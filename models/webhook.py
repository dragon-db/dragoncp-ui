#!/usr/bin/env python3
"""
DragonCP Webhook Models (v2)
Database models for webhook notifications (movies, series, anime, renames)

Schema v2 Changes:
- Table renames: radarr_webhook, sonarr_webhook, rename_webhook
- Column renames: synced_at → completed_at, processed_at → completed_at
- Added: updated_at columns
"""

import json
from datetime import datetime
from typing import List, Dict, Optional


class WebhookNotification:
    """WebhookNotification model for movie webhook notifications"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def create(self, notification_data: Dict, raw_webhook_data: str = None) -> str:
        """Create a new webhook notification record"""
        print(f"📝 Creating webhook notification for {notification_data.get('title', 'Unknown')}")
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO radarr_webhook (
                        notification_id, title, year, folder_path, poster_url, requested_by,
                        file_path, quality, size, languages, subtitles, 
                        release_title, release_indexer, release_size, tmdb_id, imdb_id, status, raw_webhook_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    notification_data['notification_id'],
                    notification_data['title'],
                    notification_data.get('year'),
                    notification_data['folder_path'],
                    notification_data.get('poster_url'),
                    notification_data.get('requested_by'),
                    notification_data['file_path'],
                    notification_data.get('quality'),
                    notification_data.get('size', 0),
                    json.dumps(notification_data.get('languages', [])),
                    json.dumps(notification_data.get('subtitles', [])),
                    notification_data.get('release_title'),
                    notification_data.get('release_indexer'),
                    notification_data.get('release_size', 0),
                    notification_data.get('tmdb_id'),
                    notification_data.get('imdb_id'),
                    notification_data.get('status', 'pending'),
                    raw_webhook_data
                ))
                conn.commit()
                print(f"✅ Webhook notification created successfully for {notification_data['title']}")
                return notification_data['notification_id']
        except Exception as e:
            print(f"❌ Error creating webhook notification: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def update(self, notification_id: str, updates: Dict) -> bool:
        """Update webhook notification record"""
        if not updates:
            return False
        
        # Convert lists to JSON strings if present
        if 'languages' in updates and isinstance(updates['languages'], list):
            updates['languages'] = json.dumps(updates['languages'])
        if 'subtitles' in updates and isinstance(updates['subtitles'], list):
            updates['subtitles'] = json.dumps(updates['subtitles'])
        
        # Add updated_at timestamp
        updates['updated_at'] = datetime.now().isoformat()
        
        # Build dynamic update query
        set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
        values = list(updates.values()) + [notification_id]
        
        with self.db.get_connection() as conn:
            cursor = conn.execute(f'''
                UPDATE radarr_webhook SET {set_clause}
                WHERE notification_id = ?
            ''', values)
            conn.commit()
            return cursor.rowcount > 0
    
    def get(self, notification_id: str) -> Optional[Dict]:
        """Get webhook notification by ID"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM radarr_webhook WHERE notification_id = ?
            ''', (notification_id,))
            row = cursor.fetchone()
            
            if row:
                notification = dict(row)
                # Parse JSON fields
                try:
                    notification['languages'] = json.loads(notification.get('languages', '[]'))
                except json.JSONDecodeError:
                    notification['languages'] = []
                try:
                    notification['subtitles'] = json.loads(notification.get('subtitles', '[]'))
                except json.JSONDecodeError:
                    notification['subtitles'] = []
                return notification
            return None
    
    def get_by_transfer_id(self, transfer_id: str) -> Optional[Dict]:
        """Get webhook notification by transfer_id (efficient indexed lookup)"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM radarr_webhook WHERE transfer_id = ?
            ''', (transfer_id,))
            row = cursor.fetchone()
            
            if row:
                notification = dict(row)
                # Parse JSON fields
                try:
                    notification['languages'] = json.loads(notification.get('languages', '[]'))
                except json.JSONDecodeError:
                    notification['languages'] = []
                try:
                    notification['subtitles'] = json.loads(notification.get('subtitles', '[]'))
                except json.JSONDecodeError:
                    notification['subtitles'] = []
                return notification
            return None
    
    def get_all(self, status_filter: str = None, limit: int = None) -> List[Dict]:
        """Get all webhook notifications with optional filtering"""
        query = "SELECT * FROM radarr_webhook"
        params = []
        
        if status_filter:
            query += " WHERE status = ?"
            params.append(status_filter)
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        with self.db.get_connection() as conn:
            cursor = conn.execute(query, params)
            notifications = []
            
            for row in cursor.fetchall():
                notification = dict(row)
                # Parse JSON fields
                try:
                    notification['languages'] = json.loads(notification.get('languages', '[]'))
                except json.JSONDecodeError:
                    notification['languages'] = []
                try:
                    notification['subtitles'] = json.loads(notification.get('subtitles', '[]'))
                except json.JSONDecodeError:
                    notification['subtitles'] = []
                notifications.append(notification)
            
            return notifications
    
    def delete(self, notification_id: str) -> bool:
        """Delete webhook notification record"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM radarr_webhook WHERE notification_id = ?
            ''', (notification_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Clean up old processed notifications"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM radarr_webhook 
                WHERE status IN ('completed', 'failed')
                AND datetime(created_at) < datetime('now', '-{} days')
            '''.format(days))
            conn.commit()
            return cursor.rowcount


class SeriesWebhookNotification:
    """
    SeriesWebhookNotification model for series/anime webhook notifications
    
    STATE LIFECYCLE DOCUMENTATION
    =============================
    
    This model tracks webhook notifications through a comprehensive state lifecycle
    designed for series/anime auto-sync with intelligent queuing and validation.
    
    POSSIBLE STATES:
    ---------------
    1. PENDING
       - Initial state when webhook is received
       - Notifications batch here during auto-sync wait period
       - Transitions to: READY_FOR_TRANSFER, MANUAL_SYNC_REQUIRED
       
    2. READY_FOR_TRANSFER
       - Dry-run validation passed, ready for transfer service to pick up
       - Waiting for slot availability and path conflict checks
       - Transitions to: SYNCING, QUEUED_SLOT, QUEUED_PATH
       
    3. QUEUED_SLOT
       - Blocked by max concurrent transfer limit (3 transfers)
       - Waiting for ANY transfer to complete to free a slot
       - Transitions to: READY_FOR_TRANSFER (when slot available)
       
    4. QUEUED_PATH
       - Blocked by same destination path conflict
       - Waiting for SAME PATH transfer to complete
       - Transitions to: READY_FOR_TRANSFER (when same path completes)
       
    5. SYNCING
       - Transfer actively in progress
       - rsync process running for this season folder
       - Transitions to: COMPLETED, FAILED, CANCELLED
       
    6. COMPLETED
       - Transfer finished successfully
       - Terminal state
       
    7. FAILED
       - Transfer failed or error occurred
       - Terminal state (can be retried)
       
    8. MANUAL_SYNC_REQUIRED
       - Dry-run validation failed (safety checks)
       - Requires manual user intervention
       - Terminal state (until manual sync)
       
    9. CANCELLED
       - User cancelled the transfer
       - Terminal state
    
    STATE TRANSITION RULES:
    ----------------------
    - BATCHING: Multiple webhooks for same series/season accumulate in PENDING
      during wait period (tracked by auto_sync_scheduled_at field)
      
    - DRY-RUN: Performed once per batch. ALL notifications in batch get same
      result and transition together (all to READY_FOR_TRANSFER or all to
      MANUAL_SYNC_REQUIRED)
      
    - SAME-PATH GROUPING: When one notification transitions to SYNCING or
      QUEUED_PATH, ALL notifications with same destination path transition
      together (ensures consistency)
      
    - COMPLETION MARKING: Only notifications in SYNCING state are marked
      COMPLETED when transfer finishes. PENDING notifications (arrived during
      sync) stay PENDING for next cycle.
    
    QUEUE PRIORITY:
    --------------
    1. Path-specific queue (QUEUED_PATH) - Promoted when SAME PATH completes
    2. Slot queue (QUEUED_SLOT) - Promoted when ANY transfer completes
    
    """
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def create(self, notification_data: Dict, raw_webhook_data: str = None) -> str:
        """Create a new series webhook notification record"""
        print(f"📝 Creating series webhook notification for {notification_data.get('series_title', 'Unknown')}")
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO sonarr_webhook (
                        notification_id, media_type, series_title, series_title_slug, series_id,
                        series_path, year, tvdb_id, tv_maze_id, tmdb_id, imdb_id,
                        poster_url, banner_url, tags, original_language, requested_by,
                        season_number, episode_count, episodes, episode_files, season_path,
                        release_title, release_indexer, release_size, download_client, status, raw_webhook_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    notification_data['notification_id'],
                    notification_data['media_type'],
                    notification_data['series_title'],
                    notification_data.get('series_title_slug'),
                    notification_data.get('series_id'),
                    notification_data['series_path'],
                    notification_data.get('year'),
                    notification_data.get('tvdb_id'),
                    notification_data.get('tv_maze_id'),
                    notification_data.get('tmdb_id'),
                    notification_data.get('imdb_id'),
                    notification_data.get('poster_url'),
                    notification_data.get('banner_url'),
                    json.dumps(notification_data.get('tags', [])),
                    notification_data.get('original_language'),
                    notification_data.get('requested_by'),
                    notification_data.get('season_number'),
                    notification_data.get('episode_count', 1),
                    json.dumps(notification_data.get('episodes', [])),
                    json.dumps(notification_data.get('episode_files', [])),
                    notification_data['season_path'],
                    notification_data.get('release_title'),
                    notification_data.get('release_indexer'),
                    notification_data.get('release_size', 0),
                    notification_data.get('download_client'),
                    notification_data.get('status', 'pending'),
                    raw_webhook_data
                ))
                conn.commit()
                print(f"✅ Series webhook notification created successfully for {notification_data.get('series_title', 'Unknown')}")
                return notification_data['notification_id']
        except Exception as e:
            print(f"❌ Error creating series webhook notification: {e}")
            raise
    
    def update(self, notification_id: str, updates: Dict) -> bool:
        """Update series webhook notification"""
        try:
            with self.db.get_connection() as conn:
                # Build dynamic update query
                update_fields = []
                values = []
                
                for key, value in updates.items():
                    if key == 'notification_id':  # Skip updating the primary key
                        continue
                    update_fields.append(f"{key} = ?")
                    values.append(value)
                
                if not update_fields:
                    return False
                
                values.append(notification_id)
                
                cursor = conn.execute(f'''
                    UPDATE sonarr_webhook 
                    SET {", ".join(update_fields)}
                    WHERE notification_id = ?
                ''', values)
                
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ Error updating series webhook notification: {e}")
            return False
    
    def get(self, notification_id: str) -> Optional[Dict]:
        """Get series webhook notification by ID"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM sonarr_webhook WHERE notification_id = ?
            ''', (notification_id,))
            row = cursor.fetchone()
            
            if row:
                notification = dict(row)
                # Parse JSON fields
                for json_field in ['tags', 'episodes', 'episode_files']:
                    try:
                        notification[json_field] = json.loads(notification.get(json_field, '[]'))
                    except json.JSONDecodeError:
                        notification[json_field] = []
                return notification
            return None
    
    def get_by_transfer_id(self, transfer_id: str) -> Optional[Dict]:
        """Get series webhook notification by transfer_id (efficient indexed lookup)"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM sonarr_webhook WHERE transfer_id = ?
            ''', (transfer_id,))
            row = cursor.fetchone()
            
            if row:
                notification = dict(row)
                # Parse JSON fields
                for json_field in ['tags', 'episodes', 'episode_files']:
                    try:
                        notification[json_field] = json.loads(notification.get(json_field, '[]'))
                    except json.JSONDecodeError:
                        notification[json_field] = []
                return notification
            return None
    
    def get_all(self, media_type_filter: str = None, status_filter: str = None, limit: int = None) -> List[Dict]:
        """Get all series webhook notifications with optional filtering"""
        query = "SELECT * FROM sonarr_webhook"
        params = []
        conditions = []
        
        if media_type_filter:
            # Handle both 'tvshows' and legacy 'series' for backward compatibility
            if media_type_filter == 'tvshows':
                conditions.append("(media_type = ? OR media_type = ?)")
                params.extend(['tvshows', 'series'])
            else:
                conditions.append("media_type = ?")
                params.append(media_type_filter)
            
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        with self.db.get_connection() as conn:
            cursor = conn.execute(query, params)
            notifications = []
            
            for row in cursor.fetchall():
                notification = dict(row)
                # Parse JSON fields
                for json_field in ['tags', 'episodes', 'episode_files']:
                    try:
                        notification[json_field] = json.loads(notification.get(json_field, '[]'))
                    except json.JSONDecodeError:
                        notification[json_field] = []
                notifications.append(notification)
            
            return notifications
    
    def delete(self, notification_id: str) -> bool:
        """Delete series webhook notification record"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM sonarr_webhook WHERE notification_id = ?
            ''', (notification_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Clean up old processed notifications"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM sonarr_webhook 
                WHERE status IN ('completed', 'failed') 
                AND created_at < datetime('now', '-{} days')
            '''.format(days))
            conn.commit()
            return cursor.rowcount
    
    def mark_same_path_notifications_as_syncing(self, season_path: str, transfer_id: str) -> int:
        """
        Mark all READY_FOR_TRANSFER notifications with same season_path as SYNCING
        
        This ensures that when a transfer starts for a season folder, ALL notifications
        for that same destination path are marked as SYNCING together (since rsync
        syncs the entire season folder, all episodes get transferred together).
        
        Args:
            season_path: The season destination path (e.g., "/path/to/Series/Season 01")
            transfer_id: The transfer ID to associate with these notifications
            
        Returns:
            Count of notifications marked as SYNCING
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    UPDATE sonarr_webhook 
                    SET status = 'syncing', 
                        transfer_id = ?,
                        completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'READY_FOR_TRANSFER'
                    AND season_path = ?
                ''', (transfer_id, season_path))
                conn.commit()
                updated_count = cursor.rowcount
                
                if updated_count > 0:
                    print(f"✅ Marked {updated_count} READY_FOR_TRANSFER notification(s) as SYNCING for path: {season_path}")
                
                return updated_count
        except Exception as e:
            print(f"❌ Error marking same-path notifications as syncing: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def mark_same_path_notifications_as_queued(self, season_path: str, queue_type: str) -> int:
        """
        Mark all READY_FOR_TRANSFER notifications with same season_path as QUEUED
        
        Args:
            season_path: The season destination path
            queue_type: Either 'QUEUED_SLOT' or 'QUEUED_PATH'
            
        Returns:
            Count of notifications marked as queued
        """
        if queue_type not in ['QUEUED_SLOT', 'QUEUED_PATH']:
            print(f"❌ Invalid queue_type: {queue_type}. Must be QUEUED_SLOT or QUEUED_PATH")
            return 0
            
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    UPDATE sonarr_webhook 
                    SET status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'READY_FOR_TRANSFER'
                    AND season_path = ?
                ''', (queue_type, season_path))
                conn.commit()
                updated_count = cursor.rowcount
                
                if updated_count > 0:
                    print(f"✅ Marked {updated_count} READY_FOR_TRANSFER notification(s) as {queue_type} for path: {season_path}")
                
                return updated_count
        except Exception as e:
            print(f"❌ Error marking same-path notifications as queued: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def get_notifications_by_season_path(self, season_path: str, status_filter: str = None) -> List[Dict]:
        """
        Get all notifications for a specific season path, optionally filtered by status
        
        Args:
            season_path: The season destination path
            status_filter: Optional status to filter by
            
        Returns:
            List of notification dictionaries
        """
        try:
            with self.db.get_connection() as conn:
                if status_filter:
                    cursor = conn.execute('''
                        SELECT * FROM sonarr_webhook
                        WHERE season_path = ? AND status = ?
                        ORDER BY created_at ASC
                    ''', (season_path, status_filter))
                else:
                    cursor = conn.execute('''
                        SELECT * FROM sonarr_webhook
                        WHERE season_path = ?
                        ORDER BY created_at ASC
                    ''', (season_path,))
                
                notifications = []
                for row in cursor.fetchall():
                    notification = dict(row)
                    # Parse JSON fields
                    for json_field in ['tags', 'episodes', 'episode_files']:
                        try:
                            notification[json_field] = json.loads(notification.get(json_field, '[]'))
                        except json.JSONDecodeError:
                            notification[json_field] = []
                    notifications.append(notification)
                
                return notifications
        except Exception as e:
            print(f"❌ Error getting notifications by season path: {e}")
            return []
    
    def link_notifications_to_transfer(self, notification_ids: List[str], transfer_id: str) -> int:
        """
        Link multiple notifications to the same transfer_id
        
        This is used when batching multiple episode notifications into a single transfer.
        All notifications in the batch should be linked to the same transfer_id so they
        can be updated together as the transfer progresses.
        
        Args:
            notification_ids: List of notification IDs to link
            transfer_id: The transfer ID to link them to
            
        Returns:
            Count of notifications linked
        """
        if not notification_ids or not transfer_id:
            return 0
        
        try:
            with self.db.get_connection() as conn:
                # Use IN clause to update all notifications at once
                placeholders = ','.join('?' * len(notification_ids))
                query = f'''
                    UPDATE sonarr_webhook
                    SET transfer_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE notification_id IN ({placeholders})
                '''
                
                params = [transfer_id] + notification_ids
                cursor = conn.execute(query, params)
                conn.commit()
                
                updated_count = cursor.rowcount
                if updated_count > 0:
                    print(f"✅ Linked {updated_count} notification(s) to transfer {transfer_id}")
                    for notif_id in notification_ids:
                        print(f"   - {notif_id}")
                
                return updated_count
        except Exception as e:
            print(f"❌ Error linking notifications to transfer: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def update_notifications_by_transfer_id(self, transfer_id: str, updates: Dict) -> int:
        """
        Update all notifications linked to a specific transfer_id
        
        This ensures all notifications in a batch maintain the same status as their
        transfer progresses through different states.
        
        Args:
            transfer_id: The transfer ID to match
            updates: Dictionary of field updates
            
        Returns:
            Count of notifications updated
        """
        if not transfer_id or not updates:
            return 0
        
        try:
            with self.db.get_connection() as conn:
                # Build dynamic update query
                set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
                values = list(updates.values()) + [transfer_id]
                
                query = f'''
                    UPDATE sonarr_webhook 
                    SET {set_clause},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE transfer_id = ?
                '''
                
                cursor = conn.execute(query, values)
                conn.commit()
                
                updated_count = cursor.rowcount
                if updated_count > 0:
                    print(f"✅ Updated {updated_count} notification(s) for transfer {transfer_id}: {updates}")
                
                return updated_count
        except Exception as e:
            print(f"❌ Error updating notifications by transfer_id: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def mark_notifications_completed_by_transfer(self, transfer_id: str) -> int:
        """
        Mark all notifications linked to a specific transfer as COMPLETED
        
        This is the preferred method for marking completions as it uses transfer_id
        linkage instead of series/season matching, ensuring only notifications that
        were actually part of the completed transfer are marked.
        
        Args:
            transfer_id: The transfer ID that completed
            
        Returns:
            Count of notifications marked as completed
        """
        if not transfer_id:
            return 0
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    UPDATE sonarr_webhook 
                    SET status = 'completed', 
                        completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE transfer_id = ?
                    AND status = 'syncing'
                ''', (transfer_id,))
                conn.commit()
                updated_count = cursor.rowcount
                
                if updated_count > 0:
                    print(f"✅ Marked {updated_count} notification(s) as COMPLETED for transfer {transfer_id}")
                
                return updated_count
        except Exception as e:
            print(f"❌ Error marking notifications as completed by transfer: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def mark_pending_by_series_season_completed(self, series_title: str, season_number: int, media_type: str) -> int:
        """
        Mark all SYNCING notifications as COMPLETED for a given series/season
        
        IMPORTANT: Only marks notifications in SYNCING state as completed.
        This prevents premature completion marking.
        
        WHY ONLY SYNCING?
        - SYNCING: Actively being transferred → Mark as COMPLETED ✓
        - PENDING: Arrived during sync → Keep for next cycle ✓
        - READY_FOR_TRANSFER: Validated but not started → Keep ✓
        - QUEUED_SLOT: Waiting for transfer slot → Keep ✓
        - QUEUED_PATH: Waiting for same path → Keep ✓
        
        BUG PREVENTED: If we marked all PENDING/QUEUED notifications as completed,
        episodes arriving during an active sync or waiting in queue would be
        incorrectly marked completed before they actually transferred.
        
        Returns count of updated records
        """
        #TODO: improve this function to match only SEASON PATH instead of parsing season number and series title
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    UPDATE sonarr_webhook 
                    SET status = 'completed', 
                        completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'syncing'
                    AND media_type = ?
                    AND series_title = ?
                    AND season_number = ?
                ''', (media_type, series_title, season_number))
                conn.commit()
                updated_count = cursor.rowcount
                
                if updated_count > 0:
                    print(f"✅ Marked {updated_count} SYNCING notification(s) as COMPLETED for {series_title} Season {season_number}")
                
                return updated_count
        except Exception as e:
            print(f"❌ Error marking notifications as completed: {e}")
            import traceback
            traceback.print_exc()
            return 0


class RenameNotification:
    """
    RenameNotification model for file rename webhook notifications from Sonarr
    
    Handles rename events where Sonarr renames files on the server and we need
    to reflect those changes in local files.
    
    STATUS VALUES:
    - 'pending': Webhook received, not yet processed
    - 'completed': All files renamed successfully
    - 'partial': Some files renamed, some failed
    - 'failed': All files failed to rename
    """
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def create(self, notification_data: Dict, raw_webhook_data: str = None) -> str:
        """Create a new rename notification record"""
        print(f"📝 Creating rename notification for {notification_data.get('series_title', 'Unknown')}")
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO rename_webhook (
                        notification_id, media_type, series_title, series_id, series_path,
                        renamed_files, total_files, success_count, failed_count,
                        status, error_message, raw_webhook_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    notification_data['notification_id'],
                    notification_data['media_type'],
                    notification_data['series_title'],
                    notification_data.get('series_id'),
                    notification_data['series_path'],
                    json.dumps(notification_data.get('renamed_files', [])),
                    notification_data.get('total_files', 0),
                    notification_data.get('success_count', 0),
                    notification_data.get('failed_count', 0),
                    notification_data.get('status', 'pending'),
                    notification_data.get('error_message'),
                    raw_webhook_data
                ))
                conn.commit()
                print(f"✅ Rename notification created successfully for {notification_data.get('series_title', 'Unknown')}")
                return notification_data['notification_id']
        except Exception as e:
            print(f"❌ Error creating rename notification: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def update(self, notification_id: str, updates: Dict) -> bool:
        """Update rename notification record"""
        if not updates:
            return False
        
        # Convert lists to JSON strings if present
        if 'renamed_files' in updates and isinstance(updates['renamed_files'], list):
            updates['renamed_files'] = json.dumps(updates['renamed_files'])
        
        # Add updated_at timestamp
        updates['updated_at'] = datetime.now().isoformat()
        
        try:
            with self.db.get_connection() as conn:
                # Build dynamic update query
                set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
                values = list(updates.values()) + [notification_id]
                
                cursor = conn.execute(f'''
                    UPDATE rename_webhook SET {set_clause}
                    WHERE notification_id = ?
                ''', values)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ Error updating rename notification: {e}")
            return False
    
    def get(self, notification_id: str) -> Optional[Dict]:
        """Get rename notification by ID"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM rename_webhook WHERE notification_id = ?
            ''', (notification_id,))
            row = cursor.fetchone()
            
            if row:
                notification = dict(row)
                # Parse JSON fields
                try:
                    notification['renamed_files'] = json.loads(notification.get('renamed_files', '[]'))
                except json.JSONDecodeError:
                    notification['renamed_files'] = []
                return notification
            return None
    
    def get_all(self, status_filter: str = None, media_type_filter: str = None, limit: int = None) -> List[Dict]:
        """Get all rename notifications with optional filtering"""
        query = "SELECT * FROM rename_webhook"
        params = []
        conditions = []
        
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        
        if media_type_filter:
            conditions.append("media_type = ?")
            params.append(media_type_filter)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        with self.db.get_connection() as conn:
            cursor = conn.execute(query, params)
            notifications = []
            
            for row in cursor.fetchall():
                notification = dict(row)
                # Parse JSON fields
                try:
                    notification['renamed_files'] = json.loads(notification.get('renamed_files', '[]'))
                except json.JSONDecodeError:
                    notification['renamed_files'] = []
                notifications.append(notification)
            
            return notifications
    
    def delete(self, notification_id: str) -> bool:
        """Delete rename notification record"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM rename_webhook WHERE notification_id = ?
            ''', (notification_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Clean up old processed notifications"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM rename_webhook 
                WHERE status IN ('completed', 'partial', 'failed')
                AND created_at < datetime('now', '-{} days')
            '''.format(days))
            conn.commit()
            return cursor.rowcount



# ---------------------------------------------------------------------------
# Cross-table notification listing
# ---------------------------------------------------------------------------

# Movie and series notifications live in separate tables with different shapes,
# but the UI shows them as one list. Reading each table with the same limit and
# merging in Python - what this replaces - both loses rows (the newest 50 of
# each is not the newest 50 overall once one source dominates) and cannot report
# how many notifications actually match, only how many were returned.

# What a person would search for: what it was called, where it went, who asked.
_RADARR_SEARCH_COLUMNS = (
    'title', 'folder_path', 'file_path', 'release_title', 'requested_by', 'notification_id',
)
_SONARR_SEARCH_COLUMNS = (
    'series_title', 'season_path', 'series_path', 'release_title', 'requested_by', 'notification_id',
)

# 'movie'/'movies' select the Radarr table, anything else the Sonarr table.
_MOVIE_TYPES = {'movie', 'movies'}


class NotificationCatalog:
    """
    Movie and series webhook notifications read as a single ordered list.

    Ordering, paging and counting happen in SQL across both tables at once, so a
    page is the newest N notifications overall and the total is the real number
    of matches rather than the size of the page.
    """

    def __init__(self, db_manager, webhook_model, series_webhook_model):
        self.db = db_manager
        self.webhook_model = webhook_model
        self.series_webhook_model = series_webhook_model

    def _tables_for(self, media_type: str = None) -> List[str]:
        """Which tables a media-type filter selects."""
        if not media_type:
            return ['radarr_webhook', 'sonarr_webhook']
        return ['radarr_webhook'] if media_type in _MOVIE_TYPES else ['sonarr_webhook']

    def _where(self, table: str, status: str = None, media_type: str = None,
               search: str = None):
        """WHERE fragment and parameters for one table."""
        conditions, params = [], []

        if status:
            conditions.append("status = ?")
            params.append(status)

        # Only the series table distinguishes tvshows from anime; 'series' is a
        # legacy value for the same thing and has to keep matching.
        if table == 'sonarr_webhook' and media_type and media_type not in _MOVIE_TYPES:
            if media_type in ('tvshows', 'series'):
                conditions.append("(media_type = ? OR media_type = ?)")
                params.extend(['tvshows', 'series'])
            else:
                conditions.append("media_type = ?")
                params.append(media_type)

        if search:
            columns = _RADARR_SEARCH_COLUMNS if table == 'radarr_webhook' else _SONARR_SEARCH_COLUMNS
            conditions.append("(" + " OR ".join(f"{c} LIKE ?" for c in columns) + ")")
            params.extend([f"%{search.strip()}%"] * len(columns))

        return (" WHERE " + " AND ".join(conditions)) if conditions else "", params

    def count(self, status: str = None, media_type: str = None, search: str = None) -> int:
        """How many notifications match, across both tables."""
        total = 0
        with self.db.get_connection() as conn:
            for table in self._tables_for(media_type):
                where, params = self._where(table, status, media_type, search)
                total += conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}{where}", params
                ).fetchone()['n']
        return total

    def status_counts(self, media_type: str = None, search: str = None) -> Dict[str, int]:
        """
        Match count per status, so the filter buttons can show how many are
        behind each one without the client fetching every page to find out.
        """
        counts: Dict[str, int] = {}
        with self.db.get_connection() as conn:
            for table in self._tables_for(media_type):
                where, params = self._where(table, None, media_type, search)
                rows = conn.execute(
                    f"SELECT status, COUNT(*) AS n FROM {table}{where} GROUP BY status", params
                ).fetchall()
                for row in rows:
                    counts[row['status']] = counts.get(row['status'], 0) + row['n']
        return counts

    def _ordered_keys(self, status=None, media_type=None, search=None,
                      limit=None, offset=0) -> List[tuple]:
        """
        (table, notification_id) for the matching rows, newest first.

        Selecting only the keys keeps the union cheap regardless of how wide and
        how different the two tables are; the page is then read from each table
        with its own columns intact.
        """
        selects, params = [], []
        for table in self._tables_for(media_type):
            where, table_params = self._where(table, status, media_type, search)
            selects.append(
                f"SELECT '{table}' AS source_table, notification_id, created_at FROM {table}{where}"
            )
            params.extend(table_params)

        query = " UNION ALL ".join(selects) + " ORDER BY created_at DESC, notification_id DESC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        with self.db.get_connection() as conn:
            return [(row['source_table'], row['notification_id'])
                    for row in conn.execute(query, params).fetchall()]

    def page(self, status: str = None, media_type: str = None, search: str = None,
             limit: int = 50, offset: int = 0) -> List[Dict]:
        """
        One page of notifications, newest first, in display shape.

        Each row carries `media_type` and `display_title` so the UI does not
        have to know which table it came from.
        """
        keys = self._ordered_keys(status, media_type, search, limit, offset)
        if not keys:
            return []

        by_table: Dict[str, List[str]] = {}
        for table, notification_id in keys:
            by_table.setdefault(table, []).append(notification_id)

        loaded: Dict[tuple, Dict] = {}
        for table, ids in by_table.items():
            model = self.webhook_model if table == 'radarr_webhook' else self.series_webhook_model
            for notification in self._load(model, table, ids):
                loaded[(table, notification['notification_id'])] = notification

        # Reassemble in the order the union produced, which is the only place
        # the two tables are ranked against each other.
        return [loaded[key] for key in keys if key in loaded]

    def _load(self, model, table: str, ids: List[str]) -> List[Dict]:
        """Full rows for a page's ids, decorated for display."""
        placeholders = ", ".join("?" for _ in ids)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE notification_id IN ({placeholders})", ids
            ).fetchall()

        notifications = []
        for row in rows:
            notification = dict(row)
            if table == 'radarr_webhook':
                for field in ('languages', 'subtitles'):
                    notification[field] = _parse_json_list(notification.get(field))
                notification['media_type'] = 'movie'
                notification['display_title'] = notification.get('title')
            else:
                for field in ('tags', 'episodes', 'episode_files'):
                    notification[field] = _parse_json_list(notification.get(field))
                season = notification.get('season_number')
                season_text = f" Season {season}" if season else ""
                notification['display_title'] = f"{notification.get('series_title')}{season_text}"
            notifications.append(notification)
        return notifications

    def delete(self, notification_ids: List[str]) -> int:
        """
        Delete notifications by id, from whichever table holds them.

        Ids are unique across both tables, so a delete is issued against each
        and only the owning table matches. That keeps the caller from having to
        track which source a row came from.
        """
        if not notification_ids:
            return 0

        deleted = 0
        with self.db.get_connection() as conn:
            for start in range(0, len(notification_ids), _DELETE_BATCH):
                batch = notification_ids[start:start + _DELETE_BATCH]
                placeholders = ", ".join("?" for _ in batch)
                for table in ('radarr_webhook', 'sonarr_webhook'):
                    deleted += conn.execute(
                        f"DELETE FROM {table} WHERE notification_id IN ({placeholders})", batch
                    ).rowcount
            conn.commit()
        return deleted

    def delete_matching(self, status: str = None, media_type: str = None,
                        search: str = None) -> int:
        """
        Delete every notification matching a filter.

        This is what "select all" performs: the filter is re-evaluated on the
        server rather than the client sending thousands of ids, so what gets
        deleted is exactly what the filter describes.
        """
        deleted = 0
        with self.db.get_connection() as conn:
            for table in self._tables_for(media_type):
                where, params = self._where(table, status, media_type, search)
                deleted += conn.execute(f"DELETE FROM {table}{where}", params).rowcount
            conn.commit()
        return deleted


# SQLite's default variable limit is 999; stay well inside it per statement.
_DELETE_BATCH = 400


def _parse_json_list(raw) -> List:
    """A JSON list column, tolerating the nulls and blanks older rows contain."""
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw or '[]')
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []
