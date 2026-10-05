#!/usr/bin/env python3
"""
Storage for the sync engine: runs, their stages, and each stage's log.

A run is one pass through the pipeline. Everything about it that a person
might ask later — what asked for it, what each stage decided and why, which
webhooks rode on it, which transfer it became — is written here as it happens,
never reconstructed afterwards. That is what lets the interface show a run's
stages with their own output, and what lets a restart see what was in flight.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from models.transfer import escape_like
from services.sync_engine.stages import (
    ACTIVE_STATES,
    OPEN_STATES,
    PENDING,
    RUNNING,
    STAGE_DONE,
    STAGE_IDS,
    WAITING,
)

#: The two webhook tables, by the media they carry.
SERIES_TABLE = 'sonarr_webhook'
MOVIE_TABLE = 'radarr_webhook'
WEBHOOK_TABLES = (SERIES_TABLE, MOVIE_TABLE)

#: Events are a log a person reads. A pathological run (a burst of hundreds of
#: webhooks) must not be able to grow one without bound.
MAX_EVENTS_PER_RUN = 2000

_JSON_FIELDS = ('options',)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def _dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(value))


def _loads(value: Optional[str], fallback: Any) -> Any:
    if value in (None, ''):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def episode_label(notification: Dict[str, Any]) -> str:
    """How one series webhook is named in a list: S01E05, or S01E05–E06."""
    episodes = notification.get('episodes')
    if isinstance(episodes, str):
        episodes = _loads(episodes, [])
    codes = []
    for episode in episodes or []:
        if not isinstance(episode, dict):
            continue
        season = episode.get('seasonNumber')
        number = episode.get('episodeNumber')
        if season is None or number is None:
            continue
        try:
            codes.append((int(season), int(number)))
        except (TypeError, ValueError):
            continue
    if not codes:
        season = notification.get('season_number')
        return f"Season {int(season):02d}" if isinstance(season, int) else 'An episode'
    codes.sort()
    first_season, first = codes[0]
    label = f"S{first_season:02d}E{first:02d}"
    if len(codes) > 1:
        label += f"–E{codes[-1][1]:02d}"
    return label


class SyncRunStore:
    """Reads and writes runs, stages, events and webhook membership."""

    def __init__(self, db_manager):
        self.db = db_manager

    # ------------------------------------------------------------------ runs

    @staticmethod
    def _row(row) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        data = dict(row)
        data['options'] = _loads(data.get('options'), {})
        return data

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a run and a pending row for every stage. Returns the run."""
        now = utc_now_iso()
        row = dict(data)
        row.setdefault('created_at', now)
        row['updated_at'] = now
        row['options'] = _dumps(row.get('options') or {})
        columns = list(row.keys())
        with self.db.get_connection() as conn:
            conn.execute(
                f"INSERT INTO sync_run ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [row[c] for c in columns],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO sync_run_stage (run_id, stage, status, updated_at) "
                "VALUES (?, ?, ?, ?)",
                [(row['run_id'], stage, PENDING, now) for stage in STAGE_IDS],
            )
            conn.commit()
        return self.get(row['run_id'])

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        if not run_id:
            return None
        with self.db.get_connection() as conn:
            return self._row(conn.execute(
                "SELECT * FROM sync_run WHERE run_id = ?", (run_id,)).fetchone())

    def update(self, run_id: str, **fields) -> bool:
        if not fields:
            return False
        fields['updated_at'] = utc_now_iso()
        for name in _JSON_FIELDS:
            if name in fields and not isinstance(fields[name], str):
                fields[name] = _dumps(fields[name] or {})
        sets = ', '.join(f"{key} = ?" for key in fields)
        with self.db.get_connection() as conn:
            cursor = conn.execute(f"UPDATE sync_run SET {sets} WHERE run_id = ?",
                                  [*fields.values(), run_id])
            conn.commit()
            return cursor.rowcount > 0

    def merge_options(self, run_id: str, **values) -> Dict[str, Any]:
        """Add keys to a run's options without losing what is there."""
        run = self.get(run_id) or {}
        options = dict(run.get('options') or {})
        options.update(values)
        self.update(run_id, options=options)
        return options

    def find_open(self, unit_key: str) -> Optional[Dict[str, Any]]:
        """The batch a new request for this folder should join, if one is open."""
        if not unit_key:
            return None
        placeholders = ', '.join('?' for _ in OPEN_STATES)
        with self.db.get_connection() as conn:
            return self._row(conn.execute(
                f"SELECT * FROM sync_run WHERE unit_key = ? AND mergeable = 1 "
                f"AND state IN ({placeholders}) ORDER BY id ASC LIMIT 1",
                (unit_key, *OPEN_STATES)).fetchone())

    def find_active(self, unit_key: str) -> Optional[Dict[str, Any]]:
        """A run copying (or paused mid-copy) into this folder, if there is one."""
        if not unit_key:
            return None
        placeholders = ', '.join('?' for _ in ACTIVE_STATES)
        with self.db.get_connection() as conn:
            return self._row(conn.execute(
                f"SELECT * FROM sync_run WHERE unit_key = ? "
                f"AND state IN ({placeholders}) ORDER BY id DESC LIMIT 1",
                (unit_key, *ACTIVE_STATES)).fetchone())

    def find_live(self, unit_key: str) -> Optional[Dict[str, Any]]:
        """Any run for this folder that has not finished — open or active."""
        return self.find_open(unit_key) or self.find_active(unit_key)

    def by_transfer(self, transfer_id: str) -> Optional[Dict[str, Any]]:
        """The newest run that owns this transfer."""
        if not transfer_id:
            return None
        with self.db.get_connection() as conn:
            return self._row(conn.execute(
                "SELECT * FROM sync_run WHERE transfer_id = ? ORDER BY id DESC LIMIT 1",
                (transfer_id,)).fetchone())

    def due(self, now: float, limit: int = 50) -> List[str]:
        """Runs in the ready check whose next step is due."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT run_id FROM sync_run WHERE state = 'waiting' "
                "AND next_check_at IS NOT NULL AND next_check_at <= ? "
                "ORDER BY next_check_at ASC LIMIT ?", (now, limit)).fetchall()
        return [r['run_id'] for r in rows]

    def in_states(self, states: Sequence[str]) -> List[Dict[str, Any]]:
        if not states:
            return []
        placeholders = ', '.join('?' for _ in states)
        with self.db.get_connection() as conn:
            return [self._row(r) for r in conn.execute(
                f"SELECT * FROM sync_run WHERE state IN ({placeholders}) ORDER BY id ASC",
                list(states)).fetchall()]

    def children(self, run_id: str) -> List[Dict[str, Any]]:
        """Runs that follow or retry this one."""
        with self.db.get_connection() as conn:
            return [self._row(r) for r in conn.execute(
                "SELECT * FROM sync_run WHERE parent_run_id = ? ORDER BY id ASC",
                (run_id,)).fetchall()]

    def _filter(self, states=None, kinds=None, search=None,
                include_simulation=True, unit_key=None):
        conditions, params = [], []
        if states:
            conditions.append(f"state IN ({', '.join('?' for _ in states)})")
            params.extend(states)
        if kinds:
            conditions.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            params.extend(kinds)
        if unit_key:
            conditions.append("unit_key = ?")
            params.append(unit_key)
        if not include_simulation:
            conditions.append("is_simulation = 0")
        if search:
            term = f"%{escape_like(search.strip())}%"
            conditions.append(
                "(title LIKE ? ESCAPE '\\' OR folder_name LIKE ? ESCAPE '\\'"
                " OR season_name LIKE ? ESCAPE '\\' OR dest_path LIKE ? ESCAPE '\\'"
                " OR run_id LIKE ? ESCAPE '\\' OR transfer_id LIKE ? ESCAPE '\\')")
            params.extend([term] * 6)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        return where, params

    def list(self, states=None, kinds=None, search=None, limit: int = 50,
             offset: int = 0, include_simulation: bool = True,
             unit_key: str = None) -> List[Dict[str, Any]]:
        where, params = self._filter(states, kinds, search, include_simulation, unit_key)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM sync_run{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, max(1, int(limit)), max(0, int(offset))]).fetchall()
        return [self._row(r) for r in rows]

    def count(self, states=None, kinds=None, search=None,
              include_simulation: bool = True, unit_key: str = None) -> int:
        where, params = self._filter(states, kinds, search, include_simulation, unit_key)
        with self.db.get_connection() as conn:
            return conn.execute(f"SELECT COUNT(*) AS n FROM sync_run{where}",
                                params).fetchone()['n']

    def state_counts(self, include_simulation: bool = True) -> Dict[str, int]:
        where = "" if include_simulation else " WHERE is_simulation = 0"
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT state, COUNT(*) AS n FROM sync_run{where} GROUP BY state").fetchall()
        return {r['state']: r['n'] for r in rows}

    # ---------------------------------------------------------------- stages

    def set_stage(self, run_id: str, stage: str, status: str,
                  summary: Optional[str] = None,
                  detail: Optional[Dict[str, Any]] = None) -> None:
        """Record where a stage is. Start and finish times are kept automatically."""
        now = utc_now_iso()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT started_at FROM sync_run_stage WHERE run_id = ? AND stage = ?",
                (run_id, stage)).fetchone()
            started_at = row['started_at'] if row else None
            if started_at is None and status != PENDING:
                started_at = now
            finished_at = now if status in STAGE_DONE else None
            conn.execute(
                "INSERT INTO sync_run_stage (run_id, stage, status, summary, detail, "
                "started_at, finished_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id, stage) DO UPDATE SET status = excluded.status, "
                "summary = COALESCE(excluded.summary, sync_run_stage.summary), "
                "detail = COALESCE(excluded.detail, sync_run_stage.detail), "
                "started_at = excluded.started_at, finished_at = excluded.finished_at, "
                "updated_at = excluded.updated_at",
                (run_id, stage, status, summary, _dumps(detail), started_at,
                 finished_at, now))
            conn.commit()

    def reset_stage(self, run_id: str, stage: str) -> None:
        """Put a stage back to pending, clearing its outcome (a resumed copy)."""
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE sync_run_stage SET status = ?, finished_at = NULL, "
                "updated_at = ? WHERE run_id = ? AND stage = ?",
                (PENDING, utc_now_iso(), run_id, stage))
            conn.commit()

    def stages(self, run_id: str) -> Dict[str, Dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sync_run_stage WHERE run_id = ?", (run_id,)).fetchall()
        out = {}
        for row in rows:
            data = dict(row)
            data['detail'] = _loads(data.get('detail'), None)
            out[data['stage']] = data
        return out

    def stage_strips(self, run_ids: Iterable[str]) -> Dict[str, Dict[str, str]]:
        """Each run's stage statuses, for a list that draws a strip per row."""
        ids = [r for r in run_ids if r]
        if not ids:
            return {}
        out: Dict[str, Dict[str, str]] = {run_id: {} for run_id in ids}
        with self.db.get_connection() as conn:
            for start in range(0, len(ids), 400):
                batch = ids[start:start + 400]
                rows = conn.execute(
                    f"SELECT run_id, stage, status FROM sync_run_stage "
                    f"WHERE run_id IN ({', '.join('?' for _ in batch)})", batch).fetchall()
                for row in rows:
                    out.setdefault(row['run_id'], {})[row['stage']] = row['status']
        return out

    # ---------------------------------------------------------------- events

    def add_event(self, run_id: str, stage: str, message: str,
                  level: str = 'info', data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = utc_now_iso()
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO sync_run_event (run_id, stage, level, message, data, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, stage, level, message, _dumps(data), now))
            event_id = cursor.lastrowid
            # Bound the log. Oldest lines go first; the end of a run's story is
            # the part a person opens it for.
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM sync_run_event WHERE run_id = ?",
                (run_id,)).fetchone()['n']
            if count > MAX_EVENTS_PER_RUN:
                conn.execute(
                    "DELETE FROM sync_run_event WHERE id IN (SELECT id FROM sync_run_event "
                    "WHERE run_id = ? ORDER BY id ASC LIMIT ?)",
                    (run_id, count - MAX_EVENTS_PER_RUN))
            conn.commit()
        return {'id': event_id, 'run_id': run_id, 'stage': stage, 'level': level,
                'message': message, 'data': data, 'created_at': now}

    def events(self, run_id: str, after_id: int = 0,
               limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = ("SELECT * FROM sync_run_event WHERE run_id = ? AND id > ? "
                 "ORDER BY id ASC")
        params: List[Any] = [run_id, int(after_id or 0)]
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data['data'] = _loads(data.get('data'), None)
            out.append(data)
        return out

    # -------------------------------------------------------------- webhooks

    def attach_webhook(self, table: str, notification_id: str, run_id: str) -> None:
        if table not in WEBHOOK_TABLES:
            raise ValueError(f"Not a webhook table: {table}")
        with self.db.get_connection() as conn:
            conn.execute(
                f"UPDATE {table} SET sync_run_id = ?, sync_attached_at = ? "
                f"WHERE notification_id = ?",
                (run_id, utc_now_iso(), notification_id))
            conn.commit()

    def move_webhooks(self, table: str, notification_ids: Sequence[str],
                      run_id: str) -> int:
        if table not in WEBHOOK_TABLES or not notification_ids:
            return 0
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE {table} SET sync_run_id = ?, sync_attached_at = ? "
                f"WHERE notification_id IN ({', '.join('?' for _ in notification_ids)})",
                (run_id, utc_now_iso(), *notification_ids))
            conn.commit()
            return cursor.rowcount

    def webhooks(self, run_id: str) -> List[Dict[str, Any]]:
        """Every webhook riding on a run, oldest first, with a readable label."""
        out: List[Dict[str, Any]] = []
        with self.db.get_connection() as conn:
            for row in conn.execute(
                    "SELECT notification_id, status, episodes, season_number, "
                    "series_title AS title, created_at, sync_attached_at, transfer_id, "
                    "requires_manual_sync, manual_sync_reason "
                    "FROM sonarr_webhook WHERE sync_run_id = ? ORDER BY created_at ASC",
                    (run_id,)).fetchall():
                data = dict(row)
                data['table'] = SERIES_TABLE
                data['label'] = episode_label(data)
                data.pop('episodes', None)
                out.append(data)
            for row in conn.execute(
                    "SELECT notification_id, status, title, year, created_at, "
                    "sync_attached_at, transfer_id, requires_manual_sync, "
                    "manual_sync_reason FROM radarr_webhook "
                    "WHERE sync_run_id = ? ORDER BY created_at ASC", (run_id,)).fetchall():
                data = dict(row)
                data['table'] = MOVIE_TABLE
                year = data.get('year')
                data['label'] = f"{data.get('title')} ({year})" if year else data.get('title')
                out.append(data)
        return out

    def webhook_ids(self, run_id: str, table: Optional[str] = None) -> List[str]:
        tables = [table] if table else list(WEBHOOK_TABLES)
        ids: List[str] = []
        with self.db.get_connection() as conn:
            for name in tables:
                ids.extend(r['notification_id'] for r in conn.execute(
                    f"SELECT notification_id FROM {name} WHERE sync_run_id = ? "
                    f"ORDER BY created_at ASC", (run_id,)).fetchall())
        return ids

    def webhook_counts(self, run_ids: Iterable[str]) -> Dict[str, int]:
        ids = [r for r in run_ids if r]
        counts: Dict[str, int] = {}
        if not ids:
            return counts
        with self.db.get_connection() as conn:
            for table in WEBHOOK_TABLES:
                for start in range(0, len(ids), 400):
                    batch = ids[start:start + 400]
                    for row in conn.execute(
                            f"SELECT sync_run_id, COUNT(*) AS n FROM {table} "
                            f"WHERE sync_run_id IN ({', '.join('?' for _ in batch)}) "
                            f"GROUP BY sync_run_id", batch).fetchall():
                        counts[row['sync_run_id']] = counts.get(row['sync_run_id'], 0) + row['n']
        return counts

    def _columns(self, conn, table: str) -> set:
        cache = getattr(self, '_column_cache', None)
        if cache is None:
            cache = self._column_cache = {}
        if table not in cache:
            cache[table] = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        return cache[table]

    def update_webhooks(self, run_id: str, updates: Dict[str, Any],
                        only_status: Optional[Sequence[str]] = None,
                        exclude_status: Optional[Sequence[str]] = None) -> int:
        """Set fields on every webhook of a run, optionally narrowed by status.

        The two webhook tables are not the same shape — the manual-sync flag and
        the dry-run result exist only for series — so each table is given only
        the fields it has.
        """
        if not updates:
            return 0
        total = 0
        with self.db.get_connection() as conn:
            for table in WEBHOOK_TABLES:
                columns = self._columns(conn, table)
                fields = {k: v for k, v in updates.items() if k in columns}
                if not fields:
                    continue
                sets = ', '.join(f"{key} = ?" for key in fields)
                query = f"UPDATE {table} SET {sets}, updated_at = ? WHERE sync_run_id = ?"
                params: List[Any] = [*fields.values(), utc_now_iso(), run_id]
                if only_status:
                    query += f" AND status IN ({', '.join('?' for _ in only_status)})"
                    params.extend(only_status)
                if exclude_status:
                    query += f" AND status NOT IN ({', '.join('?' for _ in exclude_status)})"
                    params.extend(exclude_status)
                total += conn.execute(query, params).rowcount
            conn.commit()
        return total

    def webhooks_attached_after(self, run_id: str, moment_iso: str) -> Dict[str, List[str]]:
        """Webhooks that joined a run after a moment — the copy may have missed them."""
        out: Dict[str, List[str]] = {}
        with self.db.get_connection() as conn:
            for table in WEBHOOK_TABLES:
                ids = [r['notification_id'] for r in conn.execute(
                    f"SELECT notification_id FROM {table} WHERE sync_run_id = ? "
                    f"AND sync_attached_at > ?", (run_id, moment_iso)).fetchall()]
                if ids:
                    out[table] = ids
        return out

    def stranded_auto_sync_webhooks(self, since_iso: str) -> List[Dict[str, Any]]:
        """Series webhooks an automatic sync had picked up and never finished.

        Two shapes: rows riding on a run that a restart interrupted, and rows
        from before the engine existed that the old scheduler had taken
        (`auto_sync_scheduled_at` set) and left pending. A row nobody scheduled
        — automatic sync off — is waiting for a person by design and is not
        stranded.
        """
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT w.notification_id, w.media_type, w.series_title, w.season_number, "
                "w.season_path, w.series_path, w.status, w.created_at, w.sync_run_id "
                "FROM sonarr_webhook w LEFT JOIN sync_run r ON r.run_id = w.sync_run_id "
                "WHERE w.created_at >= ? AND COALESCE(w.is_simulation, 0) = 0 "
                "AND w.status IN ('pending', 'READY_FOR_TRANSFER') "
                "AND COALESCE(w.requires_manual_sync, 0) = 0 "
                "AND ((w.sync_run_id IS NULL AND w.auto_sync_scheduled_at IS NOT NULL) "
                "     OR r.state = 'interrupted') "
                "ORDER BY w.created_at ASC", (since_iso,)).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- cleanup

    def delete_runs(self, run_ids: Sequence[str]) -> int:
        ids = [r for r in run_ids if r]
        if not ids:
            return 0
        deleted = 0
        with self.db.get_connection() as conn:
            for start in range(0, len(ids), 400):
                batch = ids[start:start + 400]
                marks = ', '.join('?' for _ in batch)
                conn.execute(f"DELETE FROM sync_run_event WHERE run_id IN ({marks})", batch)
                conn.execute(f"DELETE FROM sync_run_stage WHERE run_id IN ({marks})", batch)
                deleted += conn.execute(
                    f"DELETE FROM sync_run WHERE run_id IN ({marks})", batch).rowcount
            conn.commit()
        return deleted

    def delete_simulation_runs(self) -> int:
        with self.db.get_connection() as conn:
            ids = [r['run_id'] for r in conn.execute(
                "SELECT run_id FROM sync_run WHERE is_simulation = 1").fetchall()]
        return self.delete_runs(ids)
