#!/usr/bin/env python3
"""
DragonCP Configuration Manager

Reads the environment file. Nothing else.

This used to also hold per-browser session overrides, and that was a lie:
`get()` only consulted them when an HTTP request was in flight, so every
background thread — the transfer monitor, the auto-sync scheduler, the backup
sorter — fell through to the file anyway. Sixteen settings appeared editable in
the UI and were ignored by the machinery that used them.

Settings that an operator should be able to change now live in the database.
`settings_registry.py` says which is which, and `services/settings_service.py`
reads both. This class is the env half and knows nothing about the other.
"""

import os
from pathlib import Path
from typing import Dict, List


#: The release this build is. Read from the `VERSION` file at the repository
#: root, which is the single place the number is written.
#:
#: It used to be a literal here, one of three hand-maintained copies — this one,
#: `frontend/package.json` and a constant in the navbar. Nothing read this one,
#: so it drifted quietly while the screen showed a different number; keeping
#: three copies in step by hand is why the version stopped being updated at all.
#: `tests/test_version.py` fails the build if they disagree again.
_VERSION_FILE = Path(__file__).resolve().parent / 'VERSION'


def _read_version() -> str:
    """
    The version, or a marker saying it could not be read.

    Never raises. A missing or unreadable VERSION file is a packaging mistake,
    not a reason for the application to refuse to start — the number is shown
    in the interface and reported by the runtime endpoint, and neither is worth
    an outage.
    """
    try:
        version = _VERSION_FILE.read_text(encoding='utf-8').strip()
        return version or 'unknown'
    except OSError:
        return 'unknown'


APP_VERSION = _read_version()

REDACTED = '<redacted>'


def _for_logging(key: str, value: str) -> str:
    """
    What may be written to the log for one setting.

    Every value in the environment file used to be printed here on every start,
    which put the operator password, the token-signing key, the Flask secret,
    the storage API token and the address allowed to reach the transfer server
    into the backend log in plain text — a file that is read over the shoulder,
    downloaded from the Settings page, and pasted into bug reports.

    The registry already records which settings are secret, so that judgement is
    made in one place rather than repeated here. Anything the registry does not
    know is redacted too: a setting added later is far more likely to be a
    credential than to be something worth reading in a startup log, and the
    Settings page already shows the ones that are not.
    """
    if not value:
        return value
    try:
        import settings_registry

        setting = settings_registry.get(key)
    except Exception:  # noqa: BLE001 - logging must never break startup
        return REDACTED
    if setting is None or setting.sensitive or setting.hidden:
        return REDACTED
    return value


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
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            config[key] = value
                            print(f"  {key}: {_for_logging(key, value)}")
            except Exception as e:
                print(f"❌ Error loading env file: {e}")
        else:
            print(f"❌ Environment file not found: {self.env_file}")
        return config
    
    def get(self, key: str, default: str = "") -> str:
        """The env file's value for a key, or the default."""
        value = self.env_config.get(key, default)
        if not value:
            print(f"⚠️  Configuration key '{key}' not found, using default: '{default}'")
        return value

    def get_all_config(self) -> Dict[str, str]:
        """Everything the env file holds."""
        return self.env_config.copy()

    
    def get_all_allowed_paths(self) -> List[str]:
        """
        Get all configured directory paths that define filesystem security boundaries.

        SECURITY: These paths are the ONLY directories DragonCP is allowed to
        operate in. All file operations (read, write, rename, delete, rsync,
        backup/restore) MUST validate that constructed paths resolve within
        one of these directories. See security.py for enforcement functions.

        Returns:
            List of configured directory paths (empty strings filtered out)
        """
        path_keys = [
            'MOVIE_PATH', 'TVSHOW_PATH', 'ANIME_PATH',
            'MOVIE_DEST_PATH', 'TVSHOW_DEST_PATH', 'ANIME_DEST_PATH',
            'BACKUP_PATH'
        ]
        return [self.get(k) for k in path_keys if self.get(k)]

    def get_destination_paths(self) -> List[str]:
        """
        Get all configured LOCAL destination paths.

        SECURITY: These are the local filesystem directories where DragonCP
        writes data. Path traversal protection is most critical for these
        paths since the Flask process has direct filesystem access.

        Returns:
            List of configured destination directory paths (empty strings filtered out)
        """
        dest_keys = [
            'MOVIE_DEST_PATH', 'TVSHOW_DEST_PATH', 'ANIME_DEST_PATH'
        ]
        return [self.get(k) for k in dest_keys if self.get(k)]
