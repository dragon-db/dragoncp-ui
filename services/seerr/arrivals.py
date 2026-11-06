#!/usr/bin/env python3
"""
What DragonCP itself knows about a requested title: has it arrived on the
remote server, and has it been synced here?

Sonarr and Radarr tell DragonCP the moment they import a file on the remote
server (the webhooks behind the Webhooks page), and each of those rows points
at the transfer that brought it here. A Seerr request names its title by the
same TVDB id (series) or TMDB id (films), so the two meet without any
matching on names.

Only arrivals since the request count: an older season that arrived last year
says nothing about this request.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

#: Arrival statuses meaning "on its way here now", from the sync engine.
SYNCING = ('READY_FOR_TRANSFER', 'QUEUED_SLOT', 'QUEUED_PATH', 'syncing')
#: Transfer statuses meaning the same.
TRANSFER_ACTIVE = ('pending', 'queued', 'running', 'paused')
#: Transfers that move nothing into the library.
_NOT_A_SYNC = ('explore_prune', 'restore')


def sqlite_time(iso_value: str) -> Optional[str]:
    """Seerr's `2026-10-30T10:00:27.000Z` as SQLite's `2026-10-30 10:00:27` (UTC)."""
    if not iso_value:
        return None
    try:
        moment = datetime.fromisoformat(str(iso_value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.strftime('%Y-%m-%d %H:%M:%S')


def _season(row) -> Optional[int]:
    """The season a row is about: Sonarr's number, or a transfer's "Season 01"."""
    keys = row.keys()
    if 'season_number' in keys and isinstance(row['season_number'], int):
        return row['season_number']
    for key in ('parsed_season', 'season_name'):
        if key in keys and row[key]:
            digits = re.search(r'\d+', str(row[key]))
            if digits:
                return int(digits.group())
    return None


def _row(row, kind: str) -> Dict[str, Any]:
    return {
        'kind': kind,
        'at': row['created_at'],
        'status': row['status'] or '',
        'held': bool(row['requires_manual_sync']) if 'requires_manual_sync' in row.keys() else False,
        'reason': (row['manual_sync_reason'] or '') if 'manual_sync_reason' in row.keys() else '',
        'season': _season(row),
        'transfer_status': row['transfer_status'] or '',
        'percent': row['progress_percent'],
        'eta_seconds': row['eta_seconds'],
    }


def arrivals_for(db_manager, media_type: str, *, tvdb_id: Optional[int],
                 tmdb_id: Optional[int], since: Optional[str]) -> List[Dict[str, Any]]:
    """Arrivals and syncs of one title since `since` (SQLite UTC), oldest first."""
    since = since or '1970-01-01 00:00:00'
    found: List[Dict[str, Any]] = []
    try:
        with db_manager.get_connection() as conn:
            if media_type == 'tv' and tvdb_id:
                rows = conn.execute('''
                    SELECT w.created_at, w.status, w.requires_manual_sync, w.manual_sync_reason,
                           w.season_number, t.status AS transfer_status,
                           t.progress_percent, t.eta_seconds
                      FROM sonarr_webhook w
                      LEFT JOIN transfers t ON t.transfer_id = w.transfer_id
                     WHERE w.tvdb_id = ? AND w.created_at >= ?
                       AND COALESCE(w.is_simulation, 0) = 0
                     ORDER BY w.created_at
                ''', (int(tvdb_id), since)).fetchall()
                found.extend(_row(r, 'arrival') for r in rows)
                source, external = 'sonarr', str(int(tvdb_id))
            elif media_type == 'movie' and tmdb_id:
                rows = conn.execute('''
                    SELECT w.created_at, w.status, w.requires_manual_sync, w.manual_sync_reason,
                           NULL AS season_number, t.status AS transfer_status,
                           t.progress_percent, t.eta_seconds
                      FROM radarr_webhook w
                      LEFT JOIN transfers t ON t.transfer_id = w.transfer_id
                     WHERE w.tmdb_id = ? AND w.created_at >= ?
                       AND COALESCE(w.is_simulation, 0) = 0
                     ORDER BY w.created_at
                ''', (int(tmdb_id), since)).fetchall()
                found.extend(_row(r, 'arrival') for r in rows)
                source, external = 'radarr', str(int(tmdb_id))
            else:
                return []
            # Syncs started by hand or from Explore carry no webhook, but the
            # title index still ties them to the title.
            placeholders = ', '.join('?' for _ in _NOT_A_SYNC)
            rows = conn.execute(f'''
                SELECT t.created_at, t.status AS status, 0 AS requires_manual_sync,
                       '' AS manual_sync_reason, NULL AS season_number,
                       t.parsed_season, t.season_name,
                       t.status AS transfer_status, t.progress_percent, t.eta_seconds
                  FROM transfers t
                  JOIN media_item m ON m.id = t.media_item_id
                 WHERE m.source = ? AND m.external_id = ? AND t.created_at >= ?
                   AND t.operation_type NOT IN ({placeholders})
                   AND COALESCE(t.is_simulation, 0) = 0
                   AND t.transfer_id NOT IN (
                       SELECT transfer_id FROM sonarr_webhook WHERE transfer_id IS NOT NULL
                       UNION SELECT transfer_id FROM radarr_webhook WHERE transfer_id IS NOT NULL)
                 ORDER BY t.created_at
            ''', (source, external, since, *_NOT_A_SYNC)).fetchall()
            found.extend(_row(r, 'transfer') for r in rows)
    except Exception:  # noqa: BLE001 - an unreadable history reads as "nothing yet"
        return []
    found.sort(key=lambda a: a['at'] or '')
    return found
