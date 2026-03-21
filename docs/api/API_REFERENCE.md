# DragonCP API Reference

Purpose: human-friendly reference for every backend HTTP API endpoint implemented by the Python server.

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
- `docs/api/openapi.yaml` (reference only, not edited)

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
- `POST /test/simulate` (if `TEST_MODE=1`; otherwise auth required)
- `POST /test/simulate/stop` (if `TEST_MODE=1`; otherwise auth required)

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
What it does: returns active runtime configuration (env + session overrides).

Auth: required.

Input: none.

Output: raw config object, for example:
```json
{
  "REMOTE_IP": "192.168.1.10",
  "REMOTE_USER": "root",
  "MOVIE_PATH": "/data/movies",
  "TVSHOW_PATH": "/data/tvshows",
  "ANIME_PATH": "/data/anime",
  "MOVIE_DEST_PATH": "/media/movies",
  "TVSHOW_DEST_PATH": "/media/tvshows",
  "ANIME_DEST_PATH": "/media/anime",
  "BACKUP_PATH": "/backups"
}
```

### POST `/config`
What it does: updates session-level config overrides (does not directly modify source code).

Auth: required.

Input JSON: any config keys to override in current session.

Output JSON:
```json
{
  "status": "success",
  "message": "Configuration saved"
}
```

### POST `/config/reset`
What it does: clears session overrides and resets runtime config back to env values.

Auth: required.

Input: none.

Output JSON:
```json
{
  "status": "success",
  "message": "Configuration reset to environment values"
}
```

### GET `/config/env-only`
What it does: returns only environment config, without session overrides.

Auth: required.

Output: raw environment config object.

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
  "password": "",
  "key_path": "/path/to/key"
}
```

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
    "files_to_transfer": 3,
    "files_to_delete": 0,
    "total_size": "4.2 GB",
    "deletions": [],
    "warnings": []
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
What it does: returns historical transfer list with optional filtering.

Auth: required.

Query params:
- `limit` (default `50`)
- `status` (optional exact status filter)

Output JSON:
```json
{
  "status": "success",
  "transfers": [],
  "total": 0
}
```

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

Implementation note:
- `queue_status.active_destinations` currently contains the transfer IDs that own reserved destinations, not the normalized path strings themselves.

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

## 5) Webhook Receiver Endpoints (Public)

### POST `/webhook/movies`
What it does: receives Radarr movie webhook, stores notification, optionally auto-syncs.

Auth: public.

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

Auth: public.

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

Auth: public.

Input JSON: Sonarr payload.

Output JSON shape is same pattern as series endpoint.

---

## 6) Webhook Notification Management Endpoints

### GET `/webhook/notifications`
What it does: returns combined notifications across movies + series + anime, sorted newest first.

Auth: required.

Query params:
- `status` (optional)
- `limit` (default `50`)

Output JSON:
```json
{
  "status": "success",
  "notifications": [],
  "total": 0
}
```

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
    "files_to_transfer": 0,
    "files_to_delete": 0,
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

### GET `/backups`
What it does: lists backups from backup model.

Auth: required.

Query params:
- `limit` (default `100`)
- `include_deleted` (`1|true|True` to include deleted records)

Output JSON:
```json
{
  "status": "success",
  "backups": [],
  "total": 0
}
```

### GET `/backups/{backup_id}`
What it does: returns one backup record.

Auth: required.

Path param:
- `backup_id`

Output JSON:
```json
{
  "status": "success",
  "backup": {}
}
```

Error behavior:
- `404` if not found.

### GET `/backups/{backup_id}/files`
What it does: lists files contained in one backup.

Auth: required.

Path param:
- `backup_id`

Query params:
- `limit` (optional)

Output JSON:
```json
{
  "status": "success",
  "files": [],
  "total": 0
}
```

### POST `/backups/{backup_id}/restore`
What it does: restores a backup fully or partially (selected relative file paths).

Auth: required.

Path param:
- `backup_id`

Input JSON (optional):
```json
{
  "files": ["relative/path1.mkv", "relative/path2.srt"]
}
```

Output JSON:
```json
{"status":"success","message":"Restore completed"}
```

Error behavior:
- `400` for invalid `files` shape or restore failure.

### POST `/backups/{backup_id}/delete`
What it does: deletes backup record and optionally backup files.

Auth: required.

Path param:
- `backup_id`

Input JSON:
```json
{
  "delete_record": true,
  "delete_files": false
}
```

Output JSON:
```json
{"status":"success","message":"..."}
```

### POST `/backups/{backup_id}/plan`
What it does: returns restore plan preview without applying restore.

Auth: required.

Path param:
- `backup_id`

Input JSON (optional):
```json
{
  "files": ["relative/path1.mkv"]
}
```

Output JSON:
```json
{
  "status": "success",
  "plan": {
    "backup_id": "id",
    "source_path": "/backup/source",
    "dest_path": "/restore/destination",
    "file_count": 1,
    "files": ["relative/path1.mkv"]
  }
}
```

### POST `/backups/reindex`
What it does: scans backup directory and imports missing backup folders into DB.

Auth: required.

Input: none.

Output JSON:
```json
{
  "status": "success",
  "message": "Imported 2 backups, skipped 5.",
  "imported": 2,
  "skipped": 5
}
```

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
    "default_timeout_minutes": 60,
    "max_timeout_minutes": 120,
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

## 10) Test Simulation Endpoints

### POST `/test/simulate`
What it does: starts fake transfer simulations for UI testing.

Auth:
- If `TEST_MODE=1`: public.
- Otherwise: JWT required.

Input JSON (all fields optional):
```json
{
  "count": 3,
  "steps": 40,
  "interval": 0.5,
  "failure_rate": 0.0
}
```

Output JSON:
```json
{
  "status": "success",
  "message": "Started 3 simulated transfers",
  "transfer_ids": ["sim_1", "sim_2", "sim_3"]
}
```

Error behavior:
- `403` if simulation disabled (`TEST_MODE!=1`).

### POST `/test/simulate/stop`
What it does: sends stop signal for running simulations.

Auth:
- If `TEST_MODE=1`: public.
- Otherwise: JWT required.

Input: no body required.

Output JSON:
```json
{"status":"success","message":"Stop signal sent"}
```

Error behavior:
- `403` if simulation disabled (`TEST_MODE!=1`).

---

## Full Endpoint Coverage Checklist

This document covers all `/api/*` routes currently implemented in backend Python route decorators:
- 5 auth endpoints
- 8 config/SSH endpoints
- 8 media endpoints
- 10 transfer endpoints
- 29 webhook-related endpoints (receivers, management, rename, settings, Discord)
- 7 backup endpoints
- 7 debug endpoints
- 2 simulation endpoints

Total covered: 76 method+path API endpoints.
