# DragonCP API Reference

Last updated: 2026-08-01

Purpose: human-friendly reference for every backend HTTP API endpoint implemented by the Python server.

## This File Is Authoritative

This document is the authoritative description of the API. It is written by
reading the route decorators and handler bodies in `app.py` and `routes/`, and
it is what you should trust for request shapes, response fields, status codes
and behaviour.

`openapi.yaml` in this same directory is the machine-readable companion. It
lists every endpoint with its method, path, auth requirement and a one-line
summary, so it can be imported into an API client or used to generate a
stub client. Its request and response schemas are deliberately thin - they name
the common fields and nothing more. When the two disagree, this file wins and
`openapi.yaml` is the one that needs fixing.

Both files are maintained by hand against the same source. Changing an endpoint
means changing both.

## IMPORTANT NOTE (For AI Agents)

- Use this document as a reference.
- Update this document only when backend API endpoints, request/response contracts, or API behavior changes.
- If there is no API change, do not edit this document.

Source checked while writing this file:
- `app.py`
- `routes/auth.py`
- `routes/media.py`
- `routes/transfers.py`
- `routes/webhooks.py`
- `routes/backups.py`
- `routes/debug.py`
- `routes/logs.py`
- `routes/simulation.py`
- `services/rename_service.py`

Base URL:
```text
http://<host>:5000/api
```

## Scope and Audience

DragonCP API is currently designed for trusted administrators and automation systems.

- Admin-only operations surface (no end-user API model)
- Typical operator count is small (1-3 admins)
- Public internet exposure is intended only for webhook receiver endpoints
- As of March 3, 2026, end-user workflows are out of scope

## Authentication Model

Most endpoints require a JWT access token:
```http
Authorization: Bearer <access-token>
```

For normal HTTP requests, query token auth (`?token=...`) is not supported.

Public endpoints (no JWT required):
- `POST /auth/login`
- `GET /auth/verify`
- `POST /auth/refresh`
- `GET /auth/status`
- `POST /webhook/movies`
- `POST /webhook/series`
- `POST /webhook/anime`

## Common Response Pattern

Most endpoints return JSON with a `status` field:
- Success example: `{"status":"success", ...}`
- Error example: `{"status":"error","message":"..."}`

Some endpoints intentionally return raw JSON objects (without `status` wrapper), especially config endpoints and raw webhook JSON endpoints.

## Canonical Status Values

Sync status values:
Used by sync-status APIs to indicate whether a media folder (or season) on the remote source and local destination are in sync when compared.
- `SYNCED`
- `OUT_OF_SYNC`
- `NO_INFO`

Transfer status values:
- `pending`
- `queued`
- `running`
- `paused`
- `completed`
- `failed`
- `cancelled`

Webhook status values (combined):
- `pending`
- `READY_FOR_TRANSFER`
- `QUEUED_SLOT`
- `QUEUED_PATH`
- `syncing`
- `completed`
- `failed`
- `cancelled`

Current implementation note:
- series/anime manual-sync-required rows are not yet persisted as `MANUAL_SYNC_REQUIRED`
- they currently remain `pending` with `requires_manual_sync=1` and `manual_sync_reason` populated

---

## 1) Authentication Endpoints

### POST `/auth/login`
What it does: authenticates user credentials and returns access + refresh tokens.

Input JSON:
```json
{
  "username": "admin",
  "password": "your-password"
}
```

Output JSON (success):
```json
{
  "status": "success",
  "message": "Login successful",
  "token": "<jwt-access-token>",
  "refresh_token": "<jwt-refresh-token>",
  "expires_at": "2026-02-28T10:00:00+00:00",
  "refresh_expires_at": "2026-03-07T10:00:00+00:00",
  "user": "admin"
}
```

Error behavior:
- `400` if JSON/body/credentials are missing.
- `401` if credentials are invalid.
- `503` if backend auth is not configured.

### POST `/auth/logout`
What it does: logs out current authenticated user (logical/client-side logout for stateless JWT flow).

Auth: required.

Input: no body required.

Output JSON:
```json
{
  "status": "success",
  "message": "Logout successful"
}
```

### GET `/auth/verify`
What it does: checks whether the provided access token is valid.

Auth: optional token check (you can call without token).

Input:
- Token from `Authorization: Bearer <access-token>` header.
- URL query token (`?token=...`) is not accepted for normal HTTP API calls.

Output JSON:
```json
{
  "status": "success",
  "valid": true,
  "user": "admin",
  "remaining_seconds": 3600
}
```

If no/invalid token, still returns `status: success` with `valid: false` and a message.

### POST `/auth/refresh`
What it does: exchanges a valid refresh token for a new access token.

Input JSON:
```json
{
  "refresh_token": "<jwt-refresh-token>"
}
```

Output JSON:
```json
{
  "status": "success",
  "message": "Token refreshed successfully",
  "token": "<new-jwt-access-token>",
  "expires_at": "2026-02-28T10:00:00+00:00",
  "user": "admin"
}
```

Error behavior:
- `400` if JSON/refresh token is missing.
- `401` if refresh token is invalid/expired.

### GET `/auth/status`
What it does: tells frontend whether auth is configured on server.

Output JSON:
```json
{
  "status": "success",
  "auth_configured": true,
  "message": "Authentication is configured"
}
```

---

## 2) Configuration and SSH Endpoints

### GET `/config`
What it does: returns every setting, in two shapes at once — grouped for the React
Settings screen, and as a flat key -> value map for the legacy static UI.

Each grouped setting carries `store` (`env` or `db`) and `editable`, so a client can
show the environment-file half read-only instead of offering a field that silently does
nothing. Environment secrets are omitted entirely; editable secrets come back as
`<redacted>`.

Auth: required.

Input: none.

Output, abbreviated:
```json
{
  "status": "success",
  "REMOTE_IP": "192.168.1.10",
  "BACKUP_RETENTION_KEEP": "2",
  "groups": [
    {
      "id": "backups",
      "label": "Backups",
      "settings": [
        {
          "key": "BACKUP_RETENTION_KEEP",
          "store": "db",
          "editable": true,
          "kind": "number",
          "label": "Versions to keep",
          "description": "How many previous versions of each movie or episode to keep.",
          "value": "2",
          "minimum": 1,
          "maximum": 50,
          "is_default": true
        }
      ]
    }
  ],
  "stores": {
    "env": { "label": "Environment file", "description": "..." },
    "db":  { "label": "Application settings", "description": "..." }
  }
}
```

### POST `/config`
What it does: writes the database-backed settings in the payload.

Environment-owned keys are **refused by name** rather than ignored, and listed in
`refused`. The whole payload is validated before anything is written, so a 400 means
nothing changed.

Auth: required.

Input JSON: any editable settings keys. Sending `<redacted>` for a secret means
"unchanged". Numbers outside a setting's bounds are clamped, not rejected.

Output JSON (the full `GET` payload is returned alongside, so a client can refresh
without a second request):
```json
{
  "status": "success",
  "message": "Saved 1 setting(s). 1 setting(s) come from the environment file and were not changed: REMOTE_IP",
  "saved": ["BACKUP_RETENTION_KEEP"],
  "refused": ["REMOTE_IP"]
}
```

Errors: `400` with `message` naming the invalid value. Nothing in the payload is
written.

### POST `/config/reset`
What it does: kept for the legacy static UI, which still calls it. There is no longer a
per-browser override layer to clear, so it reports success and changes nothing.

Auth: required.

Input: none.

### GET `/config/env-only`
What it does: returns the environment-backed settings alone, which is what the legacy
UI's comparison column shows. Secrets are redacted; hidden env secrets are omitted.

Auth: required.

### POST `/connect`
What it does: creates SSH connection to remote server and attaches it to active backend runtime.

Auth: required.

Input JSON:
```json
{
  "host": "192.168.1.10",
  "username": "root",
  "password": "optional",
  "key_path": "optional"
}
```

Output JSON:
```json
{
  "status": "success",
  "message": "Connected successfully"
}
```

Error examples:
- `{"status":"error","message":"Host and username are required"}`
- `{"status":"error","message":"Connection failed"}`

### POST `/disconnect`
What it does: disconnects current SSH session and clears connection state.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "message": "Disconnected"
}
```

### GET `/auto-connect`
What it does: auto-connects via configured env values (`REMOTE_IP`, `REMOTE_USER`, optional password/key path).

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "message": "Auto-connected successfully"
}
```

Error examples:
- `{"status":"error","message":"SSH credentials not configured"}`
- `{"status":"error","message":"Auto-connection failed"}`

### GET `/ssh-config`
What it does: returns SSH config values currently loaded by backend.

Auth: required.

Output JSON:
```json
{
  "host": "192.168.1.10",
  "username": "root",
  "key_path": "/path/to/key",
  "has_password": true
}
```

The stored password is never returned. It is reduced to the boolean
`has_password` so it cannot reach the browser.

---

## 3) Media Browsing and Sync Endpoints

### GET `/media-types`
What it does: returns static media types and configured source paths.

Auth: required.

Output JSON (array):
```json
[
  {"id":"movies","name":"Movies","path":"/data/movies"},
  {"id":"tvshows","name":"TV Shows","path":"/data/tvshows"},
  {"id":"anime","name":"Anime","path":"/data/anime"}
]
```

### GET `/folders/{media_type}`
What it does: lists remote folders for one media type.

Auth: required.

Path param:
- `media_type`: `movies | tvshows | anime`

Output JSON:
```json
{
  "status": "success",
  "folders": [
    {"name":"Folder Name","modification_time":1730000000}
  ]
}
```

### GET `/seasons/{media_type}/{folder_name}`
What it does: lists season folders inside a show/anime folder.

Auth: required.

Path params:
- `media_type`: usually `tvshows` or `anime`
- `folder_name`: series folder name

Output JSON:
```json
{
  "status": "success",
  "seasons": [
    {"name":"Season 01","modification_time":1730000000}
  ]
}
```

### GET `/episodes/{media_type}/{folder_name}/{season_name}`
What it does: lists files (episodes) inside a season folder.

Auth: required.

Path params:
- `media_type`
- `folder_name`
- `season_name`

Output JSON:
```json
{
  "status": "success",
  "episodes": ["S01E01.mkv", "S01E02.mkv"]
}
```

### GET `/sync-status/{media_type}`
What it does: returns sync status for every folder in selected media type.

Auth: required.

Path param:
- `media_type`: `movies | tvshows | anime`

Output JSON:
```json
{
  "status": "success",
  "sync_statuses": {
    "Some Folder": {
      "status": "SYNCED",
      "type": "movie",
      "modification_time": 1730000000
    }
  }
}
```

For series/anime, each folder can include season-level summary inside `sync_statuses`.

### GET `/sync-status/{media_type}/{folder_name}`
What it does: returns detailed sync status for one folder.

Auth: required.

Path params:
- `media_type`
- `folder_name`

Output JSON (movie):
```json
{
  "status": "success",
  "folder_name": "Some Movie",
  "sync_status": {
    "status": "OUT_OF_SYNC",
    "type": "movie",
    "modification_time": 1730000000
  }
}
```

Output JSON (series/anime) includes `sync_status` summary and `seasons_sync_status` map.

### GET `/sync-status/{media_type}/{folder_name}/enhanced`
What it does: returns sync status with file counts, total sizes, and sample file metadata.

Auth: required.

Path params:
- `media_type`
- `folder_name`

Output JSON:
```json
{
  "status": "success",
  "folder_name": "Some Series",
  "sync_status": {
    "status": "SYNCED",
    "type": "series",
    "seasons": [],
    "most_recent_season": "Season 02"
  }
}
```

### POST `/media/dry-run`
What it does: simulates an rsync for a chosen media folder (no file changes).

Auth: required.

Input JSON:
```json
{
  "media_type": "tvshows",
  "folder_name": "Example Show",
  "season_name": "Season 01"
}
```

`season_name` is optional.

Output JSON:
```json
{
  "status": "success",
  "dry_run_result": {
    "safe_to_sync": true,
    "reason": "All safety checks passed",
    "incoming_count": 3,
    "deleted_count": 0,
    "server_file_count": 12,
    "local_file_count": 9,
    "incoming_files": [],
    "deleted_files": [],
    "raw_output": "..."
  }
}
```

---

## 4) Transfer Endpoints

### POST `/transfer`
What it does: starts transfer immediately or queues it if slots/path locks are busy.

Auth: required.

Input JSON:
```json
{
  "type": "folder",
  "media_type": "movies",
  "folder_name": "Movie Folder",
  "season_name": "optional",
  "episode_name": "required only when type=file"
}
```

Rules:
- `media_type` and `folder_name` are required.
- If `type=file`, `episode_name` is required.

Output JSON:
```json
{
  "status": "success",
  "transfer_id": "transfer_1700000000",
  "transfer_state": "running",
  "message": "Transfer started",
  "source": "/source/path",
  "destination": "/destination/path",
  "episode_name": null
}
```

### GET `/transfer/{transfer_id}/status`
What it does: returns one transfer object with progress/log summary.

Auth: required.

Path param:
- `transfer_id`

Output JSON:
```json
{
  "status": "success",
  "transfer": {
    "id": "transfer_1700000000",
    "status": "running",
    "progress": "45%",
    "logs": [],
    "log_count": 0,
    "start_time": "2026-02-28T10:00:00",
    "end_time": null,
    "media_type": "tvshows",
    "folder_name": "Example Show",
    "season_name": "Season 01",
    "parsed_title": "Example Show",
    "parsed_season": "Season 01",
    "operation_type": "folder",
    "source_path": "/source",
    "dest_path": "/dest"
  }
}
```

### GET `/transfer/{transfer_id}/logs`
What it does: returns full log stream for one transfer.

Auth: required.

Path param:
- `transfer_id`

Output JSON:
```json
{
  "status": "success",
  "logs": ["..."],
  "log_count": 123,
  "transfer_status": "running"
}
```

### POST `/transfer/{transfer_id}/cancel`
What it does: requests cancellation for a transfer.

Auth: required.

Path param:
- `transfer_id`

Output JSON:
```json
{"status":"success","message":"Transfer cancelled"}
```

### POST `/transfer/{transfer_id}/pause`
What it does: pauses a running transfer, keeping its partially copied files.

rsync is stopped rather than suspended: the transfer command sets
`--timeout=300`, so a frozen process would lose its connection after five
minutes. The partial files remain on disk (`--partial`/`--partial-dir`), and the
queue slot is released so queued transfers can start.

Auth: required.

Path param:
- `transfer_id`

Output JSON:
```json
{"status":"success","message":"Transfer paused"}
```

Errors (HTTP 400):
- `{"status":"error","message":"Only running transfers can be paused (currently completed)"}`

### POST `/transfer/{transfer_id}/resume`
What it does: resumes a paused transfer, continuing from its partial files.

Goes back through the queue manager, so a resume respects the concurrency limit
and cannot collide with a transfer that claimed the same destination while this
one was paused. If no slot is free the transfer is queued instead of started,
and the message says so.

Auth: required.

Path param:
- `transfer_id`

Output JSON:
```json
{"status":"success","message":"Transfer resumed"}
```
```json
{"status":"success","message":"Transfer resumed and queued"}
```

Errors (HTTP 400):
- `{"status":"error","message":"Only paused transfers can be resumed (currently running)"}`
- `{"status":"error","message":"Another transfer is already syncing to this destination"}`

### POST `/transfer/{transfer_id}/restart`
What it does: restarts failed/cancelled transfer.

Auth: required.

Path param:
- `transfer_id`

Output JSON:
```json
{"status":"success","message":"Transfer restarted successfully"}
```

### POST `/transfer/{transfer_id}/delete`
What it does: deletes transfer record from DB (cannot delete running transfer).

Auth: required.

Path param:
- `transfer_id`

Output JSON:
```json
{"status":"success","message":"Transfer deleted successfully"}
```

Common error:
- `{"status":"error","message":"Cannot delete a running transfer. Please cancel it first."}`

### GET `/transfers/all`
What it does: returns one page of the transfer history, newest first, with
optional filtering and search.

Auth: required.

Query params:
- `limit` (default `50`, capped at `200`)
- `offset` (default `0`) — where the page starts
- `status` (optional exact status filter)
- `statuses` (optional comma-separated list, e.g. `completed,failed,cancelled`)
- `search` (optional) — matches `parsed_title`, `folder_name`, `season_name`,
  `dest_path`, `source_path` or `transfer_id`, case-insensitively and anywhere
  in the value

Output JSON:
```json
{
  "status": "success",
  "transfers": [],
  "total": 0,
  "count": 0,
  "limit": 50,
  "offset": 0,
  "status_counts": {},
  "unfiltered_total": 0
}
```

- `total` — records matching `status`/`statuses`/`search`, across the whole table
- `count` — records on this page
- `status_counts` — matching records per status, so filter controls can show
  their own counts without a request each. Honours `statuses` and `search`;
  ignores `status`, so the counts stay stable as filters change.
- `unfiltered_total` — records matching `statuses` alone, ignoring `status` and
  `search`, for a tab badge that should not move while someone types

Each transfer object carries the listing fields described under
`/transfers/active` below, plus `end_time` and `created_at`.

Implementation notes:
- Filtering, searching and paging all happen in SQL. `status` previously
  filtered the page after limiting it, so asking for failed transfers returned
  none whenever the newest `limit` rows happened to be completed.
- Listings never include the `logs` array, only `log_count`. The log body is
  available from `/transfer/{transfer_id}/logs`.

### POST `/transfers/bulk-delete`
What it does: deletes several transfer records at once, either by id or by
re-running a filter on the server.

Auth: required.

Input JSON — either an explicit list:
```json
{ "ids": ["transfer_id_1", "transfer_id_2"] }
```
or every record a filter finds:
```json
{ "all_matching": true, "status": "failed", "statuses": ["completed", "failed"], "search": "dune" }
```

`all_matching` re-evaluates the filter here rather than trusting a list of ids,
so "select all" means every match and not only the rows a client had loaded.
When it is set, `ids` is ignored.

Output JSON:
```json
{
  "status": "success",
  "deleted_count": 0,
  "skipped": [],
  "message": "Nothing to delete"
}
```

- `skipped` — ids of transfers left alone because they are still `running`. A
  running transfer has a live rsync process behind it, so its row is never
  deleted; it must be cancelled first.

Deleting `completed` records also removes the sync history that Browse Media
reads, so media those transfers copied will show as not yet synced afterwards.

### GET `/transfers/active`
What it does: returns currently active transfers plus queue state.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "transfers": [],
  "total": 0,
  "queue_status": {
    "max_concurrent": 3,
    "running_count": 0,
    "queued_count": 0,
    "available_slots": 3,
    "running_transfer_ids": [],
    "queued_transfer_ids": [],
    "active_destinations": []
  }
}
```

Each transfer object contains:

| Field | Meaning |
|---|---|
| `id`, `status`, `progress` | Transfer id, lifecycle state, latest rsync line |
| `media_type`, `folder_name`, `season_name` | What is being copied |
| `parsed_title`, `parsed_season` | Cleaned-up title/season for display |
| `operation_type`, `source_path`, `dest_path` | Folder or file, and the paths |
| `start_time`, `paused_at`, `created_at` | When it started, was paused, was queued |
| `queue_reason` | `slot` or `path` for a queued transfer, else null |
| `rsync_process_id` | PID of the running rsync, if any |
| `log_count` | Number of stored log lines (the lines themselves are not included) |
| `is_simulation` | True for rows created by the simulation tool |
| `progress_percent`, `bytes_transferred`, `total_bytes`, `speed_bps`, `eta_seconds` | Parsed rsync progress; see `database-schema.md` |

Implementation notes:
- `queue_status.active_destinations` currently contains the transfer IDs that own reserved destinations, not the normalized path strings themselves.
- The listing query excludes the `logs` column and counts it in SQL, and filters
  by status in SQL rather than reading the whole table. This is why `log_count`
  is present but `logs` is not.

### GET `/transfers/queue/status`
What it does: returns queue state only.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "queue": {
    "max_concurrent": 3,
    "running_count": 0,
    "queued_count": 0,
    "available_slots": 3
  }
}
```

### POST `/transfers/cleanup`
What it does: removes duplicate transfer records by destination path, keeping latest successful one.

Auth: required.

Input: none.

Output JSON:
```json
{
  "status": "success",
  "message": "Cleaned up 3 duplicate transfers",
  "cleaned_count": 3
}
```

---

## 5) Webhook Receiver Endpoints

These are the only endpoints intended to be reachable from outside the trusted
network. They do not take a JWT, but they are not unauthenticated: each is
decorated with `@require_webhook_auth` (`webhook_auth.py`), which enforces an
HMAC `X-DragonCP-Signature` when `WEBHOOK_SECRET` is set and an IP allowlist
when `WEBHOOK_ALLOWED_IPS` is set. They are open only when neither is
configured. See `../features/webhooks/README.md`.

### POST `/webhook/movies`
What it does: receives Radarr movie webhook, stores notification, optionally auto-syncs.

Auth: webhook auth (HMAC signature and/or IP allowlist), not JWT.

Input JSON: Radarr payload (movie import/test event payload).

Special behavior:
- Detects test webhooks (`eventType=Test`, `title=Test Title`, or `testpath`) and returns test success.
- For normal events, creates notification record and either triggers sync automatically or leaves for manual sync.

Output JSON:
```json
{
  "status": "success",
  "message": "Webhook received for Movie Name. Manual sync required.",
  "notification_id": "id",
  "auto_sync": false
}
```

### POST `/webhook/series`
What it does: receives Sonarr series webhook for TV shows.

Auth: webhook auth (HMAC signature and/or IP allowlist), not JWT.

Input JSON: Sonarr payload.

Special behavior:
- Handles test webhook detection.
- If `eventType` is `Rename`, processes rename workflow instead of import sync flow.
- For import flow, creates series notification and optionally schedules auto-sync.

Output JSON:
```json
{
  "status": "success",
  "message": "Series webhook received for Show Season 1. Auto-sync scheduled.",
  "notification_id": "id",
  "auto_sync": true
}
```

### POST `/webhook/anime`
What it does: receives Sonarr anime webhook (same logic pattern as series endpoint but `media_type=anime`).

Auth: webhook auth (HMAC signature and/or IP allowlist), not JWT.

Input JSON: Sonarr payload.

Output JSON shape is same pattern as series endpoint.

---

## 6) Webhook Notification Management Endpoints

### GET `/webhook/notifications`
What it does: returns one page of notifications across movies + series + anime,
newest first.

Auth: required.

Query params:
- `status` (optional exact status filter)
- `media_type` (optional) — `movies`/`movie` selects the Radarr table; anything
  else selects the Sonarr table, with `tvshows` also matching the legacy
  `series` value
- `search` (optional) — matches title, folder or season path, release title,
  requester or notification id in whichever table is being read
- `limit` (default `50`, capped at `200`)
- `offset` (default `0`)

Output JSON:
```json
{
  "status": "success",
  "notifications": [],
  "total": 0,
  "count": 0,
  "limit": 50,
  "offset": 0,
  "status_counts": {},
  "unfiltered_total": 0
}
```

- `total` — notifications matching the filter across both tables
- `count` — notifications on this page
- `status_counts` — matching notifications per status; honours `media_type` and
  `search`, ignores `status`
- `unfiltered_total` — notifications matching `media_type` alone

Each notification carries `media_type` (`movie` for Radarr rows, the stored
value for Sonarr rows) and `display_title` so a caller does not need to know
which table it came from.

Implementation notes:
- Ordering, paging and counting run across both tables in one query. The
  endpoint used to read each table with the same `limit`, merge in Python and
  re-slice, which could return no more rows than `limit` however far a caller
  paged, and reported `total` as the length of the page it had just built.

### POST `/webhook/notifications/bulk-delete`
What it does: deletes several notifications at once, either by id or by
re-running a filter on the server.

Auth: required.

Input JSON — either an explicit list:
```json
{ "ids": ["notification_id_1", "notification_id_2"] }
```
or every notification a filter finds:
```json
{ "all_matching": true, "status": "failed", "media_type": "tvshows", "search": "dune" }
```

Ids are unique across both tables, so a delete by id finds the owning table
without the caller tracking which source a row came from. When `all_matching`
is set, `ids` is ignored.

Output JSON:
```json
{
  "status": "success",
  "deleted_count": 0,
  "message": "Deleted 0 notifications"
}
```

Deleting a notification does not touch media already copied, nor the transfers
that copied it. Deleting a `pending` notification means it can no longer be
synced from the UI.

### GET `/webhook/series/notifications`
What it does: returns only TV series notifications.

Auth: required.

Query params: `status`, `limit`.

Output JSON: `{"status":"success","notifications":[...],"total":N}`

### GET `/webhook/anime/notifications`
What it does: returns only anime notifications.

Auth: required.

Query params: `status`, `limit`.

Output JSON: `{"status":"success","notifications":[...],"total":N}`

### GET `/webhook/notifications/{notification_id}`
What it does: returns one notification by ID (checks movies first, then series/anime).

Auth: required.

Path param:
- `notification_id`

Output JSON:
```json
{
  "status": "success",
  "notification": {}
}
```

Error behavior:
- `404` if not found.

### GET `/webhook/notifications/{notification_id}/json`
What it does: returns raw stored webhook JSON payload for given notification.

Auth: required.

Path param:
- `notification_id`

Output:
- Raw JSON document with `application/json` content type.
- Not wrapped with `status`.

Error behavior:
- `404` if notification or raw data not available.

### POST `/webhook/notifications/{notification_id}/sync`
What it does: manually triggers sync for a movie notification.

Auth: required.

Path param:
- `notification_id`

Output JSON:
```json
{"status":"success","message":"..."}
```

Error behavior:
- `400` if trigger fails.

### POST `/webhook/series/notifications/{notification_id}/sync`
What it does: manually triggers sync for a series notification.

Auth: required.

Path param:
- `notification_id`

Output JSON: same shape as movie sync endpoint.

### POST `/webhook/anime/notifications/{notification_id}/sync`
What it does: manually triggers sync for an anime notification.

Auth: required.

Path param:
- `notification_id`

Output JSON: same shape as series sync endpoint.

### POST `/webhook/series/notifications/sync-batch`
What it does: syncs a whole group of series/anime notifications as **one
transfer per season**, which is what "Sync all" on a group calls.

Auth: required.

A series transfer is scoped to the season *folder*, so one run brings the whole
season down. Posting each notification separately produced one transfer per
episode against a single destination — the queue serialised them on the path
conflict and all but the first moved zero bytes.

The grouping is re-derived on the server from each notification's
`(media_type, series_title_slug, season_number)`. The client does not get to
name the folder, because the resulting rsync runs with `--delete`. The whole
group is submitted, including notifications that are already `completed`, so
they end up linked to the run that actually fetched them.

Input JSON:
```json
{"notification_ids": [12, 13, 14, 15, 16, 17]}
```

Output JSON:
```json
{
  "status": "success",
  "message": "Started 1 transfer(s) for 6 episode(s)",
  "transfers": [{"season": 1, "notification_id": 13, "transfer_id": "transfer_1757226652"}]
}
```

Returns 400 for an empty list, and reports ids that no longer exist in
`message` rather than failing the whole call. Notifications whose status is
already terminal are skipped; if none of them can be synced the call returns
`status: "error"` with `nothing to sync`.

### POST `/webhook/notifications/{notification_id}/complete`
What it does: manually marks movie notification as completed.

Auth: required.

Path param:
- `notification_id`

Output JSON:
```json
{"status":"success","message":"Movie notification marked as complete successfully"}
```

Error behavior:
- `404` if notification not found.

### POST `/webhook/series/notifications/{notification_id}/complete`
What it does: manually marks series notification as completed.

Auth: required.

Path param:
- `notification_id`

Output JSON: success/error message pattern.

### POST `/webhook/anime/notifications/{notification_id}/complete`
What it does: manually marks anime notification as completed.

Auth: required.

Path param:
- `notification_id`

Output JSON: success/error message pattern.

### POST `/webhook/notifications/{notification_id}/delete`
What it does: deletes movie notification record.

Auth: required.

Path param:
- `notification_id`

Output JSON:
```json
{"status":"success","message":"Notification deleted successfully"}
```

### POST `/webhook/series/notifications/{notification_id}/delete`
What it does: deletes series notification record.

Auth: required.

Path param:
- `notification_id`

Output JSON: success/error message pattern.

### POST `/webhook/anime/notifications/{notification_id}/delete`
What it does: deletes anime notification record.

Auth: required.

Path param:
- `notification_id`

Output JSON: success/error message pattern.

### POST `/webhook/notifications/{notification_id}/dry-run`
What it does: dry-run rsync preview for a movie notification's source/destination.

Auth: required.

Path param:
- `notification_id`

Output JSON:
```json
{
  "status": "success",
  "dry_run_result": {
    "safe_to_sync": true,
    "incoming_count": 0,
    "deleted_count": 0,
    "total_size": "0 B",
    "deletions": [],
    "warnings": []
  }
}
```

### POST `/webhook/series/notifications/{notification_id}/dry-run`
What it does: dry-run rsync preview for a series notification.

Auth: required.

Path param:
- `notification_id`

Output JSON: same `dry_run_result` shape as movie dry-run.

### POST `/webhook/anime/notifications/{notification_id}/dry-run`
What it does: dry-run rsync preview for anime notification.

Auth: required.

Path param:
- `notification_id`

Output JSON: same as series dry-run endpoint.

### GET `/webhook/rename/notifications`
What it does: returns rename-event notifications.

Auth: required.

Query params:
- `status` (optional)
- `media_type` (`tvshows | anime`, optional)
- `limit` (default `50`)

Output JSON:
```json
{"status":"success","notifications":[...],"total":N}
```

### GET `/webhook/rename/notifications/{notification_id}`
What it does: returns one rename notification by ID.

Auth: required.

Path param:
- `notification_id`

Output JSON:
```json
{
  "status": "success",
  "notification": {}
}
```

### GET `/webhook/rename/notifications/{notification_id}/json`
What it does: returns raw rename webhook JSON.

Auth: required.

Path param:
- `notification_id`

Output:
- Raw JSON response (`application/json`, no status wrapper).

### POST `/webhook/rename/notifications/{notification_id}/delete`
What it does: deletes rename notification record.

Auth: required.

Path param:
- `notification_id`

Output JSON:
```json
{"status":"success","message":"Rename notification deleted successfully"}
```

### POST `/webhook/rename/notifications/{notification_id}/verify`
What it does: checks whether the files from one rename run are on disk under
their new names right now.

This is a read-only check. It renames nothing, and the result is returned to the
caller only - it is not written back to the rename history row. Running it twice
is free.

Auth: required.

Path param:
- `notification_id`

Input: no body required.

The file list comes from the stored per-file rename results. If those are empty,
the stored raw webhook payload is re-parsed instead, so a run whose results never
persisted can still be checked.

Output JSON:
```json
{
  "status": "success",
  "result": {
    "notification_id": "rename_123_1700000000000",
    "series_title": "Example Show",
    "media_type": "tvshows",
    "status": "partial",
    "total_files": 3,
    "verified_count": 2,
    "failed_count": 1,
    "verified_at": "2026-07-27T10:00:00",
    "files": [
      {
        "previous_name": "old.mkv",
        "expected_name": "new.mkv",
        "local_previous_path": "/media/tv/Example Show/Season 01/old.mkv",
        "local_expected_path": "/media/tv/Example Show/Season 01/new.mkv",
        "actual_name": "new.mkv",
        "actual_path": "/media/tv/Example Show/Season 01/new.mkv",
        "status": "verified",
        "message": "Expected renamed file exists locally"
      }
    ],
    "message": "Verified 2/3 renamed file(s) for Example Show (1 missing)"
  }
}
```

`result.status` is `verified` when every file passed, `failed` when none did, and
`partial` in between. Each entry in `files` is `verified` or `failed`, with one of
these messages:
- `Expected renamed file exists locally` - the file is where it should be
- `File still exists at the previous path` - still under its old name; `actual_path` points at it, so the season needs re-syncing
- `Expected renamed file was not found locally` - neither name is present, usually because the season was never synced to this machine
- `Path traversal rejected: ...` - the path in the payload failed the safety check and was not looked at

Status codes:
- `200` whenever the check ran, **including** when `result.status` is `partial`
  or `failed`. The HTTP code reports whether the check ran, not whether it
  passed. Callers must read `result.status`, not the status code, to know the
  outcome.
- `400` only when there is nothing to verify: the notification exists but has no
  file records and no usable stored payload. Body is
  `{"status":"error","result":{...,"status":"failed","message":"No renamed files are available for verification"}}`.
- `404` when the notification does not exist.
- `500` when the rename service is not wired up, or on an unexpected error.

See `../features/renames/README.md` for what the three failure shapes mean in
practice and how the Renames tab presents them.

---

## 7) Webhook and Discord Settings Endpoints

### GET `/webhook/settings`
What it does: returns webhook auto-sync settings.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "settings": {
    "auto_sync_movies": false,
    "auto_sync_series": false,
    "auto_sync_anime": false,
    "series_anime_sync_wait_time": 60
  }
}
```

### POST `/webhook/settings`
What it does: updates webhook auto-sync settings in app settings storage.

Auth: required.

Input JSON (any subset):
```json
{
  "auto_sync_movies": true,
  "auto_sync_series": false,
  "auto_sync_anime": false,
  "series_anime_sync_wait_time": 120
}
```

Notes:
- `series_anime_sync_wait_time` is clamped to minimum `30`, maximum `900`.

Output JSON:
```json
{"status":"success","message":"Settings updated successfully"}
```

### GET `/discord/settings`
What it does: returns Discord notification settings.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "settings": {
    "webhook_url": "",
    "app_url": "http://localhost:5000",
    "manual_sync_thumbnail_url": "",
    "icon_url": "",
    "enabled": false
  }
}
```

### POST `/discord/settings`
What it does: updates Discord notification settings.

Auth: required.

Input JSON (any subset):
```json
{
  "enabled": true,
  "webhook_url": "https://discord.com/api/webhooks/...",
  "app_url": "https://dragoncp.example.com",
  "manual_sync_thumbnail_url": "https://example.com/thumb.png",
  "icon_url": "https://example.com/icon.png"
}
```

Output JSON:
```json
{"status":"success","message":"Discord settings updated successfully"}
```

### POST `/discord/test`
What it does: sends a test embed notification to configured Discord webhook.

Auth: required.

Input: no body required.

Output JSON:
```json
{"status":"success","message":"Test Discord notification sent successfully!"}
```

Error behavior:
- `400` if Discord notifications are disabled or webhook URL missing/invalid/fails.

---

## 8) Backup Endpoints

Backups are organised by **slot** — one movie, or one episode — with a version
history inside each. A **capture** is one stored version. See
`../features/backups/README.md` for the model.

### GET `/backups/overview`
What it does: totals, backup-disk pressure, the retention rule, per-library
counts, and how many old per-transfer folders are still awaiting migration.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "configured": true,
  "totals": {"capture_count": 0, "total_size": 0, "file_count": 0,
             "pinned_count": 0, "unsorted_count": 0, "slot_count": 0},
  "disk": {"total": 0, "used": 0, "free": 0, "percent_used": 0},
  "retention": {"enabled": true, "keep": 2, "grace_hours": 24},
  "libraries": [],
  "legacy_folders": 0
}
```

`configured` is false when `BACKUP_PATH` is unset — in which case transfers
refuse to start, because there is nowhere safe to put displaced files.

### GET `/backups/titles`
What it does: titles holding stored versions.

Auth: required. Query params: `library` (`movies|shows|anime`, optional).

### GET `/backups/seasons`
What it does: seasons within one title.

Auth: required. Query params: `library`, `title` (both required; `400` without).

### GET `/backups/slots`
What it does: one row per movie or episode with stored versions, with the
version count and total size.

Auth: required.

Query params: `library`, `title`, `season`, `search`, `limit` (max `1000`),
`offset`, `sort` (`recent` — default — or `size`, biggest first, which is the
order you want when the question is what to delete to get space back).

Output JSON:
```json
{
  "status": "success",
  "slots": [{"slot_key": "shows|example_show|S01E01", "library": "shows",
             "title": "Example Show (2024)", "season_number": 1,
             "episode_number": 1, "version_count": 2, "total_size": 0,
             "latest_captured_at": "2026-07-30T14:22:05.311Z",
             "has_pinned": 0, "display": "Example Show (2024) — S01E01"}],
  "total": 1, "limit": 200, "offset": 0
}
```

### GET `/backups/slot`
What it does: one slot's versions, newest first, plus what the library holds for
it right now.

Auth: required. Query params: `slot_key` (required; `400` without, `404` when
the slot has no versions).

### GET `/backups/captures/{capture_id}`
What it does: one version with its files and the slots it belongs to (more than
one for a double episode). `404` when unknown.

Auth: required.

### GET `/backups/unsorted`
What it does: files kept but not identified. They cannot be restored — there is
nowhere to put them back — but they are listed so they can be recovered by hand.

Auth: required.

### POST `/backups/captures/{capture_id}/plan`
What it does: previews a restore. Reads only; the same planner runs it.

Auth: required.

Input JSON: `files` (optional list of paths inside the capture). Omit it to mean
every file. An **empty list is rejected** with `400` — ticking nothing is not a
request to restore everything.

Output JSON:
```json
{
  "status": "success",
  "plan": {
    "capture_id": "20260730T142205.311Z__t1a2b3",
    "slot_display": "Example Show (2024) — S01E01",
    "target_dir": "/library/tv/Example Show (2024)/Season 01",
    "operations": [{"relative_path": "...mkv", "target": "/library/...mkv",
                    "replaces": "/library/...New.mkv", "replaces_size": 0,
                    "file_size": 0, "is_media": true, "display": "..."}],
    "warnings": [], "blocked": null, "total_size": 0, "replaces_count": 1
  }
}
```

`replaces` is `null` when the slot is empty — the restore re-adds the file
rather than replacing anything. `blocked` is set, with the reason, when the
restore cannot run at all.

### POST `/backups/captures/{capture_id}/restore`
What it does: starts a restore. Returns as soon as it is accepted; it runs as a
queued transfer with progress and logs.

Auth: required. Input: same `files` rule as `/plan`.

Refuses with `400` when the destination is busy, when every transfer slot is
taken, or when the same version is already being restored. It does not queue
silently.

The file each restored file replaces is stored as a new version of the same slot
first, so the restore can itself be undone.

### POST `/backups/captures/{capture_id}/pin`
What it does: pinned versions are never removed by retention.

Auth: required. Input JSON: `pinned` (bool, default `true`). `404` when unknown.

### POST `/backups/captures/{capture_id}/delete`
What it does: removes a version's files and its index entry, always together. The
library is not touched.

There is no record-only option. The index is derived from the backup tree, so removing
a row on its own frees no space and the entry returns at the next rebuild. Any
`delete_files` or `delete_record` flag in the body is ignored.

Auth: required. Input: none.

### POST `/backups/delete/preview`
What it does: previews a deletion — the versions it would remove and the space
it would free. Reads only.

Auth: required.

Input JSON (at least one of):
- `capture_ids` — specific versions
- `slot_keys` — every version of those movies/episodes
- `keep_newest` — with `slot_keys`, leave the most recent N of each
- `include_pinned` — default false

Output JSON:
```json
{
  "status": "success",
  "captures": [{"capture_id": "...", "display": "...", "captured_at": "...",
                "total_size": 0, "file_count": 1, "pinned": false}],
  "count": 1, "total_size": 0, "skipped_pinned": 0
}
```

### POST `/backups/delete`
What it does: removes several versions at once — the space-reclaiming action.

Auth: required. Input: as `/delete/preview`.

Pinned versions are held back unless `include_pinned` is set, and the number
held back is reported rather than silently absorbed. Deleting removes the files
and the index entry together, prunes the folders it emptied, and never touches
the library. **This has no undo** — the files are the last copy of that version.

Output JSON:
```json
{
  "status": "success",
  "message": "Deleted 3 version(s), reclaiming 12.40 GB",
  "deleted": ["..."], "deleted_count": 3,
  "reclaimed": 0, "skipped_pinned": 0, "errors": []
}
```

### POST `/backups/unsorted/delete`
What it does: throws away everything that could not be identified.

Auth: required. Input JSON: `confirm` must be `true`; `400` without it.

### POST `/backups/rebuild`
What it does: regenerates the index by walking the backup tree. Writes no files
and deletes no media. Idempotent. Pins, displacement reasons and transfer
provenance are carried forward, because a path cannot hold them.

Auth: required.

Output JSON:
```json
{
  "status": "success", "message": "Indexed 12 version(s), 15 file(s)",
  "indexed": 12, "files": 15, "total_size": 0, "unsorted": 0,
  "removed": 0, "errors": []
}
```

### GET `/backups/retention`
What it does: the current rule and backup-disk usage. `retention.editable` is
false when there is no database store, in which case the rule can only be
changed in the env file.

Auth: required.

### POST `/backups/retention`
What it does: **saves** the rule.

Auth: required. Input JSON: `keep`, `grace_hours`, `enabled` — all optional,
only what is sent is written. `keep` is clamped to 1–50.

Written to the `app_settings` table, not the env file. That is the only store
that both survives a restart and is visible to the background thread that
applies the rule after a transfer; a value in the Flask session would be
invisible to it. `BACKUP_RETENTION_*` in the env file remains the default when
nothing has been saved.

### POST `/backups/retention/preview`
What it does: which versions keep-N would remove. Reads only.

Auth: required. Input JSON: `keep`, `grace_hours` (both optional, default to the
configured rule).

### POST `/backups/retention/apply`
What it does: removes them, reporting what went and how much was reclaimed.

Auth: required. Input: as `/preview`.

### POST `/backups/migration/plan`
What it does: previews adopting the old per-transfer folders. Moves nothing.

Auth: required.

Output includes `moves`, `unidentified`, `empty_folders` and `blocked` —
the last set when a transfer is still running, because migration moves files
across the whole backup disk.

### POST `/backups/migration/apply`
What it does: carries out the migration and rebuilds the index over the result.

Auth: required. Input JSON: `confirm` must be `true`; `400` without it.

**It re-derives its own plan** rather than redeeming the one `/migration/plan`
returned, so a folder that appeared or changed since the preview is handled as
it is now. That is safe here in a way it would not be for a deletion: migration
only moves legacy folders into the tree and removes ones it has emptied, so a
plan that has drifted costs accuracy, not files.

Refusals come back `409` with `applied: false` and the reason in `message` — a
transfer is active, or whether one is active could not be determined. A refusal
is never reported as a success with a zero count.

### Legacy endpoints

Kept because the static UI is what production serves. They are backed by the
same store, with a capture id in place of the old backup id.

| Endpoint | Notes |
|---|---|
| `GET /backups` | Versions, newest first, in the old record shape |
| `GET /backups/{id}` | One version in the old shape |
| `GET /backups/{id}/files` | Its files |
| `POST /backups/{id}/plan` | Old plan shape. `"files": []` means "everything" here, unlike the current API |
| `POST /backups/{id}/restore` | As the current restore |
| `POST /backups/{id}/delete` | Files and entry go together |
| `POST /backups/reindex` | The index rebuild under its old name |

---

## 9) Debug and Diagnostics Endpoints

### GET `/debug`
What it does: returns wide diagnostic snapshot (config, SSH status, websocket info, rsync checks, active transfers).

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "debug_info": {
    "timestamp": "2026-02-28T10:00:00",
    "working_directory": "/app",
    "ssh_connected": true,
    "websocket_info": {},
    "configuration": {},
    "active_transfers": 0
  }
}
```

### GET `/debug/transfers`
What it does: returns DB-focused transfer debug info.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "debug_info": {
    "database_path": "/path/db.sqlite",
    "total_transfers_in_db": 10,
    "active_transfers_in_db": 1,
    "recent_transfers": []
  }
}
```

### GET `/runtime/status`
What it does: returns lightweight runtime connectivity state for the frontend shell.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "runtime_status": {
    "backend_reachable": true,
    "ssh_connected": false,
    "websocket": {
      "active_connections": 1,
      "cleanup_thread_running": true,
      "runtime": {}
    },
    "timestamp": "2026-03-14T12:00:00"
  }
}
```

### GET `/websocket/status`
What it does: reports websocket connection count and per-connection timing info.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "websocket_status": {
    "active_connections": 1,
    "default_timeout_minutes": 35,
    "max_timeout_minutes": 65,
    "connection_details": []
  }
}
```

### GET `/local-files`
What it does: lists local files in a directory path.

Auth: required.

Query param:
- `path` (default `/`)

Output JSON:
```json
{"status":"success","files":["file1.mkv","file2.srt"]}
```

### GET `/disk-usage/local`
What it does: runs local disk checks for configured paths and returns usage stats.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "disk_info": [
    {
      "path": "/media",
      "total_size": "10T",
      "used_size": "4T",
      "available_size": "6T",
      "usage_percent": 40,
      "available": true
    }
  ]
}
```

### GET `/disk-usage/remote`
What it does: calls configured remote disk API (`DISK_API_ENDPOINT`) and normalizes storage stats.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "storage_info": {
    "free_storage_gb": 500,
    "total_storage_value": 2000,
    "used_storage_value": 1500,
    "usage_percent": 75,
    "available": true
  }
}
```

---

## 10) Server Log Endpoints

Implementation: `routes/logs.py`. The backend log file location, rotation size
and retention are set by the logging configuration; see
`../operations/runtime-and-deployment.md`.

### GET `/logs`
What it does: returns recent backend log records, filtered by severity.

Auth: required.

Query params:
- `level` (default `ERROR`; one of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, `ALL`). Matching is not uniformly "that level and above": `ALL` returns everything, `ERROR` returns `ERROR` and `CRITICAL`, `WARNING` returns `WARNING`, `ERROR` and `CRITICAL`, and `DEBUG`, `INFO` and `CRITICAL` match that level **exactly**. So `level=INFO` hides errors. An unrecognised value is silently coerced to `ERROR` rather than rejected (`routes/logs.py:_normalize_level`, `_level_matches`).
- `limit` (default `200`, maximum `1000`)
- `search` (optional case-insensitive substring match)

The file is scanned backwards from the end, bounded between 1,000 and 20,000
lines, so a very large log does not have to be read in full.

Output JSON:
```json
{
  "status": "success",
  "log_file": "logs/dragoncp_backend.log",
  "level": "ERROR",
  "limit": 200,
  "line_count": 2,
  "size_bytes": 20971520,
  "last_modified": "2026-07-28T10:15:48",
  "lines": [
    { "level": "ERROR", "text": "2026-07-28 10:15:48 | ERROR | ... | message" }
  ]
}
```

`lines` holds objects, not strings, and is ordered oldest-first.

### GET `/logs/download`
What it does: downloads the whole backend log file.

Auth: required.

Output: the live log file as a `text/plain` attachment. Rotated files
(`.log.1` and older) are not served by any endpoint.

Errors:
- `404` `{"status":"error","message":"Log file is not available."}` when the file does not exist.

---

## 11) Simulation Endpoints

Runs the real transfer pipeline against throwaway files generated on the server,
so queueing, webhook status handling and the UI can be observed without touching
media or the remote server. Simulated rows are flagged `is_simulation` and are
removed by cleanup.

These replaced the former `POST /test/simulate` endpoints, which faked progress
rather than running anything and bypassed authentication when `TEST_MODE=1`.
These require auth and are safe to run in production.

Implementation: `services/simulation_service.py`, `routes/simulation.py`.

### GET `/simulation/status`
What it does: returns the scenarios on offer and what is currently on the board.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "scenarios": [
    {
      "key": "queue_overflow",
      "name": "Fill the queue",
      "description": "Starts more copies than there are slots...",
      "transfers": 5,
      "size_mb": 24,
      "bwlimit_kbps": 2000,
      "same_destination": false,
      "with_webhooks": true,
      "fail": false
    }
  ],
  "total": 0,
  "by_status": {},
  "finished": true,
  "disk_bytes": 0,
  "real_transfers_running": 0,
  "max_concurrent": 3
}
```

Scenario keys: `queue_overflow`, `path_conflict`, `slow_copy`, `failure`,
`season_batch`.

### POST `/simulation/start`
What it does: generates fixture files and starts the scenario's transfers
through `TransferCoordinator.start_transfer`.

Auth: required.

Input JSON:
```json
{"scenario": "queue_overflow", "confirm_busy": false}
```

Output JSON:
```json
{
  "status": "success",
  "message": "Fill the queue started with 5 transfers",
  "run_id": "sim_1785202435_caa5dd",
  "transfer_ids": ["simulation_sim_1785202435_caa5dd_0"]
}
```

Errors:
- `409` when real transfers are running and `confirm_busy` was not set. The body
  carries `code: "real_transfers_running"` and a `running` array naming them, so
  the caller can confirm before taking a queue slot:
  ```json
  {
    "status": "error",
    "code": "real_transfers_running",
    "message": "2 real transfer(s) are running. A simulation takes a queue slot and may delay them.",
    "running": [{"id": "webhook_123", "title": "Some Show", "status": "running"}]
  }
  ```
- `400` for an unknown scenario, a simulation already on the board, a scenario
  above the size ceiling, or too little free disk.

### POST `/simulation/stop`
What it does: cancels simulated transfers still moving, leaving the rows so the
result can be read.

Auth: required.

Output JSON:
```json
{"status":"success","message":"Stopped 3 simulation transfer(s)","stopped":3}
```

### POST `/simulation/cleanup`
What it does: removes every simulation row and the files it generated.

Deletes only rows carrying `is_simulation` and only files under the simulation
directory. Real transfers, notifications and media are untouched.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "message": "Cleared 5 transfer(s) and 5 notification(s)",
  "transfers_removed": 5,
  "notifications_removed": 5,
  "files_removed": true
}
```

---

## 12) Explore Endpoints

Explore compares the remote library against the local one and turns the
difference into a plan you approve before anything is written. It replaces the
browsing half of section 3 in the UI; those endpoints still exist and are still
served, but nothing in the React app calls them any more.

Two rules apply across this whole section:

- **The client never describes work.** It asks for a plan, the server computes
  and stores it, and every later call quotes the plan's id. A plan is single-use
  and expires 15 minutes after it is made.
- **Real status codes.** 400 bad input, 401 no session, 404 unknown
  library/series/season, 409 no remote browse session or an expired/used plan,
  422 needs an explicit override, 429 rate limited, 502 the remote listing
  failed. The `plan`, `dry-run`, `series` and `season` endpoints and
  `tree?refresh=1` share a per-user allowance of **12 calls per minute**,
  because each walks the remote library.

### GET `/explore/libraries`
What it does: the three libraries with both configured paths, whether each is
usable, and when it was last compared.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "libraries": [
    {
      "id": "tvshows",
      "label": "TV Shows",
      "remote_path": "/home/user/media/TV Shows",
      "local_path": "/mnt/media/tv_shows",
      "configured": true,
      "local_exists": true,
      "checked_at": "2026-07-31T09:12:04.113402"
    }
  ]
}
```

### GET `/explore/tree/{media_type}`
What it does: every series in one library with its rolled-up status, plus each
series' seasons so several can stay expanded at once.

Query: `refresh=1` forces a fresh comparison (rate limited). Without it the
cached snapshot is returned and `stale` is `true`.

Auth: required.

Output JSON (abridged):
```json
{
  "status": "success",
  "media_type": "tvshows",
  "checked_at": "2026-07-31T09:12:04.113402",
  "stale": false,
  "series": [
    {
      "name": "Example Series (2019)",
      "status": "PARTIAL_SYNC",
      "season_count": 5,
      "exists_locally": true,
      "remote_bytes": 214748364800,
      "misplaced_count": 0,
      "counts": {"in_sync": 40, "missing": 2, "upgraded": 1, "local_only": 0,
                 "remote_total": 43, "incoming_bytes": 6442450944,
                 "removable_bytes": 0},
      "seasons": [ ... ]
    }
  ]
}
```

`status` is one of `SYNCED`, `PARTIAL_SYNC`, `OUT_OF_SYNC`, `NO_INFO`.

### GET `/explore/series/{media_type}/{folder}`
What it does: one series with its seasons, from a fresh comparison.

Auth: required. Rate limited.

Not called by the React app — the tree already carries seasons — but it is the
middle step of the resource hierarchy and is covered by tests.

### GET `/explore/season/{media_type}/{folder}/{season}`
What it does: one season's episodes, each labelled.

Auth: required. Rate limited.

Output JSON (abridged):
```json
{
  "status": "success",
  "season": {
    "series": "Example Series (2019)",
    "season": 5,
    "name": "Season 05",
    "status": "PARTIAL_SYNC",
    "misplaced": [],
    "episodes": [
      {
        "label": "MISSING",
        "code": "S05E06",
        "season": 5,
        "episode": 6,
        "renamed": false,
        "remote_name": "Example Series - S05E06 - ... .mkv",
        "remote_size": 2051014656,
        "local_name": null,
        "local_size": null
      }
    ]
  }
}
```

`label` is one of `IN_SYNC`, `MISSING`, `UPGRADED`, `LOCAL_ONLY`.

For `movies` the season layer is a single pseudo-season named `Files`.

### GET `/explore/history/{media_type}/{folder}`
What it does: past Explore runs for this series, newest first, each with the
per-file records of what it did.

Query: `season=<season folder>` narrows to one season.

Auth: required.

### GET `/explore/backups/{media_type}/{folder}`
What it does: copies an earlier sync moved aside for this series, so they can be
seen from the season you are looking at. **Read-only** — restoring is section 8.

Query: `season=<season folder>` narrows to one season.

Auth: required.

Output JSON (abridged):
```json
{
  "status": "success",
  "backups": [
    {
      "backup_id": "transfer_1756549539",
      "media_type": "tvshows",
      "folder_name": "Example Series (2019)",
      "season_name": "Season 05",
      "status": "ready",
      "created_at": "2026-05-20T09:23:11.000000Z",
      "file_count": 3,
      "shown_count": 1,
      "shown_size": 2165283996,
      "files": [
        {
          "relative_path": "Example Series - S05E05 - Some Episode ... .mkv",
          "original_path": "/mnt/media/tv_shows/Example Series (2019)/Season 05/...",
          "file_size": 2165283996,
          "season": 5,
          "episode": 5,
          "code": "S05E05"
        }
      ]
    }
  ]
}
```

`file_count` is the whole run; `shown_count`/`shown_size` describe what is left
after narrowing to the requested season. Matching is on the backup's
`folder_name` and each **file's** own parsed season — see
[`../features/explore/README.md`](../features/explore/README.md) for why neither
`context_series_title` nor the run's `season_name` can be used.

### POST `/explore/plan`
What it does: evaluates an operation against a fresh comparison, stores it, and
returns the plan with its verdict and safety checks. Nothing is written.

Auth: required. Rate limited.

Input JSON:
```json
{
  "media_type": "tvshows",
  "operation": "sync_season",
  "folder": "Example Series (2019)",
  "season": "Season 05",
  "seasons": ["Season 04", "Season 05"],
  "codes": ["S05E06"],
  "include_removals": true
}
```

| Field | Applies to | Notes |
|---|---|---|
| `operation` | all | `sync_series`, `sync_seasons`, `sync_season`, `download`, `replace` |
| `season` | `sync_season`, `download`, `replace` | Season folder name; ignored for movies |
| `seasons` | `sync_seasons` | Season folder names; one plan covers them all |
| `codes` | `download`, `replace` | Episode codes such as `S05E06` |
| `include_removals` | the sync operations | `false` leaves local-only files alone |

Output JSON (abridged):
```json
{
  "status": "success",
  "plan": {
    "plan_id": "plan_9f2c1ab34de5f678",
    "operation": "sync_season",
    "verdict": "This season sync downloads 2, replaces 1, removes nothing.",
    "safe": true,
    "is_destructive": true,
    "is_empty": false,
    "requires_override": false,
    "counts": {"fetch": 2, "supersede": 1, "remove": 0,
               "incoming_bytes": 6442450944, "backup_bytes": 2147483648},
    "checks": [{"id": "free_space", "label": "The destination has room",
                "passed": true, "detail": "6.0 GB incoming, 900.1 GB free"}],
    "warnings": [],
    "groups": [{"season_label": "Season 05", "fetch": 2, "supersede": 1,
                "remove": 0, "actions": [ ... ]}]
  }
}
```

### POST `/explore/dry-run`
What it does: runs the plan's own rsync command with `--dry-run` and reports
what rsync says. Changes nothing, and **leaves the plan runnable** — rehearsing
an operation must not be what stops you performing it.

Auth: required. Rate limited.

Input JSON: `{"plan_id": "plan_9f2c1ab34de5f678"}`

Output JSON (abridged):
```json
{
  "status": "success",
  "plan_id": "plan_9f2c1ab34de5f678",
  "report": {
    "ok": true,
    "ran": true,
    "exit_code": 0,
    "verdict": "rsync agrees: 2 file(s) would be downloaded, 1 would be replaced, with the current copy backed up first.",
    "summary": {"new": 2, "replaced": 1, "unchanged": 0, "directories": 0,
                "deleted": 0, "backed_up": 1, "removed": 0,
                "incoming_bytes": 6442450944, "backup_bytes": 2147483648,
                "removed_bytes": 0, "media_new": 2, "media_replaced": 1},
    "files": [{"change": "new", "rel": "Season 05/...mkv", "size": 3221225472,
               "itemize": ">f+++++++++", "is_media": true}],
    "backups": [ ... ],
    "removals": [ ... ],
    "warnings": [],
    "raw_tail": "Number of files: 3\n..."
  }
}
```

`ran` is `false` when the plan only removes files: there is nothing to transfer,
so rsync is never invoked and the local changes are reported from the plan.
`change` is one of `new`, `replaced`, `unchanged`, `deleted`, `directory`; an
`itemize` of `after-backup` marks a file rsync could not see as changing because
the plan moves its local copy aside first.

### POST `/explore/transfer`
What it does: executes a stored plan. Moves what the plan supersedes or removes
into that run's backup directory, then hands the file list to the normal
transfer pipeline. Consumes the plan.

Auth: required.

Input JSON:
```json
{"plan_id": "plan_9f2c1ab34de5f678", "override": false, "confirm_text": ""}
```

A plan that failed its safety checks needs `override: true` **and**
`confirm_text` equal to the season label, or the series name when there is none;
anything else returns 422.

Output JSON:
```json
{
  "status": "success",
  "message": "Started 3 transfers — one per season (Season 01, Season 02, Season 03)",
  "runs": [
    {"season_label": "Season 01", "transfer_id": "explore_4b91cd77a0e2", "state": "running"},
    {"season_label": "Season 02", "transfer_id": "explore_9f21ab0c73de", "state": "running"},
    {"season_label": "Season 03", "transfer_id": "explore_2c04e8b1a9f7", "state": "QUEUED_SLOT"}
  ],
  "transfer_ids": ["explore_4b91cd77a0e2", "explore_9f21ab0c73de", "explore_2c04e8b1a9f7"],
  "transfer_id": null,
  "operation": "sync_series",
  "series": "Example Series (2019)"
}
```

**One transfer per season.** A transfer is scoped to a season folder everywhere
in this application, so a plan spanning seasons produces one ordinary transfer
for each. They land on distinct destinations and run in parallel up to the
queue's slot cap.

`transfer_id` is a convenience for the common single-season case and is `null`
whenever there is not exactly one. A run with `state: "done"` moved files to
backup and had nothing to download — it is recorded as a completed
`explore_prune` transfer rather than queued.

---

## Full Endpoint Coverage Checklist

This document covers all `/api/*` routes currently implemented in backend Python route decorators:
- 5 auth endpoints
- 8 config/SSH endpoints
- 8 media endpoints
- 13 transfer endpoints (including `pause`, `resume` and `bulk-delete`)
- 32 webhook-related endpoints (receivers, management, rename, settings, Discord)
- 7 backup endpoints
- 7 debug endpoints
- 4 simulation endpoints
- 2 server log endpoints
- 9 explore endpoints

Total covered: 95 method+path API endpoints.

Counts verified against the `@*_bp.route`/`@app.route` decorators in `routes/`
and `app.py`, counting one per method+path. `GET /` is excluded: it serves the
legacy UI page and is not an API route.
