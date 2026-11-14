#!/usr/bin/env python3
"""
Prowlarr: search every indexer, see which are healthy, send a release on.

Everything needs a sign-in. Sending a release passes the service's guard (a
test instance refuses it unless allowed). A release is named by its search
and its place in it; its download address and guid stay on the server.
"""

import logging
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request

from auth import require_auth

prowlarr_bp = Blueprint('prowlarr', __name__)
logger = logging.getLogger('dragoncp.routes.prowlarr')

_service = None


def init_prowlarr_routes(service):
    global _service
    _service = service


def _refuse(error: str, status: int):
    """A refusal in the app's shape: `message` for the shared error helper,
    `error` for the panels, both the same sentence."""
    return jsonify({'success': False, 'error': error, 'message': error}), status


def _unavailable():
    return _refuse('Prowlarr is not available', 503)


def _result(result):
    if result.get('ok'):
        return jsonify({'success': True, **{k: v for k, v in result.items() if k != 'ok'}})
    return _refuse(result.get('error') or 'Prowlarr did not do it', int(result.get('status') or 400))


@prowlarr_bp.route('/prowlarr/overview')
@require_auth
def api_overview():
    """Indexers and their health, Prowlarr's warnings, the download clients."""
    if _service is None:
        return _unavailable()
    try:
        overview = _service.overview(fresh=request.args.get('fresh') == '1')
    except Exception:  # noqa: BLE001 - the page must say something, not 500
        logger.exception('Reading Prowlarr failed')
        return _refuse('Could not read Prowlarr', 500)
    return jsonify({'success': True, **overview})


@prowlarr_bp.route('/prowlarr/indexers/<int:indexer_id>/test', methods=['POST'])
@require_auth
def api_test_indexer(indexer_id):
    if _service is None:
        return _unavailable()
    return _result(_service.test_indexer(indexer_id))


@prowlarr_bp.route('/prowlarr/search', methods=['POST'])
@require_auth
def api_search():
    """Start a search. Its results are read back from the address below."""
    if _service is None:
        return _unavailable()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _refuse('Send a JSON object', 400)
    return _result(_service.start_search(body))


@prowlarr_bp.route('/prowlarr/search/<search_id>')
@require_auth
def api_search_poll(search_id):
    if _service is None:
        return _unavailable()
    try:
        cursor = int(request.args.get('cursor', 0))
    except (TypeError, ValueError):
        return _refuse('cursor must be a number', 400)
    search = _service.poll(search_id, cursor)
    if search is None:
        return _refuse('This search has expired. Search again.', 410)
    return jsonify({'success': True, 'search': search})


@prowlarr_bp.route('/prowlarr/search/<search_id>/releases/<int:release_id>/grab', methods=['POST'])
@require_auth
def api_grab(search_id, release_id):
    if _service is None:
        return _unavailable()
    body = request.get_json(silent=True) or {}
    client = body.get('download_client_id') if isinstance(body, dict) else None
    try:
        client = int(client) if client not in (None, '') else None
    except (TypeError, ValueError):
        return _refuse('download_client_id must be a number', 400)
    return _result(_service.grab(search_id, release_id, client))


@prowlarr_bp.route('/prowlarr/search/<search_id>/releases/<int:release_id>/route')
@require_auth
def api_route(search_id, release_id):
    """Where the release lands, whether Sonarr or Radarr imports it, and after
    a send where it is now. Reads only."""
    if _service is None:
        return _unavailable()
    return _result(_service.release_route(search_id, release_id))


@prowlarr_bp.route('/prowlarr/search/<search_id>/releases/<int:release_id>/magnet')
@require_auth
def api_magnet(search_id, release_id):
    if _service is None:
        return _unavailable()
    return _result(_service.magnet(search_id, release_id))


@prowlarr_bp.route('/prowlarr/search/<search_id>/releases/<int:release_id>/file')
@require_auth
def api_file(search_id, release_id):
    """The .torrent or .nzb. A release whose file is a magnet link answers with it as JSON."""
    if _service is None:
        return _unavailable()
    result = _service.release_file(search_id, release_id)
    if not result.get('ok'):
        return _result(result)
    if result.get('magnet'):
        return jsonify({'success': True, 'magnet': result['magnet']})
    filename = result['filename']
    ascii_name = filename.encode('ascii', 'ignore').decode() or 'release'
    response = Response(result['content'], mimetype=result['content_type'])
    response.headers['Content-Disposition'] = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}")
    response.headers['Cache-Control'] = 'no-store'
    return response
