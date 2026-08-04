# DragonCP Database Schema v2 Documentation

Last updated: 2026-08-01

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
    raw_webhook_data TEXT
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

**No changes from v1.**

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
  `simulation`, `explore_plan`
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

See `../archive/v1-to-v2-migration-notes.md` for legacy migration context.

---

## Related Documentation

- **Legacy migration notes:** `../archive/v1-to-v2-migration-notes.md`
- **Database Manager:** `models/database.py`
- **Transfer Model:** `models/transfer.py`
- **Backup Model:** `models/backup.py`
- **Webhook Models:** `models/webhook.py`
- **Settings Model:** `models/settings.py`
- **Migration Script:** `scripts/migrate_v1_to_v2.py`
