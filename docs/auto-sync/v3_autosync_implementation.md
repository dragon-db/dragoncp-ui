# Series/Anime Auto-Sync Flow V3 Implementation

## Overview

Complete redesign of the series/anime auto-sync system with intelligent queue management, explicit state tracking, and dynamic queue type conversion. This implementation eliminates ambiguous states, prevents transfers from getting stuck, and ensures proper synchronization between transfer and webhook notification states.

### Key Features

- **Explicit Queue Type Tracking**: Added `queue_reason` field (`'path'` or `'slot'`) for reliable queue management
- **Dynamic Queue Conversion**: QUEUED_SLOT transfers automatically convert to QUEUED_PATH when path conflicts emerge
- **Tuple Return Pattern**: `start_transfer()` returns `(success, queue_type)` for immediate state determination
- **Transfer-Webhook Sync**: Webhook notifications always reflect actual transfer state
- **Path-Specific Promotion**: Only same-path completion triggers QUEUED_PATH promotion
- **Comprehensive Logging**: Structured logs with service name, transfer_id, and notification_id
- **Batching with Linkage**: Multiple episodes link to single transfer via `transfer_id`

## Problems Solved

### Issue 1: Unreliable Queue Type Detection

**Problem**: System tried to determine queue type by re-reading transfer record and parsing `progress` field, but the field was empty when read back from database, causing incorrect QUEUED_SLOT/QUEUED_PATH detection.

**Solution**: 
- Added explicit `queue_reason` field (`'path'` or `'slot'`) to transfer records
- Changed `start_transfer()` to return `(success, queue_type)` tuple
- Webhook service uses returned queue type directly, no database re-read needed

### Issue 2: QUEUED_SLOT Marked as DUPLICATE on Path Conflict

**Problem**: When a QUEUED_SLOT transfer was promoted but found a path conflict (another transfer now running on same path), it was marked as `DUPLICATE` (terminal state), leaving it stuck forever.

**Solution**: 
- Modified `_promote_next_queued_transfer()` to convert QUEUED_SLOT → QUEUED_PATH when path conflict emerges
- Updates `queue_reason` from `'slot'` to `'path'`
- Syncs webhook notification status to QUEUED_PATH
- Transfer stays in queue and is picked up by `_promote_same_path_queued()` later

### Issue 3: Incorrect Completion Marking

**Problem**: `mark_pending_by_series_season_completed()` marked ALL notifications with states `pending`, `syncing`, and `waiting_auto_sync` as completed. Episodes arriving during active sync were incorrectly marked completed.

**Solution**: Only mark `SYNCING` notifications as completed (those actually in the transfer, linked via `transfer_id`). Keep `PENDING` and `READY_FOR_TRANSFER` notifications for next cycle.

### Issue 4: Ambiguous State Names

**Problem**: State names like `waiting_auto_sync` were ambiguous and unclear.

**Solution**: 
- Renamed `waiting_auto_sync` to `READY_FOR_TRANSFER` (clear: passed validation, ready for transfer service)
- Added separate `QUEUED_SLOT` and `QUEUED_PATH` states (clear: why it's queued)
- All states now have clear, descriptive names

## Complete State Flow

### Detailed Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    SERIES/ANIME AUTO-SYNC V3 FLOW                            │
└──────────────────────────────────────────────────────────────────────────────┘

1. WEBHOOK RECEPTION & BATCHING
   ├─ Webhook arrives (Episode downloaded)
   ├─ Store in series_webhook_notification table
   ├─ Status: PENDING
   └─ Auto-sync Scheduler: Batch episodes (60s window)
      ├─ Episode 1 arrives at T+0s → PENDING
      ├─ Episode 2 arrives at T+15s → PENDING (extends batch window to T+75s)
      └─ Episode 3 arrives at T+40s → PENDING (extends batch window to T+100s)

2. DRY-RUN VALIDATION (after batch window)
   ├─ Perform rsync --dry-run on season folder
   ├─ Check for file deletions and conflicts
   │
   ├─ PASS ✓
   │  ├─ Mark ALL batched notifications: READY_FOR_TRANSFER
   │  ├─ Link ALL notifications to same transfer_id
   │  └─ Proceed to transfer initiation
   │
   └─ FAIL ✗
      ├─ Mark ALL batched notifications: MANUAL_SYNC_REQUIRED
      └─ Send Discord alert

3. TRANSFER INITIATION (Coordinator.start_transfer)
   ├─ Check [A]: Path conflict? (duplicate destination check)
   ├─ Check [B]: Slot available? (< 3 concurrent transfers)
   │
   ├─ Path Conflict (A=YES)
   │  ├─ Create transfer: status='queued', queue_reason='path'
   │  ├─ Return: (True, 'QUEUED_PATH')
   │  └─ Update webhook: QUEUED_PATH
   │
   ├─ Slot Full (A=NO, B=NO)
   │  ├─ Create transfer: status='queued', queue_reason='slot'
   │  ├─ Return: (True, 'QUEUED_SLOT')
   │  └─ Update webhook: QUEUED_SLOT
   │
   └─ Both OK (A=NO, B=YES)
      ├─ Create transfer: status='pending'
      ├─ Start rsync process
      ├─ Return: (True, 'running')
      └─ Update webhook: SYNCING

4. QUEUE PROMOTION (when transfer completes)
   ├─ Transfer X completes (dest_path: /path/to/season)
   ├─ Unregister from queue manager
   │
   ├─ Step 1: Check for QUEUED_PATH with SAME dest_path
   │  ├─ Query: SELECT * WHERE status='queued' AND queue_reason='path' 
   │  │         AND dest_path='/path/to/season' ORDER BY created_at
   │  ├─ Found? → Promote oldest one → Start transfer
   │  └─ Not found? → Continue to Step 2
   │
   └─ Step 2: Check for QUEUED_SLOT (any path)
      ├─ Query: SELECT * WHERE status='queued' AND queue_reason='slot'
      │         ORDER BY created_at
      ├─ Found? → Re-validate path conflict
      │  ├─ Path OK? → Promote → Start transfer
      │  └─ Path conflict? → Convert to QUEUED_PATH
      │     ├─ Update: queue_reason='slot' → 'path'
      │     ├─ Update webhook: QUEUED_SLOT → QUEUED_PATH
      │     └─ Skip (wait for path-specific promotion)
      └─ Not found? → Done

5. DYNAMIC QUEUE CONVERSION
   ├─ Scenario: QUEUED_SLOT transfer promoted, but path now occupied
   ├─ Instead of marking DUPLICATE (terminal state)
   ├─ Convert: QUEUED_SLOT → QUEUED_PATH
   │  ├─ Update transfer: queue_reason='slot' → 'path'
   │  ├─ Update webhook: QUEUED_SLOT → QUEUED_PATH
   │  └─ Will be picked up by path-specific promotion later
   └─ This prevents transfers from getting stuck

6. COMPLETION MARKING
   ├─ Transfer completes successfully
   ├─ Find ALL notifications with this transfer_id
   ├─ Update ALL linked notifications: SYNCING → COMPLETED
   └─ Notifications with other states (PENDING, READY_FOR_TRANSFER) stay unchanged
```

### Transfer Record Structure

```
transfers table:
├─ transfer_id: "series_webhook_tvshows_267_s1_ef76577_1763970383"
├─ status: 'queued' | 'pending' | 'running' | 'completed' | 'failed'
├─ queue_reason: 'path' | 'slot' | NULL  ← NEW: Explicit queue type
├─ progress: Human-readable message
└─ dest_path: "/path/to/destination"

series_webhook_notification table:
├─ notification_id: "tvshows_267_s1_ef76577"
├─ status: 'PENDING' | 'READY_FOR_TRANSFER' | 'QUEUED_SLOT' | 
│          'QUEUED_PATH' | 'SYNCING' | 'COMPLETED' | 'FAILED'
├─ transfer_id: Links to transfers table (for batched episodes)
└─ season_path: "/source/path/Season 01"
```

### State Synchronization Pattern

```
Coordinator.start_transfer() returns:
   ↓
(success: bool, queue_type: str)
   ↓
   ├─ (True, 'running')      → Webhook: SYNCING
   ├─ (True, 'QUEUED_SLOT')  → Webhook: QUEUED_SLOT
   ├─ (True, 'QUEUED_PATH')  → Webhook: QUEUED_PATH
   └─ (False, 'failed')      → Webhook: FAILED

No database re-read needed - queue type is explicit and immediate
```

### All Possible States

| State | Description | Transitions To | Terminal? |
|-------|-------------|---------------|-----------|
| `PENDING` | Webhook received, waiting for batch window | `READY_FOR_TRANSFER`, `MANUAL_SYNC_REQUIRED` | No |
| `READY_FOR_TRANSFER` | Dry-run passed, ready for transfer service | `SYNCING`, `QUEUED_SLOT`, `QUEUED_PATH` | No |
| `QUEUED_SLOT` | Blocked by max concurrent limit (3 transfers) | `READY_FOR_TRANSFER` | No |
| `QUEUED_PATH` | Blocked by same destination path conflict | `READY_FOR_TRANSFER` | No |
| `SYNCING` | Transfer actively in progress | `COMPLETED`, `FAILED`, `CANCELLED` | No |
| `COMPLETED` | Transfer finished successfully | None | Yes |
| `FAILED` | Transfer failed | None (can retry) | Yes |
| `MANUAL_SYNC_REQUIRED` | Dry-run validation failed | None (needs user) | Yes |
| `CANCELLED` | User cancelled transfer | None | Yes |

### State Transition Rules

1. **Batching (PENDING)**:
    - Multiple webhooks for same series/season stay PENDING during wait window
    - `auto_sync_scheduled_at` field tracks batch completion time
    - All batched notifications validated together

2. **Dry-Run Validation**:

    - Performed ONCE per batch (entire season folder)
    - ALL notifications in batch get same result (pass or fail)
    - If passed: ALL move to `READY_FOR_TRANSFER`
    - If failed: ALL move to `MANUAL_SYNC_REQUIRED`

3. **Same-Path Grouping**:

    - When marking `SYNCING`, mark ALL same-path `READY_FOR_TRANSFER` notifications
    - When marking `QUEUED_PATH`, mark ALL same-path `READY_FOR_TRANSFER` notifications
    - Ensures consistency (same destination = same state)

4. **Completion Marking**:

    - Only mark notifications with `SYNCING` state as `COMPLETED`
    - `PENDING` notifications (arrived during sync) stay `PENDING` for next cycle
    - `READY_FOR_TRANSFER` notifications stay for next attempt

## Queue System Logic

### Queue Types

1. **Slot Queue (QUEUED_SLOT)**

    - Reason: Max 3 concurrent transfers reached
    - Promotion: When ANY transfer completes (slot freed)
    - Priority: After path-specific queue

2. **Path Queue (QUEUED_PATH)**

    - Reason: Same destination path has active transfer
    - Promotion: ONLY when SAME PATH transfer completes
    - Priority: First (before general slot queue)

### Queue Promotion Algorithm

```python
def _promote_next_queued_transfer():
    """
    Intelligent queue promotion with path-priority and dynamic conversion
    """
    # Get all queued transfers, sorted by creation time (FIFO)
    queued_transfers = get_all_queued_transfers_sorted_by_time()
    
    for transfer in queued_transfers:
        # Determine queue type from explicit queue_reason field
        if transfer.queue_reason == 'path':
            is_path_queue = True
        elif transfer.queue_reason == 'slot':
            is_path_queue = False
        else:
            # Fallback: parse progress message (legacy support)
            is_path_queue = parse_progress_for_path_indicators(transfer.progress)
        
        # Re-check for path conflict before promoting
        is_duplicate, existing_transfer_id = check_duplicate_destination(
            transfer.dest_path, 
            transfer.transfer_id
        )
        
        if is_duplicate:
            if is_path_queue:
                # QUEUED_PATH transfer - path still occupied
                # Skip and keep in queue (path-specific wait)
                print(f"⏭️ Skipping QUEUED_PATH {transfer.id} (path occupied)")
                continue
            else:
                # QUEUED_SLOT transfer - path conflict emerged!
                # CRITICAL: Convert to QUEUED_PATH instead of marking DUPLICATE
                print(f"🔄 Converting QUEUED_SLOT → QUEUED_PATH")
                
                update_transfer(transfer.id, {
                    'queue_reason': 'path',  # slot → path
                    'progress': 'Queued: Waiting for same path to complete'
                })
                
                # Sync webhook notification status
                update_webhook_notifications(transfer.id, {
                    'status': 'QUEUED_PATH'
                })
                
                # Skip promotion - will be picked up by path-specific check later
                continue
        
        # Path is free - promote this transfer!
        register_transfer(transfer.id, transfer.dest_path)
        start_queued_transfer(transfer.id)
        break  # Only promote one at a time
```

### Critical Edge Cases & Solutions

**Case 1: Episode Arrives During Active Sync**

```
Timeline:
T+0s:   Episode 1 downloaded → PENDING
T+60s:  Validation passes → READY_FOR_TRANSFER → SYNCING
T+90s:  Episode 2 downloaded → PENDING (new batch window)
T+120s: Episode 1 still SYNCING
T+150s: Episode 2 validation passes → READY_FOR_TRANSFER
        Path check: Episode 1 still syncing same path
        Result: Episode 2 → QUEUED_PATH
T+180s: Episode 1 → COMPLETED
        Promotion check: Found Episode 2 in QUEUED_PATH (same path)
        Result: Episode 2 → SYNCING

✓ Late-arriving episodes properly queued and picked up
```

**Case 2: Dynamic Queue Conversion (THE FIX)**

```
Initial State:
- 3 transfers running (slots full)
- Transfer A: QUEUED_SLOT (dest: /anime/SeriesX/S1)
- Transfer B: QUEUED_SLOT (dest: /anime/SeriesX/S1) [SAME PATH as A]

Slot Opens:
- One transfer completes → slot freed
- System attempts to promote Transfer A
- Transfer A registers and starts → SYNCING
- Queue manager tries to promote next → Transfer B

Transfer B Promotion Attempt:
1. Re-check path conflict
2. Found: Transfer A now running on /anime/SeriesX/S1
3. OLD BEHAVIOR: Mark Transfer B as DUPLICATE ❌
4. NEW BEHAVIOR: Convert Transfer B: QUEUED_SLOT → QUEUED_PATH ✓
   - Update queue_reason: 'slot' → 'path'
   - Update webhook: QUEUED_SLOT → QUEUED_PATH
   - Skip promotion (wait for Transfer A)

Transfer A Completes:
- Path-specific promotion check
- Found: Transfer B in QUEUED_PATH for /anime/SeriesX/S1
- Promote Transfer B → SYNCING ✓

✓ Prevents transfers from getting stuck in DUPLICATE status
✓ Dynamic queue type reflects actual blocking reason
```

**Case 3: Multiple Same-Path Queued Transfers**

```
Active Transfers (3/3 slots):
- Transfer X: SYNCING (path: /anime/Series1/S1)
- Transfer Y: SYNCING (path: /anime/Series2/S1)  
- Transfer Z: SYNCING (path: /movies/Movie1)

Queued Transfers:
- Transfer A: QUEUED_PATH (path: /anime/Series1/S1) [same as X]
- Transfer B: QUEUED_PATH (path: /anime/Series1/S1) [same as X]
- Transfer C: QUEUED_SLOT (path: /anime/Series3/S1) [different]

Event 1: Transfer Y completes (different path)
├─ Check path-specific: No QUEUED_PATH for /anime/Series2/S1
├─ Check slot queue: Transfer C found
├─ Re-validate Transfer C: No path conflict
└─ Result: Transfer C promoted → SYNCING

Event 2: Transfer X completes (path: /anime/Series1/S1)
├─ Check path-specific: Transfer A found (oldest, same path)
├─ Promote Transfer A → SYNCING
└─ Transfer B stays QUEUED_PATH (waits for A)

Event 3: Transfer A completes (path: /anime/Series1/S1)
├─ Check path-specific: Transfer B found (same path)
├─ Promote Transfer B → SYNCING
└─ Queue empty

✓ Path-specific promotion ensures sequential processing
✓ Oldest queued transfer for specific path always picked first
```

**Case 4: Batched Episodes with Transfer Linkage**

```
Batch 1 (Episodes 1, 2, 3):
├─ 3 notifications created (each with unique notification_id)
├─ All marked: PENDING
├─ Validation passes → All marked: READY_FOR_TRANSFER
├─ Transfer initiated: transfer_id = "series_webhook_..._1763970383"
├─ Link ALL 3 notifications to this transfer_id
└─ Update ALL 3: READY_FOR_TRANSFER → SYNCING

Transfer Completes:
├─ Query: SELECT * WHERE transfer_id = "series_webhook_..._1763970383"
├─ Found: 3 notifications
├─ Update ALL 3: SYNCING → COMPLETED
└─ Only notifications in THIS transfer marked completed

Batch 2 (Episode 4 - arrived late):
├─ Still in PENDING state
├─ NOT affected by Batch 1 completion
└─ Will be processed in next cycle

✓ Transfer-notification linkage ensures accurate completion marking
✓ Only episodes actually synced are marked completed
```

## Implementation Details

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Component Flow                           │
└─────────────────────────────────────────────────────────────────┘

Webhook Request
   ↓
WebhookService.parse_series_webhook_data()
   ├─ Extract episode info
   └─ Store in series_webhook_notification (PENDING)
   ↓
AutoSyncScheduler (manages batching)
   ├─ Accumulate episodes (60s window)
   ├─ Perform dry-run validation
   └─ Mark: PENDING → READY_FOR_TRANSFER (or MANUAL_SYNC_REQUIRED)
   ↓
WebhookService.trigger_series_webhook_sync()
   ├─ Link all batched notifications to transfer_id
   └─ Call TransferCoordinator.start_transfer()
   ↓
TransferCoordinator.start_transfer() → returns (bool, queue_type)
   ├─ Check path conflict → (True, 'QUEUED_PATH')
   ├─ Check slot full → (True, 'QUEUED_SLOT')
   └─ Both OK → (True, 'running')
   ↓
WebhookService (uses returned queue_type)
   ├─ Map queue_type to webhook status
   └─ Update all linked notifications
   ↓
QueueManager (when transfer completes)
   ├─ Path-specific promotion (QUEUED_PATH)
   ├─ Slot promotion with conversion (QUEUED_SLOT → QUEUED_PATH if needed)
   └─ Call TransferCoordinator.start_queued_transfer()
   ↓
TransferService.start_rsync_process()
   ├─ Execute rsync with monitoring
   └─ Update transfer status: pending → running → completed
   ↓
WebhookService.update_webhook_transfer_status()
   └─ Update all notifications linked to transfer_id: SYNCING → COMPLETED
```

### Modified Files

#### 1. `models/webhook.py`

**Changes:**

- Fixed `mark_pending_by_series_season_completed()` to only mark `SYNCING` notifications
- Added `link_notifications_to_transfer()` for batching support
- Added `update_notifications_by_transfer_id()` for consistent status updates
- Added `mark_notifications_completed_by_transfer()` for accurate completion
- Comprehensive state documentation in class docstring

**Key Methods:**

```python
def link_notifications_to_transfer(notification_ids: List[str], transfer_id: str):
    """Link multiple batched notifications to a single transfer"""
    
def update_notifications_by_transfer_id(transfer_id: str, updates: dict):
    """Update all notifications linked to a transfer (batched episodes)"""
    
def mark_notifications_completed_by_transfer(transfer_id: str):
    """Mark only SYNCING notifications for this transfer as completed"""
```

#### 2. `services/queue_manager.py`

**Changes:**

- Added `dest_path` parameter to `unregister_transfer()` for path-specific promotion
- Added `_promote_same_path_queued(dest_path)` for path-specific queue handling
- **CRITICAL FIX**: Modified `_promote_next_queued_transfer()` to convert QUEUED_SLOT → QUEUED_PATH when path conflict emerges
- Added explicit `queue_reason` field checking (primary), with fallback to progress parsing

**Key Logic:**

```python
def _promote_next_queued_transfer():
    """
    Promotion with dynamic queue conversion
    """
    for transfer in queued_transfers:
        # Check explicit queue_reason field (NEW)
        if transfer.queue_reason == 'path':
            is_path_queue = True
        elif transfer.queue_reason == 'slot':
            is_path_queue = False
        
        # Re-check for path conflict
        is_duplicate, existing_id = check_duplicate_destination(...)
        
        if is_duplicate:
            if is_path_queue:
                # Already QUEUED_PATH - skip and keep waiting
                continue
            else:
                # QUEUED_SLOT encountering path conflict
                # CONVERT instead of marking DUPLICATE
                update_transfer({
                    'queue_reason': 'path',  # slot → path
                    'progress': 'Queued: Waiting for same path'
                })
                
                # Sync webhook status
                update_webhook_notifications({'status': 'QUEUED_PATH'})
                continue  # Skip, wait for path-specific promotion
        
        # Path free - promote!
        promote_transfer(transfer)
```

#### 3. `services/transfer_coordinator.py`

**Changes:**

- **MAJOR**: Changed `start_transfer()` return type: `bool` → `Tuple[bool, str]`
- Returns `(success, queue_type)` where queue_type is: `'running'`, `'QUEUED_SLOT'`, `'QUEUED_PATH'`, or `'failed'`
- Added explicit `queue_reason` field to transfer records
- Modified duplicate handling to create queued records (not failed)
- Updated `_post_transfer_completion()` to pass `dest_path` for path-specific promotion

**New Return Pattern:**

```python
def start_transfer(...) -> Tuple[bool, str]:
    """
    Start transfer and return explicit queue type
    
    Returns:
        (success, queue_type) where queue_type is:
        - 'running': Transfer started successfully
        - 'QUEUED_SLOT': Queued due to max concurrent limit
        - 'QUEUED_PATH': Queued due to path conflict  
        - 'failed': Failed to start
    """
    
    # Path conflict check
    if is_duplicate:
        transfer_data = {
            'status': 'queued',
            'queue_reason': 'path',  # Explicit tracking
            'progress': 'Queued: Waiting for same path...'
        }
        create_transfer(transfer_data)
        return (True, 'QUEUED_PATH')  # Explicit queue type
    
    # Slot availability check
    can_start, queue_status = queue_manager.register_transfer(...)
    if queue_status == 'queued':
        transfer_data = {
            'status': 'queued',
            'queue_reason': 'slot',  # Explicit tracking
            'progress': 'Waiting in queue...'
        }
        create_transfer(transfer_data)
        return (True, 'QUEUED_SLOT')  # Explicit queue type
    
    # All checks passed - start immediately
    if can_start:
        create_and_start_transfer()
        return (True, 'running')  # Started
    
    return (False, 'failed')  # Shouldn't reach here
```

#### 4. `services/webhook_service.py`

**Changes:**

- Updated `trigger_series_webhook_sync()` to unpack tuple return: `success, queue_type = start_transfer(...)`
- **Eliminated database re-read**: Uses returned `queue_type` directly for webhook status
- Added `batched_notification_ids` parameter for linking multiple episodes to single transfer
- Updated `update_webhook_transfer_status()` to use `update_notifications_by_transfer_id()`
- Replaced `_mark_pending_season_notifications_completed()` with `_mark_notifications_completed_by_transfer()`

**New Pattern:**

```python
def trigger_series_webhook_sync(notification_id, batched_notification_ids):
    """
    Trigger sync with explicit queue type handling
    """
    # Link all batched notifications to transfer
    link_notifications_to_transfer(batched_notification_ids, transfer_id)
    
    # Start transfer - returns explicit queue type
    success, queue_type = coordinator.start_transfer(...)
    
    # Map queue type to webhook status (no DB re-read!)
    webhook_status_map = {
        'running': 'syncing',
        'QUEUED_SLOT': 'QUEUED_SLOT',
        'QUEUED_PATH': 'QUEUED_PATH'
    }
    
    webhook_status = webhook_status_map.get(queue_type, 'syncing')
    
    # Update ALL linked notifications with same status
    if webhook_status == 'syncing':
        update_notifications_by_transfer_id(transfer_id, {
            'status': 'syncing',
            'synced_at': datetime.now()
        })
    elif webhook_status in ['QUEUED_SLOT', 'QUEUED_PATH']:
        update_notifications_by_transfer_id(transfer_id, {
            'status': webhook_status
        })
```

#### 5. `services/auto_sync_scheduler.py`

**Changes:**

- Updated state transitions: `waiting_auto_sync` → `READY_FOR_TRANSFER`
- Added `batched_notification_ids` tracking for linking episodes
- Pass all batched notification IDs to `trigger_series_webhook_sync()`
- Integrated `sync_logger` for structured logging

**Batching Logic:**

```python
def _execute_job(job):
    """
    Execute scheduled job with batched notifications
    """
    notification_ids = job.notification_ids  # All batched episodes
    
    # Dry-run validation on entire season
    validation_result = coordinator.perform_dry_run_validation(...)
    
    if validation_result['safe_to_sync']:
        # Mark ALL batched notifications as READY_FOR_TRANSFER
        for nid in notification_ids:
            series_webhook_model.update(nid, {'status': 'READY_FOR_TRANSFER'})
        
        # Trigger sync with ALL notification IDs
        # Coordinator will link them all to same transfer_id
        success, message = coordinator.trigger_series_webhook_sync(
            notification_id=notification_ids[0],
            batched_notification_ids=notification_ids  # All IDs
        )
```

**Future Enhancement - Sonarr API:**

```python
# TODO: Dynamic Wait Time with Sonarr API
# GET /api/v3/queue?seriesId={series_id}
# 
# If queue has pending episodes for same season:
#   - Extend wait time (up to max 15 min)
# Else:
#   - Proceed with dry-run immediately
```

#### 6. `services/sync_logger.py` (NEW FILE)

**Purpose:** Structured logging utility for traceability

**Key Functions:**

```python
def log_sync(service, message, notification_id=None, transfer_id=None, icon="📋"):
    """
    Log with consistent formatting
    Format: 🔍 [Service] [notif:id][xfer:id] > message
    """
    
def log_batch(service, batch_key, notification_ids, message, icon="📦"):
    """Log batch processing events"""
    
def log_state_change(service, notification_id, old_status, new_status, 
                     transfer_id=None, icon="🔄"):
    """Log state transitions"""
```

**Usage:**
```python
log_sync("TransferCoordinator", "Checking for duplicate destination", 
         transfer_id=transfer_id, icon="🔍")
# Output: 🔍 [TransferCoordinator] [xfer:series_webhook_..._123] > Checking...

log_state_change("WebhookService", notification_id, "QUEUED_SLOT", "QUEUED_PATH",
                 transfer_id=transfer_id)
# Output: 🔄 [WebhookService] [notif:tvshows_267_s1_abc][xfer:...] > 
#         State change: QUEUED_SLOT -> QUEUED_PATH
```

### Database Schema

**No schema changes required** - using existing TEXT columns for status.

**New/Modified Fields:**

#### `transfers` table:
- `status`: `'queued'` | `'pending'` | `'running'` | `'completed'` | `'failed'` | `'cancelled'`
- `queue_reason`: `'path'` | `'slot'` | `NULL` **(NEW)** - Explicit queue type tracking
- `progress`: Human-readable message
- `dest_path`: Destination path for duplicate detection

#### `series_webhook_notifications` table:
- `status`: State values (user-facing)
  - `PENDING`
  - `READY_FOR_TRANSFER` (replaces `waiting_auto_sync`)
  - `QUEUED_SLOT` **(NEW)**
  - `QUEUED_PATH` **(NEW)**
  - `SYNCING`
  - `COMPLETED`
  - `FAILED`
  - `MANUAL_SYNC_REQUIRED`
  - `CANCELLED`
- `transfer_id`: Links to `transfers.transfer_id` **(UTILIZED)** - For batching and accurate status updates
- `season_path`: Source path for validation

### State Marking Fix Details

**File**: `models/webhook.py`, function `mark_pending_by_series_season_completed()`

**Current (WRONG):**

```python
WHERE status IN ('pending', 'syncing', 'waiting_auto_sync')
```

**New (CORRECT):**

```python
WHERE status = 'syncing'
```

**Rationale**:

- Only notifications actively being synced should be marked completed
- `PENDING` notifications arrived late, need next sync cycle
- `READY_FOR_TRANSFER` notifications haven't started yet
- `QUEUED_*` notifications are waiting in queue

## Implementation Steps

1. **Add State Flow Documentation** (models/webhook.py)

- Add comprehensive state documentation to class docstring
- Document all possible states and transitions
- Add state transition rules

2. **Fix State Marking Logic** (models/webhook.py)

- Modify `mark_pending_by_series_season_completed()`
- Change SQL WHERE clause to only mark `SYNCING` as completed
- Update function docstring with rationale

3. **Add Same-Path Notification Marking** (models/webhook.py)

- Add `mark_same_path_notifications_as_syncing()` method
- Query READY_FOR_TRANSFER with same dest_path
- Mark all as SYNCING when transfer starts

4. **Enhance Queue Manager for Path-Specific Queuing** (services/queue_manager.py)

- Add `dest_path` param to `unregister_transfer()`
- Add `_promote_same_path_queued(dest_path)` method
- Modify `_promote_next_queued_transfer()` to prioritize same-path queue

5. **Update Transfer Coordinator** (services/transfer_coordinator.py)

- Modify duplicate handling in `start_transfer()` to create queued records
- Update `_post_transfer_completion()` to pass dest_path
- Add logic to mark same-path notifications as SYNCING

6. **Update Webhook Service State Mapping** (services/webhook_service.py)

- Handle `QUEUED_SLOT` and `QUEUED_PATH` states
- Ensure transfer state changes propagate to webhook notifications
- Add state transition logging

7. **Update Auto-Sync Scheduler** (services/auto_sync_scheduler.py)

- Change `waiting_auto_sync` to `READY_FOR_TRANSFER`
- Add Sonarr API TODO with implementation details
- Update state transition calls

8. **Frontend State Display** (static/modules/webhook-manager.js)

- Add badges/colors for new states
- Update state display logic
- Add tooltips explaining queue types

## Testing Scenarios

1. **Basic Flow**: Single episode → PENDING → READY_FOR_TRANSFER → SYNCING → COMPLETED
2. **Batching**: 3 episodes in 60s → All stay PENDING → All to READY_FOR_TRANSFER → All to SYNCING
3. **Late Arrival**: Episode during sync → PENDING (stays) → Next cycle → READY_FOR_TRANSFER
4. **Path Conflict**: Same path already syncing → QUEUED_PATH → Previous completes → SYNCING
5. **Slot Full**: 3 transfers running → 4th → QUEUED_SLOT → Any completes → READY_FOR_TRANSFER
6. **Sequential Same-Path**: Multiple queued for same path → Process one-by-one
7. **Dry-Run Fail**: Batch fails validation → ALL → MANUAL_SYNC_REQUIRED

## Design Decisions

### Why Two State Tracking Approaches?

**Transfers Table:** Generic `status='queued'` + Specific `queue_reason='path'|'slot'`

**Webhook Table:** Specific `status='QUEUED_SLOT'|'QUEUED_PATH'`

**Rationale:**
1. **Backward Compatibility**: Transfers table used by movies (no queue types needed)
2. **User Experience**: Webhook notifications directly displayed in UI (need clear labels)
3. **Separation of Concerns**: Transfer system stays generic; webhook system is specific
4. **Query Efficiency**: `queue_reason` provides metadata without changing core state machine

### Why Tuple Return Pattern?

**Old:** `start_transfer() → bool`
- Required database re-read to determine queue type
- Race condition: progress field could be empty
- Unreliable queue type detection

**New:** `start_transfer() → (bool, queue_type)`
- Explicit, immediate queue type knowledge
- No database round-trip needed
- Reliable state synchronization
- Clear contract: caller knows exactly what happened

### Why Dynamic Queue Conversion?

**Problem:** Transfers queued for slot availability can encounter path conflicts during promotion

**Solution:** Convert QUEUED_SLOT → QUEUED_PATH dynamically
- Reflects actual blocking reason
- Prevents DUPLICATE terminal state
- Ensures transfer eventually executes
- User sees accurate queue reason in UI

## Success Criteria

- ✅ All webhook states clearly documented with transitions
- ✅ State names are intuitive (`READY_FOR_TRANSFER`, `QUEUED_SLOT`, `QUEUED_PATH`)
- ✅ Explicit queue type tracking via `queue_reason` field
- ✅ Tuple return pattern eliminates database re-read race condition
- ✅ Dynamic queue conversion prevents transfers from getting stuck
- ✅ Path conflict transfers queue as `QUEUED_PATH`, not marked as duplicate
- ✅ Only same-path transfer completion triggers `QUEUED_PATH` promotion
- ✅ Only `SYNCING` notifications (linked via transfer_id) marked completed
- ✅ Episodes arriving during sync stay `PENDING` for next cycle
- ✅ Queue system handles both slot limits and path conflicts with automatic conversion
- ✅ Structured logging with transfer_id and notification_id for full traceability
- ✅ Frontend displays queue-specific states with clear labels

## Known Limitations

1. **Fixed Batch Window**: Currently uses 60s fixed window (Sonarr API integration documented as future enhancement)
2. **Generic Transfer Status**: Transfer table uses `status='queued'` for backward compatibility (requires checking `queue_reason` for specifics)
3. **No Queue Priority**: FIFO only (no prioritization by file size, age, or user preference)
4. **Single-Level Queuing**: No nested queue priorities (e.g., high-priority path conflicts)

---

## Git Commit Message

```
feat: Implement V3 series/anime auto-sync with intelligent queue management

Complete redesign of series/anime auto-sync system with explicit state 
tracking, dynamic queue conversion, and reliable transfer-webhook 
synchronization. Eliminates race conditions and prevents transfers from 
getting stuck in terminal states.

### Major Changes

**1. Explicit Queue Type Tracking**
- Added `queue_reason` field ('path' or 'slot') to transfer records
- Eliminates unreliable progress message parsing
- Provides authoritative source for queue type determination

**2. Tuple Return Pattern**
- Changed `start_transfer()` signature: bool → (bool, queue_type)
- Returns explicit queue type: 'running', 'QUEUED_SLOT', 'QUEUED_PATH', 'failed'
- Eliminates database re-read race condition
- Webhook service uses returned value directly for accurate state sync

**3. Dynamic Queue Conversion**
- QUEUED_SLOT transfers automatically convert to QUEUED_PATH when path 
  conflicts emerge during promotion
- Prevents transfers from being marked as DUPLICATE (terminal state)
- Updates queue_reason field and webhook notification status
- Ensures all transfers eventually execute

**4. Transfer-Notification Linkage**
- All batched episodes linked to single transfer via transfer_id
- Consistent status updates across all notifications in a batch
- Accurate completion marking using transfer_id instead of series/season matching
- Prevents late-arriving episodes from being incorrectly marked completed

**5. Path-Specific Promotion**
- Queue manager prioritizes QUEUED_PATH transfers for specific destination paths
- Only same-path completion triggers QUEUED_PATH promotion
- Sequential processing of transfers to same destination
- Slot-based promotion handled after path-specific checks

**6. Comprehensive Logging**
- New sync_logger utility for structured, traceable logs
- Format: [Service][notif:id][xfer:id] > message
- Full lifecycle tracking from webhook receipt to completion
- Easy database query correlation

### Files Modified

**Core Services:**
- services/transfer_coordinator.py: Tuple return pattern, explicit queue_reason
- services/queue_manager.py: Dynamic conversion, path-specific promotion
- services/webhook_service.py: Direct queue type usage, transfer linkage
- services/auto_sync_scheduler.py: Batch notification ID tracking
- services/sync_logger.py: NEW - Structured logging utility

**Models:**
- models/webhook.py: Transfer linkage methods, accurate completion marking

**Frontend:**
- static/modules/webhook-manager.js: QUEUED_SLOT and QUEUED_PATH badges

### State Flow

PENDING → READY_FOR_TRANSFER → {SYNCING | QUEUED_SLOT | QUEUED_PATH}
                                      ↓          ↓            ↓
                                  COMPLETED  (converts→)  (path-specific
                                              QUEUED_PATH   promotion)

### Fixes

- ✅ No more stuck transfers in DUPLICATE status
- ✅ Reliable queue type detection without database race conditions  
- ✅ Accurate completion marking for batched episodes
- ✅ Dynamic queue adaptation to emerging conflicts
- ✅ Clear state names (READY_FOR_TRANSFER vs waiting_auto_sync)
- ✅ Full traceability with structured logging

### Breaking Changes

None. Changes are backward compatible:
- Generic transfer.status='queued' maintained for movie compatibility
- New queue_reason field is optional metadata
- Webhook states are additive (QUEUED_SLOT, QUEUED_PATH are new)

### Future Enhancements

- Sonarr API integration for dynamic batch windows
- Queue priority system (by age, size, or user preference)
- Multi-level queue priorities

Closes issues with queue management, state synchronization, and transfer 
completion accuracy for series/anime auto-sync workflow.
```