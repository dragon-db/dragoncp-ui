# Realtime (Socket.IO) Reference

Last updated: 2026-10-05
Primary files: `websocket.py`, `app.py`, `services/transfer_service.py`, `services/transfer_coordinator.py`, `services/queue_manager.py`, `services/backups/service.py`, `services/rename_service.py`, `services/sync_engine/engine.py`, `services/alert_service.py`, `routes/webhooks.py`, `frontend/src/services/socket.ts`, `frontend/src/hooks/useRuntime.ts`

## Realtime is opt-in

Nothing in DragonCP connects a socket by itself. The browser creates the Socket.IO client with `autoConnect: false` (`frontend/src/services/socket.ts`) and only calls `connectSocket()` when `realtimeRequested` is true in the runtime store. That flag is set by the **Enable realtime** button in the connection popover (`frontend/src/components/layout/realtime-status.tsx`, which calls `enableRealtime()` in `frontend/src/hooks/useRuntime.ts`). Until someone presses it, the app runs with no socket at all.

With realtime off, every page still works, because the React Query hooks poll on their own timers: active transfers every 5 seconds, one transfer's status or its open log every 2 seconds, and queue status every 5 seconds (`frontend/src/hooks/useTransfers.ts`). Transfer **history** does not poll at all - `useAllTransfers` sets no `refetchInterval`, so the History tab only refreshes on an explicit refetch, webhook and rename notifications every 10 seconds (`frontend/src/hooks/useWebhooks.ts`), runtime status on its own interval (`frontend/src/hooks/useConfig.ts`). Turning realtime on does not switch polling off — the socket runs *alongside* the polling and mostly serves to make updates appear sooner and to raise toasts.

What this means if you build on these events:

- **Never treat a socket event as the only delivery of a fact.** A user with realtime off will never receive it. Anything that must be durable has to be written to the database and exposed through the REST API (see [`api.md`](api.md)); the event is a hint that the API has something new.
- **Every listener needs a polling equivalent.** That is how the existing pages are written: the transfers page uses `transfer_progress` to patch the query cache in place and `transfer_complete`/`transfer_queued`/`transfer_promoted` to trigger a refetch, all of which the 2–5 second poll would eventually have done anyway.
- **Events are broadcast to everyone.** Apart from `transfer_logs` (see [Log streaming](#log-streaming-and-rooms)), no emit passes a `room`, `to`, or `namespace` argument, so every connected client receives every event regardless of which user started the work. There is no per-user filtering to rely on.
- **Emits are best-effort.** In `routes/webhooks.py` the emit is wrapped by `emit_socketio_event()`, which swallows and logs any exception so a failed emit never fails the webhook. In `services/backups/service.py` they go through `_emit()`, which swallows and logs the same way. The sync engine (`_event` and `_emit_run` in `services/sync_engine/engine.py`) and the alert service (`_emit` in `services/alert_service.py`) also swallow a failed emit, but **without logging it**, so a broken emit there leaves no trace. If nobody is listening, nothing anywhere notices.

## Server-emitted events

Events are emitted on the default namespace (`/`). Most are broadcast to every
connected client; `transfer_logs` is the exception — it goes only to clients
that asked for that transfer's output. See
[Log streaming](#log-streaming-and-rooms).

| Event | What triggers it | Emitted by | Payload fields |
|---|---|---|---|
| `transfer_progress` | Every line rsync writes while a transfer is running (the socket is *not* throttled; only the database writes are) | `services/transfer_service.py` | `transfer_id`, `progress` (the raw rsync line), `log_count`, `status` (always `"running"`), `stats`. **No log body** — see `transfer_logs` |
| `transfer_progress` | Per file, while a backup restore runs | `services/backups/service.py` (`_run_restore`) | `transfer_id` (a synthetic `restore_<epoch>_<hex>` id), `status` (`"running"`), `progress` (`"Restoring 2/5: <filename>"`), `folder_name` (the slot, e.g. `Example Show (2024) — S01E01`) |
| `transfer_complete` | The rsync monitor thread has seen the process exit | `services/transfer_service.py` | `transfer_id`, `status` (`completed`, `failed`, `paused` or `cancelled`), `message`, `log_count`, `stats`. **No log body** |
| `transfer_complete` | The rsync monitor thread itself raised — the transfer row is forced to `failed` | `services/transfer_service.py` | `transfer_id`, `status` (`"failed"`), `message`, `log_count` — **no** log body and **no** `stats` on this path |
| `transfer_complete` | A backup restore finished, successfully or not | `services/backups/service.py` (`_finish_restore`) | `transfer_id`, `status` (`completed` / `failed`), `message`, `folder_name` |
| `transfer_queued` | A new transfer is held because another transfer already owns the destination path | `services/transfer_coordinator.py:238` | `transfer_id`, `status` (`"queued"`), `queue_type` (`"path"`), `existing_transfer_id`, `dest_path`, `message` |
| `transfer_queued` | A new transfer is held because the concurrency cap is reached | `services/transfer_coordinator.py:277` | `transfer_id`, `message` (`"Transfer added to queue"`) |
| `transfer_queued` | A paused transfer was resumed but had to go back into the queue | `services/transfer_coordinator.py:515` | `transfer_id`, `message` (`"Resumed transfer added to queue"`) |
| `transfer_promoted` | A path-queued transfer got its destination path back and is about to start | `services/queue_manager.py:372` | `transfer_id`, `message`, `queue_type` (`"path"`) |
| `transfer_promoted` | A slot-queued transfer got a free running slot and is about to start | `services/queue_manager.py:492` | `transfer_id`, `message` (`"Transfer promoted from queue"`) |
| `transfer_logs` | A transfer produced output **and** at least one client is subscribed to it. Also once at completion | `services/transfer_service.py:_emit_logs` | `transfer_id`, `logs` (tail of at most 100 lines), `log_count`, `status`. **Room-scoped**, not broadcast |
| `webhook_received` | A real (non-test) Radarr/Sonarr webhook was parsed and stored. Sent before the webhook is handed to the sync engine, so it says nothing about the batch it joins | `routes/webhooks.py:174` (movies), `:319` (series), `:463` (anime) | `notification_id`, `title`, `media_type` (`movies` / `tvshows` / `anime`), `auto_sync` (whether auto-sync is on for that media type), `message`, `timestamp` |
| `test_webhook_received` | A webhook the receiver classified as a test (`eventType == "Test"`, title `Test Title`, or `testpath` in the folder path) | `routes/webhooks.py:133` (movies), `:259` (series), `:403` (anime) | `message`, `timestamp` |
| `rename_webhook_received` | A Sonarr `Rename` webhook was parsed and stored, before the renames are executed | `services/rename_service.py:83` | `notification_id`, `series_title`, `total_files`, `media_type`, `timestamp` |
| `rename_completed` | The rename run finished **and** its history row was updated successfully | `services/rename_service.py:146` | The whole result object: `notification_id`, `series_title`, `media_type`, `total_files`, `success_count`, `failed_count`, `status` (`completed` / `partial` / `failed`), `renamed_files`, `completed_at`, `message` |
| `backup_retention` | The automatic retention sweep deleted stored versions after a sync | `services/backups/service.py` (`_apply_retention_quietly`) | `deleted` (count), `reclaimed` (bytes), `summary` (the titles as a phrase), `items` (up to 10 removed versions, each with its display name, sizes and full library/backup paths). Only emitted when something was actually removed |
| `sync_run_updated` | A sync run changed: every stage outcome the engine records (`_stage`), every write to the run's own row (`_update`, so every state change), and after the rest of a run's stages are marked skipped (`_skip_rest`) or a refusal's Tell stage is recorded (`_refuse`) | `services/sync_engine/engine.py:382` (`_emit_run`) | The run as one list row, built by `SyncEngine.summarise()`: `run_id`, `kind`, `kind_label`, `label` (e.g. `Example Show — Season 01`), `title`, `season_name`, `media_type`, `source`, `state`, `state_label`, `current_stage`, `outcome`, `outcome_message`, `transfer_id`, `parent_run_id`, `parent_relation`, `is_simulation`, `requested_by` (`kind`, `name`, `label`), `stages` (nine `{id, status}` objects, in pipeline order), `webhook_count` (**always `null` here**; only the REST list fills it), `next_check_at` (ISO-8601), `created_at`, `updated_at`, `started_at`, `finished_at` |
| `sync_run_event` | A line was added to a run's log: every stage outcome recorded with a sentence, plus the engine's free-standing lines (a webhook joining, a follow-up opening, a restart, what recovery found after a restart) | `services/sync_engine/engine.py:371` (`_event`) | `run_id`, `event`: the stored `sync_run_event` row — `id`, `run_id`, `stage`, `level` (`info` / `success` / `warning` / `error`), `message`, `data` (object or `null`), `created_at` |
| `alerts_changed` | An alert opened or was bumped (`raise_alert`), an admin acted on one (`act`), or DragonCP closed one itself because Sonarr answered again or a failing job succeeded (`integration_up`, `job_recovered`) | `services/alert_service.py:130` (`_emit`) | `open` (how many alerts are open), `by_severity` (open counts keyed by severity, e.g. `{"warning": 2, "failure": 1}`). Counts only: no alert is in the payload |

`stats` on the transfer events is the five-field object built by `build_progress_stats()` in `services/transfer_service.py:138`: `progress_percent`, `bytes_transferred`, `total_bytes`, `speed_bps`, `eta_seconds`. Individual fields may be `null` when rsync has not reported them yet.

The three sync-engine events are hints, like every other event here. Each has a
REST equivalent that holds the same fact, which is what a page must poll (see
[`../features/sync-engine/README.md`](../features/sync-engine/README.md#api)):

| Event | Poll instead |
|---|---|
| `sync_run_updated` | `GET /api/sync/runs` (the same row, with `webhook_count` filled in) or `GET /api/sync/runs/<run_id>` |
| `sync_run_event` | `GET /api/sync/runs/<run_id>/events?after=<last id seen>` — the route says it exists for "what a live view polls for between socket events" |
| `alerts_changed` | `GET /api/alerts/summary` (the same two fields) and `GET /api/alerts` for the alerts themselves |

Behaviours worth knowing before you rely on an event:

- **Nothing in the React client listens to the three sync-engine events yet.**
  `frontend/src/` has no reference to `sync_run_updated`, `sync_run_event` or
  `alerts_changed`, nor to `/api/sync/` or `/api/alerts` (checked 2026-10-05):
  the pipeline view and the Notifications tab that will use them are not built.
  Whoever builds them must poll the REST equivalents above and treat the events
  as a reason to refetch sooner.
- **`sync_run_updated` is not throttled and arrives in bursts.** One step of a
  run usually emits it more than once — once for the stage, once for the run's
  state — and each emit re-reads the run and its nine stage rows from SQLite.
  Read it as "refetch this run", not as a list of distinct changes.
- **Not every stage change writes a log line.** Stages marked skipped in bulk
  (`_skip_rest`, e.g. "Not reached: an earlier stage failed.") and the Tell
  stage after a refusal are written straight to `sync_run_stage`, so they arrive
  as `sync_run_updated` only, never as `sync_run_event`.
- **`rename_completed` is skipped when the history write fails.** `services/rename_service.py` returns early if `rename_model.update()` reports failure, so the files were renamed on disk but no completion event is sent. Only the REST rename history will show what happened.
- **There is no separate failure event for transfers.** A failed rsync arrives as `transfer_complete` with `status: "failed"`, which is exactly how the transfers page and the runtime toast handler distinguish it (`frontend/src/hooks/useRuntime.ts` shows an error toast when `payload.status === "failed"`). See [Known defects](#known-defects).

### Client-to-server events

| Event | Sent when | Handled by | Response |
|---|---|---|---|
| `connect` (handshake) | The user enables realtime | `websocket.py:87` | Handler returns `False` to reject, `True` to accept |
| `activity` | Any click, keypress, form submit or touch in the browser, throttled to once per 1.5 s; also on **Extend** and when a timeout is deferred | `websocket.py:155` | None — it just refreshes `last_activity` |
| `authenticate` | After the axios interceptor refreshes the access token (`reAuthenticateSocket()` in `frontend/src/services/socket.ts`) | `websocket.py` | Acknowledgement callback: `{success: true, user}` or `{success: false, message}` |
| `transfer_logs_subscribe` | A transfer's row is expanded in the UI, and on every reconnect for rows still open | `websocket.py` | None. Joins room `transfer_logs:<transfer_id>` |
| `transfer_logs_unsubscribe` | The row is collapsed or the page unmounts | `websocket.py` | None. Leaves the room |

## Log streaming and rooms

rsync output is the largest thing this application pushes, and it only matters
to whoever has that transfer's row open. It used to ride along on every
`transfer_progress` broadcast: roughly 4.4 KB per event against 297 bytes for
the same event without it — **93% of the payload**, sent to every connected
client several times a second whether or not anyone was reading it.

Output now travels on its own event, scoped to a room per transfer:

```text
client expands a row  ->  transfer_logs_subscribe {transfer_id}
                          server: join_room("transfer_logs:<id>")
rsync writes a line   ->  transfer_progress   broadcast, ~300 bytes, no log body
                      ->  transfer_logs       only to that room
client collapses row  ->  transfer_logs_unsubscribe {transfer_id}
```

Three properties worth knowing:

- **Unwatched transfers cost nothing extra.** `_emit_logs` checks
  `has_log_subscribers()` before assembling anything, so a transfer nobody is
  watching never builds a log payload at all.
- **Subscriptions survive a reconnect.** Rooms live on the server connection and
  are lost when a socket drops, so `frontend/src/services/socket.ts` keeps the
  set of wanted transfers and replays it on `connect`.
- **The polling path is unchanged.** Realtime is opt-in, so an open log panel
  refreshes on its own 2-second poll regardless; the subscription only makes it
  arrive sooner. Nothing depends on the socket being enabled.

The registry is cleaned up on disconnect (`websocket.py:_drop_subscriber`),
otherwise a dropped client would keep a transfer looking watched and the
producer would keep building payloads for nobody.

## Connection lifecycle

### Handshake and authentication

The client connects with `auth: { token }` carrying the current access token. `handle_connect()` in `websocket.py` reads that dict and passes it to `validate_websocket_token()` in `auth.py`, which validates it as an **access** token and returns the username claim. A missing auth payload or an invalid token makes the handler return `False`, which rejects the handshake; both cases are logged with the reason (`missing-auth-payload` or `invalid-or-missing-token`), the truncated session id and the transport.

A token in the query string is only considered when the environment flag `ALLOW_QUERY_TOKEN_AUTH` is truthy (`1`, `true`, `yes`, `on`). It defaults to off and is read at import time from `os.environ` — see the note in [`../features/auth/README.md`](../features/auth/README.md) about that flag not being readable from the env file.

Accepted connections are stored in an in-process dictionary guarded by a lock, keyed by socket session id, holding `connected_at`, `last_activity`, `timeout_seconds`, `username`, `transport` and `origin`. Disconnects pop the entry.

Because the identity is fixed at handshake time, a token refresh would leave the socket holding a stale one. The `authenticate` event is the repair path: the client re-sends the new token, the server re-validates it and updates the stored username and activity timestamp. On failure the server only declines — it does **not** disconnect. The client-side handler does, though: `reAuthenticateSocket()` disconnects and reconnects when the acknowledgement is not a success.

Transport and CORS are configured in `app.py`: `async_mode='threading'`, `ping_interval=25` seconds, `ping_timeout=60` seconds, with CORS origins from `get_cors_origins()`. The client requests `["polling", "websocket"]` with upgrade enabled, so a session normally starts on long-polling and upgrades.

### The activity ping

While the socket is connected, `frontend/src/hooks/useRuntime.ts` listens for `click`, `keydown`, `submit` and `touchstart` on the document. Each one calls `sendActivityPing()` (which emits `activity`) and marks activity locally, throttled to at most once every 1.5 seconds. The **Extend** button in the connection popover sends the same ping on demand.

The browser also runs its own countdown on a 15 second interval:

- Two minutes before the deadline it raises a warning toast (once per connection).
- At the deadline it first calls `GET /api/transfers/active`. If any transfer is running it keeps the session alive — marking activity and sending another ping — and tells the user the timeout was prevented. Otherwise it disconnects the socket, flags the state as auto-disconnected, and says polling remains active.

The client's countdown uses `WEBSOCKET_TIMEOUT_MINUTES` from `GET /api/config`, defaulting to `30` when absent, and is clamped to 5–60 minutes by the runtime store.

### The idle sweeper

`start_cleanup_thread(socketio)` is called once during startup in `app.py` and starts a single daemon thread named `dragoncp-websocket-cleanup` (it refuses to start a second one if the first is alive). Every five seconds the loop calls `reap_stale_connections()`:

1. Takes a snapshot of the connection map.
2. Re-validates the account id, auth source and token version recorded at handshake.
3. Compares `last_activity` against that connection's own `timeout_seconds`.
4. For a revoked or expired connection, calls `socketio.server.disconnect(sid=..., namespace='/')`, removes the entry, and logs it.

Revocation and an expired idle deadline therefore have at most about five
seconds of sweep delay. In practice the browser's own countdown usually
disconnects an ordinary idle session first.

### Timeout constants and how configurable they are

Defined at the top of `websocket.py`:

| Constant | Value | Role |
|---|---|---|
| `WEBSOCKET_TIMEOUT_DEFAULT` | 35 minutes | Used when the session carries no configured timeout |
| `WEBSOCKET_TIMEOUT_MAX` | 65 minutes | Hard ceiling on any computed timeout |
| `WEBSOCKET_TIMEOUT_MIN` | 5 minutes | Declared but never referenced anywhere in the codebase |
| `AUTH_SWEEP_SECONDS` | 5 seconds | Maximum interval between independent identity/idle sweeps |

These are literals in the source. **There is no environment variable or setting that changes them** — the only tunable is the per-session value.

`get_websocket_timeout_for_session()` computes that value at handshake time. It reads `WEBSOCKET_TIMEOUT_MINUTES` through the settings resolver, clamps it to 5–60 minutes, adds a 5-minute buffer, and caps the result at `WEBSOCKET_TIMEOUT_MAX`. With no value present it returns the 35-minute default.

The setting lives in the **database** (`app_settings`), written by `POST /api/config` from the Settings page. It used to be read out of the Flask session's `ui_config`, which meant the value an operator saved was visible only to their own browser: the server's own stale-connection sweeper never saw it and stayed on 35 minutes regardless. Reading it from the database removes the question of whether a session cookie accompanies the handshake — it does not need one.

The buffer is deliberate: the server always waits five minutes longer than the client's own countdown, so the browser is the one that normally ends an idle session and the sweeper is the backstop for clients that vanished.

### Inspecting live connections

Three authenticated endpoints report on the socket layer (all in `routes/debug.py`):

- `GET /api/runtime/status` — `active_connections`, `cleanup_thread_running`, and the static `socketio_runtime_info` block (async mode, ping interval/timeout, whether the WebSocket transport is available). This is the endpoint the frontend polls for backend/SSH reachability.
- `GET /api/websocket/status` — the same counts plus `default_timeout_minutes`, `max_timeout_minutes`, and per-connection details (truncated session id, minutes since connect, minutes since last activity, that connection's timeout, transport). The connection count shown in the popover comes from here, via `useWebSocketStatus()`.
- `GET /api/debug` — includes the same websocket block along with the session's configured timeout.

## Known defects

None open. The three recorded here on 2026-07-28 were rechecked on 2026-10-05
and are fixed:

- **The frontend no longer subscribes to `transfer_failed`.** `onTransferError()` is gone from `frontend/src/services/socket.ts`; a comment in its place says a failure arrives as `transfer_complete` with `status: "failed"`. No server code emits `transfer_failed`. The string does appear in `services/alert_service.py`, but as the name of an alert kind (`alert.kind`), not as a socket event.
- **`TransferUpdate` no longer overstates its payload.** Every field but `transfer_id` is optional, which matches `transfer_queued` (the emits at `services/transfer_coordinator.py:277` and `:515` send only `transfer_id` and `message`) and `transfer_promoted`.
- **`app.py` no longer imports `WEBSOCKET_TIMEOUT_MAX` or `WEBSOCKET_TIMEOUT_DEFAULT`.**

The table above accounts for every server emit: twenty-one call sites across `services/` and `routes/`. `services/backups/service.py` sends its three events through one `_emit()`, and `routes/webhooks.py` makes its six through `emit_socketio_event()`; with that helper's own definition, these are the twenty-two lines a repository-wide search for `socketio.emit` and `emit_socketio_event(` returns (the virtualenv aside).

## Not verified

- **Not verified**: behaviour under multiple backend workers. The connection map, the sweeper thread and the queue manager's state are all process-local, and `socketio_runtime_info` names `gunicorn --config deploy/gunicorn.conf.py app:app` as the recommended production server, but I did not read that config or test a multi-worker run, so I cannot say how emits and idle cleanup behave across workers.
- **Not verified**: behaviour across a real process restart with an active
  browser and transfer; release validation for the React cutover covers this.
- **Not verified**: the three sync-engine events on a running server. Their
  rows above are read from the code; no test exercises them, because the engine
  and alert-service tests (`tests/test_sync_engine.py` and the modules built on
  it) construct both without a socket, and no client listens yet.

## Related documentation

- [`../features/queue/README.md`](../features/queue/README.md) — what `transfer_queued` and `transfer_promoted` mean in queue terms
- [`../features/transfers/README.md`](../features/transfers/README.md) — the transfer lifecycle behind `transfer_progress` and `transfer_complete`
- [`../features/webhooks/README.md`](../features/webhooks/README.md) and [`../features/renames/README.md`](../features/renames/README.md) — the receivers that emit the webhook and rename events
- [`../features/sync-engine/README.md`](../features/sync-engine/README.md) — the runs, stages and alerts behind `sync_run_updated`, `sync_run_event` and `alerts_changed`
- [`database-schema.md`](database-schema.md) — the `sync_run`, `sync_run_event` and `alert` tables those payloads are read from
- [`../features/auth/README.md`](../features/auth/README.md) — token validation, refresh, and the `ALLOW_QUERY_TOKEN_AUTH` flag
- [`api.md`](api.md) — the REST surface that every event is a hint about
- [`frontend.md`](frontend.md) — where the client-side pieces live
