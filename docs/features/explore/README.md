# Explore

Explore compares your **local** library against the **remote** one and turns the
difference into a plan you review before anything is written. It replaces the
old Browse Media page, which walked the remote server and guessed at sync state
from transfer timestamps.

Last updated: 2026-07-30

## The idea in one paragraph

Sonarr and Radarr keep the remote library current and webhooks pull most of it
down automatically. Explore is for what the automation missed. It reads both
libraries as lists of files, gives every media file an **episode identity**
(`S01E23`), and labels each one: in sync, missing, upgraded, or local-only. Every
badge, count and action on the page comes from those four labels.

## Where it lives

| Concern | File |
| --- | --- |
| Filename → episode identity | `services/explore/identity.py` |
| Both libraries as flat file lists | `services/explore/inventory.py` |
| Lining them up and labelling | `services/explore/compare.py` |
| Turning a comparison into an operation + verdict | `services/explore/planner.py` |
| Carrying a plan out | `services/explore/executor.py` |
| Snapshots, plan tokens, per-file outcomes | `services/explore/store.py` |
| The facade the routes call | `services/explore/service.py` |
| Endpoints, rate limiting, status codes | `routes/explore.py` |
| The rsync command for a plan | `services/transfer_service.py` (`_start_explore_rsync`) |
| Page, tree, table, inspector, review dialog | `frontend/src/components/explore/`, `frontend/src/components/pages/explore.tsx` |
| Thread-line geometry | `frontend/src/index.css` (`.explore-*`) |

## How the comparison works

1. **One ssh command** walks the whole remote library and returns every path,
   size and mtime. Records are NUL-separated with the path last, so a filename
   containing a tab or newline cannot forge entries.
2. **A directory walk** does the same locally (~65 ms for 7000 files).
3. **Episode identity** comes from the `S01E23` anchor. This is what lets an
   upgrade be recognised: the same episode under a different filename is a
   replacement, not a new file to sit alongside the old one.
4. **Seasons pair by number, not by folder name** — the library contains both
   `Season 01` and `Season 1`, and `Specials` is season 0.
5. **Roll-up**: a season with nothing missing and nothing upgraded is Synced;
   some present is Partial; none present is Out of sync. **A series' status
   covers all its seasons**, not just the newest.

Results are cached and timestamped. The page reads the cache instantly and shows
"checked …"; **Re-check** forces a fresh pass.

### Deliberate: local-only files do not break "Synced"

Holding everything the remote holds is what Synced means. Files the remote has
since dropped are reported as their own count and warned about loudly at sync
time — that is the case where a mirror would delete them.

## The operations

| Operation | Does | Can it remove? |
| --- | --- | --- |
| **Sync series** | Reconciles every season as one plan, grouped by season | Yes, after review |
| **Sync seasons** | Reconciles the ticked seasons as one plan | Yes, after review |
| **Sync season** | Reconciles one season | Yes, after review |
| **Download** | Copies the ticked episodes, `--ignore-existing` | No, never |
| **Replace** | Backs up the local file, brings the remote one | Only the ticked episodes |

A sync computes, per episode: download what is missing, replace what changed
(old file to backup first, so no duplicate), and list local-only files as removal
candidates. It does **not** use `rsync --delete` — the plan owns removals, which
is what makes the preview honest and keeps artwork and subtitles out of the
danger zone.

**One review, one transfer per season.** A transfer in this application *is* a
season folder: it is what the queue locks on, what a webhook produces, and what
history and backups are keyed by. So a five-season series sync is not one large
run — it is five ordinary ones. They land on distinct destinations, so the queue
runs them in parallel up to `MAX_CONCURRENT_TRANSFERS` (3) instead of pushing
one run through every season in turn, and each shows its own progress.

The *plan* stays whole: one verdict, one set of safety checks, one review
grouped by season with the removals at the top. Only the execution fans out.
Ticking several seasons behaves the same way — the plan covers what you ticked,
and each ticked season becomes its own transfer.

A season with nothing to do produces no transfer at all. A season that only
loses files still gets one, because those files have to be moved to backup and
the run recorded.

Because each transfer is rooted at its own pair of season folders, a season
spelled `Season 01` on the remote and `Season 1` locally needs no special
handling: the run reads from one and writes into the other, and the file list is
bare filenames that cannot recreate a folder. See the naming note below.

**Season folders that Sonarr would have named differently are flagged, not
blocked.** Sonarr writes `Season {season:00}`, so `Season 01` and `Specials`.
Anything else — `Season 1`, `Season 001` — still works, because seasons pair by
number and new files go into whichever folder is already on disk. The comparison
reports the drift (`odd_folders` on both the season and the series) and the
actions panel shows it, so it can be tidied up deliberately rather than
discovered later. Renaming the folders is not something Explore does.

**Replace is the only way to re-fetch a file that already matches.** Any file can
be ticked, in sync or not, and replacing an in-sync file backs the local copy up
and brings the remote one again — for when your copy is damaged. A *sync* never
does this: a matching file is left alone, because nothing about it needs doing.
Download still refuses, because download is defined as "never overwrites".

## The dry run

Every operation can be rehearsed before it runs. "Dry run" builds the plan as
normal, then hands rsync **the same command the real transfer would use**, with
`--dry-run` in front of it, and reports what rsync says back.

The command is built once, in `TransferService.build_explore_rsync_command`, so
the rehearsal cannot drift from the run it is rehearsing. A rehearsal that
differs from the real thing is worse than none.

rsync is asked for `--out-format=%i|%l|%n`, one line per item. The first field
is the itemised change string and carries the whole answer:

| itemise      | means                                       | shown as    |
| ------------ | ------------------------------------------- | ----------- |
| `>f+++++++++` | every attribute differs — the file is new  | `new`       |
| `>f..t......` | some attribute differs — it is overwritten | `replaced`  |
| `.f.........` | nothing differs                            | `unchanged` |
| `cd+++++++++` | a directory would be created               | `directory` |
| `*deleting`   | rsync would remove it                      | `deleted`   |

**The report reconciles two answers, and says where they disagree.** The plan is
worked out from two file listings; rsync is asked separately. Where they differ,
one of them is wrong and you want to know before anything moves.

One gap is expected rather than wrong: the real run moves every superseded local
file into backup **before** rsync starts, so rsync — asked now, with those files
still in place — reports nothing to do for them. Those are folded back in as
`replaced`. Leaving them out would read as "this file is safe" about a file that
is about to be overwritten. Any other disagreement becomes a warning.

A plan that only removes files never reaches rsync at all: there is nothing to
transfer, so the report says so instead of reporting an empty run as "nothing
would happen".

The plan is read with `peek_plan`, not `take_plan` — rehearsing an operation must
not be the thing that stops you performing it. You can dry run as many times as
you like and then approve the same plan.

## The backup view

While you are looking at a series or a season, the actions panel lists what an
earlier sync moved aside there and whether it is still recoverable. It answers
the question you actually have at that moment — "I replaced that episode, can I
get the old one back?" — without leaving the page.

It is **read-only**. Putting a copy back means matching it to a destination file
that may since have been renamed or re-encoded, and confirming what gets
replaced; the Backups page already owns that, and the Restore button links to it.

### Which backups belong to what you are looking at

Matched on the backup's **`folder_name`**, which is the series folder the
transfer ran against. Deliberately **not** on `context_series_title`: that column
is parsed by splitting the filename at the first `" - "`, so the production
library stores "Re - ZERO, Starting Life in Another World (2016)" as just `Re`,
and matching on it would hide that series' backups from itself.

Narrowing to a season uses each **file's own** `context_season`, not the backup's
`season_name`. One series-level sync produces a single backup holding files from
several seasons; filtering by the run's season would show all of them under every
season or none under any. Files with no parsed season — artwork, `.nfo` — fall
back to the run's `season_name`, which is the folder it was scoped to.

`context_season` and `context_episode` are stored zero-padded **as text** (`'03'`,
not `3`), so they are converted before being compared to a season number.

A run whose files all belong to other seasons is dropped from the list entirely,
and the counts shown describe what is being displayed, not the whole run — with
`N in the whole run` beside it when the two differ.

## The safety gate

Anything that can remove or overwrite a local file requires a **fresh
server-side plan that passed**. The plan is stored with a short-lived id; the
transfer endpoint refuses without one, and a plan is single-use. A plan that
failed its checks needs an explicit override plus the season name typed out.

Checks (media files only — the library holds ~2× as many `.nfo`/`.jpg` as
episodes, so counting them would make the numbers meaningless):

- removals do not outnumber arrivals
- removals stay under a share of the local season
- the remote is not smaller than the local copy
- no episode matches more than one local file
- the destination has room

Everything removed or superseded is **moved** into the transfer's backup
directory, which the existing backup finaliser registers — so it is restorable
from the Backups page.

## Behaviour worth knowing

**Misplaced files are detected, not repaired.** The old single-episode download
built its destination with the filename included and then created it as a
directory, leaving files at `Season 01/ep.mkv/ep.mkv` where no media server can
see them. **There are 22 of these in the current library** (3 in TV Shows, 19 in
Anime), plus 4 nested `Season NN/Season NN` folders. Explore flags them per
season; moving them back is manual for now.

**A run that only removes files is written down too.** It starts no rsync, so
nothing in the normal pipeline would record it — it used to appear in no history
and produce no backup record, leaving the moved files in the backup directory
with nothing pointing at them. It now writes a completed transfer row
(`operation_type='explore_prune'`) and indexes its backup, which is exactly what
restore already does for its own synthetic run. A pure removal is the run you are
most likely to want to undo.

**A queued sync moves its backups first.** Files being superseded or removed are
moved before the transfer is handed to the queue, so a run waiting on a slot
leaves those episodes in backup until it starts. If the transfer fails to start,
the moves are rolled back and the library is left exactly as it was.

**Comparison is manual.** There is no schedule. A full-library pass has not been
measured against the real remote yet, and scheduling work of unknown cost against
the media server is not something to guess at — see the plan's follow-ups.

**One browse session is shared by everyone.** Unchanged from before, and a
deliberate single-operator assumption.

**A plan is only spent when it actually runs.** `execute` checks the safety
verdict and the typed confirmation *before* claiming the plan, so a rejected
request leaves it usable — mistyping the confirmation used to consume it, and
the corrected retry then met "expired or already used". The claim itself is a
single `UPDATE ... WHERE consumed = 0`, so two callers racing each other cannot
both run the same destructive plan.

**Rate limiting is per user and only on the expensive endpoints.** Twelve
comparisons a minute; cached reads are unlimited.

**Switching library throws the selection away.** The page is keyed on the media
type, so moving from TV Shows to Anime clears the open series, the open season,
the expanded rows and the ticked files. Carrying them over used to leave a TV
series selected inside Anime, showing an empty file list with no way back to it.

## On a phone

The three panes become one at a time, and a few things behave differently below
`xl` (1280px), where the actions panel is off screen:

- **The tick gutter shrinks below `sm`.** From `sm` up it keeps its full width,
  because the desktop columns line up against it.
- **Ticking a file in a movie folder opens the actions panel.** A movie holds one
  file, so picking it is the whole decision.
- **Picking files or seasons raises a bar above the status line** with the count,
  the size, the primary action, the full actions panel, and a way to clear the
  selection. Above `xl` the panel is already on screen, so the bar stays hidden.
- **The breadcrumb and the remote path scroll sideways** instead of ending in an
  ellipsis. A long series name used to have no way to be read in full.
- **The header strip splits in two below `sm`.** Back, path, tally, Actions and
  the density switch on one 34px strip is fine on a desktop and unreadable on a
  phone, so there the path gets the strip to itself.
- **A movie row carries a film icon where a series has its chevron.** Movies do
  not expand, and the slot was a column of empty space down the whole list.

The tick box hands its click to a hidden `input` that Base UI renders *beside*
it, not inside it. That click reaches the row, so anything that stops the row
handler has to sit around both elements — not on the tick box. Getting this
wrong ticks and immediately unticks, which reads as the tap not registering at
all.

## API

```
GET  /api/explore/libraries                      media types, both paths, config health
GET  /api/explore/tree/<media_type>[?refresh=1]  series with rolled-up status
GET  /api/explore/series/<media_type>/<folder>   seasons
GET  /api/explore/season/<...>/<season>          episodes with labels
GET  /api/explore/history/<media_type>/<folder>  past runs + per-file records
GET  /api/explore/backups/<media_type>/<folder>  backed-up copies, ?season= narrows
POST /api/explore/plan                           evaluate; returns verdict + plan_id
POST /api/explore/dry-run                        rehearse a plan; leaves it runnable
POST /api/explore/transfer                       execute a plan by id
```

`/plan` takes `seasons: [...]` for the sync_seasons operation, and `codes: [...]`
for download and replace. `/dry-run` and `/plan` are rate limited with the
comparisons — both open an ssh connection and walk the remote.

Failures return real status codes: 400 bad input, 401 no session, 404 unknown
library/series, 409 no browse session or expired plan, 422 needs override, 429
rate limited, 502 remote listing failed.

## Data

| Table | Holds |
| --- | --- |
| `explore_snapshot` | the cached comparison per library |
| `explore_plan` | an evaluated operation, its verdict and expiry |
| `transfer_file` | what a run did, file by file |
| `transfers.explore_*` | the approved file list, so a queued or restarted run rebuilds the same command |

## Tests

```bash
PYTHONPATH=venv/lib/python3.12/site-packages python3 -m unittest \
  tests.test_explore_identity tests.test_explore_compare \
  tests.test_explore_planner tests.test_explore_service \
  tests.test_explore_routes tests.test_explore_dryrun tests.test_explore_backups
```

105 tests: the identity parser against real filename shapes from the library, the
comparison labels, planning and safety, multi-season plans, re-fetching a file
that already matches, reading rsync's itemised dry-run output and reconciling it
with the plan, scoping backups to a series and season, an end-to-end run with the
ssh boundary faked, and the HTTP layer.

The backup scoping was additionally checked against the 160 real backups in the
production database — including "Re - ZERO", the series whose stored context
title is wrong.

## Related

- [../../plans/explore-rebuild.md](../../plans/explore-rebuild.md) — the design and why the old code was replaced
- [../queue/README.md](../queue/README.md) — what happens after a transfer starts
- [../backups/README.md](../backups/README.md) — restoring what a sync moved
