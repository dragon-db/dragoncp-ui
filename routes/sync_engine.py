#!/usr/bin/env python3
"""
The sync engine, the Notifications tab and the scheduler, over HTTP.

Everything an admin needs to see how a sync went — every run, its nine stages,
what each stage did and why, the log lines under each stage, the webhooks
linked to it and the transfer it became — and the few things an admin can do to
a run that has not finished: go now, cancel, go ahead despite the safety check.

The pipeline the interface draws comes from `/sync/catalogue`, which is the
same data the engine runs on, so the screen cannot describe a different
pipeline from the one that ran.
"""

import logging

from flask import Blueprint, jsonify, request

from activity_log import record, record_failure
from auth import require_auth
from services.alert_service import ACTION_LABELS, KINDS as ALERT_KINDS
from services.sync_engine import stages as S

sync_engine_bp = Blueprint('sync_engine', __name__)
log = logging.getLogger('dragoncp.routes.sync_engine')

MAX_PAGE_SIZE = 200

_coordinator = None

#: Named groups of states a list can be filtered by.
STATE_GROUPS = {
    'open': list(S.OPEN_STATES),
    'active': list(S.ACTIVE_STATES),
    'live': list(S.LIVE_STATES),
    'finished': list(S.TERMINAL_STATES),
}


def init_sync_engine_routes(coordinator):
    global _coordinator
    _coordinator = coordinator


def _engine():
    return getattr(_coordinator, 'sync_engine', None)


def _unavailable():
    return jsonify({'status': 'error', 'message': 'The sync engine is not running'}), 503


def _page():
    limit = max(1, min(request.args.get('limit', 50, type=int), MAX_PAGE_SIZE))
    offset = max(0, request.args.get('offset', 0, type=int))
    return limit, offset


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

@sync_engine_bp.route('/sync/catalogue')
@require_auth
def api_sync_catalogue():
    """The nine stages, every kind of sync and what it does at each stage."""
    catalogue = S.catalogue()
    catalogue['state_groups'] = STATE_GROUPS
    catalogue['alert_actions'] = ACTION_LABELS
    catalogue['alert_kinds'] = ALERT_KINDS
    return jsonify({'status': 'success', **catalogue})


@sync_engine_bp.route('/sync/runs')
@require_auth
def api_sync_runs():
    """Runs, newest first, each with its stage strip.

    `state` takes a state, or a group: open, active, live, finished, all.
    `kind` takes one kind or several, comma separated.
    `copied` is 1 for runs whose copy started and 0 for runs that ended, or
    are waiting, before it — the Transfers page lists the second kind beside
    its transfers, since those never get a transfer row of their own.
    """
    engine = _engine()
    if engine is None:
        return _unavailable()
    limit, offset = _page()
    state = (request.args.get('state') or 'all').strip()
    states = None
    if state in STATE_GROUPS:
        states = STATE_GROUPS[state]
    elif state and state != 'all':
        states = [s for s in state.split(',') if s]
    kinds = [k for k in (request.args.get('kind') or '').split(',') if k] or None
    search = (request.args.get('search') or request.args.get('q') or '').strip() or None
    include_simulation = request.args.get('simulations', '1') not in ('0', 'false', 'no')
    copied_arg = (request.args.get('copied') or '').strip().lower()
    copied = (True if copied_arg in ('1', 'true', 'yes') else
              False if copied_arg in ('0', 'false', 'no') else None)
    try:
        listing = engine.list_runs(states=states, kinds=kinds, search=search, limit=limit,
                                   offset=offset, include_simulation=include_simulation,
                                   copied=copied)
    except Exception as error:  # noqa: BLE001
        log.exception('Could not list sync runs')
        return jsonify({'status': 'error', 'message': str(error)}), 500
    return jsonify({'status': 'success', 'limit': limit, 'offset': offset, **listing})


@sync_engine_bp.route('/sync/runs/<run_id>')
@require_auth
def api_sync_run(run_id):
    """One run, stage by stage, with each stage's own log lines."""
    engine = _engine()
    if engine is None:
        return _unavailable()
    described = engine.describe_run(run_id)
    if described is None:
        return jsonify({'status': 'error', 'message': 'No such sync run'}), 404
    return jsonify({'status': 'success', 'run': described})


@sync_engine_bp.route('/sync/runs/<run_id>/events')
@require_auth
def api_sync_run_events(run_id):
    """Log lines after `after` — what a live view polls for between socket events."""
    engine = _engine()
    if engine is None:
        return _unavailable()
    if engine.store.get(run_id) is None:
        return jsonify({'status': 'error', 'message': 'No such sync run'}), 404
    after = max(0, request.args.get('after', 0, type=int))
    stage = request.args.get('stage')
    events = engine.store.events(run_id, after_id=after)
    if stage:
        events = [e for e in events if e['stage'] == stage]
    return jsonify({'status': 'success', 'events': events})


@sync_engine_bp.route('/sync/lookup')
@require_auth
def api_sync_lookup():
    """The run behind a transfer or a webhook, so any screen can link to it."""
    engine = _engine()
    if engine is None:
        return _unavailable()
    transfer_id = (request.args.get('transfer_id') or '').strip()
    notification_id = (request.args.get('notification_id') or '').strip()
    run = None
    if transfer_id:
        run = engine.store.by_transfer(transfer_id)
        if run is None:
            row = _coordinator.transfer_model.get(transfer_id)
            if row and row.get('sync_run_id'):
                run = engine.store.get(row['sync_run_id'])
    elif notification_id:
        _table, row = engine._find_webhook(notification_id)
        if row and row.get('sync_run_id'):
            run = engine.store.get(row['sync_run_id'])
    else:
        return jsonify({'status': 'error',
                        'message': 'Give a transfer_id or a notification_id'}), 400
    if run is None:
        return jsonify({'status': 'error', 'message': 'No sync run found'}), 404
    return jsonify({'status': 'success', 'run_id': run['run_id'],
                    'run': engine.summarise(run)})


def _act(run_id, action, fn, verb):
    engine = _engine()
    if engine is None:
        return _unavailable()
    run = engine.store.get(run_id)
    if run is None:
        return jsonify({'status': 'error', 'message': 'No such sync run'}), 404
    result = fn(run_id)
    label = run.get('title') or run.get('folder_name') or run_id
    if run.get('season_name'):
        label = f"{label} — {run['season_name']}"
    (record if result.ok else record_failure)(
        action, f"{verb} the sync of {label}",
        target_type='sync_run', target_id=run_id, target_label=label,
        detail={'result': result.message})
    return jsonify({'status': 'success' if result.ok else 'error', **result.as_dict()}), \
        (200 if result.ok else 409)


@sync_engine_bp.route('/sync/runs/<run_id>/go-now', methods=['POST'])
@require_auth
def api_sync_run_go_now(run_id):
    """A waiting batch — held for a person, or waiting on Sonarr — goes now."""
    return _act(run_id, 'sync.go_now', lambda r: _engine().go_now(r), 'Started now')


@sync_engine_bp.route('/sync/runs/<run_id>/cancel', methods=['POST'])
@require_auth
def api_sync_run_cancel(run_id):
    return _act(run_id, 'sync.cancel', lambda r: _engine().cancel_run(r), 'Cancelled')


@sync_engine_bp.route('/sync/runs/<run_id>/sync-anyway', methods=['POST'])
@require_auth
def api_sync_run_anyway(run_id):
    """Go ahead with a sync the safety check stopped. An admin's call, recorded."""
    return _act(run_id, 'sync.sync_anyway', lambda r: _engine().sync_anyway(r),
                'Went ahead despite the safety check with')


# ---------------------------------------------------------------------------
# The Notifications tab
# ---------------------------------------------------------------------------

def _alerts():
    return getattr(_coordinator, 'alerts', None)


@sync_engine_bp.route('/alerts')
@require_auth
def api_alerts():
    """Alerts, newest first. `state`: open (default), done, wrong, dismissed, several
    of them comma separated (the Closed tab asks for done,wrong,dismissed), or all."""
    alerts = _alerts()
    if alerts is None:
        return _unavailable()
    limit, offset = _page()
    state = (request.args.get('state') or 'open').strip()
    kinds = [k for k in (request.args.get('kind') or '').split(',') if k] or None
    return jsonify({'status': 'success', 'limit': limit, 'offset': offset,
                    **alerts.list(state=state, kinds=kinds, limit=limit, offset=offset)})


@sync_engine_bp.route('/alerts/summary')
@require_auth
def api_alerts_summary():
    """How many alerts are open — the badge on the tab."""
    alerts = _alerts()
    if alerts is None:
        return _unavailable()
    return jsonify({'status': 'success', **alerts.summary()})


@sync_engine_bp.route('/alerts/<alert_id>/action', methods=['POST'])
@require_auth
def api_alert_action(alert_id):
    """Act on an alert: sync_now, retry, sync_anyway, run_now, mark_done, mark_wrong, dismiss."""
    alerts = _alerts()
    if alerts is None:
        return _unavailable()
    payload = request.get_json(silent=True) or {}
    action = str(payload.get('action') or '').strip()
    if action not in ACTION_LABELS:
        return jsonify({'status': 'error', 'message': f"Unknown action {action!r}"}), 400
    ok, message, alert = alerts.act(alert_id, action)
    if alert is None and not ok:
        return jsonify({'status': 'error', 'message': message}), 404
    return jsonify({'status': 'success' if ok else 'error', 'message': message,
                    'alert': alert}), (200 if ok else 409)


# ---------------------------------------------------------------------------
# The scheduler
# ---------------------------------------------------------------------------

@sync_engine_bp.route('/scheduler/jobs')
@require_auth
def api_scheduler_jobs():
    scheduler = getattr(_coordinator, 'scheduler', None)
    if scheduler is None:
        return _unavailable()
    return jsonify({'status': 'success', 'jobs': scheduler.status()})


@sync_engine_bp.route('/scheduler/jobs/<name>/run', methods=['POST'])
@require_auth
def api_scheduler_run(name):
    scheduler = getattr(_coordinator, 'scheduler', None)
    if scheduler is None:
        return _unavailable()
    if name not in scheduler.jobs():
        return jsonify({'status': 'error', 'message': 'No such job'}), 404
    started = scheduler.run_now(name)
    (record if started else record_failure)(
        'scheduler.run_now', f"{'Ran' if started else 'Could not run'} the job {name} now",
        target_type='job', target_id=name)
    return jsonify({'status': 'success' if started else 'error',
                    'message': 'Started.' if started else 'That job is already running.',
                    'job': scheduler.job_status(name)}), (200 if started else 409)
