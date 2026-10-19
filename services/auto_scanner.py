#!/usr/bin/env python3
"""
The scheduled auto-scanner: what a webhook never delivered.

A webhook is the only thing that starts an automatic sync, which makes a lost
one a silent, total failure — DragonCP restarting, a network blip, an error
inside Sonarr, and the episode sits on the media server until somebody looks.
The scanner asks the service instead, on a schedule (decided 2026-10-02):

  * **What did you import since the last scan?** Sonarr's and Radarr's own
    history — new episodes, new titles, upgrades. Anything nothing has synced
    since it was imported is a find.
  * **Which seasons are short here?** For titles this disk already keeps, a
    season holding fewer files than the service has. That is a missing episode,
    whatever the reason.

Titles this disk has never held are only fetched when the service imports
something for them. The service's whole backlog is not a gap: plenty of
libraries keep a subset here on purpose, and a scanner that fetched everything
it could see would fill the disk five titles at a time.

Every find goes through the sync engine as an `auto_scanner` sync, so the batch
check (no duplicates), Sonarr's ready check and the safety check all apply.
The scanner itself only decides what to ask for. One switch per service, on its
integration page, off by default.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from activity_log import record
from actor import AUTO_SCANNER, acting_as
from models.media_item import SOURCE_RADARR, SOURCE_SONARR
from models.sync_run import utc_now
from services.sync_engine import stages as S
from services.sync_engine.coverage import last_copies
from services.sync_engine.units import unit_key

log = logging.getLogger('dragoncp.auto_scanner')

#: New runs one scan may open, per service. A first scan of a library that has
#: never been reconciled can find a great deal at once; a safety net that starts
#: all of it is a stampede. The rest is found again next scan.
MAX_NEW_RUNS_PER_SCAN = 5

#: Runs opened for the same gap before the scanner stops retrying it by itself.
#: A gap that survives two attempts is not going to close on a third — it waits
#: for a person, through an alert.
MAX_ATTEMPTS = 2

#: How far back the history is read when this service has never been scanned.
FIRST_SCAN_LOOKBACK = timedelta(hours=24)

LAST_SCAN_KEY = 'AUTO_SCANNER_LAST_SCAN_{source}'

_LIBRARY_ROOTS = {
    'movies': ('MOVIE_PATH', 'MOVIE_DEST_PATH'),
    'tvshows': ('TVSHOW_PATH', 'TVSHOW_DEST_PATH'),
    'anime': ('ANIME_PATH', 'ANIME_DEST_PATH'),
}


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _season_folder_here(item: Dict[str, Any], season: int) -> Optional[str]:
    """The folder this disk keeps a season in, as the library view found it."""
    for entry in item.get('seasons') or []:
        if entry.get('season_number') == season:
            return entry.get('folder_here') or None
    return None


@dataclass
class Find:
    """One thing the scanner thinks needs syncing, and why."""

    source: str
    external_id: str
    title: str
    media_type: str
    source_path: str
    dest_path: str
    folder: str
    season_number: Optional[int] = None
    season_name: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    #: For the Receive stage: "found 2 episode files missing here".
    finding: str = ''
    #: When the service imported it; None for a gap found by comparing libraries.
    imported_at: Optional[datetime] = None

    @property
    def key(self) -> str:
        return unit_key(self.dest_path)

    @property
    def label(self) -> str:
        return f"{self.title} — {self.season_name}" if self.season_name else self.title

    def as_dict(self) -> Dict[str, Any]:
        return {'source': self.source, 'external_id': self.external_id, 'title': self.title,
                'media_type': self.media_type, 'source_path': self.source_path,
                'dest_path': self.dest_path, 'folder_name': self.folder,
                'season_number': self.season_number, 'season_name': self.season_name,
                'reasons': list(self.reasons), 'label': self.label}


class AutoScanner:
    """Finds what the services have and this disk does not, and hands it to the engine."""

    def __init__(self, db_manager, media_index, engine, config, alerts=None,
                 clock=time.time):
        self.db = db_manager
        self.index = media_index
        self.engine = engine
        self.config = config
        self.alerts = alerts
        self.clock = clock
        self._last: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------ the switch

    def _adapter(self, source: str):
        try:
            return self.index._adapter(source)
        except Exception:  # noqa: BLE001
            return None

    def interval_seconds(self, source: str) -> Optional[float]:
        """The scheduler's question: how often, or None when switched off."""
        adapter = self._adapter(source)
        if adapter is None or not getattr(adapter, 'auto_scanner_enabled', None):
            return None
        if not adapter.auto_scanner_enabled():
            return None
        return adapter.auto_scanner_interval_minutes() * 60.0

    def jobs(self):
        """The two scheduler entries this scanner provides."""
        from services.scheduler import Job
        return [
            Job(name=f"{source}_auto_scanner",
                label=f"{source.title()} auto-scanner",
                description=(f"Asks {source.title()} what it imported and syncs anything "
                             f"this disk does not have yet."),
                interval=(lambda s=source: self.interval_seconds(s)),
                run=(lambda s=source: self.scan(s)),
                first_run_delay=60.0)
            for source in (SOURCE_SONARR, SOURCE_RADARR)
        ]

    # ------------------------------------------------------------------ scan

    def scan(self, source: str) -> Dict[str, Any]:
        """One scan of one service. The scheduler's job; never raises past here."""
        with acting_as(AUTO_SCANNER):
            result = self._scan(source)
        self._last[source] = result
        return result

    def last_scan(self, source: Optional[str] = None) -> Dict[str, Any]:
        if source:
            return dict(self._last.get(source) or {})
        return {k: dict(v) for k, v in self._last.items()}

    def _scan(self, source: str) -> Dict[str, Any]:
        name = source.title()
        started = utc_now()
        adapter = self._adapter(source)
        if adapter is None:
            return {'ok': True, 'skipped': True,
                    'summary': f"{name} is not connected, so there was nothing to scan."}

        try:
            check = adapter.check()
        except Exception as error:  # noqa: BLE001
            check = None
            message = str(error)
        else:
            message = check.message
        if check is None or not check.ok:
            return {'ok': False, 'summary': f"{name} did not answer: {message}"}

        view = self.index.library_view(source, refresh=True)
        if not view.get('live'):
            return {'ok': False, 'summary': f"{name} did not send its library."}

        since = self._last_scan_at(source) or (started - FIRST_SCAN_LOOKBACK)
        finds: Dict[str, Find] = {}
        imported, history_ok = self._from_history(source, adapter, view, since)
        for find in imported:
            self._merge(finds, find)
        for find in self._from_library(source, view, adapter):
            self._merge(finds, find)

        decisions = self._act(source, list(finds.values()))

        started_runs = [d for d in decisions if d['action'] == 'started']
        on_the_way = [d for d in decisions if d['action'] == 'already_on_its_way']
        held = [d for d in decisions if d['action'] == 'held_back']
        # The history window only moves on once everything in it was handled.
        # A find held back by the per-scan limit, or one a copy already under
        # way may have missed, would otherwise drop out of the window and never
        # be seen again; read from the same point next time, and the ones
        # already started are recognised as on their way.
        if history_ok and not held and not any(d.get('recheck') for d in decisions):
            self._set_last_scan_at(source, started)
        given_up = [d for d in decisions if d['action'] == 'needs_a_person']
        failed = [d for d in decisions if d['action'] == 'failed']

        summary = (f"Checked {view.get('total', 0)} {name} title(s): "
                   f"{len(finds)} to sync — {len(started_runs)} started, "
                   f"{len(on_the_way)} already on their way, {len(held)} held back for "
                   f"the next scan, {len(given_up)} waiting for a person.")
        if not finds:
            summary = (f"Checked {view.get('total', 0)} {name} title(s): everything it "
                       f"imported is here.")
        if not history_ok:
            summary += f" {name}'s history could not be read; only the library was compared."

        record('scanner.run', summary, target_type='connector', target_id=source,
               detail={'finds': [d['find'] for d in decisions], 'since': since.isoformat()})
        if started_runs:
            self._announce(source, started_runs, held)
        log.info('Auto-scanner · %s · %s', name, summary)
        return {'ok': True, 'summary': summary, 'source': source,
                'found': len(finds), 'started': len(started_runs),
                'already_on_its_way': len(on_the_way), 'held_back': len(held),
                'needs_a_person': len(given_up), 'failed': len(failed),
                'since': since.isoformat(), 'decisions': decisions}

    @staticmethod
    def _merge(finds: Dict[str, Find], find: Find) -> None:
        existing = finds.get(find.key)
        if existing is None:
            finds[find.key] = find
        else:
            existing.reasons.extend(r for r in find.reasons if r not in existing.reasons)

    # ------------------------------------------------------- what to look at

    def _from_history(self, source: str, adapter, view: Dict[str, Any],
                      since: datetime) -> Tuple[List[Find], bool]:
        """Imports since the last scan that nothing has synced since."""
        ok, records = adapter.imports_since(since.isoformat())
        if not ok:
            return [], False
        by_service_id = {str(i.get('service_item_id')): i for i in view.get('items', [])
                         if i.get('service_item_id') not in (None, '')}

        latest: Dict[Tuple[str, Optional[int]], Tuple[datetime, Dict[str, Any]]] = {}
        for entry in records:
            moment = _parse(entry.get('date'))
            if moment is None:
                continue
            if source == SOURCE_SONARR:
                service_id = entry.get('seriesId')
                season = (entry.get('episode') or {}).get('seasonNumber')
                if season is None or season == 0:
                    continue
            else:
                service_id = entry.get('movieId')
                season = None
            if service_id in (None, ''):
                continue
            key = (str(service_id), season)
            if key not in latest or moment > latest[key][0]:
                latest[key] = (moment, entry)

        out: List[Find] = []
        for (service_id, season), (moment, entry) in latest.items():
            item = by_service_id.get(service_id)
            if item is None:
                continue
            find = self._find_for(source, item, season, adapter)
            if find is None or self._synced_since(find.dest_path, moment):
                continue
            find.imported_at = moment
            when = moment.astimezone().strftime('%Y-%m-%d %H:%M')
            what = (f"season {season}" if season is not None else 'the movie')
            find.reasons.append(f"{source.title()} imported {what} at {when}, and nothing "
                                f"has synced it since.")
            find.finding = f"found an import from {when} that was never synced"
            out.append(find)
        return out, True

    def _from_library(self, source: str, view: Dict[str, Any], adapter) -> List[Find]:
        """Seasons this disk keeps that hold fewer episodes than the service has."""
        if source != SOURCE_SONARR:
            return []
        out: List[Find] = []
        for item in view.get('items', []):
            if not item.get('present_locally') or not item.get('service_has_files'):
                continue
            for season in item.get('seasons') or []:
                if not season.get('counts_towards_state'):
                    continue
                # Episodes on both sides: Sonarr counts every episode a file
                # holds, so one double-episode file is two of its episodes.
                theirs = season.get('episode_file_count') or 0
                ours = season.get('episodes_here', season.get('files_here')) or 0
                if ours == 0 or ours >= theirs:
                    # A season this disk does not keep at all is not a gap: it
                    # is fetched when the service imports something for it.
                    continue
                find = self._find_for(source, item, season['season_number'], adapter)
                if find is None:
                    continue
                find.reasons.append(f"{source.title()} has files for {theirs} episode(s) of "
                                    f"season {season['season_number']}; this disk has {ours}.")
                find.finding = f"found {theirs - ours} episode(s) missing here"
                out.append(find)
        return out

    def _find_for(self, source: str, item: Dict[str, Any], season: Optional[int],
                  adapter) -> Optional[Find]:
        """The folders one title (and season) would be copied between."""
        service_path = item.get('service_path') or ''
        media_type = item.get('media_type') or self._library_of(service_path) or (
            'movies' if source == SOURCE_RADARR else '')
        remote_root, local_root = self._roots(media_type)
        if not remote_root or not local_root or not service_path:
            return None
        if not service_path.rstrip('/').startswith(remote_root + '/'):
            # The boundary: an address the service supplied is not a reason to
            # read somewhere this installation was not configured to read.
            return None
        remote_folder = os.path.basename(service_path.rstrip('/'))
        local_folder = item.get('local_folder') or remote_folder
        source_path = f"{remote_root}/{remote_folder}"
        dest_path = f"{local_root}/{local_folder}"
        season_name = None
        if season is not None:
            folder_name = None
            if adapter is not None and item.get('service_item_id'):
                try:
                    folder_name = adapter.season_folder(item['service_item_id'], season)
                except Exception:  # noqa: BLE001
                    folder_name = None
            season_name = folder_name or f"Season {int(season):02d}"
            source_path = f"{source_path}/{season_name}"
            # Into the folder this disk already keeps the season in, whatever
            # it is called: a rebuilt name would start a second one beside it.
            dest_path = f"{dest_path}/{_season_folder_here(item, season) or season_name}"
        return Find(source=source, external_id=str(item.get('external_id') or ''),
                    title=item.get('title') or local_folder, media_type=media_type,
                    source_path=source_path, dest_path=dest_path, folder=local_folder,
                    season_number=season, season_name=season_name)

    def _roots(self, media_type: str) -> Tuple[str, str]:
        keys = _LIBRARY_ROOTS.get(media_type)
        if not keys or self.config is None:
            return '', ''
        try:
            return ((self.config.get(keys[0]) or '').rstrip('/'),
                    (self.config.get(keys[1]) or '').rstrip('/'))
        except Exception:  # noqa: BLE001
            return '', ''

    def _library_of(self, service_path: str) -> str:
        if not service_path:
            return ''
        for media_type in ('movies', 'tvshows', 'anime'):
            remote_root, _ = self._roots(media_type)
            if remote_root and service_path.rstrip('/').startswith(remote_root + '/'):
                return media_type
        return ''

    def _synced_since(self, dest_path: str, imported_at: datetime) -> bool:
        """Whether a copy that started after the import has finished.

        Started, not finished: a copy lists the folder when it starts, so one
        that began before the import may have missed it however late it ended.
        """
        key = unit_key(dest_path)
        copied = last_copies(self.db, key).get(key)
        return copied is not None and copied >= imported_at

    @staticmethod
    def _copy_may_miss(live: Dict[str, Any], find: Find) -> bool:
        """A copy that began before the import may not have picked it up."""
        if find.imported_at is None or live.get('state') not in S.ACTIVE_STATES:
            return False
        # A resumed copy lists the folder again, so the latest start counts.
        began = _parse((live.get('options') or {}).get('transfer_started_at')
                       or live.get('started_at'))
        return began is None or began < find.imported_at

    # --------------------------------------------------------------- acting

    def _act(self, source: str, finds: List[Find]) -> List[Dict[str, Any]]:
        from services.sync_engine.engine import SyncRequest
        decisions: List[Dict[str, Any]] = []
        seen = set()
        opened = 0
        for find in finds:
            seen.add((find.external_id, find.season_number))
            memory = self._remember(find)
            decision = {'find': find.as_dict(), 'action': '', 'run_id': None, 'detail': ''}

            live = self.engine.store.find_live(find.key)
            if live is not None:
                decision['action'] = 'already_on_its_way'
                if self._copy_may_miss(live, find):
                    # Whether this copy caught the import is not known until it
                    # ends, so the next scan reads the same history again.
                    decision['recheck'] = True
                    decision['detail'] = 'copying since before the import; checked again next scan'
                decisions.append(decision)
                continue

            attempts = memory.get('sync_attempts') or 0
            if attempts >= MAX_ATTEMPTS:
                decision['action'] = 'needs_a_person'
                decision['detail'] = f"tried {attempts} times"
                if self.alerts is not None:
                    self.alerts.scanner_gap(source, find.label, find.as_dict(),
                                            ' '.join(find.reasons))
                decisions.append(decision)
                continue

            if opened >= MAX_NEW_RUNS_PER_SCAN:
                decision['action'] = 'held_back'
                decision['detail'] = 'held back until the next scan'
                decisions.append(decision)
                continue

            options = {'finding': find.finding or 'found a gap',
                       'reasons': list(find.reasons)}
            options['tvdb_id' if source == SOURCE_SONARR else 'tmdb_id'] = find.external_id
            result = self.engine.submit(SyncRequest(
                kind=S.AUTO_SCANNER, source=source, media_type=find.media_type,
                source_path=find.source_path, dest_path=find.dest_path,
                folder_name=find.folder, season_name=find.season_name,
                season_number=find.season_number, title=find.title, options=options))
            decision['run_id'] = result.run_id
            if result.action in ('opened', 'follow_up'):
                opened += 1
                decision['action'] = 'started'
                self._stamp(find, sync_attempts=attempts + 1,
                            sync_started_at=utc_now().isoformat(),
                            last_transfer_id=result.run_id)
                record('scanner.sync_started',
                       f"Started a sync of {find.label}: {' '.join(find.reasons)}",
                       target_type='sync_run', target_id=result.run_id,
                       target_label=find.label, detail=find.as_dict())
            elif result.action in ('skipped', 'joined'):
                decision['action'] = 'already_on_its_way'
            else:
                decision['action'] = 'failed'
                decision['detail'] = result.message
            decisions.append(decision)

        self._resolve_absent(source, seen)
        return decisions

    def _announce(self, source: str, started: List[Dict[str, Any]],
                  held: List[Dict[str, Any]]) -> None:
        try:
            from services.connectors import notify
            from services.connectors.events import Event, Field, headline
            lines = [f"• {d['find']['label']} — {d['find']['reasons'][0]}"
                     for d in started[:10] if d['find'].get('reasons')]
            if len(started) > 10:
                lines.append(f"… and {len(started) - 10} more")
            fields = [Field('Started', '\n'.join(lines) or 'see Notifications')]
            if held:
                fields.append(Field('Held back for the next scan', str(len(held))))
            notify(Event(
                key='scanner.found', severity='info',
                title=f"Auto-scanner found {len(started)} to sync in {source.title()}",
                summary='These go through the normal pipeline; the usual finished or '
                        'failed message follows for each.',
                fields=tuple(fields), author=headline('Auto-scanner', 'syncs started'),
            ))
        except Exception:  # noqa: BLE001
            log.exception('Could not announce the scan')

    # ----------------------------------------------------- the library tab

    def sync_one(self, source: str, external_id: str) -> Dict[str, Any]:
        """An admin pressed Sync on one title in a Library tab.

        Every season this disk is missing or short of is fetched — a person
        named this title, so the "only what was imported" rule that keeps the
        scanner from fetching a whole backlog does not apply.
        """
        from services.sync_engine.engine import SyncRequest
        view = self.index.library_view(source, refresh=False)
        if not view.get('live'):
            return {'success': False, 'error': f"{source.title()} did not answer"}
        item = next((i for i in view.get('items', [])
                     if str(i.get('external_id')) == str(external_id)), None)
        if item is None:
            return {'success': False, 'error': 'No such title is recorded'}
        if not item.get('service_has_files'):
            return {'success': False, 'error': 'The service holds no files for it yet'}

        adapter = self._adapter(source)
        finds: List[Find] = []
        if source == SOURCE_RADARR:
            if not item.get('present_locally'):
                find = self._find_for(source, item, None, adapter)
                if find:
                    finds.append(find)
        else:
            for season in item.get('seasons') or []:
                if not season.get('counts_towards_state'):
                    continue
                if (season.get('files_here') or 0) >= (season.get('episode_file_count') or 0):
                    continue
                find = self._find_for(source, item, season['season_number'], adapter)
                if find:
                    finds.append(find)
        if not finds:
            return {'success': False, 'error': 'Everything the service holds is already here'}

        runs = []
        for find in finds:
            result = self.engine.submit(SyncRequest(
                kind=S.MANUAL, source=source, media_type=find.media_type,
                source_path=find.source_path, dest_path=find.dest_path,
                folder_name=find.folder, season_name=find.season_name,
                season_number=find.season_number, title=find.title,
                options={('tvdb_id' if source == SOURCE_SONARR else 'tmdb_id'):
                         find.external_id}))
            runs.append(result.as_dict())
        started = [r for r in runs if r['ok']]
        return {'success': bool(started), 'runs': runs, 'transfers_started': len(started),
                'error': '' if started else '; '.join(r['message'] for r in runs)}

    # ------------------------------------------------------------- memory

    def _last_scan_at(self, source: str) -> Optional[datetime]:
        try:
            with self.db.get_connection() as conn:
                row = conn.execute("SELECT value FROM app_settings WHERE key = ?",
                                   (LAST_SCAN_KEY.format(source=source.upper()),)).fetchone()
            return _parse(row['value']) if row else None
        except Exception:  # noqa: BLE001
            return None

    def _set_last_scan_at(self, source: str, moment: datetime) -> None:
        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (LAST_SCAN_KEY.format(source=source.upper()), moment.isoformat()))
                conn.commit()
        except Exception:  # noqa: BLE001
            pass

    def _remember(self, find: Find) -> Dict[str, Any]:
        """Record that this gap exists; hand back what is known about it."""
        now = utc_now().isoformat()
        try:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    'SELECT * FROM sweep_finding WHERE source = ? AND external_id = ? '
                    'AND season_number IS ?',
                    (find.source, find.external_id, find.season_number)).fetchone()
                if row is None:
                    conn.execute(
                        'INSERT INTO sweep_finding (source, external_id, season_number, '
                        'title, finding, detail, first_seen_at, last_seen_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (find.source, find.external_id, find.season_number, find.title,
                         'scanner', ' '.join(find.reasons), now, now))
                    conn.commit()
                    return {'sync_attempts': 0}
                existing = dict(row)
                reopened = existing.get('resolved_at') is not None
                conn.execute(
                    'UPDATE sweep_finding SET last_seen_at = ?, resolved_at = NULL, '
                    'title = ?, detail = ?, '
                    'sync_attempts = CASE WHEN ? THEN 0 ELSE sync_attempts END '
                    'WHERE id = ?',
                    (now, find.title, ' '.join(find.reasons), reopened, existing['id']))
                conn.commit()
                if reopened:
                    existing['sync_attempts'] = 0
                return existing
        except Exception:  # noqa: BLE001
            return {'sync_attempts': 0}

    def _stamp(self, find: Find, **fields) -> None:
        try:
            with self.db.get_connection() as conn:
                sets = ', '.join(f'{k} = ?' for k in fields)
                conn.execute(
                    f'UPDATE sweep_finding SET {sets} WHERE source = ? AND external_id = ? '
                    f'AND season_number IS ?',
                    (*fields.values(), find.source, find.external_id, find.season_number))
                conn.commit()
        except Exception:  # noqa: BLE001
            pass

    def _resolve_absent(self, source: str, seen: set) -> None:
        """Gaps not found this scan are closed, and their attempt count with them."""
        try:
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    'SELECT id, external_id, season_number FROM sweep_finding '
                    'WHERE source = ? AND resolved_at IS NULL', (source,)).fetchall()
                for row in rows:
                    if (str(row['external_id']), row['season_number']) not in seen:
                        conn.execute('UPDATE sweep_finding SET resolved_at = ? WHERE id = ?',
                                     (utc_now().isoformat(), row['id']))
                conn.commit()
        except Exception:  # noqa: BLE001
            pass
