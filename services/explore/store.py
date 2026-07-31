#!/usr/bin/env python3
"""
Persistence for Explore: cached comparisons, approved plans, per-file outcomes.

The plan store is the security boundary for destructive operations. A plan is
written here when it is evaluated and can only be executed once, before it
expires, by presenting its id. The client never gets to describe the work — it
gets to approve work the server already decided on.
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# How long an approved plan stays executable. Long enough to read the report,
# short enough that the library cannot have changed much underneath it.
PLAN_TTL_MINUTES = 15


def _as_int(value) -> Optional[int]:
    """`context_season` is stored zero-padded and as text: '03', not 3."""
    if value is None or value == '':
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _episode_code(season: Optional[int], episode: Optional[int]) -> Optional[str]:
    if season is None or episode is None:
        return None
    return f"S{season:02d}E{episode:02d}"


class ExploreStore:
    def __init__(self, db_manager):
        self.db = db_manager

    # ---- snapshots --------------------------------------------------------

    def save_snapshot(self, media_type: str, scope: str, payload: Dict,
                      remote_ok: bool, local_ok: bool, error: Optional[str]) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                '''INSERT INTO explore_snapshot
                       (media_type, scope, payload, remote_ok, local_ok, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(media_type, scope) DO UPDATE SET
                       payload = excluded.payload,
                       remote_ok = excluded.remote_ok,
                       local_ok = excluded.local_ok,
                       error = excluded.error,
                       created_at = excluded.created_at''',
                (media_type, scope, json.dumps(payload), int(remote_ok), int(local_ok),
                 error, datetime.now().isoformat()),
            )
            conn.commit()

    def get_snapshot(self, media_type: str, scope: str) -> Optional[Dict]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM explore_snapshot WHERE media_type = ? AND scope = ?',
                (media_type, scope),
            ).fetchone()
        if not row:
            return None
        return {
            'payload': json.loads(row['payload']),
            'remote_ok': bool(row['remote_ok']),
            'local_ok': bool(row['local_ok']),
            'error': row['error'],
            'checked_at': row['created_at'],
        }

    # ---- plans ------------------------------------------------------------

    def save_plan(self, plan, execution: Dict, created_by: Optional[str]) -> str:
        plan_id = f"plan_{uuid.uuid4().hex[:16]}"
        expires = datetime.now() + timedelta(minutes=PLAN_TTL_MINUTES)
        payload = {'plan': plan.to_dict(), 'exec': execution}
        # Expired plans are already unusable — take_plan and peek_plan both
        # refuse them — but nothing was clearing the rows out, so the table grew
        # for the life of the install. Doing it here keeps it to a single write
        # path rather than a schedule to forget about.
        self.purge_expired_plans()
        with self.db.get_connection() as conn:
            conn.execute(
                '''INSERT INTO explore_plan
                       (plan_id, media_type, operation, series, season_label,
                        payload, safe, consumed, created_by, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)''',
                (plan_id, plan.media_type, plan.operation, plan.series,
                 plan.season_label, json.dumps(payload), int(plan.safe),
                 created_by, expires.isoformat()),
            )
            conn.commit()
        return plan_id

    def peek_plan(self, plan_id: str) -> Optional[Dict]:
        """
        Read a plan without spending it.

        Only for the dry run, which changes nothing and must leave the plan
        executable — rehearsing an operation cannot be what stops you running
        it. Everything that touches the disk goes through `take_plan`.
        """
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM explore_plan WHERE plan_id = ? AND consumed = 0',
                (plan_id,),
            ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row['expires_at']) < datetime.now():
            return None
        return self._plan_record(row)

    def take_plan(self, plan_id: str) -> Optional[Dict]:
        """
        Claim a plan for execution, or return None if it is already spent.

        The claim IS the UPDATE: reading the row first and then updating it lets
        two callers both see `consumed = 0` and both go on to run the same
        destructive plan. Putting both conditions in the statement's WHERE
        clause means the database decides, and exactly one caller sees a row
        change.

        `expires_at` is written by save_plan with `datetime.isoformat()`, so
        every row shares one format and comparing as text is chronological.
        """
        now = datetime.now().isoformat()
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                '''UPDATE explore_plan SET consumed = 1
                   WHERE plan_id = ? AND consumed = 0 AND expires_at > ?''',
                (plan_id, now),
            )
            if not cursor.rowcount:
                # Unknown, already claimed, or expired — all the same answer.
                conn.commit()
                return None
            row = conn.execute(
                'SELECT * FROM explore_plan WHERE plan_id = ?', (plan_id,)
            ).fetchone()
            conn.commit()

        return self._plan_record(row) if row else None

    @staticmethod
    def _plan_record(row) -> Dict:
        payload = json.loads(row['payload'])
        return {
            'plan_id': row['plan_id'],
            'media_type': row['media_type'],
            'operation': row['operation'],
            'series': row['series'],
            'season_label': row['season_label'],
            'safe': bool(row['safe']),
            'plan': payload['plan'],
            'exec': payload['exec'],
        }

    def purge_expired_plans(self) -> int:
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                'DELETE FROM explore_plan WHERE expires_at < ?',
                (datetime.now().isoformat(),),
            )
            conn.commit()
            return cursor.rowcount or 0

    # ---- per-file outcomes ------------------------------------------------

    def record_files(self, transfer_id: str, records: List[Dict]) -> None:
        if not records:
            return
        with self.db.get_connection() as conn:
            conn.executemany(
                '''INSERT INTO transfer_file
                       (transfer_id, action, rel_path, size, code, season_label, backup_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                [
                    (transfer_id, r.get('action', ''), r.get('rel_path', ''),
                     int(r.get('size') or 0), r.get('code'), r.get('season_label'),
                     r.get('backup_path'))
                    for r in records
                ],
            )
            conn.commit()

    def files_for(self, transfer_id: str) -> List[Dict]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM transfer_file WHERE transfer_id = ? ORDER BY id',
                (transfer_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def backups(self, media_type: str, folder_name: str,
                season_number: Optional[int] = None,
                season_name: Optional[str] = None,
                limit: int = 25) -> List[Dict]:
        """
        Backed-up copies belonging to one series, newest first.

        Matched on the backup's `folder_name`, which is the series folder the
        transfer ran against — NOT on `context_series_title`. That column is
        parsed from the filename by splitting at the first " - ", so a series
        called "Re - ZERO, Starting Life in Another World" is stored as "Re" and
        would never match itself.

        Narrowing to a season uses each file's own `context_season`, because one
        series-level sync produces a single backup holding files from several
        seasons — filtering by the backup's `season_name` alone would show all
        of them or none. Files with no parsed season fall back to the backup's
        `season_name`, which is the folder the run was scoped to.
        """
        query = (
            'SELECT backup_id, transfer_id, media_type, folder_name, season_name, '
            'backup_path, dest_path, file_count, total_size, status, created_at, '
            'restored_at FROM backup '
            "WHERE media_type = ? AND folder_name = ? AND status != 'deleted' "
            'ORDER BY created_at DESC LIMIT ?'
        )

        with self.db.get_connection() as conn:
            rows = conn.execute(query, (media_type, folder_name, limit)).fetchall()
            runs = []
            for row in rows:
                run = dict(row)
                files = conn.execute(
                    'SELECT relative_path, original_path, file_size, modified_time, '
                    'context_season, context_episode, context_absolute, context_display '
                    'FROM backup_file WHERE backup_id = ? ORDER BY relative_path',
                    (row['backup_id'],),
                ).fetchall()

                kept = []
                for entry in files:
                    file = dict(entry)
                    file['season'] = _as_int(file.get('context_season'))
                    file['episode'] = _as_int(file.get('context_episode'))
                    file['code'] = _episode_code(file['season'], file['episode'])
                    if season_number is not None:
                        if file['season'] is not None:
                            if file['season'] != season_number:
                                continue
                        elif (run.get('season_name') or None) != season_name:
                            continue
                    kept.append(file)

                if not kept:
                    continue
                run['files'] = kept
                # The counts describe what is being shown, not the whole run.
                run['shown_count'] = len(kept)
                run['shown_size'] = sum(int(f.get('file_size') or 0) for f in kept)
                runs.append(run)
        return runs

    def history(self, media_type: str, folder_name: str,
                season_name: Optional[str] = None, limit: int = 25) -> List[Dict]:
        """Past runs for a series or one of its seasons, newest first."""
        query = (
            'SELECT transfer_id, media_type, folder_name, season_name, operation_type, '
            'status, progress, start_time, end_time, total_bytes, bytes_transferred, '
            'explore_mode FROM transfers WHERE media_type = ? AND folder_name = ?'
        )
        params: List = [media_type, folder_name]
        if season_name:
            query += ' AND season_name = ?'
            params.append(season_name)
        query += ' ORDER BY COALESCE(end_time, start_time, created_at) DESC LIMIT ?'
        params.append(limit)

        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            runs = []
            for row in rows:
                run = dict(row)
                files = conn.execute(
                    'SELECT action, rel_path, size, code, season_label '
                    'FROM transfer_file WHERE transfer_id = ? ORDER BY id',
                    (row['transfer_id'],),
                ).fetchall()
                run['files'] = [dict(f) for f in files]
                runs.append(run)
        return runs
