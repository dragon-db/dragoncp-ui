# Changelog

What changed in each release, in terms of what an operator would notice.

The version lives in [`VERSION`](VERSION), which is the file you edit; package
metadata is synchronized to it rather than read from it. How to choose the next
number, and when to bump it, is in
[`docs/reference/versioning.md`](docs/reference/versioning.md).

Newest first.

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
