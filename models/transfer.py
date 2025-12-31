#!/usr/bin/env python3
"""
DragonCP Transfer Model (v2)
Database model for transfer operations and metadata parsing

Schema v2 Changes:
- Removed: episode_name, parsed_episode columns
- Renamed: transfer_type → operation_type
- Renamed: process_id → rsync_process_id
"""

import json
import re
from datetime import datetime
from typing import List, Dict, Optional


class Transfer:
    """Transfer model for database operations"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def create(self, transfer_data: Dict) -> str:
        """Create a new transfer record"""
        print(f"📝 Creating transfer record for {transfer_data['transfer_id']}")
        print(f"📝 Transfer data: {transfer_data}")
        
        # Parse metadata from folder and season names
        parsed_data = self._parse_metadata(
            transfer_data.get('folder_name', ''),
            transfer_data.get('season_name', ''),
            transfer_data.get('media_type', '')
        )
        
        print(f"📝 Parsed metadata: {parsed_data}")
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO transfers (
                        transfer_id, media_type, folder_name, season_name,
                        source_path, dest_path, operation_type, status, rsync_process_id,
                        parsed_title, parsed_season, start_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    transfer_data['transfer_id'],
                    transfer_data['media_type'],
                    transfer_data['folder_name'],
                    transfer_data.get('season_name'),
                    transfer_data['source_path'],
                    transfer_data['dest_path'],
                    transfer_data['operation_type'],
                    transfer_data.get('status', 'pending'),
                    transfer_data.get('rsync_process_id'),
                    parsed_data['title'],
                    parsed_data['season'],
                    datetime.now().isoformat()
                ))
                conn.commit()
                print(f"✅ Transfer record created successfully for {transfer_data['transfer_id']}")
                return transfer_data['transfer_id']
        except Exception as e:
            print(f"❌ Error creating transfer record: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def update(self, transfer_id: str, updates: Dict) -> bool:
        """Update transfer record"""
        if not updates:
            return False
        
        # Add updated_at timestamp
        updates['updated_at'] = datetime.now().isoformat()
        
        # Convert logs to JSON string if present
        if 'logs' in updates and isinstance(updates['logs'], list):
            updates['logs'] = json.dumps(updates['logs'])
        
        # Build dynamic update query
        set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
        values = list(updates.values()) + [transfer_id]
        
        with self.db.get_connection() as conn:
            cursor = conn.execute(f'''
                UPDATE transfers SET {set_clause}
                WHERE transfer_id = ?
            ''', values)
            conn.commit()
            return cursor.rowcount > 0
    
    def get(self, transfer_id: str) -> Optional[Dict]:
        """Get transfer by ID"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM transfers WHERE transfer_id = ?
            ''', (transfer_id,))
            row = cursor.fetchone()
            
            if row:
                transfer = dict(row)
                # Parse logs from JSON
                if transfer['logs']:
                    try:
                        transfer['logs'] = json.loads(transfer['logs'])
                    except json.JSONDecodeError:
                        transfer['logs'] = []
                else:
                    transfer['logs'] = []
                return transfer
            return None
    
    def get_all(self, status_filter: str = None, limit: int = None) -> List[Dict]:
        """Get all transfers with optional filtering"""
        query = "SELECT * FROM transfers"
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
            transfers = []
            
            for row in cursor.fetchall():
                transfer = dict(row)
                # Parse logs from JSON
                if transfer['logs']:
                    try:
                        transfer['logs'] = json.loads(transfer['logs'])
                    except json.JSONDecodeError:
                        transfer['logs'] = []
                else:
                    transfer['logs'] = []
                transfers.append(transfer)
            
            return transfers
    
    def get_active(self) -> List[Dict]:
        """Get all active (running/pending) transfers"""
        return self.get_all(status_filter=None)  # We'll filter in memory for multiple statuses
    
    def delete(self, transfer_id: str) -> bool:
        """Delete transfer record"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM transfers WHERE transfer_id = ?
            ''', (transfer_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old_transfers(self, days: int = 30) -> int:
        """Clean up old completed transfers"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM transfers 
                WHERE status IN ('completed', 'failed', 'cancelled')
                AND datetime(created_at) < datetime('now', '-{} days')
            '''.format(days))
            conn.commit()
            return cursor.rowcount
    
    def cleanup_duplicate_transfers(self) -> int:
        """Remove duplicate completed transfers per dest_path, keeping only the most recent one."""
        with self.db.get_connection() as conn:
            import sqlite3
            # Find dest_paths that have more than one completed transfer
            duplicate_paths = conn.execute('''
                SELECT dest_path
                FROM transfers
                WHERE status = 'completed' AND dest_path IS NOT NULL
                GROUP BY dest_path
                HAVING COUNT(*) > 1
            ''').fetchall()

            total_deleted = 0

            for row in duplicate_paths:
                dest_path = row[0]

                # Determine the single record to keep for this dest_path
                keep_row = conn.execute('''
                    SELECT id, end_time, updated_at, created_at
                    FROM transfers
                    WHERE status = 'completed' AND dest_path = ?
                    ORDER BY (end_time IS NULL), end_time DESC,
                             (updated_at IS NULL), updated_at DESC,
                             (created_at IS NULL), created_at DESC,
                             id DESC
                    LIMIT 1
                ''', (dest_path,)).fetchone()

                if keep_row is None:
                    continue

                keep_id = keep_row['id'] if isinstance(keep_row, sqlite3.Row) else keep_row[0]

                # Delete all other completed entries for the same dest_path
                cursor = conn.execute('''
                    DELETE FROM transfers
                    WHERE status = 'completed' AND dest_path = ? AND id <> ?
                ''', (dest_path, keep_id))

                deleted_count = cursor.rowcount or 0
                total_deleted += deleted_count
                print(f"🧹 Cleaned up {deleted_count} duplicate transfers for path: {dest_path} (kept id {keep_id})")

            conn.commit()
            return total_deleted
    
    def add_log(self, transfer_id: str, log_line: str) -> bool:
        """Add a log line to transfer"""
        transfer = self.get(transfer_id)
        if not transfer:
            return False
        
        logs = transfer.get('logs', [])
        logs.append(log_line)
        
        return self.update(transfer_id, {
            'logs': logs,
            'progress': log_line
        })
    
    def _parse_metadata(self, folder_name: str, season_name: str = None, 
                       media_type: str = '') -> Dict[str, str]:
        """Parse metadata from folder and season names"""
        
        # Clean and normalize names
        title = self._clean_title(folder_name)
        season = None
        
        # Parse season information
        if season_name:
            season_match = re.search(r'[Ss]eason\s*(\d+)|[Ss](\d+)|(\d+)', season_name)
            if season_match:
                season = season_match.group(1) or season_match.group(2) or season_match.group(3)
        
        return {
            'title': title,
            'season': season
        }
    
    def _clean_title(self, title: str) -> str:
        """Clean and normalize title"""
        if not title:
            return title
        
        # Remove common patterns
        title = re.sub(r'\[\d{4}\]', '', title)  # Remove [2024]
        title = re.sub(r'\(\d{4}\)', '', title)  # Remove (2024)
        title = re.sub(r'\.', ' ', title)  # Replace dots with spaces
        title = re.sub(r'_', ' ', title)  # Replace underscores with spaces
        title = re.sub(r'\s+', ' ', title)  # Multiple spaces to single
        title = title.strip()
        
        return title
    
    def get_sync_status(self, media_type: str, folder_name: str, season_name: str = None, 
                       remote_modification_time: int = 0) -> str:
        """
        Get sync status for a folder/season
        Returns: 'SYNCED', 'OUT_OF_SYNC', or 'NO_INFO'
        """
        try:
            # Build query based on media type
            if media_type == 'movies':
                # For movies, check folder-level transfers only
                query = '''
                    SELECT end_time, updated_at FROM transfers 
                    WHERE media_type = ? AND folder_name = ? AND status = 'completed'
                    AND season_name IS NULL
                    ORDER BY end_time DESC LIMIT 1
                '''
                params = (media_type, folder_name)
            else:
                # For TV shows and anime, check season-level transfers
                if season_name:
                    query = '''
                        SELECT end_time, updated_at FROM transfers 
                        WHERE media_type = ? AND folder_name = ? AND season_name = ? AND status = 'completed'
                        ORDER BY end_time DESC LIMIT 1
                    '''
                    params = (media_type, folder_name, season_name)
                else:
                    # This shouldn't happen for series/anime without season_name
                    return 'NO_INFO'
            
            with self.db.get_connection() as conn:
                cursor = conn.execute(query, params)
                row = cursor.fetchone()
                
                if not row:
                    return 'NO_INFO'
                
                # Convert end_time to timestamp for comparison
                from datetime import datetime
                import time
                
                end_time_str = row['end_time']
                if end_time_str:
                    try:
                        # Parse ISO format datetime
                        end_time_dt = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                        end_time_timestamp = int(end_time_dt.timestamp())
                        
                        # Compare with remote modification time
                        if remote_modification_time > 0:
                            if end_time_timestamp >= remote_modification_time:
                                return 'SYNCED'
                            else:
                                return 'OUT_OF_SYNC'
                        else:
                            # If no remote modification time available, assume synced if we have a completion record
                            return 'SYNCED'
                    except (ValueError, AttributeError):
                        # If we can't parse the date, assume it's synced if we have a record
                        return 'SYNCED'
                else:
                    # Transfer exists but no end_time (shouldn't happen for completed transfers)
                    return 'NO_INFO'
                    
        except Exception as e:
            print(f"❌ Error getting sync status: {e}")
            return 'NO_INFO'
    
    def get_folder_sync_status_summary(self, media_type: str, folder_name: str, 
                                     seasons_with_metadata: List[Dict] = None) -> Dict:
        """
        Get sync status summary for a folder, handling series/anime aggregation logic
        For movies: returns folder-level status
        For series/anime: returns aggregated status based on most recent season
        """
        try:
            if media_type == 'movies':
                # Simple case: just check the folder itself
                status = self.get_sync_status(media_type, folder_name, None, 0)
                return {
                    'status': status,
                    'type': 'movie',
                    'seasons': []
                }
            else:
                # Complex case: check all seasons and aggregate
                if not seasons_with_metadata:
                    return {
                        'status': 'NO_INFO',
                        'type': 'series',
                        'seasons': []
                    }
                
                season_statuses = []
                most_recent_season = None
                most_recent_time = 0
                
                for season_data in seasons_with_metadata:
                    season_name = season_data['name']
                    mod_time = season_data.get('modification_time', 0)
                    
                    status = self.get_sync_status(media_type, folder_name, season_name, mod_time)
                    
                    season_statuses.append({
                        'name': season_name,
                        'status': status,
                        'modification_time': mod_time
                    })
                    
                    # Track most recently modified season
                    if mod_time > most_recent_time:
                        most_recent_time = mod_time
                        most_recent_season = {
                            'name': season_name,
                            'status': status
                        }
                
                # Determine overall status based on most recent season
                overall_status = 'NO_INFO'
                if most_recent_season:
                    overall_status = most_recent_season['status']
                
                return {
                    'status': overall_status,
                    'type': 'series',
                    'seasons': season_statuses,
                    'most_recent_season': most_recent_season
                }
                
        except Exception as e:
            print(f"❌ Error getting folder sync status summary: {e}")
            return {
                'status': 'NO_INFO',
                'type': 'unknown',
                'seasons': []
            }

