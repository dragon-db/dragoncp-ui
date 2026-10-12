# Webhooks

DragonCP listens for notifications from Radarr and Sonarr so that newly imported media on the remote server can be pulled down without anyone touching the UI. Each incoming notification is stored as a record with the full original payload, shown in the Webhooks page, and handed to the [sync engine](../sync-engine/README.md) as part of a batch for the folder it is about — every time, whatever the auto-sync switches say. With a library's switch on, the batch goes by itself: a movie straight away, a TV or anime season once Sonarr has nothing more for it on the way, so a whole season arrives as one transfer. With the switch off, the batch is held until someone presses Sync. Either way a dry run checks that the sync is safe before anything is written. The notification's status follows its batch and then its transfer: pending, queued, syncing, completed or failed.

## Where it lives

| Concern | File |
| --- | --- |
| Receiver endpoints, handing each notification to the engine, notification management API, webhook settings | `routes/webhooks.py` (`_submit_webhook`, `_manual_sync`) |
| Payload parsing; notification status for transfers from before the engine | `services/webhook_service.py` |
| Notification tables and queries (movies, series/anime, renames) | `models/webhook.py` |
| Table definitions and indexes | `models/database.py` |
| Request authentication for receivers (HMAC + IP allowlist) | `webhook_auth.py` |
| Batching, the ready check, the safety check, manual sync of notifications, notification status | `services/sync_engine/engine.py` (`submit`, `sync_notifications`) |
| Which batch a notification rides on (`sync_run_id`) | `models/sync_run.py` |
| What happens to waiting batches after a restart | `services/sync_engine/recovery.py` |
| Refusal, restart and stuck-download alerts, and their Discord announcements | `services/alert_service.py` |
| Indexing a notification's title for the ready check (`index_notification`); transfer lifecycle hooks into the engine | `services/transfer_coordinator.py` |
| Source→destination path construction | `services/path_service.py`, `services/sync_engine/units.py` |
| Sonarr `Rename` event handling | `services/rename_service.py` |
| Blueprint registration under `/api` | `app.py` |
| Status grouping and labels in the UI, including showing a flagged `pending` notification as Manual (`effectiveStatus`) | `frontend/src/lib/webhook-grouping.ts` |
| An episode's or movie's detail: "Waiting for a person" and **Open its sync** | `frontend/src/components/webhooks/episode-details.tsx` |

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

Every other `eventType` — `Download`, `Grab`, `MovieDelete`, `SeriesDelete`, `HealthIssue`, and anything else Radarr/Sonarr sends — falls through to the import path, becomes a notification row and is handed to the sync engine. There is no allowlist of event types anywhere in the receiver code.

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

### 5. Handing the notification to the sync engine

Every stored notification is handed to the sync engine by `_submit_webhook`, whatever the auto-sync switches say. It first folds the title into the title index (`TransferCoordinator.index_notification`), so the ready check has an identifier to ask Sonarr about — nothing there reaches the network, and a failure only means the fallback wait is used instead. Then it submits one request: kind `radarr_webhook` from the movie receiver, `sonarr_webhook` from the series and anime receivers.

The library's switch — `AUTO_SYNC_MOVIES`, `AUTO_SYNC_SERIES` or `AUTO_SYNC_ANIME`, read through the settings service — decides one thing only: whether the batch is **held** for a person. Before 2.3.0 a switched-off notification was stored and nothing else; now it opens or joins a batch either way, and pressing Sync later sends the whole batch.

Identify and Batch run inside the request. The ready check, the dry run and the hand-off to the queue run on the engine's own threads, so every receiver answers without waiting on rsync — the movie receiver included, which used to start the transfer inside Radarr's HTTP call. The answer carries the `notification_id` and the `run_id` of the batch. With auto-sync on, `status` is `warning` and `auto_sync` is `false` only when the engine could not work out a folder to sync (see the non-import bullet under Behaviour worth knowing).

### 6. Batching several episodes onto one transfer

A batch belongs to a destination folder: for a Sonarr notification, the season folder taken from the episode file's own path (`season_path`, then `Season NN` under the series path, then the whole series path); for a Radarr notification, the movie folder. Destinations are built by `PathService.get_destination_path`.

- No batch for the folder yet: one opens.
- A batch is open — held, waiting in the ready check, being checked, or queued, but not copying yet: the notification joins it. A six-episode season pack is one batch and one transfer.
- The folder is being copied right now: the notification goes into **one follow-up batch** behind the copy. Every later notification for that folder joins the follow-up; there is never a third.

Batches are rows in the database (`sync_run`), and each notification records the batch it rides on (`sync_run_id`), so a restart loses none of this.

**The ready check** — Sonarr only — decides when a season's batch goes:

- **Sonarr connected and answering:** ten seconds after the batch opens, Sonarr is asked whether anything for that season is still downloading, then asked again after its own time-left estimate — never sooner than 10 seconds or later than 5 minutes apart, 30 seconds when it gives no estimate — until nothing is. A download that will not finish by itself (import blocked, failed and waiting on a decision, or stalled) does not hold the season: the batch goes without it and a *Stuck download* alert names it. After 30 minutes the season syncs whatever is there, and a *Waited 30 minutes* alert says what was still downloading.
- **Sonarr not connected, not answering, or the series has no TVDB id:** the fallback wait decides — `SERIES_ANIME_SYNC_WAIT_TIME` (60 s by default) after the first notification, plus the same again for each later one, never more than 15 minutes after the first. The timer's end is stored on the batch and re-read at every step, so a later notification really does push it back. If Sonarr stops answering partway through, the batch finishes on the same timer. A Sonarr that fails the first check also opens an *Integration* alert, closed again by its next successful check.

Radarr notifications skip the ready check: one Radarr webhook is one finished movie.

**The safety check** runs next, for movies as well as seasons: one dry run of the folder (`TransferService.perform_dry_run_rsync`). For series and anime its result is stored on every notification in the batch (`dry_run_result`, `dry_run_performed_at`). If it passes, the batch is handed to the queue as one transfer and every notification in it gets that `transfer_id`. If it fails — including when the dry run itself could not finish, such as when the media server is unreachable — the batch is **refused**: nothing is written, every notification in it goes back to `pending` with `requires_manual_sync = 1` and the reason in `manual_sync_reason` (movies as well as series and anime, since 2026-10-05), and a *Safety check* alert opens with **Sync anyway**. A refusal is also announced on Discord (`autosync.blocked`) when the batch started by itself, but not when a person started it — an admin's own Sync that opened the batch, or a press of Sync or Go now that released it while it was held or waiting. Until 2026-10-05 a batch released that way was announced as an automatic refusal.

When a copy completes, a notification that joined after rsync started is moved to a follow-up batch instead of being marked synced, because the copy may already have listed the folder.

Every stage, and the reason each kind of sync skips one, is described once, in [Sync engine](../sync-engine/README.md).

### 7. Keeping notification status in step with the batch and the transfer

The engine sets the status of every notification on a batch together, matched by `sync_run_id` across both tables, and never changes one that is already `completed`:

| Moment | Notification status |
| --- | --- |
| Stored; batch held for a person | `pending` |
| Waiting in the ready check | `pending`, with `auto_sync_scheduled_at` set to when the batch is next looked at |
| Safety check passed, handed to the queue | `READY_FOR_TRANSFER`, with `transfer_id` set |
| Every slot busy | `QUEUED_SLOT` |
| Another transfer is writing to the same folder, or to one inside or around it | `QUEUED_PATH` |
| rsync starting — straight away, on promotion from the queue, or on resume | `syncing` |
| Transfer completed | `completed` |
| Transfer failed or could not start, or no folder could be worked out | `failed`, with `error_message` |
| Transfer or batch cancelled | `cancelled` |
| Refused by the safety check, or interrupted by a restart | `pending`, with `requires_manual_sync = 1` and `manual_sync_reason` (movies too, since 2026-10-05) |
| `MANUAL_SYNC_REQUIRED` | **never written** — see below |

Movie notifications go through the same table, queue states and the manual-sync flag included: since 2026-10-05 `radarr_webhook` has `requires_manual_sync` and `manual_sync_reason`, so a refused or interrupted movie carries the flag and the reason as a series notification does. It still has no dry-run columns.

Two older writers still touch series rows by `transfer_id` rather than by batch: promotion out of the queue sets every series row carrying the transfer's id to `syncing` (`TransferCoordinator.start_queued_transfer`), and re-filing a slot wait as a folder wait sets them to `QUEUED_PATH` (`QueueManager._promote_next_queued_transfer`). Neither touches movie rows, but the engine does, by batch: the re-filing also tells it (`on_transfer_waiting`), and it moves every notification on the sync — movies included — to `QUEUED_PATH`, as `before_transfer_start` moves them all to `syncing`. Until 2026-10-05 a movie whose slot wait became a folder wait kept saying `QUEUED_SLOT`.

A transfer started before the engine existed has no batch. When one of those finishes, the coordinator falls back to the old mapping, `WebhookService.update_webhook_transfer_status`, which finds notifications by `transfer_id` and maps transfer `completed`/`failed`/`cancelled` onto them, and then sends the Discord notification itself.

## Behaviour worth knowing

- **Sync on a group is one transfer per folder, not one per episode.** Sonarr
  sends a webhook per episode, so a six-episode grab arrives as six
  notifications for the same season, and a series transfer copies the whole
  season *folder* — the right unit for a group is one transfer, with every
  notification in it riding on that transfer. Every Sync on the Webhooks page —
  **Sync all** on a group (`/sync-batch`) or Sync on one row — goes to the
  engine's `sync_notifications`, which works out each notification's folder
  again and submits one manual sync per folder. The **grouping is re-derived
  server-side on purpose** — the client groups for display, but it must not get
  to decide which folder is synced, since the resulting rsync runs with
  `--delete`. Notifications for different folders are never merged.
  Notifications already `completed` are skipped ("already synced"), and so is
  one whose batch is being copied right now ("being copied right now"): moving
  it would leave the running copy unable to mark it synced. If the folder
  already has an open batch, the press joins it — and if that batch is still
  held or waiting, tells it to go now, after which it counts as a manual sync —
  so a press during the ready check never starts a second transfer. A manual sync skips the ready check but not the
  safety check. Until 2026-07-30 the page posted one sync per notification
  instead, which produced N transfers against a single destination — the queue
  serialised them on the path conflict and every run after the first moved zero
  bytes. See `tests/test_webhook_group_sync.py`.
- **Sync on one episode copies its whole season but closes only what it was
  given.** Only the notifications in the request — plus any already on the same
  open batch — are marked synced. Other pending notifications for that season,
  left on an older refused or interrupted batch, stay as they were; Sync all on
  the group closes them together.
- **`MANUAL_SYNC_REQUIRED` is not a stored status.** The engine — when the safety check refuses a batch, or after a restart — writes `status='pending'`, `requires_manual_sync=1` and `manual_sync_reason`. The string `MANUAL_SYNC_REQUIRED` appears in the model docstring, in `frontend/src/lib/webhook-grouping.ts`, in the filter dropdown on the Webhooks page and in `docs/reference/api.md`, but nothing in the backend ever sets it. The listing translates a filter on that name into `requires_manual_sync = 1 AND status = 'pending'` on the series table (`NotificationCatalog` in `models/webhook.py`), on both tables (`NotificationCatalog` in `models/webhook.py`), so the Manual filter lists series, anime and — since 2026-10-05, when movies gained the flag — movies. Only **Sync anyway**, and **Mark as done** on an *After a restart* alert, lower the flag again; a notification synced any other way keeps it, which is why the filter also requires `pending`.
- **A refused sync reads Manual, and its alert has the way past it.** A refused notification shows **Manual** instead of Pending and is listed under the Manual filter; its detail opens with "Waiting for a person: <reason>" and **Open its sync**, and a series or anime one also carries its stored dry-run result. The reason and **Sync anyway** are on the alert, on the Notifications page and on the sync's own page. Pressing Sync on the notification again starts a new manual sync, which runs the safety check again and, if that refuses too, is not announced on Discord. Until 2026-10-05 the alert could be reached only through the API (`GET /api/alerts`), and a refused notification read Pending everywhere, the Manual filter's own list included.
- **The auto-sync switch is read when a batch opens.** Switching it off does not stop a batch already waiting in the ready check. Switching it on does not release a batch already held — the next notification for that folder does, or a press of Sync.
- **`completed_at` is not only a completion time.** The engine stamps it with the current time when a sync *starts* (the move to `syncing`) and again when it completes. Treat it as "time of last significant state change" rather than "time it finished".
- **Completion is by batch membership.** When a copy completes, every notification on its batch is marked `completed`, except one that joined after rsync started, which moves to a follow-up batch. The older guard that lets only `syncing` rows complete (`mark_notifications_completed_by_transfer`) now runs only for transfers from before the engine, and is still bypassed there: `update_webhook_transfer_status` first calls `update_notifications_by_transfer_id(transfer_id, {'status': 'completed', ...})`, which updates every row carrying that transfer id regardless of its current status, so the guarded call has nothing left to match.
- **Re-delivering the same Sonarr webhook returns `500`.** The notification id for series/anime is derived from the episode file id, and `notification_id` is `UNIQUE`. A retried or duplicated delivery hits the constraint, the exception propagates to the route's `except`, and the caller gets `{"status": "error"}` with HTTP 500. Radarr deliveries embed a second-precision timestamp instead, so a retry creates a second, duplicate notification row rather than an error. There is no idempotency handling on either path.
- **`'testpath' in path` is a substring check.** A genuine library path containing that substring anywhere would be classified as a test and silently discarded.
- **Radarr `Rename` events are not special-cased.** The rename branch exists only on the series and anime endpoints. A Radarr rename notification is stored as an ordinary movie notification and handed to the engine like any other: with auto-sync on, its folder is synced after the safety check.
- **Non-import events can trigger real work.** Because event types are not filtered, a Radarr `Grab` webhook (which has a `movie.folderPath` but no imported file yet) creates a notification and, with `AUTO_SYNC_MOVIES` on, is synced at once — Radarr notifications skip the ready check — so it can copy a folder that does not contain the file yet. A payload with no `movie`/`series` object at all still inserts a row (empty `folder_path` / `series_path`); the engine then records a failed run at its Identify stage and marks the notification `failed` straight away. That happens with auto-sync off too, because the engine works out the folder before it decides whether to hold the batch.
- **Batches survive a restart, but nothing resumes by itself.** A batch that was waiting in the ready check or the safety check when DragonCP stopped is marked interrupted at start-up: its notifications go back to `pending` with the manual-sync flag (reason "DragonCP restarted before this was synced"), and an *After a restart* alert offers **Sync now**, **Mark as done**, **Mark as wrong** and **Dismiss**, announced on Discord as `sync.interrupted`. Held batches stay held; queued and copying ones carry on. Notifications the old in-memory scheduler had picked up and a restart dropped — `auto_sync_scheduled_at` set, no batch, from the last 7 days — are found once and get one such alert per folder. See [Sync engine](../sync-engine/README.md), "After a restart".
- **Episodes that arrive mid-copy wait in a follow-up batch.** They do not join the running transfer. The follow-up goes through its own ready check and dry run straight away — so that dry run can see a folder the copy ahead of it is still filling — and its transfer then waits in the queue as `QUEUED_PATH` until the copy finishes.
- **Transfers from before the engine can still complete unrelated notifications.** When such a transfer completes with no notification linked by transfer id, `_mark_pending_season_notifications_completed_from_transfer` parses the series title out of `folder_name` (stripping a trailing `(YYYY)`) and the season number out of `season_name`, then marks every `syncing` notification matching that title/season/media type as completed. The code carries a `TODO` saying this should match on season path instead. Syncs started since the engine went in are closed by batch membership and never take this path.
- **Marking a notification complete or deleting it does not touch its transfer or its batch.** `/complete` only writes `status='completed'` and `completed_at`; `/delete` only removes the row. A running rsync keeps going. The engine never rewrites a `completed` row, but promotion out of the queue still sets every series row carrying the transfer's id to `syncing`, so a row marked complete while its transfer waited in the queue can come back — and a transfer from before the engine may rewrite it when it finishes.
- **Test webhooks leave no record.** A connectivity check is only visible as a toast and a log line.
- **Webhook auth config is cached for the process lifetime.** `_get_webhook_config` memoises the parsed values on first use. `reload_webhook_config()` exists to clear that cache but has no callers, so changing `WEBHOOK_SECRET` or `WEBHOOK_ALLOWED_IPS` requires a restart.
- **Client IP comes from `request.remote_addr`.** Behind a reverse proxy without `ProxyFix`, that is the proxy's address, so an IP allowlist would either admit everything or reject everything. The module docstring calls this out. Not verified: whether the deployed configuration applies `ProxyFix`.
- **Retention helpers are unused.** All three models implement `cleanup_old_notifications(days=30)`, but nothing calls them — notification rows accumulate indefinitely unless deleted through the API.
- **Some helpers are dead code.** `mark_same_path_notifications_as_syncing`, `mark_same_path_notifications_as_queued` and `get_notifications_by_season_path` have no callers, and since the engine neither do `link_notifications_to_transfer` or the coordinator's `perform_dry_run_validation`, `mark_for_manual_sync` and `send_manual_sync_discord_alert`; grouping is by batch (`sync_run_id`) instead. `TransferCoordinator.trigger_webhook_sync`, `trigger_series_webhook_sync` and `sync_notification_group` survive as wrappers around the engine's `sync_notifications`, and nothing in the app calls them — the routes call the engine directly.
- **`requested_by` depends on tag shape.** Both parsers only accept tags that are strings matching `"<digits> - <name>"`. If Radarr/Sonarr sends tag ids or objects, `requested_by` stays null.

## Data

Written by this feature:

- `radarr_webhook` — one row per movie notification. Notable columns: `notification_id` (unique), `title`, `year`, `folder_path`, `file_path`, `poster_url`, `requested_by`, `quality`, `size`, `languages` and `subtitles` (JSON strings), `release_title`, `release_indexer`, `release_size`, `tmdb_id`, `imdb_id`, `status`, `error_message`, `transfer_id`, `raw_webhook_data`, `sync_run_id` and `sync_attached_at` (the batch it rides on, and when it joined), `requires_manual_sync` and `manual_sync_reason` (refused, or interrupted by a restart; added 2026-10-05), `created_at`, `completed_at`, `updated_at`.
- `sonarr_webhook` — one row per series/anime notification. Adds `media_type`, `series_title`, `series_title_slug`, `series_id`, `series_path`, `season_number`, `season_path`, `episode_count`, `episodes` and `episode_files` (JSON), `tags`, `banner_url`, `original_language`, `download_client`, `sync_run_id` and `sync_attached_at`, `requires_manual_sync` and `manual_sync_reason` (as on movies), plus the fields the engine writes for series only: `auto_sync_scheduled_at` (when the batch is next looked at; on rows from before the engine, when the old scheduler's window was due), `dry_run_result` and `dry_run_performed_at` (the safety check).
- `rename_webhook` — one row per Sonarr `Rename` event: `renamed_files` (JSON), `total_files`, `success_count`, `failed_count`, `status`, `error_message` (which also holds the operation log).
- `app_settings` — read and written for `AUTO_SYNC_MOVIES`, `AUTO_SYNC_SERIES`, `AUTO_SYNC_ANIME` and `SERIES_ANIME_SYNC_WAIT_TIME` (since 2.3.0 only the fallback timer, used when Sonarr cannot be asked). The `DISCORD_*` keys moved to the connector tables in 2.3.0; see [Integrations](../integrations/README.md).

The batches themselves are `sync_run` rows, with their stages and log lines in `sync_run_stage` and `sync_run_event`; refusals and restart leftovers open rows in `alert`. All four belong to the [sync engine](../sync-engine/README.md).

Read and joined against: `transfers` (via `transfer_id`, indexed on both webhook tables) and `sync_run` (via `sync_run_id`, indexed on both).

Full column list: [../../reference/database-schema.md](../../reference/database-schema.md).

## API

Receivers (authenticated by `require_webhook_auth`, not by the user session):

- `POST /api/webhook/movies`
- `POST /api/webhook/series`
- `POST /api/webhook/anime`

A stored notification's answer carries `notification_id`, `auto_sync` and the `run_id` of the batch it opened or joined.

Management (all behind `require_auth`):

- `GET /api/webhook/notifications` — one page of movies + series + anime, newest first; `status`, `media_type`, `search`, `limit` and `offset` query params
- `POST /api/webhook/notifications/bulk-delete` — delete many notifications by id, or every notification a filter finds
- `POST /api/webhook/series/notifications/sync-batch` — sync one UI group, one manual sync per destination folder; body is `{"notification_ids": [...]}`. Answers with `run_ids`; `transfer_ids` is always empty now, because a transfer exists only once a batch has passed its safety check
- `GET /api/webhook/series/notifications`, `GET /api/webhook/anime/notifications`
- `GET /api/webhook/notifications/<id>` — tries the movie table, then the series table
- `GET /api/webhook/notifications/<id>/json` — the stored raw payload
- `POST /api/webhook/notifications/<id>/sync`, `.../series/notifications/<id>/sync`, `.../anime/notifications/<id>/sync` — all three go to the engine's `sync_notifications` and answer with `run_ids`
- `POST /api/webhook/notifications/<id>/dry-run` and the series/anime equivalents (the anime route delegates to the series handler) — a dry run on demand; it stores nothing and does not count as a batch's safety check
- `POST /api/webhook/notifications/<id>/complete` and the series/anime equivalents
- `POST /api/webhook/notifications/<id>/delete` and the series/anime equivalents
- `GET|POST /api/webhook/settings` — auto-sync toggles and `series_anime_sync_wait_time`, the fallback timer (clamped to 30–900 s on write)
- `GET /api/webhook/rename/notifications`, `.../<id>`, `.../<id>/json`, `.../<id>/delete`, `.../<id>/verify`

The batch behind a notification: `GET /api/sync/lookup?notification_id=<id>`. Batches, alerts and their actions (go now, cancel, sync anyway) are the sync engine's endpoints; see [Sync engine](../sync-engine/README.md).

Full contracts: [../../reference/api.md](../../reference/api.md). Note that the API reference currently describes the three receivers as "public"; they have been behind `require_webhook_auth` since the auth module was added, and are only unauthenticated when neither `WEBHOOK_SECRET` nor `WEBHOOK_ALLOWED_IPS` is configured.

## The screen

`frontend/src/components/pages/webhooks.tsx` splits the page into two tabs, each with its own counter in the tab strip: **Media sync**, counting every notification on record, and **Renames**, counting the rename runs the API reports. The page listens on the socket and refetches the matching list when a webhook is captured or a rename arrives or completes.

Two controls sit in the header and apply to both tabs. **Refresh** refetches both lists. **Auto-sync** is a popover with one switch per library (Movies, TV Shows, Anime); the trigger button carries a dot per library, lit when that library syncs on its own, plus an `n/3` count, so the state is readable without opening it. Each switch writes immediately and confirms with a toast. The popover footer says when TV and anime start, e.g. "TV & anime start once Sonarr has nothing more for the season; if Sonarr cannot be asked, 60s after the last episode." — the number is the configured fallback wait. Until 2026-10-05 it read "TV & anime wait 60s after the last episode", which stopped being true when Sonarr began deciding.

### Media sync tab

Four tiles head the tab - media syncs, completed, in progress, failed. All four
count notifications across the whole record, not the page in view, taken from
the `status_counts` the listing returns; "in progress" is everything that is
neither completed nor failed. The first tile is annotated with how many groups
the current page collapses into. The tiles and the filter buttons therefore
agree - they used to disagree, because the tiles counted groups on screen while
the filters counted notifications in the table.

Under them, the "Arrivals" card lists the notifications, filtered by a row of
status buttons: All, Completed, Pending, Syncing, Manual, Failed. Each carries
its own count, taken from the same `status_counts`, so the number is the reason
to click. The Manual filter passes `MANUAL_SYNC_REQUIRED`, which as noted above
is never stored; the listing turns it into the manual-sync flag on series and
anime rows, and its count comes separately (`manual_sync_count`), so it lists
the episodes and movies a safety check refused or a restart interrupted
(movies since 2026-10-05).

### Searching, paging and clearing arrivals

A search box sits at the end of the toolbar and matches title, folder or season
path, release title, requester or notification id. Typing is debounced by 300 ms,
because the search runs against the database rather than the rows already loaded.

Below the list, the pager states the position in records rather than page
numbers - "51–100 of 141 arrivals" - with page sizes of 25, 50 and 100. Changing
the filter, the search or the page size returns to the first page.

Because grouping happens after paging, a season whose episodes fall either side
of a page boundary appears as a group on each page. The page is a window on the
arrivals; grouping is what happens inside it.

Each row carries a checkbox, and a bar above the list appears once anything is
picked. It offers two distinct things: **Select page**, which takes the rows in
view, and **Select all N**, which means every notification the current filter
finds - the server re-runs the filter at delete time, so it covers pages nobody
has opened. Deleting is confirmed first, and the prompt states which of the two
is about to happen. Selecting a season row selects every arrival in it.

Deleting an arrival does not touch media already copied, nor the transfer that
copied it. Deleting a pending arrival does mean it can no longer be synced from
this screen, and the confirmation says so.

### One row per season, not per episode

Grouping is done in `frontend/src/lib/webhook-grouping.ts`. Series, TV and anime notifications collapse into one row per series and season, keyed on the series slug plus the season number; movies stay one row each. A season pack that fans out into a dozen episode webhooks is therefore one row. Rows are ordered by the newest notification in each.

The group takes the most urgent status any of its episodes holds, in this order: syncing, failed, queued-path, queued-slot, ready, pending, manual. Only when none of those is present does the row read completed - so a season is never reported as done while one episode is still failed or queued.

**Manual instead of Pending.** A notification that is `pending` with `requires_manual_sync` raised — its sync was stopped by the safety check or interrupted by a restart — is shown as **Manual** (`effectiveStatus` in `webhook-grouping.ts`): on its episode row, on a movie row, and in the group status above, the dashboard's webhook rail included. A plainly `pending` episode outranks it, so a season with both reads Pending. Since 2026-10-05; before, such a notification read Pending, as if it were still on its way.

The row itself shows the poster, the title and year, a media badge, the status, and a facts line: who requested it, `Season N · M episodes`, the size on disk, and how long ago it arrived. The episode count is distinct episode numbers, not webhooks, so an episode grabbed individually and then upgraded by a pack is counted once. The size is likewise the newest imported file per episode number - the grab size on a season pack's webhook is the size of the whole pack repeated on every episode, so summing it would multiply the season.

A group with anything syncable in it gets a **Sync all** button that starts a sync for every pending, failed or manual notification in the group and reports the batch in one message. A movie row gets **Sync**, or **Retry** when the last attempt failed.

Expanding a group shows a summary line (`M episodes · K webhooks · <size> on disk`) and then one row per episode, showing the file currently on disk with its quality, size and status, marked "Pack" when Sonarr classified the release as a season pack and carrying a history count when the episode was grabbed more than once. Expanding an episode - or a movie row, which expands straight to it - opens the full detail: first, for a notification waiting for a person, "Waiting for a person: <reason>", and for one linked to a sync, **Open its sync** (the sync panel on Transfers, `/transfers?sync=<run_id>`); then the release chips and title, media facts read from the stored payload, the season and file paths, the stored dry-run result as a one-line summary with a "Details" button that opens the shared dry-run dialog, the superseded grabs under "Replaced by upgrade", and the per-item actions (Sync/Retry, Mark complete, Dry-run, View JSON, and Delete, which is hidden while the item is syncing).

### Renames tab

Four tiles again: rename runs, files renamed, failed files, and how long ago the last run was. The counts are summed over the per-run `success_count` and `failed_count`, so they count files, not webhooks.

The "Rename history" card lists the runs: series title, `x/y renamed`, the media label, how long ago, and the run's status badge - `completed`, `partial` or `failed`. Each run offers **Details** (a dialog with the run's totals and a before/after filename diff per file, marking a file as not renamed when it has no new name), **Verify rename**, **View JSON** (opens the stored payload in a new tab) and **Delete**.

### How the verification report classifies each file

**Verify rename** re-checks the run against this machine and opens the report in `frontend/src/components/webhooks/rename-verify-report.tsx`. The backend records only `verified` or `failed` per file, plus a message and whichever path it actually found; the report turns that into four outcomes:

| Shown as | Meaning | What the record looked like |
| --- | --- | --- |
| **Verified** | The file is on disk under its new name | per-file status `verified` |
| **Old name** | The rename never reached this machine - the previous filename is still there | not verified, but a path was found on disk (`actual_path` set) |
| **Blocked** | The path was rejected before it could be checked | not verified and the message mentions traversal |
| **Missing** | Neither the new nor the old name is on disk | not verified and no path found |

The distinction is the point of the report: "Old name" means re-sync that season, while "Missing" means go looking - the file is not there under either name. The filter buttons above the list are All, Verified, Old name and Missing, and the Missing filter includes the blocked files.

Above the list sit a verdict banner - "Every file verified", "Some files not verified", "Nothing to verify", or "No files verified", taken from the run-level status - four counters, and a proportional bar. Each file row carries its outcome badge, the episode marker, a before/after filename diff, and for anything not verified either the path that was found (`on disk: …`) or the path it looked for (`looked for: …`). The whole verification payload is available as JSON at the bottom, with a copy button.

## Related

- [../sync-engine/README.md](../sync-engine/README.md) — the nine stages every notification's batch goes through, restart recovery, alerts
- [../auto-sync/README.md](../auto-sync/README.md) — the three switches, held batches, and Sonarr deciding when a season is ready
- [../queue/README.md](../queue/README.md) — what `QUEUED_SLOT` and `QUEUED_PATH` mean and how promotion works
- [../simulation/README.md](../simulation/README.md) — synthetic notifications used to exercise this flow
- [../../architecture/system-overview.md](../../architecture/system-overview.md)
- [../../reference/api.md](../../reference/api.md)
- [../../reference/database-schema.md](../../reference/database-schema.md)
- [../../reference/path-handling.md](../../reference/path-handling.md) — how source paths become destination paths
