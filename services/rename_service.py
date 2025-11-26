#!/usr/bin/env python3
"""
DragonCP Rename Service
Handles file rename operations from Sonarr webhook notifications.

This service is isolated from the sync/transfer logic because:
- Rename operations are local filesystem operations only (no rsync/SSH)
- Immediate execution, no queue management needed
- Simple os.rename() vs complex transfer coordination
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

from services.path_service import PathService


class RenameService:
    """
    Service for processing file rename webhooks from Sonarr.
    
    Handles the 'Rename' eventType webhook which contains information about
    files that were renamed on the server side and need to be reflected locally.
    """
    
    def __init__(self, config, rename_model, socketio=None, notification_service=None):
        """
        Initialize the rename service.
        
        Args:
            config: Application configuration (for path mappings)
            rename_model: RenameNotification database model
            socketio: Optional SocketIO instance for real-time updates
            notification_service: Optional NotificationService for Discord notifications
        """
        self.config = config
        self.rename_model = rename_model
        self.socketio = socketio
        self.notification_service = notification_service
        self.path_service = PathService(config)
    
    def process_rename_webhook(self, webhook_data: Dict, media_type: str) -> Tuple[bool, Dict]:
        """
        Main entry point for processing rename webhooks.
        
        Args:
            webhook_data: Raw webhook JSON from Sonarr
            media_type: 'tvshows' or 'anime'
        
        Returns:
            Tuple of (success, result_dict) where result_dict contains:
            - notification_id: Unique ID for this rename operation
            - series_title: Name of the series
            - total_files: Total number of files to rename
            - success_count: Number of files successfully renamed
            - failed_count: Number of files that failed to rename
            - status: 'completed', 'partial', or 'failed'
            - renamed_files: List of file rename results
            - message: Human-readable summary
        """
        try:
            # Parse the rename webhook data
            rename_data = self._parse_rename_data(webhook_data, media_type)
            
            print(f"📝 Processing rename webhook for {rename_data['series_title']}")
            print(f"   Total files to rename: {rename_data['total_files']}")
            
            # Store initial notification in database
            raw_webhook_json = json.dumps(webhook_data, indent=2)
            notification_id = self.rename_model.create(rename_data, raw_webhook_json)
            
            # Emit WebSocket event for UI update
            if self.socketio:
                self.socketio.emit('rename_webhook_received', {
                    'notification_id': notification_id,
                    'series_title': rename_data['series_title'],
                    'total_files': rename_data['total_files'],
                    'media_type': media_type,
                    'timestamp': datetime.now().isoformat()
                })
            
            # Execute the rename operations
            renamed_files, operation_logs = self._execute_renames(rename_data)
            
            # Calculate results
            success_count = sum(1 for f in renamed_files if f['status'] == 'success')
            failed_count = sum(1 for f in renamed_files if f['status'] == 'failed')
            
            # Determine overall status
            if failed_count == 0:
                status = 'completed'
            elif success_count == 0:
                status = 'failed'
            else:
                status = 'partial'
            
            # Store all operation logs (success, errors, already renamed, etc.)
            # This is stored in error_message field but contains all logs
            error_message = "\n".join(operation_logs) if operation_logs else None
            
            # Update notification in database
            self.rename_model.update(notification_id, {
                'renamed_files': renamed_files,
                'success_count': success_count,
                'failed_count': failed_count,
                'status': status,
                'error_message': error_message,
                'processed_at': datetime.now().isoformat()
            })
            
            # Build result
            result = {
                'notification_id': notification_id,
                'series_title': rename_data['series_title'],
                'total_files': rename_data['total_files'],
                'success_count': success_count,
                'failed_count': failed_count,
                'status': status,
                'renamed_files': renamed_files,
                'message': self._build_result_message(rename_data['series_title'], success_count, failed_count)
            }
            
            # Emit completion WebSocket event
            if self.socketio:
                self.socketio.emit('rename_completed', result)
            
            # Log result
            status_icon = '✅' if status == 'completed' else ('⚠️' if status == 'partial' else '❌')
            print(f"{status_icon} Rename {status}: {success_count}/{rename_data['total_files']} files renamed for {rename_data['series_title']}")
            
            # Send Discord notification
            if self.notification_service:
                # Add media_type to result for notification
                result['media_type'] = rename_data['media_type']
                self.notification_service.send_rename_discord_notification(result)
            
            return (status != 'failed', result)
            
        except Exception as e:
            print(f"❌ Error processing rename webhook: {e}")
            import traceback
            traceback.print_exc()
            return (False, {
                'status': 'failed',
                'message': f"Failed to process rename webhook: {str(e)}",
                'error': str(e)
            })
    
    def _parse_rename_data(self, webhook_data: Dict, media_type: str) -> Dict:
        """
        Parse rename webhook JSON into structured data.
        
        Args:
            webhook_data: Raw webhook JSON from Sonarr
            media_type: 'tvshows' or 'anime'
        
        Returns:
            Parsed rename data dictionary
        """
        series = webhook_data.get('series', {})
        renamed_episode_files = webhook_data.get('renamedEpisodeFiles', [])
        
        # Extract series information
        series_title = series.get('title', 'Unknown Series')
        series_id = series.get('id')
        series_path = series.get('path', '')
        
        # Generate unique notification ID
        timestamp = int(datetime.now().timestamp() * 1000)  # Millisecond precision
        notification_id = f"rename_{series_id or 'unknown'}_{timestamp}"
        
        # Parse each renamed file
        renamed_files = []
        for file_info in renamed_episode_files:
            renamed_files.append({
                'id': file_info.get('id'),
                'previous_path': file_info.get('previousPath', ''),
                'previous_relative_path': file_info.get('previousRelativePath', ''),
                'new_path': file_info.get('path', ''),
                'new_relative_path': file_info.get('relativePath', ''),
                'previous_name': os.path.basename(file_info.get('previousPath', '')),
                'new_name': os.path.basename(file_info.get('path', '')),
                'status': 'pending',
                'error': None,
                'local_previous_path': None,
                'local_new_path': None
            })
        
        return {
            'notification_id': notification_id,
            'media_type': media_type,
            'series_title': series_title,
            'series_id': series_id,
            'series_path': series_path,
            'renamed_files': renamed_files,
            'total_files': len(renamed_files),
            'success_count': 0,
            'failed_count': 0,
            'status': 'pending'
        }
    
    def _execute_renames(self, rename_data: Dict) -> Tuple[List[Dict], List[str]]:
        """
        Execute local file rename operations.
        
        Args:
            rename_data: Parsed rename data from _parse_rename_data
        
        Returns:
            Tuple of (results list, operation logs list)
            Each result has status, message, and error info
        """
        results = []
        operation_logs = []
        series_path = rename_data['series_path']
        media_type = rename_data['media_type']
        
        for file_info in rename_data['renamed_files']:
            result = file_info.copy()
            
            try:
                # Map server paths to local paths
                local_previous_path = self._map_to_local_path(
                    file_info['previous_relative_path'],
                    series_path,
                    media_type
                )
                local_new_path = self._map_to_local_path(
                    file_info['new_relative_path'],
                    series_path,
                    media_type
                )
                
                result['local_previous_path'] = local_previous_path
                result['local_new_path'] = local_new_path
                
                # Check if source file exists
                if not os.path.exists(local_previous_path):
                    # Check if file is already renamed (idempotency)
                    if os.path.exists(local_new_path):
                        result['status'] = 'success'
                        result['message'] = 'File already renamed (exists at new path)'
                        result['error'] = None
                        log_msg = f"ℹ️  File already renamed: {result['new_name']}"
                        print(f"   {log_msg}")
                        operation_logs.append(log_msg)
                    else:
                        result['status'] = 'failed'
                        result['message'] = 'File not found locally'
                        result['error'] = f"File not found locally: {local_previous_path}"
                        log_msg = f"❌ File not found: {result['previous_name']}"
                        print(f"   {log_msg}")
                        operation_logs.append(log_msg)
                else:
                    # Check if target already exists with different file
                    if os.path.exists(local_new_path):
                        result['status'] = 'failed'
                        result['message'] = 'Target file already exists'
                        result['error'] = f"Target file already exists: {local_new_path}"
                        log_msg = f"❌ Target exists: {result['new_name']}"
                        print(f"   {log_msg}")
                        operation_logs.append(log_msg)
                    else:
                        # Ensure target directory exists
                        target_dir = os.path.dirname(local_new_path)
                        if not os.path.exists(target_dir):
                            os.makedirs(target_dir, exist_ok=True)
                        
                        # Perform the rename
                        os.rename(local_previous_path, local_new_path)
                        result['status'] = 'success'
                        result['message'] = 'Renamed successfully'
                        result['error'] = None
                        log_msg = f"✅ Renamed: {result['previous_name']} → {result['new_name']}"
                        print(f"   {log_msg}")
                        operation_logs.append(log_msg)
                        
            except PermissionError as e:
                result['status'] = 'failed'
                result['message'] = 'Permission denied'
                result['error'] = f"Permission denied: {str(e)}"
                log_msg = f"❌ Permission denied: {result['previous_name']}"
                print(f"   {log_msg}")
                operation_logs.append(log_msg)
            except OSError as e:
                result['status'] = 'failed'
                result['message'] = f"OS error: {str(e)}"
                result['error'] = f"OS error: {str(e)}"
                log_msg = f"❌ OS error renaming {result['previous_name']}: {e}"
                print(f"   {log_msg}")
                operation_logs.append(log_msg)
            except Exception as e:
                result['status'] = 'failed'
                result['message'] = f"Unexpected error: {str(e)}"
                result['error'] = f"Unexpected error: {str(e)}"
                log_msg = f"❌ Error renaming {result['previous_name']}: {e}"
                print(f"   {log_msg}")
                operation_logs.append(log_msg)
            
            results.append(result)
        
        return results, operation_logs
    
    def _map_to_local_path(self, relative_path: str, server_series_path: str, media_type: str) -> str:
        """
        Convert a server relative path to a local filesystem path.
        
        Example:
            relative_path: "Season 01/Show - S01E01 - Title.mkv"
            server_series_path: "/home/dragondb/media/TV Shows/Show Name (2025)"
            media_type: "tvshows"
            
            Result: "{TVSHOW_DEST_PATH}/Show Name (2025)/Season 01/Show - S01E01 - Title.mkv"
        
        Args:
            relative_path: Relative path from Sonarr (e.g., "Season 01/filename.mkv")
            server_series_path: Full server path to series folder
            media_type: 'tvshows' or 'anime'
        
        Returns:
            Full local filesystem path
        """
        # Get the series folder name from the server path
        series_folder_name = os.path.basename(server_series_path.rstrip('/'))
        
        # Get the local base destination path for this media type
        dest_base = self.path_service.get_base_destination(media_type)
        if not dest_base:
            raise ValueError(f"Destination path not configured for media type: {media_type}")
        
        # Normalize path separators for the current OS
        # Sonarr sends paths with forward slashes, but we need OS-appropriate separators
        relative_path_normalized = relative_path.replace('/', os.sep).replace('\\', os.sep)
        
        # Construct the full local path
        local_path = os.path.join(dest_base, series_folder_name, relative_path_normalized)
        
        return local_path
    
    def _build_result_message(self, series_title: str, success_count: int, failed_count: int) -> str:
        """
        Build a human-readable result message.
        
        Args:
            series_title: Name of the series
            success_count: Number of successfully renamed files
            failed_count: Number of failed renames
        
        Returns:
            Human-readable message
        """
        total = success_count + failed_count
        
        if failed_count == 0:
            return f"Successfully renamed {success_count} file(s) for {series_title}"
        elif success_count == 0:
            return f"Failed to rename {failed_count} file(s) for {series_title}"
        else:
            return f"Renamed {success_count}/{total} file(s) for {series_title} ({failed_count} failed)"

