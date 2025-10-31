#!/usr/bin/env python3
"""
DragonCP Transfer Service
Handles rsync process lifecycle: start, monitor, cancel, restart
"""

import os
import subprocess
import threading
import re
from datetime import datetime
from typing import Dict, Optional, List


class TransferService:
    """Service for rsync process management and monitoring"""
    
    def __init__(self, config, db_manager, transfer_model, socketio=None, queue_manager=None):
        self.config = config
        self.db = db_manager
        self.transfer_model = transfer_model
        self.socketio = socketio
        self.queue_manager = queue_manager
        self.transfers = {}  # Active transfer processes: {transfer_id: process}
    
    def perform_dry_run_rsync(self, source_path: str, dest_path: str, is_season_folder: bool = True) -> Dict:
        """
        Perform rsync dry-run to validate sync safety
        
        Returns detailed validation results including:
        - Deleted file count
        - Incoming file count
        - Total file counts (server vs local)
        - List of deleted/incoming files
        - Safety status
        """
        try:
            print(f"🔍 Starting dry-run validation")
            print(f"   Source: {source_path}")
            print(f"   Dest: {dest_path}")
            
            # Get SSH connection details
            ssh_user = self.config.get("REMOTE_USER")
            ssh_host = self.config.get("REMOTE_IP")
            ssh_key_path = self.config.get("SSH_KEY_PATH", "")
            
            if not ssh_user or not ssh_host:
                return {
                    'safe_to_sync': False,
                    'reason': 'SSH credentials not configured',
                    'deleted_count': 0,
                    'incoming_count': 0,
                    'server_file_count': 0,
                    'local_file_count': 0,
                    'deleted_files': [],
                    'incoming_files': []
                }
            
            # Resolve SSH key path
            if ssh_key_path:
                if not os.path.isabs(ssh_key_path):
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    ssh_key_path = os.path.join(os.path.dirname(script_dir), ssh_key_path)
                if not os.path.exists(ssh_key_path):
                    ssh_key_path = ""
            
            # Build SSH options
            ssh_options = ["-o", "StrictHostKeyChecking=no", "-o", "Compression=no"]
            if ssh_key_path and os.path.exists(ssh_key_path):
                ssh_options.extend(["-i", ssh_key_path])
            
            # Build dry-run rsync command
            rsync_cmd = [
                "rsync", "-av",
                "--dry-run",
                "--stats",
                "--itemize-changes",
                "--delete",
                "--exclude", ".*",
                "--exclude", "*.tmp",
                "--exclude", "*.log",
                "--size-only",
                "--no-perms",
                "--no-owner",
                "--no-group",
                "-e", f"ssh {' '.join(ssh_options)}"
            ]
            
            # Add source and destination
            if is_season_folder:
                rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}/", f"{dest_path}/"])
            else:
                rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}", f"{dest_path}/"])
            
            print(f"🔄 Executing dry-run: {' '.join(rsync_cmd)}")
            
            # Execute dry-run
            result = subprocess.run(
                rsync_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=300  # 5 minute timeout
            )
            
            # Parse output with destination path for local file counting
            validation_result = self._parse_dry_run_output(result.stdout, result.stderr, dest_path)
            
            # Perform safety checks
            deleted_count = validation_result['deleted_count']
            incoming_count = validation_result['incoming_count']
            server_file_count = validation_result['server_file_count']
            local_file_count = validation_result['local_file_count']
            
            # BOTH validation approaches:
            # 1. Server files >= Local files
            # 2. Deleted files <= Incoming files
            
            reasons = []
            
            # Check 1: Server should have at least as many files as local
            if server_file_count > 0 and local_file_count > 0:
                if server_file_count < local_file_count:
                    reasons.append(f"Server has fewer media files ({server_file_count}) than local ({local_file_count})")
            
            # Check 2: Deleted files should not exceed incoming files
            if deleted_count > incoming_count:
                reasons.append(f"Would delete {deleted_count} media files but only receive {incoming_count} new files")
            
            safe_to_sync = len(reasons) == 0
            reason = "; ".join(reasons) if reasons else "All safety checks passed"
            
            validation_result['safe_to_sync'] = safe_to_sync
            validation_result['reason'] = reason
            
            print(f"📊 Dry-run results:")
            print(f"   Server files: {server_file_count}")
            print(f"   Local files: {local_file_count}")
            print(f"   Deleted: {deleted_count}")
            print(f"   Incoming: {incoming_count}")
            print(f"   Safe to sync: {safe_to_sync}")
            if not safe_to_sync:
                print(f"   Reason: {reason}")
            
            return validation_result
            
        except subprocess.TimeoutExpired:
            print(f"❌ Dry-run timed out")
            return {
                'safe_to_sync': False,
                'reason': 'Dry-run operation timed out',
                'deleted_count': 0,
                'incoming_count': 0,
                'server_file_count': 0,
                'local_file_count': 0,
                'deleted_files': [],
                'incoming_files': []
            }
        except Exception as e:
            print(f"❌ Error during dry-run: {e}")
            import traceback
            traceback.print_exc()
            return {
                'safe_to_sync': False,
                'reason': f'Dry-run execution error: {str(e)}',
                'deleted_count': 0,
                'incoming_count': 0,
                'server_file_count': 0,
                'local_file_count': 0,
                'deleted_files': [],
                'incoming_files': []
            }
    
    def _count_local_media_files(self, dest_path: str) -> int:
        """Count media files in the local destination directory"""
        media_extensions = ('.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.flv', '.webm', '.ts')
        
        # Check if destination exists
        if not os.path.exists(dest_path):
            return 0
        
        count = 0
        try:
            for root, dirs, files in os.walk(dest_path):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in media_extensions):
                        count += 1
        except Exception as e:
            print(f"⚠️  Error counting local media files in {dest_path}: {e}")
            return 0
        
        return count
    
    def _parse_dry_run_output(self, stdout: str, stderr: str, dest_path: str = None) -> Dict:
        """Parse rsync dry-run output to extract file counts and lists"""
        
        deleted_files = []
        incoming_files = []
        
        # Media file extensions to count
        media_extensions = ('.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.flv', '.webm', '.ts')
        
        # Parse itemize-changes output
        for line in stdout.split('\n'):
            line = line.strip()
            
            # *deleting indicates a file will be deleted
            if line.startswith('*deleting'):
                file_path = line.replace('*deleting', '').strip()
                # Only count media files
                if any(file_path.lower().endswith(ext) for ext in media_extensions):
                    deleted_files.append(file_path)
            
            # >f+++++++++ indicates a new file will be transferred
            # >f.st...... indicates file size/time change
            elif line.startswith('>f'):
                # Extract filename (after the itemize prefix)
                if len(line) > 11:
                    file_path = line[11:].strip()
                    if any(file_path.lower().endswith(ext) for ext in media_extensions):
                        incoming_files.append(file_path)
        
        # Count server files from rsync stats section
        server_file_count = 0
        stats_pattern = r'Number of (?:regular )?files: (\d+)'
        stats_match = re.search(stats_pattern, stdout)
        if stats_match:
            server_file_count = int(stats_match.group(1))
        
        # If we can't get exact server count, estimate it
        if server_file_count == 0:
            server_file_count = len(incoming_files)
        
        # Count actual local media files from filesystem
        local_file_count = 0
        if dest_path:
            local_file_count = self._count_local_media_files(dest_path)
            print(f"📊 Local media file count in {dest_path}: {local_file_count}")
        
        return {
            'deleted_count': len(deleted_files),
            'incoming_count': len(incoming_files),
            'server_file_count': server_file_count,
            'local_file_count': local_file_count,
            'deleted_files': deleted_files[:50],  # Limit to first 50 for storage
            'incoming_files': incoming_files[:50],
            'raw_output': stdout[:5000]  # Store first 5000 chars of output for debugging
        }
    
    def start_rsync_process(self, transfer_id: str, source_path: str, dest_path: str, transfer_type: str, backup_dir: str) -> bool:
        """Start the rsync process"""
        try:
            print(f"🔄 Starting transfer {transfer_id}")
            print(f"📁 Source: {source_path}")
            print(f"📁 Destination: {dest_path}")
            print(f"📁 Type: {transfer_type}")
            
            # Create destination directory
            try:
                # Check TEST_MODE before creating destination directory
                if os.environ.get('TEST_MODE', '0') == '1':
                    print(f"🧪 TEST_MODE: Would create destination directory: {dest_path}")
                else:
                    os.makedirs(dest_path, exist_ok=True)
                    print(f"✅ Created destination directory: {dest_path}")
            except Exception as e:
                print(f"❌ Failed to create destination directory: {e}")
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': f'Failed to create destination: {e}',
                    'end_time': datetime.now().isoformat()
                })
                return False
            
            # Get SSH connection details
            ssh_user = self.config.get("REMOTE_USER")
            ssh_host = self.config.get("REMOTE_IP")
            ssh_password = self.config.get("REMOTE_PASSWORD", "")
            ssh_key_path = self.config.get("SSH_KEY_PATH", "")
            
            print(f"🔑 SSH User: {ssh_user}")
            print(f"🔑 SSH Host: {ssh_host}")
            print(f"🔑 SSH Key Path: {ssh_key_path}")
            
            if not ssh_user or not ssh_host:
                print("❌ SSH credentials not configured")
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': 'SSH credentials not configured',
                    'end_time': datetime.now().isoformat()
                })
                return False
            
            # Resolve SSH key path to absolute path if it exists
            if ssh_key_path:
                if not os.path.isabs(ssh_key_path):
                    # If relative path, make it absolute relative to the app directory
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    ssh_key_path = os.path.join(os.path.dirname(script_dir), ssh_key_path)
                
                if not os.path.exists(ssh_key_path):
                    print(f"❌ SSH key file not found: {ssh_key_path}")
                    ssh_key_path = ""
                else:
                    print(f"✅ SSH key found: {ssh_key_path}")
            
            # Ensure backup directory exists
            try:
                # Check TEST_MODE before creating backup directories
                if os.environ.get('TEST_MODE', '0') == '1':
                    print(f"🧪 TEST_MODE: Would create backup directories: {backup_dir}")
                else:
                    os.makedirs(backup_dir, exist_ok=True)
                    os.makedirs(os.path.join(backup_dir, '.rsync-partial'), exist_ok=True)
            except Exception as e:
                print(f"⚠️  Could not prepare dynamic backup directory: {e}")
            
            # Build rsync command with SSH connection
            rsync_cmd = [
                "rsync", "-av",
                "--progress",
                "--delete",
                "--backup",
                "--backup-dir", backup_dir,
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
                "--partial-dir", f"{backup_dir}/.rsync-partial",
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
            
            # Add --dry-run flag when TEST_MODE is enabled
            if os.environ.get('TEST_MODE', '0') == '1':
                rsync_cmd.append("--dry-run")
                print("🧪 TEST_MODE enabled - rsync will run in dry-run mode (no actual file transfers)")
            
            # Build SSH options for rsync
            ssh_options = ["-o", "StrictHostKeyChecking=no", "-o", "Compression=no"]
            if ssh_key_path and os.path.exists(ssh_key_path):
                ssh_options.extend(["-i", ssh_key_path])
            
            rsync_cmd.extend(["-e", f"ssh {' '.join(ssh_options)}"])
            
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
                bufsize=1,
                env=os.environ.copy()
            )
            
            # Check if process started successfully
            if process.poll() is not None:
                print(f"❌ rsync process failed to start, return code: {process.poll()}")
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': f'rsync process failed to start, return code: {process.poll()}',
                    'end_time': datetime.now().isoformat()
                })
                return False
            
            print(f"✅ rsync process started successfully (PID: {process.pid})")
            
            # Store process
            self.transfers[transfer_id] = process
            
            # Update transfer with process ID and running status
            self.transfer_model.update(transfer_id, {
                'status': 'running',
                'process_id': process.pid,
                'progress': 'Transfer started...'
            })
            
            # Start monitoring thread
            threading.Thread(target=self._monitor_transfer, args=(transfer_id, process), daemon=True).start()
            
            return True
            
        except Exception as e:
            print(f"❌ Transfer start failed: {e}")
            import traceback
            traceback.print_exc()
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': f'Transfer start failed: {e}',
                'end_time': datetime.now().isoformat()
            })
            return False
    
    def _monitor_transfer(self, transfer_id: str, process):
        """Monitor transfer progress with database updates"""
        print(f"🔍 Starting monitoring for transfer {transfer_id} (PID: {process.pid})")
        
        try:
            # Use the socketio instance passed to the constructor
            socketio = self.socketio
            
            # Read output line by line
            for line in iter(process.stdout.readline, ''):
                if line:
                    line = line.strip()
                    
                    # Add log line to database
                    self.transfer_model.add_log(transfer_id, line)
                    
                    # Get updated transfer data
                    transfer = self.transfer_model.get(transfer_id)
                    
                    # Emit progress via WebSocket to all clients
                    if socketio:
                        socketio.emit('transfer_progress', {
                            'transfer_id': transfer_id,
                            'progress': line,
                            'logs': transfer['logs'][-100:],  # Last 100 lines for better visibility
                            'log_count': len(transfer['logs']),
                            'status': transfer.get('status', 'running')
                        })
            
            # Wait for process to complete
            print(f"⏳ Waiting for transfer {transfer_id} to complete...")
            return_code = process.wait()
            print(f"🏁 Transfer {transfer_id} completed with return code: {return_code}")
            
            if return_code == 0:
                status = 'completed'
                progress = 'Transfer completed successfully!'
                print(f"✅ Transfer {transfer_id} completed successfully")
            else:
                status = 'failed'
                progress = f'Transfer failed with exit code: {return_code}'
                print(f"❌ Transfer {transfer_id} failed with exit code: {return_code}")
            
            # Update final status in database
            self.transfer_model.update(transfer_id, {
                'status': status,
                'progress': progress,
                'end_time': datetime.now().isoformat()
            })
            
            # Get final transfer data
            transfer = self.transfer_model.get(transfer_id)
            
            # Emit completion status to all clients
            if socketio:
                socketio.emit('transfer_complete', {
                    'transfer_id': transfer_id,
                    'status': status,
                    'message': progress,
                    'logs': transfer['logs'][-100:],
                    'log_count': len(transfer['logs'])
                })
            
            # Remove from active transfers
            if transfer_id in self.transfers:
                del self.transfers[transfer_id]
            
            return status
            
        except Exception as e:
            print(f"❌ Error monitoring transfer {transfer_id}: {e}")
            import traceback
            traceback.print_exc()
            
            error_msg = f"Transfer monitoring failed: {e}"
            
            # Update error status in database
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': error_msg,
                'end_time': datetime.now().isoformat()
            })
            
            # Add error to logs
            self.transfer_model.add_log(transfer_id, f"ERROR: {error_msg}")
            
            # Get updated transfer data
            transfer = self.transfer_model.get(transfer_id)
            
            # Emit error to all clients
            if socketio:
                socketio.emit('transfer_complete', {
                    'transfer_id': transfer_id,
                    'status': 'failed',
                    'message': error_msg,
                    'logs': transfer['logs'][-100:],
                    'log_count': len(transfer['logs'])
                })
            
            # Remove from active transfers
            if transfer_id in self.transfers:
                del self.transfers[transfer_id]
            
            return 'failed'

    def cancel_transfer(self, transfer_id: str) -> bool:
        """Cancel a running or queued transfer"""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False
        
        # Handle queued transfers (not yet started)
        if transfer['status'] == 'queued':
            self.transfer_model.update(transfer_id, {
                'status': 'cancelled',
                'progress': 'Transfer cancelled by user (was in queue)',
                'end_time': datetime.now().isoformat()
            })
            print(f"✅ Queued transfer {transfer_id} cancelled")
            return True
        
        # Handle running transfers
        if transfer['status'] == 'running' and transfer['process_id']:
            try:
                import psutil
                process = psutil.Process(transfer['process_id'])
                process.terminate()
                
                # Update status
                self.transfer_model.update(transfer_id, {
                    'status': 'cancelled',
                    'progress': 'Transfer cancelled by user',
                    'end_time': datetime.now().isoformat()
                })
                
                # Remove from active transfers
                if transfer_id in self.transfers:
                    del self.transfers[transfer_id]
                
                return True
            except Exception as e:
                print(f"❌ Error cancelling transfer {transfer_id}: {e}")
                return False
        
        return False

    def restart_transfer(self, transfer_id: str, backup_dir: str) -> bool:
        """Restart a failed or cancelled transfer"""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False
        
        if transfer['status'] in ['failed', 'cancelled', 'completed']:
            # Reset transfer status
            self.transfer_model.update(transfer_id, {
                'status': 'pending',
                'progress': 'Restarting transfer...',
                'process_id': None,
                'start_time': datetime.now().isoformat(),
                'end_time': None
            })
            
            # Start the transfer again
            return self.start_rsync_process(
                transfer_id, 
                transfer['source_path'], 
                transfer['dest_path'], 
                transfer['transfer_type'],
                backup_dir
            )
        
        return False

    def resume_active_transfers(self):
        """Resume transfers that were running when app was stopped"""
        active_transfers = self.transfer_model.get_all()
        resumed_count = 0
        
        for transfer in active_transfers:
            if transfer['status'] == 'running':
                # Check if process is still running
                if transfer['process_id'] and self._is_process_running(transfer['process_id']):
                    print(f"📋 Resuming monitoring for transfer {transfer['transfer_id']} (PID: {transfer['process_id']})")
                    # Resume monitoring in a separate thread
                    threading.Thread(
                        target=self._resume_transfer_monitoring, 
                        args=(transfer['transfer_id'],), 
                        daemon=True
                    ).start()
                    resumed_count += 1
                else:
                    # Process is no longer running, mark as failed
                    self.transfer_model.update(transfer['transfer_id'], {
                        'status': 'failed',
                        'progress': 'Transfer process was interrupted',
                        'end_time': datetime.now().isoformat()
                    })
                    print(f"❌ Transfer {transfer['transfer_id']} marked as failed (process not found)")
        
        if resumed_count > 0:
            print(f"✅ Resumed monitoring for {resumed_count} active transfers")
    
    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is still running"""
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            # Fallback method without psutil
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
    
    def _resume_transfer_monitoring(self, transfer_id: str):
        """Resume monitoring for an existing transfer"""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return
        
        try:
            import psutil
            process = psutil.Process(transfer['process_id'])
            
            # Monitor the process until completion
            process.wait()
            return_code = process.returncode
            
            if return_code == 0:
                self.transfer_model.update(transfer_id, {
                    'status': 'completed',
                    'progress': 'Transfer completed successfully!',
                    'end_time': datetime.now().isoformat()
                })
            else:
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': f'Transfer failed with exit code: {return_code}',
                    'end_time': datetime.now().isoformat()
                })
                
        except Exception as e:
            print(f"❌ Error resuming monitoring for {transfer_id}: {e}")
            self.transfer_model.update(transfer_id, {
                'status': 'failed',
                'progress': f'Monitoring failed: {e}',
                'end_time': datetime.now().isoformat()
            })

