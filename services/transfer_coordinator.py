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
        
        # Initialize services
        self.backup_service = BackupService(config, db_manager, self.backup_model, self.transfer_model, socketio)
        self.transfer_service = TransferService(config, db_manager, self.transfer_model, socketio)
        self.notification_service = NotificationService(config, self.settings, self.transfer_model, self.webhook_model, self.series_webhook_model)
        self.webhook_service = WebhookService(config, self.webhook_model, self.series_webhook_model, self)
        self.auto_sync_scheduler = AutoSyncScheduler(db_manager, self.settings)
        
        # Set coordinator reference in scheduler (circular dependency)
        self.auto_sync_scheduler.set_coordinator(self)
        
        print(f"✅ TransferCoordinator initialized")
        
        # Resume any transfers that were running when the app was stopped
        self.transfer_service.resume_active_transfers()
    
    # Transfer Operations
    def start_transfer(self, transfer_id: str, source_path: str, dest_path: str, 
                      transfer_type: str = "folder", media_type: str = "", 
                      folder_name: str = "", season_name: str = None, episode_name: str = None) -> bool:
        """Start a new transfer with database persistence"""
        
        # Create transfer record in database
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
        
        # Calculate dynamic backup directory for this transfer
        transfer = self.transfer_model.get(transfer_id)
        backup_dir = self.backup_service._get_dynamic_backup_dir(transfer)
        
        # Start the actual transfer process
        success = self.transfer_service.start_rsync_process(transfer_id, source_path, dest_path, transfer_type, backup_dir)
        
        if success:
            # Start a thread to finalize backup and send notifications after completion
            import threading
            threading.Thread(
                target=self._post_transfer_completion, 
                args=(transfer_id,), 
                daemon=True
            ).start()
        
        return success
    
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
        """Cancel a running transfer"""
        return self.transfer_service.cancel_transfer(transfer_id)
    
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
        """Get active transfers (running/pending)"""
        all_transfers = self.transfer_model.get_all()
        return [t for t in all_transfers if t['status'] in ['running', 'pending']]
    
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
            # Source: Server path (where files currently exist)
            source_path = notification['season_path']
            
            # Destination: Construct local destination path from config
            media_type = notification['media_type']
            series_title = notification['series_title']
            season_number = notification.get('season_number')
            
            # Get the correct destination base path from config
            dest_base_map = {
                "anime": self.config.get("ANIME_DEST_PATH"),
                "series": self.config.get("TVSHOW_DEST_PATH"),
                "tvshows": self.config.get("TVSHOW_DEST_PATH")
            }
            
            dest_base = dest_base_map.get(media_type)
            if not dest_base:
                return {
                    'safe_to_sync': False,
                    'reason': f'{media_type.title()} destination path not configured',
                    'deleted_count': 0,
                    'incoming_count': 0,
                    'server_file_count': 0,
                    'local_file_count': 0,
                    'deleted_files': [],
                    'incoming_files': []
                }
            
            # Build folder name (series title with year if available)
            if notification.get('year'):
                folder_name = f"{series_title} ({notification['year']})"
            else:
                folder_name = series_title
            
            # Build destination path: {dest_base}/{folder_name}/Season {season_number}
            season_name = f"Season {season_number:02d}" if season_number else "Season Unknown"
            dest_path = f"{dest_base}/{folder_name}/{season_name}"
            
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

