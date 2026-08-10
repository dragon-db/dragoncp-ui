#!/usr/bin/env python3
"""
DragonCP Explore routes

Every endpoint requires a valid session (`@require_auth`). Beyond that:

*   Path components from the URL or body are validated with
    `validate_path_component` before they are used, and the service re-checks
    every constructed destination against the configured local library.
*   The client never describes work. It asks for a plan, the server computes and
    stores it, and execution quotes the plan's id. A destructive plan that
    failed its checks additionally needs an explicit typed confirmation.
*   Comparison endpoints do real work on the media server, so they are rate
    limited per user — the rest of the app has no rate limiting at all and a
    held-down refresh key would otherwise keep the remote busy.
*   Failures return real status codes (400/404/409/422/502) so the UI can tell
    "no session" from "empty library", which the old browse endpoints could not.
"""

import time
from collections import defaultdict, deque
from functools import wraps

from flask import Blueprint, g, jsonify, request

from activity_log import record
from auth import require_auth
from services.explore.service import ExploreError, ExploreService

explore_bp = Blueprint('explore', __name__)

explore_service: ExploreService = None


def init_explore_routes(service: ExploreService):
    global explore_service
    explore_service = service


# --- rate limiting ---------------------------------------------------------
# Comparisons walk the whole remote library. A small allowance per user, with a
# sliding window, keeps an impatient refresh from turning into remote load.
_HITS = defaultdict(deque)
_WINDOW_SECONDS = 60
_MAX_COMPARISONS = 12


def rate_limited(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = getattr(g, 'current_user', None) or request.remote_addr or 'anonymous'
        now = time.time()
        hits = _HITS[user]
        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= _MAX_COMPARISONS:
            retry_after = int(_WINDOW_SECONDS - (now - hits[0])) + 1
            return jsonify({
                'status': 'error',
                'message': 'Too many library checks. Give the media server a moment.',
                'retry_after': retry_after,
            }), 429
        hits.append(now)
        return f(*args, **kwargs)
    return wrapper


def handled(f):
    """Turn an ExploreError into its intended status code."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if explore_service is None:
            return jsonify({'status': 'error', 'message': 'Explore is not ready'}), 503
        try:
            return f(*args, **kwargs)
        except ExploreError as error:
            return jsonify({'status': 'error', 'message': error.message}), error.status
        except Exception as error:  # noqa: BLE001 - surface, do not swallow
            import traceback
            traceback.print_exc()
            return jsonify({'status': 'error', 'message': str(error)}), 500
    return wrapper


# --- reads -----------------------------------------------------------------

@explore_bp.route('/explore/libraries')
@require_auth
@handled
def api_libraries():
    return jsonify({'status': 'success', 'libraries': explore_service.libraries()})


@explore_bp.route('/explore/tree/<media_type>')
@require_auth
@handled
def api_tree(media_type):
    refresh = request.args.get('refresh') == '1'
    if refresh:
        limited = rate_limited(lambda: None)()
        if limited is not None:
            return limited
    return jsonify({'status': 'success', **explore_service.tree(media_type, refresh=refresh)})


@explore_bp.route('/explore/series/<media_type>/<path:folder>')
@require_auth
@rate_limited
@handled
def api_series(media_type, folder):
    return jsonify({'status': 'success', 'series': explore_service.series(media_type, folder)})


@explore_bp.route('/explore/season/<media_type>/<folder>/<path:season>')
@require_auth
@rate_limited
@handled
def api_season(media_type, folder, season):
    return jsonify({
        'status': 'success',
        'season': explore_service.season(media_type, folder, season),
    })


@explore_bp.route('/explore/history/<media_type>/<path:folder>')
@require_auth
@handled
def api_history(media_type, folder):
    season = request.args.get('season') or None
    return jsonify({
        'status': 'success',
        'runs': explore_service.history(media_type, folder, season),
    })


@explore_bp.route('/explore/backups/<media_type>/<path:folder>')
@require_auth
@handled
def api_backups(media_type, folder):
    """Backed-up copies for this series or season. Restoring one goes through
    the Backups endpoints, which own the destination matching and the preview."""
    season = request.args.get('season') or None
    return jsonify({
        'status': 'success',
        'backups': explore_service.backups(media_type, folder, season),
    })


# --- repair ----------------------------------------------------------------

@explore_bp.route('/explore/repair/<media_type>/<path:folder>')
@require_auth
@handled
def api_repair_plan(media_type, folder):
    """What repairing the stranded files here would do. Moves nothing."""
    season = request.args.get('season') or None
    return jsonify({
        'status': 'success',
        'plan': explore_service.repair_plan(media_type, folder, season),
    })


@explore_bp.route('/explore/repair/<media_type>/<path:folder>', methods=['POST'])
@require_auth
@handled
def api_repair_apply(media_type, folder):
    """
    Lift the stranded files back to where they belong.

    The plan is rebuilt server-side from the disk as it is now, so a client
    cannot name a file to move. The body carries the scope and, for files whose
    place is already taken by another copy, which of the two to keep — a choice
    between two files the server itself found, not a path it will trust.
    """
    data = request.get_json(silent=True) or {}
    season = data.get('season') or None
    decisions = data.get('decisions')
    if decisions is not None and not isinstance(decisions, dict):
        return jsonify({'status': 'error', 'message': 'decisions must be an object'}), 400

    result = explore_service.repair_apply(media_type, folder, season, decisions)

    summary = f"Repaired {result['moved_count']} misplaced file(s)"
    if result['deleted_count']:
        summary += f", deleted {result['deleted_count']} redundant copy/copies"
    if result['replaced_count']:
        summary += f", replaced {result['replaced_count']}"
    record('explore.repair', f"{summary} in {result['scope']}",
           target_type='explore_repair', target_id=f"{media_type}/{folder}")
    return jsonify({'status': 'success', **result})


# --- planning and execution ------------------------------------------------

@explore_bp.route('/explore/plan', methods=['POST'])
@require_auth
@rate_limited
@handled
def api_plan():
    data = request.get_json(silent=True) or {}
    plan = explore_service.plan(
        media_type=data.get('media_type', ''),
        operation=data.get('operation', ''),
        folder=data.get('folder', ''),
        season_label=data.get('season'),
        codes=data.get('codes') or [],
        include_removals=bool(data.get('include_removals', True)),
        created_by=getattr(g, 'current_user', None),
        season_labels=data.get('seasons') or [],
    )
    return jsonify({'status': 'success', 'plan': plan})


@explore_bp.route('/explore/dry-run', methods=['POST'])
@require_auth
@rate_limited
@handled
def api_dry_run():
    """
    Rehearse a plan. Runs rsync with --dry-run and reports what it says.

    Rate limited with the comparisons: it opens an ssh connection and walks the
    same file list the real run would.
    """
    data = request.get_json(silent=True) or {}
    plan_id = data.get('plan_id')
    if not plan_id:
        return jsonify({'status': 'error', 'message': 'plan_id is required'}), 400
    return jsonify({'status': 'success', **explore_service.dry_run(plan_id)})


@explore_bp.route('/explore/transfer', methods=['POST'])
@require_auth
@handled
def api_execute():
    data = request.get_json(silent=True) or {}
    plan_id = data.get('plan_id')
    if not plan_id:
        return jsonify({'status': 'error', 'message': 'plan_id is required'}), 400

    result = explore_service.execute(
        plan_id,
        override=bool(data.get('override')),
        confirm_text=data.get('confirm_text'),
    )
    record('explore.transfer', 'Ran an approved Explore plan',
           target_type='explore_plan', target_id=plan_id)
    return jsonify({'status': 'success', **result})
