#!/usr/bin/env python3
"""
DragonCP Transfer Routes
Handles transfer operations: start, status, cancel, restart, delete, cleanup

SECURITY: All path components from POST body data (folder_name, season_name,
episode_name) are validated through security.validate_path_component() before
being used to construct filesystem paths. This prevents path traversal attacks.
See security.py for the validation implementation.
"""

import time
from flask import Blueprint, jsonify, request
from auth import require_auth
from security import validate_path_component, assert_path_within_bounds, PathTraversalError

transfers_bp = Blueprint('transfers', __name__)

# Global references to be set by app.py
config = None
transfer_coordinator = None


def init_transfer_routes(app_config, app_transfer_coordinator):
    """Initialize route dependencies"""
    global config, transfer_coordinator
    config = app_config
    transfer_coordinator = app_transfer_coordinator


@transfers_bp.route('/transfer', methods=['POST'])
@require_auth
def api_transfer():
    """Start a transfer"""
    try:
        data = request.json
        operation_type = data.get('type', 'folder')  # 'folder' or 'file'
        media_type = data.get('media_type')
        folder_name = data.get('folder_name')
        season_name = data.get('season_name')
        episode_name = data.get('episode_name')
        
        print(f"🔄 Transfer request: {data}")
        
        if not media_type or not folder_name:
            print("❌ Missing media_type or folder_name")
            return jsonify({"status": "error", "message": "Media type and folder name are required"})

        # SECURITY: Validate all path components from POST body to prevent
        # directory traversal. Each component must be a single path segment
        # without "..", "/", "\", or null bytes. See security.py.
        if not validate_path_component(folder_name):
            return jsonify({"status": "error", "message": "Invalid folder name"}), 400
        if season_name and not validate_path_component(season_name):
            return jsonify({"status": "error", "message": "Invalid season name"}), 400
        if episode_name and not validate_path_component(episode_name):
            return jsonify({"status": "error", "message": "Invalid episode name"}), 400

        # Get source path from config
        source_path_map = {
            "movies": config.get("MOVIE_PATH"),
            "tvshows": config.get("TVSHOW_PATH"),
            "anime": config.get("ANIME_PATH")
        }
        
        # Get destination path from config
        dest_path_map = {
            "movies": config.get("MOVIE_DEST_PATH"),
            "tvshows": config.get("TVSHOW_DEST_PATH"),
            "anime": config.get("ANIME_DEST_PATH")
        }
        
        base_source = source_path_map.get(media_type)
        base_dest = dest_path_map.get(media_type)
        
        print(f"📁 Base source path for {media_type}: {base_source}")
        print(f"📁 Base destination path for {media_type}: {base_dest}")
        
        if not base_source:
            print(f"❌ Source path not configured for {media_type}")
            return jsonify({"status": "error", "message": f"Source path not configured for {media_type}"})
        
        if not base_dest:
            print(f"❌ Destination path not configured for {media_type}")
            return jsonify({"status": "error", "message": f"Destination path not configured for {media_type}"})
        
        # Construct source path (folder/season)
        source_path = f"{base_source}/{folder_name}"
        if season_name:
            source_path = f"{source_path}/{season_name}"

        # Construct destination path (folder/season)
        dest_path = f"{base_dest}/{folder_name}"
        if season_name:
            dest_path = f"{dest_path}/{season_name}"

        # True single-episode transfer semantics: type=file + episode_name
        if operation_type == 'file':
            if not episode_name:
                return jsonify({
                    "status": "error",
                    "message": "episode_name is required when type=file"
                }), 400
            source_path = f"{source_path}/{episode_name}"
            dest_path = f"{dest_path}/{episode_name}"
        
        # SECURITY: Resolve dest_path to its real absolute path and verify it
        # stays within base_dest. Component validation above prevents literal
        # traversal, but this catches symlink-based escapes.
        try:
            assert_path_within_bounds(dest_path, [base_dest])
        except PathTraversalError:
            return jsonify({"status": "error", "message": "Destination path escapes configured boundary"}), 400

        print(f"📁 Final source path: {source_path}")
        print(f"📁 Final destination path: {dest_path}")

        # Generate transfer ID
        transfer_id = f"transfer_{int(time.time())}"
        
        # Start transfer
        print(f"🚀 Starting transfer with ID: {transfer_id}")
        print(f"📋 Transfer parameters:")
        print(f"   - media_type: {media_type}")
        print(f"   - folder_name: {folder_name}")
        print(f"   - season_name: {season_name}")
        print(f"   - episode_name: {episode_name}")
        print(f"   - operation_type: {operation_type}")

        try:
            transfer_started, transfer_state = transfer_coordinator.start_transfer(
                transfer_id, 
                source_path, 
                dest_path, 
                operation_type,
                media_type,
                folder_name,
                season_name
            )
            
            if transfer_started:
                print(f"✅ Transfer {transfer_id} started successfully")
                # Verify the transfer was created in database
                db_transfer = transfer_coordinator.get_transfer_status(transfer_id)
                if db_transfer:
                    print(f"✅ Transfer {transfer_id} found in database with status: {db_transfer['status']}")
                else:
                    print(f"❌ Transfer {transfer_id} NOT found in database!")
                
                return jsonify({
                    "status": "success", 
                    "transfer_id": transfer_id,
                    "transfer_state": transfer_state,
                    "message": "Transfer started" if transfer_state == "running" else "Transfer queued",
                    "source": source_path,
                    "destination": dest_path,
                    "episode_name": episode_name
                })
            else:
                print(f"❌ Failed to start transfer {transfer_id}")
                return jsonify({
                    "status": "error",
                    "message": f"Failed to start transfer: {transfer_state}"
                })
                
        except Exception as e:
            print(f"❌ Exception starting transfer {transfer_id}: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"Exception starting transfer: {str(e)}"})
            
    except Exception as e:
        print(f"❌ Error in api_transfer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Internal server error: {str(e)}"})


@transfers_bp.route('/transfer/<transfer_id>/status')
@require_auth
def api_transfer_status(transfer_id):
    """Get transfer status"""
    transfer = transfer_coordinator.get_transfer_status(transfer_id)
    if transfer:
        return jsonify({
            "status": "success",
            "transfer": {
                "id": transfer_id,
                "status": transfer["status"],
                "progress": transfer["progress"],
                "logs": transfer["logs"],
                "log_count": len(transfer["logs"]),
                "start_time": transfer["start_time"],
                "end_time": transfer.get("end_time"),
                "media_type": transfer["media_type"],
                "folder_name": transfer["folder_name"],
                "season_name": transfer.get("season_name"),
                "parsed_title": transfer.get("parsed_title"),
                "parsed_season": transfer.get("parsed_season"),
                "operation_type": transfer["operation_type"],
                "source_path": transfer["source_path"],
                "dest_path": transfer["dest_path"]
            }
        })
    else:
        return jsonify({"status": "error", "message": "Transfer not found"})


@transfers_bp.route('/transfer/<transfer_id>/cancel', methods=['POST'])
@require_auth
def api_cancel_transfer(transfer_id):
    """Cancel a transfer"""
    success = transfer_coordinator.cancel_transfer(transfer_id)
    if success:
        return jsonify({"status": "success", "message": "Transfer cancelled"})
    else:
        return jsonify({"status": "error", "message": "Failed to cancel transfer"})


@transfers_bp.route('/transfer/<transfer_id>/logs')
@require_auth
def api_transfer_logs(transfer_id):
    """Get full logs for a transfer"""
    transfer = transfer_coordinator.get_transfer_status(transfer_id)
    if transfer:
        return jsonify({
            "status": "success",
            "logs": transfer["logs"],
            "log_count": len(transfer["logs"]),
            "transfer_status": transfer["status"]
        })
    else:
        return jsonify({"status": "error", "message": "Transfer not found"})


@transfers_bp.route('/transfers/all')
@require_auth
def api_all_transfers():
    """Get all transfers with optional filtering"""
    try:
        limit = request.args.get('limit', 50, type=int)
        status_filter = request.args.get('status')
        
        transfers = transfer_coordinator.get_all_transfers(limit=limit)
        
        # Apply status filter if provided
        if status_filter:
            transfers = [t for t in transfers if t['status'] == status_filter]
        
        # Format transfers for response
        formatted_transfers = []
        for transfer in transfers:
            formatted_transfer = {
                "id": transfer["transfer_id"],
                "status": transfer["status"],
                "progress": transfer["progress"],
                "media_type": transfer["media_type"],
                "folder_name": transfer["folder_name"],
                "season_name": transfer.get("season_name"),
                "parsed_title": transfer.get("parsed_title"),
                "parsed_season": transfer.get("parsed_season"),
                "operation_type": transfer["operation_type"],
                "source_path": transfer["source_path"],
                "dest_path": transfer["dest_path"],
                "start_time": transfer["start_time"],
                "end_time": transfer.get("end_time"),
                "created_at": transfer["created_at"],
                "log_count": len(transfer["logs"])
            }
            formatted_transfers.append(formatted_transfer)
        
        return jsonify({
            "status": "success",
            "transfers": formatted_transfers,
            "total": len(formatted_transfers)
        })
        
    except Exception as e:
        print(f"❌ Error getting all transfers: {e}")
        return jsonify({"status": "error", "message": f"Failed to get transfers: {str(e)}"})


@transfers_bp.route('/transfers/active')
@require_auth
def api_active_transfers():
    """Get only active (running/pending/queued) transfers"""
    try:
        active_transfers = transfer_coordinator.get_active_transfers()
        
        # Get queue status
        queue_status = transfer_coordinator.get_queue_status()
        
        # Format transfers for response
        formatted_transfers = []
        for transfer in active_transfers:
            formatted_transfer = {
                "id": transfer["transfer_id"],
                "status": transfer["status"],
                "progress": transfer["progress"],
                "media_type": transfer["media_type"],
                "folder_name": transfer["folder_name"],
                "season_name": transfer.get("season_name"),
                "parsed_title": transfer.get("parsed_title"),
                "parsed_season": transfer.get("parsed_season"),
                "operation_type": transfer["operation_type"],
                "source_path": transfer["source_path"],
                "dest_path": transfer["dest_path"],
                "start_time": transfer["start_time"],
                "rsync_process_id": transfer.get("rsync_process_id"),
                "log_count": len(transfer["logs"])
            }
            formatted_transfers.append(formatted_transfer)
        
        return jsonify({
            "status": "success",
            "transfers": formatted_transfers,
            "total": len(formatted_transfers),
            "queue_status": queue_status
        })
        
    except Exception as e:
        print(f"❌ Error getting active transfers: {e}")
        return jsonify({"status": "error", "message": f"Failed to get active transfers: {str(e)}"})


@transfers_bp.route('/transfers/queue/status')
@require_auth
def api_queue_status():
    """Get queue status"""
    try:
        queue_status = transfer_coordinator.get_queue_status()
        return jsonify({
            "status": "success",
            "queue": queue_status
        })
    except Exception as e:
        print(f"❌ Error getting queue status: {e}")
        return jsonify({"status": "error", "message": f"Failed to get queue status: {str(e)}"})


@transfers_bp.route('/transfer/<transfer_id>/restart', methods=['POST'])
@require_auth
def api_restart_transfer(transfer_id):
    """Restart a failed or cancelled transfer"""
    try:
        success = transfer_coordinator.restart_transfer(transfer_id)
        if success:
            return jsonify({"status": "success", "message": "Transfer restarted successfully"})
        else:
            return jsonify({"status": "error", "message": "Failed to restart transfer"})
    except Exception as e:
        print(f"❌ Error restarting transfer {transfer_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to restart transfer: {str(e)}"})


@transfers_bp.route('/transfer/<transfer_id>/delete', methods=['POST'])
@require_auth
def api_delete_transfer(transfer_id):
    """Delete a transfer record from the database"""
    try:
        # Get the transfer details first
        transfer = transfer_coordinator.transfer_model.get(transfer_id)
        if not transfer:
            return jsonify({"status": "error", "message": "Transfer not found"})
        
        # Check if transfer is currently running
        if transfer['status'] == 'running':
            return jsonify({"status": "error", "message": "Cannot delete a running transfer. Please cancel it first."})
        
        # Delete the transfer
        deleted = transfer_coordinator.transfer_model.delete(transfer_id)
        if deleted:
            return jsonify({"status": "success", "message": "Transfer deleted successfully"})
        else:
            return jsonify({"status": "error", "message": "Failed to delete transfer"})
    except Exception as e:
        print(f"❌ Error deleting transfer {transfer_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to delete transfer: {str(e)}"})


@transfers_bp.route('/transfers/cleanup', methods=['POST'])
@require_auth
def api_cleanup_transfers():
    """Remove duplicate transfers based on destination path, keeping only the latest successful transfer"""
    try:
        cleaned = transfer_coordinator.transfer_model.cleanup_duplicate_transfers()
        return jsonify({
            "status": "success", 
            "message": f"Cleaned up {cleaned} duplicate transfers",
            "cleaned_count": cleaned
        })
    except Exception as e:
        print(f"❌ Error cleaning up duplicate transfers: {e}")
        return jsonify({"status": "error", "message": f"Failed to cleanup duplicate transfers: {str(e)}"})

