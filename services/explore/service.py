#!/usr/bin/env python3
"""
ExploreService — the facade the routes talk to.

Reads are served from a cached comparison so the page is instant and can say
when it last checked. Anything that will touch the disk re-compares first: a
plan is always built against the library as it is right now, never against a
cached view that may be minutes stale.
"""

import os
from typing import Dict, List, Optional, Sequence, Tuple

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
    def __init__(self, config, db_manager, coordinator, ssh_manager=None):
        self.config = config
        self.db = db_manager
        self.coordinator = coordinator
        self.ssh_manager = ssh_manager
        self.store = ExploreStore(db_manager)
        self.executor = ExploreExecutor(config, coordinator, self.store)

    def set_ssh_manager(self, ssh_manager) -> None:
        """The browse session is recreated on connect; keep the pointer fresh."""
        self.ssh_manager = ssh_manager

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

    def _require_session(self) -> None:
        if not self.ssh_manager or not getattr(self.ssh_manager, 'connected', False):
            raise ExploreError(
                'No remote browse session. Connect in Settings and try again.', 409)

    def compare(self, media_type: str) -> cmp.LibraryDiff:
        """Fresh comparison of a whole library. One ssh round trip."""
        remote_root, local_root = self._roots(media_type)
        self._require_session()

        remote = RemoteInventory(self.ssh_manager).read(media_type, remote_root)
        if not remote.exists:
            raise ExploreError(remote.error or 'Could not read the remote library', 502)

        local = LocalInventory().read(media_type, local_root)
        diff = cmp.compare_library(media_type, remote, local)

        self.store.save_snapshot(
            media_type, 'library',
            {'series': [s.to_dict(include_seasons=True) for s in diff.series]},
            diff.remote_ok, diff.local_ok, diff.remote_error or diff.local_error,
        )
        return diff

    def tree(self, media_type: str, refresh: bool = False) -> Dict:
        """The series list, from cache unless asked to re-check."""
        if media_type not in MEDIA_TYPES:
            raise ExploreError(f"Unknown library '{media_type}'", 404)

        if not refresh:
            snapshot = self.store.get_snapshot(media_type, 'library')
            if snapshot:
                return {
                    'media_type': media_type,
                    'series': snapshot['payload'].get('series', []),
                    'checked_at': snapshot['checked_at'],
                    'stale': True,
                }

        diff = self.compare(media_type)
        snapshot = self.store.get_snapshot(media_type, 'library')
        return {
            'media_type': media_type,
            'series': [s.to_dict(include_seasons=True) for s in diff.series],
            'checked_at': snapshot['checked_at'] if snapshot else None,
            'stale': False,
        }

    def _series_diff(self, media_type: str, folder: str) -> cmp.SeriesDiff:
        if not validate_path_component(folder):
            raise ExploreError('Invalid folder name', 400)
        diff = self.compare(media_type)
        series = diff.find(folder)
        if not series:
            raise ExploreError(f"'{folder}' is not in this library", 404)
        return series

    def series(self, media_type: str, folder: str) -> Dict:
        series = self._series_diff(media_type, folder)
        return series.to_dict(include_seasons=True)

    def season(self, media_type: str, folder: str, season_label: str) -> Dict:
        series = self._series_diff(media_type, folder)
        season = self._find_season(series, season_label)
        return season.to_dict(include_episodes=True)

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
        series = self._series_diff(media_type, folder)

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
        counts = scope.counts
        return counts.in_sync + counts.upgraded + counts.local_only

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
                if episode.label in (cmp.UPGRADED, cmp.IN_SYNC) and episode.key:
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

        decisions = {
            path: choice for path, choice in (decisions or {}).items()
            if choice in repair_mod.DECISIONS and plan.find(path) is not None
        }
        if not plan.clean and not decisions:
            raise ExploreError(
                'Every file here already has another copy in place. Choose which '
                'copy to keep for at least one of them.', 400)

        try:
            result = repair_mod.apply_repair(
                local_root, plan, self.config.get_all_allowed_paths(),
                decisions=decisions,
                keep_a_copy=self._keep_a_copy(media_type),
            )
        except PathTraversalError as error:
            raise ExploreError(str(error), 400) from error

        result['scope'] = scope
        result['blocked'] = [b.as_dict() for b in plan.blocked]
        return result

    def _keep_a_copy(self, media_type: str):
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
            ok, message, _ = backups.capture_library_file(
                library, relative_path, absolute_path, 'explore_repair')
            return ok, message

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
