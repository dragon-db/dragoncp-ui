#!/usr/bin/env python3
"""
The facade routes and the coordinator talk to.

Holds the wiring — layout, index, sorter, planner, retention, migration — and
the two operations that need more than one of them: sorting a finished
transfer, and running a restore.

A restore goes through the queue like any other transfer. That is not
decoration: the previous implementation ran rsync inside the web request and
never reserved its destination, so a restore could pre-delete and write into a
library folder while a sync was writing the same one.
"""

import os
import shutil
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from .identity import SlotIdentity, media_type_for_library, parse_capture_id
from .indexer import BackupIndexer
from .layout import BackupLayout, BackupPathNotConfigured, utc_now
from .migrate import LegacyMigration
from .restore import RestorePlanner, RestoreRunner
from .retention import RetentionPolicy
from .sorter import BackupSorter, SortedCapture, SortResult

#: What counts as "still using the disk". Mirrors the transfer model's own
#: definition; stated here so the guard does not depend on a helper's name
#: matching what it actually returns.
_ACTIVE_STATUSES = frozenset({'running', 'pending', 'queued', 'paused'})


class BackupsService:
    """Everything the Backups feature does, in one place."""

    def __init__(self, config, db_manager, capture_model, transfer_model,
                 socketio=None, coordinator=None, settings=None,
                 legacy_backup_model=None):
        self.config = config
        self.db = db_manager
        self.captures = capture_model
        self.transfer_model = transfer_model
        self.socketio = socketio
        self.coordinator = coordinator
        self.settings = settings

        self.layout = BackupLayout(config)
        self.indexer = BackupIndexer(self.layout, capture_model)
        self.sorter = BackupSorter(config, self.layout)
        self.planner = RestorePlanner(config, self.layout, capture_model)
        self.retention = RetentionPolicy(config, self.layout, capture_model, settings)
        self.migration = LegacyMigration(
            config, self.layout, legacy_backup_model, transfer_model, self.indexer,
        )

        self._restores_running: Dict[str, str] = {}
        self._lock = threading.Lock()

    def set_coordinator(self, coordinator) -> None:
        self.coordinator = coordinator

    # ---- configuration ----------------------------------------------------

    def is_configured(self) -> bool:
        return self.layout.is_configured()

    def require_backup_path(self) -> str:
        """
        The base, or an exception naming the setting.

        Callers that write MUST go through this. Falling back to a temporary
        directory is what made backups look like they worked and be
        unrecoverable.
        """
        return self.layout.base()

    # ---- after a transfer -------------------------------------------------

    def sort_after_transfer(self, transfer_id: str, reason: str = 'sync_replace') -> Dict:
        """
        File everything a transfer displaced, then index it and apply retention.

        Called once a transfer has settled. Safe to call for a transfer that
        displaced nothing — it finds an empty or absent staging folder and
        returns without creating anything, which is what stops clean syncs
        leaving empty containers behind.
        """
        summary = {'captures': 0, 'files': 0, 'bytes': 0, 'unsorted': 0, 'errors': []}

        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return summary

        # A simulation writes into its own confined root, not the library, so
        # anything it displaces is generated filler with no identity. Sorting it
        # would fill the unsorted bucket with `simulation_1.bin` and leave rows
        # the simulation cleanup — which deletes by `is_simulation` — cannot
        # reach. Clear the staging folder and record nothing.
        if transfer.get('is_simulation'):
            self.discard_staging(transfer_id)
            return summary

        try:
            result: SortResult = self.sorter.sort_transfer(transfer, reason=reason)
        except BackupPathNotConfigured as error:
            summary['errors'].append(str(error))
            return summary

        for capture in result.captures:
            try:
                self.index_sorted(capture)
            except Exception as error:  # noqa: BLE001 - files are placed; index is rebuildable
                summary['errors'].append(f"{capture.capture_id}: {error}")

        summary['captures'] = len(result.captures)
        summary['files'] = result.file_count
        summary['bytes'] = result.total_size
        summary['unsorted'] = result.unsorted_count
        summary['errors'].extend(result.errors)

        if result.captures:
            self._apply_retention_quietly()

        return summary

    def index_sorted(self, capture: SortedCapture) -> None:
        """Write the index row for a capture the sorter just created."""
        identity = capture.identity
        # Read the provenance back out of the id rather than splitting on the
        # separator: a disambiguated id ends in "__2", and taking the last
        # segment recorded the disambiguator as the source instead of the
        # transfer it came from.
        parsed = parse_capture_id(capture.capture_id)
        record = {
            'capture_id': capture.capture_id,
            'library': capture.library or None,
            'title': capture.title or None,
            'season_number': identity.season if identity else None,
            'episode_number': identity.episode if identity else None,
            'release_year': identity.year if identity else None,
            'slot_key': identity.slot_key if identity else None,
            'capture_path': self.layout.relative(capture.path),
            'captured_at': capture.captured_at.isoformat().replace('+00:00', 'Z'),
            'source_transfer_id': capture.source_transfer_id,
            'source_ref': parsed[1] if parsed else '',
            'reason': capture.reason,
            'kind': capture.kind,
            'file_count': len(capture.files),
            'total_size': capture.total_size,
            'pinned': 0,
            'status': 'present',
        }
        slot_keys = list(identity.all_slot_keys) if identity else []
        self.captures.upsert(record, capture.files, slot_keys)

    def staging_dir(self, transfer_id: str) -> str:
        """Where rsync should send displaced files for this transfer."""
        return self.layout.staging_dir(transfer_id)

    def discard_staging(self, transfer_id: str) -> None:
        """Throw a transfer's staging folder away without indexing anything."""
        try:
            staging = self.layout.staging_dir(transfer_id)
        except Exception:  # noqa: BLE001 - nothing configured, nothing to discard
            return
        shutil.rmtree(staging, ignore_errors=True)

    # ---- browsing ---------------------------------------------------------

    def overview(self) -> Dict:
        totals = self.captures.totals()
        return {
            'configured': self.is_configured(),
            'backup_path_set': self.is_configured(),
            'totals': totals,
            'disk': self.retention.disk_usage(),
            'retention': self.retention.describe(),
            'libraries': self._library_summary(),
            'legacy_folders': len(self.layout.legacy_folders()),
        }

    def _library_summary(self) -> List[Dict]:
        rows = self.captures.titles()
        summary: Dict[str, Dict] = {}
        for row in rows:
            library = row['library'] or 'unknown'
            entry = summary.setdefault(library, {
                'library': library, 'title_count': 0,
                'capture_count': 0, 'total_size': 0,
            })
            entry['title_count'] += 1
            entry['capture_count'] += row['capture_count'] or 0
            entry['total_size'] += row['total_size'] or 0
        return sorted(summary.values(), key=lambda e: e['library'])

    def titles(self, library: Optional[str] = None) -> List[Dict]:
        return self.captures.titles(library)

    def seasons(self, library: str, title: str) -> List[Dict]:
        return self.captures.seasons(library, title)

    def slots(self, library: Optional[str] = None, title: Optional[str] = None,
              season: Optional[int] = None, search: Optional[str] = None,
              limit: int = 200, offset: int = 0, sort: str = 'recent') -> Dict:
        rows = self.captures.slots(
            library=library, title=title, season=season,
            search=search, limit=limit, offset=offset, sort=sort,
        )
        for row in rows:
            row['display'] = SlotIdentity(
                library=row.get('library') or '',
                title=row.get('title') or '',
                season=row.get('season_number'),
                episode=row.get('episode_number'),
                year=row.get('release_year'),
            ).display
        return {
            'slots': rows,
            'total': self.captures.count_slots(
                library=library, title=title, season=season, search=search,
            ),
            'limit': limit,
            'offset': offset,
            'sort': sort,
        }

    def slot(self, slot_key: str) -> Dict:
        """One slot's whole version history, newest first."""
        captures = self.captures.captures_for_slot(slot_key)
        for capture in captures:
            capture['files'] = self.captures.files(capture['capture_id'])
            capture['display'] = SlotIdentity(
                library=capture.get('library') or '',
                title=capture.get('title') or '',
                season=capture.get('season_number'),
                episode=capture.get('episode_number'),
                year=capture.get('release_year'),
            ).display
            capture['slot_keys'] = self.captures.slot_keys_for(capture['capture_id'])

        current = self._current_occupant(captures[0]) if captures else None
        return {
            'slot_key': slot_key,
            'captures': captures,
            'current': current,
            'display': captures[0]['display'] if captures else '',
        }

    def _current_occupant(self, capture: Dict) -> Optional[Dict]:
        """What the library holds for this slot right now."""
        target_dir = self.planner.target_directory(capture)
        if not target_dir or not os.path.isdir(target_dir):
            return None
        occupants = self.planner._locate_in_library(capture, target_dir)
        media = [o for o in occupants if o['is_media']]
        if not media:
            return None
        best = media[0]
        return {
            'path': best['path'],
            'name': os.path.basename(best['path']),
            'size': best['size'],
            'directory': target_dir,
        }

    def capture(self, capture_id: str) -> Optional[Dict]:
        record = self.captures.get(capture_id)
        if not record:
            return None
        record['files'] = self.captures.files(capture_id)
        record['slot_keys'] = self.captures.slot_keys_for(capture_id)
        record['display'] = SlotIdentity(
            library=record.get('library') or '',
            title=record.get('title') or '',
            season=record.get('season_number'),
            episode=record.get('episode_number'),
            year=record.get('release_year'),
        ).display
        return record

    def unsorted(self, limit: int = 500) -> List[Dict]:
        rows = self.captures.by_kind('unsorted', limit=limit)
        for row in rows:
            row['files'] = self.captures.files(row['capture_id'])
        return rows

    # ---- restore ----------------------------------------------------------

    def plan_restore(self, capture_id: str, files: Optional[List[str]] = None) -> Dict:
        return self.planner.plan(capture_id, files).as_dict()

    def restore(self, capture_id: str, files: Optional[List[str]] = None) -> Tuple[bool, str, Dict]:
        """
        Start a restore.

        Returns as soon as the run is accepted; progress arrives over the
        socket and the run appears in Transfers like anything else. Refuses
        rather than queueing when the destination is busy — a restore is
        watched, and silently parking it behind a sync is worse than saying so.
        """
        capture = self.captures.get(capture_id)
        if not capture:
            return False, 'This backup is no longer in the index', {}

        plan = self.planner.plan(capture_id, files)
        if plan.blocked:
            return False, plan.blocked, plan.as_dict()
        if not plan.operations:
            return False, 'Nothing to restore for the selected files', plan.as_dict()

        with self._lock:
            if capture_id in self._restores_running:
                return False, 'This backup is already being restored', plan.as_dict()

            ok, message, transfer_id = self._reserve(plan)
            if not ok:
                return False, message, plan.as_dict()
            self._restores_running[capture_id] = transfer_id

        threading.Thread(
            target=self._run_restore,
            args=(transfer_id, capture_id, capture, plan),
            daemon=True,
        ).start()

        return True, f"Restoring {plan.slot_display}", {
            **plan.as_dict(), 'transfer_id': transfer_id,
        }

    def _reserve(self, plan) -> Tuple[bool, str, str]:
        """Take the destination from the queue, or explain why we cannot."""
        transfer_id = f"restore_{int(utc_now().timestamp())}_{os.urandom(3).hex()}"
        queue = getattr(self.coordinator, 'queue_manager', None)

        if queue is not None:
            is_duplicate, existing = queue.check_duplicate_destination(plan.target_dir, transfer_id)
            if is_duplicate:
                return False, (
                    'A transfer is currently writing to this folder. '
                    'Wait for it to finish and try again.'
                ), ''

            registered, status = queue.register_transfer(transfer_id, plan.target_dir)
            if not registered:
                # 'queued' still reserves the destination, and nothing would
                # ever come along to run it — release it before refusing.
                queue.unregister_transfer(transfer_id, plan.target_dir)
                if status == 'queued':
                    return False, (
                        'All transfer slots are busy. Wait for one to finish and try again.'
                    ), ''
                return False, f"Could not reserve the destination ({status})", ''

        self.transfer_model.create({
            'transfer_id': transfer_id,
            'media_type': media_type_for_library(plan.library) or 'backup',
            'folder_name': plan.slot_display,
            'season_name': None,
            'source_path': plan.operations[0].source if plan.operations else '',
            'dest_path': plan.target_dir,
            'operation_type': 'restore',
            'status': 'running',
            'rsync_process_id': None,
        })
        return True, 'reserved', transfer_id

    def _run_restore(self, transfer_id: str, capture_id: str,
                     capture: Dict, plan) -> None:
        def log(message: str) -> None:
            try:
                self.transfer_model.add_log(transfer_id, message)
            except Exception:  # noqa: BLE001
                pass

        def progress(index: int, total: int, name: str) -> None:
            text = f"Restoring {index}/{total}: {name}"
            try:
                self.transfer_model.update(transfer_id, {'progress': text})
            except Exception:  # noqa: BLE001
                pass
            self._emit('transfer_progress', {
                'transfer_id': transfer_id,
                'status': 'running',
                'progress': text,
                'folder_name': plan.slot_display,
            })

        runner = RestoreRunner(self.config, self.layout, self.captures, self.indexer, log)
        log(f"Restore plan: {len(plan.operations)} file(s), "
            f"{plan.replaces_count} replacing a file already in the library")

        ok = False
        message = 'Restore failed'
        summary: Dict = {}
        try:
            ok, message, summary = runner.run(plan, capture, progress)
        except Exception as error:  # noqa: BLE001 - must always release the queue
            message = f"Restore failed: {error}"
            log(message)
        finally:
            self._finish_restore(
                transfer_id, capture_id, capture, plan, ok, message, summary,
            )

    def _finish_restore(self, transfer_id: str, capture_id: str, capture: Dict,
                        plan, ok: bool, message: str, summary: Dict) -> None:
        now = datetime.now().isoformat()
        try:
            self.transfer_model.update(transfer_id, {
                'status': 'completed' if ok else 'failed',
                'progress': message,
                'end_time': now,
            })
        except Exception as error:  # noqa: BLE001 - the queue must still be released
            # Swallowed but never silent: the files are already where they
            # belong, and what is lost is the record saying so. A transfer stuck
            # showing 'running' with no explanation is what this used to leave.
            print(f"⚠️  Restore {transfer_id} finished but its status could not be "
                  f"recorded: {error}")

        # Record WHEN it was restored, and leave `status` alone: the files are
        # still in the backup tree, so the capture stays restorable and stays
        # subject to retention. Marking it 'restored' made a successful restore
        # its own last — the planner then refused to read files that were still
        # there, and retention skipped it forever.
        #
        # A partial restore is not recorded as one. Some files went back and
        # some did not, and the honest thing is to leave it looking un-restored
        # so it is obvious the run has to be repeated.
        if ok and not summary.get('failed'):
            try:
                self.captures.update(capture_id, {'restored_at': now})
            except Exception as error:  # noqa: BLE001 - the restore itself succeeded
                print(f"⚠️  Restore of {capture_id} succeeded but the restore time "
                      f"could not be recorded: {error}")

        self._emit('transfer_complete', {
            'transfer_id': transfer_id,
            'status': 'completed' if ok else 'failed',
            'message': message,
            'folder_name': plan.slot_display,
        })

        queue = getattr(self.coordinator, 'queue_manager', None)
        if queue is not None:
            try:
                queue.unregister_transfer(transfer_id, plan.target_dir)
            except Exception:  # noqa: BLE001
                pass

        with self._lock:
            self._restores_running.pop(capture_id, None)

        if ok and summary.get('captured'):
            self._apply_retention_quietly()

    def _emit(self, event: str, payload: Dict) -> None:
        if not self.socketio:
            return
        try:
            self.socketio.emit(event, payload)
        except Exception:  # noqa: BLE001
            pass

    # ---- captures ---------------------------------------------------------

    def set_pinned(self, capture_id: str, pinned: bool) -> Tuple[bool, str]:
        if not self.captures.get(capture_id):
            return False, 'Backup not found'
        self.captures.update(capture_id, {'pinned': 1 if pinned else 0})
        return True, 'Pinned' if pinned else 'Unpinned'

    def delete_capture(self, capture_id: str) -> Tuple[bool, str]:
        """
        Remove one version, files and index entry together.

        There is deliberately no way to drop the index entry alone. The tree is
        the source of truth and the index is derived from it, so a row removed
        without its files frees no space and comes straight back on the next
        rebuild — the entry looks deleted until it silently is not.
        """
        record = self.captures.get(capture_id)
        if not record:
            return False, 'Backup not found'

        ok, error = self._remove_capture_files(record)
        if not ok:
            return False, error

        self.captures.delete(capture_id)
        return True, 'Backup deleted'

    def _remove_capture_files(self, record: Dict) -> Tuple[bool, str]:
        """Remove one capture's folder and tidy the directories it emptied."""
        try:
            path = self.layout.absolute(record['capture_path'])
        except Exception as error:  # noqa: BLE001
            return False, f"Refusing to delete: {error}"
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass  # Already gone from disk; the index row still has to go.
        except OSError as error:
            return False, f"Could not remove the files: {error}"
        self.layout.prune_empty_dirs(path)
        return True, ''

    # ---- reclaiming space -------------------------------------------------

    def preview_delete(self, capture_ids: Optional[List[str]] = None,
                       slot_keys: Optional[List[str]] = None,
                       keep_newest: int = 0,
                       include_pinned: bool = False) -> Dict:
        """
        What a deletion would remove, and how much space it would free.

        Reads only. Deleting backups is the one action here with no undo — the
        files are the last copy of that version — so the count and the size go
        in front of the operator before anything happens.
        """
        selected, skipped_pinned = self._select_for_delete(
            capture_ids, slot_keys, keep_newest, include_pinned,
        )
        return {
            'captures': [
                {
                    'capture_id': c['capture_id'],
                    'display': self._display(c),
                    'captured_at': c.get('captured_at'),
                    'total_size': c.get('total_size') or 0,
                    'file_count': c.get('file_count') or 0,
                    'pinned': bool(c.get('pinned')),
                }
                for c in selected
            ],
            'count': len(selected),
            'total_size': sum(c.get('total_size') or 0 for c in selected),
            'skipped_pinned': skipped_pinned,
        }

    def delete_many(self, capture_ids: Optional[List[str]] = None,
                    slot_keys: Optional[List[str]] = None,
                    keep_newest: int = 0,
                    include_pinned: bool = False) -> Dict:
        """
        Remove several versions at once, reporting exactly what went.

        `keep_newest` lets a whole slot be cleared down to its most recent N
        versions in one action, which is the shape of "free some space but do
        not leave me with nothing".
        """
        selected, skipped_pinned = self._select_for_delete(
            capture_ids, slot_keys, keep_newest, include_pinned,
        )

        deleted, freed, errors = [], 0, []
        for record in selected:
            ok, error = self._remove_capture_files(record)
            if not ok:
                errors.append(f"{self._display(record)}: {error}")
                continue
            self.captures.delete(record['capture_id'])
            deleted.append(record['capture_id'])
            freed += record.get('total_size') or 0

        return {
            'deleted': deleted,
            'deleted_count': len(deleted),
            'reclaimed': freed,
            'skipped_pinned': skipped_pinned,
            'errors': errors,
        }

    def _select_for_delete(self, capture_ids: Optional[List[str]],
                           slot_keys: Optional[List[str]],
                           keep_newest: int,
                           include_pinned: bool) -> Tuple[List[Dict], int]:
        """
        Resolve a selection to the captures it names.

        Pinned versions are held back unless explicitly included — the whole
        point of a pin is that a sweep does not take it. How many were held back
        is reported rather than silently absorbed.
        """
        records: Dict[str, Dict] = {}

        if capture_ids:
            for record in self.captures.get_many(list(dict.fromkeys(capture_ids))):
                records[record['capture_id']] = record

        if slot_keys:
            for slot_key in dict.fromkeys(slot_keys):
                versions = self.captures.captures_for_slot(slot_key)
                # `captures_for_slot` is already newest first.
                for record in versions[max(0, keep_newest):]:
                    records[record['capture_id']] = record

        selected = list(records.values())
        if include_pinned:
            return selected, 0

        kept = [r for r in selected if not r.get('pinned')]
        return kept, len(selected) - len(kept)

    def clear_unsorted(self, include_pinned: bool = False) -> Dict:
        """
        Throw away everything that could not be identified.

        Offered as one action because the bucket is, by definition, files
        nothing can tell you anything about — and on a full disk that is the
        least painful thing to lose.

        Pinned captures are held back like everywhere else, and the count is
        reported. This used to force `include_pinned`, so the one sweep an
        operator could not narrow was also the only one that ignored a pin —
        and a pin on an unidentified file is the clearest possible statement
        that it is worth keeping until someone works out what it is.
        """
        return self.delete_many(
            capture_ids=[c['capture_id'] for c in self.captures.by_kind('unsorted', limit=100000)],
            include_pinned=include_pinned,
        )

    @staticmethod
    def _display(record: Dict) -> str:
        if record.get('kind') != 'slot':
            return record.get('capture_path') or record.get('capture_id', '')
        return SlotIdentity(
            library=record.get('library') or '',
            title=record.get('title') or '',
            season=record.get('season_number'),
            episode=record.get('episode_number'),
            year=record.get('release_year'),
        ).display

    # ---- index and housekeeping ------------------------------------------

    def rebuild_index(self) -> Dict:
        return self.indexer.rebuild().as_dict()

    def retention_preview(self, keep: Optional[int] = None,
                          grace_hours: Optional[int] = None) -> Dict:
        return self.retention.candidates(keep=keep, grace_hours=grace_hours).as_dict()

    def retention_apply(self, keep: Optional[int] = None,
                        grace_hours: Optional[int] = None) -> Dict:
        return self.retention.apply(keep=keep, grace_hours=grace_hours).as_dict()

    def save_retention(self, keep: Optional[int] = None,
                       grace_hours: Optional[int] = None,
                       enabled: Optional[bool] = None) -> Dict:
        """
        Persist the retention rule so it survives a restart.

        Written to `app_settings`, not to the env file — that is the only store
        that both survives a restart AND is visible to the background threads
        that actually apply the rule. A value in the Flask session would be
        invisible to them, and a value in the env file would need a redeploy.
        """
        return self.retention.save(keep=keep, grace_hours=grace_hours, enabled=enabled)

    def _apply_retention_quietly(self) -> None:
        """Run retention after a capture is added, reporting to the log only."""
        if not self.retention.enabled():
            return
        try:
            result = self.retention.apply()
        except Exception as error:  # noqa: BLE001
            print(f"⚠️  Backup retention failed: {error}")
            return
        if result.deleted:
            reclaimed_gb = result.reclaimed / 1e9
            print(
                f"🧹 Backup retention removed {len(result.deleted)} old version(s), "
                f"reclaiming {reclaimed_gb:.2f} GB"
            )
            self._emit('backup_retention', {
                'deleted': len(result.deleted),
                'reclaimed': result.reclaimed,
            })

    def migration_plan(self) -> Dict:
        report = self.migration.plan().as_dict()
        report['blocked'] = self._migration_blocker()
        return report

    def migration_apply(self) -> Dict:
        blocker = self._migration_blocker()
        if blocker:
            return {
                'applied': False, 'blocked': blocker, 'moved_count': 0,
                'removed_folders': 0, 'errors': [blocker],
                'moves': [], 'unidentified': [], 'empty_folders': [],
                'folders_seen': 0, 'move_count': 0, 'unidentified_count': 0,
                'empty_folder_count': 0, 'total_size': 0, 'warnings': [],
            }
        return self.migration.apply().as_dict()

    def _migration_blocker(self) -> Optional[str]:
        """
        Why migration must not run right now.

        A transfer that is running — or queued or paused, either of which can
        start writing at any moment — is using the same disk this is about to
        reorganise. The old folders are not going anywhere; waiting is free.

        The statuses are named here rather than trusting a helper. The first
        version of this called `get_active()`, whose name and docstring promised
        active transfers and whose body returned the entire table, so a database
        holding ten *completed* transfers reported ten still running.

        Not being able to answer the question blocks too. This is the guard in
        front of an operation that moves files across the whole backup disk, so
        "the database did not respond" has to mean wait, not proceed.
        """
        try:
            active = [
                transfer for transfer in self.transfer_model.get_active()
                if (transfer.get('status') or '') in _ACTIVE_STATUSES
            ]
        except Exception as error:  # noqa: BLE001 - cannot tell, so refuse
            return (
                f"Could not check whether any transfers are running ({error}). "
                'Migration moves files across the whole backup disk, so it only '
                'runs when the system is known to be idle.'
            )

        if not active:
            return None

        count = len(active)
        noun = 'transfer is' if count == 1 else 'transfers are'
        names = ', '.join(
            sorted({
                (t.get('folder_name') or t.get('transfer_id') or 'unknown')
                for t in active
            })[:3]
        )
        return (
            f"{count} {noun} still active ({names}). Migration moves files across "
            'the whole backup disk, so it waits until nothing is using it.'
        )
