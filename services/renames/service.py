#!/usr/bin/env python3
"""
Renames from DragonCP: find the episodes still named TBA, find their titles,
rename them here, and have Sonarr rename its own copy.

Where a title comes from, in order (operator, 2026-10-23):

  1. Sonarr holds the file and its rename would give it a real title: the
     name here becomes exactly Sonarr's new name, and Sonarr is asked to rename
     its copy too. Both ends then carry the same name.
  2. Sonarr has a real title but no longer holds the file (the remote server
     cleans up after a sync): the title is swapped into the name here.
  3. Sonarr still says TBA, or does not have the series: TMDB's title, if a
     key is set and the episode can be matched safely. Only ever for a file
     still named TBA. When Sonarr later gets a title of its own, the check
     offers to rename to that.

Identity is the episode (SxxEyy), never the old file name, and only the title
part of a name changes. A rename never leaves its folder, never overwrites, and
takes the episode's subtitles, `.nfo` and artwork with it. Test mode rehearses:
the same plan and the same report, and nothing on disk or in Sonarr changes.

How often Sonarr is asked: never on a page view. A title check reads one list
per series with a TBA episode; a preview or a rename reads three more for the
one series. Requests are spaced half a second apart.
"""

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from env_flags import test_mode_enabled
from security import (
    PathTraversalError, assert_path_within_bounds, validate_path_component,
)
from services.explore.identity import EpisodeKey, is_media_file
from services.explore.inventory import FileEntry, LocalInventory, build_entry
from services.local_library import normalise, year_of

from . import naming
from .tmdb import TmdbClient

#: The libraries that have episodes. Films have no titles to wait for: none of
#: the 223 on this disk carried a placeholder when this was written.
LIBRARIES = {'tvshows': 'TVSHOW_DEST_PATH', 'anime': 'ANIME_DEST_PATH'}
LABELS = {'tvshows': 'TV Shows', 'anime': 'Anime'}

#: Seconds between two requests to Sonarr.
SONARR_SPACING = 0.5

#: How long Sonarr's series list and naming settings are reused.
SERIES_LIST_SECONDS = 600

#: How far apart Sonarr's and TMDB's air dates may be for one episode.
AIR_DATE_SLACK_DAYS = 1

READY, WAITING, SKIPPED = 'ready', 'waiting', 'skipped'
SOURCE_SONARR, SOURCE_TMDB = 'sonarr', 'tmdb'


class RenamesError(Exception):
    """A message meant for the operator, and an HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class _Candidate:
    entry: FileEntry
    #: Renamed to a TMDB title earlier; only Sonarr's own title replaces it.
    tmdb_titled: bool = False


@dataclass
class _Sources:
    """What is known about one series' titles, gathered once per plan."""
    media_type: str
    folder: str
    sonarr_state: str = 'off'            # found | missing | unavailable | off
    series: Optional[Dict[str, Any]] = None
    episodes: Dict[Tuple[int, int], Dict[str, Any]] = field(default_factory=dict)
    files: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    preview: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    #: Whether files and the rename preview were read (a preview or a rename).
    full: bool = False
    rules: naming.NamingRules = field(default_factory=naming.NamingRules)
    tmdb: Optional[TmdbClient] = None
    tmdb_state: str = 'off'              # linked | unlinked | unavailable | off
    tmdb_id: Optional[int] = None
    tmdb_name: str = ''
    tmdb_link_source: str = ''
    tmdb_counts: Dict[int, int] = field(default_factory=dict)
    tmdb_seasons: Dict[int, Optional[Dict[int, Dict[str, Any]]]] = field(default_factory=dict)


class RenamesService:
    def __init__(self, config, db_manager, rename_model, store, *,
                 connectors: Optional[Callable[[], Any]] = None,
                 active_transfers: Optional[Callable[[], List[Dict[str, Any]]]] = None,
                 media_items=None, socketio=None, notification_service=None,
                 alerts=None, sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self.db = db_manager
        self.rename_model = rename_model
        self.store = store
        self._connectors = connectors or _default_connectors
        self._active_transfers = active_transfers
        self.media_items = media_items
        self.socketio = socketio
        self.notification_service = notification_service
        self.alerts = alerts
        self._sleep = sleep
        self._pace_lock = threading.Lock()
        self._last_sonarr_call = 0.0
        self._series_cache: Optional[Tuple[float, List[Dict[str, Any]]]] = None
        self._naming_cache: Optional[Tuple[float, naming.NamingRules]] = None
        self._check_lock = threading.Lock()
        self._library_runs: Dict[str, Dict[str, Any]] = {}

    # ==================================================================
    # Sonarr and TMDB
    # ==================================================================

    def _sonarr_adapter(self):
        """Sonarr's adapter while it is switched on, configured or not. Never raises."""
        try:
            service = self._connectors()
            if service is None:
                return None
            row = service.store.get_connector('sonarr')
            if not row or not row.get('enabled'):
                return None
            return service.adapter('sonarr')
        except Exception:  # noqa: BLE001 - "cannot tell" reads as "not connected"
            return None

    def _sonarr(self):
        adapter = self._sonarr_adapter()
        return adapter if adapter is not None and adapter.is_configured() else None

    def _tmdb(self) -> Optional[TmdbClient]:
        """The TMDB client, from the key on Sonarr's Connection tab."""
        adapter = self._sonarr_adapter()
        token = adapter.tmdb_token() if adapter is not None and hasattr(adapter, 'tmdb_token') else ''
        return TmdbClient(token) if token else None

    def title_check_hours(self) -> int:
        adapter = self._sonarr()
        if adapter is None or not hasattr(adapter, 'title_check_hours'):
            return 0
        return adapter.title_check_hours()

    def _paced(self, call: Callable, *args):
        """One Sonarr request, at least `SONARR_SPACING` after the last one."""
        with self._pace_lock:
            wait = SONARR_SPACING - (time.monotonic() - self._last_sonarr_call)
            if wait > 0:
                self._sleep(wait)
            try:
                return call(*args)
            finally:
                self._last_sonarr_call = time.monotonic()

    def _series_list(self, adapter) -> Tuple[bool, List[Dict[str, Any]]]:
        cached = self._series_cache
        if cached and time.monotonic() - cached[0] < SERIES_LIST_SECONDS:
            return True, cached[1]
        ok, rows = self._paced(adapter.library)
        if ok:
            self._series_cache = (time.monotonic(), rows)
        return ok, rows

    def _naming_rules(self, adapter) -> naming.NamingRules:
        cached = self._naming_cache
        if cached and time.monotonic() - cached[0] < SERIES_LIST_SECONDS:
            return cached[1]
        config = self._paced(adapter.naming_config)
        rules = naming.NamingRules.from_sonarr(config)
        if config is not None:
            self._naming_cache = (time.monotonic(), rules)
        return rules

    def _match_series(self, rows: List[Dict[str, Any]], folder: str) -> Optional[Dict[str, Any]]:
        """The Sonarr series this folder holds: by its folder, then by its name."""
        for row in rows:
            if os.path.basename(str(row.get('path') or '').rstrip('/\\')) == folder:
                return row
        if self.media_items is not None:
            try:
                item = self.media_items.get_by_folder(folder)
            except Exception:  # noqa: BLE001
                item = None
            if item and item.get('source') == 'sonarr':
                for row in rows:
                    if str(row.get('tvdbId')) == str(item.get('external_id')):
                        return row
        wanted, year = normalise(folder), year_of(folder)
        named = [r for r in rows if normalise(r.get('title') or '') == wanted]
        if year:
            dated = [r for r in named if r.get('year') == year]
            named = dated or named
        return named[0] if len(named) == 1 else None

    def _sources(self, media_type: str, folder: str, full: bool) -> _Sources:
        src = _Sources(media_type=media_type, folder=folder, full=full)
        adapter = self._sonarr()
        if adapter is not None:
            ok, rows = self._series_list(adapter)
            if not ok:
                src.sonarr_state = 'unavailable'
            else:
                series = self._match_series(rows, folder)
                if series is None:
                    src.sonarr_state = 'missing'
                else:
                    src.series = series
                    ok, episodes = self._paced(adapter.episodes, series.get('id'))
                    if not ok:
                        src.sonarr_state = 'unavailable'
                    else:
                        src.sonarr_state = 'found'
                        for episode in episodes:
                            key = (episode.get('seasonNumber'), episode.get('episodeNumber'))
                            if None not in key:
                                src.episodes[key] = episode
                        if full:
                            src.rules = self._naming_rules(adapter)
                            ok_files, files = self._paced(adapter.episode_files, series.get('id'))
                            ok_preview, preview = self._paced(adapter.rename_preview,
                                                              series.get('id'))
                            if not (ok_files and ok_preview):
                                src.sonarr_state = 'unavailable'
                            else:
                                src.files = {f.get('id'): f for f in files if f.get('id')}
                                src.preview = {p.get('episodeFileId'): p for p in preview
                                               if p.get('episodeFileId')}
        src.tmdb = self._tmdb()
        if src.tmdb is not None:
            link = self.store.link(media_type, folder)
            src.tmdb_state = 'unlinked'
            if link:
                src.tmdb_state = 'linked'
                src.tmdb_id = int(link['tmdb_id'])
                src.tmdb_name = link.get('tmdb_name') or ''
                src.tmdb_link_source = link.get('source') or 'manual'
        return src

    def _tmdb_show(self, src: _Sources) -> Optional[int]:
        """TMDB's id for this series, matched once and remembered."""
        if src.tmdb is None:
            return None
        if src.tmdb_id is None and src.series is not None:
            show = None
            if src.series.get('tmdbId'):
                show = src.tmdb.show(src.series['tmdbId'])
            if show is None and src.series.get('tvdbId'):
                found = src.tmdb.find_by_tvdb(src.series['tvdbId'])
                show = src.tmdb.show(found['tmdb_id']) if found else None
            if show and show.get('tmdb_id'):
                src.tmdb_id = int(show['tmdb_id'])
                src.tmdb_name = show.get('name') or ''
                src.tmdb_counts = show.get('seasons') or {}
                src.tmdb_state = 'linked'
                src.tmdb_link_source = 'sonarr'
                self.store.save_link(src.media_type, src.folder, src.tmdb_id, src.tmdb_name,
                                     show.get('year'), source='sonarr')
            else:
                src.tmdb_state = 'unavailable'
        if src.tmdb_id is not None and not src.tmdb_counts:
            show = src.tmdb.show(src.tmdb_id)
            src.tmdb_counts = (show or {}).get('seasons') or {}
        return src.tmdb_id

    def _tmdb_season(self, src: _Sources, season: int) -> Optional[Dict[int, Dict[str, Any]]]:
        if season not in src.tmdb_seasons:
            show_id = self._tmdb_show(src)
            src.tmdb_seasons[season] = src.tmdb.season(show_id, season) if show_id else None
        return src.tmdb_seasons[season]

    # ==================================================================
    # what is on the disk
    # ==================================================================

    def _root(self, media_type: str) -> str:
        if media_type not in LIBRARIES:
            raise RenamesError('Renames are for TV shows and anime', 404)
        root = self.config.get(LIBRARIES[media_type])
        if not root:
            raise RenamesError(f"No local path configured for {LABELS[media_type]}", 409)
        return root

    def _local(self, media_type: str, folder: str, season: Optional[str] = None
               ) -> Tuple[str, List[FileEntry], Dict[str, List[str]]]:
        """Every media file in the season folders of one series, and their neighbours."""
        if not validate_path_component(folder):
            raise RenamesError('Invalid folder name', 400)
        if season and not validate_path_component(season):
            raise RenamesError('Invalid season name', 400)
        root = self._root(media_type)
        series_dir = os.path.join(root, folder)
        try:
            assert_path_within_bounds(series_dir, [root])
        except PathTraversalError as error:
            raise RenamesError(str(error), 400) from error
        if not os.path.isdir(series_dir):
            raise RenamesError(f"'{folder}' is not on this disk", 404)

        entries: List[FileEntry] = []
        siblings: Dict[str, List[str]] = {}
        for child in sorted(os.scandir(series_dir), key=lambda c: c.name):
            if not child.is_dir() or (season and child.name != season):
                continue
            names = []
            try:
                items = list(os.scandir(child.path))
            except OSError:
                continue
            for item in items:
                if not item.is_file():
                    continue
                names.append(item.name)
                if is_media_file(item.name):
                    try:
                        stat = item.stat()
                        size, mtime = stat.st_size, int(stat.st_mtime)
                    except OSError:
                        size, mtime = 0, 0
                    entries.append(build_entry(media_type, f"{folder}/{child.name}/{item.name}",
                                               size, mtime))
            siblings[child.name] = names
        return root, entries, siblings

    def _candidates(self, media_type: str, folder: str,
                    entries: Sequence[FileEntry]) -> List[_Candidate]:
        titled = self.store.episode_titles(media_type, folder)
        out = []
        for entry in entries:
            if entry.season is None or entry.misplaced:
                continue
            if naming.is_placeholder(entry.name):
                out.append(_Candidate(entry))
                continue
            if len(entry.keys) == 1:
                row = titled.get((entry.keys[0].season, entry.keys[0].episode))
                if row and row.get('source') == SOURCE_TMDB and row.get('file_name') == entry.name:
                    out.append(_Candidate(entry, tmdb_titled=True))
        return out

    # ==================================================================
    # deciding one file
    # ==================================================================

    def _decide(self, candidate: _Candidate, src: _Sources,
                season_size: Dict[int, int]) -> Optional[Dict[str, Any]]:
        entry = candidate.entry
        item: Dict[str, Any] = {
            'path': entry.relative_path.split('/', 1)[1],
            'season_folder': entry.season_folder,
            'season': entry.season,
            'code': str(entry.keys[0]) if entry.keys else entry.name,
            'old_name': entry.name,
            'new_name': None,
            'title': None,
            'source': None,
            'state': WAITING,
            'reason': '',
            'sidecars': [],
            'sonarr_file_id': None,
            'sonarr_rename': False,
            'retitle': candidate.tmdb_titled,
            'size': entry.size,
        }

        copy = self._sonarr_copy(entry, src)
        if copy['file_id']:
            # Sonarr still names its copy TBA and its rename would give it the
            # title: it is asked to, whatever this file ends up called.
            item.update(sonarr_file_id=copy['file_id'], sonarr_rename=True)

        if len(entry.keys) != 1:
            # Sonarr names a double episode by joining both titles. Until that
            # rule is checked against real files, only Sonarr's own name is
            # trusted for one.
            if copy['name']:
                item.update(state=READY, new_name=copy['name'],
                            title=naming.title_of(copy['name']), source=SOURCE_SONARR)
                return item
            item.update(state=SKIPPED, reason='It holds more than one episode. '
                                              'Rename it in Sonarr.')
            return item

        key = entry.keys[0]
        episode = src.episodes.get((key.season, key.episode))
        sonarr_title = (episode or {}).get('title')

        if copy['name']:
            item.update(state=READY, new_name=copy['name'],
                        title=naming.title_of(copy['name']), source=SOURCE_SONARR)
            return item

        if naming.is_real_title(sonarr_title):
            new_name, why = naming.retitle(entry.name, sonarr_title, src.rules)
            if new_name is None:
                item.update(state=SKIPPED, reason=why)
            elif new_name == entry.name:
                item.update(state=SKIPPED, reason='It already has this title')
            else:
                item.update(state=READY, new_name=new_name, title=sonarr_title,
                            source=SOURCE_SONARR)
            return item

        if candidate.tmdb_titled:
            # Named from TMDB already, and Sonarr has no title of its own yet:
            # nothing to offer, and nothing wrong with it either.
            return None

        title, why = self._tmdb_title(src, key, episode, season_size)
        if title:
            new_name, retitle_why = naming.retitle(entry.name, title, src.rules)
            if new_name is None:
                item.update(state=SKIPPED, reason=retitle_why)
            else:
                item.update(state=READY, new_name=new_name, title=title, source=SOURCE_TMDB)
            return item

        item.update(state=WAITING, reason=self._waiting_reason(src, why, sonarr_title))
        return item

    def _sonarr_copy(self, entry: FileEntry, src: _Sources) -> Dict[str, Any]:
        """Sonarr's copy of this episode: what it would be renamed to, and by whom.

        `file_id` is set when Sonarr's copy is still named TBA and its own
        rename would give it a real title, so Sonarr is asked to rename it.
        `name` is Sonarr's new name for it, given to the file here too when the
        two are the same file named alike apart from the title, so both ends
        match afterwards. Read from a preview or a rename only, never a check.
        """
        out: Dict[str, Any] = {'name': None, 'file_id': None}
        if not src.full or not src.files or not entry.keys:
            return out
        episode = src.episodes.get((entry.keys[0].season, entry.keys[0].episode)) or {}
        held = src.files.get(episode.get('episodeFileId')) if episode.get('hasFile') else None
        if not held:
            return out
        existing = os.path.basename(str(held.get('relativePath') or '').replace('\\', '/'))
        preview = src.preview.get(held.get('id'))
        target = (os.path.basename(str(preview.get('newPath') or '').replace('\\', '/'))
                  if preview else existing)
        if not target or not naming.is_real_title(naming.title_of(target)):
            return out
        if preview and naming.is_placeholder(existing):
            out['file_id'] = held.get('id')
        same_file = entry.name == existing or naming.same_apart_from_title(entry.name, existing)
        if same_file and target != entry.name:
            out['name'] = target
        return out

    def _tmdb_title(self, src: _Sources, key: EpisodeKey, episode: Optional[Dict[str, Any]],
                    season_size: Dict[int, int]) -> Tuple[Optional[str], str]:
        """TMDB's title for one episode, only when it is surely the same episode."""
        if src.tmdb is None:
            return None, 'no-key'
        if src.sonarr_state == 'unavailable':
            # Without Sonarr's air dates a Sonarr series cannot be matched safely.
            return None, ''
        if src.series is None and src.tmdb_state != 'linked':
            return None, 'unlinked'
        season = self._tmdb_season(src, key.season)
        if season is None:
            if src.tmdb_id is None:
                return None, 'tmdb-unmatched'
            return None, f"TMDB has no season {key.season} for it"
        found = season.get(key.episode)
        if not found:
            return None, f"TMDB has no episode {key.episode} in season {key.season}"
        if not naming.is_real_title(found.get('title')):
            return None, 'tmdb-untitled'
        if src.series is not None:
            # Both sides number the same episode: their air dates must agree.
            sonarr_day = _day(episode.get('airDate') if episode else None)
            tmdb_day = _day(found.get('air_date'))
            if sonarr_day is None or tmdb_day is None:
                return None, "Can't match it to TMDB safely: one side has no air date"
            if abs((sonarr_day - tmdb_day).days) > AIR_DATE_SLACK_DAYS:
                return None, ("Can't match it to TMDB safely: TMDB's episode with this number "
                              "aired on another day")
        else:
            # No Sonarr to compare with: the season here must fit TMDB's.
            if season_size.get(key.season, 0) > len(season):
                return None, ("Can't match it to TMDB safely: this season has more episodes "
                              "here than on TMDB")
        return found['title'], ''

    @staticmethod
    def _waiting_reason(src: _Sources, why: str, sonarr_title: Optional[str] = None) -> str:
        if why and why not in ('no-key', 'unlinked', 'tmdb-unmatched', 'tmdb-untitled'):
            return why
        if src.sonarr_state == 'off':
            base = 'Sonarr is not connected'
        elif src.sonarr_state == 'unavailable':
            base = 'Sonarr did not answer'
        elif src.sonarr_state == 'missing':
            if why == 'no-key':
                return 'Not in Sonarr. Add a TMDB key on Sonarr’s Connection tab to find titles'
            if why == 'unlinked':
                return 'Not in Sonarr. Find it on TMDB to get titles'
            base = 'Not in Sonarr'
        elif sonarr_title and not naming.is_placeholder_title(sonarr_title):
            # "Episode 17" is a number, not a title: renaming to it gains nothing.
            base = f"Sonarr only has “{sonarr_title.strip()}” so far"
        else:
            base = 'Sonarr still says TBA'
        if why == 'tmdb-untitled':
            return f"{base}, and TMDB has no title yet either"
        if why == 'tmdb-unmatched':
            return f"{base}, and TMDB could not be matched to this series"
        return base

    def _finish(self, items: List[Dict[str, Any]], siblings: Dict[str, List[str]]) -> None:
        """Sidecars, and never two files given one name or a name already taken."""
        leaving = {(i['season_folder'], i['old_name']) for i in items if i['state'] == READY}
        claimed: Dict[Tuple[str, str], int] = {}
        for item in items:
            if item['state'] == READY:
                claimed[(item['season_folder'], item['new_name'])] = \
                    claimed.get((item['season_folder'], item['new_name']), 0) + 1
        for item in items:
            if item['state'] != READY:
                continue
            folder = item['season_folder']
            names = siblings.get(folder, [])
            taken = set(names) - {n for f, n in leaving if f == folder}
            if claimed[(folder, item['new_name'])] > 1:
                item.update(state=SKIPPED, new_name=None,
                            reason='Another file here would get the same name')
                continue
            if item['new_name'] in taken:
                item.update(state=SKIPPED, new_name=None,
                            reason='A file with the new name already exists here')
                continue
            pairs = naming.sidecars(item['old_name'], item['new_name'], names)
            clash = [new for _old, new in pairs if new in taken]
            if clash:
                item.update(state=SKIPPED, new_name=None,
                            reason=f"Its {clash[0].rsplit('.', 1)[-1]} file would overwrite "
                                   'one already there')
                continue
            item['sidecars'] = [{'old': old, 'new': new} for old, new in pairs]

    # ==================================================================
    # the plan
    # ==================================================================

    def _build(self, media_type: str, folder: str, season: Optional[str], full: bool
               ) -> Tuple[str, List[Dict[str, Any]], _Sources]:
        root, entries, siblings = self._local(media_type, folder, season)
        candidates = self._candidates(media_type, folder, entries)
        src = _Sources(media_type=media_type, folder=folder)
        items: List[Dict[str, Any]] = []
        if candidates:
            src = self._sources(media_type, folder, full)
            season_size: Dict[int, int] = {}
            for entry in entries:
                for key in entry.keys:
                    season_size[key.season] = max(season_size.get(key.season, 0), key.episode)
            items = [item for item in (self._decide(c, src, season_size) for c in candidates)
                     if item is not None]
            self._finish(items, siblings)
        items.sort(key=lambda i: (i['season'] if i['season'] is not None else -1, i['code']))
        return root, items, src

    def plan(self, media_type: str, folder: str, season: Optional[str] = None) -> Dict[str, Any]:
        """What renaming here would do. Changes nothing."""
        _root, items, src = self._build(media_type, folder, season, full=True)
        return self._payload(media_type, folder, season, items, src)

    def _payload(self, media_type: str, folder: str, season: Optional[str],
                 items: List[Dict[str, Any]], src: _Sources) -> Dict[str, Any]:
        counts = {
            READY: sum(1 for i in items if i['state'] == READY),
            WAITING: sum(1 for i in items if i['state'] == WAITING),
            SKIPPED: sum(1 for i in items if i['state'] == SKIPPED),
            'sonarr_files': sum(1 for i in items if i['state'] == READY and i['sonarr_rename']),
            'sidecars': sum(len(i['sidecars']) for i in items if i['state'] == READY),
            'from_tmdb': sum(1 for i in items if i['state'] == READY and i['source'] == SOURCE_TMDB),
        }
        return {
            'media_type': media_type,
            'folder': folder,
            'season': season,
            'scope': f"{folder} — {season}" if season else folder,
            'items': items,
            'counts': counts,
            'sonarr': self._sonarr_summary(src),
            'tmdb': self._tmdb_summary(src),
            'blocker': self._blocker(media_type, folder),
            'test_mode': test_mode_enabled(),
        }

    @staticmethod
    def _sonarr_summary(src: _Sources) -> Dict[str, Any]:
        words = {
            'found': f"In Sonarr as {(src.series or {}).get('title') or 'this series'}",
            'missing': 'Not in Sonarr',
            'unavailable': 'Sonarr did not answer',
            'off': 'Sonarr is not connected',
        }
        return {
            'state': src.sonarr_state,
            'series_id': (src.series or {}).get('id'),
            'title': (src.series or {}).get('title'),
            'message': words.get(src.sonarr_state, ''),
        }

    @staticmethod
    def _tmdb_summary(src: _Sources) -> Dict[str, Any]:
        return {
            'state': src.tmdb_state,
            'tmdb_id': src.tmdb_id,
            'name': src.tmdb_name,
            'link_source': src.tmdb_link_source or None,
        }

    def _blocker(self, media_type: str, folder: str) -> Optional[str]:
        """Why a rename must not run now: a transfer writing into this series."""
        if self._active_transfers is None:
            return None
        try:
            active = [t for t in self._active_transfers()
                      if (t.get('media_type') or '') == media_type
                      and (t.get('folder_name') or '') == folder]
        except Exception as error:  # noqa: BLE001 - cannot tell, so refuse
            return (f"Could not check whether a transfer is running ({error}). A rename only "
                    'runs when this series is known to be idle.')
        if not active:
            return None
        noun = 'transfer is' if len(active) == 1 else 'transfers are'
        return (f"{len(active)} {noun} still writing into {folder}. Rename waits until it "
                'finishes.')

    # ==================================================================
    # renaming
    # ==================================================================

    def apply(self, media_type: str, folder: str, season: Optional[str] = None,
              picks: Optional[Sequence[Dict[str, str]]] = None,
              actor: Optional[str] = None, trigger: str = 'manual',
              announce: bool = True) -> Dict[str, Any]:
        """Rename what the preview showed.

        The plan is rebuilt here from the disk and Sonarr as they are now. The
        caller names the files it approved, by their path and the new name it
        was shown; anything whose new name has changed since is left alone.
        """
        blocker = self._blocker(media_type, folder)
        if blocker:
            raise RenamesError(blocker, 409)
        root, items, src = self._build(media_type, folder, season, full=True)
        ready = [i for i in items if i['state'] == READY]
        if picks is not None:
            wanted = {(str(p.get('path') or ''), str(p.get('new_name') or ''))
                      for p in picks if isinstance(p, dict)}
            chosen = [i for i in ready if (i['path'], i['new_name']) in wanted]
            if wanted and not chosen:
                raise RenamesError('These names changed since the preview. Review them again.',
                                   409)
        else:
            chosen = ready
        if not chosen:
            raise RenamesError('Nothing here can be renamed right now.', 400)

        dry_run = test_mode_enabled()
        results = [self._rename_one(root, folder, item, dry_run) for item in chosen]
        done = [r for r in results if r['status'] == 'success']

        sonarr = self._ask_sonarr(src, [r for r in done if r.get('sonarr_rename')], dry_run)
        if not dry_run:
            for result in done:
                key = result.get('key')
                if not key:
                    continue
                if result['source'] == SOURCE_TMDB:
                    self.store.record_title(media_type, folder, key[0], key[1],
                                            result['title'] or '', SOURCE_TMDB, result['new_name'])
                else:
                    self.store.forget_title(media_type, folder, key[0], key[1])

        record = self._record(media_type, folder, src, results, sonarr, trigger, actor, dry_run,
                              announce)
        try:
            self.check_folder(media_type, folder)
        except Exception:  # noqa: BLE001 - the rename is done whatever the check says
            pass
        return record

    def _rename_one(self, root: str, folder: str, item: Dict[str, Any],
                    dry_run: bool) -> Dict[str, Any]:
        directory = os.path.join(root, folder, item['season_folder'])
        old = os.path.join(directory, item['old_name'])
        new = os.path.join(directory, item['new_name'])
        result = {
            'previous_name': item['old_name'],
            'new_name': item['new_name'],
            'previous_relative_path': item['path'],
            'new_relative_path': f"{item['season_folder']}/{item['new_name']}",
            'local_previous_path': old,
            'local_new_path': new,
            'code': item['code'],
            'title': item['title'],
            'source': item['source'],
            'sonarr_rename': item['sonarr_rename'],
            'sonarr_file_id': item['sonarr_file_id'],
            'sidecars': [],
            'status': 'failed',
            'message': '',
            'error': None,
            'dry_run': dry_run,
            'key': None,
        }
        if item['code'] and item['code'][:1] == 'S' and 'E' in item['code']:
            try:
                season, episode = item['code'][1:].split('E', 1)
                result['key'] = (int(season), int(episode))
            except ValueError:
                result['key'] = None
        pairs = [(os.path.join(directory, s['old']), os.path.join(directory, s['new']))
                 for s in item['sidecars']]
        try:
            for path in [old, new, *[p for pair in pairs for p in pair]]:
                assert_path_within_bounds(path, [root])
            if not os.path.lexists(old):
                result.update(message='The file is no longer there', error='missing')
                return result
            if os.path.lexists(new):
                result.update(message='A file with the new name already exists',
                              error='target exists')
                return result
            for _src, dst in pairs:
                if os.path.lexists(dst):
                    result.update(message=f"{os.path.basename(dst)} already exists",
                                  error='sidecar target exists')
                    return result
            if dry_run:
                result.update(status='success', message='Test mode: not renamed')
                result['sidecars'] = [{'old': os.path.basename(a), 'new': os.path.basename(b),
                                       'status': 'success'} for a, b in pairs]
                return result
            os.rename(old, new)
            result.update(status='success', message='Renamed')
            for src_path, dst in pairs:
                entry = {'old': os.path.basename(src_path), 'new': os.path.basename(dst)}
                try:
                    if os.path.lexists(src_path) and not os.path.lexists(dst):
                        os.rename(src_path, dst)
                        entry['status'] = 'success'
                    else:
                        entry['status'] = 'failed'
                        entry['error'] = 'Not there any more, or its new name is taken'
                except OSError as error:
                    entry['status'] = 'failed'
                    entry['error'] = str(error)
                result['sidecars'].append(entry)
            return result
        except PathTraversalError as error:
            result.update(message='Path rejected', error=str(error))
            return result
        except PermissionError as error:
            result.update(message='Permission denied', error=str(error))
            return result
        except OSError as error:
            result.update(message=f"Could not rename: {error.strerror or error}", error=str(error))
            return result

    def _ask_sonarr(self, src: _Sources, done: List[Dict[str, Any]],
                    dry_run: bool) -> Dict[str, Any]:
        """Have Sonarr rename the copies it holds of what was just renamed here."""
        files = sorted({r['sonarr_file_id'] for r in done if r.get('sonarr_file_id')})
        if not files:
            return {'asked': False, 'ok': None, 'files': 0, 'message': ''}
        if dry_run:
            return {'asked': False, 'ok': None, 'files': len(files),
                    'message': f"Test mode: Sonarr was not asked to rename its {len(files)} "
                               'copy/copies'}
        adapter = self._sonarr()
        if adapter is None or src.series is None:
            return {'asked': False, 'ok': False, 'files': len(files),
                    'message': 'Sonarr is not connected, so its copies keep their old names'}
        sent, answer, words = self._paced(
            adapter.command, 'RenameFiles',
            {'seriesId': src.series.get('id'), 'files': files})
        if not sent:
            return {'asked': True, 'ok': False, 'files': len(files),
                    'message': f"Sonarr did not take the rename: {words}"}
        return {'asked': True, 'ok': True, 'files': len(files),
                'command_id': (answer or {}).get('id'),
                'message': f"Sonarr is renaming its {len(files)} copy/copies"}

    def _record(self, media_type: str, folder: str, src: _Sources,
                results: List[Dict[str, Any]], sonarr: Dict[str, Any], trigger: str,
                actor: Optional[str], dry_run: bool, announce: bool = True) -> Dict[str, Any]:
        success = sum(1 for r in results if r['status'] == 'success')
        failed = len(results) - success
        status = 'completed' if failed == 0 else ('failed' if success == 0 else 'partial')
        notification_id = f"rename_{trigger}_{int(time.time() * 1000)}"
        title = (src.series or {}).get('title') or folder
        stored = [{k: v for k, v in r.items() if k != 'key'} for r in results]
        lines = [(f"{'🧪' if dry_run else '✅'} {r['previous_name']} → {r['new_name']}"
                  if r['status'] == 'success'
                  else f"❌ {r['previous_name']}: {r['message']}") for r in results]
        if sonarr.get('message'):
            lines.append(sonarr['message'])
        root = self.config.get(LIBRARIES[media_type]) or ''
        data = {
            'notification_id': notification_id,
            'media_type': media_type,
            'series_title': title,
            'series_id': (src.series or {}).get('id'),
            'series_path': os.path.join(root, folder),
            'renamed_files': stored,
            'total_files': len(results),
            'success_count': success,
            'failed_count': failed,
            'status': status,
            'error_message': '\n'.join(lines),
            'trigger_kind': trigger,
            'triggered_by': actor,
            'sonarr_message': sonarr.get('message') or None,
        }
        self.rename_model.create(data)
        self.rename_model.update(notification_id, {'completed_at': datetime.now().isoformat()})

        result = {
            'notification_id': notification_id,
            'series_title': title,
            'folder': folder,
            'media_type': media_type,
            'status': status,
            'total_files': len(results),
            'success_count': success,
            'failed_count': failed,
            'renamed_files': stored,
            'sidecar_count': sum(len(r['sidecars']) for r in results),
            'sonarr': sonarr,
            'dry_run': dry_run,
            'trigger_kind': trigger,
            'message': _result_message(title, success, failed, dry_run),
        }
        # Rename all reports once, when it finishes, not once per series.
        if announce and self.socketio is not None:
            try:
                self.socketio.emit('rename_completed', result)
            except Exception:  # noqa: BLE001
                pass
        if announce and self.notification_service is not None and not dry_run:
            self.notification_service.send_rename_discord_notification(result)
        return result

    # ==================================================================
    # Undo
    # ==================================================================

    def undo(self, notification_id: str, actor: Optional[str] = None) -> Dict[str, Any]:
        """Put the names of one rename run back. Sonarr's copies keep their new names."""
        row = self.rename_model.get(notification_id)
        if not row:
            raise RenamesError('That rename is not in the history', 404)
        if row.get('undone_at'):
            raise RenamesError('That rename was already undone', 409)
        files = [f for f in row.get('renamed_files') or []
                 if f.get('status') == 'success' and not f.get('dry_run')
                 and f.get('local_previous_path') and f.get('local_new_path')]
        if not files:
            raise RenamesError('Nothing in that rename changed a file, so there is nothing to '
                               'put back', 400)
        media_type = row.get('media_type')
        root = self.config.get(LIBRARIES.get(media_type, '')) if media_type in LIBRARIES else None
        if not root:
            raise RenamesError('That library is not configured here', 409)
        folder = os.path.basename(str(row.get('series_path') or '').rstrip('/'))
        blocker = self._blocker(media_type, folder)
        if blocker:
            raise RenamesError(blocker, 409)

        dry_run = test_mode_enabled()
        restored, failed = [], []
        for info in files:
            new, old = info['local_new_path'], info['local_previous_path']
            local_new = self._local_twin(root, row, new)
            local_old = self._local_twin(root, row, old)
            try:
                assert_path_within_bounds(local_new, [root])
                assert_path_within_bounds(local_old, [root])
                if os.path.dirname(local_new) != os.path.dirname(local_old):
                    raise OSError('the two names are in different folders')
                if not os.path.lexists(local_new):
                    raise OSError('the renamed file is no longer there')
                if os.path.lexists(local_old):
                    raise OSError('a file with the old name is back already')
                if not dry_run:
                    os.rename(local_new, local_old)
                    directory = os.path.dirname(local_old)
                    for sidecar in info.get('sidecars') or []:
                        if sidecar.get('status') != 'success':
                            continue
                        a = os.path.join(directory, sidecar['new'])
                        b = os.path.join(directory, sidecar['old'])
                        if os.path.lexists(a) and not os.path.lexists(b):
                            os.rename(a, b)
                    self._forget_tmdb_title(media_type, folder, info)
                restored.append(info.get('previous_name'))
            except (OSError, PathTraversalError) as error:
                failed.append({'name': info.get('new_name'), 'error': str(error)})

        if not dry_run and restored:
            self.rename_model.update(notification_id, {'undone_at': datetime.now().isoformat()})
            try:
                if folder:
                    self.check_folder(media_type, folder)
            except Exception:  # noqa: BLE001
                pass
        sonarr_renamed = any(f.get('sonarr_rename') for f in files) or \
            (row.get('trigger_kind') in (None, 'webhook'))
        return {
            'notification_id': notification_id,
            'restored_count': len(restored),
            'failed': failed,
            'dry_run': dry_run,
            'message': (
                ('Test mode: nothing was put back. Would have restored '
                 if dry_run else 'Put back ')
                + f"{len(restored)} name(s)"
                + (f"; {len(failed)} could not be" if failed else '')
                + ('. Sonarr’s copy keeps its new name.' if sonarr_renamed and restored else '.')
            ),
        }

    def _local_twin(self, root: str, row: Dict[str, Any], path: str) -> str:
        """A path a rename recorded, as it is on this disk."""
        if path.startswith(root.rstrip('/') + '/'):
            return path
        # A webhook run records the server's path; its last three parts are the
        # series, season and file here.
        parts = [p for p in path.replace('\\', '/').split('/') if p]
        return os.path.join(root, *parts[-3:])

    def _forget_tmdb_title(self, media_type: str, folder: str, info: Dict[str, Any]) -> None:
        code = info.get('code') or ''
        if info.get('source') != SOURCE_TMDB or not code.startswith('S') or 'E' not in code:
            return
        try:
            season, episode = code[1:].split('E', 1)
            self.store.forget_title(media_type, folder, int(season), int(episode))
        except ValueError:
            pass

    # ==================================================================
    # the title check
    # ==================================================================

    def check_folder(self, media_type: str, folder: str) -> Dict[str, Any]:
        """Check one series' titles and store the answer for Explore to show."""
        _root, items, src = self._build(media_type, folder, None, full=False)
        if not items:
            # Kept, at zero, rather than deleted: Explore's tags come from the
            # last walk of the library until the next one, and this row is what
            # says the TBA files have gone in the meantime.
            summary = {'folder': folder, 'state': 'clear', 'placeholders': 0, 'ready': 0,
                       'waiting': 0, 'skipped': 0, 'message': ''}
            self.store.save_check(media_type, folder, summary, {'items': {}, 'seasons': {}})
            return summary
        summary = self._summary(folder, items, src)
        detail = {
            'items': {i['path']: {k: i[k] for k in ('code', 'season_folder', 'old_name',
                                                    'new_name', 'state', 'reason', 'source',
                                                    'retitle')}
                      for i in items},
            'seasons': {},
            'sonarr': self._sonarr_summary(src),
            'tmdb': self._tmdb_summary(src),
        }
        for item in items:
            season = detail['seasons'].setdefault(item['season_folder'],
                                                  {READY: 0, WAITING: 0, SKIPPED: 0})
            season[item['state']] += 1
        self.store.save_check(media_type, folder, summary, detail)
        return summary

    @staticmethod
    def _summary(folder: str, items: List[Dict[str, Any]], src: _Sources) -> Dict[str, Any]:
        ready = sum(1 for i in items if i['state'] == READY)
        waiting = sum(1 for i in items if i['state'] == WAITING)
        skipped = sum(1 for i in items if i['state'] == SKIPPED)
        if ready:
            state = READY
        elif src.sonarr_state == 'missing' and src.tmdb_state != 'linked':
            state = 'not_in_sonarr'
        elif src.sonarr_state in ('unavailable', 'off'):
            state = 'unknown'
        else:
            state = WAITING
        return {
            'folder': folder, 'state': state,
            'placeholders': sum(1 for i in items if not i['retitle']),
            'ready': ready, 'waiting': waiting, 'skipped': skipped,
            'sonarr_series_id': (src.series or {}).get('id'),
            'message': RenamesService._sonarr_summary(src)['message'],
        }

    def folders_to_check(self, media_type: str) -> List[str]:
        """Series folders here with a TBA episode, or one named from TMDB."""
        root = self._root(media_type)
        inventory = LocalInventory().read(media_type, root)
        folders = {e.series for e in inventory.files
                   if e.series and e.is_media and not e.misplaced
                   and naming.is_placeholder(e.name)}
        for folder in self.store.tmdb_titled_folders(media_type):
            if os.path.isdir(os.path.join(root, folder)):
                folders.add(folder)
        return sorted(folders)

    def check_all(self, trigger: str = 'manual',
                  media_types: Sequence[str] = tuple(LIBRARIES)) -> Dict[str, Any]:
        """The title check across the libraries: the scheduler's job and the button."""
        if not self._check_lock.acquire(blocking=False):
            return {'ok': True, 'summary': 'A title check is already running', 'busy': True}
        try:
            totals = {READY: 0, WAITING: 0, 'series': 0, 'new_ready': 0}
            fresh: List[Tuple[str, str, int]] = []
            for media_type in media_types:
                if not self.config.get(LIBRARIES[media_type]):
                    continue
                folders = self.folders_to_check(media_type)
                previous = {row['folder']: row for row in self.store.checks(media_type)}
                for folder in folders:
                    try:
                        summary = self.check_folder(media_type, folder)
                    except RenamesError:
                        continue
                    totals['series'] += 1
                    totals[READY] += summary.get(READY, 0)
                    totals[WAITING] += summary.get(WAITING, 0)
                    told = (previous.get(folder) or {}).get('notified_ready') or 0
                    if summary.get(READY, 0) > told:
                        totals['new_ready'] += summary[READY] - told
                        fresh.append((media_type, folder, summary[READY]))
                self.store.forget_checks_except(media_type, folders)
            if trigger == 'scheduled' and fresh:
                self._tell(fresh, totals)
            self._emit('titles_checked', {'trigger': trigger, **totals})
            sentence = (f"{totals[READY]} episode(s) in {totals['series']} series can get "
                        f"their real titles; {totals[WAITING]} still waiting")
            return {'ok': True, 'summary': sentence, **totals}
        finally:
            self._check_lock.release()

    def _tell(self, fresh: List[Tuple[str, str, int]], totals: Dict[str, int]) -> None:
        """An alert and a Discord message when the check found titles to rename."""
        count = sum(n for _mt, _f, n in fresh)
        names = ', '.join(folder for _mt, folder, _n in fresh[:4])
        if len(fresh) > 4:
            names += f" and {len(fresh) - 4} more"
        message = (f"{count} episode(s) still named TBA can get their real titles: {names}. "
                   'Open Explore, filter by Needs titles, and press Rename. Nothing is '
                   'renamed by itself.')
        media_type = fresh[0][0]
        if self.alerts is not None:
            self.alerts.raise_alert(
                'titles_ready', f"Titles ready to rename: {count} episode(s)", message,
                'info', dedupe_key='titles_ready',
                link=f"/media/{media_type}?filter=titles",
                data={'explore': {'media_type': media_type, 'series': fresh[0][1],
                                  'filter': 'titles'}})
        try:
            from services.connectors import notify
            from services.connectors.events import Event, Field, headline
            notify(Event(
                key='titles.ready', severity='info',
                title=f"{count} episode(s) can get their real titles",
                summary=message,
                fields=tuple(Field(f"{LABELS.get(mt, mt)}", f"{folder}: {n} ready")
                             for mt, folder, n in fresh[:8]),
                author=headline('Renames', 'titles ready'),
            ))
        except Exception:  # noqa: BLE001 - a message must not stop the check
            pass
        for media_type, folder, ready in fresh:
            self.store.mark_notified(media_type, folder, ready)

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        if self.socketio is None:
            return
        try:
            self.socketio.emit(event, payload)
        except Exception:  # noqa: BLE001
            pass

    def scheduler_job(self):
        from services.scheduler import Job
        return Job(
            name='title_check', label='Title check',
            description=('Looks for real titles for episodes still named TBA, in Sonarr and '
                         'on TMDB, and tells you when some can be renamed. Never renames by '
                         'itself.'),
            interval=lambda: (self.title_check_hours() * 3600) or None,
            run=lambda: self.check_all(trigger='scheduled'),
            first_run_delay=300.0,
        )

    # ==================================================================
    # refresh, and the whole library
    # ==================================================================

    def refresh(self, media_type: str, folder: str) -> Dict[str, Any]:
        """Ask Sonarr to fetch fresh titles for a series, then check again."""
        self._local(media_type, folder)
        adapter = self._sonarr()
        if adapter is None:
            summary = self.check_folder(media_type, folder)
            return {'asked_sonarr': False, 'message': 'Checked TMDB again', 'summary': summary}
        ok, rows = self._series_list(adapter)
        series = self._match_series(rows, folder) if ok else None
        if series is None:
            summary = self.check_folder(media_type, folder)
            return {'asked_sonarr': False, 'message': 'Not in Sonarr. Checked TMDB again',
                    'summary': summary}
        sent, answer, words = self._paced(adapter.command, 'RefreshSeries',
                                          {'seriesId': series.get('id')})
        if not sent:
            summary = self.check_folder(media_type, folder)
            return {'asked_sonarr': False, 'message': f"{words}. Checked again with what "
                                                      'Sonarr has now', 'summary': summary}
        command_id = (answer or {}).get('id')
        threading.Thread(target=self._after_refresh, args=(adapter, command_id, media_type,
                                                           folder),
                         daemon=True, name='title-refresh').start()
        return {'asked_sonarr': True, 'message': 'Sonarr is fetching fresh titles. This '
                                                 'checks again when it is done.'}

    def _after_refresh(self, adapter, command_id, media_type: str, folder: str) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            self._sleep(4)
            status = self._paced(adapter.command_status, command_id)
            if status in ('completed', 'failed', 'aborted', 'cancelled', None):
                break
        try:
            summary = self.check_folder(media_type, folder)
        except Exception:  # noqa: BLE001
            summary = {}
        self._emit('titles_checked', {'trigger': 'refresh', 'media_type': media_type,
                                      'folder': folder, **summary})

    def library_status(self, media_type: str) -> Dict[str, Any]:
        """Every checked series of one library, for Explore's tree and strip."""
        if media_type not in LIBRARIES:
            return {}
        rows = self.store.checks(media_type)
        out: Dict[str, Any] = {}
        for row in rows:
            detail = row.get('detail') or {}
            out[row['folder']] = {
                'state': row['state'], 'ready': row['ready'], 'waiting': row['waiting'],
                'skipped': row['skipped'], 'placeholders': row['placeholders'],
                'checked_at': row['checked_at'], 'message': row['message'],
                'seasons': detail.get('seasons') or {},
                'tmdb': detail.get('tmdb') or {},
                'sonarr': detail.get('sonarr') or {},
            }
        return out

    def season_titles(self, media_type: str, folder: str,
                      season: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """{file name: what the last check proposed} for one season or series."""
        row = self.store.check(media_type, folder)
        if not row:
            return {}
        out = {}
        for path, item in ((row.get('detail') or {}).get('items') or {}).items():
            if season and item.get('season_folder') != season:
                continue
            out[item.get('old_name') or path] = item
        return out

    def plan_library(self, media_type: str) -> Dict[str, Any]:
        """What Rename all ready would do, from the last title check. Asks nothing."""
        self._root(media_type)
        series = []
        for row in self.store.checks(media_type):
            items = [i for i in ((row.get('detail') or {}).get('items') or {}).values()
                     if i.get('state') == READY]
            if items:
                series.append({'folder': row['folder'], 'checked_at': row['checked_at'],
                               'items': sorted(items, key=lambda i: i.get('code') or '')})
        series.sort(key=lambda s: s['folder'])
        return {
            'media_type': media_type,
            'series': series,
            'files': sum(len(s['items']) for s in series),
            'running': self._library_runs.get(media_type, {}).get('running', False),
            'test_mode': test_mode_enabled(),
        }

    def apply_library(self, media_type: str, folders: Sequence[str],
                      actor: Optional[str] = None) -> Dict[str, Any]:
        """Rename every ready episode in the chosen series, one series at a time."""
        self._root(media_type)
        chosen = [f for f in folders if isinstance(f, str) and validate_path_component(f)]
        if not chosen:
            raise RenamesError('Pick at least one series', 400)
        run = self._library_runs.get(media_type)
        if run and run.get('running'):
            raise RenamesError('Rename all is already running for this library', 409)
        run = {'running': True, 'done': 0, 'total': len(chosen), 'results': []}
        self._library_runs[media_type] = run
        threading.Thread(target=self._run_library, args=(media_type, chosen, actor, run),
                         daemon=True, name='rename-library').start()
        return {'started': True, 'total': len(chosen)}

    def _run_library(self, media_type: str, folders: Sequence[str], actor: Optional[str],
                     run: Dict[str, Any]) -> None:
        try:
            for folder in folders:
                outcome: Dict[str, Any] = {'folder': folder}
                try:
                    result = self.apply(media_type, folder, actor=actor, trigger='manual',
                                        announce=False)
                    run.setdefault('files', []).extend(result['renamed_files'])
                    outcome.update(ok=True, renamed=result['success_count'],
                                   failed=result['failed_count'],
                                   notification_id=result['notification_id'],
                                   sonarr=result['sonarr'].get('message'))
                except RenamesError as error:
                    outcome.update(ok=False, message=error.message)
                except Exception as error:  # noqa: BLE001 - one series must not stop the rest
                    outcome.update(ok=False, message=str(error))
                run['done'] += 1
                run['results'].append(outcome)
                self._emit('rename_progress', {'media_type': media_type, 'done': run['done'],
                                               'total': run['total'], 'last': outcome})
        finally:
            run['running'] = False
            renamed = sum(o.get('renamed') or 0 for o in run['results'])
            failed = sum(o.get('failed') or 0 for o in run['results'])
            if renamed and self.notification_service is not None and not test_mode_enabled():
                # One message for the whole run, not one per series.
                self.notification_service.send_rename_discord_notification({
                    'series_title': f"{LABELS.get(media_type, media_type)}: "
                                    f"{len(run['results'])} series",
                    'media_type': media_type,
                    'total_files': renamed + failed,
                    'success_count': renamed,
                    'failed_count': failed,
                    'status': 'completed' if not failed else 'partial',
                    'renamed_files': run.get('files') or [],
                })
            self._emit('rename_library_finished', {
                'media_type': media_type, 'renamed': renamed,
                'series': len(run['results']),
                'failed': [o for o in run['results'] if not o.get('ok') or o.get('failed')],
                'dry_run': test_mode_enabled(),
            })

    # ==================================================================
    # TMDB links for series Sonarr does not have
    # ==================================================================

    def tmdb_search(self, media_type: str, folder: str, query: Optional[str] = None
                    ) -> Dict[str, Any]:
        self._local(media_type, folder)
        client = self._tmdb()
        if client is None:
            raise RenamesError('No TMDB key is set. Add one on Sonarr’s Connection tab.', 409)
        wanted = (query or '').strip() or _strip_year(folder)
        ok, rows, words = client.search(wanted, None if query else year_of(folder))
        if ok and not rows and not query and year_of(folder):
            ok, rows, words = client.search(wanted)
        if not ok:
            raise RenamesError(words or 'TMDB did not answer', 502)
        link = self.store.link(media_type, folder)
        return {'query': wanted, 'results': rows, 'linked': link}

    def tmdb_link(self, media_type: str, folder: str, tmdb_id: Any,
                  actor: Optional[str] = None) -> Dict[str, Any]:
        self._local(media_type, folder)
        client = self._tmdb()
        if client is None:
            raise RenamesError('No TMDB key is set. Add one on Sonarr’s Connection tab.', 409)
        try:
            tmdb_id = int(tmdb_id)
        except (TypeError, ValueError):
            raise RenamesError('Pick a show from the list', 400)
        show = client.show(tmdb_id)
        if show is None:
            raise RenamesError('TMDB has no such show', 404)
        self.store.save_link(media_type, folder, tmdb_id, show.get('name') or '',
                             show.get('year'), source='manual', linked_by=actor)
        summary = self.check_folder(media_type, folder)
        return {'linked': self.store.link(media_type, folder), 'summary': summary}

    def tmdb_unlink(self, media_type: str, folder: str) -> Dict[str, Any]:
        self._local(media_type, folder)
        removed = self.store.remove_link(media_type, folder)
        summary = self.check_folder(media_type, folder)
        return {'removed': removed, 'summary': summary}


def _day(value: Any) -> Optional[date]:
    text = str(value or '')[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _strip_year(folder: str) -> str:
    import re
    return re.sub(r'\s*\(\d{4}\)\s*$', '', folder or '').strip()


def _result_message(title: str, success: int, failed: int, dry_run: bool) -> str:
    if dry_run:
        return f"Test mode: nothing was renamed. Would have renamed {success} file(s) in {title}"
    if failed == 0:
        return f"Renamed {success} file(s) in {title}"
    if success == 0:
        return f"Could not rename {failed} file(s) in {title}"
    return f"Renamed {success} of {success + failed} file(s) in {title}; {failed} could not be"


def _default_connectors():
    from services.connectors import get_service
    return get_service()
