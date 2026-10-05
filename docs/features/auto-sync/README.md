# Automatic sync

Last updated: 2026-10-05

Whether a Sonarr or Radarr webhook starts a sync by itself, and when. Three
switches decide whether — one each for movies, TV shows and anime — and for TV
shows and anime, Sonarr decides when: the season starts once Sonarr has nothing
more for it on the way. Everything a sync does after that is the
[sync engine](../sync-engine/README.md)'s pipeline; this page covers only what
"automatic" adds to it.

## Where it lives

| Concern | File |
|---|---|
| The three switches and the fallback wait | `settings_registry.py` (`AUTO_SYNC_MOVIES`, `AUTO_SYNC_SERIES`, `AUTO_SYNC_ANIME`, `SERIES_ANIME_SYNC_WAIT_TIME`) |
| Handing every webhook to the engine, held or not | `routes/webhooks.py` (`_submit_webhook`) |
| The ready check: asking Sonarr, the fallback timer | `services/sync_engine/engine.py` (`_ready_step` and below) |
| Sonarr's answer: downloading, stuck, time left | `services/connectors/adapters/_arr.py` (`InFlight`, `classify_row`) |

## How it works

### 1. The webhook is stored and handed to the engine

Always, whatever the switch says. With the switch **off**, the batch is opened
and **held**: the Pipeline page lists it as *Waiting for a person*, under
*Needs a person*, and pressing Sync on any of its webhooks (or **Sync now** on
the batch's own page) sends the whole batch. With the switch **on**, it carries
on to the ready check.

### 2. Movies go straight on

A Radarr webhook is one finished movie: the ready check is skipped and the
safety check runs at once.

### 3. TV shows and anime wait until the season is ready

The webhooks for one season gather into one batch. Ten seconds after the batch
opens, Sonarr is asked whether anything else for that season is still
downloading, and asked again by its own time-left estimate (10 seconds to 5
minutes apart) until nothing is. A download stuck in Sonarr is not waited for;
a slow one is waited for at most 30 minutes. Details and the alerts each case
raises: [ready check](../sync-engine/README.md#4-ready-check--still-downloading).

### 4. When Sonarr cannot be asked, the fallback timer decides

Sonarr not connected, not answering, or the series has no TVDB id: the season
starts **Fallback wait** seconds after the first webhook (default 60, allowed
30–900), plus the same again for each later webhook, never more than 15
minutes after the first. There is no switch for asking Sonarr — whether it
answers decides.

The screens say the same. Settings → Automation labels the field **Fallback
wait (seconds)** and explains it is used only when Sonarr cannot be asked, and
the Auto-sync popover on the Webhooks page reads "TV & anime start once Sonarr
has nothing more for the season; if Sonarr cannot be asked, Ns after the last
episode." Until 2026-10-05 both still described the old fixed wait.

## Behaviour worth knowing

- **Switching automatic sync on does not start batches already held.** They
  wait for a person, or for the next webhook for the same folder, which sets
  the held batch going.
- **A lost webhook is not noticed by automatic sync.** The
  [scheduled auto-scanner](../sync-engine/README.md#the-scheduled-auto-scanner)
  is what catches those, when it is switched on.
- **An automatic sync never goes ahead past a failed safety check.** It stops,
  opens an alert and announces "automatic sync refused" on Discord; only an
  admin can choose **Sync anyway**, on the alert (Notifications) or on the
  sync's own page (Pipeline). Its webhooks read **Manual** on the Webhooks page
  until then.
- **A batch a person released is a manual sync from then on.** Sync on any of
  its webhooks, or Go now, while the batch is held or still in its ready check
  — or a restart that joins it — releases it. A refusal then opens the alert
  without the Discord announcement, and the result is announced as "Manual
  Sync". With the switch off, that is every batch. Until 2026-10-05 a released
  batch kept its automatic label and its refusal was announced.

## Data

Webhooks keep their `status` in step with the run they ride on: `pending`
while waiting (with `auto_sync_scheduled_at` set to the next ready-check step),
`READY_FOR_TRANSFER`, `QUEUED_SLOT` or `QUEUED_PATH` in the queue, `syncing`
while copying, then `completed`, `failed` or `cancelled`. A sync stopped for a
person sets `requires_manual_sync` and `manual_sync_reason`. Each webhook names
its run in `sync_run_id`.

## API

No endpoints of its own. The switches are saved through the settings API; the
runs are read through [the sync engine's API](../sync-engine/README.md#api).

## Related

- [Sync engine](../sync-engine/README.md) — the pipeline every sync follows
- [Webhooks](../webhooks/README.md) — the receivers
- [Settings](../settings/README.md) — where the switches are
- [Archived V3 design](../../archive/auto-sync-flow-v3.md) — the in-memory scheduler this replaced
