#!/usr/bin/env python3
"""
Storage for alerts — the Notifications tab.

An alert is something that needs a person: work a restart left unfinished, a
download stuck in Sonarr, a sync the safety check stopped, a transfer that
failed. It stays open until an admin acts on it, and records who did what.

`dedupe_key` keeps one open alert per subject. The same thing happening again
while its alert is still open bumps that alert instead of stacking a second.
"""

import json
import uuid
from typing import Any, Dict, List, Optional, Sequence

from models.sync_run import utc_now, utc_now_iso

OPEN = 'open'
DONE = 'done'
WRONG = 'wrong'
DISMISSED = 'dismissed'
STATES = (OPEN, DONE, WRONG, DISMISSED)


def _loads(value, fallback):
    if value in (None, ''):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


class AlertStore:
    def __init__(self, db_manager):
        self.db = db_manager

    @staticmethod
    def _row(row) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        data = dict(row)
        data['actions'] = _loads(data.get('actions'), [])
        data['data'] = _loads(data.get('data'), {})
        return data

    def find_open(self, dedupe_key: str) -> Optional[Dict[str, Any]]:
        if not dedupe_key:
            return None
        with self.db.get_connection() as conn:
            return self._row(conn.execute(
                "SELECT * FROM alert WHERE dedupe_key = ? AND state = 'open' "
                "ORDER BY id DESC LIMIT 1", (dedupe_key,)).fetchone())

    def create(self, kind: str, severity: str, title: str, message: str = '',
               dedupe_key: Optional[str] = None, run_id: Optional[str] = None,
               transfer_id: Optional[str] = None, unit_key: Optional[str] = None,
               link: Optional[str] = None, actions: Sequence[str] = (),
               data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = utc_now_iso()
        alert_id = f"alert_{uuid.uuid4().hex[:12]}"
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO alert (alert_id, kind, severity, title, message, state, "
                "dedupe_key, run_id, transfer_id, unit_key, link, actions, data, "
                "occurrences, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (alert_id, kind, severity, title, message, dedupe_key, run_id,
                 transfer_id, unit_key, link, json.dumps(list(actions)),
                 json.dumps(data or {}, default=str), now, now))
            conn.commit()
        return self.get(alert_id)

    def bump(self, alert_id: str, message: Optional[str] = None,
             data: Optional[Dict[str, Any]] = None,
             run_id: Optional[str] = None,
             link: Optional[str] = None) -> Optional[Dict[str, Any]]:
        sets = ["occurrences = occurrences + 1", "updated_at = ?"]
        params: List[Any] = [utc_now_iso()]
        if message is not None:
            sets.append("message = ?")
            params.append(message)
        if data is not None:
            sets.append("data = ?")
            params.append(json.dumps(data, default=str))
        if run_id is not None:
            sets.append("run_id = ?")
            params.append(run_id)
        if link is not None:
            sets.append("link = ?")
            params.append(link)
        with self.db.get_connection() as conn:
            conn.execute(f"UPDATE alert SET {', '.join(sets)} WHERE alert_id = ?",
                         (*params, alert_id))
            conn.commit()
        return self.get(alert_id)

    def get(self, alert_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            return self._row(conn.execute(
                "SELECT * FROM alert WHERE alert_id = ?", (alert_id,)).fetchone())

    def closed_by_a_person_since(self, dedupe_key: str, window) -> bool:
        """Whether an alert with this key was dismissed or marked wrong recently."""
        since = (utc_now() - window).isoformat()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM alert WHERE dedupe_key = ? AND state IN (?, ?) "
                "AND resolved_at >= ? LIMIT 1",
                (dedupe_key, DISMISSED, WRONG, since)).fetchone()
        return row is not None

    def last_closed_by_a_person(self, dedupe_key: str) -> Optional[Dict[str, Any]]:
        """The latest alert with this key that was dismissed or marked wrong."""
        with self.db.get_connection() as conn:
            return self._row(conn.execute(
                "SELECT * FROM alert WHERE dedupe_key = ? AND state IN (?, ?) "
                "ORDER BY resolved_at DESC LIMIT 1",
                (dedupe_key, DISMISSED, WRONG)).fetchone())

    def open_for_unit(self, unit_keys: Sequence[str]) -> List[Dict[str, Any]]:
        """Open alerts, of any kind, about one of these folders."""
        keys = [k for k in unit_keys if k]
        if not keys:
            return []
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM alert WHERE state = 'open' AND unit_key IN "
                f"({', '.join('?' for _ in keys)}) ORDER BY id DESC", keys).fetchall()
        return [self._row(r) for r in rows]

    def resolve(self, alert_id: str, state: str, action: str, actor) -> Optional[Dict[str, Any]]:
        now = utc_now_iso()
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE alert SET state = ?, resolved_action = ?, resolved_at = ?, "
                "updated_at = ?, resolved_by_kind = ?, resolved_by_name = ?, "
                "resolved_by_account_id = ? WHERE alert_id = ?",
                (state, action, now, now, getattr(actor, 'kind', None),
                 getattr(actor, 'name', None), getattr(actor, 'account_id', None),
                 alert_id))
            conn.commit()
        return self.get(alert_id)

    def list(self, states: Optional[Sequence[str]] = None, kinds=None, limit: int = 50,
             offset: int = 0, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conditions, params = [], []
        if states:
            conditions.append(f"state IN ({', '.join('?' for _ in states)})")
            params.extend(states)
        if kinds:
            conditions.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            params.extend(kinds)
        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM alert{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, max(1, int(limit)), max(0, int(offset)))).fetchall()
        return [self._row(r) for r in rows]

    def count(self, states: Optional[Sequence[str]] = None, kinds=None) -> int:
        conditions, params = [], []
        if states:
            conditions.append(f"state IN ({', '.join('?' for _ in states)})")
            params.extend(states)
        if kinds:
            conditions.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            params.extend(kinds)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self.db.get_connection() as conn:
            return conn.execute(f"SELECT COUNT(*) AS n FROM alert{where}",
                                params).fetchone()['n']

    def open_counts_by_severity(self) -> Dict[str, int]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT severity, COUNT(*) AS n FROM alert WHERE state = 'open' "
                "GROUP BY severity").fetchall()
        return {r['severity']: r['n'] for r in rows}
