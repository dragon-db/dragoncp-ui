# Series/Anime Auto-Sync Flow V3

Last updated: 2026-03-19
Primary files: `routes/webhooks.py`, `services/auto_sync_scheduler.py`, `services/webhook_service.py`, `services/transfer_coordinator.py`, `services/queue_manager.py`, `models/webhook.py`

## Purpose

This document describes the current series/anime auto-sync path, including batching, dry-run validation, queueing, promotion, and webhook/transfer state synchronization.

It also calls out the places where the implementation still differs from the original V3 target.

## Current End-to-End Flow

### 1. Webhook reception

Series and anime Sonarr download events enter through:
- `routes/webhooks.py` series receiver
- `routes/webhooks.py` anime receiver

For non-test, non-rename events:
- payloads are parsed by `WebhookService.parse_series_webhook_data()`
- a row is created in `sonarr_webhook`
- the initial notification status is `pending`

### 2. Auto-sync batching

If auto-sync is enabled for the media type:
- `TransferCoordinator.schedule_auto_sync()` delegates to `AutoSyncScheduler.schedule_job()`
- jobs are grouped by `series_title_slug + season_number`
- additional episodes for the same season extend the existing batch window
- `auto_sync_scheduled_at` is stored on the notification rows

Important current behavior:
- scheduler jobs themselves are still in-memory only
- the DB stores the next scheduled timestamp, but not a durable recoverable job record

### 3. Dry-run validation

When the batch window expires:
- `AutoSyncScheduler._execute_job()` fetches the first notification in the batch
- `TransferCoordinator.perform_dry_run_validation()` resolves the source season path
- `PathService` computes the destination path using the same rules as real sync
- `TransferService.perform_dry_run_rsync()` runs rsync dry-run safety checks

If validation passes:
- all batched notifications are updated to `READY_FOR_TRANSFER`
- the scheduler calls `WebhookService.trigger_series_webhook_sync()`

If validation fails:
- each notification is updated through `TransferCoordinator.mark_for_manual_sync()`
- current implementation keeps `status='pending'`
- `requires_manual_sync=1` and `manual_sync_reason` hold the real manual-action signal
- a Discord alert may be sent once for the batch

This is one of the main remaining gaps versus the original V3 plan, which expected a real `MANUAL_SYNC_REQUIRED` status.

## Transfer Creation and Queueing

`WebhookService.trigger_series_webhook_sync()`:
- creates one `transfer_id` for the batch
- links all batched notifications to that `transfer_id`
- resolves `source_path`, `dest_path`, `folder_name`, and `season_name`
- calls `TransferCoordinator.start_transfer()`

`TransferCoordinator.start_transfer()` returns `(success, queue_type)` where `queue_type` is:
- `running`
- `QUEUED_SLOT`
- `QUEUED_PATH`
- `failed`

### Queue decision rules

#### Path conflict

If the destination path is already reserved:
- a transfer row is created with `status='queued'`
- `queue_reason='path'`
- progress text explains the blocking transfer/path
- the coordinator returns `QUEUED_PATH`
- linked webhook notifications become `QUEUED_PATH`

#### Slot full

If no path conflict exists but all running slots are full:
- a transfer row is created with `status='queued'`
- `queue_reason='slot'`
- the destination path is still reserved in memory
- the coordinator returns `QUEUED_SLOT`
- linked webhook notifications become `QUEUED_SLOT`

#### Immediate start

If the path is free and a slot is available:
- the queue manager reserves the destination and running slot in memory
- a transfer row is created with `status='pending'`
- rsync starts
- linked webhook notifications become `syncing`

## Queue Reason Behavior

`queue_reason` is now part of the real implementation, not just the design:
- older databases get the `transfers.queue_reason` column automatically at startup
- `Transfer.create()` persists `queue_reason` on insert
- queue promotion logic uses `queue_reason` first
- progress text parsing remains only as a legacy fallback

This fixed the earlier mismatch where the code expected `queue_reason` but the schema/insert path did not actually store it.

## Promotion Rules

Promotion happens after `QueueManager.unregister_transfer()` removes a running transfer.

Promotion order:
1. same freed path first
2. general slot queue second

### Path-specific promotion

`QueueManager._promote_same_path_queued(dest_path)`:
- finds queued transfer rows for the same normalized destination path
- prefers transfers that are explicitly or implicitly path-queued
- re-checks path ownership
- re-registers the promoted transfer in queue-manager running state before start
- hands the transfer to `TransferCoordinator.start_queued_transfer()`

`start_queued_transfer()` then performs the actual state transition to `pending` / `syncing` after queue ownership has been confirmed.

The re-registration step above is the production fix for issue `#40`.

### Slot promotion

`QueueManager._promote_next_queued_transfer()`:
- scans queued rows oldest-first
- classifies each row as path-queue or slot-queue using `queue_reason` first
- re-checks destination ownership before promotion

If a slot-queued transfer now conflicts with a running transfer on the same path:
- the transfer stays `queued`
- `queue_reason` changes from `slot` to `path`
- progress text is updated
- linked notifications move from `QUEUED_SLOT` to `QUEUED_PATH`

If the path is free:
- queue state is reserved in memory
- the transfer is promoted and started

## Start of Promoted Transfers

`TransferCoordinator.start_queued_transfer()` now performs a defensive check before rsync starts:
- the transfer must already be represented in queue-manager running state
- if queue state is missing, the transfer is not started

After that check:
- transfer status changes to `pending`
- linked notifications for the `transfer_id` are updated to `syncing`
- rsync starts
- post-completion monitoring thread is started

## Completion Marking

### What is correct today

The DB helper `SeriesWebhookNotification.mark_notifications_completed_by_transfer()` only updates rows where:
- `transfer_id` matches
- current status is `syncing`

That is the right rule for V3 because it avoids incorrectly completing:
- late-arriving `pending` notifications
- validated-but-not-started `READY_FOR_TRANSFER` notifications
- queued notifications still waiting on slot/path

### What is still not fully aligned

The broader series/anime completion path still bulk-updates linked notifications to `completed` before calling the stricter helper.

So the data model contains the correct narrow completion primitive, but the full runtime path should still be tightened so only truly synced rows move to `completed`.

## Restart and Recovery Behavior

### What survives restart now

Running transfer recovery improved:
- queue-manager running reservations are rebuilt from DB rows marked `running`
- monitoring of live rsync PIDs is resumed
- post-completion watchers are restarted so queue release and downstream cleanup still happen

### What still does not survive restart

Scheduled auto-sync batch windows do not fully survive restart:
- `auto_sync_scheduled_at` remains in the DB
- in-memory scheduler jobs are lost
- no startup recovery currently rebuilds them into `AutoSyncScheduler.jobs`

This is the main blocker for true restart-safe batching.

## Current State Table

### Transfer row states

| Transfer state | Meaning | Extra metadata |
|---|---|---|
| `pending` | admitted and preparing to start | none |
| `queued` | blocked from starting | `queue_reason='slot'` or `queue_reason='path'` |
| `running` | rsync active | `rsync_process_id` set |
| `completed` | finished successfully | end time set |
| `failed` | start or runtime failure | error/progress text |
| `cancelled` | user/system cancelled | end time set |

### Series/anime webhook row states actually used today

| Webhook state | Meaning |
|---|---|
| `pending` | received or waiting; also currently reused for manual-sync-required rows |
| `READY_FOR_TRANSFER` | dry-run passed and awaiting transfer admission |
| `QUEUED_SLOT` | blocked by global concurrency |
| `QUEUED_PATH` | blocked by same destination path |
| `syncing` | transfer active |
| `completed` | transfer finished |
| `failed` | transfer/scheduler error |
| `cancelled` | transfer cancelled |

Supporting manual-sync fields in current use:
- `requires_manual_sync`
- `manual_sync_reason`
- `dry_run_result`
- `dry_run_performed_at`

## V3 Alignment Status

### Implemented and working

- season-level batching by series/season
- dry-run validation before sync
- queue reason separation between slot and path
- tuple return contract from `start_transfer()`
- transfer-to-notification linkage by `transfer_id`
- slot-to-path queue conversion when a path conflict emerges later
- same-path promotion re-registration before start
- restart rebuild of running queue reservations

### Partially implemented

- completion marking is designed correctly in the model layer, but the full completion path still needs tightening
- restart recovery is better for running transfers, but not yet for scheduled batch jobs

### Not yet aligned with the original target

- no real `MANUAL_SYNC_REQUIRED` stored status yet
- scheduler jobs are not durably persisted/recovered
- movie webhook lifecycle is not as explicit about queue reasons as series/anime

## Recommended Next Steps

1. persist/recover scheduler jobs using DB-backed batch records or deterministic rebuild from `pending` + `auto_sync_scheduled_at`
2. normalize manual-sync-required notifications to one explicit terminal status
3. tighten series/anime completion propagation so only rows that were actually `syncing` become `completed`

## Summary

The current V3 implementation is much closer to the intended design after the queue fixes: queue reasons are now persisted, same-path promotions reclaim in-memory ownership correctly, and running transfers recover their path reservations after restart. The main remaining gaps are durable scheduler recovery, explicit manual-sync-required status, and stricter completion propagation.
