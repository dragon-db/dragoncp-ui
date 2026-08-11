# Changelog

What changed in each release, in terms of what an operator would notice.

The version lives in [`VERSION`](VERSION) and nowhere else. How to choose the
next number, and when to bump it, is in
[`docs/reference/versioning.md`](docs/reference/versioning.md).

Newest first.

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

---

## 2.1.4 and earlier

Not recorded here. This file starts at 2.2.0; earlier history is in the git log
and in the per-feature documents under [`docs/`](docs/INDEX.md).
