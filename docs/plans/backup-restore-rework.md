# Backup and Restore Rework

**Status:** **built** 2026-08-01, migration not yet run. Tracked as TASK-014.
Current behaviour lives in
[`../features/backups/README.md`](../features/backups/README.md); this page is
kept for the reasoning and the measurements that drove it.

Two things changed during implementation and are recorded at the end under
*What implementation changed*.

Rebuilds how displaced media is stored, indexed and put back. The current
feature works by accident more than by design: it organises backups by the
*event* that produced them, re-implements a weaker copy of the episode parser
Explore already owns, and treats the database as authoritative over a disk it
has largely lost track of.

This replaces that with one idea — **every movie and every episode is a slot
with a version history** — and derives the storage layout, the restore flow and
the retention rule from it.

Sonarr/Radarr API integration is explicitly *not* in this scope. Backups are
independent of it, which is why this goes first.

---

## 1. Why — what the disk actually says

Measured 2026-08-01 against the live backup area and this checkout's database.

| | |
|---|---|
| Backup disk | 1.01 TB total, 0.32 TB free — **68% full** |
| Library disk | 19.9 TB total, 12.7 TB free — **a separate physical device** |
| Backup folders on disk | **864**, of which **687 hold no files at all** |
| Files on disk | 330, totalling **367 GB** |
| Files the index knows about | **19** |

Three conclusions, and they set the whole design:

**The index is a stale sample of the disk, not a description of it.** 330 files
exist and 19 are known. Even allowing for the production instance holding rows
this checkout does not, the drift is severe. The recovery action meant to close
that gap is the one that cannot import webhook-created backups — which is most
of them. Any design that keeps the database authoritative and the disk opaque
has already been tried here and has failed.

**Containers are created per event, not per thing.** 687 empty directories exist
because a folder is made for every transfer whether or not anything is
displaced. Most transfers displace nothing.

**There is no retention of any kind**, on a disk that is already 68% full. A
version-history model that never prunes would fill it. Retention is load-bearing,
not a refinement.

**The two disks are different devices.** Displacing a file out of the library is
a real copy, not a rename — as it already is today. Reorganising *within* the
backup area, however, is a rename and effectively free. That asymmetry is why
the layout below is affordable and why restore has to be queued.

## 2. The model

An episode is not a file. It is a **slot** that holds one file at a time.

- The **library** holds the slot's current occupant.
- The **backup area** holds its previous occupants, newest first.
- A **capture** is one previous occupant: the media file plus the sidecars that
  travelled with it, taken at one moment.

Every operation is the same primitive: *displace whatever occupies the slot into
its history, then put something else there.* A sync does it. A restore does it.
An Explore removal does it.

Stated for a user:

> Every movie and episode has a version history. The library holds the current
> version; the backup area holds the rest. Restoring promotes an old version to
> current, which pushes the current one into history.

**Reversibility is not a feature in this model — it is a consequence.** Undoing
a restore is restoring the capture the restore itself created. There is no
separate reverse path to write, and none to keep correct.

## 3. On-disk layout

Decided: the tree is reorganised on disk, not only in the index.

```
<BACKUP_PATH>/
  movies/
    Example Film (2024)/
      2026-07-30T14-22-05Z__t1a2b3/
        Example Film (2024) [Bluray-1080p].mkv
        Example Film (2024).nfo
  shows/
    Example Show/
      Season 01/
        S01E01/
          2026-07-30T14-22-05Z__t1a2b3/
            Example Show - S01E01 - An Episode [WEBDL-1080p].mkv
            Example Show - S01E01 - An Episode.srt
          2026-08-04T09-10-33Z__t9f8e7/
            Example Show - S01E01 - An Episode [HDTV-720p].mkv
  anime/
    Example Anime (2018)/
      Season 01/
        S01E24/
          ...
  unsorted/
    <original transfer-relative path>
```

Why each level:

- **`movies` / `shows` / `anime`** — mirrors the three configured destinations,
  so a human reading the disk starts where they expect to.
- **Title folder** — the series or movie folder name exactly as it appears in
  the library, so the two trees read the same way.
- **Season folder** — present for series and anime only.
- **Slot folder (`S01E01`)** — always the padded code, never the season folder's
  spelling. The library contains both `Season 01` and `Season 1`; the slot name
  must not inherit that inconsistency.
- **Capture folder (`<UTC timestamp>__<short transfer ref>`)** — a folder, not a
  file, so sidecars stay welded to the copy they belong to. The timestamp orders
  versions; the transfer ref keeps provenance and disambiguates two captures in
  the same second.
- **`unsorted/`** — anything the parser cannot identify, keeping its original
  relative path. Nothing is ever discarded for being unrecognised, and improving
  the parser later lets it be re-sorted without loss.

Series-level and season-level extras that belong to no episode (posters,
season artwork) go under a `_extras/<capture>/` folder at the level they were
found. They are never treated as slot occupants.

**The tree is the source of truth.** Every fact needed to rebuild the index —
library, title, season, episode, capture time, provenance — is in the path. That
is the direct answer to the 19-of-330 problem: an index that can always be
rebuilt from disk cannot drift from it for long.

## 4. Identity — reuse Explore, do not re-implement it

The current context parser is a second, weaker implementation of something the
Explore rebuild already solved against the real library. It splits filenames at
the first `" - "` to get a series title, which mis-parses any title that itself
contains `" - "`; it matches a season/episode code without requiring the series
to agree; and it re-walks the entire destination tree once per file to find a
match.

Explore's identity module already handles the four things that break naive
parsers here — titles that sometimes carry a year, anime absolute numbers,
`Season 01` versus `Season 1`, Specials, and multi-episode files — and its
inventory already walks and caches the library.

Backups adopt both:

- **Classifying a displaced file** uses the same identity parser. One parser,
  one set of rules, one place to fix a mis-parse.
- **Finding what a restore would replace** asks the library inventory for the
  slot's current occupant instead of walking the tree with regexes.

Two additions are needed:

- **Movie identity.** The existing parser is episode-shaped. Movies need title +
  release year derived from the library folder, which is the same rule Explore's
  path splitter already applies.
- **A slot lookup on the inventory** — "what currently occupies this slot, and
  at what path" — which the cached snapshot can answer without a fresh walk.

A file carrying two episode keys (`S01E01E02`) registers under both slots. It is
one capture referenced from two places, never two copies.

## 5. The write path

rsync writes displaced files flat, at their destination-relative path, into a
per-transfer staging folder. That does not change — rsync's native `--backup-dir`
stays exactly as it is.

What is new is a **sorting step after the transfer settles**:

1. Walk the staging folder.
2. Identify each file. Group each media file with its sidecars.
3. Create the slot folder and a capture folder under it.
4. `os.rename` each file into place — same device, instant, no copying.
5. Anything unidentified moves to `unsorted/` with its original relative path.
6. Remove the staging folder once empty.
7. Write the index rows.

Safety properties worth stating plainly:

- It only ever touches files that are **already out of the library**. A failure
  cannot damage media in the library.
- It is **idempotent**. If the process dies part-way the staging folder still
  exists and the next run finishes the job.
- It is **cheap**. Renames within one device, regardless of file size.

The staging folder is created lazily, only when rsync actually writes something
into it. That alone stops the 687-empty-folder problem from recurring.

## 6. Restore

### The sequence

Restore is a swap, and the two disks are different devices, so it moves real
bytes in both directions. Order is chosen so that nothing is destroyed before
its replacement is safely written.

1. **Capture the current occupant** — copy the library file into a new capture
   folder in the same slot. Verify it landed at the expected size.
2. **Write the restored file** — copy from its capture to the target path under
   a temporary name, then rename into place. The rename is within the library
   disk, so the swap into position is atomic.
3. **Remove the previous occupant** only if its path differs from the target
   (an upgrade may have renamed the file since).
4. **Index** the new capture and mark the restored capture as promoted.

Step 1 completing before step 3 is the whole safety argument. The current
implementation deletes first and copies after, with delete failures logged and
ignored.

### Two current defects this closes

- **Restore runs inside the web request and never reserves its destination.** It
  can write into a library folder a running transfer is writing to. Restore
  becomes a normal queued transfer, which serialises it against syncs by
  destination and gives it live progress, logs and cancellation for free.
- **Restore compares by size only,** so a same-size file at the destination is
  silently not replaced while the log still reports it as copied. The new
  sequence writes unconditionally and the log records what actually happened.

### The preview

Per file, before anything runs:

| Column | Shows |
|---|---|
| What this is | `Example Show — S01E01`, or `Example Film (2024)` |
| Version | Capture time, size, and the quality tag parsed from the name |
| Replaces | The current library file — name, size, quality tag |
| Restores to | The exact destination path to be written |

When the slot is empty, **Replaces** reads *nothing to replace — this will be
re-added*. Nothing in the preview is guessed: the identity comes from the path,
and the occupant comes from the library inventory.

## 7. Retention

Decided: **keep the most recent N captures per slot**, `N` configurable,
defaulting to 2. Pruning runs after a capture is added.

Rules that keep it from being destructive:

- **Never prune a capture younger than a grace period** (default 24 hours), so
  an accidental sync cannot immediately push the copy you wanted off the end.
- **Pinned captures are never pruned.** Pinning is one toggle per capture, for
  the copy worth keeping regardless of age.
- **Report, never silently delete.** Every prune is logged and surfaced, with
  what was removed and how much was reclaimed.
- **Disk pressure is shown, not acted on.** At 68% full the number belongs in
  front of the operator; automatic behaviour keyed to free space is
  unpredictable at exactly the wrong moment.

Retention is only expressible *because* files are grouped by slot. Today nothing
knows two files are the same episode, so no such rule could be written at all.

## 8. The index

The database stops being the source of truth and becomes a rebuildable index
over the tree. Shape:

**`backup_capture`** — one row per capture

| Column | Notes |
|---|---|
| `capture_id` | `<UTC timestamp>__<short transfer ref>`, matches the folder name |
| `library` | `movies` / `shows` / `anime` |
| `title_folder` | Library folder name, as on disk |
| `season_number`, `episode_number` | Integers; null for movies |
| `slot_key` | Normalised, e.g. `shows|example_show|S01E01` — indexed |
| `capture_path` | Relative to `BACKUP_PATH` |
| `captured_at` | Explicit UTC |
| `source_transfer_id` | Provenance, nullable |
| `reason` | `sync_replace`, `sync_delete`, `restore_swap`, `explore_prune` |
| `file_count`, `total_size` | |
| `pinned` | Retention skips it |
| `status` | `present`, `files_removed` |

**`backup_capture_file`** — one row per file within a capture: relative path
inside the capture, the library path it came from, size, mtime, and whether it
is media or a sidecar.

**`backup_capture_key`** — `(capture_id, slot_key)`. Normally one row per
capture; a multi-episode file has several. This is what lets `S01E01E02` appear
under both slots without duplicating the capture.

**Rebuild** walks the tree and regenerates all three from the paths. It needs no
matching transfer record, which is what makes it work for webhook and simulation
backups — the case that defeats the current recovery action. Rebuild becomes a
routine, safe operation rather than a fragile import.

## 9. Migration

Decided: migrate everything, preview first.

1. **Dry run.** Walk the 864 existing folders, identify all 330 files, and
   produce the full proposed mapping — every file, its detected identity, and
   its destination in the new tree — with anything unidentified listed
   separately. Nothing moves.
2. **Approve**, then execute. Moves are renames within the backup disk.
3. **Unidentified files** go to `unsorted/` keeping their original relative
   path. Nothing is deleted for being unrecognised.
4. **Remove the 687 empty folders.**
5. **Rebuild the index** from the resulting tree.
6. Existing `backup` / `backup_file` rows are read for provenance during the
   migration, then retired.

Captures created before the split cannot be ordered against each other within a
slot beyond their file mtimes; where two captures of one slot have equal
timestamps, order is arbitrary and the migration says so rather than inventing
one.

## 10. The screen

Brought to the level of Transfers and Webhooks, and shaped like Explore so the
two read as one system.

- **Tree** — library → title → season, the same navigation Explore already uses.
- **Slot list** — every episode or movie with captures, showing how many
  versions exist and the total size held.
- **Inspector** — the slot's versions, newest first: capture time, size, quality
  tag, the reason it was displaced, and the transfer it came from. Per version:
  **Restore**, **Pin**, **Delete**.
- **Restore preview** — the table in §6, then one confirmation.
- **Restore progress** — a queued transfer with live logs, like every other
  transfer.
- **Housekeeping** — disk usage for the backup area, retention settings, the
  rebuild action, and the `unsorted/` bucket with a way to re-sort it after a
  parser improvement.

After a restore, the swapped-out file appears as the newest version in the same
slot. Undo is visibly just restoring it.

## 11. What this removes

Defects that stop existing rather than needing individual fixes:

- Reindexed webhook backups cannot be restored — identity comes from the path,
  not from a transfer lookup.
- Backups with no recorded destination — the destination is derived from the
  slot.
- Explore's backup panel matching on a title parsed by splitting at the first
  `" - "` — it looks up a slot key.
- No way to see every old copy of an episode — that is the slot folder.
- 687 empty folders — staging is created lazily.
- Index drift — the tree is authoritative and rebuild is routine.
- Restore racing a running transfer — it goes through the queue.
- Restore silently skipping same-size files — it writes unconditionally.
- Delete-before-copy losing a file if the copy fails — capture-before-destroy.
- No retention on a 68%-full disk — keep-N-per-slot.

Still open and **not** solved here: the `BACKUP_PATH` default mismatch, where an
unset value writes backups to a temporary directory that restore then refuses to
read. That is a live data-safety bug and should be fixed on its own, ahead of
this work, rather than folded into it.

## 12. Phasing

Each phase is separately verifiable and leaves the system working.

1. **Fix the `BACKUP_PATH` default mismatch.** Small, independent, and a live
   data-safety defect. Do it first.
2. **Identity.** Extend Explore's parser to movies; add the slot lookup to the
   inventory. Test against the real library, read-only.
3. **Layout and sorting.** New captures land in the new tree. Nothing else
   changes yet.
4. **Index and rebuild.** New tables, rebuild-from-disk, run against the real
   tree read-only before it is trusted.
5. **Migration.** Dry run, review, execute, remove the empty folders.
6. **Restore.** Capture-before-destroy, queued, with the preview.
7. **Retention.** Keep-N, grace period, pinning, reporting.
8. **UI.** The screen in §10.
9. **Explore hand-off.** TASK-010's parked step — restore from Explore itself —
   becomes possible once the slot lookup and the preview exist.

## 13. What implementation changed

The design survived contact with the disk almost intact. Two things did not:

**Legacy folder names cannot be split.** §9 assumed the old
`<safe title>_<transfer id>` name could be parted at the id. Real ids on the
live disk look like `series_webhook_tvshows_301_s1_ef92`, so any split rule is
guesswork. Migration now matches the whole folder name against the library's
own title folders — longest prefix wins — which recovers the library *and* the
title's real spelling from something that exists rather than from a pattern.
That took the preview from 77 of 301 files identified to 271.

**A third bucket was needed.** §3 had slots and `_unsorted`. Season artwork and
series-level `.nfo` files belong to a title but to no episode, and sending them
to `_unsorted` buried them. They now go to `<library>/<title>/_extras/`, listed
but never restorable as a slot occupant.

Also worth recording: capture ids carry milliseconds, not seconds. A sync
followed immediately by a restore of the same episode produces two captures
whose order matters more than any other pair's, and second-resolution could not
tell them apart.

## Related

- [`../features/backups/README.md`](../features/backups/README.md) — how it works today
- [`../features/explore/README.md`](../features/explore/README.md) — the identity and inventory being reused
- [`explore-rebuild.md`](explore-rebuild.md) — why identity is the anchor
- [`../features/queue/README.md`](../features/queue/README.md) — what restore joins
- [`../operations/known-issues.md`](../operations/known-issues.md) — the `BACKUP_PATH` defect and the restore/queue race
