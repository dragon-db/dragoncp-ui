#!/usr/bin/env python3
"""
Jellyfin: what is playing now, and the record of every play.

Read only towards Jellyfin. The record is DragonCP's own table, so it can be
read with Jellyfin switched off or down.
"""

import logging
import re

from flask import Blueprint, Response, jsonify, request

from auth import require_auth

jellyfin_bp = Blueprint('jellyfin', __name__)
logger = logging.getLogger('dragoncp.routes.jellyfin')

_service = None

#: Jellyfin item ids are 32 hex digits, with or without dashes.
_ITEM_ID = re.compile(r'^[0-9a-fA-F-]{32,36}$')


def init_jellyfin_routes(service):
    global _service
    _service = service


def _unavailable():
    return jsonify({'success': False, 'error': 'Jellyfin is not available'}), 503


@jellyfin_bp.route('/jellyfin/now-playing')
@require_auth
def api_now_playing():
    """Every stream playing right now, converted ones first."""
    if _service is None:
        return _unavailable()
    try:
        snapshot = _service.poll()
    except Exception:  # noqa: BLE001 - the page must say something, not 500
        logger.exception('Reading what Jellyfin is playing failed')
        return jsonify({'success': False, 'error': 'Could not read what is playing'}), 500
    return jsonify({'success': True, **snapshot})


@jellyfin_bp.route('/jellyfin/plays')
@require_auth
def api_plays():
    """Recorded plays, newest first."""
    if _service is None:
        return _unavailable()
    try:
        limit = max(1, min(200, int(request.args.get('limit', 50))))
        offset = max(0, int(request.args.get('offset', 0)))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'limit and offset must be numbers'}), 400
    converted_arg = str(request.args.get('converted', '') or '').lower()
    converted = {'1': True, 'true': True, '0': False, 'false': False}.get(converted_arg)
    user = str(request.args.get('user', '') or '').strip()
    search = str(request.args.get('q', '') or '').strip()[:100]
    page = _service.plays(limit=limit, offset=offset, user=user,
                          converted=converted, search=search)
    return jsonify({'success': True, 'recording': _service.recording(), **page})


@jellyfin_bp.route('/jellyfin/image/<item_id>')
def api_image(item_id):
    """An item's poster, through DragonCP.

    No sign-in check: an `<img>` cannot send the token. The address is signed
    instead, so only posters this app handed to a signed-in page are served —
    this is not a way to read Jellyfin's library from outside.
    """
    if _service is None or not _ITEM_ID.match(item_id or ''):
        return Response(status=404)
    if not _service.signature_ok(item_id, request.args.get('s', '')):
        return Response(status=404)
    try:
        width = max(60, min(600, int(request.args.get('w', 240))))
    except (TypeError, ValueError):
        width = 240
    result = _service.image(item_id, width)
    if result is None or not result.ok:
        return Response(status=404)
    content_type = result.content_type if result.content_type.startswith('image/') else 'image/jpeg'
    response = Response(result.content, mimetype=content_type)
    response.headers['Cache-Control'] = 'private, max-age=86400'
    return response
