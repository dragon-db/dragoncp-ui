#!/usr/bin/env python3
"""
DragonCP Connector Routes
Configuring the outside services this app talks to.

One rule governs every handler here: **no response body ever contains a
secret.** Not redacted, not partially shown. Credentials live in
`connector_secret`, the store exposes them only through `secret()`, and nothing
below calls it. What a client gets instead is `secrets_set`, saying whether a
value exists — which is all a form needs to render "configured" beside a field
it must never be shown.
"""

import logging

from flask import Blueprint, jsonify, request

from activity_log import record, record_failure
from auth import require_auth
from services.connectors import events as event_catalogue
from services.connectors import registry
from services.connectors.base import NotifyingConnector
from services.connectors.events import INFO, TEST_EVENT_KEY, Event, Field
from settings_registry import REDACTED

connectors_bp = Blueprint('connectors', __name__)

logger = logging.getLogger(__name__)

# Set by app.py
connector_service = None
connector_store = None

MAX_LABEL_LENGTH = 60


def init_connector_routes(service, store):
    global connector_service, connector_store
    connector_service = service
    connector_store = store


def _fail(message: str, code: int = 400):
    return jsonify({'status': 'error', 'message': message}), code


def _adapter_or_404(connector_id: str):
    """The adapter for a connector, or a 404 response."""
    adapter = connector_service.adapter(connector_id) if connector_service else None
    if adapter is None:
        return None, _fail(f"No connector called {connector_id}", 404)
    return adapter, None


def _notifier_or_error(connector_id: str):
    """The adapter, but only if it can be sent announcements.

    Destinations belong to notifying connectors. Sonarr has none and never
    will, and asking it for one should say so rather than fail on a missing
    attribute halfway through.
    """
    adapter, error = _adapter_or_404(connector_id)
    if error:
        return None, error
    if not isinstance(adapter, NotifyingConnector):
        return None, _fail(f"{adapter.display_name} does not send notifications")
    return adapter, None


# ===== LISTING =====

@connectors_bp.route('/connectors')
@require_auth
def api_connectors():
    """Every connector this build knows about, configured or not."""
    try:
        return jsonify({
            'status': 'success',
            'connectors': connector_service.describe_all(),
        })
    except Exception as e:
        logger.exception("Failed to list connectors")
        return _fail(f"Failed to list connectors: {e}", 500)


@connectors_bp.route('/connectors/events')
@require_auth
def api_connector_events():
    """The announcement catalogue, and where each one currently goes.

    Driven by the catalogue rather than by stored rows: an event with no route
    still has to appear, because "uses the default" is a real answer and the
    operator needs to see it to change it.
    """
    try:
        routes = {
            (r['event_key'], r['connector_id']): r
            for r in connector_store.list_routes()
        }
        notifying = [
            c for c in connector_service.describe_all()
            if 'notify' in c.get('capabilities', [])
        ]

        catalogue = []
        for entry in event_catalogue.catalogue():
            per_connector = {}
            for connector in notifying:
                route = routes.get((entry['key'], connector['id']))
                per_connector[connector['id']] = {
                    'target_id': route.get('target_id') if route else None,
                    'enabled': route.get('enabled', True) if route else True,
                    'using_default': not (route and route.get('target_id')),
                }
            catalogue.append({**entry, 'routes': per_connector})

        return jsonify({
            'status': 'success',
            'events': catalogue,
            'connectors': [
                {'id': c['id'], 'display_name': c['display_name'],
                 'targets': c.get('targets', [])}
                for c in notifying
            ],
        })
    except Exception as e:
        logger.exception("Failed to read the notification catalogue")
        return _fail(f"Failed to read the catalogue: {e}", 500)


@connectors_bp.route('/connectors/<connector_id>')
@require_auth
def api_connector_detail(connector_id):
    try:
        described = connector_service.describe(connector_id)
        if described is None:
            return _fail(f"No connector called {connector_id}", 404)
        described['routes'] = connector_store.list_routes(connector_id)
        return jsonify({'status': 'success', 'connector': described})
    except Exception as e:
        logger.exception("Failed to read connector %s", connector_id)
        return _fail(f"Failed to read the connector: {e}", 500)


# ===== SAVING =====

@connectors_bp.route('/connectors/<connector_id>', methods=['POST'])
@require_auth
def api_connector_save(connector_id):
    """Save a connector's settings.

    Fields declared secret go to `connector_secret`; everything else goes in
    the config blob. A secret submitted as the redaction placeholder means
    "unchanged", the same convention the settings panel already uses, so a form
    can round-trip without the value ever leaving the server.
    """
    adapter, error = _adapter_or_404(connector_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    config_payload = data.get('config')
    if config_payload is not None and not isinstance(config_payload, dict):
        return _fail('config must be an object')

    try:
        by_name = {f.name: f for f in adapter.config_fields}
        plain, secrets, unknown = {}, {}, []

        for name, value in (config_payload or {}).items():
            field = by_name.get(name)
            if field is None:
                unknown.append(name)
                continue
            if field.secret:
                # The placeholder means the client never had the real value and
                # is sending back what it was shown. Not a change.
                if value != REDACTED:
                    secrets[name] = '' if value is None else str(value)
            else:
                plain[name] = '' if value is None else str(value)

        if unknown:
            return _fail(f"Not a setting of this connector: {', '.join(sorted(unknown))}")

        enabled = data.get('enabled')
        connector_store.upsert_connector(
            connector_id, adapter.display_name,
            enabled=None if enabled is None else bool(enabled),
            config=plain or None,
        )
        for name, value in secrets.items():
            if value:
                connector_store.set_secret(connector_id, name, value)
            else:
                # An emptied credential is an answer: the operator is
                # disconnecting this service, not declining to change it.
                connector_store.delete_secret(connector_id, name)

        changed = sorted(list(plain) + list(secrets)) + (
            ['enabled'] if enabled is not None else []
        )
        record('connector.update',
               f"Changed {adapter.display_name} settings: "
               f"{', '.join(changed) or 'nothing'}",
               target_type='connector', target_id=connector_id,
               target_label=adapter.display_name,
               detail={'keys': changed})

        return jsonify({
            'status': 'success',
            'message': f"{adapter.display_name} settings saved",
            'connector': connector_service.describe(connector_id),
        })
    except Exception as e:
        logger.exception("Failed to save connector %s", connector_id)
        return _fail(f"Failed to save: {e}", 500)


@connectors_bp.route('/connectors/<connector_id>/check', methods=['POST'])
@require_auth
def api_connector_check(connector_id):
    """Reach the service now and say what happened."""
    adapter, error = _adapter_or_404(connector_id)
    if error:
        return error

    if not adapter.supports_check:
        return _fail(
            f"{adapter.display_name} has nothing to test at this level. "
            f"Use Test beside a {getattr(adapter, 'target_noun', 'destination')}."
        )

    try:
        result = connector_service.check(connector_id)
        (record if result.ok else record_failure)(
            'connector.check',
            f"{'Reached' if result.ok else 'Could not reach'} {adapter.display_name}",
            target_type='connector', target_id=connector_id,
            target_label=adapter.display_name,
        )
        return jsonify({'status': 'success', 'result': result.as_dict()})
    except Exception as e:
        logger.exception("Check failed for %s", connector_id)
        return _fail(f"Check failed: {e}", 500)


# ===== DESTINATIONS =====

@connectors_bp.route('/connectors/<connector_id>/targets', methods=['POST'])
@require_auth
def api_target_create(connector_id):
    adapter, error = _notifier_or_error(connector_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    label = (data.get('label') or '').strip()
    credential = (data.get('credential') or '').strip()

    if not label:
        return _fail('Give this destination a name you will recognise')
    if len(label) > MAX_LABEL_LENGTH:
        return _fail(f"That name is too long (max {MAX_LABEL_LENGTH} characters)")

    reason = adapter.validate_target(credential)
    if reason:
        return _fail(reason)

    if any(t['label'].lower() == label.lower()
           for t in connector_store.list_targets(connector_id)):
        return _fail(f"There is already a destination called “{label}”")

    try:
        # A connector row has to exist before something can belong to it.
        if not connector_store.get_connector(connector_id):
            connector_store.upsert_connector(connector_id, adapter.display_name)

        target_id = connector_store.create_target(
            connector_id, label, credential,
            make_default=data.get('make_default'),
        )
        record('connector.target_add',
               f"Added the {adapter.display_name} {adapter.target_noun} “{label}”",
               target_type='connector', target_id=connector_id,
               target_label=adapter.display_name, detail={'label': label})
        return jsonify({
            'status': 'success',
            'target_id': target_id,
            'targets': connector_store.list_targets(connector_id),
        })
    except Exception as e:
        logger.exception("Failed to add a target to %s", connector_id)
        return _fail(f"Failed to add: {e}", 500)


@connectors_bp.route('/connectors/<connector_id>/targets/<target_id>', methods=['PATCH'])
@require_auth
def api_target_update(connector_id, target_id):
    adapter, error = _notifier_or_error(connector_id)
    if error:
        return error

    existing = connector_store.get_target(target_id)
    if not existing or existing['connector_id'] != connector_id:
        return _fail('That destination no longer exists', 404)

    data = request.get_json(silent=True) or {}
    label = data.get('label')
    credential = data.get('credential')

    if label is not None:
        label = str(label).strip()
        if not label:
            return _fail('A destination needs a name')
        if len(label) > MAX_LABEL_LENGTH:
            return _fail(f"That name is too long (max {MAX_LABEL_LENGTH} characters)")
        clash = any(
            t['label'].lower() == label.lower() and t['target_id'] != target_id
            for t in connector_store.list_targets(connector_id)
        )
        if clash:
            return _fail(f"There is already a destination called “{label}”")

    if credential is not None:
        credential = str(credential).strip()
        if credential == REDACTED:
            # What the client was shown, sent back unchanged.
            credential = None
        else:
            reason = adapter.validate_target(credential)
            if reason:
                return _fail(reason)

    try:
        connector_store.update_target(
            target_id, label=label, credential=credential,
            enabled=data.get('enabled'),
            make_default=data.get('make_default'),
        )
        record('connector.target_update',
               f"Changed the {adapter.display_name} {adapter.target_noun} "
               f"“{label or existing['label']}”",
               target_type='connector', target_id=connector_id,
               target_label=adapter.display_name)
        return jsonify({
            'status': 'success',
            'targets': connector_store.list_targets(connector_id),
        })
    except Exception as e:
        logger.exception("Failed to update target %s", target_id)
        return _fail(f"Failed to save: {e}", 500)


@connectors_bp.route('/connectors/<connector_id>/targets/<target_id>', methods=['DELETE'])
@require_auth
def api_target_delete(connector_id, target_id):
    adapter, error = _notifier_or_error(connector_id)
    if error:
        return error

    existing = connector_store.get_target(target_id)
    if not existing or existing['connector_id'] != connector_id:
        return _fail('That destination no longer exists', 404)

    try:
        connector_store.delete_target(target_id)
        record('connector.target_delete',
               f"Removed the {adapter.display_name} {adapter.target_noun} "
               f"“{existing['label']}”",
               target_type='connector', target_id=connector_id,
               target_label=adapter.display_name,
               detail={'label': existing['label']})
        return jsonify({
            'status': 'success',
            'targets': connector_store.list_targets(connector_id),
        })
    except Exception as e:
        logger.exception("Failed to delete target %s", target_id)
        return _fail(f"Failed to remove: {e}", 500)


@connectors_bp.route('/connectors/<connector_id>/targets/<target_id>/test', methods=['POST'])
@require_auth
def api_target_test(connector_id, target_id):
    """Send a real message to one destination, now.

    Deliberately bypasses routing: the question being asked is "does this
    webhook work", not "where would a sync notification go".
    """
    adapter, error = _notifier_or_error(connector_id)
    if error:
        return error

    existing = connector_store.get_target(target_id)
    if not existing or existing['connector_id'] != connector_id:
        return _fail('That destination no longer exists', 404)

    event = Event(
        # Not a catalogue event: a test send ignores routing by design, and
        # recording it as a finished transfer would put a lie in the log.
        key=TEST_EVENT_KEY,
        severity=INFO,
        title='DragonCP test message',
        summary=f"Sent from the {adapter.display_name} settings page.",
        fields=(
            Field('Destination', existing['label'], inline=True),
            Field('Result', 'If you can read this, it works.', inline=True),
        ),
        author='Test Notification',
        footer='This is a test message from DragonCP',
    )

    try:
        result = connector_service.send_test(connector_id, target_id, event)
        (record if result.ok else record_failure)(
            'connector.target_test',
            f"{'Sent' if result.ok else 'Could not send'} a test message to "
            f"“{existing['label']}”",
            target_type='connector', target_id=connector_id,
            target_label=adapter.display_name,
            detail={'label': existing['label']},
        )
        if result.ok:
            return jsonify({
                'status': 'success',
                'message': f"Test message sent to “{existing['label']}”",
            })
        return _fail(result.error or 'The message was not accepted')
    except Exception as e:
        logger.exception("Test send failed for %s", target_id)
        return _fail(f"Test failed: {e}", 500)


# ===== ROUTING =====

@connectors_bp.route('/connectors/routes', methods=['PUT'])
@require_auth
def api_routes_save():
    """Save the routing table.

    Accepts a list of rows. A row whose `target_id` is null means "use the
    connector's default", which is also what a missing row means — so clearing
    a choice and never making one behave identically, as they should.
    """
    data = request.get_json(silent=True) or {}
    rows = data.get('routes')
    if not isinstance(rows, list):
        return _fail('routes must be a list')

    valid_connectors = set(registry.known_ids())
    saved = 0

    try:
        for row in rows:
            if not isinstance(row, dict):
                return _fail('Each route must be an object')
            event_key = row.get('event_key')
            connector_id = row.get('connector_id')

            if event_key not in event_catalogue.EVENT_KEYS:
                return _fail(f"Unknown notification: {event_key}")
            if connector_id not in valid_connectors:
                return _fail(f"Unknown connector: {connector_id}")

            target_id = row.get('target_id') or None
            if target_id:
                target = connector_store.get_target(target_id)
                if not target or target['connector_id'] != connector_id:
                    return _fail('That destination no longer exists')

            connector_store.set_route(
                event_key, connector_id, target_id,
                enabled=bool(row.get('enabled', True)),
            )
            saved += 1

        record('connector.routes_update',
               f"Changed where {saved} notification{'s' if saved != 1 else ''} "
               f"{'are' if saved != 1 else 'is'} sent",
               target_type='connector', target_id='routes',
               detail={'count': saved})

        return jsonify({'status': 'success', 'saved': saved})
    except Exception as e:
        logger.exception("Failed to save routes")
        return _fail(f"Failed to save: {e}", 500)


# ===== DELIVERY HISTORY =====

@connectors_bp.route('/connectors/<connector_id>/deliveries')
@require_auth
def api_connector_deliveries(connector_id):
    """What was actually sent, and what happened to it."""
    if connector_id not in registry.known_ids():
        return _fail(f"No connector called {connector_id}", 404)
    try:
        limit = request.args.get('limit', 50, type=int)
        return jsonify({
            'status': 'success',
            'deliveries': connector_store.list_deliveries(connector_id, limit),
        })
    except Exception as e:
        logger.exception("Failed to read deliveries for %s", connector_id)
        return _fail(f"Failed to read the history: {e}", 500)
