#!/usr/bin/env python3
"""
DragonCP Backup Model (v2)
Database model for backup management and file tracking

Schema v2 Changes:
- Table renames: transfer_backups → backup, transfer_backup_files → backup_file
- Removed: episode_name column
- Renamed: backup_dir → backup_path
- Added: updated_at column
"""

from datetime import datetime
from typing import List, Dict, Optional


class Backup:
    """Backup model to track per-transfer rsync backups and files"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def create_or_replace_backup(self, record: Dict) -> str:
        """Create a backup record. If backup_id exists, replace core fields."""
        backup_id = record['backup_id']
        with self.db.get_connection() as conn:
            # Upsert-like behavior
            existing = conn.execute('SELECT id FROM backup WHERE backup_id = ?', (backup_id,)).fetchone()
            if existing:
                conn.execute('''
                    UPDATE backup SET
                        transfer_id = ?, media_type = ?, folder_name = ?, season_name = ?,
                        source_path = ?, dest_path = ?, backup_path = ?, file_count = ?, total_size = ?,
                        status = ?, restored_at = NULL, created_at = COALESCE(?, created_at),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE backup_id = ?
                ''', (
                    record['transfer_id'], record.get('media_type'), record.get('folder_name'), record.get('season_name'),
                    record['source_path'], record['dest_path'], record['backup_path'], record.get('file_count', 0), record.get('total_size', 0),
                    record.get('status', 'ready'), record.get('created_at'), backup_id
                ))
            else:
                if record.get('created_at'):
                    conn.execute('''
                        INSERT INTO backup (
                            backup_id, transfer_id, media_type, folder_name, season_name,
                            source_path, dest_path, backup_path, file_count, total_size, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        backup_id, record['transfer_id'], record.get('media_type'), record.get('folder_name'), record.get('season_name'),
                        record['source_path'], record['dest_path'], record['backup_path'], record.get('file_count', 0), record.get('total_size', 0), record.get('status', 'ready'), record['created_at']
                    ))
                else:
                    conn.execute('''
                        INSERT INTO backup (
                            backup_id, transfer_id, media_type, folder_name, season_name,
                            source_path, dest_path, backup_path, file_count, total_size, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        backup_id, record['transfer_id'], record.get('media_type'), record.get('folder_name'), record.get('season_name'),
                        record['source_path'], record['dest_path'], record['backup_path'], record.get('file_count', 0), record.get('total_size', 0), record.get('status', 'ready')
                    ))
            conn.commit()
        return backup_id
    
    def add_backup_files(self, backup_id: str, files: List[Dict]):
        """Add files to backup record"""
        if not files:
            return 0
        with self.db.get_connection() as conn:
            conn.executemany('''
                INSERT INTO backup_file (
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
        """Get all backups with optional filtering"""
        query = 'SELECT * FROM backup'
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
        """Get backup by ID"""
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT * FROM backup WHERE backup_id = ?', (backup_id,)).fetchone()
            return dict(row) if row else None
    
    def get_files(self, backup_id: str, limit: int = None) -> List[Dict]:
        """Get files for a backup"""
        query = 'SELECT relative_path, original_path, file_size, modified_time, context_media_type, context_title, context_release_year, context_series_title, context_season, context_episode, context_absolute, context_key, context_display FROM backup_file WHERE backup_id = ? ORDER BY relative_path'
        params = [backup_id]
        if limit:
            query += ' LIMIT ?'
            params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    
    def update(self, backup_id: str, updates: Dict) -> bool:
        """Update backup record"""
        if not updates:
            return False
        # Add updated_at timestamp
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [backup_id]
        with self.db.get_connection() as conn:
            cur = conn.execute(f'UPDATE backup SET {set_clause} WHERE backup_id = ?', values)
            conn.commit()
            return cur.rowcount > 0
    
    def delete(self, backup_id: str) -> int:
        """Delete backup record and associated files"""
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM backup_file WHERE backup_id = ?', (backup_id,))
            cur = conn.execute('DELETE FROM backup WHERE backup_id = ?', (backup_id,))
            conn.commit()
            return cur.rowcount
