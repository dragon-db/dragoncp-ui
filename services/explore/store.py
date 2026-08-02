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


def _capture_display(capture: Dict) -> str:
    """'Example Show — S01E02', or 'Example Film (2024)'."""
    title = capture.get('title') or ''
    if capture.get('library') == 'movies':
        year = capture.get('release_year')
        return f"{title} ({year})" if year else title
    season, episode = capture.get('season_number'), capture.get('episode_number')
    if season is None or episode is None:
        return title
    return f"{title} — S{season:02d}E{episode:02d}"


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
        Stored versions belonging to one series, newest first.

        Read from the backup index by slot, so narrowing to a season is an
        exact match on the season number rather than a filename guess. This
        used to match on a `context_series_title` parsed by splitting the
        filename at the first " - ", which stored "Alpha - Bravo, Charlie of
        the Delta" as "Alpha" and hid that series' own backups from it.

        One row per version, which is also how the Backups page presents them —
        the two screens now describe the same thing the same way.
        """
        library = {'movies': 'movies', 'tvshows': 'shows',
                   'series': 'shows', 'anime': 'anime'}.get(media_type)
        if not library:
            return []

        where = ["c.kind = 'slot'", 'c.library = ?', 'c.title = ?', "c.status != 'files_removed'"]
        params: List = [library, folder_name]
        if season_number is not None:
            where.append('c.season_number = ?')
            params.append(season_number)
        params.append(limit)

        query = f'''
            SELECT c.* FROM backup_capture c
            WHERE {' AND '.join(where)}
            ORDER BY c.captured_at DESC, c.capture_id DESC
            LIMIT ?
        '''

        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            runs = []
            for row in rows:
                capture = dict(row)
                files = conn.execute(
                    'SELECT relative_path, original_path, file_size, modified_time '
                    'FROM backup_capture_file WHERE capture_id = ? '
                    'ORDER BY is_media DESC, relative_path',
                    (capture['capture_id'],),
                ).fetchall()

                season = capture.get('season_number')
                episode = capture.get('episode_number')
                shown = []
                for entry in files:
                    file = dict(entry)
                    file['season'] = season
                    file['episode'] = episode
                    file['code'] = _episode_code(season, episode)
                    file['context_display'] = _capture_display(capture)
                    shown.append(file)

                if not shown:
                    continue

                runs.append({
                    'backup_id': capture['capture_id'],
                    'transfer_id': capture.get('source_transfer_id') or '',
                    'media_type': media_type,
                    'folder_name': capture.get('title') or folder_name,
                    'season_name': (
                        None if season is None
                        else ('Specials' if season == 0 else f"Season {season:02d}")
                    ),
                    'backup_path': capture.get('capture_path') or '',
                    'dest_path': '',
                    'status': 'restored' if capture.get('status') == 'restored' else 'ready',
                    'created_at': capture.get('captured_at'),
                    'restored_at': None,
                    'pinned': bool(capture.get('pinned')),
                    'file_count': capture.get('file_count') or len(shown),
                    'total_size': capture.get('total_size') or 0,
                    'shown_count': len(shown),
                    'shown_size': sum(int(f.get('file_size') or 0) for f in shown),
                    'files': shown,
                })
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
