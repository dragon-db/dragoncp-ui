#!/usr/bin/env python3
"""
The library and history views — what the service holds, and what we hold.

Read-only towards the services, and structurally so: every handler here
reaches Sonarr or Radarr through the connector adapters, which refuse any verb
other than GET or HEAD. The one route that acts — Sync on a title — acts on
*this* side, through the sync engine like every other sync.

The library view exists to answer a question this application could not answer
before the title index: **which parts of the Sonarr library have we actually
got?** The interesting answer is not the titles that are synced — it is the ones
that never were, which have no transfer, no notification and no record of any
kind here, and so were invisible.
"""

import logging

from flask import Blueprint, jsonify, request

from auth import require_auth
from env_flags import test_mode_enabled
from models.media_item import SOURCES

media_library_bp = Blueprint('media_library', __name__)
logger = logging.getLogger('dragoncp.routes.media_library')

_index = None
_scanner = None


def init_media_library_routes(media_index, scanner=None):
    global _index, _scanner
    _index = media_index
    _scanner = scanner


def _guard(source: str):
    """Reject anything that is not one of the sources we read."""
    if _index is None:
        return jsonify({'success': False,
                        'error': 'The library index is not available'}), 503
    if source not in SOURCES:
        return jsonify({'success': False,
                        'error': f"Unknown source '{source}'"}), 404
    return None


@media_library_bp.route('/library/<source>')
@require_auth
def api_library(source):
    """One row per title, with what the service has beside what we hold.

    `refresh=1` pulls the service's whole catalogue into the index first, which
    is how titles that have never been synced appear at all — nothing else in
    this application ever hears about a series until a notification arrives for
    it.
    """
    problem = _guard(source)
    if problem:
        return problem
    refresh = str(request.args.get('refresh', '')).lower() in ('1', 'true', 'yes')
    try:
        view = _index.library_view(source, refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - a view must not 500 on one bad row
        logger.exception('Library view failed for %s', source)
        return jsonify({'success': False, 'error': str(exc)}), 500
    view['success'] = True
    view['read_only'] = True
    view['test_mode'] = test_mode_enabled()
    return jsonify(view)


@media_library_bp.route('/library/<source>/history')
@require_auth
def api_library_history(source):
    """A page of the service's own history, with our titles matched in."""
    problem = _guard(source)
    if problem:
        return problem
    try:
        page = max(1, int(request.args.get('page', 1)))
        page_size = max(1, min(200, int(request.args.get('page_size', 50))))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'page and page_size must be numbers'}), 400
    try:
        view = _index.history_view(source, page=page, page_size=page_size)
    except Exception as exc:  # noqa: BLE001
        logger.exception('History view failed for %s', source)
        return jsonify({'success': False, 'error': str(exc)}), 500
    view['success'] = True
    view['read_only'] = True
    return jsonify(view)


@media_library_bp.route('/library/<source>/queue')
@require_auth
def api_library_queue(source):
    """What is waiting on the service, and why each row is waiting."""
    problem = _guard(source)
    if problem:
        return problem
    try:
        view = _index.queue_view(source)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Queue view failed for %s', source)
        return jsonify({'success': False, 'error': str(exc)}), 500
    view['success'] = True
    view['read_only'] = True
    return jsonify(view)


@media_library_bp.route('/library/<source>/sync', methods=['POST'])
@require_auth
def api_library_sync(source):
    """Fetch one title's gap, because somebody pressed Sync on it.

    The one write this blueprint has, and it writes to *this* side: transfers
    are started through the ordinary pipeline, with the ordinary safety checks.
    What to fetch is derived on the server from a fresh look at the service —
    a browser tab can be hours old, and "sync what is missing" has to mean
    missing now, not missing when the page loaded.
    """
    problem = _guard(source)
    if problem:
        return problem
    if _scanner is None:
        return jsonify({'success': False,
                        'error': 'Syncing from the library view is not available'}), 503

    payload = request.get_json(silent=True) or {}
    external_id = str(payload.get('external_id') or '').strip()
    if not external_id:
        return jsonify({'success': False, 'error': 'external_id is required'}), 400

    try:
        result = _scanner.sync_one(source, external_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Library sync failed for %s:%s', source, external_id)
        return jsonify({'success': False, 'error': str(exc)}), 500

    status = 200 if result.get('success') else 409
    return jsonify(result), status


@media_library_bp.route('/library/<source>/refresh', methods=['POST'])
@require_auth
def api_library_refresh(source):
    """Pull the service's catalogue into the index.

    A POST because it writes — to *our* database. Nothing is sent to Sonarr or
    Radarr but a GET; the adapters cannot do otherwise.
    """
    problem = _guard(source)
    if problem:
        return problem
    try:
        ok, seen = _index.refresh_library(source)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Library refresh failed for %s', source)
        return jsonify({'success': False, 'error': str(exc)}), 500
    if not ok:
        return jsonify({'success': False,
                        'error': f'{source.title()} did not answer'}), 502
    return jsonify({'success': True, 'source': source, 'titles_seen': seen,
                    'read_only': True})
