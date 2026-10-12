# Sync engine

Last updated: 2026-10-06

Every sync DragonCP performs — a Sonarr or Radarr webhook, the auto-scanner, a
press of Sync, an Explore plan, a restart, a restore, a simulation — goes
through the same nine stages, in the same order, and leaves the same record:
what asked for it, which folders it was about, what each stage decided and
why, the log lines each stage wrote, the transfer it became and how it ended.
A kind of sync may run a stage differently or skip it, but a skipped stage
always says why in a sentence an admin can read, and no sync skips the queue.
The record is kept in the database as it happens, so a restart forgets nothing
and an admin can read back exactly what happened to any webhook or transfer —
on the **Transfers** page, one sync at a time, or through the [API](#api).

## Where it lives

| Concern | File |
|---|---|
| The nine stages, the kinds of sync, every skip reason | `services/sync_engine/stages.py` |
| Identify: what a request is about and its folders | `services/sync_engine/units.py` |
| The engine: batching, ready check, safety check, queue hand-off, finish, tell | `services/sync_engine/engine.py` |
| What happens to unfinished syncs at start-up | `services/sync_engine/recovery.py` |
| Runs, stages, log lines and webhook links in the database | `models/sync_run.py` |
| Alerts (the Notifications page) | `services/alert_service.py`, `models/alert.py` |
| The scheduler that runs background jobs | `services/scheduler.py` |
| The scheduled auto-scanner | `services/auto_scanner.py` |
| Sonarr's "is anything for this season still downloading" answer | `services/connectors/adapters/_arr.py` (`InFlight`, `classify_row`) |
| Where the engine plugs into transfers (start, pause, resume, finish), and the start-up order | `services/transfer_coordinator.py` (`start_background`) |
| Folder conflicts in the queue | `services/queue_manager.py` |
| HTTP | `routes/sync_engine.py` |
| Syncs on the Transfers page, the sync panel, and the Notifications page | `frontend/src/components/pages/transfers.tsx`, `frontend/src/components/transfers/transfer-detail.tsx`, `frontend/src/components/pipeline/` (`run-stages.tsx`, `sync-sheet.tsx`, `sync-row.tsx`), `frontend/src/components/pages/notifications.tsx`, `frontend/src/hooks/useSync.ts` |
| The auto-scanner card on the Sonarr and Radarr pages | `frontend/src/components/integrations/scanner-status.tsx` |

## Screens

Everything below is drawn by the React app; [the frontend
reference](../../reference/frontend.md#syncs-on-the-transfers-page-and-notifications)
has the components. There is no Pipeline page of its own: there was one until
2026-10-06, and `/pipeline` and `/pipeline/<run_id>` now redirect to
Transfers.

**Transfers** (`/transfers`) is where a sync is read:

- **A transfer's detail** — open any row — shows its sync under **Pipeline**,
  where a queued / started / completed timeline used to be: what started it,
  then [the stages](#the-stages-wherever-they-are-drawn). The copy's progress,
  facts and rsync output stay where they were in the row, so the Transfer stage
  leaves them out here; the webhooks that asked are under Receive, and an alert
  still waiting on a person shows above the stages with its buttons. A
  transfer from before 2.3.0 says it ran before syncs recorded their stages.
  Until 2026-10-07 the row also linked to the sync panel ("Webhooks, alerts and
  related syncs"), which repeated what the row shows; it was taken out.
- **Waiting to start**, on the Activity tab above the copies in flight, lists
  the syncs that have not reached the queue: held for a person (automatic sync
  off), waiting for the download, or in their safety check. Each row shows the
  title, the kind, the state, a nine-segment strip — one segment per stage,
  coloured by how it ended — the stage it is on, one sentence, who asked, how
  long ago and how many webhooks are linked to it. A held or waiting one has
  **Sync now** / **Go now** on the row. The card appears only while something
  is waiting, and the Activity tab's count includes it.
- **Stopped before copying**, on the History tab under the transfers, lists the
  syncs that ended without a transfer — stopped by the safety check,
  cancelled, failed, or cut off by a restart — 10 to a page, each row's
  sentence saying how it ended.
- **The sync panel** (`/transfers?sync=<run_id>`) opens from any of those rows,
  and it is where an alert, an episode on the Webhooks page and the
  auto-scanner card lead. It has:
  - a header with the state, the kind and who asked, and the actions that fit:
    **Sync now** on a held batch, **Go now** on one in its ready check, **Sync
    anyway** (asks to confirm) on one the safety check stopped, **Retry** on a
    failed or cancelled one with a transfer — the panel then follows the
    retry — and **Cancel** (asks to confirm) on one that has not finished;
  - one sentence on where it stands, in the state's colour — for a batch waiting
    on Sonarr or the fallback wait, with the time of its next step;
  - its alerts, with their buttons;
  - the stages, with the Transfer stage's own progress and rsync output;
  - the webhooks linked to it (**Manual** when one is waiting for a person), its
    transfer, and related syncs — the one it follows or retries, and any
    follow-up or retry of it, each opening in the panel.

  An id the server does not know — a rehearsal since cleaned up, say — shows
  "No such sync".

#### The stages, wherever they are drawn

Nine cards — three across when narrow, then five, then all nine once each
card can hold its label, sized by the space they are given rather than by the
screen — each saying in a word how its stage ended, with the stage a moving
sync is on marked live and, in the single row, a short rule joining each card
to the next. Picking a card opens that one stage below; picking it again, or
its close button, closes it. Nothing is open for a sync that went through
cleanly; one working, waiting, stopped or failed opens that stage by itself
until someone picks another. Until 2026-10-07 every stage was listed below the
cards with its sentence and log, which made a finished transfer's row a page
long.

An open stage shows its sentence, when it ran and for how long, the kind's note
when this kind runs it differently or skips it, the facts it decided on, and
its own log lines. Receive lists the webhooks that asked. Identify shows both
folders. Ready check shows how it decided (asking Sonarr or the fallback wait),
how many times it asked, how many are still downloading, Sonarr's time left,
when the fallback wait ends, when it gives up waiting, and the downloading and
stuck lists. Safety check shows what it would copy and delete and the files on
each side, with the file lists. Transfer shows progress, the route (fast or
SSH), how much moved, speed, time left, rsync's closing figures and the rsync
output, refreshed every 2 seconds while it copies.

The sentences are written for whoever pressed the button, not for the code: an
Explore sync says which button was pressed ("pressed Download in Explore") and
what Explore's review checked ("1 file to download, nothing moved to
backups"), and a sync with no webhook says "No webhook is linked to this
sync". Until 2026-10-06 they said "approved an Explore plan" and "no webhooks
rode on this sync".

**Notifications** (sidebar → Workspace → Notifications, or the bell in the
header, `/notifications`) lists the alerts: **Open** and **Closed** tabs, 25 to
a page. Each alert shows its title, what happened, how many times it was raised
while open, its buttons — **Sync anyway** asks to confirm — and **Open the
sync**, which opens the sync panel on Transfers; a closed one says who closed
it and how. The sidebar item carries the
open count, and the bell a dot, while anything is open.

**From other pages:** an episode's detail on Webhooks has **Open its sync**,
which opens the sync panel on Transfers. An episode a safety check stopped, or a
restart interrupted, shows **Manual** instead of Pending, and its detail says
"Waiting for a person: <reason>". The Sonarr and Radarr Connection tabs under
Integrations carry an **Auto-scanner** card — see
[below](#the-scheduled-auto-scanner).

The pages poll: every 2.5 seconds for a sync still moving, every 4 seconds for
a list holding one, and every 15 seconds (list) or not at all (a finished sync)
otherwise; alerts every 30 seconds. With realtime on, the socket events below
make them refresh sooner, and a toast says so when something new needs a
person.

## How it works

A sync is a **run**. A run moves through **stages**; each stage ends
`passed`, `skipped`, `failed` or `refused`, and while it works it is `running`
or `waiting` (on a timer, on Sonarr, on the queue, or on a person). Every stage
keeps a one-line summary, optional detail, and its own log lines.

### 1. Receive — write down what asked

The request is recorded with who or what made it: the Sonarr or Radarr
receiver, the auto-scanner, or the signed-in admin. A Sonarr webhook's summary
names the episodes ("Sonarr webhook for Example Show — Season 01 — S01E03").

### 2. Identify — what, and which folders

Works out what is being synced — a season, a whole series or a movie — and the
source and destination folders, using the same path rules as every other copy
(`services/path_service.py`). A destination outside the configured library
folders is refused here; the run is recorded as failed with the reason, so a
request that names nothing syncable is still visible.

The destination folder is what identifies the work. Two requests that would
write the same folder are the same piece of work.

### 3. Batch — join one or open one

- **A batch is already open for this folder** (waiting, checking or queued —
  not copying yet): the request joins it. Six episode webhooks for one season
  become one transfer.
- **This folder is being copied right now:** the request goes into one
  **follow-up batch** behind the copy, which runs straight after it. Never a
  third: later requests join the follow-up.
- **Nothing for this folder:** a new batch opens.

Joining and the queued→copying switch happen under one lock per folder, so a
webhook cannot slip between "the batch is open" and "the copy started". As a
last net, a webhook that joined after rsync started is moved to a follow-up
when the copy finishes, because the copy may already have listed the folder.

The stage's sentence follows the batch as it grows. It opens as "Opened a new
batch for Example Show — Season 01 with 1 webhook."; each webhook, press of Sync
or restart that joins rewrites it to "One batch for Example Show — Season 01: 3
webhooks in it.", and the join itself is a log line on the stage ("Joined this
batch (3 webhooks in it now)."). An auto-scanner find that lands on an open
batch only adds a log line. A follow-up batch keeps saying it is one: "Follow-up
batch for Example Show — Season 01, behind run run_…: 2 webhooks in it."

### 4. Ready check — still downloading?

Only Sonarr syncs wait. Radarr webhooks, manual syncs, restarts, Explore,
restores and simulations skip this stage, each with its reason.

1. **Is Sonarr reachable?** The connector is asked. If it is not connected, does
   not answer, or the series has no TVDB id to ask about, the **fallback
   wait** decides (below), and an unreachable Sonarr opens an *Integration* alert that
   closes itself when Sonarr answers again.
2. **Settle.** Wait 10 seconds after the batch opened, so the rest of a burst of
   webhooks can join.
3. **Ask.** "Is anything for this series and season still downloading?" Nothing
   → go. Something → ask again after Sonarr's own time-left estimate, never
   sooner than 10 seconds or later than 5 minutes (30 seconds when Sonarr gives
   no estimate).
4. **Stuck downloads do not hold the season.** A download Sonarr reports as
   stalled, blocked from importing, or failed-pending is listed in the stage and
   in a *Stuck download* alert, and the season syncs without it.
5. **At most 30 minutes.** A season still downloading after 30 minutes syncs
   what is there; the rest arrives through its own webhook or the auto-scanner.
   A *Waited 30 minutes* alert says what was still downloading.

**The fallback wait** (when Sonarr cannot be asked): the *Fallback wait* setting
— 60 seconds unless changed — after the first webhook, plus the same again for
each later webhook, never more than 15 minutes after the first. The stage's
sentence quotes the configured wait. The timer's end is stored on the run and
re-read at every step, so a later webhook really does extend it.

An admin can skip the wait at any point with **Go now**.

### 5. Safety check — dry run first

Before anything is written, rsync is asked what the sync would do (a dry run).
It is stopped when it would delete more files than it brings in, or when the
media server holds fewer files than this disk (when both hold some). The stage
shows the counts: files to copy, files to delete, files on each side.

It is also stopped when the dry run itself does not finish. rsync's exit
status is read before its output: anything but 0, or 24 (files vanished
mid-scan, as when Sonarr moves an import), stops the sync with "The dry run did
not finish (rsync exit N): …", so an unreachable media server or a missing
folder is never read as "nothing to change". Until 2026-10-05 it was read that
way: such a dry run listed nothing, and an empty list passed.

The "…" is the first error line that names a cause — "ssh: Could not resolve
hostname …", "rsync: change_dir … No such file or directory". rsync's closing
`rsync error: … (code N)` line, which only restates the exit code, and ssh's
`Warning:` host-key notices are passed over; when nothing else is there, the
first line is used, and with no error output at all, "rsync gave no error
output". The first build of this check quoted the last line, which is usually
that closing summary.

A stopped sync is **refused**: nothing is written, its webhooks — movies and
series alike — are flagged as needing a person, and a *Safety check* alert
opens with **Sync anyway**. Only a sync that started by itself is also
announced on Discord (as "auto-sync blocked"). An admin who pressed Sync is
already looking at it, and so is one who released a waiting batch — with Sync
or Go now, or a restart that joined it — which counts as a manual sync from
then on.

Explore plans and restores do not run a second dry run: their own review did
this before they were approved, and the stage says so. Simulations skip it:
the dry run checks the media server, and a simulation copies sandbox files on
this machine. Three more skips are decided per run rather than per kind, each
with its reason on the stage: a restart of a simulated transfer, which carries
the simulation flag and is skipped for the simulation's reason; a single-file
sync, because rsync deletes nothing when it is given one file; and a restart of
an Explore plan's transfer, which copies the plan's own file list with no
`--delete` — a dry run of the whole folder would judge a different copy. Until
2026-10-05 each of these ran the folder dry run.

### 6. Queue — wait for a turn

The run becomes one transfer and is handed to the queue, which starts it when:

- **nothing else is writing to the same folder, or to a folder inside or
  around it.** Two different seasons of one series may copy together; the same
  season never; a whole-series copy waits for any season copy of that series,
  and the other way round;
- **a slot is free** — three transfers at once.

While it waits, the stage says which of the two it is waiting for.

### 7. Transfer — copy the files

rsync copies the folder; files it would replace go to the backup area first
(see [backups](../backups/README.md)). The stage records how the copy reaches
the media server — over SSH or over the fast transfer server — and the rsync
process id. Pause and resume are recorded here. The live rsync output stays in
the transfer's own log.

### 8. Finish — close the batch

Every webhook in the batch is marked synced, or failed with the reason, or
cancelled. Webhooks that arrived after the copy began move to the follow-up
batch instead (step 3). A failed transfer opens a *Failed* alert with
**Retry** — except a simulation's, which opens none, and a restore's, titled
"Restore failed" and offering only **Dismiss**: a restore is run again from the
Backups page.

### 9. Tell — Discord and Notifications

The outcome is announced on Discord with a label for the kind of sync
("Automated Sync", "Manual Sync", "Auto-scanner", …). A Sonarr, Radarr or
auto-scanner batch that a person released — Sync or Go now while it was held or
waiting, or a restart that joined it — is announced as "Manual Sync".
Cancelled syncs, restores and simulations — restarted simulations included —
are not announced, and the stage says why. Anything that needs a person opens
an alert on the Notifications page.

## Kinds of sync

`run` = the standard stage; `diff` = runs differently (reason in the stage);
`skip` = skipped (reason in the stage). `GET /api/sync/catalogue` serves this
table with every reason, so the interface draws the pipeline the engine runs.

| Kind | Receive | Identify | Batch | Ready | Safety | Queue | Transfer | Finish | Tell |
|---|---|---|---|---|---|---|---|---|---|
| Sonarr webhook | run | run | run | run | run | run | run | run | run |
| Radarr webhook | run | run | run | skip | run | run | run | run | run |
| Auto-scanner | diff | run | run | diff | run | run | run | run | diff |
| Manual sync | run | run | diff | skip | diff | run | run | run | run |
| Explore | run | diff | skip | skip | diff | run | run | run | run |
| Restart | run | diff | diff | skip | run | run | diff | run | run |
| Restore | run | diff | skip | skip | diff | diff | diff | diff | run* |
| Simulation | diff | diff | skip | skip | skip | run | diff | run | diff |

\* A restore's Tell stage records that restores are not announced.

The table is the kinds' standing rules, and it is what the catalogue serves.
Three Safety skips are decided per run instead, so it does not show them: a
restart of a simulated transfer, a single-file sync and a restart of an Explore
plan's transfer (step 5). A restart of a simulated transfer also skips Tell.

What the differences are:

- **Manual sync** — a press of Sync on the Webhooks page, a Library tab, or an
  alert. A batch already waiting for the folder is told to go now instead of a
  second transfer starting. The ready check is skipped. When the safety check
  stops it, the admin may choose **Sync anyway**; automatic syncs never go
  ahead without a person.
- **Restart** — retries a failed, cancelled or finished transfer, but never a
  restore's: "A restore is run again from the Backups page, where its preview
  shows what it will replace." It goes through the safety check (bar the
  per-run skips above) and the queue like any other sync; if a batch for the
  folder is already waiting, the restart joins it rather than copying twice —
  and a batch still held or in its ready check is released by it, and counts
  as a manual sync from then on. rsync picks up its partial files.
- **Explore, restore and simulation** stand alone: they never take in
  webhooks, because each is an exact plan. The queue still holds them behind
  anything writing to the same folder — except a **restore, which refuses
  rather than waits** when its folder is busy: someone is watching it.
- **Auto-scanner** — see [below](#the-scheduled-auto-scanner).

## Automatic sync switched off

A webhook is always recorded and always opens or joins a batch. With automatic
sync off for that library, the batch is **held** — "Automatic sync is off, so
this waits for someone to press Sync" — until an admin presses Sync on any of
its webhooks or Go now on the batch. If automatic sync has been switched on by
the time another webhook for the same folder arrives, that webhook sets the
held batch going.

## After a restart

Batches live in the database, so a restart forgets nothing — but nothing
restarts behind anyone's back either.

| What was happening | What happens at start-up |
|---|---|
| Waiting in the ready check, or in the safety check | Marked **interrupted**; an *After a restart* alert offers **Sync now**, **Mark as done**, **Mark as wrong**, **Dismiss** |
| Held for a person | Still held |
| In the queue | Carries on by itself. A transfer that was just starting goes back into the queue |
| Marked as copying, but its transfer had not started — still `queued`, or `pending` (about to start) | Back in the queue, and the sync says so; a `pending` transfer is put back as a slot wait. Until 2026-10-05 such a sync was marked interrupted |
| Copying, and rsync survived | DragonCP watches it again and finishes the run when it ends |
| Copying, and rsync was already gone at start-up, or its result cannot be read once it ends | The transfer is marked failed with "Result unknown: …"; a *Result unknown* alert opens instead of a "Sync failed" message, with **Retry** and **Mark as done** |
| The copy had ended, but DragonCP stopped before closing the sync | Finished normally |

Webhooks the old in-memory scheduler had taken and a restart dropped (from
before this engine, up to 7 days back) are found once and raise one alert per
folder.

**Sync now on an *After a restart* alert redoes that sync from its own
record**, so it copies what the interrupted sync would have: the same folder,
the same single file, or the same Explore list of files, with its webhooks
carried along so the new sync marks them synced. An exact list is never widened
into a whole-folder copy: if an Explore list's file is gone, Sync now refuses
("Make the plan again in Explore") and copies nothing. A sync whose transfer
was already written down is retried as a Restart instead; a restore is redone
from Backups, and a simulation from Transfers → Simulate. Each interrupted sync
gets its own alert, so two for one folder each keep their own Sync now. A sync
with no webhooks — the auto-scanner's, Explore's, a manual one — says what it
was doing rather than "0 webhooks". Until 2026-10-12 (branch only) Sync now on
such an alert failed with "This alert does not say what to sync".

**The queue waits for recovery.** At start-up the queue rebuilds
its state from the database without starting anything
(`force_unregister_stale_transfers(promote=False)`, while the coordinator is
built); rsync processes that survived are reattached, and a `running` transfer
whose rsync is gone is recorded as "Result unknown: …"; then, once the
connector layer is up, the sync engine's recovery runs, and only after it does
the queue start whatever has a free slot and a free folder
(`QueueManager.promote_waiting()`, in `TransferCoordinator.start_background`).
A copy started from the queue at that point goes through the engine's hooks
like any other. The completion watchers for transfers found running start after
recovery too, because a watcher whose transfer already ended releases its slot,
and releasing a slot promotes what is waiting.

Until 2026-10-05 the queue started queued work while the coordinator was being
built, before recovery ran. A copy promoted then could still be `pending` when
recovery looked; recovery took it for a copy the restart had cut off, marked
its sync interrupted and opened a false "Some syncs might have been skipped"
alert. And a `running` transfer whose rsync was gone at start-up was recorded as
"Transfer process was interrupted", which the engine treated as an ordinary
failure — "Sync failed" on Discord and a *Failed* alert — rather than as a
result nobody saw.

## The scheduled auto-scanner

A webhook is the only thing that starts an automatic sync, so a lost one is a
silent failure. The auto-scanner asks Sonarr and Radarr instead, on a schedule.
One switch per service, on the Sonarr and Radarr integration settings, **off by
default**, with an interval in minutes.

Each scan:

1. checks the service answers (a scan that cannot reach it counts as failed);
2. reads the service's **import history since the last scan** — new episodes,
   new titles, upgrades — and keeps each import nothing has synced since
   (the first scan looks back 24 hours). "Synced since" means a finished copy
   of that folder that **started** after the import: rsync lists the folder
   when a copy starts, so one that began earlier may have missed the episode
   however late it ended. A copy that was paused and resumed counts from its
   latest start. Single-file copies, restores and simulations never count; a
   transfer from before the engine counts from its own start, and one the
   engine ran only through its sync. The Library tabs read the same rule
   (`services/sync_engine/coverage.py`). Until 2026-10-12 (branch only) a
   copy that began before the import but ended after it counted, through its
   transfer row's end time, and the import was never synced;
3. for Sonarr, also finds **seasons this disk keeps but is short of** — fewer
   files here than in Sonarr;
4. hands every find to the engine as an *Auto-scanner* sync, so batching, the
   ready check and the safety check all apply. A find whose folder already has
   a sync on its way is left to it.

It deliberately does **not** fetch the service's whole backlog: a season this
disk holds nothing of, or a title it never held, is fetched only when the
service imports something for it.

Limits:

- at most **5 new syncs per scan** per service; the rest wait for the next scan,
  and the history window does not move past them;
- a gap the scanner has tried to close **twice** is not retried by itself: a
  *Auto-scanner* alert offers **Sync now**;
- an import that landed while its season was mid-copy is checked again on the
  next scan, because the copy may have missed it.

Each scan's result is in the activity trail (`scanner.run`) and, when it
started anything, on Discord (`scanner.found`).

**On screen**, below the settings on each service's Connection tab, an
**Auto-scanner** card shows the scanner's job: "Switched off" with a pointer to
the switch above it, or "Every 15 min · next scan at …"; the last scan's result
("Last scan 5 min ago: …", in red when it failed, with how many times in a row
when more than once); up to eight of that scan's finds, each with what became of
it — a started one links to its sync — and **Scan now** while the scanner is
on. The card says "Switched off" whenever the job does not run: the switch is
off, or the connector itself is off or has no address or API key — though its
sentence mentions only the switch.

## The scheduler

One service runs everything DragonCP does on a clock. This release has two
jobs: the Sonarr and Radarr auto-scanners. For every job:

- its switch and interval are read on every tick, so turning it on or off
  takes effect without a restart;
- the first run comes shortly (60 seconds) after start-up;
- it never overlaps itself;
- its last run and result survive a restart;
- three failures in a row open a *Scheduler* alert with **Run now**; the next
  success closes it.

## Alerts

The Notifications page lists what needs a person (see [Screens](#screens)).
Each alert has a kind, a title, what happened, links to the run, and the
actions that make sense for it. An alert for the same thing is not opened
twice: a repeat bumps the open one's count. Alerts that need a person are also
announced on Discord once, when they open.

Three kinds watch a condition rather than report an event — *Auto-scanner*,
*Integration* and *Scheduler*. Once a person dismisses one, or marks it wrong,
the same subject does not open — or announce — a new alert for 24 hours; after
that, if the condition is still there at the next check, it opens again. The
other kinds each report one event and are not affected. Until 2026-10-05 a
dismissed one came back at the very next check, every 15 minutes at the
scanner's default interval.

| Kind | Opens when | Actions |
|---|---|---|
| After a restart | A sync was waiting when DragonCP stopped | Sync now · Mark as done · Mark as wrong · Dismiss |
| Result unknown | A copy's result was lost in a restart: its rsync was gone at start-up, or ended where DragonCP could not read how | Retry · Mark as done · Dismiss |
| Stuck download | A season synced without a download stuck in Sonarr | Dismiss |
| Waited 30 minutes | A season synced while Sonarr was still downloading | Dismiss |
| Safety check | The dry run stopped a sync | Sync anyway · Dismiss |
| Failed | A transfer failed, or the queue would not start it. A restore's is titled "Restore failed" | Retry · Mark as done · Dismiss; a restore's, Dismiss only |
| Auto-scanner | The scanner tried a gap twice | Sync now · Dismiss |
| Integration | Sonarr stopped answering (closes itself when it answers) | Dismiss |
| Scheduler | A background job failed three times in a row (closes itself on success) | Run now · Dismiss |

**Mark as done** on a *Failed*, *Result unknown* or *After a restart* alert
closes its run as completed and marks its webhooks synced. The transfer keeps
its own status: a failed transfer stays `failed` in the history, and the run's
Finish stage says "The transfer itself stays recorded as failed."

Closing an alert records who closed it and how, in the alert and in the
activity trail (`alert.resolve`).

## Behaviour worth knowing

- **Every webhook is visible as part of a run.** An episode's or a movie's
  detail on the Webhooks page links to its sync (**Open its sync**), and a
  transfer's detail on Transfers draws its sync's stages, both from the
  `sync_run_id` on the row; any other client can ask
  `GET /api/sync/lookup?notification_id=…` or `?transfer_id=…`.
- **A batch belongs to a folder, not a series.** A whole-series sync and a
  season webhook for the same series are different batches; the queue keeps
  them from copying at the same time.
- **Sync on a webhook that is being copied right now does nothing to it**, and
  says so: moving it would leave the running copy unable to mark it synced.
  Webhooks already synced are skipped the same way.
- **Deleting a waiting transfer closes its sync.** The transfer list cancels a
  queued or paused transfer before deleting it, which frees its place in the
  queue and closes the run as cancelled. Should a queued run's transfer row be
  gone all the same, the next request for that folder closes the run as
  cancelled ("Its transfer was deleted from the transfer list before it
  started.") and opens a new batch, and **Cancel** closes it directly. Until
  2026-10-05 the run stayed "In the queue", and later webhooks for the folder
  joined it and never started.
- **The ready check asks Sonarr one question at a time per batch**, however
  many webhooks join while it waits.
- **A cancel holds while Sonarr or the dry run is still answering.** Both take
  seconds, and nothing is locked while they do. Their answer is written under
  the folder's lock and only if the sync is still waiting for it, so a sync
  cancelled (or marked done) in the meantime stays that way and no copy
  starts; a dry run that answers late is logged as not used. Cancel itself
  decides under the same lock, so it can never miss a copy the queue is
  starting at that moment. Until 2026-10-12 (branch only) Sonarr's late answer
  could undo a cancel and start the copy anyway.
- **Test mode:** the transfer runs rsync with `--dry-run`; the Transfer stage
  says it was a rehearsal and nothing was written.
- **Log lines per run are capped at 2,000**; the oldest go first.
- **Fast transfers:** the Transfer stage records which route a copy took. The
  next piece of work on fast transfers builds on this record.

## Data

| Table | What it holds | Written by |
|---|---|---|
| `sync_run` | One row per run: kind, folders, state, current stage, outcome, transfer, parent run (follow-up or retry), who asked, ready-check timing | `models/sync_run.py` |
| `sync_run_stage` | Nine rows per run: status, summary, detail, start and finish | `models/sync_run.py` |
| `sync_run_event` | The log lines, each tagged with its stage | `models/sync_run.py` |
| `alert` | The Notifications page | `models/alert.py` |
| `scheduled_job` | Each job's last run and result | `services/scheduler.py` |

Links from existing tables: `sonarr_webhook.sync_run_id` and
`radarr_webhook.sync_run_id` (with `sync_attached_at`), and
`transfers.sync_run_id`. The auto-scanner keeps its last-scan time in
`app_settings` and its attempt counts in `sweep_finding`. Full column lists are
in [the schema reference](../../reference/database-schema.md).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sync/catalogue` | The stages, the kinds of sync and every skip reason |
| GET | `/api/sync/runs` | Runs, newest first, with their stage strip and `current_summary` — the sentence the stage a run is on last wrote. Filters: `state` (a state, several comma separated, or `open`, `active`, `live`, `finished`, `all`), `kind`, `search`, `limit`, `offset`, `simulations`, and `copied` — `0` for runs whose Transfer stage never started (what the Transfers page lists as waiting to start or stopped before copying), `1` for the rest |
| GET | `/api/sync/runs/<run_id>` | One run: every stage with its summary, detail and log lines; its webhooks, transfer, related runs, alerts, and the actions available. Carries `current_summary` too |
| GET | `/api/sync/runs/<run_id>/events` | Log lines after `after`, optionally for one `stage` |
| GET | `/api/sync/lookup` | The run behind a `transfer_id` or a `notification_id` |
| POST | `/api/sync/runs/<run_id>/go-now` | Skip the wait. `409` "This sync already ended." once the run has finished |
| POST | `/api/sync/runs/<run_id>/cancel` | Cancel |
| POST | `/api/sync/runs/<run_id>/sync-anyway` | Go ahead despite the safety check. `409`, with the run `failed`, when the queue will not take it |
| GET | `/api/alerts` | Alerts; `state` = `open` (default), `done`, `wrong`, `dismissed`, several of them comma separated (the Closed tab asks for `done,wrong,dismissed`), or `all`; `kind` filters, and `total` counts what the filters match |
| GET | `/api/alerts/summary` | Open counts, for the bell and the sidebar count |
| POST | `/api/alerts/<alert_id>/action` | Act on an alert: `{"action": "sync_now"}` etc. |
| GET | `/api/scheduler/jobs` | Jobs with their switch, interval, last and next run |
| POST | `/api/scheduler/jobs/<name>/run` | Run a job now |

Socket events: `sync_run_updated` (a run's list row changed), `sync_run_event`
(a new log line) and `alerts_changed` (the open counts). With realtime on, the
app refreshes the run lists and that run on `sync_run_updated`, and the run on
`sync_run_event` — each at most once every 1.5 seconds — and takes the open
counts straight from `alerts_changed`, refreshing the alert lists and showing a
toast when the count rises. Pages poll either way; see
[realtime](../../reference/realtime.md).

## Related

- [Webhooks](../webhooks/README.md) — the receivers that start most syncs
- [Queue](../queue/README.md) — slots and folder locks
- [Transfers](../transfers/README.md) — the rsync side of the Transfer stage
- [Integrations](../integrations/README.md) — Sonarr, Radarr and Discord
- [Notifications](../notifications/README.md) — what each Discord message says
- [Auto-sync](../auto-sync/README.md) — the automatic-sync switches
- [Frontend reference](../../reference/frontend.md#syncs-on-the-transfers-page-and-notifications) — the components behind the screens
