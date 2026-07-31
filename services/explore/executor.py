#!/usr/bin/env python3
"""
Execution — carry out an approved plan.

Order matters and is deliberate:

  1. move every superseded/removed local file into this transfer's backup
     directory (so an upgrade whose filename changed cannot leave two copies,
     and a removal is always recoverable),
  2. write the file list rsync will be held to,
  3. hand the run to the normal transfer pipeline, so it queues, streams
     progress, logs, and can be paused or cancelled like any other transfer.

If the transfer fails to start, the moves are rolled back — the library is left
exactly as it was found.

The backup directory is the same one the existing backup finaliser scans after
a transfer completes, so everything moved here is registered and restorable
from the Backups page without any new machinery.

SECURITY: every path is re-derived from the stored plan and re-checked against
the configured local base before anything is moved. The client supplies a plan
id and nothing else.
"""

import os
import shutil
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from env_flags import test_mode_enabled
from security import PathTraversalError, assert_path_within_bounds, validate_relative_path


class ExploreExecutor:
    def __init__(self, config, coordinator, store):
        self.config = config
        self.coordinator = coordinator
        self.store = store

    # ---- helpers ----------------------------------------------------------

    def _backup_dir(self, folder_name: str, transfer_id: str) -> str:
        backup_service = self.coordinator.backup_service
        return backup_service._get_dynamic_backup_dir({
            'folder_name': folder_name,
            'transfer_id': transfer_id,
        })

    def _work_dir(self, transfer_id: str) -> str:
        base = self.config.get('BACKUP_PATH') or '/tmp'
        path = os.path.join(base, '.explore-plans', transfer_id)
        os.makedirs(path, exist_ok=True)
        return path

    # ---- the run ----------------------------------------------------------

    def execute(self, record: Dict) -> Tuple[bool, str, Optional[str]]:
        """
        Run one approved plan.

        Returns (started, message, transfer_id).
        """
        spec = record['exec']
        source_root = spec['source_root']
        dest_root = spec['dest_root']
        mode = spec['mode']
        media_type = record['media_type']
        series = record['series']
        season_name = spec.get('season_name')

        allowed_local = self.config.get_destination_paths()
        try:
            assert_path_within_bounds(dest_root, allowed_local)
        except PathTraversalError:
            return False, 'Destination is outside the configured local library', None

        transfer_id = f"explore_{uuid.uuid4().hex[:12]}"
        backup_dir = self._backup_dir(series, transfer_id)

        # --- 1. move what the plan supersedes or removes --------------------
        # TEST_MODE puts rsync into --dry-run, so nothing arrives. Moving the
        # local files anyway would strand them: the old copy gone, the new one
        # never fetched. Test mode has to skip the moves as well, or it is not
        # a rehearsal — it is a deletion with no download.
        dry_run = test_mode_enabled()
        moved: List[Tuple[str, str]] = []
        records: List[Dict] = []
        try:
            for item in spec.get('backups', []):
                rel = item['local_rel']
                if not validate_relative_path(rel):
                    raise PathTraversalError(f"Unsafe local path in plan: {rel!r}")
                source = os.path.join(dest_root, rel)
                assert_path_within_bounds(source, allowed_local)
                if not os.path.isfile(source):
                    # Already gone; nothing to preserve, and not a failure.
                    continue
                target = os.path.join(backup_dir, rel)
                if dry_run:
                    print(f"🧪 TEST_MODE: would move to backup: {source}")
                else:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.move(source, target)
                    moved.append((source, target))
                records.append({
                    'action': item['action'],
                    'rel_path': rel,
                    'size': item.get('local_size', 0),
                    'code': item.get('code'),
                    'season_label': item.get('season_label'),
                    'backup_path': target,
                })
        except (OSError, PathTraversalError) as error:
            self._rollback(moved)
            return False, f"Could not move files to backup: {error}", None

        # --- 2. the list rsync is held to -----------------------------------
        rels = spec.get('transfers', [])
        work_dir = self._work_dir(transfer_id)
        files_from = os.path.join(work_dir, 'files.txt')
        try:
            with open(files_from, 'w', encoding='utf-8') as handle:
                for rel in rels:
                    # validate_relative_path rejects newlines, which is what
                    # stops a crafted filename injecting an extra entry here.
                    if not validate_relative_path(rel):
                        raise PathTraversalError(f"Unsafe remote path in plan: {rel!r}")
                    handle.write(rel + '\n')
        except (OSError, PathTraversalError) as error:
            self._rollback(moved)
            return False, f"Could not prepare the file list: {error}", None

        for rel in rels:
            records.append({
                'action': 'fetch',
                'rel_path': rel,
                'size': spec.get('sizes', {}).get(rel, 0),
                'code': spec.get('codes', {}).get(rel),
                'season_label': spec.get('season_labels', {}).get(rel),
            })

        # Nothing to transfer: the plan was removals only, which are already done.
        #
        # This still has to be written down. A pure removal is the run you are
        # most likely to want to undo, and without a row here it appeared in no
        # history and produced no backup record — the files sat in the backup
        # directory with nothing pointing at them.
        if not rels:
            self.store.record_files(transfer_id, records)
            self._record_removal_only_run(
                transfer_id, media_type, series, season_name,
                source_root, dest_root, len(moved),
            )
            return True, f"{len(moved)} file(s) moved to backup. Nothing to download.", None

        # --- 3. hand it to the normal pipeline ------------------------------
        started, state = self.coordinator.start_transfer(
            transfer_id,
            source_root,
            dest_root,
            operation_type=f"explore_{mode}",
            media_type=media_type,
            folder_name=series,
            season_name=season_name,
            extra_fields={
                'explore_files_from': files_from,
                'explore_mode': mode,
                'explore_plan_id': record['plan_id'],
            },
        )

        if not started:
            self._rollback(moved)
            return False, f"Could not start the transfer ({state})", None

        self.store.record_files(transfer_id, records)

        message = {
            'running': 'Transfer started',
            'QUEUED_PATH': 'Queued — the destination is busy with another transfer',
            'QUEUED_SLOT': 'Queued — waiting for a transfer slot',
        }.get(state, f"Transfer {state}")
        return True, message, transfer_id

    def _record_removal_only_run(self, transfer_id: str, media_type: str, series: str,
                                 season_name: Optional[str], source_root: str,
                                 dest_root: str, moved_count: int) -> None:
        """
        Write down a run that moved files aside and downloaded nothing.

        rsync never started, so nothing in the normal pipeline would record it.
        A completed transfer row is what every other part of the app reads:
        Explore's own history comes from `transfers`, and the backup index is
        built by walking the backup directory for a transfer id. Creating the
        row here gets both, and follows the same pattern restore already uses
        for its synthetic run.
        """
        coordinator = self.coordinator
        transfer_model = getattr(coordinator, 'transfer_model', None)
        backup_service = getattr(coordinator, 'backup_service', None)
        if transfer_model is None:
            return

        now = datetime.now().isoformat()
        try:
            transfer_model.create({
                'transfer_id': transfer_id,
                'media_type': media_type,
                'folder_name': series,
                'season_name': season_name,
                'source_path': source_root,
                'dest_path': dest_root,
                'operation_type': 'explore_prune',
                'status': 'completed',
                'rsync_process_id': None,
            })
            transfer_model.update(transfer_id, {
                'status': 'completed',
                'progress': f"{moved_count} file(s) moved to backup. Nothing to download.",
                'start_time': now,
                'end_time': now,
            })
        except Exception as error:  # noqa: BLE001 - the files are already safe
            print(f"⚠️  Could not record the removal-only run {transfer_id}: {error}")
            return

        # Index what was moved, so it is listed and restorable like any backup.
        if backup_service is not None:
            try:
                backup_service.finalize_backup_for_transfer(transfer_id)
            except Exception as error:  # noqa: BLE001
                print(f"⚠️  Could not index the backup for {transfer_id}: {error}")

    def _rollback(self, moved: List[Tuple[str, str]]) -> None:
        """Put back anything we moved, so a failed start changes nothing."""
        for source, target in reversed(moved):
            try:
                os.makedirs(os.path.dirname(source), exist_ok=True)
                shutil.move(target, source)
            except OSError as error:
                print(f"⚠️  Explore rollback failed for {target}: {error}")


def build_execution_spec(plan, season_name: Optional[str]) -> Dict:
    """
    Freeze a plan into the literal instructions the executor will follow.

    Everything the executor needs is captured here at approval time, so the run
    cannot drift from the report that was approved.
    """
    sizes: Dict[str, int] = {}
    codes: Dict[str, str] = {}
    season_labels: Dict[str, str] = {}
    backups: List[Dict] = []

    for action in plan.actions:
        if action.rel:
            sizes[action.rel] = action.size
            if action.code:
                codes[action.rel] = action.code
            if action.season_label:
                season_labels[action.rel] = action.season_label
        if action.local_rel:
            backups.append({
                'action': action.action,
                # The remote file that takes its place, so a dry run can tell
                # "rsync skipped this" from "rsync has not seen it move yet".
                'rel': action.rel,
                'local_rel': action.local_rel,
                'local_size': action.local_size,
                'code': action.code,
                'season_label': action.season_label,
            })

    return {
        'source_root': plan.source_root,
        'dest_root': plan.dest_root,
        'mode': {'sync_series': 'sync', 'sync_season': 'sync',
                 'download': 'download', 'replace': 'replace'}.get(plan.operation, 'sync'),
        'season_name': season_name,
        'transfers': plan.transfer_rels,
        'backups': backups,
        'sizes': sizes,
        'codes': codes,
        'season_labels': season_labels,
    }
