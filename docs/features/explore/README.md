# Explore

Explore compares your **local** library against the **remote** one and turns the
difference into a plan you review before anything is written. It replaces the
old Browse Media page, which walked the remote server and guessed at sync state
from transfer timestamps.

Last updated: 2026-10-21

## The idea in one paragraph

Sonarr and Radarr keep the remote library current and webhooks pull most of it
down automatically. Explore is for what the automation missed. It reads both
libraries as lists of files, gives every media file an **episode identity**
(`S01E23`), and labels each one: in sync, nested, missing, upgraded, or
local-only. Every badge, count and action on the page comes from those five
labels.

## Where it lives

| Concern | File |
| --- | --- |
| Filename → episode identity | `services/explore/identity.py` |
| Both libraries as flat file lists | `services/explore/inventory.py` |
| Lining them up and labelling | `services/explore/compare.py` |
| Turning a comparison into an operation + verdict | `services/explore/planner.py` |
| Carrying a plan out | `services/explore/executor.py` |
| Handing each season to the sync pipeline | `services/explore/executor.py` (`_sync_request`), `services/sync_engine/engine.py` |
| Snapshots, plan tokens, per-file outcomes | `services/explore/store.py` |
| Repairing files stranded a level too deep | `services/explore/repair.py` |
| The facade the routes call; how often the remote is read | `services/explore/service.py` |
| The SSH session to the remote server: reconnecting, and never hammering it | `services/remote_session.py`, `ssh.py` (`is_alive`, keepalive) |
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
6. **Upgrade is a tag, not a status.** A series, season or film with at least
   one upgraded file carries a sky **Upgrade** tag beside its status, and the
   episode's own label reads **Upgrade** (the action that fetches it is still
   called Replace). It is a tag because one series can be missing an episode
   and have an upgrade for another; "Partial" alone could not say which. The
   **Upgrade** filter lists every title with one, however old — as of the last
   Re-check sync.
7. **A file in a nested folder is never In sync** (2.3.2, operator,
   2026-10-21). Below the season folder means the media server cannot see
   it, so the episode reads **Nested**, not In sync, and nothing is
   downloaded again — the file is here; [Repair](#repairing-misplaced-files)
   moves it. A season or series that would otherwise be Synced reads **Needs
   repair**; Partial, Out of sync and Not on remote keep their status and gain
   an amber **Nested** tag, the way an upgrade gets its tag. See
   [Nested files on the page](#nested-files-on-the-page).

### "Not on remote" is an answer, not a gap

The fourth status is the one that confuses people. It does **not** mean the
comparison has not run — it means the comparison ran and found the remote holds
no episodes for that title. There is nothing to measure the local copy against,
so it can be neither Synced nor Out of sync, and re-checking will say the same.

Two ways to get there: the title is not on the remote at all, or its folder is
there and holds no media. Both are real — one library has a season folder on the
remote containing a single `folder.jpg`.

It is a common state, not an edge case: in the current library it covers 165 of
202 movies, 74 of 85 TV series and 64 of 82 anime, because the local library is
far larger than the remote. Rows in that state report **your** file count and
size rather than the remote's zeroes, and the actions panel explains why there
is nothing to compare.

The wire value is still `NO_INFO`; only what it is called on screen changed. It
used to read "Not checked", which said the opposite of what had happened and
sent people looking for a button to press.

Results are cached and timestamped. The page paints the saved result at once and
then checks the remote by itself — see [Keeping it current](#keeping-it-current).

## Keeping it current

Since 2.3.2 (operator, 2026-10-20) opening Explore brings it up to date without a
button, and repeated opening does not read the remote again and again.

1. **The page opens on the saved result**, instantly, then asks the server to
   check (`GET /explore/tree/<lib>?check=auto`). A small label beside Re-check
   says "Checking remote…", then "Checked just now" (or "3 min ago").
2. **One walk answers for two minutes.** A walk of a remote library from the
   last 2 minutes is reused — unless Sonarr or Radarr has sent an import webhook
   for that library since, which is the moment the remote changed. Even then a
   walk less than 15 seconds old is reused, so a burst of webhooks during a
   season pack does not make every click a walk. An anime import does not
   count against TV Shows.
3. **This disk is read every time.** It is a local walk (~65 ms) and where syncs
   land, so a finished copy shows at once even when the remote walk is reused.
4. **Series and seasons use the same walk.** Opening a season used to walk the
   whole remote library each time (production: 60 season opens, 60 walks, 5 of
   them refused as "too many"). Now it reuses the library's walk on the same
   two-minute rule, and the season answer carries its `checked_at`.
5. **Re-check always reads the remote**, except when a walk finished less than
   10 seconds ago or is still running — then it shares that one.
6. **One walk at a time per library.** A request that arrives during a walk
   waits for it and shares its result: two tabs, or a double click, are one
   walk.
7. **Plan, Dry run, Download, Replace and Sync still read the remote fresh
   every time.** A plan is never built on a reused walk.

The cost being saved: one walk is one `find` over the library, median 0.5 s
and at most 1.8 s on production (22 Re-checks measured, 2026-10-20).

### The SSH session

Explore reads the remote over one SSH session, shared by everyone. Before
2.3.2 it was opened only by Settings → Auto Connect, was gone after every
restart, and was believed open after the server had reset it — so Re-check
failed at once with "Re-check failed" (production: 9 times; "Connection reset
by peer" on 2026-10-19). Now (`services/remote_session.py`):

- **Before every walk the session is checked for real** — the transport is
  asked, not a flag set once at connect time.
- **A missing or dead session is reopened with the saved login**, if
  **Auto-connect** is on (Settings → Remote server; on by default). A walk that
  fails because the session died under it is retried once on a fresh one.
- **Keepalive every 30 seconds**, so an idle session is not dropped.
- **It never hammers the remote server** (operator, 2026-10-20): one connect at
  a time, whoever asks; after a failed automatic attempt the next waits 30 s,
  then 1, 2, 4 and 5 minutes; a refused login or a host key that does not
  match stops automatic attempts until a person connects; a person's own
  presses are spaced 60 s after a refused login and 10 s after anything else.
  A failed login is what gets an address banned, and a ban would stop every
  sync. rsync and the fast transfer server's set-up use their own SSH and are
  not affected.
- **When the remote cannot be read**, the page keeps the saved result and an
  amber strip says why and how old it is, with **Connect** on the page — greyed
  out with "Connect at 12:01:30" while the spacing above applies. The label
  beside Re-check reads "Offline". The old full-page "Remote browse session
  required" is gone.
- **With Auto-connect off**, nothing connects by itself: the strip says so, and
  Connect (here or in Settings) is how to open the session.

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

**Each season's transfer is a sync like any other.** Since 2.3.0 an approved
plan hands every season to the sync engine as an *Explore* sync
([sync engine](../sync-engine/README.md)), and waits for the queue's answer
(`submit(..., wait=True)`) because the moves made beforehand have to be rolled
back if the transfer is refused. The run records what the review already
checked instead of running a second dry run — "Explore’s review checked this
before it started: 4 files to download, 1 local file moved to backups first.",
or "Explore’s review flagged a problem, and an admin went ahead by typing its
name: …" when the plan was overridden. Its first stage names the button that
was pressed: "<who> pressed Download in Explore for <title>". Until 2026-10-06
these read "The Explore plan was judged safe before it was approved" and
"approved an Explore plan", which used a word the screen never shows. It never
takes in webhooks, because a plan is an exact file list, and it skips the ready
check. The queue still holds it behind anything writing to the same folder —
and, since 2.3.0, behind a copy of the whole series that folder belongs to. Its
finished or failed message on Discord is headed **MANUAL SYNC - EXPLORE**
(2.3.2); 2.3.x said "Explore", and before that "Manual Sync".

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

## Reading a filename

Sonarr and Radarr write a predictable shape, and the library holds ~4,300 files
in it:

```
Series - S01E03 - Third Episode [WEBRip-1080p][GROUP].mkv
Series (2025) - S02E04 - 016 - The Title [Anime Dual-Audio WEBDL-1080p][JA+EN][GROUP].mkv
Title (2025) WEBDL-1080p [HI+ML] [GROUP].mkv
```

Two things follow, and both shape how a row reads:

**The whole filename is shown**, with the episode code picked out inside it.
Abbreviating it hid which of two copies of an episode a row referred to.

**The interesting parts sit at both ends.** The container, quality, languages
and group are at the very end, which is the first thing a truncating cell loses
— so exactly the facts needed to tell two files apart were the ones guaranteed
to disappear. They are lifted out into chips beside the name, where truncation
cannot reach them.

Names run to 102 characters at the median and 248 at the extreme, so on a narrow
pane one line is not enough — the episode code itself was being cut off. Rows
wrap, up to three lines; on a wide window a name fits on one line and rows keep
their normal height.

### Three views, not two row heights

The switch on the header strip used to offer comfortable and compact rows, which
changed only how tall a row was. That is the least useful axis on a screen whose
whole job is comparing two copies of a library — and the table was collapsing
the comparison anyway, showing `remote ?? local` for name, size and date, so the
one thing the page exists to reveal was the one thing it did not show. Both
sides have always been on the wire.

Each view answers a different question:

| View | Answers | Shows |
| --- | --- | --- |
| **List** | What is in here? | One line per row — name, size, date, sync state |
| **Compare** | What is actually different? | Local and remote stacked, with the fields that disagree in amber, and `not on this side` where a copy is absent |
| **Quality** | What would a sync change? | Resolution, source, codec and release group on both sides, the size difference, and a sentence saying which way it goes |

Absence is stated rather than left blank: an empty cell and "you do not have
this" are the same picture otherwise, and only one of them is a reason to sync.

**Quality exists because the Sync column raises a question it does not answer.**
A row labelled `Upgraded` says the remote copy is different. It does not say
whether that is 2160p replacing 1080p, a Bluray replacing a web rip, or the same
1080p from another group at twice the size — and those are opposite decisions.

Everything in it is read out of the file name by `lib/media-filename.ts`, so
where the name says nothing the view says nothing rather than guessing: sides
with no parseable quality read `the filename does not say`. The source ordering
(HDTV → WebRip → WebDL → Bluray → Remux) is acknowledged in the code as rough —
a good web release beats a bad disc rip — and is used only to say which way a
swap goes, never to recommend one.

The source is taken from the word joined to the resolution (`WEBDL-1080p`), and
that match is deliberately not anchored to the start of the tag: quality tags
carry other words in front of them (`Anime Dual-Audio WEBDL-1080p`), and
anchoring dropped the source on every one of those.

Quality is **disabled on the season list**, because a season is a folder and
there is no file name to read. The switch greys it out with the reason rather
than offering an option that would render nothing, and the season list falls
back to List so a segment is always lit.

At the season level Compare shows the two folder names with their file counts
and sizes, because the question one level up is how far apart the folders are —
the file-by-file answer is one click down. The local count is derived from the
labels that describe a local file (`in_sync + upgraded + local_only`); there is
no local total on the wire.

**The title slot is not always a title.** 48 files are named
`Example Show - S01E01 - 1080p x265.mkv`, where the slot holds quality. Printing
that made twenty-two episodes read identically and look broken. Those rows now
show an em dash for the title and `1080p` `x265` as format, which is what the
filename actually says.

The distinction is narrow on purpose: `Sample Series - S01E01 - Pilot Bluray-1080p.mkv`
*does* have a title. The quality is lifted out of the slot and `Pilot` is kept —
an earlier attempt discarded the whole slot and lost real titles with it.

`frontend/src/lib/media-filename.ts` was checked against every media file in the
library: 4,316 of 4,316 yield a quality, and exactly the 48 known files yield no
title. There is no frontend test runner, so that check was a one-off script
rather than a committed test — see the gap noted in
[`../../getting-started/testing.md`](../../getting-started/testing.md).

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

**Restoring works here.** "Restore this version" runs the Backups page's own
planner and shows its own confirmation, so the library file being replaced is
named the same way it would be there. The two screens cannot disagree because
there is one planner behind both — the `backup_id` in this view is the capture
id the `/backups/captures/{id}/plan` and `/restore` endpoints take.

A run narrowed to a season here still restores the **whole capture**. The
capture is what was saved; restoring half of it would leave the slot in a state
nothing on either page can describe. Pinning, retention and deleting stay on the
Backups page, which is what the link at the bottom of the panel is for.

The file that a restore displaces is itself captured first, so a restore is
undone by restoring the capture the restore created.

**The count loads with the selection, not with the click.** The panel's Backups
header carries how many kept files exist for what is selected. It used to fetch
nothing until the section was opened, so the one question the badge answers at a
glance — *is there anything to put back here?* — required the click that only
makes sense once you already know the answer. It is one small index read per
selection, and opening the section is then instant. While it is in flight the
badge shows a placeholder rather than nothing: an absent badge reads as "no
backups here", which is the single wrong answer it can give.

### Which backups belong to what you are looking at

Matched on the backup's **`folder_name`**, which is the series folder the
transfer ran against. Deliberately **not** on `context_series_title`: that column
is parsed by splitting the filename at the first `" - "`, so the production
library stores "Alpha - Bravo, Charlie of the Delta (2016)" as just `Re`,
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

## Repairing misplaced files

The old single-episode download built its destination with the filename included
and then created it as a *directory*, leaving files at `Season 01/ep.mkv/ep.mkv`
where no media server can see them. **There were 22 of these in the library when
this was written** (3 in TV Shows, 19 in Anime), plus 4 nested `Season NN/Season
NN` folders.

Explore flags them per season and per series, and the warning now carries a
Repair button. It previews first: every file it will move is shown as both ends
of the move — where it is now and where it lands, each path in full — with the
folder that comes down under it, and the total. Nothing is renamed — the file
takes the name it already has, one level up.

The preview used to show a truncated filename and only the destination's season
folder, which left out where the file actually is; being in the wrong place is
the entire subject of a repair. The same applies to the two candidates in a
contested move: both are named by their full path, because "keep this one" is a
choice between two files that frequently share a filename.

Three rules shape what it will and will not do.

**A file is only moved when the destination is derivable.** Too *deep* is
repairable: the series and season folders are right there in the path above it.
Too *shallow* is not — an episode sitting loose in the series folder does not say
which season it belongs to, and reading that off the filename would be a rename
wearing a repair's clothes. Those are reported, never touched. The same applies
to a wrapper folder holding anything besides the file itself: it has to come
down for the file to take its name.

**A copy already in place is found by identity, not by name.** This is the
difference between the repair helping and the repair causing the problem it
exists to prevent. A competing copy of an episode is almost never named the
same — it is a different quality or release group — so comparing paths would
report no conflict, move the file up, and leave the episode in the folder twice
under two names for the media server to pick between. Episodes are matched on
their `SxxEyy` code; for a film the folder *is* the slot, so any media file
already in it is another copy of that film whatever it is called.

**Nothing is destroyed, only displaced.** When both copies exist the run stops
and asks: the dialog names both, with their sizes, and each one is kept or
dropped by an explicit choice. There is no default — no rule about which copy
wins is right often enough to be worth the times it would be wrong. Whichever
copy loses is captured into the backup area first and appears on the Backups
page, so both answers are undone by an ordinary restore.

That second choice is the useful one in practice: when the copy already in place
is the good one, the stranded file is not something to repair at all, it is
wasted disk. Keeping the existing copy deletes it and reports the space back.

Mechanically, the wrapper case has to go via a staging name inside the season
folder: the destination *is* the directory that still contains the file, so it
cannot be emptied until the file leaves and cannot be written until it is
emptied. Staging is a rename within one directory, so nothing is copied and
there is no window where the file does not exist. If the folder will not clear,
the file goes back where it was rather than sitting under a name nothing
recognises.

A repair refuses while a transfer is active **against the same title** — that
transfer is writing into the folders being renamed inside. A transfer on another
title, or another library, does not block it. If the check itself cannot be made,
that blocks too: this guards a rename on the media library, so "the database did
not respond" has to mean wait.

**The repair endpoints never touch the remote**, and are deliberately built to
work with the browse session down — a file that is invisible to the media server
should not wait on a connection the fix does not use.

The *page* only partly delivers that. Since 2.3.2 it opens on the saved result
when SSH is down, with an amber strip and Connect, instead of a full-page "no
browse session"; but opening a title still needs a walk under two minutes old,
so the Repair button cannot be reached offline. The
capability is in the API and covered by tests; only the screen gates it. Making
it reachable means serving the series and season views from the cached snapshot
and disabling the actions that genuinely need the remote — a change worth making
deliberately rather than as a side effect.

### Nested files on the page

Until 2.3.2 the only sign was a warning in the actions panel, which is off
screen below `xl`; the rows said **In sync** and **Synced**. Found when
Sonarr's Library tab said an episode was "Missing here" and Explore said "In
sync" for the same file: the Library tab looks only directly inside the season
folder, Explore at every level, and neither was the truth. Now:

- **The episode** reads **Nested** (label `NESTED`), with the path it is really
  at on hover. An upgrade or a local-only file that is nested keeps its label
  and gains "nested folder" beside its name (`local_nested`).
- **The season and the series** read **Needs repair** instead of Synced, or
  carry a **Nested** tag beside any other status — in the tree, in the season
  list, and in the actions panel. A **Nested** filter lists every title with
  one.
- **Opening one** shows an amber strip above the list — "1 file in this
  season is inside a nested folder, where your media server cannot see it" —
  with **Repair**, at every screen width.
- **A sync leaves it alone and says why**: an empty plan reads "Nothing to
  download — but 1 file here is inside a nested folder. Repair moves it into
  place." The Library tab's **Get** says the same instead of "nothing to
  copy".
- **Replace still works on it**: the stranded copy goes to backup and the
  remote one lands in the season folder. Any folder a sync or a replace
  empties by moving a file to backup is removed before the copy starts (the
  arriving file usually has the very name of the folder), never the season
  folder itself; a rollback makes it again.
- **Two copies of one episode**, one in place and one nested: the one in
  place is the match (it is what plays), and the nested one still marks the
  season Needs repair. Repair then asks which to keep.

**The first run against the real library** was the operator's, on production
2.3.1, 2026-10-21: one TV episode, the banner gone afterwards, the file in its
season folder and the wrapper folder deleted. All 22 wrappers left in the
library then predated 2026-07-12; nothing creates them any more.

## Behaviour worth knowing


**A run that only removes files is written down too.** It starts no rsync, so
nothing in the normal pipeline would record it — it used to appear in no history
and produce no backup record, leaving the moved files in the backup directory
with nothing pointing at them. It now writes a completed transfer row
(`operation_type='explore_prune'`) and indexes its backup, which is exactly what
restore already does for its own synthetic run. A pure removal is the run you are
most likely to want to undo. Since 2.3.0 it is also recorded in the sync pipeline
as a finished *Explore* run (`SyncEngine.record_finished_run`): Queue and
Transfer skipped — "Nothing to download: 2 file(s) moved to the backup area." —
and nothing announced.

**A queued sync moves its backups first.** Files being superseded or removed are
moved before the transfer is handed to the queue, so a run waiting on a slot
leaves those episodes in backup until it starts. If the transfer fails to start
— including when the sync pipeline turns it away — the moves are rolled back and
the library is left exactly as it was.

**Restarting a failed Explore transfer re-runs the plan's file list.** The rerun
uses the stored file list (`transfers.explore_*`) and goes through the pipeline
as a *Restart*, not as Explore: the plan's review is not repeated, and the
safety check is skipped, with its reason on the stage — the retry copies the
plan's own files and deletes nothing, the plan was checked before it was
approved, and a dry run of the whole season folder would judge a different
copy. Fixed 2026-10-05: before, the restart was judged by that folder dry run,
with files only this disk has counted as deletions
(`tests/test_sync_engine.py::FinishTests::test_a_retried_explore_plan_is_not_judged_by_a_folder_dry_run`).

**There is no background comparison.** Explore reads the remote when the page
is opened or Re-check is pressed, never on a timer or on returning to the tab
(see [Keeping it current](#keeping-it-current)).

**One browse session is shared by everyone.** Unchanged from before, and a
deliberate single-operator assumption. Disconnecting in Settings closes it for
everyone; with Auto-connect on, the next Explore read opens it again.

**A season view while the remote is out of reach** shows the season pane's own
message ("Not connected to the remote server…") rather than "empty on both
sides". It is served from the last walk while that is under two minutes old;
older than that it needs the remote, because the saved result keeps seasons but
not their episodes (TASK-018).

**A plan is only spent when it actually runs.** `execute` checks the safety
verdict and the typed confirmation *before* claiming the plan, so a rejected
request leaves it usable — mistyping the confirmation used to consume it, and
the corrected retry then met "expired or already used". The claim itself is a
single `UPDATE ... WHERE consumed = 0`, so two callers racing each other cannot
both run the same destructive plan.

**Rate limiting is per user and only on the expensive endpoints.** Twelve a
minute for Re-check, Plan and Dry run. Opening the page and its series and
seasons are not limited since 2.3.2: they reuse one walk for two minutes, so
they rarely reach the remote at all.

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
  the view switch on one 34px strip is fine on a desktop and unreadable on a
  phone, so there the path gets the strip to itself. The view switch shows its
  labels from `md` up and icons alone below that — "Compare" and "Quality" are
  not guessable from a glyph the way a row-height control was.
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
GET  /api/explore/tree/<media_type>[?check=auto|refresh]  series with rolled-up status
GET  /api/explore/session                       the SSH session: connected, Auto-connect, last failure, when it may retry
POST /api/explore/connect                       connect now (spaced like any attempt; 409 with the reason and the time)
GET  /api/explore/series/<media_type>/<folder>   seasons
GET  /api/explore/season/<...>/<season>          episodes with labels
GET  /api/explore/history/<media_type>/<folder>  past runs + per-file records
GET  /api/explore/backups/<media_type>/<folder>  backed-up copies, ?season= narrows
GET  /api/explore/repair/<media_type>/<folder>  what a repair would move; moves nothing
POST /api/explore/repair/<media_type>/<folder>  move misplaced files back into place
POST /api/explore/plan                           evaluate; returns verdict + plan_id
POST /api/explore/dry-run                        rehearse a plan; leaves it runnable
POST /api/explore/transfer                       execute a plan by id
```

`/plan` takes `seasons: [...]` for the sync_seasons operation, and `codes: [...]`
for download and replace. `/dry-run`, `/plan` and `?check=refresh` are rate
limited — each walks the remote. `?refresh=1` is the older spelling of
`check=refresh`. The two `repair`
routes are the exception to everything above: local only, no ssh, no rate limit,
and the POST body carries the scope and nothing else so it cannot name a file.

Restoring a backed-up copy is not an Explore route. `backup_id` from
`/explore/backups` is a capture id, and the Backups endpoints
(`POST /api/backups/captures/<id>/plan`, then `/restore`) take it directly.

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
| `sync_run` (kind `explore`) | one run per season transfer, and one finished run per removals-only season; the plan id, mode and counts in `options`. Linked from the transfer by `transfers.sync_run_id` |

## Tests

```bash
PYTHONPATH=venv/lib/python3.12/site-packages python3 -m unittest \
  tests.test_explore_identity tests.test_explore_compare \
  tests.test_explore_planner tests.test_explore_service \
  tests.test_explore_routes tests.test_explore_dryrun \
  tests.test_explore_backups tests.test_explore_repair
```

183 tests: the identity parser against real filename shapes from the library, the
comparison labels, planning and safety, multi-season plans, re-fetching a file
that already matches, nested files (never In sync, never re-downloaded, the
emptied wrapper folder removed and put back on rollback), reading rsync's
itemised dry-run output and reconciling it
with the plan, scoping backups to a series and season, an end-to-end run with the
ssh boundary faked, and the HTTP layer.

They run without the sync engine: the fake coordinator has none, so the executor
takes its direct `start_transfer()` fallback. The engine side of an approved plan
is pinned in `tests/test_sync_engine.py`
(`test_explore_runs_synchronously_and_stands_alone`); the removals-only record
(`record_finished_run`) has no test.

The repair tests run against a real directory on disk — the repair is a rename
and an rmdir, so faking the filesystem would test nothing. They cover the shape
the bug actually produced, finding a rival copy by episode code rather than by
filename, both decisions end to end (including that the losing copy really does
land in the backup index and not merely on disk), the refusals (two copies
wanting one path, a file above its season folder, a wrapper holding something
else), that a failed capture aborts the deletion, the transfer guard in both
directions, and that the whole thing works with the browse session down.

The backup scoping was additionally checked against the 160 real backups in the
production database — including "Alpha - Bravo", the series whose stored context
title is wrong.

## Related

- [../../plans/explore-rebuild.md](../../plans/explore-rebuild.md) — the design and why the old code was replaced
- [../sync-engine/README.md](../sync-engine/README.md) — the pipeline each approved season runs through
- [../queue/README.md](../queue/README.md) — what happens after a transfer starts
- [../backups/README.md](../backups/README.md) — restoring what a sync moved
