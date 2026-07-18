#!/usr/bin/env python3
"""
DragonCP SSH Manager
Handles SSH connections and remote operations

=== SECURITY BOUNDARY - REMOTE COMMAND INJECTION ===

Remote commands are built as shell strings and run via exec_command(). Any
path segment interpolated into a command MUST be shell-quoted with
shlex.quote() so that quotes, backticks, `$`, `;`, and other metacharacters in
folder/season/episode names (which are legitimate in media filenames, or may
come from an untrusted remote listing) cannot break out of the intended
argument and execute a second command on the SSH target.

Do NOT interpolate a raw path into a command string. Always pass it through
self._quote_remote_path(). See also security.py (path-component validation)
and webhook_auth.py (webhook authentication).
"""

import os
import shlex
import logging
import paramiko
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# ===== SSH HOST-KEY VERIFICATION (SEC-07) =====
#
# Host-key checking is configurable via SSH_HOST_KEY_CHECKING:
#   - "strict"      -> reject unknown hosts (paramiko RejectPolicy / ssh yes).
#                      Most secure; requires the host key to be pre-provisioned
#                      in the known_hosts file.
#   - "accept-new"  -> trust-on-first-use (DEFAULT). Unknown hosts are added and
#                      persisted; a later key CHANGE is rejected as a possible
#                      MITM. Secure default that stays usable on first connect.
#   - "no"          -> legacy insecure behaviour: accept any key (vulnerable to
#                      MITM). Only for users who cannot manage known_hosts.
#
# The paramiko (browsing) and rsync (transfer) paths share these helpers so both
# consult/persist the SAME known_hosts file and agree on the policy.

DEFAULT_KNOWN_HOSTS_FILENAME = "dragoncp_known_hosts"
VALID_HOST_KEY_POLICIES = ("strict", "accept-new", "no")


def normalize_host_key_policy(configured: Optional[str]) -> str:
    """Normalise the SSH_HOST_KEY_CHECKING value to a canonical policy string."""
    policy = (configured or "").strip().lower()
    if policy in ("strict", "yes"):
        return "strict"
    if policy in ("accept-new", "acceptnew", "tofu"):
        return "accept-new"
    if policy in ("no", "off", "none", "false", "disable", "disabled"):
        return "no"
    if policy:
        logger.warning(
            "SSH: unrecognised SSH_HOST_KEY_CHECKING=%r; defaulting to 'accept-new'",
            configured,
        )
    return "accept-new"


def resolve_known_hosts_file(configured: Optional[str] = None) -> str:
    """
    Resolve the known_hosts file path used for host-key verification.

    Defaults to <app_dir>/dragoncp_known_hosts so the app owns a managed
    known_hosts file independent of the invoking user's ~/.ssh.
    """
    if configured and configured.strip():
        return os.path.abspath(os.path.expanduser(configured.strip()))
    app_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(app_dir, DEFAULT_KNOWN_HOSTS_FILENAME)


def _ensure_known_hosts_file(path: str) -> bool:
    """Ensure the known_hosts file (and its parent dir) exist so keys persist."""
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(path):
            open(path, 'a').close()
        return True
    except OSError as e:
        logger.warning("SSH: could not create known_hosts file %s: %s", path, e)
        return False


class SSHManager:
    """SSH connection manager"""
    
    def __init__(self, host: str, username: str, password: str = None, key_path: str = None,
                 host_key_policy: str = "accept-new", known_hosts_file: str = None):
        self.host = host
        self.username = username
        self.password = password
        self.key_path = key_path
        # SECURITY (SEC-07): host-key verification policy and managed known_hosts file
        self.host_key_policy = normalize_host_key_policy(host_key_policy)
        self.known_hosts_file = resolve_known_hosts_file(known_hosts_file)
        self.client = None
        self.connected = False

    def _apply_host_key_policy(self):
        """
        SECURITY (SEC-07): Configure host-key verification on self.client.

        Loads the app-managed known_hosts file (so a CHANGED key is detected as a
        possible MITM) and applies the configured missing-host-key policy. In "no"
        mode we skip loading entirely to preserve the legacy accept-anything
        behaviour.
        """
        if self.host_key_policy == "no":
            logger.warning(
                "SSH: host-key verification is DISABLED (SSH_HOST_KEY_CHECKING=no) for %s. "
                "The connection is vulnerable to man-in-the-middle attacks. "
                "Set SSH_HOST_KEY_CHECKING=accept-new (default) or strict.",
                self.host,
            )
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            return

        # Load ONLY the app-managed known_hosts file — deliberately NOT the
        # invoking user's ~/.ssh/known_hosts. The rsync transfer path
        # (transfer_service.py) passes this same file via UserKnownHostsFile, so
        # trusting an extra system source here would let browsing accept a host
        # that rsync then rejects (e.g. under strict mode). Recorded keys are
        # trusted; a changed key raises BadHostKeyException.
        if _ensure_known_hosts_file(self.known_hosts_file):
            try:
                # load_host_keys() also sets the persistence target so that
                # AutoAddPolicy writes newly-accepted keys back to this file.
                self.client.load_host_keys(self.known_hosts_file)
            except (IOError, OSError) as e:
                logger.warning(
                    "SSH: could not load known_hosts %s: %s", self.known_hosts_file, e
                )

        if self.host_key_policy == "strict":
            # Reject any host not already present in known_hosts.
            self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:  # accept-new (trust-on-first-use, persists accepted keys)
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def connect(self) -> bool:
        """Establish SSH connection"""
        try:
            self.client = paramiko.SSHClient()
            # SECURITY (SEC-07): apply configured host-key verification policy
            self._apply_host_key_policy()

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
        except paramiko.BadHostKeyException as e:
            # SECURITY (SEC-07): the server presented a key that does NOT match
            # the one recorded in known_hosts — a strong MITM indicator.
            logger.error(
                "SSH: HOST KEY MISMATCH for %s — the server's key changed and does "
                "not match known_hosts. Possible man-in-the-middle. %s", self.host, e
            )
            print(f"SSH connection failed: host key verification FAILED for {self.host} "
                  f"(possible MITM). Remove the stale entry from '{self.known_hosts_file}' "
                  f"only if you trust the new key.")
            self.connected = False
            return False
        except paramiko.SSHException as e:
            # RejectPolicy raises SSHException ("Server ... not found in known_hosts")
            # under strict mode for an unknown host.
            if self.host_key_policy == "strict" and "known_hosts" in str(e).lower():
                logger.error(
                    "SSH: host %s is not in known_hosts and SSH_HOST_KEY_CHECKING=strict. "
                    "Add its key to '%s' (e.g. ssh-keyscan) or use accept-new. %s",
                    self.host, self.known_hosts_file, e
                )
                print(f"SSH connection failed: host {self.host} not in known_hosts "
                      f"(strict mode). Provision its key in '{self.known_hosts_file}'.")
            else:
                print(f"SSH connection failed: {e}")
            self.connected = False
            return False
        except Exception as e:
            print(f"SSH connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Close SSH connection"""
        if self.client:
            self.client.close()
        self.connected = False
    
    @staticmethod
    def _quote_remote_path(path: str) -> str:
        """
        Shell-quote a remote path for safe interpolation into a command string.

        SECURITY: This is the mandatory boundary that prevents remote command
        injection. shlex.quote() wraps the value so that any shell metacharacter
        (", ', `, $, ;, &, |, newline, space, ...) is treated as literal data
        rather than shell syntax. This preserves legitimate media names that
        contain such characters while making injection impossible.

        Args:
            path: The remote filesystem path to quote

        Returns:
            A safely quoted shell token

        Raises:
            ValueError: If path is not a non-empty string
        """
        if not isinstance(path, str) or not path:
            raise ValueError("Remote path must be a non-empty string")
        return shlex.quote(path)

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
        # SECURITY: quote the path to prevent remote command injection
        command = f'find {self._quote_remote_path(path)} -mindepth 1 -maxdepth 1 -type d -exec basename "{{}}" \\;'
        exit_code, output, error = self.execute_command(command)

        if exit_code == 0 and output:
            folders = [f.strip() for f in output.split('\n') if f.strip()]
            return sorted(folders, key=lambda x: (len(x), x))
        return []
    
    def list_folders_with_metadata(self, path: str) -> List[Dict]:
        """List folders in remote directory with metadata including most recent file modification time"""
        # Get folder names with most recent file modification time within each folder
        # SECURITY: quote the path to prevent remote command injection
        command = f'''find {self._quote_remote_path(path)} -mindepth 1 -maxdepth 1 -type d -exec sh -c '
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
        # SECURITY: quote the path to prevent remote command injection
        command = f'find {self._quote_remote_path(path)} -maxdepth 1 -type f -exec basename "{{}}" \\;'
        exit_code, output, error = self.execute_command(command)
        
        if exit_code == 0 and output:
            files = [f.strip() for f in output.split('\n') if f.strip()]
            return sorted(files, key=lambda x: (len(x), x))
        return []

    def list_files_with_metadata(self, path: str) -> List[Dict]:
        """List files in remote directory with metadata including modification time and size"""
        # SECURITY: quote the path to prevent remote command injection
        command = f'''find {self._quote_remote_path(path)} -maxdepth 1 -type f -exec sh -c '
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
        # SECURITY: quote the path to prevent remote command injection
        command = f'''find {self._quote_remote_path(path)} -type f -exec sh -c '
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

