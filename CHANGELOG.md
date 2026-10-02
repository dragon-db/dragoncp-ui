# Changelog

What changed in each release, in terms of what an operator would notice.

The version lives in [`VERSION`](VERSION), which is the file you edit; package
metadata is synchronized to it rather than read from it. How to choose the next
number, and when to bump it, is in
[`docs/reference/versioning.md`](docs/reference/versioning.md).

Newest first.

---

## 2.3.0

The release that made DragonCP extensible: outside services are now
**connectors**, each with its own page under a new Integrations section in the
sidebar.

### Integrations

- **New Integrations section** in the sidebar, with one page per connector.
  Discord, Sonarr, Radarr and Jellyfin are there today; adding another is a
  single file on the server, and it appears in this menu on its own.
- **Discord now supports several webhooks**, each with a name you choose. One is
  the default.
- **Every notification can be pointed at a specific webhook.** A new
  Notifications tab lists all five announcements DragonCP makes — sync finished,
  sync failed, rename finished, old backups deleted, automatic sync refused —
  each with a destination and an on/off switch. Anything left on "use default"
  goes where the default webhook points, so a notification added in a future
  version arrives instead of shipping silent.
- **A new Activity tab shows the last hundred messages** and what happened to
  each: delivered, failed with the reason, or held back and why. Answering "why
  didn't I get told about that" previously meant reading the server console.
- **Each webhook has its own Test button**, so a test proves *that* webhook
  rather than whichever one happened to be saved.
- **Sonarr, Radarr and Jellyfin can be connected and tested.** Nothing reads
  them yet; using them to decide when a sync should start comes next.
- **Your existing Discord setup is carried over automatically.** The webhook you
  had becomes a destination called "Default", nothing is re-routed, and messages
  keep going exactly where they went before.

### Fixed

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
