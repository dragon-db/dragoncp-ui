# Rsync Log Streaming Redesign Plan (No Implementation Yet)

## 1. Purpose

This document explains the plan to improve transfer logging.

Main goals:

1. Stop storing full rsync raw logs in the database.
2. Keep live logs in real time for the UI.
3. Keep only useful final data in DB (summary + errors + small excerpt).
4. Support recovery when the server app restarts.

This is a planning document only.  
No code changes are part of this document.

---

## 2. Current Problem (Simple)

Today, each rsync output line is saved to DB immediately.

That means for every line:

1. Read full logs list from DB.
2. Add one new line.
3. Write full logs list back to DB.

Why this is bad:

1. Too many DB writes.
2. Slower as logs get larger.
3. Unnecessary storage of progress spam lines.

---

## 3. Target Behavior

### During transfer (live)

`rsync output -> server -> websocket -> UI`

Key idea:

1. Use in-memory buffering for live logs.
2. Push log chunks to UI in real time.
3. Do not save every line to DB.

### After transfer (final persistence)

Save only:

1. Parsed summary stats.
2. Error lines.
3. Compact excerpt (small tail + key lines).

Do not save full raw logs in DB.

---

## 4. Important Clarification About Restart

Question: "If server restarts, why not reconnect to rsync subprocess?"

Answer:

1. Reconnecting to process identity (PID) is possible.
2. Reconnecting to old stdout pipe is not reliable with current `stdout=PIPE` model.

Best practical design:

1. Write rsync output to a per-transfer log file.
2. Server tails this file and sends logs to websocket.
3. Save read offset in DB.
4. After restart, server can resume reading from last offset if process is still running.

This provides restart-safe log continuity.

---

## 5. Data Model Plan

## 5.1 Keep using `transfers` table

Continue using `transfers` as main lifecycle table.

Add fields:

1. `rsync_summary` (JSON text): parsed final stats.
2. `log_excerpt` (JSON text): compact saved log lines.

Note: Existing `logs` field can be repurposed as excerpt for backward compatibility if needed.

## 5.2 Add runtime tracking table (recommended)

Create `transfer_runtime` table for active process tracking:

1. `transfer_id` (primary key, foreign key to transfer).
2. `pid`.
3. `process_start_time` (important for PID reuse safety).
4. `log_file_path`.
5. `last_read_offset`.
6. `state` (`running`, `completed`, `failed`, `lost`).
7. `exit_code` (nullable).
8. `updated_at`.

Cleanup rule:

1. On successful completion, runtime row can be removed (or marked completed based on preference).

---

## 6. Live Streaming Plan (WebSocket)

Current issue:

1. Logs are broadcast to all clients.

Planned improvement:

1. Use per-transfer subscription rooms.

### New websocket client events

1. `transfer_logs_subscribe` with `transfer_id`.
2. `transfer_logs_unsubscribe` with `transfer_id`.

### New websocket server events

1. `transfer_logs_snapshot` (initial recent lines).
2. `transfer_logs_chunk` (new lines).
3. `transfer_logs_end` (final state + summary).

Compatibility:

1. Keep existing `transfer_progress` and `transfer_complete` during migration.

---

## 7. API Plan (Backward Compatible)

Keep existing endpoint behavior to avoid breaking UI:

1. `GET /transfer/{transfer_id}/logs` still returns `logs` and `log_count`.

Change meaning carefully:

1. `logs` now represents compact excerpt (not full raw run).

Optional new fields:

1. `summary`.
2. `live_stream_available`.

Update docs:

1. `docs/api/openapi.yaml`
2. `docs/api/API_REFERENCE.md`

---

## 8. Rsync Summary Parser Plan

Parse final rsync output into structured fields:

1. number of files.
2. created/deleted/transferred counts.
3. total file size / transferred size.
4. bytes sent/received.
5. average speed.
6. speedup.
7. collected errors.

Why:

1. Better notifications.
2. Easier reporting.
3. Less reliance on raw logs.

---

## 9. Startup Recovery Plan

On server startup:

1. Find transfers marked `running`.
2. Check runtime row + PID + process start time.
3. If process alive, resume tailing log file from saved offset.
4. If process missing, mark transfer failed/lost.
5. Rebuild in-memory queue/path locks based on recovered active transfers.

---

## 10. Rollout Phases

## Phase 1 - Foundation

1. Add DB fields/tables (`rsync_summary`, `log_excerpt`, `transfer_runtime`).
2. Add log file writer/tailer and runtime state tracking.

## Phase 2 - Live streaming change

1. Add per-transfer websocket subscription.
2. Keep old websocket events for compatibility.

## Phase 3 - Persistence minimization

1. Stop per-line DB log writes.
2. Save only summary + errors + excerpt at end.

## Phase 4 - Hardening

1. Startup recovery and queue-state rebuild.
2. Retention cleanup for old raw log files.
3. Documentation updates.

---

## 11. Test Scenarios

1. Single transfer streams correctly.
2. Multiple transfers stream without mixing logs.
3. Subscriber joins mid-transfer and gets snapshot + new chunks.
4. Failed transfer captures error lines and final summary.
5. Server restart during transfer resumes tailing from last offset.
6. PID reuse safety check blocks wrong process attach.
7. Existing logs API still works for current UI.
8. DB write count is significantly reduced.

---

## 12. Acceptance Criteria

This plan is successful when:

1. No per-line full-log DB rewrites remain in rsync monitor path.
2. UI still gets real-time logs.
3. Full raw logs are not stored in DB.
4. Final summary + error info is saved clearly.
5. Restart recovery works with runtime metadata and log files.
6. Existing API/UI remains functional during migration.

---

## 13. Out of Scope (For This Plan)

1. Actual implementation.
2. Multi-server distributed log streaming.
3. Full redesign of queue manager.

This file is only the execution plan.
