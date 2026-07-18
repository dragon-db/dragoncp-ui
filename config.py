#!/usr/bin/env python3
"""
DragonCP Configuration Manager
Manages environment configuration and session overrides
"""

import os
from datetime import datetime
from typing import Dict, List
from flask import session, has_request_context


# Application version for cache busting
APP_VERSION = "2.1.4"


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

    def save_config(self, config_data: Dict[str, str]):
        """Save configuration to .env file (legacy method - use update_session_config instead)"""
        try:
            # Check TEST_MODE before writing configuration file
            if os.environ.get('TEST_MODE', '0') == '1':
                print(f"🧪 TEST_MODE: Would write configuration to: {self.env_file}")
                print(f"🧪 TEST_MODE: Configuration would contain {len(config_data)} settings")
            else:
                with open(self.env_file, 'w') as f:
                    f.write("# DragonCP Configuration\n")
                    f.write(f"# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    for key, value in config_data.items():
                        f.write(f'{key}="{value}"\n')
            self.env_config = config_data
            print(f"✅ Configuration saved to .env file: {self.env_file}")
        except Exception as e:
            print(f"❌ Error saving configuration to .env file: {e}")
