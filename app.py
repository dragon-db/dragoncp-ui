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
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import paramiko
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dragoncp-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

socketio = SocketIO(app, cors_allowed_origins="*")

# Global variables for SSH connection
ssh_client = None
ssh_connected = False

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
        # First check session config (UI overrides)
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
    
    def list_files(self, path: str) -> List[str]:
        """List files in remote directory"""
        # Fix escape sequence warning by using raw string
        command = f'find "{path}" -maxdepth 1 -type f -exec basename "{{}}" \\;'
        exit_code, output, error = self.execute_command(command)
        
        if exit_code == 0 and output:
            files = [f.strip() for f in output.split('\n') if f.strip()]
            return sorted(files, key=lambda x: (len(x), x))
        return []

class TransferManager:
    """Manage file transfers using rsync"""
    
    def __init__(self, config: DragonCPConfig):
        self.config = config
        self.transfers = {}
    
    def start_transfer(self, transfer_id: str, source_path: str, dest_path: str, 
                      transfer_type: str = "folder") -> bool:
        """Start a new transfer"""
        try:
            # Create destination directory
            os.makedirs(dest_path, exist_ok=True)
            
            # Get SSH connection details
            ssh_user = self.config.get("REMOTE_USER")
            ssh_host = self.config.get("REMOTE_IP")
            
            if not ssh_user or not ssh_host:
                print("❌ SSH credentials not configured")
                return False
            
            # Build rsync command with SSH connection
            rsync_cmd = [
                "rsync", "-av",
                "--progress",
                "-e", f"ssh -o StrictHostKeyChecking=no -o Compression=no",
                "--delete",
                "--backup",
                "--backup-dir", self.config.get("BACKUP_PATH", "/tmp/backup"),
                "--update",
                "--exclude", ".*",
                "--exclude", "*.tmp",
                "--exclude", "*.log",
                "--stats",
                "--human-readable",
                "--bwlimit=0",
                "--block-size=65536",
                "--no-compress",
                "--partial",
                "--partial-dir", f"{self.config.get('BACKUP_PATH', '/tmp/backup')}/.rsync-partial",
                "--timeout=300",
                "--size-only",
                "--no-perms",
                "--no-owner",
                "--no-group",
                "--no-checksum",
                "--whole-file",
                "--preallocate",
                "--no-motd"
            ]
            
            if transfer_type == "file":
                rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}", f"{dest_path}/"])
            else:
                rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}/", f"{dest_path}/"])
            
            print(f"🔄 Starting rsync: {' '.join(rsync_cmd)}")
            
            # Start transfer in background
            process = subprocess.Popen(
                rsync_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            self.transfers[transfer_id] = {
                "process": process,
                "source": source_path,
                "dest": dest_path,
                "type": transfer_type,
                "start_time": datetime.now(),
                "status": "running",
                "progress": "",
                "logs": []
            }
            
            # Start monitoring thread
            threading.Thread(target=self._monitor_transfer, args=(transfer_id,), daemon=True).start()
            
            return True
        except Exception as e:
            print(f"Transfer start failed: {e}")
            return False
    
    def _monitor_transfer(self, transfer_id: str):
        """Monitor transfer progress"""
        if transfer_id not in self.transfers:
            return
        
        transfer = self.transfers[transfer_id]
        process = transfer["process"]
        
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    transfer["logs"].append(line.strip())
                    transfer["progress"] = line.strip()
                    
                    # Emit progress via WebSocket with full logs
                    socketio.emit('transfer_progress', {
                        'transfer_id': transfer_id,
                        'progress': line.strip(),
                        'logs': transfer["logs"],  # Send full logs instead of just last 10
                        'log_count': len(transfer["logs"])
                    })
            
            # Wait for process to complete
            process.wait()
            
            if process.returncode == 0:
                transfer["status"] = "completed"
                transfer["progress"] = "Transfer completed successfully!"
            else:
                transfer["status"] = "failed"
                transfer["progress"] = f"Transfer failed with exit code: {process.returncode}"
            
            # Emit completion status
            socketio.emit('transfer_complete', {
                'transfer_id': transfer_id,
                'status': transfer["status"],
                'message': transfer["progress"],
                'logs': transfer["logs"],  # Include full logs in completion
                'log_count': len(transfer["logs"])
            })
            
        except Exception as e:
            transfer["status"] = "failed"
            transfer["progress"] = f"Transfer monitoring failed: {e}"
            socketio.emit('transfer_complete', {
                'transfer_id': transfer_id,
                'status': 'failed',
                'message': transfer["progress"],
                'logs': transfer["logs"],
                'log_count': len(transfer["logs"])
            })
    
    def get_transfer_status(self, transfer_id: str) -> Optional[Dict]:
        """Get transfer status"""
        return self.transfers.get(transfer_id)
    
    def cancel_transfer(self, transfer_id: str) -> bool:
        """Cancel a running transfer"""
        if transfer_id in self.transfers:
            transfer = self.transfers[transfer_id]
            if transfer["status"] == "running" and transfer["process"]:
                transfer["process"].terminate()
                transfer["status"] = "cancelled"
                return True
        return False

# Initialize global objects
config = DragonCPConfig()
ssh_manager = None
transfer_manager = TransferManager(config)

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
    
    print(f"🔍 Listing folders in: {path}")
    folders = ssh_manager.list_folders(path)
    print(f"📁 Found folders: {folders}")
    
    return jsonify({"status": "success", "folders": folders})

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
    seasons = ssh_manager.list_folders(full_path)
    return jsonify({"status": "success", "seasons": seasons})

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

@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    """Start a transfer"""
    data = request.json
    transfer_type = data.get('type')  # 'folder' or 'file'
    media_type = data.get('media_type')
    folder_name = data.get('folder_name')
    season_name = data.get('season_name')
    episode_name = data.get('episode_name')
    
    print(f"🔄 Transfer request: {data}")
    
    if not media_type or not folder_name:
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
    
    if not base_source:
        return jsonify({"status": "error", "message": f"Source path not configured for {media_type}"})
    
    if not base_dest:
        return jsonify({"status": "error", "message": f"Destination path not configured for {media_type}"})
    
    # Construct source path
    source_path = f"{base_source}/{folder_name}"
    if season_name:
        source_path = f"{source_path}/{season_name}"
    
    # Construct destination path
    dest_path = f"{base_dest}/{folder_name}"
    if season_name:
        dest_path = f"{dest_path}/{season_name}"
    
    print(f"📁 Source: {source_path}")
    print(f"📁 Destination: {dest_path}")
    
    # Generate transfer ID
    transfer_id = f"transfer_{int(time.time())}"
    
    # Start transfer
    success = transfer_manager.start_transfer(transfer_id, source_path, dest_path, transfer_type)
    
    if success:
        return jsonify({
            "status": "success", 
            "transfer_id": transfer_id,
            "message": "Transfer started",
            "source": source_path,
            "destination": dest_path
        })
    else:
        return jsonify({"status": "error", "message": "Failed to start transfer"})

@app.route('/api/transfer/<transfer_id>/status')
def api_transfer_status(transfer_id):
    """Get transfer status"""
    status = transfer_manager.get_transfer_status(transfer_id)
    if status:
        return jsonify({
            "status": "success",
            "transfer": {
                "id": transfer_id,
                "status": status["status"],
                "progress": status["progress"],
                "logs": status["logs"],
                "log_count": len(status["logs"]),
                "start_time": status["start_time"].isoformat()
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
    status = transfer_manager.get_transfer_status(transfer_id)
    if status:
        return jsonify({
            "status": "success",
            "logs": status["logs"],
            "log_count": len(status["logs"]),
            "transfer_status": status["status"]
        })
    else:
        return jsonify({"status": "error", "message": "Transfer not found"})

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

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    print("DragonCP Web UI starting...")
    print("Access the application at: http://localhost:5000")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True) 