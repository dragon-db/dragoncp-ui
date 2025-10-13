#!/usr/bin/env python3
"""
DragonCP WebSocket Manager
WebSocket event handlers for real-time communication
"""

import time
import threading
from datetime import datetime, timedelta
from flask import request


# WebSocket timeout configuration
WEBSOCKET_TIMEOUT_MIN = 5 * 60    # 5 minutes minimum
WEBSOCKET_TIMEOUT_MAX = 65 * 60   # 65 minutes maximum (5 minutes longer than max client timeout)
WEBSOCKET_TIMEOUT_DEFAULT = 35 * 60  # 35 minutes default


# WebSocket connection tracking
websocket_connections = {}


def get_websocket_timeout_for_session(session):
    """Get WebSocket timeout for current session, respecting user configuration"""
    try:
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
    """Register WebSocket event handlers"""
    
    @socketio.on('connect')
    def handle_connect():
        """Handle WebSocket connection"""
        session_id = request.sid
        websocket_connections[session_id] = {
            'connected_at': datetime.now(),
            'last_activity': datetime.now(),
            'timeout_seconds': get_websocket_timeout_for_session(request.environ.get('flask.session', {}))  # Store timeout for this session
        }
        print(f"🔌 WebSocket connected: {session_id}")
        print(f"🔌 Active WebSocket connections: {len(websocket_connections)}")

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle WebSocket disconnection"""
        session_id = request.sid
        if session_id in websocket_connections:
            del websocket_connections[session_id]
        print(f"🔌 WebSocket disconnected: {session_id}")
        print(f"🔌 Active WebSocket connections: {len(websocket_connections)}")

    @socketio.on('activity')
    def handle_activity():
        """Handle client activity ping"""
        session_id = request.sid
        if session_id in websocket_connections:
            websocket_connections[session_id]['last_activity'] = datetime.now()


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
                print(f"🧹 Cleaning up stale WebSocket connection: {session_id}")
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

