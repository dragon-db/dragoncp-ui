#!/usr/bin/env python3
"""
DragonCP Activity Model
Data access for the record of who did what.

Only consequential actions are written here — the ones that change something, or
that someone would later want held to account. Reads are deliberately absent:
browsing a library is nobody's business to answer for, and recording it would
bury the entries that matter under noise.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


#: Actions the application records, grouped by what they act on. Kept as a
#: closed vocabulary so the activity screen can offer them as filters and so a
#: typo at a call site shows up as an unknown action rather than a new category
#: nobody notices.
ACTIONS = {
    # transfers
    'transfer.start': 'Started a sync',
    'transfer.cancel': 'Cancelled a sync',
    'transfer.pause': 'Paused a sync',
    'transfer.resume': 'Resumed a sync',
    'transfer.restart': 'Restarted a sync',
    'transfer.delete': 'Deleted a sync record',
    'transfer.bulk_delete': 'Deleted several sync records',
    'transfer.cleanup': 'Cleaned up duplicate sync records',
    # backups
    'backup.restore': 'Restored a backup',
    'backup.delete': 'Deleted a backup',
    'backup.bulk_delete': 'Deleted several backups',
    'backup.clear_unsorted': 'Cleared unidentified backups',
    'backup.pin': 'Pinned a backup',
    'backup.unpin': 'Unpinned a backup',
    'backup.rebuild_index': 'Rebuilt the backup index',
    'backup.retention_save': 'Changed the backup retention rule',
    'backup.retention_apply': 'Applied the backup retention rule',
    'backup.migrate': 'Migrated old backup folders',
    # webhook notifications
    'notification.sync': 'Synced from a notification',
    'notification.sync_batch': 'Synced a group of notifications',
    'notification.delete': 'Deleted a notification',
    'notification.bulk_delete': 'Deleted several notifications',
    'notification.complete': 'Marked a notification complete',
    'notification.received': 'Received a notification',
    'notification.verify_rename': 'Verified a rename',
    # explore
    'explore.transfer': 'Ran an approved Explore plan',
    'explore.repair': 'Moved misplaced files back into place',
    # settings and connection
    'settings.update': 'Changed settings',
    'settings.webhook_update': 'Changed webhook settings',
    'settings.discord_update': 'Changed Discord settings',
    'settings.discord_test': 'Sent a Discord test message',
    'ssh.connect': 'Connected to the media server',
    'ssh.disconnect': 'Disconnected from the media server',
    # simulation
    'simulation.start': 'Started a simulation',
    'simulation.stop': 'Stopped a simulation',
    'simulation.cleanup': 'Cleared simulation data',
    # accounts and sessions
    'auth.login': 'Signed in',
    'auth.login_failed': 'Failed to sign in',
    'auth.login_blocked': 'Was blocked after repeated failures',
    'auth.logout': 'Signed out',
    'auth.password_change': 'Changed their password',
}

OUTCOME_OK = 'ok'
OUTCOME_FAILED = 'failed'
OUTCOME_REFUSED = 'refused'


def _row_to_dict(row) -> Dict[str, Any]:
    entry = dict(row)
    detail = entry.get('detail')
    if detail:
        try:
            entry['detail'] = json.loads(detail)
        except (TypeError, ValueError):
            entry['detail'] = None
    return entry


def _normalise_timestamp(value: str, field: str) -> str:
    """Convert an ISO timestamp to the UTC text format SQLite stores here."""
    raw = str(value).strip()
    if raw.endswith(('Z', 'z')):
        raw = f'{raw[:-1]}+00:00'
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{field} must be a valid ISO timestamp') from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')


class Activity:
    """Read and write the activity table."""

    def __init__(self, db_manager):
        self.db = db_manager

    # ----- writing ---------------------------------------------------------

    def record(
        self,
        actor,
        action: str,
        summary: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        target_label: Optional[str] = None,
        detail: Optional[Dict] = None,
        outcome: str = OUTCOME_OK,
        request_ip: Optional[str] = None,
    ) -> Optional[int]:
        """
        Write one entry. Returns its id, or None if it could not be written.

        Recording must never be the reason an action fails: a transfer that ran
        and a backup that was deleted have happened whether or not the trail
        caught them, and raising here would turn a bookkeeping problem into a
        user-visible one. Failures are reported to the log and swallowed.
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    '''
                    INSERT INTO activity (
                        actor_kind, actor_name, actor_account_id,
                        action, target_type, target_id, target_label,
                        summary, detail, outcome, request_ip
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        actor.kind,
                        actor.name,
                        actor.account_id,
                        action,
                        target_type,
                        str(target_id) if target_id is not None else None,
                        target_label,
                        summary,
                        json.dumps(detail, default=str) if detail else None,
                        outcome,
                        request_ip,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as error:  # noqa: BLE001 - see docstring
            print(f"⚠️  Could not record activity '{action}': {error}")
            return None

    # ----- reading ---------------------------------------------------------

    def query(
        self,
        actor_account_id: Optional[int] = None,
        actor_name: Optional[str] = None,
        actor_kind: Optional[str] = None,
        action: Optional[str] = None,
        action_group: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Page through the trail, newest first, with the total behind it.

        Every filter is optional and they combine with AND.
        """
        clauses: List[str] = []
        params: List[Any] = []

        if actor_account_id is not None:
            clauses.append('actor_account_id = ?')
            params.append(actor_account_id)
        if actor_name:
            clauses.append('actor_name = ? COLLATE NOCASE')
            params.append(actor_name)
        if actor_kind:
            clauses.append('actor_kind = ?')
            params.append(actor_kind)
        if action:
            clauses.append('action = ?')
            params.append(action)
        if action_group:
            # 'backup' matches backup.restore, backup.delete, and so on.
            clauses.append('action LIKE ?')
            params.append(f'{action_group}.%')
        if target_type:
            clauses.append('target_type = ?')
            params.append(target_type)
        if target_id:
            clauses.append('target_id = ?')
            params.append(str(target_id))
        if outcome:
            clauses.append('outcome = ?')
            params.append(outcome)
        if since:
            clauses.append('occurred_at >= ?')
            params.append(_normalise_timestamp(since, 'since'))
        if until:
            clauses.append('occurred_at <= ?')
            params.append(_normalise_timestamp(until, 'until'))
        if search:
            clauses.append('(summary LIKE ? OR target_label LIKE ? OR actor_name LIKE ?)')
            like = f'%{search}%'
            params.extend([like, like, like])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        with self.db.get_connection() as conn:
            total = conn.execute(
                f'SELECT COUNT(*) AS total FROM activity {where}', params
            ).fetchone()['total']

            rows = conn.execute(
                f'''
                SELECT * FROM activity {where}
                ORDER BY occurred_at DESC, id DESC
                LIMIT ? OFFSET ?
                ''',
                params + [limit, offset],
            ).fetchall()

        return {
            'entries': [_row_to_dict(row) for row in rows],
            'total': int(total),
            'limit': limit,
            'offset': offset,
        }

    def for_target(self, target_type: str, target_id: str, limit: int = 50) -> List[Dict]:
        """Everything recorded against one thing, oldest first — its story."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT * FROM activity
                 WHERE target_type = ? AND target_id = ?
                 ORDER BY occurred_at ASC, id ASC
                 LIMIT ?
                ''',
                (target_type, str(target_id), max(1, min(int(limit), 500))),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def actors_seen(self) -> List[Dict]:
        """
        Everyone and everything that appears in the trail.

        Drives the filter list on the activity screen, and includes actors whose
        accounts have since been disabled — the point of keeping the rows.
        """
        with self.db.get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT actor_kind, actor_name, actor_account_id, COUNT(*) AS entries,
                       MAX(occurred_at) AS last_seen
                  FROM activity
                 GROUP BY actor_kind, actor_name, actor_account_id
                 ORDER BY actor_kind, actor_name COLLATE NOCASE
                '''
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        with self.db.get_connection() as conn:
            return int(conn.execute('SELECT COUNT(*) AS c FROM activity').fetchone()['c'])
