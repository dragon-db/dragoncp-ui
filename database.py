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
            
            # Create index for better performance
            conn.execute('CREATE INDEX IF NOT EXISTS idx_transfer_id ON transfers(transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON transfers(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON transfers(created_at)')
            # Helpful for duplicate cleanup queries
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dest_status ON transfers(dest_path, status)')
            
            conn.commit()
        
        print(f"✅ Database initialized: {self.db_path}")
    
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

class TransferManager:
    """Enhanced transfer manager with database persistence"""
    
    def __init__(self, config, db_manager: DatabaseManager, socketio=None):
        print(f"🔄 Initializing TransferManager")
        self.config = config
        self.db = db_manager
        self.transfer_model = Transfer(db_manager)
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
            
            # Build rsync command with SSH connection (same as original)
            rsync_cmd = [
                "rsync", "-av",
                "--progress",
                "--delete",
                "--backup",
                "--backup-dir", self.config.get("BACKUP_PATH", "/tmp/backup"),
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
                "--partial-dir", f"{self.config.get('BACKUP_PATH', '/tmp/backup')}/.rsync-partial",
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