# Queue Management System Implementation

**Version**: v1.9.0  
**Date**: October 31, 2024  
**Feature**: Advanced Queue Management with Duplicate Detection

---

## Overview

This document describes the implementation of the new queue management system with STRICT destination path validation for DragonCP. The system prevents duplicate syncs to the same destination and limits concurrent transfers to 3 at a time.

---

## Key Features

### 1. **STRICT Duplicate Destination Validation**
- **When**: Before any transfer starts (auto-sync or manual)
- **How**: Checks if an active/running transfer already has the same destination path
- **Action**: Marks new transfer as `duplicate` status if destination conflict detected
- **Normalization**: Paths are normalized (absolute, case-insensitive on Windows, trailing slash removed)

### 2. **Queue System (Max 3 Concurrent Transfers)**
- **Limit**: Maximum 3 transfers can run simultaneously
- **Queuing**: Additional transfers are marked as `queued` status
- **Auto-Promotion**: When a transfer completes, the oldest queued transfer is automatically promoted to `pending` and starts
- **Applies To**: ALL transfers (movies auto-sync, series/anime auto-sync, manual syncs)

### 3. **New Transfer Statuses**
- **`queued`**: Transfer is waiting for an available slot (< 3 running transfers)
- **`duplicate`**: Transfer was rejected due to duplicate destination path

---

## Architecture

### New Component: QueueManager

**File**: `services/queue_manager.py`

**Responsibilities**:
- Track active destinations to prevent duplicates
- Limit concurrent transfers to 3
- Manage queue of pending transfers
- Auto-promote queued transfers when slots become available

**Key Methods**:
- `check_duplicate_destination(dest_path)`: STRICT validation for duplicate paths
- `register_transfer(transfer_id, dest_path)`: Register and queue/start transfer
- `unregister_transfer(transfer_id)`: Unregister completed transfer and promote next
- `get_queue_status()`: Get current queue statistics

### Updated Components

#### 1. TransferCoordinator
**File**: `services/transfer_coordinator.py`

**Changes**:
- Initialize QueueManager before starting transfers
- STRICT duplicate check BEFORE creating transfer record
- Queue management integration in `start_transfer()`
- Unregister transfers on completion in `_post_transfer_completion()`
- New method: `start_queued_transfer()` for promoting queued transfers
- New method: `get_queue_status()` for queue statistics

#### 2. TransferService
**File**: `services/transfer_service.py`

**Changes**:
- Accept `queue_manager` parameter in constructor
- Enhanced `cancel_transfer()` to handle queued transfers

#### 3. Transfer Routes
**File**: `routes/transfers.py`

**Changes**:
- `/api/transfers/active` now returns `queue_status` object
- New endpoint: `/api/transfers/queue/status` for queue statistics

#### 4. Frontend (Transfer Manager)
**File**: `static/modules/transfer-manager.js`

**Changes**:
- `loadActiveTransfers()` now processes queue status
- New method: `updateQueueStatusDisplay()` to show queue info in badge
- Badge shows: `"X/3 running, Y queued"` format

#### 5. Frontend (CSS)
**File**: `static/style.css`

**Changes**:
- New CSS class: `.transfer-status-queued` (cyan badge)
- New CSS class: `.transfer-status-duplicate` (orange badge)

---

## Flow Diagrams

### Transfer Start Flow with Queue Management

```
User/Webhook triggers transfer
        │
        ▼
┌───────────────────────────────────────┐
│ TransferCoordinator.start_transfer()  │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ STRICT CHECK:                         │
│ QueueManager.check_duplicate_dest()   │
└───────────────────────────────────────┘
        │
        ├─── Duplicate Found? ────────────> Mark as 'duplicate', Return False
        │
        ▼ No Duplicate
┌───────────────────────────────────────┐
│ QueueManager.register_transfer()      │
│ - Check if < 3 transfers running      │
└───────────────────────────────────────┘
        │
        ├─── Queue Full (3 running) ──────> Mark as 'queued', Return True
        │
        ▼ Slot Available
┌───────────────────────────────────────┐
│ Start Transfer Immediately            │
│ - Create DB record with 'running'     │
│ - Start rsync process                 │
│ - Start monitoring thread             │
└───────────────────────────────────────┘
```

### Transfer Completion and Promotion Flow

```
Transfer completes/fails/cancelled
        │
        ▼
┌───────────────────────────────────────┐
│ _post_transfer_completion()           │
│ - Update webhook status               │
│ - Send Discord notification           │
│ - Finalize backup                     │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ QueueManager.unregister_transfer()    │
│ - Remove from active destinations     │
│ - Remove from running transfers       │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ QueueManager._promote_next_queued()   │
│ - Get oldest queued transfer          │
│ - Re-check for duplicate destination  │
│ - Update status to 'pending'          │
│ - Call coordinator.start_queued()     │
└───────────────────────────────────────┘
```

---

## Database Schema

### Transfer Status Values

The `transfers` table `status` column now supports these values:

| Status | Description |
|--------|-------------|
| `pending` | Transfer is ready to start (initial state) |
| `running` | Transfer is currently in progress |
| `queued` | Transfer is waiting for an available slot |
| `duplicate` | Transfer was rejected due to duplicate destination |
| `completed` | Transfer finished successfully |
| `failed` | Transfer encountered an error |
| `cancelled` | Transfer was cancelled by user |

**Note**: No schema migration required as `status` is TEXT type.

---

## API Changes

### Endpoint: `GET /api/transfers/active`

**Response** (new field added):
```json
{
  "status": "success",
  "transfers": [...],
  "total": 5,
  "queue_status": {
    "max_concurrent": 3,
    "running_count": 2,
    "queued_count": 3,
    "available_slots": 1,
    "running_transfer_ids": ["transfer1", "transfer2"],
    "queued_transfer_ids": ["transfer3", "transfer4", "transfer5"],
    "active_destinations": ["transfer1", "transfer2"]
  }
}
```

### New Endpoint: `GET /api/transfers/queue/status`

**Response**:
```json
{
  "status": "success",
  "queue": {
    "max_concurrent": 3,
    "running_count": 2,
    "queued_count": 1,
    "available_slots": 1,
    "running_transfer_ids": ["transfer1", "transfer2"],
    "queued_transfer_ids": ["transfer3"],
    "active_destinations": ["transfer1", "transfer2"]
  }
}
```

---

## WebSocket Events

### New Events Emitted by QueueManager

1. **`transfer_duplicate`**
   - **When**: Duplicate destination detected
   - **Payload**:
     ```json
     {
       "transfer_id": "movie_123_456",
       "existing_transfer_id": "movie_123_455",
       "dest_path": "/mnt/media/Movies/Example (2024)",
       "message": "Duplicate destination detected"
     }
     ```

2. **`transfer_queued`**
   - **When**: Transfer added to queue (3 already running)
   - **Payload**:
     ```json
     {
       "transfer_id": "series_789_012",
       "message": "Transfer added to queue"
     }
     ```

3. **`transfer_promoted`**
   - **When**: Queued transfer promoted to running
   - **Payload**:
     ```json
     {
       "transfer_id": "series_789_012",
       "message": "Transfer promoted from queue"
     }
     ```

---

## Use Cases

### Use Case 1: Series Episode Batch (Your Original Scenario)

**Scenario**: 10 episode notifications received in 10 seconds for the same season

**Behavior**:
1. **First episode notification** arrives → Auto-sync triggered after 60s wait time
   - Destination: `/mnt/media/TV Shows/Series Name (2024)/Season 01`
   - Status: `running` (slot 1/3)

2. **Second episode notification** (2 seconds later) → Auto-sync triggered after 60s wait
   - **Same destination**: `/mnt/media/TV Shows/Series Name (2024)/Season 01`
   - **STRICT CHECK**: Duplicate detected!
   - Status: `duplicate` (not queued, not started)
   - User sees in UI: Orange badge "duplicate"

3. **Episodes 3-10**: Same as #2, all marked as `duplicate`

**Result**: Only ONE sync runs for the entire season, preventing conflicts and redundant operations.

---

### Use Case 2: Multiple Different Transfers

**Scenario**: User triggers 5 different movie syncs manually

**Behavior**:
1. **Movies 1-3**: Start immediately
   - Status: `running` (slots 1/3, 2/3, 3/3)

2. **Movies 4-5**: Queue is full
   - Status: `queued`
   - User sees in UI: Badge shows "3/3 running, 2 queued"

3. **Movie 1 completes**: 
   - Movie 4 auto-promoted to `running`
   - Badge updates: "3/3 running, 1 queued"

4. **Movie 2 completes**:
   - Movie 5 auto-promoted to `running`
   - Badge updates: "3/3 running"

---

### Use Case 3: Mixed Auto-Sync and Manual Sync

**Scenario**: 2 auto-syncs running, user starts 3 manual syncs

**Behavior**:
1. **Auto-syncs 1-2**: Running (slots 1/3, 2/3)
2. **Manual sync 1**: Starts immediately (slot 3/3)
3. **Manual syncs 2-3**: Queued
4. **Queue system treats all equally**: Auto-syncs and manual syncs share the same queue

---

## Configuration

### Queue Settings

**File**: `services/queue_manager.py`

```python
class QueueManager:
    # Maximum number of concurrent transfers allowed
    MAX_CONCURRENT_TRANSFERS = 3
```

**To Change**: Modify `MAX_CONCURRENT_TRANSFERS` constant in `QueueManager` class.

---

## UI Display

### Active Transfers Badge

**Before**:
```
[2 active]
```

**After** (with queue):
```
[2/3 running, 1 queued]
```

### Transfer Status Badges

| Status | Badge Color | CSS Class |
|--------|-------------|-----------|
| Running | Blue | `.transfer-status-running` |
| Pending | Yellow | `.transfer-status-pending` |
| **Queued** | **Cyan** | **`.transfer-status-queued`** |
| **Duplicate** | **Orange** | **`.transfer-status-duplicate`** |
| Completed | Green | `.transfer-status-completed` |
| Failed | Red | `.transfer-status-failed` |
| Cancelled | Gray | `.transfer-status-cancelled` |

---

## Testing Scenarios

### Test 1: Duplicate Detection
1. Start a manual sync for a movie
2. Immediately start another sync for the SAME movie
3. **Expected**: Second sync marked as `duplicate`

### Test 2: Queue System
1. Start 3 different movie syncs quickly
2. Start a 4th sync
3. **Expected**: 
   - First 3 show `running`
   - 4th shows `queued`
   - Badge shows "3/3 running, 1 queued"

### Test 3: Auto-Promotion
1. Have 3 transfers running and 2 queued
2. Cancel one running transfer
3. **Expected**: 
   - First queued transfer auto-promoted to `running`
   - Badge updates to "3/3 running, 1 queued"

### Test 4: Series Episode Batching
1. Trigger 10 episode notifications for same season within 10 seconds
2. **Expected**:
   - First one goes through auto-sync
   - Remaining 9 marked as `duplicate`
   - Only ONE actual rsync runs

---

## Limitations and Edge Cases

### Handled Edge Cases

1. **App Restart During Queue**: 
   - `force_unregister_stale_transfers()` cleans up stale tracking on startup
   
2. **Path Normalization**: 
   - Windows paths are case-insensitive
   - Trailing slashes removed
   - Relative paths converted to absolute

3. **Cancelled Queued Transfers**: 
   - Can cancel queued transfers before they start
   - Status updated to `cancelled`

### Known Limitations

1. **Queue Persistence**: Queue is in-memory, not persisted to database
   - On app restart, queued transfers revert to `pending` status
   
2. **Queue Order**: FIFO (First In, First Out) based on `created_at` timestamp
   - No priority system for transfers

3. **Destination Comparison**: Based on destination path string only
   - Doesn't check if files are identical (relies on rsync)

---

## Troubleshooting

### Issue: Transfers stuck in "queued" status

**Cause**: Running transfers may have crashed without cleanup

**Solution**:
1. Restart the app (cleanup runs on startup)
2. Or manually cancel stuck transfers

### Issue: False duplicate detection

**Cause**: Path normalization differences

**Debug**:
```python
# Check normalized paths in logs
print(f"Normalized: {queue_manager._normalize_path(dest_path)}")
```

### Issue: Too many transfers queued

**Cause**: High incoming webhook rate

**Solution**: Increase `MAX_CONCURRENT_TRANSFERS` in `queue_manager.py`

---

## Future Enhancements

1. **Priority Queue**: Add priority levels for transfers
2. **Configurable Max Concurrent**: Make `MAX_CONCURRENT_TRANSFERS` a UI setting
3. **Queue Persistence**: Store queue state in database
4. **Smart Batching**: Auto-merge queued transfers with same source/dest
5. **Bandwidth Management**: Dynamic queue size based on available bandwidth

---

## Summary of Changes

### New Files
- `services/queue_manager.py` - Queue management service

### Modified Files
- `services/transfer_coordinator.py` - Queue integration
- `services/transfer_service.py` - Queue-aware transfer handling
- `routes/transfers.py` - Queue status API endpoints
- `static/modules/transfer-manager.js` - Queue UI display
- `static/style.css` - New status badge styles
- `templates/index.html` - Version bump to v1.9.0

### Database
- No schema changes required (status is TEXT type)
- New status values: `queued`, `duplicate`

---

## Rollback Instructions

If issues arise, to rollback:

1. **Remove Queue Manager**:
   - Delete `services/queue_manager.py`
   
2. **Revert TransferCoordinator**:
   - Remove `QueueManager` import and initialization
   - Revert `start_transfer()` to directly start transfers
   
3. **Revert Version**:
   - Change `v1.9.0` back to `v1.8.5` in `templates/index.html`

---

## Version History

- **v1.9.0** (Oct 31, 2024): Queue management with duplicate detection
- **v1.8.5** (Previous): Series/anime auto-sync with dry-run validation

