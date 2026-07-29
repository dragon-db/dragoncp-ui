#!/usr/bin/env python3
"""
DragonCP Transfer Service
Handles rsync process lifecycle: start, monitor, cancel, restart
"""

import os
import subprocess
import threading
import re
import time
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from env_flags import test_mode_enabled


# How often a superseding progress line is allowed to reach the database. The
# UI is told about every one over the socket; this only bounds writes.
PROGRESS_WRITE_INTERVAL = 1.0

# How many trailing lines ride along on a progress event.
SOCKET_LOG_TAIL = 100

# Default speed ceiling for simulation transfers, in KB/s. A local copy would
# otherwise finish before the UI could show anything.
SIMULATION_BWLIMIT_KBPS = 4000


# rsync -h reports sizes in powers of 1000 (a bare -h, not -hh).
_SIZE_UNITS = {'': 1, 'K': 1000, 'M': 1000 ** 2, 'G': 1000 ** 3,
               'T': 1000 ** 4, 'P': 1000 ** 5}

# A progress line from rsync's --info=progress2 output, e.g.
#   "          2.70G  64%  142.31MB/s    0:00:11"
# Without --human-readable the byte count is comma grouped ("2,834,567,890"),
# and some rsync builds omit the ETA field, so both forms have to parse.
_PROGRESS_LINE_RE = re.compile(
    r'^\s*([\d,]+(?:\.\d+)?)\s*([KMGTPkmgtp]?)\s+(\d{1,3})%\s+'
    r'([\d,]+(?:\.\d+)?)\s*([KMGTPkmgtp]?)B/s'
    r'(?:\s+(\d+):(\d{2}):(\d{2}))?'
)

# The --stats summary line, which carries the exact total for the transfer set:
#   "total size is 4.21G  speedup is 1.00"
_TOTAL_SIZE_RE = re.compile(
    r'total size is\s+([\d,]+(?:\.\d+)?)\s*([KMGTPkmgtp]?)', re.IGNORECASE
)


def _to_bytes(number: str, unit: str) -> int:
    """Convert an rsync size token (e.g. "2.70", "G") to a byte count"""
    try:
        return int(float(number.replace(',', '')) * _SIZE_UNITS[unit.upper()])
    except (ValueError, KeyError):
        return 0


def parse_rsync_progress(line: str) -> Optional[Dict]:
    """
    Parse one rsync progress line into structured stats.

    Returns None for any line that is not a progress line (file names, the
    --stats block, warnings), so callers can pass every log line through.
    """
    match = _PROGRESS_LINE_RE.match(line)
    if not match:
        return None

    done_num, done_unit, percent, speed_num, speed_unit, hours, minutes, seconds = match.groups()

    stats = {
        'bytes_transferred': _to_bytes(done_num, done_unit),
        'progress_percent': max(0, min(100, int(percent))),
        'speed_bps': _to_bytes(speed_num, speed_unit),
    }

    if hours is not None:
        stats['eta_seconds'] = int(hours) * 3600 + int(minutes) * 60 + int(seconds)

    return stats


def parse_rsync_total_size(line: str) -> Optional[int]:
    """Extract the exact transfer-set size from the rsync --stats summary"""
    match = _TOTAL_SIZE_RE.search(line)
    if not match:
        return None
    total = _to_bytes(match.group(1), match.group(2))
    return total or None


def _known(stats: Dict) -> Dict:
    """Drop unknown figures so a write never clears a column it has no value for."""
    return {key: value for key, value in stats.items() if value is not None}


def build_progress_stats(transfer: Dict) -> Dict:
    """Pull the structured progress columns off a transfer row for API/socket use"""
    return {
        'progress_percent': transfer.get('progress_percent'),
        'bytes_transferred': transfer.get('bytes_transferred'),
        'total_bytes': transfer.get('total_bytes'),
        'speed_bps': transfer.get('speed_bps'),
        'eta_seconds': transfer.get('eta_seconds'),
    }


class TransferService:
    """Service for rsync process management and monitoring"""

    def __init__(self, config, db_manager, transfer_model, socketio=None, queue_manager=None):
        self.config = config
        self.db = db_manager
        self.transfer_model = transfer_model
        self.socketio = socketio
        self.queue_manager = queue_manager
        self.transfers = {}  # Active transfer processes: {transfer_id: process}

        # Transfers stopped on purpose: {transfer_id: 'cancelled' | 'paused'}.
        # rsync exits non-zero when we terminate it, so without this the monitor
        # thread would overwrite the real outcome with 'failed'.
        self._intentional_stops = {}
        self._stops_lock = threading.Lock()

        # Locked-in total size per transfer, so the derived total does not
        # jitter as the reported percentage ticks up.
        self._total_estimates = {}

    def _mark_intentional_stop(self, transfer_id: str, outcome: str):
        with self._stops_lock:
            self._intentional_stops[transfer_id] = outcome

    def _take_intentional_stop(self, transfer_id: str) -> Optional[str]:
        with self._stops_lock:
            return self._intentional_stops.pop(transfer_id, None)

    def _clear_intentional_stop(self, transfer_id: str):
        with self._stops_lock:
            self._intentional_stops.pop(transfer_id, None)

    def _emit_logs(self, transfer_id: str, tail: List[str], log_count: int, status: str):
        """
        Send a transfer's log tail to the clients watching that transfer.

        Skipped entirely when nobody is subscribed, which is the usual case -
        an operator has at most one row open. That check is the point of the
        exercise: an unwatched transfer costs a ~300 byte broadcast per tick
        instead of ~4.4 KB to every connected client.
        """
        if not self.socketio:
            return
        try:
            from websocket import has_log_subscribers, transfer_log_room
        except ImportError:
            return

        if not has_log_subscribers(transfer_id):
            return

        self.socketio.emit('transfer_logs', {
            'transfer_id': transfer_id,
            'logs': tail,
            'log_count': log_count,
            'status': status,
        }, to=transfer_log_room(transfer_id))

    def _progress_updates(self, transfer_id: str, line: str) -> Optional[Dict]:
        """
        Build the column updates for one rsync output line, or None if the line
        carries no progress information.
        """
        total = parse_rsync_total_size(line)
        if total:
            # The --stats summary is authoritative; replace the estimate.
            self._total_estimates[transfer_id] = total
            return {'total_bytes': total}

        stats = parse_rsync_progress(line)
        if not stats:
            return None

        estimated_total = self._estimate_total_bytes(transfer_id, stats)
        if estimated_total:
            stats['total_bytes'] = estimated_total

        return stats

    def _estimate_total_bytes(self, transfer_id: str, stats: Dict) -> Optional[int]:
        """
        Derive the transfer-set size from bytes-done and percent-done.

        Below 5% the derived value swings wildly (1% of granularity is a huge
        relative error), so hold off until the percentage is meaningful, then
        keep the first estimate stable for the rest of the run.
        """
        cached = self._total_estimates.get(transfer_id)
        if cached:
            return cached

        percent = stats.get('progress_percent') or 0
        done = stats.get('bytes_transferred') or 0

        if percent >= 5 and done > 0:
            total = int(done * 100 / percent)
            self._total_estimates[transfer_id] = total
            return total

        return None

    def _build_ssh_host_key_options(self) -> List[str]:
        """
        SECURITY (SEC-07): Build rsync's `ssh -o ...` host-key options from the
        configured policy, mirroring the paramiko path in ssh.py so both agree.

        - strict     -> StrictHostKeyChecking=yes + managed UserKnownHostsFile
        - accept-new -> StrictHostKeyChecking=accept-new + managed UserKnownHostsFile
                        (trust-on-first-use; a changed key is rejected)
        - no         -> StrictHostKeyChecking=no (legacy insecure)
        """
        # Imported here to avoid any import-order coupling at module load.
        from ssh import (
            normalize_host_key_policy,
            resolve_known_hosts_file,
            _ensure_known_hosts_file,
        )

        policy = normalize_host_key_policy(self.config.get("SSH_HOST_KEY_CHECKING"))
        if policy == "no":
            print("⚠️  SSH host-key verification DISABLED for rsync (SSH_HOST_KEY_CHECKING=no) "
                  "- vulnerable to MITM")
            return ["-o", "StrictHostKeyChecking=no"]

        known_hosts = resolve_known_hosts_file(self.config.get("SSH_KNOWN_HOSTS_FILE"))
        # Ensure the managed known_hosts file (and its parent) exist so rsync's
        # ssh can read it (strict) and persist first-seen keys (accept-new). This
        # is the SAME file the paramiko browse path loads, keeping both consistent.
        if not _ensure_known_hosts_file(known_hosts):
            print(f"⚠️  Could not prepare known_hosts file {known_hosts}; "
                  "rsync host-key verification may be unreliable")
        strict_val = "yes" if policy == "strict" else "accept-new"
        # NOTE: the path is embedded in rsync's single -e string (space-split by
        # rsync), so it must not contain spaces. The default app-dir path is safe.
        return ["-o", f"StrictHostKeyChecking={strict_val}",
                "-o", f"UserKnownHostsFile={known_hosts}"]


    def perform_dry_run_rsync(self, source_path: str, dest_path: str) -> Dict:
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
            # SECURITY (SEC-07): host-key verification per configured policy
            ssh_options = self._build_ssh_host_key_options() + ["-o", "Compression=no"]
            if ssh_key_path and os.path.exists(ssh_key_path):
                ssh_options.extend(["-i", ssh_key_path])
            
            # Build dry-run rsync command
            # Note: Using -avv (double verbose) to get ALL files in itemize-changes output,
            # including unchanged files (.f notation), not just transferred files (>f notation)
            rsync_cmd = [
                "rsync", "-avv",
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
            # IMPORTANT: Always use trailing slash for source to sync folder contents, not the folder itself
            # This ensures consistent behavior and proper file comparison in itemize-changes output
            rsync_cmd.extend([f"{ssh_user}@{ssh_host}:{source_path}/", f"{dest_path}/"])
            
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
        server_media_files = []  # Track all media files on server
        
        # Media file extensions to count
        media_extensions = ('.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.flv', '.webm', '.ts')
        
        # Parse itemize-changes output to count server media files accurately
        for line in stdout.split('\n'):
            line = line.strip()
            
            # *deleting indicates a file will be deleted (exists locally but not on server)
            if line.startswith('*deleting'):
                file_path = line.replace('*deleting', '').strip()
                # Only count media files
                if any(file_path.lower().endswith(ext) for ext in media_extensions):
                    deleted_files.append(file_path)
            
            # Parse itemize-changes format: XYZcstpoguax path
            # X = file type: '.' = unchanged, '>' = transferred, 'c' = created, '*' = message
            # First character tells us about the file:
            # - '>f' = file being transferred (new or changed)
            # - '.f' = file exists and is unchanged
            # - 'cf' = file being created
            elif len(line) > 11 and line[0] in ('>', '.', 'c') and line[1] == 'f':
                # Extract filename (after the 11-character itemize prefix)
                file_path = line[11:].strip()
                
                # Check if it's a media file
                if any(file_path.lower().endswith(ext) for ext in media_extensions):
                    # Add to server media files (these exist on server)
                    if file_path not in server_media_files:
                        server_media_files.append(file_path)
                    
                    # If it's being transferred (new or changed), add to incoming
                    if line[0] == '>':
                        incoming_files.append(file_path)
        
        # Server media file count is based on itemize-changes parsing (accurate)
        server_file_count = len(server_media_files)
        
        # Count actual local media files from filesystem
        local_file_count = 0
        if dest_path:
            local_file_count = self._count_local_media_files(dest_path)
            print(f"📊 Local media file count in {dest_path}: {local_file_count}")
        
        print(f"📊 Server media file count from itemize-changes: {server_file_count}")
        print(f"   - Files to transfer/update: {len(incoming_files)}")
        print(f"   - Files to delete: {len(deleted_files)}")
        
        return {
            'deleted_count': len(deleted_files),
            'incoming_count': len(incoming_files),
            'server_file_count': server_file_count,
            'local_file_count': local_file_count,
            'deleted_files': deleted_files,  # Store full list of files to be deleted
            'incoming_files': incoming_files,  # Store full list of files to be transferred
            'raw_output': stdout  # Store full output for complete log display
        }
    
    def start_rsync_process(self, transfer_id: str, source_path: str, dest_path: str, operation_type: str, backup_dir: str) -> bool:
        """Start the rsync process"""
        try:
            print(f"🔄 Starting transfer {transfer_id}")
            print(f"📁 Source: {source_path}")
            print(f"📁 Destination: {dest_path}")
            print(f"📁 Type: {operation_type}")

            # A resumed or restarted run re-derives its own totals, and must not
            # inherit a stop intent recorded for the previous run.
            self._clear_intentional_stop(transfer_id)
            self._total_estimates.pop(transfer_id, None)

            # Create destination directory
            try:
                # Check TEST_MODE before creating destination directory
                if test_mode_enabled():
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
            
            # A simulation copies fixture files that live on this machine, so it
            # runs rsync locally instead of over SSH. Everything downstream -
            # the monitor, progress parsing, queueing, pause and resume - is the
            # same code the real transfers use, which is the point of it.
            transfer_row = self.transfer_model.get(transfer_id) or {}
            is_simulation = bool(transfer_row.get('is_simulation'))

            # Get SSH connection details
            ssh_user = self.config.get("REMOTE_USER")
            ssh_host = self.config.get("REMOTE_IP")
            ssh_password = self.config.get("REMOTE_PASSWORD", "")
            ssh_key_path = self.config.get("SSH_KEY_PATH", "")

            if is_simulation:
                print(f"🎭 Simulation transfer - running rsync locally, no SSH")
            print(f"🔑 SSH User: {ssh_user}")
            print(f"🔑 SSH Host: {ssh_host}")
            print(f"🔑 SSH Key Path: {ssh_key_path}")
            
            if not is_simulation and (not ssh_user or not ssh_host):
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
                if test_mode_enabled():
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
                # progress2 reports percent/bytes/speed/ETA for the WHOLE
                # transfer instead of the current file, which is what the UI
                # shows. Keep --progress before it so -v still names each file.
                "--info=progress2",
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
            
            # Add --dry-run flag when TEST_MODE is enabled. A simulation is
            # exempt: it copies its own fixture files, so it has to actually
            # move bytes for the progress figures to mean anything.
            if test_mode_enabled() and not is_simulation:
                rsync_cmd.append("--dry-run")
                print("🧪 TEST_MODE enabled - rsync will run in dry-run mode (no actual file transfers)")

            if is_simulation:
                # Hold the copy to a realistic speed so progress, ETA and the
                # queue behave the way they do against a remote server, rather
                # than finishing instantly at local disk speed.
                bwlimit = transfer_row.get('simulation_bwlimit') or SIMULATION_BWLIMIT_KBPS
                rsync_cmd = [arg for arg in rsync_cmd if not arg.startswith("--bwlimit")]
                rsync_cmd.append(f"--bwlimit={int(bwlimit)}")
                rsync_cmd.extend([f"{source_path}/", f"{dest_path}/"])
            else:
                # Build SSH options for rsync
                # SECURITY (SEC-07): host-key verification per configured policy
                ssh_options = self._build_ssh_host_key_options() + ["-o", "Compression=no"]
                if ssh_key_path and os.path.exists(ssh_key_path):
                    ssh_options.extend(["-i", ssh_key_path])

                rsync_cmd.extend(["-e", f"ssh {' '.join(ssh_options)}"])

                # IMPORTANT: Always use trailing slash for folder syncs to sync contents, not the folder itself
                # For 'file' type, no trailing slash; for 'folder' type, trailing slash on both source and dest
                if operation_type == "file":
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
            
            # Update transfer with process ID and running status.
            # Stats are zeroed so a resumed run does not display the previous
            # run's speed/ETA until rsync emits its first progress line.
            self.transfer_model.update(transfer_id, {
                'status': 'running',
                'rsync_process_id': process.pid,
                'progress': 'Transfer started...',
                'progress_percent': 0,
                'bytes_transferred': 0,
                'total_bytes': None,
                'speed_bps': 0,
                'eta_seconds': None,
                'paused_at': None
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

            # The log tail is tracked here rather than re-read per line. Building
            # the socket payload used to cost a second full-row read for every
            # line rsync printed.
            existing = self.transfer_model.get(transfer_id) or {}
            tail = list(existing.get('logs') or [])
            log_count = len(tail)
            del tail[:-SOCKET_LOG_TAIL]

            # Whether the last line actually WRITTEN is a progress line. This
            # has to track the database, not the in-memory tail: when the write
            # interval skips a tick the two diverge, and replacing based on the
            # tail would overwrite a real log line with a progress line.
            db_last_was_progress = bool(tail) and parse_rsync_progress(tail[-1]) is not None
            last_line_was_progress = db_last_was_progress
            last_progress_write = 0.0

            # Latest parsed figures, so a throttled tick still reports live
            # numbers to the UI without reading them back from the database.
            latest_stats = build_progress_stats(existing)

            # A progress line the interval skipped, held so it can be flushed
            # when rsync stops talking.
            pending_progress = None

            # Read output line by line
            for line in iter(process.stdout.readline, ''):
                if not line:
                    continue

                line = line.strip()
                if not line:
                    continue

                stats = self._progress_updates(transfer_id, line)
                if stats:
                    latest_stats.update(stats)
                is_progress = parse_rsync_progress(line) is not None

                # A progress line supersedes the previous one instead of adding
                # to the log; anything else is a real event and is kept.
                if is_progress and last_line_was_progress and tail:
                    tail[-1] = line
                else:
                    tail.append(line)
                    log_count += 1
                del tail[:-SOCKET_LOG_TAIL]

                # Progress lines arrive several times a second and each one only
                # moves the same numbers along, so they are persisted at an
                # interval. Everything else is written as it happens, and
                # carries the newest figures so the columns never lag behind a
                # tick that the interval skipped.
                now = time.monotonic()
                if not is_progress or (now - last_progress_write) >= PROGRESS_WRITE_INTERVAL:
                    self.transfer_model.add_log(
                        transfer_id, line, _known(latest_stats),
                        replace_last=is_progress and db_last_was_progress
                    )
                    db_last_was_progress = is_progress
                    pending_progress = None
                    if is_progress:
                        last_progress_write = now
                else:
                    # Remember it so the last thing rsync reported is not lost
                    # to the interval when the output ends.
                    pending_progress = line

                last_line_was_progress = is_progress

                # The UI still sees every tick - the throttle is only about what
                # reaches the database.
                #
                # The log tail is ~93% of what this event used to weigh and is
                # only of interest to whoever has this transfer's row open, so
                # it travels separately to that transfer's room. Everyone still
                # gets the figures the list needs.
                if socketio:
                    socketio.emit('transfer_progress', {
                        'transfer_id': transfer_id,
                        'progress': line,
                        'log_count': log_count,
                        'status': 'running',
                        'stats': dict(latest_stats)
                    })
                    self._emit_logs(transfer_id, tail, log_count, 'running')
            
            # rsync has stopped writing. Flush the last progress line if the
            # write interval skipped it, otherwise a finished transfer would be
            # left showing whatever percentage happened to land on an interval.
            if pending_progress:
                self.transfer_model.add_log(
                    transfer_id, pending_progress, _known(latest_stats),
                    replace_last=db_last_was_progress
                )

            # Wait for process to complete
            print(f"⏳ Waiting for transfer {transfer_id} to complete...")
            return_code = process.wait()
            print(f"🏁 Transfer {transfer_id} completed with return code: {return_code}")

            # We terminate rsync ourselves for pause and cancel, so a non-zero
            # exit is expected there. cancel_transfer/pause_transfer already
            # wrote the correct row; do not overwrite it with 'failed'.
            intentional_stop = self._take_intentional_stop(transfer_id)

            if intentional_stop == 'paused':
                status = 'paused'
                progress = 'Transfer paused'
                print(f"⏸️  Transfer {transfer_id} stopped for pause")
            elif intentional_stop == 'cancelled':
                status = 'cancelled'
                progress = 'Transfer cancelled by user'
                print(f"🛑 Transfer {transfer_id} stopped by user")
            elif return_code == 0:
                status = 'completed'
                progress = 'Transfer completed successfully!'
                print(f"✅ Transfer {transfer_id} completed successfully")
            else:
                status = 'failed'
                progress = f'Transfer failed with exit code: {return_code}'
                print(f"❌ Transfer {transfer_id} failed with exit code: {return_code}")

            if not intentional_stop:
                # Update final status in database
                self.transfer_model.update(transfer_id, {
                    'status': status,
                    'progress': progress,
                    'end_time': datetime.now().isoformat(),
                    'speed_bps': 0,
                    'eta_seconds': None
                })

            # Get final transfer data
            transfer = self.transfer_model.get(transfer_id)

            # Emit completion status to all clients
            if socketio:
                socketio.emit('transfer_complete', {
                    'transfer_id': transfer_id,
                    'status': status,
                    'message': progress,
                    'log_count': len(transfer['logs']),
                    'stats': build_progress_stats(transfer)
                })
                # One last push to anyone watching, so an open row ends on the
                # real final output rather than waiting for a refetch.
                self._emit_logs(transfer_id, transfer['logs'][-SOCKET_LOG_TAIL:],
                                len(transfer['logs']), status)

            # Remove from active transfers
            if transfer_id in self.transfers:
                del self.transfers[transfer_id]
            self._total_estimates.pop(transfer_id, None)

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
                    'log_count': len(transfer['logs'])
                })
                self._emit_logs(transfer_id, transfer['logs'][-SOCKET_LOG_TAIL:],
                                len(transfer['logs']), 'failed')
            
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
        
        # A paused transfer has no live process, so cancelling is a state change
        if transfer['status'] == 'paused':
            self.transfer_model.update(transfer_id, {
                'status': 'cancelled',
                'progress': 'Transfer cancelled by user (was paused)',
                'paused_at': None,
                'end_time': datetime.now().isoformat()
            })
            print(f"✅ Paused transfer {transfer_id} cancelled")
            return True

        # Handle running transfers
        if transfer['status'] == 'running':
            # A running row without a live rsync process is either a simulated
            # transfer or one whose process already exited. There is nothing to
            # signal, but the row still has to be cancellable - otherwise it is
            # stuck as 'running' forever.
            pid = transfer.get('rsync_process_id')
            has_process = bool(pid) and self._is_process_running(pid)

            if has_process:
                try:
                    import psutil

                    # Record intent BEFORE terminating, so the monitor thread
                    # reads 'cancelled' rather than treating the non-zero exit
                    # as a failure
                    self._mark_intentional_stop(transfer_id, 'cancelled')
                    psutil.Process(pid).terminate()
                except Exception as e:
                    print(f"❌ Error cancelling transfer {transfer_id}: {e}")
                    self._clear_intentional_stop(transfer_id)
                    return False
            else:
                print(f"🛑 Transfer {transfer_id} has no live rsync process to signal")

            self.transfer_model.update(transfer_id, {
                'status': 'cancelled',
                'progress': 'Transfer cancelled by user',
                'end_time': datetime.now().isoformat(),
                'speed_bps': 0,
                'eta_seconds': None
            })

            # Remove from active transfers
            if transfer_id in self.transfers:
                del self.transfers[transfer_id]

            return True

        return False

    def pause_transfer(self, transfer_id: str) -> Tuple[bool, str]:
        """
        Pause a running transfer.

        rsync cannot be suspended safely (the command sets --timeout=300, so a
        frozen process loses its connection after five minutes). Instead we stop
        rsync and rely on --partial/--partial-dir, which are already part of the
        transfer command: the partially written files stay on disk and the
        resumed run picks up from them.
        """
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return False, 'Transfer not found'

        if transfer['status'] != 'running':
            return False, f"Only running transfers can be paused (currently {transfer['status']})"

        # A running row without a live rsync process is either a simulated
        # transfer or one whose process already exited; there is nothing to
        # signal, so pausing is purely a state change.
        pid = transfer.get('rsync_process_id')
        has_process = bool(pid) and self._is_process_running(pid)

        # Mark intent first so the monitor thread does not race us to 'failed'
        self._mark_intentional_stop(transfer_id, 'paused')
        self.transfer_model.update(transfer_id, {
            'status': 'paused',
            'progress': 'Transfer paused - partial files kept, resume to continue',
            'paused_at': datetime.now().isoformat(),
            'speed_bps': 0,
            'eta_seconds': None
        })

        if has_process:
            try:
                import psutil
                psutil.Process(pid).terminate()
            except Exception as e:
                # Signalling failed, so the process is still running - put the
                # row back rather than stranding it in a state it is not in
                print(f"❌ Error pausing transfer {transfer_id}: {e}")
                self._clear_intentional_stop(transfer_id)
                self.transfer_model.update(transfer_id, {
                    'status': 'running',
                    'progress': f'Pause failed: {e}',
                    'paused_at': None
                })
                return False, f'Failed to pause transfer: {e}'
        else:
            print(f"⏸️  Transfer {transfer_id} has no live rsync process to signal")
            self._clear_intentional_stop(transfer_id)

        if transfer_id in self.transfers:
            del self.transfers[transfer_id]

        print(f"⏸️  Transfer {transfer_id} paused")
        return True, 'Transfer paused'

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
                'rsync_process_id': None,
                'start_time': datetime.now().isoformat(),
                'end_time': None
            })
            
            # Start the transfer again
            return self.start_rsync_process(
                transfer_id, 
                transfer['source_path'], 
                transfer['dest_path'], 
                transfer['operation_type'],
                backup_dir
            )
        
        return False

    def resume_active_transfers(self):
        """Resume transfers that were running when app was stopped"""
        active_transfers = self.transfer_model.get_all(statuses=['running'], include_logs=False)
        resumed_count = 0
        active_running_transfer_ids = []
        
        for transfer in active_transfers:
            if transfer['status'] == 'running':
                active_running_transfer_ids.append(transfer['transfer_id'])

                # Check if process is still running
                if transfer['rsync_process_id'] and self._is_process_running(transfer['rsync_process_id']):
                    print(f"📋 Resuming monitoring for transfer {transfer['transfer_id']} (PID: {transfer['rsync_process_id']})")
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

        return active_running_transfer_ids
    
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
            process = psutil.Process(transfer['rsync_process_id'])
            
            # Monitor the process until completion
            return_code = process.wait()

            if return_code is None:
                self.transfer_model.update(transfer_id, {
                    'status': 'completed',
                    'progress': 'Transfer finished after restart (exit status unavailable)',
                    'end_time': datetime.now().isoformat()
                })
                return

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
        except psutil.NoSuchProcess:
            self.transfer_model.update(transfer_id, {
                'status': 'completed',
                'progress': 'Transfer process ended before restart monitoring attached',
                'end_time': datetime.now().isoformat()
            })
        except Exception as e:
            print(f"❌ Error resuming monitoring for {transfer_id}: {e}")
            refreshed_transfer = self.transfer_model.get(transfer_id)
            if refreshed_transfer and refreshed_transfer['status'] == 'running':
                self.transfer_model.update(transfer_id, {
                    'status': 'failed',
                    'progress': f'Monitoring failed: {e}',
                    'end_time': datetime.now().isoformat()
                })
