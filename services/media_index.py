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

Every public method here returns a value on every path. Nothing raises, and
nothing blocks for longer than the timeout on one HTTP call. A caller that
cannot get an answer is expected to carry on exactly as it did before this
module existed — which is what makes the whole feature safe to switch on.
"""

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models.media_item import SOURCE_RADARR, SOURCE_SONARR, MediaItemStore
from services.connectors.adapters._arr import UNKNOWN, InFlight
from services.local_library import LocalLibrary

#: Media types that come from Sonarr. Anime is a separate library here but the
#: same service upstream, which is why source and media_type are separate
#: fields — a show can move between libraries without changing identity.
SONARR_MEDIA_TYPES = ('tvshows', 'anime')


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MediaIndex:
    """Keeps the title index current and answers the gate's question."""

    def __init__(self, db_manager, connector_service=None, config=None):
        self.store = MediaItemStore(db_manager)
        self._connectors = connector_service
        # Presence is read from the disk, not from the transfer log. Without a
        # config there is nothing to walk, and the view falls back to saying it
        # cannot tell rather than guessing from history.
        self.local = LocalLibrary(config) if config is not None else None
        self._lock = threading.Lock()

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
        return True, len(seen)

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
        """
        live = False
        if refresh:
            live, _ = self.refresh_library(source)

        service_rows: Dict[str, Dict[str, Any]] = {}
        adapter = self._adapter(source)
        if adapter is not None:
            ok, rows = adapter.library()
            if ok:
                live = True
                field = adapter.external_id_field
                for row in rows:
                    key = row.get(field)
                    if key not in (None, ''):
                        service_rows[str(key)] = row

        facts = self._local_facts()
        on_disk = self.local.scan() if self.local else None

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

            items.append(_merge(item, service, local, source, folder,
                                disk_known=on_disk is not None))

        counts: Dict[str, int] = {}
        for entry in items:
            counts[entry['sync_state']] = counts.get(entry['sync_state'], 0) + 1

        return {
            'source': source,
            'live': live,
            'total': len(items),
            'counts': counts,
            'items': items,
        }

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

        now = datetime.now(timezone.utc)
        entries, counts = [], {}
        for row in rows:
            verdict = adapter.classify_row(row)
            service_item_id = (row.get('seriesId') if source == SOURCE_SONARR
                               else row.get('movieId'))
            known = by_service_id.get(service_item_id)

            size = row.get('size') or 0
            left = row.get('sizeleft') or 0
            progress = round(100 * (1 - left / size), 1) if size else 0.0

            added = _parse_iso(row.get('added'))
            age_hours = round((now - added).total_seconds() / 3600, 1) if added else None

            # A row naming no title cannot hold a sync — nothing knows what it
            # would be holding — but it is the single most likely row to have
            # been sitting there forgotten, so it is called out rather than hidden.
            unattributed = service_item_id in (None, '')

            entry = {
                'id': row.get('id'),
                'title': (known or {}).get('title') or row.get('title') or 'Unknown',
                'release': row.get('title'),
                'service_item_id': service_item_id,
                'external_id': (known or {}).get('external_id'),
                'known_here': known is not None,
                'unattributed': unattributed,
                'season_number': row.get('seasonNumber'),
                'state': row.get('trackedDownloadState'),
                'status': row.get('trackedDownloadStatus'),
                'verdict': verdict['verdict'],
                'holds_sync': bool(verdict['holds']) and not unattributed,
                'why': verdict['why'],
                'progress': progress,
                'size': size,
                'size_left': left,
                'time_left': row.get('timeleft'),
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
                     page_size: int = 50) -> Dict[str, Any]:
        """A page of the service's own history. Read-only, always."""
        adapter = self._adapter(source)
        if adapter is None:
            return {'source': source, 'live': False, 'records': [],
                    'page': page, 'total': 0,
                    'message': f'{source.title()} is not connected'}
        ok, payload = adapter.history(page=page, page_size=page_size)
        if not ok:
            return {'source': source, 'live': False, 'records': [],
                    'page': page, 'total': 0,
                    'message': f'{source.title()} did not answer'}

        by_service_id = {}
        for item in self.store.list_items(source=source):
            if item.get('service_item_id'):
                by_service_id[item['service_item_id']] = item

        records = []
        for record in payload.get('records', []):
            if not isinstance(record, dict):
                continue
            service_item_id = (record.get('seriesId') if source == SOURCE_SONARR
                               else record.get('movieId'))
            known = by_service_id.get(service_item_id)
            records.append({
                'id': record.get('id'),
                'event_type': record.get('eventType'),
                'date': record.get('date'),
                'source_title': record.get('sourceTitle'),
                'quality': ((record.get('quality') or {}).get('quality') or {}).get('name'),
                'service_item_id': service_item_id,
                'title': (known or {}).get('title'),
                'external_id': (known or {}).get('external_id'),
                'known_here': known is not None,
            })

        return {
            'source': source, 'live': True, 'records': records,
            'page': payload.get('page', page),
            'page_size': payload.get('pageSize', page_size),
            'total': payload.get('totalRecords', len(records)),
        }


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


def _season_number(season_name: str) -> Optional[int]:
    """The number out of a folder label such as "Season 03"."""
    if not season_name:
        return None
    digits = ''.join(ch for ch in str(season_name) if ch.isdigit())
    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def _merge(item: Dict[str, Any], service: Optional[Dict[str, Any]],
           local: Dict[str, Any], source: str,
           folder: Optional[Dict[str, Any]] = None,
           disk_known: bool = False) -> Dict[str, Any]:
    """One title, as the service holds it and as the disk holds it.

    Two rules decide the state, and both were learned the hard way.

    **Only titles the service actually holds files for are judged.** A series
    added to Sonarr whose first episode has not aired has nothing to sync, and
    calling that "never synced" turns a list of real gaps into a list of
    99 non-problems. It gets its own state and is counted separately.

    **Presence is read from the disk, not from the transfer log.** The log says
    what this installation fetched; the question is what is *there*. Files put
    there by hand, restored from a backup, or synced by another instance sharing
    the disk are present either way, and deriving from history reported an
    entire library as missing.
    """
    transfers = local.get('transfers', 0)
    present_locally = folder is not None and folder.get('file_count', 0) > 0
    listed = service is not None or bool(item.get('present_in_service'))

    # -- what the service holds ------------------------------------------
    their_seasons = set()
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
            if files and number > 0:
                their_seasons.add(number)
            seasons.append({
                'season_number': number,
                'specials': number == 0,
                'monitored': bool(season.get('monitored')),
                'episode_count': stats.get('episodeCount') or 0,
                'episode_file_count': files,
                'files_here': our_season_files.get(number, 0),
                'synced_here': our_season_files.get(number, 0) > 0,
                'counts_towards_state': bool(files and number > 0),
            })

    if source == SOURCE_SONARR:
        stats = (service or {}).get('statistics') or {}
        service_has_files = (stats.get('episodeFileCount') or 0) > 0
    else:
        service_has_files = bool((service or {}).get('hasFile'))

    # -- the state -------------------------------------------------------
    if not listed:
        state = 'orphan' if (present_locally or transfers) else 'unknown'
    elif not disk_known:
        # Nothing to compare against. Better to say so than to report every
        # title as missing, which is what deriving from the transfer log did.
        state = 'unknown'
    elif not service_has_files:
        state = 'no_files'
    elif not present_locally:
        state = 'never'
    elif source == SOURCE_SONARR and (their_seasons - {
            n for n, count in ((folder or {}).get('seasons') or {}).items() if count}):
        state = 'partial'
    else:
        state = 'synced'

    stats = (service or {}).get('statistics') or {}
    poster = ''
    for image in (service or {}).get('images') or []:
        if image.get('coverType') == 'poster':
            poster = image.get('remoteUrl') or image.get('url') or ''
            break

    return {
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
        'poster': poster,
        'present_in_service': listed,
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
