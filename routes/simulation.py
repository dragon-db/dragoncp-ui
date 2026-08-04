#!/usr/bin/env python3
"""
DragonCP Simulation Routes

Endpoints for running the transfer pipeline against throwaway local files.

SECURITY: simulations only ever read and write inside the app's simulation
directory, and only ever delete rows carrying the is_simulation flag. Scenario
names are looked up in a fixed table rather than used to build paths, so nothing
from the request reaches the filesystem. See services/simulation_service.py.
"""

from flask import Blueprint, jsonify, request
from activity_log import record
from auth import require_auth

simulation_bp = Blueprint('simulation', __name__)

# Global reference to be set by app.py
simulation_service = None


def init_simulation_routes(app_simulation_service):
    """Initialize route dependencies"""
    global simulation_service
    simulation_service = app_simulation_service


@simulation_bp.route('/simulation/status')
@require_auth
def api_simulation_status():
    """Available scenarios, what is on the board, and whether real work is running"""
    try:
        return jsonify({"status": "success", **simulation_service.status()})
    except Exception as e:
        print(f"❌ Error reading simulation status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@simulation_bp.route('/simulation/start', methods=['POST'])
@require_auth
def api_simulation_start():
    """
    Start a simulation.

    Simulations share the real queue on purpose - that is the only way queueing
    can be observed - so the caller must acknowledge when genuine transfers are
    running by passing confirm_busy.
    """
    try:
        payload = request.json or {}
        scenario = payload.get('scenario')
        if not scenario:
            return jsonify({"status": "error", "message": "No scenario given"}), 400

        busy = simulation_service.running_real_transfers()
        if busy and not payload.get('confirm_busy'):
            return jsonify({
                "status": "error",
                "code": "real_transfers_running",
                "message": (
                    f"{len(busy)} real transfer(s) are running. A simulation takes a "
                    f"queue slot and may delay them."
                ),
                "running": [
                    {
                        "id": t['transfer_id'],
                        "title": t.get('parsed_title') or t.get('folder_name'),
                        "status": t['status'],
                    }
                    for t in busy
                ],
            }), 409

        started, message, detail = simulation_service.start(scenario)
        if not started:
            return jsonify({"status": "error", "message": message}), 400

        record('simulation.start', f"Started the {scenario} simulation",
               target_type='simulation', target_id=scenario)
        return jsonify({"status": "success", "message": message, **detail})
    except Exception as e:
        print(f"❌ Error starting simulation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@simulation_bp.route('/simulation/stop', methods=['POST'])
@require_auth
def api_simulation_stop():
    """Stop anything still moving, keeping the rows so the result can be read"""
    try:
        stopped = simulation_service.stop()
        record('simulation.stop', 'Stopped the running simulation', target_type='simulation')
        return jsonify({
            "status": "success",
            "message": f"Stopped {stopped} simulation transfer(s)",
            "stopped": stopped,
        })
    except Exception as e:
        print(f"❌ Error stopping simulation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@simulation_bp.route('/simulation/cleanup', methods=['POST'])
@require_auth
def api_simulation_cleanup():
    """Remove every simulation row and the files it generated"""
    try:
        result = simulation_service.cleanup()
        record('simulation.cleanup', 'Cleared the simulation data', target_type='simulation')
        return jsonify({
            "status": "success",
            "message": (
                f"Cleared {result['transfers_removed']} transfer(s) and "
                f"{result['notifications_removed']} notification(s)"
            ),
            **result,
        })
    except Exception as e:
        print(f"❌ Error clearing simulation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
