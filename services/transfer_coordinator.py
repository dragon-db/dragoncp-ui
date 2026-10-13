#!/usr/bin/env python3
"""
DragonCP Transfer Coordinator
Main orchestrator that coordinates transfer, backup, webhook, and notification services
"""

import os
import time
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Import services
from services.backups import BackupsService
from services.backups.layout import BackupPathNotConfigured
from services.transfer_service import TransferService
from services.notification_service import NotificationService
from services.webhook_service import WebhookService
from services.auto_scanner import AutoScanner
from services.media_index import MediaIndex
from services.scheduler import SchedulerService
from services.alert_service import AlertService
from services.sync_engine.engine import SyncEngine
from models.alert import AlertStore
from models.sync_run import SyncRunStore
from services.sync_logger import log_sync, log_validation, log_state_change
from services.queue_manager import QueueManager
from services.path_service import PathService
from services.settings_service import SettingsService
from services.remote_daemon import RemoteDaemonService
from services.connectors import notify
from services.connectors.events import ACCENT_BLOCKED, WARNING, Event, Field

# The model owns the definition of "active"; importing it here keeps one list
# rather than two that can drift.
from models.transfer import Transfer as _Transfer


class TransferCoordinator:
    """Main coordinator that orchestrates all transfer-related operations"""
    
    def __init__(self, config, db_manager, socketio=None):
        print(f"🔄 Initializing TransferCoordinator")
        self.config = config
        self.db = db_manager
        self.socketio = socketio
        
        # Import models
        from models import (
            Transfer, Backup, BackupCapture, WebhookNotification,
            SeriesWebhookNotification, AppSettings,
        )

        # Initialize models
        self.transfer_model = Transfer(db_manager)
        self.backup_model = Backup(db_manager)
        self.capture_model = BackupCapture(db_manager)
        self.webhook_model = WebhookNotification(db_manager)
        self.series_webhook_model = SeriesWebhookNotification(db_manager)
        self.settings = AppSettings(db_manager)
        # Reads across both stores. Everything that used to reach for
        # `self.settings` with an ad-hoc env fallback goes through this, so
        # "which store does this live in" is answered in one place.
        self.settings_service = SettingsService(config, self.settings)
        
        # Initialize queue manager (must be before transfer service)
        self.queue_manager = QueueManager(self.transfer_model, socketio)
        
        # Initialize services
        self.path_service = PathService(config)
        # `backup_model` is the legacy per-transfer table. Nothing writes to it
        # any more; the migration reads it for provenance and that is all.
        self.backups = BackupsService(
            config, db_manager, self.capture_model, self.transfer_model,
            socketio=socketio, coordinator=self, settings=self.settings_service,
            legacy_backup_model=self.backup_model,
        )
        # The transfer server on the remote host — the fast route past SSH's own
        # speed limit. Built here rather than in the application so that the
        # transfers and the Settings panel share ONE instance: it caches the
        # health answer and holds the lock that stops an idle shutdown racing a
        # starting transfer, and neither works with two copies.
        self.remote_daemon = RemoteDaemonService(config, self.settings_service)

        self.transfer_service = TransferService(config, db_manager, self.transfer_model, socketio, self.queue_manager,
                                                remote_daemon=self.remote_daemon)
        self.notification_service = NotificationService(config, self.settings_service, self.transfer_model, self.webhook_model, self.series_webhook_model)
        self.webhook_service = WebhookService(config, self.webhook_model, self.series_webhook_model, self)

        # The title index: one row per film or series, keyed by the identifier
        # the service will not change. Built here so the engine, the webhook
        # path and the auto-scanner all read and write the same instance.
        self.media_index = MediaIndex(db_manager, config=config)

        # Everything that needs a person — the Notifications tab.
        self.alerts = AlertService(AlertStore(db_manager), socketio)

        # The sync engine: the one pipeline every sync goes through. Built
        # here because it hands transfers to this coordinator's queue; started
        # by `start_background()`, once the connector layer is up, so what it
        # finds on start-up can be announced.
        self.sync_engine = SyncEngine(
            SyncRunStore(db_manager), coordinator=self, media_index=self.media_index,
            settings=self.settings_service, socketio=socketio, alerts=self.alerts,
            config=config)
        self.alerts.engine = self.sync_engine

        # The scheduled auto-scanner — what a webhook never delivered — and the
        # scheduler that runs it. One scheduler for everything DragonCP does on
        # a clock; this release gives it the Sonarr and Radarr auto-scanners.
        self.auto_scanner = AutoScanner(db_manager, self.media_index, self.sync_engine,
                                        config, alerts=self.alerts)
        self.scheduler = SchedulerService(db_manager, alerts=self.alerts)
        for job in self.auto_scanner.jobs():
            self.scheduler.register(job)
        self.alerts.scheduler = self.scheduler
        self.queue_manager.set_coordinator(self)

        print(f"✅ TransferCoordinator initialized")

        # Clean up stale transfer tracking before resuming. Nothing is started
        # here: the sync engine first looks at what the restart interrupted
        # (`start_background`), then the queue moves on.
        self.queue_manager.force_unregister_stale_transfers(promote=False)

        # Resume any transfers that were running when the app was stopped. Their
        # completion watchers start in `start_background()`: a watcher that
        # finds its transfer already ended announces the result, and before the
        # connector layer exists that announcement goes nowhere.
        self._resumed_transfer_ids = self.transfer_service.resume_active_transfers()
        self._background_started = False

    def start_background(self) -> None:
        """Start the work that runs on its own: watchers and the sync engine.

        Called once, after the connector layer is configured, so that what a
        restart finds — a transfer that failed while DragonCP was down, a batch
        that was waiting — is announced rather than dropped.
        """
        if self._background_started:
            return
        self._background_started = True
        # Recovery first. A completion watcher that finds its transfer already
        # ended releases its queue slot, and releasing a slot starts the next
        # queued transfer — which recovery would then take for one a restart
        # cut off. So the engine looks before anything is allowed to move.
        self.sync_engine.start()
        import threading
        for transfer_id in self._resumed_transfer_ids or []:
            threading.Thread(
                target=self._post_transfer_completion,
                args=(transfer_id,),
                daemon=True
            ).start()
        # After recovery: a transfer started now goes through the engine's
        # hooks like any other, instead of being mistaken for an interrupted one.
        self.queue_manager.promote_waiting()
        self.scheduler.start()

    def _hook(self, name: str, *args) -> None:
        """Tell the sync engine about a transfer's lifecycle. Never raises."""
        engine = getattr(self, 'sync_engine', None)
        if engine is None:
            return
        try:
            getattr(engine, name)(*args)
        except Exception as error:  # noqa: BLE001 - bookkeeping must not break a transfer
            print(f"⚠️  Sync engine hook {name} failed: {error}")
            import traceback
            traceback.print_exc()
    
    # Transfer Operations
    def start_transfer(self, transfer_id: str, source_path: str, dest_path: str,
                      operation_type: str = "folder", media_type: str = "",
                      folder_name: str = "", season_name: str = None,
                      is_simulation: bool = False,
                      simulation_bwlimit: int = None,
                      extra_fields: Dict = None) -> Tuple[bool, str]:
        """
        Start a new transfer with database persistence and queue management

        extra_fields is merged into the transfer row on whichever path it takes
        (running, path-queued or slot-queued). Explore uses it to attach the
        approved file list, so a promoted or restarted run rebuilds the same
        command instead of falling back to a whole-directory mirror.

        Returns tuple of (success, status_code)
        """
        extra_fields = extra_fields or {}
        
        log_sync("TransferCoordinator", f"start_transfer() called", 
                icon="🎯", transfer_id=transfer_id)
        log_sync("TransferCoordinator", f"dest_path: {dest_path}", 
                icon="📁", transfer_id=transfer_id, indent=1)
        
        # STRICT VALIDATION: Check for duplicate destination BEFORE creating transfer
        log_sync("TransferCoordinator", f"Checking for duplicate destination...", 
                icon="🔍", transfer_id=transfer_id)
        is_duplicate, existing_transfer_id = self.queue_manager.check_duplicate_destination(dest_path, transfer_id)
        log_sync("TransferCoordinator", f"is_duplicate={is_duplicate}, existing={existing_transfer_id}", 
                icon="📋", transfer_id=transfer_id, indent=1)
        
        if is_duplicate:
            print(f"🚫 PATH CONFLICT DETECTED - QUEUING!")
            print(f"   Transfer {transfer_id} -> {dest_path}")
            print(f"   Existing transfer {existing_transfer_id} already syncing to this path")
            
            # Get the existing transfer details for a better message
            existing_transfer = self.transfer_model.get(existing_transfer_id)
            if existing_transfer:
                existing_title = existing_transfer.get('parsed_title') or existing_transfer.get('folder_name') or 'Unknown'
                if existing_transfer.get('season_name'):
                    existing_info = f"{existing_title} - {existing_transfer['season_name']}"
                else:
                    existing_info = existing_title
                queue_message = f'Queued: Waiting for "{existing_info}" to complete (same destination path)'
            else:
                queue_message = f'Queued: Waiting for path to be available: {dest_path}'
            
            # Create transfer record with 'queued' status (will be promoted when path is free)
            transfer_data = {
                'transfer_id': transfer_id,
                'media_type': media_type,
                'folder_name': folder_name,
                'season_name': season_name,
                'source_path': source_path,
                'dest_path': dest_path,
                'operation_type': operation_type,
                'status': 'queued',  # Changed from 'duplicate' to 'queued'
                'progress': queue_message,
                'queue_reason': 'path',  # Explicit tracking: 'path' or 'slot'
                'start_time': datetime.now().isoformat(),  # Track when queued
                'is_simulation': is_simulation,
                'simulation_bwlimit': simulation_bwlimit
            }
            
            transfer_data.update(extra_fields)
            self.transfer_model.create(transfer_data)
            
            # Update webhook notification status to QUEUED_PATH if this is from a webhook
            # This will be handled by the calling service (webhook_service or auto_sync_scheduler)
            
            print(f"✅ Transfer {transfer_id} queued (QUEUED_PATH) - will start when path is free")
            
            # Emit WebSocket notification
            if self.socketio:
                self.socketio.emit('transfer_queued', {
                    'transfer_id': transfer_id,
                    'status': 'queued',
                    'queue_type': 'path',
                    'existing_transfer_id': existing_transfer_id,
                    'dest_path': dest_path,
                    'message': queue_message
                })
            
            return (True, 'QUEUED_PATH')  # Transfer queued due to path conflict
        
        # Register transfer with queue manager
        print(f"📝 Registering transfer with queue manager...")
        can_start, queue_status = self.queue_manager.register_transfer(transfer_id, dest_path)
        print(f"   can_start: {can_start}, queue_status: {queue_status}")
        
        # If queued, create record with 'queued' status and return
        if queue_status == 'queued':
            transfer_data = {
                'transfer_id': transfer_id,
                'media_type': media_type,
                'folder_name': folder_name,
                'season_name': season_name,
                'source_path': source_path,
                'dest_path': dest_path,
                'operation_type': operation_type,
                'status': 'queued',
                'progress': 'Waiting in queue...',
                'queue_reason': 'slot',  # Explicit tracking: 'path' or 'slot'
                'is_simulation': is_simulation,
                'simulation_bwlimit': simulation_bwlimit
            }
            
            transfer_data.update(extra_fields)
            self.transfer_model.create(transfer_data)
            print(f"⏳ Transfer {transfer_id} added to queue")
            
            # Emit WebSocket notification
            if self.socketio:
                self.socketio.emit('transfer_queued', {
                    'transfer_id': transfer_id,
                    'message': 'Transfer added to queue'
                })
            
            return (True, 'QUEUED_SLOT')  # Transfer queued due to slot limit
        
        # If can start immediately, create with 'pending' status and start transfer
        if can_start:
            print(f"✅ Can start immediately, creating transfer record...")
            # Create transfer record with 'pending' status (will be updated to 'running' by start_rsync_process)
            transfer_data = {
                'transfer_id': transfer_id,
                'media_type': media_type,
                'folder_name': folder_name,
                'season_name': season_name,
                'source_path': source_path,
                'dest_path': dest_path,
                'operation_type': operation_type,
                'status': 'pending',
                'is_simulation': is_simulation,
                'simulation_bwlimit': simulation_bwlimit
            }
            
            transfer_data.update(extra_fields)
            self.transfer_model.create(transfer_data)
            print(f"✅ Transfer record created with status 'pending'")
            
            # Where rsync sends anything this transfer displaces.
            backup_dir = self._staging_dir(transfer_id)
            if backup_dir is None:
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': (
                        'BACKUP_PATH is not configured. Set it before syncing — a '
                        'sync can replace or delete files, and without a backup '
                        'location those copies cannot be recovered.'
                    ),
                })
                self.queue_manager.unregister_transfer(transfer_id, dest_path)
                return (False, 'failed')
            print(f"📁 Backup staging dir: {backup_dir}")

            # Start the actual transfer process. The engine flips its run to
            # "copying" first, so a webhook arriving from here on goes to the
            # follow-up batch rather than into a copy that may have started.
            print(f"🚀 Calling start_rsync_process...")
            self._hook('before_transfer_start', transfer_id)
            success = self.transfer_service.start_rsync_process(transfer_id, source_path, dest_path, operation_type, backup_dir)
            print(f"   start_rsync_process returned: {success}")

            if success:
                self._hook('on_transfer_started', transfer_id)
                # Start a thread to finalize backup and send notifications after completion
                import threading
                threading.Thread(
                    target=self._post_transfer_completion, 
                    args=(transfer_id,), 
                    daemon=True
                ).start()
                return (True, 'running')  # Transfer started successfully
            else:
                # If failed to start, unregister from queue manager
                self.queue_manager.unregister_transfer(transfer_id)
                # No rsync means no completion watcher, so nothing else would
                # ever let the transfer server go.
                self._release_fast_route()
                return (False, 'failed')  # Failed to start
        
        return (False, 'failed')  # Shouldn't reach here, but return failure
    
    def _transfers_still_active(self) -> bool:
        """
        Whether any transfer still needs the remote host.

        Counts pending and queued as well as running: a queued transfer is one
        that will want the transfer server within seconds, and stopping it in
        between only to start it again is churn for nothing.
        """
        try:
            active = self.transfer_model.get_all(
                statuses=['running', 'queued', 'pending'], include_logs=False)
            # Simulations copy fixture files on this machine and never touch the
            # remote host, so counting one as demand held the transfer server
            # open for work that could not possibly use it.
            return any(not row.get('is_simulation') for row in active)
        except Exception as error:  # noqa: BLE001
            # Unsure means leave it running. A transfer server left up costs a
            # listening port; one stopped underneath a running transfer costs
            # the transfer.
            print(f"⚠️  Could not check for active transfers: {error}")
            return True

    def _release_fast_route(self) -> None:
        """Let the transfer server stop if it is meant to run only on demand."""
        try:
            self.remote_daemon.release(self._transfers_still_active)
        except Exception as error:  # noqa: BLE001 - housekeeping only
            print(f"⚠️  Could not release the transfer server: {error}")

    def _post_transfer_completion(self, transfer_id: str):
        """Wait for transfer to complete, then finalize backup and send notifications"""
        # Poll until transfer is no longer running
        max_wait = 24 * 60 * 60  # 24 hours max wait
        waited = 0
        check_interval = 5  # Check every 5 seconds
        
        while waited < max_wait:
            transfer = self.transfer_model.get(transfer_id)
            if not transfer or transfer['status'] not in ['running', 'pending']:
                # Transfer completed or failed
                status = transfer['status'] if transfer else 'unknown'
                dest_path = transfer.get('dest_path') if transfer else None

                if status == 'paused':
                    # A pause is not an outcome. Release the slot and the
                    # destination so queued work can proceed, but leave webhook
                    # state and backup records alone - resume_transfer() starts
                    # a fresh watcher that finalizes them when it really ends.
                    print(f"⏸️  Transfer {transfer_id} paused, releasing queue slot")
                    self.queue_manager.unregister_transfer(transfer_id, dest_path)
                    # A pause can last hours. Leaving the transfer server up for
                    # all of it is exactly what "only while transfers run" is
                    # supposed to prevent, and resuming starts it again anyway.
                    self._release_fast_route()
                    break

                # Unregister from queue manager (will promote next queued transfer)
                # Pass dest_path for path-specific queue promotion
                print(f"🏁 Transfer {transfer_id} finished with status: {status}")
                self.queue_manager.unregister_transfer(transfer_id, dest_path)

                if transfer and transfer.get('sync_run_id') and getattr(self, 'sync_engine', None):
                    # The pipeline's Finish and Tell stages: webhooks marked,
                    # the outcome announced, alerts opened, follow-ups told.
                    self._hook('on_transfer_finished', transfer_id, status)
                else:
                    # A transfer from before the engine existed — finished the
                    # way it would have been then.
                    self.webhook_service.update_webhook_transfer_status(transfer_id, status, self.transfer_model)
                    if status in ['completed', 'failed']:
                        try:
                            self.notification_service.send_discord_notification(transfer_id, status)
                        except Exception as de:
                            print(f"⚠️  Discord notification error for {transfer_id}: {de}")
                
                # File whatever this transfer displaced into the backup tree,
                # index it, and apply retention. A transfer that displaced
                # nothing finds an empty staging folder and creates nothing.
                try:
                    summary = self.backups.sort_after_transfer(transfer_id)
                    if summary.get('captures'):
                        print(
                            f"💾 Backed up {summary['files']} file(s) into "
                            f"{summary['captures']} version(s)"
                        )
                    for error in summary.get('errors', []):
                        print(f"⚠️  Backup sorting: {error}")
                except Exception as be:
                    print(f"⚠️  Backup sorting error for {transfer_id}: {be}")

                # Switch the transfer server off if nothing else needs it. Done
                # last, and after the queue has had its chance to promote the
                # next transfer, so a queue that is still working keeps it.
                self._release_fast_route()

                break
            
            time.sleep(check_interval)
            waited += check_interval
    
    def cancel_transfer(self, transfer_id: str) -> bool:
        """Cancel a running or queued transfer"""
        before = self.transfer_model.get(transfer_id) or {}
        result = self.transfer_service.cancel_transfer(transfer_id)

        # Unregister from queue manager if it was running
        if result:
            self.queue_manager.unregister_transfer(transfer_id)
            # A queued or paused transfer has no completion watcher, so nothing
            # else would ever close its run.
            if before.get('status') in ('queued', 'paused', 'pending'):
                self._hook('on_transfer_finished', transfer_id, 'cancelled')

        return result
    
    def pause_transfer(self, transfer_id: str) -> Tuple[bool, str]:
        """
        Pause a running transfer and release its queue slot.

        The slot is released here rather than left to _post_transfer_completion,
        which only polls every few seconds - a resume issued inside that window
        would otherwise be told the queue is full and be needlessly queued.
        Unregistering twice is harmless, so the watcher can still run.
        """
        transfer = self.transfer_model.get(transfer_id)
        dest_path = transfer.get('dest_path') if transfer else None

        success, message = self.transfer_service.pause_transfer(transfer_id)

        if success:
            self.queue_manager.unregister_transfer(transfer_id, dest_path)
            self._hook('on_transfer_paused', transfer_id)

        return success, message

    def resume_transfer(self, transfer_id: str) -> Tuple[bool, str]:
        """
        Resume a paused transfer.

        Goes back through the queue manager rather than starting rsync directly,
        so a resume respects the concurrency limit and cannot collide with a
        transfer that claimed the same destination while this one was paused.
        """
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False, 'Transfer not found'

        if transfer['status'] != 'paused':
            return False, f"Only paused transfers can be resumed (currently {transfer['status']})"

        can_start, queue_status = self.queue_manager.register_transfer(
            transfer_id, transfer['dest_path']
        )

        if queue_status == 'duplicate':
            return False, 'Another transfer is already syncing to this destination'

        if queue_status == 'queued':
            self.transfer_model.update(transfer_id, {
                'status': 'queued',
                'progress': 'Resumed - waiting in queue...',
                'queue_reason': 'slot',
                'paused_at': None
            })
            print(f"⏳ Resumed transfer {transfer_id} added to queue")

            if self.socketio:
                self.socketio.emit('transfer_queued', {
                    'transfer_id': transfer_id,
                    'message': 'Resumed transfer added to queue'
                })

            self._hook('on_transfer_resumed', transfer_id, 'queued')
            return True, 'Transfer resumed and queued'

        if not can_start:
            return False, f'Could not resume transfer ({queue_status})'

        self.transfer_model.update(transfer_id, {
            'status': 'pending',
            'progress': 'Resuming transfer...',
            'paused_at': None,
            'end_time': None
        })

        backup_dir = self._staging_dir(transfer_id)
        if backup_dir is None:
            self.transfer_model.update(transfer_id, {
                'status': 'paused',
                'progress': 'BACKUP_PATH is not configured; refusing to resume',
                'paused_at': datetime.now().isoformat(),
            })
            self.queue_manager.unregister_transfer(transfer_id, transfer['dest_path'])
            return False, 'BACKUP_PATH is not configured; refusing to resume'

        transfer = self.transfer_model.get(transfer_id)
        self._hook('on_transfer_resumed', transfer_id, 'running')
        self._hook('before_transfer_start', transfer_id)
        success = self.transfer_service.start_rsync_process(
            transfer_id,
            transfer['source_path'],
            transfer['dest_path'],
            transfer['operation_type'],
            backup_dir
        )
        if success:
            self._hook('on_transfer_started', transfer_id)

        if not success:
            # The row was set to 'pending' above. Leaving it there strands the
            # transfer: no monitor was started, the queue slot is about to be
            # released, and 'pending' counts as active - so it sits in Activity
            # forever, and cancel_transfer has no branch for it. Put it back to
            # paused, which is both true and retryable: the partial files are
            # still on disk and resume can be tried again.
            self.transfer_model.update(transfer_id, {
                'status': 'paused',
                'progress': 'Resume failed - partial files kept, try again',
                'paused_at': datetime.now().isoformat()
            })
            self.queue_manager.unregister_transfer(transfer_id, transfer['dest_path'])
            # Its sync was told the copy was starting; it is paused again.
            self._hook('on_transfer_paused', transfer_id,
                       'Resuming could not start rsync. The partial files are kept; '
                       'resume again to continue.')
            return False, 'Failed to resume transfer'

        import threading
        threading.Thread(
            target=self._post_transfer_completion,
            args=(transfer_id,),
            daemon=True
        ).start()

        return True, 'Transfer resumed'

    def restart_transfer(self, transfer_id: str) -> bool:
        """Restart a failed or cancelled transfer — through the pipeline.

        A restart used to start rsync directly, skipping the queue: no folder
        check, no slot limit, and no watcher, so nothing announced the result.
        It is a run of its own now (safety check, then the queue), see
        `SyncEngine.restart_transfer`.
        """
        return self.sync_engine.restart_transfer(transfer_id).ok

    def _path_queue_message(self, existing_transfer_id: Optional[str], dest_path: str) -> str:
        existing_transfer = self.transfer_model.get(existing_transfer_id) if existing_transfer_id else None
        if existing_transfer:
            existing_title = existing_transfer.get('parsed_title') or existing_transfer.get('folder_name') or 'Unknown'
            if existing_transfer.get('season_name'):
                existing_info = f"{existing_title} - {existing_transfer['season_name']}"
            else:
                existing_info = existing_title
            return f'Queued: Waiting for "{existing_info}" to complete (same destination path)'
        return f'Queued: Waiting for path to be available: {dest_path}'

    def requeue_transfer(self, transfer_id: str, sync_run_id: Optional[str] = None) -> Tuple[bool, str]:
        """Run an existing transfer row again, through the queue.

        The same folder check and slot limit a new transfer gets, and the same
        completion watcher afterwards. rsync picks up its partial files, so a
        retry continues rather than starts over.
        """
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False, 'missing'
        if transfer.get('status') in ('queued', 'pending', 'running', 'paused'):
            # Already on its way: a second request must not start a second rsync.
            return False, 'already_active'
        dest_path = transfer['dest_path']
        reset = {
            'rsync_process_id': None, 'end_time': None, 'paused_at': None,
            'start_time': datetime.now().isoformat(), 'progress_percent': 0,
            'bytes_transferred': 0, 'speed_bps': 0, 'eta_seconds': None,
        }
        if sync_run_id:
            reset['sync_run_id'] = sync_run_id

        is_duplicate, existing_transfer_id = self.queue_manager.check_duplicate_destination(
            dest_path, transfer_id)
        if is_duplicate:
            self.transfer_model.update(transfer_id, {
                **reset, 'status': 'queued', 'queue_reason': 'path',
                'progress': self._path_queue_message(existing_transfer_id, dest_path)})
            return True, 'QUEUED_PATH'

        can_start, queue_status = self.queue_manager.register_transfer(transfer_id, dest_path)
        if queue_status == 'queued':
            self.transfer_model.update(transfer_id, {
                **reset, 'status': 'queued', 'queue_reason': 'slot',
                'progress': 'Waiting in queue...'})
            return True, 'QUEUED_SLOT'
        if not can_start:
            return False, queue_status

        self.transfer_model.update(transfer_id, {**reset, 'status': 'pending',
                                                 'progress': 'Restarting transfer...'})
        backup_dir = self._staging_dir(transfer_id)
        if backup_dir is None:
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': 'BACKUP_PATH is not configured; refusing to restart',
                'end_time': datetime.now().isoformat()})
            self.queue_manager.unregister_transfer(transfer_id, dest_path)
            return False, 'failed'

        self._hook('before_transfer_start', transfer_id)
        success = self.transfer_service.start_rsync_process(
            transfer_id, transfer['source_path'], dest_path,
            transfer['operation_type'], backup_dir)
        if not success:
            self.queue_manager.unregister_transfer(transfer_id, dest_path)
            self._release_fast_route()
            return False, 'failed'
        self._hook('on_transfer_started', transfer_id)
        import threading
        threading.Thread(target=self._post_transfer_completion, args=(transfer_id,),
                         daemon=True).start()
        return True, 'running'

    def _staging_dir(self, transfer_id: str) -> Optional[str]:
        """
        Where rsync sends what a transfer displaces, or None when there is
        nowhere safe to send it.

        Returning None rather than falling back is the point. Writing displaced
        media to a temporary directory the OS may clear, while restore refuses
        to read from anywhere but a configured BACKUP_PATH, is what made
        backups look like they worked and be unrecoverable.
        """
        try:
            return self.backups.staging_dir(transfer_id)
        except BackupPathNotConfigured as error:
            print(f"🛑 {error}")
            return None
        except Exception as error:  # noqa: BLE001
            print(f"🛑 Could not prepare the backup staging directory: {error}")
            return None
    
    def get_transfer_status(self, transfer_id: str) -> Optional[Dict]:
        """Get transfer status from database"""
        return self.transfer_model.get(transfer_id)
    
    def get_all_transfers(self, limit: int = 50, status_filter: str = None,
                          search: str = None, offset: int = 0,
                          statuses: List[str] = None) -> List[Dict]:
        """Get all transfers from database (listing only - no log bodies)"""
        return self.transfer_model.get_all(
            limit=limit, status_filter=status_filter, include_logs=False,
            search=search, offset=offset, statuses=statuses
        )

    def count_transfers(self, status_filter: str = None, search: str = None,
                        statuses: List[str] = None) -> int:
        """How many transfers match a filter, ignoring the page window."""
        return self.transfer_model.count(
            status_filter=status_filter, search=search, statuses=statuses
        )
    
    #: Kept as an attribute because callers reference it; the definition lives
    #: on the model so there is one list, not two that can drift apart.
    ACTIVE_STATUSES = list(_Transfer.ACTIVE_STATUSES)

    def get_active_transfers(self) -> List[Dict]:
        """Get active transfers (running/pending/queued/paused)"""
        return self.transfer_model.get_active()
    
    def start_queued_transfer(self, transfer_id: str) -> bool:
        """
        Start a queued transfer (called by queue manager when promoting)
        """
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False

        registered, register_status = self.queue_manager.ensure_running_transfer_registered(
            transfer_id,
            transfer['dest_path']
        )
        if not registered:
            print(f"⚠️  Cannot start queued transfer {transfer_id}: queue state not ready ({register_status})")
            return False

        # Update status from 'queued' to 'pending' before starting
        # (start_rsync_process will update it to 'running')
        self.transfer_model.update(transfer_id, {
            'status': 'pending',
            'progress': 'Starting transfer...'
        })
        
        # Update ALL webhook notifications linked to this transfer from QUEUED_* to 'syncing'
        # This ensures all batched episodes transition together
        if transfer.get('media_type') in ['anime', 'tvshows', 'series']:
            # Use transfer_id to update all linked notifications at once
            updated_count = self.series_webhook_model.update_notifications_by_transfer_id(
                transfer_id,
                {
                    'status': 'syncing',
                    'completed_at': datetime.now().isoformat()
                }
            )
            if updated_count > 0:
                print(f"📋 Updated {updated_count} notification(s) linked to transfer {transfer_id} to SYNCING (transfer starting)")
        
        # Refresh transfer data after update
        transfer = self.transfer_model.get(transfer_id)

        # Where rsync sends anything this transfer displaces.
        backup_dir = self._staging_dir(transfer_id)
        if backup_dir is None:
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': 'BACKUP_PATH is not configured; refusing to start',
                'end_time': datetime.now().isoformat(),
            })
            self.queue_manager.unregister_transfer(transfer_id, transfer.get('dest_path'))
            self._start_failed(transfer_id)
            return False

        # Start the transfer
        self._hook('before_transfer_start', transfer_id)
        success = self.transfer_service.start_rsync_process(
            transfer_id,
            transfer['source_path'],
            transfer['dest_path'],
            transfer['operation_type'],
            backup_dir
        )

        if success:
            self._hook('on_transfer_started', transfer_id)
            # Start post-completion thread
            import threading
            threading.Thread(
                target=self._post_transfer_completion,
                args=(transfer_id,),
                daemon=True
            ).start()
        else:
            # If failed to start, unregister from queue manager
            self.queue_manager.unregister_transfer(transfer_id)
            # Same as the first start path: no rsync, no watcher, so release here.
            self._release_fast_route()
            self._start_failed(transfer_id)

        return success

    def _start_failed(self, transfer_id: str) -> None:
        """A transfer the queue let through could not start: tell its sync.

        Started from the queue, nobody is waiting on the answer, and with no
        rsync there is no completion watcher either. Without this the sync sat
        at Queued or Copying for good, with no alert and a Retry that could
        not get past it.
        """
        row = self.transfer_model.get(transfer_id) or {}
        if row.get('status') != 'failed':
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': row.get('progress') or 'The transfer could not start',
                'end_time': datetime.now().isoformat(),
            })
        if row.get('sync_run_id') and getattr(self, 'sync_engine', None):
            self._hook('on_transfer_finished', transfer_id, 'failed')
            return
        # Queued before the sync engine existed: closed the way the completion
        # watcher closes such a transfer, so its episodes stop reading syncing.
        try:
            self.webhook_service.update_webhook_transfer_status(
                transfer_id, 'failed', self.transfer_model)
            self.notification_service.send_discord_notification(transfer_id, 'failed')
        except Exception as error:  # noqa: BLE001 - bookkeeping must not break the queue
            print(f"⚠️  Could not close {transfer_id} after it failed to start: {error}")
    
    def get_queue_status(self) -> Dict:
        """Get current queue status"""
        return self.queue_manager.get_queue_status()
    
    # Backup Operations — see services/backups/. The coordinator holds the
    # service so routes and Explore can reach it; it delegates nothing itself.

    # Webhook Operations
    def parse_webhook_data(self, webhook_json: Dict) -> Dict:
        """Parse webhook JSON data for movies"""
        return self.webhook_service.parse_webhook_data(webhook_json)
    
    def parse_series_webhook_data(self, webhook_json: Dict, media_type: str) -> Dict:
        """Parse series/anime webhook JSON data"""
        return self.webhook_service.parse_series_webhook_data(webhook_json, media_type)
    
    def trigger_webhook_sync(self, notification_id: str) -> Tuple[bool, str]:
        """Trigger sync for a webhook notification (movies)"""
        return self.webhook_service.trigger_webhook_sync(notification_id)
    
    def sync_notification_group(self, notification_ids: List[str]) -> Tuple[bool, str, List[str]]:
        """Sync a group of episode notifications as one transfer per season."""
        return self.webhook_service.sync_notification_group(notification_ids)

    def trigger_series_webhook_sync(self, notification_id: str, batched_notification_ids: List[str] = None) -> Tuple[bool, str]:
        """Trigger sync for a series/anime webhook notification"""
        return self.webhook_service.trigger_series_webhook_sync(notification_id, batched_notification_ids)
    
    def update_webhook_transfer_status(self, transfer_id: str, status: str):
        """Update webhook notification status based on transfer completion"""
        self.webhook_service.update_webhook_transfer_status(transfer_id, status, self.transfer_model)
    
    # Notification Operations
    def parse_transfer_logs(self, logs: List[str]) -> Dict:
        """Parse rsync transfer logs to extract transfer statistics"""
        return self.notification_service.parse_transfer_logs(logs)
    
    def send_discord_notification(self, transfer_id: str, transfer_status: str):
        """Send Discord webhook notification for completed transfer"""
        self.notification_service.send_discord_notification(transfer_id, transfer_status)
    
    # Auto-Sync Operations
    def index_notification(self, table: str, notification_id: str, media_type: str = '') -> None:
        """Fold a webhook's title into the index so the engine can ask about it.

        Nothing here reaches the network and nothing here can stop a sync: a
        failure leaves the index unchanged and the engine falls back to the
        fixed timer.
        """
        try:
            if table == 'sonarr_webhook':
                notification = self.series_webhook_model.get(notification_id)
                if notification:
                    self.media_index.record_series_notification(notification, media_type)
            else:
                notification = self.webhook_model.get(notification_id)
                if notification:
                    self.media_index.record_movie_notification(notification)
        except Exception as exc:  # noqa: BLE001 - indexing must never block a sync
            print(f"⚠️  Could not index {notification_id}: {exc}")

    def perform_dry_run_validation(self, notification: Dict) -> Dict:
        """
        Perform dry-run validation for series/anime sync
        Returns validation results with safety status
        """
        try:
            # Extract media type and paths
            media_type = notification['media_type']
            series_path = notification.get('series_path')
            season_path = notification.get('season_path')
            season_number = notification.get('season_number')
            
            # Determine source path - prefer the actual season_path from webhook
            # (extracted from real episode file path on remote server)
            if season_path:
                # PRIMARY: Use the actual season path from webhook notification
                # This is extracted from the episode file path and represents the real folder on disk
                source_path = season_path
                print(f"📁 Using actual season_path from webhook: {source_path}")
            elif series_path and season_number is not None:
                # FALLBACK: Reconstruct season path if season_path is not available
                # This is a fallback only, assumes Sonarr's standard "Season XX" format
                source_path = f"{series_path.rstrip('/')}/Season {season_number:02d}"
                print(f"⚠️  season_path not in notification, reconstructed: {source_path}")
            elif series_path:
                # Whole series sync (rare case, no season specified)
                source_path = series_path
                print(f"📁 Using series_path for whole series sync: {source_path}")
            else:
                return {
                    'safe_to_sync': False,
                    'reason': 'Missing series_path and season_path in notification',
                    'deleted_count': 0,
                    'incoming_count': 0,
                    'server_file_count': 0,
                    'local_file_count': 0,
                    'deleted_files': [],
                    'incoming_files': []
                }
            
            # Use PathService to construct destination path consistently
            # This ensures dry-run uses the same path as actual sync
            try:
                dest_path = self.path_service.get_destination_path(source_path, media_type)
            except ValueError as e:
                return {
                    'safe_to_sync': False,
                    'reason': str(e),
                    'deleted_count': 0,
                    'incoming_count': 0,
                    'server_file_count': 0,
                    'local_file_count': 0,
                    'deleted_files': [],
                    'incoming_files': []
                }
            
            print(f"🔍 Dry-run validation:")
            print(f"   Source (server): {source_path}")
            print(f"   Destination (local): {dest_path}")
            
            # Perform dry-run using transfer service
            validation_result = self.transfer_service.perform_dry_run_rsync(
                source_path=source_path,
                dest_path=dest_path
            )
            
            # Store dry-run result in notification
            self.series_webhook_model.update(notification['notification_id'], {
                'dry_run_result': json.dumps(validation_result),
                'dry_run_performed_at': datetime.now().isoformat()
            })
            
            return validation_result
            
        except Exception as e:
            print(f"❌ Error performing dry-run validation: {e}")
            import traceback
            traceback.print_exc()
            return {
                'safe_to_sync': False,
                'reason': f'Validation error: {str(e)}',
                'deleted_count': 0,
                'incoming_count': 0,
                'server_file_count': 0,
                'local_file_count': 0,
                'deleted_files': [],
                'incoming_files': []
            }
    
    def mark_for_manual_sync(self, notification_id: str, reason: str, validation_result: Dict = None):
        """Mark a notification as requiring manual sync"""
        updates = {
            'status': 'pending',  # Keep as pending but flag for manual sync
            'requires_manual_sync': 1,
            'manual_sync_reason': reason
        }
        
        # Store validation result if provided
        if validation_result:
            updates['dry_run_result'] = json.dumps(validation_result)
            updates['dry_run_performed_at'] = datetime.now().isoformat()
        
        self.series_webhook_model.update(notification_id, updates)
        print(f"⚠️  Marked {notification_id} for manual sync: {reason}")
    
    def send_manual_sync_discord_alert(self, notification: Dict, validation_result: Dict):
        """Announce that an automatic sync refused and wants a person.

        The most consequential message this app sends: something was going to
        run by itself, looked wrong, and stopped. Nobody is watching the screen
        when it happens, which is the entire reason it is pushed.
        """
        try:
            media_type = notification['media_type']
            series_title = notification['series_title']
            season_number = notification['season_number']
            season_path = notification['season_path']

            notify(Event(
                key='autosync.blocked',
                severity=WARNING,
                accent=ACCENT_BLOCKED,
                title=f"**{series_title}** - Season {season_number}",
                summary='Media Type: ' + media_type.upper(),
                fields=(
                    Field('Season Path', season_path, monospace=True),
                    Field('Reason', validation_result['reason']),
                    Field(
                        'File Analysis',
                        f"Server Files: {validation_result.get('server_file_count', 0)}\n"
                        f"Local Files: {validation_result.get('local_file_count', 0)}\n"
                        f"Would Delete: {validation_result.get('deleted_count', 0)} media files\n"
                        f"Would Add: {validation_result.get('incoming_count', 0)} media files",
                        monospace=True,
                    ),
                ),
                author='Manual Sync Alert ⚠️',
                footer='DRAGONCP Auto-Sync Safety Check',
                context={'media_type': media_type},
            ))

        except Exception as e:
            print(f"❌ Error announcing the manual sync alert: {e}")
            import traceback
            traceback.print_exc()
