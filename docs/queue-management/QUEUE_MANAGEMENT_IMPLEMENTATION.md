# Queue Management Implementation

Last updated: 2026-03-19
Primary files: `services/queue_manager.py`, `services/transfer_coordinator.py`, `services/transfer_service.py`, `models/transfer.py`, `models/database.py`

## Purpose

DragonCP uses one shared queue system for manual syncs, movie webhooks, and series/anime syncs.

The queue system enforces two runtime guarantees:
- only one transfer may write to a normalized destination path at a time
- only `MAX_CONCURRENT_TRANSFERS` transfers may run at once (`3` today)

## Current Queue Model

### Transfer-level states

Transfer rows in `transfers` use these statuses:
- `pending`: admitted and preparing to start
- `queued`: not allowed to start yet
- `running`: rsync process active
- `completed`
- `failed`
- `cancelled`

Queued transfer rows use `queue_reason` for the blocking reason:
- `path`: same destination path already reserved by another transfer
- `slot`: concurrency cap reached

`queue_reason` is persisted in the `transfers` table and is now added automatically for older databases during startup.

### Webhook-level states

Series/anime webhook rows in `sonarr_webhook` expose the queue reason more explicitly:
- `READY_FOR_TRANSFER`
- `QUEUED_SLOT`
- `QUEUED_PATH`
- `syncing`
- `completed`
- `failed`
- `cancelled`

Movie webhook rows do not currently expose queue-reason-specific states; they still share the same transfer queue internally.

## In-Memory Queue State

`QueueManager` maintains two process-local maps:
- `active_destinations`: `{normalized_dest_path: transfer_id}`
- `running_transfers`: `{transfer_id: normalized_dest_path}`

These maps are the live path-lock and running-slot authority used during admission and promotion.

## Admission Flow

All new transfers converge through `TransferCoordinator.start_transfer()`.

### 1. Path-conflict check

`QueueManager.check_duplicate_destination()` checks whether the normalized destination path is already reserved.

If the path is already owned:
- the new transfer row is created with `status='queued'`
- `queue_reason='path'`
- the transfer returns as `QUEUED_PATH`
- for series/anime, linked webhook notifications are updated to `QUEUED_PATH`

### 2. Slot-cap check

If the path is free, `QueueManager.register_transfer()` decides whether the transfer can run immediately.

If all slots are full:
- the new transfer row is created with `status='queued'`
- `queue_reason='slot'`
- the destination is still reserved in `active_destinations`
- the transfer returns as `QUEUED_SLOT`

That destination reservation is intentional: it prevents later transfers for the same path from being admitted ahead of the already-queued owner.

### 3. Immediate start

If both the path and slot checks pass:
- the transfer is registered in `active_destinations` and `running_transfers`
- the transfer row is created with `status='pending'`
- `TransferService.start_rsync_process()` starts rsync and then updates the row to `running`

## Promotion Flow

Promotion happens from `QueueManager.unregister_transfer()` after a running transfer finishes, fails, or is cancelled.

Promotion order is always:
1. same-path queue first
2. general slot queue second

### Path-specific promotion

`_promote_same_path_queued(dest_path)`:
- looks for queued transfer rows whose normalized `dest_path` matches the freed path
- prefers transfers that are explicitly or implicitly path-queued
- re-checks the path lock for safety
- re-registers the promoted transfer in `active_destinations` and `running_transfers`
- hands it off to `TransferCoordinator.start_queued_transfer()`

`start_queued_transfer()` then performs the visible state transitions (`queued` -> `pending` and `QUEUED_*` -> `syncing`) only after queue ownership has been confirmed.

This re-registration step is the fix for issue `#40`: a same-path promoted transfer must reclaim in-memory queue ownership before rsync starts, otherwise a later transfer can incorrectly see the path as free.

### General slot promotion

`_promote_next_queued_transfer()`:
- scans queued transfer rows oldest-first
- determines queue type from `queue_reason` first, then falls back to `progress` parsing for legacy rows
- re-checks path ownership before promotion

If a queued slot transfer now conflicts with a running transfer on the same destination:
- it is converted from `queue_reason='slot'` to `queue_reason='path'`
- its `progress` text is updated
- linked series/anime webhooks move from `QUEUED_SLOT` to `QUEUED_PATH`
- it stays queued until the same path is freed

If a queued transfer is promotable:
- queue state is reserved before start
- the transfer is started through `start_queued_transfer()`

## Defensive Start Guard

`TransferCoordinator.start_queued_transfer()` now verifies that the promoted transfer is already represented in queue-manager running state before it starts rsync.

This prevents untracked queued promotions from bypassing path ownership rules.

## Startup and Restart Recovery

Queue state is process-local, so startup now rebuilds it from the database.

Current startup flow:
1. `QueueManager.force_unregister_stale_transfers()` removes stale in-memory entries
2. the same method rebuilds running reservations from DB rows with `status='running'`
3. `TransferService.resume_active_transfers()` resumes monitoring for live rsync PIDs
4. `TransferCoordinator` restarts post-completion watchers for resumed transfers so queue release, webhook status updates, Discord notifications, and backup finalization still happen

This recovery closes the gap where a restarted app could have running rsync processes but no in-memory path reservations.

## Queue Reason Behavior

### Current behavior

- `queue_reason` is stored on transfer creation for both path and slot queues
- it is updated when slot-queued work is reclassified as path-queued
- queue promotion logic uses `queue_reason` as the primary classifier
- progress-text parsing remains only as backward-compatible fallback for pre-column or legacy rows

### Why this matters

Without a persisted `queue_reason`, queue logic has to infer intent from human-readable `progress` text, which is fragile and can misclassify queued work.

## Current API Notes

Queue status is exposed through:
- `GET /api/transfers/active`
- `GET /api/transfers/queue/status`

Returned fields:
- `max_concurrent`
- `running_count`
- `queued_count`
- `available_slots`
- `running_transfer_ids`
- `queued_transfer_ids`
- `active_destinations`

Implementation note: `active_destinations` currently returns the transfer IDs that own reserved destinations, not the normalized path strings themselves.

## Current Series/Anime Queue Lifecycle

For series/anime auto-sync:
1. webhook rows batch in `pending`
2. dry-run success moves them to `READY_FOR_TRANSFER`
3. transfer admission returns one of:
   - `running`
   - `QUEUED_SLOT`
   - `QUEUED_PATH`
4. linked webhook rows follow that result
5. on promotion, queued webhook rows move to `syncing`
6. on transfer completion, linked webhook rows are finalized

## Known Gaps

These are not queue-breakers, but they still matter operationally:
- movie webhook rows do not currently expose queue reason or queued status as clearly as series/anime rows
- auto-sync batch jobs are still in-memory only and do not survive restart
- manual-sync-required behavior still uses `pending + requires_manual_sync` instead of one explicit terminal status
- completion marking for series/anime is safer than before, but the broader completion path should still be tightened to guarantee that only truly synced rows move to `completed`

## Files Most Relevant To Queue Behavior

- `services/queue_manager.py`
- `services/transfer_coordinator.py`
- `services/transfer_service.py`
- `services/webhook_service.py`
- `services/auto_sync_scheduler.py`
- `models/transfer.py`
- `models/database.py`
- `models/webhook.py`

## Summary

The queue system now correctly preserves same-path ownership across promotion, persists queue intent through `queue_reason`, and rebuilds live running reservations after restart. The remaining work is mostly around queue visibility and lifecycle consistency for scheduler persistence, movie webhook queue states, and manual-sync status normalization.
