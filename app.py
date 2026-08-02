#!/usr/bin/env python3
"""
DragonCP Web UI - Flask application initialization
Refactored version with modular architecture
"""

import importlib.util
import logging
import os
import sys
import time
from typing import Any, cast

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
from flask_socketio import SocketIO

from logging_setup import configure_logging, get_log_file_path

# Import configuration and managers
from config import DragonCPConfig, APP_VERSION
from ssh import SSHManager
from websocket import (
    register_websocket_handlers,
    set_settings_service as set_websocket_settings_service,
    start_cleanup_thread,
    websocket_connections,
)
from websocket import WEBSOCKET_TIMEOUT_MAX, WEBSOCKET_TIMEOUT_DEFAULT
from auth import require_auth

# Import models
from models import DatabaseManager
from models.webhook import RenameNotification

from env_flags import env_flag, test_mode_enabled

# Import services
from services import TransferCoordinator
from services.rename_service import RenameService
from services.simulation_service import SimulationService
from services.explore.service import ExploreService

# Import routes
from routes import (
    auth_bp, media_bp, transfers_bp, backups_bp, webhooks_bp, debug_bp, logs_bp,
    simulation_bp,
    init_media_routes, init_transfer_routes, init_backup_routes,
    explore_bp, init_explore_routes,
    init_webhook_routes, init_debug_routes, init_simulation_routes
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


# No local env_flag here. Every key in the env file is pushed into os.environ by
# the loop above before any flag is read, so a _early_config fallback would be
# unreachable - and a second parser is exactly the divergence that let
# TEST_MODE=true mean two different things. env_flags.env_flag is the reader.


def _socketio_verbose_logging_enabled() -> bool:
    return env_flag('SOCKETIO_VERBOSE_LOGGING', default=False) or env_flag('TEST_MODE', default=False) or env_flag('FLASK_DEBUG', default=False)


def _is_simple_websocket_available() -> bool:
    return importlib.util.find_spec('simple_websocket') is not None


# Redaction and the constant/variable boundary both live in
# `settings_registry.py` now, so there is one definition of "sensitive" rather
# than a marker list here and a different judgement in each route.


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
TEST_MODE_ENABLED = env_flag('TEST_MODE', default=False)
FLASK_DEBUG_ENABLED = env_flag('FLASK_DEBUG', default=False)

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
    'test_mode': TEST_MODE_ENABLED,
    'flask_debug': FLASK_DEBUG_ENABLED,
    'entrypoint': os.path.basename(sys.argv[0]) if sys.argv else 'unknown',
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

logger.info(
    'Runtime profile initialized: entrypoint=%s, test_mode=%s, flask_debug=%s, socketio_verbose_logging=%s',
    socketio_runtime_info['entrypoint'],
    socketio_runtime_info['test_mode'],
    socketio_runtime_info['flask_debug'],
    socketio_runtime_info['verbose_logging'],
)

if TEST_MODE_ENABLED or FLASK_DEBUG_ENABLED:
    logger.warning(
        'Runtime is using development/test flags: test_mode=%s, flask_debug=%s',
        TEST_MODE_ENABLED,
        FLASK_DEBUG_ENABLED,
    )
else:
    logger.info('Runtime is using production-safe flags: test_mode=False, flask_debug=False')

if SOCKETIO_ASYNC_MODE == 'threading' and not SOCKETIO_WEBSOCKET_TRANSPORT_READY:
    logger.warning(
        'simple-websocket is not installed. Socket.IO will fall back to polling and websocket upgrades may fail until the dependency is installed.'
    )

# Initialize global objects
config = DragonCPConfig()
ssh_manager = None
db_manager = DatabaseManager()
transfer_coordinator = TransferCoordinator(config, db_manager, socketio)

# Settings read across both stores — the env file for what an installation is
# built with, the database for what an operator changes while running it. The
# coordinator owns it so every background service reads through the same one.
settings_service = transfer_coordinator.settings_service

# Copy any database-eligible values still sitting in the env file into the
# database, once. Without this, moving a setting across the boundary would
# change behaviour on the way over: the env value keeps working as a fallback
# until something is saved, then silently stops being the source of truth.
_adopted = settings_service.adopt_env_defaults()
if _adopted:
    logger.info(
        'Adopted %d setting(s) from the environment file into app settings: %s',
        len(_adopted), ', '.join(_adopted),
    )

# Initialize rename service
rename_model = RenameNotification(db_manager)
rename_service = RenameService(config, rename_model, socketio, transfer_coordinator.notification_service)

# The websocket cleanup thread enforces the idle timeout and has no request
# context, so it needs the settings service directly.
set_websocket_settings_service(settings_service)

# Register WebSocket handlers (with auth support)
register_websocket_handlers(socketio)
start_cleanup_thread(socketio)

# Initialize route dependencies
init_media_routes(config, ssh_manager, transfer_coordinator)
init_transfer_routes(config, transfer_coordinator)
init_backup_routes(transfer_coordinator)
init_webhook_routes(config, transfer_coordinator, rename_service)
init_debug_routes(config, ssh_manager, db_manager, transfer_coordinator, websocket_connections, socketio_runtime_info)

# Simulations run the real transfer pipeline against throwaway local files.
# Anything a previous process left behind is cleared before serving.
simulation_service = SimulationService(config, transfer_coordinator, socketio)
simulation_service.purge_leftovers()
init_simulation_routes(simulation_service)

# Explore compares the remote library against the local one and turns the
# difference into a reviewable plan. It holds its own pointer to the browse
# session because that session is rebuilt on every connect.
explore_service = ExploreService(config, db_manager, transfer_coordinator, ssh_manager)
init_explore_routes(explore_service)

# Register route blueprints
app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(media_bp, url_prefix='/api')
app.register_blueprint(transfers_bp, url_prefix='/api')
app.register_blueprint(backups_bp, url_prefix='/api')
app.register_blueprint(webhooks_bp, url_prefix='/api')
app.register_blueprint(debug_bp, url_prefix='/api')
app.register_blueprint(logs_bp, url_prefix='/api')
app.register_blueprint(simulation_bp, url_prefix='/api')
app.register_blueprint(explore_bp, url_prefix='/api')

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
    """
    Settings, on both sides of the boundary.

    GET returns every setting grouped, with `store` and `editable` on each, so
    the UI can show the environment-file half read-only and say where it comes
    from rather than offering a field that silently does nothing.

    POST writes only the database-backed half. Environment keys are refused BY
    NAME — the previous version accepted anything, wrote it to a per-browser
    session, and reported success for settings no background thread would ever
    read.
    """
    if request.method == 'GET':
        # The grouped payload for the React page, plus the flat key -> value map
        # the legacy static UI reads. That UI is still what production serves,
        # so it keeps working; it simply cannot change the env-backed half any
        # more, which was already true and merely invisible before.
        return jsonify({
            "status": "success",
            **settings_service.flat(),
            **settings_service.describe(),
        })

    data = request.json or {}
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "Invalid configuration payload"}), 400

    saved, refused, errors = settings_service.set_many(data)
    if errors:
        return jsonify({"status": "error", "message": "; ".join(errors)}), 400

    message = f"Saved {len(saved)} setting(s)" if saved else "Nothing to save"
    if refused:
        message += (
            f". {len(refused)} setting(s) come from the environment file and were "
            f"not changed: {', '.join(sorted(refused))}"
        )
    return jsonify({
        "status": "success",
        "message": message,
        "saved": sorted(saved),
        "refused": sorted(refused),
        **settings_service.describe(),
    })


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
    
    ssh_manager = SSHManager(
        host, username, password, key_path,
        host_key_policy=config.get("SSH_HOST_KEY_CHECKING", "accept-new"),
        known_hosts_file=config.get("SSH_KNOWN_HOSTS_FILE", ""),
    )
    if ssh_manager.connect():
        print("✅ SSH connection successful")
        session['ssh_connected'] = True
        
        # Update route dependencies with new ssh_manager
        init_media_routes(config, ssh_manager, transfer_coordinator)
        explore_service.set_ssh_manager(ssh_manager)
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
    explore_service.set_ssh_manager(ssh_manager)
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
    
    ssh_manager = SSHManager(
        host, username, password or '', key_path or '',
        host_key_policy=config.get("SSH_HOST_KEY_CHECKING", "accept-new"),
        known_hosts_file=config.get("SSH_KNOWN_HOSTS_FILE", ""),
    )
    if ssh_manager.connect():
        print("✅ Auto-connection successful")
        session['ssh_connected'] = True
        
        # Update route dependencies with new ssh_manager
        init_media_routes(config, ssh_manager, transfer_coordinator)
        explore_service.set_ssh_manager(ssh_manager)
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


@app.route('/api/config/env-only')
@require_auth
def api_env_config():
    """
    The environment-file half, flat. Read by the legacy static UI's comparison
    column, which contrasted the file against a per-browser overlay. There is no
    overlay now, so this is just the env-backed settings — which is what that
    column was showing all along.
    """
    return jsonify(settings_service.env_only())


@app.route('/api/config/reset', methods=['POST'])
@require_auth
def api_reset_config():
    """
    Kept for the legacy static UI, which has a "Reset to Env" button.

    There is nothing left to reset: the per-browser overlay it cleared is gone,
    so environment settings already ARE the environment values. Answering 200
    with an honest message keeps that page working without pretending an
    overlay was discarded.
    """
    return jsonify({
        "status": "success",
        "message": (
            "Environment settings are read directly from the file, so there is "
            "nothing to reset. Application settings are unchanged."
        ),
    })


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
    if test_mode_enabled():
        logger.info('TEST_MODE enabled: skipping template/static directory creation')
    else:
        os.makedirs('templates', exist_ok=True)
        os.makedirs('static', exist_ok=True)
    
    runtime_port = _get_runtime_port()
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    test_mode = test_mode_enabled()
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
