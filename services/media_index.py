#!/usr/bin/env python3
"""
The title index, and the one question the scheduler asks about a title.

Two jobs, kept in one place because they share the same awkward detail:

  * keeping `media_item` current as webhooks arrive and as the service's
    library changes;
  * answering "is anything still arriving for this season" — which needs the
    service's *own* row id, a value that is not stable and therefore cannot be
    stored as identity.

That second point is the reason this module exists rather than the scheduler
calling a connector directly. Resolving `tvdbId` -> `seriesId`, noticing that
the cached `seriesId` has gone stale, and re-resolving it, is bookkeeping the
scheduler should not grow its own copy of.

It also draws the Library, Queue and History tabs. The Library list judges
every title from what one catalogue read, one history read and one walk of the
disk can tell; the detail view (`title_detail`) compares one title episode by
episode, and the list borrows that exact answer for a while once someone has
looked (see `library_compare.py` for the episode states).

Every public method here returns a value on every path. Nothing raises, and
nothing blocks for longer than the timeout on one HTTP call. A caller that
cannot get an answer is expected to carry on exactly as it did before this
module existed — which is what makes the whole feature safe to switch on.
"""

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from models.media_item import SOURCE_RADARR, SOURCE_SONARR, MediaItemStore
from models.transfer import escape_like
from services import library_compare as cmp
from services.connectors.adapters._arr import (
    UNKNOWN,
    InFlight,
    first_status_message,
    seconds_left,
)
from services.local_library import LocalLibrary, media_sizes_in, size_of_path
from services.sync_engine import stages as S
from services.sync_engine.coverage import last_copies
from services.sync_engine.units import unit_key

#: Media types that come from Sonarr. Anime is a separate library here but the
#: same service upstream, which is why source and media_type are separate
#: fields — a show can move between libraries without changing identity.
SONARR_MEDIA_TYPES = ('tvshows', 'anime')

#: How far back the Library list reads the service's imports to notice an
#: episode that arrived after the last sync. Two weeks covers a weekly season
#: twice over without pulling a busy library's whole year on every page load.
IMPORT_WINDOW = timedelta(days=14)

#: How long one read of that history is reused. A page reload, a second tab and
#: the auto-scanner's own library read inside a minute need not each ask again.
IMPORTS_TTL_SECONDS = 60

#: How long an exact, episode-by-episode answer stands in for the list's
#: estimate. Long enough to come back from the detail view to a card that says
#: the same thing; short enough that a finished sync is picked up unasked.
EXACT_TTL_SECONDS = 600

#: Where each library's folders sit on the media server, by media type — read
#: to tell an anime series from a TV one when this disk does not hold it yet.
#: How many entries one title's history returns, newest first.
TITLE_HISTORY_LIMIT = 150

_REMOTE_ROOTS = (('anime', 'ANIME_PATH'), ('tvshows', 'TVSHOW_PATH'), ('movies', 'MOVIE_PATH'))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MediaIndex:
    """Keeps the title index current and answers the gate's question."""

    def __init__(self, db_manager, connector_service=None, config=None):
        self.store = MediaItemStore(db_manager)
        self._connectors = connector_service
        self.config = config
        # Presence is read from the disk, not from the transfer log. Without a
        # config there is nothing to walk, and the view falls back to saying it
        # cannot tell rather than guessing from history.
        self.local = LocalLibrary(config) if config is not None else None
        self._lock = threading.Lock()
        #: The import history the list last read, per source: (when, imports).
        self._imports: Dict[str, Tuple[float, Optional[Dict[Tuple[str, Optional[int]], List]]]] = {}
        #: Exact answers from the detail view, per (source, external id).
        self._exact: Dict[Tuple[str, str], Dict[str, Any]] = {}
        #: Swapped in tests to age the caches without sleeping.
        self.clock: Callable[[], float] = time.time

    # -- connector plumbing --------------------------------------------------

    def _adapter(self, source: str):
        """The adapter for a source, or None when it cannot be used.

        None is returned for every unusable case — no connector service, no
        adapter registered, switched off, missing credentials — so callers have
        one branch to handle rather than four.
        """
        service = self._connectors
        if service is None:
            try:
                from services.connectors import get_service
                service = get_service()
            except Exception:
                return None
        if service is None:
            return None
        try:
            row = service.store.get_connector(source)
            if not row or not row.get('enabled'):
                return None
            adapter = service.adapter(source)
            if adapter is None or not adapter.is_configured():
                return None
            return adapter
        except Exception:
            return None

    def available(self, source: str) -> bool:
        return self._adapter(source) is not None

    # -- recording what arrives ---------------------------------------------

    def record_series_notification(self, notification: Dict[str, Any],
                                   media_type: str = '') -> Optional[int]:
        """Fold one Sonarr notification into the title index.

        Called on the webhook path, where the external id is already present —
        every series notification this application has ever stored carried one.
        Nothing here reaches the network.
        """
        if not notification:
            return None
        external_id = notification.get('tvdb_id') or notification.get('tvdbId')
        if external_id in (None, ''):
            return None
        return self.store.upsert(
            SOURCE_SONARR, external_id,
            media_type=media_type or notification.get('media_type'),
            service_item_id=notification.get('series_id'),
            service_item_id_seen_at=_now_iso(),
            title=notification.get('series_title'),
            title_slug=notification.get('series_title_slug'),
            year=notification.get('year'),
            imdb_id=notification.get('imdb_id'),
            present_in_service=1,
            last_seen_in_service_at=_now_iso(),
        )

    def record_movie_notification(self, notification: Dict[str, Any]) -> Optional[int]:
        """Fold one Radarr notification into the title index."""
        if not notification:
            return None
        external_id = notification.get('tmdb_id') or notification.get('tmdbId')
        if external_id in (None, ''):
            return None
        return self.store.upsert(
            SOURCE_RADARR, external_id,
            media_type='movies',
            title=notification.get('title'),
            year=notification.get('year'),
            imdb_id=notification.get('imdb_id'),
            present_in_service=1,
            last_seen_in_service_at=_now_iso(),
        )

    def note_transfer(self, transfer_id: str, media_item_id: Optional[int],
                      folder_name: str = '') -> None:
        """Tie a transfer to its title, and learn the folder from it.

        The folder name is only ever *learned* here, never guessed: it is
        whatever the transfer actually used. That is the mapping the rest of the
        application has been re-deriving by string munging.
        """
        if not media_item_id:
            return
        self.store.attach_transfer(transfer_id, media_item_id)
        if folder_name:
            item = self.store.get_by_id(media_item_id)
            if item and not item.get('local_folder'):
                self.store.upsert(item['source'], item['external_id'],
                                  local_folder=folder_name)

    # -- resolving the service's own id -------------------------------------

    def service_item_id(self, item: Dict[str, Any],
                        refresh: bool = True) -> Optional[Any]:
        """The service's row id for a title, resolving it if need be.

        Cached because the queue endpoints need it on every call, re-resolved
        because it is not stable: a title removed and re-added comes back with a
        different one, and the ids that have been used are never reissued.
        """
        if not item:
            return None
        cached = item.get('service_item_id')
        if cached and not refresh:
            return cached

        if cached:
            return cached

        adapter = self._adapter(item['source'])
        if adapter is None:
            return None
        ok, rows = adapter.library()
        if not ok:
            return None

        field = adapter.external_id_field
        wanted = str(item['external_id'])
        for row in rows:
            if str(row.get(field) or '') == wanted:
                self.store.upsert(item['source'], item['external_id'],
                                  service_item_id=row.get('id'),
                                  service_item_id_seen_at=_now_iso(),
                                  title=row.get('title'),
                                  title_slug=row.get('titleSlug'),
                                  year=row.get('year'))
                return row.get('id')
        return None

    # -- the question the scheduler asks ------------------------------------

    def in_flight_for_season(self, tvdb_id: Any, season_number: Optional[int],
                             media_type: str = '') -> InFlight:
        """Is anything still arriving for this series and season.

        Returns `UNKNOWN` — never raises — for every unusable case: connector
        off, unconfigured, unreachable, credentials rejected, a title the
        service does not list, a response that is not what it should be. The
        caller treats `known == False` as "carry on as before".
        """
        try:
            adapter = self._adapter(SOURCE_SONARR)
            if adapter is None:
                return InFlight(known=False, reason='Sonarr is not connected')

            item = self.store.get(SOURCE_SONARR, tvdb_id)
            if not item:
                # Nothing recorded yet: the webhook path normally creates this,
                # but a sync can be started by hand for a title never seen.
                item = {'source': SOURCE_SONARR, 'external_id': str(tvdb_id),
                        'service_item_id': None}

            series_id = self.service_item_id(item)
            if not series_id:
                return InFlight(
                    known=False,
                    reason='Sonarr does not list this series')

            result = adapter.in_flight(series_id, season_number)

            # A cached id that no longer resolves is worse than no id: it points
            # at whatever now occupies that row. Drop it so the next call
            # resolves again from the external id.
            if not result.known and item.get('id'):
                self.store.forget_service_item_id(item['id'])

            return result
        except Exception as exc:  # noqa: BLE001 - a gate must never raise
            return InFlight(known=False, reason=f'Could not ask Sonarr: {exc}')

    def in_flight_for_movie(self, tmdb_id: Any) -> InFlight:
        """Is anything still arriving for this film."""
        try:
            adapter = self._adapter(SOURCE_RADARR)
            if adapter is None:
                return InFlight(known=False, reason='Radarr is not connected')
            item = self.store.get(SOURCE_RADARR, tmdb_id) or {
                'source': SOURCE_RADARR, 'external_id': str(tmdb_id),
                'service_item_id': None}
            movie_id = self.service_item_id(item)
            if not movie_id:
                return InFlight(known=False,
                                reason='Radarr does not list this film')
            return adapter.in_flight(movie_id)
        except Exception as exc:  # noqa: BLE001
            return InFlight(known=False, reason=f'Could not ask Radarr: {exc}')

    # -- refreshing from the service ----------------------------------------

    def refresh_library(self, source: str) -> Tuple[bool, int]:
        """Pull the service's catalogue into the title index.

        Also marks titles the service no longer lists. They are flagged rather
        than deleted: the files are still on the disk, and a view that only
        walks the service's side would never show them.
        """
        adapter = self._adapter(source)
        if adapter is None:
            return False, 0
        ok, rows = adapter.library()
        if not ok:
            return False, 0
        return True, self._store_catalogue(source, adapter, rows)

    def _store_catalogue(self, source: str, adapter, rows: List[Dict[str, Any]]) -> int:
        """Write one catalogue read into the index; how many titles it named.

        Shared by Refresh and by the library view, so a view asked to refresh
        reads the whole catalogue once rather than twice.
        """
        field = adapter.external_id_field
        seen: List[str] = []
        for row in rows:
            external_id = row.get(field)
            if external_id in (None, ''):
                continue
            seen.append(str(external_id))
            self.store.upsert(
                source, external_id,
                service_item_id=row.get('id'),
                service_item_id_seen_at=_now_iso(),
                title=row.get('title'),
                title_slug=row.get('titleSlug'),
                year=row.get('year'),
                imdb_id=row.get('imdbId'),
                present_in_service=1,
                last_seen_in_service_at=_now_iso(),
            )
        self.store.mark_absent_from_service(source, seen)
        return len(seen)

    def refresh_season_counts(self, tvdb_id: Any, season_number: int) -> bool:
        """Record how much of a season the service holds, and when that was true."""
        adapter = self._adapter(SOURCE_SONARR)
        item = self.store.get(SOURCE_SONARR, tvdb_id)
        if adapter is None or not item:
            return False
        series_id = self.service_item_id(item)
        if not series_id:
            return False
        counts = adapter.season_files(series_id, season_number)
        if not counts:
            return False
        self.store.upsert_season(item['id'], season_number,
                                 refreshed_at=_now_iso(), **counts)
        return True

    # -- the library view ----------------------------------------------------

    def _local_facts(self) -> Dict[int, Dict[str, Any]]:
        """Everything our side knows, in two queries rather than one per title.

        A per-title query would be 129 round trips for a page that renders in
        one. The whole point of the index is that this join is now possible at
        all — before it, there was no reliable way to attribute a transfer to a
        title.
        """
        facts: Dict[int, Dict[str, Any]] = {}
        try:
            with self.store.db.get_connection() as conn:
                for row in conn.execute(
                    "SELECT media_item_id, COUNT(*) AS runs, "
                    "       MAX(created_at) AS last_at "
                    "  FROM transfers "
                    " WHERE media_item_id IS NOT NULL AND status = 'completed' "
                    " GROUP BY media_item_id"
                ):
                    facts[row['media_item_id']] = {
                        'transfers': row['runs'],
                        'last_synced_at': row['last_at'],
                        'seasons': set(),
                    }
                for row in conn.execute(
                    "SELECT DISTINCT media_item_id, season_name FROM transfers "
                    " WHERE media_item_id IS NOT NULL AND status = 'completed' "
                    "   AND season_name IS NOT NULL AND season_name != ''"
                ):
                    entry = facts.setdefault(row['media_item_id'], {
                        'transfers': 0, 'last_synced_at': None, 'seasons': set()})
                    number = _season_number(row['season_name'])
                    if number is not None:
                        entry['seasons'].add(number)
        except Exception as exc:  # noqa: BLE001 - a view must not fail on a join
            print(f"⚠️  Could not read local sync facts: {exc}")
        return facts

    def library_view(self, source: str = SOURCE_SONARR,
                     refresh: bool = False) -> Dict[str, Any]:
        """The service's catalogue with what we hold beside it.

        Reads the service when it can and the index when it cannot, and says
        which happened. A view that silently showed a stale index as though it
        were live would be worse than one that admits the service is down.

        What each title is called comes from three reads — the catalogue, the
        last two weeks of imports, and the disk — never from a call per title;
        `_judge` has the rules. A title someone opened in the detail view in the
        last ten minutes is shown with that exact answer instead.
        """
        live = False
        service_rows: Dict[str, Dict[str, Any]] = {}
        adapter = self._adapter(source)
        if adapter is not None:
            ok, rows = adapter.library()
            if ok:
                live = True
                if refresh:
                    self._store_catalogue(source, adapter, rows)
                field = adapter.external_id_field
                for row in rows:
                    key = row.get(field)
                    if key not in (None, ''):
                        service_rows[str(key)] = row

        facts = self._local_facts()
        on_disk = self.local.scan() if self.local else None
        recent = self._recent_imports(source, adapter) if live else None
        synced = self._last_syncs() if on_disk is not None else {}

        items = []
        for item in self.store.list_items(source=source):
            service = service_rows.get(str(item['external_id']))
            local = facts.get(item['id'], {})

            folder = None
            if self.local is not None:
                folder = self.local.find(
                    (service or {}).get('title') or item.get('title') or '',
                    (service or {}).get('year') or item.get('year'),
                    item.get('local_folder') or '')
                # Learned once and written down, so the next read is a lookup
                # rather than another name comparison.
                if folder and not item.get('local_folder'):
                    self.store.upsert(source, item['external_id'],
                                      local_folder=folder['folder'])
                    item['local_folder'] = folder['folder']

            entry = _merge(item, service, local, source, folder,
                           disk_known=on_disk is not None)
            _judge(entry, source, service, folder, recent,
                   _sync_lookup(synced, folder),
                   self._exact_for(source, item['external_id']))
            items.append(entry)

        counts: Dict[str, int] = {}
        for entry in items:
            counts[entry['sync_state']] = counts.get(entry['sync_state'], 0) + 1

        return {
            'source': source,
            'live': live,
            'total': len(items),
            'counts': counts,
            # Whether rule (b) could be applied at all. Without it an episode
            # imported after the last sync can only be caught by the counts.
            'history_checked': recent is not None,
            'items': items,
        }

    # -- what the list is judged from ----------------------------------------

    def _recent_imports(self, source: str, adapter) \
            -> Optional[Dict[Tuple[str, Optional[int]], List[Dict[str, Any]]]]:
        """The service's imports of the last two weeks, by (title id, season).

        One call — the same `history/since` the auto-scanner reads — and reused
        for a minute. None when the service would not say, which the judge
        treats as "this rule cannot be applied", never as "nothing arrived".
        """
        now = self.clock()
        with self._lock:
            cached = self._imports.get(source)
            if cached is not None and now - cached[0] < IMPORTS_TTL_SECONDS:
                return cached[1]

        since = (datetime.now(timezone.utc) - IMPORT_WINDOW).replace(microsecond=0)
        try:
            ok, rows = adapter.imports_since(since.isoformat())
        except Exception:  # noqa: BLE001 - a view must not fail on one read
            ok, rows = False, []

        grouped: Optional[Dict[Tuple[str, Optional[int]], List[Dict[str, Any]]]] = None
        if ok:
            grouped = {}
            for row in rows:
                moment = _parse_iso(row.get('date'))
                if moment is None:
                    continue
                if source == SOURCE_SONARR:
                    service_id = row.get('seriesId')
                    episode = row.get('episode') or {}
                    season = episode.get('seasonNumber')
                    number = episode.get('episodeNumber')
                    if season is None:
                        continue
                else:
                    service_id, season, number = row.get('movieId'), None, None
                if service_id in (None, ''):
                    continue
                data = row.get('data') or {}
                grouped.setdefault((str(service_id), season), []).append({
                    'at': moment,
                    'episode': number,
                    'size': _int_or_none(data.get('size')),
                })

        with self._lock:
            self._imports[source] = (now, grouped)
        return grouped

    def _last_syncs(self) -> Dict[str, datetime]:
        """When each destination folder last had a completed sync, by unit key.

        The auto-scanner's own rule, read for every folder at once (see
        `services/sync_engine/coverage.py`): a copy counts from when it
        started, and single files, restores and simulations never count.
        """
        try:
            return last_copies(self.store.db)
        except Exception as exc:  # noqa: BLE001 - a view must not fail on a join
            print(f"⚠️  Could not read when folders were last synced: {exc}")
            return {}

    def _exact_for(self, source: str, external_id: Any) -> Optional[Dict[str, Any]]:
        """The detail view's answer for a title, while it is still fresh."""
        key = (source, str(external_id))
        with self._lock:
            entry = self._exact.get(key)
            if entry is not None and self.clock() - entry['at'] > EXACT_TTL_SECONDS:
                self._exact.pop(key, None)
                entry = None
        return entry

    def _remember_exact(self, source: str, external_id: str,
                        result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Keep an exact answer for the list to borrow; returns what needs doing."""
        attention: List[Dict[str, Any]] = []
        for season in result.get('seasons') or []:
            if not season['counts_towards_state']:
                continue
            for state, kind in ((cmp.MISSING_HERE, 'missing'), (cmp.DIFFERENT, 'different')):
                codes = [row['code'] for row in season['episodes'] if row['state'] == state]
                if codes:
                    attention.append({'kind': kind, 'season_number': season['season_number'],
                                      'count': len(codes), 'episodes': codes})
        movie = result.get('movie') or {}
        if movie.get('state') == cmp.DIFFERENT:
            theirs = movie.get('service_file') or {}
            attention.append({'kind': 'different', 'season_number': None, 'count': 1,
                              'quality': theirs.get('quality'), 'size': theirs.get('size')})
        now = self.clock()
        with self._lock:
            for key in [k for k, v in self._exact.items() if now - v['at'] > EXACT_TTL_SECONDS]:
                self._exact.pop(key, None)
            self._exact[(source, str(external_id))] = {
                'at': now,
                'computed_at': datetime.now(timezone.utc),
                'state': result['state'],
                'summary': result['summary'],
                'attention': attention,
                'kept': result['counts'].get(cmp.ONLY_HERE, 0),
            }
        return attention

    # -- one title, episode by episode ---------------------------------------

    def title_detail(self, source: str, external_id: Any) -> Dict[str, Any]:
        """One title compared episode by episode — the detail view.

        Three reads for a series (the series, its episodes, its files) and a
        fresh walk of its one folder here; two at most for a film. Only ever
        for the one title a person opened, which is what keeps the list cheap.

        `found` is false only when nothing anywhere knows the id; `live` is
        false when the service could not be asked, and `message` says why.
        """
        external_id = str(external_id or '').strip()
        name = source.title()
        item = self.store.get(source, external_id) if external_id else None
        out: Dict[str, Any] = {
            'source': source, 'external_id': external_id, 'live': False,
            'found': item is not None, 'read_only': True,
        }

        adapter = self._adapter(source)
        if adapter is None:
            out['message'] = f'{name} is not connected'
            out['title'] = self._header(source, item, None, None)
            return out

        ok, row = self._service_row(source, adapter, item, external_id)
        if not ok:
            out['message'] = f'{name} did not answer'
            out['title'] = self._header(source, item, None, None)
            return out

        item = self.store.get(source, external_id) or item
        folder = None
        if self.local is not None:
            source_row = row or {}
            folder = self.local.find(source_row.get('title') or (item or {}).get('title') or '',
                                     source_row.get('year') or (item or {}).get('year'),
                                     (item or {}).get('local_folder') or '')
        media_type = self._media_type_for(source, item, folder, row)

        if row is None:
            if item is None:
                out['not_found'] = True
                out['message'] = f'{name} does not list this title'
                return out
            # Files from a title the service has since dropped: nothing to
            # compare against, but the folder can still be opened in Explore.
            return self._without_comparison(
                out, source, item, folder, media_type, cmp.ORPHAN if folder else cmp.UNKNOWN,
                f"{name} no longer lists this title"
                + ("; the files here are kept." if folder else ", and nothing of it is here."))
        if self.local is None:
            return self._without_comparison(
                out, source, item, folder, media_type, cmp.UNKNOWN,
                "This disk's library folders are not configured, so nothing can be compared.",
                row=row)

        local = self.local.files_of(folder) if folder else None

        if source == SOURCE_SONARR:
            ok_episodes, episodes = adapter.episodes(row.get('id'))
            ok_files, files = adapter.episode_files(row.get('id'))
            if not (ok_episodes and ok_files):
                out['message'] = f'{name} did not answer'
                out['title'] = self._header(source, item, row, folder)
                return out
            result = cmp.compare_series(episodes, files, local, row.get('seasons'), service=name)
        else:
            result = cmp.compare_movie(row, local, service=name)

        last_sync = _sync_lookup(self._last_syncs(), folder)
        series_folder = (folder or {}).get('folder') or os.path.basename(
            str(row.get('path') or '').rstrip('/'))
        first_needing = None
        # The title's own "last synced" is its latest, whether that was the
        # whole folder or one season of it.
        moment = last_sync(None)
        for season in result.get('seasons') or []:
            number = season['season_number']
            synced = last_sync(number)
            season['last_synced_at'] = synced.isoformat() if synced else None
            if synced and (moment is None or synced > moment):
                moment = synced
            season['explore_season'] = (season['service_folder'] or season['folder_here']
                                        or ('Specials' if number == 0 else f"Season {number:02d}"))
            needs = season['counts'][cmp.MISSING_HERE] or season['counts'][cmp.DIFFERENT]
            if needs and season['counts_towards_state'] and first_needing is None:
                first_needing = season['explore_season']

        out.update({
            'live': True,
            'found': True,
            'title': self._header(source, item, row, folder, media_type),
            'state': result['state'],
            'summary': result['summary'],
            'counts': result['counts'],
            'seasons': result.get('seasons') or [],
            'movie': result.get('movie'),
            'duplicates': result.get('duplicates') or {},
            'last_synced_at': moment.isoformat() if moment else None,
            'actions': {
                'sync': result['sync'],
                'explore': {
                    'media_type': media_type,
                    'series': series_folder or None,
                    'season': first_needing if source == SOURCE_SONARR else None,
                },
            },
            'computed_at': _now_iso(),
        })
        # The same summary the list shows for a title, so a card can be
        # brought up to date the moment its detail has been read.
        out['attention'] = self._remember_exact(source, external_id, result)
        out['kept_here_count'] = result['counts'].get(cmp.ONLY_HERE, 0)
        return out

    def title_history(self, source: str, external_id: Any,
                      limit: int = TITLE_HISTORY_LIMIT) -> Dict[str, Any]:
        """What happened to one title, on both sides, newest first.

        The service's own record for the title (imported, grabbed, deleted,
        failed) beside DragonCP's syncs of its folder here (finished, failed,
        stopped by the safety check, cancelled, cut off by a restart) and the
        transfers from before the sync engine. Each entry carries a status, so
        the screen can answer "what happened, and what was not done".

        Whether an import's episode is here now is not decided here: the
        episode-by-episode comparison the series view already holds says it
        exactly, so the screen marks imports from that one answer.
        """
        external_id = str(external_id or '').strip()
        name = source.title()
        item = self.store.get(source, external_id) if external_id else None
        out: Dict[str, Any] = {'source': source, 'external_id': external_id, 'live': False,
                               'entries': [], 'total': 0, 'read_only': True}

        adapter = self._adapter(source)
        row = None
        if adapter is None:
            out['message'] = f'{name} is not connected'
        else:
            ok, row = self._service_row(source, adapter, item, external_id)
            if ok:
                out['live'] = True
            else:
                out['message'] = f'{name} did not answer'
        item = self.store.get(source, external_id) or item
        if row is None and item is None:
            out['not_found'] = True
            out['message'] = f'{name} does not list this title'
            return out

        entries: List[Dict[str, Any]] = []
        if out['live'] and row and row.get('id') is not None \
                and hasattr(adapter, 'title_history'):
            ok, records = adapter.title_history(row.get('id'))
            if ok:
                field = adapter.external_id_field
                # Sonarr's per-series history names each episode by its id
                # only, whatever it is asked to include; the series' episode
                # list turns the id back into "S01E08" and a title.
                by_id: Dict[Any, Dict[str, Any]] = {}
                if source == SOURCE_SONARR and any(
                        not isinstance(record.get('episode'), dict) for record in records):
                    ok_episodes, episodes = adapter.episodes(row.get('id'))
                    if ok_episodes:
                        by_id = {episode.get('id'): episode for episode in episodes}
                for record in records:
                    if not isinstance(record.get('episode'), dict) \
                            and record.get('episodeId') in by_id:
                        record = {**record, 'episode': by_id[record['episodeId']]}
                    mapped = _history_record(source, record, {}, field)
                    entries.append(_service_entry(source, mapped, name))
            else:
                out['message'] = f'{name} did not send its history'

        folder = None
        if self.local is not None:
            source_row = row or {}
            folder = self.local.find(source_row.get('title') or (item or {}).get('title') or '',
                                     source_row.get('year') or (item or {}).get('year'),
                                     (item or {}).get('local_folder') or '')
        if folder and folder.get('path'):
            entries.extend(self._sync_entries(folder['path'], movie=source == SOURCE_RADARR))

        entries.sort(key=lambda entry: entry['_at'], reverse=True)
        entries = _grouped(entries, name)
        for entry in entries:
            entry.pop('_at', None)
        out['total'] = len(entries)
        out['entries'] = entries[:max(1, int(limit))]
        return out

    def _sync_entries(self, folder_path: str, movie: bool) -> List[Dict[str, Any]]:
        """DragonCP's syncs of one title's folder here, and the transfers before them."""
        pattern = escape_like(folder_path.rstrip('/')) + '/%'
        found: List[Dict[str, Any]] = []
        try:
            with self.store.db.get_connection() as conn:
                runs = conn.execute(
                    "SELECT run_id, kind, state, outcome_message, season_name, created_at, "
                    "       finished_at, requested_by_name FROM sync_run "
                    " WHERE COALESCE(is_simulation, 0) = 0 "
                    "   AND (dest_path = ? OR dest_path LIKE ? ESCAPE '\\') "
                    " ORDER BY id DESC LIMIT ?",
                    (folder_path.rstrip('/'), pattern, TITLE_HISTORY_LIMIT)).fetchall()
                transfers = conn.execute(
                    "SELECT transfer_id, status, season_name, progress, start_time, end_time, "
                    "       created_at, started_by_name FROM transfers "
                    " WHERE COALESCE(sync_run_id, '') = '' AND COALESCE(is_simulation, 0) = 0 "
                    "   AND (dest_path = ? OR dest_path LIKE ? ESCAPE '\\') "
                    " ORDER BY id DESC LIMIT ?",
                    (folder_path.rstrip('/'), pattern, TITLE_HISTORY_LIMIT)).fetchall()
        except Exception as exc:  # noqa: BLE001 - a view must not fail on a query
            print(f"⚠️  Could not read the syncs of {folder_path}: {exc}")
            return found
        for run in runs:
            found.append(_run_entry(dict(run), movie))
        for transfer in transfers:
            found.append(_transfer_entry(dict(transfer), movie))
        return found

    def _without_comparison(self, out: Dict[str, Any], source: str,
                            item: Optional[Dict[str, Any]], folder: Optional[Dict[str, Any]],
                            media_type: str, state: str, summary: str,
                            row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """A detail view with a header and a sentence but no episodes to show."""
        out.update({
            'live': True,
            'found': True,
            'title': self._header(source, item, row, folder, media_type),
            'state': state,
            'summary': summary,
            'counts': cmp.empty_counts(),
            'seasons': [],
            'movie': None,
            'duplicates': {},
            'last_synced_at': None,
            'actions': {
                'sync': {'offered': False, 'seasons': [], 'reason': ''},
                'explore': {'media_type': media_type,
                            'series': (folder or {}).get('folder'),
                            'season': None} if folder else None,
            },
            'computed_at': _now_iso(),
        })
        return out

    def _service_row(self, source: str, adapter, item: Optional[Dict[str, Any]],
                     external_id: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """The service's own row for a title: (answered, row or None).

        The cached service id is tried first — one small read. When it fails or
        now names a different title (a title removed and re-added comes back
        with a new id), the catalogue is searched by the external id and the
        cache corrected; only if that read fails too is the service down.
        """
        field = adapter.external_id_field
        cached = (item or {}).get('service_item_id')
        if cached not in (None, ''):
            ok, row = adapter.item(cached)
            if ok and row and str(row.get(field) or '') == external_id:
                return True, row

        ok, rows = adapter.library()
        if not ok:
            return False, None
        for candidate in rows:
            if str(candidate.get(field) or '') != external_id:
                continue
            self.store.upsert(source, external_id,
                              service_item_id=candidate.get('id'),
                              service_item_id_seen_at=_now_iso(),
                              title=candidate.get('title'),
                              title_slug=candidate.get('titleSlug'),
                              year=candidate.get('year'),
                              present_in_service=1,
                              last_seen_in_service_at=_now_iso())
            return True, candidate
        if item and item.get('id') and cached not in (None, ''):
            self.store.forget_service_item_id(item['id'])
        return True, None

    def _header(self, source: str, item: Optional[Dict[str, Any]],
                row: Optional[Dict[str, Any]], folder: Optional[Dict[str, Any]],
                media_type: Optional[str] = None) -> Dict[str, Any]:
        """The facts at the top of the detail view."""
        item, row = item or {}, row or {}
        return {
            'external_id': str(item.get('external_id') or row.get(
                'tvdbId' if source == SOURCE_SONARR else 'tmdbId') or ''),
            'service_item_id': row.get('id') or item.get('service_item_id'),
            'title': row.get('title') or item.get('title'),
            'year': row.get('year') or item.get('year'),
            'poster': _poster(row),
            'status': row.get('status'),
            'network': row.get('network') or row.get('studio'),
            'monitored': bool(row.get('monitored')),
            'service_path': row.get('path') or '',
            'local_folder': (folder or {}).get('folder') or item.get('local_folder'),
            'media_type': media_type or (folder or {}).get('media_type') or item.get('media_type'),
        }

    def _config_value(self, key: str) -> str:
        if self.config is None:
            return ''
        try:
            return str(self.config.get(key) or '').strip()
        except Exception:  # noqa: BLE001
            return ''

    def _media_type_for(self, source: str, item: Optional[Dict[str, Any]],
                        folder: Optional[Dict[str, Any]], row: Optional[Dict[str, Any]]) -> str:
        """Which library a title belongs to here: tvshows, anime or movies.

        The folder here says, when there is one. Otherwise the series' path on
        the media server is matched against the configured library roots, so a
        series not yet here still opens in the right Explore library.
        """
        if folder and folder.get('media_type'):
            return folder['media_type']
        if item and item.get('media_type'):
            return item['media_type']
        if source == SOURCE_RADARR:
            return 'movies'
        path = str((row or {}).get('path') or '').rstrip('/')
        for media_type, key in _REMOTE_ROOTS:
            root = self._config_value(key).rstrip('/')
            if root and path.startswith(root + '/'):
                return media_type
        return 'tvshows'

    # -- the queue and the history -------------------------------------------

    def queue_view(self, source: str = SOURCE_SONARR) -> Dict[str, Any]:
        """Everything waiting on the service, and why each row is waiting.

        The rows worth surfacing are not the ones downloading — those look after
        themselves. They are the ones that will never finish on their own:

          * a download reporting progress that has not moved,
          * an import blocked on something only a person can settle,
          * a row the service cannot attribute to any title at all, which its
            own interface tends not to show you,
          * anything that has simply been there for days.

        Each row carries whether it is holding an automatic sync, decided by the
        same classifier the gate uses, so this screen and that decision cannot
        drift apart.
        """
        adapter = self._adapter(source)
        if adapter is None:
            return {'source': source, 'live': False, 'rows': [], 'counts': {},
                    'message': f'{source.title()} is not connected'}

        ok, rows = adapter.queue_all()
        if not ok:
            return {'source': source, 'live': False, 'rows': [], 'counts': {},
                    'message': f'{source.title()} did not answer'}

        by_service_id = {}
        for item in self.store.list_items(source=source):
            if item.get('service_item_id'):
                by_service_id[item['service_item_id']] = item

        field = adapter.external_id_field
        now = datetime.now(timezone.utc)
        entries, counts = [], {}
        for row in rows:
            verdict = adapter.classify_row(row)
            service_item_id = (row.get('seriesId') if source == SOURCE_SONARR
                               else row.get('movieId'))
            known = by_service_id.get(service_item_id)
            # Folded in by the service when asked (`queue_include`): the title
            # and episode, even for a title DragonCP has never heard of.
            title_row = row.get('series') if source == SOURCE_SONARR else row.get('movie')
            title_row = title_row if isinstance(title_row, dict) else {}
            episode = row.get('episode') if isinstance(row.get('episode'), dict) else {}

            size = row.get('size') or 0
            left = row.get('sizeleft') or 0
            progress = round(100 * (1 - left / size), 1) if size else 0.0

            added = _parse_iso(row.get('added'))
            age_hours = round((now - added).total_seconds() / 3600, 1) if added else None

            # A row naming no title cannot hold a sync — nothing knows what it
            # would be holding — but it is the single most likely row to have
            # been sitting there forgotten, so it is called out rather than hidden.
            unattributed = service_item_id in (None, '')

            season_number = row.get('seasonNumber')
            if season_number is None:
                season_number = episode.get('seasonNumber')
            episode_number = episode.get('episodeNumber')
            external = (known or {}).get('external_id') or title_row.get(field)

            entry = {
                'id': row.get('id'),
                'title': ((known or {}).get('title') or title_row.get('title')
                          or row.get('title') or 'Unknown'),
                'year': title_row.get('year') or (known or {}).get('year'),
                'release': row.get('title'),
                'service_item_id': service_item_id,
                'external_id': str(external) if external not in (None, '') else None,
                'known_here': known is not None,
                'unattributed': unattributed,
                'season_number': season_number,
                'episode_number': episode_number,
                'episode_code': (cmp.episode_code(season_number, episode_number)
                                 if source == SOURCE_SONARR and season_number is not None
                                 and episode_number is not None else None),
                'episode_title': episode.get('title') or None,
                'quality': cmp.quality_name(row),
                'custom_formats': cmp.custom_format_names(row),
                'custom_format_score': row.get('customFormatScore'),
                'state': row.get('trackedDownloadState'),
                'status': row.get('trackedDownloadStatus'),
                'client_status': row.get('status'),
                'verdict': verdict['verdict'],
                'holds_sync': bool(verdict['holds']) and not unattributed,
                'why': verdict['why'],
                'progress': progress,
                'size': size,
                'size_left': left,
                'time_left': row.get('timeleft'),
                'seconds_left': seconds_left(row) if verdict['verdict'] != 'imported' else None,
                'estimated_completion': row.get('estimatedCompletionTime'),
                'download_client': row.get('downloadClient'),
                'indexer': row.get('indexer'),
                'protocol': row.get('protocol'),
                'error_message': row.get('errorMessage') or '',
                'added': row.get('added'),
                'age_hours': age_hours,
                'needs_attention': verdict['verdict'] in (
                    'stalled', 'blocked', 'failed', 'stale', 'unrecognised')
                or unattributed
                or (age_hours is not None and age_hours > 48),
            }
            entry.update(_queue_status(verdict, row))
            entries.append(entry)
            counts[entry['verdict']] = counts.get(entry['verdict'], 0) + 1

        entries.sort(key=lambda e: (not e['needs_attention'], -(e['age_hours'] or 0)))

        return {
            'source': source,
            'live': True,
            'rows': entries,
            'counts': counts,
            'total': len(entries),
            'needing_attention': sum(1 for e in entries if e['needs_attention']),
            'holding_a_sync': sum(1 for e in entries if e['holds_sync']),
        }

    def history_view(self, source: str = SOURCE_SONARR, page: int = 1,
                     page_size: int = 50, event: Optional[str] = None) -> Dict[str, Any]:
        """A page of the service's own history. Read-only, always.

        Each row says what happened to which episode, in the service's own
        terms — "Example Show 1x08 Episode Title, WEBDL-1080p, WEB Tier 01" —
        because the release name alone is what made the old tab unreadable.
        `event` narrows it to one kind (`HISTORY_FILTERS`), on the service's
        side, so paging stays honest.
        """
        adapter = self._adapter(source)
        if adapter is None:
            return {'source': source, 'live': False, 'records': [],
                    'page': page, 'total': 0, 'event': event or 'all',
                    'message': f'{source.title()} is not connected'}
        event_type = None
        if event:
            event_type = (getattr(adapter, 'history_event_types', None) or {}).get(event)
        ok, payload = adapter.history(page=page, page_size=page_size, event_type=event_type)
        if not ok:
            return {'source': source, 'live': False, 'records': [],
                    'page': page, 'total': 0, 'event': event or 'all',
                    'message': f'{source.title()} did not answer'}

        by_service_id = {}
        for item in self.store.list_items(source=source):
            if item.get('service_item_id'):
                by_service_id[item['service_item_id']] = item

        field = adapter.external_id_field
        records = [_history_record(source, record, by_service_id, field)
                   for record in payload.get('records', []) if isinstance(record, dict)]

        return {
            'source': source, 'live': True, 'records': records,
            'page': payload.get('page', page),
            'page_size': payload.get('pageSize', page_size),
            'total': payload.get('totalRecords', len(records)),
            'event': event or 'all',
        }


# =============================================================================
# The history tab's words
# =============================================================================

#: The service's event names, in the words the History tab uses.
_HISTORY_KIND = {
    'grabbed': 'grabbed',
    'downloadFolderImported': 'imported',
    'seriesFolderImported': 'imported',
    'movieFolderImported': 'imported',
    'downloadFailed': 'failed',
    'episodeFileDeleted': 'deleted',
    'movieFileDeleted': 'deleted',
    'episodeFileRenamed': 'renamed',
    'movieFileRenamed': 'renamed',
    'downloadIgnored': 'ignored',
}

#: What the History tab can be narrowed to.
HISTORY_FILTERS = ('imported', 'grabbed', 'deleted', 'failed', 'renamed', 'ignored')

HISTORY_LABELS = {
    'imported': 'Imported',
    'grabbed': 'Grabbed',
    'deleted': 'Deleted',
    'failed': 'Download failed',
    'renamed': 'Renamed',
    'ignored': 'Ignored',
    'other': 'Other',
}

#: Why a file was deleted, as the service records it.
_DELETE_REASONS = {
    'Upgrade': 'Replaced by an upgrade',
    'Manual': 'Deleted by hand',
    'MissingFromDisk': 'Missing from disk',
    'NoLinkedEpisodes': 'No episode linked to it any more',
    'ManualOverride': 'Replaced by a manual import',
}


def _history_record(source: str, record: Dict[str, Any], by_service_id: Dict[Any, Dict],
                    field: str) -> Dict[str, Any]:
    """One history row: what happened, to which title and episode, in which quality."""
    raw = record.get('eventType') or ''
    kind = _HISTORY_KIND.get(raw, 'other')
    data = record.get('data') if isinstance(record.get('data'), dict) else {}
    if source == SOURCE_SONARR:
        service_item_id = record.get('seriesId')
        title_row = record.get('series')
    else:
        service_item_id = record.get('movieId')
        title_row = record.get('movie')
    title_row = title_row if isinstance(title_row, dict) else {}
    episode = record.get('episode') if isinstance(record.get('episode'), dict) else {}
    known = by_service_id.get(service_item_id)

    season = episode.get('seasonNumber')
    number = episode.get('episodeNumber')
    has_episode = source == SOURCE_SONARR and season is not None and number is not None

    reason = None
    if kind == 'deleted':
        raw_reason = data.get('reason') or ''
        reason = _DELETE_REASONS.get(raw_reason, raw_reason) or None
    elif kind in ('failed', 'ignored'):
        reason = data.get('message') or None
    elif kind == 'renamed':
        before = str(data.get('sourceRelativePath') or data.get('sourcePath') or '')
        before = before.replace('\\', '/').rsplit('/', 1)[-1]
        reason = f"Was {before}" if before else None

    external = (known or {}).get('external_id') or title_row.get(field)
    score = record.get('customFormatScore')
    if score is None:
        score = _int_or_none(data.get('customFormatScore'))
    return {
        'id': record.get('id'),
        'event_type': raw,
        'event': kind,
        'event_label': HISTORY_LABELS.get(kind) or raw or 'Event',
        'date': record.get('date'),
        'source_title': record.get('sourceTitle'),
        'quality': cmp.quality_name(record),
        'custom_formats': cmp.custom_format_names(record),
        'custom_format_score': score,
        'service_item_id': service_item_id,
        'title': (known or {}).get('title') or title_row.get('title'),
        'year': title_row.get('year') or (known or {}).get('year'),
        'external_id': str(external) if external not in (None, '') else None,
        'known_here': known is not None,
        'season_number': season if has_episode else None,
        'episode_number': number if has_episode else None,
        'episode_code': cmp.episode_code(season, number) if has_episode else None,
        # Sonarr's own short form, the one its History screen prints.
        'episode_label': f"{int(season)}x{int(number):02d}" if has_episode else None,
        'episode_title': (episode.get('title') or None) if has_episode else None,
        'absolute_episode_number': episode.get('absoluteEpisodeNumber') if has_episode else None,
        'download_client': data.get('downloadClientName') or data.get('downloadClient') or None,
        'indexer': data.get('indexer') or None,
        'release_group': data.get('releaseGroup') or None,
        'size': _int_or_none(data.get('size')),
        'reason': reason,
    }


# =============================================================================
# One title's history
# =============================================================================

#: A sync run's ending, as the history says it, and whether it got done.
_RUN_ENDINGS = {
    S.COMPLETED: ('Synced {what}', 'done'),
    S.FAILED_STATE: ('Sync of {what} failed', 'failed'),
    S.REFUSED_STATE: ('Sync of {what} was stopped by the safety check', 'not_done'),
    S.CANCELLED: ('Sync of {what} was cancelled', 'not_done'),
    S.INTERRUPTED: ('Sync of {what} was cut off by a restart', 'not_done'),
}

#: A transfer from before the sync engine, the same way.
_TRANSFER_ENDINGS = {
    'completed': ('Copied {what}', 'done'),
    'failed': ('Copy of {what} failed', 'failed'),
    'cancelled': ('Copy of {what} was stopped', 'not_done'),
}


def _entry(at: Optional[datetime], side: str, kind: str, title: str, detail: str,
           status: str, **extra) -> Dict[str, Any]:
    moment = at or datetime.min.replace(tzinfo=timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return {
        'at': at.isoformat() if at else None, 'side': side, 'kind': kind,
        'title': title, 'detail': detail, 'status': status,
        'episodes': extra.pop('episodes', []), '_at': moment, **extra,
    }


def _service_entry(source: str, record: Dict[str, Any], name: str) -> Dict[str, Any]:
    """One of the service's own events for the title, in a sentence."""
    code = record.get('episode_code')
    what = code or ('the film' if source == SOURCE_RADARR else 'an episode')
    kind = record.get('event') or 'other'
    quality = record.get('quality')
    size = record.get('size')
    facts = [record.get('episode_title'), quality,
             cmp.size_words(size) if size else None]
    if kind == 'imported':
        title, detail, status = f"{name} imported {what}", facts, 'info'
    elif kind == 'grabbed':
        title = f"{name} grabbed {what}"
        detail, status = [quality, record.get('indexer') or record.get('download_client')], 'info'
    elif kind == 'failed':
        title, detail, status = f"{name}'s download of {what} failed", [record.get('reason')], 'failed'
    elif kind == 'deleted':
        title, detail, status = f"{name} deleted its file for {what}", [record.get('reason')], 'info'
    elif kind == 'renamed':
        title, detail, status = f"{name} renamed the file for {what}", [record.get('reason')], 'info'
    elif kind == 'ignored':
        title = f"{name} ignored a download for {what}"
        detail, status = [record.get('reason')], 'info'
    else:
        title = f"{name}: {record.get('event_label') or 'an event'} for {what}"
        detail, status = [], 'info'
    return _entry(_parse_iso(record.get('date')), 'service', kind, title,
                  ' · '.join(str(part) for part in detail if part), status,
                  episodes=[code] if code else [], quality=quality,
                  custom_formats=record.get('custom_formats') or [],
                  service_id=record.get('id'))


#: Service events a burst of which reads as one: a clean-up deleting a
#: season's files at once, a rename of a whole folder.
_GROUPABLE = {
    'deleted': '{name} deleted its files for {episodes}',
    'renamed': '{name} renamed the files for {episodes}',
}
#: How close together a burst's events are.
_BURST = timedelta(minutes=10)


def _episodes_text(codes: List[str]) -> str:
    """"S01E01 to S01E07" for a run in one season; a short list, or a count, otherwise."""
    keys = []
    for code in codes:
        try:
            keys.append((int(code[1:3]), int(code[4:])))
        except (ValueError, IndexError):
            keys = []
            break
    keys.sort()
    if keys and len({season for season, _ in keys}) == 1 and \
            [number for _, number in keys] == list(range(keys[0][1], keys[-1][1] + 1)):
        return f"{cmp.episode_code(*keys[0])} to {cmp.episode_code(*keys[-1])}"
    ordered = sorted(codes)
    if len(ordered) <= 4:
        return ', '.join(ordered[:-1]) + f" and {ordered[-1]}"
    return f"{len(ordered)} episodes"


def _grouped(entries: List[Dict[str, Any]], name: str) -> List[Dict[str, Any]]:
    """Fold a burst of the same deletion or rename into one entry naming every episode."""
    out: List[Dict[str, Any]] = []
    for entry in entries:
        last = out[-1] if out else None
        if (last and entry['side'] == 'service' and last['side'] == 'service'
                and entry['kind'] in _GROUPABLE and entry['kind'] == last['kind']
                and entry['detail'] == last['detail'] and entry['episodes']
                and last['episodes'] and abs(last['_at'] - entry['_at']) <= _BURST):
            last['episodes'] = last['episodes'] + entry['episodes']
            last['title'] = _GROUPABLE[entry['kind']].format(
                name=name, episodes=_episodes_text(last['episodes']))
            continue
        out.append(dict(entry))
    return out


def _run_entry(run: Dict[str, Any], movie: bool) -> Dict[str, Any]:
    """One of DragonCP's syncs of the title's folder, in a sentence."""
    what = run.get('season_name') or ('the film' if movie else 'the whole series')
    state = run.get('state') or ''
    title, status = _RUN_ENDINGS.get(state, (None, None))
    if title is None:
        title, status = f"Sync of {{what}}: {S.describe_state(state).lower()}", 'in_progress'
    who = run.get('requested_by_name')
    detail = [S.kind_label(run.get('kind') or ''),
              f"by {who}" if who and who != 'system' else None,
              run.get('outcome_message')]
    return _entry(_parse_iso(run.get('finished_at') or run.get('created_at')), 'dragoncp',
                  'sync', title.format(what=what),
                  ' · '.join(str(part) for part in detail if part), status,
                  run_id=run.get('run_id'), state=state, season=run.get('season_name'))


def _transfer_entry(transfer: Dict[str, Any], movie: bool) -> Dict[str, Any]:
    """A transfer from before the sync engine, which left no run to read."""
    what = transfer.get('season_name') or ('the film' if movie else 'the whole series')
    status_word = transfer.get('status') or ''
    title, status = _TRANSFER_ENDINGS.get(status_word, ('Copy of {what}: ' + status_word, 'info'))
    who = transfer.get('started_by_name')
    detail = ['Before sync records',
              f"by {who}" if who and who != 'system' else None,
              transfer.get('progress') if status != 'done' else None]
    moment = _parse_local(transfer.get('end_time') or transfer.get('start_time')
                          or transfer.get('created_at'))
    return _entry(moment, 'dragoncp', 'transfer', title.format(what=what),
                  ' · '.join(str(part) for part in detail if part), status,
                  transfer_id=transfer.get('transfer_id'), state=status_word,
                  season=transfer.get('season_name'))


def _queue_status(verdict: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    """A queue row's state in plain words: a short label, the detail, and a tone.

    Tones are the app's four notes: brand for something moving, amber for
    something stuck that a person may need to settle, rose for a failure,
    emerald for done.
    """
    kind = verdict.get('verdict') or ''
    why = verdict.get('why') or ''
    client = str(row.get('status') or '').lower()
    warning = str(row.get('trackedDownloadStatus') or '').lower() == 'warning'
    message = first_status_message(row) or row.get('errorMessage') or ''

    if kind == 'downloading':
        if client == 'paused':
            return _status('Paused', 'Paused in the download client', 'warn')
        if client == 'queued':
            return _status('Queued', 'Waiting for a slot in the download client', 'brand')
        if client == 'delay':
            return _status('Delayed', 'Held back by a delay profile', 'muted')
        return _status('Downloading', message if warning else '', 'warn' if warning else 'brand')
    if kind == 'importpending':
        return _status('Waiting to import', message, 'warn' if warning else 'brand')
    if kind == 'importing':
        return _status('Importing', '', 'brand')
    if kind == 'imported':
        return _status('Imported', 'The download client is still seeding it', 'ok')
    if kind in ('stalled', 'blocked'):
        return _status('Stuck', why or message, 'warn')
    if kind == 'failed':
        return _status('Failed', row.get('errorMessage') or 'Waiting on a retry decision', 'crit')
    if kind == 'stale':
        return _status('Stale', 'The library already has this file', 'warn')
    if kind == 'unrecognised':
        return _status('Unrecognised', why, 'warn')
    return _status('Waiting', why, 'muted')


def _status(label: str, detail: str, tone: str) -> Dict[str, Any]:
    detail = (detail or '').strip()
    return {
        'status_label': label,
        'status_detail': detail,
        'status_text': f"{label}: {detail}" if detail else label,
        'tone': tone,
    }


# =============================================================================
# Small readings
# =============================================================================

def _parse_iso(value) -> Optional[datetime]:
    """A service timestamp, or None. Never raises on a shape it did not expect."""
    if not value:
        return None
    try:
        text = str(value).replace('Z', '+00:00')
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_local(value) -> Optional[datetime]:
    """A timestamp written in this machine's local time with no zone — the
    transfers table's — as an aware moment."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def _int_or_none(value) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _season_number(season_name: str) -> Optional[int]:
    """The number out of a folder label such as "Season 03"."""
    if not season_name:
        return None
    digits = ''.join(ch for ch in str(season_name) if ch.isdigit())
    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def _poster(row: Optional[Dict[str, Any]]) -> str:
    for image in (row or {}).get('images') or []:
        if isinstance(image, dict) and image.get('coverType') == 'poster':
            return image.get('remoteUrl') or image.get('url') or ''
    return ''


def _when(moment: Optional[datetime]) -> str:
    return moment.astimezone().strftime('%Y-%m-%d %H:%M') if moment else ''


def _sync_lookup(synced: Dict[str, datetime], folder: Optional[Dict[str, Any]]) \
        -> Callable[[Optional[int]], Optional[datetime]]:
    """For one title here: when was this season's folder — or the whole title —
    last synced. None when never, as far as anything recorded says."""
    if not folder or not synced or not folder.get('path'):
        return lambda season: None
    base = folder['path']
    names = folder.get('season_folders') or {}

    def last(season: Optional[int]) -> Optional[datetime]:
        paths = [base]
        if season is not None:
            if names.get(season):
                paths.append(os.path.join(base, names[season]))
            paths.append(os.path.join(base, f"Season {int(season):02d}"))
            paths.append(os.path.join(base, f"Season {int(season)}"))
            if season == 0:
                paths.append(os.path.join(base, 'Specials'))
        moments = [synced.get(unit_key(path)) for path in paths]
        moments = [moment for moment in moments if moment]
        return max(moments) if moments else None

    return last


# =============================================================================
# One title in the list
# =============================================================================

def _merge(item: Dict[str, Any], service: Optional[Dict[str, Any]],
           local: Dict[str, Any], source: str,
           folder: Optional[Dict[str, Any]] = None,
           disk_known: bool = False) -> Dict[str, Any]:
    """One title, as the service holds it and as the disk holds it.

    Rules learned the hard way decide which titles are judged at all:

    **Only titles the service actually holds files for are judged.** A series
    added to Sonarr whose first episode has not aired has nothing to sync, and
    calling that "never synced" turns a list of real gaps into a list of
    99 non-problems. It gets its own state and is counted separately.

    **Presence is read from the disk, not from the transfer log.** The log says
    what this installation fetched; the question is what is *there*. Files put
    there by hand, restored from a backup, or synced by another instance sharing
    the disk are present either way, and deriving from history reported an
    entire library as missing.

    **Files here that the service no longer holds are not a gap.** A media
    server that deletes what has been synced leaves this disk holding more
    than the service — that is `kept_here`, shown as in sync.

    The titles left — listed, held there, present here — are judged by `_judge`.
    """
    transfers = local.get('transfers', 0)
    present_locally = folder is not None and folder.get('file_count', 0) > 0
    listed = service is not None or bool(item.get('present_in_service'))
    episodes_here = (folder or {}).get('episodes_here') or {}
    folders_here = (folder or {}).get('season_folders') or {}

    # -- what the service holds ------------------------------------------
    seasons = []
    if service and source == SOURCE_SONARR:
        our_season_files = (folder or {}).get('seasons') or {}
        for season in service.get('seasons') or []:
            number = season.get('seasonNumber')
            if number is None:
                continue
            stats = season.get('statistics') or {}
            files = stats.get('episodeFileCount') or 0
            # Season 0 is Specials. Left out of the judgement because most
            # libraries deliberately do not carry them, and a warning nobody can
            # clear is one everybody learns to ignore. Still listed below.
            seasons.append({
                'season_number': number,
                'specials': number == 0,
                'monitored': bool(season.get('monitored')),
                'episode_count': stats.get('episodeCount') or 0,
                'episode_file_count': files,
                # The files' combined size, to the byte: what the list's size
                # check matches against the files here.
                'size_on_disk': stats.get('sizeOnDisk') or 0,
                'files_here': our_season_files.get(number, 0),
                'synced_here': our_season_files.get(number, 0) > 0,
                'counts_towards_state': bool(files and number > 0),
                # Distinct episodes here, read from the file names — what
                # `episode_file_count` is compared with (it counts episodes).
                'episodes_here': episodes_here.get(number, 0),
                'folder_here': folders_here.get(number),
            })

    if source == SOURCE_SONARR:
        stats = (service or {}).get('statistics') or {}
        service_has_files = (stats.get('episodeFileCount') or 0) > 0
    else:
        service_has_files = bool((service or {}).get('hasFile'))

    # -- the states that need no judging ---------------------------------
    if not listed:
        state = cmp.ORPHAN if (present_locally or transfers) else cmp.UNKNOWN
    elif service is None:
        # Listed when last read, but the service sent no row for it now —
        # it did not answer, or the catalogue changed since. What it holds is
        # not known, and "it holds nothing" would be a claim, not a reading.
        state = cmp.UNKNOWN
    elif not disk_known:
        # Nothing to compare against. Better to say so than to report every
        # title as missing, which is what deriving from the transfer log did.
        state = cmp.UNKNOWN
    elif not service_has_files:
        state = cmp.KEPT_HERE if present_locally else cmp.NO_FILES
    elif not present_locally:
        state = cmp.NEVER
    else:
        state = None  # judged by `_judge`

    stats = (service or {}).get('statistics') or {}
    entry = {
        'external_id': item['external_id'],
        'service_item_id': item.get('service_item_id'),
        # The service's own folder, on the machine the files come *from*. It is
        # not derivable from the local one: a show filed here as
        # "Alpha Bravo" is "ALPHA BRAVO (2020)" there, and building a
        # source path out of the local name points a sync at nothing.
        'service_path': (service or {}).get('path') or '',
        'title': (service or {}).get('title') or item.get('title'),
        'year': (service or {}).get('year') or item.get('year'),
        'media_type': (folder or {}).get('media_type') or item.get('media_type'),
        'monitored': bool((service or {}).get('monitored')),
        'service_status': (service or {}).get('status'),
        'poster': _poster(service),
        'present_in_service': listed,
        'service_answered': service is not None,
        'service_has_files': service_has_files,
        'sync_state': state,
        'local_folder': (folder or {}).get('folder') or item.get('local_folder'),
        'present_locally': present_locally,
        'local_file_count': (folder or {}).get('file_count', 0),
        'transfers': transfers,
        'last_synced_at': local.get('last_synced_at'),
        'service_episode_count': stats.get('episodeCount') or 0,
        'service_episode_file_count': stats.get('episodeFileCount') or 0,
        'service_size_on_disk': stats.get('sizeOnDisk') or 0,
        'seasons': seasons,
        'seasons_synced_here': sorted(
            n for n, count in ((folder or {}).get('seasons') or {}).items() if count),
    }

    # The quiet counts line on a card: "Sonarr 1 · here 7". Specials left out
    # on both sides, as they are out of the judgement.
    if source == SOURCE_SONARR:
        entry['service_files_counted'] = sum(s['episode_file_count'] for s in seasons
                                             if s['season_number'] > 0)
        entry['episodes_here'] = sum(count for number, count in episodes_here.items()
                                     if number > 0)
    else:
        movie_file = (service or {}).get('movieFile')
        movie_file = movie_file if isinstance(movie_file, dict) else {}
        loose = (folder or {}).get('loose_media') or []
        entry['service_files_counted'] = 1 if service_has_files else 0
        entry['episodes_here'] = len(loose)
        entry['service_file_size'] = int(movie_file.get('size') or 0) or int(
            (service or {}).get('sizeOnDisk') or 0)
        entry['local_file_size'] = max((int(f.get('size') or 0) for f in loose), default=0)
        entry['quality'] = cmp.quality_name(movie_file)
    return entry


def _judge(entry: Dict[str, Any], source: str, service: Optional[Dict[str, Any]],
           folder: Optional[Dict[str, Any]],
           recent: Optional[Dict[Tuple[str, Optional[int]], List[Dict[str, Any]]]],
           last_sync: Callable[[Optional[int]], Optional[datetime]],
           exact: Optional[Dict[str, Any]]) -> None:
    """What the list calls one title, and why. Fills the state fields in place.

    Every rule here is cheap — none needs a call per title:

    (a) Sonarr's per-season count of episodes with a file, against the
        distinct episodes here. More there means something is missing here.
        When Sonarr holds as many or fewer — one to three episodes — their
        combined size must be made of files here (`cmp.holds_files_of_size`).
        That is what catches one new episode on Sonarr beside seven older
        ones here, whatever the sync records say.
    (b) An import the service made in the last two weeks for a season, after
        the last completed sync of that season's folder (the auto-scanner's
        own rule), is not here yet — unless the very file plainly is: the same
        episode at the same size.
    (c) Radarr's catalogue carries each film's file and its size, so a film is
        compared file against file with no extra call at all.

    A season where this disk holds *more* than the service is the media server
    having cleaned up after a sync: `kept_here`, which reads as in sync.

    When someone opened the title's detail view in the last ten minutes, that
    exact answer is used instead — unless the service has imported something
    for the title since it was worked out.
    """
    name = source.title()
    service_id = str((service or {}).get('id') or entry.get('service_item_id') or '')
    imports: Dict[Optional[int], List[Dict[str, Any]]] = {}
    if recent and service_id:
        imports = {season: rows for (sid, season), rows in recent.items() if sid == service_id}
    latest = max((row['at'] for rows in imports.values() for row in rows), default=None)
    entry['last_import_at'] = latest.isoformat() if latest else None

    state = entry['sync_state']
    attention: List[Dict[str, Any]] = []
    kept = 0
    exactly = False

    if state is None and source == SOURCE_SONARR:
        here = (folder or {}).get('episodes_here') or {}
        files = (folder or {}).get('episode_files') or {}
        listed = set()
        for season in entry['seasons']:
            number = season['season_number']
            listed.add(number)
            if number <= 0:
                continue
            theirs = season['episode_file_count'] or 0
            ours = here.get(number, 0)
            if theirs > ours:
                attention.append({
                    'kind': 'short' if ours else 'season_not_here',
                    'season_number': number, 'count': theirs - ours,
                    'theirs': theirs, 'ours': ours,
                })
                continue
            # As many or more here: the media server cleaning up after a sync,
            # or the service holding something this disk lacks. Counts cannot
            # tell those apart — "1 there, 7 here" is both — but sizes can.
            folder_name = season.get('folder_here')
            if theirs and folder and folder_name:
                sizes = media_sizes_in(os.path.join(folder['path'], folder_name))
                if cmp.holds_files_of_size(sizes or [], theirs,
                                           season.get('size_on_disk') or 0) is False:
                    attention.append({
                        'kind': 'not_matching', 'season_number': number, 'count': theirs,
                        'theirs': theirs, 'ours': ours,
                    })
                    continue
            kept += ours - theirs
        kept += sum(count for number, count in here.items()
                    if number > 0 and number not in listed)

        for season in sorted(s for s in imports if s is not None and s > 0):
            since = last_sync(season)
            # Only an episode's latest import describes the file the service
            # holds now. An upgrade imports the same episode again, and the
            # first import's size will never match what is here — read on its
            # own, it flagged every upgraded episode as a new file.
            latest_import: Dict[int, Dict[str, Any]] = {}
            for row in imports[season]:
                number = row.get('episode')
                if number is not None and (number not in latest_import
                                           or row['at'] > latest_import[number]['at']):
                    latest_import[number] = row
            missing: Dict[int, datetime] = {}
            changed: Dict[int, datetime] = {}
            for number, row in latest_import.items():
                if since is not None and row['at'] <= since:
                    continue
                paths = files.get((season, number)) or []
                if not paths:
                    missing[number] = row['at']
                    continue
                # The episode is here. If it is the very file imported — same
                # size — something other than a recorded sync put it here.
                if row.get('size') and folder and any(
                        size_of_path(os.path.join(folder['path'], path)) == row['size']
                        for path in paths):
                    continue
                changed[number] = row['at']
            for kind, found in (('new_import', missing), ('new_file', changed)):
                if found:
                    attention.insert(0, {
                        'kind': kind, 'season_number': season, 'count': len(found),
                        'episodes': [cmp.episode_code(season, n) for n in sorted(found)],
                        'imported_at': max(found.values()).isoformat(),
                    })
        # A season the import rule named by its episodes needs no second,
        # vaguer reason from the size check.
        named = {row['season_number'] for row in attention
                 if row['kind'] in ('new_import', 'new_file')}
        attention = [row for row in attention
                     if not (row['kind'] == 'not_matching' and row['season_number'] in named)]
        state = cmp.OUT_OF_SYNC if attention else (cmp.KEPT_HERE if kept else cmp.TITLE_IN_SYNC)

    elif state is None:
        loose = (folder or {}).get('loose_media') or []
        result = cmp.compare_movie(service or {}, {'loose': loose}, name)
        movie = result['movie']
        theirs = movie['service_file'] or {}
        if theirs.get('size') and any(f.get('size') for f in loose):
            exactly = True
            if movie['state'] == cmp.DIFFERENT:
                attention.append({'kind': 'different', 'season_number': None, 'count': 1,
                                  'quality': theirs.get('quality'), 'size': theirs.get('size')})
        else:
            # No size to compare: fall back to the import rule.
            since = last_sync(None)
            newer = [row for row in imports.get(None, []) if since is None or row['at'] > since]
            if newer:
                attention.append({'kind': 'new_file', 'season_number': None, 'count': 1,
                                  'episodes': [],
                                  'imported_at': max(r['at'] for r in newer).isoformat()})
        state = cmp.OUT_OF_SYNC if attention else cmp.TITLE_IN_SYNC

    used_exact = False
    if exact and state not in (cmp.ORPHAN, cmp.UNKNOWN) and (
            latest is None or latest <= exact['computed_at']):
        state = exact['state']
        attention = list(exact['attention'])
        kept = exact.get('kept', kept)
        used_exact = exactly = True

    entry['sync_state'] = state
    entry['attention'] = attention
    entry['kept_here_count'] = kept
    entry['state_exact'] = exactly
    entry['state_reason'] = (exact['summary'] if used_exact
                             else _reason(state, attention, kept, entry, name))


def _reason(state: str, attention: List[Dict[str, Any]], kept: int,
            entry: Dict[str, Any], name: str) -> str:
    """The list's one sentence for a title. The UI words its own from
    `attention`, with times in "2 days ago" form; this is the plain fallback."""
    if state == cmp.OUT_OF_SYNC and attention:
        first = attention[0]
        kind, count = first['kind'], first.get('count') or 0
        season = first.get('season_number')
        when = _when(_parse_iso(first.get('imported_at')))
        codes = ', '.join(first.get('episodes') or [])
        if kind == 'new_import':
            text = (f"{cmp.plural(count, 'new episode')} on {name}, imported {when}"
                    + (f" ({codes})" if codes else ''))
        elif kind == 'new_file':
            text = (f"{'A newer file' if count == 1 else f'{count} newer files'} on {name}"
                    + (f" for {codes}" if codes else '') + f", imported {when}")
        elif kind == 'short':
            text = (f"{name} has {first['theirs']} episode files for season {season}; "
                    f"{first['ours']} here")
        elif kind == 'season_not_here':
            text = f"Season {season} is not here; {name} has {first['theirs']} episode files"
        elif kind == 'not_matching':
            text = (f"{name} has a file for season {season} that is not here"
                    if first['theirs'] == 1 else
                    f"Not all of {name}'s {first['theirs']} files for season {season} are here")
        elif kind == 'missing':
            text = f"{cmp.plural(count, 'episode')} on {name} not here yet ({codes})"
        else:
            text = f"{name} holds a different file"
        more = len(attention) - 1
        return text + (f" — and {more} more" if more > 0 else '') + '.'
    if state == cmp.TITLE_IN_SYNC:
        return f"Everything {name} holds is here."
    if state == cmp.KEPT_HERE:
        if not entry.get('service_has_files'):
            return f"{name} holds no files for it any more; what is here is kept."
        return (f"Everything {name} holds is here; {cmp.plural(kept, 'more episode')} "
                f"kept only here.")
    if state == cmp.NEVER:
        return f"Not here yet. {name} holds files for it."
    if state == cmp.NO_FILES:
        return f"{name} holds no files for it yet."
    if state == cmp.ORPHAN:
        return f"{name} no longer lists it; the files here are kept."
    if not entry.get('present_in_service'):
        return f"Not in {name}'s catalogue, and not here."
    if not entry.get('service_answered'):
        return f"Cannot tell: {name} did not send this title."
    return "Cannot tell: the library folders could not be read."
