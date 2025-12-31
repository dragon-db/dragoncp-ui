#!/usr/bin/env python3
"""
DragonCP Database Manager (v2)
Provides SQLite database initialization and connection management

Schema v2 Changes:
- Table renames: radarr_webhook, sonarr_webhook, rename_webhook, backup, backup_file
- Removed: episode_name, parsed_episode from transfers
- Renamed: transfer_type → operation_type, process_id → rsync_process_id
- Renamed: backup_dir → backup_path
- Renamed: synced_at → completed_at, processed_at → completed_at
- Added: updated_at to webhook and backup tables
"""

import sqlite3
import os


class DatabaseManager:
    """Database manager for SQLite operations"""
    
    def __init__(self, db_path: str = "dragoncp.db"):
        # Store database path relative to script directory
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(script_dir, db_path)
        print(f"🗄️  Database path: {self.db_path}")
        self.init_database()
    
    def init_database(self):
        """Initialize database and create tables"""
        with sqlite3.connect(self.db_path) as conn:
            # ==========================================
            # Table: transfers
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transfer_id TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,
                    folder_name TEXT NOT NULL,
                    season_name TEXT,
                    source_path TEXT NOT NULL,
                    dest_path TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress TEXT DEFAULT '',
                    rsync_process_id INTEGER,
                    logs TEXT DEFAULT '[]',
                    parsed_title TEXT,
                    parsed_season TEXT,
                    start_time DATETIME,
                    end_time DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # ==========================================
            # Table: radarr_webhook (movie webhooks from Radarr)
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS radarr_webhook (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    year INTEGER,
                    folder_path TEXT NOT NULL,
                    poster_url TEXT,
                    requested_by TEXT,
                    file_path TEXT NOT NULL,
                    quality TEXT,
                    size INTEGER DEFAULT 0,
                    languages TEXT DEFAULT '[]',
                    subtitles TEXT DEFAULT '[]',
                    release_title TEXT,
                    release_indexer TEXT,
                    release_size INTEGER DEFAULT 0,
                    tmdb_id INTEGER,
                    imdb_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    transfer_id TEXT,
                    raw_webhook_data TEXT
                )
            ''')
            
            # ==========================================
            # Table: sonarr_webhook (series/anime webhooks from Sonarr)
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sonarr_webhook (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,
                    series_title TEXT NOT NULL,
                    series_title_slug TEXT,
                    series_id INTEGER,
                    series_path TEXT NOT NULL,
                    year INTEGER,
                    tvdb_id INTEGER,
                    tv_maze_id INTEGER,
                    tmdb_id INTEGER,
                    imdb_id TEXT,
                    poster_url TEXT,
                    banner_url TEXT,
                    tags TEXT DEFAULT '[]',
                    original_language TEXT,
                    requested_by TEXT,
                    season_number INTEGER,
                    episode_count INTEGER DEFAULT 1,
                    episodes TEXT DEFAULT '[]',
                    episode_files TEXT DEFAULT '[]',
                    season_path TEXT NOT NULL,
                    release_title TEXT,
                    release_indexer TEXT,
                    release_size INTEGER DEFAULT 0,
                    download_client TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    transfer_id TEXT,
                    requires_manual_sync INTEGER DEFAULT 0,
                    manual_sync_reason TEXT,
                    auto_sync_scheduled_at DATETIME,
                    dry_run_result TEXT,
                    dry_run_performed_at DATETIME,
                    raw_webhook_data TEXT
                )
            ''')

            # ==========================================
            # Table: rename_webhook (file rename webhooks from Sonarr)
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS rename_webhook (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,
                    series_title TEXT NOT NULL,
                    series_id INTEGER,
                    series_path TEXT NOT NULL,
                    renamed_files TEXT DEFAULT '[]',
                    total_files INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    raw_webhook_data TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # ==========================================
            # Table: app_settings (key-value store)
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # ==========================================
            # Table: backup (rsync backup records)
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS backup (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_id TEXT UNIQUE NOT NULL,
                    transfer_id TEXT NOT NULL,
                    media_type TEXT,
                    folder_name TEXT,
                    season_name TEXT,
                    source_path TEXT NOT NULL,
                    dest_path TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    file_count INTEGER DEFAULT 0,
                    total_size INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    restored_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # ==========================================
            # Table: backup_file (individual backup files)
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS backup_file (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    file_size INTEGER,
                    modified_time INTEGER,
                    context_media_type TEXT,
                    context_title TEXT,
                    context_release_year TEXT,
                    context_series_title TEXT,
                    context_season TEXT,
                    context_episode TEXT,
                    context_absolute TEXT,
                    context_key TEXT,
                    context_display TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # ==========================================
            # Indexes
            # ==========================================
            # Transfer indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_transfer_id ON transfers(transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON transfers(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON transfers(created_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dest_status ON transfers(dest_path, status)')
            
            # Radarr webhook indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_notification_id ON radarr_webhook(notification_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_status ON radarr_webhook(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_created_at ON radarr_webhook(created_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_transfer_id ON radarr_webhook(transfer_id)')
            
            # Sonarr webhook indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sonarr_webhook_notification_id ON sonarr_webhook(notification_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sonarr_webhook_status ON sonarr_webhook(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sonarr_webhook_transfer_id ON sonarr_webhook(transfer_id)')
            
            # Rename webhook indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_webhook_notification_id ON rename_webhook(notification_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_webhook_status ON rename_webhook(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_webhook_created_at ON rename_webhook(created_at)')
            
            # Backup indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_transfer_id ON backup(transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_file_backup_id ON backup_file(backup_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_file_context_key ON backup_file(context_key)')
            
            conn.commit()
        
        print(f"✅ Database initialized: {self.db_path}")
    
    def get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
