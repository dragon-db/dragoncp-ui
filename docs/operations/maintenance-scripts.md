# Maintenance and Operator Scripts

Last updated: 2026-07-28
Primary files: `scripts/migrate_v1_to_v2.py`, `scripts/verify_v2_schema.py`, `scripts/compact_transfer_logs.py`

## Purpose

Three scripts ship in `scripts/`. They are run by hand from a shell on the machine that holds the database. None of them is called by the application, and none of them is wired into startup.

| Script | Writes to the database? | Safe while the app runs? |
| --- | --- | --- |
| `migrate_v1_to_v2.py` | Yes — drops and recreates tables | No |
| `verify_v2_schema.py` | No — reads only | Yes |
| `compact_transfer_logs.py` | Only with `--apply` | No, when applying |

All three work on the same SQLite file the application uses. The app resolves its database as `dragoncp.db` in the project root (`models/database.py`), so that is the file to think about in every section below.

Run everything from the project checkout, using the project virtualenv. `compact_transfer_logs.py` imports application code, so a bare system Python will usually fail on it.

---

## `migrate_v1_to_v2.py` — one-time v1 to v2 cutover

### What it does

This is the historical cutover from the v1 schema to the v2 schema. In order, a run:

1. Copies the database aside, but only if `--backup` was passed.
2. Reads out `app_settings`, `transfer_backups` and `transfer_backup_files`, but only if `--migrate-data` was passed.
3. Drops these tables if they exist: `transfers`, `webhook_notifications`, `series_webhook_notifications`, `rename_notifications`, `app_settings`, `transfer_backups`, `transfer_backup_files`.
4. Creates the v2 tables — `transfers`, `radarr_webhook`, `sonarr_webhook`, `rename_webhook`, `app_settings`, `backup`, `backup_file` — plus their indexes.
5. Re-inserts the data read out in step 2 into `app_settings`, `backup` and `backup_file`.
6. Prints a validation report.
7. Runs `VACUUM` to shrink the file.

For background on the rename and column changes it encodes, see [../archive/v1-to-v2-migration-notes.md](../archive/v1-to-v2-migration-notes.md). The live schema is documented in [../reference/database-schema.md](../reference/database-schema.md).

### Usage

```
python scripts/migrate_v1_to_v2.py [--backup] [--migrate-data] [--db-path PATH]
```

- `--backup` — copy the database to `<db>.v1_backup_<YYYYmmdd_HHMMSS>` before anything else. Off by default.
- `--migrate-data` — carry settings and backup records across. Off by default.
- `--db-path PATH` — operate on another file. Default is `dragoncp.db` in the project root, worked out from the script's own location.

There are no other flags. Passing none of them still performs the full destructive migration, with no backup and nothing carried across.

If the database file does not exist the script prints that this is a fresh install and exits without doing anything.

### Is it destructive?

Yes, unconditionally, and more so than the flag names suggest.

- All transfer history is deleted. `transfers` is dropped and recreated empty. `--migrate-data` does not carry transfers across — it only handles settings, backup records and backup file records.
- All webhook history is deleted. The three v1 webhook tables are dropped and nothing is read out of them first.
- `--migrate-data` preserves exactly three things: rows from `app_settings`, rows from `transfer_backups` (re-inserted into `backup`, with `backup_dir` becoming `backup_path`), and rows from `transfer_backup_files` (re-inserted into `backup_file`).

Two behaviours are worth knowing before you press enter:

- **There is no check that the database is actually v1.** Pointed at a database that is already on v2, the script still drops `transfers` and `app_settings`, because those two names exist in both schemas. The result is a live installation with its entire transfer history erased. The v2-only tables (`radarr_webhook`, `sonarr_webhook`, `rename_webhook`, `backup`, `backup_file`) are not in the drop list and survive untouched.
- **Extraction failures do not stop the run.** Each read-out step catches its own errors, prints a warning line, and returns an empty result. The drop then proceeds regardless. A `--migrate-data` run can therefore report warnings, complete "successfully", and have carried nothing across.

### Is it reversible?

No. The only route back is restoring a copy of the file taken beforehand. `VACUUM` at the end also releases the freed pages, so nothing is recoverable from within the file afterwards.

### Before running

1. **Stop the application.** It writes to the same file, and the script drops tables and runs `VACUUM` underneath it. Queue and path-lock state is also held in memory by the running process (see [../features/queue/README.md](../features/queue/README.md)), so it must not be alive across a schema swap.
2. **Take your own copy of `dragoncp.db`,** to a path outside the project directory. Do this rather than relying on `--backup`, which is off unless you ask for it and writes its copy next to the original.
3. Note down anything you need from transfer and webhook history first — it does not survive.
4. Pass `--backup --migrate-data` unless you have a specific reason not to.

### After running

- Read the printed validation section. It checks that the seven v2 tables exist, that the removed columns are gone from `transfers`, that `operation_type` and `rsync_process_id` are present, that the three webhook tables have `completed_at` and `updated_at` and not `synced_at`/`processed_at`, and that `backup` has `backup_path` and not `backup_dir` or `episode_name`.
- **Do not trust the exit code.** The script exits 0 whether validation passed or failed; a failure only changes the final line to "Migration completed with validation warnings!". Read the output.
- The schema this script creates is v2 as it stood when the script was written, and is older than what the application expects today. Later columns — `queue_reason`, `progress_percent`, `bytes_transferred`, `total_bytes`, `speed_bps`, `eta_seconds`, `paused_at`, `is_simulation`, `simulation_bwlimit`, and `is_simulation` on the two webhook tables — are added by the application itself on startup (`models/database.py`). Start the app once after migrating, and let it finish its startup before assuming the database is complete.

---

## `verify_v2_schema.py` — read-only schema check

### What it does

Prints a report on the current shape of the database: every table name it finds, whether each of the seven expected v2 tables is present, whether each of the five v1 tables is gone, the full column list of `transfers`, and then a handful of specific column checks.

It only issues `SELECT` and `PRAGMA` statements. Nothing is written, dropped or altered.

### Usage

```
python scripts/verify_v2_schema.py
DRAGONCP_DB=/path/to/dragoncp.db python scripts/verify_v2_schema.py
```

There are no command-line flags. The database path comes from the `DRAGONCP_DB` environment variable, and falls back to `dragoncp.db` **relative to the current working directory** — not to the project root, unlike the other two scripts. Run it from the project root, or set `DRAGONCP_DB` to an absolute path. If the file is not found it prints that and exits with status 1.

### Is it destructive or reversible?

Neither applies. It is read-only and safe to run at any time, including while the application is serving traffic and while transfers are in flight.

### What it checks, and what it does not

Checked: the seven v2 tables exist; `webhook_notifications`, `series_webhook_notifications`, `rename_notifications`, `transfer_backups` and `transfer_backup_files` are gone; `transfers` has `operation_type` and `rsync_process_id` and no longer has `episode_name` or `parsed_episode`; `radarr_webhook` has `completed_at` and `updated_at`; `backup` has `backup_path` and no `episode_name`.

Not checked: the columns of `sonarr_webhook` and `rename_webhook`, and every column the application has added since (`queue_reason`, the progress columns, the simulation columns). A clean report here does not mean the database matches [../reference/database-schema.md](../reference/database-schema.md).

The script always finishes with "Schema verification complete!" regardless of how many checks failed, and its exit status is not a pass/fail signal. Read the `✗` lines.

---

## `compact_transfer_logs.py` — shrink stored rsync progress lines

### What it does

Rewrites the stored log of past transfers so that each run of consecutive rsync progress lines is reduced to its newest line. Every other line is kept as it is. Only the `logs` column of the `transfers` table is touched — no other column and no other table.

Transfers created recently already collapse progress lines as they are written. This script applies the same rule to rows that predate that change, where the stored log is mostly superseded progress ticks. The reasoning, and the measured effect, is in [../plans/rsync-log-streaming.md](../plans/rsync-log-streaming.md).

Progress figures themselves live in their own columns, so the numbers the UI shows are not affected by dropping the intermediate lines.

### Usage

```
python scripts/compact_transfer_logs.py                      # report only, no changes
python scripts/compact_transfer_logs.py --apply              # rewrite the rows
python scripts/compact_transfer_logs.py --apply --backup     # rewrite, copy the file aside first
python scripts/compact_transfer_logs.py --apply --db /path/to/dragoncp.db
```

- No flags — **report only**. This is the default, and the recommended first run. It scans every row and prints how many transfers were scanned, how many would change, log lines before and after, the size of the log column before and after, and the single transfer with the biggest saving. It changes nothing and ends with a reminder to re-run with `--apply`.
- `--apply` — write the compacted logs back, then `VACUUM` to reclaim the freed pages and report the file size before and after. Without the `VACUUM` the file would stay the same size on disk.
- `--backup` — copy the database to `<db>.pre_log_compaction_<YYYYmmdd_HHMMSS>` before writing. This only happens when `--apply` is also given; on a report-only run the flag has no effect.
- `--db PATH` — operate on another file. Default is `dragoncp.db` in the project root, worked out from the script's own location.

Because the script imports the application's rsync progress parser from `services/transfer_service.py`, run it from the checkout with the project virtualenv active.

### Is it destructive?

With `--apply`, yes, but narrowly. The intermediate progress lines are removed from storage permanently. Nothing else about a transfer changes, and rows whose log is not valid JSON are skipped rather than rewritten.

Without `--apply` it is completely read-only.

### Is it reversible?

Not on its own. The removed lines are gone once `VACUUM` has run. `--backup` is the only route back, which is why it is worth passing every time you pass `--apply`.

### Before running

1. **Run it without `--apply` first** and read the report.
2. **Stop the application, or at least wait until no transfers are running.** The script reads every row up front and writes the compacted versions back afterwards. Any log lines a live transfer appends in between are inside that window and will be replaced by the earlier snapshot. `VACUUM` also wants the file to itself.
3. Pass `--backup` alongside `--apply`, or take your own copy of `dragoncp.db` first.

---

## Related documentation

- [../reference/database-schema.md](../reference/database-schema.md) — the current live schema
- [../archive/v1-to-v2-migration-notes.md](../archive/v1-to-v2-migration-notes.md) — background on the v1 to v2 change
- [../plans/rsync-log-streaming.md](../plans/rsync-log-streaming.md) — why log compaction exists and what remains outstanding
- [./runtime-and-deployment.md](./runtime-and-deployment.md) — how the application is run in production
- [../features/queue/README.md](../features/queue/README.md) — in-memory queue state, which does not survive a stop
