#!/usr/bin/env python3
"""
DragonCP WebSocket Manager
WebSocket event handlers for real-time communication with authentication
"""

import logging
import os
import time
import threading
from datetime import datetime, timedelta
from typing import Any
from flask import request, session
from flask_socketio import join_room, leave_room, disconnect
from auth import validate_websocket_token, websocket_identity_still_valid
from env_flags import env_flag


# WebSocket timeout configuration
WEBSOCKET_TIMEOUT_MIN = 5 * 60    # 5 minutes minimum
WEBSOCKET_TIMEOUT_MAX = 65 * 60   # 65 minutes maximum (5 minutes longer than max client timeout)
WEBSOCKET_TIMEOUT_DEFAULT = 35 * 60  # 35 minutes default

# How often a live connection's account is re-checked while it keeps pinging.
# Small enough that a disabled administrator loses their updates promptly,
# large enough that a frequent ping does not turn into a read per ping.
AUTH_RECHECK_SECONDS = 60


# WebSocket connection tracking
websocket_connections = {}
websocket_connections_lock = threading.RLock()

# Which clients are watching which transfer's log output:
#   {transfer_id: {sid, sid, ...}}
#
# rsync output is by far the largest thing this app pushes - a progress event
# carrying the log tail is roughly fifteen times the size of the same event
# without it - and it is only of interest to whoever has that transfer's row
# open. Rooms keep it off everyone else's socket, and this registry lets the
# producer skip building the payload at all when nobody is listening.
transfer_log_subscribers: dict[str, set[str]] = {}
transfer_log_subscribers_lock = threading.RLock()


def transfer_log_room(transfer_id: str) -> str:
    """Room name for one transfer's log stream."""
    return f"transfer_logs:{transfer_id}"


def has_log_subscribers(transfer_id: str) -> bool:
    """
    Whether anyone is watching this transfer's output.

    Callers check this before assembling a log payload, so an unwatched
    transfer costs nothing beyond the small progress broadcast.
    """
    with transfer_log_subscribers_lock:
        return bool(transfer_log_subscribers.get(transfer_id))


def _drop_subscriber(session_id: str, transfer_id: str = None):
    """Remove one subscription, or every subscription held by a session."""
    with transfer_log_subscribers_lock:
        targets = [transfer_id] if transfer_id else list(transfer_log_subscribers)
        for key in targets:
            watchers = transfer_log_subscribers.get(key)
            if not watchers:
                continue
            watchers.discard(session_id)
            if not watchers:
                transfer_log_subscribers.pop(key, None)


cleanup_thread = None
cleanup_thread_lock = threading.Lock()

logger = logging.getLogger('dragoncp.websocket')




ALLOW_QUERY_TOKEN_AUTH = env_flag('ALLOW_QUERY_TOKEN_AUTH', default=False)


def get_websocket_connection_count():
    """Return current websocket connection count."""
    with websocket_connections_lock:
        return len(websocket_connections)


def get_websocket_connection_snapshot():
    """Return a shallow copy of websocket connection state."""
    with websocket_connections_lock:
        return {
            sid: info.copy()
            for sid, info in websocket_connections.items()
        }


def get_cleanup_thread_status():
    """Return whether the websocket cleanup thread is currently running."""
    with cleanup_thread_lock:
        return cleanup_thread is not None and cleanup_thread.is_alive()


#: Set by app.py once the settings service exists. Left as None in tests and
#: any context without one, where the default applies.
_settings_service = None


def set_settings_service(service):
    """Give the websocket layer a way to read the configured idle timeout."""
    global _settings_service
    _settings_service = service


def get_websocket_timeout_for_session(session=None):
    """
    How long a realtime connection may sit idle before the server drops it.

    Read from the application settings, not from the caller's browser session.
    It used to come from a per-browser overlay, which meant the timeout applied
    to whoever happened to save it and to nobody else — and was invisible to the
    cleanup thread that enforces it, because that thread has no request context.

    `session` is still accepted so callers do not all have to change; it is no
    longer read.
    """
    del session
    try:
        if _settings_service is None:
            return WEBSOCKET_TIMEOUT_DEFAULT
        minutes = _settings_service.get_int('WEBSOCKET_TIMEOUT_MINUTES', 0)
        if not minutes:
            return WEBSOCKET_TIMEOUT_DEFAULT
        # The server holds on a little longer than the client is told to, so a
        # client that is about to reconnect is not cut off mid-handshake.
        return min(WEBSOCKET_TIMEOUT_MAX, minutes * 60 + 5 * 60)
    except (TypeError, ValueError, AttributeError):
        return WEBSOCKET_TIMEOUT_DEFAULT


def register_websocket_handlers(socketio):
    """Register WebSocket event handlers with authentication"""
    
    @socketio.on('connect')
    def handle_connect(auth=None):
        """Handle WebSocket connection with authentication"""
        session_id = str(getattr(request, 'sid', ''))
        transport = request.args.get('transport', 'unknown')
        
        # Validate authentication token
        auth_data: dict[str, Any] | None = auth if isinstance(auth, dict) else None
        if not auth_data and ALLOW_QUERY_TOKEN_AUTH:
            query_token = request.args.get('token')
            if query_token:
                auth_data = {'token': query_token}
        if not auth_data:
            logger.warning(
                'WebSocket connection rejected: sid=%s transport=%s reason=missing-auth-payload',
                session_id[:8],
                transport,
            )
            return False
        identity = validate_websocket_token(auth_data)

        if not identity:
            logger.warning(
                'WebSocket connection rejected: sid=%s transport=%s reason=invalid-or-missing-token',
                session_id[:8],
                transport,
            )
            # Reject the connection
            return False

        username = identity['username']

        # Store connection with authenticated user info. The account id and
        # token version come along so the cleanup thread can tell whether this
        # connection is still backed by a live account - a socket authenticates
        # once at handshake, and without this a disabled admin would keep
        # receiving updates until they happened to disconnect.
        with websocket_connections_lock:
            websocket_connections[session_id] = {
                'connected_at': datetime.now(),
                'last_activity': datetime.now(),
                'timeout_seconds': get_websocket_timeout_for_session(session),
                'username': username,
                'account_id': identity.get('account_id'),
                'token_version': identity.get('token_version', 0),
                'auth_source': identity.get('source', 'env'),
                'transport': transport,
                'origin': request.headers.get('Origin', ''),
            }
            active_connections = len(websocket_connections)
        logger.info(
            'WebSocket connected: sid=%s user=%s transport=%s active_connections=%s',
            session_id[:8],
            username,
            transport,
            active_connections,
        )
        
        return True

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle WebSocket disconnection"""
        session_id = str(getattr(request, 'sid', ''))
        with websocket_connections_lock:
            connection_info = websocket_connections.pop(session_id, {})
            active_connections = len(websocket_connections)
        # Rooms are torn down with the socket, but this registry is ours to
        # clear - otherwise a dropped client keeps a transfer looking watched
        # and the producer keeps building payloads for nobody.
        _drop_subscriber(session_id)
        username = connection_info.get('username', 'unknown')
        transport = connection_info.get('transport', 'unknown')
        logger.info(
            'WebSocket disconnected: sid=%s user=%s transport=%s active_connections=%s',
            session_id[:8],
            username,
            transport,
            active_connections,
        )

    @socketio.on('activity')
    def handle_activity():
        """
        Handle client activity ping, and take the chance to re-check the account.

        A connection authenticates once at handshake. Re-checking here is what
        makes disabling an administrator take effect on their live updates in
        about a minute rather than whenever the cleanup sweep next runs. The
        check is throttled because this ping is frequent and the account row is
        read fresh each time.
        """
        session_id = str(getattr(request, 'sid', ''))
        now = datetime.now()

        with websocket_connections_lock:
            connection = websocket_connections.get(session_id)
            if connection is None:
                return
            connection['last_activity'] = now

            last_check = connection.get('last_auth_check')
            if last_check is not None and (now - last_check).total_seconds() < AUTH_RECHECK_SECONDS:
                return

            connection['last_auth_check'] = now
            account_id = connection.get('account_id')
            token_version = connection.get('token_version', 0)
            auth_source = connection.get('auth_source', 'env')
            username = connection.get('username', 'unknown')

        if websocket_identity_still_valid(account_id, token_version, auth_source):
            return

        logger.info(
            'WebSocket dropped, account no longer valid: sid=%s user=%s',
            session_id[:8],
            username,
        )
        with websocket_connections_lock:
            websocket_connections.pop(session_id, None)
        _drop_subscriber(session_id)
        disconnect()

    @socketio.on('transfer_logs_subscribe')
    def handle_transfer_logs_subscribe(data):
        """
        Start receiving one transfer's log output.

        The connect handler rejects unauthenticated sockets outright, so a
        session that reaches here is already authenticated; the membership
        check only guards against a socket that has since been reaped.
        """
        session_id = str(getattr(request, 'sid', ''))
        transfer_id = (data or {}).get('transfer_id')
        if not transfer_id:
            return
        with websocket_connections_lock:
            if session_id not in websocket_connections:
                return

        join_room(transfer_log_room(transfer_id))
        with transfer_log_subscribers_lock:
            transfer_log_subscribers.setdefault(transfer_id, set()).add(session_id)
        logger.debug('Log subscribe: sid=%s transfer=%s', session_id[:8], transfer_id)

    @socketio.on('transfer_logs_unsubscribe')
    def handle_transfer_logs_unsubscribe(data):
        """Stop receiving a transfer's log output."""
        session_id = str(getattr(request, 'sid', ''))
        transfer_id = (data or {}).get('transfer_id')
        if not transfer_id:
            return
        leave_room(transfer_log_room(transfer_id))
        _drop_subscriber(session_id, transfer_id)
        logger.debug('Log unsubscribe: sid=%s transfer=%s', session_id[:8], transfer_id)

    @socketio.on('authenticate')
    def handle_authenticate(data):
        """Handle re-authentication after token refresh"""
        session_id = str(getattr(request, 'sid', ''))
        
        if not data or not isinstance(data, dict):
            return {'success': False, 'message': 'Invalid auth data'}
        
        identity = validate_websocket_token(data)

        if identity:
            username = identity['username']
            with websocket_connections_lock:
                if session_id in websocket_connections:
                    connection = websocket_connections[session_id]
                    connection['username'] = username
                    connection['account_id'] = identity.get('account_id')
                    connection['token_version'] = identity.get('token_version', 0)
                    connection['auth_source'] = identity.get('source', 'env')
                    connection['last_activity'] = datetime.now()
            logger.info('WebSocket re-authenticated: sid=%s user=%s', session_id[:8], username)
            return {'success': True, 'user': username}
        else:
            logger.warning('WebSocket re-authentication failed: sid=%s', session_id[:8])
            return {'success': False, 'message': 'Invalid token'}


def cleanup_stale_connections(socketio):
    """Cleanup stale WebSocket connections"""
    while True:
        try:
            current_time = datetime.now()
            
            stale_connections = []
            for session_id, connection_info in get_websocket_connection_snapshot().items():
                # Get timeout for this specific session (stored when connection was made)
                session_timeout = connection_info.get('timeout_seconds', WEBSOCKET_TIMEOUT_DEFAULT)
                timeout_threshold = current_time - timedelta(seconds=session_timeout)

                if connection_info['last_activity'] < timeout_threshold:
                    stale_connections.append(session_id)
                    continue

                # A connection that has stopped pinging is not re-checked by the
                # activity handler, so the account behind it is confirmed here
                # too. Nothing that is still receiving updates should outlive
                # the account that opened it.
                if not websocket_identity_still_valid(
                    connection_info.get('account_id'),
                    connection_info.get('token_version', 0),
                    connection_info.get('auth_source', 'env'),
                ):
                    logger.info(
                        'Closing WebSocket for revoked account: sid=%s user=%s',
                        session_id[:8],
                        connection_info.get('username', 'unknown'),
                    )
                    stale_connections.append(session_id)

            for session_id in stale_connections:
                connection_info = get_websocket_connection_snapshot().get(session_id, {})
                username = connection_info.get('username', 'unknown')
                try:
                    socketio.server.disconnect(sid=session_id, namespace='/')
                except Exception:
                    logger.exception(
                        'Failed to disconnect stale WebSocket connection: sid=%s user=%s',
                        session_id[:8],
                        username,
                    )
                    continue

                with websocket_connections_lock:
                    connection_info = websocket_connections.pop(session_id, connection_info)
                    active_connections = len(websocket_connections)
                logger.info(
                    'Cleaning stale WebSocket connection: sid=%s user=%s active_connections=%s',
                    session_id[:8],
                    connection_info.get('username', username),
                    active_connections,
                )
            
            if stale_connections:
                logger.info('Cleaned up %s stale WebSocket connection(s)', len(stale_connections))
                
        except Exception as e:
            logger.exception('Error in cleanup_stale_connections: %s', e)
        
        # Sleep for 5 minutes before next cleanup
        time.sleep(5 * 60)


def start_cleanup_thread(socketio):
    """Start the WebSocket cleanup thread"""
    global cleanup_thread

    with cleanup_thread_lock:
        if cleanup_thread is not None and cleanup_thread.is_alive():
            return cleanup_thread

        cleanup_thread = threading.Thread(
            target=cleanup_stale_connections,
            args=(socketio,),
            daemon=True,
            name='dragoncp-websocket-cleanup',
        )
        cleanup_thread.start()

    logger.info('Started WebSocket cleanup thread')
    return cleanup_thread


def get_authenticated_connections():
    """Get list of authenticated WebSocket connections"""
    return {
        sid: {
            'username': info.get('username'),
            'connected_at': info.get('connected_at').isoformat() if info.get('connected_at') else None,
            'last_activity': info.get('last_activity').isoformat() if info.get('last_activity') else None,
            'transport': info.get('transport'),
        }
        for sid, info in get_websocket_connection_snapshot().items()
    }
