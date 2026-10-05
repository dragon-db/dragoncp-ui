# Transfers

Last updated: 2026-10-05

A transfer copies one folder (or one episode file) from the remote media server
onto local storage and keeps a record of how it went. The operator sees a live
percentage, throughput, ETA and the running rsync output; anything the copy would
have destroyed at the destination is set aside first, so it can be restored. A
transfer can be paused and picked up again later, cancelled, restarted after a
failure, and its record deleted once it is no longer interesting. Every transfer
is the copy step of a sync in the [sync engine](../sync-engine/README.md): the
engine decides when the transfer is created — after the sync's safety check,
with the queue deciding when it starts — and closes the sync when the copy ends.

## Where it lives

| Concern | File |
|---|---|
| rsync command, monitor loop, progress parsing, pause/cancel, reattaching after a restart | `services/transfer_service.py` |
| Orchestration: queue admission, re-running a row through the queue (`requeue_transfer`), resume, post-completion follow-up, lifecycle hooks into the sync engine | `services/transfer_coordinator.py` |
| When a transfer is created, restart as a new sync, closing the sync and telling Discord | `services/sync_engine/engine.py` |
| What happens to a sync's transfer after a DragonCP restart | `services/sync_engine/recovery.py` |
| HTTP endpoints | `routes/transfers.py` |
| Row storage, log storage, listing query | `models/transfer.py` |
| Concurrency and destination locking | `services/queue_manager.py` |
| Backup staging directory, and sorting what a transfer displaced | `services/backups/` |
| SSH host-key policy shared with the browse path | `ssh.py` |
| Path-component validation for request input | `security.py` |
| Storage tests | `tests/test_transfer_logging.py`, `tests/test_transfer_listing.py` |
| Restart through the queue, a lost result after a restart, the safety-check skips, a deleted transfer's sync | `tests/test_sync_engine.py` |

## How it works

### 1. Creation

`POST /api/transfer` lands in `api_transfer()` in `routes/transfers.py`. It
validates `folder_name`, `season_name` and `episode_name` with
`validate_path_component()` so none of them can contain `..`, a separator or a
null byte, then builds the source and destination from the configured base paths
(`MOVIE_PATH`/`MOVIE_DEST_PATH` and the TV/anime equivalents). Before anything
starts, `assert_path_within_bounds()` resolves the destination and rejects it if
it escapes the configured base — component validation alone would not catch a
symlink pointing out of the tree.

`type=file` requires an `episode_name` and appends it to both sides; `type=folder`
does not. That distinction reappears later in the rsync arguments — and on the
destination side it is a bug: the file is copied into a new folder named after
it rather than over it (Behaviour worth knowing).

The request then goes to the sync engine as a **manual sync**
(`SyncEngine.submit()`), not straight to the queue, and the answer comes back
before any transfer exists. It carries the sync's `run_id`, the run's state in
`transfer_state` (`checking` for a fresh request) and a message; `transfer_id`
is `null`. What happens next is the engine's — see
[Sync engine](../sync-engine/README.md):

- if the same destination folder already has a batch that has not started
  copying — a webhook batch waiting for Sonarr, say — the request joins it
  rather than starting a second transfer, and tells it to go now if it is still
  waiting or held;
- if the folder is being copied right now, the request goes into the one
  follow-up batch behind that copy, opening it if needed;
- the ready check is skipped, and the safety check — a dry run of the same
  copy — runs first. If it refuses, no transfer is created (see Behaviour worth
  knowing). A `type=file` request skips the dry run: rsync deletes nothing when
  it is given a single file;
- at the Queue stage the engine creates the transfer, with an id of
  `transfer_<unix seconds>_<six hex characters>`.

The activity entry for the request names the sync run, not a transfer.

Every other way a sync starts goes through the engine too — Sonarr and Radarr
webhooks, the auto-scanner, Explore, simulations and restarts. Apart from
fallbacks that Explore and simulations use only when no engine exists, the
engine's Queue stage is the only caller of `TransferCoordinator.start_transfer()`;
a restart uses `requeue_transfer()` instead (section 8). Explore and simulations
wait for the queue's answer before returning (`submit(..., wait=True)`), because
they have to roll back or report at once.

### 2. Admission

`TransferCoordinator.start_transfer()` decides whether the transfer runs now or
waits. It asks `QueueManager.check_duplicate_destination()` whether another
transfer already holds the destination folder — or a folder inside or around it,
so a whole-series copy and a copy of one of its seasons never run together — and
`QueueManager.register_transfer()` whether a slot is free. Either check can
produce a `queued` row with `queue_reason` set to `path` or `slot`; only when
both pass is a `pending` row created and rsync started. The details of queueing
and promotion are in [../queue/README.md](../queue/README.md).

For a transfer that can start, the coordinator asks the backups service for the
transfer's staging directory, `<BACKUP_PATH>/.staging/<transfer_id>`
(`BackupsService.staging_dir()`); with no `BACKUP_PATH` configured the row is
marked `failed` and nothing runs. It then tells the sync engine the copy is
starting (`before_transfer_start` — the run moves to copying and its webhooks to
`syncing`, under the folder's lock, so a webhook arriving from then on goes to a
follow-up batch), calls `TransferService.start_rsync_process()`, records on the
run which route rsync took — SSH, the fast transfer server, or local for a
simulation (`on_transfer_started`) — and starts a `_post_transfer_completion()`
watcher thread.

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
The destination always carries a trailing slash, and is created as a directory
beforehand — which, for a file transfer, is what puts the file into a folder of
its own name (Behaviour worth knowing).

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
4. Every line is emitted over the socket as `transfer_progress` with the line,
   the running log count and the current stats, to every client. The tail goes
   separately as `transfer_logs`, only into the transfer's own room — joined
   with `transfer_logs_subscribe` by whoever has the row open — and not at all
   when nobody is subscribed. The throttle is only about database writes; the
   UI sees every tick.

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
and, once it is no longer `running`/`pending`, releases the queue slot and hands
the outcome to the sync engine (`on_transfer_finished`). The run's Finish stage
marks every webhook on it synced, failed or cancelled; its Tell stage announces
`completed` and `failed` on Discord, labelled by how the sync started
("Automated Sync", "Manual Sync", "Auto-scanner"…; a webhook or auto-scanner
batch a person released with Sync or Go now is a "Manual Sync"), and opens a
*Failed* alert with **Retry** for a failure — except a failure whose result a
restart lost, which gets its own alert instead (section 10), and a failed
restore, whose alert offers only **Dismiss** and points at the Backups page.
Cancelled syncs, restores and simulations — restarted simulations included —
are not announced, and a failed simulation opens no alert. A transfer with no
run — one created before the engine existed — is finished the old way: webhook
rows by transfer id, then the Discord notification. Either way the watcher then files what the transfer
displaced into the backup tree (`sort_after_transfer`). A `paused` row is the
exception: the slot is released but webhook state and backup sorting are
deliberately left alone, because the transfer is expected to resume. Calling
`on_transfer_finished` more than once for the same run is harmless; only the
first call closes it.

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
claimed the same folder — or one inside or around it — while this one was
paused. Depending on the answer it either becomes `queued` again (with
`queue_reason='slot'`), moves to `pending` and starts a fresh rsync run plus a
fresh watcher thread, or — when another transfer holds the folder — is refused
with "Another transfer is already syncing to this destination" and stays paused.

Both are recorded on the transfer's sync run (`on_transfer_paused`,
`on_transfer_resumed`): the Transfer stage says who paused it, and a resume that
has to wait puts the run back at its Queue stage.

### 8. Cancel, restart, delete

`cancel_transfer()` handles three cases. A `queued` row and a `paused` row have
no live process, so cancelling them is a row update. A `running` row is checked
for a live PID first: if one exists, the intent is recorded and the process
terminated; if not — a row whose process already exited — the row is still moved
to `cancelled`, because otherwise it would be stuck as `running` forever. The
coordinator then unregisters it from the queue. A queued or paused transfer has
no watcher thread, so the coordinator closes its sync run itself
(`on_transfer_finished(..., 'cancelled')`); a running one is closed by its
watcher.

Restart goes through the sync engine (`SyncEngine.restart_transfer()`, which both
`POST /transfer/<id>/restart` and an alert's **Retry** call) and accepts
`failed`, `cancelled` and `completed` rows — except a restore's, which it
refuses: "A restore is run again from the Backups page, where its preview shows
what it will replace." It never starts rsync directly. It opens a new sync run
of kind `restart`, linked to the run it retries and taking over that run's
webhooks; the ready check is skipped, the safety check runs — unless the
transfer is a simulation's, a single file, or an Explore plan's, each of which
skips it with its reason (Behaviour worth knowing) — and then the run waits its
turn in the queue like any other sync.

At the Queue stage, `TransferCoordinator.requeue_transfer()` reuses the same
transfer row: it clears the PID, end time, pause time and progress figures, sets
a new `start_time`, points the row at the new run, and puts it through the same
two checks as a new transfer — `queued` with `queue_reason` `path` or `slot`, or
started straight away with a fresh watcher thread. Because the id is unchanged,
so is the staging directory and its `.rsync-partial` folder, and rsync carries on
from the previous attempt's partial files.

If the folder already has a batch that has not started copying, the restart
does not run at all: any webhooks on the old run move onto that batch, which is
told to go now if it is still waiting, so the folder is copied once. The transfer
that was restarted keeps its `failed` or `cancelled` status; the batch's own
transfer does the copy.

`POST /transfer/<id>/delete` refuses only a `running` row (with a message telling
the operator to cancel first). A `queued` or `paused` row is cancelled first,
exactly as above — so its queue reservation is freed and its sync run closed as
cancelled — and then the record is deleted via `Transfer.delete()`
(`_cancel_before_delete` in `routes/transfers.py`). A `pending` row cannot be
cancelled (Behaviour worth knowing) and is deleted as it is. Only the database
row goes; files on disk, including partial files and the transfer's backup
directory, are not touched.

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
appears in the rows the model returns automatically. `json_valid` guards rows
written before the column held JSON. Filtering, searching and paging are all
applied in SQL; filtering used to happen after the limit, which meant a page of
recent completed transfers could hide every failed one.

The endpoints do not pass rows through as they are: `routes/transfers.py` picks
the fields each listing returns, so a new column reaches the page only once it
is named there. Who started a transfer (`started_by_kind`, `started_by_name`,
`started_by_account_id`), its route (`transport`), its queue reason and its sync
(`sync_run_id`) were missing from both `/transfers/all` and `/transfers/active`
until 2026-10-05 (`/transfers/active` had `queue_reason`), so the Transfers page
said "not recorded" for every transfer's starter and never showed the **Fast**
badge or the route. Both listings return them now, and a transfer's detail links
to its sync.

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
than the rows a browser happened to have loaded. Either way, every queued or
paused transfer among the rows is cancelled before anything is deleted, as for
a single delete (`Transfer.waiting_ids_among`, `waiting_ids_matching`).

Deleting `completed` records used to have a consequence beyond the list:
`get_sync_status` read them to decide the SYNCED / OUT_OF_SYNC badges in Browse
Media, so media covered by a deleted record showed as not yet synced. That
coupling is gone — both the badges and the method that produced them were retired
with Browse Media. Explore compares the two libraries directly, so what it says
does not depend on the transfer history surviving.

`Transfer.get_active()` is the one definition of "still in flight": `running`,
`pending`, `queued` and `paused`. `TransferCoordinator.get_active_transfers()`
delegates to it, so `/api/transfers/active` and the migration guard cannot
disagree about what active means.

Queued and paused count deliberately. Neither is writing this instant, but both
can start at any moment — which is what matters both to an operator reading the
Activity panel and to anything asking whether it is safe to move files.

**It was broken until 2026-08-01.** The body was `get_all(status_filter=None)` —
every transfer ever recorded — behind a docstring promising active ones, with a
comment saying filtering would happen in memory. It never did. Nothing called
it, so nothing noticed until the backup migration guard did and read a history
of ten completed transfers as ten running ones.

Both coordinator listing methods (`get_all_transfers`, `get_active_transfers`)
and `resume_active_transfers()` pass `include_logs=False`. The detail endpoints
(`/transfer/<id>/status`, `/transfer/<id>/logs`) use `Transfer.get()`, which does
select and parse the log body.

### 10. Startup recovery

Start-up runs in a fixed order, and the queue's own promotion waits until the
sync engine has looked at what the restart interrupted:

1. While the coordinator is built, the queue rebuilds its state from the
   database without starting anything
   (`QueueManager.force_unregister_stale_transfers(promote=False)`).
2. `TransferService.resume_active_transfers()`, also during construction: rows
   still marked `running` whose recorded PID is alive get a
   `_resume_transfer_monitoring()` thread; rows whose process is gone are marked
   `failed` with "Result unknown: DragonCP restarted while this was copying and
   could not read how rsync finished. …" (`UNKNOWN_RESULT_MESSAGE`) — the copy
   may have finished before DragonCP stopped, or been cut off with it.
3. `TransferCoordinator.start_background()`, which `app.py` calls once the
   connector layer is configured — so a result found at start-up can actually
   be announced — starts the `_post_transfer_completion()` watchers for all of
   those rows; they do the usual queue release, Finish and Tell, and backup
   sorting.
4. It then starts the sync engine, whose recovery
   (`services/sync_engine/recovery.py`) looks at every sync that was in flight.
5. Only then does the queue start whatever has a free slot and a free folder
   (`QueueManager.promote_waiting()`), so a copy started now goes through the
   engine's hooks like any other.

One gap, read from the code and not reproduced: the watchers of step 3 check
their transfer at once, and one whose transfer step 2 marked "Result unknown"
releases its queue slot straight away. Releasing a slot promotes queued work
(`QueueManager.unregister_transfer`), so a queued transfer can start in step 3,
before or during step 4. See [known issues](../../operations/known-issues.md),
under Syncing.

Recovery restarts nothing by itself:

- a sync whose transfer is still `queued` carries on; one already marked as
  copying is put back in the queue state;
- a transfer left `pending` — promoted, and about to start — is put back in the
  queue as a slot wait, and the queue's state is rebuilt again, without starting
  anything, so step 5 starts it normally. That holds whether its sync was still
  in the queue or had already been marked as copying; such a sync goes back to
  the queue too, instead of being called interrupted;
- a sync whose transfer had finished, failed or been cancelled is closed as
  usual. A transfer marked "Result unknown" in step 2 is one of these: the
  engine reads that wording and opens a *Result unknown* alert (**Retry**,
  **Mark as done**, **Dismiss**) instead of announcing "Sync failed";
- a reattached rsync is watched to the end, but its result cannot be read
  (Behaviour worth knowing), so it ends the same way: `failed`, "Result unknown",
  and the *Result unknown* alert;
- a sync that was still waiting or being checked, with no transfer yet, is
  marked interrupted with an *After a restart* alert.

Two things were different until 2026-10-05. The queue started queued work in
step 1, before recovery ran; a copy promoted then could still be `pending` when
recovery looked, and recovery marked its sync interrupted with a false "Some
syncs might have been skipped" alert. And step 2 recorded a dead rsync as
"Transfer process was interrupted", which the engine took for an ordinary
failure: "Sync failed" on Discord and a *Failed* alert.

See [Sync engine](../sync-engine/README.md), "After a restart".

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
- **After an app restart, a reattached transfer's result is unknown.**
  `_resume_transfer_monitoring()` cannot read the exit status of an rsync the
  restarted process did not start, so when it ends the row is marked `failed`
  with a message starting "Result unknown: DragonCP restarted while this was
  copying…" (`UNKNOWN_RESULT_MESSAGE`). A process already gone when monitoring
  attaches gets the same, and so, since 2026-10-05, does a `running` row whose
  rsync was already gone at start-up (section 10). The engine reads that
  wording and opens a *Result unknown* alert — **Retry**, **Mark as done**,
  **Dismiss**, announced on Discord under the `sync.interrupted` event — instead
  of a "Sync failed" message and a *Failed* alert. Until 2.3.0 the reattached
  path recorded the transfer as `completed`, so an rsync that failed after a
  restart could show as a success. A transfer with no sync run (from before the
  engine) is still reported as a plain failed sync, with the "Result unknown"
  sentence as its error.
- **Which restart case is the common one depends on how DragonCP stops.**
  Not verified: the committed systemd example sets no `KillMode`, and systemd's
  default stops every process in the service's control group, rsync included —
  so after a service restart rsync is normally already gone, and an rsync that
  outlived DragonCP's own process is the rarer case. Both now end as "Result
  unknown". Until 2026-10-05 the common case was recorded as "Transfer process
  was interrupted" and announced as an ordinary failed sync.
- **A restart is a new sync, not a re-run of the old one.** It runs the safety
  check first — bar the skips in the next bullet — so a restart can be refused
  by the dry run, and it waits its turn in the queue like anything else — it
  counts against `MAX_CONCURRENT_TRANSFERS`, takes the destination lock, and on
  finishing updates webhooks, announces the result and sorts its backups. Until 2.3.0 it started rsync directly and did
  none of that. The Transfers page shows the same row going back through
  `queued`/`pending`/`running`, because the row is reused; the sync behind it is
  new, linked to the one it retries.
- **Some syncs skip the safety check's dry run, and say why.** A restart of a
  simulated transfer skips it, as a fresh simulation does: a dry run against the
  media server could only fail for sandbox files that live on this machine. A
  restart of an Explore plan's transfer skips it: the retry copies the plan's
  own file list and deletes nothing, the plan was checked before it was
  approved, and a dry run of the whole season folder would judge a different
  copy. A single-file sync (`type=file`) skips it, because rsync deletes nothing
  when it is given one file. The Safety stage gives the reason in each case. A
  restarted simulation is not announced either, and opens no alert when it
  fails. Fixed 2026-10-05 — before, every restart and every single-file sync
  ran the folder dry run, against the media server even for a simulation's
  sandbox paths, and a restarted simulation was announced like real work.
- **A dry run that did not finish stops the sync.** rsync's exit status is read
  before its output: anything but 0, or 24 (files vanished mid-scan, as when
  Sonarr moves an import), makes the dry run unsafe with "The dry run did not
  finish (rsync exit N): <cause>", the cause being the first error line that
  names one ("ssh: Could not resolve hostname …") rather than rsync's closing
  `rsync error: … (code N)` summary or an ssh `Warning:` line. An unreachable
  media server or a missing source folder therefore stops the sync for a
  person. Fixed 2026-10-05 — before, only the output lines were read, and such a
  dry run reported zero files to copy and zero to delete, which passed.
- **A manual sync can be refused, quietly.** When the safety check stops one, no
  transfer is created; the run is "Stopped for a person" and a *Safety check*
  alert offers **Sync anyway** (also `POST /api/sync/runs/<run_id>/sync-anyway`).
  A sync a person started is not announced on Discord when refused — whether the
  press opened its own batch or released a webhook or auto-scanner batch that
  was still held or waiting. The refusal is on the Notifications page and on the
  sync's own page under Pipeline, each with **Sync anyway**, and any webhook on
  it reads **Manual**. The toast that answers the press is the server's own
  sentence on the Webhooks page, and "on their way — safety check first" on a
  Library tab, so it no longer claims a start the safety check then refuses;
  nothing appears on Transfers for a refused sync. Only a batch that started
  by itself is announced, which includes one a press joined after its ready
  check had already passed. Until 2026-10-05 a batch a press released was
  announced as an automatic refusal too, and until the Pipeline and
  Notifications pages arrived the same day such a refusal was visible only
  through the API.
- **A `pending` transfer cannot be cancelled.** `cancel_transfer()` handles
  `queued`, `paused` and `running` and returns `False` for anything else, so the
  API answers "Failed to cancel transfer" for a row in the brief `pending` window
  between admission and rsync starting, and a delete in that window removes the
  row without cancelling it.
- **Deleting a waiting transfer cancels it first.** A `queued` or `paused`
  transfer is cancelled before its row is deleted — by a single delete, a bulk
  delete by ids, or a bulk delete by filter — so its queue reservation is freed,
  whatever was waiting on that folder can be promoted, and its sync run closes
  as cancelled. Two safety nets cover a queued sync whose transfer row has gone
  anyway: the next request for that folder closes it as cancelled ("Its transfer
  was deleted from the transfer list before it started.") and opens a new
  batch, and **Cancel** on the run closes it directly. Fixed 2026-10-05 —
  before, the delete removed the row only: the reservation stayed until a
  restart, the sync stayed "In the queue" collecting later webhooks for that
  folder that never started, cancelling it failed, and a deleted paused
  transfer left its run showing Paused for good.
- **A single-file transfer lands in a folder named after the file.** For
  `type=file` the episode name is part of `dest_path`, which is created as a
  directory and handed to rsync with a trailing slash, so
  `Season 01/Example Show - S01E01.mkv` is copied to
  `Season 01/Example Show - S01E01.mkv/Example Show - S01E01.mkv` instead of over
  the episode. When the episode file already exists here, creating that folder
  fails and so does the transfer ("Failed to create destination: …"). The same
  code is on `main`. API-only: no screen sends `type=file`. See
  [known issues](../../operations/known-issues.md), under Syncing.
- **Transfer ids carry a random suffix.** The engine names a new transfer
  `<prefix>_<unix seconds>_<six hex characters>` — `transfer_` for a manual
  sync, `webhook_` and `series_webhook_` for Radarr and Sonarr, `scanner_` for
  the auto-scanner — so two syncs started in the same second no longer collide
  on the `UNIQUE` `transfer_id` column, as manual ones could when the id was
  `transfer_<unix seconds>`. A restart keeps the id it retries; Explore,
  simulations and restores bring their own.
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
- **Figures go to everyone; the log tail only to whoever is watching.**
  `transfer_progress` (the line, the log count and the stats) and
  `transfer_complete` are emitted to every connected client; the last 100 log
  lines travel as `transfer_logs` into the transfer's own room, and are not sent
  at all when nobody has subscribed.
- **There is no `transfer_failed` socket event.** Failures arrive as
  `transfer_complete` with `status: "failed"`, as `frontend/src/services/socket.ts`
  notes.
- **Simulation rows are real transfers.** They live in the same table and run the
  same code; only `is_simulation` tells them apart, and cleanup deletes by that
  flag — their sync runs included.

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
| `sync_run_id` | The sync run that owns the transfer: set at creation by the engine, and moved to the new run by `requeue_transfer()` on a restart. A row without one predates the engine and is finished the old way |
| `rsync_process_id` | Set when rsync starts, cleared on restart |
| `logs` | `Transfer.add_log()`, JSON array, collapsed and capped as described above |
| `progress_percent`, `bytes_transferred`, `total_bytes`, `speed_bps`, `eta_seconds` | Parsed by the monitor loop and folded into the same UPDATE as the log line |
| `paused_at` | Set on pause, cleared on resume and on a fresh rsync start |
| `start_time`, `end_time`, `created_at`, `updated_at` | Lifecycle timestamps |
| `is_simulation`, `simulation_bwlimit` | Simulation rows only |

`Transfer.get_sync_status()` and `get_folder_sync_status_summary()` used to
read this table to badge folders in Browse Media. Both were deleted with the
endpoints they served: a completed transfer row says a transfer once finished,
not that the files still match.

## API

All routes are registered under `/api` (`app.py`). Full request and response
contracts are in [../../reference/api.md](../../reference/api.md).

| Method | Path | Purpose |
|---|---|---|
| POST | `/transfer` | Ask for a manual sync. Answers with `run_id` and the run's state; `transfer_id` is `null`, because the transfer is created after the safety check |
| GET | `/transfer/{id}/status` | One transfer with progress figures and full log |
| GET | `/transfer/{id}/logs` | Stored log lines and count |
| POST | `/transfer/{id}/cancel` | Cancel a queued, paused or running transfer |
| POST | `/transfer/{id}/pause` | Stop rsync, keep partial files |
| POST | `/transfer/{id}/resume` | Continue a paused transfer, re-admitted through the queue |
| POST | `/transfer/{id}/restart` | Retry a failed, cancelled or completed transfer as a new sync: safety check, then the queue. Answers with `run_id`. Refuses a restore |
| POST | `/transfer/{id}/delete` | Delete the record (not while running); a queued or paused transfer is cancelled first |
| GET | `/transfers/all` | History page — `limit`, `offset`, `status`, `statuses`, `search` |
| GET | `/transfers/active` | Running/pending/queued/paused plus queue status |
| GET | `/transfers/queue/status` | Queue counters only |
| POST | `/transfers/bulk-delete` | Delete many records by id, or every record a filter finds; queued and paused ones are cancelled first |
| POST | `/transfers/cleanup` | Drop duplicate completed rows per destination |

Every endpoint is behind `@require_auth`. Socket events emitted from this
feature: `transfer_progress`, `transfer_complete` and `transfer_logs`
(`transfer_service.py`), `transfer_queued` (`transfer_coordinator.py`),
`transfer_promoted` (`queue_manager.py`). The sync run behind a transfer is
`GET /api/sync/lookup?transfer_id=<id>`; runs, their stages and alerts have
their own endpoints and socket events, listed in
[../sync-engine/README.md](../sync-engine/README.md).

## Related

- [../sync-engine/README.md](../sync-engine/README.md) — the pipeline a transfer is the copy step of: batching, the safety check, restart recovery, alerts
- [../queue/README.md](../queue/README.md) — admission, the destination lock, and promotion
- [../simulation/README.md](../simulation/README.md) — running this pipeline against local fixtures
- [../../architecture/system-overview.md](../../architecture/system-overview.md) — where transfers sit in the system
- [../../reference/api.md](../../reference/api.md) — full endpoint contracts
- [../../reference/database-schema.md](../../reference/database-schema.md) — the `transfers` table
- [../../reference/test-mode.md](../../reference/test-mode.md) — what `TEST_MODE` guarantees, path by path
