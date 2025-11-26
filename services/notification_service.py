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
    
    def __init__(self, config, settings, transfer_model, webhook_model, series_webhook_model=None):
        self.config = config
        self.settings = settings
        self.transfer_model = transfer_model
        self.webhook_model = webhook_model
        self.series_webhook_model = series_webhook_model
    
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
    
    def extract_rsync_errors(self, logs: List[str]) -> List[str]:
        """Extract rsync error messages from transfer logs"""
        try:
            errors = []
            
            if not logs:
                return errors
            
            # Look for rsync errors in logs
            for line in logs:
                line = line.strip()
                
                # Capture rsync error lines (case-insensitive)
                if 'rsync:' in line.lower() and ('error' in line.lower() or 'failed' in line.lower()):
                    # Clean up the error message
                    errors.append(line)
                
                # Capture specific error patterns
                elif 'no space left on device' in line.lower():
                    errors.append(line)
                elif 'permission denied' in line.lower():
                    errors.append(line)
                elif 'connection refused' in line.lower():
                    errors.append(line)
                elif 'timeout' in line.lower() and 'rsync' in line.lower():
                    errors.append(line)
            
            # Limit to last 10 errors to avoid overly long messages
            if len(errors) > 10:
                errors = errors[-10:]
            
            print(f"🔍 Extracted {len(errors)} error messages from logs")
            return errors
            
        except Exception as e:
            print(f"❌ Error extracting rsync errors: {e}")
            return []
    
    def send_discord_notification(self, transfer_id: str, transfer_status: str):
        """Send Discord webhook notification for completed or failed transfer"""
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
            
            # Only send notifications for completed and failed transfers
            if transfer_status not in ['completed', 'failed']:
                print(f"📭 Skipping Discord notification for transfer {transfer_id} with status: {transfer_status}")
                return
            
            # Parse transfer logs for statistics and errors
            logs = transfer.get('logs', [])
            stats = self.parse_transfer_logs(logs)
            errors = self.extract_rsync_errors(logs) if transfer_status == 'failed' else []
            
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
            is_auto_sync = False
            
            # Get the transfer's media_type to determine which webhook model to check
            media_type = transfer.get('media_type', '')
            
            if media_type == 'movies':
                # Look for movie webhook notification linked to this transfer
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
                    # Movies are always auto-sync if from webhook
                    is_auto_sync = True
                    
            elif media_type in ['series', 'anime', 'tvshows']:
                # Look for series/anime webhook notification linked to this transfer
                if self.series_webhook_model:
                    notifications = self.series_webhook_model.get_all()
                    for notification in notifications:
                        if notification.get('transfer_id') == transfer_id:
                            webhook_notification = notification
                            break
                    
                    if webhook_notification:
                        # Use poster from webhook if available
                        if webhook_notification.get('poster_url'):
                            thumbnail_url = webhook_notification['poster_url']
                        requested_by = webhook_notification.get('requested_by')
                        # Check if this was auto-sync (has auto_sync_scheduled_at)
                        is_auto_sync = webhook_notification.get('auto_sync_scheduled_at') is not None
            
            # Determine sync type based on whether it was auto-synced
            if webhook_notification:
                sync_type = "Automated Sync" if is_auto_sync else "Manual Sync"
            else:
                sync_type = "Manual Sync"
            
            # Build Discord embed based on transfer status
            if transfer_status == 'failed':
                # Failed transfer - use red color and include error details
                embed = {
                    'title': title,
                    'color': 15158332,  # Red color for failures
                    'fields': [
                        {
                            'name': 'Folder Path',
                            'value': transfer.get('dest_path', 'Unknown'),
                            'inline': False
                        }
                    ],
                    'author': {
                        'name': f"{sync_type} - FAILED ❌",
                        'icon_url': icon_url
                    },
                    'timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                    'thumbnail': {
                        'url': thumbnail_url
                    } if thumbnail_url else None
                }
                
                # Add error messages if available
                if errors:
                    # Combine error messages, truncate if too long
                    error_text = '\n'.join(errors)
                    if len(error_text) > 1000:
                        error_text = error_text[:997] + '...'
                    
                    embed['fields'].append({
                        'name': 'Error Details',
                        'value': f"```\n{error_text}\n```",
                        'inline': False
                    })
                else:
                    # If no specific errors found, use the progress message
                    progress_msg = transfer.get('progress', 'Unknown error')
                    if len(progress_msg) > 1000:
                        progress_msg = progress_msg[:997] + '...'
                    
                    embed['fields'].append({
                        'name': 'Error Details',
                        'value': f"```\n{progress_msg}\n```",
                        'inline': False
                    })
                
                # Add partial stats if available
                if stats.get('regular_files_transferred') is not None or stats.get('deleted_files') is not None:
                    embed['fields'].append({
                        'name': 'Partial Transfer Stats',
                        'value': f"```Transferred: {stats.get('regular_files_transferred', 'N/A')}\nDeleted: {stats.get('deleted_files', 'N/A')}```",
                        'inline': True
                    })
            else:
                # Successful transfer - use purple color
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
                print(f"✅ Discord notification sent successfully for transfer {transfer_id} (status: {transfer_status})")
            else:
                print(f"❌ Discord notification failed for transfer {transfer_id}: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Error sending Discord notification for transfer {transfer_id}: {e}")
            import traceback
            traceback.print_exc()
    
    def send_rename_discord_notification(self, rename_result: Dict):
        """
        Send Discord webhook notification for completed file rename operation.
        
        Args:
            rename_result: Dictionary containing rename operation results with:
                - notification_id: Unique ID for this rename operation
                - series_title: Name of the series
                - total_files: Total number of files to rename
                - success_count: Number of files successfully renamed
                - failed_count: Number of files that failed to rename
                - status: 'completed', 'partial', or 'failed'
                - renamed_files: List of file rename results
                - media_type: Type of media (tvshows, anime)
        """
        try:
            # Check if Discord notifications are enabled
            notifications_enabled = self.settings.get_bool('DISCORD_NOTIFICATIONS_ENABLED', False)
            if not notifications_enabled:
                print("📭 Discord notifications are disabled, skipping rename notification")
                return
            
            # Get Discord webhook URL from settings
            discord_webhook_url = self.settings.get('DISCORD_WEBHOOK_URL')
            if not discord_webhook_url:
                print("📭 Discord webhook URL not configured, skipping rename notification")
                return
            
            # Extract rename information
            series_title = rename_result.get('series_title', 'Unknown Series')
            total_files = rename_result.get('total_files', 0)
            success_count = rename_result.get('success_count', 0)
            failed_count = rename_result.get('failed_count', 0)
            status = rename_result.get('status', 'unknown')
            renamed_files = rename_result.get('renamed_files', [])
            media_type = rename_result.get('media_type', 'series')
            
            # Get settings for Discord notification
            app_url = self.settings.get('DISCORD_APP_URL', 'http://localhost:5000')
            icon_url = self.settings.get('DISCORD_ICON_URL', '')
            
            # Determine color based on status
            # Teal/Cyan color (1752220) for successful renames - unique to rename operation
            # Orange (15105570) for partial renames
            # Red (15158332) for failed renames
            if status == 'completed':
                color = 1752220  # Teal/Cyan - unique to rename
                status_icon = '✅'
                status_text = 'Completed'
            elif status == 'partial':
                color = 15105570  # Orange for partial
                status_icon = '⚠️'
                status_text = 'Partial'
            else:
                color = 15158332  # Red for failed
                status_icon = '❌'
                status_text = 'Failed'
            
            # Build file rename summary (show result file names only)
            rename_summary_lines = []
            for file_info in renamed_files[:5]:  # Show first 5 renames
                new_name = file_info.get('new_name', 'Unknown')
                file_status = file_info.get('status', 'unknown')
                
                if file_status == 'success':
                    rename_summary_lines.append(f"✓ {new_name}")
                else:
                    rename_summary_lines.append(f"✗ {new_name}")
            
            if len(renamed_files) > 5:
                rename_summary_lines.append(f"... and {len(renamed_files) - 5} more files")
            
            rename_summary = '\n'.join(rename_summary_lines) if rename_summary_lines else 'No files renamed'
            
            # Truncate if too long for Discord
            if len(rename_summary) > 900:
                rename_summary = rename_summary[:897] + '...'
            
            # Build Discord embed
            embed = {
                'title': series_title,
                'color': color,
                'fields': [
                    {
                        'name': 'Media Type',
                        'value': media_type.upper() if media_type else 'SERIES',
                        'inline': True
                    },
                    {
                        'name': 'Rename Status',
                        'value': f"{status_icon} {status_text}",
                        'inline': True
                    },
                    {
                        'name': 'Files Summary',
                        'value': f"```Total: {total_files}\nRenamed: {success_count}\nFailed: {failed_count}```",
                        'inline': False
                    },
                    {
                        'name': 'Renamed Files',
                        'value': f"```{rename_summary}```",
                        'inline': False
                    }
                ],
                'author': {
                    'name': f'File Rename',
                    'icon_url': icon_url
                },
                'timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                'footer': {
                    'text': 'DragonCP Rename Operation'
                }
            }
            
            # Add URL only if it's a valid format
            if app_url and self._is_valid_discord_url(app_url):
                embed['url'] = app_url
            
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
                print(f"✅ Discord rename notification sent successfully for {series_title} (status: {status})")
            else:
                print(f"❌ Discord rename notification failed for {series_title}: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Error sending Discord rename notification: {e}")
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

