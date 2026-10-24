#!/usr/bin/env python3
"""
Renames from Explore (TASK-028).

Every endpoint requires a session. The client never names a file to rename:
the server builds the plan from the disk and Sonarr, and a rename quotes back
the path and new name the preview showed, so only names the server itself
proposed can be applied. Folder and season names are validated as single path
components before use, and every constructed path is checked against the
library root.

Nothing here reads Sonarr on a page view. A preview or a rename reads one
series; a title check reads one list per series with a TBA episode.
"""

import threading
from functools import wraps

from flask import Blueprint, g, jsonify, request

from activity_log import record
from auth import require_auth
from services.renames.service import RenamesError, RenamesService

renames_bp = Blueprint('renames', __name__)

renames_service: RenamesService = None


def init_renames_routes(service: RenamesService):
    global renames_service
    renames_service = service


def handled(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if renames_service is None:
            return jsonify({'status': 'error', 'message': 'Renames are not ready'}), 503
        try:
            return f(*args, **kwargs)
        except RenamesError as error:
            return jsonify({'status': 'error', 'message': error.message}), error.status
        except Exception as error:  # noqa: BLE001 - surface, do not swallow
            import traceback
            traceback.print_exc()
            return jsonify({'status': 'error', 'message': str(error)}), 500
    return wrapper


def _actor() -> str:
    return getattr(g, 'current_user', None) or ''


# --- one series ------------------------------------------------------------

@renames_bp.route('/explore/rename/<media_type>/<path:folder>')
@require_auth
@handled
def api_rename_plan(media_type, folder):
    """What renaming here would do. Changes nothing."""
    season = request.args.get('season') or None
    return jsonify({'status': 'success',
                    'plan': renames_service.plan(media_type, folder, season)})


@renames_bp.route('/explore/rename/<media_type>/<path:folder>', methods=['POST'])
@require_auth
@handled
def api_rename_apply(media_type, folder):
    data = request.get_json(silent=True) or {}
    season = data.get('season') or None
    picks = data.get('picks')
    if picks is not None and not isinstance(picks, list):
        return jsonify({'status': 'error', 'message': 'picks must be a list'}), 400
    result = renames_service.apply(media_type, folder, season, picks, actor=_actor())
    rehearsal = result['dry_run']
    record('explore.rename',
           f"{'Rehearsed a rename in test mode: would rename' if rehearsal else 'Renamed'} "
           f"{result['success_count']} file(s) in {folder}"
           + (f"; {result['sonarr']['message']}" if result['sonarr'].get('message') else ''),
           target_type='rename', target_id=result['notification_id'], target_label=folder)
    # The run's own status (completed, partial, failed) travels as run_status;
    # `status` is the request's, as on every other endpoint.
    return jsonify({**result, 'run_status': result['status'], 'status': 'success'})


@renames_bp.route('/explore/titles/refresh/<media_type>/<path:folder>', methods=['POST'])
@require_auth
@handled
def api_titles_refresh(media_type, folder):
    """Ask Sonarr to fetch fresh titles for this series, then check again."""
    result = renames_service.refresh(media_type, folder)
    if result.get('asked_sonarr'):
        record('explore.refresh_titles', f"Asked Sonarr to refresh the titles of {folder}",
               target_type='series', target_label=folder)
    return jsonify({'status': 'success', **result})


# --- the title check ---------------------------------------------------------

@renames_bp.route('/explore/titles/<media_type>')
@require_auth
@handled
def api_titles(media_type):
    """The last title check of every series in one library. Asks nothing."""
    return jsonify({'status': 'success', 'media_type': media_type,
                    'titles': renames_service.library_status(media_type)})


@renames_bp.route('/explore/titles/<media_type>/<path:folder>')
@require_auth
@handled
def api_titles_season(media_type, folder):
    """What the last check proposed for each file of one series or season."""
    season = request.args.get('season') or None
    return jsonify({'status': 'success',
                    'files': renames_service.season_titles(media_type, folder, season)})


@renames_bp.route('/explore/titles/check', methods=['POST'])
@require_auth
@handled
def api_titles_check():
    """Check one series now, or every library in the background."""
    data = request.get_json(silent=True) or {}
    media_type = data.get('media_type')
    folder = data.get('folder')
    if folder:
        summary = renames_service.check_folder(media_type or '', folder)
        return jsonify({'status': 'success', 'summary': summary})
    threading.Thread(target=renames_service.check_all, kwargs={'trigger': 'manual'},
                     daemon=True, name='title-check').start()
    record('explore.check_titles', 'Started a title check of the TV and anime libraries')
    return jsonify({'status': 'success', 'started': True}), 202


# --- the whole library -------------------------------------------------------

@renames_bp.route('/explore/rename-all/<media_type>')
@require_auth
@handled
def api_rename_all_plan(media_type):
    return jsonify({'status': 'success', 'plan': renames_service.plan_library(media_type)})


@renames_bp.route('/explore/rename-all/<media_type>', methods=['POST'])
@require_auth
@handled
def api_rename_all_apply(media_type):
    data = request.get_json(silent=True) or {}
    folders = data.get('folders')
    if not isinstance(folders, list):
        return jsonify({'status': 'error', 'message': 'folders must be a list'}), 400
    result = renames_service.apply_library(media_type, folders, actor=_actor())
    record('explore.rename_all', f"Started renaming the ready episodes of {len(folders)} series",
           target_type='library', target_id=media_type)
    return jsonify({'status': 'success', **result}), 202


# --- TMDB, for series Sonarr does not have -----------------------------------

@renames_bp.route('/explore/tmdb/search/<media_type>/<path:folder>')
@require_auth
@handled
def api_tmdb_search(media_type, folder):
    return jsonify({'status': 'success',
                    **renames_service.tmdb_search(media_type, folder, request.args.get('q'))})


@renames_bp.route('/explore/tmdb/link/<media_type>/<path:folder>', methods=['POST'])
@require_auth
@handled
def api_tmdb_link(media_type, folder):
    data = request.get_json(silent=True) or {}
    result = renames_service.tmdb_link(media_type, folder, data.get('tmdb_id'), actor=_actor())
    linked = result.get('linked') or {}
    record('explore.tmdb_link', f"Linked {folder} to {linked.get('tmdb_name') or 'a TMDB show'}",
           target_type='series', target_label=folder)
    return jsonify({'status': 'success', **result})


@renames_bp.route('/explore/tmdb/link/<media_type>/<path:folder>', methods=['DELETE'])
@require_auth
@handled
def api_tmdb_unlink(media_type, folder):
    result = renames_service.tmdb_unlink(media_type, folder)
    record('explore.tmdb_unlink', f"Removed the TMDB link of {folder}",
           target_type='series', target_label=folder)
    return jsonify({'status': 'success', **result})


# --- Undo --------------------------------------------------------------------

@renames_bp.route('/webhook/rename/notifications/<notification_id>/undo', methods=['POST'])
@require_auth
@handled
def api_rename_undo(notification_id):
    result = renames_service.undo(notification_id, actor=_actor())
    record('rename.undo', result['message'], target_type='rename', target_id=notification_id)
    return jsonify({'status': 'success', **result})
