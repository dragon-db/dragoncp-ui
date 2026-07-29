# Transfers

A transfer copies one folder (or one episode file) from the remote media server
onto local storage and keeps a record of how it went. The operator sees a live
percentage, throughput, ETA and the running rsync output; anything the copy would
have destroyed at the destination is set aside first, so it can be restored. A
transfer can be paused and picked up again later, cancelled, restarted after a
failure, and its record deleted once it is no longer interesting.

## Where it lives

| Concern | File |
|---|---|
| rsync command, monitor loop, progress parsing, pause/cancel/restart | `services/transfer_service.py` |
| Orchestration: queue admission, resume, post-completion follow-up | `services/transfer_coordinator.py` |
| HTTP endpoints | `routes/transfers.py` |
| Row storage, log storage, listing query | `models/transfer.py` |
| Concurrency and destination locking | `services/queue_manager.py` |
| Per-transfer backup directory, backup finalization | `services/backup_service.py` |
| SSH host-key policy shared with the browse path | `ssh.py` |
| Path-component validation for request input | `security.py` |
| Storage tests | `tests/test_transfer_logging.py`, `tests/test_transfer_listing.py` |

## How it works

### 1. Creation

`POST /api/transfer` lands in `api_transfer()` in `routes/transfers.py`. It
validates `folder_name`, `season_name` and `episode_name` with
`validate_path_component()` so none of them can contain `..`, a separator or a
null byte, then builds the source and destination from the configured base paths
(`MOVIE_PATH`/`MOVIE_DEST_PATH` and the TV/anime equivalents). Before anything
starts, `assert_path_within_bounds()` resolves the destination and rejects it if
it escapes the configured base — component validation alone would not catch a
symlink pointing out of the tree. The transfer id is `transfer_<unix seconds>`.

`type=file` requires an `episode_name` and appends it to both sides; `type=folder`
does not. That distinction reappears later in the rsync arguments.

The same entry point is used by everything else that syncs:
`services/webhook_service.py` (movie and series webhook triggers) and
`services/simulation_service.py` both call
`TransferCoordinator.start_transfer()`.

### 2. Admission

`TransferCoordinator.start_transfer()` decides whether the transfer runs now or
waits. It asks `QueueManager.check_duplicate_destination()` whether the
destination is already reserved, and `QueueManager.register_transfer()` whether a
slot is free. Either check can produce a `queued` row with `queue_reason` set to
`path` or `slot`; only when both pass is a `pending` row created and rsync
started. The details of queueing and promotion are in
[../queue/README.md](../queue/README.md).

For a transfer that can start, the coordinator asks
`BackupService._get_dynamic_backup_dir()` for a per-transfer directory under
`BACKUP_PATH` (named `<safe folder name>_<transfer_id>`), then calls
`TransferService.start_rsync_process()`, then starts a
`_post_transfer_completion()` watcher thread.

### 3. The rsync command

`start_rsync_process()` first clears any recorded stop intent and any cached
total-size estimate for this id, because a resumed or restarted run must derive
its own figures and must not inherit the previous run's intent. It creates the
destination directory, the backup directory and `<backup dir>/.rsync-partial`.

The command it builds:

| Argument | What it is doing |
|---|---|
| `-av` | Archive mode, verbose. The verbose output is what names each file in the log |
| `--progress` | Kept ahead of `--info=progress2` so `-v` still prints file names |
| `--info=progress2` | Percent/bytes/speed/ETA for the whole transfer instead of the current file. This is the line the UI reads |
| `--delete` | The destination converges on the source |
| `--backup`, `--backup-dir` | Anything `--delete` or an overwrite would destroy is moved into this transfer's backup directory instead |
| `--update` | Do not overwrite a destination file that is newer |
| `--exclude .*`, `*.tmp`, `*.log` | Dotfiles and scratch files are not media |
| `--stats` | Produces the summary block, including `total size is ...`, which is parsed for the exact transfer size |
| `--human-readable` | A single `-h`, so sizes are powers of 1000 — the parser's unit table assumes exactly this |
| `--bwlimit=0` | No speed ceiling (a simulation replaces this, see below) |
| `--block-size=65536`, `--no-compress`, `--no-checksum`, `--whole-file`, `--preallocate` | Throughput choices for large media files; `--whole-file` turns off the delta algorithm, `--no-compress` is paired with `Compression=no` on the ssh side |
| `--partial`, `--partial-dir` | Partially written files survive into `<backup dir>/.rsync-partial`. This is what makes pause and resume possible at all |
| `--timeout=300` | Five-minute I/O timeout. This is also the reason pause stops rsync rather than suspending it |
| `--size-only` | Compare by size, not checksum or timestamp |
| `--no-perms`, `--no-owner`, `--no-group` | Do not carry remote ownership or permissions onto local storage |
| `--no-motd` | Keeps a server banner out of the parsed output |
| `-e ssh ...` | Host-key options from `_build_ssh_host_key_options()`, plus `-i <key>` when a readable key is configured |

`_build_ssh_host_key_options()` mirrors the policy used by the paramiko browse
path in `ssh.py`, so both agree: `strict` and `accept-new` both point rsync's ssh
at the managed known-hosts file, `no` disables verification and prints a warning.
The known-hosts path is embedded in a single `-e` string that rsync splits on
spaces, so a path containing spaces would break it.

Source and destination are appended last. A folder transfer uses a trailing slash
on the source so the folder's *contents* are synced; a file transfer does not.

Two variations:

- **`TEST_MODE=1`** appends `--dry-run` and skips directory creation, so nothing
  is written.
- **A simulation row** (`is_simulation`) runs rsync locally with no SSH at all,
  and its `--bwlimit=0` is replaced by the row's `simulation_bwlimit` (default
  `SIMULATION_BWLIMIT_KBPS`, 4000 KB/s) so the copy takes long enough to watch.
  Everything downstream is the production path — see
  [../simulation/README.md](../simulation/README.md).

rsync is started with `subprocess.Popen`, stderr folded into stdout, line
buffered. If it has already exited by the time `poll()` is checked, the row is
marked `failed`. Otherwise the row moves to `running` with its PID recorded and
`progress_percent`, `bytes_transferred`, `total_bytes`, `speed_bps`,
`eta_seconds` and `paused_at` reset — a resumed run must not display the previous
run's speed and ETA until rsync emits its first tick. A daemon thread then runs
`_monitor_transfer()`.

### 4. The monitor loop

`_monitor_transfer()` reads rsync's output line by line. It holds the last 100
lines (`SOCKET_LOG_TAIL`) in memory rather than re-reading the row per line,
because building the socket payload used to cost a second full-row read for every
line rsync printed.

For each line:

1. `_progress_updates()` turns it into column updates, or `None` if it carries no
   figures.
2. If the line is a progress line and the previous line was too, it *replaces*
   the last entry in the tail instead of being appended.
3. The write is throttled: a progress line only reaches the database once per
   `PROGRESS_WRITE_INTERVAL` (1 second). Any other line is written immediately,
   and carries the newest figures with it so the columns never lag behind a tick
   the interval skipped.
4. Every line is emitted over the socket as `transfer_progress` with the tail,
   the running log count and the current stats. The throttle is only about
   database writes; the UI sees every tick.

A skipped progress line is held in `pending_progress` and flushed once rsync
stops writing, otherwise a finished transfer would be left displaying whatever
percentage happened to land on an interval boundary.

There are two separate "was the last line a progress line?" flags on purpose.
`last_line_was_progress` tracks the in-memory tail; `db_last_was_progress` tracks
what was actually written. When the interval skips a tick the two diverge, and
replacing based on the tail would overwrite a real log line — a file name — with
a progress line. `tests/test_transfer_logging.py::test_real_log_lines_are_never_replaced_by_a_progress_line`
pins that.

### 5. Parsing progress

`parse_rsync_progress()` matches one `--info=progress2` line, e.g.
`2.70G  64%  142.31MB/s    0:00:11`, into `bytes_transferred`,
`progress_percent` (clamped 0-100) and `speed_bps`, plus `eta_seconds` when the
build emits an ETA field — some do not, and the regex makes that group optional.
It also accepts comma-grouped byte counts, the form produced without
`--human-readable`. Any line that is not a progress line returns `None`, so every
line of output can be passed through it.

`total_bytes` comes from two sources. While running, `_estimate_total_bytes()`
derives it from bytes-done and percent-done, but only once percent has reached 5
— below that, one percent of granularity is a huge relative error and the derived
figure swings wildly. The first usable estimate is cached per transfer in
`_total_estimates` and reused for the rest of the run so the displayed total does
not jitter. When rsync's `--stats` summary prints `total size is ...`,
`parse_rsync_total_size()` reads the exact figure and replaces the estimate.

`build_progress_stats()` is the single place that shapes these five columns for
API responses and socket payloads; `routes/transfers.py` spreads it into every
transfer object it returns.

### 6. Finishing, and intentional stops

Pause and cancel both terminate rsync, which then exits non-zero. Without help,
the monitor thread would see that exit code and overwrite the correct row with
`failed`. `TransferService` therefore keeps `_intentional_stops`, a
lock-protected map of `transfer_id -> 'paused' | 'cancelled'`. `pause_transfer()`
and `cancel_transfer()` record the intent *before* signalling the process; the
monitor calls `_take_intentional_stop()` after `process.wait()` and, if it finds
one, reports that outcome and skips the final row update entirely — the row was
already written correctly by the caller. If signalling fails, the caller clears
the intent again so a still-running transfer is not left mislabelled.

With no recorded intent, exit code 0 is `completed` and anything else is
`failed`. Either way a `transfer_complete` socket event goes out with the last
100 log lines and the final stats, the process is dropped from `self.transfers`,
and the cached total estimate is discarded.

`_post_transfer_completion()` in the coordinator polls the row every five seconds
and, once it is no longer `running`/`pending`, releases the queue slot, updates
linked webhook rows, sends the Discord notification for `completed`/`failed`, and
finalizes the backup record. A `paused` row is the exception: the slot is
released but webhook state and backup finalization are deliberately left alone,
because the transfer is expected to resume.

### 7. Pause and resume

rsync cannot be suspended in place. The command sets `--timeout=300`, so a
process frozen with SIGSTOP would lose its connection after five minutes and the
resume would fail anyway. `pause_transfer()` instead stops rsync outright and
relies on `--partial`/`--partial-dir`, which are already part of every transfer
command: the partially written files stay in `<backup dir>/.rsync-partial` and
the next run continues from them.

The order matters. The intent is recorded, then the row is written to `paused`
with `paused_at` set and speed/ETA zeroed, then the process is terminated. If
termination throws, the intent is cleared and the row is put back to `running`,
because the process is in fact still running. `TransferCoordinator.pause_transfer()`
then releases the queue slot immediately rather than waiting for the watcher's
five-second poll, so a resume issued straight away is not told the queue is full.

`TransferCoordinator.resume_transfer()` only accepts a `paused` row and goes back
through `QueueManager.register_transfer()` rather than starting rsync directly,
so a resume respects the concurrency cap and cannot collide with a transfer that
claimed the same destination while this one was paused. Depending on the answer
it either becomes `queued` again (with `queue_reason='slot'`) or moves to
`pending` and starts a fresh rsync run plus a fresh watcher thread.

### 8. Cancel, restart, delete

`cancel_transfer()` handles three cases. A `queued` row and a `paused` row have
no live process, so cancelling them is a row update. A `running` row is checked
for a live PID first: if one exists, the intent is recorded and the process
terminated; if not — a row whose process already exited — the row is still moved
to `cancelled`, because otherwise it would be stuck as `running` forever. The
coordinator then unregisters it from the queue.

`restart_transfer()` accepts `failed`, `cancelled` and `completed` rows. It
resets the row to `pending`, clears the recorded PID, sets a new `start_time`,
clears `end_time`, and calls `start_rsync_process()` again with a freshly
computed backup directory.

`POST /transfer/<id>/delete` refuses only a `running` row (with a message telling
the operator to cancel first) and otherwise deletes the record via
`Transfer.delete()`. It deletes the database row only; files on disk, including
partial files and the transfer's backup directory, are not touched.

### 9. Listing versus detail

`Transfer.get_all(include_logs=False)` leaves the `logs` column out of the SELECT
entirely and adds a computed `log_count` instead:

```sql
CASE WHEN json_valid(logs) THEN json_array_length(logs) ELSE 0 END AS log_count
```

The log is by far the largest thing on a transfer row and no listing displays it —
only how many lines there are — so selecting it meant reading and JSON-parsing
megabytes per request to render counts. The column list is read once from
`PRAGMA table_info(transfers)` and cached per process, so any column added later
appears in listings automatically. `json_valid` guards rows written before the
column held JSON. Filtering, searching and paging are all applied in SQL;
filtering used to happen after the limit, which meant a page of recent completed
transfers could hide every failed one.

### 9a. Paging the history

History is a page, not a prefix. `Transfer.get_all()` takes `limit`, `offset`,
`search` and either a single `status` or a set of `statuses`; `count()` and
`status_counts()` answer the same filter without the page window, sharing one
`_filter_sql()` so a listing and its total cannot drift apart.

The page states three different numbers, and they are not interchangeable:

| Field | Counts |
|---|---|
| `count` | rows on this page |
| `total` | rows matching the current filter and search |
| `unfiltered_total` | rows matching only the status set — what the tab badge shows, so it does not move while someone types |

`search` matches anywhere in `parsed_title`, `folder_name`, `season_name`,
`dest_path`, `source_path` or `transfer_id` — what a person remembers about a
transfer rather than what the schema calls it.

The History tab asks for `statuses=completed,failed,cancelled`, so live
transfers never reach it. Before this, the page fetched a fixed 200 rows and
narrowed them in the browser: with 519 transfers on record, 61% of the history
could not be reached at all, and "Failed" showed nothing whenever the newest 200
rows happened to be completed.

### 9b. Deleting in bulk

`Transfer.delete_many()` takes a list of ids and returns
`(deleted_count, skipped_ids)`. Transfers still `running` are never deleted —
there is a live rsync process behind the row — so they come back in `skipped`
and the caller reports them rather than losing them silently. Ids are deleted in
batches of `DELETE_BATCH` (400), safely inside SQLite's 999-variable limit.

`POST /transfers/bulk-delete` accepts either explicit `ids` or `all_matching`
with the same filter the list was showing. The `all_matching` form re-runs the
query on the server, which is what lets "select all" mean every match rather
than the rows a browser happened to have loaded.

Deleting `completed` records has a consequence beyond the list: `get_sync_status`
reads completed transfers to decide the SYNCED / OUT_OF_SYNC badges in Browse
Media, so media covered by a deleted record shows as not yet synced. The
confirmation in the UI says so.

Both coordinator listing methods (`get_all_transfers`, `get_active_transfers`)
and `resume_active_transfers()` pass `include_logs=False`. The detail endpoints
(`/transfer/<id>/status`, `/transfer/<id>/logs`) use `Transfer.get()`, which does
select and parse the log body.

### 10. Startup recovery

`TransferService.resume_active_transfers()` runs during coordinator construction.
Rows still marked `running` whose recorded PID is alive get a
`_resume_transfer_monitoring()` thread; rows whose process is gone are marked
`failed` with "Transfer process was interrupted". The coordinator also restarts a
`_post_transfer_completion()` watcher for each resumed id, so queue release,
webhook updates, notifications and backup finalization still happen.

## Behaviour worth knowing

- **A resumed run continues the same log.** Neither resume nor restart clears the
  `logs` array, so a restarted transfer's output is appended to the previous
  run's. The log is capped at `LOG_MAX_LINES` (5000) and the *oldest* lines are
  dropped, because the end of an rsync log is the part worth keeping — it holds
  the `--stats` block and any errors.
- **After an app restart, a live transfer stops reporting progress.**
  `_resume_transfer_monitoring()` reattaches to the PID with psutil and waits on
  it; it has no access to the original stdout pipe, so no further log lines or
  progress figures are recorded for that run. The percentage freezes at whatever
  was last written until the process exits.
- **That recovery path can record a failure as success.** When the exit status is
  unavailable (the rsync process is not a child of the restarted app) the code
  marks the transfer `completed` with "Transfer finished after restart (exit
  status unavailable)", and a `NoSuchProcess` is likewise recorded as completed.
  An rsync that fails after an app restart may therefore show as completed.
- **Restart bypasses the queue.** `TransferCoordinator.restart_transfer()` calls
  `TransferService.restart_transfer()` directly. It does not go through
  `QueueManager.register_transfer()` and does not start a
  `_post_transfer_completion()` watcher. A restarted transfer is therefore not
  counted against `MAX_CONCURRENT_TRANSFERS`, does not take the destination lock,
  and on finishing will not update webhook rows, send a Discord notification or
  finalize its backup record. Pause and resume are unaffected — resume does go
  through the queue.
- **A `pending` transfer cannot be cancelled.** `cancel_transfer()` handles
  `queued`, `paused` and `running` and returns `False` for anything else, so the
  API answers "Failed to cancel transfer" for a row in the brief `pending` window
  between admission and rsync starting.
- **Deleting a queued transfer leaks its destination reservation.** The delete
  endpoint removes the row without calling `QueueManager.unregister_transfer()`,
  and a queued transfer holds an entry in `active_destinations`. Until the app
  restarts (where `force_unregister_stale_transfers()` rebuilds the maps), later
  transfers to that destination can be queued behind a transfer that no longer
  exists.
- **Transfer ids are second-granularity.** `transfer_<int(time.time())>` from
  `routes/transfers.py`, against a `UNIQUE` `transfer_id` column. Two manual
  transfers started within the same second would collide on insert. Not verified:
  what the UI shows when that happens.
- **`--update` and `--delete` together.** A destination file that is newer than
  the remote copy is kept, but a destination file with no remote counterpart is
  removed (into the backup directory, not deleted outright).
- **Progress percent is rsync's, not a byte ratio.** `progress_percent` is read
  straight from the progress line. `total_bytes` is derived from it while the
  transfer runs, so early in a run the total shown is an estimate that only
  becomes exact when `--stats` prints.
- **No automatic retention.** `Transfer.cleanup_old_transfers()` exists but is
  not called from anywhere in the codebase. The only cleanup exposed is
  `POST /transfers/cleanup`, which removes duplicate *completed* rows per
  destination path, keeping the most recent by `end_time`, then `updated_at`,
  then `created_at`, then id.
- **Logs are broadcast to every connected client.** `transfer_progress` and
  `transfer_complete` are emitted globally, not into a per-transfer room. This is
  a known gap in `docs/plans/rsync-log-streaming.md`.
- **The frontend listens for a `transfer_failed` socket event that the backend
  never emits** (`frontend/src/services/socket.ts`); failures arrive as
  `transfer_complete` with `status: "failed"`.
- **Simulation rows are real transfers.** They live in the same table and run the
  same code; only `is_simulation` tells them apart, and cleanup deletes by that
  flag.

## Data

Everything lives in the `transfers` table. See
[../../reference/database-schema.md](../../reference/database-schema.md) for the
full definition.

| Column | Written by |
|---|---|
| `transfer_id`, `media_type`, `folder_name`, `season_name`, `source_path`, `dest_path`, `operation_type` | `Transfer.create()` at admission |
| `parsed_title`, `parsed_season` | `Transfer._parse_metadata()` at creation — strips years, dots and underscores from the folder name and pulls a season number out of the season name |
| `status`, `progress` | Every stage; `progress` holds the most recent rsync output line |
| `queue_reason` | `path` or `slot` for queued rows |
| `rsync_process_id` | Set when rsync starts, cleared on restart |
| `logs` | `Transfer.add_log()`, JSON array, collapsed and capped as described above |
| `progress_percent`, `bytes_transferred`, `total_bytes`, `speed_bps`, `eta_seconds` | Parsed by the monitor loop and folded into the same UPDATE as the log line |
| `paused_at` | Set on pause, cleared on resume and on a fresh rsync start |
| `start_time`, `end_time`, `created_at`, `updated_at` | Lifecycle timestamps |
| `is_simulation`, `simulation_bwlimit` | Simulation rows only |

Reads elsewhere: `Transfer.get_sync_status()` and
`get_folder_sync_status_summary()` query completed transfers by
media type/folder/season to decide whether the media browser shows a folder as
`SYNCED`, `OUT_OF_SYNC` or `NO_INFO`.

## API

All routes are registered under `/api` (`app.py`). Full request and response
contracts are in [../../reference/api.md](../../reference/api.md).

| Method | Path | Purpose |
|---|---|---|
| POST | `/transfer` | Start (or queue) a transfer |
| GET | `/transfer/{id}/status` | One transfer with progress figures and full log |
| GET | `/transfer/{id}/logs` | Stored log lines and count |
| POST | `/transfer/{id}/cancel` | Cancel a queued, paused or running transfer |
| POST | `/transfer/{id}/pause` | Stop rsync, keep partial files |
| POST | `/transfer/{id}/resume` | Continue a paused transfer, re-admitted through the queue |
| POST | `/transfer/{id}/restart` | Run a failed, cancelled or completed transfer again |
| POST | `/transfer/{id}/delete` | Delete the record (not while running) |
| GET | `/transfers/all` | History page — `limit`, `offset`, `status`, `statuses`, `search` |
| GET | `/transfers/active` | Running/pending/queued/paused plus queue status |
| GET | `/transfers/queue/status` | Queue counters only |
| POST | `/transfers/bulk-delete` | Delete many records by id, or every record a filter finds |
| POST | `/transfers/cleanup` | Drop duplicate completed rows per destination |

Every endpoint is behind `@require_auth`. Socket events emitted from this
feature: `transfer_progress` and `transfer_complete` (`transfer_service.py`),
`transfer_queued` (`transfer_coordinator.py`), `transfer_promoted`
(`queue_manager.py`).

## Related

- [../queue/README.md](../queue/README.md) — admission, the destination lock, and promotion
- [../simulation/README.md](../simulation/README.md) — running this pipeline against local fixtures
- [../../architecture/system-overview.md](../../architecture/system-overview.md) — where transfers sit in the system
- [../../reference/api.md](../../reference/api.md) — full endpoint contracts
- [../../reference/database-schema.md](../../reference/database-schema.md) — the `transfers` table
