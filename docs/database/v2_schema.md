# DragonCP Database Schema v2 Documentation

## Overview

This document describes the current SQLite schema used by DragonCP.

**Database System:** SQLite  
**Database File:** `dragoncp.db` (stored in project root)  
**Connection Manager:** `DatabaseManager` in `models/database.py`

## Current Schema Conventions

### Table Names In Current Code
- `transfers`
- `radarr_webhook`
- `sonarr_webhook`
- `rename_webhook`
- `backup`
- `backup_file`
- `app_settings`

### Column Renames
- `transfer_type` → `operation_type` (more descriptive)
- `process_id` → `rsync_process_id` (clearer purpose)
- `backup_dir` → `backup_path` (consistent with other path fields)

### Post-v2 Additions

Added through `DatabaseManager._ensure_column`, so existing databases pick them
up on startup without a migration script:

- `transfers`: `progress_percent`, `bytes_transferred`, `total_bytes`,
  `speed_bps`, `eta_seconds` (parsed rsync progress); `paused_at`
  (pause/resume); `is_simulation`, `simulation_bwlimit` (simulation tool)
- `radarr_webhook.is_simulation`, `sonarr_webhook.is_simulation` - notifications
  created by the simulation tool, removed by its cleanup

### Queue-Related Additions/Changes
- `transfers.queue_reason` stores whether a queued transfer is blocked by `path` or `slot`
- series/anime manual-sync-required rows currently use `requires_manual_sync` + `manual_sync_reason`
- timestamp usage is standardized around `created_at`, `updated_at`, and `completed_at`

---

## Table: `transfers`

**Purpose:** Tracks file transfer operations (rsync transfers)

**Schema:**
```sql
CREATE TABLE transfers (
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
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Parsed rsync progress (added post-v2, via _ensure_column)
    progress_percent INTEGER,
    bytes_transferred INTEGER,
    total_bytes INTEGER,
    speed_bps INTEGER,
    eta_seconds INTEGER,

    -- Pause/resume
    paused_at DATETIME,

    -- Simulation tool
    is_simulation INTEGER DEFAULT 0,
    simulation_bwlimit INTEGER
)
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `transfer_id` - Unique identifier for the transfer (UUID format)
- `media_type` - Type of media: 'movies', 'tvshows', 'anime'
- `folder_name` - Name of the media folder
- `season_name` - Name of the season folder (for series/anime)
- `source_path` - Source path on remote server
- `dest_path` - Destination path on local machine
- `operation_type` - Type of operation: 'folder', 'file', etc. (renamed from `transfer_type`)
- `status` - Transfer status: 'pending', 'queued', 'running', 'paused', 'completed', 'failed', 'cancelled'
- `progress` - Latest rsync output line (text). The structured figures below are
  the ones the UI reads; this is the raw line.
- `queue_reason` - Queue reason for queued transfers: `path`, `slot`, or `NULL`
- `rsync_process_id` - Process ID of the rsync process (renamed from `process_id`)
- `logs` - JSON array of log entries
- `parsed_title` - Parsed title from folder name
- `parsed_season` - Parsed season number
- `start_time` - Transfer start timestamp
- `end_time` - Transfer end timestamp
- `created_at` - Record creation timestamp
- `updated_at` - Record last update timestamp

**Parsed progress columns** (populated from rsync's `--info=progress2` output by
`services/transfer_service.py`; see `parse_rsync_progress`):
- `progress_percent` - Percent complete for the whole transfer, 0-100
- `bytes_transferred` - Bytes copied so far
- `total_bytes` - Size of the transfer set. Derived from percent and bytes while
  running, then replaced with the exact figure from rsync's `--stats` summary
- `speed_bps` - Current throughput in bytes per second, 0 once finished
- `eta_seconds` - rsync's own estimate of seconds remaining, NULL once finished

**Pause/resume:**
- `paused_at` - When the transfer was paused, NULL otherwise. A pause stops the
  rsync process and keeps the partial files; resuming starts a new rsync run that
  continues from them via `--partial`/`--partial-dir`

**Simulation tool** (see `services/simulation_service.py`):
- `is_simulation` - 1 for rows created by the simulation tool. They run through
  the real pipeline, so they live in this table; the flag is what tells them
  apart from genuine history and what cleanup deletes by
- `simulation_bwlimit` - Speed ceiling in KB/s for a simulated transfer, so a
  scenario runs slowly enough to observe. NULL for real transfers

**Log storage note:** `logs` holds a JSON array, but rsync progress lines are not
accumulated into it. Consecutive progress lines collapse to the newest, so the
array holds the durable output - file names, the `--stats` block, warnings and
errors - plus at most one trailing progress line. Listing queries never select
this column; they count it in SQL instead. See
`docs/plans/RSYNC_LOG_STREAMING_REDESIGN.md`.

**Indexes:**
- `idx_transfer_id` on `transfer_id` - Fast lookup by transfer ID
- `idx_status` on `status` - Filtering by status
- `idx_created_at` on `created_at` - Sorting by creation time
- `idx_dest_status` on `dest_path, status` - Duplicate detection queries

**Model:** `Transfer` in `models/transfer.py`

---

## Table: `radarr_webhook`

**Purpose:** Movie webhook notifications from Radarr

**Schema:**
```sql
CREATE TABLE radarr_webhook (
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
    transfer_id TEXT,
    raw_webhook_data TEXT
)
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `notification_id` - Unique identifier for the notification (UUID format)
- `title` - Movie title
- `year` - Release year
- `folder_path` - Server source path
- `poster_url` - Movie poster image URL
- `requested_by` - User who requested the movie
- `file_path` - Path to the movie file
- `quality` - Video quality (e.g., 'Bluray-1080p')
- `size` - File size in bytes
- `languages` - JSON array of audio languages
- `subtitles` - JSON array of subtitle languages
- `release_title` - Release title from indexer
- `release_indexer` - Indexer name
- `release_size` - Release size in bytes
- `tmdb_id` - The Movie Database ID
- `imdb_id` - Internet Movie Database ID
- `status` - Notification status: 'pending', 'syncing', 'completed', 'failed', 'cancelled'
- `error_message` - Error details if failed
- `created_at` - Record creation timestamp
- `completed_at` - Timestamp when the notification completed
- `transfer_id` - Associated transfer ID
- `raw_webhook_data` - Full webhook JSON payload

**Indexes:**
- `idx_radarr_webhook_notification_id` on `notification_id` - Fast lookup by notification ID
- `idx_radarr_webhook_status` on `status` - Filtering by status
- `idx_radarr_webhook_created_at` on `created_at` - Sorting by creation time
- `idx_radarr_webhook_transfer_id` on `transfer_id` - Lookup by transfer ID

**Model:** `WebhookNotification` in `models/webhook.py`

---

## Table: `sonarr_webhook`

**Purpose:** Series/anime webhook notifications from Sonarr

**Schema:**
```sql
CREATE TABLE sonarr_webhook (
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
    completed_at DATETIME,
    transfer_id TEXT,
    -- Auto-sync related fields
    requires_manual_sync INTEGER DEFAULT 0,  -- 0=false, 1=true
    manual_sync_reason TEXT,
    auto_sync_scheduled_at DATETIME,
    dry_run_result TEXT,  -- JSON with dry-run validation results
    dry_run_performed_at DATETIME,
    raw_webhook_data TEXT
)
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `notification_id` - Unique identifier for the notification (UUID format)
- `media_type` - Type of media: 'tvshows' or 'anime'
- `series_title` - Series title
- `series_title_slug` - URL-safe series identifier
- `series_id` - Series ID from Sonarr
- `series_path` - Server source path for the series
- `year` - Series release year
- `tvdb_id` - TheTVDB ID
- `tv_maze_id` - TVMaze ID
- `tmdb_id` - The Movie Database ID
- `imdb_id` - Internet Movie Database ID
- `poster_url` - Series poster image URL
- `banner_url` - Series banner image URL
- `tags` - JSON array of series tags
- `original_language` - Original language of the series
- `requested_by` - User who requested the series
- `season_number` - Season number
- `episode_count` - Number of episodes in this notification
- `episodes` - JSON array of episode details
- `episode_files` - JSON array of episode file details
- `season_path` - Season-level source path from Sonarr event; also used to derive destination path
- `release_title` - Release title from indexer
- `release_indexer` - Indexer name
- `release_size` - Release size in bytes
- `download_client` - Download client name
- `status` - Notification status (see State Lifecycle below)
- `error_message` - Error details if failed
- `created_at` - Record creation timestamp
- `completed_at` - Timestamp when the notification completed or was marked syncing/completed by current flow
- `transfer_id` - Associated transfer ID
- `requires_manual_sync` - Boolean flag (0=false, 1=true)
- `manual_sync_reason` - Reason why manual sync is required
- `auto_sync_scheduled_at` - Scheduled auto-sync timestamp
- `dry_run_result` - JSON with dry-run validation results
- `dry_run_performed_at` - Timestamp when dry-run was performed
- `raw_webhook_data` - Full webhook JSON payload

**Status Values In Current Code:**
- `pending` - Initial state and also currently reused for manual-sync-required rows
- `READY_FOR_TRANSFER` - Dry-run validation passed, ready for transfer
- `QUEUED_SLOT` - Blocked by max concurrent transfer limit
- `QUEUED_PATH` - Blocked by same destination path conflict
- `syncing` - Transfer actively in progress
- `completed` - Transfer finished successfully
- `failed` - Transfer failed or error occurred
- `cancelled` - User cancelled the transfer

**Manual-sync-required behavior today:**
- the code does not currently persist `MANUAL_SYNC_REQUIRED` as a status
- instead it keeps `status='pending'` and sets `requires_manual_sync=1`
- `manual_sync_reason`, `dry_run_result`, and `dry_run_performed_at` hold the safety decision details

**Indexes:**
- `idx_sonarr_webhook_notification_id` on `notification_id` - Fast lookup by notification ID
- `idx_sonarr_webhook_status` on `status` - Filtering by status
- `idx_sonarr_webhook_transfer_id` on `transfer_id` - Lookup by transfer ID

**Model:** `SeriesWebhookNotification` in `models/webhook.py`

---

## Table: `rename_webhook`

**Purpose:** File rename webhook notifications from Sonarr

**Schema:**
```sql
CREATE TABLE rename_webhook (
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
    completed_at DATETIME,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `notification_id` - Unique identifier for the notification (UUID format)
- `media_type` - Type of media: 'tvshows' or 'anime'
- `series_title` - Series title
- `series_id` - Series ID from Sonarr
- `series_path` - Server source path for the series
- `renamed_files` - JSON array of rename operations with status
- `total_files` - Total number of files to rename
- `success_count` - Number of successfully renamed files
- `failed_count` - Number of failed rename operations
- `status` - Notification status: 'pending', 'completed', 'partial', 'failed'
- `error_message` - Error details if failed
- `raw_webhook_data` - Full webhook JSON payload
- `created_at` - Record creation timestamp
- `completed_at` - Timestamp when processing completed
- `updated_at` - Timestamp of the last row update

**Indexes:**
- `idx_rename_webhook_notification_id` on `notification_id` - Fast lookup by notification ID
- `idx_rename_webhook_status` on `status` - Filtering by status
- `idx_rename_webhook_created_at` on `created_at` - Sorting by creation time

**Model:** `RenameNotification` in `models/webhook.py`

---

## Table: `app_settings`

**Purpose:** Key-value settings store for dynamic configuration

**Schema:**
```sql
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

**Column Descriptions:**
- `key` - Setting key (primary key)
- `value` - Setting value (stored as text)
- `updated_at` - Last update timestamp

**Model:** `AppSettings` in `models/settings.py`

**No changes from v1.**

---

## Table: `backup`

**Purpose:** Backup records for rsync --backup deletions

**Schema:**
```sql
CREATE TABLE backup (
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
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `backup_id` - Unique identifier for the backup (UUID format)
- `transfer_id` - Associated transfer ID
- `media_type` - Type of media: 'movies', 'tvshows', 'anime'
- `folder_name` - Name of the media folder
- `season_name` - Name of the season folder (for series/anime)
- `source_path` - Source path on remote server
- `dest_path` - Destination path on local machine
- `backup_path` - Directory where backup files are stored (renamed from `backup_dir`)
- `file_count` - Number of files in backup
- `total_size` - Total size of backup in bytes
- `status` - Backup status: 'ready', 'deleted', etc.
- `created_at` - Record creation timestamp
- `restored_at` - Timestamp when backup was restored
- `updated_at` - Last update timestamp

**Indexes:**
- `idx_backup_transfer_id` on `transfer_id` - Lookup by transfer ID

**Model:** `Backup` in `models/backup.py`

---

## Table: `backup_file`

**Purpose:** Individual files within backups

**Schema:**
```sql
CREATE TABLE backup_file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    original_path TEXT NOT NULL,
    file_size INTEGER,
    modified_time INTEGER,
    -- Context-aware fields for smarter restore
    -- These fields store metadata about the file's context to enable
    -- intelligent restore operations that can match files to their
    -- original locations even if paths have changed.
    context_media_type TEXT,      -- Media type: 'movies', 'tvshows', 'anime'
    context_title TEXT,            -- Movie or series title
    context_release_year TEXT,    -- Release year
    context_series_title TEXT,    -- Series title (for series/anime)
    context_season TEXT,          -- Season number/name
    context_episode TEXT,         -- Episode number/name
    context_absolute TEXT,        -- Absolute path context
    context_key TEXT,             -- Composite key for context-aware queries
    context_display TEXT,         -- Display-friendly context string
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `backup_id` - Foreign key to `backup.backup_id`
- `relative_path` - Relative path within backup directory
- `original_path` - Original path before backup
- `file_size` - File size in bytes
- `modified_time` - File modification timestamp
- `context_media_type` - Media type context for restore
- `context_title` - Title context for restore
- `context_release_year` - Release year context for restore
- `context_series_title` - Series title context for restore
- `context_season` - Season context for restore
- `context_episode` - Episode context for restore
- `context_absolute` - Absolute path context
- `context_key` - Key for context-aware restore queries
- `context_display` - Display-friendly context string
- `created_at` - Record creation timestamp

**Indexes:**
- `idx_backup_file_backup_id` on `backup_id` - Fast lookup by backup ID
- `idx_backup_file_context_key` on `context_key` - Context-aware restore queries

**Model:** `Backup` in `models/backup.py`

**Context Fields Purpose:**
The `context_*` fields are used for intelligent restore operations. They store metadata about the file's context (media type, title, season, episode, etc.) to enable context-aware restore queries that can match files to their original locations even if paths have changed. These fields are essential for the restore functionality and are kept in v2.

---

## Database Indexes Summary

### Performance Indexes
All indexes are created with `CREATE INDEX IF NOT EXISTS` to allow safe re-execution.

**Transfer Indexes:**
- `idx_transfer_id` on `transfers(transfer_id)` - Primary lookup index
- `idx_status` on `transfers(status)` - Status filtering
- `idx_created_at` on `transfers(created_at)` - Time-based queries
- `idx_dest_status` on `transfers(dest_path, status)` - Duplicate detection

**Radarr Webhook Indexes:**
- `idx_radarr_webhook_notification_id` on `radarr_webhook(notification_id)` - Primary lookup
- `idx_radarr_webhook_status` on `radarr_webhook(status)` - Status filtering
- `idx_radarr_webhook_created_at` on `radarr_webhook(created_at)` - Time-based queries
- `idx_radarr_webhook_transfer_id` on `radarr_webhook(transfer_id)` - Transfer linking

**Sonarr Webhook Indexes:**
- `idx_sonarr_webhook_notification_id` on `sonarr_webhook(notification_id)` - Primary lookup
- `idx_sonarr_webhook_status` on `sonarr_webhook(status)` - Status filtering
- `idx_sonarr_webhook_transfer_id` on `sonarr_webhook(transfer_id)` - Transfer linking

**Rename Webhook Indexes:**
- `idx_rename_webhook_notification_id` on `rename_webhook(notification_id)` - Primary lookup
- `idx_rename_webhook_status` on `rename_webhook(status)` - Status filtering
- `idx_rename_webhook_created_at` on `rename_webhook(created_at)` - Time-based queries

**Backup Indexes:**
- `idx_backup_transfer_id` on `backup(transfer_id)` - Transfer linking
- `idx_backup_file_backup_id` on `backup_file(backup_id)` - File lookup by backup
- `idx_backup_file_context_key` on `backup_file(context_key)` - Context-aware restore queries

---

## Legacy/Migration Notes

Older v1-to-v2 migration guidance, including destructive migration assumptions, has been moved out of this live schema reference.

See `docs/database/LEGACY_V2_MIGRATION_NOTES.md` for legacy migration context.

---

## Related Documentation

- **v1 Schema:** `docs/database/v1_schema.md`
- **Legacy migration notes:** `docs/database/LEGACY_V2_MIGRATION_NOTES.md`
- **Database Manager:** `models/database.py`
- **Transfer Model:** `models/transfer.py`
- **Backup Model:** `models/backup.py`
- **Webhook Models:** `models/webhook.py`
- **Settings Model:** `models/settings.py`
- **Migration Script:** `scripts/migrate_v1_to_v2.py`
