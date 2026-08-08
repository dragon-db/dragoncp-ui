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

    def _ensure_column(self, conn, table_name: str, column_name: str, column_sql: str):
        """Add a missing column to an existing table."""
        existing_columns = {
            row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }

        if column_name in existing_columns:
            return

        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
        print(f"🧩 Added missing column {table_name}.{column_name}")

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
                    queue_reason TEXT,
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
            # Table: backup_capture (one displaced copy, at one moment)
            # ==========================================
            # The tree under BACKUP_PATH is the source of truth for these three
            # tables. They are an index over it and can be dropped and rebuilt
            # by walking the disk — see services/backups/indexer.py.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS backup_capture (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_id TEXT UNIQUE NOT NULL,
                    library TEXT,
                    title TEXT,
                    season_number INTEGER,
                    episode_number INTEGER,
                    release_year TEXT,
                    slot_key TEXT,
                    capture_path TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    source_transfer_id TEXT,
                    source_ref TEXT,
                    reason TEXT,
                    kind TEXT NOT NULL DEFAULT 'slot',
                    file_count INTEGER DEFAULT 0,
                    total_size INTEGER DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    -- Whether the FILES are still there, and nothing else. A
                    -- capture that has been restored still has its files and
                    -- stays 'present', so it can be restored again and stays
                    -- subject to retention; when it was restored is recorded
                    -- separately in restored_at.
                    status TEXT NOT NULL DEFAULT 'present',
                    restored_at TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # ==========================================
            # Table: backup_capture_file (files inside a capture)
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS backup_capture_file (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    file_size INTEGER DEFAULT 0,
                    modified_time INTEGER DEFAULT 0,
                    is_media INTEGER NOT NULL DEFAULT 0
                )
            ''')

            # ==========================================
            # Table: backup_capture_key (which slots a capture belongs to)
            # ==========================================
            # Normally one row per capture. A double episode (S01E01E02) has
            # two, so the one stored copy is reachable from both episodes
            # instead of being duplicated or findable from only the first.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS backup_capture_key (
                    capture_id TEXT NOT NULL,
                    slot_key TEXT NOT NULL,
                    PRIMARY KEY (capture_id, slot_key)
                )
            ''')

            # ==========================================
            # Indexes
            # ==========================================
            # Backup capture indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_capture_slot ON backup_capture(slot_key)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_capture_library_title ON backup_capture(library, title)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_capture_captured_at ON backup_capture(captured_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_capture_kind ON backup_capture(kind)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_capture_transfer ON backup_capture(source_transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_capture_file_capture ON backup_capture_file(capture_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_capture_key_slot ON backup_capture_key(slot_key)')

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

            # Backward-compatible schema additions
            self._ensure_column(conn, 'transfers', 'queue_reason', "TEXT")

            # Structured rsync progress, parsed from the --info=progress2 output
            # so the UI can show speed/ETA/size without re-parsing log text.
            self._ensure_column(conn, 'transfers', 'progress_percent', "INTEGER")
            self._ensure_column(conn, 'transfers', 'bytes_transferred', "INTEGER")
            self._ensure_column(conn, 'transfers', 'total_bytes', "INTEGER")
            self._ensure_column(conn, 'transfers', 'speed_bps', "INTEGER")
            self._ensure_column(conn, 'transfers', 'eta_seconds', "INTEGER")

            # Pause/resume support
            self._ensure_column(conn, 'transfers', 'paused_at', "DATETIME")

            # Rehearsals: rows created by the simulation tool. They run through
            # the real pipeline so they must live in the real tables, but they
            # are flagged so they can be shown as rehearsals and removed
            # afterwards without touching genuine history.
            self._ensure_column(conn, 'transfers', 'is_simulation', "INTEGER DEFAULT 0")
            # Speed ceiling in KB/s for a rehearsal, so a scenario can run slow
            # enough to exercise pause and resume, or fast enough to fill the
            # queue quickly. Survives a restart, unlike in-memory run state.
            self._ensure_column(conn, 'transfers', 'simulation_bwlimit', "INTEGER")
            self._ensure_column(conn, 'radarr_webhook', 'is_simulation', "INTEGER DEFAULT 0")
            self._ensure_column(conn, 'sonarr_webhook', 'is_simulation', "INTEGER DEFAULT 0")

            # Explore runs carry an explicit file list instead of mirroring a
            # whole directory, so rsync is given --files-from and never
            # --delete. Stored on the row so a queued, promoted, resumed or
            # restarted run rebuilds the same command.
            self._ensure_column(conn, 'transfers', 'explore_files_from', "TEXT")
            self._ensure_column(conn, 'transfers', 'explore_mode', "TEXT")
            self._ensure_column(conn, 'transfers', 'explore_plan_id', "TEXT")

            # When a backup was last restored. Split out from `status`, which
            # briefly carried 'restored' as well as presence and so made a
            # successful restore its own last: the planner refused to restore
            # anything not marked 'present', and retention skipped it forever,
            # filling the disk with copies it would never prune. `status` now
            # answers only "are the files there".
            self._ensure_column(conn, 'backup_capture', 'restored_at', "TEXT")
            conn.execute(
                "UPDATE backup_capture SET status = 'present' WHERE status = 'restored'"
            )

            # ==========================================
            # Table: explore_snapshot — a cached comparison of one scope
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS explore_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    remote_ok INTEGER DEFAULT 1,
                    local_ok INTEGER DEFAULT 1,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(media_type, scope)
                )
            ''')

            # ==========================================
            # Table: explore_plan — an evaluated operation awaiting approval
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS explore_plan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    series TEXT NOT NULL,
                    season_label TEXT,
                    payload TEXT NOT NULL,
                    safe INTEGER DEFAULT 0,
                    consumed INTEGER DEFAULT 0,
                    created_by TEXT,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # ==========================================
            # Table: transfer_file — what a run actually did, file by file
            # ==========================================
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transfer_file (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transfer_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    size INTEGER DEFAULT 0,
                    code TEXT,
                    season_label TEXT,
                    backup_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # ==========================================
            # Table: admin_account — who is allowed to sign in
            # ==========================================
            # Accounts are created and maintained from the server with
            # scripts/manage_admins.py; there is no account-management UI. Rows
            # are never deleted, because the activity trail refers back to them:
            # a departed admin is disabled and keeps their history.
            #
            # `id` is the stable identity. Usernames can be renamed, so anything
            # recording who did something stores this id alongside the name it
            # displayed at the time.
            #
            # `token_version` is what makes a disable or a password change take
            # effect immediately. Sign-in tokens carry the value they were minted
            # with, every request compares it against the row, and bumping it
            # here retires every token already issued for that account.
            #
            # `role` is reserved. Everyone is 'admin' today and nothing reads it;
            # it exists so a narrower role can arrive later without migrating
            # every account.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS admin_account (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    token_version INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    last_login_at DATETIME,
                    password_changed_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # ==========================================
            # Table: activity — who did what, and when
            # ==========================================
            # The record of every consequential action, whoever took it. Reads
            # are not recorded: browsing the library is not something anyone
            # needs held to account, and recording it would bury the actions
            # that matter.
            #
            # The actor is stored three ways on purpose. `actor_account_id` is
            # the stable identity that survives a rename; `actor_name` is the
            # name as it read at the time, so old entries keep saying what they
            # said; `actor_kind` separates a person from automation without
            # having to recognise names.
            #
            # `summary` is a finished sentence written at the call site, because
            # the code doing the work is the only place that knows what it did.
            # Rendering one later from ids would mean re-deriving facts that may
            # no longer exist — a restored capture that has since been pruned
            # still needs to read correctly.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    actor_kind TEXT NOT NULL,
                    actor_name TEXT NOT NULL,
                    actor_account_id INTEGER,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    target_label TEXT,
                    summary TEXT NOT NULL,
                    detail TEXT,
                    outcome TEXT NOT NULL DEFAULT 'ok',
                    request_ip TEXT
                )
            ''')

            # Who started a run. Stamped on the row as well as recorded in the
            # activity trail, because "who started this" is asked while looking
            # at the transfer itself, and a join per row to answer it would be
            # the wrong shape for a list that pages.
            self._ensure_column(conn, 'transfers', 'started_by_kind', "TEXT")
            self._ensure_column(conn, 'transfers', 'started_by_name', "TEXT")
            self._ensure_column(conn, 'transfers', 'started_by_account_id', "INTEGER")

            # Who put a version back. Restore is the most consequential thing
            # the backups screen can do — it replaces what is in the library —
            # so the answer belongs next to the capture, not only in the trail.
            self._ensure_column(conn, 'backup_capture', 'restored_by_kind', "TEXT")
            self._ensure_column(conn, 'backup_capture', 'restored_by_name', "TEXT")
            self._ensure_column(conn, 'backup_capture', 'restored_by_account_id', "INTEGER")

            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_occurred ON activity(occurred_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_actor ON activity(actor_account_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_action ON activity(action)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_target ON activity(target_type, target_id)')

            conn.execute('CREATE INDEX IF NOT EXISTS idx_transfer_file_transfer ON transfer_file(transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_explore_plan_expiry ON explore_plan(expires_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_admin_account_active ON admin_account(is_active)')

            conn.commit()
        
        print(f"✅ Database initialized: {self.db_path}")
    
    def get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
