# Backups on the media disk (Planned — Not Implemented)

Last updated: 2026-08-13
Status: **the code half is built** (§3, §4 and the placement guard from §5).
Nothing has been moved on disk yet — §6 onwards is still the plan.

> Hardlinking is already in place and already correct on the current layout: it
> checks whether the two paths share a filesystem and falls back to copying when
> they do not. Today they do not, so nothing changes yet. The moment the backup
> area moves onto the media disk, every keep-before-destroy becomes instant and
> free with no further code change.

## 1. What this is

The backup area sits on a 1 TB SSD; the media sits on a 20 TB disk. They are
different filesystems, so every file the app keeps has to be *copied* between
them rather than renamed. Measured on the real disks with a 1 GB file:

| | Time |
| --- | --- |
| Move within the media disk | **2.3 ms** |
| Move to the backup disk | **2.8 s** (364 MB/s) |

Roughly 1200× slower, scaling with file size. A 10 GB upgrade spends ~28 seconds
copying the old file aside before the new one starts arriving.

Putting both on the same disk makes every one of those moves instant. It also
unlocks something that is impossible across disks — hardlinks — which removes
the remaining copies as well.

The original reason for splitting them was to avoid spending media space on
backups. That was reasonable, but the numbers do not support it any more: the
media disk has **12 TB free** and the whole backup history is **366 GB**.

## 2. Where the time actually goes today

Six places move or copy backup data. They are not equally affected.

| What happens | Today | On one disk | With a hardlink |
| --- | --- | --- | --- |
| rsync replaces a file (`--backup-dir`) | copy across disks | **instant** | not applicable — already one copy |
| rsync deletes a file (`--delete --backup`) | copy across disks | **instant** | not applicable |
| An Explore plan moves a displaced file aside | copy across disks | **instant** | not applicable |
| Keeping a file before it is destroyed (`BackupsService`) | real copy | faster copy | **instant, no space** |
| Keeping the current file before a restore | real copy | faster copy | **instant, no space** |
| Writing a backup back into the library (restore) | real copy | faster copy | instant — **but see §4** |

The first three are the frequent ones — every replaced or deleted file, on every
transfer. They are *moves*, so they never duplicated anything; they were simply
slow. Same disk fixes them completely, with no code change at all.

The last three are genuine copies, and they are where hardlinks earn their keep.

## 3. Hardlinks: what they do and do not buy

A hardlink is a second name for the same bytes. Two paths, one file, counted
once on disk. Creating one is instant regardless of size. They cannot cross
filesystems, which is exactly why this only becomes available once both live on
the same disk.

The intuition — "the same file in two places costs one file" — is right. The
thing to be careful about is what "the same file" means: it is not a copy that
happens to match, it is *literally the same data*. Write to one name and the
other changes, because there is no other.

So a hardlinked backup is only a backup while nothing writes to the library file
**in place**.

What writes to library files here:

| Who | How | Safe to hardlink? |
| --- | --- | --- |
| rsync | writes a temporary file, renames it into place. `--inplace` is never used | **Yes** — the rename breaks the link and the backup keeps the old bytes |
| The rename service | `os.rename` — changes the name, not the bytes | **Yes** |
| Explore repair | `os.rename` | **Yes** |
| Restore | writes a temporary file, then replaces atomically | **Yes** |
| **Anything outside this app** | a tagger, a subtitle muxer, a metadata writer editing a file in place | **No — and we cannot control it** |

That last row is the whole risk. A tool that rewrites a video container's tags in
place would silently rewrite the "backup" too, and nothing would report it. The
backup would still be listed, still be restorable, and quietly no longer be what
was backed up.

## 4. The rule this plan adopts

**Hardlink when the original is about to be destroyed. Copy when it is going to
stay.**

- **Keeping a file before destroying it** — hardlink. The two names coexist for
  seconds, and the point of the operation is that one of them is about to go.
  This is the frequent case and the big win.
- **Writing a backup back into the library during a restore** — keep the copy.
  Here the shared state would persist indefinitely on a *live* library file,
  exposed to every tool that ever touches the library. A restore is rare and
  user-initiated; a copy is affordable. Instant restores are not worth a class of
  silent corruption that only shows up when someone needs the backup.

Both paths must check that source and target are on the same filesystem and fall
back to copying when they are not, so the code stays correct if the backup area
is ever moved back off the media disk.

Two consequences worth writing down:

- **"Backup size" changes meaning.** A hardlinked capture is counted once, shared
  with the library file. During the brief window before the original is
  destroyed, the backup area appears to occupy less than it will.
- **Retention frees nothing while a link is shared.** Deleting a capture that is
  still hardlinked to a live file removes a name, not the data. Only relevant in
  that same brief window.

## 5. Where the backup area goes

**Not inside any library folder.** The local libraries are
`…/media_external/media/{movies,tv_shows,anime}`. Explore walks those three
directories to build its picture of what is on this machine, and path validation
treats them as the boundary for writes. A backup area *inside* one of them would
be scanned as if it were media — every stored old version would look like a
misplaced library file.

Proposed: **`…/media_external/sync_backup`** — on the same disk, a sibling of
`media/`, outside all three library roots. Same filesystem (hardlinks work),
separate subtree (nothing walks it).

## 6. Moving what is already there

**The stored index holds absolute paths.** `backup_capture.capture_path` (233
rows today), plus `backup.backup_path` and `backup.dest_path`. Moving the tree
invalidates them.

That is recoverable by design: the tree on disk is the source of truth and the
database is an index over it, rebuildable by walking the disk. The Backups page
already has that action.

Order, and it matters:

1. **Confirm nothing is running** — no transfer running, queued or pending, no
   restore in progress.
2. **Stop the application.** Not optional: a transfer starting mid-move would
   write into an area that is half-moved.
3. **Copy — do not move — the tree** to the new location. 366 GB across disks at
   ~364 MB/s is about 17 minutes. Copying rather than moving means the original is
   still there if anything goes wrong.
4. **Point `BACKUP_PATH` at the new location** in the environment file.
5. **Start the application and rebuild the backup index.**
6. **Verify before deleting anything**: the same number of captures as before,
   the Backups page lists what it did before, and — the real test — **restore one
   file and confirm it lands correctly**.
7. **Only then remove the old tree** from the SSD.

Rollback at any point before step 7 is: point `BACKUP_PATH` back, rebuild the
index, restart. The old tree has not been touched.

## 7. Clean up first, move less

366 GB, and some of it is known waste. Doing this before the move means copying
less and starting clean.

Three separate things, in increasing order of judgement required:

1. **Old-format per-transfer folders.** Several remain from before the backup
   rework — one folder per transfer rather than the identity tree. A few are
   empty (8 KB); a handful hold real files. The Backups page has a migrate action
   for exactly these. Migrate them, then confirm none are left.
2. **`_unsorted`, ~8 GB.** Files the sorter could not identify as any particular
   film or episode. They are unreachable by a normal restore because nothing
   knows what they are versions *of*. Worth listing before clearing — anything
   genuinely wanted should be identified and re-filed rather than dropped.
3. **Retention across the identity tree** — anime 226 GB, shows 76 GB, movies
   54 GB. Retention keeps N versions per film/episode with a grace period. It is
   worth checking what N currently is and what a lower N would actually free
   before changing it, because this is the part where a wrong answer deletes
   something wanted.

Point 3 needs a "what would this delete?" preview before it runs. Retention
already has a grace period and pinning; a dry run that reports the total it would
free, per library, is the missing piece and should come before any bulk prune.

## 8. The end-to-end flow after this change

### Keeping a file (every transfer that replaces or deletes something)

1. rsync is about to replace or delete a library file.
2. `--backup-dir` moves it into this transfer's staging folder — **now a rename
   on the same disk: instant, no data movement, whatever the file size**.
3. The new file is written into the library.
4. After the transfer settles, the sorter walks staging and renames each file into
   the identity tree at `<library>/<title>/<season>/<SxxEyy>/<capture>/` — still
   renames within one disk, still instant.
5. The index is updated, and retention prunes older versions of that slot.

Unchanged in shape. Every step that used to copy now renames.

### Explore plans

1. The plan is approved; files it will supersede or remove are moved into staging
   **first** — now instant renames rather than cross-disk copies.
2. rsync fetches the approved list.
3. Failure at any point rolls the moves back — also now instant.

### Restore

1. The operator picks a stored version.
2. **The file currently in place is kept first** — by hardlink, instant and
   free, because it is about to be replaced.
3. The stored version is **copied** to a temporary name beside its target,
   size-verified, then moved into place atomically. Copied rather than linked, per
   §4: this file becomes live and must not share bytes with the backup.
4. If the upgrade had renamed the file, the old occupant is removed.
5. The index records the restore.

A restore is therefore reversible in the same way it always was — the thing it
replaced is now a stored version itself — but the "keep first" half stops costing
a full copy.

### What does not change

Queueing, transfer monitoring, progress, the identity tree layout, pinning,
retention semantics, and the fact that nothing is ever deleted outright — only
moved into backup. This plan changes *where* the backup area lives and *how* files
get into it, not what it means.

## 9. Risks

| Risk | Consequence | Mitigation |
| --- | --- | --- |
| Backup area placed inside a library folder | Explore scans stored versions as if they were media | Put it outside all three roots (§5); assert this at startup |
| An external tool edits a library file in place while a hardlink is shared | A backup silently stops matching what was backed up | Only hardlink files about to be destroyed (§4); never hardlink a restored file |
| The index is not rebuilt after the move | Backups page lists versions that cannot be found | Rebuild is step 5 and verification is step 6, before anything is deleted |
| The old tree is deleted before a restore is tested | No way back | Step 7 comes last, and only after a real restore |
| Backups now grow on the media disk | The original concern returns at a larger scale | Clean up first (§7), and give retention a dry-run preview |
| A transfer starts mid-move | Writes into a half-moved area | Stop the application for the move (§6 step 2) |

## 10. Open questions

1. What is retention currently set to keep, and what would a lower number free?
   Needs the dry-run preview from §7 before anyone answers by guessing.
2. Is anything in `_unsorted` wanted? It has to be looked at, not assumed either
   way.
3. Should disk reporting keep pointing at the SSD once it is empty, or be
   repointed at whatever it is used for next?
4. Should the startup check that refuses a backup area inside a library folder be
   a hard failure or a warning? A hard failure is safer and this is a value set
   once, so it is unlikely to strand a running installation.

## Related

- [`../features/backups/README.md`](../features/backups/README.md) — how backups
  work today
- [`fast-transport.md`](fast-transport.md) §7.9 — where this problem was found
