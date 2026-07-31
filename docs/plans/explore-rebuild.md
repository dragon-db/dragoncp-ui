# Explore — rebuild plan (v2)

Status: **built** (2026-07-31)      Branch: `explore-page`
Supersedes [../features/media-browser/README.md](../features/media-browser/README.md), which describes the code that was replaced.

> **This is the design, not the current behaviour.** It is kept for the
> reasoning — why add-only was rejected, why the plan owns removals rather than
> `rsync --delete`, why episode identity is the anchor. For what the feature
> actually does today, read
> [../features/explore/README.md](../features/explore/README.md).
>
> Three things shipped that this document does not describe, all added after it
> was written:
>
> - **`sync_seasons`** — ticking several seasons produces one plan and one
>   transfer, rather than one per season
> - **The dry run as a user-facing step** — this document uses "dry-run" to mean
>   the safety evaluation; the shipped feature also runs the plan's own rsync
>   command with `--dry-run` and reconciles what rsync says against the plan
> - **The read-only backup view** — what earlier syncs moved aside, scoped to the
>   series or season on screen

Explore was rebuilt from scratch: new service module, new endpoints, new data.
None of the old sync-status or transfer-shaping logic was carried forward.

---

## 1. Your questions, answered first

### "Add-only — this means there will be duplicates, right?"

**Yes. Exactly right, and that is why we are not doing it.**

Add-only means "copy what is missing, never remove anything". It is safe for
missing episodes, and it is broken for upgrades. Here is why:

```
remote:  Show - S01E23 - Title [Bluray-2160p][NEW-Dragon DB].mkv
local:   Show - S01E23 - Title [WEBDL-1080p][OLD-Dragon DB].mkv
```

Same episode, different file, **different filename**. Add-only sees a file it
does not have locally, copies it, and leaves the old one alone. You now have two
copies of S01E23 in the same folder, and your media server picks one at random.

So add-only is off the table. But plain `rsync --delete` mirroring is not the
answer either — it deletes blindly, including your artwork and subtitles, and it
cannot tell you *what* it is about to do in terms you care about.

### What we do instead: reconcile per episode

The sync works out, **episode by episode**, what needs to happen:

| Situation | Action |
| --- | --- |
| On remote, not local | **Download** it |
| Both sides, same file | **Skip** it |
| Both sides, different file (upgrade) | **Replace** — back up the old one, bring the new one. No duplicate. |
| Local, not on remote | **Removal candidate** — never silent, always shown, always confirmed |

Now your two scenarios:

**Scenario A — remote grew from 5 to 10 episodes.** The plan is: download 5,
skip 5, remove nothing. If one of the original 5 was also upgraded, it becomes
download 5 + replace 1 (old file goes to backup first, so no duplicate). Nothing
is deleted, no warning is needed, and afterwards local matches remote exactly.
That is precisely what you described.

**Scenario B — remote has 2 episodes, local has 10.** The plan is: 8 removal
candidates. This is the dangerous one, so the dry-run stops and says, in plain
words:

> This season would **remove 8 local episodes** and receive 0. The remote holds
> fewer episodes than your local copy — this usually means the remote lost files,
> not that you should delete yours.

and it lists all 8 by name. You cannot proceed by accident. You get three
choices: cancel, proceed anyway (typed confirmation, and the 8 go to backup, not
to nowhere), or run **"Download & replace only"** — which does the additions and
upgrades and leaves your extra 8 alone.

So "mirror" is the default meaning of Sync, but removal is always an explicit,
informed decision.

### Anime and TV naming

I did not have to guess — I read your library. Everything is Sonarr-renamed and
every file carries the `S01E07` anchor:

```
TV     C.I.D. - S02E03 - Body In The Red Suitcase [WEBDL-1080p][DUS-Dragon DB].mkv
TV     Dark Matter (2024) - S01E03 - The Box [WEBDL-1080p][HONE].mkv
Anime  DARLING in the FRANXX (2018) - S01E24 - 024 - Never Let Me Go [Anime Dual-Audio Bluray-1080p][JA+EN][Chotab-Dragon DB].mkv
Anime  Bleach (2004) - S17E22 - 388 - MARCHING OUT THE ZOMBIES [...].mkv
Movie  How to Train Your Dragon (2025) Bluray-1080p [PSA-Dragon DB].mkv
```

Four things that came out of the real files and would have caused bugs:

1. **The season/episode code is the only reliable anchor.** The series title
   sometimes carries the year (`Dark Matter (2024) - S01E03`) and sometimes not
   (`C.I.D. - S02E03`). Anime adds an absolute number (`- 024 -`) after the code.
   Never parse the title; parse `S(\d+)E(\d+)`.
2. **Season folders are not consistently padded.** Most are `Season 01`, but
   `Money Heist/Season 1` exists. Matching remote and local season folders by
   *string* would fail there. We match on the season **number**.
3. **`Specials` folders exist** — that is season 0, and it has to be handled or
   specials will read as an unmatched folder forever.
4. **Some files predate the current naming** (`Money Heist - S01E15 - 1080p
   x265.mkv`). The code anchor still works, which is why we anchor on it.

Your library right now: 4206 `.mkv`, 102 `.mp4` — and 1920 `.nfo`, 616 `.jpg`,
214 `.srt`, 25 `.png`. **Media files drive every decision and every safety
threshold; the artwork/metadata/subtitle files travel along with them and never
trip a warning.** This is what you asked for and the numbers show why it matters
— artwork outnumbers episodes here.

### Movies

Movies have no episode numbers, so identity is simpler: **a movie folder holds
one main media file** (the largest media file in it) plus its artwork, `.nfo`
and subtitles. That gives movies three sensible operations:

- **Sync the movie** — reconcile the folder: bring the main file if missing,
  replace it if the remote has a different one, bring along artwork/subtitles.
- **Replace the movie file** — the upgrade case on its own, old file to backup.
- **Download only** — take the folder's files without removing anything.

There is no season layer, so the Explore tree for Movies is one level: the movie
list, and an inspector showing the folder's contents. Movies do not get the
"download selected episodes" action; they get "download selected files" instead,
which is the same machinery.

### Backups

Out of scope for this module by your call. All this plan needs from backups is
what already exists: move a file into the backup directory and record it so the
Backups page can restore it. **Retention and pruning are the next module.**

### Comparison: scheduled or manual?

**Manual for now** — you press Re-check, we compare, the result is cached and
timestamped so the page is instant afterwards.

I would not schedule it yet, and here is the honest reason: a full-library
comparison is one big remote directory walk. Until we have measured that against
your real library (7000+ files) we do not know whether it costs two seconds or
two minutes, and scheduling something of unknown cost against your media server
is how you end up with a spinning disk at 3am. The right sequence is: build it,
measure it, then decide. This is recorded as a follow-up in §11 rather than
being quietly dropped.

---

## 2. What Explore is for

Two copies of one library — remote and local. Sonarr and Radarr keep the remote
current and webhooks pull most of it down automatically. Explore exists for
**what the automation missed**: a season that never came, an episode upgraded on
the remote and never re-pulled, a show you skipped and now want.

So its job is:

> Tell me honestly how local differs from remote, and let me fix exactly that
> difference without breaking anything else.

---

## 3. Why the current code is being replaced, not patched

Verified by reading the code, not the docs.

**The sync badge never looks at your local disk.** It compares the finish time of
the last completed transfer row against the newest remote file mtime. Delete an
entire local season and it still reads "Synced". If the remote mtime comes back
as `0` — which the error fallback produces for *every* folder — any completed
transfer at all counts as Synced. A series' badge is just its newest season's
badge, so a show reads Synced with four older seasons missing. And `PARTIAL_SYNC`
exists in the UI but no Python code ever returns it.

There is no repair for this that keeps the approach: the approach is the bug.

**Single-episode download is broken.** The destination path includes the
filename, then the code runs `os.makedirs()` on it and hands rsync a trailing
slash — so downloading one episode creates a *directory* named after the episode
and puts the file inside it:

```
/local/tvshows/Show/Season 01/Show.S01E01.mkv/Show.S01E01.mkv
                             └── a directory ─┘
```

That command also carries `--delete`, which has no business in a single-file copy.

**The sync flags fight the replace feature.** The real transfer runs with
`--update` (skip files newer on the local side) and `--size-only`. An upgraded
remote file with an older mtime, or one that happens to be the same size, is
silently skipped. Those flags are fine for bulk mirroring and wrong for
everything you asked for.

**Browsing costs one SSH round trip per show.** Fourteen shows is fifteen calls
before a badge renders — which is why status refresh is a separate button today.

**Smaller, but all in the way:** episode listings return bare filenames (no size,
no date, no order); sort order is by name length; most failures return HTTP 200
so the UI cannot tell "empty" from "failed"; a dead SSH session renders as an
empty library; and an episode-level transfer does not register as conflicting
with its own season in the queue, so a mirror and a download can run on the same
directory at once.

**What survives.** Path security is genuinely good and is reused as-is:
`validate_path_component` (rejects `..`, separators, null bytes),
`assert_path_within_bounds` (resolves symlinks, confines writes to configured
bases), `shlex.quote` on every remote path, JWT on every endpoint, and the
existing backup + restore service.

---

## 4. The comparison engine

One capability underneath everything: compare the two libraries as files.

**Step 1 — inventory both sides.** One remote command walks the library tree and
returns every file with its relative path, size and mtime. *One* round trip for
a whole library, not one per show. Locally, a directory walk gives the same three
facts.

**Step 2 — give every media file an identity.**

- **TV and anime:** season and episode number from the `S01E07` anchor, with
  multi-episode files (`S01E01E02`) mapping to several identities, and `Specials`
  or `Season 0` mapping to season 0.
- **Movies:** the folder is the identity; the largest media file in it is the
  main file.

**Step 3 — line them up and label every episode:** in sync, missing, upgraded,
or local-only. Upgrade detection is the reason we parse identity rather than
compare filenames — a re-release changes the name, and only the episode number
stays put.

**Step 4 — roll up.** A season with nothing missing and nothing upgraded is
Synced. Some present, some missing → Partial. Anything missing or upgraded →
Out of sync. Never compared → Not checked. **A series' status is the roll-up of
all its seasons**, not the newest one.

**Size, not checksum.** Checksumming a season over SSH is minutes of remote CPU.
Size plus episode identity catches every real case, since any re-encode changes
size. A "verify this file with a checksum" action is available on a single file
when you genuinely doubt a match.

**Cached and timestamped.** Results are stored, the UI reads them instantly and
shows "checked 6 minutes ago", and Re-check forces a fresh pass. This is what
makes the new tree — badges, counts and sizes on every row — affordable at all.

---

## 5. The operations

### 5.1 Sync a season, and sync a series

Reconcile local to match remote, using the plan from §1. Creates the series and
season folders (matching the remote's names) when they do not exist. A series
sync is the same thing across every season, presented as one plan.

**Dry-run is mandatory.** The transfer will not be queued without a fresh,
passed evaluation — see §6. This is the "alert users on what will happen before
the operation is passed to the transfer queue" requirement, and it is enforced
server-side, not in the UI.

### 5.2 Download episodes — cannot replace anything

Copies the episodes you ticked, creating folders as needed. Multiple episodes go
in **one rsync** via a file list, so five episodes is one transfer with one
progress bar. Runs with `--ignore-existing`: if a file of that name is already
there it is skipped, never overwritten. Nothing is deleted, nothing you did not
tick is touched.

No dry-run gate — it cannot destroy anything.

### 5.3 Replace episodes — the surgical one

The case that has no answer today: `S01E23` was upgraded on the remote, but the
remote only holds E23 for that season right now. Syncing the season would treat
E01–E22 as removal candidates. You just want E23 swapped.

Per selected episode:

1. **Find the local counterpart by episode identity**, not filename — so
   `S01E23 [WEBDL-1080p][OLD]` is matched to `S01E23 [Bluray-2160p][NEW]`.
2. **Move the local file to backup** and record it, so it is restorable.
3. **Copy the remote file in.**

Nothing else in the season is touched. If an episode has no local counterpart it
is reported as "will be added" rather than replaced. If it matches *more than
one* local file, it is flagged and skipped rather than guessed at — that is a
duplicate you should look at yourself.

Runs without `--update` and `--size-only`, or the upgrade would be skipped.

Dry-run required, showing each pairing: which exact local file is going to
backup, and which exact remote file replaces it.

### 5.4 Movies

As described in §1: sync the folder, replace the main file, or download selected
files. Same engine, no season layer.

### 5.5 How a plan is executed

Not by handing rsync `--delete` and hoping. The plan is explicit and so is the
execution:

1. Move superseded local files (upgrades, and confirmed removals) into the backup
   directory, recording each one.
2. Run **one** rsync with a file list of exactly what should arrive — no
   `--delete`, so it cannot touch anything the plan did not name.
3. Record what actually happened, per file.

This is what makes the detailed dry-run possible, keeps artwork and subtitles out
of the danger zone, and means the transfer log lines up with the preview you
approved.

---

## 6. The dry-run gate

**Rule: anything that can remove or overwrite a local file requires a fresh
server-side evaluation that passed.**

Running an evaluation stores the result server-side and returns a short-lived
token tied to that exact operation, those exact paths and that exact selection.
The transfer endpoint refuses a destructive operation without a valid, matching,
unexpired token — so the client cannot claim to have previewed. A failed
evaluation returns a token marked unsafe; proceeding anyway requires an explicit
override, and the UI makes you type the season name for it.

**What the report shows** (this is the "detailed info" requirement):

- A one-line verdict, in your terms: *"Downloads 5 episodes (24.1 GB), replaces 1,
  removes nothing."*
- **Per episode**, what happens and why: added / replaced / in sync / removed,
  with the local file and the remote file side by side for replacements.
- Ancillary files (`.nfo`, `.jpg`, `.srt`) counted separately and never mixed
  into the episode numbers.
- Space required, and free space at the destination.
- The safety checks, each pass/fail with its own reason.

**Safety checks** — all on media files only:

| Check | Fails when |
| --- | --- |
| Removals vs arrivals | more episodes would be removed than received |
| Removal share | more than a configurable share of the local season would go |
| Remote shrunk | the remote holds fewer episodes than local |
| Duplicate identity | one remote episode matches several local files |
| Free space | the destination cannot hold the incoming set |
| Errors | the evaluation itself produced errors |

Every removal and every replacement moves the file to the backup directory with a
record. "Removed" always means "recoverable".

---

## 7. History

The `transfers` table already records media type, folder, season, status, timings
and the rsync log — but matched by literal name and with no per-file detail.

Adding:

1. **Per-file records.** The executor already knows exactly what it moved,
   downloaded and backed up; write that to a `transfer_file` table. History then
   answers "when did E14 arrive, and what did it replace" rather than "a transfer
   ran".
2. **A rename-tolerant key.** Store a normalised slug next to the literal folder
   name so a renamed show keeps its history — same idea as the webhook side's
   `series_title_slug`.
3. **A history endpoint** for a series or season: past runs newest-first with
   their per-file records and links to any backups created.

In the UI: a History tab in the inspector — what ran, when, what arrived, what
was replaced, and a restore link for anything backed up.

---

## 8. Security

Foundations stay (JWT everywhere, component validation, bounds checks, quoted
remote paths). Added:

1. **The file list is validated.** Every entry passes `validate_relative_path` —
   which rejects `..`, absolute paths and, critically here, embedded newlines,
   since a newline would inject an extra entry into rsync's list file. Entries
   must be plain names within the named season.
2. **The client's selection is a filter, not an instruction.** Every selected
   file must exist in the server's own inventory before it is acted on.
3. **Rate limiting** on browse and compare endpoints. There is none anywhere in
   the app today, and these cause real work on the media server.
4. **Explicit media-type whitelist** rather than a dict lookup returning `None`.
5. **Real HTTP status codes** — 400/401/404/409/422 — so the UI can tell a dead
   session from an empty library.
6. **SSH session health-checked** before listing, with a clear "reconnect"
   error instead of an empty list.
7. **Episode-level transfers register against their season** in the queue, so a
   season sync and an episode download can no longer run on the same directory
   at once.

One thing I am **not** fixing here and want recorded: the browse SSH connection
is a single global connection shared by every logged-in browser. Whoever
connects, connects for everyone. That is fine for a single-operator install,
which is what this is, and rebuilding session handling does not belong in this
module.

---

## 9. What gets built

### New module

`services/explore/` — inventory, identity parsing, comparison, planning,
execution. Self-contained, unit-testable without SSH (the inventory is an
interface with a real and a fake implementation). Nothing imports the old
sync-status code; `get_sync_status` and `get_folder_sync_status_summary` are
deleted with the old endpoints.

### New data

| Table | Holds |
| --- | --- |
| `library_snapshot` | one row per compared scope: when it ran, counts by label |
| `library_file` | the inventory: side, relative path, size, mtime, parsed identity, label |
| `sync_plan` | an evaluation, its token, operation, paths, selection, verdict, expiry |
| `transfer_file` | per-file outcome of a run: path, action, size |

### New endpoints

```
GET  /api/explore/libraries                    media types, both paths, config health
GET  /api/explore/tree/<media_type>            series with rolled-up status, counts, size
GET  /api/explore/series/<media_type>/<folder> seasons with status, counts, size
GET  /api/explore/season/<...>/<season>        episodes: name, size, date, label, local counterpart
POST /api/explore/compare                      run a comparison for a scope
GET  /api/explore/history/<media_type>/<folder> past runs + per-file records
POST /api/explore/plan                         evaluate an operation; verdict + token
POST /api/explore/transfer                     execute; token required when destructive
POST /api/explore/verify                       checksum one file against the remote
```

The old browse endpoints stay until the UI moves, then are removed with their code.

### Build order

**Phase 1 — the engine.** Inventory (both sides), identity parser, comparison,
snapshot cache. Tested against the real filename shapes in §1 including
`Season 1`, `Specials`, multi-episode and the pre-Sonarr names.

**Phase 2 — planning and execution.** Plan computation, the dry-run report and
its token gate, the executor (backup moves + one file-list rsync), and the four
operations.

**Phase 3 — history.** Per-file records, slug key, history endpoint.

**Phase 4 — hardening.** Rate limiting, queue conflicts, status codes, session
health.

**Phase 5 — UI.** Option 04 "Console" against the new endpoints.

Each phase leaves the app working.

---

## 10. Open question I still have

**How should a series-level sync present itself when seasons disagree?** If a
series has one season needing 5 downloads and another needing 8 removals, is
that one plan you approve as a whole, or per-season decisions rolled into one
screen? My inclination is one plan, grouped by season, with the removals called
out at the top — but it changes the UI, so I would rather ask.

---

## 11. Recorded for later, deliberately not in this module

- **Scheduled comparison.** Manual Re-check ships first; scheduling is revisited
  once we have measured a full-library pass against the real library.
- **Backup retention and pruning.** Next module, by your call.
- **Checksum verification in bulk.** Single-file only for now.
- **Per-user SSH sessions.** Single global connection is a deliberate
  single-operator assumption (§8).
