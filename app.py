#!/usr/bin/env python3
"""
DragonCP Web UI - Flask application initialization
Refactored version with modular architecture
"""

import importlib.util
import logging
import os
import time
from typing import Any, cast

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
from flask_socketio import SocketIO

from logging_setup import configure_logging, get_log_file_path

# Import configuration and managers
from config import DragonCPConfig, APP_VERSION
from ssh import SSHManager
from websocket import register_websocket_handlers, start_cleanup_thread, websocket_connections
from websocket import WEBSOCKET_TIMEOUT_MAX, WEBSOCKET_TIMEOUT_DEFAULT
from auth import require_auth, test_mode_or_auth

# Import models
from models import DatabaseManager
from models.webhook import RenameNotification

# Import services
from services import TransferCoordinator
from services.rename_service import RenameService

# Import routes
from routes import (
    auth_bp, media_bp, transfers_bp, backups_bp, webhooks_bp, debug_bp, logs_bp,
    init_media_routes, init_transfer_routes, init_backup_routes,
    init_webhook_routes, init_debug_routes
)


# ===== EARLY CONFIG LOADING =====

def _load_env_file_early() -> dict:
    """
    Load configuration from dragoncp_env.env or .env file early
    (before DragonCPConfig is instantiated) for Flask/SocketIO setup.
    """
    config = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    env_files = [
        os.path.join(script_dir, 'dragoncp_env.env'),
        os.path.join(script_dir, '.env'),
    ]
    
    for env_file in env_files:
        if os.path.exists(env_file):
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            config[key.strip()] = value.strip().strip('"').strip("'")
                break
            except Exception as e:
                print(f"⚠️  Error loading early config from {env_file}: {e}")
    
    return config


# Load early config for Flask/SocketIO setup
_early_config = _load_env_file_early()

# Expose early env-file values to process env before logging setup
for _config_key, _config_value in _early_config.items():
    os.environ.setdefault(_config_key, _config_value)

configure_logging()
LOG_FILE_PATH = get_log_file_path()
logger = logging.getLogger("dragoncp.app")

_early_secret_key = _early_config.get('SECRET_KEY') or os.environ.get('SECRET_KEY')
if not _early_secret_key:
    raise RuntimeError(
        "Missing SECRET_KEY. Set SECRET_KEY in dragoncp_env.env, .env, or environment."
    )


def get_cors_origins():
    """Get CORS allowed origins from config file"""
    cors_origins = _early_config.get('CORS_ORIGINS', '*')
    if cors_origins == '*':
        return '*'
    # Parse comma-separated origins
    origins = [origin.strip() for origin in cors_origins.split(',') if origin.strip()]
    return origins if origins else '*'


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        raw_value = _early_config.get(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _socketio_verbose_logging_enabled() -> bool:
    return _env_flag('SOCKETIO_VERBOSE_LOGGING', default=False) or _env_flag('TEST_MODE', default=False) or _env_flag('FLASK_DEBUG', default=False)


def _is_simple_websocket_available() -> bool:
    return importlib.util.find_spec('simple_websocket') is not None


REDACTED_VALUE = "<redacted>"
SENSITIVE_CONFIG_KEY_MARKERS = ("SECRET", "PASSWORD", "API_KEY", "TOKEN", "CLIENT_SECRET")


def _is_sensitive_config_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    key_upper = key.upper()
    return any(marker in key_upper for marker in SENSITIVE_CONFIG_KEY_MARKERS)


def sanitize_config_response(config_map: dict) -> dict:
    """
    Return a config map safe for API responses by redacting sensitive keys.
    """
    if not isinstance(config_map, dict):
        return {}

    sanitized = {}
    for key, value in config_map.items():
        if _is_sensitive_config_key(key):
            sanitized[key] = REDACTED_VALUE if value not in ("", None) else ""
        else:
            sanitized[key] = value
    return sanitized


def sanitize_config_update_payload(payload: dict, current_config: dict) -> dict:
    """
    Prevent redacted placeholders from being persisted back into config/session.
    """
    if not isinstance(payload, dict):
        return {}

    sanitized = {}
    for key, value in payload.items():
        if _is_sensitive_config_key(key) and value == REDACTED_VALUE:
            sanitized[key] = current_config.get(key, "")
        else:
            sanitized[key] = value
    return sanitized


# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = _early_secret_key
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['LOG_FILE_PATH'] = str(get_log_file_path())
app.logger.handlers.clear()
app.logger.propagate = True

# Get CORS origins
cors_origins = get_cors_origins()
logger.info("CORS allowed origins: %s", cors_origins)

SOCKETIO_ASYNC_MODE = 'threading'
SOCKETIO_PING_INTERVAL_SECONDS = 25
SOCKETIO_PING_TIMEOUT_SECONDS = 60
SOCKETIO_VERBOSE_LOGGING = _socketio_verbose_logging_enabled()
SOCKETIO_WEBSOCKET_TRANSPORT_READY = _is_simple_websocket_available()

# Initialize SocketIO with CORS configuration
socketio = SocketIO(
    app, 
    async_mode=SOCKETIO_ASYNC_MODE,
    cors_allowed_origins=cors_origins,
    ping_timeout=SOCKETIO_PING_TIMEOUT_SECONDS,
    ping_interval=SOCKETIO_PING_INTERVAL_SECONDS,
    logger=SOCKETIO_VERBOSE_LOGGING,
    engineio_logger=SOCKETIO_VERBOSE_LOGGING,
)

socketio_runtime_info = {
    'async_mode': SOCKETIO_ASYNC_MODE,
    'ping_interval_seconds': SOCKETIO_PING_INTERVAL_SECONDS,
    'ping_timeout_seconds': SOCKETIO_PING_TIMEOUT_SECONDS,
    'verbose_logging': SOCKETIO_VERBOSE_LOGGING,
    'websocket_transport_ready': SOCKETIO_WEBSOCKET_TRANSPORT_READY,
    'recommended_prod_server': 'gunicorn --config deploy/gunicorn.conf.py app:app',
}

logger.info(
    'Socket.IO runtime initialized: async_mode=%s, websocket_transport_ready=%s, ping_interval=%ss, ping_timeout=%ss, verbose_logging=%s',
    socketio_runtime_info['async_mode'],
    socketio_runtime_info['websocket_transport_ready'],
    socketio_runtime_info['ping_interval_seconds'],
    socketio_runtime_info['ping_timeout_seconds'],
    socketio_runtime_info['verbose_logging'],
)

if SOCKETIO_ASYNC_MODE == 'threading' and not SOCKETIO_WEBSOCKET_TRANSPORT_READY:
    logger.warning(
        'simple-websocket is not installed. Socket.IO will fall back to polling and websocket upgrades may fail until the dependency is installed.'
    )

# Initialize global objects
config = DragonCPConfig()
ssh_manager = None
db_manager = DatabaseManager()
transfer_coordinator = TransferCoordinator(config, db_manager, socketio)

# Initialize rename service
rename_model = RenameNotification(db_manager)
rename_service = RenameService(config, rename_model, socketio, transfer_coordinator.notification_service)

# Register WebSocket handlers (with auth support)
register_websocket_handlers(socketio)
start_cleanup_thread(socketio)

# Initialize route dependencies
init_media_routes(config, ssh_manager, transfer_coordinator)
init_transfer_routes(config, transfer_coordinator)
init_backup_routes(transfer_coordinator)
init_webhook_routes(config, transfer_coordinator, rename_service)
init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections, socketio_runtime_info)

# Register route blueprints
app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(media_bp, url_prefix='/api')
app.register_blueprint(transfers_bp, url_prefix='/api')
app.register_blueprint(backups_bp, url_prefix='/api')
app.register_blueprint(webhooks_bp, url_prefix='/api')
app.register_blueprint(debug_bp, url_prefix='/api')
app.register_blueprint(logs_bp, url_prefix='/api')

logger.info('Backend logging file: %s', LOG_FILE_PATH)


# ===== CORS HEADERS FOR PREFLIGHT =====

@app.before_request
def start_request_timer():
    """Track request latency for backend request logging."""
    g.request_started_at = time.perf_counter()

@app.after_request
def after_request(response):
    """Add CORS headers to all responses"""
    origin = request.headers.get('Origin')
    
    if cors_origins == '*':
        response.headers['Access-Control-Allow-Origin'] = '*'
    elif origin and (origin in cors_origins):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        # When echoing a specific origin, make cache behavior origin-aware.
        vary_values = [v.strip() for v in response.headers.get('Vary', '').split(',') if v.strip()]
        if 'Origin' not in vary_values:
            vary_values.append('Origin')
            response.headers['Vary'] = ', '.join(vary_values)
    
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'

    if not request.path.startswith('/static/'):
        request_started_at = getattr(g, 'request_started_at', None)
        elapsed_ms = -1
        if request_started_at is not None:
            elapsed_ms = int((time.perf_counter() - request_started_at) * 1000)
        if not request.path.startswith('/api/logs'):
            logging.getLogger('dragoncp.http').info(
                '%s %s -> %s (%sms)',
                request.method,
                request.path,
                response.status_code,
                elapsed_ms,
            )
    
    return response


# ===== CONTEXT PROCESSORS =====

@app.context_processor
def inject_app_version():
    """Inject APP_VERSION into all templates for cache busting"""
    return {'APP_VERSION': APP_VERSION}


# ===== SIMPLE ROUTES (non-blueprint) =====

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/api/config', methods=['GET', 'POST'])
@require_auth
def api_config():
    """Configuration API - Protected"""
    if request.method == 'GET':
        return jsonify(sanitize_config_response(config.get_all_config()))
    else:
        data = request.json or {}
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Invalid configuration payload"}), 400
        current_config = config.get_all_config()
        config.update_session_config(sanitize_config_update_payload(data, current_config))
        return jsonify({"status": "success", "message": "Configuration saved"})


@app.route('/api/connect', methods=['POST'])
@require_auth
def api_connect():
    """Connect to SSH server - Protected"""
    global ssh_manager
    
    print("🔌 API: /api/connect called")
    
    raw_data = request.get_json(silent=True)
    if raw_data is None:
        data: dict[str, Any] = {}
    elif not isinstance(raw_data, dict):
        return jsonify({"status": "error", "message": "Invalid JSON payload; expected an object"}), 400
    else:
        data = cast(dict[str, Any], raw_data)
    host = str(data.get('host') or '')
    username = str(data.get('username') or '')
    password = str(data.get('password') or '')
    key_path = str(data.get('key_path') or '')
    
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
        init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections, socketio_runtime_info)
        
        return jsonify({"status": "success", "message": "Connected successfully"})
    else:
        print("❌ SSH connection failed")
        return jsonify({"status": "error", "message": "Connection failed"})


@app.route('/api/disconnect', methods=['POST'])
@require_auth
def api_disconnect():
    """Disconnect from SSH server - Protected"""
    global ssh_manager
    
    if ssh_manager:
        ssh_manager.disconnect()
        ssh_manager = None
    
    session['ssh_connected'] = False
    
    # Update route dependencies
    init_media_routes(config, ssh_manager, transfer_coordinator)
    init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections, socketio_runtime_info)
    
    return jsonify({"status": "success", "message": "Disconnected"})


@app.route('/api/auto-connect')
@require_auth
def api_auto_connect():
    """Auto-connect using environment variables - Protected"""
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
    
    ssh_manager = SSHManager(host, username, password or '', key_path or '')
    if ssh_manager.connect():
        print("✅ Auto-connection successful")
        session['ssh_connected'] = True
        
        # Update route dependencies with new ssh_manager
        init_media_routes(config, ssh_manager, transfer_coordinator)
        init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections, socketio_runtime_info)
        
        return jsonify({"status": "success", "message": "Auto-connected successfully"})
    else:
        print("❌ Auto-connection failed")
        return jsonify({"status": "error", "message": "Auto-connection failed"})


@app.route('/api/ssh-config')
@require_auth
def api_ssh_config():
    """Get SSH configuration from environment - Protected"""
    remote_password = config.get("REMOTE_PASSWORD", "")
    ssh_config = {
        "host": config.get("REMOTE_IP", ""),
        "username": config.get("REMOTE_USER", ""),
        "key_path": config.get("SSH_KEY_PATH", ""),
        "has_password": bool(remote_password),
    }
    return jsonify(ssh_config)


@app.route('/api/config/reset', methods=['POST'])
@require_auth
def api_reset_config():
    """Reset session configuration to environment values - Protected"""
    if 'ui_config' in session:
        del session['ui_config']
    return jsonify({"status": "success", "message": "Configuration reset to environment values"})


@app.route('/api/config/env-only')
@require_auth
def api_env_config():
    """Get only environment configuration (without session overrides) - Protected"""
    return jsonify(sanitize_config_response(config.env_config))


# ===== TEST SIMULATION ENDPOINTS =====

@app.route('/api/test/simulate', methods=['POST'])
@test_mode_or_auth
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
@test_mode_or_auth
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

def _get_runtime_port() -> int:
    port_value = os.environ.get('PORT', '5000').strip()
    try:
        parsed_port = int(port_value)
    except ValueError:
        logger.warning('Invalid PORT value %r, defaulting to 5000', port_value)
        return 5000

    if not 1 <= parsed_port <= 65535:
        logger.warning('PORT %s is outside valid range, defaulting to 5000', parsed_port)
        return 5000

    return parsed_port

if __name__ == '__main__':
    # Create templates and static directories if they don't exist
    # Check TEST_MODE before creating app directories
    if os.environ.get('TEST_MODE', '0') == '1':
        logger.info('TEST_MODE enabled: skipping template/static directory creation')
    else:
        os.makedirs('templates', exist_ok=True)
        os.makedirs('static', exist_ok=True)
    
    runtime_port = _get_runtime_port()
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    test_mode = os.environ.get('TEST_MODE', '0') == '1'
    allow_unsafe_werkzeug = debug_mode or test_mode

    logger.info('DragonCP Web UI starting on port %s (debug=%s)', runtime_port, debug_mode)
    logger.info('Access the application at: http://localhost:%s', runtime_port)
    logger.info('Socket.IO runtime mode for direct startup: %s', SOCKETIO_ASYNC_MODE)

    if allow_unsafe_werkzeug:
        logger.info('allow_unsafe_werkzeug is enabled for local debug/test startup')
    else:
        logger.warning(
            'Direct python app.py startup is not the supported production path. Use the systemd + gunicorn service configuration for long-term production stability.'
        )
    
    socketio.run(
        app,
        host='0.0.0.0',
        port=runtime_port,
        debug=debug_mode,
        use_reloader=False,
        allow_unsafe_werkzeug=allow_unsafe_werkzeug,
    )
