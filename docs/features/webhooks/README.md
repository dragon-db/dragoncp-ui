# Webhooks

DragonCP listens for notifications from Radarr and Sonarr so that newly imported media on the remote server can be pulled down without anyone touching the UI. Each incoming notification is stored as a record with the full original payload, shown in the Webhooks page, and — depending on the auto-sync switches — either turned into a transfer straight away, held for a batching window so a whole season arrives as one transfer, or left alone for someone to sync by hand. Once a transfer exists, the notification tracks that transfer's fate: queued, syncing, completed, or failed.

## Where it lives

| Concern | File |
| --- | --- |
| Receiver endpoints, notification management API, webhook/Discord settings | `routes/webhooks.py` |
| Payload parsing, sync triggering, transfer→notification status mapping | `services/webhook_service.py` |
| Notification tables and queries (movies, series/anime, renames) | `models/webhook.py` |
| Table definitions and indexes | `models/database.py` |
| Request authentication for receivers (HMAC + IP allowlist) | `webhook_auth.py` |
| Batching window and dry-run gate for series/anime | `services/auto_sync_scheduler.py` |
| Facade the routes call; dry-run validation, manual-sync marking, Discord alert | `services/transfer_coordinator.py` |
| Source→destination path construction | `services/path_service.py` |
| Sonarr `Rename` event handling | `services/rename_service.py` |
| Blueprint registration under `/api` | `app.py` |
| Status grouping and labels in the UI | `frontend/src/lib/webhook-grouping.ts` |

## How it works

### 1. The request arrives

Three receivers exist, all registered under the `/api` prefix in `app.py`:
`POST /api/webhook/movies`, `POST /api/webhook/series`, `POST /api/webhook/anime`.

Each is wrapped in `require_webhook_auth` (`webhook_auth.py`). That decorator reads `WEBHOOK_SECRET` and `WEBHOOK_ALLOWED_IPS` from `dragoncp_env.env` / `.env` (env vars used as a fallback) and applies this matrix:

| `WEBHOOK_SECRET` | `WEBHOOK_ALLOWED_IPS` | Result |
| --- | --- | --- |
| unset | unset | request allowed, warning logged once per process |
| unset | set | `request.remote_addr` must fall inside one of the listed IPs/CIDRs, else `403` |
| set | unset | `X-DragonCP-Signature` must be `sha256=<hex>` of the raw body, else `401` |
| set | set | either check passing is enough, else `403` |

The HMAC is computed with `hmac.new(secret, raw_body, sha256)` and compared with `hmac.compare_digest`, so it is constant-time. The decorator calls `request.get_data()` before the handler touches `request.json`, because Flask has to have the raw bytes cached for the signature to be reproducible. If an env file exists but cannot be read, `_load_env_file` raises rather than falling through to the allow-all branch — the deliberate choice is to fail closed.

The handler then rejects anything that is not `application/json` (`400`) and any empty body (`400`).

### 2. Test detection

Before anything is parsed or stored, all three receivers check:

```
eventType == 'Test'  or  title == 'Test Title'  or  'testpath' in <folderPath|path>
```

If any is true the handler emits a `test_webhook_received` Socket.IO event, returns `{"status": "success", "is_test": true}` and stops. Nothing is written to the database. This is what makes the "Test" button in Radarr/Sonarr report success without leaving a phantom movie in the notification list.

### 3. Event types

Only two `eventType` values are branched on:

- `Test` — handled above, on all three endpoints.
- `Rename` — on `/webhook/series` and `/webhook/anime` only. It is handed to `RenameService.process_rename_webhook`, which renames the matching local files immediately and writes a row to `rename_webhook` with status `completed`, `partial` or `failed`. If the rename service was not initialised the endpoint returns `500`.

Every other `eventType` — `Download`, `Grab`, `MovieDelete`, `SeriesDelete`, `HealthIssue`, and anything else Radarr/Sonarr sends — falls through to the import path and becomes a notification row. There is no allowlist of event types anywhere in the receiver code.

### 4. Parsing and storage

Movies go through `WebhookService.parse_webhook_data`, which reads:

- title, year, `movie.folderPath`
- poster URL: first `images[]` entry whose `coverType` is `poster`, using its `remoteUrl`
- `requested_by`: the first tag string shaped `"<digits> - <name>"`, split on the first `" - "`
- `movieFile.path`, `quality`, `size`, language names, `mediaInfo.subtitles`
- `release.releaseTitle` / `indexer` / `size`, plus `tmdbId` and `imdbId`
- notification id `movie_{movie.id}_{unix_seconds}`

Series and anime go through `parse_series_webhook_data(webhook_json, media_type)`, which additionally:

- takes the season number from `episodes[0].seasonNumber`
- reads the singular `episodeFile` key (not `episodeFiles`) and stores it as a one-element `episode_files` list
- derives `season_path` as `os.path.dirname(episodeFile.path)` — the real directory on the remote server. Only if there is no episode file does it fall back to `"{series_path}/Season {NN}"`, which assumes Sonarr's default naming
- builds the notification id as `{media_type}_{series_id}_s{season}_ef{episodeFileId}`, falling back to a microsecond timestamp when there is no episode file id. The comment in the code explains why: second-precision ids collided when a season pack imported several episodes inside the same second

The route then serialises the untouched request body with `json.dumps(webhook_data, indent=2)` and passes it to `WebhookNotification.create` / `SeriesWebhookNotification.create` as `raw_webhook_data`, so the original payload is always retrievable later via the `/json` endpoint. New rows start at status `pending`. A `webhook_received` Socket.IO event is emitted through `emit_socketio_event`, which swallows and logs emit failures so a dead websocket never turns a good webhook into an error response.

### 5. From notification to transfer

**Movies.** The route reads `AUTO_SYNC_MOVIES` from the `app_settings` table, falling back to the env value. If enabled it calls `trigger_webhook_sync(notification_id)` synchronously, inside the HTTP request. That function refuses if the notification is already `syncing` or `completed`, sets status to `syncing`, builds a transfer id `webhook_{notification_id}_{unix_seconds}`, uses `folder_path` as the source, asks `PathService.get_destination_path(source, 'movies')` for the destination, records the transfer id on the notification, and calls `TransferCoordinator.start_transfer`. A missing `folder_path` or an unconfigured destination base marks the notification `failed` with `error_message` set.

**Series and anime.** The route reads `AUTO_SYNC_SERIES` / `AUTO_SYNC_ANIME` (DB only, default false). If enabled it calls `schedule_auto_sync`, which reads `SERIES_ANIME_SYNC_WAIT_TIME` (default `60` seconds) and hands the notification to `AutoSyncScheduler.schedule_job`. Nothing is transferred from inside the request.

### 6. Batching several episodes onto one transfer

`AutoSyncScheduler` keys jobs by `f"{series_title_slug}_S{season_number}"`. The first notification for a key creates an `AutoSyncJob` with `scheduled_time = now + wait_time` and starts a daemon thread that sleeps until then. Every further notification for the same key is appended to `job.notification_ids` and pushes `scheduled_time` further out by another wait period, capped so the total from job creation never exceeds `max_wait_time` (900 s). Notifications stay `pending` throughout, with `auto_sync_scheduled_at` recording when the window is due to close. The point is that a season pack lands as one rsync of the season folder rather than one rsync per episode.

When the window closes, `_execute_job`:

1. loads the first notification in the batch and calls `TransferCoordinator.perform_dry_run_validation`, which runs one dry-run rsync against the season path and stores `dry_run_result` / `dry_run_performed_at` on that notification
2. if `safe_to_sync` — sets every notification in the batch to `READY_FOR_TRANSFER`, then calls `trigger_series_webhook_sync(primary_id, batched_notification_ids=all_ids)`
3. if not safe — calls `mark_for_manual_sync` on every notification in the batch and sends a single Discord alert for the batch
4. either way, removes the batch job from the scheduler in a `finally` block

`trigger_series_webhook_sync` picks the source path (`season_path` first, reconstructed `Season NN` second, whole `series_path` last), derives the destination through `PathService`, writes the transfer id onto the primary notification, and — this is the batching link — calls `link_notifications_to_transfer` to stamp the same `transfer_id` onto every notification in the batch. From that point on the whole batch is addressed as one unit through `update_notifications_by_transfer_id`.

### 7. Keeping notification status in step with the transfer

`start_transfer` returns an explicit `queue_type`, and `trigger_series_webhook_sync` maps it onto the notification status of every row sharing the transfer id:

| `start_transfer` result | Notification status |
| --- | --- |
| `running` | `syncing` |
| `pending` | `syncing` |
| `QUEUED_SLOT` | `QUEUED_SLOT` |
| `QUEUED_PATH` | `QUEUED_PATH` |
| failure | `failed` with `error_message` |

Later transitions come from two places:

- `TransferCoordinator.start_queued_transfer` — when the queue promotes a transfer, it moves every notification linked to that transfer id from `QUEUED_*` to `syncing` before rsync starts.
- `TransferCoordinator._post_transfer_completion` — a watcher thread per transfer polls the transfer row every 5 s and, once it is no longer `running`/`pending`, calls `WebhookService.update_webhook_transfer_status`. That maps transfer `running` → `syncing`, `completed` → `completed`, `failed` → `failed` (with `error_message` "Transfer failed"), `cancelled` → `cancelled`. Transfer status `queued` is deliberately a no-op, because the queue reason is already known to the caller that queued it.

Movie notifications are found by `WebhookNotification.get_by_transfer_id`; series/anime updates go through `update_notifications_by_transfer_id`, so a batch of episodes moves together.

The full set of statuses a series/anime row can hold, and where each is written:

| Status | Written by |
| --- | --- |
| `pending` | on creation, and during the batching window |
| `READY_FOR_TRANSFER` | `AutoSyncScheduler._execute_job` after a passing dry run |
| `QUEUED_SLOT` | `trigger_series_webhook_sync` when the concurrency cap is full |
| `QUEUED_PATH` | `trigger_series_webhook_sync` when another transfer owns the destination |
| `syncing` | transfer started, or a queued transfer was promoted |
| `completed` | transfer finished, or the "mark complete" endpoint |
| `failed` | transfer failed, or the sync could not be started |
| `cancelled` | transfer cancelled |
| `MANUAL_SYNC_REQUIRED` | **never written** — see below |

Movie rows only ever hold `pending`, `syncing`, `completed` or `failed` from this flow.

## Behaviour worth knowing

- **`MANUAL_SYNC_REQUIRED` is not a stored status.** `TransferCoordinator.mark_for_manual_sync` writes `status='pending'`, `requires_manual_sync=1` and `manual_sync_reason`. The string `MANUAL_SYNC_REQUIRED` appears in the model docstring, in `frontend/src/lib/webhook-grouping.ts`, in the filter dropdown on the Webhooks page and in `docs/reference/api.md`, but nothing in the backend ever sets it. Filtering the notification list by that status therefore returns nothing; the real signal is the `requires_manual_sync` flag.
- **Movie notifications say `syncing` even when the transfer is only queued.** `trigger_webhook_sync` sets `status='syncing'` before calling `start_transfer` and then ignores the returned `queue_type`. A movie waiting behind the concurrency cap looks like it is transferring. The series/anime path does not have this problem because it maps `queue_type` explicitly.
- **`completed_at` is not only a completion time.** Both `trigger_webhook_sync` and the `running`→`syncing` mapping stamp `completed_at` with the current time when a sync *starts*. Treat it as "time of last significant state change" rather than "time it finished".
- **The "only `syncing` rows may complete" guard is bypassed on the normal completion path.** `update_webhook_transfer_status` first calls `update_notifications_by_transfer_id(transfer_id, {'status': 'completed', ...})`, which updates every row carrying that transfer id regardless of its current status, and only afterwards calls `mark_notifications_completed_by_transfer`, whose `AND status='syncing'` clause therefore has nothing left to match. The protection described at length in the `SeriesWebhookNotification` docstring holds between *different* transfers (each has its own id), not within one.
- **Re-delivering the same Sonarr webhook returns `500`.** The notification id for series/anime is derived from the episode file id, and `notification_id` is `UNIQUE`. A retried or duplicated delivery hits the constraint, the exception propagates to the route's `except`, and the caller gets `{"status": "error"}` with HTTP 500. Radarr deliveries embed a second-precision timestamp instead, so a retry creates a second, duplicate notification row rather than an error. There is no idempotency handling on either path.
- **`'testpath' in path` is a substring check.** A genuine library path containing that substring anywhere would be classified as a test and silently discarded.
- **Radarr `Rename` events are not special-cased.** The rename branch exists only on the series and anime endpoints. A Radarr rename notification is stored as an ordinary movie notification and, with auto-sync on, triggers a folder sync.
- **Non-import events can trigger real work.** Because event types are not filtered, a Radarr `Grab` webhook (which has a `movie.folderPath` but no imported file yet) creates a notification and, with `AUTO_SYNC_MOVIES` on, immediately starts an rsync of a folder that may not contain the file yet. Payloads with no `movie`/`series` object at all still insert a row (empty `folder_path` / `series_path`), and only fail later when the sync cannot find a source path.
- **Movie auto-sync runs inside the HTTP request.** Radarr's webhook call blocks until path construction, the queue admission check and the rsync process spawn have all returned. Series and anime hand off to a background thread and answer immediately.
- **Batch jobs live only in memory.** `AutoSyncScheduler.jobs` is a plain dict guarded by a lock, and the wait is a daemon thread sleeping in one-second steps. A restart during the batching window loses the job; the notifications stay `pending` with an `auto_sync_scheduled_at` in the past and nothing reschedules them.
- **Episodes that arrive mid-sync do not join the running transfer.** They create a new notification, a new batch job, and eventually a new transfer for the same destination, which the queue then holds as `QUEUED_PATH` until the first one finishes.
- **Manual syncs of a season can complete unrelated notifications.** When a completed transfer has no notification linked by transfer id, `_mark_pending_season_notifications_completed_from_transfer` parses the series title out of `folder_name` (stripping a trailing `(YYYY)`) and the season number out of `season_name`, then marks every `syncing` notification matching that title/season/media type as completed. The code carries a `TODO` saying this should match on season path instead.
- **Marking a notification complete or deleting it does not touch its transfer.** `/complete` only writes `status='completed'` and `completed_at`; `/delete` only removes the row. A running rsync keeps going, and its watcher may later rewrite the status of a row that still exists.
- **Test webhooks leave no record.** A connectivity check is only visible as a toast and a log line.
- **Webhook auth config is cached for the process lifetime.** `_get_webhook_config` memoises the parsed values on first use. `reload_webhook_config()` exists to clear that cache but has no callers, so changing `WEBHOOK_SECRET` or `WEBHOOK_ALLOWED_IPS` requires a restart.
- **Client IP comes from `request.remote_addr`.** Behind a reverse proxy without `ProxyFix`, that is the proxy's address, so an IP allowlist would either admit everything or reject everything. The module docstring calls this out. Not verified: whether the deployed configuration applies `ProxyFix`.
- **Retention helpers are unused.** All three models implement `cleanup_old_notifications(days=30)`, but nothing calls them — notification rows accumulate indefinitely unless deleted through the API.
- **Some model helpers are dead code.** `mark_same_path_notifications_as_syncing`, `mark_same_path_notifications_as_queued` and `get_notifications_by_season_path` have no callers; same-path grouping is currently achieved through `transfer_id` linkage instead.
- **`requested_by` depends on tag shape.** Both parsers only accept tags that are strings matching `"<digits> - <name>"`. If Radarr/Sonarr sends tag ids or objects, `requested_by` stays null.

## Data

Written by this feature:

- `radarr_webhook` — one row per movie notification. Notable columns: `notification_id` (unique), `title`, `year`, `folder_path`, `file_path`, `poster_url`, `requested_by`, `quality`, `size`, `languages` and `subtitles` (JSON strings), `release_title`, `release_indexer`, `release_size`, `tmdb_id`, `imdb_id`, `status`, `error_message`, `transfer_id`, `raw_webhook_data`, `created_at`, `completed_at`, `updated_at`.
- `sonarr_webhook` — one row per series/anime notification. Adds `media_type`, `series_title`, `series_title_slug`, `series_id`, `series_path`, `season_number`, `season_path`, `episode_count`, `episodes` and `episode_files` (JSON), `tags`, `banner_url`, `original_language`, `download_client`, plus the auto-sync fields `requires_manual_sync`, `manual_sync_reason`, `auto_sync_scheduled_at`, `dry_run_result`, `dry_run_performed_at`.
- `rename_webhook` — one row per Sonarr `Rename` event: `renamed_files` (JSON), `total_files`, `success_count`, `failed_count`, `status`, `error_message` (which also holds the operation log).
- `app_settings` — read and written for `AUTO_SYNC_MOVIES`, `AUTO_SYNC_SERIES`, `AUTO_SYNC_ANIME`, `SERIES_ANIME_SYNC_WAIT_TIME`, and the `DISCORD_*` keys.

Read and joined against: `transfers` (via `transfer_id`, indexed on both webhook tables).

Full column list: [../../reference/database-schema.md](../../reference/database-schema.md).

## API

Receivers (authenticated by `require_webhook_auth`, not by the user session):

- `POST /api/webhook/movies`
- `POST /api/webhook/series`
- `POST /api/webhook/anime`

Management (all behind `require_auth`):

- `GET /api/webhook/notifications` — movies + series + anime merged and sorted newest first; `status` and `limit` query params
- `GET /api/webhook/series/notifications`, `GET /api/webhook/anime/notifications`
- `GET /api/webhook/notifications/<id>` — tries the movie table, then the series table
- `GET /api/webhook/notifications/<id>/json` — the stored raw payload
- `POST /api/webhook/notifications/<id>/sync`, `.../series/notifications/<id>/sync`, `.../anime/notifications/<id>/sync`
- `POST /api/webhook/notifications/<id>/dry-run` and the series/anime equivalents (the anime route delegates to the series handler)
- `POST /api/webhook/notifications/<id>/complete` and the series/anime equivalents
- `POST /api/webhook/notifications/<id>/delete` and the series/anime equivalents
- `GET|POST /api/webhook/settings` — auto-sync toggles and `series_anime_sync_wait_time` (clamped to 30–900 s on write)
- `GET|POST /api/discord/settings`, `POST /api/discord/test`
- `GET /api/webhook/rename/notifications`, `.../<id>`, `.../<id>/json`, `.../<id>/delete`, `.../<id>/verify`

Full contracts: [../../reference/api.md](../../reference/api.md). Note that the API reference currently describes the three receivers as "public"; they have been behind `require_webhook_auth` since the auth module was added, and are only unauthenticated when neither `WEBHOOK_SECRET` nor `WEBHOOK_ALLOWED_IPS` is configured.

## Related

- [../auto-sync/README.md](../auto-sync/README.md) — the batching window, dry-run gate and manual-sync flag in detail
- [../queue/README.md](../queue/README.md) — what `QUEUED_SLOT` and `QUEUED_PATH` mean and how promotion works
- [../simulation/README.md](../simulation/README.md) — synthetic notifications used to exercise this flow
- [../../architecture/system-overview.md](../../architecture/system-overview.md)
- [../../reference/api.md](../../reference/api.md)
- [../../reference/database-schema.md](../../reference/database-schema.md)
- [../../reference/path-handling.md](../../reference/path-handling.md) — how source paths become destination paths
