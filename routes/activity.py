#!/usr/bin/env python3
"""
DragonCP Activity Routes
Reading the record of who did what.

Read-only by design. Nothing here writes to the trail and nothing edits or
removes an entry — an audit record you can alter from the same console it
audits is not worth keeping. Entries age out only if someone prunes the table
on the server.
"""

from flask import Blueprint, jsonify, request

from auth import require_auth
from models.activity import ACTIONS

activity_bp = Blueprint('activity', __name__)

# Set by app.py
activity_model = None

MAX_PAGE_SIZE = 200


def init_activity_routes(model):
    global activity_model
    activity_model = model


def _fail(message: str, code: int = 400):
    return jsonify({'status': 'error', 'message': message}), code


def _actions(raw):
    """
    The `action` parameter, which may name one action or several.

    Several is what a screen filtering to "everything that removed a backup"
    needs: four separate actions do that and no prefix groups them. Returned as
    a list so the model builds one `IN` clause, keeping the total and the paging
    honest — a client-side filter would page over rows it then discards.
    """
    if not raw:
        return None
    wanted = [part.strip() for part in str(raw).split(',') if part.strip()]
    if not wanted:
        return None
    return wanted[0] if len(wanted) == 1 else wanted


@activity_bp.route('/activity')
@require_auth
def api_activity():
    """
    The activity trail, newest first.

    Filters, all optional and combined with AND:
      actor        a username, or an automation name such as 'auto-sync'
      actor_kind   admin | automated | system
      account_id   the stable account id, which survives a rename
      action       an exact action, e.g. 'backup.restore', or several separated
                   by commas meaning any of them
      group        an action family, e.g. 'backup'
      target_type  transfer | backup_capture | notification | setting | account
      target_id    one specific thing
      outcome      ok | failed | refused
      since/until  ISO timestamps
      search       matches the summary, the thing acted on, or the actor
      limit/offset paging
    """
    if activity_model is None:
        return _fail('Activity is not available', 503)

    try:
        limit = max(1, min(request.args.get('limit', 50, type=int) or 50, MAX_PAGE_SIZE))
        offset = max(request.args.get('offset', 0, type=int) or 0, 0)

        result = activity_model.query(
            actor_account_id=request.args.get('account_id', type=int),
            actor_name=request.args.get('actor') or None,
            actor_kind=request.args.get('actor_kind') or None,
            action=_actions(request.args.get('action')),
            action_group=request.args.get('group') or None,
            target_type=request.args.get('target_type') or None,
            target_id=request.args.get('target_id') or None,
            outcome=request.args.get('outcome') or None,
            since=request.args.get('since') or None,
            until=request.args.get('until') or None,
            search=request.args.get('search') or None,
            limit=limit,
            offset=offset,
        )
        return jsonify({'status': 'success', **result})
    except ValueError as error:
        return _fail(str(error), 400)
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error reading the activity trail: {error}")
        return _fail(f'Failed to read activity: {error}', 500)


@activity_bp.route('/activity/for/<target_type>/<path:target_id>')
@require_auth
def api_activity_for_target(target_type, target_id):
    """Everything recorded against one thing, oldest first — its story."""
    if activity_model is None:
        return _fail('Activity is not available', 503)

    try:
        return jsonify({
            'status': 'success',
            'entries': activity_model.for_target(target_type, target_id),
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to read activity: {error}', 500)


@activity_bp.route('/activity/filters')
@require_auth
def api_activity_filters():
    """
    What the activity screen can filter by.

    Actors come from the trail rather than the account table, so somebody whose
    account has since been disabled still appears — which is the entire reason
    accounts are disabled rather than deleted.
    """
    if activity_model is None:
        return _fail('Activity is not available', 503)

    try:
        return jsonify({
            'status': 'success',
            'actors': activity_model.actors_seen(),
            'actions': [
                {'action': action, 'label': label, 'group': action.split('.')[0]}
                for action, label in sorted(ACTIONS.items())
            ],
            'total': activity_model.count(),
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to read activity filters: {error}', 500)
