# DragonCP Custom Sync Application: Logic and Implementation Analysis

Last updated: 2026-02-16
Scope: Backend sync application only (`frontend/` excluded)

## 1. What This System Is Doing

DragonCP is a Flask-based sync orchestrator for media libraries that:
- Receives Radarr/Sonarr webhooks.
- Converts webhook payloads into normalized sync jobs.
- Runs `rsync` from remote source paths to local destination paths.
- Applies queue controls for destination conflicts and concurrency limits.
- Performs dry-run safety validation for series/anime auto-sync.
- Persists transfer/webhook/backup state in SQLite.
- Streams progress to clients over authenticated WebSocket.

Core bootstrap and wiring happen in `app.py:90`, `app.py:101`, `app.py:115`, and route registration at `app.py:119`.

## 2. High-Level Runtime Architecture

Main layers and responsibilities:
- API layer: Flask routes in `routes/` accept commands and webhooks.
- Orchestration layer: `TransferCoordinator` coordinates all sync-related workflows (`services/transfer_coordinator.py:26`).
- Domain services: transfer execution, queueing, webhook parsing, scheduler, backup, notifications, path mapping.
- Persistence layer: SQLite models in `models/`.
- Real-time layer: Socket.IO with auth and stale-session cleanup (`websocket.py:46`, `websocket.py:115`).

## 3. Core Sync Flows

### 3.1 Manual Transfer Flow

Entry point: `routes/transfers.py:27`.

Flow:
1. API receives media type, folder, optional season.
2. Source and destination paths are constructed from configured base paths.
3. Transfer is submitted to coordinator via `start_transfer` (`services/transfer_coordinator.py:69`).
4. Queue manager enforces duplicate destination checks and concurrent slot limits (`services/queue_manager.py:113`).
5. If runnable, transfer service starts `rsync` (`services/transfer_service.py:259`) and monitoring thread (`services/transfer_service.py:425`).
6. On completion/failure, coordinator updates webhook linkage (if any), backup finalization, and Discord notifications (`services/transfer_coordinator.py:218`).

### 3.2 Movie Webhook Flow (Radarr)

Entry point: `routes/webhooks.py:33`.

Flow:
1. Route validates payload and test events.
2. Webhook payload is parsed into normalized notification fields (`services/webhook_service.py:23`).
3. Notification is persisted in `radarr_webhook`.
4. If auto-sync enabled, coordinator triggers transfer immediately through `trigger_webhook_sync` (`services/webhook_service.py:261`).
5. Destination path is resolved through `PathService` for consistency (`services/path_service.py:27`).
6. Transfer and webhook status evolve together via transfer-status mapping (`services/webhook_service.py:524`).

### 3.3 Series/Anime Webhook Flow (Sonarr)

Entry points: `routes/webhooks.py:125` and `routes/webhooks.py:227`.

Flow:
1. Route handles test events, then checks if event type is rename.
2. Non-rename events are parsed with series/anime metadata (`services/webhook_service.py:122`).
3. Notification is persisted in `sonarr_webhook`.
4. If auto-sync enabled, job is scheduled for batching/wait window (`services/auto_sync_scheduler.py:49`).
5. Scheduler batches notifications by series+season key, extends wait time, then executes dry-run (`services/auto_sync_scheduler.py:161`).
6. If dry-run passes, state transitions to `READY_FOR_TRANSFER`, then transfer starts/queues.
7. If dry-run fails safety checks, notification is flagged for manual intervention (`services/transfer_coordinator.py:504`) and Discord alert can be sent (`services/transfer_coordinator.py:520`).

### 3.4 Rename-Only Flow

Entry points: `routes/webhooks.py:166` and `routes/webhooks.py:268`.

Flow:
1. Sonarr rename events are routed to `RenameService` (`services/rename_service.py`).
2. Relative remote paths are mapped to local filesystem paths via media base path.
3. Local rename operations execute immediately (no transfer queue).
4. Results are persisted in `rename_webhook` and optionally sent as Discord notifications.

## 4. Queueing and Concurrency Logic

Queue manager (`services/queue_manager.py:13`) enforces two constraints:
- Path exclusivity: only one active transfer per normalized destination path.
- Global concurrency cap: `MAX_CONCURRENT_TRANSFERS = 3` (`services/queue_manager.py:17`).

Queue states represented through transfer + webhook state coupling:
- `QUEUED_PATH`: waiting on same destination path to be freed.
- `QUEUED_SLOT`: waiting on global slot availability.

Promotion behavior:
- Path-specific promotion first (`services/queue_manager.py:190`).
- General slot promotion second (`services/queue_manager.py:270`).

This design prioritizes correctness on path conflicts and avoids parallel writes to the same target folder.

## 5. Transfer Execution and Safety Model

`TransferService` runs and monitors `rsync` processes (`services/transfer_service.py:259`, `services/transfer_service.py:425`).

Safety and behavior choices currently implemented:
- Uses `--delete` for destination convergence.
- Uses `--size-only` and disables checksums for speed.
- Disables file permission/owner/group propagation.
- Uses partial transfer directory and backup directory support.

Dry-run validation (`services/transfer_service.py:26`) computes:
- Incoming media files.
- Deletions.
- Estimated server/local file count comparison.
- Safety decision (`safe_to_sync`) with reason string.

## 6. Persistence Model and State Tracking

Database initialization and schema are centralized in `models/database.py:19`.

Primary tables:
- `transfers`: transfer lifecycle and logs.
- `radarr_webhook`: movie notifications.
- `sonarr_webhook`: series/anime notifications with batch and dry-run fields.
- `rename_webhook`: rename operation outcomes.
- `backup` and `backup_file`: per-transfer backup metadata and context-aware restore mapping.
- `app_settings`: runtime toggles and notification configuration.

State transitions for series/anime notifications are documented in model comments (`models/webhook.py:189`).

## 7. Backup and Restore Logic

Backup finalization occurs after transfer completion (`services/transfer_coordinator.py:218` calling backup service).

Backup implementation (`services/backup_service.py`):
- Scans transfer-specific backup directories.
- Records backed-up files with context metadata.
- Supports restore planning with context matching before copy.
- Supports reindexing existing backup folders.

This design improves recoverability but adds filesystem walk overhead after each transfer.

## 8. QoS and Performance Improvement Opportunities

## Priority A (high impact)

1. Replace per-log-line full JSON rewrites for transfer logs.
- Current behavior: every rsync output line calls `add_log`, which reads full log array and writes it back (`models/transfer.py:219`), driven by monitor loop (`services/transfer_service.py:425`).
- Impact: high SQLite write amplification and increasing latency as logs grow.
- Improvement: move logs to append-only table or buffered batch writes (for example every 250-500 ms / N lines).

2. Remove O(N) notification scans in Discord notification path.
- Current behavior: `send_discord_notification` scans all webhook rows (`services/notification_service.py:162`, `services/notification_service.py:179`).
- Impact: response slowdown as webhook history grows.
- Improvement: use existing indexed lookup methods (`get_by_transfer_id`) already available in `models/webhook.py:112` and `models/webhook.py:370`.

3. Replace polling completion watcher with event-driven completion propagation.
- Current behavior: coordinator polls transfer status every 5 seconds per transfer (`services/transfer_coordinator.py:218`).
- Impact: unnecessary DB load and delayed downstream actions.
- Improvement: emit coordinator callback directly from transfer monitor completion path (`services/transfer_service.py:425`).

4. Persist scheduler jobs across restarts.
- Current behavior: jobs live in memory only (`services/auto_sync_scheduler.py:32`, `services/auto_sync_scheduler.py:49`).
- Impact: restart can drop pending auto-sync windows.
- Improvement: persist scheduled jobs in DB and recover on startup.

## Priority B (correctness and state quality)

5. Normalize manual-sync-required status semantics.
- Current behavior: `mark_for_manual_sync` keeps status as `pending` plus flags (`services/transfer_coordinator.py:504`), while model documentation expects explicit manual-required terminal state (`models/webhook.py:189`).
- Impact: operator ambiguity and filtering complexity.
- Improvement: introduce and consistently use a single explicit status for manual intervention.

6. Fix transfer API return-contract mismatch.
- Current behavior: route expects boolean (`routes/transfers.py:95`, `routes/transfers.py:105`) but coordinator returns tuple `(success, queue_state)` (`services/transfer_coordinator.py:69`).
- Impact: potential false-positive success handling and inconsistent API semantics.
- Improvement: align contract and expose queue outcome explicitly in response.

7. Add idempotency guard for manual transfer ID generation.
- Current behavior: manual transfer IDs use second precision (`routes/transfers.py:92`), risking collisions under burst requests.
- Improvement: move to UUID or monotonic + random suffix.

## Priority C (operational QoS)

8. Add adaptive concurrency and backpressure.
- Current behavior: fixed global concurrency of 3 (`services/queue_manager.py:17`).
- Improvement: dynamic slots based on IO wait, disk usage, and destination saturation signals.

9. Improve dry-run confidence model.
- Current behavior: safety uses file counts and delete/incoming comparison.
- Improvement: add configurable guardrails (maximum delete ratio, protected extensions, minimum confidence threshold) and record validation decision metadata for audit.

10. Add structured observability.
- Current behavior: mostly console prints.
- Improvement: structured logs with correlation IDs (`transfer_id`, `notification_id`), latency metrics (queue wait, rsync duration, dry-run duration), and failure taxonomy.

11. Reduce heavy `get_all()` usage in queue transitions.
- Current behavior: queue promotions repeatedly load all transfers then filter in memory (`services/queue_manager.py:190`, `services/queue_manager.py:270`).
- Improvement: targeted indexed queries by status/path and FIFO timestamp.

## 9. Recommended Next Refactor Sequence

1. Logging storage redesign (`transfers_log` table or buffered append) and notification lookup optimization.
2. Event-driven completion callbacks and queue-promotion query optimization.
3. Scheduler persistence and state normalization (`MANUAL_SYNC_REQUIRED` consistency).
4. API contract cleanup for manual transfer endpoint and improved id generation.
5. Observability and adaptive QoS policy rollout.

## 10. Summary

The current design is strong on workflow coverage and functional correctness for mixed manual + webhook sync scenarios, especially around path-conflict queueing and series/anime batching. The largest risks now are scalability and state consistency under growth: SQLite write amplification from logs, full-table scans in runtime paths, in-memory scheduler volatility, and a few state/contract inconsistencies that can affect operational clarity.
