#!/usr/bin/env python3
"""
DragonCP Database Manager
Provides SQLite database initialization and connection management
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
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transfer_id TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,
                    folder_name TEXT NOT NULL,
                    season_name TEXT,
                    episode_name TEXT,
                    source_path TEXT NOT NULL,
                    dest_path TEXT NOT NULL,
                    transfer_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress TEXT DEFAULT '',
                    process_id INTEGER,
                    logs TEXT DEFAULT '[]',
                    parsed_title TEXT,
                    parsed_season TEXT,
                    parsed_episode TEXT,
                    start_time DATETIME,
                    end_time DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Webhook notifications for automated movie sync
            conn.execute('''
                CREATE TABLE IF NOT EXISTS webhook_notifications (
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
                    synced_at DATETIME,
                    transfer_id TEXT
                )
            ''')
            
            # Webhook notifications for series/anime sync
            conn.execute('''
                CREATE TABLE IF NOT EXISTS series_webhook_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,  -- 'tvshows' or 'anime'
                    series_title TEXT NOT NULL,
                    series_title_slug TEXT,
                    series_id INTEGER,
                    series_path TEXT NOT NULL,
                    year INTEGER,
                    tvdb_id INTEGER,
                    tv_maze_id INTEGER,
                    tmdb_id INTEGER,
                    imdb_id TEXT,
                    poster_url TEXT,  -- Poster image URL
                    banner_url TEXT,  -- Banner image URL
                    tags TEXT DEFAULT '[]',
                    original_language TEXT,
                    requested_by TEXT,
                    season_number INTEGER,
                    episode_count INTEGER DEFAULT 1,
                    episodes TEXT DEFAULT '[]',  -- JSON array of episode details
                    episode_files TEXT DEFAULT '[]',  -- JSON array of episode file details
                    season_path TEXT NOT NULL,  -- Season-level destination path
                    release_title TEXT,
                    release_indexer TEXT,
                    release_size INTEGER DEFAULT 0,
                    download_client TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    synced_at DATETIME,
                    transfer_id TEXT,
                    -- Auto-sync related fields
                    requires_manual_sync INTEGER DEFAULT 0,  -- 0=false, 1=true
                    manual_sync_reason TEXT,
                    auto_sync_scheduled_at DATETIME,
                    dry_run_result TEXT,  -- JSON with dry-run validation results
                    dry_run_performed_at DATETIME
                )
            ''')

            # Rename notifications for file rename webhooks from Sonarr
            conn.execute('''
                CREATE TABLE IF NOT EXISTS rename_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,  -- 'tvshows' or 'anime'
                    series_title TEXT NOT NULL,
                    series_id INTEGER,
                    series_path TEXT NOT NULL,
                    renamed_files TEXT DEFAULT '[]',  -- JSON array of {previousPath, newPath, localPreviousPath, localNewPath, status, error}
                    total_files INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'completed', 'partial', 'failed'
                    error_message TEXT,
                    raw_webhook_data TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processed_at DATETIME
                )
            ''')

            # Application settings (key-value store for dynamic UI settings)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Backups for rsync --backup deletions
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transfer_backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_id TEXT UNIQUE NOT NULL,
                    transfer_id TEXT NOT NULL,
                    media_type TEXT,
                    folder_name TEXT,
                    season_name TEXT,
                    episode_name TEXT,
                    source_path TEXT NOT NULL,
                    dest_path TEXT NOT NULL,
                    backup_dir TEXT NOT NULL,
                    file_count INTEGER DEFAULT 0,
                    total_size INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    restored_at DATETIME
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transfer_backup_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    file_size INTEGER,
                    modified_time INTEGER,
                    -- Context-aware fields for smarter restore
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
            
            # Create index for better performance
            conn.execute('CREATE INDEX IF NOT EXISTS idx_transfer_id ON transfers(transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON transfers(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON transfers(created_at)')
            # Helpful for duplicate cleanup queries
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dest_status ON transfers(dest_path, status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_id ON transfer_backup_files(backup_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_context_key ON transfer_backup_files(context_key)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backups_transfer_id ON transfer_backups(transfer_id)')
            # Webhook notifications indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_webhook_notification_id ON webhook_notifications(notification_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_webhook_status ON webhook_notifications(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_webhook_created_at ON webhook_notifications(created_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_webhook_transfer_id ON webhook_notifications(transfer_id)')
            # Series webhook notifications indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_series_webhook_notification_id ON series_webhook_notifications(notification_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_series_webhook_status ON series_webhook_notifications(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_series_webhook_transfer_id ON series_webhook_notifications(transfer_id)')
            # Rename notifications indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_notification_id ON rename_notifications(notification_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_status ON rename_notifications(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_created_at ON rename_notifications(created_at)')
            
            conn.commit()
        
        print(f"✅ Database initialized: {self.db_path}")
        # Perform lightweight migrations to add context columns if upgrading from older schema
        # MIGRATION CODE - Can be removed in future versions after all deployments are upgraded
        self._ensure_backup_file_context_columns()
        self._ensure_webhook_notification_columns()
        self._ensure_app_settings_table()
        self._ensure_series_webhook_auto_sync_columns()
        self._ensure_raw_webhook_data_columns()
        self._ensure_rename_notifications_table()

    def _ensure_backup_file_context_columns(self):
        """MIGRATION CODE: Ensure context columns exist on transfer_backup_files for upgrades."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cols = {row[1] for row in conn.execute('PRAGMA table_info(transfer_backup_files)')}
                to_add = []
                def add(col, type_decl):
                    if col not in cols:
                        to_add.append((col, type_decl))
                add('context_media_type', 'TEXT')
                add('context_title', 'TEXT')
                add('context_release_year', 'TEXT')
                add('context_series_title', 'TEXT')
                add('context_season', 'TEXT')
                add('context_episode', 'TEXT')
                add('context_absolute', 'TEXT')
                add('context_key', 'TEXT')
                add('context_display', 'TEXT')
                for col, typ in to_add:
                    try:
                        conn.execute(f'ALTER TABLE transfer_backup_files ADD COLUMN {col} {typ}')
                    except Exception as e:
                        # Ignore if concurrent/multiple attempts
                        pass
                # Ensure index as well
                try:
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_context_key ON transfer_backup_files(context_key)')
                except Exception:
                    pass
                conn.commit()
        except Exception as e:
            print(f"⚠️  Migration check failed: {e}")
    
    def _ensure_webhook_notification_columns(self):
        """MIGRATION CODE: Ensure tmdb_id and imdb_id columns exist on webhook_notifications for upgrades."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cols = {row[1] for row in conn.execute('PRAGMA table_info(webhook_notifications)')}
                to_add = []
                def add(col, type_decl):
                    if col not in cols:
                        to_add.append((col, type_decl))
                add('tmdb_id', 'INTEGER')
                add('imdb_id', 'TEXT')
                for col, typ in to_add:
                    try:
                        conn.execute(f'ALTER TABLE webhook_notifications ADD COLUMN {col} {typ}')
                    except Exception as e:
                        # Ignore if concurrent/multiple attempts or table doesn't exist yet
                        pass
                conn.commit()
        except Exception as e:
            print(f"⚠️  Webhook notification migration check failed: {e}")

    def _ensure_app_settings_table(self):
        """MIGRATION CODE: Ensure app_settings table exists (for upgrades)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
        except Exception as e:
            print(f"⚠️  App settings table check failed: {e}")
    
    def _ensure_series_webhook_auto_sync_columns(self):
        """MIGRATION CODE: Ensure auto-sync columns exist on series_webhook_notifications."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cols = {row[1] for row in conn.execute('PRAGMA table_info(series_webhook_notifications)')}
                to_add = []
                def add(col, type_decl):
                    if col not in cols:
                        to_add.append((col, type_decl))
                add('requires_manual_sync', 'INTEGER DEFAULT 0')
                add('manual_sync_reason', 'TEXT')
                add('auto_sync_scheduled_at', 'DATETIME')
                add('dry_run_result', 'TEXT')
                add('dry_run_performed_at', 'DATETIME')
                add('raw_webhook_data', 'TEXT')
                for col, typ in to_add:
                    try:
                        conn.execute(f'ALTER TABLE series_webhook_notifications ADD COLUMN {col} {typ}')
                    except Exception as e:
                        # Ignore if concurrent/multiple attempts
                        pass
                conn.commit()
        except Exception as e:
            print(f"⚠️  Series webhook auto-sync columns migration check failed: {e}")
    
    def _ensure_raw_webhook_data_columns(self):
        """MIGRATION CODE: Ensure raw_webhook_data columns exist for storing full webhook JSON."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                # Check webhook_notifications table
                cols = {row[1] for row in conn.execute('PRAGMA table_info(webhook_notifications)')}
                if 'raw_webhook_data' not in cols:
                    try:
                        conn.execute('ALTER TABLE webhook_notifications ADD COLUMN raw_webhook_data TEXT')
                    except Exception:
                        pass
                
                # Check series_webhook_notifications table
                cols = {row[1] for row in conn.execute('PRAGMA table_info(series_webhook_notifications)')}
                if 'raw_webhook_data' not in cols:
                    try:
                        conn.execute('ALTER TABLE series_webhook_notifications ADD COLUMN raw_webhook_data TEXT')
                    except Exception:
                        pass
                
                conn.commit()
        except Exception as e:
            print(f"⚠️  Raw webhook data columns migration check failed: {e}")
    
    def _ensure_rename_notifications_table(self):
        """MIGRATION CODE: Ensure rename_notifications table exists (for upgrades)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS rename_notifications (
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
                        processed_at DATETIME
                    )
                ''')
                # Ensure indexes
                conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_notification_id ON rename_notifications(notification_id)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_status ON rename_notifications(status)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_rename_created_at ON rename_notifications(created_at)')
                conn.commit()
        except Exception as e:
            print(f"⚠️  Rename notifications table migration check failed: {e}")
    
    def get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

