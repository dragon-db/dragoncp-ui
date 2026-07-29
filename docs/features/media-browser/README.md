# Media Browsing

Media browsing is the part of DragonCP that lets you walk your remote library
from the web UI: pick a library (Movies, TV Shows, Anime), see the folders on
the remote server with a badge saying whether that title looks synced, drill
into seasons and episode files, and start a transfer or a dry-run for whatever
you selected. Everything you see here is read live from the remote server over
SSH each time you open or refresh a screen - nothing about the remote library is
cached in the database. The sync badge is the one piece of local knowledge: it
comes from comparing the newest file on the remote against the last completed
transfer DragonCP recorded for that folder or season.

Last updated: 2026-07-28

## Where it lives

| Concern | File |
| --- | --- |
| Browse/sync-status/dry-run endpoints | `routes/media.py` |
| SSH connection, remote listings, host-key policy | `ssh.py` |
| Host-key policy on the rsync side | `services/transfer_service.py` (`_build_ssh_host_key_options`) |
| Sync status derivation | `models/transfer.py` (`get_sync_status`, `get_folder_sync_status_summary`) |
| Starting a manual transfer | `routes/transfers.py` (`api_transfer`) |
| Queue admission for that transfer | `services/transfer_coordinator.py`, `services/queue_manager.py` |
| Destination path construction (webhook/auto-sync paths) | `services/path_service.py` |
| Path-component and boundary validation | `security.py` |
| Connect / disconnect / auto-connect | `app.py` (`api_connect`, `api_disconnect`, `api_auto_connect`) |
| Connection state the UI polls | `routes/debug.py` (`/api/runtime/status`) |
| Browser UI | `frontend/src/components/pages/media-browser.tsx`, `frontend/src/hooks/useMedia.ts` |

## How it works

### The browse session

Browsing uses one long-lived paramiko connection held in the `ssh_manager`
module global in `app.py`. It is created by `api_connect` (credentials posted
from Settings) or `api_auto_connect` (credentials from config: `REMOTE_IP`,
`REMOTE_USER`, `REMOTE_PASSWORD`, `SSH_KEY_PATH`). Both construct `SSHManager`
with `host_key_policy=config.get("SSH_HOST_KEY_CHECKING", "accept-new")` and
`known_hosts_file=config.get("SSH_KNOWN_HOSTS_FILE", "")`, then call
`init_media_routes(...)` again so the media blueprint's module-level
`ssh_manager` points at the new connection. `api_disconnect` closes it and sets
the global back to `None`.

Every browse endpoint in `routes/media.py` starts with
`if not ssh_manager or not ssh_manager.connected` and returns
`{"status": "error", "message": "Not connected to server"}`. The React page
does not rely on that: `MediaBrowserPage` reads `runtime_status.ssh_connected`
from `/api/runtime/status`, only enables its queries when that is true, and
otherwise shows the "Remote browse session required" card. It also attempts one
automatic `/api/auto-connect` per mount if saved SSH host and username exist.

### Host-key policy

`ssh.py` owns the policy for both browsing and rsync.
`normalize_host_key_policy()` maps the configured `SSH_HOST_KEY_CHECKING` value
onto one of three canonical strings, accepting several spellings
(`yes` -> `strict`; `acceptnew`/`tofu` -> `accept-new`;
`off`/`none`/`false`/`disable`/`disabled` -> `no`). An unrecognised value logs a
warning and falls back to `accept-new`.

`resolve_known_hosts_file()` returns `SSH_KNOWN_HOSTS_FILE` if set, otherwise
`<app dir>/dragoncp_known_hosts`. The app deliberately manages its own
known_hosts file instead of the invoking user's `~/.ssh/known_hosts`, and
`_apply_host_key_policy()` loads only that file. The reason is written in the
code: `services/transfer_service.py` passes the same file to rsync's ssh via
`UserKnownHostsFile`, so trusting an extra source during browsing would let a
host be accepted for browsing that rsync then rejects.

- `strict` - `paramiko.RejectPolicy`; unknown host fails the connect.
- `accept-new` (default) - `paramiko.AutoAddPolicy` on top of the loaded
  known_hosts, so a first-seen key is recorded and a *changed* key still raises
  `BadHostKeyException`.
- `no` - skips loading known_hosts entirely, logs a warning naming the host, and
  accepts any key.

`SSHManager.connect()` catches `BadHostKeyException` and the strict-mode
`SSHException` separately so the server log explains what happened and names the
known_hosts file to fix. Both still return `False`.

### Listing media types, folders, seasons, episodes

`GET /api/media-types` is static: three hardcoded entries whose `path` values
come from `MOVIE_PATH`, `TVSHOW_PATH` and `ANIME_PATH`. It touches no SSH.

Every other listing endpoint maps `media_type` through the same three-key
`path_map` dictionary, so an unknown media type is rejected before any path is
built. Folder and season names arriving in the URL or POST body are checked with
`security.validate_path_component()` first - it rejects empty strings, `.`,
`..`, anything containing `..`, `/`, `\` or a null byte - and only then are they
appended to the configured base path.

- `GET /api/folders/<media_type>` -> `SSHManager.list_folders_with_metadata(path)`
- `GET /api/seasons/<media_type>/<folder_name>` -> the same helper on
  `base/folder`
- `GET /api/episodes/<media_type>/<folder_name>/<season_name>` ->
  `SSHManager.list_files(path)`, names only

All remote commands are shell strings run through `exec_command()`, so every
interpolated path goes through `SSHManager._quote_remote_path()`, which is
`shlex.quote()`. That is what makes media names containing quotes, `$`,
backticks or semicolons safe.

### How modification times are read

`list_folders_with_metadata()` runs a `find -mindepth 1 -maxdepth 1 -type d`
over the parent, and for each directory runs
`find "$dir" -type f -printf "%T@\n" | sort -nr | head -1` - the newest
modification time of any file anywhere beneath that folder. If the folder
contains no files at all it falls back to `stat -c %Y "$dir"`, the folder's own
mtime. The deliberate choice here is recursion: a folder's own mtime only moves
when entries are added or removed at the top level, so the newest contained file
is a far better answer to "when did this title last change". Output is one
`name|timestamp` line per folder, parsed as `int(float(...))`, with a fallback of
`0` if a line will not parse.

`list_files_with_metadata()` and `get_folder_file_summary()` are the file-level
equivalents, using `stat -c %Y` and `stat -c %s`; only the `/enhanced` endpoint
uses them.

### How sync status is derived

`TransferModel.get_sync_status(media_type, folder_name, season_name, remote_modification_time)`
looks up the most recent **completed** transfer for that exact folder (and for
TV/anime, that exact season):

```
SELECT end_time, updated_at FROM transfers
WHERE media_type = ? AND folder_name = ? AND status = 'completed'
AND season_name IS NULL           -- movies only
ORDER BY end_time DESC LIMIT 1
```

For TV shows and anime the query adds `season_name = ?`; calling it for a series
without a season name returns `NO_INFO` immediately. From there:

- no matching row -> `NO_INFO`
- row with a null `end_time` -> `NO_INFO`
- `end_time` parsed and `remote_modification_time > 0`:
  `end_time >= remote_modification_time` -> `SYNCED`, otherwise `OUT_OF_SYNC`
- `remote_modification_time` is `0` -> `SYNCED` (a completion record exists, so
  it is treated as good)
- `end_time` unparseable -> `SYNCED`
- any exception -> `NO_INFO`

`get_folder_sync_status_summary()` handles the series case. It calls
`get_sync_status` once per season with that season's modification time, collects
`{name, status, modification_time}` for each, and sets the folder-level
`status` to the status of the season with the highest modification time. With no
season metadata it returns `NO_INFO`.

`GET /api/sync-status/<media_type>` puts these together: list folders with
metadata, then for movies call `get_sync_status` directly with the folder's
recursive newest-file time, and for TV/anime list that folder's seasons over SSH
and call the summary. `GET /api/sync-status/<media_type>/<folder_name>` returns
the same summary for one folder plus a `seasons_sync_status` map keyed by season
name - that map is what draws the per-season badges.

`GET /api/sync-status/<media_type>/<folder_name>/enhanced` is a richer variant
that adds file counts, total sizes and a sample of file metadata (first 10 files
for a movie, first 5 per season), and for movies derives status from
`get_folder_file_summary()`'s `latest_modification` rather than the folder
listing.

### Starting a transfer from a browsed folder

Selecting a folder (movies) or a season (TV/anime) opens the options screen.
"Sync Entire Folder" posts `POST /api/transfer` with
`{type: "folder", media_type, folder_name, season_name?}`; the episode list
posts the same shape with `type: "file"` and `episode_name`.

`routes/transfers.py::api_transfer` then:

1. validates `folder_name`, `season_name` and `episode_name` with
   `validate_path_component()`;
2. builds `source_path` as `<SOURCE_BASE>/<folder>[/<season>]` and `dest_path`
   as `<DEST_BASE>/<folder>[/<season>]` from the config maps, failing if either
   base is unconfigured;
3. for `type=file`, requires `episode_name` and appends it to **both** paths;
4. calls `assert_path_within_bounds(dest_path, [base_dest])`, which resolves
   symlinks with `realpath` - component validation already blocks literal `..`,
   so this exists to catch a symlink pointing out of the destination tree;
5. generates `transfer_id = f"transfer_{int(time.time())}"`;
6. hands off to `TransferCoordinator.start_transfer()`, which applies the path
   lock and concurrency cap described in [../queue/README.md](../queue/README.md).

The response carries `transfer_state`, and the message is "Transfer started" or
"Transfer queued" depending on it.

"Dry-Run" on the same screen posts `POST /api/media/dry-run`, which repeats the
same path construction in `routes/media.py::api_media_dry_run` and calls
`TransferService.perform_dry_run_rsync()`. It reports what a real sync would
add and delete without writing anything.

## Behaviour worth knowing

**`PARTIAL_SYNC` is never produced by the backend.** The value exists in
`frontend/src/lib/api-types.ts` and has a badge and a sort priority in
`media-browser.tsx`, but no Python code returns it. A grep across the repo finds
it only in those two frontend files.

**A series folder's badge reflects one season only.** The folder-level status is
the status of the *most recently modified* season. A show whose latest season is
fully synced reads `SYNCED` even if several older seasons were never
transferred. There is no aggregation across seasons.

**Sync status is a timestamp comparison, not a file comparison.** Nothing checks
that the destination actually holds the files. A completed transfer row whose
`end_time` is at or after the remote's newest file mtime is enough for `SYNCED`.
Use the dry-run for an answer grounded in actual file contents.

**Missing remote timestamps read as synced.** If the remote timestamp could not
be determined (`0`), or `end_time` cannot be parsed, `get_sync_status` returns
`SYNCED` whenever any completed transfer exists. That includes the fallback path
in `routes/media.py`, where an exception during metadata listing produces
`modification_time: 0` for every folder.

**Clock skew moves badges.** `end_time` is written as
`datetime.now().isoformat()` on the app host, while the remote modification time
comes from the media server's own clock. If the two hosts disagree by more than
the gap between a transfer finishing and the remote file being written, statuses
flip in one direction or the other.

**Renaming a folder on the remote resets its history.** Transfers are matched by
the literal `folder_name` and `season_name` strings, so a renamed show or a
re-lettered season folder falls back to `NO_INFO` until it is synced again.

**A dead SSH session looks like an empty library.** `ssh_manager.connected` is
set once at connect time and never re-checked. `execute_command()` swallows
exceptions and returns exit code `1`, and every listing helper returns `[]` for a
non-zero exit. The UI then renders "No folders found" rather than an error.
Note also that `list_folders_with_metadata()` returns `[]` instead of raising on
a failed command, so the `except` fallback to `list_folders()` in
`routes/media.py` only fires for genuine exceptions.

**Most browse errors return HTTP 200.** "Not connected to server", "Invalid
media type" and the sync-status failure paths return
`{"status": "error", ...}` with the default 200 status. Only the
`validate_path_component` rejections and the dry-run's own validation return
400/500.

**One SSH connection is shared by everyone.** `ssh_manager` is a module global,
not per browser session. Whoever connects, connects for all logged-in browsers;
whoever disconnects, disconnects them too. `session['ssh_connected']` is set per
session but `/api/runtime/status` reports the global connection's state.

**The remote must be GNU-flavoured.** The listing commands use `find -printf`
and `stat -c`, which are GNU extensions. Against a BSD or macOS remote the
commands fail and every listing comes back empty.

**Listing order is not what the UI shows.** `list_folders()` and `list_files()`
sort by `(len(name), name)` - shortest name first, which is not alphabetical and
not episode order. `list_folders_with_metadata()` does not sort at all and
returns whatever order `find` produced. The React page re-sorts folders itself
(recently modified or alphabetical) and sorts seasons by sync status then name,
but the episode list is rendered in the order the API returned it.

**Sync status is one remote command per folder for series libraries.**
`GET /api/sync-status/<media_type>` runs a listing for the library plus one more
for every show or anime folder to enumerate its seasons. On a large library that
is slow, which is why folder listing and sync-status refresh are separate buttons
in the UI.

**Episodes carry no metadata.** `/api/episodes/...` returns bare filenames -
no size, no modification time, no per-episode sync status - and the endpoint has
no try/except, so any failure shows as an empty list.

**A single-episode transfer does not conflict with its season.** The destination
path for `type=file` includes the episode filename, and
`QueueManager._normalize_path` compares exact paths, so the queue does not see
it as a conflict with a running transfer targeting the parent season folder.

**Dry-run does not need the browse session.** `POST /api/media/dry-run` never
checks `ssh_manager`; it shells out to rsync, which opens its own ssh connection
using `_build_ssh_host_key_options()`. In practice you reach the button by
browsing, but the endpoint itself works without a paramiko connection.

**`PathService` is not on this path.** `routes/media.py` and
`routes/transfers.py` build destination paths by string concatenation and then
bounds-check them; `services/path_service.py` is used by the webhook, auto-sync
and rename services. For the shapes produced here (`base/folder[/season]`) the
two agree, but a change to one does not change the other.

**Source and destination bases are session-overridable.** `DragonCPConfig.get()`
consults the current Flask session's `ui_config` before the env file, so
`MOVIE_PATH` and friends - and therefore which remote tree you are browsing -
can differ per browser session.

**Two buttons do the same thing.** On the options screen for a season, "Manual
Episode Sync" and "Download Single Episode" both just switch the view to the
episode list.

**A rsync known_hosts path containing spaces will break.**
`_build_ssh_host_key_options()` notes that the path is embedded in rsync's single
`-e` string, which rsync splits on spaces. The default app-directory path is
safe; a custom `SSH_KNOWN_HOSTS_FILE` with a space in it is not.

Not verified: whether `find ... -exec sh -c '...' _ {} +` ever splits into more
than one shell invocation on a real library. If it does, `get_folder_file_summary()`
would receive several `count|size|time` lines while its parser only splits the
whole output once on `|`, and the `int()` conversion would fail and yield the
zeroed summary. This only affects the `/enhanced` endpoint.

Not verified: whether any client still calls
`GET /api/sync-status/<media_type>/<folder_name>/enhanced`. It has no caller in
`frontend/src`.

## Data

Browsing itself writes nothing. It reads the `transfers` table through
`TransferModel.get_sync_status()`:

| Table | Columns read | Used for |
| --- | --- | --- |
| `transfers` | `media_type`, `folder_name`, `season_name`, `status` | selecting the matching completed transfer |
| `transfers` | `end_time` | the timestamp compared against the remote modification time |
| `transfers` | `updated_at` | selected by the query but not used |

Starting a transfer from the browser creates a row in `transfers` via
`TransferCoordinator.start_transfer()`; the columns it fills are covered in
[../queue/README.md](../queue/README.md).

Full schema: [../../reference/database-schema.md](../../reference/database-schema.md)

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/media-types` | the three libraries and their configured source paths |
| GET | `/api/folders/<media_type>` | remote folders with modification times |
| GET | `/api/seasons/<media_type>/<folder_name>` | season folders with modification times |
| GET | `/api/episodes/<media_type>/<folder_name>/<season_name>` | episode filenames |
| GET | `/api/sync-status/<media_type>` | status for every folder in a library |
| GET | `/api/sync-status/<media_type>/<folder_name>` | folder summary plus per-season statuses |
| GET | `/api/sync-status/<media_type>/<folder_name>/enhanced` | as above plus file counts, sizes and samples |
| POST | `/api/media/dry-run` | rsync dry-run for a browsed folder or season |
| POST | `/api/transfer` | start the transfer for a browsed folder, season or episode |

Supporting endpoints used by the same screen: `POST /api/connect`,
`GET /api/auto-connect`, `POST /api/disconnect`, `GET /api/ssh-config`,
`GET /api/runtime/status`.

All routes require authentication (`@require_auth`) and are registered under the
`/api` prefix in `app.py`.

Full contracts: [../../reference/api.md](../../reference/api.md). Note that the
canonical sync-status list there is `SYNCED`, `OUT_OF_SYNC`, `NO_INFO`, which
matches the backend.

## The screen

`frontend/src/components/pages/media-browser.tsx` renders one page per library;
the sidebar link decides which of `movies`, `tvshows` and `anime` it is opened
with. The header carries the title of whatever you have selected, a "Refresh
Folders" button and a "Refresh Sync Status" button. Both are disabled until the
browse session is connected, and each spins while its own request is in flight.
Refreshing sync status also re-requests the per-season statuses when you have a
folder open.

If there is no browse session the page shows the amber "Remote browse session
required" card instead of a folder list, with a "Connect Browse Session" button
when SSH host and username are already saved and an "Open Settings" link either
way.

### Finding a folder

The folder list has a "Search folders" box and a sort dropdown, both of which
only affect the folder level - seasons and episodes have neither.

Search is a plain case-insensitive substring match on the folder name. The card
subtitle counts what you are looking at: `120 folders` normally, `7 of 120
folders` while a search is narrowing it.

The sort dropdown offers two orders:

- **Recently Modified** - the default. Folders are ordered by the modification
  time the listing returned, newest first. Because that time is the newest file
  anywhere under the folder (see "How modification times are read"), this puts
  the titles that changed on the server most recently at the top.
- **Alphabetical** - `localeCompare` on the folder name.

Switching library resets the view to the folder list and clears the search box,
the selection and the sort back to Recently Modified.

Each folder row shows the name, a relative date under it ("Today",
"Yesterday", "4 days ago", "3 weeks ago", or a plain date once it is older than
30 days; blank when no timestamp came back) and the sync badge on the right -
"Synced", "Out of Sync", "Not checked" for `NO_INFO`, and "Partial" for the
`PARTIAL_SYNC` value the backend never sends. While a sync-status refresh is
running, every badge on screen reads "Loading" regardless of its real value.

### Drilling down

The path is library -> folder -> season -> options -> episodes, with movies
skipping the season step: selecting a movie folder goes straight to the options
screen. A breadcrumb appears above the card as soon as you leave the folder
list, and each earlier crumb is clickable to go back to that level. The season
card also has its own "Back" button and the episode card a "Back to Options"
button.

Seasons are not sorted by name first. They are ordered by sync status - out of
sync, then not checked, then synced - and only then alphabetically, so the
season that needs attention is at the top. Episodes are rendered in whatever
order the API returned them.

### Transfer options

The options screen shows the folder (and season) you picked and up to four
choices:

- **Sync Entire Folder** - starts the transfer for the whole folder or season.
  The toast repeats the message the API returned, which is where you find out
  whether it started or was queued.
- **Dry-Run** - runs the preview described below. It does not start anything.
- **Manual Episode Sync** and **Download Single Episode** - only shown for a
  season, and both simply open the episode list.

The episode list gives each filename a "Download" button that starts a
file-level transfer for that one episode.

Nothing on this screen requires a dry-run before a sync. The two buttons are
independent; the preview is advice, not a gate.

### The dry-run preview

"Dry-Run" opens a dialog titled "Dry-run validation", subtitled with the folder
and season you are looking at. It is rendered by
`frontend/src/components/dry-run/dry-run-report.tsx` from the parser in
`frontend/src/lib/dry-run.ts`, and the same dialog is used by the Webhooks page.
Closing it discards the result; switching library also clears it.

The dialog answers, top to bottom:

- **A verdict banner.** "Safe to sync" when the backend returned
  `safe_to_sync`, "Manual review required" when it did not, and "Validation
  failed" when rsync never reported at all - no raw output and no counted files.
  That third state matters: it is the difference between "nothing would change"
  and "we could not find out", and the report says so rather than showing
  zeroes.
- **Five counters** - Incoming, Deleting, Already in sync, Server files, Local
  files - and a proportional bar splitting the folder into unchanged, incoming
  and deleted.
- **Safety checks**, three of them, each shown as passed or not with its own
  detail line: the server holds at least as many files as the local copy;
  deletions do not outnumber incoming files; rsync produced no error lines.
- **rsync errors or warnings**, when the output contained any, up to eight.
- **The file list.** One row per path with a New / Update / In sync / Delete
  label, the episode marker when the filename carries one, the release tags in
  brackets and the extension. Filter buttons (All, Incoming, In sync, Deleting)
  carry their own counts, a box filters by path text, and the list pages in
  blocks of 60 behind a "Show N more" button.
- **Collapsible detail** - the full rsync statistics table with the source it
  connected to, the raw rsync output, and the JSON payload, the last two with
  copy buttons.

This is the safety step because it is the only view on this page grounded in
actual files. The folder badge is a timestamp comparison and will read "Synced"
in several situations where the destination does not hold the files (see
"Behaviour worth knowing"). The dry run asks rsync what it would really do -
and, because a real sync runs with `--delete`, the "Deleting" list is the only
place you see which local files would be removed before they are removed.

## Related

- [../queue/README.md](../queue/README.md) - what happens after a transfer is started
- [../auto-sync/README.md](../auto-sync/README.md) - the automatic counterpart to manual browsing
- [../simulation/README.md](../simulation/README.md) - synthetic transfers for testing
- [../../architecture/system-overview.md](../../architecture/system-overview.md)
- [../../reference/path-handling.md](../../reference/path-handling.md)
- [../../reference/api.md](../../reference/api.md)
- [../../reference/database-schema.md](../../reference/database-schema.md)
