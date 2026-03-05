#!/usr/bin/env python3
"""
DragonCP Debug Routes
Handles debug and diagnostic endpoints
"""

import os
import subprocess
from datetime import datetime
from flask import Blueprint, jsonify, request
from auth import require_auth

debug_bp = Blueprint('debug', __name__)

# Global references to be set by app.py
config = None
ssh_manager = None
db_manager = None
transfer_coordinator = None
websocket_connections = None


def init_debug_routes(app_config, app_ssh_manager, app_db_manager, app_transfer_coordinator, app_ws_connections):
    """Initialize route dependencies"""
    global config, ssh_manager, db_manager, transfer_coordinator, websocket_connections
    config = app_config
    ssh_manager = app_ssh_manager
    db_manager = app_db_manager
    transfer_coordinator = app_transfer_coordinator
    websocket_connections = app_ws_connections


@debug_bp.route('/debug')
@require_auth
def api_debug():
    """Debug endpoint to check configuration and SSH status"""
    from flask import session
    from websocket import WEBSOCKET_TIMEOUT_MAX, WEBSOCKET_TIMEOUT_DEFAULT, get_websocket_timeout_for_session
    
    try:
        debug_info = {
            "timestamp": datetime.now().isoformat(),
            "working_directory": os.getcwd(),
            "environment_file": config.env_file,
            "environment_file_exists": os.path.exists(config.env_file),
            "ssh_connected": ssh_manager.connected if ssh_manager else False,
            "websocket_info": {
                "active_connections": len(websocket_connections),
                "default_timeout_minutes": WEBSOCKET_TIMEOUT_DEFAULT // 60,
                "max_timeout_minutes": WEBSOCKET_TIMEOUT_MAX // 60,
                "current_session_timeout_minutes": get_websocket_timeout_for_session() // 60,
                "session_config_timeout": session.get('ui_config', {}).get('WEBSOCKET_TIMEOUT_MINUTES', 'Not set'),
                "connections_details": [
                    {
                        "session_id": sid[:8] + "...",  # Only show first 8 chars for privacy
                        "connected_minutes_ago": int((datetime.now() - info['connected_at']).total_seconds() // 60),
                        "last_activity_minutes_ago": int((datetime.now() - info['last_activity']).total_seconds() // 60),
                        "timeout_minutes": info.get('timeout_seconds', WEBSOCKET_TIMEOUT_DEFAULT) // 60
                    }
                    for sid, info in websocket_connections.items()
                ]
            },
            "configuration": {
                "REMOTE_IP": config.get("REMOTE_IP"),
                "REMOTE_USER": config.get("REMOTE_USER"),
                "REMOTE_PASSWORD": "***" if config.get("REMOTE_PASSWORD") else "Not set",
                "SSH_KEY_PATH": config.get("SSH_KEY_PATH"),
                "MOVIE_PATH": config.get("MOVIE_PATH"),
                "TVSHOW_PATH": config.get("TVSHOW_PATH"),
                "ANIME_PATH": config.get("ANIME_PATH"),
                "MOVIE_DEST_PATH": config.get("MOVIE_DEST_PATH"),
                "TVSHOW_DEST_PATH": config.get("TVSHOW_DEST_PATH"),
                "ANIME_DEST_PATH": config.get("ANIME_DEST_PATH"),
                "BACKUP_PATH": config.get("BACKUP_PATH"),
                "DISK_PATH_1": config.get("DISK_PATH_1"),
                "DISK_PATH_2": config.get("DISK_PATH_2"),
                "DISK_PATH_3": config.get("DISK_PATH_3"),
                "DISK_API_ENDPOINT": config.get("DISK_API_ENDPOINT"),
                "DISK_API_TOKEN": "***" if config.get("DISK_API_TOKEN") else "Not set"
            },
            "ssh_key_check": {
                "key_path": config.get("SSH_KEY_PATH"),
                "key_exists": os.path.exists(config.get("SSH_KEY_PATH", "")) if config.get("SSH_KEY_PATH") else False,
                "key_readable": os.access(config.get("SSH_KEY_PATH", ""), os.R_OK) if config.get("SSH_KEY_PATH") and os.path.exists(config.get("SSH_KEY_PATH", "")) else False
            },
            "rsync_check": {
                "rsync_available": subprocess.run(["which", "rsync"], capture_output=True, text=True).returncode == 0,
                "rsync_version": subprocess.run(["rsync", "--version"], capture_output=True, text=True).stdout.split('\n')[0] if subprocess.run(["which", "rsync"], capture_output=True, text=True).returncode == 0 else "Not available"
            },
            "active_transfers": len(transfer_coordinator.transfer_service.transfers),
            "session_config": session.get('ui_config', {})
        }
        
        return jsonify({
            "status": "success",
            "debug_info": debug_info
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Debug failed: {str(e)}",
            "debug_info": {
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        })


@debug_bp.route('/debug/transfers')
@require_auth
def api_debug_transfers():
    """Debug endpoint to check database transfers"""
    try:
        # Get all transfers from database
        all_transfers = transfer_coordinator.get_all_transfers(limit=10)
        active_transfers = transfer_coordinator.get_active_transfers()
        
        debug_info = {
            "timestamp": datetime.now().isoformat(),
            "database_path": db_manager.db_path,
            "database_exists": os.path.exists(db_manager.db_path),
            "total_transfers_in_db": len(all_transfers),
            "active_transfers_in_db": len(active_transfers),
            "recent_transfers": all_transfers[:5],  # Last 5 transfers
            "transfer_coordinator_type": str(type(transfer_coordinator)),
            "db_manager_type": str(type(db_manager))
        }
        
        return jsonify({
            "status": "success",
            "debug_info": debug_info
        })
        
    except Exception as e:
        print(f"❌ Error in debug transfers: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Debug transfers failed: {str(e)}",
            "error": str(e)
        })


@debug_bp.route('/websocket/status')
@require_auth
def api_websocket_status():
    """Get WebSocket connection status and count"""
    from websocket import WEBSOCKET_TIMEOUT_DEFAULT
    
    try:
        current_time = datetime.now()
        connection_details = []
        
        for session_id, connection_info in websocket_connections.items():
            connected_minutes_ago = int((current_time - connection_info['connected_at']).total_seconds() // 60)
            last_activity_minutes_ago = int((current_time - connection_info['last_activity']).total_seconds() // 60)
            timeout_minutes = connection_info.get('timeout_seconds', WEBSOCKET_TIMEOUT_DEFAULT) // 60
            
            connection_details.append({
                "session_id": session_id[:8] + "...",  # Only show first 8 chars for privacy
                "connected_minutes_ago": connected_minutes_ago,
                "last_activity_minutes_ago": last_activity_minutes_ago,
                "timeout_minutes": timeout_minutes
            })
        
        from websocket import WEBSOCKET_TIMEOUT_MAX
        status_info = {
            "active_connections": len(websocket_connections),
            "default_timeout_minutes": WEBSOCKET_TIMEOUT_DEFAULT // 60,
            "max_timeout_minutes": WEBSOCKET_TIMEOUT_MAX // 60,
            "connection_details": connection_details,
            "timestamp": current_time.isoformat()
        }
        
        return jsonify({
            "status": "success",
            "websocket_status": status_info
        })
        
    except Exception as e:
        print(f"❌ Error getting WebSocket status: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get WebSocket status: {str(e)}"
        })


@debug_bp.route('/local-files')
@require_auth
def api_local_files():
    """Get local files in a directory"""
    path = request.args.get('path', '/')
    try:
        if os.path.exists(path) and os.path.isdir(path):
            files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
            return jsonify({"status": "success", "files": sorted(files)})
        else:
            return jsonify({"status": "error", "message": "Path not found"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@debug_bp.route('/disk-usage/local')
@require_auth
def api_local_disk_usage():
    """Get local disk usage for configured paths"""
    try:
        disk_paths = [
            config.get("DISK_PATH_1", "/home"),
            config.get("DISK_PATH_2"),
            config.get("DISK_PATH_3")
        ]
        
        disk_info = []
        
        for path in disk_paths:
            if not path or not os.path.exists(path):
                disk_info.append({
                    "path": path,
                    "error": "Path not found or not configured",
                    "available": False
                })
                continue
            
            try:
                # Run df command to get disk usage
                result = subprocess.run(
                    ["df", "-h", path], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
                
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    if len(lines) >= 2:
                        # Parse df output (format: Filesystem Size Used Avail Use% Mounted on)
                        fields = lines[1].split()
                        if len(fields) >= 6:
                            filesystem = fields[0]
                            total_size = fields[1]
                            used_size = fields[2]
                            available_size = fields[3]
                            usage_percent = fields[4].rstrip('%')
                            mount_point = ' '.join(fields[5:])
                            
                            disk_info.append({
                                "path": path,
                                "filesystem": filesystem,
                                "total_size": total_size,
                                "used_size": used_size,
                                "available_size": available_size,
                                "usage_percent": int(usage_percent),
                                "mount_point": mount_point,
                                "available": True
                            })
                        else:
                            disk_info.append({
                                "path": path,
                                "error": "Could not parse df output",
                                "available": False
                            })
                    else:
                        disk_info.append({
                            "path": path,
                            "error": "Invalid df output",
                            "available": False
                        })
                else:
                    disk_info.append({
                        "path": path,
                        "error": f"df command failed: {result.stderr}",
                        "available": False
                    })
                    
            except subprocess.TimeoutExpired:
                disk_info.append({
                    "path": path,
                    "error": "Command timeout",
                    "available": False
                })
            except Exception as e:
                disk_info.append({
                    "path": path,
                    "error": f"Error: {str(e)}",
                    "available": False
                })
        
        return jsonify({
            "status": "success",
            "disk_info": disk_info
        })
        
    except Exception as e:
        print(f"❌ Error getting local disk usage: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get local disk usage: {str(e)}"
        })


@debug_bp.route('/disk-usage/remote')
@require_auth
def api_remote_disk_usage():
    """Get remote disk usage from configured API"""
    import requests
    
    try:
        api_endpoint = config.get("DISK_API_ENDPOINT")
        api_token = config.get("DISK_API_TOKEN")
        
        if not api_endpoint:
            return jsonify({
                "status": "error",
                "message": "Remote disk API endpoint not configured"
            })
        
        headers = {}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        
        # Make request to remote API
        response = requests.get(api_endpoint, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Parse the expected format
            if "service_stats_info" in data:
                stats = data["service_stats_info"]
                
                # Convert GiB to GB (1 GiB = 1.073741824 GB)
                GIB_TO_GB = 1.073741824
                
                # Get values - all are in GiB (including free_storage_gb)
                total_gib = stats.get("total_storage_value", 0)
                used_gib = stats.get("used_storage_value", 0)
                free_gib = stats.get("free_storage_gb", 0)  # This is actually in GiB, not GB
                
                # Convert all GiB values to GB
                total_gb = round(total_gib * GIB_TO_GB)
                used_gb = round(used_gib * GIB_TO_GB)
                free_gb = round(free_gib * GIB_TO_GB)
                
                # Calculate usage percentage based on converted values
                usage_percent = round((used_gb / max(total_gb, 1)) * 100, 1) if total_gb > 0 else 0
                
                # Always display in GB for consistency
                total_display = f"{total_gb} GB"
                used_display = f"{used_gb} GB"
                free_display = f"{round(free_gb)} GB"
                
                # Extract storage information
                storage_info = {
                    "free_storage_bytes": stats.get("free_storage_bytes", 0),
                    "free_storage_gb": round(free_gb),
                    "total_storage_value": total_gb,
                    "total_storage_unit": "GB",
                    "used_storage_value": used_gb,
                    "used_storage_unit": "GB",
                    "usage_percent": usage_percent,
                    "total_display": total_display,
                    "used_display": used_display,
                    "free_display": free_display,
                    "available": True
                }
                
                return jsonify({
                    "status": "success",
                    "storage_info": storage_info
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "Invalid API response format"
                })
        else:
            return jsonify({
                "status": "error",
                "message": f"API request failed: {response.status_code} - {response.text}"
            })
            
    except requests.RequestException as e:
        print(f"❌ Error getting remote disk usage: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get remote disk usage: {str(e)}"
        })
    except Exception as e:
        print(f"❌ Error getting remote disk usage: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get remote disk usage: {str(e)}"
        })

