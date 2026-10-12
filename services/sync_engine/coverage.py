#!/usr/bin/env python3
"""
When each folder was last copied: the one rule the auto-scanner and the
Library tabs share, so "nothing has synced it since" means the same in both.

A copy counts from when it started, because that is when rsync listed the
folder: an episode imported after the start may not be in the copy, even
though the copy finished after it. A copy that was paused and resumed listed
the folder again, so its latest start counts.

What never counts: a simulation (it copies nothing), a restore (it copies from
a backup, not from the service), a single file (one file is not the season),
and Explore's removals-only plan (nothing was downloaded). A transfer from
before the sync engine has only its own row, so it counts from that row's
start; a transfer the engine owns counts through its run, never through the
transfer row's times.
"""

import json
from datetime import datetime, timezone
from typing import Dict, Optional

from services.sync_engine.units import unit_key

#: Copies that say nothing about whether the rest of the folder is here.
NARROW_COPIES = ('file', 'restore', 'explore_prune')


def last_copies(db, key: Optional[str] = None) -> Dict[str, datetime]:
    """When each destination folder's latest finished copy started, by unit key.

    `key` limits the answer to one folder. Moments are aware, in UTC.
    """
    latest: Dict[str, datetime] = {}

    def keep(folder: str, moment: Optional[datetime]) -> None:
        if folder and moment and (folder not in latest or moment > latest[folder]):
            latest[folder] = moment

    narrow = ', '.join('?' for _ in NARROW_COPIES)
    with db.get_connection() as conn:
        runs = conn.execute(
            "SELECT unit_key, started_at, options FROM sync_run "
            " WHERE state = 'completed' AND COALESCE(is_simulation, 0) = 0 "
            "   AND started_at IS NOT NULL AND COALESCE(unit_key, '') != '' "
            f"  AND COALESCE(operation_type, 'folder') NOT IN ({narrow})"
            + (" AND unit_key = ?" if key else ""),
            (*NARROW_COPIES, *((key,) if key else ())))
        for row in runs:
            keep(row['unit_key'],
                 _utc(_options(row['options']).get('transfer_started_at')
                      or row['started_at']))

        legacy = conn.execute(
            "SELECT dest_path, MAX(start_time) AS at FROM transfers "
            " WHERE status = 'completed' AND start_time IS NOT NULL "
            "   AND COALESCE(sync_run_id, '') = '' AND COALESCE(is_simulation, 0) = 0 "
            f"  AND COALESCE(operation_type, 'folder') NOT IN ({narrow})"
            + (" AND dest_path IN (?, ?)" if key else "")
            + " GROUP BY dest_path",
            (*NARROW_COPIES, *((key, key + '/') if key else ())))
        for row in legacy:
            keep(unit_key(row['dest_path'] or ''), _local(row['at']))
    return latest


def _options(value) -> Dict:
    try:
        loaded = json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _utc(value) -> Optional[datetime]:
    """A run's timestamp: ISO, in UTC when it says no zone."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _local(value) -> Optional[datetime]:
    """A transfers-table timestamp: this machine's local time, with no zone."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(timezone.utc)
