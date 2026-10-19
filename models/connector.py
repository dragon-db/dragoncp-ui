#!/usr/bin/env python3
"""
Connector rows: the store behind the connector layer.

Six tables, one class. Every method here is about rows; nothing here knows
what a Discord webhook is or how an announcement is rendered.

The one invariant worth stating: **secrets go out of this class only through
`secret()` and `secret_reader()`**. There is no `get_all_secrets`, no secret
in any dictionary returned by a listing method, and no code path from an API
response back to `connector_secret`. That is why the values live in their own
table instead of inside the config blob — the rule is enforced by there being
nothing to call, rather than by remembering to redact.
"""

import json
import uuid
from typing import Any, Callable, Dict, List, Optional

#: How many delivery rows to keep per connector. Enough to answer "why didn't
#: I get told about that" for a normal week; small enough to never matter.
DELIVERY_HISTORY_LIMIT = 100


def _id_list(raw: Any) -> Optional[List[str]]:
    """A stored JSON list of ids, or None when nothing is stored."""
    if raw in (None, ''):
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return [str(item) for item in value] if isinstance(value, list) else None


def _id_json(ids: Optional[List[str]]) -> Optional[str]:
    return None if ids is None else json.dumps([str(i) for i in ids])


class ConnectorStore:
    """Row access for connectors, their secrets, targets, routes and deliveries."""

    def __init__(self, db_manager):
        self.db = db_manager

    # ---- connectors --------------------------------------------------------

    def list_connectors(self) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM connector ORDER BY connector_id'
            ).fetchall()
        return [self._connector_row(row) for row in rows]

    def get_connector(self, connector_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM connector WHERE connector_id = ?', (connector_id,)
            ).fetchone()
        return self._connector_row(row) if row else None

    def upsert_connector(self, connector_id: str, display_name: str, *,
                         enabled: Optional[bool] = None,
                         config: Optional[Dict[str, Any]] = None) -> None:
        """Create the row, or update only the parts that were supplied.

        `enabled=None` and `config=None` mean "leave alone" rather than "set to
        empty" — saving one tab of a form must not silently reset another.
        """
        existing = self.get_connector(connector_id)
        merged_config = dict(existing['config']) if existing else {}
        if config is not None:
            merged_config.update(config)
        resolved_enabled = (
            bool(enabled) if enabled is not None
            else (existing['enabled'] if existing else False)
        )

        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO connector (connector_id, display_name, enabled, config)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(connector_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    enabled = excluded.enabled,
                    config = excluded.config,
                    updated_at = CURRENT_TIMESTAMP
            ''', (connector_id, display_name, 1 if resolved_enabled else 0,
                  json.dumps(merged_config)))
            conn.commit()

    def set_enabled(self, connector_id: str, enabled: bool) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                'UPDATE connector SET enabled = ?, updated_at = CURRENT_TIMESTAMP '
                'WHERE connector_id = ?',
                (1 if enabled else 0, connector_id),
            )
            conn.commit()

    def record_check(self, connector_id: str, ok: bool, message: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute('''
                UPDATE connector
                   SET last_check_at = CURRENT_TIMESTAMP,
                       last_check_ok = ?,
                       last_check_message = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE connector_id = ?
            ''', (1 if ok else 0, message, connector_id))
            conn.commit()

    def clear_check(self, connector_id: str) -> None:
        """Forget the last check, once it describes a connection that changed."""
        with self.db.get_connection() as conn:
            conn.execute('''
                UPDATE connector
                   SET last_check_at = NULL,
                       last_check_ok = NULL,
                       last_check_message = NULL
                 WHERE connector_id = ?
            ''', (connector_id,))
            conn.commit()

    def delete_connector(self, connector_id: str) -> None:
        """Remove a connector and everything belonging to it."""
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM connector WHERE connector_id = ?', (connector_id,))
            conn.execute('DELETE FROM connector_secret WHERE connector_id = ?', (connector_id,))
            conn.execute('DELETE FROM connector_target WHERE connector_id = ?', (connector_id,))
            conn.execute('DELETE FROM notification_route WHERE connector_id = ?', (connector_id,))
            conn.execute('DELETE FROM connector_mention WHERE connector_id = ?', (connector_id,))
            conn.commit()

    # ---- secrets -----------------------------------------------------------

    def secret(self, connector_id: str, name: str) -> str:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT value FROM connector_secret WHERE connector_id = ? AND name = ?',
                (connector_id, name),
            ).fetchone()
        return row[0] if row else ''

    def secret_reader(self, connector_id: str) -> Callable[[str], str]:
        """A reader bound to one connector, for handing to its adapter."""
        return lambda name: self.secret(connector_id, name)

    def set_secret(self, connector_id: str, name: str, value: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO connector_secret (connector_id, name, value, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(connector_id, name) DO UPDATE SET
                    value = excluded.value, updated_at = CURRENT_TIMESTAMP
            ''', (connector_id, name, value))
            conn.commit()

    def delete_secret(self, connector_id: str, name: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                'DELETE FROM connector_secret WHERE connector_id = ? AND name = ?',
                (connector_id, name),
            )
            conn.commit()

    def has_secret(self, connector_id: str, name: str) -> bool:
        """Whether a value is set, without reading it.

        This is what the UI asks so it can show "configured" beside a field it
        must never be shown the contents of.
        """
        return bool(self.secret(connector_id, name))

    # ---- targets -----------------------------------------------------------

    def list_targets(self, connector_id: str) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM connector_target WHERE connector_id = ? '
                'ORDER BY is_default DESC, created_at ASC, id ASC',
                (connector_id,),
            ).fetchall()
        return [self._target_row(row) for row in rows]

    def get_target(self, target_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM connector_target WHERE target_id = ?', (target_id,)
            ).fetchone()
        return self._target_row(row) if row else None

    def default_target(self, connector_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM connector_target '
                'WHERE connector_id = ? AND is_default = 1',
                (connector_id,),
            ).fetchone()
        return self._target_row(row) if row else None

    def create_target(self, connector_id: str, label: str, credential: str, *,
                      make_default: Optional[bool] = None,
                      target_id: Optional[str] = None) -> str:
        """Add a destination and store its credential.

        The first target of a connector always becomes the default: a
        connector with destinations but no default cannot deliver anything,
        and arriving in that state by adding one webhook would be a trap.
        """
        target_id = target_id or f"tgt_{uuid.uuid4().hex[:12]}"
        secret_ref = f"target:{target_id}"
        existing = self.list_targets(connector_id)
        is_default = (not existing) if make_default is None else bool(make_default)

        self.set_secret(connector_id, secret_ref, credential)
        with self.db.get_connection() as conn:
            if is_default:
                conn.execute(
                    'UPDATE connector_target SET is_default = 0 WHERE connector_id = ?',
                    (connector_id,),
                )
            conn.execute('''
                INSERT INTO connector_target
                    (target_id, connector_id, label, secret_ref, is_default, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
            ''', (target_id, connector_id, label, secret_ref, 1 if is_default else 0))
            conn.commit()
        return target_id

    def update_target(self, target_id: str, *, label: Optional[str] = None,
                      credential: Optional[str] = None,
                      enabled: Optional[bool] = None,
                      make_default: Optional[bool] = None,
                      mention_ids: Optional[List[str]] = None) -> bool:
        """Change what was supplied; `mention_ids=[]` clears the webhook's pings."""
        target = self.get_target(target_id)
        if not target:
            return False

        if credential is not None:
            self.set_secret(target['connector_id'], target['secret_ref'], credential)

        with self.db.get_connection() as conn:
            if make_default:
                # One default per connector, cleared and set in one transaction
                # so no moment exists where two rows claim it or none does.
                conn.execute(
                    'UPDATE connector_target SET is_default = 0 WHERE connector_id = ?',
                    (target['connector_id'],),
                )
                conn.execute(
                    'UPDATE connector_target SET is_default = 1 WHERE target_id = ?',
                    (target_id,),
                )
            if label is not None:
                conn.execute(
                    'UPDATE connector_target SET label = ? WHERE target_id = ?',
                    (label, target_id),
                )
            if enabled is not None:
                conn.execute(
                    'UPDATE connector_target SET enabled = ? WHERE target_id = ?',
                    (1 if enabled else 0, target_id),
                )
            if mention_ids is not None:
                conn.execute(
                    'UPDATE connector_target SET mention_ids = ? WHERE target_id = ?',
                    (_id_json(mention_ids), target_id),
                )
            conn.commit()
        return True

    def delete_target(self, target_id: str) -> bool:
        """Remove a destination, promoting a new default if this was it.

        Deleting the default must not leave the connector undeliverable while
        other destinations exist. Routes pointing at the deleted target are
        cleared to NULL rather than removed, so they fall back to the default
        instead of the event going silent.
        """
        target = self.get_target(target_id)
        if not target:
            return False

        connector_id = target['connector_id']
        self.delete_secret(connector_id, target['secret_ref'])

        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM connector_target WHERE target_id = ?', (target_id,))
            conn.execute(
                'UPDATE notification_route SET target_id = NULL, '
                'updated_at = CURRENT_TIMESTAMP WHERE target_id = ?',
                (target_id,),
            )
            if target['is_default']:
                promoted = conn.execute(
                    'SELECT target_id FROM connector_target WHERE connector_id = ? '
                    'ORDER BY created_at ASC, id ASC LIMIT 1',
                    (connector_id,),
                ).fetchone()
                if promoted:
                    conn.execute(
                        'UPDATE connector_target SET is_default = 1 WHERE target_id = ?',
                        (promoted[0],),
                    )
            conn.commit()
        return True

    def record_send(self, target_id: str, ok: bool, error: Optional[str]) -> None:
        with self.db.get_connection() as conn:
            conn.execute('''
                UPDATE connector_target
                   SET last_send_at = CURRENT_TIMESTAMP,
                       last_send_ok = ?,
                       last_send_error = ?
                 WHERE target_id = ?
            ''', (1 if ok else 0, error, target_id))
            conn.commit()

    # ---- routes ------------------------------------------------------------

    def list_routes(self, connector_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = 'SELECT * FROM notification_route'
        params: tuple = ()
        if connector_id:
            query += ' WHERE connector_id = ?'
            params = (connector_id,)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._route_row(row) for row in rows]

    def get_route(self, event_key: str, connector_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM notification_route WHERE event_key = ? AND connector_id = ?',
                (event_key, connector_id),
            ).fetchone()
        return self._route_row(row) if row else None

    def set_route(self, event_key: str, connector_id: str,
                  target_id: Optional[str], enabled: bool = True,
                  ping_when: Optional[str] = None,
                  mention_ids: Optional[List[str]] = None) -> None:
        """Where one notification goes, and when and whom it pings.

        `ping_when=None` is the catalogue's default; `mention_ids=None` is the
        webhook's own pings, and `[]` is nobody.
        """
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO notification_route
                    (event_key, connector_id, target_id, enabled, ping_when,
                     mention_ids, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(event_key, connector_id) DO UPDATE SET
                    target_id = excluded.target_id,
                    enabled = excluded.enabled,
                    ping_when = excluded.ping_when,
                    mention_ids = excluded.mention_ids,
                    updated_at = CURRENT_TIMESTAMP
            ''', (event_key, connector_id, target_id, 1 if enabled else 0,
                  ping_when, _id_json(mention_ids)))
            conn.commit()

    def clear_route(self, event_key: str, connector_id: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                'DELETE FROM notification_route WHERE event_key = ? AND connector_id = ?',
                (event_key, connector_id),
            )
            conn.commit()

    # ---- mentions ----------------------------------------------------------

    def list_mentions(self, connector_id: str) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM connector_mention WHERE connector_id = ? '
                'ORDER BY created_at ASC, id ASC',
                (connector_id,),
            ).fetchall()
        return [self._mention_row(row) for row in rows]

    def get_mention(self, mention_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM connector_mention WHERE mention_id = ?', (mention_id,)
            ).fetchone()
        return self._mention_row(row) if row else None

    def mentions_by_ids(self, connector_id: str,
                        mention_ids: Optional[List[str]]) -> List[Dict[str, Any]]:
        """These mentions, in the order given. Ids that no longer exist are
        skipped: a deleted mention pings nobody rather than failing a message."""
        if not mention_ids:
            return []
        known = {m['mention_id']: m for m in self.list_mentions(connector_id)}
        seen, out = set(), []
        for mention_id in mention_ids:
            if mention_id in known and mention_id not in seen:
                seen.add(mention_id)
                out.append(known[mention_id])
        return out

    def create_mention(self, connector_id: str, label: str, kind: str,
                       value: str = '') -> str:
        mention_id = f"men_{uuid.uuid4().hex[:12]}"
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO connector_mention (mention_id, connector_id, label, kind, value)
                VALUES (?, ?, ?, ?, ?)
            ''', (mention_id, connector_id, label, kind, value or ''))
            conn.commit()
        return mention_id

    def update_mention(self, mention_id: str, *, label: Optional[str] = None,
                       kind: Optional[str] = None, value: Optional[str] = None) -> bool:
        if not self.get_mention(mention_id):
            return False
        with self.db.get_connection() as conn:
            for column, new in (('label', label), ('kind', kind), ('value', value)):
                if new is not None:
                    conn.execute(
                        f'UPDATE connector_mention SET {column} = ? WHERE mention_id = ?',
                        (new, mention_id),
                    )
            conn.commit()
        return True

    def delete_mention(self, mention_id: str) -> bool:
        """Remove a mention, and take it out of every webhook and route.

        A route that pinged only this one is left pinging nobody rather than
        falling back to its webhook's pings: someone chose who that route
        pings, and quietly choosing others would be worse.
        """
        mention = self.get_mention(mention_id)
        if not mention:
            return False
        connector_id = mention['connector_id']
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM connector_mention WHERE mention_id = ?', (mention_id,))
            for table, key in (('connector_target', 'target_id'),
                               ('notification_route', 'rowid')):
                rows = conn.execute(
                    f'SELECT {key}, mention_ids FROM {table} '
                    f'WHERE connector_id = ? AND mention_ids IS NOT NULL',
                    (connector_id,),
                ).fetchall()
                for row in rows:
                    ids = _id_list(row[1]) or []
                    if mention_id in ids:
                        conn.execute(
                            f'UPDATE {table} SET mention_ids = ? WHERE {key} = ?',
                            (_id_json([i for i in ids if i != mention_id]), row[0]),
                        )
            conn.commit()
        return True

    # ---- deliveries --------------------------------------------------------

    def record_delivery(self, connector_id: str, *, ok: bool,
                        target_id: Optional[str] = None,
                        target_label: Optional[str] = None,
                        event_key: Optional[str] = None,
                        title: Optional[str] = None,
                        skipped_reason: Optional[str] = None,
                        status_code: Optional[int] = None,
                        error: Optional[str] = None,
                        duration_ms: int = 0,
                        mentions: Optional[str] = None) -> None:
        """`mentions` is who the message pinged, by name, for the log."""
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO connector_delivery
                    (connector_id, target_id, target_label, event_key, title,
                     ok, skipped_reason, status_code, error, duration_ms, mentions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (connector_id, target_id, target_label, event_key, title,
                  1 if ok else 0, skipped_reason, status_code, error, duration_ms,
                  mentions or None))
            # Trimmed on write rather than by a sweep, so the table cannot grow
            # between sweeps and there is no second thing to schedule.
            conn.execute('''
                DELETE FROM connector_delivery
                 WHERE connector_id = ?
                   AND id NOT IN (
                       SELECT id FROM connector_delivery
                        WHERE connector_id = ?
                        ORDER BY id DESC LIMIT ?
                   )
            ''', (connector_id, connector_id, DELIVERY_HISTORY_LIMIT))
            conn.commit()

    def list_deliveries(self, connector_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), DELIVERY_HISTORY_LIMIT))
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM connector_delivery WHERE connector_id = ? '
                'ORDER BY id DESC LIMIT ?',
                (connector_id, limit),
            ).fetchall()
        return [dict(row) | {'ok': bool(row['ok'])} for row in rows]

    # ---- row shaping -------------------------------------------------------

    @staticmethod
    def _connector_row(row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data['config'] = json.loads(data.get('config') or '{}')
        except (TypeError, ValueError):
            data['config'] = {}
        data['enabled'] = bool(data.get('enabled'))
        if data.get('last_check_ok') is not None:
            data['last_check_ok'] = bool(data['last_check_ok'])
        return data

    @staticmethod
    def _target_row(row) -> Dict[str, Any]:
        data = dict(row)
        data['is_default'] = bool(data.get('is_default'))
        data['enabled'] = bool(data.get('enabled'))
        if data.get('last_send_ok') is not None:
            data['last_send_ok'] = bool(data['last_send_ok'])
        data['mention_ids'] = _id_list(data.get('mention_ids')) or []
        return data

    @staticmethod
    def _route_row(row) -> Dict[str, Any]:
        data = dict(row)
        data['enabled'] = bool(data.get('enabled'))
        data['mention_ids'] = _id_list(data.get('mention_ids'))
        return data

    @staticmethod
    def _mention_row(row) -> Dict[str, Any]:
        data = dict(row)
        data.pop('id', None)
        return data
