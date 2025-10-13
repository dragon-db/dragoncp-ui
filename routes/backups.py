#!/usr/bin/env python3
"""
DragonCP Backup Routes
Handles backup operations: list, get, restore, delete, plan, reindex
"""

from flask import Blueprint, jsonify, request

backups_bp = Blueprint('backups', __name__)

# Global references to be set by app.py
transfer_coordinator = None


def init_backup_routes(app_transfer_coordinator):
    """Initialize route dependencies"""
    global transfer_coordinator
    transfer_coordinator = app_transfer_coordinator


@backups_bp.route('/backups')
def api_list_backups():
    """List transfer backups."""
    try:
        limit = request.args.get('limit', 100, type=int)
        include_deleted = request.args.get('include_deleted', '0') in ('1', 'true', 'True')
        backups = transfer_coordinator.backup_model.get_all(limit=limit, include_deleted=include_deleted)
        return jsonify({
            "status": "success",
            "backups": backups,
            "total": len(backups)
        })
    except Exception as e:
        print(f"❌ Error listing backups: {e}")
        return jsonify({"status": "error", "message": f"Failed to list backups: {str(e)}"}), 500


@backups_bp.route('/backups/<backup_id>')
def api_get_backup(backup_id):
    """Get backup details."""
    try:
        backup = transfer_coordinator.backup_model.get(backup_id)
        if not backup:
            return jsonify({"status": "error", "message": "Backup not found"}), 404
        return jsonify({"status": "success", "backup": backup})
    except Exception as e:
        print(f"❌ Error getting backup {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to get backup: {str(e)}"}), 500


@backups_bp.route('/backups/<backup_id>/files')
def api_get_backup_files(backup_id):
    """List files inside a backup."""
    try:
        limit = request.args.get('limit', type=int)
        files = transfer_coordinator.backup_model.get_files(backup_id, limit=limit)
        return jsonify({"status": "success", "files": files, "total": len(files)})
    except Exception as e:
        print(f"❌ Error getting backup files {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to get backup files: {str(e)}"}), 500


@backups_bp.route('/backups/<backup_id>/restore', methods=['POST'])
def api_restore_backup(backup_id):
    """Restore a backup (optionally selected files)."""
    try:
        payload = request.json or {}
        files = payload.get('files')
        if files and not isinstance(files, list):
            return jsonify({"status": "error", "message": "'files' must be a list of relative paths"}), 400
        ok, msg = transfer_coordinator.restore_backup(backup_id, files)
        if ok:
            return jsonify({"status": "success", "message": msg})
        else:
            return jsonify({"status": "error", "message": msg}), 400
    except Exception as e:
        print(f"❌ Error restoring backup {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to restore backup: {str(e)}"}), 500


@backups_bp.route('/backups/<backup_id>/delete', methods=['POST'])
def api_delete_backup(backup_id):
    """Delete a backup record and optionally remove backup files from disk."""
    try:
        payload = request.json or {}
        # Independent delete options: delete_record and delete_files
        delete_record = bool(payload.get('delete_record', True))
        delete_files = bool(payload.get('delete_files', False))
        # Use new granular delete
        ok, msg = transfer_coordinator.delete_backup_options(backup_id, delete_record=delete_record, delete_files=delete_files)
        if ok:
            return jsonify({"status": "success", "message": msg})
        else:
            return jsonify({"status": "error", "message": msg}), 400
    except Exception as e:
        print(f"❌ Error deleting backup {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to delete backup: {str(e)}"}), 500


@backups_bp.route('/backups/<backup_id>/plan', methods=['POST'])
def api_plan_backup_restore(backup_id):
    """Dry-run plan for context-aware restore. Optionally accept 'files' list."""
    try:
        payload = request.json or {}
        files = payload.get('files')
        if files and not isinstance(files, list):
            return jsonify({"status": "error", "message": "'files' must be a list of relative paths"}), 400
        plan = transfer_coordinator.plan_context_restore(backup_id, files)
        return jsonify({"status": "success", "plan": plan})
    except Exception as e:
        print(f"❌ Error planning restore for {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to plan restore: {str(e)}"}), 500


@backups_bp.route('/backups/reindex', methods=['POST'])
def api_reindex_backups():
    """Scan BACKUP_PATH for existing backup folders and import missing ones."""
    try:
        imported, skipped = transfer_coordinator.reindex_backups()
        return jsonify({
            "status": "success",
            "message": f"Imported {imported} backups, skipped {skipped}.",
            "imported": imported,
            "skipped": skipped
        })
    except Exception as e:
        print(f"❌ Error reindexing backups: {e}")
        return jsonify({"status": "error", "message": f"Failed to reindex backups: {str(e)}"}), 500

