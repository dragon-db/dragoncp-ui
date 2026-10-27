# Renames

Last updated: 2026-10-27

Sonarr names an episode `TBA` while its title is still unknown, and keeps that name until someone renames it:

    Example Show (2024) - S01E05 - TBA [WEBDL-1080p][GRP].mkv

DragonCP renames those episodes to their real titles in two ways:

- **From Explore** (since 2026-10-23). Explore shows which series still have TBA episodes, what each would be called, and renames them here — and asks Sonarr to rename its own copy when it still holds one. Titles Sonarr does not have yet can come from TMDB.
- **Replaying Sonarr's own renames.** When Sonarr renames files on the remote server, its rename webhook arrives here and DragonCP renames the local copies to match.

Both are local renames only: nothing is copied, downloaded or read from the remote server, so they work while Explore is offline and cost seconds. Every run is recorded in the Renames tab under Webhooks, with Undo.

## Where it lives

| Concern | File |
| --- | --- |
| Renames from Explore: plan, rename, Undo, title check, TMDB links | `services/renames/service.py` |
| Where a title sits in a file name, and how Sonarr writes one | `services/renames/naming.py` |
| TMDB reads | `services/renames/tmdb.py` |
| Title checks, TMDB links, titles taken from TMDB | `models/title_store.py` |
| Sonarr's `RenameFiles` / `RefreshSeries`, naming settings, rename preview, the TMDB key field | `services/connectors/adapters/sonarr.py`, `services/connectors/adapters/_arr.py` (`command`) |
| Explore and Undo endpoints | `routes/renames.py` |
| Rename replay and verification logic | `services/rename_service.py` |
| Webhook receivers that route rename events | `routes/webhooks.py` |
| Rename history storage | `models/webhook.py` (`RenameNotification`) |
| Table definition and indexes | `models/database.py` |
| Local path mapping base directories | `services/path_service.py` (`get_base_destination`) |
| Path safety checks | `security.py` |
| Discord summary | `services/notification_service.py` (`send_rename_discord_notification`) |
| Service wiring | `app.py` |
| Renames tab (history, Undo), verification report | `frontend/src/components/pages/webhooks.tsx`, `frontend/src/components/webhooks/rename-verify-report.tsx` |
| Explore's tags, strip and review | `frontend/src/components/pages/explore.tsx`, `frontend/src/components/explore/` |

## Renaming from Explore

### What you see

1. **A TBA tag** on every series and season in the Explore tree that still has an episode named TBA, and a **Needs titles** filter that shows only those. The tag is read from file names Explore already lists, so it costs nothing.
2. **A strip above the episode list** of such a series or season: how many episodes can get their real titles now and how many are still waiting, with **Rename** and **Refresh titles**. Each episode row shows its new name under the old one, or why it is still waiting ("Sonarr still says TBA", "Not in Sonarr").
3. **Rename** opens a review: every file old → new in full, the subtitles, `.nfo` and artwork that move with it, which ones Sonarr will also rename, and what is left alone and why. Nothing changes until you confirm, and only the names you were shown are applied — if any one of them changed in between, nothing is renamed and you review again.
4. **Rename all ready**, with the Needs titles filter on, does the same for every ready episode in the library, one series at a time, with progress as it goes and one Discord message at the end.
5. **A series Sonarr does not have** offers **Find titles on TMDB**: search by the folder's name and year, pick the right show once, and its episodes can then be renamed from TMDB's titles.

The Sonarr Library pop-up of a series with TBA episodes says how many, with a **Rename in Explore** link.

### Where a title comes from

For each episode still named TBA, in this order:

1. **Sonarr holds the file and its own rename would give it a title.** The file here gets exactly the name Sonarr's rename gives its copy — including anything else Sonarr's naming would change, such as a tag added to its naming since — and Sonarr is asked to rename its copy too. Both ends then carry the same name, so Explore sees them as in sync. This is used only when the file here is named like Sonarr's copy apart from the title, i.e. it is the same file.
2. **Sonarr has the title but no longer holds the file** (the remote server cleans up after a sync). The title is put into the name here. Only the title changes; quality, release group and languages stay exactly as they are.
3. **Sonarr still says TBA, or does not have the series.** TMDB's title, when a TMDB key is set and the episode can be matched safely:
   - for a series Sonarr has, TMDB's episode with the same number must have aired on the same day (one day either side) as Sonarr's;
   - for a series Sonarr does not have, it must be linked to a TMDB show first, and the season here must not have more episodes than TMDB's.

   A number in place of a title ("Episode 5", from TMDB or Sonarr) is not a title and is never used. A title taken from TMDB is marked "from TMDB"; once Sonarr has a title of its own, Explore offers to rename to Sonarr's. One TMDB title is never replaced by another.

Titles are written the way Sonarr writes them (its "clean title" rules and its colon and illegal-character settings): `Who's There? Part 1: The End` becomes `Whos There Part 1 The End`. Those rules were checked against every file Sonarr held on 2026-10-23 — all of them came out the same.

### What a rename does

- Renames the video, and every file beside it whose name starts with the video's name — `Example Show - S01E05 - TBA [WEBDL-1080p][GRP].nfo`, `….en.srt`, `…-thumb.jpg` — to the same new name. Another video is never one of them.
- Stays in the season folder, and never overwrites: a name already taken, or two files that would get one name, are left alone with the reason.
- Leaves out a double episode (`S01E01E02`) unless Sonarr itself names it, and a name that does not follow the naming format.
- Waits while a transfer is writing into the same series.
- Leaves out files stranded in a nested folder — Repair moves them into place first.
- Asks Sonarr to rename the copies it holds (its `RenameFiles` command). Sonarr then sends its usual rename webhook, which finds the files here already renamed and records that.
- Under `TEST_MODE`, rehearses: the same review and the same report, and nothing on disk or in Sonarr changes.

**Undo**, from the run in the Renames tab, puts the old names back (with the subtitles and info files). Sonarr's copies keep their new names — Sonarr would only rename them to the same title again. Undo works for Sonarr's webhook runs too, except files the webhook found already renamed: it changed nothing there, so there is nothing to put back. A file that cannot be put back (its old name is taken) keeps Undo available; the rest are remembered, so Undo again finishes the job once that is fixed. Undoing a switch from a TMDB title to Sonarr's brings the TMDB title back, so Sonarr's is offered again.

### Asking Sonarr and TMDB

Nothing is asked on a page view. The tags come from file names; the strip and the new names under each episode come from the last **title check**, which is stored.

- The title check reads one episode list from Sonarr per series with a TBA episode (about 25 today), and TMDB's season lists where Sonarr has no title. It runs when someone presses **Check titles** or **Refresh titles**, and after every rename. A scheduled check is off by default; **Scheduled title check** under Renames on Sonarr's Connection tab switches it on (every 6 hours unless **Check every (hours)** says otherwise).
- When the scheduled check finds titles it has not announced before, it opens a **Titles ready** alert in Notifications and sends one Discord message. It never renames by itself.
- **Refresh titles** asks Sonarr to fetch fresh titles for the series (its `RefreshSeries` command), then checks again once Sonarr is done.
- A review or a rename reads three more things for the one series: the files Sonarr holds, its rename preview and its naming settings.
- Requests to Sonarr are spaced half a second apart; TMDB answers are kept for an hour.

`RenameFiles` and `RefreshSeries` are the only things DragonCP ever asks Sonarr to do. Every other write to Sonarr or Radarr is still refused in code, and in test mode neither is sent.

### The TMDB key

An optional field on **Sonarr's Connection tab**, not a connector of its own: renaming is a Sonarr feature, and TMDB only fills the titles Sonarr does not have. Paste TMDB's **API Read Access Token** (themoviedb.org → Settings → API); it is sent in a header and never appears in a logged address. Without it everything Sonarr has a title for still renames. **Test connection** reports Sonarr and the TMDB key on separate lines. While Sonarr is switched off, TMDB lookups stop too.

### Films

None needed: no film on this disk carried a placeholder when this was built. A Radarr rename notification is acknowledged and ignored — before, it was read as a new download and synced the film again.

## Replaying Sonarr's renames

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

`_execute_renames()` walks the file records. When the old name is not here and the new name is not either, the file is looked for **by its episode** (`_find_by_episode`): the one media file in the target season folder holding the same `SxxEyy` code(s). That covers a file renamed here already under another title (named from TMDB, for instance) and one synced under a different name. Two candidates for one episode find nothing — that is a choice for a person. Then one of five outcomes:

- **Source exists, target does not** — creates the target directory if needed (`os.makedirs`), then `os.rename()`, then moves the subtitles, `.nfo` and artwork that share the video's name (`sidecars` on the record). Status `success`, message `Renamed successfully`; `matched_by_episode` is set when the source was found by its episode.
- **Source missing, target exists** — treated as already done. Status `success`, message `File already renamed (exists at new path)`, `changed: false` so Undo leaves it alone. This is what makes a redelivered webhook harmless, and what a rename started in Explore leaves for the webhook Sonarr sends afterwards.
- **Nothing for the episode here** — status `not_here`, message `Not on this disk`. Sonarr renames every file it holds, synced here or not, so this is not a failure and is not counted as one.
- **Source exists and target also exists** — status `failed`, message `Target file already exists`. The service refuses to overwrite; deciding which of two real files wins is not something it will guess.
- **Test mode** — status `success`, message `Renamed successfully (dry run)`, `dry_run` set, nothing moved.

Every branch also appends a one-line human-readable entry to an operation log. `PathTraversalError`, `PermissionError`, `OSError` and any other exception are caught per file, so one bad file cannot stop the rest.

### 5. Recording the result

Counts are tallied into an overall status: `completed` (no failures — including a run where nothing was on this disk), `failed` (no successes), or `partial`. `not_here` files are counted separately (`not_here_count`) and are neither. The row is updated with the per-file records, the counts, the status, `completed_at`, and the joined operation log. Note that the log goes into `error_message` — that column holds all log lines, successes included, not just errors.

Before the row is written, files the run really renamed retire any title taken from TMDB for their episode (kept on the file as `tmdb_before`, so Undo can bring it back). Once the run is stored, that series' title check runs again in the background and sends `titles_checked`, so Explore's tags and strip follow Sonarr's rename.

If that update returns false, the service returns failure with `persistence_error: true` and a message saying the rename happened on disk but history could not be updated. It returns **before** emitting `rename_completed` and before the Discord notification, so a persistence failure is loud rather than silently successful.

On the normal path it emits `rename_completed` over the socket, calls `NotificationService.send_rename_discord_notification()` (teal embed for completed, orange for partial, red for failed; first five filenames listed), and returns `(status != 'failed', result)`.

### 6. Verification, later and on demand

Verification is a separate manual action — `POST /api/webhook/rename/notifications/<id>/verify` — and it never renames anything. `verify_rename_notification()` loads the stored notification and picks its file list via `_extract_verification_files()`: persisted per-file results first, and if those are empty, it re-parses `raw_webhook_data` so a run whose results never persisted can still be checked.

For each file, `_verify_local_rename()` resolves the expected local path (reusing `local_new_path` if stored, otherwise re-deriving it from the relative path) and checks the filesystem:

Files recorded as `not_here` are left out: there is nothing of them to verify.

- new path exists → `verified`, with `actual_path` set
- new path missing but previous path exists → `failed`, message `File still exists at the previous path`, `actual_path` pointing at the old file
- neither exists → `failed`, message `Expected renamed file was not found locally`
- path rejected during mapping → `failed`, message `Path traversal rejected: ...`

Those three failure shapes matter more than the pass/fail count, and the UI leans on them: `rename-verify-report.tsx` classifies a result with an `actual_path` as "Old name" (re-sync the season), no path as "Missing", and a traversal message as "Blocked". The response status is `verified`, `partial` or `failed` by the same all/none/some rule used for the rename itself. Verification results are returned to the caller only — they are not written back to the database.

## Behaviour worth knowing

- **Renames never enter the transfer queue.** No rsync, no SSH, no slot or path locking (`../queue/README.md` does not apply here). The trade-off is that a rename run holds the webhook request open for its whole duration.
- **Films are not replayed.** The `/api/webhook/movies` receiver answers a Radarr `Rename` event with success and does nothing else (since 2026-10-23; before, it was parsed as an ordinary movie notification and synced the film again). Rename replay covers TV shows and anime only.
- **A renamed series folder still breaks the mapping.** Both the previous and the new local path are built from the series folder name in the *current* payload, and the episode match looks in that folder too. If Sonarr renamed the series folder itself, or the local folder name differs from Sonarr's for any reason, every file reports `Not on this disk`.
- **Files moved between season folders leave the old folder behind.** The target directory is created when missing, but the source directory is never cleaned up.
- **"Not on this disk" is not an error.** It is the expected result for seasons that were never synced to this machine. A run where nothing was here is `completed` and the receiver answers HTTP 200. (Before 2026-10-23 such files were `failed` with `File not found locally`, and a run of only those answered Sonarr with HTTP 400.)
- **Replays are safe.** A second delivery of the same payload finds the files already at their new names and reports success. The notification ID embeds a millisecond timestamp, so the replay creates a *new* history row rather than updating the old one.
- **A persistence failure leaves a misleading row.** The disk rename has happened, but the row stays `pending` with zero counts and no `completed_at`, no `rename_completed` event fires, and no Discord message is sent. The caller gets `persistence_error: true` and HTTP 400. Verification still works on such a row because it falls back to the stored raw webhook JSON.
- **`error_message` is a log, not just errors.** Reading it as an error field will mislead: successful runs populate it too.
- **The work still happens inside the request.** Renaming local files takes milliseconds, so the receiver answers when the run is done rather than handing it to a background thread.
- **Rename history is never pruned automatically.** `RenameNotification.cleanup_old_notifications()` exists but no caller invokes it anywhere in the codebase; rows accumulate until deleted through the UI or the delete endpoint.
- **Empty rename payloads verify as a failure.** A notification with no files at all returns status `failed` with `No renamed files are available for verification` and HTTP 400, not an empty success.
- **Path traversal is rejected per file, not per run.** A crafted relative path fails only its own file and is logged with a `SECURITY:` prefix; the remaining files still process.
- **If the service is not wired up, the endpoints answer 500.** `routes/webhooks.py` guards every rename entry point with a `rename_service` null check. In practice `app.py` always constructs it at startup.
- Not verified: whether Sonarr retries a rename webhook after a 400 response, and how it behaves on the request timeout of a very large rename batch.

## Data

Rename history is the `rename_webhook` table, for both kinds of run; renames from Explore also use `title_check`, `title_link` and `episode_title`. Full column lists in `../../reference/database-schema.md`.

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
| `trigger_kind`, `triggered_by` | Who started it: `webhook` (or NULL, rows from before), `manual` (Explore, with the admin's name) |
| `undone_at` | Set once Undo has put the old names back |
| `sonarr_message` | For a run from Explore, whether Sonarr took the request to rename its copies |

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

- `POST /api/webhook/rename/notifications/{id}/undo` — put the old names back

Renames from Explore (session auth): `GET`/`POST /api/explore/rename/{media_type}/{folder}` (review / rename), `POST /api/explore/titles/refresh/{media_type}/{folder}`, `GET /api/explore/titles/{media_type}` and `…/{folder}` (the last check), `POST /api/explore/titles/check`, `GET /api/explore/title-jobs` (polled while a check or Rename all runs), `GET`/`POST /api/explore/rename-all/{media_type}`, `GET /api/explore/tmdb/search/{media_type}/{folder}`, `POST`/`DELETE /api/explore/tmdb/link/{media_type}/{folder}`. Contracts in `../../reference/api.md`, section 12.

Socket events: `rename_webhook_received` (before work starts), `rename_completed` (after a successfully persisted run, from the webhook or Explore), `titles_checked` (a title check finished), `rename_progress` and `rename_library_finished` (Rename all ready).

## Related

- [Auto-sync](../auto-sync/README.md) — what happens to the non-rename Sonarr events on the same receivers
- [Queue](../queue/README.md) — the transfer machinery renames deliberately bypass
- [Simulation](../simulation/README.md)
- [System overview](../../architecture/system-overview.md)
- [API reference](../../reference/api.md)
- [Database schema](../../reference/database-schema.md)
- [Explore](../explore/README.md) — where renames are started, beside Repair
- [Integrations](../integrations/README.md) — Sonarr's connection, where the TMDB key and the check schedule live
- [../../reference/test-mode.md](../../reference/test-mode.md) — renames are skipped under `TEST_MODE`, reported as a dry run; Sonarr is not asked
