#!/usr/bin/env python3
"""
DragonCP Media Routes

What is left of the old Browse Media backend. The folder, season, episode and
sync-status endpoints were retired once Explore replaced them: Explore compares
both libraries file by file and reports what is actually there, where the old
endpoints inferred a folder's state from whether a transfer row existed for it
and could not tell "synced" from "we ran a transfer here once".

SECURITY: All path components from URL parameters and POST body data
are validated through security.validate_path_component() before being
used to construct filesystem paths. This prevents path traversal attacks
via crafted folder_name, season_name, or episode_name values.
See security.py for the validation implementation.
"""

from flask import Blueprint, jsonify, request
from auth import require_auth
from security import validate_path_component, assert_path_within_bounds, PathTraversalError

media_bp = Blueprint('media', __name__)

# Global references to be set by app.py
config = None
ssh_manager = None
transfer_coordinator = None


def init_media_routes(app_config, app_ssh_manager, app_transfer_coordinator):
    """Initialize route dependencies"""
    global config, ssh_manager, transfer_coordinator
    config = app_config
    ssh_manager = app_ssh_manager
    transfer_coordinator = app_transfer_coordinator


@media_bp.route('/media-types')
@require_auth
def api_media_types():
    """Get available media types"""
    print("🔍 API: /api/media-types called")
    
    movie_path = config.get("MOVIE_PATH")
    tvshow_path = config.get("TVSHOW_PATH")
    anime_path = config.get("ANIME_PATH")
    
    print(f"📁 Movie path: {movie_path}")
    print(f"📁 TV Show path: {tvshow_path}")
    print(f"📁 Anime path: {anime_path}")
    
    media_types = [
        {"id": "movies", "name": "Movies", "path": movie_path},
        {"id": "tvshows", "name": "TV Shows", "path": tvshow_path},
        {"id": "anime", "name": "Anime", "path": anime_path}
    ]
    
    print(f"📋 Returning media types: {media_types}")
    return jsonify(media_types)


# ===== DRY-RUN ENDPOINT =====

@media_bp.route('/media/dry-run', methods=['POST'])
@require_auth
def api_media_dry_run():
    """Perform manual dry-run for a selected media folder"""
    try:
        data = request.json
        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400
        
        media_type = data.get('media_type')
        folder_name = data.get('folder_name')
        season_name = data.get('season_name')  # Optional, for series/anime
        
        if not media_type or not folder_name:
            return jsonify({
                "status": "error",
                "message": "media_type and folder_name are required"
            }), 400

        # SECURITY: Validate path components from POST body to prevent traversal
        if not validate_path_component(folder_name):
            return jsonify({"status": "error", "message": "Invalid folder name"}), 400
        if season_name and not validate_path_component(season_name):
            return jsonify({"status": "error", "message": "Invalid season name"}), 400

        print(f"🔍 Manual dry-run requested from media browser")
        print(f"   Media type: {media_type}")
        print(f"   Folder: {folder_name}")
        if season_name:
            print(f"   Season: {season_name}")
        
        # Get source path based on media type
        path_map = {
            "movies": config.get("MOVIE_PATH"),
            "tvshows": config.get("TVSHOW_PATH"),
            "anime": config.get("ANIME_PATH")
        }
        
        source_base = path_map.get(media_type)
        if not source_base:
            return jsonify({
                "status": "error",
                "message": "Invalid media type"
            }), 400
        
        # Build source path
        if season_name:
            # For series/anime with season
            source_path = f"{source_base}/{folder_name}/{season_name}"
            is_season_folder = True
        else:
            # For movies or entire series folder
            source_path = f"{source_base}/{folder_name}"
            is_season_folder = (media_type in ['tvshows', 'anime'])
        
        # Get destination path based on media type
        dest_path_map = {
            "movies": config.get("MOVIE_DEST_PATH"),
            "tvshows": config.get("TVSHOW_DEST_PATH"),
            "anime": config.get("ANIME_DEST_PATH")
        }
        
        dest_base = dest_path_map.get(media_type)
        if not dest_base:
            return jsonify({
                "status": "error",
                "message": f"{media_type.capitalize()} destination path not configured"
            }), 400
        
        # Build destination path
        if season_name:
            # For series/anime with season
            dest_path = f"{dest_base}/{folder_name}/{season_name}"
        else:
            # For movies or entire series folder
            dest_path = f"{dest_base}/{folder_name}"

        # SECURITY: Resolve dest_path to its real absolute path and verify it
        # stays within dest_base. Component validation above prevents literal
        # traversal, but this catches symlink-based escapes.
        try:
            assert_path_within_bounds(dest_path, [dest_base])
        except PathTraversalError:
            return jsonify({"status": "error", "message": "Destination path escapes configured boundary"}), 400

        print(f"📁 Source: {source_path}")
        print(f"📁 Dest: {dest_path}")

        # Perform dry-run using transfer service
        dry_run_result = transfer_coordinator.transfer_service.perform_dry_run_rsync(
            source_path=source_path,
            dest_path=dest_path
        )
        
        print(f"✅ Dry-run completed: {dry_run_result.get('safe_to_sync', False)}")
        
        return jsonify({
            "status": "success",
            "dry_run_result": dry_run_result
        })
        
    except Exception as e:
        print(f"❌ Error performing media dry-run: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Failed to perform dry-run: {str(e)}"
        }), 500