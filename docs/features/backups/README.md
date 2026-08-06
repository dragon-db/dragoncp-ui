# Backups and Restore

Every movie and every episode is a **slot**. The library holds the slot's
current occupant; this feature holds the previous ones, newest first. A sync
that replaces or deletes a file moves the old copy here first, and a restore
promotes an old copy back to current — which pushes the file it replaced into
the same slot's history.

That last part is why there is no separate "undo". Undoing a restore is
restoring the version the restore itself created.

Last updated: 2026-08-06
Primary files: `services/backups/`, `models/backup_capture.py`, `routes/backups.py`,
`services/transfer_coordinator.py`

## Where it lives

| Concern | File |
| --- | --- |
| What a displaced file is — the slot it belongs to | `services/backups/identity.py` |
| Where that slot lives on disk, and reading it back | `services/backups/layout.py` |
| rsync's staging output → the identity tree | `services/backups/sorter.py` |
| Rebuilding the index by walking the tree | `services/backups/indexer.py` |
| Planning and running a restore | `services/backups/restore.py` |
| Keeping N versions per slot | `services/backups/retention.py` |
| Adopting the old per-transfer folders | `services/backups/migrate.py` |
| The facade routes and the coordinator use | `services/backups/service.py` |
| Index reads and writes | `models/backup_capture.py` |
| Table definitions and indexes | `models/database.py` |
| HTTP endpoints | `routes/backups.py` |
| Path-boundary checks | `security.py` |
| UI page and data hooks | `frontend/src/components/pages/backups.tsx`, `frontend/src/components/backups/`, `frontend/src/hooks/useBackups.ts` |

## Vocabulary

| Term | Means |
| --- | --- |
| **Slot** | One movie, or one episode of one series. The unit everything hangs off. |
| **Capture** | One previous occupant of a slot: the media file plus the sidecars that travelled with it, taken at one moment. |
| **Version** | A capture, as the UI says it. |
| **Staging** | Where rsync's `--backup-dir` writes during a transfer, before anything is sorted. |
| **Extras** | Files belonging to a title but to no episode — season artwork, a series `.nfo`. Kept, never restorable as a slot occupant. |
| **Unsorted** | Files carrying no usable identity. Kept and listed, never guessed at. |

## How it works

### 1. rsync displaces files into staging

`TransferCoordinator` asks `BackupsService.staging_dir(transfer_id)` for a
folder before starting rsync, in all four places a transfer can begin, so a
resumed run keeps writing into the folder its first attempt used.

The folder is `<BACKUP_PATH>/.staging/<transfer id>`. It is dot-prefixed so it
never appears as content in the tree, and it is created lazily — a transfer
that displaces nothing leaves nothing behind.

rsync runs with `--backup --backup-dir <staging>` as before, so a file at
`<dest>/Season 01/ep.mkv` lands at `<staging>/Season 01/ep.mkv`.

**If `BACKUP_PATH` is unset the transfer refuses to start.** There is no
fallback. See "Failing closed" below.

### 2. What was displaced is sorted into the tree

Once the transfer settles, `_post_transfer_completion` calls
`BackupsService.sort_after_transfer`. It walks staging, identifies every file,
and moves each into the slot it belongs to:

```
<BACKUP_PATH>/
  movies/
    Example Film (2024)/
      20260730T142205.311Z__t1a2b3/
        Example Film (2024) [Bluray-1080p].mkv
        Example Film (2024).nfo
  shows/
    Example Show (2024)/
      Season 01/
        S01E01/
          20260730T142205.311Z__t1a2b3/
            Example Show (2024) - S01E01 - An Episode [WEBDL-1080p].mkv
            Example Show (2024) - S01E01 - An Episode.srt
          20260804T091033.007Z__t9f8e7/
            Example Show (2024) - S01E01 - An Episode [HDTV-720p].mkv
      _extras/
        20260730T142205.311Z__t1a2b3/
          poster.jpg
  anime/
    ...
  _unsorted/
    20260730T142205.311Z__t1a2b3/
      <the path the file had inside the transfer's destination>
  .staging/
    <transfer id>/
```

Three properties make this safe to run unattended after every transfer:

- it only touches files that are **already out of the library**, so a failure
  cannot damage media;
- it is a **rename within one filesystem** — instant regardless of file size,
  because staging and the tree share a device even though the backup area and
  the library do not;
- it is **idempotent**. If it dies part-way the staging folder still holds what
  is left and the next run finishes the job.

A capture is a *folder*, not a file, so an episode's subtitles and metadata stay
welded to the copy they belong to. Sidecars need no pairing heuristic: a file
named `... - S01E01 - Title.srt` carries the same episode code as the video, so
it lands in the same capture on its own.

One transfer usually produces **several** captures — a slot per episode, one
per title's extras, and the unsorted bucket — and each gets its own id. They
share a timestamp and a source reference because they share a cause, and a
`__2` suffix keeps them apart. Reusing a single id across them all meant the
second capture's index row replaced the first's, so a transfer that displaced a
whole season left one episode listed and the rest on disk with nothing able to
find them.

### 3. Identity

Episode parsing is **not** reimplemented here. `services/explore/identity.py`
already derives its rules from the real library and handles the four things
that break naive parsers: titles that sometimes carry a year, anime absolute
numbers, `Season 01` versus `Season 1`, Specials, and multi-episode files.

`services/backups/identity.py` adds the movie half — title and release year,
taken from the library folder first because Radarr names it `Title (2024)` and
it stays stable while the file inside carries quality tags — and the naming
rules for the tree.

A file with no usable identity is never guessed at. If it sits under a known
title it goes to that title's `_extras`; otherwise it goes to `_unsorted`,
keeping the relative path it had, where it is still recoverable by hand and can
be re-sorted later once the parser improves.

**Multi-episode files.** `S01E01E02` is stored once, under `S01E01`, and
registered against both slots in `backup_capture_key`. It is therefore
reachable from either episode without being duplicated.

### 4. The index

Three tables — `backup_capture`, `backup_capture_file`, `backup_capture_key` —
and **none of them is the source of truth**. The tree is. Every fact needed to
rebuild the index is in the path: library, title, season, episode, capture time
and provenance.

`POST /api/backups/rebuild` regenerates the whole index by walking the disk. It
needs no transfer record and no prior index, and is idempotent. Four things are
carried over from the existing index rather than regenerated, because a path
cannot hold them: whether a capture is **pinned**, **why** it was displaced,
**which transfer** produced it, and **when it was last restored**.

It deletes no media and moves nothing, with one exception. A capture folder
whose name is already in use elsewhere in the tree is renamed, and the count is
reported as `repaired`. The name *is* the capture's identity, so two folders
sharing one means only one of them can be indexed and the other's files sit on
disk unlistable — a rename inside the backup disk is instant and loses nothing,
so the invariant is repaired rather than reported and left broken. On a tree
written by the current sorter this is always zero.

This is a direct answer to the state the previous implementation left: on the
live disk it had 864 folders and 330 files, and the index knew about 19 of them.

### 5. Restore

`plan_restore(capture_id, files)` is the read-only half and backs both the
preview and the run, so what is approved is what happens.

For each file it resolves:

- **target** — where it will be written, derived from the slot, not from a
  destination recorded months ago,
- **replaces** — the file currently occupying that slot, from a listing of the
  slot's own folder filtered by episode identity.

A media file only ever replaces a media file and a sidecar only ever replaces a
sidecar, so restoring a subtitle can never delete an episode. An exact filename
match wins; failing that, the single occupant of the matching kind is used,
which is what catches an upgrade that renamed the file.

The run is a swap, ordered so nothing is destroyed before its replacement is
safely written:

1. **Capture the current occupant** — copy it into a new capture in the same
   slot, and verify the copy landed at the expected size. A failure here aborts
   with `Nothing was changed`.
2. **Write the restored file** to a temporary name beside the target, verify,
   then `os.replace` it into position — atomic, because it is within the
   library disk.
3. **Remove the previous occupant** only if its path differs from the target.
   When the names match, step 2 has already overwritten it.
4. **Index** the capture the restore created.

The restore runs as a normal queued transfer with live progress and logs.

A restore records **when** it happened and changes nothing else about the
version it restored. The files are still in the backup tree, so the same
version can be restored again, and it stays subject to retention like any
other. Marking it "restored" instead made a successful restore its own last:
the next attempt was refused with a message about the files having been removed
while they were sitting right there, and retention skipped it forever, so every
restore added a version the rule would never prune. A **partial** restore —
some files back, some not — is not recorded as a restore at all, because the
run has to be repeated.

### 6. Deleting, to get space back

Retention runs on its own; this is the manual half, for when a disk is full
now.

- **One version** — the trash control on any version in the inspector.
- **Several versions** — tick them in the inspector, or tick whole items in the
  slot list to mean *every version of these*, then **Delete selected**.
- **Keep a safety net** — a slot deletion can leave the most recent N versions
  (`keep_newest`), which is the shape of "free some space but do not leave me
  with nothing".
- **The unidentified bucket** — one action clears all of it. By definition
  nothing can tell you what those files are, which on a full disk makes them
  the least painful thing to lose.
- **Find what is worth deleting** — the slot list sorts by **Largest** as well
  as **Newest**. Reclaiming space is a question about size, not recency.

Two rules hold throughout:

**Every delete is previewed first.** The count and the total size are shown
before anything happens, whether one version was picked or fifty. This is the
only action in the feature with no undo — those files are the last copy of that
version — so it never runs on a bare click.

**Pinned versions are held back** unless explicitly included, and the number
held back is reported rather than silently absorbed. A pin that a bulk sweep
ignored would be worthless.

Deleting removes the files and the index entry together, and prunes the folders
it emptied. The library is never touched. There is deliberately no way to drop
the index entry on its own: the index is derived from the tree, so a row
removed without its files frees no space and returns at the next rebuild — the
version looks deleted right up until it silently is not.

### 7. Retention

Keep the newest `N` captures per slot, `N` from `BACKUP_RETENTION_KEEP`
(default 2). Runs automatically after a capture is added.

Three things protect a capture:

- being within the newest `N` for its slot,
- being **pinned**,
- being younger than `BACKUP_RETENTION_GRACE_HOURS` (default 24) — which stops
  an accidental sync immediately pushing the copy you wanted off the end.

A multi-episode capture is only pruned when it has fallen out of the window in
**every** slot it belongs to; otherwise restoring the other episode would find
nothing. Nothing is removed silently: every prune reports what went and how
much was reclaimed.

Disk pressure is **shown and never acted on**. Pruning keyed to free space
fires at unpredictable moments, which for a recovery tool is the wrong
property.

**Where the rule is stored.** In the `app_settings` table, not the env file.
That is the only store that both survives a restart and is visible to the
background thread that applies the rule after a transfer — a value in the Flask
session would be invisible to it, and a value in the env file would need a
redeploy. `BACKUP_RETENTION_*` in the env file still works as the default when
nothing has been saved.

### 8. Migrating the old layout

`POST /api/backups/migration/plan` previews adopting the old
`<safe title>_<transfer id>/` folders; `/apply` carries it out. Always preview
first — identity is being inferred for files that in some cases have no
transfer record left to check the inference against.

Where a legacy record survives, its media type and destination are used. Where
none does — the common case on the live disk — the library is asked instead:
the folder name is matched against every title folder in every configured root,
longest prefix wins, and that gives both the library and the folder's real
spelling. An absent or ambiguous match stays unknown and those files go to
`_unsorted`.

Migration **refuses to run while any transfer is active**, because it moves
files across the whole backup disk and a running transfer is still writing to
it. Running, pending, queued and paused all count — a queued transfer is not
writing yet, but it can start at any moment. It also refuses when it cannot
*tell*: if the transfer table cannot be read, the answer is wait, not proceed.

Each identified group gets its own capture id, including several episodes out
of one legacy folder. Sharing one id across a whole season meant each episode's
index row overwrote the last, leaving every episode but one on disk and
invisible.

**A shared backup disk needs a second guard.** More than one instance can point
at the same `BACKUP_PATH` — a development checkout alongside the live one, each
with its own database. The active-transfer check only sees its own database, so
it cannot know the other instance is mid-transfer. Any legacy folder whose
contents changed in the last 15 minutes is therefore left alone regardless, and
reported as skipped.

**Migrating on a shared disk moves the files for everyone, immediately.** The
other instance's records still point at the folders that have just moved, so its
Backups page will list versions it can no longer restore until it is running
this code and has rebuilt its index. Sequence it deliberately: deploy first, or
accept that the other instance's backup page is stale until you do.

## Behaviour worth knowing

- **Failing closed on `BACKUP_PATH`.** Unset, transfers refuse to start, resume
  and restart. Previously writing fell back to `/tmp/backup` while restore
  refused anything but a configured path, so every sync quietly wrote displaced
  media somewhere the OS may clear and nothing could get it back. Both halves
  now agree, and they agree on refusing.

- **A restore takes its turn in the queue.** It reserves its destination like
  any transfer, so it can no longer write into a folder a sync is writing to.
  If the destination is busy or every slot is full it says so rather than
  queueing silently — a restore is watched, and parking it invisibly is worse
  than refusing.

- **A restore always rewrites the file.** The previous implementation compared
  by size only, so a same-size file at the destination was silently left alone
  while the log still reported it as copied.

- **Restoring a capture records `restored_at` and leaves `status` alone.** The
  files stay in the backup tree, so it stays in the slot's history, can be
  restored again, and is pruned by retention like any other version. A partial
  restore is not recorded as one — the run has to be repeated.

- **Deleting a version removes its files and its index entry together.** There
  is no longer a record to keep without files — the index is derived from the
  tree.

- **`_unsorted` is not restorable.** There is nowhere to put those files back,
  so the plan is blocked with an explanation rather than offering a guess.

- **Timestamps are UTC everywhere**, to millisecond precision. The milliseconds
  are not decoration: versions inside a slot are ordered by capture time, and a
  sync followed immediately by a restore of the same episode would otherwise
  produce two captures that could not be told apart — the pair whose order
  matters most.

- **The deprecated compatibility endpoints still work during the React cutover
  soak.** `/api/backups`, `/api/backups/<id>/files|plan|restore|delete` and
  `/api/backups/reindex` are backed by the new store, with a capture id in place
  of the old backup id. One deliberate difference survives at those
  paths: the old page sends `"files": []` to mean "everything", so the legacy
  plan route normalises it, while the current API rejects an empty list because
  ticking nothing is not a request to restore everything.

- **Explore reads the same index.** Its actions panel lists a series' or
  season's stored versions by slot, so a title containing `" - "` finds its own
  backups. The previous implementation matched on a title parsed by splitting
  the filename at the first `" - "`, which stored "Alpha - Bravo, Charlie of the
  Delta" as "Alpha" and hid that series' backups from itself.

- **In-flight rsync fragments are skipped.** `--partial-dir` points inside
  staging, and anything under `.rsync-partial` is excluded from sorting rather
  than indexed as recoverable media.

## Data

Created in `models/database.py`, accessed through `models/backup_capture.py`.
Full column reference: [../../reference/database-schema.md](../../reference/database-schema.md).

`backup_capture` — one row per version:

| Column | Notes |
| --- | --- |
| `capture_id` | `<UTC timestamp>__<short source ref>`, matches the folder name, unique across the whole tree |
| `library` | `movies` / `shows` / `anime` |
| `title` | Library folder name, as on disk |
| `season_number`, `episode_number` | Integers; null for movies |
| `release_year` | Movies only |
| `slot_key` | `shows\|example_show\|S01E01`, indexed |
| `capture_path` | Relative to `BACKUP_PATH` |
| `captured_at` | Explicit UTC, millisecond precision |
| `source_transfer_id`, `source_ref` | Provenance; the transfer id is null after a rebuild |
| `reason` | `sync_replace`, `sync_delete`, `restore_swap`, `explore_prune` |
| `kind` | `slot`, `extras`, `unsorted` |
| `file_count`, `total_size` | From the files inside |
| `pinned` | Retention skips it |
| `status` | Whether the files are still on disk: `present` or `files_removed` |
| `restored_at` | When it was last put back, or null. A restore does not make a version permanent — it stays restorable and stays subject to retention |

`backup_capture_file` — one row per file: path inside the capture, the library
path it came from, size, mtime, and whether it is media or a sidecar.

`backup_capture_key` — `(capture_id, slot_key)`. One row per capture, except a
multi-episode file which has one per episode.

The `backup` and `backup_file` tables from the previous implementation are no
longer written to. Migration reads them for provenance.

## API

All endpoints require authentication. Full contracts:
[../../reference/api.md](../../reference/api.md).

| Endpoint | Purpose |
| --- | --- |
| `GET /api/backups/overview` | Totals, disk pressure, retention rule, libraries, legacy folder count |
| `GET /api/backups/titles?library=` | Titles holding versions |
| `GET /api/backups/seasons?library=&title=` | Seasons within a title |
| `GET /api/backups/slots?library=&title=&season=&search=&limit=&offset=&sort=` | Slot list with version counts. `sort=size` puts the biggest first |
| `GET /api/backups/slot?slot_key=` | One slot's versions and what the library holds now |
| `GET /api/backups/captures/<id>` | One version with its files |
| `GET /api/backups/unsorted` | Files that could not be identified |
| `POST /api/backups/captures/<id>/plan` | Preview. Omit `files` for all; `[]` is rejected |
| `POST /api/backups/captures/<id>/restore` | Run it. Returns once accepted |
| `POST /api/backups/captures/<id>/pin` | `{"pinned": true\|false}` |
| `POST /api/backups/captures/<id>/delete` | Remove one version — files and index entry together |
| `POST /api/backups/delete/preview` | What a deletion would remove, and the space it frees. Reads only |
| `POST /api/backups/delete` | Remove many at once: `capture_ids`, `slot_keys`, `keep_newest`, `include_pinned` |
| `POST /api/backups/unsorted/delete` | Clear the unidentified bucket in one call. `{"confirm": true}`. The UI does not use it — it routes that button through the preview and confirm path like every other deletion |
| `POST /api/backups/retention` | **Save** the rule to the database |
| `POST /api/backups/rebuild` | Regenerate the index from the tree |
| `GET /api/backups/retention` | The rule and disk usage |
| `POST /api/backups/retention/preview` | What keep-N would remove |
| `POST /api/backups/retention/apply` | Remove it |
| `POST /api/backups/migration/plan` | Preview adopting the old folders |
| `POST /api/backups/migration/apply` | `{"confirm": true}` |

Deprecated paths retained for a browser-only rollback: `GET /api/backups`,
`GET /api/backups/<id>`, `GET /api/backups/<id>/files`,
`POST /api/backups/<id>/plan|restore|delete`, `POST /api/backups/reindex`.

## The screen

`frontend/src/components/pages/backups.tsx`, shaped like Explore on purpose —
titles on the left, contents on the right, details in an inspector — because
the two are views of the same library.

- **Stat tiles and disk bar** — items with versions, versions stored, size held,
  pinned; and how full the backup disk is.
- **Library tabs** — Movies / TV Shows / Anime, with a title search.
- **Titles pane** — every title holding versions, with counts and size.
- **Slot list** — each movie or episode with versions, showing how many and how
  much. A pin marker appears when any of its versions is pinned.
- **Inspector** — the slot's history. The library's current copy sits at the
  top, marked as current rather than listed among the versions; under it, each
  version with its capture time, why it was displaced, its files and sizes, and
  **Restore**, **Pin** and **Delete**.
- **Restore preview** — one row per file: what is being written, and what it
  replaces, or *nothing to replace — this will be re-added*.
- **Selection and bulk delete** — tick items in the list (meaning *every
  version of these*) or versions in the inspector (meaning *these specific
  ones*). A bar appears with **Delete selected**, and every delete is previewed
  with its count and total size before it runs.
- **Newest / Largest** — the slot list sorts either way. Largest first is the
  order for reclaiming space.
- **Housekeeping** — retention settings that **save to the database** and take
  effect without a restart; the index rebuild; the one-off migration; and the
  unidentified list.
- **Every deletion is previewed, and the preview is binding.** Retention's
  *Remove them now* is disabled until the current numbers have been previewed,
  and editing them clears the preview — otherwise previewing "keep 10" and then
  typing 1 would delete the far larger keep-1 set unseen. Clearing the
  unidentified bucket goes through the same confirm dialog as any other delete,
  with its count and total size, rather than firing on one click.

Below `lg` the two panes become one at a time with a back control, and the
inspector is a sheet.

## Related

- [../explore/README.md](../explore/README.md) — the identity and inventory this reuses
- [../queue/README.md](../queue/README.md) — what a restore joins
- [../../plans/backup-restore-rework.md](../../plans/backup-restore-rework.md) — the design, and the measurements behind it
- [../../reference/database-schema.md](../../reference/database-schema.md)
- [../../reference/api.md](../../reference/api.md)
- [../../reference/test-mode.md](../../reference/test-mode.md)
