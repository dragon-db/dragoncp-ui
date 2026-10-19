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

import json
import os
import sqlite3
import uuid


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

    def _migrate_discord_to_connector(self, conn):
        """Move the single Discord webhook onto the connector layer.

        Discord used to be five `DISCORD_*` rows in `app_settings`: one URL,
        one on/off switch and three presentation URLs. It is now a connector
        with named destinations and per-event routing.

        The upgrade has to be invisible. The stored URL becomes a destination
        called "Default", and **no routing rows are written** — a missing route
        means "use the default", so every notification carries on going exactly
        where it went before.

        Guarded on the connector row already existing rather than on a version
        number, so it is safe to run on every start and safe to run twice.
        """
        already = conn.execute(
            "SELECT 1 FROM connector WHERE connector_id = 'discord'"
        ).fetchone()
        if already:
            return

        rows = conn.execute(
            "SELECT key, value FROM app_settings WHERE key LIKE 'DISCORD_%'"
        ).fetchall()
        if not rows:
            return

        values = {row[0]: (row[1] or '') for row in rows}
        webhook_url = values.get('DISCORD_WEBHOOK_URL', '').strip()
        enabled = values.get('DISCORD_NOTIFICATIONS_ENABLED', '').strip().lower() \
            in ('1', 'true', 'yes', 'on')
        config = {
            'app_url': values.get('DISCORD_APP_URL', '').strip(),
            'icon_url': values.get('DISCORD_ICON_URL', '').strip(),
            'manual_sync_thumbnail_url':
                values.get('DISCORD_MANUAL_SYNC_THUMBNAIL_URL', '').strip(),
        }
        config = {k: v for k, v in config.items() if v}

        if not webhook_url and not config and not enabled:
            # Rows existed but held nothing. Leave no connector row behind, so
            # the Integrations page shows Discord as never configured rather
            # than as configured-and-empty.
            conn.execute("DELETE FROM app_settings WHERE key LIKE 'DISCORD_%'")
            return

        conn.execute('''
            INSERT INTO connector (connector_id, display_name, enabled, config)
            VALUES ('discord', 'Discord', ?, ?)
        ''', (1 if enabled else 0, json.dumps(config)))

        if webhook_url:
            target_id = f"tgt_{uuid.uuid4().hex[:12]}"
            secret_ref = f"target:{target_id}"
            conn.execute('''
                INSERT INTO connector_secret (connector_id, name, value)
                VALUES ('discord', ?, ?)
            ''', (secret_ref, webhook_url))
            conn.execute('''
                INSERT INTO connector_target
                    (target_id, connector_id, label, secret_ref, is_default, enabled)
                VALUES (?, 'discord', 'Default', ?, 1, 1)
            ''', (target_id, secret_ref))

        # One value, one home. Leaving these behind would give the same
        # setting two places to live, which is the exact failure the settings
        # boundary was rebuilt to end.
        conn.execute("DELETE FROM app_settings WHERE key LIKE 'DISCORD_%'")
        print("🔌 Migrated Discord settings onto the connector layer")

    def _backfill_media_items(self, conn):
        """
        Build the title index out of rows this database already holds.

        No API call, no operator step. Every notification ever received carries
        the external identifier — `tvdb_id` on 820 of 820 series rows,
        `tmdb_id` on 72 of 72 film rows — and each one points at the transfer it
        started, which is where the library folder name actually lives. Between
        the two, the mapping this table exists to hold can simply be read off.

        Runs once: guarded on the table being empty rather than on a version
        number, so it is safe on every start and safe to run twice. An install
        with no history gets an empty table and fills it as webhooks arrive.

        A title string is used in exactly one place here — attributing the
        transfers that were started by hand or by Explore and so never carried
        an identifier. That is a one-off at migration rather than a lookup on
        every operation, and anything it cannot match is left null and shown as
        unattributed rather than guessed at.
        """
        if conn.execute('SELECT COUNT(*) FROM media_item').fetchone()[0] > 0:
            return

        def _tables():
            return {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}

        present = _tables()
        made = 0

        # -- series, keyed by tvdb_id ---------------------------------------
        if 'sonarr_webhook' in present:
            rows = conn.execute("""
                SELECT tvdb_id,
                       MAX(series_title)      AS title,
                       MAX(series_title_slug) AS slug,
                       MAX(imdb_id)           AS imdb_id,
                       MAX(series_id)         AS service_item_id,
                       MAX(year)              AS year,
                       MAX(media_type)        AS media_type
                  FROM sonarr_webhook
                 WHERE tvdb_id IS NOT NULL AND tvdb_id != ''
                 GROUP BY tvdb_id
            """).fetchall()
            # Positional rather than by name: this connection is the plain one
            # init_database opens, without a row factory.
            for tvdb_id, title, slug, imdb_id, service_item_id, year, media_type in rows:
                folder = conn.execute("""
                    SELECT t.folder_name FROM transfers t
                      JOIN sonarr_webhook w ON w.transfer_id = t.transfer_id
                     WHERE w.tvdb_id = ? AND t.folder_name IS NOT NULL
                     ORDER BY t.created_at DESC LIMIT 1
                """, (tvdb_id,)).fetchone()
                conn.execute("""
                    INSERT OR IGNORE INTO media_item
                        (source, external_id, media_type, service_item_id, title,
                         year, title_slug, imdb_id, local_folder)
                    VALUES ('sonarr', ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(tvdb_id), media_type, service_item_id, title, year,
                      slug, imdb_id, folder[0] if folder else None))
                made += 1

        # -- films, keyed by tmdb_id ----------------------------------------
        if 'radarr_webhook' in present:
            rows = conn.execute("""
                SELECT tmdb_id,
                       MAX(title)   AS title,
                       MAX(imdb_id) AS imdb_id,
                       MAX(year)    AS year
                  FROM radarr_webhook
                 WHERE tmdb_id IS NOT NULL AND tmdb_id != ''
                 GROUP BY tmdb_id
            """).fetchall()
            for tmdb_id, title, imdb_id, year in rows:
                folder = conn.execute("""
                    SELECT t.folder_name FROM transfers t
                      JOIN radarr_webhook w ON w.transfer_id = t.transfer_id
                     WHERE w.tmdb_id = ? AND t.folder_name IS NOT NULL
                     ORDER BY t.created_at DESC LIMIT 1
                """, (tmdb_id,)).fetchone()
                conn.execute("""
                    INSERT OR IGNORE INTO media_item
                        (source, external_id, media_type, title, year,
                         imdb_id, local_folder)
                    VALUES ('radarr', ?, 'movies', ?, ?, ?, ?)
                """, (str(tmdb_id), title, year, imdb_id,
                      folder[0] if folder else None))
                made += 1

        if not made:
            return

        # -- attach transfers, identifier first ------------------------------
        linked = 0
        for wh, col, src in (('sonarr_webhook', 'tvdb_id', 'sonarr'),
                             ('radarr_webhook', 'tmdb_id', 'radarr')):
            if wh not in present:
                continue
            cur = conn.execute(f"""
                UPDATE transfers SET media_item_id = (
                    SELECT m.id FROM media_item m
                      JOIN {wh} w ON w.{col} = m.external_id
                     WHERE w.transfer_id = transfers.transfer_id
                       AND m.source = '{src}'
                     LIMIT 1)
                 WHERE media_item_id IS NULL
                   AND transfer_id IN (SELECT transfer_id FROM {wh}
                                        WHERE transfer_id IS NOT NULL)
            """)
            linked += cur.rowcount or 0

        # -- then, and only then, by folder name -----------------------------
        by_name = conn.execute("""
            UPDATE transfers SET media_item_id = (
                SELECT m.id FROM media_item m
                 WHERE m.local_folder = transfers.folder_name LIMIT 1)
             WHERE media_item_id IS NULL AND folder_name IS NOT NULL
               AND EXISTS (SELECT 1 FROM media_item m
                            WHERE m.local_folder = transfers.folder_name)
        """).rowcount or 0

        # -- stored versions follow their transfer, or their folder ----------
        if 'backup_capture' in present:
            conn.execute("""
                UPDATE backup_capture SET media_item_id = (
                    SELECT t.media_item_id FROM transfers t
                     WHERE t.transfer_id = backup_capture.source_transfer_id
                       AND t.media_item_id IS NOT NULL LIMIT 1)
                 WHERE media_item_id IS NULL AND source_transfer_id IS NOT NULL
            """)
            conn.execute("""
                UPDATE backup_capture SET media_item_id = (
                    SELECT m.id FROM media_item m
                     WHERE m.local_folder = backup_capture.title LIMIT 1)
                 WHERE media_item_id IS NULL AND title IS NOT NULL
                   AND EXISTS (SELECT 1 FROM media_item m
                                WHERE m.local_folder = backup_capture.title)
            """)

        print(f"🧩 Built the title index: {made} titles, "
              f"{linked} transfers by identifier, {by_name} by folder name")

    def _create_sync_engine_tables(self, conn):
        """The sync engine's memory: every pass through the pipeline, stage by stage.

        One `sync_run` is one pass — a batch of webhooks for a season, a manual
        sync, an Explore plan, a restart. It is written as it changes, so a
        restart can see what was in flight and say so instead of forgetting it.

        `sync_run_stage` holds one row per stage of a run: where it got to and a
        sentence saying why — including, always, why a stage was skipped.
        `sync_run_event` is the log, every line tagged with the stage it belongs
        to, which is what lets the interface show each stage's own output.
        """
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sync_run (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL,
                source TEXT,
                media_type TEXT,
                unit_key TEXT,
                mergeable INTEGER NOT NULL DEFAULT 1,
                title TEXT,
                season_number INTEGER,
                season_name TEXT,
                folder_name TEXT,
                source_path TEXT,
                dest_path TEXT,
                operation_type TEXT DEFAULT 'folder',
                state TEXT NOT NULL,
                current_stage TEXT,
                outcome TEXT,
                outcome_message TEXT,
                transfer_id TEXT,
                parent_run_id TEXT,
                parent_relation TEXT,
                requested_by_kind TEXT,
                requested_by_name TEXT,
                requested_by_account_id INTEGER,
                is_simulation INTEGER NOT NULL DEFAULT 0,
                ready_mode TEXT,
                next_check_at REAL,
                timer_due_at REAL,
                ready_deadline_at REAL,
                checks_made INTEGER NOT NULL DEFAULT 0,
                go_now INTEGER NOT NULL DEFAULT 0,
                force_safety INTEGER NOT NULL DEFAULT 0,
                options TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sync_run_stage (
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT,
                detail TEXT,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, stage)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sync_run_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                message TEXT NOT NULL,
                data TEXT,
                created_at TEXT NOT NULL
            )
        ''')

        # Which run a webhook rides on, and which run owns a transfer. A column
        # rather than a join table: a webhook belongs to exactly one run at a
        # time, and "webhooks that belong to no run" is the question the
        # restart recovery asks.
        self._ensure_column(conn, 'sonarr_webhook', 'sync_run_id', "TEXT")
        self._ensure_column(conn, 'sonarr_webhook', 'sync_attached_at', "TEXT")
        self._ensure_column(conn, 'radarr_webhook', 'sync_run_id', "TEXT")
        self._ensure_column(conn, 'radarr_webhook', 'sync_attached_at', "TEXT")
        self._ensure_column(conn, 'transfers', 'sync_run_id', "TEXT")
        # A movie the safety check stopped, or a restart interrupted, carries
        # the same "needs a person" flag a series webhook does.
        self._ensure_column(conn, 'radarr_webhook', 'requires_manual_sync', "INTEGER DEFAULT 0")
        self._ensure_column(conn, 'radarr_webhook', 'manual_sync_reason', "TEXT")

        conn.execute('CREATE INDEX IF NOT EXISTS idx_sync_run_state ON sync_run(state)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sync_run_unit ON sync_run(unit_key, state)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sync_run_transfer ON sync_run(transfer_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sync_run_created ON sync_run(created_at DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sync_run_due ON sync_run(state, next_check_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sync_event_run ON sync_run_event(run_id, id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sonarr_webhook_sync_run ON sonarr_webhook(sync_run_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_radarr_webhook_sync_run ON radarr_webhook(sync_run_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_transfers_sync_run ON transfers(sync_run_id)')

        # ---- the Notifications tab -----------------------------------------
        # Everything that needs a person. An alert is opened by the engine (a
        # restart left work unfinished, a download is stuck, a sync was refused
        # or failed) and closed by an admin acting on it. `dedupe_key` keeps one
        # open alert per subject: a second occurrence bumps the first.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS alert (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT,
                state TEXT NOT NULL DEFAULT 'open',
                dedupe_key TEXT,
                run_id TEXT,
                transfer_id TEXT,
                unit_key TEXT,
                link TEXT,
                actions TEXT NOT NULL DEFAULT '[]',
                data TEXT NOT NULL DEFAULT '{}',
                occurrences INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_action TEXT,
                resolved_by_kind TEXT,
                resolved_by_name TEXT,
                resolved_by_account_id INTEGER
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_alert_state ON alert(state, created_at DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_alert_dedupe ON alert(dedupe_key, state)')

        # ---- the scheduler's memory -----------------------------------------
        # One row per background job: when it last ran, whether it worked, and
        # what it said. Kept so the interface can show a job's state after a
        # restart, and so a job failing again and again is noticed.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_job (
                name TEXT PRIMARY KEY,
                last_run_at TEXT,
                last_finished_at TEXT,
                last_ok INTEGER,
                last_result TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        ''')

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

            # How the transfer reached the remote host: 'daemon' for the fast
            # transfer server, 'ssh' for the original route, NULL for a run that
            # predates the choice or never left this machine (a simulation).
            #
            # Written when rsync starts, because the answer depends on what was
            # true at that moment — whether the server was up and would accept
            # us — and cannot be reconstructed afterwards. Without it, a
            # transfer that fell back and one that never had a faster option
            # look identical: both simply slow.
            self._ensure_column(conn, 'transfers', 'transport', "TEXT")

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

            # ---- the title index ------------------------------------------
            # One row per title, keyed by the identifier the service will not
            # change: tvdbId for Sonarr, tmdbId for Radarr. See
            # models/media_item.py for why neither the service's own row id nor
            # the title itself can play that part.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS media_item (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    media_type TEXT,
                    service_item_id INTEGER,
                    service_item_id_seen_at DATETIME,
                    title TEXT,
                    year INTEGER,
                    title_slug TEXT,
                    imdb_id TEXT,
                    local_folder TEXT,
                    present_in_service INTEGER DEFAULT 1,
                    last_seen_in_service_at DATETIME,
                    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source, external_id)
                )
            ''')

            # Counts are a cache of what the service said, which is why every
            # row carries the moment it was true. A reader that cannot see the
            # age of an answer ends up trusting a stale one.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS media_item_season (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_item_id INTEGER NOT NULL,
                    season_number INTEGER NOT NULL,
                    episodes_total INTEGER,
                    episodes_with_file INTEGER,
                    episodes_monitored INTEGER,
                    refreshed_at DATETIME,
                    last_synced_transfer_id TEXT,
                    last_synced_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(media_item_id, season_number)
                )
            ''')

            # Plain nullable integers rather than declared foreign keys: no
            # other table in this database declares one, SQLite does not enforce
            # them unless switched on per connection, and adding constraints to
            # only the newest relationships would change delete behaviour in one
            # corner of a schema that is otherwise consistent.
            self._ensure_column(conn, 'transfers', 'media_item_id', "INTEGER")
            self._ensure_column(conn, 'backup_capture', 'media_item_id', "INTEGER")

            # ---- what the library sweep has already seen -------------------
            # Without this the sweep has no memory: it re-derives the same gap
            # every run, re-announces it, and — when it is allowed to act —
            # starts the same transfer again. Measured before this existed: the
            # same five seasons queued 34 times in eight hours, and Discord got
            # a message for each round.
            #
            # A finding is keyed by what it is about, not by when it was found,
            # so the same gap seen an hour later updates a row rather than
            # adding one. `resolved_at` is what makes a reappearance tellable
            # from a persistence — a season that came back after being fetched
            # is news; one that has been missing all week is not.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sweep_finding (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    season_number INTEGER,
                    title TEXT,
                    finding TEXT,
                    detail TEXT,
                    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    notified_at DATETIME,
                    sync_started_at DATETIME,
                    sync_attempts INTEGER DEFAULT 0,
                    last_transfer_id TEXT,
                    resolved_at DATETIME,
                    UNIQUE(source, external_id, season_number)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sweep_finding_open '
                         'ON sweep_finding(source, resolved_at)')

            conn.execute('CREATE INDEX IF NOT EXISTS idx_media_item_folder ON media_item(local_folder)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_media_item_service ON media_item(source, service_item_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_media_item_type ON media_item(media_type)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_media_item_season_item ON media_item_season(media_item_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_transfers_media_item ON transfers(media_item_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backup_capture_media_item ON backup_capture(media_item_id)')

            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_occurred ON activity(occurred_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_actor ON activity(actor_account_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_action ON activity(action)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_target ON activity(target_type, target_id)')

            # ==========================================
            # Tables: connectors
            # ==========================================
            # A connector is a link to one outside service. These are a *list*,
            # not a fixed set of keys, which is why they sit outside
            # `settings_registry` — that registry holds singleton values whose
            # existence is known at import time, and "the three Discord
            # webhooks this operator added" is not that.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS connector (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    connector_id TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    config TEXT NOT NULL DEFAULT '{}',
                    last_check_at DATETIME,
                    last_check_ok INTEGER,
                    last_check_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Secrets live in their own table under one rule: no read path
            # reaches a response body. Not redacted, not partially shown —
            # there is simply no route that serialises this. That is easier to
            # keep true than "remember which four keys inside a JSON blob need
            # masking", which is how the setting this replaces was handled.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS connector_secret (
                    connector_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (connector_id, name)
                )
            ''')

            # One destination belonging to a connector — a named Discord
            # webhook today. The label is unique per connector because it is an
            # identifier an operator picked and reasons about, not decoration.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS connector_target (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id TEXT UNIQUE NOT NULL,
                    connector_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    secret_ref TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_send_at DATETIME,
                    last_send_ok INTEGER,
                    last_send_error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (connector_id, label)
                )
            ''')

            # Which destination an announcement goes to. A missing row means
            # "use the connector's default", so a newly added event type is
            # delivered rather than silently dropped.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS notification_route (
                    event_key TEXT NOT NULL,
                    connector_id TEXT NOT NULL,
                    target_id TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (event_key, connector_id)
                )
            ''')

            # What actually happened, bounded. This is the whole answer to "why
            # didn't I get told about that", which before this table required
            # reading the server console while it was still in the buffer.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS connector_delivery (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    connector_id TEXT NOT NULL,
                    target_id TEXT,
                    target_label TEXT,
                    event_key TEXT,
                    title TEXT,
                    ok INTEGER NOT NULL,
                    skipped_reason TEXT,
                    status_code INTEGER,
                    error TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_occurred ON activity(occurred_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_actor ON activity(actor_account_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_action ON activity(action)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_target ON activity(target_type, target_id)')

            conn.execute('CREATE INDEX IF NOT EXISTS idx_transfer_file_transfer ON transfer_file(transfer_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_explore_plan_expiry ON explore_plan(expires_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_admin_account_active ON admin_account(is_active)')

            # Who a message may ping: a Discord role, a user, @here or
            # @everyone, under a name the operator chose. Webhooks and routes
            # refer to these by id (JSON lists), so renaming one or fixing its
            # id changes every place it is used.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS connector_mention (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mention_id TEXT UNIQUE NOT NULL,
                    connector_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (connector_id, label)
                )
            ''')
            # A webhook's own pings, used for every message sent to it unless
            # the notification chooses others. NULL is nobody.
            self._ensure_column(conn, 'connector_target', 'mention_ids', "TEXT")
            # When a notification pings (never / warnings and failures /
            # always; NULL is the catalogue's default) and whom (NULL is the
            # webhook's own pings).
            self._ensure_column(conn, 'notification_route', 'ping_when', "TEXT")
            self._ensure_column(conn, 'notification_route', 'mention_ids', "TEXT")
            # Who a delivered message pinged, by name, for the delivery log.
            self._ensure_column(conn, 'connector_delivery', 'mentions', "TEXT")

            conn.execute('CREATE INDEX IF NOT EXISTS idx_connector_target_owner ON connector_target(connector_id)')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_connector_delivery_recent '
                'ON connector_delivery(connector_id, id DESC)'
            )

            self._create_sync_engine_tables(conn)

            self._migrate_discord_to_connector(conn)
            self._backfill_media_items(conn)

            conn.commit()
        
        print(f"✅ Database initialized: {self.db_path}")
    
    def get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
