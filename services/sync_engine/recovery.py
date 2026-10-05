#!/usr/bin/env python3
"""
After a restart: find what was in flight, and say so.

Batches are written to the database as they change, so a restart forgets
nothing — but nothing restarts behind anyone's back either (decided
2026-10-02). What a restart interrupted becomes an alert in Notifications, and
an admin decides: Sync now, Mark as done, Mark as wrong, or Dismiss.

What carries on by itself, because it already did before the engine existed:
a transfer still in the queue (the queue restores its own state), and a copy
whose rsync survived the restart (DragonCP reattaches to it).
"""

import logging
from collections import OrderedDict
from datetime import timedelta
from typing import Any, Dict, List

from models.sync_run import SERIES_TABLE, utc_now, utc_now_iso
from services.sync_engine import stages as S
from services.sync_engine.units import IdentifyError, from_series_notification

log = logging.getLogger('dragoncp.sync_engine.recovery')

#: How far back a stranded webhook from before the engine existed is looked
#: for. Older than this, it is history rather than unfinished work.
LOOKBACK_DAYS = 7

RESTART_REASON = 'DragonCP restarted before this was synced'


def recover_after_restart(engine) -> Dict[str, int]:
    """Look at every unfinished run once, at start-up. Returns what it found."""
    found = {'interrupted': 0, 'still_queued': 0, 'reattached': 0,
             'finished_while_down': 0, 'legacy_alerts': 0}
    store = engine.store

    for run in store.in_states([S.WAITING_STATE, S.CHECKING]):
        _interrupt(engine, run)
        found['interrupted'] += 1

    requeue = False
    for run in store.in_states([S.QUEUED]):
        transfer = _transfer(engine, run.get('transfer_id'))
        status = (transfer or {}).get('status')
        if status == 'queued':
            engine._event(run['run_id'], S.QUEUE,
                          'DragonCP restarted. This is still in the queue and carries on '
                          'by itself.')
            found['still_queued'] += 1
        elif status == 'pending':
            _back_in_queue(engine, run)
            requeue = True
            found['still_queued'] += 1
        elif status in ('running',):
            found['reattached'] += 1
        elif status in ('completed', 'failed', 'cancelled'):
            engine.on_transfer_finished(run['transfer_id'], status)
            found['finished_while_down'] += 1
        else:
            _interrupt(engine, run)
            found['interrupted'] += 1

    for run in store.in_states([S.TRANSFERRING, S.FINISHING]):
        transfer = _transfer(engine, run.get('transfer_id'))
        status = (transfer or {}).get('status')
        if status in ('queued', 'pending'):
            # Not copying after all: back in the queue, which carries it on.
            if status == 'pending':
                _back_in_queue(engine, run)
                requeue = True
            else:
                engine._event(run['run_id'], S.QUEUE,
                              'DragonCP restarted. This is still in the queue and carries '
                              'on by itself.')
            engine._set_state(run['run_id'], S.QUEUED, S.QUEUE)
            found['still_queued'] += 1
        elif status == 'running':
            engine._event(run['run_id'], S.TRANSFER,
                          'DragonCP restarted while this was copying. rsync was still '
                          'running, so DragonCP is watching it again.', 'warning')
            found['reattached'] += 1
        elif status in ('completed', 'failed', 'cancelled'):
            engine.on_transfer_finished(run['transfer_id'], status)
            found['finished_while_down'] += 1
        elif status == 'paused':
            engine._set_state(run['run_id'], S.PAUSED, S.TRANSFER)
        else:
            _interrupt(engine, run)
            found['interrupted'] += 1

    if requeue and engine.coordinator is not None:
        try:
            # Rebuilt without starting anything: the coordinator promotes once
            # recovery is over, so what starts goes through the engine's hooks.
            engine.coordinator.queue_manager.force_unregister_stale_transfers(promote=False)
        except Exception:  # noqa: BLE001
            log.exception('Could not rebuild the queue after recovery')

    found['legacy_alerts'] = _legacy_webhooks(engine)
    if any(found.values()):
        log.info('Sync engine recovery: %s', found)
    return found


def _back_in_queue(engine, run: Dict[str, Any]) -> None:
    """A transfer that was about to start when DragonCP stopped.

    A pending row belongs to neither the running set nor the queue, so it would
    sit there forever; putting it back in the queue lets it start normally.
    """
    engine.coordinator.transfer_model.update(run['transfer_id'], {
        'status': 'queued', 'queue_reason': 'slot',
        'progress': 'Back in the queue after a restart'})
    engine._event(run['run_id'], S.QUEUE,
                  'DragonCP restarted just as this was starting; it went back into the queue.')


def _transfer(engine, transfer_id):
    if not transfer_id or engine.coordinator is None:
        return None
    try:
        return engine.coordinator.transfer_model.get(transfer_id)
    except Exception:  # noqa: BLE001
        return None


def _interrupt(engine, run: Dict[str, Any]) -> None:
    run_id = run['run_id']
    stage = run.get('current_stage') or S.READY
    doing = {
        S.WAITING_STATE: 'waiting for the download',
        S.CHECKING: 'running the safety check',
        S.QUEUED: 'waiting in the queue',
        S.TRANSFERRING: 'copying',
        S.FINISHING: 'finishing',
    }.get(run['state'], 'working')
    engine._stage(run_id, stage, S.FAILED,
                  f"DragonCP restarted while this was {doing}. Nothing restarts by "
                  f"itself — see the alert in Notifications.", level='warning')
    engine._skip_rest(run_id, stage, 'Not reached: DragonCP restarted.')
    engine.store.update_webhooks(
        run_id, {'status': 'pending', 'requires_manual_sync': 1,
                 'manual_sync_reason': RESTART_REASON},
        exclude_status=('completed',))
    engine._set_state(run_id, S.INTERRUPTED, stage, outcome='interrupted',
                      outcome_message=f"DragonCP restarted while this was {doing}")
    if engine.alerts is not None:
        label = run.get('title') or run.get('folder_name') or 'A sync'
        if run.get('season_name'):
            label = f"{label} — {run['season_name']}"
        engine.alerts.restart_unfinished(
            run.get('unit_key') or run_id, label, engine.store.webhook_ids(run_id),
            run_id=run_id)


def _legacy_webhooks(engine) -> int:
    """Webhooks the old in-memory scheduler had taken and a restart dropped."""
    since = (utc_now() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    try:
        rows = engine.store.stranded_auto_sync_webhooks(since)
    except Exception:  # noqa: BLE001
        log.exception('Could not look for stranded webhooks')
        return 0
    # Only the rows nothing owns: rows on an interrupted run were handled above.
    rows = [r for r in rows if not r.get('sync_run_id')]
    if not rows:
        return 0

    groups: 'OrderedDict[str, Dict[str, Any]]' = OrderedDict()
    path_service = engine._path_service()
    for row in rows:
        key, label = None, row.get('series_title') or 'A series'
        if path_service is not None:
            try:
                unit = from_series_notification(row, path_service)
                key, label = unit.unit_key, unit.label
            except IdentifyError:
                key = None
        key = key or f"{row.get('series_title')}:{row.get('season_number')}"
        group = groups.setdefault(key, {'label': label, 'ids': []})
        group['ids'].append(row['notification_id'])

    for key, group in groups.items():
        if engine.alerts is not None:
            engine.alerts.restart_unfinished(key, group['label'], group['ids'])
        with engine.store.db.get_connection() as conn:
            conn.execute(
                f"UPDATE {SERIES_TABLE} SET requires_manual_sync = 1, "
                f"manual_sync_reason = ?, updated_at = ? WHERE notification_id IN "
                f"({', '.join('?' for _ in group['ids'])})",
                (RESTART_REASON, utc_now_iso(), *group['ids']))
            conn.commit()
    return len(groups)
