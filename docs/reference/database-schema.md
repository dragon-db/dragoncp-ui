# DragonCP Database Schema v2 Documentation

Last updated: 2026-10-05

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
- `backup` *(legacy — read by the backups migration, written by nothing)*
- `backup_file` *(legacy — as above)*
- `backup_capture`
- `backup_capture_file`
- `backup_capture_key`
- `app_settings`
- `admin_account`
- `activity`
- `sync_run`, `sync_run_stage`, `sync_run_event` *(the sync engine, 2.3.0)*
- `alert` *(the Notifications page, 2.3.0)*
- `scheduled_job` *(the scheduler, 2.3.0)*
- `sweep_finding` *(gaps the auto-scanner has seen)*

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
- `transfers`: `explore_files_from`, `explore_mode`, `explore_plan_id` - an
  Explore run copies an approved list of files rather than a whole directory, so
  rsync is given `--files-from` and never `--delete`. Stored on the row so a
  queued, promoted, resumed or restarted run rebuilds the same command.
- `transfers.transport` - which route reached the media host: `daemon` for the
  fast transfer server, `ssh` for the original route, `NULL` for a run that
  predates the choice or never left this machine. Written when rsync starts,
  because the answer depends on what was true at that moment and cannot be
  reconstructed; without it a transfer that fell back to the slow route and one
  that never had a faster option look identical. See
  `../features/fast-transfers/README.md`.
- `sonarr_webhook.sync_run_id`, `sonarr_webhook.sync_attached_at`,
  `radarr_webhook.sync_run_id`, `radarr_webhook.sync_attached_at`,
  `transfers.sync_run_id` (2.3.0) - which sync run a webhook rides on, when it
  joined that run, and which run owns a transfer. A column rather than a join
  table because a webhook belongs to exactly one run at a time, and "webhooks
  that belong to no run" is the question restart recovery asks. Added by
  `DatabaseManager._create_sync_engine_tables`, together with an index on each.
- `radarr_webhook.requires_manual_sync` (`INTEGER DEFAULT 0`) and
  `radarr_webhook.manual_sync_reason` (`TEXT`) (2.3.0, added 2026-10-05) - the
  "needs a person" flag and its reason, which until then only `sonarr_webhook`
  had, so a movie the safety check stopped or a restart interrupted went back
  to `pending` with nothing saying why. Added by the same
  `_create_sync_engine_tables`.

### Explore Tables

Added in the same startup path, created with `CREATE TABLE IF NOT EXISTS`:
`explore_snapshot` (the cached comparison), `explore_plan` (an evaluated
operation awaiting approval) and `transfer_file` (what a run did, file by file).
Each is documented in full below.

### Account Table

`admin_account` arrived with named administrators and is created the same way,
with `CREATE TABLE IF NOT EXISTS` at startup. An existing database picks it up
empty, and sign-in keeps using the environment-file credentials until the first
account is added — so the upgrade needs no migration step and changes nothing
until someone chooses to.

### Sync Engine Tables

Created in 2.3.0 by `DatabaseManager._create_sync_engine_tables`, which
`init_database` calls on every start, all with `CREATE TABLE IF NOT EXISTS`:
`sync_run` (one pass through the nine-stage pipeline), `sync_run_stage` (where
each stage of a run got to, and why), `sync_run_event` (each stage's log
lines), `alert` (the Notifications page) and `scheduled_job` (each background
job's last run). An upgraded database picks them up empty and nothing is
backfilled into them, though the first start's restart recovery may open
alerts for webhooks the old in-memory scheduler had taken and dropped (see
`sonarr_webhook.auto_sync_scheduled_at`). Each is documented in full below;
what the pipeline does is in `../features/sync-engine/README.md`.

Two times are stored differently from everything else here. The ready-check
columns on `sync_run` (`next_check_at`, `timer_due_at`, `ready_deadline_at`)
are `REAL` Unix epoch seconds, because the engine compares them with its own
clock. Every other time in these five tables is `TEXT` ISO-8601 in UTC with an
explicit offset (`datetime.now(timezone.utc).isoformat()`), unlike the older
tables' `DATETIME DEFAULT CURRENT_TIMESTAMP`. The API converts the epoch columns
to ISO strings before sending them.

### Queue-Related Additions/Changes
- `transfers.queue_reason` stores whether a queued transfer is blocked by `path` or `slot`
- manual-sync-required rows use `requires_manual_sync` + `manual_sync_reason`, on series/anime rows and, since 2026-10-05, on movie rows too
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
    simulation_bwlimit INTEGER,

    -- Sync engine (2.3.0)
    sync_run_id TEXT
)
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `transfer_id` - Unique identifier for the transfer. Not a UUID; the prefix
  records what created it: `transfer_<epoch>` (manual),
  `webhook_<notification_id>_<epoch>` (Radarr),
  `series_webhook_<notification_id>_<epoch>` (Sonarr),
  `simulation_<run_id>_<index>`, `restore_<backup_id>_<epoch>`
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

**Sync engine** (see `../features/sync-engine/README.md`):
- `sync_run_id` - the `sync_run` that owns this transfer. Written by
  `Transfer.create` when the engine hands a run to the queue, and rewritten by
  `TransferCoordinator.requeue_transfer` when a restart re-queues an existing
  row. It also decides how a finished transfer is closed: with it set, the
  engine's Finish and Tell stages mark the webhooks and announce the result;
  NULL (a transfer from before 2.3.0) is finished the old way, by
  `WebhookService.update_webhook_transfer_status` and a direct Discord message
  (`services/transfer_coordinator.py`). A restore's transfer row is created
  before its run, so it stays NULL here; the run still points at the transfer
  through `sync_run.transfer_id`

**Log storage note:** `logs` holds a JSON array, but rsync progress lines are not
accumulated into it. Consecutive progress lines collapse to the newest, so the
array holds the durable output - file names, the `--stats` block, warnings and
errors - plus at most one trailing progress line. Listing queries never select
this column; they count it in SQL instead. See
`../plans/rsync-log-streaming.md`.

**Indexes:**
- `idx_transfer_id` on `transfer_id` - Fast lookup by transfer ID
- `idx_status` on `status` - Filtering by status
- `idx_created_at` on `created_at` - Sorting by creation time
- `idx_dest_status` on `dest_path, status` - Duplicate detection queries
- `idx_transfers_sync_run` on `sync_run_id` - from a run to its transfer and back

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
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    transfer_id TEXT,
    raw_webhook_data TEXT,

    -- Sync engine (2.3.0, via _ensure_column)
    sync_run_id TEXT,
    sync_attached_at TEXT,
    requires_manual_sync INTEGER DEFAULT 0,  -- 0=false, 1=true (added 2026-10-05)
    manual_sync_reason TEXT                  -- (added 2026-10-05)
)
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `notification_id` - Unique identifier for the notification. Not a UUID;
  `movie_<movieId>_<epoch>` for Radarr, `<media_type>_<seriesId>_s<season>_ef<episodeFileId>`
  for Sonarr (falling back to a microsecond timestamp), `rename_<seriesId>_<epoch_ms>`
  for renames
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
- `status` - Notification status: 'pending', 'syncing', 'completed', 'failed',
  'cancelled'. Since 2.3.0 the sync engine writes every webhook on a run the same
  way, so a movie row also passes through 'READY_FOR_TRANSFER', 'QUEUED_SLOT' and
  'QUEUED_PATH' (meanings under `sonarr_webhook` below). A movie sync the
  safety check stopped, or a restart interrupted, goes back to 'pending' with
  `requires_manual_sync` set, as a series row does. Before 2026-10-05 this table
  had no manual-sync columns, and the reason lived only on the run
  (`sync_run.outcome_message`) and in its alert
- `error_message` - Error details if failed
- `created_at` - Record creation timestamp
- `completed_at` - Timestamp when the notification completed. The engine also
  stamps it when the copy starts (status 'syncing')
- `transfer_id` - Associated transfer ID
- `raw_webhook_data` - Full webhook JSON payload
- `sync_run_id` - The `sync_run` this webhook rides on. Set when it opens or
  joins a batch, and re-pointed whenever it moves: carried to a follow-up
  because it arrived after the copy began, taken over by a restart, or synced
  again by an admin after its run ended. NULL for rows from before 2.3.0
- `sync_attached_at` - When the webhook joined its current run (ISO-8601 UTC).
  At the end of a successful copy the engine compares it with the moment rsync
  started; a webhook that joined later is moved to a follow-up batch, because
  the copy may already have listed the folder
- `requires_manual_sync` - 1 when the movie needs a person: set by the Safety
  check refusing its sync, or by restart recovery finding a batch a restart
  interrupted; cleared by **Sync anyway**, and by **Mark as done** on an *After
  a restart* alert. Added 2026-10-05 (`_ensure_column`, so older rows read 0).
  The Webhooks page's Manual filter reads it on both tables
- `manual_sync_reason` - why: the dry run's reason, or `DragonCP restarted
  before this was synced`. Added 2026-10-05

**Indexes:**
- `idx_radarr_webhook_notification_id` on `notification_id` - Fast lookup by notification ID
- `idx_radarr_webhook_status` on `status` - Filtering by status
- `idx_radarr_webhook_created_at` on `created_at` - Sorting by creation time
- `idx_radarr_webhook_transfer_id` on `transfer_id` - Lookup by transfer ID
- `idx_radarr_webhook_sync_run` on `sync_run_id` - The webhooks riding on a run

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
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    transfer_id TEXT,
    -- Auto-sync related fields
    requires_manual_sync INTEGER DEFAULT 0,  -- 0=false, 1=true
    manual_sync_reason TEXT,
    auto_sync_scheduled_at DATETIME,
    dry_run_result TEXT,  -- JSON with dry-run validation results
    dry_run_performed_at DATETIME,
    raw_webhook_data TEXT,

    -- Sync engine (2.3.0, via _ensure_column)
    sync_run_id TEXT,
    sync_attached_at TEXT
)
```

**Column Descriptions:**
- `id` - Primary key, auto-incrementing integer
- `notification_id` - Unique identifier for the notification. Not a UUID;
  `movie_<movieId>_<epoch>` for Radarr, `<media_type>_<seriesId>_s<season>_ef<episodeFileId>`
  for Sonarr (falling back to a microsecond timestamp), `rename_<seriesId>_<epoch_ms>`
  for renames
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
- `updated_at` - Timestamp of the last row update. The sync engine sets it on
  every change it makes to the webhooks of a run
- `transfer_id` - Associated transfer ID
- `requires_manual_sync` - Boolean flag (0=false, 1=true)
- `manual_sync_reason` - Reason why manual sync is required
- `auto_sync_scheduled_at` - Since 2.3.0, written by the sync engine as the
  time of the batch's **next ready-check step**: the first question to Sonarr
  after the 10-second settle, the next question after Sonarr's time-left
  estimate, or the end of the fallback timer (`_mark_webhooks_waiting` in
  `services/sync_engine/engine.py`). It moves on every step, so it says when
  DragonCP will next look, not when the copy will start. The engine writes ISO
  UTC with an offset; rows from the old in-memory scheduler hold local time with
  none. Restart recovery also reads it: a row with this set, no `sync_run_id`,
  still `pending` or `READY_FOR_TRANSFER`, not a simulation, not already
  flagged for a manual sync and created in the last 7 days is one the old
  scheduler took and a restart dropped. Recovery flags it and raises one alert
  per folder (`services/sync_engine/recovery.py`)
- `dry_run_result` - JSON with dry-run validation results. Written by the sync
  engine's Safety check to every series webhook on the run (`raw_output`
  removed)
- `dry_run_performed_at` - Timestamp when dry-run was performed
- `raw_webhook_data` - Full webhook JSON payload
- `sync_run_id` - The `sync_run` this webhook rides on. Same meaning as on
  `radarr_webhook` above: set on joining a batch, re-pointed when the webhook
  moves to a follow-up, a restart or a later manual sync, NULL before 2.3.0
- `sync_attached_at` - When the webhook joined its current run (ISO-8601 UTC);
  compared with the start of the copy to catch a webhook that joined too late
  to be in it

**Status Values In Current Code:**

Since 2.3.0 the sync engine writes these for every webhook on a run
(`SyncRunStore.update_webhooks`), and never moves a row that is already
`completed` to another status.
- `pending` - Initial state; also the state while the batch is held for a
  person or waiting in the ready check, and the state a manual-sync-required
  row is put back to
- `READY_FOR_TRANSFER` - Dry-run validation passed; the run is being handed to the queue
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
- two things set it: the Safety check refusing a sync (`manual_sync_reason` is
  the dry run's reason), and restart recovery finding a batch a restart
  interrupted (`manual_sync_reason` is `DragonCP restarted before this was
  synced`). **Sync anyway** clears the flag on the run's webhooks. Since
  2026-10-05 the same is true of `radarr_webhook`, apart from the dry-run
  columns, which only this table has

**Indexes:**
- `idx_sonarr_webhook_notification_id` on `notification_id` - Fast lookup by notification ID
- `idx_sonarr_webhook_status` on `status` - Filtering by status
- `idx_sonarr_webhook_transfer_id` on `transfer_id` - Lookup by transfer ID
- `idx_sonarr_webhook_sync_run` on `sync_run_id` - The webhooks riding on a run

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
- `notification_id` - Unique identifier for the notification. Not a UUID;
  `movie_<movieId>_<epoch>` for Radarr, `<media_type>_<seriesId>_s<season>_ef<episodeFileId>`
  for Sonarr (falling back to a microsecond timestamp), `rename_<seriesId>_<epoch_ms>`
  for renames
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

**Changed in 2.3.0:** the five `DISCORD_*` keys were removed. Discord became a
connector, and its webhook URL is a row in `connector_target` /
`connector_secret` rather than a settings key. Existing rows are migrated and
deleted automatically by `DatabaseManager._migrate_discord_to_connector`.

**Also changed in 2.3.0:**
- `AUTO_SCANNER_LAST_SCAN_SONARR` and `AUTO_SCANNER_LAST_SCAN_RADARR` are
  written by the auto-scanner (`services/auto_scanner.py`, `LAST_SCAN_KEY`)
  straight to this table, not through the settings registry, so they never
  appear on the Settings page. The value is an ISO-8601 UTC time: the start of
  the last scan of that service whose import history was fully dealt with. The
  next scan asks the service for imports since that moment; with no row, the
  first scan looks back 24 hours. It only moves on after a scan in which the
  service answered, its history was read, nothing was held back by the
  five-per-scan limit and no copy already under way may have missed an import;
  otherwise the next scan reads the same window again
- the three `AUTOSYNC_GATE_*` keys (`AUTOSYNC_GATE_ENABLED`,
  `AUTOSYNC_GATE_POLL_SECONDS`, `AUTOSYNC_GATE_SETTLE_SECONDS`) left the
  registry. Unlike the Discord keys, nothing migrates or deletes them: rows an
  installation already holds stay in the table and nothing reads them. The
  same goes for `AUTOSYNC_SWEEP_LAST_RUN`, which the removed library sweep
  wrote directly

---

## Table: `connector`

**Purpose:** one link to an outside service. Connectors are a *list*, not a
fixed set of keys, which is why they sit outside `settings_registry`.

**Schema:**
```sql
CREATE TABLE connector (
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
```

**Column Descriptions:**
- `connector_id` - stable id matching a registered adapter: `discord`, `sonarr`, `radarr`, `jellyfin`
- `enabled` - off means nothing is sent to or read from it
- `config` - JSON, **non-secret settings only**
- `last_check_*` - what the Test connection button last found

**Model:** `ConnectorStore` in `models/connector.py`. **Added in 2.3.0.**

---

## Table: `connector_secret`

**Purpose:** credentials, in their own table under one rule: **no read path
reaches a response body.** Not redacted, not partially shown — there is nothing
to call. Easier to keep true than remembering which keys inside a config blob
need masking.

**Schema:**
```sql
CREATE TABLE connector_secret (
    connector_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (connector_id, name)
)
```

**Column Descriptions:**
- `name` - either a config field name (`api_key`) or a destination reference (`target:tgt_abc123`)
- `value` - stored unencrypted, the same posture the Discord webhook URL had before this

**Added in 2.3.0.**

---

## Table: `connector_target`

**Purpose:** one destination belonging to a connector — a named Discord webhook.

**Schema:**
```sql
CREATE TABLE connector_target (
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
```

**Column Descriptions:**
- `label` - the operator's own name for it, unique per connector, offered by name in the routing table
- `secret_ref` - key into `connector_secret` holding the actual URL
- `is_default` - exactly one per connector; enforced in `update_target` / `create_target`, not by a constraint
- `enabled` - "out of service": messages routed here are held, **not** redirected

**Added in 2.3.0.**

---

## Table: `notification_route`

**Purpose:** which destination each announcement goes to.

**Schema:**
```sql
CREATE TABLE notification_route (
    event_key TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    target_id TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (event_key, connector_id)
)
```

**Column Descriptions:**
- `event_key` - one of the keys in `services/connectors/events.py`
- `target_id` - **NULL means "use the connector's default"**, which is also what a missing row means. That is the rule that keeps a notification added in a later version from shipping silent.
- `enabled` - off means this announcement is not made at all

Deliberately not a foreign key: deleting a destination sets pointing rows to
NULL rather than removing them, so those notifications fall back to the default
instead of going quiet.

**Added in 2.3.0.**

---

## Table: `connector_delivery`

**Purpose:** what was actually sent and what happened to it — the whole answer
to "why didn't I get told about that", which previously required reading the
server console.

**Schema:**
```sql
CREATE TABLE connector_delivery (
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
```

**Column Descriptions:**
- `skipped_reason` - set when the message was held back deliberately (switched off, destination out of service, no default)
- `error` - set when it was attempted and failed. Already redacted; never contains a credential.

Trimmed to the last 100 rows per connector on every write, so there is no sweep
to schedule and the table cannot grow between sweeps.

**Added in 2.3.0.**

---

## Table: `backup` *(legacy)*

**Purpose:** the previous per-transfer backup records. **No longer written to.**
The backups migration reads them for provenance and nothing else; see
`../features/backups/README.md`. Retained until the migration has run and been
trusted for a while.

---

## Table: `backup_file` *(legacy)*

**Purpose:** files within a legacy backup record. As above: read by the
migration, written by nothing.

The `context_*` columns on this table are why it is superseded. They stored a
series title parsed by splitting the filename at the first `" - "`, so a title
containing one was recorded as only its first word and its own backups became
invisible to it. Identity now comes from the library folder and the episode
code, and is never parsed out of a filename.

---

## Table: `backup_capture`

**Purpose:** one stored version of one slot — a movie or an episode — displaced
at one moment.

**None of the three `backup_capture*` tables is the source of truth.** The tree
under `BACKUP_PATH` is; these are a queryable index over it that can be dropped
and rebuilt by walking the disk (`POST /api/backups/rebuild`). That is
deliberate: the previous shape treated the database as authoritative over a disk
it had largely lost track of, and what it lost track of was unrecoverable.

**Schema:**
```sql
CREATE TABLE backup_capture (
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
    status TEXT NOT NULL DEFAULT 'present',
    restored_at TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

**Column Descriptions:**
- `capture_id` - `<UTC timestamp>__<short source ref>`, and the folder name on
  disk. The timestamp carries **milliseconds**: versions inside a slot are
  ordered by it, and a sync followed immediately by a restore of the same
  episode would otherwise produce two captures that could not be told apart.
  Unique across the **whole tree**, not just within a slot — one transfer that
  displaces two episodes writes two capture folders in two different places and
  each needs its own id. A `__2` suffix is appended when a base id is already
  taken. The rebuild renames any folder it finds sharing a name with another,
  because indexing one over the other would leave the second's files on disk
  and unreachable
- `library` - `movies`, `shows` or `anime`
- `title` - the library folder name, exactly as it appears on disk
- `season_number`, `episode_number` - integers; null for movies
- `release_year` - movies only
- `slot_key` - normalised match key, e.g. `shows|example_show|S01E01`
- `capture_path` - relative to `BACKUP_PATH`
- `captured_at` - explicit UTC, millisecond precision
- `source_transfer_id` - provenance; **null after a rebuild**, because the path
  does not carry it
- `source_ref` - the short reference embedded in `capture_id`
- `reason` - `sync_replace`, `sync_delete`, `restore_swap`, `explore_prune`
- `kind` - `slot` (restorable), `extras` (belongs to a title but no episode),
  `unsorted` (no usable identity)
- `pinned` - retention never removes a pinned version
- `status` - whether the **files** are still on disk, and nothing else:
  `present` or `files_removed`. It briefly also carried `restored`, which made
  a successful restore its own last — the planner refused to read files that
  were still there, and retention skipped the capture forever
- `restored_at` - when this version was last put back into the library, or null.
  Set only on a fully successful restore: a partial one leaves it null, because
  the run has to be repeated. Carried across a rebuild, like `pinned`, since the
  path does not hold it

**Indexes:**
- `idx_backup_capture_slot` on `slot_key`
- `idx_backup_capture_library_title` on `(library, title)`
- `idx_backup_capture_captured_at` on `captured_at`
- `idx_backup_capture_kind` on `kind`
- `idx_backup_capture_transfer` on `source_transfer_id`

**Model:** `BackupCapture` in `models/backup_capture.py`

---

## Table: `backup_capture_file`

**Purpose:** the files inside one capture.

**Schema:**
```sql
CREATE TABLE backup_capture_file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    original_path TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    modified_time INTEGER DEFAULT 0,
    is_media INTEGER NOT NULL DEFAULT 0
)
```

**Column Descriptions:**
- `relative_path` - path within the capture folder
- `original_path` - where it was in the library. Empty after a rebuild; the
  restore target is re-derived from the slot and the live library, which is more
  reliable than a path stored months ago and never revisited
- `is_media` - `1` for video, `0` for a sidecar. A media file only ever replaces
  a media file, so restoring a subtitle can never delete an episode

**Indexes:**
- `idx_backup_capture_file_capture` on `capture_id`

---

## Table: `backup_capture_key`

**Purpose:** which slots a capture belongs to.

**Schema:**
```sql
CREATE TABLE backup_capture_key (
    capture_id TEXT NOT NULL,
    slot_key TEXT NOT NULL,
    PRIMARY KEY (capture_id, slot_key)
)
```

Normally one row per capture. A double episode (`S01E01E02`) has two, so the one
stored copy is reachable from both episodes rather than duplicated or findable
from only the first. Retention reads this too: such a capture is only pruned
once it has fallen out of the keep window in **every** slot it belongs to.

**Indexes:**
- `idx_backup_capture_key_slot` on `slot_key`

---

## Table: `explore_snapshot`

**Purpose:** The cached result of comparing one library's remote and local sides,
so the Explore page paints instantly and can say when it last checked.

**Schema:**
```sql
CREATE TABLE explore_snapshot (
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
```

**Column Descriptions:**
- `media_type` - `movies`, `tvshows` or `anime`
- `scope` - always `library` today; the column exists so a narrower cache can be
  added without a migration
- `payload` - the whole comparison as JSON: every series with its seasons
- `remote_ok` / `local_ok` - whether each side could be read at all
- `error` - why a side failed, when one did
- `created_at` - when the comparison ran; surfaced as "last checked"

One row per `(media_type, scope)`: `save_snapshot` upserts on that unique
constraint rather than accumulating history, so this table never grows.

**Model:** `ExploreStore` in `services/explore/store.py`

---

## Table: `explore_plan`

**Purpose:** An evaluated operation awaiting approval. This table is the
security boundary for destructive work — the client asks for a plan, the server
computes and stores it here, and execution quotes only its id.

**Schema:**
```sql
CREATE TABLE explore_plan (
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
```

**Column Descriptions:**
- `plan_id` - `plan_<16 hex>`, the only handle the client ever holds
- `operation` - `sync_series`, `sync_seasons`, `sync_season`, `download`, `replace`
- `season_label` - the season the plan is scoped to; NULL for series-wide and
  multi-season plans
- `payload` - JSON holding both the reviewable plan and the frozen execution
  spec, so the run cannot drift from what was approved
- `safe` - whether every safety check passed; a `0` needs an explicit override
  and a typed confirmation to execute
- `consumed` - set to 1 by `take_plan` inside the same transaction that reads
  the row, which is what makes a plan single-use
- `created_by` - the authenticated user who asked for it
- `expires_at` - 15 minutes after creation (`PLAN_TTL_MINUTES`)

`peek_plan` reads a row **without** consuming it — used only by the dry run, so
rehearsing an operation does not spend it. Expired rows are deleted on the next
`save_plan`.

**Indexes:**
- `idx_explore_plan_expiry` on `expires_at` - purging expired plans

**Model:** `ExploreStore` in `services/explore/store.py`

---

## Table: `transfer_file`

**Purpose:** What one run did, file by file. Backs the per-series and per-season
history that Explore shows.

**Schema:**
```sql
CREATE TABLE transfer_file (
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
```

**Column Descriptions:**
- `transfer_id` - the run these records belong to
- `action` - `fetch` (copied in), `supersede` (local copy backed up, then
  replaced) or `remove` (local copy backed up, nothing replaced it)
- `rel_path` - path relative to the run's source or destination root
- `code` - the episode identity, e.g. `S05E06`; NULL for files with no episode
- `season_label` - which season the file belongs to, for grouping a series run
- `backup_path` - where the displaced local copy was moved, for `supersede` and
  `remove`

**Indexes:**
- `idx_transfer_file_transfer` on `transfer_id` - fetching a run's records

**Model:** `ExploreStore` in `services/explore/store.py`

Distinct from `backup_file`: this records what a run *did*, keyed by transfer;
`backup_file` indexes what is *on disk* in a backup directory, keyed by backup.

---

## Table: `admin_account`

**Purpose:** Who is allowed to sign in to the web interface. Created and
maintained from the server with `scripts/manage_admins.py`; there is no
account-management UI.

**Schema:**
```sql
CREATE TABLE admin_account (
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
```

**Column Descriptions:**
- `id` - the stable identity. Usernames can be renamed, so anything recording
  who did something stores this alongside the name shown at the time
- `username` - `COLLATE NOCASE`, so `Alice` and `alice` are the same account and
  cannot both exist. Three to thirty-two characters, must start with a letter,
  and may not start with `auto` or `system` (those prefixes are reserved for
  automated actors, see `actor.py`)
- `password_hash` - `pbkdf2:sha256` via `werkzeug.security`
- `role` - reserved. Everyone is `'admin'` and nothing reads it; it exists so a
  narrower role can arrive later without migrating every account
- `is_active` - `0` disables sign-in without removing the row
- `token_version` - carried in every sign-in token and compared on every
  request. Incrementing it retires all tokens already issued for the account.
  Bumped by disable, password change and rename
- `must_change_password` - set when the password was chosen by whoever ran the
  script rather than by the person using it. The application holds them at a
  password screen until they replace it
- `last_login_at` - stamped on each successful sign-in

**Indexes:**
- `idx_admin_account_active` on `is_active` - counting who can sign in, which
  decides whether the environment-file fallback applies

**Model:** `AdminAccount` in `models/admin_account.py`

**Rows are never deleted.** The activity trail refers back to them, so a
departed administrator is disabled and keeps their history. `rename` preserves
`id` for the same reason — deleting and recreating would orphan the record.

While no row has `is_active = 1`, sign-in falls back to `DRAGONCP_USERNAME` /
`DRAGONCP_PASSWORD` from the environment file. See
`../operations/admin-accounts.md`.

---

## Table: `activity`

**Purpose:** Who did what, and when. Written for every consequential action;
reads are deliberately not recorded.

**Schema:**
```sql
CREATE TABLE activity (
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
```

**Column Descriptions:**
- `actor_kind` - `admin` (a person), `automated` (a named background process),
  or `system` (nobody could be identified — which is a statement, not a blank)
- `actor_name` - the name as it read at the time. A rename does not rewrite it
- `actor_account_id` - the stable identity that survives a rename; NULL for
  automation
- `action` - from the closed vocabulary in `models/activity.py:ACTIONS`, e.g.
  `backup.restore`. A test asserts every action used in the codebase is declared
- `target_type` / `target_id` - what was acted on: `transfer`,
  `backup_capture`, `notification`, `setting`, `account`, `connection`,
  `simulation`, `explore_plan`, `explore_repair`, `connector`, and from the
  sync engine `sync_run` (Go now, Cancel, Sync anyway, a scanner-started sync),
  `alert` (acting on an alert) and `job` (Run now on a scheduled job). A scan
  itself is recorded against `connector`, with the service as `target_id`
- `target_label` - how that thing was named at the time. The only place the name
  survives once the thing itself is deleted
- `summary` - a finished sentence written at the call site, because the code
  doing the work is the only place that knows what it did
- `detail` - JSON extras, e.g. counts and bytes reclaimed
- `outcome` - `ok`, `failed`, or `refused`
- `request_ip` - honours one proxy hop via `X-Forwarded-For`

**Indexes:**
- `idx_activity_occurred` on `occurred_at DESC` - the default listing order
- `idx_activity_actor` on `actor_account_id` - "everything this person did"
- `idx_activity_action` on `action` - filtering by action and by family
- `idx_activity_target` on `(target_type, target_id)` - one thing's story

**Model:** `Activity` in `models/activity.py`

Nothing in the application edits or deletes an entry. An audit record alterable
from the console it audits is not worth keeping.

**Related ownership columns**, added post-v2 via `_ensure_column`:
- `transfers.started_by_kind` / `started_by_name` / `started_by_account_id` -
  who started a run, stamped at the single choke point every path funnels
  through (`Transfer.create`)
- `backup_capture.restored_by_kind` / `restored_by_name` /
  `restored_by_account_id` - who put a version back

Both are NULL on rows that predate attribution. Those read as "not recorded" in
the UI — unknown rather than nobody. Nothing was backfilled, because inventing
an owner for a past action is what an audit trail exists to prevent.

---

## Table: `sync_run`

**Purpose:** One pass through the sync pipeline: a batch of webhooks for one
folder, a press of Sync, an Explore plan, a restart, a restore, a simulation, or
something the auto-scanner found. Written as it changes, never reconstructed
afterwards, so a restart can see what was in flight. A request that names
nothing syncable is still recorded, as a `failed` run stopped at `identify`.

**Schema:**
```sql
CREATE TABLE sync_run (
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
```

**Column Descriptions:**
- `run_id` - `run_<12 hex>`, the handle the API, the alerts and the webhook and
  transfer rows use
- `kind` - what started it: `sonarr_webhook`, `radarr_webhook`,
  `auto_scanner`, `manual`, `explore`, `restart`, `restore`, `simulation`. What
  each kind does at each stage is `KINDS` in `services/sync_engine/stages.py`
- `source` - `sonarr` or `radarr` when a service is behind the request (a
  webhook, an auto-scanner find, Sync pressed on webhooks or on a Library tab
  title). NULL for a sync started from the media browser, Explore, a restore or
  a simulation; a restart keeps the value of the run it retries
- `media_type` - `tvshows`, `anime` or `movies`; a restore whose library cannot
  be named records `backup`
- `unit_key` - the destination folder in one comparable form (absolute,
  normalised, no trailing slash; `units.unit_key`). It identifies the work: a
  request for a folder joins the open batch with the same key, and the engine's
  per-folder lock is taken on it
- `mergeable` - 1 when later requests for the same folder may join this run; 0
  for Explore, restore and simulation runs, which always stand alone. Only
  mergeable runs are found as an open batch
- `title`, `season_number`, `season_name`, `folder_name` - what the run is
  about, as a person names it ("Example Show — Season 01")
- `source_path`, `dest_path` - the remote and local folders
- `operation_type` - handed to the transfer: `folder` by default, `file` for a
  single-file manual sync (which skips the safety check's dry run),
  `explore_<mode>` for Explore, `restore` for a restore
- `state` - where the run is. **Open**, so a new request for the folder joins
  it: `held` (automatic sync is off; waits for a person), `waiting` (in the
  ready check), `checking` (the safety dry run), `queued`. **Active**, so a new
  request goes to a follow-up batch instead: `transferring`, `paused`,
  `finishing`. **Finished**: `completed`, `failed`, `cancelled`, `refused` (the
  safety check stopped it for a person) and `interrupted` (a restart stopped it;
  an alert asks what to do)
- `current_stage` - one of `receive`, `identify`, `batch`, `ready`, `safety`,
  `queue`, `transfer`, `finish`, `tell`
- `outcome` - NULL while the run is live; then `completed`, `failed`,
  `cancelled`, `refused` or `interrupted`. Sync anyway clears it again
- `outcome_message` - the sentence behind the outcome, e.g. the transfer's last
  progress line or the dry run's reason. A failed run whose message starts with
  `Result unknown` (a restart lost how the copy ended) is reported by its own
  alert rather than as a failure
- `transfer_id` - the transfer the run became. Set when the run is handed to
  the queue; Explore, restores, simulations and restarts supply it up front
- `parent_run_id` / `parent_relation` - the run this one follows: `follow_up`
  (opened behind a copy of the same folder, or holding webhooks that joined that
  copy too late) or `retry` (a restart of that run's transfer)
- `requested_by_kind` / `requested_by_name` / `requested_by_account_id` - who
  asked, in the same vocabulary as the `activity` actor columns (`admin`,
  `automated` with a name such as `auto-scanner`, or `system`). Rewritten to the
  admin who presses Go now on a held batch, or Sync anyway. The engine does the
  run's later work as this actor, which is how the transfer it creates is
  attributed
- `is_simulation` - 1 for simulation runs, and for a restart of a simulated
  transfer, which takes it from the transfer row. The engine skips the safety
  check and Tell for any run carrying it, whatever its kind. The simulation
  cleanup deletes these runs with their stages and log lines
- `ready_mode` - how the ready check decides: NULL before its first look, `ask`
  (asking Sonarr) or `timer` (the fallback timer)
- `next_check_at` - epoch seconds when the ready check's next step is due. The
  engine's loop picks up `waiting` runs whose time has come
  (`SyncRunStore.due`); cleared when the ready check passes
- `timer_due_at` - epoch seconds when the fallback timer ends:
  `SERIES_ANIME_SYNC_WAIT_TIME` after the batch opened, plus the same again for
  every webhook that joins, never past 15 minutes after it opened. Kept on the
  row and re-read at every step, so an extension cannot be lost
- `ready_deadline_at` - epoch seconds 30 minutes after the batch opened: the
  longest the ready check waits on Sonarr. The engine also derives the opening
  time from it
- `checks_made` - how many times Sonarr has been asked
- `go_now` - 1 once an admin asks the batch to go now — Go now, Sync on one of
  its webhooks, or a restart joining it, while the run is `held` or `waiting`;
  the ready check passes on its next step. A `sonarr_webhook`, `radarr_webhook`
  or `auto_scanner` run with it set counts as started by a person: it is
  announced as "Manual Sync", and a safety-check refusal of it is not announced
  on Discord
- `force_safety` - 1 when an admin chose to go ahead even if the dry run fails
  (a manual sync asked for it, or Sync anyway). Automatic syncs never set it
- `options` - JSON of kind-specific facts: the title's ids (`tvdb_id`,
  `tmdb_id`, `series_id`, `imdb_id`; the ready check asks Sonarr by `tvdb_id`),
  Explore's plan and transfer columns (`extra_fields`), `safety_summary`,
  `simulation_bwlimit`, the scanner's `finding` and `reasons`, a restore's
  `capture_id`, what the queue answered (`queue_state`), and when rsync last
  started (`transfer_started_at`)
- `created_at`, `updated_at` - ISO-8601 UTC
- `started_at` - when the copy first started; a resumed copy keeps the first time
- `finished_at` - when the run reached a finished state

**Indexes:**
- `idx_sync_run_state` on `state`
- `idx_sync_run_unit` on `(unit_key, state)` - the open or active batch for a folder
- `idx_sync_run_transfer` on `transfer_id` - from a transfer to its run
- `idx_sync_run_created` on `created_at DESC`
- `idx_sync_run_due` on `(state, next_check_at)` - ready checks that are due

**Model:** `SyncRunStore` in `models/sync_run.py`

Nothing prunes real runs: each sync adds one row here, nine to
`sync_run_stage` and up to 2,000 to `sync_run_event`. Only simulation runs are
ever deleted (`SyncRunStore.delete_simulation_runs`).

**Added in 2.3.0.**

---

## Table: `sync_run_stage`

**Purpose:** Where each of a run's nine stages got to, and a sentence saying
why — including, always, why a stage was skipped. The sentence is what the
interface shows under the stage.

**Schema:**
```sql
CREATE TABLE sync_run_stage (
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
```

**Column Descriptions:**
- `run_id`, `stage` - the key. All nine rows are inserted, `pending`, in the
  same transaction as the run
- `status` - `pending` (not reached), `running`, `waiting` (paused on purpose:
  a timer, Sonarr, the queue or a person), `passed`, `skipped`, `failed`, or
  `refused` (stopped on purpose, for a person to decide)
- `summary` - the one-line sentence. An update that brings no new sentence
  keeps the previous one
- `detail` - JSON, e.g. the dry run's counts and first 50 file names, Sonarr's
  answer, or the folders Identify settled on. Same keep-the-previous rule
- `started_at` - the first time the stage left `pending`; kept through later
  updates
- `finished_at` - set when the status becomes `passed`, `skipped`, `failed` or
  `refused`, NULL while `running` or `waiting`. Sync anyway puts Queue,
  Transfer, Finish and Tell back to `pending` and clears it

**Model:** `SyncRunStore` in `models/sync_run.py`. **Added in 2.3.0.**

---

## Table: `sync_run_event`

**Purpose:** The log, one line per row, each tagged with the stage it belongs
to. That tag is what lets a sync's page under Pipeline show each stage's own
output.

**Schema:**
```sql
CREATE TABLE sync_run_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    data TEXT,
    created_at TEXT NOT NULL
)
```

**Column Descriptions:**
- `id` - also the read cursor: `GET /api/sync/runs/<run_id>/events?after=<id>`
  returns only newer lines
- `stage` - one of the nine stage ids
- `level` - `info` (the default), `success`, `warning` or `error`. A stage's
  own sentence is logged as `error` when the stage failed, `warning` when it
  refused and `success` when it passed, unless the engine names a level
- `message` - the line
- `data` - optional JSON
- `created_at` - ISO-8601 UTC

Capped at 2,000 lines per run (`MAX_EVENTS_PER_RUN`): writing one more deletes
the oldest, because the end of a run's story is the part a person opens it
for. Every new line is also broadcast as the `sync_run_event` socket event; see
[`realtime.md`](realtime.md).

**Indexes:**
- `idx_sync_event_run` on `(run_id, id)` - a run's lines, in order

**Model:** `SyncRunStore` in `models/sync_run.py`. **Added in 2.3.0.**

---

## Table: `alert`

**Purpose:** The Notifications page: everything that needs a person. Opened by
the sync engine, the auto-scanner and the scheduler; closed by an admin acting
on it, or by DragonCP itself for the two kinds that clear on their own.

**Schema:**
```sql
CREATE TABLE alert (
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
```

**Column Descriptions:**
- `alert_id` - `alert_<12 hex>`
- `kind` - `restart_unfinished`, `transfer_unknown`, `stuck_download`,
  `ready_timeout`, `sync_refused`, `transfer_failed`, `scanner_gap`,
  `integration_down`, `job_failing`. Labels and wording are in
  `services/alert_service.py` (`KINDS` and one method per kind)
- `severity` - `warning`, or `failure` for a failed transfer. `info` is defined
  but no kind uses it
- `title`, `message` - what the Notifications page shows. A `transfer_failed`
  alert for a restore is titled "Restore failed: …", its message ends "Run it
  again from the Backups page.", and its `actions` are `["dismiss"]`
- `state` - `open`, then `done`, `wrong` (Mark as wrong) or `dismissed`
- `dedupe_key` - one open alert per subject, e.g. `restart:<unit_key>`,
  `failed:<transfer_id>`, `integration_down:sonarr`, `job:<job name>`. Raising
  an alert whose key already has an open one bumps that one instead of opening
  a second. For the three kinds that watch a condition — `scanner_gap`,
  `integration_down`, `job_failing` — a row with the same key that a person
  closed as `dismissed` or `wrong` within the last 24 hours (`resolved_at`)
  stops a new one opening at all (`AlertStore.closed_by_a_person_since`;
  2026-10-05)
- `run_id`, `transfer_id`, `unit_key` - what it is about. A bump replaces the
  message (and the data, when the new occurrence carries any) and can move
  `run_id` on to the newer run
- `link` - where the interface sends you: `/transfers?sync=<run_id>` (the sync
  panel on Transfers; `/pipeline/<run_id>` before 2026-10-06, still redirected)
  when the alert names a run, `/integrations/<service>` for an integration that stopped
  answering, otherwise NULL
- `actions` - JSON list of what may be done: `sync_now`, `retry`,
  `sync_anyway`, `run_now`, `mark_done`, `mark_wrong`, `dismiss`. Dismiss is
  accepted on every alert, listed or not
- `data` - JSON the actions need: the notification ids Sync now syncs, the
  folders of a scanner gap, the transfer to retry, the job to run, the dry-run
  counts
- `occurrences` - 1, plus one for every bump
- `resolved_at`, `resolved_action` - when and how it closed; `auto` when
  DragonCP closed it itself (Sonarr answered again, a failing job succeeded)
- `resolved_by_kind` / `resolved_by_name` / `resolved_by_account_id` - who
  closed it; the system actor for `auto`. An admin's action is also written to
  the activity trail as `alert.resolve`

**Indexes:**
- `idx_alert_state` on `(state, created_at DESC)` - the tab's listing
- `idx_alert_dedupe` on `(dedupe_key, state)` - the open alert for a subject

**Model:** `AlertStore` in `models/alert.py`; raised and acted on through
`AlertService` in `services/alert_service.py`. Nothing deletes an alert.

**Added in 2.3.0.**

---

## Table: `scheduled_job`

**Purpose:** The scheduler's memory: one row per background job, saying when
it last ran, whether it worked and what it said, so the interface can show a
job's state after a restart and a job failing again and again is noticed.

**Schema:**
```sql
CREATE TABLE scheduled_job (
    name TEXT PRIMARY KEY,
    last_run_at TEXT,
    last_finished_at TEXT,
    last_ok INTEGER,
    last_result TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
)
```

**Column Descriptions:**
- `name` - the job. Two today: `sonarr_auto_scanner` and `radarr_auto_scanner`
- `last_run_at`, `last_finished_at` - ISO-8601 UTC
- `last_ok` - 1 or 0; NULL before the first run
- `last_result` - JSON: what the job returned (a `summary` sentence and, for
  the auto-scanner, its counts and every decision). The traceback the
  scheduler keeps in memory for a failure is left out
- `consecutive_failures` - reset by a success. At three
  (`FAILURES_BEFORE_ALERT`) a *Scheduler* alert opens; the next success closes it

Upserted after every run. Whether a job is running, and when it runs next, are
**not** stored: after a restart the next run is worked out from `last_run_at`
and the job's interval, and is never sooner than the job's first-run delay (60
seconds for the auto-scanners) after start-up.

**Model:** none; `SchedulerService` in `services/scheduler.py` reads and writes
it. **Added in 2.3.0.**

---

## Table: `media_item`

**Purpose:** The title index: one row per title a service holds, keyed by the
identifier the service will not change — `tvdbId` for Sonarr, `tmdbId` for
Radarr — and the one place that records which local folder a title lives in.
Every other link between tables used to be a title string, and a folder name
cannot be turned back into the title it came from. The reasoning, with the
measurements behind it, is the docstring of `models/media_item.py`.

**Schema:**
```sql
CREATE TABLE media_item (
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
```

**Column Descriptions:**
- `source` - `sonarr` or `radarr`
- `external_id` - the durable id (`tvdbId` / `tmdbId`), stored as text
- `service_item_id`, `service_item_id_seen_at` - the service's own row id
  (`seriesId` / `movieId`) and when it was last confirmed. A cache, never
  joined on: a title removed and re-added comes back with a new one, so it is
  re-resolved from `external_id` when the service answers 404
  (`forget_service_item_id`)
- `title`, `year`, `title_slug`, `imdb_id`, `media_type` - as the service or a
  webhook last reported them
- `local_folder` - the folder this title lives in here. Learned, never guessed:
  from what a transfer actually used (`MediaIndex.note_transfer`) or from
  matching the service's titles against the folders on disk
- `present_in_service`, `last_seen_in_service_at` - 0 once a full read of the
  service no longer lists the title (`mark_absent_from_service`); the row is
  kept, because files synced from it may still be on the disk

**Written by:** `services/media_index.py` — from every Sonarr and Radarr
webhook (`TransferCoordinator.index_notification`) and from each read of a
service's library (the Library tabs, the auto-scanner).

**Model:** `MediaItemStore` in `models/media_item.py`.

---

## Table: `media_item_season`

**Purpose:** How much of each season the service holds, with the time that was
true, so a reader can see how old the answer is.

**Schema:**
```sql
CREATE TABLE media_item_season (
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
```

**Not written today.** The only writer, `MediaIndex.refresh_season_counts`,
has no caller, so the table stays empty. The Library tabs take their season
counts from the service's live answer instead.

---

## Links to the title index

- `transfers.media_item_id` - the title a transfer copied. Set by the sync
  engine since 2026-10-05 when the sync carries the title's TVDB or TMDB id
  (`SyncEngine._link_title` → `MediaIndex.note_transfer`): webhook and
  auto-scanner syncs, and manual syncs that name a title. Transfers from
  before, and syncs started from a bare path, are not linked. The Library
  tabs read it for "last synced".
- `backup_capture.media_item_id` - declared, never written.

Both are plain nullable integers rather than declared foreign keys, like every
other relationship in this database.

**Indexes:** `idx_media_item_folder` on `media_item(local_folder)`,
`idx_media_item_service` on `media_item(source, service_item_id)`,
`idx_media_item_type` on `media_item(media_type)`,
`idx_media_item_season_item` on `media_item_season(media_item_id)`,
`idx_transfers_media_item` on `transfers(media_item_id)`,
`idx_backup_capture_media_item` on `backup_capture(media_item_id)`.

---

## Table: `sweep_finding`

**Purpose:** One row per gap a service has that this disk does not, keyed by
what it is about rather than when it was seen, so the same gap seen again
updates a row instead of adding one. Created for the library sweep that 2.3.0
replaced; the auto-scanner reuses it as its memory of **how many times it has
tried to close each gap**.

**Schema:**
```sql
CREATE TABLE sweep_finding (
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
```

**Column Descriptions** (as the auto-scanner uses them):
- `source` - `sonarr` or `radarr`
- `external_id`, `season_number` - the title's id at the service and the
  season; `season_number` is NULL for a movie and is matched with `IS`
- `title`, `detail` - the title and the scanner's reasons, refreshed every time
  the gap is seen
- `finding` - `scanner` on rows the scanner created; rows left by the sweep
  keep the sweep's own value
- `first_seen_at`, `last_seen_at` - when the gap was first and last seen
- `sync_attempts` - syncs the scanner has started for this gap. At two
  (`MAX_ATTEMPTS`) it stops starting them and opens an *Auto-scanner* alert
  instead
- `sync_started_at` - when the scanner last started one
- `last_transfer_id` - despite the name, the scanner stores the **sync run id**
  (`run_…`) it started here, not a transfer id
- `resolved_at` - set when a scan of that service no longer finds the gap.
  Seeing it again clears it and resets `sync_attempts` to 0
- `notified_at` - the sweep's reminder stamp; the scanner never writes it

**Indexes:**
- `idx_sweep_finding_open` on `(source, resolved_at)` - the open gaps for a service

**Model:** none; `services/auto_scanner.py` (`_remember`, `_stamp`,
`_resolve_absent`) reads and writes it directly.

---

## Database Indexes Summary

### Performance Indexes
All indexes are created with `CREATE INDEX IF NOT EXISTS` to allow safe re-execution.

**Transfer Indexes:**
- `idx_transfer_id` on `transfers(transfer_id)` - Primary lookup index
- `idx_status` on `transfers(status)` - Status filtering
- `idx_created_at` on `transfers(created_at)` - Time-based queries
- `idx_dest_status` on `transfers(dest_path, status)` - Duplicate detection
- `idx_transfers_sync_run` on `transfers(sync_run_id)` - Sync run linking

**Radarr Webhook Indexes:**
- `idx_radarr_webhook_notification_id` on `radarr_webhook(notification_id)` - Primary lookup
- `idx_radarr_webhook_status` on `radarr_webhook(status)` - Status filtering
- `idx_radarr_webhook_created_at` on `radarr_webhook(created_at)` - Time-based queries
- `idx_radarr_webhook_transfer_id` on `radarr_webhook(transfer_id)` - Transfer linking
- `idx_radarr_webhook_sync_run` on `radarr_webhook(sync_run_id)` - Sync run linking

**Sonarr Webhook Indexes:**
- `idx_sonarr_webhook_notification_id` on `sonarr_webhook(notification_id)` - Primary lookup
- `idx_sonarr_webhook_status` on `sonarr_webhook(status)` - Status filtering
- `idx_sonarr_webhook_transfer_id` on `sonarr_webhook(transfer_id)` - Transfer linking
- `idx_sonarr_webhook_sync_run` on `sonarr_webhook(sync_run_id)` - Sync run linking

**Sync Engine Indexes:**
- `idx_sync_run_state` on `sync_run(state)` - Listing by state
- `idx_sync_run_unit` on `sync_run(unit_key, state)` - The open or active batch for a folder
- `idx_sync_run_transfer` on `sync_run(transfer_id)` - From a transfer to its run
- `idx_sync_run_created` on `sync_run(created_at DESC)` - Newest first
- `idx_sync_run_due` on `sync_run(state, next_check_at)` - Ready checks that are due
- `idx_sync_event_run` on `sync_run_event(run_id, id)` - A run's log lines, in order

**Alert Indexes:**
- `idx_alert_state` on `alert(state, created_at DESC)` - The Notifications listing
- `idx_alert_dedupe` on `alert(dedupe_key, state)` - The open alert for a subject

**Auto-scanner Indexes:**
- `idx_sweep_finding_open` on `sweep_finding(source, resolved_at)` - Open gaps per service

**Rename Webhook Indexes:**
- `idx_rename_webhook_notification_id` on `rename_webhook(notification_id)` - Primary lookup
- `idx_rename_webhook_status` on `rename_webhook(status)` - Status filtering
- `idx_rename_webhook_created_at` on `rename_webhook(created_at)` - Time-based queries

**Connector Indexes:**
- `idx_connector_target_owner` on `connector_target(connector_id)` - Destination lookup
- `idx_connector_delivery_recent` on `connector_delivery(connector_id, id DESC)` - Recent-first history

**Backup Indexes:**
- `idx_backup_transfer_id` on `backup(transfer_id)` - Transfer linking
- `idx_backup_file_backup_id` on `backup_file(backup_id)` - File lookup by backup
- `idx_backup_file_context_key` on `backup_file(context_key)` - Context-aware restore queries

---

## Legacy/Migration Notes

Older v1-to-v2 migration guidance, including destructive migration assumptions, has been moved out of this live schema reference.

See `../archive/v1-to-v2-migration-notes.md` for legacy migration context.

---

## Related Documentation

- **Legacy migration notes:** `../archive/v1-to-v2-migration-notes.md`
- **Database Manager:** `models/database.py`
- **Transfer Model:** `models/transfer.py`
- **Backup Model:** `models/backup.py`
- **Webhook Models:** `models/webhook.py`
- **Settings Model:** `models/settings.py`
- **Sync Run Store:** `models/sync_run.py`
- **Alert Store:** `models/alert.py`
- **Scheduler:** `services/scheduler.py` (owns `scheduled_job`)
- **Sync engine, auto-scanner, scheduler and alerts:** `../features/sync-engine/README.md`
- **Migration Script:** `scripts/migrate_v1_to_v2.py`
