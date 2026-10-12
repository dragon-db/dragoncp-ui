# DragonCP Custom Sync Application: Logic and Implementation Analysis

Last updated: 2026-10-05
Scope: Backend sync application only (`frontend/` excluded)

Code is referenced by file and symbol rather than by line number, because line
numbers in this codebase move with every change.

## 1. What This System Is Doing

DragonCP is a Flask-based sync orchestrator for media libraries that:
- Receives Radarr/Sonarr webhooks.
- Runs every sync — webhook, scheduled auto-scanner, manual, Explore, restart, restore, simulation — through one nine-stage pipeline, the sync engine, which keeps each sync in the database stage by stage.
- Runs `rsync` from remote source paths to local destination paths.
- Applies queue controls for folder conflicts (the same folder, or one inside the other) and concurrency limits.
- Performs a dry-run safety check before every sync, except where a kind's own review already did it (Explore, restore), there is nothing on the media server to check (simulation, a restarted one included), or the copy cannot delete anything (a single-file sync, a retried Explore plan's file list). A dry run rsync could not finish fails the check.
- Opens alerts for what needs a person — a refused or failed sync, work a restart interrupted — most of which are also announced on Discord. The web app's Notifications page lists them (`/api/alerts`), and its Transfers page shows every sync stage by stage (`/api/sync/runs`) — inside each transfer, and for syncs that never became one.
- Persists transfer/webhook/sync/alert/backup state in SQLite.
- Streams progress to clients over authenticated WebSocket.

Core bootstrap and wiring happen in `app.py`: the `TransferCoordinator` is built
with the database and Socket.IO, the routes are initialised, the connector layer
is configured, and only then does `transfer_coordinator.start_background()` start
the sync engine (whose start-up recovery runs first), the completion watchers,
the queue's waiting work and the scheduler — so what they find at start-up can
be announced, and nothing the queue starts is mistaken for a copy the restart
interrupted. Blueprints are registered under `/api`.

## 2. High-Level Runtime Architecture

Main layers and responsibilities:
- API layer: Flask routes in `routes/` accept commands and webhooks.
- Orchestration layer, in two parts:
  - The sync engine (`services/sync_engine/`, `SyncEngine`) decides when each sync becomes a transfer and records what every stage did. Every way a sync starts enters through `SyncEngine.submit()`, except a restart (`restart_transfer()`) and a restore, which the backups service runs itself and records on the engine (`begin_restore`). See `../features/sync-engine/README.md`.
  - `TransferCoordinator` (`services/transfer_coordinator.py`) owns the queue and the transfer lifecycle, and calls back into the engine at each step (`before_transfer_start`, `on_transfer_started`, `on_transfer_paused`, `on_transfer_resumed`, `on_transfer_finished`).
- Domain services: transfer execution, queueing, webhook parsing, alerts, the scheduler and its auto-scanner jobs, backup, notifications, path mapping.
- Persistence layer: SQLite models in `models/`.
- Real-time layer: Socket.IO with auth and stale-session cleanup (`register_websocket_handlers`, `start_cleanup_thread` and `reap_stale_connections` in `websocket.py`).

## 3. Core Sync Flows

Every flow below except the rename-only one enters the sync engine and passes
the same stages — Receive, Identify, Batch, Ready check, Safety check, Queue,
Transfer, Finish, Tell — with each kind running a stage differently or skipping
it, and saying why (`KINDS` in `services/sync_engine/stages.py`).

### 3.1 Manual Transfer Flow

Entry point: `api_transfer` in `routes/transfers.py`.

Flow:
1. API receives media type, folder, optional season (and an episode for a file transfer — which currently lands in a folder named after the file; see `../operations/known-issues.md`).
2. Source and destination paths are constructed from configured base paths, and the destination is checked against its base (`assert_path_within_bounds`).
3. The request is submitted to the engine as kind `manual` (`SyncEngine.submit`); the answer carries the `run_id`. A batch already open for the same folder is joined — and told to go now if it is still waiting — instead of a second transfer starting.
4. The ready check is skipped; the dry-run safety check runs (not for a single file, where rsync deletes nothing); the Queue stage hands the run to `TransferCoordinator.start_transfer` with a generated transfer id.
5. Queue manager enforces folder-conflict checks and concurrent slot limits (`QueueManager.check_duplicate_destination`, `register_transfer`).
6. If runnable, `TransferService.start_rsync_process` starts `rsync` and `_monitor_transfer` follows it.
7. On completion/failure, `_post_transfer_completion` releases the queue slot and calls the engine's `on_transfer_finished`: Finish marks the sync's webhooks, Tell sends the Discord notification and opens an alert for a failure; the coordinator then sorts the backup.

### 3.2 Movie Webhook Flow (Radarr)

Entry point: `api_webhook_movies_receiver` in `routes/webhooks.py`.

Flow:
1. Route authenticates (`require_webhook_auth`), validates payload and test events.
2. Webhook payload is parsed into normalized notification fields (`WebhookService.parse_webhook_data`).
3. Notification is persisted in `radarr_webhook`.
4. The title is indexed (`TransferCoordinator.index_notification`) and the notification submitted to the engine as kind `radarr_webhook` (`_submit_webhook`) — always; with `AUTO_SYNC_MOVIES` off the batch is held for a person.
5. Destination path is resolved through `PathService.get_destination_path` for consistency; the notification joins any open batch for the same movie folder.
6. The ready check is skipped (one webhook is one finished movie); the dry-run safety check runs; then the queue.
7. Notification status follows the sync: `READY_FOR_TRANSFER`, then `QUEUED_*` or `syncing`, then `completed`/`failed`.

### 3.3 Series/Anime Webhook Flow (Sonarr)

Entry points: `api_webhook_series_receiver` and `api_webhook_anime_receiver` in `routes/webhooks.py`.

Flow:
1. Route handles test events, then checks if event type is rename.
2. Non-rename events are parsed with series/anime metadata (`WebhookService.parse_series_webhook_data`).
3. Notification is persisted in `sonarr_webhook`.
4. The title is indexed and the notification submitted to the engine as kind `sonarr_webhook` — always; held when the library's auto-sync switch is off.
5. Batched by destination season folder: it joins an open batch, or the single follow-up batch behind a copy in progress, or opens one. Batches are `sync_run` rows, so a restart does not lose them.
6. Ready check: Sonarr is asked whether anything for the season is still downloading — 10 s after the batch opens, then by Sonarr's own time-left estimate (10 s to 5 min apart), at most 30 minutes; stuck downloads do not hold the season. When Sonarr cannot be asked, the fallback wait decides (`SERIES_ANIME_SYNC_WAIT_TIME`, plus the same per later webhook, at most 15 minutes).
7. If the dry run passes, the batch becomes one transfer and every notification on it gets that transfer id.
8. If the dry run fails — or could not finish — the sync is refused: notifications are flagged `requires_manual_sync`, and a *Safety check* alert offers Sync anyway, announced on Discord as `autosync.blocked` unless a person released the batch with Sync or Go now (`SyncEngine._refuse`, `AlertService.sync_refused`).

### 3.4 Rename-Only Flow

Entry points: the `Rename` branch inside `api_webhook_series_receiver` and `api_webhook_anime_receiver`.

Flow:
1. Sonarr rename events are routed to `RenameService` (`services/rename_service.py`).
2. Relative remote paths are mapped to local filesystem paths via media base path.
3. Local rename operations execute immediately (no sync engine, no transfer queue).
4. Results are persisted in `rename_webhook` and optionally sent as Discord notifications.

## 4. Queueing and Concurrency Logic

Queue manager (`QueueManager` in `services/queue_manager.py`) enforces two constraints:
- Folder exclusivity: no two active transfers whose destinations are the same folder or one inside the other (`QueueManager._overlaps`). Two different seasons of a show may copy together; a whole-series copy waits for any of its seasons, and the other way round.
- Global concurrency cap: `MAX_CONCURRENT_TRANSFERS = 3` (`QueueManager.MAX_CONCURRENT_TRANSFERS`).

Queue states represented through transfer + webhook state coupling:
- `QUEUED_PATH`: waiting for a colliding folder to be freed.
- `QUEUED_SLOT`: waiting on global slot availability.

Implementation details now in place:
- queued transfer rows persist `queue_reason` (`path` or `slot`) in `transfers`
- same-folder promotions re-register queue ownership before rsync starts
- startup rebuilds running transfer reservations from DB before resuming monitors, then gives queued transfers theirs oldest first, one owner per set of colliding folders, so two queued transfers cannot block each other (`_restore_queued_reservations_internal`); the rebuild starts nothing (`force_unregister_stale_transfers(promote=False)`), and queued work is promoted only after the sync engine's recovery has run (`QueueManager.promote_waiting`, in `TransferCoordinator.start_background`), so recovery does not mistake a copy the queue is just starting for one the restart cut off — bar the completion-watcher gap recorded in `../operations/known-issues.md`
- deleting a queued or paused transfer cancels it first, freeing its reservation and closing its sync (`_cancel_before_delete` in `routes/transfers.py`)
- a restart reuses its transfer row and goes through the same two checks (`TransferCoordinator.requeue_transfer`); it no longer starts rsync directly
- the sync engine is told when a queued transfer starts (`before_transfer_start`) and when a slot wait is re-filed as a folder wait (`on_transfer_waiting`)

Promotion behavior:
- Folder promotion first (`_promote_same_path_queued`), over queued transfers that collide with the freed folder, taking the first that is no longer blocked.
- General slot promotion second (`_promote_next_queued_transfer`).

This design prioritizes correctness on folder conflicts and avoids parallel writes to the same target folder, or to a folder and one inside it. Details: `../features/queue/README.md`.

## 5. Transfer Execution and Safety Model

`TransferService` runs and monitors `rsync` processes (`services/transfer_service.py`).

**Two routes to the media host.** Before rsync starts, `resolve_route()` decides
whether to pull over the transfer server installed on the media host — about
three times faster, because SSH caps itself at roughly 13 MB/s on this 154 ms
link — or over SSH as before. Only the source address and two arguments differ;
every other flag is identical, which is why the backups, deletions, queueing and
progress parsing below are unaffected by the choice. Anything that makes the
faster route unavailable falls back to SSH rather than failing, and the route
that ran is recorded on the transfer. See
`../features/fast-transfers/README.md`.

Safety and behavior choices currently implemented:
- Uses `--delete` for destination convergence.
- Uses `--size-only` and disables checksums for speed.
- Disables file permission/owner/group propagation.
- Uses partial transfer directory and backup directory support.
- Uses `--info=progress2`, so progress reflects the whole transfer rather than
  the file currently in flight. Each progress line is parsed into
  percent/bytes/speed/ETA and stored in dedicated columns
  (`parse_rsync_progress`); the exact total replaces the derived estimate once
  `--stats` reports it.

Progress lines are not accumulated into the log. Each one supersedes the last,
so consecutive progress lines collapse to the newest and their database writes
are throttled; the socket still emits every one from an in-memory tail. Durable
output - file names, the `--stats` block, warnings and errors - is kept in full.
Against the transfers on record this took stored log lines from 149,317 to
13,752. See `../plans/rsync-log-streaming.md`.

Pause and resume: rsync cannot be suspended in place because the command sets
`--timeout=300`, so a frozen process loses its connection after five minutes.
A pause stops rsync and relies on `--partial`/`--partial-dir`, which are already
part of the command, so the resumed run continues from the partial files.

Cancel and pause both terminate rsync, which exits non-zero. `TransferService`
records the intent before signalling so the monitor thread reports the real
outcome rather than overwriting it with `failed`.

After a DragonCP restart, an rsync that survived is reattached, but its exit
status cannot be read; the transfer is then marked `failed` with a message
starting "Result unknown", and the engine raises a *Result unknown* alert rather
than reporting a failed sync (`UNKNOWN_RESULT_MESSAGE` in
`services/transfer_service.py`). A `running` transfer whose rsync is already
gone at start-up is marked the same way (`resume_active_transfers`).

The same execution path runs simulated transfers, pointed at local fixture files
instead of over SSH and held to a bandwidth ceiling. See
`../features/simulation/README.md`.

Dry-run validation (`TransferService.perform_dry_run_rsync`), run by the sync
engine's Safety check stage, computes:
- Incoming media files.
- Deletions.
- Estimated server/local file count comparison.
- Safety decision (`safe_to_sync`) with reason string: unsafe first when rsync did not finish — an exit code other than 0 or 24, reported with the first error line that names a cause (not rsync's closing `rsync error:` summary or an ssh `Warning:`) and `rsync_exit_code` — then when the media server lists fewer media files than this disk holds, or when it would delete more media files than it brings in.

## 6. Persistence Model and State Tracking

Database initialization and schema are centralized in `DatabaseManager.init_database` (`models/database.py`).

Primary tables:
- `transfers`: transfer lifecycle, parsed progress figures, logs, and the sync run that owns each transfer (`sync_run_id`).
- `radarr_webhook`: movie notifications.
- `sonarr_webhook`: series/anime notifications with manual-sync and dry-run fields.
- `rename_webhook`: rename operation outcomes.
- `sync_run`, `sync_run_stage`, `sync_run_event`: one row per sync, its nine stages, and each stage's log lines (`models/sync_run.py`). Both webhook tables point at the sync a notification rides on through `sync_run_id`.
- `alert`: what needs a person (`models/alert.py`); `scheduled_job`: each background job's last run.
- `backup` and `backup_file`: per-transfer backup metadata and context-aware restore mapping.
- `app_settings`: runtime toggles and notification configuration.

The `SeriesWebhookNotification` docstring in `models/webhook.py` describes the
intended notification states; which ones are actually written, and by what, is
in `../features/webhooks/README.md`.

Important current-state notes:
- manual-sync-required rows are still stored as `pending` plus `requires_manual_sync=1`, in both webhook tables since 2026-10-05 — written by the engine for a refused sync and for one a restart interrupted; the explicit `MANUAL_SYNC_REQUIRED` status is planned but not yet normalized end-to-end.
- batches are in the database: a restart does not lose a waiting batch, but does not resume it either — recovery (`services/sync_engine/recovery.py`) marks it interrupted and opens an alert.
- listing queries exclude the `logs` column and count it in SQL, and filter by
  status in SQL. Only the detail and log endpoints read log bodies. See
  `../reference/database-schema.md`.

## 7. Backup and Restore Logic

Sorting runs after a transfer settles (`services/transfer_coordinator.py`,
`_post_transfer_completion`, calling `BackupsService.sort_after_transfer`).

Implementation (`services/backups/`):
- rsync's `--backup-dir` writes into `<BACKUP_PATH>/.staging/<transfer id>`.
- Everything it displaced is identified and renamed into an identity tree —
  `<library>/<title>/<season>/<SxxEyy>/<capture>/` — so a movie or episode's
  previous versions sit together in one folder.
- The database is an index over that tree, not the source of truth, and can be
  rebuilt by walking the disk.
- A restore keeps the file it is about to replace before writing anything, and
  claims its folder through the queue's checks — but refuses rather than waits
  when the folder is busy or every slot is taken. It is recorded as a sync of
  kind `restore`.
- Retention keeps the newest N versions per slot.

The sort is a set of renames within one filesystem, so it costs a directory walk
and no data movement regardless of file size.

## 8. QoS and Performance Improvement Opportunities

## Priority A (high impact)

1. Replace per-log-line full JSON rewrites for transfer logs.
- Current behavior: every durable rsync output line, and at most one progress line a second, calls `Transfer.add_log` (`models/transfer.py`), which reads the full log array and writes it back; driven by `TransferService._monitor_transfer`.
- Impact: high SQLite write amplification and increasing latency as logs grow.
- Improvement: move logs to append-only table or buffered batch writes (for example every 250-500 ms / N lines).

2. Remove O(N) notification scans in Discord notification path.
- Current behavior: `NotificationService._webhook_context`, used by `send_discord_notification`, loads every row of the notification table (`get_all()`) and scans it for the transfer id.
- Impact: response slowdown as webhook history grows.
- Improvement: use the indexed lookups already available, `WebhookNotification.get_by_transfer_id` and `SeriesWebhookNotification.get_by_transfer_id` in `models/webhook.py`.

3. Replace polling completion watcher with event-driven completion propagation.
- Current behavior: the coordinator polls transfer status every 5 seconds per transfer (`TransferCoordinator._post_transfer_completion`), and the sync engine's Finish and Tell stages run from that watcher, so they trail a transfer's end by up to 5 seconds.
- Impact: unnecessary DB load and delayed downstream actions.
- Improvement: emit coordinator callback directly from transfer monitor completion path (`TransferService._monitor_transfer`).

4. Persist scheduler jobs across restarts.
- Done (2026-10-05): batches are `sync_run` rows, written as they change, and the in-memory scheduler (`services/auto_sync_scheduler.py`) was deleted. A restart marks a batch that was waiting as interrupted and opens an alert instead of resuming it — on purpose: nothing restarts behind anyone's back.

## Priority B (correctness and state quality)

5. Normalize manual-sync-required status semantics.
- Current behavior: the engine's refusal (`SyncEngine._refuse`) and restart recovery (`_interrupt` in `services/sync_engine/recovery.py`) keep status as `pending` plus `requires_manual_sync`, while model documentation expects an explicit manual-required state (`SeriesWebhookNotification` docstring). The notification list translates a `MANUAL_SYNC_REQUIRED` filter into the flag (`NotificationCatalog`), on the series table only — the movie table has carried the same flag since 2026-10-05, but the filter does not read it.
- Impact: operator ambiguity and filtering complexity.
- Improvement: introduce and consistently use a single explicit status for manual intervention.

6. Fix transfer API return-contract mismatch.
- Resolved: `POST /api/transfer` answers from the engine's result — `run_id`, the run's state and its message. The transfer is created after the safety check, so `transfer_id` is `null` in that answer.

7. Add idempotency guard for manual transfer ID generation.
- Resolved: the engine names transfers `<prefix>_<unix seconds>_<six hex characters>` (`SyncEngine._transfer_id_for`), and a second request for the same folder joins the first one's batch while it has not started copying.

## Priority C (operational QoS)

8. Add adaptive concurrency and backpressure.
- Current behavior: fixed global concurrency of 3 (`QueueManager.MAX_CONCURRENT_TRANSFERS`).
- Improvement: dynamic slots based on IO wait, disk usage, and destination saturation signals.

9. Improve dry-run confidence model.
- Current behavior: rsync's exit status is checked first — since 2026-10-05 a dry run rsync could not finish (exit other than 0 or 24) is unsafe, where before it reported zero changes and passed — then safety uses file counts and delete/incoming comparison.
- Improvement: add configurable guardrails (maximum delete ratio, protected extensions, minimum confidence threshold) and record validation decision metadata for audit.

10. Add structured observability.
- Current behavior: console prints and the activity trail, plus — since the sync engine — a per-sync, per-stage log in the database (`sync_run_event`) with the run id as a correlation id. Transfers themselves still log mostly to the console.
- Improvement: structured logs with correlation IDs (`run_id`, `transfer_id`, `notification_id`), latency metrics (queue wait, rsync duration, dry-run duration), and failure taxonomy.

11. Reduce heavy `get_all()` usage in queue transitions.
- Current behavior: queue promotions load every queued transfer (`get_all(statuses=['queued'])`) and filter by folder in Python (`_promote_same_path_queued`, `_promote_next_queued_transfer`).
- Improvement: targeted indexed queries by status/path and FIFO timestamp.

## 9. Recommended Next Refactor Sequence

1. Logging storage redesign (`transfers_log` table or buffered append) and notification lookup optimization.
2. Event-driven completion callbacks and queue-promotion query optimization.
3. Explicit manual-sync status normalization. (Scheduler persistence, completion by batch membership, the manual transfer endpoint's answer and its id generation arrived with the sync engine; a dry run that fails when rsync could not run followed on 2026-10-05.)
4. Observability and adaptive QoS policy rollout.

## 10. Summary

The current design is strong on workflow coverage and functional correctness for mixed manual + webhook sync scenarios, especially around folder-conflict queueing and per-folder batching, and since the sync engine every sync leaves a stage-by-stage record that survives a restart. The largest risks now are scalability and state consistency under growth: SQLite write amplification from logs, full-table scans in runtime paths, and a state inconsistency — the manual-sync flag kept beside a `pending` status rather than as a status of its own — that can affect operational clarity.
