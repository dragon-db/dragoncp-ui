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
from services.transfer_service import build_progress_stats

# A page the UI would never render is a payload nobody reads; cap it so a
# hand-written limit cannot pull the whole table back.
MAX_PAGE_SIZE = 200

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
                "paused_at": transfer.get("paused_at"),
                "media_type": transfer["media_type"],
                "folder_name": transfer["folder_name"],
                "season_name": transfer.get("season_name"),
                "parsed_title": transfer.get("parsed_title"),
                "parsed_season": transfer.get("parsed_season"),
                "operation_type": transfer["operation_type"],
                "source_path": transfer["source_path"],
                "dest_path": transfer["dest_path"],
                **build_progress_stats(transfer)
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


@transfers_bp.route('/transfer/<transfer_id>/pause', methods=['POST'])
@require_auth
def api_pause_transfer(transfer_id):
    """
    Pause a running transfer

    Stops rsync but keeps the partially transferred files, so /resume continues
    from where it stopped instead of starting over.
    """
    try:
        success, message = transfer_coordinator.pause_transfer(transfer_id)
        if success:
            return jsonify({"status": "success", "message": message})
        return jsonify({"status": "error", "message": message}), 400
    except Exception as e:
        print(f"❌ Error pausing transfer {transfer_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to pause transfer: {str(e)}"}), 500


@transfers_bp.route('/transfer/<transfer_id>/resume', methods=['POST'])
@require_auth
def api_resume_transfer(transfer_id):
    """Resume a paused transfer (may queue if no slot is free)"""
    try:
        success, message = transfer_coordinator.resume_transfer(transfer_id)
        if success:
            return jsonify({"status": "success", "message": message})
        return jsonify({"status": "error", "message": message}), 400
    except Exception as e:
        print(f"❌ Error resuming transfer {transfer_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to resume transfer: {str(e)}"}), 500


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
        limit = max(1, min(request.args.get('limit', 50, type=int), MAX_PAGE_SIZE))
        offset = max(0, request.args.get('offset', 0, type=int))
        status_filter = request.args.get('status')
        search = (request.args.get('search') or '').strip() or None
        # History wants every finished run and no live ones, which is a set of
        # statuses rather than one - hence a list alongside the single filter.
        statuses = [s for s in (request.args.get('statuses') or '').split(',') if s] or None

        # Filtering, searching and paging all happen in SQL: pulling every row
        # back to drop most of them made the limit meaningless, and a client
        # cannot filter what it was never sent.
        transfers = transfer_coordinator.get_all_transfers(
            limit=limit, status_filter=status_filter, search=search, offset=offset,
            statuses=statuses
        )
        total = transfer_coordinator.count_transfers(
            status_filter=status_filter, search=search, statuses=statuses
        )
        
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
                "paused_at": transfer.get("paused_at"),
                "created_at": transfer["created_at"],
                "log_count": transfer["log_count"],
                "is_simulation": bool(transfer.get("is_simulation")),
                **build_progress_stats(transfer)
            }
            formatted_transfers.append(formatted_transfer)
        
        return jsonify({
            "status": "success",
            "transfers": formatted_transfers,
            # `total` counts everything matching the filter; `count` is what
            # this page holds. They were the same number before paging existed,
            # which is why the UI could not tell it had more to show.
            "total": total,
            "count": len(formatted_transfers),
            "limit": limit,
            "offset": offset,
            "status_counts": transfer_coordinator.transfer_model.status_counts(
                search=search, statuses=statuses
            ),
            # Everything on record regardless of what is being asked for right
            # now, so a tab badge does not count down as someone types.
            "unfiltered_total": transfer_coordinator.count_transfers(statuses=statuses),
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
                "paused_at": transfer.get("paused_at"),
                # created_at lets the UI show how long a transfer waited before
                # it started, which is the difference between a slow copy and a
                # backed-up queue.
                "created_at": transfer["created_at"],
                "queue_reason": transfer.get("queue_reason"),
                "rsync_process_id": transfer.get("rsync_process_id"),
                "log_count": transfer["log_count"],
                "is_simulation": bool(transfer.get("is_simulation")),
                **build_progress_stats(transfer)
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


@transfers_bp.route('/transfers/bulk-delete', methods=['POST'])
@require_auth
def api_bulk_delete_transfers():
    """
    Delete several transfer records at once.

    Accepts either an explicit list of ids, or `all_matching` with the same
    filter the list was showing. The filter form re-runs the query on the
    server, so clearing a filtered view does not depend on the client having
    loaded every row it is about to delete.

    Transfers that are still running are never deleted - they are reported back
    as skipped so the caller can say so rather than silently losing them.
    """
    try:
        payload = request.get_json(silent=True) or {}
        model = transfer_coordinator.transfer_model

        if payload.get('all_matching'):
            statuses = payload.get('statuses')
            deleted, skipped = model.delete_matching(
                status_filter=payload.get('status'),
                statuses=statuses if isinstance(statuses, list) else None,
                search=(payload.get('search') or '').strip() or None,
            )
        else:
            transfer_ids = payload.get('ids') or []
            if not isinstance(transfer_ids, list):
                return jsonify({"status": "error", "message": "ids must be a list"}), 400
            if not transfer_ids:
                return jsonify({
                    "status": "success", "deleted_count": 0, "skipped": [],
                    "message": "Nothing to delete",
                })
            deleted, skipped = model.delete_many(transfer_ids)

        message = f"Deleted {deleted} transfer{'s' if deleted != 1 else ''}"
        if skipped:
            message += f", skipped {len(skipped)} still running"

        return jsonify({
            "status": "success",
            "deleted_count": deleted,
            "skipped": skipped,
            "message": message,
        })
    except Exception as e:
        print(f"❌ Error bulk deleting transfers: {e}")
        return jsonify({"status": "error", "message": f"Failed to delete transfers: {str(e)}"}), 500


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

