# Realtime (Socket.IO) Reference

Last updated: 2026-07-28
Primary files: `websocket.py`, `app.py`, `services/transfer_service.py`, `services/transfer_coordinator.py`, `services/queue_manager.py`, `services/backups/service.py`, `services/rename_service.py`, `routes/webhooks.py`, `frontend/src/services/socket.ts`, `frontend/src/hooks/useRuntime.ts`

## Realtime is opt-in

Nothing in DragonCP connects a socket by itself. The browser creates the Socket.IO client with `autoConnect: false` (`frontend/src/services/socket.ts`) and only calls `connectSocket()` when `realtimeRequested` is true in the runtime store. That flag is set by the **Enable realtime** button in the connection popover (`frontend/src/components/layout/realtime-status.tsx`, which calls `enableRealtime()` in `frontend/src/hooks/useRuntime.ts`). Until someone presses it, the app runs with no socket at all.

With realtime off, every page still works, because the React Query hooks poll on their own timers: active transfers every 5 seconds, one transfer's status or its open log every 2 seconds, and queue status every 5 seconds (`frontend/src/hooks/useTransfers.ts`). Transfer **history** does not poll at all - `useAllTransfers` sets no `refetchInterval`, so the History tab only refreshes on an explicit refetch, webhook and rename notifications every 10 seconds (`frontend/src/hooks/useWebhooks.ts`), runtime status on its own interval (`frontend/src/hooks/useConfig.ts`). Turning realtime on does not switch polling off — the socket runs *alongside* the polling and mostly serves to make updates appear sooner and to raise toasts.

What this means if you build on these events:

- **Never treat a socket event as the only delivery of a fact.** A user with realtime off will never receive it. Anything that must be durable has to be written to the database and exposed through the REST API (see [`api.md`](api.md)); the event is a hint that the API has something new.
- **Every listener needs a polling equivalent.** That is how the existing pages are written: the transfers page uses `transfer_progress` to patch the query cache in place and `transfer_complete`/`transfer_queued`/`transfer_promoted` to trigger a refetch, all of which the 2–5 second poll would eventually have done anyway.
- **Events are broadcast to everyone.** No emit in the codebase passes a `room`, `to`, or `namespace` argument, so every connected client receives every event regardless of which user started the work. There is no per-user filtering to rely on.
- **Emits are best-effort.** In `routes/webhooks.py` the emit is wrapped by `emit_socketio_event()`, which swallows and logs any exception so a failed emit never fails the webhook. In `services/backups/service.py` they go through `_emit()`, which swallows and logs the same way. If nobody is listening, nothing anywhere notices.

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
| `transfer_queued` | A new transfer is held because another transfer already owns the destination path | `services/transfer_coordinator.py:144` | `transfer_id`, `status` (`"queued"`), `queue_type` (`"path"`), `existing_transfer_id`, `dest_path`, `message` |
| `transfer_queued` | A new transfer is held because the concurrency cap is reached | `services/transfer_coordinator.py:182` | `transfer_id`, `message` (`"Transfer added to queue"`) |
| `transfer_queued` | A paused transfer was resumed but had to go back into the queue | `services/transfer_coordinator.py:345` | `transfer_id`, `message` (`"Resumed transfer added to queue"`) |
| `transfer_promoted` | A path-queued transfer got its destination path back and is about to start | `services/queue_manager.py:329` | `transfer_id`, `message`, `queue_type` (`"path"`) |
| `transfer_promoted` | A slot-queued transfer got a free running slot and is about to start | `services/queue_manager.py:445` | `transfer_id`, `message` (`"Transfer promoted from queue"`) |
| `transfer_logs` | A transfer produced output **and** at least one client is subscribed to it. Also once at completion | `services/transfer_service.py:_emit_logs` | `transfer_id`, `logs` (tail of at most 100 lines), `log_count`, `status`. **Room-scoped**, not broadcast |
| `webhook_received` | A real (non-test) Radarr/Sonarr webhook was parsed and stored | `routes/webhooks.py:117` (movies), `:245` (series), `:370` (anime) | `notification_id`, `title`, `media_type` (`movies` / `tvshows` / `anime`), `auto_sync` (whether auto-sync is on for that media type), `message`, `timestamp` |
| `test_webhook_received` | A webhook the receiver classified as a test (`eventType == "Test"`, title `Test Title`, or `testpath` in the folder path) | `routes/webhooks.py:87` (movies), `:201` (series), `:326` (anime) | `message`, `timestamp` |
| `rename_webhook_received` | A Sonarr `Rename` webhook was parsed and stored, before the renames are executed | `services/rename_service.py:83` | `notification_id`, `series_title`, `total_files`, `media_type`, `timestamp` |
| `rename_completed` | The rename run finished **and** its history row was updated successfully | `services/rename_service.py:146` | The whole result object: `notification_id`, `series_title`, `media_type`, `total_files`, `success_count`, `failed_count`, `status` (`completed` / `partial` / `failed`), `renamed_files`, `completed_at`, `message` |

`stats` on the transfer events is the five-field object built by `build_progress_stats()` in `services/transfer_service.py:96`: `progress_percent`, `bytes_transferred`, `total_bytes`, `speed_bps`, `eta_seconds`. Individual fields may be `null` when rsync has not reported them yet.

Two behaviours worth knowing before you rely on an event:

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

`start_cleanup_thread(socketio)` is called once during startup in `app.py` and starts a single daemon thread named `dragoncp-websocket-cleanup` (it refuses to start a second one if the first is alive). The loop in `cleanup_stale_connections()`:

1. Takes a snapshot of the connection map.
2. For each connection, compares `last_activity` against that connection's own `timeout_seconds`.
3. For anything past its deadline, calls `socketio.server.disconnect(sid=..., namespace='/')`, removes the entry, and logs it.
4. Sleeps **5 minutes** and repeats.

So a connection can sit idle for up to its timeout plus almost five more minutes before the sweeper notices. In practice the browser's own countdown usually disconnects first.

### Timeout constants and how configurable they are

Defined at the top of `websocket.py`:

| Constant | Value | Role |
|---|---|---|
| `WEBSOCKET_TIMEOUT_DEFAULT` | 35 minutes | Used when the session carries no configured timeout |
| `WEBSOCKET_TIMEOUT_MAX` | 65 minutes | Hard ceiling on any computed timeout |
| `WEBSOCKET_TIMEOUT_MIN` | 5 minutes | Declared but never referenced anywhere in the codebase |

These are literals in the source. **There is no environment variable or setting that changes them** — the only tunable is the per-session value.

`get_websocket_timeout_for_session()` computes that per-session value at handshake time. It reads `WEBSOCKET_TIMEOUT_MINUTES` out of the Flask session's `ui_config`, clamps it to 5–60 minutes, adds a 5-minute buffer, and caps the result at `WEBSOCKET_TIMEOUT_MAX`. With no value present it returns the 35-minute default. `ui_config` is written by `config.update_session_config()`, which is called from `POST /api/config` — that is the Settings page, which exposes `WEBSOCKET_TIMEOUT_MINUTES` as a number field with `min=5` and `max=60`. The setting lives in the Flask session, not in the env file (`dragoncp_env_sample.env` does not mention it) and not in the database.

The buffer is deliberate: the server always waits five minutes longer than the client's own countdown, so the browser is the one that normally ends an idle session and the sweeper is the backstop for clients that vanished.

### Inspecting live connections

Three authenticated endpoints report on the socket layer (all in `routes/debug.py`):

- `GET /api/runtime/status` — `active_connections`, `cleanup_thread_running`, and the static `socketio_runtime_info` block (async mode, ping interval/timeout, whether the WebSocket transport is available). This is the endpoint the frontend polls for backend/SSH reachability.
- `GET /api/websocket/status` — the same counts plus `default_timeout_minutes`, `max_timeout_minutes`, and per-connection details (truncated session id, minutes since connect, minutes since last activity, that connection's timeout, transport). The connection count shown in the popover comes from here, via `useWebSocketStatus()`.
- `GET /api/debug` — includes the same websocket block along with the session's configured timeout.

## Known defects

**The frontend subscribes to `transfer_failed`, which no server code emits.** Verified in both directions on 2026-07-28:

- `frontend/src/services/socket.ts:206-211` defines `onTransferError()`, whose body is `socket.on("transfer_failed", callback)` with a matching `off` in the returned cleanup.
- Searching every tracked file for `transfer_failed` returns exactly one file — `frontend/src/services/socket.ts`. There is no `emit('transfer_failed', ...)` anywhere in `services/`, `routes/`, `app.py` or `websocket.py`. The events in the table above account for every server emit: nineteen call sites across `services/` and `routes/`, which is what a repository-wide search for `socketio.emit` and `emit_socketio_event(` returns.

Consequences today are limited, because `onTransferError` is exported but never imported anywhere in `frontend/src/`, so no listener is ever actually registered. The practical risk is for whoever wires it up next: a page that calls `onTransferError()` expecting failure notifications will silently receive nothing forever. Transfer failures currently arrive as `transfer_complete` with `status: "failed"`. Either delete `onTransferError` or point it at `transfer_complete` and filter on status.

Two smaller mismatches found while checking the above:

- The `TransferUpdate` interface in `frontend/src/services/socket.ts` declares `status`, `progress`, `media_type` and `folder_name` as required, but no server payload for `transfer_queued` or `transfer_promoted` contains `media_type` or `folder_name`, and `transfer_queued` from `services/transfer_coordinator.py:182` and `:345` contains only `transfer_id` and `message`. Nothing breaks — TypeScript does not check socket payloads at runtime and the consumers use fallbacks — but the type overstates what arrives.
- `app.py:23` imports `WEBSOCKET_TIMEOUT_MAX` and `WEBSOCKET_TIMEOUT_DEFAULT` and never uses either.

## Not verified

- **Not verified**: behaviour under multiple backend workers. The connection map, the sweeper thread and the queue manager's state are all process-local, and `socketio_runtime_info` names `gunicorn --config deploy/gunicorn.conf.py app:app` as the recommended production server, but I did not read that config or test a multi-worker run, so I cannot say how emits and idle cleanup behave across workers.
- **Not verified**: whether the Flask session cookie is actually present during a Socket.IO handshake from the React frontend. `get_websocket_timeout_for_session()` reads `ui_config` off the Flask session; if the handshake carries no session cookie, every connection would silently get the 35-minute default regardless of the Settings value. I did not run this to confirm which way it falls.
- **Not verified**: the legacy Jinja UI under `templates/` and `static/`. I only traced the React client in `frontend/`.

## Related documentation

- [`../features/queue/README.md`](../features/queue/README.md) — what `transfer_queued` and `transfer_promoted` mean in queue terms
- [`../features/transfers/README.md`](../features/transfers/README.md) — the transfer lifecycle behind `transfer_progress` and `transfer_complete`
- [`../features/webhooks/README.md`](../features/webhooks/README.md) and [`../features/renames/README.md`](../features/renames/README.md) — the receivers that emit the webhook and rename events
- [`../features/auth/README.md`](../features/auth/README.md) — token validation, refresh, and the `ALLOW_QUERY_TOKEN_AUTH` flag
- [`api.md`](api.md) — the REST surface that every event is a hint about
- [`frontend.md`](frontend.md) — where the client-side pieces live
