#!/usr/bin/env python3
"""
ExploreService — the facade the routes talk to.

Reads are served from a cached comparison so the page is instant and can say
when it last checked. Anything that will touch the disk re-compares first: a
plan is always built against the library as it is right now, never against a
cached view that may be minutes stale.

How often the remote is read (operator, 2026-10-20). Opening the page checks
it, but one walk of a library is reused for `FRESH_FOR` seconds — unless
Sonarr or Radarr has reported an import for that library since, which is the
moment the remote changed. Re-check always reads again, except that a press
landing within `RECHECK_REUSE` seconds of a finished walk, or while one is
running, shares it. This side is re-read on every view: it is a local walk and
it is where syncs land, so a finished copy shows at once.
"""

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from env_flags import test_mode_enabled
from security import (
    PathTraversalError, assert_path_within_bounds, validate_path_component,
    validate_relative_path,
)

from . import compare as cmp
from . import dryrun
from . import planner
from . import repair as repair_mod
from services.backups import identity as backups_identity
from .executor import ExploreExecutor, build_execution_spec
from .identity import season_number_from_folder
from .inventory import LocalInventory, RemoteInventory
from .store import ExploreStore

MEDIA_TYPES = ('movies', 'tvshows', 'anime')

REMOTE_KEYS = {'movies': 'MOVIE_PATH', 'tvshows': 'TVSHOW_PATH', 'anime': 'ANIME_PATH'}
LOCAL_KEYS = {'movies': 'MOVIE_DEST_PATH', 'tvshows': 'TVSHOW_DEST_PATH', 'anime': 'ANIME_DEST_PATH'}

LABELS = {'movies': 'Movies', 'tvshows': 'TV Shows', 'anime': 'Anime'}

#: Seconds one walk of a remote library answers for, when nothing was imported
#: into it since (operator, 2026-10-20: 2 minutes).
FRESH_FOR = 120

#: Seconds a Re-check reuses a walk that has only just finished.
RECHECK_REUSE = 10

#: Seconds any walk answers for, imports or not, outside a Re-check: a burst of
#: webhooks during a season pack must not turn every click into a walk.
MIN_WALK_GAP = 15

#: Which webhook rows mean "the remote library changed", per library.
_IMPORTS = {
    'movies': ('radarr_webhook', None),
    'tvshows': ('sonarr_webhook', ('tvshows', 'series')),
    'anime': ('sonarr_webhook', ('anime',)),
}


@dataclass
class _RemoteRead:
    """One walk of a remote library, and what had been imported when it ran."""
    inventory: Any
    at: float               # monotonic, for ages
    checked_at: str         # what the page shows, in the snapshot's own format
    imports_seen: int       # the newest import webhook id at the time


class _SeasonSelection:
    """
    The seasons someone ticked, standing in for a series when the safety checks
    run. Only `counts` and `seasons` are read there, and both mean the same
    thing for a subset as for the whole.
    """

    def __init__(self, seasons):
        self.seasons = list(seasons)
        counts = cmp.Counts()
        for season in self.seasons:
            counts = counts.add(season.counts)
        self.counts = counts


class ExploreError(Exception):
    """Raised with a message meant for the operator, and an HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class ExploreService:
    def __init__(self, config, db_manager, coordinator, ssh_manager=None, session=None,
                 clock=time.monotonic):
        self.config = config
        self.db = db_manager
        self.coordinator = coordinator
        self.ssh_manager = ssh_manager
        #: The app's RemoteSession: opens and reopens the browse session, within
        #: the rules that keep the remote server from banning this address.
        #: Without it (tests), `ssh_manager` is used as it is.
        self.session = session
        self.clock = clock
        self.store = ExploreStore(db_manager)
        self.executor = ExploreExecutor(config, coordinator, self.store)
        self._remote: Dict[str, _RemoteRead] = {}
        self._walk_locks = {media_type: threading.Lock() for media_type in MEDIA_TYPES}

    def set_ssh_manager(self, ssh_manager) -> None:
        """The browse session is recreated on connect; keep the pointer fresh."""
        self.ssh_manager = ssh_manager

    def set_session(self, session) -> None:
        self.session = session

    def session_status(self) -> Dict:
        if self.session is not None:
            return self.session.status()
        connected = bool(self.ssh_manager and getattr(self.ssh_manager, 'connected', False))
        return {'connected': connected, 'auto_connect': False, 'host': '', 'last_error': '',
                'last_error_kind': None, 'paused': False, 'retry_at': None}

    def connect(self) -> Dict:
        """A person pressed Connect on the Explore page."""
        if self.session is None:
            raise ExploreError('Connecting is not available here', 409)
        ok, message = self.session.connect()
        return {'ok': ok, 'message': message, 'session': self.session.status()}

    # ---- configuration ----------------------------------------------------

    def _roots(self, media_type: str) -> Tuple[str, str]:
        if media_type not in MEDIA_TYPES:
            raise ExploreError(f"Unknown library '{media_type}'", 404)
        remote = self.config.get(REMOTE_KEYS[media_type])
        local = self.config.get(LOCAL_KEYS[media_type])
        if not remote:
            raise ExploreError(f"No remote path configured for {LABELS[media_type]}", 409)
        if not local:
            raise ExploreError(f"No local path configured for {LABELS[media_type]}", 409)
        return remote, local

    def libraries(self) -> List[Dict]:
        out = []
        for media_type in MEDIA_TYPES:
            remote = self.config.get(REMOTE_KEYS[media_type])
            local = self.config.get(LOCAL_KEYS[media_type])
            snapshot = self.store.get_snapshot(media_type, 'library')
            out.append({
                'id': media_type,
                'label': LABELS[media_type],
                'remote_path': remote,
                'local_path': local,
                'configured': bool(remote and local),
                'local_exists': bool(local and os.path.isdir(local)),
                'checked_at': snapshot['checked_at'] if snapshot else None,
            })
        return out

    # ---- comparison -------------------------------------------------------

    def _manager(self):
        """A live browse session, or an ExploreError a person can act on."""
        if self.session is not None:
            from services.remote_session import SessionUnavailable
            try:
                return self.session.ensure()
            except SessionUnavailable as error:
                raise ExploreError(error.message, 409) from error
        if not self.ssh_manager or not getattr(self.ssh_manager, 'connected', False):
            raise ExploreError(
                'No remote browse session. Connect in Settings and try again.', 409)
        return self.ssh_manager

    def _imports_seen(self, media_type: str) -> int:
        """The newest import webhook for this library: it rises when the remote changes."""
        table, kinds = _IMPORTS[media_type]
        query = f"SELECT COALESCE(MAX(id), 0) AS n FROM {table}"
        params: Tuple = ()
        if kinds:
            query += f" WHERE media_type IN ({', '.join('?' for _ in kinds)})"
            params = kinds
        try:
            with self.db.get_connection() as conn:
                return int(conn.execute(query, params).fetchone()['n'])
        except Exception:  # noqa: BLE001 - unknown means "assume it changed"
            return -1

    def _usable(self, read: Optional[_RemoteRead], media_type: str, max_age: float) -> bool:
        if read is None:
            return False
        age = self.clock() - read.at
        if age >= max_age:
            return False
        if age < min(MIN_WALK_GAP, max_age):
            return True
        seen = self._imports_seen(media_type)
        return seen != -1 and seen <= read.imports_seen

    def _read_remote(self, media_type: str, remote_root: str,
                     max_age: float) -> Tuple[_RemoteRead, bool]:
        """The remote library: a recent walk if it still answers, else a new one.

        Returns the read and whether this call walked. One walk per library at
        a time: a request arriving during one waits and then shares it.
        """
        with self._walk_locks[media_type]:
            cached = self._remote.get(media_type)
            if self._usable(cached, media_type, max_age):
                return cached, False
            imports = self._imports_seen(media_type)
            manager = self._manager()
            remote = RemoteInventory(manager).read(media_type, remote_root)
            if not remote.exists and self.session is not None and not self.session.alive():
                # The session died under the walk. Once more on a fresh one,
                # if the reconnect rules allow it now.
                manager = self._manager()
                remote = RemoteInventory(manager).read(media_type, remote_root)
            if not remote.exists:
                raise ExploreError(remote.error or 'Could not read the remote library', 502)
            read = _RemoteRead(remote, self.clock(), datetime.now().isoformat(), imports)
            self._remote[media_type] = read
            return read, True

    def _diff(self, media_type: str, max_age: float) -> Tuple[cmp.LibraryDiff, _RemoteRead, bool]:
        remote_root, local_root = self._roots(media_type)
        read, walked = self._read_remote(media_type, remote_root, max_age)
        local = LocalInventory().read(media_type, local_root)
        diff = cmp.compare_library(media_type, read.inventory, local)
        if walked:
            self.store.save_snapshot(
                media_type, 'library',
                {'series': [s.to_dict(include_seasons=True) for s in diff.series]},
                diff.remote_ok, diff.local_ok, diff.remote_error or diff.local_error,
            )
        return diff, read, walked

    def compare(self, media_type: str) -> cmp.LibraryDiff:
        """Fresh comparison of a whole library. One ssh round trip, always."""
        return self._diff(media_type, max_age=0)[0]

    def tree(self, media_type: str, refresh: bool = False, check: Optional[str] = None) -> Dict:
        """The series list.

        `check`: None reads the saved result only (instant; checks when there
        is none); `auto` is opening the page — the remote is read unless a walk
        from the last `FRESH_FOR` seconds still answers; `refresh` is Re-check.
        When the remote cannot be read, the saved result is returned with the
        reason, so the page can show it and say how old it is.
        """
        if media_type not in MEDIA_TYPES:
            raise ExploreError(f"Unknown library '{media_type}'", 404)
        if refresh:
            check = 'refresh'
        snapshot = self.store.get_snapshot(media_type, 'library')

        if check is None and snapshot:
            return self._from_snapshot(media_type, snapshot)

        max_age = RECHECK_REUSE if check == 'refresh' else FRESH_FOR
        try:
            diff, read, walked = self._diff(media_type, max_age)
        except ExploreError as error:
            if snapshot is None or error.status not in (409, 502):
                raise
            out = self._from_snapshot(media_type, snapshot)
            out['remote_error'] = error.message
            return out
        return {
            'media_type': media_type,
            'series': [s.to_dict(include_seasons=True) for s in diff.series],
            'checked_at': read.checked_at,
            'stale': False,
            'walked': walked,
            'remote_error': None,
            'session': self.session_status(),
        }

    def _from_snapshot(self, media_type: str, snapshot: Dict) -> Dict:
        return {
            'media_type': media_type,
            'series': snapshot['payload'].get('series', []),
            'checked_at': snapshot['checked_at'],
            'stale': True,
            'walked': False,
            'remote_error': None,
            'session': self.session_status(),
        }

    def _series_diff(self, media_type: str, folder: str,
                     max_age: float = 0) -> Tuple[cmp.SeriesDiff, _RemoteRead]:
        if not validate_path_component(folder):
            raise ExploreError('Invalid folder name', 400)
        diff, read, _walked = self._diff(media_type, max_age)
        series = diff.find(folder)
        if not series:
            raise ExploreError(f"'{folder}' is not in this library", 404)
        return series, read

    def series(self, media_type: str, folder: str) -> Dict:
        series, _read = self._series_diff(media_type, folder, FRESH_FOR)
        return series.to_dict(include_seasons=True)

    def season(self, media_type: str, folder: str, season_label: str) -> Dict:
        """One season, from the library's last walk while it still answers."""
        series, read = self._series_diff(media_type, folder, FRESH_FOR)
        season = self._find_season(series, season_label)
        out = season.to_dict(include_episodes=True)
        out['checked_at'] = read.checked_at
        return out

    @staticmethod
    def _find_season(series: cmp.SeriesDiff, season_label: str) -> cmp.SeasonDiff:
        for season in series.seasons:
            if season.display_name == season_label:
                return season
        raise ExploreError(f"'{season_label}' is not in this series", 404)

    # ---- planning ---------------------------------------------------------

    def plan(self, media_type: str, operation: str, folder: str,
             season_label: Optional[str] = None,
             codes: Optional[Sequence[str]] = None,
             include_removals: bool = True,
             created_by: Optional[str] = None,
             season_labels: Optional[Sequence[str]] = None) -> Dict:
        """
        Evaluate an operation and store it for approval.

        Always built from a fresh comparison — a plan approved against a stale
        view could remove a file that has since come back.
        """
        remote_root, local_root = self._roots(media_type)
        series, _read = self._series_diff(media_type, folder)

        return self._build_plan(media_type, operation, folder, season_label, codes,
                                include_removals, created_by, season_labels,
                                series, remote_root, local_root)

    def _build_plan(self, media_type, operation, folder, season_label, codes,
                    include_removals, created_by, season_labels,
                    series, remote_root, local_root) -> Dict:
        if operation == planner.SYNC_SERIES:
            plan = planner.plan_series_sync(
                media_type, series, remote_root, local_root, include_removals)
            scope = series
            season_name = None
        elif operation == planner.SYNC_SEASONS:
            if not season_labels:
                raise ExploreError('Pick at least one season', 400)
            seasons = [self._find_season(series, label) for label in season_labels]
            plan = planner.plan_seasons_sync(
                media_type, series, seasons, remote_root, local_root, include_removals)
            scope = _SeasonSelection(seasons)
            # The transfer is scoped to the series folder, because the file
            # list spans seasons. Naming one of them would be a lie.
            season_name = None
        elif operation in (planner.SYNC_SEASON, planner.DOWNLOAD, planner.REPLACE):
            if media_type == 'movies':
                season = series.seasons[0] if series.seasons else None
                if season is None:
                    raise ExploreError('Nothing to compare in this folder', 404)
            else:
                if not season_label:
                    raise ExploreError('A season is required for this operation', 400)
                season = self._find_season(series, season_label)

            if operation == planner.SYNC_SEASON:
                plan = (planner.plan_movie_sync(media_type, series, remote_root, local_root,
                                                include_removals)
                        if media_type == 'movies'
                        else planner.plan_season_sync(media_type, series, season,
                                                      remote_root, local_root, include_removals))
            elif operation == planner.DOWNLOAD:
                plan = planner.plan_download(media_type, series, season,
                                             remote_root, local_root, codes or [])
            else:
                plan = planner.plan_replace(media_type, series, season,
                                            remote_root, local_root, codes or [])
            scope = season
            season_name = season.local_folder or season.remote_folder
        else:
            raise ExploreError(f"Unknown operation '{operation}'", 400)

        local_media_total = self._local_media_total(scope)
        planner.evaluate(plan, scope, local_media_total,
                         duplicate_codes=self._duplicate_codes(scope))

        # SECURITY: the destination must resolve inside the configured local
        # library before this plan is ever offered for approval.
        try:
            assert_path_within_bounds(plan.dest_root, self.config.get_destination_paths())
        except PathTraversalError:
            raise ExploreError('Destination escapes the configured library', 400)

        payload = plan.to_dict()
        plan_id = self.store.save_plan(
            plan, build_execution_spec(plan), created_by)
        payload['plan_id'] = plan_id
        payload['requires_override'] = not plan.safe
        return payload

    @staticmethod
    def _local_media_total(scope) -> int:
        return scope.counts.local_media

    @staticmethod
    def _duplicate_codes(scope) -> List[str]:
        """Episodes that match more than one local file — never guessed at."""
        # A season has no `seasons` attribute and stands in for itself. A series
        # with an empty season list is still a series: falling back to [scope]
        # there would look for episodes on an object that has none.
        seasons = getattr(scope, 'seasons', None)
        if seasons is None:
            seasons = [scope]
        seen: Dict[str, int] = {}
        for season in seasons:
            for episode in season.episodes:
                if episode.label in (cmp.UPGRADED, cmp.IN_SYNC, cmp.NESTED) and episode.key:
                    seen[str(episode.key)] = seen.get(str(episode.key), 0) + 1
        return [code for code, count in seen.items() if count > 1]

    # ---- rehearsal --------------------------------------------------------

    def dry_run(self, plan_id: str) -> Dict:
        """
        Run the plan's own rsync commands with `--dry-run` and report them back.

        A plan is carried out as one transfer per season, so a series plan is
        rehearsed the same way — rsync is asked once per season, against that
        season's own pair of folders. The answers are merged into one report,
        because the plan is one review however many runs it becomes.

        The plan stays executable afterwards: rehearsing an operation must not
        be the thing that stops you performing it. Removals and backups never
        reach rsync — the plan performs those itself before the transfer starts
        — so they are folded in from the plan and labelled as such.
        """
        record = self.store.peek_plan(plan_id)
        if not record:
            raise ExploreError(
                'That plan has expired or was already used. Re-check and try again.', 409)

        units = record['exec'].get('units') or []
        report = dryrun.DryRunReport()
        # Several seasons can hold a file of the same name, so the season is
        # kept on each path once there is more than one of them.
        label_paths = len(units) > 1
        tails: List[str] = []
        ran_any = False

        transfer_service = getattr(self.coordinator, 'transfer_service', None)

        for index, unit in enumerate(units):
            backups = unit.get('backups', [])
            season = unit.get('season_label') or ''
            report.backups.extend(b for b in backups if b.get('action') == 'supersede')
            report.removals.extend(b for b in backups if b.get('action') == 'remove')

            rels = unit.get('transfers', [])
            if not rels:
                continue

            if transfer_service is None or not hasattr(transfer_service, 'run_explore_dry_run'):
                raise ExploreError('Dry run is not available on this server', 503)

            files_from = self._files_from(plan_id, rels, index)
            ok, exit_code, output, error = transfer_service.run_explore_dry_run(
                unit['source_root'], unit['dest_root'], files_from,
                unit.get('mode', 'sync'),
            )
            ran_any = True

            # Reconcile each season against its own plan before merging: the
            # file lists are relative to that season's folder, so comparing
            # them across seasons would pair up unrelated names.
            sizes = unit.get('sizes', {})
            part = dryrun.DryRunReport(
                ok=ok, exit_code=exit_code, error=error,
                files=dryrun.parse(output),
            )
            if ok:
                superseded = {b['rel']: int(sizes.get(b['rel'], 0))
                              for b in backups
                              if b.get('action') == 'supersede' and b.get('rel')}
                dryrun.reconcile(
                    part,
                    planned={rel: int(sizes.get(rel, 0)) for rel in rels},
                    superseded=superseded,
                )
            else:
                report.ok = False
                report.exit_code = exit_code or report.exit_code
                report.error = '; '.join(x for x in (report.error, error) if x)

            for file in part.files:
                if label_paths and season:
                    file.rel = f"{season}/{file.rel}"
                report.files.append(file)
            for warning in part.warnings:
                report.warnings.append(f"{season}: {warning}" if label_paths and season else warning)

            tail = dryrun.tail(output)
            if tail:
                tails.append(f"— {season} —\n{tail}" if label_paths and season else tail)

        if not ran_any:
            # Removals only. There is nothing for rsync to be asked about, and
            # saying "rsync found nothing" would read as "nothing happens".
            report.ran = False
            report.warnings.append(
                'No files would be transferred, so rsync was not run. '
                'The local changes below are made by DragonCP itself.')

        report.raw_tail = '\n\n'.join(tails)
        return self._dry_run_payload(record, report)

    def _files_from(self, plan_id: str, rels: Sequence[str], index: int = 0) -> str:
        """
        Write one season's file list somewhere rsync can read it.

        Numbered per season, because a series plan asks rsync once for each and
        a shared name would have every run reading the last season's list.

        Separate from the executor's copy: a dry run must not leave anything
        behind that a later real run could pick up by accident.
        """
        # Under BACKUP_PATH via the layout, so it fails closed with the rest of
        # the backup area rather than falling back to a temporary directory the
        # OS may clear.
        work_dir = self.coordinator.backups.layout.plans_dir('dryrun')
        os.makedirs(work_dir, exist_ok=True)
        path = os.path.join(work_dir, f"{plan_id}-{index}.txt")
        with open(path, 'w', encoding='utf-8') as handle:
            for rel in rels:
                if not validate_relative_path(rel):
                    raise ExploreError(f"Unsafe path in plan: {rel}", 400)
                handle.write(rel + '\n')
        return path

    @staticmethod
    def _dry_run_payload(record: Dict, report: 'dryrun.DryRunReport') -> Dict:
        return {
            'plan_id': record['plan_id'],
            'operation': record['operation'],
            'series': record['series'],
            'season_label': record['season_label'],
            # The plan's own roots describe its scope. The work happens against
            # each season's pair of folders, which the units carry.
            'source_root': record['plan'].get('source_root'),
            'dest_root': record['plan'].get('dest_root'),
            'seasons': [u.get('season_label') for u in record['exec'].get('units') or []],
            'report': report.to_dict(),
        }

    # ---- execution --------------------------------------------------------

    def execute(self, plan_id: str, override: bool = False,
                confirm_text: Optional[str] = None) -> Dict:
        # Check first, claim second. Claiming up front spent the plan on every
        # rejected request, so mistyping the confirmation left nothing to
        # confirm — the retry met "expired or already used" instead.
        record = self.store.peek_plan(plan_id)
        if not record:
            raise ExploreError(
                'That plan has expired or was already used. Re-check and try again.', 409)

        if not record['safe'] and not override:
            raise ExploreError(
                'This plan did not pass its safety checks. Review it and confirm explicitly.',
                422)

        if not record['safe'] and override:
            expected = record['season_label'] or record['series']
            if (confirm_text or '').strip() != expected:
                raise ExploreError(
                    f"Type '{expected}' to confirm an operation that failed its checks.", 422)

        # Now spend it. The claim is atomic, so a second caller racing this one
        # loses here rather than running the same plan twice.
        record = self.store.take_plan(plan_id)
        if not record:
            raise ExploreError(
                'That plan has expired or was already used. Re-check and try again.', 409)

        started, message, runs = self.executor.execute(record)
        if not started:
            raise ExploreError(message, 500)

        # A series plan becomes one transfer per season, so the id is plural.
        # `transfer_id` stays for the single-season case, which is most of them.
        transfer_ids = [r['transfer_id'] for r in runs if r.get('transfer_id')]
        return {
            'message': message,
            'runs': runs,
            'transfer_ids': transfer_ids,
            'transfer_id': transfer_ids[0] if len(transfer_ids) == 1 else None,
            'operation': record['operation'],
            'series': record['series'],
        }

    # ---- repair -----------------------------------------------------------

    def _repair_entries(self, media_type: str, folder: str,
                        season_label: Optional[str]) -> Tuple[str, List, str]:
        """
        The local files for one series or season, and a name for that scope.

        Local only — a repair never asks the remote anything, so it works with
        the browse session down. That matters: the files it fixes are invisible
        to the media server right now, and waiting on SSH to move a file that
        never leaves the local disk would be a made-up dependency.
        """
        if media_type not in MEDIA_TYPES:
            raise ExploreError(f"Unknown library '{media_type}'", 404)
        if not validate_path_component(folder):
            raise ExploreError('Invalid folder name', 400)
        if season_label and not validate_path_component(season_label):
            raise ExploreError('Invalid season name', 400)

        local_root = self.config.get(LOCAL_KEYS[media_type])
        if not local_root:
            raise ExploreError(f"No local path configured for {LABELS[media_type]}", 409)

        local = LocalInventory().read(media_type, local_root)
        if not local.exists:
            raise ExploreError(local.error or 'Could not read the local library', 502)

        entries = local.in_series(folder)
        scope = folder
        # Movies have no season layer, so a season narrows nothing there.
        if season_label and media_type != 'movies':
            entries = [e for e in entries if e.season_folder == season_label]
            scope = f"{folder} — {season_label}"

        return local_root, entries, scope

    def repair_plan(self, media_type: str, folder: str,
                    season_label: Optional[str] = None) -> Dict:
        """What repairing the stranded files here would do. Moves nothing."""
        local_root, entries, scope = self._repair_entries(media_type, folder, season_label)
        plan = repair_mod.plan_repair(media_type, local_root, entries, scope)
        payload = plan.as_dict()
        payload['blocker'] = self._repair_blocker(media_type, folder)
        return payload

    def repair_apply(self, media_type: str, folder: str,
                     season_label: Optional[str] = None,
                     decisions: Optional[Dict[str, str]] = None) -> Dict:
        """
        Carry out the repair.

        The plan is rebuilt here from the disk as it is now rather than taken
        from the caller. A repair moves files inside the media library, so the
        client does not get to name them — the same reason an Explore transfer
        re-derives its own file list server-side. `decisions` is the one thing
        the caller does supply, and it only ever selects between two copies the
        server itself found.
        """
        local_root, entries, scope = self._repair_entries(media_type, folder, season_label)

        blocker = self._repair_blocker(media_type, folder)
        if blocker:
            raise ExploreError(blocker, 409)

        plan = repair_mod.plan_repair(media_type, local_root, entries, scope)
        if not plan.actions:
            raise ExploreError('Nothing here can be repaired automatically.', 400)

        # Keep only decisions that name a file this plan actually holds, and
        # normalise them to {'choice': ..., 'rival': ...}. The rival is what the
        # preview showed; `apply_repair` refuses if the disk no longer agrees.
        decisions = {
            path: {'choice': value.get('choice'), 'rival': value.get('rival')}
            for path, value in (decisions or {}).items()
            if isinstance(value, dict)
            and value.get('choice') in repair_mod.DECISIONS
            and plan.find(path) is not None
        }
        if not plan.clean and not decisions:
            raise ExploreError(
                'Every file here already has another copy in place. Choose which '
                'copy to keep for at least one of them.', 400)

        # Collected by the keep-a-copy callback below, so the versions this
        # repair creates appear in the backup history alongside the ones a sync
        # makes. Without it a file can only be found by someone who already
        # knows a repair happened.
        kept: List[str] = []
        try:
            # Test mode rehearses: the same checks and the same report, and no
            # file in the library is moved, kept, replaced or removed.
            result = repair_mod.apply_repair(
                local_root, plan, self.config.get_all_allowed_paths(),
                decisions=decisions,
                keep_a_copy=self._keep_a_copy(media_type, kept),
                dry_run=test_mode_enabled(),
            )
        except PathTraversalError as error:
            raise ExploreError(str(error), 400) from error

        backups = getattr(self.coordinator, 'backups', None)
        if backups is not None and kept:
            backups.record_captures_created(
                kept,
                f"A repair of {folder} kept {len(kept)} file(s) it removed, "
                'which are now restorable',
                source=folder,
            )

        result['scope'] = scope
        result['blocked'] = [b.as_dict() for b in plan.blocked]
        return result

    def _keep_a_copy(self, media_type: str, kept: Optional[List[str]] = None):
        """
        Hands the repair a way to preserve a file it is about to remove.

        Routed through the backups service rather than reimplemented, so a file
        deleted here lands in the same tree, is indexed the same way, and comes
        back through the same restore as anything else. Without a backups
        service there is nothing to preserve into, and refusing is the only safe
        answer — a delete that cannot be undone is not one this offers.
        """
        backups = getattr(self.coordinator, 'backups', None)
        library = backups_identity.library_for_media_type(media_type) if backups else None

        def keep(relative_path: str, absolute_path: str):
            if backups is None or not library:
                return False, 'the backup area is not available'
            ok, message, capture_id = backups.capture_library_file(
                library, relative_path, absolute_path, 'explore_repair')
            if ok and capture_id and kept is not None:
                kept.append(capture_id)
            if not ok:
                return ok, message

            def undo(because: str = 'the file it was kept from is still there'):
                """
                Give the kept copy back if the removal does not happen.

                A file is kept by giving it a SECOND NAME, on the promise that
                the caller destroys the first one immediately. A caller whose
                delete fails has to withdraw that, or the library file stays
                welded to an indexed backup and any in-place edit rewrites both.
                """
                if not capture_id:
                    return
                # Only drop it from the audit list if it really went. A capture
                # whose files could not be removed still exists and is still
                # indexed, so quietly forgetting it here would hide the one
                # thing somebody needs to go and deal with.
                if backups.discard_capture(capture_id, because):
                    if kept is not None and capture_id in kept:
                        kept.remove(capture_id)

            return ok, message, undo

        return keep

    def _repair_blocker(self, media_type: str, folder: str) -> Optional[str]:
        """
        Why a repair must not run right now, or None.

        Narrowed to this library and this title: a movie transfer has no bearing
        on a stranded TV episode, and blocking on it would mean the repair is
        never available on a busy instance. A transfer against the same title is
        a different matter — it is writing into the very folders this is about
        to rename inside.

        Not being able to answer blocks too. This guards a rename on the media
        library, so "the database did not respond" has to mean wait.
        """
        try:
            active = [
                transfer for transfer in self.coordinator.get_active_transfers()
                if (transfer.get('media_type') or '') == media_type
                and (transfer.get('folder_name') or '') == folder
            ]
        except Exception as error:  # noqa: BLE001 - cannot tell, so refuse
            return (
                f"Could not check whether any transfers are running ({error}). "
                'Repair renames files in your media library, so it only runs '
                'when this title is known to be idle.'
            )

        if not active:
            return None

        count = len(active)
        noun = 'transfer is' if count == 1 else 'transfers are'
        return (
            f"{count} {noun} still active for {folder}. Repair moves files inside "
            'that folder, so it waits until nothing else is writing there.'
        )

    # ---- history ----------------------------------------------------------

    def backups(self, media_type: str, folder: str,
                season_label: Optional[str] = None) -> List[Dict]:
        """
        What has been backed up for this series, or for one of its seasons.

        Read-only. Restoring is the Backups page's job — this is here so you can
        see, while looking at a season, that a previous sync moved something
        aside and that it is still recoverable.
        """
        if media_type not in MEDIA_TYPES:
            raise ExploreError(f"Unknown library '{media_type}'", 404)
        if not validate_path_component(folder):
            raise ExploreError('Invalid folder name', 400)
        if season_label and not validate_path_component(season_label):
            raise ExploreError('Invalid season name', 400)

        season_number = season_number_from_folder(season_label) if season_label else None
        # A movie folder has no season layer; its pseudo-season must not filter.
        if media_type == 'movies':
            season_number, season_label = None, None

        return self.store.backups(media_type, folder, season_number, season_label)

    def history(self, media_type: str, folder: str,
                season_name: Optional[str] = None) -> List[Dict]:
        if media_type not in MEDIA_TYPES:
            raise ExploreError(f"Unknown library '{media_type}'", 404)
        if not validate_path_component(folder):
            raise ExploreError('Invalid folder name', 400)
        if season_name and not validate_path_component(season_name):
            raise ExploreError('Invalid season name', 400)
        return self.store.history(media_type, folder, season_name)
