#!/usr/bin/env python3
"""
DragonCP Transfer Coordinator
Main orchestrator that coordinates transfer, backup, webhook, and notification services
"""

import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Import services
from services.backup_service import BackupService
from services.transfer_service import TransferService
from services.notification_service import NotificationService
from services.webhook_service import WebhookService


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
        self.notification_service = NotificationService(config, self.settings, self.transfer_model, self.webhook_model)
        self.webhook_service = WebhookService(config, self.webhook_model, self.series_webhook_model, self)
        
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

