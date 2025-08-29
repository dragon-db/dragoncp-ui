#!/usr/bin/env python3
"""
DragonCP Web UI - A modern web interface for DragonCP media transfer script
Compatible with Python 3.12
"""

import os
import json
import subprocess
import tempfile
import threading
import time
import shutil
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask import has_request_context
from flask_socketio import SocketIO, emit
import paramiko
from werkzeug.utils import secure_filename

# Import new database modules
from database import DatabaseManager, TransferManager
from simulator import TransferSimulator

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dragoncp-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# WebSocket timeout configuration
WEBSOCKET_TIMEOUT_MIN = 5 * 60    # 5 minutes minimum
WEBSOCKET_TIMEOUT_MAX = 65 * 60   # 65 minutes maximum (5 minutes longer than max client timeout)
WEBSOCKET_TIMEOUT_DEFAULT = 35 * 60  # 35 minutes default

def get_websocket_timeout_for_session():
    """Get WebSocket timeout for current session, respecting user configuration"""
    try:
        # Get user's configured timeout from session
        session_config = session.get('ui_config', {})
        user_timeout_minutes = session_config.get('WEBSOCKET_TIMEOUT_MINUTES')
        
        if user_timeout_minutes:
            # Convert to seconds and add 5 minutes buffer, but cap at maximum
            user_timeout_seconds = min(60, max(5, int(user_timeout_minutes))) * 60
            server_timeout = min(WEBSOCKET_TIMEOUT_MAX, user_timeout_seconds + 5 * 60)
            return server_timeout
        else:
            return WEBSOCKET_TIMEOUT_DEFAULT
    except:
        return WEBSOCKET_TIMEOUT_DEFAULT

socketio = SocketIO(
    app, 
    cors_allowed_origins="*",
    ping_timeout=WEBSOCKET_TIMEOUT_MAX,  # Use maximum for SocketIO config
    ping_interval=25 * 60  # Send ping every 25 minutes
)

# Global variables for SSH connection
ssh_client = None
ssh_connected = False

# WebSocket connection tracking
websocket_connections = {}
import threading
from datetime import datetime, timedelta

class DragonCPConfig:
    """Configuration manager for DragonCP"""
    
    def __init__(self, env_file: str = "dragoncp_env.env"):
        # Look for environment file in the same directory as this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.env_file = os.path.join(script_dir, env_file)
        
        if os.path.exists(self.env_file):
            print(f"✅ Found environment file: {self.env_file}")
        else:
            print(f"⚠️  Environment file not found: {self.env_file}")
            print(f"   Please create {env_file} in the project root directory")
        
        self.env_config = self.load_env_config()
        print(f"📋 Loaded environment configuration: {list(self.env_config.keys())}")
    
    def load_env_config(self) -> Dict[str, str]:
        """Load configuration from environment file (read-only)"""
        config = {}
        if self.env_file and os.path.exists(self.env_file):
            try:
                with open(self.env_file, 'r') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            config[key.strip()] = value.strip().strip('"').strip("'")
                            print(f"  {key.strip()}: {value.strip().strip('"').strip("'")}")
            except Exception as e:
                print(f"❌ Error loading env file: {e}")
        else:
            print(f"❌ Environment file not found: {self.env_file}")
        return config
    
    def get(self, key: str, default: str = "") -> str:
        """Get configuration value (env config takes precedence)"""
        # First check session config (UI overrides) only if in a request context
        if has_request_context():
            session_config = session.get('ui_config', {})
            if key in session_config:
                return session_config[key]
        
        # Fall back to env config
        value = self.env_config.get(key, default)
        if not value:
            print(f"⚠️  Configuration key '{key}' not found, using default: '{default}'")
        return value
    
    def get_all_config(self) -> Dict[str, str]:
        """Get all configuration (env + session overrides)"""
        # Start with env config
        all_config = self.env_config.copy()
        
        # Override with session config
        session_config = session.get('ui_config', {})
        all_config.update(session_config)
        
        return all_config
    
    def update_session_config(self, config_data: Dict[str, str]):
        """Update session configuration (doesn't modify .env file)"""
        current_session_config = session.get('ui_config', {})
        current_session_config.update(config_data)
        session['ui_config'] = current_session_config
        print(f"✅ Session configuration updated: {list(config_data.keys())}")
    
    def save_config(self, config_data: Dict[str, str]):
        """Save configuration to .env file (legacy method - use update_session_config instead)"""
        try:
            with open(self.env_file, 'w') as f:
                f.write("# DragonCP Configuration\n")
                f.write(f"# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                for key, value in config_data.items():
                    f.write(f'{key}="{value}"\n')
            self.env_config = config_data
            print(f"✅ Configuration saved to .env file: {self.env_file}")
        except Exception as e:
            print(f"❌ Error saving configuration to .env file: {e}")

class SSHManager:
    """SSH connection manager"""
    
    def __init__(self, host: str, username: str, password: str = None, key_path: str = None):
        self.host = host
        self.username = username
        self.password = password
        self.key_path = key_path
        self.client = None
        self.connected = False
    
    def connect(self) -> bool:
        """Establish SSH connection"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if self.key_path and os.path.exists(self.key_path):
                private_key = paramiko.RSAKey.from_private_key_file(self.key_path)
                self.client.connect(
                    hostname=self.host,
                    username=self.username,
                    pkey=private_key,
                    timeout=10
                )
            else:
                self.client.connect(
                    hostname=self.host,
                    username=self.username,
                    password=self.password,
                    timeout=10
                )
            
            self.connected = True
            return True
        except Exception as e:
            print(f"SSH connection failed: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Close SSH connection"""
        if self.client:
            self.client.close()
        self.connected = False
    
    def execute_command(self, command: str) -> Tuple[int, str, str]:
        """Execute command on remote server"""
        if not self.connected:
            return 1, "", "Not connected"
        
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8').strip()
            error = stderr.read().decode('utf-8').strip()
            return exit_code, output, error
        except Exception as e:
            return 1, "", str(e)
    
    def list_folders(self, path: str) -> List[str]:
        """List folders in remote directory"""
        # Fix escape sequence warning by using raw string
        command = f'find "{path}" -mindepth 1 -maxdepth 1 -type d -exec basename "{{}}" \\;'
        exit_code, output, error = self.execute_command(command)
        
        if exit_code == 0 and output:
            folders = [f.strip() for f in output.split('\n') if f.strip()]
            return sorted(folders, key=lambda x: (len(x), x))
        return []
    
    def list_folders_with_metadata(self, path: str) -> List[Dict]:
        """List folders in remote directory with metadata including most recent file modification time"""
        # Get folder names with most recent file modification time within each folder
        command = f'''find "{path}" -mindepth 1 -maxdepth 1 -type d -exec sh -c '
            for dir; do
                # Get the most recent file modification time within this folder (recursive)
                latest_file_time=$(find "$dir" -type f -printf "%T@\\n" | sort -nr | head -1)
                if [ -n "$latest_file_time" ]; then
                    echo "$(basename "$dir")|$latest_file_time"
                else
                    # If no files found, use folder modification time as fallback
                    echo "$(basename "$dir")|$(stat -c %Y "$dir")"
                fi
            done
        ' _ {{}} +'''
        
        exit_code, output, error = self.execute_command(command)
        
        folders = []
        if exit_code == 0 and output:
            for line in output.strip().split('\n'):
                if line.strip() and '|' in line:
                    folder_name, mod_time = line.strip().split('|', 1)
                    try:
                        folders.append({
                            'name': folder_name,
                            'modification_time': int(float(mod_time))  # Convert from float timestamp
                        })
                    except ValueError:
                        # Fallback for invalid modification time
                        folders.append({
                            'name': folder_name,
                            'modification_time': 0
                        })
        
        return folders
    
    def list_files(self, path: str) -> List[str]:
        """List files in remote directory"""
        # Fix escape sequence warning by using raw string
        command = f'find "{path}" -maxdepth 1 -type f -exec basename "{{}}" \\;'
        exit_code, output, error = self.execute_command(command)
        
        if exit_code == 0 and output:
            files = [f.strip() for f in output.split('\n') if f.strip()]
            return sorted(files, key=lambda x: (len(x), x))
        return []

    def list_files_with_metadata(self, path: str) -> List[Dict]:
        """List files in remote directory with metadata including modification time and size"""
        command = f'''find "{path}" -maxdepth 1 -type f -exec sh -c '
            for file; do
                filename=$(basename "$file")
                mod_time=$(stat -c %Y "$file")
                file_size=$(stat -c %s "$file")
                echo "$filename|$mod_time|$file_size"
            done
        ' _ {{}} +'''
        
        exit_code, output, error = self.execute_command(command)
        
        files = []
        if exit_code == 0 and output:
            for line in output.strip().split('\n'):
                if line.strip() and '|' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 3:
                        filename, mod_time, file_size = parts[0], parts[1], parts[2]
                        try:
                            files.append({
                                'name': filename,
                                'modification_time': int(mod_time),
                                'size': int(file_size)
                            })
                        except ValueError:
                            # Fallback for invalid data
                            files.append({
                                'name': filename,
                                'modification_time': 0,
                                'size': 0
                            })
        
        return sorted(files, key=lambda x: x['modification_time'], reverse=True)

    def get_folder_file_summary(self, path: str) -> Dict:
        """Get summary of files in a folder including count, total size, and most recent modification"""
        command = f'''find "{path}" -type f -exec sh -c '
            total_size=0
            latest_time=0
            file_count=0
            for file; do
                file_count=$((file_count + 1))
                file_size=$(stat -c %s "$file")
                mod_time=$(stat -c %Y "$file")
                total_size=$((total_size + file_size))
                if [ $mod_time -gt $latest_time ]; then
                    latest_time=$mod_time
                fi
            done
            echo "$file_count|$total_size|$latest_time"
        ' _ {{}} +'''
        
        exit_code, output, error = self.execute_command(command)
        
        if exit_code == 0 and output:
            try:
                parts = output.strip().split('|')
                if len(parts) >= 3:
                    return {
                        'file_count': int(parts[0]),
                        'total_size': int(parts[1]),
                        'latest_modification': int(parts[2])
                    }
            except ValueError:
                pass
        
        return {
            'file_count': 0,
            'total_size': 0,
            'latest_modification': 0
        }



# Initialize global objects
config = DragonCPConfig()
ssh_manager = None
db_manager = DatabaseManager()
transfer_manager = TransferManager(config, db_manager, socketio)
simulator = TransferSimulator(transfer_manager, socketio)

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Configuration API"""
    if request.method == 'GET':
        return jsonify(config.get_all_config())
    else:
        data = request.json
        config.update_session_config(data)
        return jsonify({"status": "success", "message": "Configuration saved"})

@app.route('/api/connect', methods=['POST'])
def api_connect():
    """Connect to SSH server"""
    global ssh_manager
    
    print("🔌 API: /api/connect called")
    
    data = request.json
    host = data.get('host')
    username = data.get('username')
    password = data.get('password')
    key_path = data.get('key_path')
    
    print(f"🔗 Connection attempt to {username}@{host}")
    
    if not host or not username:
        print("❌ Missing host or username")
        return jsonify({"status": "error", "message": "Host and username are required"})
    
    ssh_manager = SSHManager(host, username, password, key_path)
    if ssh_manager.connect():
        print("✅ SSH connection successful")
        session['ssh_connected'] = True
        return jsonify({"status": "success", "message": "Connected successfully"})
    else:
        print("❌ SSH connection failed")
        return jsonify({"status": "error", "message": "Connection failed"})

@app.route('/api/disconnect')
def api_disconnect():
    """Disconnect from SSH server"""
    global ssh_manager
    
    if ssh_manager:
        ssh_manager.disconnect()
        ssh_manager = None
    
    session['ssh_connected'] = False
    return jsonify({"status": "success", "message": "Disconnected"})

@app.route('/api/media-types')
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

@app.route('/api/folders/<media_type>')
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

@app.route('/api/seasons/<media_type>/<folder_name>')
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

@app.route('/api/episodes/<media_type>/<folder_name>/<season_name>')
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

@app.route('/api/sync-status/<media_type>')
def api_sync_status(media_type):
    """Get sync status for all folders in a media type"""
    print(f"🔍 API: /api/sync-status/{media_type} called")
    
    if not ssh_manager or not ssh_manager.connected:
        print("❌ Not connected to server")
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    if not transfer_manager:
        print("❌ Transfer manager not available")
        return jsonify({"status": "error", "message": "Transfer manager not available"})
    
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
                status = transfer_manager.transfer_model.get_sync_status(
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
                    
                    summary = transfer_manager.transfer_model.get_folder_sync_status_summary(
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

@app.route('/api/sync-status/<media_type>/<folder_name>')
def api_folder_sync_status(media_type, folder_name):
    """Get detailed sync status for a specific folder (useful for series/anime seasons)"""
    print(f"🔍 API: /api/sync-status/{media_type}/{folder_name} called")
    
    if not ssh_manager or not ssh_manager.connected:
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    if not transfer_manager:
        return jsonify({"status": "error", "message": "Transfer manager not available"})
    
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
            status = transfer_manager.transfer_model.get_sync_status(
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
            
            summary = transfer_manager.transfer_model.get_folder_sync_status_summary(
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

@app.route('/api/sync-status/<media_type>/<folder_name>/enhanced')
def api_enhanced_folder_sync_status(media_type, folder_name):
    """Get enhanced sync status with detailed file information"""
    print(f"🔍 API: /api/sync-status/{media_type}/{folder_name}/enhanced called")
    
    if not ssh_manager or not ssh_manager.connected:
        return jsonify({"status": "error", "message": "Not connected to server"})
    
    if not transfer_manager:
        return jsonify({"status": "error", "message": "Transfer manager not available"})
    
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
            status = transfer_manager.transfer_model.get_sync_status(
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
                season_status = transfer_manager.transfer_model.get_sync_status(
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

@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    """Start a transfer"""
    try:
        data = request.json
        transfer_type = data.get('type')  # 'folder' or 'file'
        media_type = data.get('media_type')
        folder_name = data.get('folder_name')
        season_name = data.get('season_name')
        episode_name = data.get('episode_name')
        
        print(f"🔄 Transfer request: {data}")
        
        if not media_type or not folder_name:
            print("❌ Missing media_type or folder_name")
            return jsonify({"status": "error", "message": "Media type and folder name are required"})
        
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
        
        # Construct source path
        source_path = f"{base_source}/{folder_name}"
        if season_name:
            source_path = f"{source_path}/{season_name}"
        
        # Construct destination path
        dest_path = f"{base_dest}/{folder_name}"
        if season_name:
            dest_path = f"{dest_path}/{season_name}"
        
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
        print(f"   - transfer_type: {transfer_type}")
        
        try:
            success = transfer_manager.start_transfer(
                transfer_id, 
                source_path, 
                dest_path, 
                transfer_type,
                media_type,
                folder_name,
                season_name,
                episode_name
            )
            
            if success:
                print(f"✅ Transfer {transfer_id} started successfully")
                # Verify the transfer was created in database
                db_transfer = transfer_manager.get_transfer_status(transfer_id)
                if db_transfer:
                    print(f"✅ Transfer {transfer_id} found in database with status: {db_transfer['status']}")
                else:
                    print(f"❌ Transfer {transfer_id} NOT found in database!")
                
                return jsonify({
                    "status": "success", 
                    "transfer_id": transfer_id,
                    "message": "Transfer started",
                    "source": source_path,
                    "destination": dest_path
                })
            else:
                print(f"❌ Failed to start transfer {transfer_id}")
                return jsonify({"status": "error", "message": "Failed to start transfer"})
                
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

@app.route('/api/transfer/<transfer_id>/status')
def api_transfer_status(transfer_id):
    """Get transfer status"""
    transfer = transfer_manager.get_transfer_status(transfer_id)
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
                "episode_name": transfer.get("episode_name"),
                "parsed_title": transfer.get("parsed_title"),
                "parsed_season": transfer.get("parsed_season"),
                "parsed_episode": transfer.get("parsed_episode"),
                "transfer_type": transfer["transfer_type"],
                "source_path": transfer["source_path"],
                "dest_path": transfer["dest_path"]
            }
        })
    else:
        return jsonify({"status": "error", "message": "Transfer not found"})

@app.route('/api/transfer/<transfer_id>/cancel', methods=['POST'])
def api_cancel_transfer(transfer_id):
    """Cancel a transfer"""
    success = transfer_manager.cancel_transfer(transfer_id)
    if success:
        return jsonify({"status": "success", "message": "Transfer cancelled"})
    else:
        return jsonify({"status": "error", "message": "Failed to cancel transfer"})

@app.route('/api/transfer/<transfer_id>/logs')
def api_transfer_logs(transfer_id):
    """Get full logs for a transfer"""
    transfer = transfer_manager.get_transfer_status(transfer_id)
    if transfer:
        return jsonify({
            "status": "success",
            "logs": transfer["logs"],
            "log_count": len(transfer["logs"]),
            "transfer_status": transfer["status"]
        })
    else:
        return jsonify({"status": "error", "message": "Transfer not found"})

@app.route('/api/transfers/all')
def api_all_transfers():
    """Get all transfers with optional filtering"""
    try:
        limit = request.args.get('limit', 50, type=int)
        status_filter = request.args.get('status')
        
        transfers = transfer_manager.get_all_transfers(limit=limit)
        
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
                "episode_name": transfer.get("episode_name"),
                "parsed_title": transfer.get("parsed_title"),
                "parsed_season": transfer.get("parsed_season"),
                "parsed_episode": transfer.get("parsed_episode"),
                "transfer_type": transfer["transfer_type"],
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

@app.route('/api/transfers/active')
def api_active_transfers():
    """Get only active (running/pending) transfers"""
    try:
        active_transfers = transfer_manager.get_active_transfers()
        
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
                "episode_name": transfer.get("episode_name"),
                "parsed_title": transfer.get("parsed_title"),
                "parsed_season": transfer.get("parsed_season"),
                "parsed_episode": transfer.get("parsed_episode"),
                "transfer_type": transfer["transfer_type"],
                "source_path": transfer["source_path"],
                "dest_path": transfer["dest_path"],
                "start_time": transfer["start_time"],
                "process_id": transfer.get("process_id"),
                "log_count": len(transfer["logs"])
            }
            formatted_transfers.append(formatted_transfer)
        
        return jsonify({
            "status": "success",
            "transfers": formatted_transfers,
            "total": len(formatted_transfers)
        })
        
    except Exception as e:
        print(f"❌ Error getting active transfers: {e}")
        return jsonify({"status": "error", "message": f"Failed to get active transfers: {str(e)}"})

@app.route('/api/transfer/<transfer_id>/restart', methods=['POST'])
def api_restart_transfer(transfer_id):
    """Restart a failed or cancelled transfer"""
    try:
        success = transfer_manager.restart_transfer(transfer_id)
        if success:
            return jsonify({"status": "success", "message": "Transfer restarted successfully"})
        else:
            return jsonify({"status": "error", "message": "Failed to restart transfer"})
    except Exception as e:
        print(f"❌ Error restarting transfer {transfer_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to restart transfer: {str(e)}"})

@app.route('/api/transfer/<transfer_id>/delete', methods=['POST'])
def api_delete_transfer(transfer_id):
    """Delete a transfer record from the database"""
    try:
        # Get the transfer details first
        transfer = transfer_manager.transfer_model.get(transfer_id)
        if not transfer:
            return jsonify({"status": "error", "message": "Transfer not found"})
        
        # Check if transfer is currently running
        if transfer['status'] == 'running':
            return jsonify({"status": "error", "message": "Cannot delete a running transfer. Please cancel it first."})
        
        # Delete the transfer
        deleted = transfer_manager.transfer_model.delete(transfer_id)
        if deleted:
            return jsonify({"status": "success", "message": "Transfer deleted successfully"})
        else:
            return jsonify({"status": "error", "message": "Failed to delete transfer"})
    except Exception as e:
        print(f"❌ Error deleting transfer {transfer_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to delete transfer: {str(e)}"})

@app.route('/api/backups')
def api_list_backups():
    """List transfer backups."""
    try:
        limit = request.args.get('limit', 100, type=int)
        include_deleted = request.args.get('include_deleted', '0') in ('1', 'true', 'True')
        backups = transfer_manager.backup_model.get_all(limit=limit, include_deleted=include_deleted)
        return jsonify({
            "status": "success",
            "backups": backups,
            "total": len(backups)
        })
    except Exception as e:
        print(f"❌ Error listing backups: {e}")
        return jsonify({"status": "error", "message": f"Failed to list backups: {str(e)}"}), 500

@app.route('/api/backups/<backup_id>')
def api_get_backup(backup_id):
    """Get backup details."""
    try:
        backup = transfer_manager.backup_model.get(backup_id)
        if not backup:
            return jsonify({"status": "error", "message": "Backup not found"}), 404
        return jsonify({"status": "success", "backup": backup})
    except Exception as e:
        print(f"❌ Error getting backup {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to get backup: {str(e)}"}), 500

@app.route('/api/backups/<backup_id>/files')
def api_get_backup_files(backup_id):
    """List files inside a backup."""
    try:
        limit = request.args.get('limit', type=int)
        files = transfer_manager.backup_model.get_files(backup_id, limit=limit)
        return jsonify({"status": "success", "files": files, "total": len(files)})
    except Exception as e:
        print(f"❌ Error getting backup files {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to get backup files: {str(e)}"}), 500

@app.route('/api/backups/<backup_id>/restore', methods=['POST'])
def api_restore_backup(backup_id):
    """Restore a backup (optionally selected files)."""
    try:
        payload = request.json or {}
        # Legacy selective file restore path retained
        files = payload.get('files')
        if files and not isinstance(files, list):
            return jsonify({"status": "error", "message": "'files' must be a list of relative paths"}), 400
        if files:
            ok, msg = transfer_manager.restore_backup(backup_id, files)
            return (jsonify({"status": "success", "message": msg}) if ok
                    else (jsonify({"status": "error", "message": msg}), 400))

        # New snapshot-based restore flow
        transfer_id = payload.get('transfer_id')
        dry_run = bool(payload.get('dry_run', False))
        if not transfer_id:
            return jsonify({"status": "error", "message": "transfer_id is required for snapshot restore"}), 400
        restore_id = payload.get('restore_id') or f"restore_{int(time.time())}"
        ok, msg = transfer_manager.start_restore(restore_id, backup_id, transfer_id, dry_run=dry_run)
        if ok:
            return jsonify({"status": "success", "message": msg, "restore_id": restore_id})
        else:
            return jsonify({"status": "error", "message": msg}), 400
    except Exception as e:
        print(f"❌ Error restoring backup {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to restore backup: {str(e)}"}), 500

@app.route('/api/backups/<backup_id>/delete', methods=['POST'])
def api_delete_backup(backup_id):
    """Delete a backup record and optionally remove backup files from disk."""
    try:
        payload = request.json or {}
        delete_files = payload.get('delete_files', True)
        ok, msg = transfer_manager.delete_backup(backup_id, delete_files=bool(delete_files))
        if ok:
            return jsonify({"status": "success", "message": msg})
        else:
            return jsonify({"status": "error", "message": msg}), 400
    except Exception as e:
        print(f"❌ Error deleting backup {backup_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to delete backup: {str(e)}"}), 500

@app.route('/api/backups/reindex', methods=['POST'])
def api_reindex_backups():
    """Scan BACKUP_PATH for existing backup folders and import missing ones."""
    try:
        imported, skipped = transfer_manager.reindex_backups()
        return jsonify({
            "status": "success",
            "message": f"Imported {imported} backups, skipped {skipped}.",
            "imported": imported,
            "skipped": skipped
        })
    except Exception as e:
        print(f"❌ Error reindexing backups: {e}")
        return jsonify({"status": "error", "message": f"Failed to reindex backups: {str(e)}"}), 500

# ===== New Analysis/Snapshot/Sync/Restore APIs =====

@app.route('/api/transfers/<transfer_id>/analysis', methods=['POST'])
def api_transfer_analysis(transfer_id):
    try:
        result = transfer_manager.analyze_sync(transfer_id)
        return jsonify({"status": "success", "analysis": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/transfers/<transfer_id>/snapshot', methods=['POST'])
def api_transfer_snapshot(transfer_id):
    try:
        payload = request.json or {}
        category = payload.get('category', 'pre_sync_snapshot')
        related_to = payload.get('related_to')
        snap_id = transfer_manager.create_snapshot(transfer_id, category=category, related_to=related_to)
        if snap_id:
            return jsonify({"status": "success", "snapshot_id": snap_id})
        return jsonify({"status": "error", "message": "Snapshot not created (possibly empty dest)"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/transfers/<transfer_id>/sync', methods=['POST'])
def api_transfer_sync(transfer_id):
    try:
        payload = request.json or {}
        strategy = payload.get('strategy', 'auto')
        dry_run = bool(payload.get('dry_run', False))
        ok = transfer_manager.run_sync(transfer_id, strategy=strategy, dry_run=dry_run)
        if ok:
            return jsonify({"status": "success", "message": "Sync started", "strategy": strategy, "dry_run": dry_run})
        return jsonify({"status": "error", "message": "Failed to start sync"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/restores', methods=['POST'])
def api_start_restore():
    try:
        payload = request.json or {}
        source_backup_id = payload.get('source_backup_id')
        transfer_id = payload.get('transfer_id')
        dry_run = bool(payload.get('dry_run', False))
        if not source_backup_id or not transfer_id:
            return jsonify({"status": "error", "message": "source_backup_id and transfer_id are required"}), 400
        restore_id = payload.get('restore_id') or f"restore_{int(time.time())}"
        ok, msg = transfer_manager.start_restore(restore_id, source_backup_id, transfer_id, dry_run=dry_run)
        if ok:
            return jsonify({"status": "success", "message": msg, "restore_id": restore_id})
        else:
            return jsonify({"status": "error", "message": msg}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/restores/<restore_id>/undo', methods=['POST'])
def api_undo_restore(restore_id):
    try:
        payload = request.json or {}
        dry_run = bool(payload.get('dry_run', False))
        ok, msg = transfer_manager.undo_restore(restore_id, dry_run=dry_run)
        if ok:
            return jsonify({"status": "success", "message": msg})
        else:
            return jsonify({"status": "error", "message": msg}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/restores', methods=['GET'])
def api_list_restores():
    try:
        transfer_id = request.args.get('transfer_id')
        limit = request.args.get('limit', 100, type=int)
        items = transfer_manager.list_restores(transfer_id=transfer_id, limit=limit)
        return jsonify({"status": "success", "restores": items, "total": len(items)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/transfers/cleanup', methods=['POST'])
def api_cleanup_transfers():
    """Remove duplicate transfers based on destination path, keeping only the latest successful transfer"""
    try:
        cleaned = transfer_manager.transfer_model.cleanup_duplicate_transfers()
        return jsonify({
            "status": "success", 
            "message": f"Cleaned up {cleaned} duplicate transfers",
            "cleaned_count": cleaned
        })
    except Exception as e:
        print(f"❌ Error cleaning up duplicate transfers: {e}")
        return jsonify({"status": "error", "message": f"Failed to cleanup duplicate transfers: {str(e)}"})

@app.route('/api/test/simulate', methods=['POST'])
def api_start_simulation():
    """Start simulated transfers for UI testing (no rsync). Controlled by TEST_MODE env."""
    if os.environ.get('TEST_MODE', '0') != '1':
        return jsonify({"status": "error", "message": "Simulation disabled. Set TEST_MODE=1 to enable."}), 403

    try:
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
def api_stop_simulation():
    """Signal all running simulations to stop."""
    if os.environ.get('TEST_MODE', '0') != '1':
        return jsonify({"status": "error", "message": "Simulation disabled. Set TEST_MODE=1 to enable."}), 403

    try:
        num = simulator.stop_all()
        return jsonify({"status": "success", "message": f"Stop signaled to {num} simulations"})
    except Exception as e:
        print(f"❌ Error stopping simulation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/local-files')
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

@app.route('/api/auto-connect')
def api_auto_connect():
    """Auto-connect using environment variables"""
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
    
    ssh_manager = SSHManager(host, username, password if password else None, key_path if key_path else None)
    if ssh_manager.connect():
        print("✅ Auto-connection successful")
        session['ssh_connected'] = True
        return jsonify({"status": "success", "message": "Auto-connected successfully"})
    else:
        print("❌ Auto-connection failed")
        return jsonify({"status": "error", "message": "Auto-connection failed"})

@app.route('/api/ssh-config')
def api_ssh_config():
    """Get SSH configuration from environment"""
    ssh_config = {
        "host": config.get("REMOTE_IP", ""),
        "username": config.get("REMOTE_USER", ""),
        "password": config.get("REMOTE_PASSWORD", ""),
        "key_path": config.get("SSH_KEY_PATH", "")
    }
    return jsonify(ssh_config)

@app.route('/api/config/reset', methods=['POST'])
def api_reset_config():
    """Reset session configuration to environment values"""
    if 'ui_config' in session:
        del session['ui_config']
    return jsonify({"status": "success", "message": "Configuration reset to environment values"})

@app.route('/api/config/env-only')
def api_env_config():
    """Get only environment configuration (without session overrides)"""
    return jsonify(config.env_config)

@app.route('/api/disk-usage/local')
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

@app.route('/api/disk-usage/remote')
def api_remote_disk_usage():
    """Get remote disk usage from configured API"""
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

@app.route('/api/debug')
def api_debug():
    """Debug endpoint to check configuration and SSH status"""
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
            "active_transfers": len(transfer_manager.transfers),
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

@app.route('/api/debug/transfers')
def api_debug_transfers():
    """Debug endpoint to check database transfers"""
    try:
        # Get all transfers from database
        all_transfers = transfer_manager.get_all_transfers(limit=10)
        active_transfers = transfer_manager.get_active_transfers()
        
        debug_info = {
            "timestamp": datetime.now().isoformat(),
            "database_path": db_manager.db_path,
            "database_exists": os.path.exists(db_manager.db_path),
            "total_transfers_in_db": len(all_transfers),
            "active_transfers_in_db": len(active_transfers),
            "recent_transfers": all_transfers[:5],  # Last 5 transfers
            "transfer_manager_type": str(type(transfer_manager)),
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

# WebSocket Events for connection management
@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    session_id = request.sid
    websocket_connections[session_id] = {
        'connected_at': datetime.now(),
        'last_activity': datetime.now(),
        'timeout_seconds': get_websocket_timeout_for_session()  # Store timeout for this session
    }
    print(f"🔌 WebSocket connected: {session_id}")
    print(f"🔌 Active WebSocket connections: {len(websocket_connections)}")

@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    session_id = request.sid
    if session_id in websocket_connections:
        del websocket_connections[session_id]
    print(f"🔌 WebSocket disconnected: {session_id}")
    print(f"🔌 Active WebSocket connections: {len(websocket_connections)}")

@socketio.on('activity')
def handle_activity():
    """Handle client activity ping"""
    session_id = request.sid
    if session_id in websocket_connections:
        websocket_connections[session_id]['last_activity'] = datetime.now()

def cleanup_stale_connections():
    """Cleanup stale WebSocket connections"""
    while True:
        try:
            current_time = datetime.now()
            
            stale_connections = []
            for session_id, connection_info in websocket_connections.items():
                # Get timeout for this specific session (stored when connection was made)
                session_timeout = connection_info.get('timeout_seconds', WEBSOCKET_TIMEOUT_DEFAULT)
                timeout_threshold = current_time - timedelta(seconds=session_timeout)
                
                if connection_info['last_activity'] < timeout_threshold:
                    stale_connections.append(session_id)
            
            for session_id in stale_connections:
                print(f"🧹 Cleaning up stale WebSocket connection: {session_id}")
                if session_id in websocket_connections:
                    del websocket_connections[session_id]
                # Disconnect the client
                socketio.disconnect(session_id)
            
            if stale_connections:
                print(f"🧹 Cleaned up {len(stale_connections)} stale connections")
                print(f"🔌 Active WebSocket connections: {len(websocket_connections)}")
                
        except Exception as e:
            print(f"❌ Error in cleanup_stale_connections: {e}")
        
        # Sleep for 5 minutes before next cleanup
        time.sleep(5 * 60)

# Start the cleanup thread
cleanup_thread = threading.Thread(target=cleanup_stale_connections, daemon=True)
cleanup_thread.start()

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    print("DragonCP Web UI starting...")
    print("Access the application at: http://localhost:5000")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True) 