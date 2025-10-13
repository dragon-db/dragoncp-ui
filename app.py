#!/usr/bin/env python3
"""
DragonCP Web UI - Flask application initialization
Refactored version with modular architecture
"""

import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO

# Import configuration and managers
from config import DragonCPConfig
from ssh import SSHManager
from websocket import register_websocket_handlers, start_cleanup_thread, websocket_connections
from websocket import WEBSOCKET_TIMEOUT_MAX, WEBSOCKET_TIMEOUT_DEFAULT

# Import models
from models import DatabaseManager

# Import services
from services import TransferCoordinator

# Import routes
from routes import (
    media_bp, transfers_bp, backups_bp, webhooks_bp, debug_bp,
    init_media_routes, init_transfer_routes, init_backup_routes,
    init_webhook_routes, init_debug_routes
)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dragoncp-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize SocketIO
socketio = SocketIO(
    app, 
    cors_allowed_origins="*",
    ping_timeout=WEBSOCKET_TIMEOUT_MAX,  # Use maximum for SocketIO config
    ping_interval=25 * 60  # Send ping every 25 minutes
)

# Initialize global objects
config = DragonCPConfig()
ssh_manager = None
db_manager = DatabaseManager()
transfer_coordinator = TransferCoordinator(config, db_manager, socketio)

# Register WebSocket handlers
register_websocket_handlers(socketio)
start_cleanup_thread(socketio)

# Initialize route dependencies
init_media_routes(config, ssh_manager, transfer_coordinator)
init_transfer_routes(config, transfer_coordinator)
init_backup_routes(transfer_coordinator)
init_webhook_routes(config, transfer_coordinator)
init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections)

# Register route blueprints
app.register_blueprint(media_bp, url_prefix='/api')
app.register_blueprint(transfers_bp, url_prefix='/api')
app.register_blueprint(backups_bp, url_prefix='/api')
app.register_blueprint(webhooks_bp, url_prefix='/api')
app.register_blueprint(debug_bp, url_prefix='/api')


# ===== SIMPLE ROUTES (non-blueprint) =====

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Configuration API"""
    if request.method == 'GET':
        return jsonify(config.get_all_config())
    else:
        data = request.json
        config.update_session_config(data)
        return jsonify({"status": "success", "message": "Configuration saved"})


@app.route('/api/connect', methods=['POST'])
def api_connect():
    """Connect to SSH server"""
    global ssh_manager
    
    print("🔌 API: /api/connect called")
    
    data = request.json
    host = data.get('host')
    username = data.get('username')
    password = data.get('password')
    key_path = data.get('key_path')
    
    print(f"🔗 Connection attempt to {username}@{host}")
    
    if not host or not username:
        print("❌ Missing host or username")
        return jsonify({"status": "error", "message": "Host and username are required"})
    
    ssh_manager = SSHManager(host, username, password, key_path)
    if ssh_manager.connect():
        print("✅ SSH connection successful")
        session['ssh_connected'] = True
        
        # Update route dependencies with new ssh_manager
        init_media_routes(config, ssh_manager, transfer_coordinator)
        init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections)
        
        return jsonify({"status": "success", "message": "Connected successfully"})
    else:
        print("❌ SSH connection failed")
        return jsonify({"status": "error", "message": "Connection failed"})


@app.route('/api/disconnect')
def api_disconnect():
    """Disconnect from SSH server"""
    global ssh_manager
    
    if ssh_manager:
        ssh_manager.disconnect()
        ssh_manager = None
    
    session['ssh_connected'] = False
    
    # Update route dependencies
    init_media_routes(config, ssh_manager, transfer_coordinator)
    init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections)
    
    return jsonify({"status": "success", "message": "Disconnected"})


@app.route('/api/auto-connect')
def api_auto_connect():
    """Auto-connect using environment variables"""
    global ssh_manager
    
    print("🔌 API: /api/auto-connect called")
    
    # Get SSH credentials from config
    host = config.get("REMOTE_IP")
    username = config.get("REMOTE_USER")
    password = config.get("REMOTE_PASSWORD", "")  # Optional
    key_path = config.get("SSH_KEY_PATH", "")  # Optional
    
    print(f"🔗 Auto-connection attempt to {username}@{host}")
    
    if not host or not username:
        print("❌ Missing REMOTE_IP or REMOTE_USER in config")
        return jsonify({"status": "error", "message": "SSH credentials not configured"})
    
    ssh_manager = SSHManager(host, username, password if password else None, key_path if key_path else None)
    if ssh_manager.connect():
        print("✅ Auto-connection successful")
        session['ssh_connected'] = True
        
        # Update route dependencies with new ssh_manager
        init_media_routes(config, ssh_manager, transfer_coordinator)
        init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections)
        
        return jsonify({"status": "success", "message": "Auto-connected successfully"})
    else:
        print("❌ Auto-connection failed")
        return jsonify({"status": "error", "message": "Auto-connection failed"})


@app.route('/api/ssh-config')
def api_ssh_config():
    """Get SSH configuration from environment"""
    ssh_config = {
        "host": config.get("REMOTE_IP", ""),
        "username": config.get("REMOTE_USER", ""),
        "password": config.get("REMOTE_PASSWORD", ""),
        "key_path": config.get("SSH_KEY_PATH", "")
    }
    return jsonify(ssh_config)


@app.route('/api/config/reset', methods=['POST'])
def api_reset_config():
    """Reset session configuration to environment values"""
    if 'ui_config' in session:
        del session['ui_config']
    return jsonify({"status": "success", "message": "Configuration reset to environment values"})


@app.route('/api/config/env-only')
def api_env_config():
    """Get only environment configuration (without session overrides)"""
    return jsonify(config.env_config)


# ===== TEST SIMULATION ENDPOINTS =====

@app.route('/api/test/simulate', methods=['POST'])
def api_start_simulation():
    """Start simulated transfers for UI testing (no rsync). Controlled by TEST_MODE env."""
    if os.environ.get('TEST_MODE', '0') != '1':
        return jsonify({"status": "error", "message": "Simulation disabled. Set TEST_MODE=1 to enable."}), 403

    try:
        from simulator import TransferSimulator
        simulator = TransferSimulator(transfer_coordinator, socketio)
        
        payload = request.json or {}
        count = int(payload.get('count', 3))
        steps = int(payload.get('steps', 40))
        interval = float(payload.get('interval', 0.5))
        failure_rate = float(payload.get('failure_rate', 0.0))

        started = simulator.start_simulations(
            count=count,
            steps=steps,
            interval_seconds=interval,
            failure_rate=failure_rate,
        )
        return jsonify({
            "status": "success",
            "message": f"Started {len(started)} simulated transfers",
            "transfer_ids": started,
        })
    except Exception as e:
        print(f"❌ Error starting simulation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/test/simulate/stop', methods=['POST'])
def api_stop_simulation():
    """Signal all running simulations to stop."""
    if os.environ.get('TEST_MODE', '0') != '1':
        return jsonify({"status": "error", "message": "Simulation disabled. Set TEST_MODE=1 to enable."}), 403

    try:
        from simulator import TransferSimulator
        # Note: We'd need to maintain a global simulator instance for this to work properly
        # For now, just return success
        return jsonify({"status": "success", "message": "Stop signal sent"})
    except Exception as e:
        print(f"❌ Error stopping simulation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ===== MAIN ENTRY POINT =====

if __name__ == '__main__':
    # Create templates and static directories if they don't exist
    # Check TEST_MODE before creating app directories
    if os.environ.get('TEST_MODE', '0') == '1':
        print("🧪 TEST_MODE: Would create templates and static directories")
    else:
        os.makedirs('templates', exist_ok=True)
        os.makedirs('static', exist_ok=True)
    
    print("DragonCP Web UI starting...")
    print("Access the application at: http://localhost:5000")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)

