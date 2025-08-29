#!/usr/bin/env python3
"""
DragonCP Database Models - SQLite-based transfer management
Provides persistent storage for transfers, progress tracking, and metadata
"""

import sqlite3
import os
import json
import re
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
                    category TEXT DEFAULT 'rsync_backup',
                    related_to TEXT,
                    notes TEXT,
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
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backups_transfer_id ON transfer_backups(transfer_id)')

            # Restores table for tracking restore operations (with undo snapshots)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS restores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    restore_id TEXT UNIQUE NOT NULL,
                    transfer_id TEXT NOT NULL,
                    source_backup_id TEXT NOT NULL,
                    undo_backup_id TEXT,
                    target_path TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    dry_run INTEGER DEFAULT 0,
                    logs TEXT DEFAULT '[]',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME,
                    ended_at DATETIME
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_restores_transfer_id ON restores(transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_restores_status ON restores(status)')
            
            conn.commit()
        
        print(f"✅ Database initialized: {self.db_path}")
        self._migrate_schema()

    def _migrate_schema(self):
        """Perform lightweight schema migrations (idempotent)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row

                # Ensure new columns exist on transfer_backups
                cols = {r[1] for r in conn.execute('PRAGMA table_info(transfer_backups)').fetchall()}
                to_add = []
                if 'category' not in cols:
                    to_add.append("ALTER TABLE transfer_backups ADD COLUMN category TEXT DEFAULT 'rsync_backup'")
                if 'related_to' not in cols:
                    to_add.append("ALTER TABLE transfer_backups ADD COLUMN related_to TEXT")
                if 'notes' not in cols:
                    to_add.append("ALTER TABLE transfer_backups ADD COLUMN notes TEXT")
                for stmt in to_add:
                    try:
                        conn.execute(stmt)
                    except Exception:
                        pass

                # Ensure default values for newly added columns
                try:
                    conn.execute("UPDATE transfer_backups SET category = COALESCE(category, 'rsync_backup')")
                except Exception:
                    pass

                # Create index on category only after the column exists
                try:
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_backups_category ON transfer_backups(category)')
                except Exception:
                    pass

                # Ensure restores table exists (already created in init, but guard here too)
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS restores (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        restore_id TEXT UNIQUE NOT NULL,
                        transfer_id TEXT NOT NULL,
                        source_backup_id TEXT NOT NULL,
                        undo_backup_id TEXT,
                        target_path TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        dry_run INTEGER DEFAULT 0,
                        logs TEXT DEFAULT '[]',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        started_at DATETIME,
                        ended_at DATETIME
                    )
                ''')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_restores_transfer_id ON restores(transfer_id)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_restores_status ON restores(status)')

                conn.commit()
        except Exception as e:
            print(f"⚠️  Schema migration warning: {e}")
    
    def get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
                        status = ?, category = COALESCE(?, category), related_to = COALESCE(?, related_to),
                        notes = COALESCE(?, notes), restored_at = NULL
                    WHERE backup_id = ?
                ''', (
                    record['transfer_id'], record.get('media_type'), record.get('folder_name'), record.get('season_name'), record.get('episode_name'),
                    record['source_path'], record['dest_path'], record['backup_dir'], record.get('file_count', 0), record.get('total_size', 0),
                    record.get('status', 'ready'), record.get('category'), record.get('related_to'), record.get('notes'), backup_id
                ))
            else:
                conn.execute('''
                    INSERT INTO transfer_backups (
                        backup_id, transfer_id, media_type, folder_name, season_name, episode_name,
                        source_path, dest_path, backup_dir, file_count, total_size, status,
                        category, related_to, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    backup_id, record['transfer_id'], record.get('media_type'), record.get('folder_name'), record.get('season_name'), record.get('episode_name'),
                    record['source_path'], record['dest_path'], record['backup_dir'], record.get('file_count', 0), record.get('total_size', 0), record.get('status', 'ready'),
                    record.get('category', 'rsync_backup'), record.get('related_to'), record.get('notes')
                ))
            conn.commit()
        return backup_id
    
    def add_backup_files(self, backup_id: str, files: List[Dict]):
        if not files:
            return 0
        with self.db.get_connection() as conn:
            conn.executemany('''
                INSERT INTO transfer_backup_files (
                    backup_id, relative_path, original_path, file_size, modified_time
                ) VALUES (?, ?, ?, ?, ?)
            ''', [
                (backup_id, f['relative_path'], f['original_path'], f.get('file_size', 0), f.get('modified_time', 0))
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
        query = 'SELECT relative_path, original_path, file_size, modified_time FROM transfer_backup_files WHERE backup_id = ? ORDER BY relative_path'
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

class TransferManager:
    """Enhanced transfer manager with database persistence"""
    
    def __init__(self, config, db_manager: DatabaseManager, socketio=None):
        print(f"🔄 Initializing TransferManager")
        self.config = config
        self.db = db_manager
        self.transfer_model = Transfer(db_manager)
        self.backup_model = Backup(db_manager)
        self.socketio = socketio
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
        
        # Use enhanced sync flow with pre-analysis and conditional snapshot
        try:
            self._emit_progress(transfer_id, 'Pre-Sync Analysis: Kickoff via start_transfer', operation='analysis', status='running')
            print('Pre-Sync Analysis: Kickoff via start_transfer')
        except Exception:
            pass
        return self.run_sync(transfer_id, strategy='auto', dry_run=False)
    
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
            
            # Prepare partial-dir (safe under .partials)
            transfer = self.transfer_model.get(transfer_id)
            safe_folder = self._safe_name(transfer.get('folder_name') or 'transfer') if transfer else 'transfer'
            backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
            # Partial dir lives under .partials so we can safely create and prune it without cluttering
            partial_parent = os.path.join(backup_base, '.partials', f"{safe_folder}_{transfer_id}")
            partial_dir = os.path.join(partial_parent, '.rsync-partial')
            try:
                os.makedirs(partial_dir, exist_ok=True)
            except Exception as e:
                print(f"⚠️  Could not prepare partial directory: {e}")
            
            # Build rsync command with SSH connection
            rsync_cmd = [
                "rsync", "-av",
                "--progress",
                "--delete",
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
                "--partial-dir", partial_dir,
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
            
            # Finalize backup record if any files were backed up
            try:
                self._finalize_backup_for_transfer(transfer_id)
            except Exception as be:
                print(f"⚠️  Backup finalization error for {transfer_id}: {be}")
            # Cleanup empty partial directories to avoid leaving empty BACKUP_PATH folders
            try:
                self._cleanup_empty_partial_dir(transfer_id)
            except Exception as ce:
                print(f"⚠️  Partial dir cleanup error for {transfer_id}: {ce}")
            
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
                files.append({
                    'relative_path': rel_path.replace('\\', '/'),
                    'original_path': original_path.replace('\\', '/'),
                    'file_size': size,
                    'modified_time': mtime,
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
            'status': 'ready'
        }
        self.backup_model.create_or_replace_backup(backup_record)
        # Replace existing file list if any
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM transfer_backup_files WHERE backup_id = ?', (transfer_id,))
            conn.commit()
        self.backup_model.add_backup_files(transfer_id, files)

    def _cleanup_empty_partial_dir(self, transfer_id: str):
        """Remove per-transfer partial dir if empty after successful sync."""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return
        backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
        safe_folder = self._safe_name(transfer.get('folder_name') or 'transfer')
        dynamic_parent = os.path.join(backup_base, '.partials', f"{safe_folder}_{transfer_id}")
        partial_dir = os.path.join(dynamic_parent, '.rsync-partial')
        try:
            # Remove .rsync-partial if empty
            if os.path.isdir(partial_dir) and not any(os.scandir(partial_dir)):
                os.rmdir(partial_dir)
            # Remove parent if empty
            if os.path.isdir(dynamic_parent) and not any(os.scandir(dynamic_parent)):
                os.rmdir(dynamic_parent)
        except Exception:
            pass

    def analyze_sync(self, transfer_id: str) -> Dict:
        """Run pre-sync analysis via rsync dry-run with --itemize-changes.
        Returns dict with sync_type, needs_snapshot, and file change lists.
        """
        import subprocess
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            raise ValueError('Transfer not found')

        dest_path = transfer['dest_path']
        # Ensure destination exists
        try:
            os.makedirs(dest_path, exist_ok=True)
        except Exception:
            pass

        # If dest missing or empty -> INITIAL_SYNC
        needs_snapshot = False
        try:
            is_empty = not any(os.scandir(dest_path))
        except FileNotFoundError:
            is_empty = True
        if is_empty:
            # Log initial sync decision
            try:
                self._emit_progress(transfer_id, 'Pre-Sync Analysis: Destination is empty → INITIAL_SYNC', operation='analysis', status='running')
                print('Pre-Sync Analysis: Destination is empty → INITIAL_SYNC')
            except Exception:
                pass
            return {
                'sync_type': 'INITIAL_SYNC',
                'needs_snapshot': False,
                'deletions': [],
                'modifications': [],
                'additions': [],
                'raw_output': []
            }

        # Prepare rsync dry-run
        ssh_user = self.config.get("REMOTE_USER")
        ssh_host = self.config.get("REMOTE_IP")
        ssh_key_path = self.config.get("SSH_KEY_PATH", "")
        ssh_options = ["-o", "StrictHostKeyChecking=no", "-o", "Compression=no"]
        if ssh_key_path:
            if not os.path.isabs(ssh_key_path):
                script_dir = os.path.dirname(os.path.abspath(__file__))
                ssh_key_path = os.path.join(script_dir, ssh_key_path)
            if os.path.exists(ssh_key_path):
                ssh_options.extend(["-i", ssh_key_path])

        if not ssh_user or not ssh_host:
            raise RuntimeError('SSH credentials not configured')

        source_path = transfer['source_path']
        if transfer['transfer_type'] == 'file':
            remote = f"{ssh_user}@{ssh_host}:{source_path}"
            local = f"{dest_path}/"
        else:
            remote = f"{ssh_user}@{ssh_host}:{source_path}/"
            local = f"{dest_path}/"

        cmd = [
            'rsync', '-av', '--delete', '--dry-run', '--itemize-changes',
            '-e', f"ssh {' '.join(ssh_options)}",
            remote, local
        ]

        # Announce analysis start and command
        try:
            self._emit_progress(transfer_id, 'Pre-Sync Analysis: Starting rsync dry-run with --itemize-changes', operation='analysis', status='running')
            self._emit_progress(transfer_id, f"Pre-Sync Analysis: Command → {' '.join(cmd)}", operation='analysis', status='running')
            print('Pre-Sync Analysis: Starting rsync dry-run with --itemize-changes')
            print('Pre-Sync Analysis: Command → ' + ' '.join(cmd))
        except Exception:
            pass

        deletions: List[str] = []
        modifications: List[str] = []
        additions: List[str] = []
        raw_lines: List[str] = []

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                s = line.strip()
                raw_lines.append(s)
                # Parse per spec
                if s.startswith('*deleting'):
                    deletions.append(s)
                    needs_snapshot = True
                elif s.startswith('>f++++++++'):
                    additions.append(s)
                elif s.startswith('>f'):
                    modifications.append(s)
                    needs_snapshot = True
                # Stream analysis output to logs/UI
                try:
                    self._emit_progress(transfer_id, f"ANALYSIS: {s}", operation='analysis', status='running')
                except Exception:
                    pass
            proc.wait()
        except Exception as e:
            raw_lines.append(f"ANALYSIS ERROR: {e}")

        sync_type = 'ADDITIVE_SYNC'
        if deletions or modifications:
            sync_type = 'DESTRUCTIVE_SYNC'
            needs_snapshot = True

        # Summary log
        try:
            self._emit_progress(
                transfer_id,
                f"Pre-Sync Analysis: Result → {sync_type} | deletions={len(deletions)} modifications={len(modifications)} additions={len(additions)}",
                operation='analysis',
                status='running'
            )
            print(f"Pre-Sync Analysis: Result → {sync_type} | deletions={len(deletions)} modifications={len(modifications)} additions={len(additions)}")
        except Exception:
            pass

        return {
            'sync_type': sync_type,
            'needs_snapshot': bool(needs_snapshot),
            'deletions': deletions,
            'modifications': modifications,
            'additions': additions,
            'raw_output': raw_lines
        }

    def _build_snapshot_name(self, transfer: Dict, prefix: str = 'snapshot') -> str:
        safe_folder = self._safe_name(transfer.get('folder_name') or 'transfer')
        season = transfer.get('season_name')
        if season:
            safe_season = self._safe_name(str(season))
            safe_folder = f"{safe_folder}_{safe_season}"
        return f"{prefix}_{safe_folder}_{transfer.get('transfer_id')}"

    def create_snapshot(self, transfer_id: str, category: str = 'pre_sync_snapshot', related_to: Optional[str] = None, name_prefix: str = 'snapshot') -> Optional[str]:
        """Create a hard-linked snapshot of destination path into BACKUP_PATH.
        Returns backup_id (snapshot id) or None if not needed/failed.
        """
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return None
        dest_path = transfer.get('dest_path')
        if not dest_path or not os.path.isdir(dest_path):
            return None
        # If destination is empty, skip snapshot
        try:
            if not any(os.scandir(dest_path)):
                return None
        except Exception:
            return None

        backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
        snap_name = self._build_snapshot_name(transfer, prefix=name_prefix)
        snapshot_path = os.path.join(backup_base, snap_name)
        try:
            os.makedirs(snapshot_path, exist_ok=True)
        except Exception as e:
            print(f"❌ Failed to create snapshot dir: {e}")
            return None

        # Log snapshot intent
        try:
            self._emit_progress(transfer_id, f"Conditional Snapshot Creation: Creating snapshot at {snapshot_path}", operation='sync', status='running')
            print(f"Conditional Snapshot Creation: Creating snapshot at {snapshot_path}")
        except Exception:
            pass

        # Try cp -al first
        def _hardlink_copy(src_root: str, dst_root: str):
            for root, dirs, files in os.walk(src_root):
                rel = os.path.relpath(root, src_root)
                target_dir = os.path.join(dst_root, rel) if rel != '.' else dst_root
                os.makedirs(target_dir, exist_ok=True)
                for d in dirs:
                    os.makedirs(os.path.join(target_dir, d), exist_ok=True)
                for f in files:
                    src_f = os.path.join(root, f)
                    dst_f = os.path.join(target_dir, f)
                    try:
                        os.link(src_f, dst_f)
                    except Exception:
                        # Fallback to copy if hard-link fails
                        try:
                            import shutil
                            shutil.copy2(src_f, dst_f)
                        except Exception:
                            pass

        try:
            import subprocess
            # Attempt to use cp -al hardlinking
            self._emit_progress(transfer_id, f"Conditional Snapshot Creation: Running → cp -al {dest_path}/. {snapshot_path}", operation='sync', status='running')
            print(f"Conditional Snapshot Creation: Running → cp -al {dest_path}/. {snapshot_path}")
            result = subprocess.run(['cp', '-al', f"{dest_path}/.", snapshot_path], capture_output=True, text=True)
            if result.returncode != 0:
                try:
                    self._emit_progress(transfer_id, f"Conditional Snapshot Creation: cp -al failed (code {result.returncode}) → falling back to manual hardlink copy", operation='sync', status='running')
                    err = (result.stderr or '').strip()
                    if err:
                        self._emit_progress(transfer_id, f"Conditional Snapshot Creation: cp stderr → {err}", operation='sync', status='running')
                    print(f"Conditional Snapshot Creation: cp -al failed (code {result.returncode}) → falling back to manual hardlink copy")
                except Exception:
                    pass
                _hardlink_copy(dest_path, snapshot_path)
        except Exception:
            try:
                self._emit_progress(transfer_id, "Conditional Snapshot Creation: cp -al not available → using manual hardlink copy", operation='sync', status='running')
                print("Conditional Snapshot Creation: cp -al not available → using manual hardlink copy")
            except Exception:
                pass
            _hardlink_copy(dest_path, snapshot_path)

        # Walk and record files
        total_size = 0
        files: List[Dict] = []
        for root, dirs, filenames in os.walk(snapshot_path):
            for fname in filenames:
                full_path = os.path.join(root, fname)
                try:
                    rel_path = os.path.relpath(full_path, snapshot_path)
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
                original_path = os.path.join(dest_path, rel_path)
                files.append({
                    'relative_path': rel_path.replace('\\', '/'),
                    'original_path': original_path.replace('\\', '/'),
                    'file_size': size,
                    'modified_time': mtime,
                })

        if not files:
            # Remove empty snapshot directory
            try:
                import shutil
                shutil.rmtree(snapshot_path)
            except Exception:
                pass
            return None

        backup_record = {
            'backup_id': snap_name,
            'transfer_id': transfer_id,
            'media_type': transfer.get('media_type'),
            'folder_name': transfer.get('folder_name'),
            'season_name': transfer.get('season_name'),
            'episode_name': transfer.get('episode_name'),
            'source_path': transfer.get('source_path'),
            'dest_path': transfer.get('dest_path'),
            'backup_dir': snapshot_path,
            'file_count': len(files),
            'total_size': total_size,
            'status': 'ready',
            'category': category,
            'related_to': related_to,
            'notes': None,
        }
        self.backup_model.create_or_replace_backup(backup_record)
        # Replace existing file list if any
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM transfer_backup_files WHERE backup_id = ?', (snap_name,))
            conn.commit()
        self.backup_model.add_backup_files(snap_name, files)
        # Log snapshot completion
        try:
            self._emit_progress(transfer_id, f"Conditional Snapshot Creation: Completed → {snap_name} ({len(files)} files, {total_size} bytes)", operation='sync', status='running')
            print(f"Conditional Snapshot Creation: Completed → {snap_name} ({len(files)} files, {total_size} bytes)")
        except Exception:
            pass
        return snap_name

    def _emit_progress(self, transfer_id: str, line: str, operation: str, status: str = 'running', restore_id: Optional[str] = None):
        try:
            self.transfer_model.add_log(transfer_id, line)
            if self.socketio:
                transfer = self.transfer_model.get(transfer_id) or {'logs': []}
                payload = {
                    'transfer_id': transfer_id,
                    'operation': operation,
                    'progress': line,
                    'logs': (transfer.get('logs') or [])[-100:],
                    'log_count': len(transfer.get('logs') or []),
                    'status': status
                }
                if restore_id:
                    payload['restore_id'] = restore_id
                self.socketio.emit('transfer_progress', payload)
        except Exception:
            pass

    def run_sync(self, transfer_id: str, strategy: str = 'auto', dry_run: bool = False) -> bool:
        """Execute rsync according to strategy: INITIAL_SYNC, ADDITIVE_SYNC, or DESTRUCTIVE_SYNC.
        If strategy is auto, perform analyze_sync to decide and create snapshot if destructive.
        """
        import subprocess
        import threading
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            raise ValueError('Transfer not found')

        # Decide strategy
        analysis = None
        if strategy == 'auto':
            try:
                self._emit_progress(transfer_id, f"Pre-Sync Analysis: Requested (strategy=auto)", operation='analysis', status='running')
                print("Pre-Sync Analysis: Requested (strategy=auto)")
            except Exception:
                pass
            analysis = self.analyze_sync(transfer_id)
            strategy = analysis.get('sync_type', 'ADDITIVE_SYNC')
            try:
                self._emit_progress(transfer_id, f"Pre-Sync Analysis: Decided strategy → {strategy}", operation='analysis', status='running')
                print(f"Pre-Sync Analysis: Decided strategy → {strategy}")
            except Exception:
                pass
        else:
            try:
                self._emit_progress(transfer_id, f"Execute Sync Operation: Using explicit strategy → {strategy}{' DRY-RUN' if dry_run else ''}", operation='sync', status='running')
                print(f"Execute Sync Operation: Using explicit strategy → {strategy}{' DRY-RUN' if dry_run else ''}")
            except Exception:
                pass

        # Create snapshot for destructive syncs (unless dry-run)
        if strategy == 'DESTRUCTIVE_SYNC' and not dry_run:
            try:
                snap_id = self.create_snapshot(transfer_id, category='pre_sync_snapshot', related_to=None, name_prefix='snapshot')
                if snap_id:
                    self._emit_progress(transfer_id, f"Prepared snapshot: {snap_id}", operation='sync', status='running')
                    print(f"Prepared snapshot: {snap_id}")
            except Exception as e:
                self._emit_progress(transfer_id, f"Snapshot creation failed: {e}", operation='sync', status='failed')
                print(f"Snapshot creation failed: {e}")
                return False

        # Build rsync command
        ssh_user = self.config.get("REMOTE_USER")
        ssh_host = self.config.get("REMOTE_IP")
        ssh_key_path = self.config.get("SSH_KEY_PATH", "")
        if not ssh_user or not ssh_host:
            raise RuntimeError('SSH credentials not configured')

        source_path = transfer['source_path']
        dest_path = transfer['dest_path']
        try:
            os.makedirs(dest_path, exist_ok=True)
        except Exception:
            pass

        backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
        safe_folder = self._safe_name(transfer.get('folder_name') or 'transfer')
        partial_base = os.path.join(backup_base, '.partials')
        dynamic_parent = os.path.join(partial_base, f"{safe_folder}_{transfer_id}")
        partial_dir = os.path.join(dynamic_parent, '.rsync-partial')
        try:
            os.makedirs(partial_dir, exist_ok=True)
        except Exception:
            pass

        rsync_cmd = [
            'rsync', '-av', '--progress', '--update',
            '--exclude', '.*', '--exclude', '*.tmp', '--exclude', '*.log',
            '--stats', '--human-readable', '--bwlimit=0', '--block-size=65536', '--no-compress',
            '--partial', '--partial-dir', partial_dir,
            '--timeout=300', '--size-only', '--no-perms', '--no-owner', '--no-group', '--no-checksum', '--whole-file', '--preallocate', '--no-motd'
        ]
        if strategy == 'DESTRUCTIVE_SYNC':
            rsync_cmd.insert(2, '--delete')
        if dry_run:
            rsync_cmd.insert(2, '--dry-run')

        ssh_options = ["-o", "StrictHostKeyChecking=no", "-o", "Compression=no"]
        if ssh_key_path:
            if not os.path.isabs(ssh_key_path):
                script_dir = os.path.dirname(os.path.abspath(__file__))
                ssh_key_path = os.path.join(script_dir, ssh_key_path)
            if os.path.exists(ssh_key_path):
                ssh_options.extend(["-i", ssh_key_path])
        rsync_cmd.extend(['-e', f"ssh {' '.join(ssh_options)}"])

        if transfer['transfer_type'] == 'file':
            rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}", f"{dest_path}/"])
        else:
            rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}/", f"{dest_path}/"])

        # Start process and stream
        try:
            self._emit_progress(transfer_id, 'Execute Sync Operation: Starting rsync', operation='sync', status='running')
            print('Execute Sync Operation: Starting rsync')
        except Exception:
            pass
        self.transfer_model.update(transfer_id, {'status': 'running', 'progress': f"Sync started ({strategy}{' DRY-RUN' if dry_run else ''})"})
        self._emit_progress(transfer_id, f"Running: {' '.join(rsync_cmd)}", operation='sync', status='running')
        try:
            print('Running: ' + ' '.join(rsync_cmd))
        except Exception:
            pass
        process = subprocess.Popen(rsync_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1, env=os.environ.copy())

        def _monitor():
            try:
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    self._emit_progress(transfer_id, line.strip(), operation='sync', status='running')
                rc = process.wait()
                if rc == 0:
                    self.transfer_model.update(transfer_id, {'status': 'completed', 'progress': 'Sync completed successfully', 'end_time': datetime.now().isoformat()})
                    try:
                        self._emit_progress(transfer_id, 'Execute Sync Operation: Completed successfully', operation='sync', status='completed')
                        print('Execute Sync Operation: Completed successfully')
                    except Exception:
                        pass
                    if self.socketio:
                        tr = self.transfer_model.get(transfer_id)
                        self.socketio.emit('transfer_complete', {
                            'transfer_id': transfer_id,
                            'operation': 'sync',
                            'status': 'completed',
                            'message': 'Sync completed successfully',
                            'logs': tr['logs'][-100:] if tr else [],
                            'log_count': len(tr['logs']) if tr else 0
                        })
                else:
                    self.transfer_model.update(transfer_id, {'status': 'failed', 'progress': f'Sync failed with exit code {rc}', 'end_time': datetime.now().isoformat()})
                    try:
                        self._emit_progress(transfer_id, f'Execute Sync Operation: Failed with exit code {rc}', operation='sync', status='failed')
                        print(f'Execute Sync Operation: Failed with exit code {rc}')
                    except Exception:
                        pass
                    if self.socketio:
                        tr = self.transfer_model.get(transfer_id)
                        self.socketio.emit('transfer_complete', {
                            'transfer_id': transfer_id,
                            'operation': 'sync',
                            'status': 'failed',
                            'message': f'Sync failed with exit code {rc}',
                            'logs': tr['logs'][-100:] if tr else [],
                            'log_count': len(tr['logs']) if tr else 0
                        })
            finally:
                try:
                    self._cleanup_empty_partial_dir(transfer_id)
                except Exception:
                    pass

        threading.Thread(target=_monitor, daemon=True).start()
        return True

    # ===== Restores tracking helpers =====
    def _restores_add_log(self, restore_id: str, line: str):
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT logs FROM restores WHERE restore_id = ?', (restore_id,)).fetchone()
            logs = []
            if row and row[0]:
                try:
                    logs = json.loads(row[0])
                except Exception:
                    logs = []
            logs.append(line)
            conn.execute('UPDATE restores SET logs = ? WHERE restore_id = ?', (json.dumps(logs), restore_id))
            conn.commit()

    def _restores_update(self, restore_id: str, updates: Dict):
        if not updates:
            return
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [restore_id]
        with self.db.get_connection() as conn:
            conn.execute(f'UPDATE restores SET {set_clause} WHERE restore_id = ?', values)
            conn.commit()

    def _create_restore_record(self, restore_id: str, transfer_id: str, source_backup_id: str, target_path: str, dry_run: bool, undo_backup_id: Optional[str] = None):
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT OR IGNORE INTO restores (
                    restore_id, transfer_id, source_backup_id, undo_backup_id, target_path, status, dry_run, logs, created_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, '[]', ?)
            ''', (restore_id, transfer_id, source_backup_id, undo_backup_id, target_path, 1 if dry_run else 0, datetime.now().isoformat()))
            conn.commit()

    def list_restores(self, transfer_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
        query = 'SELECT * FROM restores'
        params: List = []
        if transfer_id:
            query += ' WHERE transfer_id = ?'
            params.append(transfer_id)
        query += ' ORDER BY created_at DESC'
        if limit:
            query += ' LIMIT ?'
            params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def start_restore(self, restore_id: str, source_backup_id: str, transfer_id: str, dry_run: bool = False) -> Tuple[bool, str]:
        import subprocess
        backup = self.backup_model.get(source_backup_id)
        if not backup:
            return False, 'Snapshot not found'
        # If the referenced transfer does not exist (e.g., ad-hoc restore), create a lightweight
        # transfer record so logs/progress can be attached and shown in the UI.
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            try:
                transfer_data = {
                    'transfer_id': transfer_id,
                    'media_type': backup.get('media_type') or 'restore',
                    'folder_name': backup.get('folder_name') or 'Restore',
                    'season_name': backup.get('season_name'),
                    'episode_name': backup.get('episode_name'),
                    'source_path': backup.get('backup_dir') or '',
                    'dest_path': backup.get('dest_path') or '',
                    'transfer_type': 'folder',
                    'status': 'pending'
                }
                self.transfer_model.create(transfer_data)
                transfer = self.transfer_model.get(transfer_id)
            except Exception as ce:
                return False, f'Failed to create restore session: {ce}'
        src_dir = backup.get('backup_dir')
        dest_path = transfer.get('dest_path')
        if not src_dir or not os.path.isdir(src_dir):
            return False, 'Snapshot directory missing'
        if not dest_path:
            return False, 'Destination path missing'
        try:
            os.makedirs(dest_path, exist_ok=True)
        except Exception:
            pass

        # Create undo snapshot unless dry-run
        undo_id = None
        if not dry_run:
            undo_id = self.create_snapshot(transfer_id, category='pre_restore_snapshot', related_to=source_backup_id, name_prefix='pre_restore')

        self._create_restore_record(restore_id, transfer_id, source_backup_id, dest_path, dry_run, undo_backup_id=undo_id)
        self._restores_update(restore_id, {'status': 'running', 'started_at': datetime.now().isoformat()})
        # Reflect status to transfer for visibility in Active Transfers
        try:
            self.transfer_model.update(transfer_id, {'status': 'running', 'progress': f"Restore started ({'DRY-RUN' if dry_run else 'live'})"})
        except Exception:
            pass

        # Announce restore plan
        try:
            op_mode = 'DRY-RUN' if dry_run else 'LIVE'
            self._emit_progress(transfer_id, f"RESTORE OPERATION LOGIC: Starting restore ({op_mode}) from {source_backup_id} to {dest_path}", operation='restore', status='running', restore_id=restore_id)
            if undo_id:
                self._emit_progress(transfer_id, f"RESTORE OPERATION LOGIC: Undo snapshot prepared → {undo_id}", operation='restore', status='running', restore_id=restore_id)
            elif dry_run:
                self._emit_progress(transfer_id, "RESTORE OPERATION LOGIC: Dry-run → undo snapshot skipped", operation='restore', status='running', restore_id=restore_id)
            print(f"RESTORE OPERATION LOGIC: Starting restore ({op_mode}) from {source_backup_id} to {dest_path}")
        except Exception:
            pass

        rsync_cmd = ['rsync', '-av', '--progress', '--delete']
        if dry_run:
            rsync_cmd.append('--dry-run')
        rsync_cmd.extend(['--size-only', '--no-perms', '--no-owner', '--no-group', '--no-motd', f"{src_dir}/", f"{dest_path}/"]) 

        self._restores_add_log(restore_id, f"Running restore: {' '.join(rsync_cmd)}")
        if self.socketio:
            self.socketio.emit('transfer_progress', {
                'transfer_id': transfer_id,
                'restore_id': restore_id,
                'operation': 'restore',
                'progress': f"Starting restore {restore_id}",
                'status': 'running'
            })
        try:
            self._emit_progress(transfer_id, f"RESTORE OPERATION LOGIC: Command → {' '.join(rsync_cmd)}", operation='restore', status='running', restore_id=restore_id)
            print('RESTORE OPERATION LOGIC: Command → ' + ' '.join(rsync_cmd))
        except Exception:
            pass

        proc = subprocess.Popen(rsync_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        try:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                s = line.strip()
                self._restores_add_log(restore_id, s)
                self._emit_progress(transfer_id, s, operation='restore', status='running', restore_id=restore_id)
            rc = proc.wait()
            if rc == 0:
                self._restores_update(restore_id, {'status': 'completed', 'ended_at': datetime.now().isoformat(), 'undo_backup_id': undo_id})
                try:
                    self.transfer_model.update(transfer_id, {'status': 'completed', 'progress': 'Restore completed', 'end_time': datetime.now().isoformat()})
                except Exception:
                    pass
                try:
                    self._emit_progress(transfer_id, 'RESTORE OPERATION LOGIC: Restore completed successfully', operation='restore', status='completed', restore_id=restore_id)
                    print('RESTORE OPERATION LOGIC: Restore completed successfully')
                except Exception:
                    pass
                if self.socketio:
                    tr = self.transfer_model.get(transfer_id) or {'logs': []}
                    self.socketio.emit('transfer_complete', {
                        'transfer_id': transfer_id,
                        'restore_id': restore_id,
                        'operation': 'restore',
                        'status': 'completed',
                        'message': 'Restore completed successfully',
                        'logs': (tr.get('logs') or [])[-100:],
                        'log_count': len(tr.get('logs') or [])
                    })
                return True, 'Restore completed successfully'
            else:
                self._restores_update(restore_id, {'status': 'failed', 'ended_at': datetime.now().isoformat()})
                try:
                    self.transfer_model.update(transfer_id, {'status': 'failed', 'progress': f'Restore failed (exit {rc})', 'end_time': datetime.now().isoformat()})
                except Exception:
                    pass
                try:
                    self._emit_progress(transfer_id, f'RESTORE OPERATION LOGIC: Restore failed with exit code {rc}', operation='restore', status='failed', restore_id=restore_id)
                    print(f'RESTORE OPERATION LOGIC: Restore failed with exit code {rc}')
                except Exception:
                    pass
                if self.socketio:
                    tr = self.transfer_model.get(transfer_id) or {'logs': []}
                    self.socketio.emit('transfer_complete', {
                        'transfer_id': transfer_id,
                        'restore_id': restore_id,
                        'operation': 'restore',
                        'status': 'failed',
                        'message': f'Restore failed with exit code {rc}',
                        'logs': (tr.get('logs') or [])[-100:],
                        'log_count': len(tr.get('logs') or [])
                    })
                return False, f'Restore failed with exit code {rc}'
        except Exception as e:
            self._restores_update(restore_id, {'status': 'failed', 'ended_at': datetime.now().isoformat()})
            try:
                self.transfer_model.update(transfer_id, {'status': 'failed', 'progress': f'Restore error: {e}', 'end_time': datetime.now().isoformat()})
            except Exception:
                pass
            if self.socketio:
                tr = self.transfer_model.get(transfer_id) or {'logs': []}
                self.socketio.emit('transfer_complete', {
                    'transfer_id': transfer_id,
                    'restore_id': restore_id,
                    'operation': 'restore',
                    'status': 'failed',
                    'message': str(e),
                    'logs': (tr.get('logs') or [])[-100:],
                    'log_count': len(tr.get('logs') or [])
                })
            return False, str(e)

    def undo_restore(self, restore_id: str, dry_run: bool = False) -> Tuple[bool, str]:
        import subprocess
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT transfer_id, undo_backup_id, target_path FROM restores WHERE restore_id = ?', (restore_id,)).fetchone()
        if not row:
            return False, 'Restore not found'
        transfer_id = row['transfer_id'] if isinstance(row, sqlite3.Row) else row[0]
        undo_id = row['undo_backup_id'] if isinstance(row, sqlite3.Row) else row[1]
        dest_path = row['target_path'] if isinstance(row, sqlite3.Row) else row[2]
        if not undo_id:
            return False, 'No undo snapshot recorded'
        backup = self.backup_model.get(undo_id)
        if not backup:
            return False, 'Undo snapshot missing'
        src_dir = backup.get('backup_dir')
        if not src_dir or not os.path.isdir(src_dir):
            return False, 'Undo snapshot directory missing'

        rsync_cmd = ['rsync', '-av', '--progress', '--delete']
        if dry_run:
            rsync_cmd.append('--dry-run')
        rsync_cmd.extend(['--size-only', '--no-perms', '--no-owner', '--no-group', '--no-motd', f"{src_dir}/", f"{dest_path}/"]) 
        self._restores_add_log(restore_id, f"Running undo-restore: {' '.join(rsync_cmd)}")
        if self.socketio:
            self.socketio.emit('transfer_progress', {
                'transfer_id': transfer_id,
                'restore_id': restore_id,
                'operation': 'undo_restore',
                'progress': f"Starting undo for {restore_id}",
                'status': 'running'
            })
        try:
            self._emit_progress(transfer_id, f"RESTORE OPERATION LOGIC: Undo command → {' '.join(rsync_cmd)}", operation='undo_restore', status='running', restore_id=restore_id)
            print('RESTORE OPERATION LOGIC: Undo command → ' + ' '.join(rsync_cmd))
        except Exception:
            pass
        proc = subprocess.Popen(rsync_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            s = line.strip()
            self._restores_add_log(restore_id, s)
            self._emit_progress(transfer_id, s, operation='undo_restore', status='running', restore_id=restore_id)
        rc = proc.wait()
        if rc == 0:
            self._restores_update(restore_id, {'status': 'undo_completed', 'ended_at': datetime.now().isoformat()})
            if self.socketio:
                tr = self.transfer_model.get(transfer_id) or {'logs': []}
                self.socketio.emit('transfer_complete', {
                    'transfer_id': transfer_id,
                    'restore_id': restore_id,
                    'operation': 'undo_restore',
                    'status': 'completed',
                    'message': 'Undo restore completed successfully',
                    'logs': (tr.get('logs') or [])[-100:],
                    'log_count': len(tr.get('logs') or [])
                })
            return True, 'Undo restore completed successfully'
        else:
            self._restores_update(restore_id, {'status': 'failed', 'ended_at': datetime.now().isoformat()})
            if self.socketio:
                tr = self.transfer_model.get(transfer_id) or {'logs': []}
                self.socketio.emit('transfer_complete', {
                    'transfer_id': transfer_id,
                    'restore_id': restore_id,
                    'operation': 'undo_restore',
                    'status': 'failed',
                    'message': f'Undo restore failed with exit code {rc}',
                    'logs': (tr.get('logs') or [])[-100:],
                    'log_count': len(tr.get('logs') or [])
                })
            return False, f'Undo restore failed with exit code {rc}'

    def restore_backup(self, backup_id: str, files: List[str] = None) -> Tuple[bool, str]:
        """Restore files from backup_id to their original destination using rsync.
        If files is provided, it should be a list of relative paths to restore selectively.
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
            rsync_cmd = [
                'rsync', '-av', '--progress', '--size-only', '--no-perms', '--no-owner', '--no-group', '--no-motd'
            ]
            temp_list_file = None
            if files:
                # Write file list to a temp file with Unix newlines
                temp_fd, temp_path = tempfile.mkstemp(prefix='backup_files_', text=True)
                os.close(temp_fd)
                with open(temp_path, 'w', newline='\n') as f:
                    for p in files:
                        f.write(p.strip().lstrip('/').replace('\\', '/') + '\n')
                rsync_cmd.extend(['-r', f"--files-from={temp_path}"])
                temp_list_file = temp_path
            # Source and destination
            rsync_cmd.extend([f"{backup_dir}/", f"{dest_path}/"]) 
            print(f"🔄 Restoring backup {backup_id}: {' '.join(rsync_cmd)}")
            result = subprocess.run(rsync_cmd, capture_output=True, text=True)
            if temp_list_file and os.path.exists(temp_list_file):
                try:
                    os.remove(temp_list_file)
                except Exception:
                    pass
            if result.returncode == 0:
                self.backup_model.update(backup_id, {'status': 'restored', 'restored_at': datetime.now().isoformat()})
                return True, 'Restore completed successfully'
            else:
                return False, f"Restore failed: {result.stderr or result.stdout}"
        except Exception as e:
            return False, str(e)

    def delete_backup(self, backup_id: str, delete_files: bool = True) -> Tuple[bool, str]:
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
            # Mark as deleted but keep high-level record for audit
            with self.db.get_connection() as conn:
                conn.execute('DELETE FROM transfer_backup_files WHERE backup_id = ?', (backup_id,))
                conn.commit()
            self.backup_model.update(backup_id, {'status': 'deleted'})
            return True, 'Backup deleted'
        except Exception as e:
            return False, str(e)

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
                    files.append({
                        'relative_path': rel.replace('\\', '/'),
                        'original_path': original_path.replace('\\', '/'),
                        'file_size': size,
                        'modified_time': mtime,
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
                'status': 'ready'
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
            # Use the enhanced sync flow to keep snapshot/analysis behavior consistent
            return self.run_sync(transfer_id, strategy='auto', dry_run=False)
        
        return False 