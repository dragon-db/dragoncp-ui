#!/usr/bin/env python3
"""
DragonCP WebSocket Manager
WebSocket event handlers for real-time communication with authentication
"""

import time
import threading
from datetime import datetime, timedelta
from flask import request
from flask_socketio import disconnect as socketio_disconnect
from auth import validate_websocket_token


# WebSocket timeout configuration
WEBSOCKET_TIMEOUT_MIN = 5 * 60    # 5 minutes minimum
WEBSOCKET_TIMEOUT_MAX = 65 * 60   # 65 minutes maximum (5 minutes longer than max client timeout)
WEBSOCKET_TIMEOUT_DEFAULT = 35 * 60  # 35 minutes default


# WebSocket connection tracking
websocket_connections = {}


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
    except:
        return WEBSOCKET_TIMEOUT_DEFAULT


def register_websocket_handlers(socketio):
    """Register WebSocket event handlers with authentication"""
    
    @socketio.on('connect')
    def handle_connect(auth=None):
        """Handle WebSocket connection with authentication"""
        session_id = request.sid
        
        # Validate authentication token
        auth_data = auth or request.args.to_dict()
        username = validate_websocket_token(auth_data)
        
        if not username:
            print(f"🔒 WebSocket connection rejected - invalid or missing token: {session_id[:8]}...")
            # Reject the connection
            return False
        
        # Store connection with authenticated user info
        websocket_connections[session_id] = {
            'connected_at': datetime.now(),
            'last_activity': datetime.now(),
            'timeout_seconds': get_websocket_timeout_for_session(request.environ.get('flask.session', {})),
            'username': username
        }
        print(f"🔌 WebSocket connected: {session_id[:8]}... (user: {username})")
        print(f"🔌 Active WebSocket connections: {len(websocket_connections)}")
        
        return True

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle WebSocket disconnection"""
        session_id = request.sid
        connection_info = websocket_connections.get(session_id, {})
        username = connection_info.get('username', 'unknown')
        
        if session_id in websocket_connections:
            del websocket_connections[session_id]
        print(f"🔌 WebSocket disconnected: {session_id[:8]}... (user: {username})")
        print(f"🔌 Active WebSocket connections: {len(websocket_connections)}")

    @socketio.on('activity')
    def handle_activity():
        """Handle client activity ping"""
        session_id = request.sid
        if session_id in websocket_connections:
            websocket_connections[session_id]['last_activity'] = datetime.now()

    @socketio.on('authenticate')
    def handle_authenticate(data):
        """Handle re-authentication after token refresh"""
        session_id = request.sid
        
        if not data or not isinstance(data, dict):
            return {'success': False, 'message': 'Invalid auth data'}
        
        username = validate_websocket_token(data)
        
        if username:
            if session_id in websocket_connections:
                websocket_connections[session_id]['username'] = username
                websocket_connections[session_id]['last_activity'] = datetime.now()
            print(f"🔄 WebSocket re-authenticated: {session_id[:8]}... (user: {username})")
            return {'success': True, 'user': username}
        else:
            print(f"🔒 WebSocket re-authentication failed: {session_id[:8]}...")
            return {'success': False, 'message': 'Invalid token'}


def cleanup_stale_connections(socketio):
    """Cleanup stale WebSocket connections"""
    while True:
        try:
            current_time = datetime.now()
            
            stale_connections = []
            for session_id, connection_info in websocket_connections.items():
                # Get timeout for this specific session (stored when connection was made)
                session_timeout = connection_info.get('timeout_seconds', WEBSOCKET_TIMEOUT_DEFAULT)
                timeout_threshold = current_time - timedelta(seconds=session_timeout)
                
                if connection_info['last_activity'] < timeout_threshold:
                    stale_connections.append(session_id)
            
            for session_id in stale_connections:
                username = websocket_connections.get(session_id, {}).get('username', 'unknown')
                print(f"🧹 Cleaning up stale WebSocket connection: {session_id[:8]}... (user: {username})")
                if session_id in websocket_connections:
                    del websocket_connections[session_id]
                # Disconnect the client
                socketio.disconnect(session_id)
            
            if stale_connections:
                print(f"🧹 Cleaned up {len(stale_connections)} stale connections")
                print(f"🔌 Active WebSocket connections: {len(websocket_connections)}")
                
        except Exception as e:
            print(f"❌ Error in cleanup_stale_connections: {e}")
        
        # Sleep for 5 minutes before next cleanup
        time.sleep(5 * 60)


def start_cleanup_thread(socketio):
    """Start the WebSocket cleanup thread"""
    cleanup_thread = threading.Thread(target=cleanup_stale_connections, args=(socketio,), daemon=True)
    cleanup_thread.start()
    return cleanup_thread


def get_authenticated_connections():
    """Get list of authenticated WebSocket connections"""
    return {
        sid: {
            'username': info.get('username'),
            'connected_at': info.get('connected_at').isoformat() if info.get('connected_at') else None,
            'last_activity': info.get('last_activity').isoformat() if info.get('last_activity') else None
        }
        for sid, info in websocket_connections.items()
    }
