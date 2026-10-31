# Integrations — the outside services DragonCP talks to

DragonCP can link to other applications. Each link is a **connector**: a named,
configurable, testable connection to one outside service, with its own page
under Integrations in the sidebar.

- **Discord** posts DragonCP's announcements — a sync finished or failed, a
  rename completed, the retention rule deleted old backups, and the alerts the
  sync engine raises. What each one says is on
  [the notifications page](../notifications/README.md).
- **Sonarr** is asked, for every season a webhook opens a batch for, whether
  anything for that season is still downloading. The answer decides when the
  season syncs.
- **Sonarr and Radarr** each have a **scheduled auto-scanner**, off by default,
  that finds imports nothing has synced — a webhook that never arrived, or a
  sync that was skipped — and alerts on them (the default, **Alert only**) or
  syncs them, and pages that show the service's library, download queue and
  history against this disk.
- **Jellyfin** can be connected and tested, but nothing reads it yet.

Last updated: 2026-10-19
Primary files: `services/connectors/`, `models/connector.py`, `routes/connectors.py`,
`services/auto_scanner.py`, `services/scheduler.py`, `services/media_index.py`,
`services/library_compare.py`, `services/local_library.py`,
`routes/media_library.py`, `frontend/src/components/pages/integrations.tsx`

## Where it lives

| Concern | File |
| --- | --- |
| What a connector is | `services/connectors/base.py` |
| The one outbound HTTP call | `services/connectors/transport.py` |
| What the app can announce | `services/connectors/events.py` |
| Which destination an announcement goes to | `services/connectors/routing.py` |
| Delivering without blocking the caller | `services/connectors/dispatch.py` |
| The facade everything else uses | `services/connectors/service.py` |
| Discord: embeds, colours, webhook validation | `services/connectors/adapters/discord.py` |
| Sonarr and Radarr: the read-only client, the "still downloading?" answer, the auto-scanner's settings | `services/connectors/adapters/_arr.py`, `sonarr.py`, `radarr.py` |
| Sonarr's two allowed commands (`RenameFiles`, `RefreshSeries`), the TMDB key and the title-check schedule | `services/connectors/adapters/sonarr.py`, `_arr.py` (`command`); behaviour in [renames](../renames/README.md) |
| Jellyfin | `services/connectors/adapters/jellyfin.py` |
| Asking Sonarr whether a season is ready — the pipeline's Ready check | `services/sync_engine/engine.py`, through `services/media_index.py` (`in_flight_for_season`) |
| The scheduled auto-scanner | `services/auto_scanner.py` |
| The scheduler that runs it | `services/scheduler.py` |
| Library, Queue and History tabs | `routes/media_library.py`, `services/media_index.py` (the list's verdicts, the detail view, the rows) |
| One title compared episode by episode | `services/library_compare.py` |
| What is on this disk, by title, season and episode | `services/local_library.py` |
| Storage | `models/connector.py`, tables `connector`, `connector_secret`, `connector_target`, `notification_route`, `connector_delivery`; `media_item` (the title index); `scheduled_job` and `sweep_finding` (the auto-scanner) |
| API | `routes/connectors.py`, `routes/media_library.py`, `routes/sync_engine.py` (scheduler jobs) |
| UI | `frontend/src/components/pages/integrations.tsx`, `frontend/src/components/integrations/` (the auto-scanner card is `scanner-status.tsx`; the Library, Queue and History tabs are `library-panel.tsx`, `queue-panel.tsx`, `history-panel.tsx`, the series pop-up `title-dialog.tsx`, their shared pieces `library-bits.tsx` and words `library-vocab.ts`), `frontend/src/hooks/useConnectors.ts`, `frontend/src/hooks/useMediaLibrary.ts`, `frontend/src/hooks/useSync.ts` (`useSchedulerJobs`, `useRunJob`) |

## What an operator sees

Each page opens with the service's name and its On/Off switch, and nothing
under the name: the one-line description of the service ("Film library
manager…") was removed in 2.3.2 to give the tabs the space. The API still
returns it as `description`.

**Integrations → Discord** has five tabs, in the order you are likely to need
them:

- **Webhooks** — the list of destinations, and where the page opens. Each has a
  name you chose, and one of them is the default. Add takes a name and a
  Discord webhook URL; the URL is stored on the server and never shown again.
  Each row has a Test button that sends a real message (pinging whoever that
  webhook pings), an "in service" switch, and **Pings**: who every message
  sent there pings unless a notification chooses others.
- **Mentions** — who a message can ping: a Discord role, a person, `@here` or
  `@everyone`, each under a name you choose ("Admins"). A role or a person
  needs its Discord ID (Developer Mode, then right-click → Copy Role ID / Copy
  User ID); the form explains where to find it and refuses a name typed in its
  place. Each row has **Test ping** (to a webhook you pick), Edit and Remove.
  Removing one takes it out of every webhook and notification that pinged it.
- **Routing** — every announcement the app can make, one per row, each
  with a destination dropdown and an on/off switch. A row set to "Use default"
  goes wherever the default webhook points. Under each, **when it pings**
  (never, on warnings and failures, or on every message — the default is
  marked) and **whom** (the webhook's pings, shown by name, or people you
  pick). The sync engine added five rows in 2.3.0 and QoL v2 one more,
  Waiting for a manual sync. Until 2026-10-05 this tab was called
  Notifications; it was renamed so it is not confused with DragonCP's own
  **Notifications** page, the alerts that need a person.
- **Activity** — the last hundred messages this connector handled, including
  the ones it held back and why.
- **Appearance** — the app URL a message links back to, the icon shown beside
  it, and the default thumbnail. The thumbnail's description says it is for
  transfers started by hand; in fact every message with no image of its own
  uses it, alerts included. Set once and rarely touched, which is why it is
  last.

**Integrations → Sonarr / Radarr** each have four tabs:

- **Library** — every title the service lists, as a grid of small posters
  against what is actually on this disk, read from the filesystem rather than
  the transfer history. Each card carries one state — **Out of sync**,
  **Needs repair** (everything is here, but a file sits in a nested folder —
  Explore's word), **In sync**, **Not here**, **Unlisted** (the service no
  longer lists it; the files here are kept), **No files yet** — and one quiet
  counts line, "Sonarr 1 · here 7". An out-of-sync title whose reason is a
  newer or different file on the service also carries a sky **Upgrade** tag;
  one that also has a nested file carries an amber **Nested** tag. Filter
  chips with counts (Out of sync first, then **Upgrade**, which is always
  offered, then **Nested** when any title has one), a search, a sort
  (needs attention first, recently imported, title) and **Refresh**, which
  re-reads the service's catalogue. Out-of-sync titles come first. How the
  state is decided is in *The Library tab: in sync or not*, below.
- **The series pop-up** — clicking a card (or a History or Queue row) opens
  that title in a pop-up over the list: a wide panel on a computer, the whole
  screen on a phone. Close, Escape or the browser's Back shuts it; the list
  behind is untouched. The address carries it
  (`?tab=library&title=<tvdb or tmdb id>`). It has two tabs, **Episodes** (a
  film's is called **File**) and **History**. Episodes leads with one sentence
  and its actions. One action leads, filled; the rest are outlined, and
  **Open in Explore** is an outlined brand button beside them rather than a
  quiet link (2.3.2, operator, 2026-10-21). Which leads follows the state:
  a nested file → **Repair in Explore**; else something missing → **Get**;
  else an upgrade → **Replace**; else nothing here → **Copy the series**;
  else, with something wrong and nothing this pop-up can do → **Open in
  Explore**.
  - "S01E38 is here, but inside a nested folder your media server cannot
    see", with where it is now, and **Repair in Explore**, which opens
    Explore on the season holding it — where the strip above the list has
    **Repair**. There is no Get for it: copying it again would not make it
    visible. A film reads the same way.
  - "S01E08 is on Sonarr but not here yet", the episode's title and Sonarr's
    file under it, and **Get S01E08** (or **Get 3 episodes**). Get never
    copies on its own: it asks Explore for a download plan of exactly those
    episodes, season by season (Explore reads the remote server fresh), and
    shows what it would do in one line, "Copy 1 file (1.6 GB) from the
    remote server into Season 01. Nothing here is replaced or removed.",
    with **Copy now** and **Cancel**. Copy now runs the plan; it copies the
    files and touches nothing else, so the episodes kept only here stay. No
    rsync dry run is involved. When the app has no browse session to the
    remote server (a restart drops it), Get connects with the saved
    credentials, as Settings' Connect does, and asks again; only if that
    fails does it say so. A plan Explore's checks stop, or one that finds
    nothing to copy, says why and offers **Open in Explore** — filled, as it
    is then the only way on (**Repair in Explore** when the episode turned
    out to be nested).
  - A file that differs gets **Replace S01E05** the same way: Explore's
    replace, which keeps the file here in Backups first.
  - A title with nothing here at all gets **Copy the series** (or **Copy the
    film**), the whole-folder sync, offered only where it removes nothing.
    Like Get it asks first (2.3.2, operator, 2026-10-21): "Copy seasons 1
    and 2: 18 files, about 24.0 GB, from the remote server. Nothing of it is
    here yet, so nothing here is replaced." — or "Copy the film
    (WEBDL-1080p, 2.8 GB) …" — with **Copy now** and **Cancel**. The numbers
    are the service's own (a double-episode file counted once; Specials are
    not fetched); the sync then runs its own dry-run safety check. It is
    never offered for a title with a nested file: that title reads Needs
    repair, not Not here.
  - Otherwise one quiet line: "Everything Sonarr has for this series is
    here."

  Below it, the seasons: one row each with "1 not here" (amber) and "7 of 8
  here", opening to a row per episode with its number, title, air date, the
  file facts that explain its state, and the state as an icon and a word
  (**Not here**, **Upgrade**, **Nested**, **Here**, **Only here**, **Not
  downloaded**; each explains itself on hover). Only Not here, Upgrade and
  Nested are coloured; a nested episode's facts give the path it is at, and a
  season with one says "1 nested".
  Seasons with something to fix open by themselves; a long one opens on just
  those episodes, with **Show all**. Episodes still to air fold into one line,
  "6 episodes still to air, the next on Oct 18", and Specials come last. A
  film shows its file against the file here, as one row when they are the
  same file.

  **History** lists what happened to the title, newest first: Sonarr's or
  Radarr's own events for it (imported, grabbed, deleted, a download that
  failed) beside DragonCP's syncs of its folder (finished, failed, stopped by
  the safety check, cancelled, cut off by a restart) and the transfers from
  before the sync engine. Each says when, what, and in a word whether it got
  done. An import is marked **Not here yet** while its episode is still
  missing here, or **Here**; a failed download of an episode that is here
  anyway reads **Here anyway**, and a failed or stopped sync that a later
  sync of the same folder finished reads **Done later**. **Not done** narrows
  the list to what is still undone. A burst of the same deletion reads as one
  entry ("deleted its files for S01E01 to S01E07"), and a sync links to its
  panel on Transfers. (`GET /api/library/<source>/<external_id>/history`.)

  Until 2026-10-12 this was a side panel that said the same thing several
  times (a summary, a legend, a strip of numbered cells, each season's
  counts) and sent the reader to Explore with a paragraph explaining why the
  season's Sync would not do. For a day it then opened as a page in place of
  the list; the operator wanted a pop-up.
- **Queue** — the service's download queue, stuck rows first, each as series ·
  SxxEyy · episode title (a film: title and year), quality, a progress bar,
  time left, the download client, and its state in plain words: Downloading,
  Waiting to import, Importing, Imported (still seeding), **Stuck:** with the
  service's own reason, **Failed**, **Stale** (the library already has the
  file). A row says whether it is holding a sync back, and opens its title.
- **History** — what the service did, a page at a time, read the way Sonarr's
  own History reads: series, `1x08`, episode title, quality, custom formats and
  their score, download client, release name, when. Chips filter by Imported,
  Grabbed, Deleted, Failed or Renamed on the service's side. A row opens its
  title. **Unknown here** marks an import for a title DragonCP has never heard
  of, which is what a lost webhook leaves behind.
- **Connection** — the address, the API key, the **Scheduled auto-scanner**
  switch, **When it finds something** (Alert only or Sync it) and **Scan every
  (minutes)**, and a Test connection button. Below
  them, an **Auto-scanner** card shows what the switch is doing (see *The
  scheduled auto-scanner*).

A connector that is switched off says so above its tabs, and the Library,
Queue and History tabs ask for it to be turned on.

**Integrations → Jellyfin** is drawn by the same layout as Sonarr and Radarr,
because it declares the same capability, so it shows Library, Queue and History
tabs too. The library endpoints know only Sonarr and Radarr and answer 404 for
Jellyfin. Not verified: how those three tabs render that refusal.

The settings tab is named by the adapter, not by the page. Discord calls its
tab **Appearance** because nothing on it reaches Discord — a webhook URL
carries its own credential, so connecting happens on the Webhooks tab. Sonarr,
Radarr and Jellyfin are reached with an address and an API key, so theirs is
called **Connection** and carries a Test connection button that genuinely
reaches the service.

Test connection tests what is in the form, saved or not, and saves nothing. A
stored API key the form still shows as hidden is used as saved. The answer
appears under the fields; for values nobody has saved yet it says so ("not
saved yet. Press Save to keep it."), and the saved connection's "last checked"
line is left alone. **Unsaved changes** shows beside Save whenever the form
differs from what is saved. Saving a new address or key tests it straight away.
The page's On/Off switch saves only on/off and keeps whatever is typed in the
form; switching a connector on with nothing saved to connect with says so.

Discord has no such button. A connector declares `supports_check = False` when
it has no endpoint to reach at that level, and the UI then offers nothing: a
test that cannot fail is worse than no test, because it leaves a green badge on
something nothing verified.

## How it works

### Announcing something

Anything in the application that wants to announce something writes this, and
nothing else:

```python
from services.connectors import notify
from services.connectors.events import Event, Field

notify(Event(
    key='transfer.failed',
    severity='failure',
    title=parsed_title,
    fields=(Field('Error Details', error_text, monospace=True),),
))
```

No enabled check, no URL, no embed, no colour, no `try`/`except`. `notify()`
resolves which connectors want the event and which destination each uses, hands
the work to a background thread, and returns. It never raises and it never
blocks.

The caller describes *what happened*. The adapter decides how its service shows
it — which is why the colours, the 1024-character field cap and the timestamp
format exist once in `adapters/discord.py` instead of in every call site.

### The catalogue

`services/connectors/events.py` holds the list of things that can be announced.
Adding one is a row there; the routing UI renders the catalogue, so an
announcement that cannot be seen cannot be turned off.

| Key | Fires when |
| --- | --- |
| `transfer.completed` | A transfer finished successfully |
| `transfer.failed` | A transfer stopped without finishing |
| `rename.finished` | A rename run finished — whole, partial or failed. Sonarr's webhook runs and renames started in Explore alike; *Rename all ready* sends one for the whole run |
| `titles.ready` | The scheduled title check found real titles for episodes still named TBA. Nothing is renamed until someone presses Rename in Explore (added 2026-10-23; never pings by default) |
| `backup.retention_deleted` | The retention rule deleted stored versions |
| `autosync.blocked` | An automatic sync's safety check stopped it, waiting for a person — not one a person started, or released with Sync or Go now |
| `sync.held` | Automatic sync is off for the library, so a batch is waiting for someone to press Sync. Once per batch: webhooks that join it later send nothing (added in 2.3.2, issue #35) |
| `sync.interrupted` | A restart may have left a sync undone, or lost the result of a copy |
| `sync.stuck` | A season went ahead without a download stuck in Sonarr, or after waiting 30 minutes |
| `scanner.found` | The auto-scanner started syncs, or cannot close a gap (a gap's alert, once dismissed, is not sent again for 24 hours) |
| `scanner.missed` | The auto-scanner, set to Alert only, found imports nothing has synced. One message per scan listing up to 10, only for new alerts; nothing was copied (added in 2.3.2) |
| `integration.down` | Sonarr did not answer when a batch asked; sent once until it answers again, and not again for 24 hours once its alert is dismissed |
| `scheduler.failing` | A background job failed three times in a row (once its alert is dismissed, not again for 24 hours) |
| `fast_route.failed` | A copy failed on the fast transfer server and ran again over SSH; sent once while its alert is open, and not again for 24 hours once it is dismissed |

The last five arrived with the sync engine in 2.3.0, and most of what they say
comes from its alerts — see [notifications](../notifications/README.md).

`connector.test` exists as a key but is deliberately outside the catalogue: a
test send ignores routing by design, so offering a destination choice for it
would be offering a choice that does nothing.

### Routing

One rule decides everything: **a missing route means the default, not
silence.** An announcement added in a later version is delivered the day it is
written, without anyone remembering to configure it — which is what the five
added in 2.3.0 do.

Resolution order, in `routing.py`:

1. Connector turned off → nothing happens, nothing recorded. (A fresh install
   has every connector off; logging each skip would bury the entries that mean
   something.)
2. The notification is switched off → skipped, recorded with the reason.
3. A destination was chosen → that one. If it no longer exists, the default.
4. No destination chosen, or no route row at all → the connector's default.
5. No default at all → skipped, recorded, and shown as a warning on the page.
   This is the only state where a message is lost, and it is visible.

A destination taken out of service is **not** quietly redirected to the
default. "Out of service" is a statement about that destination, and sending
somewhere the operator did not choose is worse than not sending.

### Pings

Who a message pings is decided once it has somewhere to go
(`routing.mentions_for`):

1. **When.** The route's rule, else the notification's `default_ping`:
   `never`; `attention`, which pings only a warning or a failure; or `always`.
   Reports of something done — Sync finished, Rename finished, Old backups
   deleted, Synced without a stuck download — default to never; everything
   else to attention. So by default "Sync failed" pings and "Sync finished"
   does not, and the auto-scanner pings when it cannot close a gap or finds a
   missed auto-sync, but not when it starts syncs.
2. **Whom.** The people the route picked; a route that picked nobody
   explicitly pings nobody. A route that never chose uses the webhook's own
   **Pings**, so "ping Admins for everything in the alerts channel" is set
   once, on the webhook.

Discord writes the pings in the message text above the card, because it never
pings from inside one, and always sends `allowed_mentions` naming exactly who
may be pinged. Nothing else in a message can ping anyone, so a title that
happens to contain "@everyone" stays text. A role can only be pinged by a
webhook if Discord allows it: if a test ping arrives as plain text, turn on
"Allow anyone to @mention this role" for that role. The **Activity** tab
shows who each delivered message pinged.

Sending one notification to several webhooks at once is not supported; it is
a recorded future improvement (operator, 2026-10-19).

### Delivering

`dispatch.py` is one daemon thread and one bounded queue. `notify()` puts and
returns.

This is a fix, not only a tidy-up. A rename notification used to be posted to
Discord synchronously inside the HTTP request Sonarr made — `RenameService`
called straight from the webhook route — so **Sonarr waited up to ten seconds
for Discord to answer**, and adding retries would have made it worse.

The queue is bounded at 500. When it fills, the oldest waiting announcement is
dropped and the drop is logged: a Discord outage with an unbounded queue is a
slow leak that looks like nothing at all until it does not.

### The one HTTP call

`transport.py` is the only place the application makes an outbound request.
Two rules hold there and nowhere else needs to know them:

- **Nothing raises.** Every path — timeout, DNS failure, refused connection,
  malformed response — returns a value. Callers are background threads that
  must survive a service being down.
- **Nothing leaks.** A URL is redacted before it reaches any string a caller
  might log, store or render. A Discord webhook URL *is* the credential; there
  is no separate token to hide, and the code this replaced printed it beside
  the response body on every failure.

One retry, on 429 and 5xx only. `Retry-After` is honoured up to ten seconds —
Discord can ask for several minutes on a hard rate limit, and blocking the
shared worker that long would stall every notification behind it.

### Asking Sonarr whether a season is ready

Every Sonarr webhook goes into a batch for its season folder, and the batch's
**Ready check** decides when it syncs. [The sync engine](../sync-engine/README.md)
has the whole pipeline; this is the part that talks to Sonarr. There is no
switch for it: whether Sonarr's API answers decides.

1. **Can Sonarr be asked?** Not connected — the connector is off, or has no
   address or API key — means the fixed fallback timer
   (`SERIES_ANIME_SYNC_WAIT_TIME`, see [Settings](../settings/README.md))
   decides, and nothing is raised. Connected but not answering its status
   check means the same timer, plus an *Integration* alert announced once as
   `integration.down`; the next batch that finds Sonarr answering closes it.
   Dismissed while Sonarr is still down, it stays closed for 24 hours. A
   series that carries no TVDB id cannot be asked about either, so it gets the
   timer too.
2. **Settle, then ask.** Ten seconds after the batch opens — so the rest of a
   burst of webhooks can join — DragonCP asks Sonarr's download queue about the
   series (`/api/v3/queue/details?seriesId=`) and keeps the rows for that
   season. One question at a time per batch, however many webhooks join.
3. **What holds the season.** A download still downloading, waiting to import,
   or importing. What does not: a row already imported (the download client
   keeps seeding after import), a row whose file is already in the library, a
   state this version does not recognise. Downloads that will not finish by
   themselves — stalled, blocked from importing, or failed and waiting on a
   retry decision — are **stuck**: they never hold the season, they are listed
   in the stage, and once the season goes ahead without them a *Stuck download*
   alert says what was left behind.
4. **When to ask again.** After the slowest blocking download's own "time left",
   kept between 10 seconds and 5 minutes (30 seconds when Sonarr gives no
   estimate).
5. **At most 30 minutes.** Then the season syncs with what is there, and a
   *Waited 30 minutes* alert lists what was still downloading. The rest arrives
   through its own webhook or the auto-scanner.

The Queue tab gives each row the same verdict because it calls the same
classifier (`ArrConnector.classify_row`), so the screen and the decision cannot
disagree.

**Radarr is never asked.** A Radarr webhook means one finished film, so it
syncs straight away — still through the safety check and the queue. A per-film
version of the question exists (`MediaIndex.in_flight_for_movie`); nothing
calls it.

An unreleased build had a switch for all this — "Wait for the download instead
of the clock", with poll and settle settings beside it. It was removed; see
[Settings](../settings/README.md).

### The scheduled auto-scanner

A webhook is the only thing that starts an automatic sync, so a lost one is a
silent failure. The auto-scanner asks the service instead, on a schedule. It
replaced the "Check for missed imports" sweep that pre-release builds had.

**The switch.** One per service, on its Connection tab: **Scheduled
auto-scanner**, off by default, and **Scan every (minutes)** — how often it
asks, 5 to 360, default 15 (60 is once an hour). It runs only while the
connector itself is on and configured. **Look back (days)**, 1 to 30, default
7, is how much history an Alert only scan reads (added in 2.3.2, operator
2026-10-20). Out-of-range numbers are clamped when read, not refused on
save, for both.

**The mode.** **When it finds something**, beside the switch:

- **Alert only** — the default, and what an unset value means. A find opens a
  *Missed auto-sync* alert and a Discord message, and nothing is copied: you
  sync it from Explore when it is ready. Added in 2.3.2 (operator,
  2026-10-19) because some downloads are not ready to sync; you stop those by
  cancelling the waiting sync, and a scanner that synced them anyway would
  undo that.
- **Sync it** — what the scanner did before: every find is synced.

**Each scan** (`services/auto_scanner.py`):

1. Checks that the service answers. One that does not is a failed scan.
2. Reads the service's library, refreshing the title index.
3. Reads its import history — in Alert only, the last **Look back (days)**
   (default 7) on every scan;
   in Sync it, since the last scan, and the first scan looks back 24 hours —
   covering new episodes, new titles and upgrades. Each import that
   nothing has synced since is a find: no finished copy of its folder started
   after it (see [Sync engine](../sync-engine/README.md), "The scheduled
   auto-scanner").
4. For Sonarr only, also finds seasons this disk keeps but holds fewer
   episodes of than Sonarr has files for, counted as episodes on both sides (a
   double-episode file is two). A season is copied from its real folder on
   the media server into the folder this disk already keeps it in.
5. A find whose folder already has a sync on its way — held for a manual
   sync, in the ready check, queued or copying — is left to that sync. Then:
   - **Alert only** opens one *Missed auto-sync* alert per folder (see below).
   - **Sync it** hands every find to the sync engine as an *Auto-scanner*
     sync, so batching, Sonarr's ready check and the safety check all apply.

It never fetches the backlog. A season this disk holds nothing of, or a title
it has never held, is fetched only when the service imports something for it —
plenty of libraries keep a subset here on purpose. Specials (season 0) are
ignored. A folder the service reports outside the configured library roots is
ignored too, and a season's folder name is read from the service's own files,
so a library that names folders `Season 1` is copied from the folder that
exists rather than one rebuilt by convention.

**Limits.** At most 5 new syncs per scan per service; the rest wait for the next
scan, and the history window does not move past them. A gap the scanner has
started two syncs for and still finds is not tried a third time: an
*Auto-scanner* alert offers **Sync now**, announced as `scanner.found`;
dismissed or marked wrong, it stays closed for 24 hours rather than coming back
at the next scan. An import that landed while its season was mid-copy is looked
at again on the next scan, in case the copy missed it.

**Alert only, in detail** (`AlertService.missed_sync`):

- The alert reads "Missed auto-sync: Example Show — Season 01" with the
  reason ("Sonarr imported season 1 at …, and nothing has synced it since")
  and offers **Open in Explore**, which opens Explore on that series and
  season (or film), and **Dismiss**. There is no Sync now: you look at the
  difference in Explore and sync from there.
- **Skipped syncs are caught.** The look-back read means a sync that was waiting
  while one scan looked, then cancelled, refused or failed, is alerted by a
  later scan once nothing is on its way any more.
- **Once per folder.** Found again on the next scan, an open alert is left as
  it is — no new message, no count going up. Only a newer import (or, for a
  short season, Sonarr holding more episodes) updates it, without a new
  Discord message.
- **Dismissed stays dismissed** until something new is imported for that
  season or film (or a short season grows on Sonarr's side) — not for 24
  hours, as other scanner alerts.
- **Not alerted twice.** A folder that already has an open alert of another
  kind — the safety check's, a failed transfer's, a restart's — gets no
  *Missed auto-sync* alert on top.
- **It closes itself** once a copy of the folder that started after the import
  finishes — a sync from Explore counts. Every scan checks, in either mode.
- One Discord message per scan, `scanner.missed`, lists what it newly alerted.
- Switching to **Sync it** later reads history from the last Alert-only scan,
  so what was already alerted is not then synced in bulk.

**What it leaves behind.** A `scanner.run` entry in the activity trail for every
scan that reached the service, with its summary, and a `scanner.sync_started`
entry for each sync it started; a `scanner.found` message on Discord when it
started anything, or a `scanner.missed` one when it alerted anything; and the
line `Auto-scanner · Sonarr · <summary>` in the
backend log.

**The scheduler.** Both scanners are jobs on DragonCP's general scheduler
(`services/scheduler.py`), which arrived with them in 2.3.0. For each job:

- its switch and interval are read every 5 seconds, so turning it on or off
  needs no restart;
- the first run comes no sooner than 60 seconds after start-up, and not before
  one interval has passed since its previous run;
- it never overlaps itself: a run that falls due while the previous one is
  still going starts when that one finishes;
- its last run and result are kept in `scheduled_job` and survive a restart;
- three failures in a row open a *Scheduler* alert, announced as
  `scheduler.failing`, with **Run now**; the next success closes it. Dismissed
  or marked wrong while the job still fails, it stays closed for 24 hours.

**On screen.** Each service's Connection tab ends with an **Auto-scanner** card
for its job (`sonarr_auto_scanner`, `radarr_auto_scanner`):

- the schedule and the saved mode — "Every 15 min · Alert only, looks back 7
  days, copies nothing · next scan at …" (or "syncs what it finds") — or
  "Switched off",
  with a pointer to the switch above;
- the last scan: "Last scan 5 min ago: …" with its summary, in red when it
  failed, and how many times in a row when more than once;
- up to eight of that scan's finds, each with its first reason and what became
  of it — Started a sync (a link to that sync), Already on its way, Held back
  for the next scan, Waiting for a person, or Could not start; in Alert only,
  Alerted, Alert updated or Already alerted (each a link to Notifications), or
  Dismissed earlier — and "and N more in the activity trail" beyond eight;
- **Scan now**, while the scanner is on; it reads "Scanning…" while a scan runs.

When the job does not run, the card says why it can tell: with the connector
itself turned off, that the service is off and must be turned on first; with
the connector on, that the scanner's switch is off. A connector that is on but
missing its address or API key also reads as switched off. Jellyfin and Discord have no card. There is no
page listing every job: `GET /api/scheduler/jobs` lists them, and
`POST /api/scheduler/jobs/<name>/run` runs one.

Worth knowing:

- **Radarr's scanner reads history only.** The library comparison is Sonarr's
  alone, though the switch's description — shared by both pages — mentions
  missing episodes.
- **A Library-tab Sync is not limited the same way.** A person named the title,
  so every missing or short season is fetched, backlog or not, as manual syncs.
  The series pop-up offers that button (**Copy the series**) only where nothing
  is here yet; a title with something missing beside files kept here gets
  **Get**, which fetches just the missing files through Explore.
- **Nothing carries over from the sweep.** Its fields never shipped in a
  release and nothing reads them: a connector runs the scanner only when its
  own **Scheduled auto-scanner** switch is on, at its own interval (15 minutes
  unless set). A development database that still holds the sweep's fields runs
  no scanner until the switch is turned on. Fixed 2026-10-05: a switch that had
  never been saved used to fall back to the sweep's pair, so the Connection tab
  could show it off while scans ran.

### The Library tab: in sync or not

Until 2026-10-06 a series read **Synced** whenever every season Sonarr held
files for had *some* file here. That answered the wrong question. Behind a media
server that deletes what has been synced, Sonarr holds one file for a season —
the newest episode, E08 — while this disk holds E01 to E07: "some file here" was
true, the card said Synced with "1 file(s) there · 7 here", and E08 was not here.

**One title, exactly.** The series pop-up compares episode by episode
(`services/library_compare.py`): Sonarr's episodes and its files for the series
against the season folders here, read fresh, with SxxEyy read from each name (a
double-episode file covers both; un-renamed anime is matched through Sonarr's
absolute numbers). Each episode gets one state:

| State | Meaning |
| --- | --- |
| In sync | Sonarr has a file, and an episode file here is the same size |
| Upgrade (different file) | both have it, sizes differ — an upgrade over there, or another release |
| Missing here | Sonarr has a file and nothing is here: this needs syncing |
| Nested | here, but only inside a folder below the season folder (`Season 01/ep.mkv/ep.mkv`), where the media server cannot see it — Explore's Repair moves it |
| Only here | here, and Sonarr has no file — normal once the media server cleans up after a sync |
| Not downloaded | neither has it, aired or not |

A title is **out of sync exactly when an episode is Missing here or an
Upgrade**. With neither, a media file in a nested folder — standing for an
episode, or a second copy beside one in place — makes it **Needs repair**
(2.3.2). Specials are compared and shown, never counted. A film is the same
comparison with one file: Radarr's file against the media file in its folder,
or in a folder below it.

**Nested files, and why this tab used to say "Missing here".** Until 2.3.2
this tab read only the files directly inside each season folder, so an
episode stranded at `Season 01/ep.mkv/ep.mkv` read "Missing here" while
Explore — which walks every level — read "In sync", and **Get** then found
nothing to copy. Both now say what is true: it is here, nested, and Repair is
the fix. A copy in place is preferred over a nested one when both exist. The
list does the same from its folder scan: a season's nested files count as
present for the count and size rules (so they are not "a file that is not
here") and add their own reason, `nested`. The scan's `seasons`, `file_count`
and `episodes_here` — what the auto-scanner decides from — still count only
what the media server can see.

**The list, cheaply.** The grid may not ask Sonarr about every title, so it
judges each one from three reads made once for the whole page:

1. Sonarr's count of episodes with a file, per season, against the distinct
   episodes here (read from the names — Sonarr counts a double episode twice).
   More there means something is missing: "Sonarr has 10 episode files for
   season 1, 8 here", or "Season 3 is not here". As many or fewer there — one
   to three episodes — is checked by size: Sonarr's combined size for the
   season (`sizeOnDisk`) must be made of one to that many files in the season
   folder here, since a copied file keeps its size to the byte. When none add
   up, "Sonarr has a file for season 1 that is not here". This is what
   catches one new episode on Sonarr beside seven older ones here even when a
   sync of that folder is on record after the import — a test-mode dry run, or
   a sync that left it out — which rule 2 alone reads as synced. Folder sizes
   are cached by the folder's modification time, so a redraw costs one stat
   per season. Added 2026-10-06, after the beta showed that case as In sync.
2. Sonarr's imports of the last 14 days (`history/since`, the auto-scanner's own
   read, reused for a minute). An episode's latest import that is newer than the
   last completed sync of that season's folder — counted from when the copy
   started (its latest start, if it was paused and resumed), whether a sync run
   or a transfer from before the engine; the auto-scanner's rule, in
   `services/sync_engine/coverage.py`; single-file copies, restores and
   simulated runs do not count — is "1 new episode on Sonarr, imported 2
   days ago", unless the very file is plainly here already: that episode, at the
   size Sonarr imported. Only the latest import counts, because an upgrade
   imports the same episode twice and the first file is gone.
3. For a film, nothing extra at all: Radarr's catalogue carries each film's file
   size, so the card compares file against file.

**Which reasons carry the Upgrade tag.** A newer file imported since the last
sync (rule 2, when the episode is here at a different size) and a file that
differs from the one here (a film by rule 3, or any title opened in the
panel). Rule 1's "a file for season 1 that is not here" does not: from sizes
alone it cannot tell an upgrade from a missing episode. So in the list a Sonarr
upgrade is tagged for 14 days after Sonarr imported it, or once its title is
opened; Explore's Upgrade filter has no such limit. A film's upgrade is tagged
for as long as Radarr holds the file.

Where this disk holds *more* than Sonarr and nothing new arrived, the title is
**kept here**: shown as In sync, with "here 7" underlined and explained on
hover. A title opened in the panel within the last ten minutes shows that exact
answer instead, unless Sonarr has imported something for it since. Without the
history (Sonarr would not send it) only rule 1 applies, and the toolbar says so.

The auto-scanner reads the same list but none of this: it still decides from
`files_here` and `episode_file_count`, which keep their meaning.

### Read-only towards the services

Every request the Sonarr and Radarr adapters make is a GET or HEAD; anything
else is refused in the adapter, in test mode or not. The Library, Queue and
History tabs only read. The one thing those pages do — Sync on a title — acts on
this side, through the sync pipeline like every other sync.

## Storage and secrets

Connectors are a **list**, not a fixed set of keys, which is why they sit
outside `settings_registry`. That registry is right about what it holds:
singleton values whose existence is known at import time. "The three webhooks
this operator added" is not that.

Credentials live in `connector_secret` under one rule: **no read path reaches a
response body.** Not redacted, not partially shown — there is simply nothing to
call. That is easier to keep true than remembering which keys inside a config
blob need masking. What the API returns instead is `secrets_set`: whether a
value exists.

They are stored unencrypted, the same as the Discord webhook URL was before
this. Anyone who can reach the Integrations page can make the server issue
requests to its own network — already true of this app's threat model of one to
three trusted administrators on a private network, and worth stating rather
than discovering. Discord destinations are restricted to Discord hosts because
a webhook URL has exactly one legitimate shape.

The auto-scanner's switch and interval are connector settings for the same
reason the connectors are: two services can want different schedules, and one
can be on while the other is off. What the scanner remembers lives elsewhere —
the last scan time per service in `app_settings`
(`AUTO_SCANNER_LAST_SCAN_SONARR`, `AUTO_SCANNER_LAST_SCAN_RADARR`), each gap and
how many syncs it has had in `sweep_finding`, and each job's last result in
`scheduled_job`.

## The upgrade from 2.2.x

Automatic and invisible, in `DatabaseManager._migrate_discord_to_connector`.
On the first start after upgrading:

1. A stored `DISCORD_WEBHOOK_URL` becomes a destination called **Default**,
   marked as the connector's default.
2. `DISCORD_NOTIFICATIONS_ENABLED` becomes the connector's on/off state.
3. The app, icon and thumbnail URLs move into the connector's settings.
4. **No routing rows are written.** Every notification falls through to the
   default, which is exactly what it did before.
5. The five `DISCORD_*` rows are deleted from `app_settings`, so no value has
   two homes.

Guarded on the connector row already existing rather than on a version number,
so it is safe to run on every start and safe to run twice. An install that
never configured Discord gets no connector row, so the page shows it as never
configured rather than configured-and-empty.

## Adding a connector

One file in `services/connectors/adapters/`, plus one import line in that
package's `__init__.py`. Nothing else changes — not the API, not the sidebar,
not the settings form, which are all driven by what the adapter declares.

```python
@register
class ExampleConnector(Connector):
    id = 'example'
    display_name = 'Example'
    capabilities = frozenset({CAP_QUERY})
    config_fields = (
        ConfigField('base_url', 'Address', kind='url', required=True),
        ConfigField('api_key', 'API key', kind='password', secret=True, required=True),
    )

    def check(self) -> CheckResult:
        ...
```

The only frontend change a new connector might want is an icon, in
`frontend/src/components/integrations/connector-icon.tsx`. Without one it gets
a plug. A connector that declares `CAP_QUERY` also gets the Library, Queue and
History tabs, which only Sonarr and Radarr can fill — see Jellyfin above.

## What is not here yet

- **Radarr is never asked whether a film is still downloading** — decided: a
  Radarr webhook means a finished film. The check exists and is unused.
- **Jellyfin** connects and tests; nothing reads it, and its page shows tabs
  whose endpoints do not serve it.
- **The scheduler has two jobs**, the auto-scanners. Nothing else DragonCP does
  on a clock has been moved onto it.
- **Not verified:** the Ready check has not yet been watched against a real
  Sonarr download, nor a scan read against a live library — the live run in
  TASK-020 is still open.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| — | `/api/connectors/…` | Connectors, destinations, routing and tests — see [the API reference](../../reference/api.md#connectors) |
| GET | `/api/library/<source>` | The Library tab for `sonarr` or `radarr`: each title's state and why; `refresh=1` re-reads the catalogue first |
| GET | `/api/library/<source>/<external_id>` | The series pop-up: one title by its TVDB or TMDB id, episode by episode, with what to do about it |
| GET | `/api/library/<source>/<external_id>/history` | The pop-up's History: the service's events for the title beside DragonCP's syncs of its folder, newest first |
| GET | `/api/library/<source>/queue` | The Queue tab: rows, verdicts in plain words, and which hold a sync |
| GET | `/api/library/<source>/history` | The History tab, a page at a time (`page`, `page_size`, `event`) |
| POST | `/api/library/<source>/sync` | Sync one title's missing or short seasons, or the film: `{"external_id": "…"}` |
| POST | `/api/library/<source>/refresh` | Re-read the service's catalogue into the title index |
| GET | `/api/scheduler/jobs` | The auto-scanner jobs: switch, interval, last and next run, last result |
| POST | `/api/scheduler/jobs/<name>/run` | Run a job now |

## Related

- [Notifications](../notifications/README.md) — what each message contains,
  and the alerts behind the newer ones
- [Sync engine](../sync-engine/README.md) — the pipeline the Ready check and the
  auto-scanner's finds go through
- [Webhooks](../webhooks/README.md) — the inbound side, Radarr and Sonarr
  pushing to DragonCP
- [Auto-sync](../auto-sync/README.md) — the automatic-sync switches
- [Settings](../settings/README.md) — the app-level settings that stayed there,
  including the fallback wait
- [API reference](../../reference/api.md#connectors)
