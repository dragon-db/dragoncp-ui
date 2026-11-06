#!/usr/bin/env python3
"""
Seerr: requests, where approved ones have got to, and issues.

Reads need a sign-in. Changes need a sign-in and pass the service's guard (a
test instance refuses them unless allowed). The webhook receiver is the one
address without a sign-in: Seerr cannot sign in, so it sends the webhook
password set on both sides instead.
"""

import logging

from flask import Blueprint, jsonify, request

from auth import require_auth

seerr_bp = Blueprint('seerr', __name__)
logger = logging.getLogger('dragoncp.routes.seerr')

_service = None


def init_seerr_routes(service):
    global _service
    _service = service


def _refuse(error: str, status: int):
    """A refusal in the app's shape: `message` for the shared error helper,
    `error` for the library panels, both the same sentence."""
    return jsonify({'success': False, 'error': error, 'message': error}), status


def _unavailable():
    return _refuse('Seerr is not available', 503)


def _paging(default_take: int = 20):
    try:
        take = max(1, min(100, int(request.args.get('take', default_take))))
        skip = max(0, int(request.args.get('skip', 0)))
    except (TypeError, ValueError):
        return None
    return take, skip


def _user_arg(name: str):
    value = str(request.args.get(name, '') or '').strip()
    return int(value) if value.isdigit() else None


def _result(result):
    if result.get('ok'):
        return jsonify({'success': True, **{k: v for k, v in result.items() if k != 'ok'}})
    return _refuse(result.get('error') or 'Seerr did not do it', int(result.get('status') or 400))


@seerr_bp.route('/seerr/summary')
@require_auth
def api_summary():
    """Counts for the tabs and the sidebar, and whether changes are allowed here."""
    if _service is None:
        return _unavailable()
    return jsonify({'success': True, **_service.summary()})


@seerr_bp.route('/seerr/requests')
@require_auth
def api_requests():
    if _service is None:
        return _unavailable()
    paging = _paging()
    if paging is None:
        return _refuse('take and skip must be numbers', 400)
    take, skip = paging
    try:
        page = _service.requests(
            view=str(request.args.get('view', 'waiting')), take=take, skip=skip,
            sort=str(request.args.get('sort', 'added')),
            media_type=str(request.args.get('type', 'all')),
            requested_by=_user_arg('user'))
    except Exception:  # noqa: BLE001 - the page must say something, not 500
        logger.exception('Reading Seerr requests failed')
        return _refuse('Could not read the requests', 500)
    return jsonify({'success': True, **page})


@seerr_bp.route('/seerr/requests/<int:request_id>')
@require_auth
def api_request(request_id):
    if _service is None:
        return _unavailable()
    return _result(_service.request(request_id))


@seerr_bp.route('/seerr/requests/<int:request_id>/options')
@require_auth
def api_request_options(request_id):
    """What can be changed before approving. Asks Sonarr or Radarr through Seerr."""
    if _service is None:
        return _unavailable()
    server = _user_arg('server')
    return _result(_service.request_options(request_id, server_id=server))


@seerr_bp.route('/seerr/requests/<int:request_id>/<decision>', methods=['POST'])
@require_auth
def api_request_decide(request_id, decision):
    if _service is None:
        return _unavailable()
    if decision not in ('approve', 'decline', 'retry'):
        return _refuse('Unknown action', 404)
    body = request.get_json(silent=True) or {}
    changes = body.get('changes') if isinstance(body, dict) else None
    return _result(_service.decide(request_id, decision, changes=changes or None))


@seerr_bp.route('/seerr/issues')
@require_auth
def api_issues():
    if _service is None:
        return _unavailable()
    paging = _paging()
    if paging is None:
        return _refuse('take and skip must be numbers', 400)
    take, skip = paging
    try:
        page = _service.issues(view=str(request.args.get('view', 'open')), take=take, skip=skip,
                               sort=str(request.args.get('sort', 'added')),
                               created_by=_user_arg('user'))
    except Exception:  # noqa: BLE001
        logger.exception('Reading Seerr issues failed')
        return _refuse('Could not read the issues', 500)
    return jsonify({'success': True, **page})


@seerr_bp.route('/seerr/issues/<int:issue_id>')
@require_auth
def api_issue(issue_id):
    if _service is None:
        return _unavailable()
    return _result(_service.issue(issue_id))


@seerr_bp.route('/seerr/issues/<int:issue_id>/comment', methods=['POST'])
@require_auth
def api_issue_comment(issue_id):
    if _service is None:
        return _unavailable()
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return _refuse('Send a JSON object', 400)
    return _result(_service.reply(issue_id, str(body.get('message') or ''),
                                  resolve=bool(body.get('resolve'))))


@seerr_bp.route('/seerr/issues/<int:issue_id>/<state>', methods=['POST'])
@require_auth
def api_issue_state(issue_id, state):
    if _service is None:
        return _unavailable()
    target = {'resolve': 'resolved', 'reopen': 'open'}.get(state)
    if target is None:
        return _refuse('Unknown action', 404)
    return _result(_service.set_issue(issue_id, target))


@seerr_bp.route('/seerr/users')
@require_auth
def api_users():
    if _service is None:
        return _unavailable()
    return jsonify({'success': True, 'users': _service.users()})


@seerr_bp.route('/webhook/seerr', methods=['POST'])
def api_webhook():
    """Seerr saying a request or issue changed. Guarded by the webhook password."""
    if _service is None:
        return _unavailable()
    status, body = _service.webhook(request.headers.get('Authorization', ''),
                                    request.get_json(silent=True))
    if status != 200:
        logger.warning('Seerr webhook refused (%s) from %s', status, request.remote_addr)
    return jsonify({'success': status == 200, **body}), status
