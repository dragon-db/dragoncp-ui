#!/usr/bin/env python3
"""
DragonCP SSH Manager
Handles SSH connections and remote operations
"""

import os
import paramiko
from typing import List, Dict, Tuple


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

