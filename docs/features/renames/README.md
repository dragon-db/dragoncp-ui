# Renames

When Sonarr renames episode files on the media server, the local copy keeps the old filenames until something replays the rename. DragonCP does that replay: a rename webhook arrives, DragonCP works out where each file should live on this machine, renames it in place, and records the outcome per file so an operator can see exactly which episodes were touched and which were not. Nothing is copied or downloaded — this is a local rename only, so it costs seconds rather than a re-sync of the whole season. A separate, on-demand verification pass answers the follow-up question: is the file actually on disk under its new name right now?

## Where it lives

| Concern | File |
| --- | --- |
| Rename replay and verification logic | `services/rename_service.py` |
| Webhook receivers that route rename events | `routes/webhooks.py` |
| Rename history storage | `models/webhook.py` (`RenameNotification`) |
| Table definition and indexes | `models/database.py` |
| Local path mapping base directories | `services/path_service.py` (`get_base_destination`) |
| Path safety checks | `security.py` |
| Discord summary | `services/notification_service.py` (`send_rename_discord_notification`) |
| Service wiring | `app.py` |
| Renames tab, verification report | `frontend/src/components/pages/webhooks.tsx`, `frontend/src/components/webhooks/rename-verify-report.tsx` |

## How it works

### 1. The webhook arrives

Sonarr posts to `/api/webhook/series` or `/api/webhook/anime`. Both receivers in `routes/webhooks.py` do the same three checks in order: authentication (`require_webhook_auth`), test-payload detection, then `if event_type == 'Rename'`. A rename event never reaches the normal parsing and auto-sync path — it is handed straight to `RenameService.process_rename_webhook()` with the media type baked in (`'tvshows'` for the series receiver, `'anime'` for the anime receiver).

The work happens synchronously inside the request. Sonarr's HTTP call stays open until every file has been renamed, and the response body carries the full result under `result`. HTTP status is `200` when the service reports success and `400` when it does not.

### 2. Parsing

`_parse_rename_data()` reads `series` and `renamedEpisodeFiles` from the payload. It builds a notification ID of the form `rename_<series id>_<epoch milliseconds>` and one record per file holding: Sonarr's `previousPath` / `previousRelativePath`, `path` / `relativePath`, the two basenames as `previous_name` and `new_name`, plus empty slots for `status`, `error`, `local_previous_path` and `local_new_path`.

That record is written to `rename_webhook` immediately (`RenameNotification.create`) with `status='pending'` and the raw webhook JSON, and a `rename_webhook_received` socket event goes out so the Renames tab refreshes before any file is touched. The row exists even if the process dies mid-rename.

### 3. Mapping server paths to local paths

`_map_to_local_path()` is deliberately narrow. It ignores the server's directory layout above the series folder and rebuilds the local path from three pieces:

1. the configured destination base for the media type — `TVSHOW_DEST_PATH` or `ANIME_DEST_PATH`, via `PathService.get_base_destination()`
2. the **basename** of `series.path` from the payload (the series folder name)
3. Sonarr's relative path (`Season 01/Show - S01E01 - Title.mkv`), with separators normalised for the local OS

So `/remote/anime/Show (2025)` + `Season 01/file.mkv` becomes `<ANIME_DEST_PATH>/Show (2025)/Season 01/file.mkv`. The mapping can be this simple because the local tree is expected to mirror the server's series/season structure under the configured base.

Both the previous and the new path go through the same function. Before joining, `validate_relative_path()` rejects absolute paths, `..` segments, null bytes and CR/LF; after joining, `assert_path_within_bounds()` resolves symlinks and confirms the result is still inside the destination base. Either failure raises `PathTraversalError` and the file is recorded as failed rather than aborting the run. A missing destination configuration raises `ValueError`, which surfaces as a per-file failure too.

### 4. Renaming, file by file

`_execute_renames()` walks the file records and decides between four outcomes:

- **Source exists, target does not** — creates the target directory if needed (`os.makedirs`), then `os.rename()`. Status `success`, message `Renamed successfully`.
- **Source missing, target exists** — treated as already done. Status `success`, message `File already renamed (exists at new path)`. This is what makes a redelivered webhook harmless.
- **Source missing, target missing** — status `failed`, message `File not found locally`, and `error` records the full local path that was checked. This is the normal outcome when the season was never synced locally.
- **Source exists and target also exists** — status `failed`, message `Target file already exists`. The service refuses to overwrite; deciding which of two real files wins is not something it will guess.

Every branch also appends a one-line human-readable entry to an operation log. `PathTraversalError`, `PermissionError`, `OSError` and any other exception are caught per file, so one bad file cannot stop the rest.

### 5. Recording the result

Counts are tallied into an overall status: `completed` (no failures), `failed` (no successes), or `partial`. The row is updated with the per-file records, the counts, the status, `completed_at`, and the joined operation log. Note that the log goes into `error_message` — that column holds all log lines, successes included, not just errors.

If that update returns false, the service returns failure with `persistence_error: true` and a message saying the rename happened on disk but history could not be updated. It returns **before** emitting `rename_completed` and before the Discord notification, so a persistence failure is loud rather than silently successful.

On the normal path it emits `rename_completed` over the socket, calls `NotificationService.send_rename_discord_notification()` (teal embed for completed, orange for partial, red for failed; first five filenames listed), and returns `(status != 'failed', result)`.

### 6. Verification, later and on demand

Verification is a separate manual action — `POST /api/webhook/rename/notifications/<id>/verify` — and it never renames anything. `verify_rename_notification()` loads the stored notification and picks its file list via `_extract_verification_files()`: persisted per-file results first, and if those are empty, it re-parses `raw_webhook_data` so a run whose results never persisted can still be checked.

For each file, `_verify_local_rename()` resolves the expected local path (reusing `local_new_path` if stored, otherwise re-deriving it from the relative path) and checks the filesystem:

- new path exists → `verified`, with `actual_path` set
- new path missing but previous path exists → `failed`, message `File still exists at the previous path`, `actual_path` pointing at the old file
- neither exists → `failed`, message `Expected renamed file was not found locally`
- path rejected during mapping → `failed`, message `Path traversal rejected: ...`

Those three failure shapes matter more than the pass/fail count, and the UI leans on them: `rename-verify-report.tsx` classifies a result with an `actual_path` as "Old name" (re-sync the season), no path as "Missing", and a traversal message as "Blocked". The response status is `verified`, `partial` or `failed` by the same all/none/some rule used for the rename itself. Verification results are returned to the caller only — they are not written back to the database.

## Behaviour worth knowing

- **Renames never enter the transfer queue.** No rsync, no SSH, no slot or path locking (`../queue/README.md` does not apply here). The trade-off is that a rename run holds the webhook request open for its whole duration.
- **Movies have no rename path.** The `/api/webhook/movies` receiver has no `Rename` branch, so a Radarr rename payload is parsed as an ordinary movie notification and stored in `radarr_webhook`. Rename replay covers TV shows and anime only.
- **A renamed series folder breaks the mapping.** Both the previous and the new local path are built from the series folder name in the *current* payload. If Sonarr renamed the series folder itself, the previous local path is computed under the new folder name, which does not exist locally — every file reports `File not found locally`. The same applies whenever the local folder name differs from Sonarr's for any reason.
- **Files moved between season folders leave the old folder behind.** The target directory is created when missing, but the source directory is never cleaned up.
- **"File not found locally" is usually not an error.** It is the expected result for seasons that were never synced to this machine. A run where every file is missing lands on status `failed`, and the receiver answers Sonarr with HTTP 400 — the webhook looks broken when nothing was actually wrong.
- **Replays are safe.** A second delivery of the same payload finds the files already at their new names and reports success. The notification ID embeds a millisecond timestamp, so the replay creates a *new* history row rather than updating the old one.
- **A persistence failure leaves a misleading row.** The disk rename has happened, but the row stays `pending` with zero counts and no `completed_at`, no `rename_completed` event fires, and no Discord message is sent. The caller gets `persistence_error: true` and HTTP 400. Verification still works on such a row because it falls back to the stored raw webhook JSON.
- **`error_message` is a log, not just errors.** Reading it as an error field will mislead: successful runs populate it too.
- **Rename history is never pruned automatically.** `RenameNotification.cleanup_old_notifications()` exists but no caller invokes it anywhere in the codebase; rows accumulate until deleted through the UI or the delete endpoint.
- **Empty rename payloads verify as a failure.** A notification with no files at all returns status `failed` with `No renamed files are available for verification` and HTTP 400, not an empty success.
- **Path traversal is rejected per file, not per run.** A crafted relative path fails only its own file and is logged with a `SECURITY:` prefix; the remaining files still process.
- **If the service is not wired up, the endpoints answer 500.** `routes/webhooks.py` guards every rename entry point with a `rename_service` null check. In practice `app.py` always constructs it at startup.
- Not verified: whether Sonarr retries a rename webhook after a 400 response, and how it behaves on the request timeout of a very large rename batch.

## Data

Reads and writes a single table, `rename_webhook`. Full column list in `../../reference/database-schema.md`.

| Column | Used for |
| --- | --- |
| `notification_id` | `rename_<series id>_<epoch ms>`, unique, used by every endpoint |
| `media_type` | `tvshows` or `anime`; selects the destination base path |
| `series_title`, `series_id`, `series_path` | From the payload's `series` object; `series_path`'s basename drives local path mapping |
| `renamed_files` | JSON array of per-file records (previous/new paths and names, `status`, `error`, `local_previous_path`, `local_new_path`) |
| `total_files`, `success_count`, `failed_count` | Tallies shown in the Renames tab |
| `status` | `pending` on insert, then `completed` / `partial` / `failed` |
| `error_message` | Joined operation log for the whole run, successes included |
| `raw_webhook_data` | Original payload; served by the `/json` endpoint and used as the verification fallback |
| `created_at`, `completed_at`, `updated_at` | Timestamps; `completed_at` is only set by the post-run update |

Indexes exist on `notification_id`, `status` and `created_at` (`models/database.py`).

## API

Receivers (webhook auth), full contracts in `../../reference/api.md`:

- `POST /api/webhook/series` — rename replay when `eventType` is `Rename`
- `POST /api/webhook/anime` — same, for anime

Management endpoints (session auth):

- `GET /api/webhook/rename/notifications` — list, filterable by `status` and `media_type`, `limit` defaults to 50
- `GET /api/webhook/rename/notifications/{id}` — one run with its per-file records
- `GET /api/webhook/rename/notifications/{id}/json` — raw stored payload, served as `application/json`
- `POST /api/webhook/rename/notifications/{id}/delete` — remove a run from history
- `POST /api/webhook/rename/notifications/{id}/verify` — verification pass. `404`
  when the notification does not exist, `400` only when there are no files to
  verify. A run where files are found still under their old names returns `200`
  with `result.status` of `partial` or `failed` — the HTTP code reports whether
  the check ran, not whether it passed

Socket events: `rename_webhook_received` (before work starts) and `rename_completed` (after a successfully persisted run).

## Related

- [Auto-sync](../auto-sync/README.md) — what happens to the non-rename Sonarr events on the same receivers
- [Queue](../queue/README.md) — the transfer machinery renames deliberately bypass
- [Simulation](../simulation/README.md)
- [System overview](../../architecture/system-overview.md)
- [API reference](../../reference/api.md)
- [Database schema](../../reference/database-schema.md)
