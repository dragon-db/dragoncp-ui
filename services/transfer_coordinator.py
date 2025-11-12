#!/usr/bin/env python3
"""
DragonCP Transfer Coordinator
Main orchestrator that coordinates transfer, backup, webhook, and notification services
"""

import os
import re
import time
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Import services
from services.backup_service import BackupService
from services.transfer_service import TransferService
from services.notification_service import NotificationService
from services.webhook_service import WebhookService
from services.auto_sync_scheduler import AutoSyncScheduler
from services.queue_manager import QueueManager
from services.path_service import PathService


class TransferCoordinator:
    """Main coordinator that orchestrates all transfer-related operations"""
    
    def __init__(self, config, db_manager, socketio=None):
        print(f"🔄 Initializing TransferCoordinator")
        self.config = config
        self.db = db_manager
        self.socketio = socketio
        
        # Import models
        from models import Transfer, Backup, WebhookNotification, SeriesWebhookNotification, AppSettings
        
        # Initialize models
        self.transfer_model = Transfer(db_manager)
        self.backup_model = Backup(db_manager)
        self.webhook_model = WebhookNotification(db_manager)
        self.series_webhook_model = SeriesWebhookNotification(db_manager)
        self.settings = AppSettings(db_manager)
        
        # Initialize queue manager (must be before transfer service)
        self.queue_manager = QueueManager(self.transfer_model, socketio)
        
        # Initialize services
        self.path_service = PathService(config)
        self.backup_service = BackupService(config, db_manager, self.backup_model, self.transfer_model, socketio)
        self.transfer_service = TransferService(config, db_manager, self.transfer_model, socketio, self.queue_manager)
        self.notification_service = NotificationService(config, self.settings, self.transfer_model, self.webhook_model, self.series_webhook_model)
        self.webhook_service = WebhookService(config, self.webhook_model, self.series_webhook_model, self)
        self.auto_sync_scheduler = AutoSyncScheduler(db_manager, self.settings)
        
        # Set coordinator reference in scheduler and queue manager (circular dependencies)
        self.auto_sync_scheduler.set_coordinator(self)
        self.queue_manager.set_coordinator(self)
        
        print(f"✅ TransferCoordinator initialized")
        
        # Clean up stale transfer tracking before resuming
        self.queue_manager.force_unregister_stale_transfers()
        
        # Resume any transfers that were running when the app was stopped
        self.transfer_service.resume_active_transfers()
    
    # Transfer Operations
    def start_transfer(self, transfer_id: str, source_path: str, dest_path: str, 
                      transfer_type: str = "folder", media_type: str = "", 
                      folder_name: str = "", season_name: str = None, episode_name: str = None) -> bool:
        """
        Start a new transfer with database persistence and queue management
        
        Returns True if transfer started/queued successfully, False if duplicate
        """
        
        print(f"🎯 TransferCoordinator.start_transfer() called for {transfer_id}")
        print(f"   dest_path: {dest_path}")
        
        # STRICT VALIDATION: Check for duplicate destination BEFORE creating transfer
        print(f"🔍 Checking for duplicate destination...")
        is_duplicate, existing_transfer_id = self.queue_manager.check_duplicate_destination(dest_path, transfer_id)
        print(f"   is_duplicate: {is_duplicate}, existing: {existing_transfer_id}")
        
        if is_duplicate:
            print(f"🚫 DUPLICATE DESTINATION DETECTED!")
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
                duplicate_message = f'Duplicate: Another transfer "{existing_info}" is already syncing to this destination'
            else:
                duplicate_message = f'Duplicate: Another transfer is already syncing to: {dest_path}'
            
            # Create transfer record with 'duplicate' status
            transfer_data = {
                'transfer_id': transfer_id,
                'media_type': media_type,
                'folder_name': folder_name,
                'season_name': season_name,
                'episode_name': episode_name,
                'source_path': source_path,
                'dest_path': dest_path,
                'transfer_type': transfer_type,
                'status': 'duplicate',
                'progress': duplicate_message,
                'end_time': datetime.now().isoformat()
            }
            
            self.transfer_model.create(transfer_data)
            
            # Emit WebSocket notification
            if self.socketio:
                self.socketio.emit('transfer_duplicate', {
                    'transfer_id': transfer_id,
                    'existing_transfer_id': existing_transfer_id,
                    'dest_path': dest_path,
                    'message': 'Duplicate destination detected'
                })
            
            return False
        
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
                'episode_name': episode_name,
                'source_path': source_path,
                'dest_path': dest_path,
                'transfer_type': transfer_type,
                'status': 'queued',
                'progress': 'Waiting in queue...'
            }
            
            self.transfer_model.create(transfer_data)
            print(f"⏳ Transfer {transfer_id} added to queue")
            
            # Emit WebSocket notification
            if self.socketio:
                self.socketio.emit('transfer_queued', {
                    'transfer_id': transfer_id,
                    'message': 'Transfer added to queue'
                })
            
            return True
        
        # If can start immediately, create with 'pending' status and start transfer
        if can_start:
            print(f"✅ Can start immediately, creating transfer record...")
            # Create transfer record with 'pending' status (will be updated to 'running' by start_rsync_process)
            transfer_data = {
                'transfer_id': transfer_id,
                'media_type': media_type,
                'folder_name': folder_name,
                'season_name': season_name,
                'episode_name': episode_name,
                'source_path': source_path,
                'dest_path': dest_path,
                'transfer_type': transfer_type,
                'status': 'pending'
            }
            
            self.transfer_model.create(transfer_data)
            print(f"✅ Transfer record created with status 'pending'")
            
            # Calculate dynamic backup directory for this transfer
            transfer = self.transfer_model.get(transfer_id)
            backup_dir = self.backup_service._get_dynamic_backup_dir(transfer)
            print(f"📁 Backup dir: {backup_dir}")
            
            # Start the actual transfer process
            print(f"🚀 Calling start_rsync_process...")
            success = self.transfer_service.start_rsync_process(transfer_id, source_path, dest_path, transfer_type, backup_dir)
            print(f"   start_rsync_process returned: {success}")
            
            if success:
                # Start a thread to finalize backup and send notifications after completion
                import threading
                threading.Thread(
                    target=self._post_transfer_completion, 
                    args=(transfer_id,), 
                    daemon=True
                ).start()
            else:
                # If failed to start, unregister from queue manager
                self.queue_manager.unregister_transfer(transfer_id)
            
            return success
        
        return False
    
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
                
                # Unregister from queue manager (will promote next queued transfer)
                print(f"🏁 Transfer {transfer_id} finished with status: {status}")
                self.queue_manager.unregister_transfer(transfer_id)
                
                # Update webhook notification status
                self.webhook_service.update_webhook_transfer_status(transfer_id, status, self.transfer_model)
                
                # Send Discord notification for completed transfers
                if status == 'completed':
                    try:
                        self.notification_service.send_discord_notification(transfer_id, status)
                    except Exception as de:
                        print(f"⚠️  Discord notification error for {transfer_id}: {de}")
                
                # Finalize backup record if any files were backed up
                try:
                    self.backup_service.finalize_backup_for_transfer(transfer_id)
                except Exception as be:
                    print(f"⚠️  Backup finalization error for {transfer_id}: {be}")
                
                break
            
            time.sleep(check_interval)
            waited += check_interval
    
    def cancel_transfer(self, transfer_id: str) -> bool:
        """Cancel a running or queued transfer"""
        result = self.transfer_service.cancel_transfer(transfer_id)
        
        # Unregister from queue manager if it was running
        if result:
            self.queue_manager.unregister_transfer(transfer_id)
        
        return result
    
    def restart_transfer(self, transfer_id: str) -> bool:
        """Restart a failed or cancelled transfer"""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False
        backup_dir = self.backup_service._get_dynamic_backup_dir(transfer)
        return self.transfer_service.restart_transfer(transfer_id, backup_dir)
    
    def get_transfer_status(self, transfer_id: str) -> Optional[Dict]:
        """Get transfer status from database"""
        return self.transfer_model.get(transfer_id)
    
    def get_all_transfers(self, limit: int = 50) -> List[Dict]:
        """Get all transfers from database"""
        return self.transfer_model.get_all(limit=limit)
    
    def get_active_transfers(self) -> List[Dict]:
        """Get active transfers (running/pending/queued)"""
        all_transfers = self.transfer_model.get_all()
        return [t for t in all_transfers if t['status'] in ['running', 'pending', 'queued']]
    
    def start_queued_transfer(self, transfer_id: str) -> bool:
        """
        Start a queued transfer (called by queue manager when promoting)
        """
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False
        
        # Update status from 'queued' to 'pending' before starting
        # (start_rsync_process will update it to 'running')
        self.transfer_model.update(transfer_id, {
            'status': 'pending',
            'progress': 'Starting transfer...'
        })
        
        # Refresh transfer data after update
        transfer = self.transfer_model.get(transfer_id)
        
        # Calculate dynamic backup directory
        backup_dir = self.backup_service._get_dynamic_backup_dir(transfer)
        
        # Start the transfer
        success = self.transfer_service.start_rsync_process(
            transfer_id,
            transfer['source_path'],
            transfer['dest_path'],
            transfer['transfer_type'],
            backup_dir
        )
        
        if success:
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
        
        return success
    
    def get_queue_status(self) -> Dict:
        """Get current queue status"""
        return self.queue_manager.get_queue_status()
    
    # Backup Operations
    def restore_backup(self, backup_id: str, files: List[str] = None) -> Tuple[bool, str]:
        """Restore a backup (optionally selected files)"""
        return self.backup_service.restore_backup(backup_id, files)
    
    def delete_backup(self, backup_id: str, delete_files: bool = True) -> Tuple[bool, str]:
        """Delete a backup record and optionally remove backup files"""
        return self.backup_service.delete_backup(backup_id, delete_files)
    
    def delete_backup_options(self, backup_id: str, delete_record: bool, delete_files: bool) -> Tuple[bool, str]:
        """Delete backup files and/or DB record independently"""
        return self.backup_service.delete_backup_options(backup_id, delete_record, delete_files)
    
    def plan_context_restore(self, backup_id: str, files: List[str] = None) -> Dict:
        """Plan a context-aware restore"""
        return self.backup_service.plan_context_restore(backup_id, files)
    
    def reindex_backups(self) -> Tuple[int, int]:
        """Scan BACKUP_PATH for existing backup dirs and import missing ones"""
        return self.backup_service.reindex_backups()
    
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
    
    def trigger_series_webhook_sync(self, notification_id: str) -> Tuple[bool, str]:
        """Trigger sync for a series/anime webhook notification"""
        return self.webhook_service.trigger_series_webhook_sync(notification_id)
    
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
    def schedule_auto_sync(self, notification_id: str, series_title_slug: str, 
                          season_number: int, media_type: str):
        """Schedule an auto-sync job for series/anime"""
        wait_time = int(self.settings.get('SERIES_ANIME_SYNC_WAIT_TIME', '60'))
        self.auto_sync_scheduler.schedule_job(
            notification_id=notification_id,
            series_title_slug=series_title_slug,
            season_number=season_number,
            wait_time=wait_time,
            media_type=media_type
        )
    
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
                dest_path=dest_path,
                is_season_folder=True
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
        """Send Discord notification when manual sync is required"""
        try:
            # Check if Discord notifications are enabled
            if not self.settings.get_bool('DISCORD_NOTIFICATIONS_ENABLED', False):
                return
            
            webhook_url = self.settings.get('DISCORD_WEBHOOK_URL')
            if not webhook_url:
                return
            
            media_type = notification['media_type']
            series_title = notification['series_title']
            season_number = notification['season_number']
            season_path = notification['season_path']
            
            # Get app URL for the link
            app_url = self.settings.get('DISCORD_APP_URL', 'http://localhost:5000')
            
            # Create embed
            embed = {
                'title': f'**{series_title}** - Season {season_number}',
                'description': 'Media Type: ' + media_type.upper(),
                'color': 15844367,  # Gold/warning color
                'fields': [
                    {   
                        'name': 'Season Path',
                        'value': f'```{season_path}```',
                        'inline': False
                    },
                    {
                        'name': 'Reason',
                        'value': validation_result['reason'],
                        'inline': False
                    },
                    {
                        'name': 'File Analysis',
                        'value': (
                            f"```\n"
                            f"Server Files: {validation_result.get('server_file_count', 0)}\n"
                            f"Local Files: {validation_result.get('local_file_count', 0)}\n"
                            f"Would Delete: {validation_result.get('deleted_count', 0)} media files\n"
                            f"Would Add: {validation_result.get('incoming_count', 0)} media files\n"
                            f"```"
                        ),
                        'inline': False
                    }
                ],
                'footer': {
                    'text': 'DRAGONCP Auto-Sync Safety Check'
                },
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Add app URL if valid
            if app_url and self._is_valid_discord_url(app_url):
                embed['url'] = app_url
            
            # Add icon if configured
            icon_url = self.settings.get('DISCORD_ICON_URL')
            if icon_url:
                embed['author'] = {
                    'name': 'Manual Sync Alert ⚠️',
                    'icon_url': icon_url
                }
            
            # Send to Discord
            payload = {'embeds': [embed]}
            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code == 204:
                print(f"✅ Discord manual sync alert sent for {series_title} Season {season_number}")
            else:
                print(f"⚠️  Discord alert failed: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error sending Discord manual sync alert: {e}")
            import traceback
            traceback.print_exc()
    
    def _is_valid_discord_url(self, url: str) -> bool:
        """Validate URL format for Discord embeds"""
        try:
            # Discord accepts http/https URLs with proper domain format
            url_pattern = r'^https?://(?:(?:[a-zA-Z0-9-]+\.)*[a-zA-Z0-9-]+|localhost|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d{1,5})?(?:/.*)?$'
            return bool(re.match(url_pattern, url))
        except Exception:
            return False

