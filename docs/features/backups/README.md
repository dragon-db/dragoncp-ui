# Backups and Restore

Every sync writes into a real media library, and a sync can overwrite an existing file or delete one that is no longer on the server. Before it does either, the copy that was already on disk is moved aside into a per-transfer backup folder. Once the transfer ends, DragonCP indexes that folder so the old files are listed in the UI with a title, season and episode next to them, and can be put back later - either the whole set or a few files - after previewing exactly which destination files the restore would replace.

Last updated: 2026-07-28
Primary files: `services/backup_service.py`, `models/backup.py`, `routes/backups.py`, `services/transfer_service.py`, `services/transfer_coordinator.py`

## Where it lives

| Concern | File |
| --- | --- |
| Backup capture during a sync (rsync flags) | `services/transfer_service.py` (`start_rsync_process`) |
| Backup folder naming, indexing, restore, delete, reindex | `services/backup_service.py` |
| Backup folder wiring into every transfer start/resume/restart | `services/transfer_coordinator.py` |
| Database reads and writes for `backup` / `backup_file` | `models/backup.py` |
| Table definitions and indexes | `models/database.py` |
| HTTP endpoints | `routes/backups.py` |
| Path-boundary and traversal checks | `security.py` |
| UI page and data hooks | `frontend/src/components/pages/backups.tsx`, `frontend/src/hooks/useBackups.ts` |

## How it works

### 1. Every sync gets its own backup folder

`TransferCoordinator` asks `BackupService._get_dynamic_backup_dir(transfer)` for a folder before it starts rsync. It does this in all four places a transfer can begin - `start_transfer`, `resume_transfer`, `restart_transfer` and `start_queued_transfer` - so a resumed run keeps writing into the same folder as its first attempt.

The folder is `<BACKUP_PATH>/<safe_folder>_<transfer_id>`, where `safe_folder` comes from `_safe_name(folder_name)`: everything outside `A-Za-z0-9._-` becomes an underscore. `BACKUP_PATH` falls back to `/tmp/backup` if it is not configured.

### 2. rsync moves the old copies there

`TransferService.start_rsync_process` creates the folder and a `.rsync-partial` subfolder inside it, then runs rsync with, among others:

```
--delete --backup --backup-dir <backup_dir> --update --size-only
--partial --partial-dir <backup_dir>/.rsync-partial
```

`--backup` plus `--backup-dir` is what does the work: instead of being overwritten in place or removed by `--delete`, the file that was already at the destination is moved into the backup folder, keeping the same path relative to the destination root. So a file at `<dest>/Season 01/ep.mkv` lands at `<backup_dir>/Season 01/ep.mkv`.

Because the sync uses `--size-only`, "would overwrite" means "the server copy is a different size", not "different content".

### 3. The record is finalized after the transfer ends

`TransferCoordinator._post_transfer_completion` polls the transfer row every 5 seconds. When the status leaves `running`/`pending` it releases the queue slot, updates webhook state, sends the Discord notification, and then calls `BackupService.finalize_backup_for_transfer(transfer_id)`. A `paused` transfer breaks out of that loop early and deliberately does **not** finalize - the run is expected to continue, and the resumed run's own watcher finalizes it at the real end.

`finalize_backup_for_transfer` walks the backup folder and, for each file, records its size, mtime, path relative to the backup folder, and the destination path it originally came from (`transfer.dest_path` + relative path). It also runs `_detect_context_from_filename` to work out what the file *is* (see below). If the walk finds zero files - the normal case, when nothing was overwritten or deleted - it returns without creating anything, so clean syncs do not litter the backups list.

Otherwise it calls `Backup.create_or_replace_backup` with `backup_id` set to the transfer ID, deletes any existing `backup_file` rows for that ID, and inserts the new ones. Replacing rather than appending is what makes a restart or resume safe: the record always describes what is on disk right now, and `create_or_replace_backup` clears `restored_at` back to NULL on replace.

### 4. Context detection

`_detect_context_from_filename` parses the filename, using the transfer's media type to decide which shape to expect:

- `movies`: `Title (YYYY)` from the start of the name. If that fails it falls back to the transfer's folder name for the title and any `(YYYY)` found anywhere in the name.
- everything else (series, anime): the text before the first ` - ` is taken as the series title, `SxxExx` is matched case-insensitively anywhere in the name, and a bare three-digit token between ` - ` separators is taken as an anime absolute episode number.

It produces a `context_display` string for the UI (`Title (2019)`, `Series - S01E04 - 123`) and a normalized `context_key` (`movie|the_title|Y2019`, `anime|series_title|S01E04|A123`). Any parse error falls back to a context built from the folder name alone rather than failing the indexing.

### 5. Planning a restore

`plan_context_restore(backup_id, files)` is the read-only half of restore and backs both the preview endpoint and the restore itself - the restore calls the same function, so what you approve is what runs.

For each backup file row (filtered to the selected relative paths if any were given) it produces one operation:

- `backup_relative` / `backup_full` - where the saved copy is
- `copy_to` - the file's recorded `original_path`, falling back to `dest_path` + relative path
- `target_delete` - the destination file that will be removed first, from `_find_dest_match_for_context`
- `context_display`

`_find_dest_match_for_context` walks the destination directory looking for a file that matches the recorded context. It exists because the file being restored may no longer be at the path it was taken from - the media manager may have renamed or re-encoded it since. The rules:

- Any candidate whose path equals `copy_to` is skipped, so the plan never proposes deleting the file it is about to write.
- Extension grouping is enforced: if the backed-up file is a video (`.mkv .mp4 .avi .mov .wmv .webm .m4v`) the candidate must also be a video; if it is ancillary (`.nfo .srt .ass .sub .idx .txt`) the candidate must be ancillary too. A subtitle can therefore never displace a video.
- For movies, the candidate name must contain `title (year)` lowercased.
- Otherwise the candidate must contain `sXXeYY`, or ` NNN ` for an anime absolute number. The series title is checked but not required - a match on `SxxExx` alone is accepted.
- If several candidates match, they are sorted by fewest path separators then shortest basename, and the first is used.

If nothing matches, `target_delete` is `None` and the restore just copies the file back to `copy_to`.

### 6. Running the restore

`restore_backup(backup_id, files)`:

1. Re-validates the file list (see the security notes below), loads the record, and refuses outright if `BACKUP_PATH` is unset, if `backup_path` resolves outside `BACKUP_PATH`, if no `*_DEST_PATH` is configured, if `dest_path` is empty, or if `dest_path` resolves outside the configured movie/tvshow/anime destinations. These are fail-closed checks - a missing configuration blocks the restore rather than widening it.
2. Creates the destination directory if it is missing.
3. Builds the plan. No operations means the restore stops with `No matching files to restore for the selected items`.
4. Creates a synthetic transfer row with ID `restore_<backup_id>_<epoch>` and `operation_type='restore'`, so the restore shows up in the transfers UI with its own log, and emits a `transfer_progress` socket event listing up to 100 planned operations.
5. Deletes each `target_delete` that still exists, logging `Deleted: <path>` with the context on the next line, and counting successes. A failed delete is logged as an error and the restore continues.
6. Writes the selected relative paths to a temporary file and runs `rsync -av --progress --size-only --no-perms --no-owner --no-group --no-motd -r --files-from=<tmp> <backup_path>/ <dest_path>/` synchronously, then removes the temp file.
7. On exit code 0 the synthetic transfer is marked `completed`, a `transfer_complete` event is emitted, and the backup row moves to `status='restored'` with `restored_at` set. On any other exit code both are marked failed and the message carries rsync's stderr (or stdout).

### 7. Deleting

`routes/backups.py` sends every delete through `delete_backup_options(backup_id, delete_record, delete_files)`, which treats the two as independent:

- `delete_files` removes the backup directory with `shutil.rmtree`. A failure here aborts before anything else changes.
- `delete_record` deletes the `backup_file` rows and then the `backup` row outright.
- If only the files are deleted, the record stays and its status becomes `files_removed`. If neither flag is set the call succeeds with `No changes`.

`BackupService.delete_backup` is the older single-flag variant: it removes the files, deletes the `backup_file` rows and sets the record's status to `deleted` rather than removing it. It is still reachable via `TransferCoordinator.delete_backup` but no route calls it.

### 8. Reindexing folders found on disk

`reindex_backups()` exists for backup folders that have no database record - left behind by an older install, a database reset, or a transfer whose finalization never ran.

It lists the immediate children of `BACKUP_PATH` and, for each directory, splits the name at the **last** underscore into a folder part and a suffix. If the suffix already starts with `transfer_` it is used as-is; otherwise the suffix is assumed to be the timestamp tail of a transfer ID and `transfer_<suffix>` is reconstructed. This is why the split is at the last underscore: a real folder is `The_Matrix_transfer_1732000000`, and taking the tail gives back `transfer_1732000000`.

It then looks up that transfer. If found, media type, folder name, season, source and destination are taken from it. If not, the import is best-effort: `dest_path` becomes an empty string and the folder name is derived from the directory name with underscores turned back into spaces.

The directory is walked exactly as finalization walks it, `created_at` is taken from the directory's mtime (converted to UTC), and the record is written with `create_or_replace_backup`. A directory is skipped if it has no underscore in its name, if a record already exists under the reconstructed transfer ID, or if it contains no files. The endpoint returns the imported and skipped counts.

## Behaviour worth knowing

- **A restore is not queued and blocks the request.** `restore_backup` runs `subprocess.run` in the request thread, so `POST /api/backups/<id>/restore` does not return until rsync finishes. It also never goes through `QueueManager`, so nothing prevents a restore from writing into a destination that a running sync is writing to at the same time.

- **A restore can silently skip files.** The restore rsync uses `--size-only`. If a file already exists at `copy_to` with the same size as the backed-up copy, rsync will not rewrite it - the restore still reports success and still logs `Copied: ...` for it. The per-operation copy log lines are written unconditionally after rsync exits; they describe the plan, not rsync's actual decisions.

- **Delete failures do not stop the restore.** If a `target_delete` cannot be removed, the error is logged and the copy still runs, which can leave both the old and the restored file in the library.

- **An empty selection means different things on the two endpoints.** `POST .../restore` rejects `"files": []` with a 400. `POST .../plan` does not: the route only checks the type, and `plan_context_restore` treats an empty list as falsy, so planning with an empty selection returns a plan for *every* file in the backup. The UI never sends this - it disables the selected-files button when nothing is ticked.

- **Reindexed folders from webhook transfers are not usable for restore.** Webhook and simulation transfers use IDs like `webhook_12_1732000000`, not `transfer_1732000000`. Reindex reconstructs the latter from the folder name, finds no matching transfer, and imports the record with an empty `dest_path`. Restoring such a record fails immediately with `Missing destination path for configured destination roots`. The files are listed and can still be recovered by hand from `backup_path`.

- **Partial-transfer leftovers can end up indexed as backup files.** `--partial-dir` points inside the backup folder, and the indexing walk only skips entries in `.rsync-partial` whose filename starts with a dot. Anything else left there is recorded as a backup file with a relative path beginning `.rsync-partial/`. Not verified: how rsync names files inside `--partial-dir` in practice, and therefore how often the dot filter actually applies.

- **TEST_MODE does not produce a working dry run for restore.** With `TEST_MODE=1` the deletions are only printed, but the code builds a `--files-from=/tmp/test_mode_dummy_file_<n>.txt` path and deliberately does not create that file. rsync then exits non-zero, so a TEST_MODE restore reports failure. Simulation runs are a separate mechanism - see [../simulation/README.md](../simulation/README.md).

- **Restoring a backup does not remove it.** The record stays listed with `status='restored'` and the files stay in `BACKUP_PATH` until someone deletes them.

- **Timestamps are not consistent.** `created_at` is written as explicit UTC with a `Z` suffix by both finalization and reindex, but `Backup.update` writes `updated_at` and `restored_at` from `datetime.now()` - local time, no marker. The list is ordered by `created_at DESC` as a string.

- **`status='files_removed'` has no dedicated badge in the UI.** `frontend/src/components/pages/backups.tsx` styles `ready`, `restored` and `deleted`; anything else renders as a plain outline badge with the raw status text. It is also still returned by `GET /backups` without `include_deleted`, since that filter only excludes `deleted`.

- **Path safety.** Selected file paths are validated twice - once in `routes/backups.py` and again in `restore_backup` - through `security.validate_relative_path`, which rejects absolute paths, `..`, null bytes and CR/LF (the CR/LF check matters here specifically because the paths are written into an rsync `--files-from` list). The plan endpoint does not validate them, which is consistent: it only compares them against stored `relative_path` values and never touches the filesystem with them.

- **The context scan can be expensive.** `_find_dest_match_for_context` does a full `os.walk` of the destination directory once per file in the plan, and it only runs when `dest_path` is an existing directory.

## Data

Both tables are created in `models/database.py` and accessed through `models/backup.py`. Full column reference: [../../reference/database-schema.md](../../reference/database-schema.md).

`backup` - one row per transfer that displaced files:

| Column | Notes |
| --- | --- |
| `backup_id` | Unique; equals the transfer ID for finalized backups, and the reconstructed `transfer_<suffix>` for reindexed ones |
| `transfer_id` | Indexed (`idx_backup_transfer_id`) |
| `media_type`, `folder_name`, `season_name` | Copied from the transfer |
| `source_path`, `dest_path` | Copied from the transfer; `dest_path` may be empty for a reindexed unknown transfer |
| `backup_path` | The `<safe_folder>_<transfer_id>` directory under `BACKUP_PATH` |
| `file_count`, `total_size` | Computed by the indexing walk |
| `status` | `ready`, `restored`, `files_removed`, `deleted` |
| `created_at`, `restored_at`, `updated_at` | See the timestamp note above |

`backup_file` - one row per displaced file:

| Column | Notes |
| --- | --- |
| `backup_id` | Indexed (`idx_backup_file_backup_id`) |
| `relative_path` | Path within `backup_path`, always forward-slashed |
| `original_path` | Where the file was in the library, used as the restore target |
| `file_size`, `modified_time` | From `os.stat`; both `0` if the stat failed |
| `context_media_type`, `context_title`, `context_release_year`, `context_series_title`, `context_season`, `context_episode`, `context_absolute` | Parsed context |
| `context_key` | Normalized match key, indexed (`idx_backup_file_context_key`) |
| `context_display` | Human-readable label used in plans and logs |

The `transfers` table also gains a row per restore (`operation_type='restore'`, ID `restore_<backup_id>_<epoch>`), which carries the restore's log lines.

Note: `context_key` is stored and indexed but no code in `services/backup_service.py` reads it back - destination matching is done by re-deriving patterns from the individual context columns.

## API

All endpoints are registered under `/api` (`app.py`) and require authentication. Full contracts: [../../reference/api.md](../../reference/api.md).

| Endpoint | Purpose |
| --- | --- |
| `GET /api/backups` | List backups. `limit` (default 100), `include_deleted` (`1`/`true`/`True`) |
| `GET /api/backups/<backup_id>` | One record; 404 if missing |
| `GET /api/backups/<backup_id>/files` | File rows with their context, optional `limit` |
| `POST /api/backups/<backup_id>/plan` | Preview only. Optional `files` list |
| `POST /api/backups/<backup_id>/restore` | Run the restore. Omit `files` for all; `[]` is rejected |
| `POST /api/backups/<backup_id>/delete` | `delete_record` (default true), `delete_files` (default false) |
| `POST /api/backups/reindex` | Import backup folders found under `BACKUP_PATH`; returns `imported` and `skipped` |

The plan response is `{"status": "success", "plan": {"operations": [...]}}`, where each operation has `backup_relative`, `backup_full`, `copy_to`, `target_delete` and `context_display`. The example shown for this endpoint in `docs/reference/api.md` does not match what `plan_context_restore` returns.

## Related

- [../queue/README.md](../queue/README.md) - why a paused transfer skips backup finalization and a resumed one reuses the same backup folder
- [../simulation/README.md](../simulation/README.md) - rehearsal runs, which go through the same rsync path and so produce backups the same way
- [../../architecture/system-overview.md](../../architecture/system-overview.md)
- [../../reference/database-schema.md](../../reference/database-schema.md)
- [../../reference/api.md](../../reference/api.md)
