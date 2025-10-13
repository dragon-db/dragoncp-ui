#!/usr/bin/env python3
"""
DragonCP Notification Service
Handles Discord notifications and log parsing for transfers
"""

import re
import requests
from datetime import datetime
from typing import Dict, List


class NotificationService:
    """Service for Discord notifications and log parsing"""
    
    def __init__(self, config, settings, transfer_model, webhook_model):
        self.config = config
        self.settings = settings
        self.transfer_model = transfer_model
        self.webhook_model = webhook_model
    
    def parse_transfer_logs(self, logs: List[str]) -> Dict:
        """Parse rsync transfer logs to extract transfer statistics"""
        try:
            stats = {
                'total_transferred_size': None,
                'avg_speed': None,
                'regular_files_transferred': None,
                'deleted_files': None,
                'bytes_sent': None,
                'bytes_received': None
            }
            
            if not logs:
                return stats
            
            # Look through the logs for summary information (usually at the end)
            for line in reversed(logs):
                # Extract transfer statistics from rsync output
                # Number of regular files transferred: "Number of regular files transferred: 1"
                if 'Number of regular files transferred:' in line:
                    match = re.search(r'Number of regular files transferred:\s*(\d+)', line)
                    if match:
                        stats['regular_files_transferred'] = int(match.group(1))
                
                # Number of deleted files: "Number of deleted files: 0"
                if 'Number of deleted files:' in line:
                    match = re.search(r'Number of deleted files:\s*(\d+)', line)
                    if match:
                        stats['deleted_files'] = int(match.group(1))
                
                # Total file size: "Total file size: 3.70G bytes"
                if 'Total transferred file size:' in line:
                    match = re.search(r'Total transferred file size:\s*([0-9.,]+[KMGT]?)\s*bytes', line)
                    if match:
                        stats['total_transferred_size'] = match.group(1)
                
                # Speed and bytes info: "sent 103 bytes  received 3.70G bytes  4.68M bytes/sec"
                if 'sent' in line and 'bytes' in line and 'received' in line and 'bytes/sec' in line:
                    match = re.search(r'sent\s+([0-9.,]+[KMGT]?)\s+bytes\s+received\s+([0-9.,]+[KMGT]?)\s+bytes\s+([0-9.,]+[KMGT]?)\s+bytes/sec', line)
                    if match:
                        stats['bytes_sent'] = match.group(1)
                        stats['bytes_received'] = match.group(2)
                        stats['avg_speed'] = match.group(3) + ' bytes/sec'
            
            print(f"📊 Parsed transfer stats: {stats}")
            return stats
            
        except Exception as e:
            print(f"❌ Error parsing transfer logs: {e}")
            return {}
    
    def send_discord_notification(self, transfer_id: str, transfer_status: str):
        """Send Discord webhook notification for completed transfer"""
        try:
            # Check if Discord notifications are enabled
            notifications_enabled = self.settings.get_bool('DISCORD_NOTIFICATIONS_ENABLED', False)
            if not notifications_enabled:
                print("📭 Discord notifications are disabled, skipping notification")
                return
            
            # Get Discord webhook URL from settings
            discord_webhook_url = self.settings.get('DISCORD_WEBHOOK_URL')
            if not discord_webhook_url:
                print("📭 Discord webhook URL not configured, skipping notification")
                return
            
            # Get transfer details
            transfer = self.transfer_model.get(transfer_id)
            if not transfer:
                print(f"❌ Transfer {transfer_id} not found for Discord notification")
                return
            
            # Only send notifications for completed transfers
            if transfer_status != 'completed':
                print(f"📭 Skipping Discord notification for transfer {transfer_id} with status: {transfer_status}")
                return
            
            # Parse transfer logs for statistics
            logs = transfer.get('logs', [])
            stats = self.parse_transfer_logs(logs)
            
            # Get settings for Discord notification
            app_url = self.settings.get('DISCORD_APP_URL', 'http://localhost:5000')
            manual_sync_thumbnail_url = self.settings.get('DISCORD_MANUAL_SYNC_THUMBNAIL_URL', '')
            icon_url = self.settings.get('DISCORD_ICON_URL', '')
            
            # Determine title and thumbnail
            title = transfer.get('parsed_title', transfer.get('folder_name', 'Unknown'))
            thumbnail_url = manual_sync_thumbnail_url  # Default to manual sync thumbnail
            
            # Check if this was a webhook-triggered transfer to get poster and requested_by
            requested_by = None
            webhook_notification = None
            
            # Look for webhook notification linked to this transfer
            notifications = self.webhook_model.get_all()
            for notification in notifications:
                if notification.get('transfer_id') == transfer_id:
                    webhook_notification = notification
                    break
            
            if webhook_notification:
                # Use poster from webhook if available
                if webhook_notification.get('poster_url'):
                    thumbnail_url = webhook_notification['poster_url']
                requested_by = webhook_notification.get('requested_by')
            
            # Determine sync type
            sync_type = "Automated Sync" if webhook_notification else "Manual Sync"
            
            # Build Discord embed
            embed = {
                'title': title,
                'color': 11164867,  # Purple color
                'fields': [
                    {
                        'name': 'Folder Synced',
                        'value': transfer.get('dest_path', 'Unknown'),
                        'inline': False
                    },
                    {
                        'name': 'Files Info',
                        'value': f"```Transferred files: {stats.get('regular_files_transferred', 'N/A')}\nDeleted Files: {stats.get('deleted_files', 'N/A')}```",
                        'inline': True
                    },
                    {
                        'name': 'Speed Info',
                        'value': f"```Transferred: {stats.get('total_transferred_size', 'N/A')}\nAvg Speed: {stats.get('avg_speed', 'N/A')}```",
                        'inline': True
                    }
                ],
                'author': {
                    'name': sync_type,
                    'icon_url': icon_url
                },
                'timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                'thumbnail': {
                    'url': thumbnail_url
                } if thumbnail_url else None
            }
            
            # Add URL only if it's a valid format (Discord is strict about URL validation)
            if app_url and self._is_valid_discord_url(app_url):
                embed['url'] = app_url
            
            # Add requested_by field only for webhook transfers
            if requested_by:
                embed['fields'].append({
                    'name': 'Requested by',
                    'value': requested_by,
                    'inline': True
                })
            
            # Remove None thumbnail if not set
            if not thumbnail_url:
                embed.pop('thumbnail', None)
            
            # Prepare Discord payload
            payload = {
                'embeds': [embed]
            }
            
            # Send Discord webhook
            response = requests.post(
                discord_webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code == 204:
                print(f"✅ Discord notification sent successfully for transfer {transfer_id}")
            else:
                print(f"❌ Discord notification failed for transfer {transfer_id}: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Error sending Discord notification for transfer {transfer_id}: {e}")
            import traceback
            traceback.print_exc()
    
    def _is_valid_discord_url(self, url: str) -> bool:
        """Validate URL format for Discord embeds"""
        try:
            import re
            # Discord accepts http/https URLs with proper domain format
            # Allow localhost, IP addresses, and proper domain names
            url_pattern = r'^https?://(?:(?:[a-zA-Z0-9-]+\.)*[a-zA-Z0-9-]+|localhost|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d{1,5})?(?:/.*)?$'
            return bool(re.match(url_pattern, url))
        except Exception:
            return False

