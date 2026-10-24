# Changelog

What changed in each release, in terms of what an operator would notice.

The version lives in [`VERSION`](VERSION), which is the file you edit; package
metadata is synchronized to it rather than read from it. How to choose the next
number, and when to bump it, is in
[`docs/reference/versioning.md`](docs/reference/versioning.md).

Newest first.

---

## 2.4.0

Renames, rebuilt: DragonCP now works out each file's real name itself and
renames it here, instead of only repeating what Sonarr renamed.

### Renames

- **A TBA tag in Explore.** Every series and season with an episode Sonarr
  named TBA gets a tag, and a **Needs titles** filter lists only those. It is
  read from file names Explore already lists, so it costs nothing.
- **Rename from Explore.** A strip above the episode list says how many
  episodes can get their real titles now and how many still wait, with
  **Rename** and **Refresh titles**. **Rename** opens a review of every file,
  old name → new name, with the subtitles, `.nfo` and artwork that move along,
  and what is left alone and why. Nothing changes until you confirm, and if
  anything changed in between the rename is refused and you review again.
- **Rename all ready** does the same for every ready episode in a library, one
  series at a time, with progress and one Discord message at the end.
- **Sonarr renames its own copy too** when it still holds the file, so both
  ends carry the same name and Explore sees them in sync. This is the only
  write DragonCP makes to Sonarr besides asking it to refresh a series;
  nothing is sent in test mode.
- **Real titles for what Sonarr lacks.** With a TMDB token on Sonarr's
  **Connection** tab, TMDB fills the titles of episodes Sonarr still calls
  TBA or TBD, only when the episode matches safely (same number, same air
  day). A series Sonarr does not have can be linked to a TMDB show once, with
  **Find titles on TMDB**. Titles taken from TMDB are marked, and Explore
  offers Sonarr's title once it has one. Without a token everything Sonarr has
  a title for still renames.
- **Titles are written the way Sonarr writes them** (its cleaning rules and
  colon and illegal-character settings). Files are never overwritten; a name
  already taken is left alone with the reason.
- **Undo** puts the old names back, for renames from Explore and from
  Sonarr's webhook alike. Both stay in the **Renames** tab under Webhooks.
- **Title check on demand.** **Check titles** and **Refresh titles** read
  Sonarr (and TMDB where needed); page views ask nothing. The scheduled check
  is off by default and, when on, only opens a **Titles ready** alert and one
  Discord message — it never renames by itself.

### Webhooks

- **Sonarr's rename webhook finds the file by its episode.** A file already
  renamed here under another title, or synced under a different name, is
  still matched.
- **"Not on this disk" is no longer a failure.** Sonarr renames everything it
  holds, synced here or not; a run where nothing was here finishes as
  completed and Sonarr gets HTTP 200 instead of 400.
- **A Radarr Rename notification is ignored.** It used to be read as a new
  download and synced the film again.

### Settings

- **Connector settings are grouped** into clearer sections, and Explore's row
  tags share one pill shape.

### Upgrading

- The database migrates itself on start: new tables for title checks,
  TMDB links and stored titles, and a Sonarr message on rename history.
  Nothing to do by hand.
- To get titles for TBA episodes, paste a TMDB API Read Access Token on
  Sonarr's Connection tab. Optional.

## 2.3.2

Quality of life, round two: connection tests that test what you typed,
upgrades you can find, Discord pings, and Discord messages that say what was
synced and how.

### Integrations

- **Test connection tests what is in the form** (issue #63). Sonarr, Radarr
  and Jellyfin used to test only the saved settings, so a freshly typed address
  and key answered "Not configured yet". The test now uses the form's values,
  saved or not, saves nothing, and shows its answer under the fields — "not
  saved yet" when it tested unsaved values. **Unsaved changes** shows beside
  Save. Saving a new address or key tests it straight away.
- **The On/Off switch no longer wipes what you typed**, and switching a
  connector on with nothing saved says so.
- **Clicking through a saved API key no longer deletes it on Save.**
- **On a phone, a page's title and its controls share one row** — "Sonarr"
  and its On/Off switch, Webhooks' Auto-sync and Refresh, Transfers' Refresh.
  Less used actions (Remove duplicates, Retention, Rebuild index) move into a
  "⋯" menu there. Backups' "Adopt old folders" and "unidentified" now sit
  under its description.
- **Integration pages and Notifications lose the line under their title**
  ("Film library manager. Already sends notifications here…", "What needs a
  person: …"), so the content starts higher.
- The activity log gives a failed test's real reason ("Sonarr test failed:
  Not configured yet") instead of always "Could not reach Sonarr".

### Upgrades

- **An Upgrade tag** (issue #25) marks a show, season or film whose remote
  file is newer than the one here — in Explore's list and on the Sonarr and
  Radarr Library tabs, each with an **Upgrade** filter. The episode label reads
  **Upgrade** instead of "Replace" (Explore) or "Different" (Library tab); the
  Replace button keeps its name. Explore's filters wrap onto a second line on a
  narrower desktop instead of hiding **Re-check sync**.

### Settings

- **Rebuilt to match the rest of the app**, in five tabs by task: **Remote
  server** (connection, Auto-connect, login details, fast transfers),
  **Syncing** (auto-sync per library, library folders as remote → local pairs,
  backup retention), **Account**, **System** (test mode, disks) and **Logs**.
  Each topic now lives in one place.
- **New Logs tab with WebSocket diagnostics.** Tiles show at a glance how many
  browsers are getting live updates, how many are on WebSocket, and how often
  this browser had to reconnect. One card lists every session with its real
  transport (it used to say "polling" for everyone), who, how long, and a bar
  counting down to when it closes. This browser is always the first row, with
  Turn on / Keep open / Turn off and its own drops and retries since the page
  loaded. The backend log sits below.
- **Fast transfers: stopped between transfers is green now.** On demand, an
  idle server read "Installed but not running" in amber. It now reads **Ready.
  It starts for each transfer and stops when they finish.** when nothing stands
  in the way of the next start.
- Values from the environment file read as locked text instead of greyed-out
  fields; coloured icons show real states (connected, running, on, test mode).
- **One save model**: switches and choices save as you change them, numbers on
  Enter; an out-of-range number is refused with its range. No more Save
  buttons.
- The tab is in the address (`/settings?tab=logs`). Switch focus rings are
  easier to see.
- The log no longer gets a "Configuration key … not found" warning each time a
  database setting with nothing saved is read.

### Explore

- **Opening Explore brings it up to date by itself.** It shows the last result
  at once, then checks the remote server and swaps in what changed — no
  Re-check needed. A check from the last 2 minutes is reused unless Sonarr or
  Radarr imported something for that library since, so reopening the page does
  not read the remote again and again. Seasons use the same check instead of
  reading the whole remote library on every click.
- **No more trips to Settings when SSH drops.** Explore reconnects with the
  saved login when the session is missing (after a restart) or dead (reset by
  the server — what made "Re-check failed"). When it cannot, it keeps showing
  the last result, says why and how old it is, and offers **Connect** on the
  page.
- **The remote server is never hammered**: one connection attempt at a time,
  growing waits after a failure (30 s up to 5 min), and a refused login is
  never retried by itself, so the server has no reason to ban this address.
- **New: Auto-connect** (Settings → Remote server, on by default). Off: connect
  by hand. The **Auto Connect** button there is now called **Connect**.
- **A file stuck in an extra folder is never "In sync" any more.** An episode
  at `Season 04/episode.mkv/episode.mkv` — invisible to the media server —
  reads **Nested**. Its season and series read **Needs repair** instead of
  Synced, or carry a **Nested** tag beside Partial / Out of sync / Not on
  remote, in the tree and the season list; a **Nested** filter lists them, and
  opening one shows a strip with **Repair** above the list. A sync never
  downloads it again and says why, and Sonarr's **Get** for it now points to
  Repair instead of "nothing to copy".
- **Replacing or syncing away a nested file removes the empty folder it
  leaves**, so the library keeps the shape Jellyfin expects.

### Sonarr and Radarr pages

- **A file in a nested folder reads the same as in Explore.** The episode
  says **Nested** instead of "Not here", the title **Needs repair** (or an
  amber **Nested** tag beside Out of sync), and a **Nested** filter appears
  when any title has one. Opening it says "S01E38 is here, but inside a nested
  folder your media server cannot see" and offers **Repair in Explore**,
  which opens Explore on that season.
- **The pop-up's buttons lead with what fits.** One action is filled: Repair
  in Explore when a file is nested, otherwise Get, then Replace, then Copy the
  series. **Open in Explore** is now an outlined button beside them instead of
  a quiet link, and filled when it is the only way on. Its copy sentences say
  "remote server" for where files come from.
- **Copy the series and Copy the film ask first**, as Get does: what will be
  copied and roughly how big, with **Copy now** and **Cancel**. Nothing starts
  from a single press any more.

### Auto-scanner

- **New: Alert only, and it is the default.** The Sonarr and Radarr
  auto-scanner has a **When it finds something** setting. **Alert only** opens
  a *Missed auto-sync* alert in Notifications — with **Open in Explore** — and
  sends one Discord message per scan, and copies nothing, so a download you
  stopped by hand stays stopped. **Sync it** keeps the old behaviour. Alert
  only also catches syncs that were skipped or cancelled within its **Look
  back (days)** (7 by default, up to 30),
  alerts each folder once, comes back after Dismiss only on a newer import,
  and closes itself once the folder is synced.
- **Open in Explore** on the safety check's alert too.

### Discord

- **Pings** (issue #35). A new **Mentions** tab holds who a message can ping —
  a Discord role, a person, @here or @everyone — each with a Test ping. Each
  webhook can ping people by default, and each notification on the Routing tab
  chooses when it pings (never, on warnings and failures, or always) and whom.
  By default failures, refusals and anything needing a person ping; "Sync
  finished" and other reports do not. Only the chosen people can be pinged: a
  title containing "@everyone" never pings anyone.
- **New: Waiting for a manual sync.** With automatic sync off, a batch waiting
  for someone to press Sync is announced once.
- **Sync messages say what was synced and how**: one line per episode copied
  (with "upgrade to …" when it replaced an older file), the route — ⚡ FAST,
  SSH or SSH FALLBACK — and size and speed.
- **One look for every message.** The line above the title names what
  happened in one upper-case scheme — AUTO SYNC - SONARR, MANUAL SYNC -
  EXPLORE, AUTO SYNC FAILED - SCANNER, SAFETY CHECK - AUTO SYNC STOPPED — and
  every message carries the same footer, `DragonCP v2.3.2`. The safety-check
  message no longer repeats its reason and counts.

### Upgrading

- The database gains one table and four columns on first start; nothing to
  run by hand.
- Nobody is pinged until someone is added on Discord's Mentions tab.
- An auto-scanner that was switched on now alerts instead of syncing. Set
  **When it finds something** to **Sync it** on the Sonarr or Radarr
  Connection tab to keep it syncing.

---

## 2.3.1

Fast transfers work again, and can no longer fail a copy on their own.

### Fast transfers

- **Explore copies work over the fast route again.** Since the remote server
  moved to Debian 13 (2026-08-20), its rsync fails every file of an Explore
  copy over the fast route — "file has vanished", nothing copied — while the dry
  run before it passes. The cause is an rsync security fix (CVE-2026-29518)
  that changes how a server without chroot opens files. Explore now asks the
  fast route for its files from the top of the library; files land where they
  always did. Normal transfers were never affected. No rsync version needs
  changing on either machine.
- **A copy that fails on the fast route finishes over SSH by itself.** Same
  transfer, same backup and partial folders, so files already copied are kept
  and a half-copied one carries on. Not retried after a pause, a cancel or a
  shutdown. The safety check and Explore's dry run do the same, so a broken
  fast route can slow syncing down but cannot stop it.
- **A fallback is never silent.** It opens one **Fast transfers** alert,
  announced once on Discord; later fallbacks add to that alert instead of
  sending more messages. The transfer's log says why in rsync's own words.

### Transfers

- **Every transfer row shows its route** — on the dashboard's Active Transfers
  and on the Transfers page's Activity and History: green **Fast**, blue
  **SSH**, amber **SSH fallback**. Before, only the fast route was marked, so an
  unmarked row could mean SSH, not started, or an old run. Nothing is shown
  while a copy is queued (the route is chosen when it starts) or for runs from
  before routes were recorded.

### Upgrading

- The fast-transfer server was removed from the remote server on 2026-08-22.
  After deploying: Settings → Connections → Fast transfers → **Install**, then
  switch **Use it for transfers** on. See
  [`docs/operations/fast-transfers-deployment.md`](docs/operations/fast-transfers-deployment.md).
- No database migration.

---

## 2.3.0

The release that made DragonCP extensible — outside services are now
**connectors**, each with its own page under a new Integrations section in the
sidebar — and gave every sync one pipeline.

### One pipeline for every sync

- **Every sync now passes the same nine stages** — receive, identify, batch,
  ready check, safety check, queue, transfer, finish, tell — whether a webhook,
  the auto-scanner, a press of Sync, an Explore plan, a restart, a restore or a
  simulation started it. Each stage records what it decided and why, including
  why it was skipped, with its own log lines.
- **Every sync can be read stage by stage on the Transfers page.** Opening a
  transfer shows its sync as nine stage cards where the queued / started /
  completed timeline used to be; picking a card shows what that stage decided
  and why (Sonarr's answers, the safety check's counts) and its log, in plain
  words — "pressed Download in Explore", "No webhook is linked to this sync".
  Syncs that have not started copying are listed on the Activity tab under
  **Waiting to start**, with Sync now or Go now on the row; syncs that ended
  before copying — stopped by the safety check, cancelled, failed — are on the
  History tab. Any sync opens in a side panel with Go now, Sync anyway, Retry
  and Cancel where they apply, and an alert or an episode on the Webhooks page
  leads straight to it.
- **Episodes no longer sync before the season has finished downloading.** A
  Sonarr webhook now waits ten seconds, then asks Sonarr whether anything else
  for that season is still downloading, and asks again by Sonarr's own time
  estimate. A download stuck in Sonarr does not hold the season up; a slow one
  holds it for at most 30 minutes. When Sonarr cannot be asked, the old fixed
  timer takes over — Settings now calls it the **Fallback wait** and says so.
- **A burst of episode webhooks is one transfer, and one arriving mid-copy is
  one more** — queued behind the copy, never a third.
- **A restart no longer loses episodes silently.** A batch waiting to sync was
  held only in memory, so a restart dropped it and nothing said so. Batches now
  live in the database, and nothing restarts by itself: what a restart
  interrupted becomes an alert, with Sync now (which repeats exactly that sync:
  the same folder, single file or Explore list), Mark as done, Mark as wrong
  and Dismiss.
- **Restart goes through the queue and the safety check** like every other
  sync, instead of starting at once. Pressing Restart says so, and a refusal
  says why.
- **Two seasons of one series may copy at the same time; the same season never,
  and a whole-series copy waits for any season copy of that series.**
- **A new scheduled auto-scanner** catches what a lost webhook would have
  missed: on a schedule, it asks Sonarr and Radarr what they imported since the
  last scan and syncs whatever no webhook delivered. An import counts as synced
  only once a copy that started after it has finished. One switch per service on its
  integration page, off by default, where a card shows when it next scans, what
  the last scan found, and a Scan now button. It never fetches the whole
  backlog.
- **Alerts, on a new Notifications page.** Anything that needs a person — a
  sync the safety check stopped, a failed transfer, a download stuck in Sonarr,
  a restart that interrupted a sync — opens an alert with the actions that fit
  it: Sync now, Retry, Sync anyway, Mark as done and so on. The Notifications
  page lists them, open and closed. The bell in the header now leads there and
  lights up when something is waiting for you — it used to light up for every
  webhook still pending — and the sidebar shows how many. An episode or movie
  the safety check stopped reads **Manual** on the Webhooks page instead of
  Pending.

### Backups

- **In test mode, the Backups page says its deletions are real.** Test mode
  rehearses syncs, restores and repairs, but deleting a backup, the retention
  clean-up and adopting old folders act on the real backup folder — which a
  test instance set up beside production shares with it. A banner says so, and
  each of those confirmations shows a red "This WILL delete real backups"
  notice whose button stays off until its tick-box is ticked.

### Integrations

- **New Integrations section** in the sidebar, with one page per connector.
  Discord, Sonarr, Radarr and Jellyfin are there today; adding another is a
  single file on the server, and it appears in this menu on its own.
- **Discord now supports several webhooks**, each with a name you choose. One is
  the default.
- **Every notification can be pointed at a specific webhook.** A new
  Routing tab lists all ten announcements DragonCP makes — sync finished,
  sync failed, rename finished, old backups deleted, automatic sync refused,
  sync may have been skipped, synced without a stuck download, auto-scanner
  found something, Sonarr or Radarr not answering, background job failing —
  each with a destination and an on/off switch. Anything left on "use default"
  goes where the default webhook points, so a notification added in a future
  version arrives instead of shipping silent.
- **A new Activity tab shows the last hundred messages** and what happened to
  each: delivered, failed with the reason, or held back and why. Answering "why
  didn't I get told about that" previously meant reading the server console.
- **Each webhook has its own Test button**, so a test proves *that* webhook
  rather than whichever one happened to be saved.
- **Sonarr, Radarr and Jellyfin can be connected and tested.** Sonarr decides
  when a season is ready to sync, and the auto-scanner reads Sonarr and Radarr;
  Jellyfin is connected but nothing reads it yet.
- **The Sonarr and Radarr pages were rebuilt to be read at a glance.** The
  Library tab shows small posters — three across on a phone — each with one
  state (Out of sync first) and a line like "Sonarr 1 · here 7". A new episode
  on Sonarr beside older ones here reads Out of sync: the first build of the
  tab called that Synced, because every season held *some* file here. Clicking
  a title opens it in a pop-up: one sentence on what is missing and a **Get
  S01E08** button that copies just that file (through Explore, with a one-line
  check of what will move), each season's episodes as not here, different,
  here, only here or not downloaded, and a **History** tab listing what
  Sonarr did to the title beside what DragonCP did about it, with what is still
  not done marked. History reads like
  Sonarr's own — series, 1x08, episode title, quality, custom formats — with
  filters for imported, grabbed, deleted, failed and renamed; Queue says what
  each download is doing in plain words. Every integration page now has the
  same tab bar as Transfers and Webhooks, with counts.
- **Your existing Discord setup is carried over automatically.** The webhook you
  had becomes a destination called "Default", nothing is re-routed, and messages
  keep going exactly where they went before.

### Fixed

- **Test mode now covers Explore's Repair.** With test mode on, Repair reports
  what it would move, delete or replace and leaves every file where it is;
  before, it changed the library for real.
- **A dry run that could not run no longer counts as safe.** When rsync could
  not reach the media server, or the folder was missing, the safety check saw
  an empty list of changes and let the sync through. It now stops the sync and
  shows the error that caused it — a host name that could not be resolved, a
  folder that is not there.
- **The Transfers page shows who started each transfer, and the fast route.**
  The transfer lists never sent either, so every transfer said "not recorded"
  for who started it and the Fast badge never appeared.
- **A copy cut short by a restart is no longer reported as a success, or as a
  failure nobody saw.** When DragonCP restarts during a copy and cannot tell how
  rsync ended, the transfer now says "Result unknown" and an alert asks you to
  check the folder, with Retry and Mark as done.
- **A queued transfer that cannot start now says so.** When the queue started a
  waiting transfer and it failed at once (no backup folder, or rsync refusing
  to start), its episodes stayed "syncing" and nothing was announced. Its sync
  now ends failed, with "Sync failed" on Discord and an alert offering Retry.
- **Deleting a waiting transfer no longer blocks its folder.** A queued or
  paused transfer deleted from the list kept its place in the queue until the
  next restart, so later syncs to the same folder waited behind nothing. It is
  now cancelled first.
- **A movie waiting for its folder says so.** A movie webhook whose transfer
  moved from waiting for a slot to waiting for the folder kept saying it waited
  for a slot.
- **A rename notification no longer holds up Sonarr.** The Discord message was
  posted inside the HTTP request Sonarr made, so Sonarr waited up to ten seconds
  for Discord to answer. Messages are now delivered in the background.
- **A very long title, path or error no longer costs the whole message.**
  Discord rejects a message outright when any field runs past its limit, and
  nothing enforced those limits before.
- **A failed send no longer prints the webhook URL to the log.** A Discord
  webhook URL is the credential; it is now redacted everywhere it could surface.
- **A Discord destination must be a Discord address.** The server posts to
  whatever is stored, and previously that could be anywhere.
- **Rate limiting is handled.** A message refused for arriving too fast is
  retried once, after the wait Discord asks for.

### Removed

- The Discord card on the Settings → Automation tab, and the
  `/api/discord/settings` and `/api/discord/test` endpoints. The Automation tab
  links to the new page.

---

## 2.2.0

The release that put the version number back in service — it had been stuck at
2.1.4 while three hand-maintained copies of it drifted apart.

### Backups

- **Deleted backups are now accounted for.** Every deletion records the versions
  themselves — title, size, and the full path on both the library and the backup
  side — written *before* anything is removed, because afterwards there is
  nothing left to read. Previously the automatic cleanup left only a count.
- **An automatic cleanup announces itself**, over Discord and with a banner on
  the page. It is the one deletion nobody asks for, so it comes and finds you
  rather than waiting to be discovered.
- **New History tab** listing what was kept, restored and deleted, with the full
  paths of every file each entry touched, filterable down to just deletions.
- **Versions created by a sync or an Explore repair are recorded too**, so the
  trail can say where a backup came from as well as where it went.
- **Full paths across every modal and list.** The delete confirmation is the one
  that mattered: it used to show a friendly label and a size, and nothing else,
  for the only action on the page with no undo.
- **The version panel was reworked** — it leads with what the library holds now,
  labels its three actions instead of showing bare icons, and keeps its own
  selection instead of pooling it with the list behind.
- Restore states its two paths as one swap: the shared folder printed once, the
  two filenames aligned beneath it.

### Explore

- **Three views replace the compact/comfortable switch**, which only changed row
  height. *List*, *Compare* and *Quality* each answer a different question.
  Compare puts local and remote side by side — the table had been collapsing
  both sides into one value and hiding the difference the page exists to reveal.
- **Quality reads both file names** and reports resolution, source, codec, group
  and the size difference, with a line saying which way a sync would move the
  quality. This is the question the `Upgraded` label raises and never answers.
- **The sync and repair previews show whole paths** instead of a truncated
  basename behind a hover, on both ends of a move.
- **Backup counts load with the selection**, so the badge answers before the
  click rather than after it.
- Browse Media has an icon that reads at nav size.

### Fixes

- **Hashed assets are served from cache.** A contradictory `no-cache` overrode
  the one-year policy, so every asset was revalidated on every page load —
  invisible on a LAN, a round trip per asset over a tunnel.
- **The backup list has a stable order when captures tie.** A season sync writes
  several versions in the same millisecond, and the list had nothing to break
  the tie, so the same page reloaded twice could show them in a different order.
- **The delete preview no longer crashes** when the server answers without file
  detail.
- **Fixed a source-detection bug** that dropped the source tag from every
  `Anime Dual-Audio WEBDL-1080p`-shaped name.

### Under the hood

- `VERSION` at the repository root is the single source of the version number.
  `config.py`, the Vite build and `frontend/package.json` all read or match it,
  and `tests/test_version.py` fails the build if a copy reappears or drifts.
- The running server reports its version on `/api/runtime/status`, and the
  navbar shows that rather than a number baked into the bundle.
- **A tab left open across a deploy now says so** and offers a reload. Assets
  were already busted by content hash, so a reload always landed on the new
  build — the gap was the session that never reloads and keeps running old code
  against the new API.

---

## 2.1.4 and earlier

Not recorded here. This file starts at 2.2.0; earlier history is in the git log
and in the per-feature documents under [`docs/`](docs/INDEX.md).
