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


# Backstop for a pathological log (a sync spanning tens of thousands of files).
# Progress lines are collapsed before they get here, so reaching this cap means
# the transfer genuinely produced that many distinct lines.
LOG_MAX_LINES = 5000

# SQLite allows 999 bound variables per statement by default; a batch well under
# that keeps a large bulk delete to a handful of statements.
DELETE_BATCH = 400


def escape_like(term: str) -> str:
    """
    Neutralise LIKE wildcards in a user's search text.

    Without this a search for `%` matches every row, and `_` matches any single
    character. That is merely confusing in a listing, but these filters also
    drive bulk delete, where "select all matching" on an unescaped `%` means
    every record.
    """
    return term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


class Transfer:
    """Transfer model for database operations"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self._list_columns = None
    
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
                        source_path, dest_path, operation_type, status, progress,
                        queue_reason, rsync_process_id, parsed_title, parsed_season, start_time,
                        is_simulation, simulation_bwlimit,
                        explore_files_from, explore_mode, explore_plan_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    transfer_data['transfer_id'],
                    transfer_data['media_type'],
                    transfer_data['folder_name'],
                    transfer_data.get('season_name'),
                    transfer_data['source_path'],
                    transfer_data['dest_path'],
                    transfer_data['operation_type'],
                    transfer_data.get('status', 'pending'),
                    transfer_data.get('progress', ''),
                    transfer_data.get('queue_reason'),
                    transfer_data.get('rsync_process_id'),
                    parsed_data['title'],
                    parsed_data['season'],
                    transfer_data.get('start_time', datetime.now().isoformat()),
                    1 if transfer_data.get('is_simulation') else 0,
                    transfer_data.get('simulation_bwlimit'),
                    # Explore runs carry the approved file list so a queued or
                    # restarted run rebuilds the same command.
                    transfer_data.get('explore_files_from'),
                    transfer_data.get('explore_mode'),
                    transfer_data.get('explore_plan_id')
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
    
    def _columns_except_logs(self, conn) -> List[str]:
        """Column names for a listing query, cached per process."""
        if self._list_columns is None:
            self._list_columns = [
                row[1] for row in conn.execute("PRAGMA table_info(transfers)").fetchall()
                if row[1] != 'logs'
            ]
        return self._list_columns

    def _filter_sql(self, status_filter=None, statuses=None, search=None):
        """Shared WHERE clause for listing and counting, so they cannot drift."""
        conditions, params = [], []
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        if statuses:
            conditions.append(f"status IN ({', '.join('?' for _ in statuses)})")
            params.extend(statuses)
        if search:
            # Matches what a person would remember about a transfer: what it was
            # called, which season, or where it went.
            term = f"%{escape_like(search.strip())}%"
            conditions.append(
                "(parsed_title LIKE ? ESCAPE '\\' OR folder_name LIKE ? ESCAPE '\\'"
                " OR season_name LIKE ? ESCAPE '\\' OR dest_path LIKE ? ESCAPE '\\'"
                " OR source_path LIKE ? ESCAPE '\\' OR transfer_id LIKE ? ESCAPE '\\')"
            )
            params.extend([term] * 6)
        return (" WHERE " + " AND ".join(conditions)) if conditions else "", params

    def count(self, status_filter: str = None, statuses: List[str] = None,
              search: str = None) -> int:
        """
        How many transfers match, ignoring limit and offset.

        Pagination needs the real total, not the size of the page it just
        fetched - the previous listing reported the latter, so the UI could not
        tell a full page from the end of the results.
        """
        where, params = self._filter_sql(status_filter, statuses, search)
        with self.db.get_connection() as conn:
            return conn.execute(f"SELECT COUNT(*) AS n FROM transfers{where}", params).fetchone()['n']

    def status_counts(self, search: str = None, statuses: List[str] = None) -> Dict[str, int]:
        """
        How many transfers sit in each status, so the filter controls can show
        their own counts without fetching a page per filter.

        `statuses` narrows the set being counted - History counts only finished
        runs, because that is all it lists.
        """
        where, params = self._filter_sql(statuses=statuses, search=search)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT status, COUNT(*) AS n FROM transfers{where} GROUP BY status", params
            ).fetchall()
        return {row['status']: row['n'] for row in rows}

    def delete_many(self, transfer_ids: List[str]) -> tuple:
        """
        Delete several transfers, refusing any that are still running.

        Returns (deleted_count, skipped_ids). A running transfer has a live
        rsync process behind it; deleting the row would leave that process with
        nowhere to report, so it is left alone and named in the result.
        """
        if not transfer_ids:
            return 0, []

        deleted, skipped = 0, []
        with self.db.get_connection() as conn:
            for start in range(0, len(transfer_ids), DELETE_BATCH):
                batch = transfer_ids[start:start + DELETE_BATCH]
                placeholders = ', '.join('?' for _ in batch)

                # The exclusion is part of the DELETE, not just the SELECT
                # before it: a transfer can be restarted between the two, and a
                # row deleted out from under a live rsync process leaves that
                # process with nowhere to report.
                deleted += conn.execute(
                    f"DELETE FROM transfers"
                    f" WHERE transfer_id IN ({placeholders}) AND status != 'running'", batch
                ).rowcount

                # Read back what survived, so the caller is told what actually
                # stayed rather than what looked running a moment ago.
                skipped.extend(
                    row['transfer_id'] for row in conn.execute(
                        f"SELECT transfer_id FROM transfers"
                        f" WHERE transfer_id IN ({placeholders})", batch
                    ).fetchall()
                )
            conn.commit()
        return deleted, skipped

    def delete_matching(self, status_filter: str = None, statuses: List[str] = None,
                        search: str = None) -> tuple:
        """
        Delete every transfer matching a filter, sparing any still running.

        This is what "select all" performs. The filter is re-evaluated here, in
        one statement, rather than the caller listing every id it wants gone -
        which would mean reading the whole matching set back just to name it,
        and would miss anything that arrived in between.
        """
        where, params = self._filter_sql(status_filter, statuses, search)
        joiner = " AND" if where else " WHERE"

        with self.db.get_connection() as conn:
            running = [
                row['transfer_id'] for row in conn.execute(
                    f"SELECT transfer_id FROM transfers{where}{joiner} status = 'running'",
                    params,
                ).fetchall()
            ]
            deleted = conn.execute(
                f"DELETE FROM transfers{where}{joiner} status != 'running'", params
            ).rowcount
            conn.commit()

        return deleted, running

    def get_all(self, status_filter: str = None, limit: int = None,
                statuses: List[str] = None, include_logs: bool = True,
                search: str = None, offset: int = None) -> List[Dict]:
        """
        Get all transfers with optional filtering.

        include_logs=False leaves the logs column out of the query entirely and
        returns a log_count instead. A transfer's log is by far the largest
        thing on the row, and no listing shows it - only how many lines there
        are - so selecting it meant reading and JSON-parsing megabytes per
        request to render counts.

        statuses filters in SQL rather than in the caller, so a listing of the
        few active transfers no longer walks the whole table to find them.
        """
        if include_logs:
            select = "*"
        else:
            with self.db.get_connection() as conn:
                columns = self._columns_except_logs(conn)
            # json_valid guards rows written before the column held JSON
            select = ", ".join(columns) + (
                ", CASE WHEN json_valid(logs) THEN json_array_length(logs) ELSE 0 END AS log_count"
            )

        where, params = self._filter_sql(status_filter, statuses, search)
        query = f"SELECT {select} FROM transfers{where} ORDER BY created_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)
            # OFFSET is only meaningful with a LIMIT in SQLite
            if offset:
                query += " OFFSET ?"
                params.append(offset)

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, params)
            transfers = []

            for row in cursor.fetchall():
                transfer = dict(row)
                if include_logs:
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

    #: The statuses that mean a transfer still has work ahead of it. `queued`
    #: and `paused` count: neither is writing this instant, but both can start
    #: at any moment, which is what matters to anything asking "is it safe to
    #: touch the files".
    ACTIVE_STATUSES = ('running', 'pending', 'queued', 'paused')

    def get_active(self) -> List[Dict]:
        """
        Transfers that are running, pending, queued or paused.

        This used to return `get_all(status_filter=None)` — every transfer ever
        recorded — behind a docstring promising active ones, with a comment
        saying the filtering would happen in memory. It never did. Any caller
        trusting the name got the whole table, so a database with ten completed
        transfers looked like ten running ones.
        """
        return self.get_all(statuses=list(self.ACTIVE_STATUSES), include_logs=False)
    
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
    
    def add_log(self, transfer_id: str, log_line: str, extra_updates: Dict = None,
                replace_last: bool = False, max_lines: int = LOG_MAX_LINES) -> bool:
        """
        Add a log line to transfer

        extra_updates lets callers fold parsed progress stats (percent, speed,
        ETA, byte counts) into the same UPDATE, so streaming rsync output does
        not cost an extra write per line.

        replace_last overwrites the final line instead of appending. rsync
        emits a progress line several times a second, each one superseding the
        last; appending them all would store tens of thousands of lines that
        say nothing the newest one does not. Callers that recognise a
        superseding line pass replace_last so only the latest is kept.

        max_lines caps the stored log, dropping the oldest lines. The end of an
        rsync log is the part worth keeping - it holds the --stats summary and
        any errors - so the tail is what survives.
        """
        transfer = self.get(transfer_id)
        if not transfer:
            return False

        logs = transfer.get('logs', [])

        if replace_last and logs:
            logs[-1] = log_line
        else:
            logs.append(log_line)

        if max_lines and len(logs) > max_lines:
            del logs[:len(logs) - max_lines]

        updates = {
            'logs': logs,
            'progress': log_line
        }
        if extra_updates:
            updates.update(extra_updates)

        return self.update(transfer_id, updates)
    
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
