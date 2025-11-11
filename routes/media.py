#!/usr/bin/env python3
"""
DragonCP Media Routes
Handles media browsing and sync status endpoints
"""

from flask import Blueprint, jsonify, request

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


@media_bp.route('/folders/<media_type>')
def api_folders(media_type):
    """Get folders for media type"""
    print(f"🔍 API: /api/folders/{media_type} called")
    
    if not ssh_manager or not ssh_manager.connected:
        print("❌ Not connected to server")
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    path_map = {
        "movies": config.get("MOVIE_PATH"),
        "tvshows": config.get("TVSHOW_PATH"),
        "anime": config.get("ANIME_PATH")
    }
    
    path = path_map.get(media_type)
    print(f"📁 Path for {media_type}: {path}")
    
    if not path:
        print(f"❌ Invalid media type: {media_type}")
        return jsonify({"status": "error", "message": "Invalid media type"})
    
    print(f"🔍 Listing folders with metadata in: {path}")
    try:
        folders_metadata = ssh_manager.list_folders_with_metadata(path)
        print(f"📁 Found folders: {[f['name'] for f in folders_metadata]}")
        return jsonify({"status": "success", "folders": folders_metadata})
    except Exception as e:
        print(f"❌ Error getting folder metadata: {e}")
        # Fallback to simple folder listing
        folders = ssh_manager.list_folders(path)
        # Convert to metadata format for consistency
        folders_metadata = [{"name": folder, "modification_time": 0} for folder in folders]
        print(f"📁 Fallback folders: {folders}")
        return jsonify({"status": "success", "folders": folders_metadata})


@media_bp.route('/seasons/<media_type>/<folder_name>')
def api_seasons(media_type, folder_name):
    """Get seasons for TV show or anime"""
    if not ssh_manager or not ssh_manager.connected:
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    path_map = {
        "movies": config.get("MOVIE_PATH"),
        "tvshows": config.get("TVSHOW_PATH"),
        "anime": config.get("ANIME_PATH")
    }
    
    base_path = path_map.get(media_type)
    if not base_path:
        return jsonify({"status": "error", "message": "Invalid media type"})
    
    full_path = f"{base_path}/{folder_name}"
    try:
        seasons_metadata = ssh_manager.list_folders_with_metadata(full_path)
        return jsonify({"status": "success", "seasons": seasons_metadata})
    except Exception as e:
        print(f"❌ Error getting season metadata: {e}")
        # Fallback to simple folder listing
        seasons = ssh_manager.list_folders(full_path)
        # Convert to metadata format for consistency
        seasons_metadata = [{"name": season, "modification_time": 0} for season in seasons]
        return jsonify({"status": "success", "seasons": seasons_metadata})


@media_bp.route('/episodes/<media_type>/<folder_name>/<season_name>')
def api_episodes(media_type, folder_name, season_name):
    """Get episodes for a season"""
    if not ssh_manager or not ssh_manager.connected:
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    path_map = {
        "movies": config.get("MOVIE_PATH"),
        "tvshows": config.get("TVSHOW_PATH"),
        "anime": config.get("ANIME_PATH")
    }
    
    base_path = path_map.get(media_type)
    if not base_path:
        return jsonify({"status": "error", "message": "Invalid media type"})
    
    full_path = f"{base_path}/{folder_name}/{season_name}"
    episodes = ssh_manager.list_files(full_path)
    return jsonify({"status": "success", "episodes": episodes})


@media_bp.route('/sync-status/<media_type>')
def api_sync_status(media_type):
    """Get sync status for all folders in a media type"""
    print(f"🔍 API: /api/sync-status/{media_type} called")
    
    if not ssh_manager or not ssh_manager.connected:
        print("❌ Not connected to server")
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    if not transfer_coordinator:
        print("❌ Transfer coordinator not available")
        return jsonify({"status": "error", "message": "Transfer coordinator not available"})
    
    path_map = {
        "movies": config.get("MOVIE_PATH"),
        "tvshows": config.get("TVSHOW_PATH"),
        "anime": config.get("ANIME_PATH")
    }
    
    path = path_map.get(media_type)
    if not path:
        print(f"❌ Invalid media type: {media_type}")
        return jsonify({"status": "error", "message": "Invalid media type"})
    
    try:
        print(f"🔍 Getting sync status for {media_type} folders in: {path}")
        
        # Get folders with metadata
        folders_metadata = ssh_manager.list_folders_with_metadata(path)
        sync_statuses = {}
        
        for folder_data in folders_metadata:
            folder_name = folder_data['name']
            modification_time = folder_data.get('modification_time', 0)
            
            print(f"📁 Processing folder: {folder_name}")
            
            if media_type == 'movies':
                # For movies, get direct folder status
                status = transfer_coordinator.transfer_model.get_sync_status(
                    media_type, folder_name, None, modification_time
                )
                sync_statuses[folder_name] = {
                    'status': status,
                    'type': 'movie',
                    'modification_time': modification_time
                }
            else:
                # For series/anime, get seasons and aggregate
                try:
                    full_path = f"{path}/{folder_name}"
                    seasons_metadata = ssh_manager.list_folders_with_metadata(full_path)
                    
                    summary = transfer_coordinator.transfer_model.get_folder_sync_status_summary(
                        media_type, folder_name, seasons_metadata
                    )
                    sync_statuses[folder_name] = summary
                    
                except Exception as season_error:
                    print(f"⚠️ Error getting seasons for {folder_name}: {season_error}")
                    # Fallback to NO_INFO if we can't get season data
                    sync_statuses[folder_name] = {
                        'status': 'NO_INFO',
                        'type': 'series',
                        'seasons': []
                    }
        
        print(f"✅ Sync status processed for {len(sync_statuses)} folders")
        return jsonify({
            "status": "success", 
            "sync_statuses": sync_statuses
        })
        
    except Exception as e:
        print(f"❌ Error getting sync status: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Failed to get sync status: {str(e)}"})


@media_bp.route('/sync-status/<media_type>/<folder_name>')
def api_folder_sync_status(media_type, folder_name):
    """Get detailed sync status for a specific folder (useful for series/anime seasons)"""
    print(f"🔍 API: /api/sync-status/{media_type}/{folder_name} called")
    
    if not ssh_manager or not ssh_manager.connected:
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    if not transfer_coordinator:
        return jsonify({"status": "error", "message": "Transfer coordinator not available"})
    
    path_map = {
        "movies": config.get("MOVIE_PATH"),
        "tvshows": config.get("TVSHOW_PATH"),
        "anime": config.get("ANIME_PATH")
    }
    
    path = path_map.get(media_type)
    if not path:
        return jsonify({"status": "error", "message": "Invalid media type"})
    
    try:
        if media_type == 'movies':
            # For movies, get folder metadata
            folders_metadata = ssh_manager.list_folders_with_metadata(path)
            folder_data = next((f for f in folders_metadata if f['name'] == folder_name), None)
            
            if not folder_data:
                return jsonify({"status": "error", "message": "Folder not found"})
            
            modification_time = folder_data.get('modification_time', 0)
            status = transfer_coordinator.transfer_model.get_sync_status(
                media_type, folder_name, None, modification_time
            )
            
            return jsonify({
                "status": "success",
                "folder_name": folder_name,
                "sync_status": {
                    'status': status,
                    'type': 'movie',
                    'modification_time': modification_time
                }
            })
        else:
            # For series/anime, get detailed season information
            full_path = f"{path}/{folder_name}"
            seasons_metadata = ssh_manager.list_folders_with_metadata(full_path)
            
            summary = transfer_coordinator.transfer_model.get_folder_sync_status_summary(
                media_type, folder_name, seasons_metadata
            )
            
            # Convert seasons data to the format expected by frontend
            seasons_sync_status = {}
            if 'seasons' in summary:
                for season_data in summary['seasons']:
                    seasons_sync_status[season_data['name']] = {
                        'status': season_data['status'],
                        'type': 'season',
                        'modification_time': season_data.get('modification_time', 0)
                    }
            
            return jsonify({
                "status": "success",
                "folder_name": folder_name,
                "sync_status": summary,
                "seasons_sync_status": seasons_sync_status
            })
            
    except Exception as e:
        print(f"❌ Error getting folder sync status: {e}")
        return jsonify({"status": "error", "message": f"Failed to get folder sync status: {str(e)}"})


@media_bp.route('/sync-status/<media_type>/<folder_name>/enhanced')
def api_enhanced_folder_sync_status(media_type, folder_name):
    """Get enhanced sync status with detailed file information"""
    print(f"🔍 API: /api/sync-status/{media_type}/{folder_name}/enhanced called")
    
    if not ssh_manager or not ssh_manager.connected:
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    if not transfer_coordinator:
        return jsonify({"status": "error", "message": "Transfer coordinator not available"})
    
    path_map = {
        "movies": config.get("MOVIE_PATH"),
        "tvshows": config.get("TVSHOW_PATH"),
        "anime": config.get("ANIME_PATH")
    }
    
    path = path_map.get(media_type)
    if not path:
        return jsonify({"status": "error", "message": "Invalid media type"})
    
    try:
        full_path = f"{path}/{folder_name}"
        
        if media_type == 'movies':
            # For movies, get detailed file information
            file_summary = ssh_manager.get_folder_file_summary(full_path)
            files_metadata = ssh_manager.list_files_with_metadata(full_path)
            
            # Get sync status using the most recent file modification time
            latest_modification = file_summary.get('latest_modification', 0)
            status = transfer_coordinator.transfer_model.get_sync_status(
                media_type, folder_name, None, latest_modification
            )
            
            return jsonify({
                "status": "success",
                "folder_name": folder_name,
                "sync_status": {
                    'status': status,
                    'type': 'movie',
                    'modification_time': latest_modification,
                    'file_count': file_summary.get('file_count', 0),
                    'total_size': file_summary.get('total_size', 0),
                    'files': files_metadata[:10]  # Show first 10 files
                }
            })
        else:
            # For series/anime, get detailed season and episode information
            seasons_metadata = ssh_manager.list_folders_with_metadata(full_path)
            
            detailed_seasons = []
            for season_data in seasons_metadata:
                season_name = season_data['name']
                season_path = f"{full_path}/{season_name}"
                
                # Get file summary for this season
                season_file_summary = ssh_manager.get_folder_file_summary(season_path)
                season_files = ssh_manager.list_files_with_metadata(season_path)
                
                # Get sync status for this season
                season_status = transfer_coordinator.transfer_model.get_sync_status(
                    media_type, folder_name, season_name, season_data.get('modification_time', 0)
                )
                
                detailed_seasons.append({
                    'name': season_name,
                    'status': season_status,
                    'modification_time': season_data.get('modification_time', 0),
                    'file_count': season_file_summary.get('file_count', 0),
                    'total_size': season_file_summary.get('total_size', 0),
                    'files': season_files[:5]  # Show first 5 files per season
                })
            
            # Determine overall status based on most recent season
            most_recent_season = max(detailed_seasons, key=lambda x: x['modification_time']) if detailed_seasons else None
            overall_status = most_recent_season['status'] if most_recent_season else 'NO_INFO'
            
            return jsonify({
                "status": "success",
                "folder_name": folder_name,
                "sync_status": {
                    'status': overall_status,
                    'type': 'series',
                    'seasons': detailed_seasons,
                    'most_recent_season': most_recent_season['name'] if most_recent_season else None
                }
            })
            
    except Exception as e:
        print(f"❌ Error getting enhanced folder sync status: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Failed to get enhanced folder sync status: {str(e)}"})


# ===== DRY-RUN ENDPOINT =====

@media_bp.route('/media/dry-run', methods=['POST'])
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
        
        print(f"📁 Source: {source_path}")
        print(f"📁 Dest: {dest_path}")
        
        # Perform dry-run using transfer service
        dry_run_result = transfer_coordinator.transfer_service.perform_dry_run_rsync(
            source_path=source_path,
            dest_path=dest_path,
            is_season_folder=is_season_folder
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