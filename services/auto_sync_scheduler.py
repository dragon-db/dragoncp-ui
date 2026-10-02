#!/usr/bin/env python3
"""
DragonCP Auto-Sync Scheduler Service
Manages scheduled auto-sync jobs for series and anime with intelligent wait-time handling

PLANNED: this wait is a guess, and it does not have to be
------------------------------------------------------------------------------
A webhook says "an episode arrived". It cannot say how many more are coming, so
this scheduler waits a fixed number of seconds and hopes the rest of the season
lands inside the window. Both outcomes are wrong in a way nobody can see:

  * the window is too short — a season is split across several transfers, each
    taking a queue slot and each writing its own backup capture,
  * the window is too long — a single episode sits waiting for company that is
    never coming.

Sonarr and Radarr both answer this properly over their own APIs: what is
queued, what is grabbed, what is still importing. Asking them turns the wait
from a fixed guess into a real answer — hold until the queue for this season is
empty, then go, with the fixed window kept only as an upper bound for when the
API cannot be reached.

That belongs with the connectors work (one place that owns talking to an
outside service) rather than here, because it needs a client with retries,
timeouts and failure reporting that this scheduler should not grow its own copy
of. The change lands in `schedule_job`/`_process_jobs` below: the wait becomes a
question asked of the connector, and `SERIES_ANIME_SYNC_WAIT_TIME` becomes the
ceiling rather than the answer.
"""

import time
import threading
from datetime import datetime
from typing import Dict, Optional
from services.sync_logger import log_sync, log_batch, log_validation, log_state_change
from actor import AUTO_SYNC_SCHEDULER, acting_as


class AutoSyncJob:
    """Represents a scheduled auto-sync job"""
    
    def __init__(self, notification_id: str, series_title_slug: str, season_number: int, 
                 scheduled_time: float, max_wait_time: int = 900):
        self.notification_id = notification_id
        self.series_title_slug = series_title_slug
        self.season_number = season_number
        self.scheduled_time = scheduled_time
        self.max_wait_time = max_wait_time
        self.created_at = time.time()
        self.notification_ids = [notification_id]  # Track all notification IDs in this batch
    
    def get_batch_key(self) -> str:
        """Get unique key for this series/season batch"""
        return f"{self.series_title_slug}_S{self.season_number}"


class AutoSyncScheduler:
    """
    Scheduler for series/anime auto-sync with intelligent wait-time handling
    """
    
    def __init__(self, db_manager, settings):
        self.db = db_manager
        self.settings = settings
        self.jobs = {}  # {batch_key: AutoSyncJob}
        self.lock = threading.Lock()
        self.coordinator = None  # Set by transfer_coordinator during initialization
        self.media_index = None  # Optional; without it the fixed wait is used
        print("✅ Auto-Sync Scheduler initialized")
    
    def set_coordinator(self, coordinator):
        """Set the transfer coordinator reference"""
        self.coordinator = coordinator

    def set_media_index(self, media_index):
        """Give the scheduler something to ask.

        Optional on purpose. Left unset — or set to something that cannot
        answer — every job falls back to the fixed wait, which is the behaviour
        this scheduler had before the gate existed.
        """
        self.media_index = media_index

    def _setting_int(self, key: str, fallback: int) -> int:
        try:
            return int(self.settings.get_int(key, fallback))
        except Exception:
            return fallback

    def _setting_bool(self, key: str) -> bool:
        try:
            return bool(self.settings.get_bool(key, False))
        except Exception:
            return False
    
    def schedule_job(self, notification_id: str, series_title_slug: str, season_number: int, 
                     wait_time: int, media_type: str):
        """
        Schedule an auto-sync job
        If a job for the same series/season exists, extend its wait time instead
        
        The wait itself is decided in `_wait_for_go` below: either the fixed
        window this setting names, or — when the gate is switched on — a
        question put to Sonarr, with this window kept as the ceiling.
        """
        batch_key = f"{series_title_slug}_S{season_number}"
        
        with self.lock:
            if batch_key in self.jobs:
                # Extend existing job
                job = self.jobs[batch_key]
                self._extend_job_wait_time(job, wait_time, notification_id)
                print(f"📅 Extended auto-sync for {batch_key} (now {len(job.notification_ids)} episodes)")
            else:
                # Create new job
                scheduled_time = time.time() + wait_time
                job = AutoSyncJob(
                    notification_id=notification_id,
                    series_title_slug=series_title_slug,
                    season_number=season_number,
                    scheduled_time=scheduled_time
                )
                self.jobs[batch_key] = job
                
                log_sync("AutoSyncScheduler", f"Scheduled auto-sync for {batch_key} in {wait_time}s", 
                        icon="📅", notification_id=notification_id)
                
                # Update notification status to 'pending' with scheduled time
                # Notification stays in PENDING during batching window
                self._update_notification_status(notification_id, 'pending', scheduled_time)
                
                # Start job execution thread. The whole job runs declared as
                # the scheduler, so the transfer it starts and anything it
                # records are attributed to automation rather than falling
                # through to an anonymous system actor. Declared at the thread
                # boundary rather than inside the job so the scope closes even
                # when the job raises.
                threading.Thread(
                    target=self._run_job_as_scheduler,
                    args=(job, media_type),
                    daemon=True
                ).start()
    
    def _extend_job_wait_time(self, job: AutoSyncJob, additional_seconds: int, new_notification_id: str):
        """Extend wait time for existing job (up to max)"""
        current_wait = job.scheduled_time - time.time()
        total_wait_from_creation = time.time() - job.created_at + current_wait + additional_seconds
        
        if total_wait_from_creation <= job.max_wait_time:
            job.scheduled_time = time.time() + current_wait + additional_seconds
            job.notification_ids.append(new_notification_id)
            print(f"⏰ Extended wait time for {job.get_batch_key()} by {additional_seconds}s")
            
            # Update new notification status to pending (batching)
            self._update_notification_status(new_notification_id, 'pending', job.scheduled_time)
        else:
            # Cap at max wait time
            max_additional = job.max_wait_time - (time.time() - job.created_at + current_wait)
            if max_additional > 0:
                job.scheduled_time += max_additional
                job.notification_ids.append(new_notification_id)
                print(f"⏰ Extended wait time for {job.get_batch_key()} by {max_additional}s (capped at max)")
                
                # Update new notification status to pending (batching)
                self._update_notification_status(new_notification_id, 'pending', job.scheduled_time)
            else:
                print(f"⚠️  Cannot extend wait time for {job.get_batch_key()} (already at max)")
                # Still add to batch but don't extend time
                job.notification_ids.append(new_notification_id)
                self._update_notification_status(new_notification_id, 'pending', job.scheduled_time)
    
    def _update_notification_status(self, notification_id: str, status: str, scheduled_time: float = None):
        """Update notification status in database"""
        try:
            updates = {'status': status}
            if scheduled_time:
                updates['auto_sync_scheduled_at'] = datetime.fromtimestamp(scheduled_time).isoformat()
            
            if self.coordinator and self.coordinator.series_webhook_model:
                self.coordinator.series_webhook_model.update(notification_id, updates)
        except Exception as e:
            print(f"❌ Error updating notification status: {e}")
    
    def _run_job_as_scheduler(self, job: 'AutoSyncJob', media_type: str):
        """Run one job with the scheduler named as the responsible actor."""
        with acting_as(AUTO_SYNC_SCHEDULER):
            self._execute_job(job, media_type)

    def _execute_job(self, job: AutoSyncJob, media_type: str):
        """
        Execute auto-sync job after wait time.

        Runs on its own thread with no request behind it, so it says who it is
        once here: everything started underneath — the transfer row, anything
        recorded along the way — is attributed to the scheduler rather than
        falling through to an anonymous system actor.
        """
        try:
            decided_by = self._wait_for_go(job)
            log_sync("AutoSyncScheduler",
                     f"{job.get_batch_key()} released by {decided_by}",
                     icon="🚦", notification_id=job.notification_ids[0])

            log_batch("AutoSyncScheduler", f"Executing auto-sync job for {job.get_batch_key()}", 
                     len(job.notification_ids), icon="⚡", notification_ids=job.notification_ids)
            
            # Get the first notification for details (all share same series/season)
            notification = self.coordinator.series_webhook_model.get(job.notification_ids[0])
            if not notification:
                log_sync("AutoSyncScheduler", f"Notification not found", icon="❌", 
                        notification_id=job.notification_ids[0])
                return
            
            # Perform dry-run validation
            log_sync("AutoSyncScheduler", f"Performing dry-run validation for {job.get_batch_key()}", 
                    icon="🔍", notification_id=job.notification_ids[0])
            validation = self.coordinator.perform_dry_run_validation(notification)
            
            if validation['safe_to_sync']:
                # Dry-run validation passed - mark all notifications as READY_FOR_TRANSFER
                print(f"✅ Validation passed for {job.get_batch_key()}, marking {len(job.notification_ids)} notification(s) as READY_FOR_TRANSFER")
                for notif_id in job.notification_ids:
                    self.coordinator.series_webhook_model.update(notif_id, {
                        'status': 'READY_FOR_TRANSFER'
                    })
                
                # Now attempt to start transfer (will check slot/path availability)
                print(f"🚀 Attempting to start transfer for {job.get_batch_key()} with {len(job.notification_ids)} batched notification(s)")
                success, message = self.coordinator.trigger_series_webhook_sync(
                    job.notification_ids[0],  # Primary notification
                    batched_notification_ids=job.notification_ids  # Pass all IDs for linking
                )
                
                if success:
                    print(f"✅ Transfer started/queued for {job.get_batch_key()}")
                    # Notifications will be updated by transfer coordinator based on slot/path checks:
                    # - If started immediately: SYNCING
                    # - If slot full: QUEUED_SLOT
                    # - If path conflict: QUEUED_PATH
                else:
                    print(f"❌ Failed to start transfer for {job.get_batch_key()}: {message}")
                    # Mark all as failed
                    for notif_id in job.notification_ids:
                        self.coordinator.series_webhook_model.update(notif_id, {
                            'status': 'failed',
                            'error_message': f'Failed to start transfer: {message}'
                        })
            else:
                # Mark for manual sync
                print(f"⚠️  Validation failed for {job.get_batch_key()}: {validation['reason']}")
                
                # Mark all notifications in batch as requiring manual sync
                for notif_id in job.notification_ids:
                    self.coordinator.mark_for_manual_sync(
                        notif_id, 
                        validation['reason'],
                        validation
                    )
                
                # Send Discord alert (once for the batch)
                self.coordinator.send_manual_sync_discord_alert(notification, validation)
            
        except Exception as e:
            print(f"❌ Error executing auto-sync job {job.get_batch_key()}: {e}")
            import traceback
            traceback.print_exc()
            
            # Mark all notifications as failed
            if self.coordinator:
                for notif_id in job.notification_ids:
                    try:
                        self.coordinator.series_webhook_model.update(notif_id, {
                            'status': 'failed',
                            'error_message': f'Auto-sync execution error: {str(e)}'
                        })
                    except Exception:
                        pass
        finally:
            # Remove auto-sync batch job from scheduler (not the transfer queue)
            with self.lock:
                batch_key = job.get_batch_key()
                if batch_key in self.jobs:
                    del self.jobs[batch_key]
                    print(f"🗑️  Removed auto-sync batch job {batch_key} from scheduler (batching complete)")
    

    def _sleep_until(self, deadline: float) -> None:
        """Sleep in short steps so a cancelled job is noticed promptly."""
        while time.time() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.time())))

    def _wait_for_go(self, job: 'AutoSyncJob') -> str:
        """
        Hold the job until it should run, and say what decided it.

        Two paths, and the first one is the old one, unchanged:

          * the gate is off, or there is nothing to ask, or the question cannot
            be answered — wait out the fixed window exactly as before;
          * the gate is on and Sonarr answers — settle briefly so episodes
            arriving together batch into one sync, then ask until nothing is
            still arriving.

        The fixed window is never abandoned, only demoted. `max_wait_time` stays
        the ceiling for the whole job, so a queue row that is stuck — one was
        observed sitting in `importPending` for six days — ends in a sync rather
        than in a season that silently never syncs again.

        Returns a short phrase naming what released the job, which is written to
        the sync log so an operator can tell an asked answer from a timed one.
        """
        if not self._setting_bool('AUTOSYNC_GATE_ENABLED') or self.media_index is None:
            self._sleep_until(job.scheduled_time)
            return 'the fixed wait'

        tvdb_id = self._tvdb_id_for(job)
        if not tvdb_id:
            self._sleep_until(job.scheduled_time)
            return 'the fixed wait (no series identifier)'

        settle = self._setting_int('AUTOSYNC_GATE_SETTLE_SECONDS', 10)
        poll = max(5, self._setting_int('AUTOSYNC_GATE_POLL_SECONDS', 30))
        ceiling = job.created_at + job.max_wait_time

        # Never settle past the point the fixed wait would have fired anyway;
        # switching the gate on must not make anything slower.
        self._sleep_until(min(time.time() + settle, job.scheduled_time, ceiling))

        asked = 0
        while True:
            # Belt and braces. `MediaIndex.in_flight_for_season` already returns
            # a value on every path, but this call sits inside `_execute_job`'s
            # try/except, which marks the whole batch failed. A gate that threw
            # would therefore turn "could not check" into "sync failed" — the
            # exact inversion this feature promises never to make.
            try:
                answer = self.media_index.in_flight_for_season(
                    tvdb_id, job.season_number)
            except Exception as exc:  # noqa: BLE001 - a gate must never fail a sync
                log_sync('AutoSyncScheduler',
                         f"{job.get_batch_key()}: gate raised ({exc}) — using the fixed wait",
                         icon='↩️', notification_id=job.notification_ids[0])
                self._sleep_until(min(job.scheduled_time, ceiling))
                return 'the fixed wait (the gate raised)'
            asked += 1

            if not answer.known:
                # No usable answer. Serve out whatever is left of the window the
                # operator configured, then behave as before. Recorded rather
                # than swallowed: a gate that has quietly stopped working should
                # be visible in the log, not inferred from timing.
                log_sync('AutoSyncScheduler',
                         f"{job.get_batch_key()}: {answer.reason} — using the fixed wait",
                         icon='↩️', notification_id=job.notification_ids[0])
                self._sleep_until(min(job.scheduled_time, ceiling))
                return f'the fixed wait ({answer.reason})'

            if answer.clear:
                return f'Sonarr ({answer.reason}, asked {asked}×)'

            if time.time() >= ceiling:
                log_sync('AutoSyncScheduler',
                         f"{job.get_batch_key()}: still {answer.blocking} arriving "
                         f"at the ceiling — going anyway",
                         icon='⏱️', notification_id=job.notification_ids[0])
                return f'the ceiling ({answer.reason})'

            self._sleep_until(min(time.time() + poll, ceiling))

    def _tvdb_id_for(self, job: 'AutoSyncJob'):
        """The durable identifier for this job's series, from its notification.

        Read from the notification rather than carried on the job so that a job
        created before this feature existed still resolves. Every series
        notification this application has ever stored carries one.
        """
        try:
            if not (self.coordinator and self.coordinator.series_webhook_model):
                return None
            notification = self.coordinator.series_webhook_model.get(
                job.notification_ids[0])
            if not notification:
                return None
            value = notification.get('tvdb_id')
            return value if value not in (None, '') else None
        except Exception:
            return None

    def cancel_job(self, series_title_slug: str, season_number: int) -> bool:
        """Cancel a scheduled auto-sync job"""
        batch_key = f"{series_title_slug}_S{season_number}"
        
        with self.lock:
            if batch_key in self.jobs:
                job = self.jobs[batch_key]
                
                # Mark all notifications as pending again
                for notif_id in job.notification_ids:
                    self._update_notification_status(notif_id, 'pending')
                
                del self.jobs[batch_key]
                print(f"❌ Cancelled auto-sync job for {batch_key}")
                return True
        
        return False
    
    def get_job_info(self, series_title_slug: str, season_number: int) -> Optional[Dict]:
        """Get information about a scheduled job"""
        batch_key = f"{series_title_slug}_S{season_number}"
        
        with self.lock:
            if batch_key in self.jobs:
                job = self.jobs[batch_key]
                time_remaining = max(0, job.scheduled_time - time.time())
                
                return {
                    'batch_key': batch_key,
                    'notification_count': len(job.notification_ids),
                    'notification_ids': job.notification_ids,
                    'scheduled_time': datetime.fromtimestamp(job.scheduled_time).isoformat(),
                    'time_remaining_seconds': int(time_remaining),
                    'created_at': datetime.fromtimestamp(job.created_at).isoformat()
                }
        
        return None
    
    def get_all_jobs(self) -> list:
        """Get information about all scheduled jobs"""
        with self.lock:
            return [self.get_job_info(job.series_title_slug, job.season_number) 
                    for job in self.jobs.values()]

