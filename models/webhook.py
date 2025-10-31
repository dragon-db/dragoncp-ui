#!/usr/bin/env python3
"""
DragonCP Webhook Models
Database models for webhook notifications (movies, series, anime)
"""

import json
from typing import List, Dict, Optional


class WebhookNotification:
    """WebhookNotification model for movie webhook notifications"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def create(self, notification_data: Dict) -> str:
        """Create a new webhook notification record"""
        print(f"📝 Creating webhook notification for {notification_data.get('title', 'Unknown')}")
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO webhook_notifications (
                        notification_id, title, year, folder_path, poster_url, requested_by,
                        file_path, quality, size, languages, subtitles, 
                        release_title, release_indexer, release_size, tmdb_id, imdb_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    notification_data.get('status', 'pending')
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
        
        # Build dynamic update query
        set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
        values = list(updates.values()) + [notification_id]
        
        with self.db.get_connection() as conn:
            cursor = conn.execute(f'''
                UPDATE webhook_notifications SET {set_clause}
                WHERE notification_id = ?
            ''', values)
            conn.commit()
            return cursor.rowcount > 0
    
    def get(self, notification_id: str) -> Optional[Dict]:
        """Get webhook notification by ID"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM webhook_notifications WHERE notification_id = ?
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
    
    def get_all(self, status_filter: str = None, limit: int = None) -> List[Dict]:
        """Get all webhook notifications with optional filtering"""
        query = "SELECT * FROM webhook_notifications"
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
                DELETE FROM webhook_notifications WHERE notification_id = ?
            ''', (notification_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Clean up old processed notifications"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM webhook_notifications 
                WHERE status IN ('completed', 'failed')
                AND datetime(created_at) < datetime('now', '-{} days')
            '''.format(days))
            conn.commit()
            return cursor.rowcount


class SeriesWebhookNotification:
    """SeriesWebhookNotification model for series/anime webhook notifications"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def create(self, notification_data: Dict) -> str:
        """Create a new series webhook notification record"""
        print(f"📝 Creating series webhook notification for {notification_data.get('series_title', 'Unknown')}")
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO series_webhook_notifications (
                        notification_id, media_type, series_title, series_title_slug, series_id,
                        series_path, year, tvdb_id, tv_maze_id, tmdb_id, imdb_id,
                        poster_url, banner_url, tags, original_language, requested_by,
                        season_number, episode_count, episodes, episode_files, season_path,
                        release_title, release_indexer, release_size, download_client, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    notification_data.get('status', 'pending')
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
                    UPDATE series_webhook_notifications 
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
                SELECT * FROM series_webhook_notifications WHERE notification_id = ?
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
    
    def get_all(self, media_type_filter: str = None, status_filter: str = None, limit: int = None) -> List[Dict]:
        """Get all series webhook notifications with optional filtering"""
        query = "SELECT * FROM series_webhook_notifications"
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
                DELETE FROM series_webhook_notifications WHERE notification_id = ?
            ''', (notification_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Clean up old processed notifications"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM series_webhook_notifications 
                WHERE status IN ('completed', 'failed') 
                AND created_at < datetime('now', '-{} days')
            '''.format(days))
            conn.commit()
            return cursor.rowcount
    
    def mark_pending_by_series_season_completed(self, series_title: str, season_number: int, media_type: str) -> int:
        """
        Mark all PENDING notifications as COMPLETED for a given series/season
        Returns count of updated records
        """
        #TODO: improve this function to match only SEASON PATH insted of parsing season number and series title
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    UPDATE series_webhook_notifications 
                    SET status = 'completed', synced_at = CURRENT_TIMESTAMP
                    WHERE status = 'pending'
                    AND media_type = ?
                    AND series_title = ?
                    AND season_number = ?
                ''', (media_type, series_title, season_number))
                conn.commit()
                updated_count = cursor.rowcount
                
                if updated_count > 0:
                    print(f"✅ Marked {updated_count} PENDING notification(s) as COMPLETED for {series_title} Season {season_number}")
                
                return updated_count
        except Exception as e:
            print(f"❌ Error marking pending notifications as completed: {e}")
            import traceback
            traceback.print_exc()
            return 0

