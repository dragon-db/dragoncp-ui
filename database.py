#!/usr/bin/env python3
"""
DragonCP Database Models - SQLite-based transfer management
Provides persistent storage for transfers, progress tracking, and metadata
"""

import sqlite3
import os
import json
import re
import requests
from datetime import datetime
import uuid
from typing import List, Dict, Optional, Tuple
from pathlib import Path

class DatabaseManager:
    """Database manager for SQLite operations"""
    
    def __init__(self, db_path: str = "dragoncp.db"):
        # Store database path relative to script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.join(script_dir, db_path)
        print(f"🗄️  Database path: {self.db_path}")
        self.init_database()
    
    def init_database(self):
        """Initialize database and create tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transfer_id TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,
                    folder_name TEXT NOT NULL,
                    season_name TEXT,
                    episode_name TEXT,
                    source_path TEXT NOT NULL,
                    dest_path TEXT NOT NULL,
                    transfer_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress TEXT DEFAULT '',
                    process_id INTEGER,
                    logs TEXT DEFAULT '[]',
                    parsed_title TEXT,
                    parsed_season TEXT,
                    parsed_episode TEXT,
                    start_time DATETIME,
                    end_time DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Webhook notifications for automated movie sync
            conn.execute('''
                CREATE TABLE IF NOT EXISTS webhook_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    year INTEGER,
                    folder_path TEXT NOT NULL,
                    poster_url TEXT,
                    requested_by TEXT,
                    file_path TEXT NOT NULL,
                    quality TEXT,
                    size INTEGER DEFAULT 0,
                    languages TEXT DEFAULT '[]',
                    subtitles TEXT DEFAULT '[]',
                    release_title TEXT,
                    release_indexer TEXT,
                    release_size INTEGER DEFAULT 0,
                    tmdb_id INTEGER,
                    imdb_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    synced_at DATETIME,
                    transfer_id TEXT
                )
            ''')

            # Application settings (key-value store for dynamic UI settings)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Backups for rsync --backup deletions
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transfer_backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_id TEXT UNIQUE NOT NULL,
                    transfer_id TEXT NOT NULL,
                    media_type TEXT,
                    folder_name TEXT,
                    season_name TEXT,
                    episode_name TEXT,
                    source_path TEXT NOT NULL,
                    dest_path TEXT NOT NULL,
                    backup_dir TEXT NOT NULL,
                    file_count INTEGER DEFAULT 0,
                    total_size INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    restored_at DATETIME
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transfer_backup_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    file_size INTEGER,
                    modified_time INTEGER,
                    -- Context-aware fields for smarter restore
                    context_media_type TEXT,
                    context_title TEXT,
                    context_release_year TEXT,
                    context_series_title TEXT,
                    context_season TEXT,
                    context_episode TEXT,
                    context_absolute TEXT,
                    context_key TEXT,
                    context_display TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create index for better performance
            conn.execute('CREATE INDEX IF NOT EXISTS idx_transfer_id ON transfers(transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON transfers(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON transfers(created_at)')
            # Helpful for duplicate cleanup queries
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dest_status ON transfers(dest_path, status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_id ON transfer_backup_files(backup_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_context_key ON transfer_backup_files(context_key)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backups_transfer_id ON transfer_backups(transfer_id)')
            # Webhook notifications indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_webhook_notification_id ON webhook_notifications(notification_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_webhook_status ON webhook_notifications(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_webhook_created_at ON webhook_notifications(created_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_webhook_transfer_id ON webhook_notifications(transfer_id)')
            
            conn.commit()
        
        print(f"✅ Database initialized: {self.db_path}")
        # Perform lightweight migrations to add context columns if upgrading from older schema
        self._ensure_backup_file_context_columns()
        self._ensure_webhook_notification_columns()
        self._ensure_app_settings_table()

    def _ensure_backup_file_context_columns(self):
        """Ensure context columns exist on transfer_backup_files for upgrades."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cols = {row[1] for row in conn.execute('PRAGMA table_info(transfer_backup_files)')}
                to_add = []
                def add(col, type_decl):
                    if col not in cols:
                        to_add.append((col, type_decl))
                add('context_media_type', 'TEXT')
                add('context_title', 'TEXT')
                add('context_release_year', 'TEXT')
                add('context_series_title', 'TEXT')
                add('context_season', 'TEXT')
                add('context_episode', 'TEXT')
                add('context_absolute', 'TEXT')
                add('context_key', 'TEXT')
                add('context_display', 'TEXT')
                for col, typ in to_add:
                    try:
                        conn.execute(f'ALTER TABLE transfer_backup_files ADD COLUMN {col} {typ}')
                    except Exception as e:
                        # Ignore if concurrent/multiple attempts
                        pass
                # Ensure index as well
                try:
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_context_key ON transfer_backup_files(context_key)')
                except Exception:
                    pass
                conn.commit()
        except Exception as e:
            print(f"⚠️  Migration check failed: {e}")
    
    def _ensure_webhook_notification_columns(self):
        """Ensure tmdb_id and imdb_id columns exist on webhook_notifications for upgrades."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cols = {row[1] for row in conn.execute('PRAGMA table_info(webhook_notifications)')}
                to_add = []
                def add(col, type_decl):
                    if col not in cols:
                        to_add.append((col, type_decl))
                add('tmdb_id', 'INTEGER')
                add('imdb_id', 'TEXT')
                for col, typ in to_add:
                    try:
                        conn.execute(f'ALTER TABLE webhook_notifications ADD COLUMN {col} {typ}')
                    except Exception as e:
                        # Ignore if concurrent/multiple attempts or table doesn't exist yet
                        pass
                conn.commit()
        except Exception as e:
            print(f"⚠️  Webhook notification migration check failed: {e}")

    def _ensure_app_settings_table(self):
        """Ensure app_settings table exists (for upgrades)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
        except Exception as e:
            print(f"⚠️  App settings table check failed: {e}")
    
    def get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

class AppSettings:
    """Simple key-value settings store in SQLite."""
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT value FROM app_settings WHERE key = ?', (key,)).fetchone()
            return (row[0] if row else default)

    def set(self, key: str, value: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            ''', (key, value))
            conn.commit()

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key)
        if val is None:
            return default
        return str(val).lower() in ('1', 'true', 'yes', 'on')

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, 'true' if value else 'false')

class Transfer:
    """Transfer model for database operations"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def create(self, transfer_data: Dict) -> str:
        """Create a new transfer record"""
        print(f"📝 Creating transfer record for {transfer_data['transfer_id']}")
        print(f"📝 Transfer data: {transfer_data}")
        
        # Parse metadata from folder and season names
        parsed_data = self._parse_metadata(
            transfer_data.get('folder_name', ''),
            transfer_data.get('season_name', ''),
            transfer_data.get('episode_name', ''),
            transfer_data.get('media_type', '')
        )
        
        print(f"📝 Parsed metadata: {parsed_data}")
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO transfers (
                        transfer_id, media_type, folder_name, season_name, episode_name,
                        source_path, dest_path, transfer_type, status, process_id,
                        parsed_title, parsed_season, parsed_episode, start_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    transfer_data['transfer_id'],
                    transfer_data['media_type'],
                    transfer_data['folder_name'],
                    transfer_data.get('season_name'),
                    transfer_data.get('episode_name'),
                    transfer_data['source_path'],
                    transfer_data['dest_path'],
                    transfer_data['transfer_type'],
                    transfer_data.get('status', 'pending'),
                    transfer_data.get('process_id'),
                    parsed_data['title'],
                    parsed_data['season'],
                    parsed_data['episode'],
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
        """Remove duplicate completed transfers per dest_path, keeping only the most recent one.
        """
        with self.db.get_connection() as conn:
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
                       episode_name: str = None, media_type: str = '') -> Dict[str, str]:
        """Parse metadata from folder and file names"""
        
        # Clean and normalize names
        title = self._clean_title(folder_name)
        season = None
        episode = None
        
        # Parse season information
        if season_name:
            season_match = re.search(r'[Ss]eason\s*(\d+)|[Ss](\d+)|(\d+)', season_name)
            if season_match:
                season = season_match.group(1) or season_match.group(2) or season_match.group(3)
        
        # Parse episode information
        if episode_name:
            # Try to extract episode number from filename
            episode_patterns = [
                r'[Ee](\d+)',  # E01, e01
                r'[Ee]pisode\s*(\d+)',  # Episode 01
                r'(\d+)x(\d+)',  # 1x01 format
                r'[Ss]\d+[Ee](\d+)',  # S01E01 format
            ]
            
            for pattern in episode_patterns:
                match = re.search(pattern, episode_name)
                if match:
                    episode = match.group(1) if len(match.groups()) == 1 else match.group(2)
                    break
        
        return {
            'title': title,
            'season': season,
            'episode': episode
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

class Backup:
    """Backup model to track per-transfer rsync backups and files"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def create_or_replace_backup(self, record: Dict) -> str:
        """Create a backup record. If backup_id exists, replace core fields."""
        backup_id = record['backup_id']
        with self.db.get_connection() as conn:
            # Upsert-like behavior
            existing = conn.execute('SELECT id FROM transfer_backups WHERE backup_id = ?', (backup_id,)).fetchone()
            if existing:
                conn.execute('''
                    UPDATE transfer_backups SET
                        transfer_id = ?, media_type = ?, folder_name = ?, season_name = ?, episode_name = ?,
                        source_path = ?, dest_path = ?, backup_dir = ?, file_count = ?, total_size = ?,
                        status = ?, restored_at = NULL, created_at = COALESCE(?, created_at)
                    WHERE backup_id = ?
                ''', (
                    record['transfer_id'], record.get('media_type'), record.get('folder_name'), record.get('season_name'), record.get('episode_name'),
                    record['source_path'], record['dest_path'], record['backup_dir'], record.get('file_count', 0), record.get('total_size', 0),
                    record.get('status', 'ready'), record.get('created_at'), backup_id
                ))
            else:
                if record.get('created_at'):
                    conn.execute('''
                        INSERT INTO transfer_backups (
                            backup_id, transfer_id, media_type, folder_name, season_name, episode_name,
                            source_path, dest_path, backup_dir, file_count, total_size, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        backup_id, record['transfer_id'], record.get('media_type'), record.get('folder_name'), record.get('season_name'), record.get('episode_name'),
                        record['source_path'], record['dest_path'], record['backup_dir'], record.get('file_count', 0), record.get('total_size', 0), record.get('status', 'ready'), record['created_at']
                    ))
                else:
                    conn.execute('''
                        INSERT INTO transfer_backups (
                            backup_id, transfer_id, media_type, folder_name, season_name, episode_name,
                            source_path, dest_path, backup_dir, file_count, total_size, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        backup_id, record['transfer_id'], record.get('media_type'), record.get('folder_name'), record.get('season_name'), record.get('episode_name'),
                        record['source_path'], record['dest_path'], record['backup_dir'], record.get('file_count', 0), record.get('total_size', 0), record.get('status', 'ready')
                    ))
            conn.commit()
        return backup_id
    
    def add_backup_files(self, backup_id: str, files: List[Dict]):
        if not files:
            return 0
        with self.db.get_connection() as conn:
            conn.executemany('''
                INSERT INTO transfer_backup_files (
                    backup_id, relative_path, original_path, file_size, modified_time,
                    context_media_type, context_title, context_release_year, context_series_title,
                    context_season, context_episode, context_absolute, context_key, context_display
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (
                    backup_id,
                    f['relative_path'],
                    f['original_path'],
                    f.get('file_size', 0),
                    f.get('modified_time', 0),
                    f.get('context_media_type'),
                    f.get('context_title'),
                    f.get('context_release_year'),
                    f.get('context_series_title'),
                    f.get('context_season'),
                    f.get('context_episode'),
                    f.get('context_absolute'),
                    f.get('context_key'),
                    f.get('context_display'),
                )
                for f in files
            ])
            conn.commit()
        return len(files)
    
    def get_all(self, limit: int = 100, include_deleted: bool = False) -> List[Dict]:
        query = 'SELECT * FROM transfer_backups'
        params = []
        if not include_deleted:
            query += " WHERE status != 'deleted'"
        query += ' ORDER BY created_at DESC'
        if limit:
            query += ' LIMIT ?'
            params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    
    def get(self, backup_id: str) -> Optional[Dict]:
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT * FROM transfer_backups WHERE backup_id = ?', (backup_id,)).fetchone()
            return dict(row) if row else None
    
    def get_files(self, backup_id: str, limit: int = None) -> List[Dict]:
        query = 'SELECT relative_path, original_path, file_size, modified_time, context_media_type, context_title, context_release_year, context_series_title, context_season, context_episode, context_absolute, context_key, context_display FROM transfer_backup_files WHERE backup_id = ? ORDER BY relative_path'
        params = [backup_id]
        if limit:
            query += ' LIMIT ?'
            params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    
    def update(self, backup_id: str, updates: Dict) -> bool:
        if not updates:
            return False
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [backup_id]
        with self.db.get_connection() as conn:
            cur = conn.execute(f'UPDATE transfer_backups SET {set_clause} WHERE backup_id = ?', values)
            conn.commit()
            return cur.rowcount > 0
    
    def delete(self, backup_id: str) -> int:
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM transfer_backup_files WHERE backup_id = ?', (backup_id,))
            cur = conn.execute('DELETE FROM transfer_backups WHERE backup_id = ?', (backup_id,))
            conn.commit()
            return cur.rowcount

class WebhookNotification:
    """WebhookNotification model for movie webhook notifications"""
    
    def __init__(self, db_manager: DatabaseManager):
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

class TransferManager:
    """Enhanced transfer manager with database persistence"""
    
    def __init__(self, config, db_manager: DatabaseManager, socketio=None):
        print(f"🔄 Initializing TransferManager")
        self.config = config
        self.db = db_manager
        self.transfer_model = Transfer(db_manager)
        self.backup_model = Backup(db_manager)
        self.webhook_model = WebhookNotification(db_manager)
        self.socketio = socketio
        # Settings API
        self.settings = AppSettings(db_manager)
        print(f"✅ Transfer model initialized")
        
        # Resume any transfers that were running when the app was stopped
        self._resume_active_transfers()
    
    def _resume_active_transfers(self):
        """Resume transfers that were running when app was stopped"""
        active_transfers = self.transfer_model.get_all()
        resumed_count = 0
        
        for transfer in active_transfers:
            if transfer['status'] == 'running':
                # Check if process is still running
                if transfer['process_id'] and self._is_process_running(transfer['process_id']):
                    print(f"📋 Resuming monitoring for transfer {transfer['transfer_id']} (PID: {transfer['process_id']})")
                    # Resume monitoring in a separate thread
                    import threading
                    threading.Thread(
                        target=self._resume_transfer_monitoring, 
                        args=(transfer['transfer_id'],), 
                        daemon=True
                    ).start()
                    resumed_count += 1
                else:
                    # Process is no longer running, mark as failed
                    self.transfer_model.update(transfer['transfer_id'], {
                        'status': 'failed',
                        'progress': 'Transfer process was interrupted',
                        'end_time': datetime.now().isoformat()
                    })
                    print(f"❌ Transfer {transfer['transfer_id']} marked as failed (process not found)")
        
        if resumed_count > 0:
            print(f"✅ Resumed monitoring for {resumed_count} active transfers")
    
    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is still running"""
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            # Fallback method without psutil
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
    
    def _resume_transfer_monitoring(self, transfer_id: str):
        """Resume monitoring for an existing transfer"""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return
        
        try:
            import psutil
            process = psutil.Process(transfer['process_id'])
            
            # Monitor the process until completion
            process.wait()
            return_code = process.returncode
            
            if return_code == 0:
                self.transfer_model.update(transfer_id, {
                    'status': 'completed',
                    'progress': 'Transfer completed successfully!',
                    'end_time': datetime.now().isoformat()
                })
            else:
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': f'Transfer failed with exit code: {return_code}',
                    'end_time': datetime.now().isoformat()
                })
                
        except Exception as e:
            print(f"❌ Error resuming monitoring for {transfer_id}: {e}")
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': f'Monitoring failed: {e}',
                'end_time': datetime.now().isoformat()
            })
    
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
        
        # Start the actual transfer process (existing logic from original start_transfer)
        return self._start_rsync_process(transfer_id, source_path, dest_path, transfer_type)
    
    def _start_rsync_process(self, transfer_id: str, source_path: str, dest_path: str, transfer_type: str) -> bool:
        """Start the rsync process (extracted from original method)"""
        try:
            import subprocess
            import threading
            
            print(f"🔄 Starting transfer {transfer_id}")
            print(f"📁 Source: {source_path}")
            print(f"📁 Destination: {dest_path}")
            print(f"📁 Type: {transfer_type}")
            
            # Create destination directory
            try:
                os.makedirs(dest_path, exist_ok=True)
                print(f"✅ Created destination directory: {dest_path}")
            except Exception as e:
                print(f"❌ Failed to create destination directory: {e}")
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': f'Failed to create destination: {e}',
                    'end_time': datetime.now().isoformat()
                })
                return False
            
            # Get SSH connection details
            ssh_user = self.config.get("REMOTE_USER")
            ssh_host = self.config.get("REMOTE_IP")
            ssh_password = self.config.get("REMOTE_PASSWORD", "")
            ssh_key_path = self.config.get("SSH_KEY_PATH", "")
            
            print(f"🔑 SSH User: {ssh_user}")
            print(f"🔑 SSH Host: {ssh_host}")
            print(f"🔑 SSH Key Path: {ssh_key_path}")
            
            if not ssh_user or not ssh_host:
                print("❌ SSH credentials not configured")
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': 'SSH credentials not configured',
                    'end_time': datetime.now().isoformat()
                })
                return False
            
            # Resolve SSH key path to absolute path if it exists
            if ssh_key_path:
                if not os.path.isabs(ssh_key_path):
                    # If relative path, make it absolute relative to the app directory
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    ssh_key_path = os.path.join(script_dir, ssh_key_path)
                
                if not os.path.exists(ssh_key_path):
                    print(f"❌ SSH key file not found: {ssh_key_path}")
                    ssh_key_path = ""
                else:
                    print(f"✅ SSH key found: {ssh_key_path}")
            
            # Determine a dynamic backup directory unique per transfer
            transfer = self.transfer_model.get(transfer_id)
            safe_folder = self._safe_name(transfer.get('folder_name') or 'transfer') if transfer else 'transfer'
            backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
            backup_id = transfer_id  # use transfer_id for stable association
            dynamic_backup_dir = os.path.join(backup_base, f"{safe_folder}_{backup_id}")
            try:
                os.makedirs(dynamic_backup_dir, exist_ok=True)
                os.makedirs(os.path.join(dynamic_backup_dir, '.rsync-partial'), exist_ok=True)
            except Exception as e:
                print(f"⚠️  Could not prepare dynamic backup directory: {e}")
            
            # Build rsync command with SSH connection
            rsync_cmd = [
                "rsync", "-av",
                "--progress",
                "--delete",
                "--backup",
                "--backup-dir", dynamic_backup_dir,
                "--update",
                "--exclude", ".*",
                "--exclude", "*.tmp",
                "--exclude", "*.log",
                "--stats",
                "--human-readable",
                "--bwlimit=0",
                "--block-size=65536",
                "--no-compress",
                "--partial",
                "--partial-dir", f"{dynamic_backup_dir}/.rsync-partial",
                "--timeout=300",
                "--size-only",
                "--no-perms",
                "--no-owner",
                "--no-group",
                "--no-checksum",
                "--whole-file",
                "--preallocate",
                "--no-motd"
            ]
            
            # Build SSH options for rsync
            ssh_options = ["-o", "StrictHostKeyChecking=no", "-o", "Compression=no"]
            if ssh_key_path and os.path.exists(ssh_key_path):
                ssh_options.extend(["-i", ssh_key_path])
            
            rsync_cmd.extend(["-e", f"ssh {' '.join(ssh_options)}"])
            
            if transfer_type == "file":
                rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}", f"{dest_path}/"])
            else:
                rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}/", f"{dest_path}/"])
            
            print(f"🔄 Starting rsync: {' '.join(rsync_cmd)}")
            
            # Start transfer in background
            process = subprocess.Popen(
                rsync_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                env=os.environ.copy()
            )
            
            # Check if process started successfully
            if process.poll() is not None:
                print(f"❌ rsync process failed to start, return code: {process.poll()}")
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': f'rsync process failed to start, return code: {process.poll()}',
                    'end_time': datetime.now().isoformat()
                })
                return False
            
            print(f"✅ rsync process started successfully (PID: {process.pid})")
            
            # Update transfer with process ID and running status
            self.transfer_model.update(transfer_id, {
                'status': 'running',
                'process_id': process.pid,
                'progress': 'Transfer started...'
            })
            
            # Start monitoring thread
            threading.Thread(target=self._monitor_transfer, args=(transfer_id, process), daemon=True).start()
            
            return True
            
        except Exception as e:
            print(f"❌ Transfer start failed: {e}")
            import traceback
            traceback.print_exc()
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': f'Transfer start failed: {e}',
                'end_time': datetime.now().isoformat()
            })
            return False
    
    def _monitor_transfer(self, transfer_id: str, process):
        """Monitor transfer progress with database updates"""
        print(f"🔍 Starting monitoring for transfer {transfer_id} (PID: {process.pid})")
        
        try:
            # Use the socketio instance passed to the constructor
            socketio = self.socketio
            
            # Read output line by line
            for line in iter(process.stdout.readline, ''):
                if line:
                    line = line.strip()
                    
                    # Add log line to database
                    self.transfer_model.add_log(transfer_id, line)
                    
                    # Get updated transfer data
                    transfer = self.transfer_model.get(transfer_id)
                    
                    # Emit progress via WebSocket to all clients
                    if socketio:
                        socketio.emit('transfer_progress', {
                            'transfer_id': transfer_id,
                            'progress': line,
                            'logs': transfer['logs'][-100:],  # Last 100 lines for better visibility
                            'log_count': len(transfer['logs']),
                            'status': transfer.get('status', 'running')
                        })
            
            # Wait for process to complete
            print(f"⏳ Waiting for transfer {transfer_id} to complete...")
            return_code = process.wait()
            print(f"🏁 Transfer {transfer_id} completed with return code: {return_code}")
            
            if return_code == 0:
                status = 'completed'
                progress = 'Transfer completed successfully!'
                print(f"✅ Transfer {transfer_id} completed successfully")
            else:
                status = 'failed'
                progress = f'Transfer failed with exit code: {return_code}'
                print(f"❌ Transfer {transfer_id} failed with exit code: {return_code}")
            
            # Update final status in database
            self.transfer_model.update(transfer_id, {
                'status': status,
                'progress': progress,
                'end_time': datetime.now().isoformat()
            })
            
            # Update webhook notification status if this was a webhook-triggered transfer
            self.update_webhook_transfer_status(transfer_id, status)
            
            # Send Discord notification for completed transfers
            try:
                self.send_discord_notification(transfer_id, status)
            except Exception as de:
                print(f"⚠️  Discord notification error for {transfer_id}: {de}")
            
            # Finalize backup record if any files were backed up
            try:
                self._finalize_backup_for_transfer(transfer_id)
            except Exception as be:
                print(f"⚠️  Backup finalization error for {transfer_id}: {be}")
            
            # Get final transfer data
            transfer = self.transfer_model.get(transfer_id)
            
            # Emit completion status to all clients
            if socketio:
                socketio.emit('transfer_complete', {
                    'transfer_id': transfer_id,
                    'status': status,
                    'message': progress,
                    'logs': transfer['logs'][-100:],
                    'log_count': len(transfer['logs'])
                })
            
        except Exception as e:
            print(f"❌ Error monitoring transfer {transfer_id}: {e}")
            import traceback
            traceback.print_exc()
            
            error_msg = f"Transfer monitoring failed: {e}"
            
            # Update error status in database
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': error_msg,
                'end_time': datetime.now().isoformat()
            })
            
            # Update webhook notification status if this was a webhook-triggered transfer
            self.update_webhook_transfer_status(transfer_id, 'failed')
            
            # Add error to logs
            self.transfer_model.add_log(transfer_id, f"ERROR: {error_msg}")
            
            # Get updated transfer data
            transfer = self.transfer_model.get(transfer_id)
            
            # Emit error to all clients
            if socketio:
                socketio.emit('transfer_complete', {
                    'transfer_id': transfer_id,
                    'status': 'failed',
                    'message': error_msg,
                    'logs': transfer['logs'][-100:],
                    'log_count': len(transfer['logs'])
                })

    def _safe_name(self, name: str) -> str:
        if not name:
            return 'transfer'
        # Reuse simple cleaning similar to _clean_title but stricter for filesystem
        cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_')
        return cleaned or 'transfer'

    def _get_dynamic_backup_dir(self, transfer: Dict) -> str:
        backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
        safe_folder = self._safe_name(transfer.get('folder_name') or 'transfer')
        backup_id = transfer.get('transfer_id') or f"backup_{uuid.uuid4().hex[:8]}"
        return os.path.join(backup_base, f"{safe_folder}_{backup_id}")

    def _finalize_backup_for_transfer(self, transfer_id: str):
        """Scan dynamic backup dir for this transfer and record files in DB if any."""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return
        dynamic_backup_dir = self._get_dynamic_backup_dir(transfer)
        if not os.path.exists(dynamic_backup_dir):
            return
        # Walk and collect files
        total_size = 0
        files = []
        for root, dirs, filenames in os.walk(dynamic_backup_dir):
            for fname in filenames:
                # skip rsync temp/partial metadata if any other than files within .rsync-partial
                if fname.startswith('.') and os.path.basename(root) == '.rsync-partial':
                    continue
                full_path = os.path.join(root, fname)
                try:
                    rel_path = os.path.relpath(full_path, dynamic_backup_dir)
                except Exception:
                    rel_path = fname
                try:
                    stat = os.stat(full_path)
                    size = stat.st_size
                    mtime = int(stat.st_mtime)
                except Exception:
                    size = 0
                    mtime = 0
                total_size += size
                original_path = os.path.join(transfer['dest_path'], rel_path)
                # Detect media context for smarter restore
                ctx = self._detect_context_from_filename(
                    rel_path,
                    transfer.get('media_type') or '',
                    transfer.get('folder_name') or '',
                    transfer.get('season_name') or None
                )
                files.append({
                    'relative_path': rel_path.replace('\\', '/'),
                    'original_path': original_path.replace('\\', '/'),
                    'file_size': size,
                    'modified_time': mtime,
                    'context_media_type': ctx.get('context_media_type'),
                    'context_title': ctx.get('context_title'),
                    'context_release_year': ctx.get('context_release_year'),
                    'context_series_title': ctx.get('context_series_title'),
                    'context_season': ctx.get('context_season'),
                    'context_episode': ctx.get('context_episode'),
                    'context_absolute': ctx.get('context_absolute'),
                    'context_key': ctx.get('context_key'),
                    'context_display': ctx.get('context_display'),
                })
        file_count = len(files)
        if file_count == 0:
            return
        backup_record = {
            'backup_id': transfer_id,
            'transfer_id': transfer_id,
            'media_type': transfer.get('media_type'),
            'folder_name': transfer.get('folder_name'),
            'season_name': transfer.get('season_name'),
            'episode_name': transfer.get('episode_name'),
            'source_path': transfer.get('source_path'),
            'dest_path': transfer.get('dest_path'),
            'backup_dir': dynamic_backup_dir,
            'file_count': file_count,
            'total_size': total_size,
            'status': 'ready',
            'created_at': datetime.utcnow().isoformat() + 'Z'  # Explicit UTC timestamp
        }
        self.backup_model.create_or_replace_backup(backup_record)
        # Replace existing file list if any
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM transfer_backup_files WHERE backup_id = ?', (transfer_id,))
            conn.commit()
        self.backup_model.add_backup_files(transfer_id, files)

    def restore_backup(self, backup_id: str, files: List[str] = None) -> Tuple[bool, str]:
        """Context-aware restore using backup context to safely replace matching media.
        If files is provided, it should be a list of relative paths to restore selectively.
        Steps:
          - Plan matching dest files by context
          - Pre-delete only the context-matched dest file(s)
          - Copy selected backup files into destination (rsync files-from)
        """
        try:
            import subprocess
            import tempfile
            record = self.backup_model.get(backup_id)
            if not record:
                return False, 'Backup not found'
            backup_dir = record['backup_dir']
            dest_path = record['dest_path']
            if not os.path.exists(backup_dir):
                return False, 'Backup directory not found on disk'
            if not os.path.exists(dest_path):
                try:
                    os.makedirs(dest_path, exist_ok=True)
                except Exception as e:
                    return False, f'Failed to create destination: {e}'

            # Build plan
            plan = self.plan_context_restore(backup_id, files)
            operations = plan.get('operations', [])
            if not operations:
                return False, 'No matching files to restore for the selected items'

            # Create a synthetic restore transfer for UI progress/logs
            restore_transfer_id = f"restore_{backup_id}_{int(datetime.now().timestamp())}"
            # Create DB record for visibility
            self.transfer_model.create({
                'transfer_id': restore_transfer_id,
                'media_type': record.get('media_type') or 'backup',
                'folder_name': record.get('folder_name') or '',
                'season_name': record.get('season_name'),
                'episode_name': None,
                'source_path': backup_dir,
                'dest_path': dest_path,
                'transfer_type': 'restore',
                'status': 'running',
                'process_id': None
            })

            # Emit initial plan summary via socket (include context)
            try:
                if self.socketio:
                    self.socketio.emit('transfer_progress', {
                        'transfer_id': restore_transfer_id,
                        'progress': f"Planning restore: {len(operations)} item(s)",
                        'logs': [
                            f"Plan: {op.get('context_display') or op.get('backup_relative')} -> replace {op['target_delete']}"
                            for op in operations
                        ][:100],
                        'log_count': min(len(operations), 100),
                        'status': 'running'
                    })
            except Exception:
                pass

            # Pre-delete target files with context logging. Show context on next line
            deleted = 0
            for op in operations:
                target = op.get('target_delete')
                if target and os.path.exists(target):
                    try:
                        os.remove(target)
                        deleted += 1
                        ctx_disp = op.get('context_display') or op.get('backup_relative')
                        self.transfer_model.add_log(restore_transfer_id, f"Deleted: {target}\nContext: {ctx_disp}")
                    except Exception as e:
                        self.transfer_model.add_log(restore_transfer_id, f"ERROR deleting {target}: {e}")

            # Prepare rsync with selected files
            rsync_cmd = [
                'rsync', '-av', '--progress', '--size-only', '--no-perms', '--no-owner', '--no-group', '--no-motd'
            ]
            temp_list_file = None
            # Use backup_relative from operations to ensure we copy exactly those files
            selected_relatives = [op['backup_relative'] for op in operations]
            if selected_relatives:
                temp_fd, temp_path = tempfile.mkstemp(prefix='backup_files_', text=True)
                os.close(temp_fd)
                with open(temp_path, 'w', newline='\n') as f:
                    for p in selected_relatives:
                        f.write(p.strip().lstrip('/').replace('\\', '/') + '\n')
                rsync_cmd.extend(['-r', f"--files-from={temp_path}"])
                temp_list_file = temp_path

            # Source and destination
            rsync_cmd.extend([f"{backup_dir}/", f"{dest_path}/"]) 
            print(f"🔄 Context-aware restore {backup_id}: {' '.join(rsync_cmd)}")
            result = subprocess.run(rsync_cmd, capture_output=True, text=True)
            # Log copy actions per operation (best-effort), include context on next line
            for op in operations:
                ctx_disp = op.get('context_display') or op.get('backup_relative')
                self.transfer_model.add_log(restore_transfer_id, f"Copied: {op.get('backup_relative')} -> {op.get('copy_to')}\nContext: {ctx_disp}")
            if temp_list_file and os.path.exists(temp_list_file):
                try:
                    os.remove(temp_list_file)
                except Exception:
                    pass

            if result.returncode == 0:
                self.transfer_model.update(restore_transfer_id, {
                    'status': 'completed',
                    'progress': f"Restore completed: {len(operations)} item(s), deleted {deleted}",
                    'end_time': datetime.now().isoformat()
                })
                # Emit completion
                try:
                    if self.socketio:
                        self.socketio.emit('transfer_complete', {
                            'transfer_id': restore_transfer_id,
                            'status': 'completed',
                            'message': f"Restore completed: {len(operations)} items",
                            'logs': self.transfer_model.get(restore_transfer_id).get('logs', [])[-100:],
                            'log_count': len(self.transfer_model.get(restore_transfer_id).get('logs', []))
                        })
                except Exception:
                    pass
                self.backup_model.update(backup_id, {'status': 'restored', 'restored_at': datetime.now().isoformat()})
                return True, 'Restore completed successfully'
            else:
                self.transfer_model.update(restore_transfer_id, {
                    'status': 'failed',
                    'progress': f"Restore failed: {result.stderr or result.stdout}",
                    'end_time': datetime.now().isoformat()
                })
                try:
                    if self.socketio:
                        self.socketio.emit('transfer_complete', {
                            'transfer_id': restore_transfer_id,
                            'status': 'failed',
                            'message': f"Restore failed: {result.stderr or result.stdout}",
                            'logs': self.transfer_model.get(restore_transfer_id).get('logs', [])[-100:],
                            'log_count': len(self.transfer_model.get(restore_transfer_id).get('logs', []))
                        })
                except Exception:
                    pass
                return False, f"Restore failed: {result.stderr or result.stdout}"
        except Exception as e:
            return False, str(e)

    def delete_backup(self, backup_id: str, delete_files: bool = True) -> Tuple[bool, str]:
        try:
            record = self.backup_model.get(backup_id)
            if not record:
                return False, 'Backup not found'
            # This method now only deletes both by default; for independent controls, use delete_backup_options
            if delete_files:
                bdir = record.get('backup_dir')
                if bdir and os.path.exists(bdir):
                    import shutil
                    try:
                        shutil.rmtree(bdir)
                    except Exception as e:
                        return False, f'Failed to remove backup directory: {e}'
            with self.db.get_connection() as conn:
                conn.execute('DELETE FROM transfer_backup_files WHERE backup_id = ?', (backup_id,))
                conn.commit()
            self.backup_model.update(backup_id, {'status': 'deleted'})
            return True, 'Backup deleted'
        except Exception as e:
            return False, str(e)

    def delete_backup_options(self, backup_id: str, delete_record: bool, delete_files: bool) -> Tuple[bool, str]:
        """Delete backup files and/or DB record independently."""
        try:
            record = self.backup_model.get(backup_id)
            if not record:
                return False, 'Backup not found'
            if delete_files:
                bdir = record.get('backup_dir')
                if bdir and os.path.exists(bdir):
                    import shutil
                    try:
                        shutil.rmtree(bdir)
                    except Exception as e:
                        return False, f'Failed to remove backup directory: {e}'
            if delete_record:
                # Remove file rows and high-level record
                with self.db.get_connection() as conn:
                    conn.execute('DELETE FROM transfer_backup_files WHERE backup_id = ?', (backup_id,))
                    conn.commit()
                deleted = self.backup_model.delete(backup_id)
                return True, 'Backup record deleted' if deleted else 'Backup record deletion attempted'
            else:
                # Keep record, update status based on files presence
                new_status = 'ready'
                if delete_files:
                    new_status = 'files_removed'
                self.backup_model.update(backup_id, {'status': new_status})
                return True, 'Backup files removed' if delete_files else 'No changes'
        except Exception as e:
            return False, str(e)

    def plan_context_restore(self, backup_id: str, files: List[str] = None) -> Dict:
        """Plan a context-aware restore: return mapping of which dest files will be replaced by which backups.
        Returns dict with operations: [{backup_relative, backup_full, target_delete, copy_to, context_display}]"""
        record = self.backup_model.get(backup_id)
        if not record:
            return {'operations': []}
        backup_dir = record['backup_dir']
        dest_path = record['dest_path'] or ''
        # Load files with context
        file_rows = self.backup_model.get_files(backup_id)
        if files:
            selected_set = set([p.strip().lstrip('/').replace('\\', '/') for p in files])
            file_rows = [r for r in file_rows if r.get('relative_path') in selected_set]
        ops = []
        for row in file_rows:
            rel = row.get('relative_path')
            backup_full = os.path.join(backup_dir, rel)
            copy_to = row.get('original_path') or os.path.join(dest_path, rel)
            # Determine target delete by scanning dest_path for context match
            target = self._find_dest_match_for_context(dest_path, row, fallback_path=copy_to)
            ops.append({
                'backup_relative': rel,
                'backup_full': backup_full,
                'copy_to': copy_to,
                'target_delete': target,
                'context_display': row.get('context_display') or rel
            })
        return {'operations': ops}

    def _find_dest_match_for_context(self, dest_root: str, ctx_row: Dict, fallback_path: str) -> Optional[str]:
        """Find a destination file path that matches the provided context, if any.
        Only returns a path if it exists and differs from fallback_path to avoid deleting the same file."""
        try:
            if not dest_root or not os.path.isdir(dest_root):
                return None
            media_type = (ctx_row.get('context_media_type') or '').lower()
            season = ctx_row.get('context_season')
            episode = ctx_row.get('context_episode')
            absolute_num = ctx_row.get('context_absolute')
            series_title = ctx_row.get('context_series_title') or ctx_row.get('context_title')
            # File type safety: treat media vs ancillary differently
            media_ext = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.webm', '.m4v'}
            ancillary_ext = {'.nfo', '.srt', '.ass', '.sub', '.idx', '.txt'}
            try:
                _, backup_ext = os.path.splitext(ctx_row.get('original_path') or '')
            except Exception:
                backup_ext = ''
            # Build patterns
            candidates = []
            for root, dirs, files in os.walk(dest_root):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    # Skip same path as copy target
                    if os.path.normpath(fpath) == os.path.normpath(fallback_path):
                        continue
                    name = fname
                    n = name.lower()
                    # Enforce extension grouping: media replaces media; ancillary replaces ancillary
                    try:
                        _, ext = os.path.splitext(name)
                    except Exception:
                        ext = ''
                    if backup_ext:
                        if (backup_ext.lower() in media_ext and ext.lower() not in media_ext) or \
                           (backup_ext.lower() in ancillary_ext and ext.lower() not in ancillary_ext):
                            continue
                    if media_type == 'movies':
                        # Match Title (YYYY)
                        title = (ctx_row.get('context_title') or '').lower()
                        year = ctx_row.get('context_release_year') or ''
                        if title and year and (f"{title} ({year})" in n):
                            candidates.append(fpath)
                    else:
                        # Series SxxExx
                        if season and episode:
                            sxe = f"s{int(season):02d}e{int(episode):02d}"
                            if sxe in n:
                                # Optionally also check series title prefix before ' - s'
                                if series_title:
                                    prefix = series_title.lower()
                                    if prefix in n:
                                        candidates.append(fpath)
                                    else:
                                        # Accept match with SxxExx even if title not present
                                        candidates.append(fpath)
                                else:
                                    candidates.append(fpath)
                        # Anime absolute
                        if absolute_num:
                            abs_str = f" {int(absolute_num):03d} "
                            if abs_str in n:
                                candidates.append(fpath)
            # Prefer shortest directory depth match
            if not candidates:
                return None
            candidates.sort(key=lambda p: (p.count(os.sep), len(os.path.basename(p))))
            return candidates[0]
        except Exception:
            return None

    def _detect_context_from_filename(self, relative_path: str, media_type: str, folder_name: str, season_name: Optional[str]) -> Dict[str, Optional[str]]:
        """Parse context based on filename patterns and media_type."""
        try:
            import re
            base = os.path.basename(relative_path)
            name, _ext = os.path.splitext(base)
            context_media_type = (media_type or '').lower()
            context = {
                'context_media_type': context_media_type,
                'context_title': None,
                'context_release_year': None,
                'context_series_title': None,
                'context_season': None,
                'context_episode': None,
                'context_absolute': None,
                'context_key': None,
                'context_display': None,
            }
            # Movies: Title (YYYY)
            if context_media_type == 'movies':
                m = re.search(r'^(.+?)\s*\((\d{4})\)', name)
                if m:
                    title = m.group(1).strip()
                    year = m.group(2)
                else:
                    # Fallback to folder name if parse fails
                    title = folder_name.strip()
                    ym = re.search(r'\((\d{4})\)', name)
                    year = ym.group(1) if ym else None
                context.update({
                    'context_title': title,
                    'context_release_year': year,
                    'context_display': f"{title} ({year})" if year else title,
                })
                key = f"movie|{self._normalize_key(title)}|Y{year or ''}"
                context['context_key'] = key
                return context

            # Series/Anime: {Series} - SxxExx - ... (Anime may have absolute number segment)
            # Extract series title before " - S"
            parts = name.split(' - ')
            series_title = parts[0].strip() if parts else (folder_name or '').strip()
            # SxxExx
            se = re.search(r'[sS](\d{1,2})[eE](\d{1,2})', name)
            season = se.group(1) if se else (None)
            episode = se.group(2) if se else (None)
            # Absolute number (anime): a 3-digit token between separators
            absnum = None
            for token in parts:
                if re.fullmatch(r'\d{3}', token.strip()):
                    absnum = token.strip()
                    break
            context.update({
                'context_series_title': series_title,
                'context_title': series_title,
                'context_season': season,
                'context_episode': episode,
                'context_absolute': absnum
            })
            disp = series_title
            if season and episode:
                disp += f" - S{int(season):02d}E{int(episode):02d}"
            if absnum:
                disp += f" - {int(absnum):03d}"
            context['context_display'] = disp
            key_parts = [context_media_type or 'series', self._normalize_key(series_title)]
            if season and episode:
                key_parts.append(f"S{int(season):02d}E{int(episode):02d}")
            if absnum:
                key_parts.append(f"A{int(absnum):03d}")
            context['context_key'] = '|'.join(key_parts)
            return context
        except Exception:
            return {
                'context_media_type': (media_type or '').lower(),
                'context_title': folder_name,
                'context_release_year': None,
                'context_series_title': folder_name,
                'context_season': None,
                'context_episode': None,
                'context_absolute': None,
                'context_key': None,
                'context_display': folder_name,
            }

    def _normalize_key(self, s: str) -> str:
        if not s:
            return ''
        import re
        x = s.lower()
        x = re.sub(r'[^a-z0-9]+', '_', x).strip('_')
        return x

    def reindex_backups(self) -> Tuple[int, int]:
        """Scan BACKUP_PATH for existing dynamic backup dirs and import missing ones.
        Returns: (num_imported, num_skipped)
        """
        backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
        imported = 0
        skipped = 0
        if not os.path.isdir(backup_base):
            return (0, 0)
        # Pattern: <safe_folder>_<transfer_id>
        for name in os.listdir(backup_base):
            full = os.path.join(backup_base, name)
            if not os.path.isdir(full):
                continue
            # parse pattern: <safe_folder>_<transfer_XXXXXXXX> (preferred) or <safe_folder>_<XXXXXXXX>
            suffix = None
            safe_folder = None
            if '_' in name:
                idx = name.rfind('_')
                safe_folder = name[:idx]
                suffix = name[idx+1:]
            if not suffix:
                skipped += 1
                continue
            if suffix.startswith('transfer_'):
                proper_id = suffix
                fallback_id = suffix
            else:
                # numeric or other suffix: assume it is timestamp, build proper transfer id
                proper_id = f"transfer_{suffix}"
                fallback_id = suffix
            # already imported with proper id?
            existing_proper = self.backup_model.get(proper_id)
            if existing_proper:
                skipped += 1
                continue
            existing_fallback = None
            if fallback_id != proper_id:
                existing_fallback = self.backup_model.get(fallback_id)
            # compute dest_path if possible from a transfer record
            t = self.transfer_model.get(proper_id)
            if t:
                dest_path = t.get('dest_path')
                media_type = t.get('media_type')
                folder_name = t.get('folder_name')
                season_name = t.get('season_name')
                episode_name = t.get('episode_name')
                source_path = t.get('source_path')
            else:
                # Unknown transfer; best-effort import with dest unknown
                dest_path = ''
                media_type = None
                # derive a readable title from safe folder (underscores -> spaces)
                folder_name = (safe_folder or '').replace('_', ' ').strip() or None
                season_name = None
                episode_name = None
                source_path = ''
            # Walk files for stats
            total_size = 0
            files = []
            # Determine created_at from directory mtime (use UTC to match SQLite CURRENT_TIMESTAMP)
            try:
                dir_stat = os.stat(full)
                # Convert to UTC to match SQLite's CURRENT_TIMESTAMP behavior
                created_utc = datetime.utcfromtimestamp(dir_stat.st_mtime)
                created_iso = created_utc.isoformat() + 'Z'  # Add Z to indicate UTC
            except Exception:
                created_iso = None
            for root, dirs, filenames in os.walk(full):
                for fname in filenames:
                    if fname.startswith('.') and os.path.basename(root) == '.rsync-partial':
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        stat = os.stat(fpath)
                        size = stat.st_size
                        mtime = int(stat.st_mtime)
                    except Exception:
                        size = 0
                        mtime = 0
                    total_size += size
                    rel = os.path.relpath(fpath, full)
                    original_path = os.path.join(dest_path, rel) if dest_path else rel
                    # Derive media_type for context detection priority
                    inferred_media_type = media_type or ('movies' if (safe_folder or '').lower() in ['movies', 'movie'] else None)
                    ctx = self._detect_context_from_filename(
                        rel,
                        inferred_media_type or (media_type or ''),
                        folder_name or safe_folder or '',
                        season_name
                    )
                    files.append({
                        'relative_path': rel.replace('\\', '/'),
                        'original_path': original_path.replace('\\', '/'),
                        'file_size': size,
                        'modified_time': mtime,
                        'context_media_type': ctx.get('context_media_type'),
                        'context_title': ctx.get('context_title'),
                        'context_release_year': ctx.get('context_release_year'),
                        'context_series_title': ctx.get('context_series_title'),
                        'context_season': ctx.get('context_season'),
                        'context_episode': ctx.get('context_episode'),
                        'context_absolute': ctx.get('context_absolute'),
                        'context_key': ctx.get('context_key'),
                        'context_display': ctx.get('context_display'),
                    })
            if not files:
                skipped += 1
                continue
            # If a fallback record exists, update it in-place to avoid duplicates
            if existing_fallback is not None:
                backup_id_to_use = fallback_id
            else:
                backup_id_to_use = proper_id

            backup_record = {
                'backup_id': backup_id_to_use,
                'transfer_id': proper_id,
                'media_type': media_type,
                'folder_name': folder_name,
                'season_name': season_name,
                'episode_name': episode_name,
                'source_path': source_path,
                'dest_path': dest_path,
                'backup_dir': full,
                'file_count': len(files),
                'total_size': total_size,
                'status': 'ready',
                'created_at': created_iso
            }
            self.backup_model.create_or_replace_backup(backup_record)
            with self.db.get_connection() as conn:
                conn.execute('DELETE FROM transfer_backup_files WHERE backup_id = ?', (backup_id_to_use,))
                conn.commit()
            self.backup_model.add_backup_files(backup_id_to_use, files)
            imported += 1
        return (imported, skipped)
    
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
    
    def cancel_transfer(self, transfer_id: str) -> bool:
        """Cancel a running transfer"""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False
        
        if transfer['status'] == 'running' and transfer['process_id']:
            try:
                import psutil
                process = psutil.Process(transfer['process_id'])
                process.terminate()
                
                # Update status
                self.transfer_model.update(transfer_id, {
                    'status': 'cancelled',
                    'progress': 'Transfer cancelled by user',
                    'end_time': datetime.now().isoformat()
                })
                return True
            except Exception as e:
                print(f"❌ Error cancelling transfer {transfer_id}: {e}")
                return False
        
        return False
    
    def restart_transfer(self, transfer_id: str) -> bool:
        """Restart a failed or cancelled transfer"""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False
        
        if transfer['status'] in ['failed', 'cancelled', 'completed']:
            # Reset transfer status
            self.transfer_model.update(transfer_id, {
                'status': 'pending',
                'progress': 'Restarting transfer...',
                'process_id': None,
                'start_time': datetime.now().isoformat(),
                'end_time': None
            })
            
            # Start the transfer again
            return self._start_rsync_process(
                transfer_id, 
                transfer['source_path'], 
                transfer['dest_path'], 
                transfer['transfer_type']
            )
        
        return False
    
    def trigger_webhook_sync(self, notification_id: str) -> Tuple[bool, str]:
        """Trigger sync for a webhook notification"""
        try:
            # Get notification details
            notification = self.webhook_model.get(notification_id)
            if not notification:
                return False, "Notification not found"
            
            if notification['status'] == 'syncing':
                return False, "Sync already in progress"
            
            if notification['status'] == 'completed':
                return False, "Already synced"
            
            # Update notification status to syncing
            self.webhook_model.update(notification_id, {
                'status': 'syncing',
                'synced_at': datetime.now().isoformat()
            })
            
            # Generate transfer ID
            transfer_id = f"webhook_{notification_id}_{int(datetime.now().timestamp())}"
            
            # Extract movie details
            folder_name = notification['title']
            if notification.get('year'):
                folder_name = f"{notification['title']} ({notification['year']})"
            
            # Use folder_path as source_path and determine destination
            source_path = notification['folder_path']
            
            # Get movie destination path from config
            dest_base = self.config.get("MOVIE_DEST_PATH")
            if not dest_base:
                self.webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': 'Movie destination path not configured'
                })
                return False, "Movie destination path not configured"
            
            dest_path = f"{dest_base}/{folder_name}"
            
            # Store transfer ID in notification
            self.webhook_model.update(notification_id, {'transfer_id': transfer_id})
            
            # Start the transfer using existing transfer logic
            success = self.start_transfer(
                transfer_id=transfer_id,
                source_path=source_path,
                dest_path=dest_path,
                transfer_type="folder",
                media_type="movies",
                folder_name=folder_name,
                season_name=None,
                episode_name=None
            )
            
            if success:
                print(f"✅ Webhook sync started for {notification['title']} (Transfer ID: {transfer_id})")
                return True, f"Sync started for {notification['title']}"
            else:
                # Update notification status back to pending on failure
                self.webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': 'Failed to start transfer'
                })
                return False, "Failed to start transfer"
                
        except Exception as e:
            print(f"❌ Error triggering webhook sync: {e}")
            import traceback
            traceback.print_exc()
            
            # Update notification status to failed
            self.webhook_model.update(notification_id, {
                'status': 'failed',
                'error_message': str(e)
            })
            return False, f"Sync failed: {str(e)}"
    
    def update_webhook_transfer_status(self, transfer_id: str, status: str):
        """Update webhook notification status based on transfer completion"""
        try:
            # Find the webhook notification by transfer_id
            notifications = self.webhook_model.get_all()
            webhook_notification = None
            
            for notification in notifications:
                if notification.get('transfer_id') == transfer_id:
                    webhook_notification = notification
                    break
            
            if webhook_notification:
                update_data = {}
                if status == 'completed':
                    update_data = {
                        'status': 'completed',
                        'synced_at': datetime.now().isoformat()
                    }
                elif status == 'failed':
                    update_data = {
                        'status': 'failed',
                        'error_message': 'Transfer failed'
                    }
                
                if update_data:
                    self.webhook_model.update(webhook_notification['notification_id'], update_data)
                    print(f"📋 Updated webhook notification status to {status} for {webhook_notification['title']}")
                    
        except Exception as e:
            print(f"❌ Error updating webhook transfer status: {e}")
    
    def parse_webhook_data(self, webhook_json: Dict) -> Dict:
        """Parse webhook JSON data according to specification"""
        try:
            movie = webhook_json.get('movie', {})
            movie_file = webhook_json.get('movieFile', {})
            release = webhook_json.get('release', {})
            
            # Extract title and year
            title = movie.get('title', 'Unknown Movie')
            year = movie.get('year')
            
            # Extract folder path
            folder_path = movie.get('folderPath', '')
            
            # Extract poster URL from images
            poster_url = None
            images = movie.get('images', [])
            for image in images:
                if image.get('coverType') == 'poster':
                    poster_url = image.get('remoteUrl')
                    break
            
            # Extract requested by from tags (format: <number> - <name>)
            requested_by = None
            tags = movie.get('tags', [])
            for tag in tags:
                if isinstance(tag, str) and ' - ' in tag:
                    parts = tag.split(' - ', 1)
                    if len(parts) == 2 and parts[0].strip().isdigit():
                        requested_by = parts[1].strip()
                        break
            
            # Extract file information
            file_path = movie_file.get('path', '')
            quality = movie_file.get('quality', '')
            size = movie_file.get('size', 0)
            
            # Extract languages
            languages = []
            movie_file_languages = movie_file.get('languages', [])
            for lang in movie_file_languages:
                if isinstance(lang, dict) and 'name' in lang:
                    languages.append(lang['name'])
            
            # Extract subtitles from mediaInfo
            subtitles = []
            media_info = movie_file.get('mediaInfo', {})
            if 'subtitles' in media_info:
                subtitles = media_info['subtitles']
            
            # Extract release information
            release_title = release.get('releaseTitle', '')
            release_indexer = release.get('indexer', '')
            release_size = release.get('size', 0)
            
            # Extract TMDB and IMDB IDs
            tmdb_id = movie.get('tmdbId')
            imdb_id = movie.get('imdbId')
            
            # Generate unique notification ID
            notification_id = f"movie_{movie.get('id', int(datetime.now().timestamp()))}_{int(datetime.now().timestamp())}"
            
            parsed_data = {
                'notification_id': notification_id,
                'title': title,
                'year': year,
                'folder_path': folder_path,
                'poster_url': poster_url,
                'requested_by': requested_by,
                'file_path': file_path,
                'quality': quality,
                'size': size,
                'languages': languages,
                'subtitles': subtitles,
                'release_title': release_title,
                'release_indexer': release_indexer,
                'release_size': release_size,
                'tmdb_id': tmdb_id,
                'imdb_id': imdb_id,
                'status': 'pending'
            }
            
            print(f"📋 Parsed webhook data for movie: {title} ({year})")
            return parsed_data
            
        except Exception as e:
            print(f"❌ Error parsing webhook data: {e}")
            import traceback
            traceback.print_exc()
            raise
    
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
                'url': app_url,
                'color': 11164867,  # Purple color
                'fields': [
                    {
                        'name': 'Folder Synced',
                        'value': transfer.get('dest_path', 'Unknown'),
                        'inline': False
                    },
                    {
                        'name': 'Files Info',
                        'value': f"```Transferred files: {stats.get('regular_files_transferred', 'N/A')} Deleted Files: {stats.get('deleted_files', 'N/A')}```",
                        'inline': True
                    },
                    {
                        'name': 'Speed Info',
                        'value': f"```Transferred Data: {stats.get('total_transferred_size', 'N/A')} Avg Speed: {stats.get('avg_speed', 'N/A')}```",
                        'inline': True
                    }
                ],
                'author': {
                    'name': sync_type,
                    'icon_url': icon_url
                },
                'timestamp': datetime.now().isoformat(),
                'thumbnail': {
                    'url': thumbnail_url
                } if thumbnail_url else None
            }
            
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