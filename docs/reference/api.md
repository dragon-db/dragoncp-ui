# DragonCP API Reference

Last updated: 2026-10-05

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
- `routes/sync_engine.py`
- `routes/media_library.py`
- `services/rename_service.py`
- `services/sync_engine/engine.py`, `services/sync_engine/stages.py`
- `services/alert_service.py`
- `services/scheduler.py`

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

A valid token is not sufficient on its own. The account behind it is read on
every request, so a protected endpoint also answers:

- `401 ACCOUNT_DISABLED` — the account has been switched off
- `401 SESSION_REVOKED` — the account was renamed or had its password changed
  since the token was issued. A disabled account answers `ACCOUNT_DISABLED`
  above, not this
- `401 UNKNOWN_ACCOUNT` — no such account
- `403 PASSWORD_CHANGE_REQUIRED` — the account still owes its first password
  change. Only `/auth/me`, `/auth/logout` and `/auth/change-password` remain
  reachable until it does.

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
Reported by Explore for a title or season, from a file-by-file comparison of the
remote and local libraries. `PARTIAL_SYNC` is Explore's addition; the retired
sync-status endpoints only had the other three, because they inferred state from
transfer rows and could not see part of a season.
- `SYNCED`
- `PARTIAL_SYNC`
- `OUT_OF_SYNC`
- `NO_INFO` — the comparison ran and the remote holds nothing for this title

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
- manual-sync-required rows — series/anime, and movies since 2026-10-05 — are not yet persisted as `MANUAL_SYNC_REQUIRED`
- they currently remain `pending` with `requires_manual_sync=1` and `manual_sync_reason` populated

Sync run states and stage statuses (the sync engine, which every sync now goes
through) are listed in section 13.

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
  "user": "admin",
  "account_id": 1,
  "role": "admin",
  "must_change_password": false,
  "is_fallback_account": false
}
```

`account_id` is the stable identity, which survives a username change; it is
`null` for the environment-file fallback account. `must_change_password` means
the password was set by whoever created the account — the frontend holds the
person at a password screen until they replace it.

Error behavior:
- `400` if JSON/body/credentials are missing.
- `401` if credentials are invalid, or the account is disabled (the two are
  deliberately indistinguishable).
- `429` with `retry_after` in seconds when too many attempts have failed. The
  attempt that trips the limit gets this rather than a `401`, and a correct
  password during the cooldown still fails.
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
  "account_id": 1,
  "role": "admin",
  "must_change_password": false,
  "is_fallback_account": false,
  "remaining_seconds": 3600
}
```

If no/invalid token, still returns `status: success` with `valid: false` and a message.
A well-formed token whose account has since been disabled, renamed, or had its
password changed also reports `valid: false`, with `code` naming the reason.

### GET `/auth/me`
What it does: reports who the caller is signed in as.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "user": "admin",
  "account_id": 1,
  "role": "admin",
  "must_change_password": false,
  "is_fallback_account": false,
  "can_change_password": true
}
```

### POST `/auth/change-password`
What it does: changes the caller's **own** password. There is no endpoint for
changing anyone else's — that is `scripts/manage_admins.py` on the server.

Auth: required.

Input JSON:
```json
{
  "current_password": "<current>",
  "new_password": "<new>"
}
```

Output JSON: the same shape as `/auth/login`. Changing a password retires every
token the account held, including the caller's, so a replacement token pair
comes back for this browser to adopt. Every other session for that account is
signed out, including its live connection.

Error behavior:
- `400` if the body is missing, the new password is under 10 characters
  (`WEAK_PASSWORD`), it matches the current one (`PASSWORD_UNCHANGED`), or the
  caller is the environment-file fallback account (`FALLBACK_ACCOUNT`, which has
  no stored password to change).
- `401` if the current password is wrong, or there is no session.

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
  "account_count": 2,
  "using_fallback_account": false,
  "message": "Authentication is configured"
}
```

`using_fallback_account` is true while no enabled administrator exists in the
database, which is when the environment-file credentials are accepted.

---

### GET `/activity`
What it does: reads the activity trail — who did what, and when — newest first.

Auth: required.

Query parameters, all optional and combined with AND:

| Parameter | Meaning |
| --- | --- |
| `actor` | a username, or an automation name such as `auto-sync` |
| `actor_kind` | `admin`, `automated` or `system` |
| `account_id` | the stable account id, which survives a rename |
| `action` | one exact action, e.g. `backup.restore`, or several separated by commas meaning any of them — `backup.delete,backup.retention_apply`. The total and the paging describe the filtered set |
| `group` | an action family, e.g. `backup` |
| `target_type` | `transfer`, `backup_capture`, `notification`, `setting`, `account`, `connection`, `simulation`, `explore_plan` |
| `target_id` | one specific thing |
| `outcome` | `ok`, `failed` or `refused` |
| `since` / `until` | ISO timestamps |
| `search` | matches the summary, the thing acted on, or the actor |
| `limit` / `offset` | paging; limit is capped at 200 |

Output JSON:
```json
{
  "status": "success",
  "entries": [
    {
      "id": 12,
      "occurred_at": "2026-08-03 15:09:38",
      "actor_kind": "admin",
      "actor_name": "priya",
      "actor_account_id": 3,
      "action": "backup.restore",
      "target_type": "backup_capture",
      "target_id": "cap_9",
      "target_label": "Example Show S01E02",
      "summary": "Restored Example Show S01E02 from a backup",
      "detail": {"files": 1},
      "outcome": "ok",
      "request_ip": "10.0.0.4"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

`actor_kind` is what separates a person from automation. `actor_name` is the
name as it read at the time — a rename does not rewrite it — while
`actor_account_id` is the stable identity that still resolves to the person.
`system` means nobody could be identified, which is a statement rather than a
blank.

### GET `/activity/for/<target_type>/<target_id>`
What it does: everything recorded against one thing, oldest first — its story.

Auth: required.

### GET `/activity/filters`
What it does: what the activity screen can filter by.

Auth: required.

Output JSON: `actors` (every actor seen in the trail, including people whose
accounts have since been disabled — which is why accounts are disabled rather
than deleted), `actions` (the closed vocabulary with human labels and their
group), and `total`.

The activity trail is read-only over HTTP. Nothing writes to it through the API
and nothing edits or removes an entry.

## 2) Configuration and SSH Endpoints

### GET `/config`
What it does: returns every setting, grouped for the React Settings screen. A
deprecated flat key -> value compatibility shape is also present during the
cutover soak.

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
What it does: deprecated cutover compatibility endpoint. There is no longer a
per-browser override layer to clear, so it reports success and changes nothing.

Auth: required.

Input: none.

### GET `/config/env-only`
What it does: deprecated cutover compatibility endpoint returning the
environment-backed settings alone. Secrets are redacted; hidden env secrets are omitted.

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

The folder, season, episode and sync-status endpoints that used to sit here
were retired when Explore replaced Browse Media. They inferred a folder's state
from whether a completed transfer row existed for it, which cannot tell "the
files match" from "we ran a transfer here once". Explore compares both
libraries file by file instead — see section 12.

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
    "raw_output": "...",
    "rsync_exit_code": 0
  }
}
```

`safe_to_sync` is `false` when rsync did not finish — an exit code other than
`0` or `24` (files that vanished mid-scan) — with `reason` reading
`The dry run did not finish (rsync exit N): <rsync's last error line>`; the
counts are whatever rsync listed before it stopped, except `local_file_count`,
which is read from this disk either way. `rsync_exit_code` is absent when
rsync never ran or ran out of time (`SSH credentials not configured`,
`Dry-run operation timed out`, `Dry-run execution error: …`). This is the same
dry run the sync engine's safety check runs.

---

## 4) Transfer Endpoints

### POST `/transfer`
What it does: syncs one folder (or one file) named by the caller. The request
goes through the sync engine as a `manual` run (section 13), like every other
sync: the folder's batch, the safety dry run, then the queue. The transfer is
only created once the safety check passes, so the answer names the run to
follow rather than a transfer.

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
- If `type=file`, `episode_name` is required. A `type=file` sync skips the
  safety check's dry run, since rsync deletes nothing when it is given one
  file. Known defect: the episode name is appended to the destination as well,
  so the file is copied into a new folder named after it rather than over it,
  and when the file already exists here the transfer fails ("Failed to create
  destination: …"). No screen sends `type=file`; see
  `../operations/known-issues.md`.

Output JSON:
```json
{
  "status": "success",
  "transfer_id": null,
  "run_id": "run_3f2a9c1d0b7e",
  "transfer_state": "checking",
  "message": "Sync started for Example Show — Season 01.",
  "source": "/source/path",
  "destination": "/destination/path",
  "episode_name": null
}
```

- `transfer_id` — `null`: no transfer exists yet when this returns. The run's
  `transfer_id` (`GET /sync/runs/{run_id}`) is filled in when it reaches the
  queue.
- `transfer_state` — the **run's** state, not the queue's. A new run answers
  `checking`, because a manual sync skips the ready check. Before the sync
  engine this field carried the queue's answer (`running`, `QUEUED_SLOT`,
  `QUEUED_PATH`).
- When a sync for the same folder exists and has not started copying, the
  request joins it and tells it to go now: `run_id` is that run's,
  `transfer_state` is `waiting` (or its current state if it was already past
  the ready check), and the message reads `Starting … now.` or
  `… is already on its way (…).`. When the folder is being copied right now, a
  follow-up run is opened behind the copy (`… is copying right now; this waits
  in a follow-up batch and runs straight after.`).

Error behavior:
- Missing `media_type`/`folder_name` or an unconfigured source or destination
  root answers `status: "error"` with HTTP 200.
- An invalid folder, season or episode name, a missing `episode_name` for
  `type=file`, or a destination that escapes its configured root answers `400`.
- When the engine cannot work out the folders, the answer is
  `{"status":"error","message":"Failed to start transfer: <reason>","run_id":"run_…"}`
  with HTTP 200; the run is still recorded, as `failed`.

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
What it does: retries a `failed`, `cancelled` or `completed` transfer as a new
`restart` run through the sync engine (section 13): the safety check runs
first, then the queue. The transfer keeps its id, and rsync picks up its
partial files. The safety check's dry run is skipped, with the reason on the
run, when the transfer is a simulation's, a single file, or an Explore plan's
(which copies its own file list and deletes nothing). A restore is refused.
When the transfer belonged to an earlier run, the webhooks that rode on it move
to the new run, which names it as its parent (`parent_relation: "retry"`).

If a sync for the same folder is already open and has not started copying, the
restart joins it instead of copying twice, and that run is told to go now — a
webhook or auto-scanner run released that way counts as a manual sync from
then on.

Auth: required.

Path param:
- `transfer_id`

Output JSON:
```json
{
  "status": "success",
  "message": "Restart requested: the safety check runs first, then the queue.",
  "run_id": "run_3f2a9c1d0b7e"
}
```

Error behavior (HTTP 200, `status: "error"`):
- `Transfer not found`
- `Only a failed, cancelled or finished transfer can be restarted (this one is running).`
- `A restore is run again from the Backups page, where its preview shows what it will replace.`

The response only says the run was opened. A refusal after that — the safety
check stopping it, or the queue refusing it (for example when `BACKUP_PATH` is
not configured) — is recorded on the run and opens an alert; it is not in this
response.

### POST `/transfer/{transfer_id}/delete`
What it does: deletes transfer record from DB (cannot delete running transfer).
A `queued` or `paused` transfer is cancelled first, as
`/transfer/{transfer_id}/cancel` would, so its queue reservation is freed and
its sync run closes as `cancelled`; a `pending` one cannot be cancelled and is
deleted as it is. Files on disk are not touched.

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
{ "all_matching": true, "status": "failed", "statuses": ["completed", "failed"], "search": "example" }
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
- In both forms, every `queued` or `paused` transfer among the rows is
  cancelled before anything is deleted, as for a single delete, so its queue
  reservation is freed and its sync run closed.

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

Every stored notification is handed to the sync engine (section 13), whether
automatic sync is on or not, so it always belongs to a run and the answer
carries that run's `run_id`. With automatic sync off for the library, the run
is opened `held` and waits for someone to press Sync on a notification or Go
now on the run. A notification for a folder whose run has not started copying
joins that run; one arriving while the folder is being copied opens a
follow-up run behind the copy.

### POST `/webhook/movies`
What it does: receives Radarr movie webhook, stores notification, hands it to
the sync engine as a `radarr_webhook` run. A Radarr run skips the ready check,
so with auto-sync on it goes straight to the safety check and the queue.

Auth: webhook auth (HMAC signature and/or IP allowlist), not JWT.

Input JSON: Radarr payload (movie import/test event payload).

Special behavior:
- Detects test webhooks (`eventType=Test`, `title=Test Title`, or `testpath`) and returns test success.
- For normal events, creates the notification record and submits it to the sync engine.

Output JSON (auto-sync off):
```json
{
  "status": "success",
  "message": "Webhook received for Example Film. Manual sync required.",
  "notification_id": "movie_42_1759655524",
  "auto_sync": false,
  "run_id": "run_3f2a9c1d0b7e"
}
```

Output JSON (auto-sync on):
```json
{
  "status": "success",
  "message": "Webhook received. Sync started for Example Film (2024).",
  "notification_id": "movie_42_1759655524",
  "auto_sync": true,
  "run_id": "run_3f2a9c1d0b7e"
}
```

With auto-sync on, `auto_sync` reports whether the engine accepted the
request. When it could not work out the folders, `status` is `warning`,
`auto_sync` is `false`, the message is
`Webhook received but auto-sync failed: <reason>`, and `run_id` names the run
recorded as `failed`.

### POST `/webhook/series`
What it does: receives Sonarr series webhook for TV shows.

Auth: webhook auth (HMAC signature and/or IP allowlist), not JWT.

Input JSON: Sonarr payload.

Special behavior:
- Handles test webhook detection.
- If `eventType` is `Rename`, processes rename workflow instead of import sync flow.
- For import flow, creates the series notification and submits it to the sync
  engine as a `sonarr_webhook` run. With auto-sync on, the run waits in the
  ready check — asking Sonarr whether anything for the season is still
  downloading, or on the fixed timer when Sonarr cannot answer — before the
  safety check and the queue.

Output JSON:
```json
{
  "status": "success",
  "message": "Series webhook received for Example Show Season 1. Sync started for Example Show — Season 01.",
  "notification_id": "tvshows_7_s1_ef1201",
  "auto_sync": true,
  "run_id": "run_3f2a9c1d0b7e"
}
```

The sentence after the first full stop is the engine's: `Sync started for …`
for a new run, `Added to the batch already open for …` when it joined one, or
the follow-up message when the season is being copied. With auto-sync off the
message ends `Manual sync required.` and `auto_sync` is `false`. With auto-sync
on and a request the engine refused, `status` is `warning` and `auto_sync` is
`false`. `Auto-sync scheduled.` is no longer sent.

### POST `/webhook/anime`
What it does: receives Sonarr anime webhook (same logic pattern as series endpoint but `media_type=anime`).

Auth: webhook auth (HMAC signature and/or IP allowlist), not JWT.

Input JSON: Sonarr payload.

Output JSON shape is same pattern as series endpoint, `run_id` included, with
messages starting `Anime webhook received for …`.

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

Notifications are returned as whole table rows, here and in the other
endpoints that return movie, series or anime notifications, so each also
carries `sync_run_id` — the sync run it rides on now (section 13), `null` for a
notification stored before the sync engine existed — and `sync_attached_at`,
when it joined that run. Rename notifications live in a separate table and do
not have these columns.

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
{ "all_matching": true, "status": "failed", "media_type": "tvshows", "search": "example" }
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
What it does: syncs a notification by hand, as a `manual` run in the sync
engine (section 13). The ready check is skipped; the safety check and the queue
still apply.

Auth: required.

Path param:
- `notification_id`

Output JSON:
```json
{
  "status": "success",
  "message": "Sync started for Example Film (2024).",
  "run_ids": ["run_3f2a9c1d0b7e"]
}
```

Behaviour:
- The id is looked up in both notification tables, so this endpoint and its
  series and anime twins below accept any notification id. The path no longer
  decides which table is read.
- If the notification's folder has a run that has not started copying, the
  notification joins it, and a run still held or waiting in the ready check is
  told to go now (`Starting … now.`). If another run is copying the folder, a
  follow-up run is opened behind it.
- A notification already `completed` is skipped (`<id>: already synced`), and
  so is one riding on a run that is copying right now (`S01E01: being copied
  right now`): moving it would leave that copy unable to mark it synced.
- `failed` and `cancelled` notifications can be synced again.

Error behavior:
- `400` with `message` when nothing could be synced: the notification does not
  exist (`1 webhook(s) no longer exist`), it was skipped for one of the reasons
  above, or its folders could not be worked out. No `run_ids` in that case.

### POST `/webhook/series/notifications/{notification_id}/sync`
What it does: syncs a series notification by hand.

Auth: required.

Path param:
- `notification_id`

Output JSON: same shape and behaviour as the movie sync endpoint, including
`run_ids`.

### POST `/webhook/anime/notifications/{notification_id}/sync`
What it does: syncs an anime notification by hand.

Auth: required.

Path param:
- `notification_id`

Output JSON: same shape and behaviour as the movie sync endpoint, including
`run_ids`.

### POST `/webhook/series/notifications/sync-batch`
What it does: syncs a whole group of notifications as **one sync run per
folder** — for series and anime, one per season — which is what "Sync all" on
a group calls. Each run is a `manual` run in the sync engine (section 13).

Auth: required.

A series transfer is scoped to the season *folder*, so one run brings the whole
season down. Posting each notification separately produced one transfer per
episode against a single destination — the queue serialised them on the path
conflict and all but the first moved zero bytes.

The grouping is re-derived on the server: each notification's destination
folder is worked out from the notification itself, and notifications with the
same destination form one run. Ids are looked up in both notification tables.
The client does not get to name the folder, because the resulting rsync runs
with `--delete`. Notifications already `completed` are skipped, and so is any
notification riding on a run that is copying right now; the message names
each one skipped and why. The same joining rules as the single sync endpoint
apply to each folder.

Input JSON — notification ids, as strings:
```json
{"notification_ids": ["tvshows_7_s1_ef1201", "tvshows_7_s1_ef1202", "tvshows_7_s1_ef1203"]}
```

Output JSON:
```json
{
  "status": "success",
  "message": "Sync started for Example Show — Season 01.",
  "transfer_ids": [],
  "run_ids": ["run_3f2a9c1d0b7e"]
}
```

- `run_ids` — one per folder the group covered. Follow them with
  `GET /sync/runs/{run_id}`.
- `transfer_ids` — always an empty list now: each run creates its transfer
  once its safety check passes, after this call has returned.
- `message` joins the outcome for each folder, then the ids skipped and why,
  then `N webhook(s) no longer exist` for ids not found, separated by `; `.

Error behavior:
- `400` when `notification_ids` is missing, empty or not a list
  (`notification_ids must be a non-empty list`), or holds anything other than
  non-empty strings (`notification_ids must be strings`).
- `400` with `status: "error"` when nothing in the group could be synced;
  `message` says why and `run_ids` is still present.
- `500` on an unexpected error.

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

## 7) Webhook Settings and Connector Endpoints

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
- `series_anime_sync_wait_time` is the sync engine's fallback timer, in
  seconds: it decides when a season's run starts only when Sonarr cannot be
  asked (not connected, not answering, or no TVDB id). When Sonarr answers, its
  own estimate of the time left decides instead. See `timer_due_at` in
  section 13.
- The `auto_sync_*` switches decide whether a webhook's run starts by itself or
  is opened `held` for a person (section 5).

Output JSON:
```json
{"status":"success","message":"Settings updated successfully"}
```

## Connectors

Discord used to be configured through `/discord/settings` and `/discord/test`,
which read and wrote five `DISCORD_*` settings keys. Those endpoints are gone.
Discord is one connector among several now, with named destinations and a
choice of destination per notification.

**No response from any endpoint below ever contains a credential.** Secrets are
stored in `connector_secret`, which has no read path to a response body. What a
client gets instead is `secrets_set` — whether a value exists — which is all a
form needs to show "configured" beside a field it must never be shown. A secret
sent back as the string `<redacted>` on save means "unchanged".

### GET `/connectors`
Every connector this build knows about, configured or not. Driven by the
adapter registry rather than by database rows, so a fresh install still lists
all of them.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "connectors": [
    {
      "id": "discord",
      "display_name": "Discord",
      "description": "Post announcements to Discord channels through webhooks.",
      "capabilities": ["notify"],
      "config_fields": [
        {"name": "app_url", "label": "App URL", "kind": "url",
         "secret": false, "required": false, "placeholder": "http://localhost:5000",
         "description": "Where a message links back to."}
      ],
      "settings_label": "Appearance",
      "settings_description": "How a message looks when it arrives in Discord.",
      "supports_check": false,
      "enabled": true,
      "configured": true,
      "config": {"app_url": "http://localhost:5000"},
      "secrets_set": {},
      "last_check_at": null,
      "last_check_ok": null,
      "last_check_message": null,
      "exists": true,
      "target_noun": "webhook",
      "targets": [
        {"target_id": "tgt_abc123", "connector_id": "discord", "label": "Default",
         "is_default": true, "enabled": true, "last_send_at": null,
         "last_send_ok": null, "last_send_error": null}
      ]
    }
  ]
}
```

Notes:
- `configured` for a notifying connector means "has a default destination", not
  "has credentials" — Discord needs no connector-level credential because a
  webhook URL carries its own.
- `exists` is false until the connector has been saved at least once.
- `settings_label` and `settings_description` name the settings form. Most
  connectors are reached with an address and a key, so theirs say "Connection";
  Discord's holds only presentation and says "Appearance". The client renders
  what it is given rather than assuming.
- `supports_check` is false when there is nothing to reach at connector level.

### GET `/connectors/<connector_id>`
One connector, plus its stored routes. `404` for an id no adapter claims.

### POST `/connectors/<connector_id>`
Saves settings. Fields declared `secret` go to `connector_secret`; everything
else goes in the config blob.

Auth: required.

Input JSON (any subset):
```json
{"enabled": true, "config": {"base_url": "http://localhost:8989", "api_key": "..."}}
```

Notes:
- Omitting `enabled` leaves it alone; omitting a config key leaves that key alone.
- A secret sent as `<redacted>` is not written. A secret sent as `""` is deleted.
- A key the connector does not declare is a `400`, naming the key.

### POST `/connectors/<connector_id>/check`
Reaches the service now and reports what happened.

`400` when the connector declares `supports_check: false` — Discord has no
endpoint to reach at this level, and answering `ok` would put a green
"last checked" badge on something nothing checked. Test a webhook instead.

Output JSON:
```json
{"status": "success", "result": {"ok": true, "message": "Connected to Sonarr 4.0.0", "detail": {}}}
```

The result is stored on the connector row, so the page can show when it was
last checked and what it said.

### POST `/connectors/<connector_id>/targets`
Adds a destination. Only for connectors that can notify — `400` otherwise.

Input JSON:
```json
{"label": "alerts", "credential": "https://discord.com/api/webhooks/...", "make_default": false}
```

Notes:
- `label` is unique per connector and is what the routing table offers by name.
- The credential is validated by the adapter first. Discord requires `https`,
  a host in the Discord set, and `/api/webhooks/` in the path — the server posts
  to whatever is stored, so this is where it is decided where it may be pointed.
- The first destination of a connector always becomes the default.

### PATCH `/connectors/<connector_id>/targets/<target_id>`
Renames, replaces the credential, takes one in or out of service, or makes it
the default. Setting a new default clears the old one in the same transaction.

### DELETE `/connectors/<connector_id>/targets/<target_id>`
Removes a destination and its credential. If it was the default, the oldest
remaining destination is promoted. Routes pointing at it are cleared to `null`
rather than deleted, so those notifications fall back to the default instead of
going silent.

### POST `/connectors/<connector_id>/targets/<target_id>/test`
Sends a real message to one destination, now, ignoring routing entirely — the
question being asked is "does this webhook work", not "where would a sync
notification go".

Error behavior: `400` with the service's own explanation, redacted.

### GET `/connectors/events`
The notification catalogue and where each announcement currently goes.

Output JSON:
```json
{
  "status": "success",
  "events": [
    {
      "key": "transfer.failed",
      "label": "Sync failed",
      "description": "A transfer stopped without finishing, with the errors rsync reported.",
      "default_severity": "failure",
      "routes": {
        "discord": {"target_id": "tgt_abc123", "enabled": true, "using_default": false}
      }
    }
  ],
  "connectors": [{"id": "discord", "display_name": "Discord", "targets": []}]
}
```

Every event appears whether or not it has been routed: a notification nobody
can see is a notification nobody can turn off. `using_default` true means no
destination was chosen, which is not a gap — it is the rule that keeps a
notification added in a later version from shipping silent.

### PUT `/connectors/routes`
Saves the routing table.

Input JSON:
```json
{"routes": [
  {"event_key": "transfer.failed", "connector_id": "discord",
   "target_id": "tgt_abc123", "enabled": true},
  {"event_key": "transfer.completed", "connector_id": "discord",
   "target_id": null, "enabled": true}
]}
```

Notes:
- `target_id: null` means "use the connector's default", the same as no row.
- An unknown event key, an unknown connector, or a destination belonging to a
  different connector is a `400` and nothing is saved for that row.

### GET `/connectors/<connector_id>/deliveries`
The last hundred announcements this connector handled, newest first. This is
the whole answer to "why didn't I get told about that", which before this
existed required reading the server console.

Output JSON:
```json
{
  "status": "success",
  "deliveries": [
    {"id": 12, "connector_id": "discord", "target_label": "alerts",
     "event_key": "transfer.failed", "title": "Example Show", "ok": true,
     "skipped_reason": null, "status_code": 204, "error": null,
     "duration_ms": 143, "created_at": "2026-08-17 01:20:11"}
  ]
}
```

A row with `ok: false` and a `skipped_reason` was held back deliberately —
the notification is switched off, the destination is out of service, or no
default is set. A row with `ok: false` and an `error` was attempted and failed.

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
queued transfer with progress and logs, and is also recorded as a `restore`
run in the sync engine (section 13). That record is bookkeeping: a restore
does not fail because it could not be written.

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
                "total_size": 0, "file_count": 1, "pinned": false,
                "capture_path": "shows/<title>/<slot>/<capture id>",
                "capture_dir": "/mnt/backup/shows/<title>/<slot>/<capture id>",
                "files": [{"name": "...", "relative_path": "...",
                           "original_path": "/mnt/media/... (null for versions
                           recovered by an index rebuild)",
                           "backup_path": "...", "file_size": 0,
                           "is_media": true}]}],
  "count": 1, "total_size": 0, "skipped_pinned": 0, "detailed": 1
}
```

`files` is populated for the first `detailed` versions only — the confirmation
dialog lists a hundred and summarises the rest, and reading file rows for a
thousand-version sweep would make the preview slower than the deletion it
describes. The counts and `total_size` always cover everything.

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

### Deprecated compatibility endpoints

Retained for one React cutover soak and backed by the same store, with a capture
id in place of the old backup id. Compatibility traffic is marked in Activity.

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

`version` is what the running server is, read from the repository's `VERSION`
file. The navbar shows this rather than the number compiled into the bundle, so
a cached frontend cannot keep reporting a release that is no longer running. See
[versioning.md](versioning.md).

Output JSON:
```json
{
  "status": "success",
  "runtime_status": {
    "backend_reachable": true,
    "version": "2.2.0",
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
through the sync engine, as `simulation` runs (section 13). A simulation run
skips the batch, ready and safety stages and is not announced; the queue and
rsync are real.

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
directory, and the sync runs flagged as simulations. Real transfers,
notifications, runs and media are untouched.

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
seen from the season you are looking at. Restoring one goes through the section 8
endpoints — `POST /backups/captures/{capture_id}/plan` for the preview, then
`/restore` — with `backup_id` here being that capture id.

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

### GET `/explore/repair/{media_type}/{folder}`
What it does: says what repairing the misplaced files in this scope would do.
Moves nothing. Local only — it works with the browse session down, because a
repair never asks the remote anything.

Query: `season=<season folder>` narrows to one season.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "plan": {
    "media_type": "tvshows",
    "scope": "Example Series (2019) — Season 05",
    "actions": [
      {
        "relative_path": "Example Series (2019)/Season 05/Example - S05E05.mkv/Example - S05E05.mkv",
        "destination": "Example Series (2019)/Season 05/Example - S05E05.mkv",
        "name": "Example - S05E05.mkv",
        "season_folder": "Season 05",
        "size": 2165283996,
        "wrapper": "Example Series (2019)/Season 05/Example - S05E05.mkv"
      }
    ],
    "blocked": [],
    "action_count": 1,
    "blocked_count": 0,
    "total_size": 2165283996,
    "blocker": null
  }
}
```

Each action carries a `rival` when another copy of the same episode or film is
already in place, and `needs_decision` is then true. The rival is found by
identity — the `SxxEyy` code, or for a film any media file in the movie folder —
not by filename, because a competing copy is almost never named the same.
`action_count` counts only the files that can simply be moved; `contested_count`
counts the ones needing a choice, and `reclaimable` is what deleting all of those
stranded copies would free.

`blocked` holds files the repair will not touch, each with a `reason` written for
a person: two stranded copies wanting the same destination, a wrapper folder
holding anything else, or a file sitting *above* its season folder and so
carrying nothing that says which season it belongs to. `blocker` is set when the
repair cannot run at all right now — an active transfer against the same title.

### POST `/explore/repair/{media_type}/{folder}`
What it does: moves the misplaced files back into place and removes the folders
they were buried in. Nothing is renamed and nothing is overwritten.

Auth: required.

Input JSON:
```json
{
  "season": "Season 05",
  "decisions": {
    "<stranded relative_path>": {
      "choice": "keep_existing",
      "rival": "<the rival relative_path the preview showed>"
    }
  }
}
```

Both optional. `season` narrows the scope. `decisions` answers the contested
files: `keep_existing` deletes the stranded copy and leaves the one in place,
`replace` does the opposite. A contested file with no decision is left alone and
reported in `failed` — the run never guesses which copy to keep.

`rival` must be the copy the preview displayed. The plan is rebuilt from disk
here, so if a different copy has appeared since, the decision no longer describes
what was agreed to and that file is refused rather than acted on.

The plan is rebuilt server-side from the disk as it is now, so the body cannot
name a file to move; a decision only selects between two files the server itself
found. Whichever copy loses is captured into the backup area before it is
removed, so both answers are reversible by an ordinary restore. If that capture
fails, nothing is deleted.

Output JSON:
```json
{
  "status": "success",
  "scope": "Example Series (2019) — Season 05",
  "moved": [{"relative_path": "...", "destination": "...", "size": 2165283996}],
  "deleted": [{"relative_path": "...", "kept_instead": "...", "size": 734003200}],
  "replaced": [{"relative_path": "...", "replaced_by": "...", "size": 524288000}],
  "failed": [],
  "blocked": [],
  "moved_count": 1,
  "deleted_count": 1,
  "replaced_count": 1,
  "failed_count": 0,
  "directories_removed": 1,
  "moved_size": 2165283996,
  "freed_size": 734003200
}
```

Errors: `409` if a transfer is active against this title or the check could not
be made; `400` if nothing in scope can be repaired automatically.

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
transfer pipeline — each season as an `explore` run in the sync engine
(section 13), handed to the queue before this call returns. Consumes the plan.

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
`explore_prune` transfer rather than queued, and as an `explore` sync run that
is already `completed`.

---

## 13) Sync Engine, Notifications and Scheduler Endpoints

Every sync passes the same nine stages — `receive`, `identify`, `batch`,
`ready`, `safety`, `queue`, `transfer`, `finish`, `tell` — whatever started it:
a Sonarr or Radarr webhook, the auto-scanner, a press of Sync, an Explore plan,
a restart, a restore or a simulation. Each pass is a **run**, kept in the
`sync_run` table and named by a `run_id` such as `run_3f2a9c1d0b7e`. A run is
what the webhook receivers and the manual sync endpoints answer with, because
its transfer is only created when the run reaches the queue. How each stage
behaves, and why a kind of sync skips one, is in
`../features/sync-engine/README.md`.

Implementation: `routes/sync_engine.py`, `services/sync_engine/`,
`services/alert_service.py`, `services/scheduler.py`.

Every endpoint in this section requires auth, and answers `503` with
`{"status":"error","message":"The sync engine is not running"}` when the part
it reads is not wired up. The alert and scheduler endpoints use that same
message.

The vocabulary, as `/sync/catalogue` serves it:

| Term | Values |
|---|---|
| Stage ids, in order | `receive`, `identify`, `batch`, `ready`, `safety`, `queue`, `transfer`, `finish`, `tell` |
| Stage status | `pending`, `running`, `waiting`, `passed`, `skipped`, `failed`, `refused` |
| Run state, open — not copying yet; a new request for the same folder joins it | `held` (automatic sync is off: waiting for a person), `waiting` (the ready check), `checking` (the safety dry run), `queued` |
| Run state, active — copying; a new webhook or manual request for the folder opens a follow-up run behind it | `transferring`, `paused`, `finishing` |
| Run state, finished | `completed`, `failed`, `cancelled`, `refused` (the safety check stopped it for a person), `interrupted` (a restart stopped it; an alert asks a person what to do) |
| Kind | `sonarr_webhook`, `radarr_webhook`, `auto_scanner`, `manual`, `explore`, `restart`, `restore`, `simulation` |

`explore`, `restore` and `simulation` runs never take in other requests
(`mergeable: false` in the catalogue).

Live updates go out over Socket.IO: `sync_run_updated` carries a run's list row
whenever the run changes, `sync_run_event` carries `{run_id, event}` for each
new log line, and `alerts_changed` carries the `/alerts/summary` figures.

### GET `/sync/catalogue`
What it does: describes the pipeline the engine runs — the stages, every kind
of sync and how it runs each stage, with the sentence shown for a stage it runs
differently or skips. A client draws the pipeline from this rather than keeping
its own copy.

Auth: required.

Output JSON (abridged):
```json
{
  "status": "success",
  "stages": [
    {"id": "receive", "label": "Receive", "tagline": "Write down what asked",
     "description": "Records the request and who or what made it — a webhook, the auto-scanner or a person — before anything else happens."}
  ],
  "kinds": [
    {
      "id": "radarr_webhook",
      "label": "Radarr webhook",
      "description": "One webhook per imported or upgraded movie. Never waits.",
      "mergeable": true,
      "stages": {
        "receive": {"mode": "run", "note": ""},
        "ready": {"mode": "skip", "note": "A Radarr webhook means one finished movie, so there is nothing to wait for — whether Radarr’s API is up or not."}
      }
    }
  ],
  "stage_statuses": ["pending", "running", "waiting", "passed", "skipped", "failed", "refused"],
  "states": {
    "open": ["held", "waiting", "checking", "queued"],
    "active": ["transferring", "paused", "finishing"],
    "terminal": ["completed", "failed", "cancelled", "refused", "interrupted"],
    "labels": {"held": "Waiting for a person", "completed": "Synced"}
  },
  "state_groups": {
    "open": ["held", "waiting", "checking", "queued"],
    "active": ["transferring", "paused", "finishing"],
    "live": ["held", "waiting", "checking", "queued", "transferring", "paused", "finishing"],
    "finished": ["completed", "failed", "cancelled", "refused", "interrupted"]
  },
  "alert_actions": {"sync_now": "Sync now", "dismiss": "Dismiss"},
  "alert_kinds": {"sync_refused": "Safety check", "transfer_failed": "Failed"}
}
```

- Each kind lists all nine stages. `mode` is `run` (the standard stage),
  `diff` (runs differently; `note` says how) or `skip` (`note` says why).
- The catalogue describes kinds, so it cannot show three skips the engine
  decides per run, each with its own sentence on the run's `safety` stage: a
  restart of a simulated transfer (which also skips `tell`), a single-file
  sync, and a restart of an Explore plan's transfer. `GET /sync/runs/{run_id}`
  shows what a given run actually did.
- `states.labels` holds a label for every state; `state_groups` are the names
  `/sync/runs?state=` accepts.
- `alert_actions` and `alert_kinds` map every alert action and kind to its
  label (see `/alerts` below).

### GET `/sync/runs`
What it does: one page of runs, newest first, each with its stage strip.

Auth: required.

Query parameters, all optional and combined with AND:

| Parameter | Meaning |
|---|---|
| `state` | one state, several separated by commas, or one group: `open`, `active`, `live` (open and active), `finished`, `all` (the default). A group name inside a comma list is read as a state and matches nothing |
| `kind` | one kind, or several separated by commas |
| `search` (or `q`) | matches title, folder, season, destination path, run id or transfer id, case-insensitively and anywhere in the value |
| `simulations` | `0`, `false` or `no` leaves simulation runs out; absent or anything else includes them |
| `limit` / `offset` | paging; `limit` defaults to `50` and is clamped to 1–200 |

Output JSON:
```json
{
  "status": "success",
  "limit": 50,
  "offset": 0,
  "total": 1,
  "state_counts": {"waiting": 1, "completed": 12},
  "runs": [
    {
      "run_id": "run_3f2a9c1d0b7e",
      "kind": "sonarr_webhook",
      "kind_label": "Sonarr webhook",
      "label": "Example Show — Season 01",
      "title": "Example Show",
      "season_name": "Season 01",
      "media_type": "tvshows",
      "source": "sonarr",
      "state": "waiting",
      "state_label": "Waiting for the download",
      "current_stage": "ready",
      "outcome": null,
      "outcome_message": null,
      "transfer_id": null,
      "parent_run_id": null,
      "parent_relation": null,
      "is_simulation": false,
      "requested_by": {"kind": "automated", "name": "webhook-series", "label": "AUTO / webhook-series"},
      "stages": [
        {"id": "receive", "status": "passed"},
        {"id": "identify", "status": "passed"},
        {"id": "batch", "status": "passed"},
        {"id": "ready", "status": "waiting"},
        {"id": "safety", "status": "pending"},
        {"id": "queue", "status": "pending"},
        {"id": "transfer", "status": "pending"},
        {"id": "finish", "status": "pending"},
        {"id": "tell", "status": "pending"}
      ],
      "webhook_count": 1,
      "next_check_at": "2026-10-05T09:12:14.113402+00:00",
      "created_at": "2026-10-05T09:12:04.113402+00:00",
      "updated_at": "2026-10-05T09:12:04.198733+00:00",
      "started_at": null,
      "finished_at": null
    }
  ]
}
```

- `total` — runs matching every filter.
- `state_counts` — runs per state across the whole table. It honours
  `simulations` only, so it does not move with `state`, `kind` or `search`.
- `label` — the title, with ` — <season>` when there is one.
- `source` — `sonarr` or `radarr` when a service is behind the request; often
  `null` otherwise.
- `transfer_id` — `null` until the run reaches the queue, where its transfer is
  created.
- `outcome` — set when the run ends: `completed`, `failed`, `cancelled`,
  `refused` or `interrupted`, with `outcome_message` saying why.
- `parent_relation` — `follow_up` (opened behind a copy of the same folder that
  was already running) or `retry` (a restart of an earlier run's transfer).
- `requested_by.kind` — `admin`, `automated` or `system`, as in the activity
  trail.
- `next_check_at` — when the ready check next looks again (asks Sonarr, or the
  fixed timer runs out); `null` outside the ready check.
- Timestamps are UTC ISO 8601.

### GET `/sync/runs/{run_id}`
What it does: one run in full — every stage with its sentence, detail and its
own log lines, the webhooks riding on it, its transfer, related runs, its
alerts, and what can be done to it now.

Auth: required.

Path param:
- `run_id`

The run carries every field of a `/sync/runs` row — `webhook_count` here
counts the `webhooks` below — plus the fields shown here.

Output JSON (abridged — list-row fields left out, one of the nine stages shown):
```json
{
  "status": "success",
  "run": {
    "run_id": "run_3f2a9c1d0b7e",
    "state": "waiting",
    "source_path": "/remote/tv/Example Show (2020)/Season 01",
    "dest_path": "/media/tv/Example Show (2020)/Season 01",
    "operation_type": "folder",
    "ready_mode": "ask",
    "checks_made": 0,
    "timer_due_at": "2026-10-05T09:13:04.113402+00:00",
    "ready_deadline_at": "2026-10-05T09:42:04.113402+00:00",
    "force_safety": false,
    "stage_detail": [
      {
        "id": "batch",
        "label": "Batch",
        "tagline": "Join one or open one",
        "description": "Looks for a batch already open for the same folder. ...",
        "mode": "run",
        "policy_note": "",
        "status": "passed",
        "summary": "Opened a new batch for Example Show — Season 01 with 1 webhook.",
        "detail": null,
        "started_at": "2026-10-05T09:12:04.143636+00:00",
        "finished_at": "2026-10-05T09:12:04.143636+00:00",
        "events": [
          {"id": 3, "run_id": "run_3f2a9c1d0b7e", "stage": "batch", "level": "success",
           "message": "Opened a new batch for Example Show — Season 01 with 1 webhook.",
           "data": null, "created_at": "2026-10-05T09:12:04.151967+00:00"}
        ]
      }
    ],
    "webhooks": [
      {"notification_id": "tvshows_7_s1_ef1201", "table": "sonarr_webhook",
       "label": "S01E01", "status": "pending", "season_number": 1,
       "title": "Example Show", "created_at": "2026-10-05 09:12:03",
       "sync_attached_at": "2026-10-05T09:12:04.160012+00:00", "transfer_id": null,
       "requires_manual_sync": 0, "manual_sync_reason": null}
    ],
    "transfer": null,
    "related": [],
    "alerts": [],
    "actions": ["go_now", "cancel"]
  }
}
```

- `stage_detail` — always nine entries, in stage order. `mode` and
  `policy_note` say how this run's kind treats the stage; `summary` is the
  stage's current sentence, `detail` its structured facts (the dry-run counts
  under `safety`, for example), and `events` its own log lines.
- `webhooks` — oldest first. Series rows carry an episode `label` such as
  `S01E01` or `S01E05–E06`; movie rows carry `year` and a `Title (year)`
  label. Both carry `requires_manual_sync` and `manual_sync_reason`
  (`SyncRunStore.webhooks`).
- `transfer` — `null` until the run has a transfer; then `transfer_id`,
  `status`, `progress`, `transport`, `progress_percent`, `bytes_transferred`,
  `total_bytes`, `speed_bps`, `eta_seconds`, `start_time`, `end_time`,
  `log_count` and `queue_reason`. The rsync lines are at
  `/transfer/{transfer_id}/logs`.
- `related` — list rows with a `relation`: the run this one follows or retries
  (`follow_up_of`, `retry_of`) and the runs that follow or retry it
  (`follow_up`, `retry`).
- `alerts` — up to 20 alerts raised about this run, in any state, newest first,
  in the `/alerts` shape.
- `ready_mode` — `ask` (asking Sonarr), `timer` (the fixed timer, used when
  Sonarr is not connected, does not answer, or the series has no TVDB id), or
  `null` before the ready check has decided. `checks_made` counts the
  questions put to Sonarr.
- `timer_due_at` — when the fixed timer runs out: the configured wait
  (`series_anime_sync_wait_time` in `/webhook/settings`, 30–900 seconds) after
  the first webhook, extended by the same again for each later one, never past
  15 minutes from the first.
- `ready_deadline_at` — the longest the ready check waits: 30 minutes after the
  run opened.
- `force_safety` — true once an admin chose to go ahead despite the safety
  check.
- `actions` — what can be done now:

| Action | Offered when | How |
|---|---|---|
| `go_now` | `held` or `waiting` | `POST /sync/runs/{run_id}/go-now` |
| `cancel` | any open or active state | `POST /sync/runs/{run_id}/cancel` |
| `sync_anyway` | `refused` | `POST /sync/runs/{run_id}/sync-anyway` |
| `restart` | `failed` or `cancelled`, with a transfer | `POST /transfer/{transfer_id}/restart` — there is no run endpoint for it |

Error behavior:
- `404` `{"status":"error","message":"No such sync run"}`.

### GET `/sync/runs/{run_id}/events`
What it does: a run's log lines after a given one — what a live view polls for
between socket events.

Auth: required.

Query params:
- `after` (default `0`) — an event `id`; only later lines are returned
- `stage` (optional) — only that stage's lines

Output JSON:
```json
{
  "status": "success",
  "events": [
    {"id": 3, "run_id": "run_3f2a9c1d0b7e", "stage": "batch", "level": "success",
     "message": "Opened a new batch for Example Show — Season 01 with 1 webhook.",
     "data": null, "created_at": "2026-10-05T09:12:04.151967+00:00"}
  ]
}
```

Oldest first. `level` is `info`, `success`, `warning` or `error`. A run keeps
at most 2,000 lines; past that the oldest are dropped.

Error behavior:
- `404` for an unknown run.

### GET `/sync/lookup`
What it does: the run behind a transfer or a webhook, so any screen can link to
it.

Auth: required.

Query params (one of):
- `transfer_id` — the newest run that owns the transfer; failing that, the run
  named on the transfer row
- `notification_id` — the run the notification rides on now. A notification can
  move to a later run: a follow-up batch, or a restart.

When both are given, `transfer_id` is used.

Output JSON:
```json
{
  "status": "success",
  "run_id": "run_3f2a9c1d0b7e",
  "run": {"run_id": "run_3f2a9c1d0b7e", "state": "waiting", "stages": [ ... ]}
}
```

`run` is a `/sync/runs` row, except that `webhook_count` is `null` here.

Error behavior:
- `400` `Give a transfer_id or a notification_id` when neither is given.
- `404` `No sync run found` when nothing links to a run — for example a
  transfer or notification from before the sync engine existed.

### POST `/sync/runs/{run_id}/go-now`, `/cancel`, `/sync-anyway`
What they do: act on a run that has not finished. Each call is recorded in the
activity trail — `sync.go_now`, `sync.cancel`, `sync.sync_anyway` — refusals
included, against target type `sync_run`.

Auth: required.

Input: no body.

All three answer in one shape:
```json
{
  "status": "success",
  "ok": true,
  "run_id": "run_3f2a9c1d0b7e",
  "action": "promoted",
  "state": "waiting",
  "message": "Starting Example Show now.",
  "transfer_id": null,
  "queue_state": null
}
```

`200` with `status: "success"` when `ok` is true; otherwise `409` with
`status: "error"`, `action: "failed"` and `message` saying why. `404`
`{"status":"error","message":"No such sync run"}` for an unknown run.

**go-now** — a run that is `held` (automatic sync is off) or `waiting` in the
ready check goes now: the ready check passes at once and the run moves on to the
safety check. `action` is `promoted`. For a run already past the ready check
(checking, queued, copying, paused, finishing) it changes nothing and answers
`200`, with a message saying the sync is already on its way and naming its
state (`Example Show is already on its way (copying).`). `409` when the run
already ended (`This sync already ended.`). A `sonarr_webhook`,
`radarr_webhook` or `auto_scanner` run released this way counts as a manual
sync from then on: its result is announced as "Manual Sync", and a
safety-check refusal of it is not announced on Discord.

**cancel** — ends the run. A run in the queue, copying or paused has its
transfer cancelled; a run still held, in the ready check or in the safety check
is closed as `cancelled`, with its webhooks — and so is a queued run whose
transfer row has gone (deleted from the transfer list), which there is no
transfer to cancel for. `action` is `cancelled`. `409` when the run already
ended (`This sync already ended.`) or its transfer could not be cancelled.

**sync-anyway** — goes ahead with a run the safety check stopped (`refused`).
The safety stage is marked passed with a warning naming who overrode it, and
the run is handed to the queue inside this request, so `transfer_id` is filled
in and `state` is the run's state after the hand-off. `action` is `promoted`.
`409` when the run is not `refused`
(`Only a sync the safety check stopped can be overridden.`), when another sync
for the same folder is already on its way, or when the queue refused the
transfer — then `state` is `failed` and `message` says why.

### GET `/alerts`
What it does: the Notifications tab — alerts, newest first. An alert is
something that needs a person; it stays open until an admin acts on it.

Auth: required.

Query params:
- `state` — `open` (default), `done`, `wrong`, `dismissed`, or `all`
- `kind` — one kind, or several separated by commas (table below)
- `limit` / `offset` — paging; `limit` defaults to `50` and is clamped to 1–200

Output JSON:
```json
{
  "status": "success",
  "limit": 50,
  "offset": 0,
  "total": 1,
  "open": 1,
  "by_severity": {"warning": 1},
  "alerts": [
    {
      "id": 1,
      "alert_id": "alert_7c1e04b9a2d3",
      "kind": "sync_refused",
      "kind_label": "Safety check",
      "severity": "warning",
      "title": "Sync stopped by the safety check: Example Show — Season 01",
      "message": "Would delete 40 files here. Nothing was written. Media server: 2 files · this disk: 0 · would delete 40 · would add 2.",
      "state": "open",
      "dedupe_key": "refused:run_3f2a9c1d0b7e",
      "run_id": "run_3f2a9c1d0b7e",
      "transfer_id": null,
      "unit_key": "/media/tv/Example Show (2020)/Season 01",
      "link": "/pipeline/run_3f2a9c1d0b7e",
      "actions": ["sync_anyway", "dismiss"],
      "action_buttons": [
        {"id": "sync_anyway", "label": "Sync anyway"},
        {"id": "dismiss", "label": "Dismiss"}
      ],
      "data": {"reason": "Would delete 40 files here", "counts": "...",
               "explore": {"media_type": "tvshows", "folder": "Example Show (2020)", "season": "Season 01"}},
      "occurrences": 1,
      "created_at": "2026-10-05T09:12:14.364264+00:00",
      "updated_at": "2026-10-05T09:12:14.364264+00:00",
      "resolved_at": null,
      "resolved_action": null,
      "resolved_by_kind": null,
      "resolved_by_name": null,
      "resolved_by_account_id": null
    }
  ]
}
```

- `total` — alerts in the requested `state` and, when given, `kind`.
- `open`, `by_severity` — the `/alerts/summary` figures, always for open
  alerts.
- `severity` — `warning`, or `failure` for a failed transfer.
- `dedupe_key` — one open alert per subject. The same thing happening again
  while the alert is open bumps `occurrences` and updates `message` instead of
  opening a second alert. For `scanner_gap`, `integration_down` and
  `job_failing`, which watch a condition, an alert with the same key that a
  person closed with `dismiss` or `mark_wrong` in the last 24 hours keeps a new
  one from opening, or being announced; after that, a condition still there
  opens one again.
- `unit_key` — the destination folder the alert is about, when it is about one.
- `link` — where the web app shows the subject: `/pipeline/<run_id>` for a run,
  `/integrations/<source>` for an integration; `null` when there is neither.
- `actions` — what this alert offers; `action_buttons` adds each button's
  label.
- `resolved_*` — who closed it, when and how. `resolved_action` is `auto` when
  the alert closed itself.

| `kind` | `kind_label` | Opens when | `actions` |
|---|---|---|---|
| `restart_unfinished` | After a restart | webhooks were waiting to sync when DragonCP stopped | `sync_now`, `mark_done`, `mark_wrong`, `dismiss` |
| `transfer_unknown` | Result unknown | DragonCP restarted during a copy and could not read how it ended | `retry`, `mark_done`, `dismiss` |
| `stuck_download` | Stuck download | a season synced without a download stuck in Sonarr | `dismiss` |
| `ready_timeout` | Waited 30 minutes | a season synced after 30 minutes with Sonarr still downloading | `dismiss` |
| `sync_refused` | Safety check | the safety dry run stopped a sync | `sync_anyway`, `dismiss` |
| `transfer_failed` | Failed | a transfer failed, or the queue refused it. For a restore the title reads `Restore failed: …` and the message ends `Run it again from the Backups page.` | `retry`, `mark_done`, `dismiss`; for a restore, `dismiss` only |
| `scanner_gap` | Auto-scanner | the auto-scanner tried a gap twice and will not retry it by itself | `sync_now`, `dismiss` |
| `integration_down` | Integration | Sonarr did not answer the ready check; closes itself (`auto`) when it answers again | `dismiss` |
| `job_failing` | Scheduler | a background job failed three times in a row; closes itself (`auto`) on its next success | `run_now`, `dismiss` |

### GET `/alerts/summary`
What it does: how many alerts are open — the badge on the tab.

Auth: required.

Output JSON:
```json
{"status": "success", "open": 2, "by_severity": {"warning": 1, "failure": 1}}
```

### POST `/alerts/{alert_id}/action`
What it does: does what the alert's button says, then closes the alert. If the
action itself fails, the alert stays open.

Auth: required.

Path param:
- `alert_id`

Input JSON:
```json
{"action": "sync_anyway"}
```

| `action` | What it does | Alert becomes |
|---|---|---|
| `sync_now` | Syncs the webhooks the alert names, as the notification sync endpoints do; for an auto-scanner gap, submits a `manual` run for the folder it names | `done` |
| `retry` | Restarts the alert's transfer, as `POST /transfer/{transfer_id}/restart` does | `done` |
| `sync_anyway` | Overrides the safety check on the alert's run, as `POST /sync/runs/{run_id}/sync-anyway` does | `done` |
| `run_now` | Runs the alert's scheduler job, as `POST /scheduler/jobs/{name}/run` does | `done` |
| `mark_done` | On `transfer_failed`, `transfer_unknown` and `restart_unfinished` alerts it records the work as finished: the webhooks the alert lists are marked `completed`, and when the alert names a run, that run is closed as `completed` and its webhooks are marked `completed`. The transfer itself keeps its own status — a `failed` transfer stays `failed` in the history, and the run's Finish stage says so. On other kinds it only closes the alert | `done` |
| `mark_wrong` | Closes the alert only | `wrong` |
| `dismiss` | Closes the alert only. Accepted on every open alert, whether offered or not | `dismissed` |

Output JSON:
```json
{
  "status": "success",
  "message": "Going ahead despite the safety check.",
  "alert": {
    "alert_id": "alert_7c1e04b9a2d3",
    "state": "done",
    "resolved_action": "sync_anyway",
    "resolved_at": "2026-10-05T09:20:41.563086+00:00",
    "resolved_by_kind": "admin",
    "resolved_by_name": "admin",
    "resolved_by_account_id": 1
  }
}
```

`alert` is the whole alert in the `/alerts` shape, after the change. Each
successful action is recorded in the activity trail as `alert.resolve`.

Error behavior:
- `400` `Unknown action '<action>'` when `action` is missing or not one of the
  seven above.
- `404` `No such alert`.
- `409` when the alert is already closed (`This alert is already closed`), the
  action is not one it offers, or the action itself failed. The body carries
  `message` and the alert as it stands.

### GET `/scheduler/jobs`
What it does: every background job on the scheduler's clock, with its switch,
interval, last run and next run. This release registers two:
`sonarr_auto_scanner` and `radarr_auto_scanner`.

Auth: required.

Output JSON:
```json
{
  "status": "success",
  "jobs": [
    {
      "name": "sonarr_auto_scanner",
      "label": "Sonarr auto-scanner",
      "description": "Asks Sonarr what it imported and syncs anything this disk does not have yet.",
      "enabled": true,
      "interval_seconds": 3600.0,
      "running": false,
      "last_run_at": "2026-10-05T08:00:04.113402+00:00",
      "last_finished_at": "2026-10-05T08:00:09.551210+00:00",
      "last_ok": true,
      "last_result": {"ok": true, "summary": "Checked 42 Sonarr title(s): everything it imported is here."},
      "consecutive_failures": 0,
      "next_run_at": "2026-10-05T09:00:04.113402+00:00"
    }
  ]
}
```

- `enabled` and `interval_seconds` are read from the job's own settings on every
  call — for the auto-scanners, the switch and interval on the Sonarr and Radarr
  integrations. `interval_seconds` is `null` when the job is off, and so is
  `next_run_at`; `next_run_at` is also `null` until the scheduler's first tick
  after start-up.
- `last_result` — what the last run returned, minus any stack trace; `summary`
  is the sentence to show. `{}` until the job has run. An auto-scanner run also
  reports `found`, `started`, `already_on_its_way`, `held_back`,
  `needs_a_person`, `failed`, `since` and its `decisions`.
- `last_run_at`, `last_finished_at`, `last_ok`, `last_result` and
  `consecutive_failures` are kept in the `scheduled_job` table and survive a
  restart. Three failures in a row open a `job_failing` alert.

### POST `/scheduler/jobs/{name}/run`
What it does: runs a job now, whatever its schedule — a job whose switch is off
runs once. Returns as soon as the run has started; the job runs in the
background.

Auth: required.

Path param:
- `name` — a job name from `/scheduler/jobs`

Output JSON:
```json
{"status": "success", "message": "Started.", "job": {"name": "sonarr_auto_scanner", "running": true}}
```

`job` is the job in the `/scheduler/jobs` shape. The call is recorded in the
activity trail as `scheduler.run_now`.

Error behavior:
- `404` `{"status":"error","message":"No such job"}`.
- `409` `That job is already running.`, with `job` — a job never overlaps
  itself.

---

## 14) Media Library Endpoints

The Library, Queue and History tabs of the Sonarr and Radarr integrations.
`{source}` is `sonarr` or `radarr`; anything else is a `404`. Every endpoint
answers `503` when the title index is not available.

Responses here use `success` (`true`/`false`) and `error` rather than the
`status` envelope. Sonarr and Radarr are only ever read: the connector adapters
refuse any verb but GET and HEAD.

Implementation: `routes/media_library.py`, `services/media_index.py`,
`services/auto_scanner.py` (`sync_one`).

### GET `/library/{source}`
What it does: one row per title the service holds, with what this disk holds
beside it.

Auth: required.

Query: `refresh=1` (or `true`, `yes`) pulls the service's whole catalogue into
the index first.

Output JSON: `source`, `live` (false when the service could not be read and the
index answered instead), `total`, `counts` (titles per `sync_state`) and
`items`, plus `success: true`, `read_only: true` and `test_mode`.

### GET `/library/{source}/history`
What it does: a page of the service's own history, with titles the index knows
matched in.

Auth: required.

Query params: `page` (default `1`), `page_size` (default `50`, clamped to
1–200); `400` when either is not a number.

Output JSON: `source`, `live`, `records`, `page`, `page_size`, `total`, plus
`success` and `read_only`. Each record carries `event_type`, `date`,
`source_title` and `quality`, and `title`, `external_id` and `known_here` from
the index. When the service is not connected or does not answer, `live` is
false, `records` is empty and `message` says which.

### GET `/library/{source}/queue`
What it does: what is waiting on the service, and why each row is waiting. Rows
that need attention come first.

Auth: required.

Output JSON: `source`, `live`, `rows`, `counts` (rows per `verdict`), `total`,
`needing_attention` and `holding_a_sync`, plus `success` and `read_only`. Each
row carries `verdict`, `why`, `holds_sync` and `needs_attention` beside the
service's own progress, size and download-client fields. When the service is
not connected or does not answer, `live` is false, `rows` is empty and
`message` says which.

### POST `/library/{source}/sync`
What it does: syncs what this disk is missing of one title, because someone
pressed Sync on it. What to fetch is worked out on the server from the service
as it is now: for Sonarr, every season that counts towards the title's state
and holds fewer files here than in Sonarr; for Radarr, the movie when it is not
here. Each becomes a `manual` run in the sync engine (section 13), so the
safety check and the queue apply as for any other sync.

Auth: required.

Input JSON — the title's TVDB id for Sonarr, TMDB id for Radarr:
```json
{"external_id": "900001"}
```

Output JSON:
```json
{
  "success": true,
  "transfers_started": 1,
  "error": "",
  "runs": [
    {"ok": true, "run_id": "run_3f2a9c1d0b7e", "action": "opened", "state": "checking",
     "message": "Sync started for Example Show — Season 02.", "transfer_id": null,
     "queue_state": null}
  ]
}
```

- `runs` — one entry per season (or the movie), in the shape the run actions
  answer with. Before the sync engine this response carried a `decision` object
  instead.
- `transfers_started` — despite its name, the number of runs the engine
  accepted. No transfer exists yet when this returns; each run creates its own
  once its safety check passes.

Error behavior:
- `400` `external_id is required`.
- `409` with `success: false` and `error` when there is nothing to start: the
  service did not answer, the title is not recorded, the service holds no files
  for it yet, or everything it holds is already here. When every run was
  refused, `error` joins their messages and `runs` is present too.
- `500` on an unexpected error; `503` when syncing from the library view is not
  available.

### POST `/library/{source}/refresh`
What it does: pulls the service's catalogue into the index. A POST because it
writes — to this side's database only.

Auth: required.

Output JSON:
```json
{"success": true, "source": "sonarr", "titles_seen": 128, "read_only": true}
```

Error behavior:
- `502` when the service does not answer.

---

## Full Endpoint Coverage Checklist

This document covers these `/api/*` routes from the backend Python route decorators:
- 7 auth endpoints
- 3 activity endpoints
- 8 config/SSH endpoints
- 2 media endpoints (`/media-types` and `/media/dry-run`; the rest were retired
  with Browse Media)
- 13 transfer endpoints (including `pause`, `resume` and `bulk-delete`)
- 29 webhook-related endpoints (receivers, management, rename, settings)
- 11 connector endpoints (listing, settings, destinations, routing, delivery history)
- 28 backup endpoints
- 7 debug endpoints
- 4 simulation endpoints
- 2 server log endpoints
- 11 explore endpoints (including `repair`)
- 13 sync engine, alert and scheduler endpoints
- 5 media library endpoints

Total covered: 143 method+path API endpoints.

Not covered here: the 8 `/remote-transfer/*` endpoints in
`routes/remote_daemon.py`, which `../features/fast-transfers/README.md` lists.
With them the backend serves 151.

Counts verified against the `@*_bp.route`/`@app.route` decorators in `routes/`
and `app.py`, counting one per method+path. `GET /` and
`GET /<path:frontend_path>` are excluded: they serve the React application
shell and are not API routes.
