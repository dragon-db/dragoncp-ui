#!/usr/bin/env python3
"""
DragonCP Remote Transfer Server Routes

Installing, controlling and inspecting the transfer server that runs on the
remote host. Every one of these is an administrative action on another machine,
so every one is recorded on the activity screen.

SECURITY: the address permitted to reach the transfer server is never returned
by any endpoint here. `status` reports only whether one is set and whether it
still matches where we appear to be connecting from — which is everything the
panel needs to be useful, and nothing a reader could take away. `detect` is the
one exception and it is deliberate: it exists so an operator can read their own
current address in order to configure it, and it is admin-only like the rest.
"""

from flask import Blueprint, jsonify, request

from activity_log import record, record_failure
from auth import require_auth
from services.remote_daemon import RemoteDaemonError

remote_daemon_bp = Blueprint('remote_daemon', __name__)

# Global reference to be set by app.py
remote_daemon_service = None


def init_remote_daemon_routes(service):
    """Initialize route dependencies"""
    global remote_daemon_service
    remote_daemon_service = service


def _unavailable():
    return jsonify({
        'status': 'error',
        'message': 'The transfer server is not available in this installation',
    }), 503


def _action(name: str, summary: str, run):
    """
    Run one control action and report it the same way every time.

    Shared so that a new action cannot accidentally skip the activity record —
    these change the state of another machine, and an unrecorded one is the kind
    of thing nobody notices until they are trying to work out what happened.
    """
    if remote_daemon_service is None:
        return _unavailable()
    try:
        ok, message = run()
    except RemoteDaemonError as error:
        record_failure(f'remote_transfer.{name}', f"{summary} failed: {error}")
        return jsonify({'status': 'error', 'message': str(error)}), 400
    except Exception as error:  # noqa: BLE001
        print(f"❌ Remote transfer server: {name} failed: {error}")
        record_failure(f'remote_transfer.{name}', f"{summary} failed")
        return jsonify({'status': 'error', 'message': str(error)}), 500

    if ok:
        record(f'remote_transfer.{name}', summary)
    else:
        record_failure(f'remote_transfer.{name}', f"{summary} failed: {message}")
    return jsonify({
        'status': 'success' if ok else 'error',
        'message': message,
    }), (200 if ok else 400)


@remote_daemon_bp.route('/remote-transfer/status')
@require_auth
def api_remote_transfer_status():
    """Whether it is configured, installed, running, and willing to talk to us"""
    if remote_daemon_service is None:
        return _unavailable()
    try:
        refresh = request.args.get('refresh', '1') not in ('0', 'false', 'no')
        return jsonify({'status': 'success', 'server': remote_daemon_service.status(refresh)})
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error reading remote transfer server status: {error}")
        return jsonify({'status': 'error', 'message': str(error)}), 500


@remote_daemon_bp.route('/remote-transfer/install', methods=['POST'])
@require_auth
def api_remote_transfer_install():
    """Generate everything, push it, register the service and start it"""
    return _action('install', 'Installed the remote transfer server',
                   lambda: remote_daemon_service.install())


@remote_daemon_bp.route('/remote-transfer/start', methods=['POST'])
@require_auth
def api_remote_transfer_start():
    return _action('start', 'Started the remote transfer server',
                   lambda: remote_daemon_service.start())


@remote_daemon_bp.route('/remote-transfer/stop', methods=['POST'])
@require_auth
def api_remote_transfer_stop():
    return _action('stop', 'Stopped the remote transfer server',
                   lambda: remote_daemon_service.stop())


@remote_daemon_bp.route('/remote-transfer/restart', methods=['POST'])
@require_auth
def api_remote_transfer_restart():
    return _action('restart', 'Restarted the remote transfer server',
                   lambda: remote_daemon_service.restart())


@remote_daemon_bp.route('/remote-transfer/uninstall', methods=['POST'])
@require_auth
def api_remote_transfer_uninstall():
    """Stop it and remove everything this application put on the remote host"""
    return _action('uninstall', 'Removed the remote transfer server',
                   lambda: remote_daemon_service.uninstall())


@remote_daemon_bp.route('/remote-transfer/rotate-password', methods=['POST'])
@require_auth
def api_remote_transfer_rotate_password():
    """
    Generate a new password and push it.

    Reinstalling is what applies it, so the two are done together — a rotation
    that changed only this side would leave the transfer server refusing every
    transfer until somebody worked out why.
    """
    if remote_daemon_service is None:
        return _unavailable()

    def run():
        remote_daemon_service.rotate_password()
        return remote_daemon_service.install()

    return _action('rotate_password', 'Changed the remote transfer server password', run)


@remote_daemon_bp.route('/remote-transfer/detect-address')
@require_auth
def api_remote_transfer_detect_address():
    """
    Ask the remote host which address this application appears to connect from.

    Exists so the allowed address never has to be looked up on a third-party
    site or guessed. It is returned to the admin who asked and is not stored or
    logged.

    Deliberately NOT recorded on the activity screen. It changes nothing, and
    this application's rule is that reads are nobody's business to answer for —
    recording them buries the actions that matter.
    """
    if remote_daemon_service is None:
        return _unavailable()
    try:
        address = remote_daemon_service.detect_address()
    except RemoteDaemonError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    except Exception as error:  # noqa: BLE001
        print(f"❌ Could not detect the connecting address: {error}")
        return jsonify({'status': 'error', 'message': str(error)}), 500

    return jsonify({
        'status': 'success',
        'address': address,
        'matches_configured': address == remote_daemon_service.allowed_address,
        'configured': bool(remote_daemon_service.allowed_address),
    })
