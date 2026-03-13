#!/usr/bin/env python3
"""
DragonCP WebSocket Manager
WebSocket event handlers for real-time communication with authentication
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Any
from flask import request
from flask_socketio import disconnect as socketio_disconnect
from auth import validate_websocket_token


# WebSocket timeout configuration
WEBSOCKET_TIMEOUT_MIN = 5 * 60    # 5 minutes minimum
WEBSOCKET_TIMEOUT_MAX = 65 * 60   # 65 minutes maximum (5 minutes longer than max client timeout)
WEBSOCKET_TIMEOUT_DEFAULT = 35 * 60  # 35 minutes default


# WebSocket connection tracking
websocket_connections = {}
websocket_connections_lock = threading.RLock()
cleanup_thread = None
cleanup_thread_lock = threading.Lock()

logger = logging.getLogger('dragoncp.websocket')


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


def get_websocket_timeout_for_session(session=None):
    """Get WebSocket timeout for current session, respecting user configuration"""
    try:
        if session is None:
            return WEBSOCKET_TIMEOUT_DEFAULT
            
        # Get user's configured timeout from session
        session_config = session.get('ui_config', {})
        user_timeout_minutes = session_config.get('WEBSOCKET_TIMEOUT_MINUTES')
        
        if user_timeout_minutes:
            # Convert to seconds and add 5 minutes buffer, but cap at maximum
            user_timeout_seconds = min(60, max(5, int(user_timeout_minutes))) * 60
            server_timeout = min(WEBSOCKET_TIMEOUT_MAX, user_timeout_seconds + 5 * 60)
            return server_timeout
        else:
            return WEBSOCKET_TIMEOUT_DEFAULT
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
        if not auth_data:
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
        username = validate_websocket_token(auth_data)
        
        if not username:
            logger.warning(
                'WebSocket connection rejected: sid=%s transport=%s reason=invalid-or-missing-token',
                session_id[:8],
                transport,
            )
            # Reject the connection
            return False
        
        # Store connection with authenticated user info
        with websocket_connections_lock:
            websocket_connections[session_id] = {
                'connected_at': datetime.now(),
                'last_activity': datetime.now(),
                'timeout_seconds': get_websocket_timeout_for_session(request.environ.get('flask.session', {})),
                'username': username,
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
        """Handle client activity ping"""
        session_id = str(getattr(request, 'sid', ''))
        with websocket_connections_lock:
            if session_id in websocket_connections:
                websocket_connections[session_id]['last_activity'] = datetime.now()

    @socketio.on('authenticate')
    def handle_authenticate(data):
        """Handle re-authentication after token refresh"""
        session_id = str(getattr(request, 'sid', ''))
        
        if not data or not isinstance(data, dict):
            return {'success': False, 'message': 'Invalid auth data'}
        
        username = validate_websocket_token(data)
        
        if username:
            with websocket_connections_lock:
                if session_id in websocket_connections:
                    websocket_connections[session_id]['username'] = username
                    websocket_connections[session_id]['last_activity'] = datetime.now()
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
            
            for session_id in stale_connections:
                with websocket_connections_lock:
                    connection_info = websocket_connections.pop(session_id, {})
                    active_connections = len(websocket_connections)
                username = connection_info.get('username', 'unknown')
                logger.info(
                    'Cleaning stale WebSocket connection: sid=%s user=%s active_connections=%s',
                    session_id[:8],
                    username,
                    active_connections,
                )
                # Disconnect the client
                socketio_disconnect(session_id)
            
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
