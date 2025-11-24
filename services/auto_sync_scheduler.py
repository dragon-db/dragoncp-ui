#!/usr/bin/env python3
"""
DragonCP Auto-Sync Scheduler Service
Manages scheduled auto-sync jobs for series and anime with intelligent wait-time handling
"""

import time
import threading
from datetime import datetime
from typing import Dict, Optional
from services.sync_logger import log_sync, log_batch, log_validation, log_state_change


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
        print("✅ Auto-Sync Scheduler initialized")
    
    def set_coordinator(self, coordinator):
        """Set the transfer coordinator reference"""
        self.coordinator = coordinator
    
    def schedule_job(self, notification_id: str, series_title_slug: str, season_number: int, 
                     wait_time: int, media_type: str):
        """
        Schedule an auto-sync job
        If a job for the same series/season exists, extend its wait time instead
        
        TODO: Dynamic Wait Time with Sonarr API Integration
        =====================================================
        Instead of using a fixed wait time, query Sonarr's queue to dynamically
        determine optimal wait time based on actual download status.
        
        APPROACH:
        1. Query Sonarr API: GET /api/v3/queue?seriesId={series_id}
        2. Filter queue for episodes from the same season
        3. If queue has pending episodes:
           - Extend wait time (up to max 15 minutes)
           - Check periodically until queue is empty
        4. If queue is empty:
           - Proceed with dry-run immediately (no need to wait)
        5. Respect max_wait_time cap (900s/15 minutes)
        
        CONFIGURATION NEEDED:
        - SONARR_API_URL: Base URL for Sonarr API (e.g., http://localhost:8989)
        - SONARR_API_KEY: API key for authentication
        - USE_DYNAMIC_WAIT: Boolean toggle (default: false, use fixed wait time)
        - SONARR_QUEUE_CHECK_INTERVAL: How often to check queue (default: 30s)
        
        BENEFITS:
        - No need to guess appropriate wait time
        - Adapts to actual download speed
        - Reduces unnecessary waiting when all episodes are ready
        - Better handles slow downloads by waiting longer
        
        IMPLEMENTATION NOTES:
        - Add sonarr_api_client module with queue checking methods
        - Modify this schedule_job method to optionally use dynamic wait
        - Add periodic queue checking in _execute_job wait loop
        - Log queue status for debugging
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
                
                # Start job execution thread
                threading.Thread(
                    target=self._execute_job, 
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
    
    def _execute_job(self, job: AutoSyncJob, media_type: str):
        """Execute auto-sync job after wait time"""
        try:
            # Wait until scheduled time
            while time.time() < job.scheduled_time:
                time.sleep(1)
            
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

