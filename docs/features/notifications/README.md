# Notifications

DragonCP announces ten things. Four report work as it ends: a sync finished, a sync failed, a file rename finished, and the retention rule deleted old backups. Six come from the sync engine and are about something a person should know or decide: an automatic sync refused to run because it looked unsafe, a restart may have left a sync undone, a season went ahead without a download that is stuck in Sonarr or still going after 30 minutes, the auto-scanner found something to sync, Sonarr stopped answering, and a background job keeps failing. A sync message carries the title involved, the folder it landed in, how many files moved, how fast, which kind of sync it was, and - for webhook-driven syncs - who requested it and the poster image for the show or film.

Everything that needs a person is also kept in the application as an **alert**, listed on the **Notifications** page (sidebar → Workspace → Notifications, or the bell in the header), where each alert waits with the actions that make sense for it - Sync now, Retry, Sync anyway, Run now, Mark as done, Mark as wrong, Dismiss. The page has **Open** and **Closed** tabs; **Sync anyway** asks to confirm; each alert about a sync links to it (**Open the sync**); a closed one says who closed it and how. While anything is open the bell carries a dot and the sidebar item a count, and with realtime on a toast says when a new one opens. The page arrived on 2026-10-05; before it, alerts could be read and acted on only through the API, so the Discord message was the alert.

**Where those messages go is configured under Integrations, not here.** How the connector layer decides which destination each announcement uses, how it delivers without blocking the caller, and how credentials are stored is [the integrations page](../integrations/README.md). This page is about what each message contains and what triggers it. The pipeline that produces most of them is [the sync engine](../sync-engine/README.md).

Everything is off until an operator turns Discord on and adds a webhook. There is no default destination. Alerts are recorded either way.

Last updated: 2026-10-05
Primary files: `services/notification_service.py`, `services/sync_engine/engine.py`, `services/alert_service.py`, `services/auto_scanner.py`, `services/connectors/adapters/discord.py`, `services/connectors/events.py`

## Where it lives

| Concern | File |
| --- | --- |
| What a sync message says, log parsing, error extraction | `services/notification_service.py` |
| When a finished sync is announced, and with which label - the pipeline's Tell stage | `services/sync_engine/engine.py` (`_tell`, `_SYNC_LABEL`) |
| Transfers with no sync run behind them (started before 2.3.0) | `services/transfer_coordinator.py` (`_post_transfer_completion`) |
| Alerts: wording, actions, deduplication, and the one Discord message each | `services/alert_service.py`, stored by `models/alert.py` |
| What opens each alert | `services/sync_engine/engine.py`, `services/sync_engine/recovery.py`, `services/auto_scanner.py`, `services/scheduler.py` |
| The Notifications page, the bell and the sidebar count | `frontend/src/components/pages/notifications.tsx`, `frontend/src/components/pipeline/alert-card.tsx`, `frontend/src/hooks/useSync.ts` (`useAlerts`, `useAlertSummary`, `useAlertAction`) |
| The auto-scanner's report | `services/auto_scanner.py` (`_announce`) |
| Trigger for the rename notification | `services/rename_service.py` (`process_rename_webhook`) |
| Trigger for the retention notification | `services/backups/service.py` |
| The list of announcements that exist | `services/connectors/events.py` |
| Turning an announcement into a Discord embed | `services/connectors/adapters/discord.py` |
| Where each announcement goes, and delivery | [Integrations](../integrations/README.md) |

## How it works

### Gate

There is no gate in this file any more. Every announcement is one `notify()` call describing what happened; whether it is sent, and where, is decided by the connector layer - the connector has to be on, the notification has to be switched on, and there has to be a destination. Every one of those decisions is recorded with a reason, visible on the connector's Activity tab.

A fresh install announces nothing until an operator adds a webhook.

### One look for every message

Since 2.3.2 every message follows one scheme, so a glance says what kind it is:

- **The headline**, the line above the title, says what happened as
  `TOPIC - DETAIL` in upper case (`headline()` in
  `services/connectors/events.py`). The Discord adapter upper-cases it again,
  so no sender can bring back its own style. The sync and alert headlines are
  in their sections below; the rest are FILE RENAME - COMPLETED / PARTIAL /
  FAILED, BACKUP RETENTION - VERSIONS DELETED, AUTO-SCANNER - SYNCS STARTED,
  MANUAL SYNC NEEDED - SONARR (`sync.held`), and TEST - MESSAGE / TEST - PING.
- **The title** is what it happened to: a show and season, a film, a job.
- **The footer** is the same on every message, `DragonCP v<version>`, and
  Discord adds the time after it. It used to differ per sender - "DragonCP
  Rename Operation", "DragonCP Backup Retention", "DRAGONCP Auto-Sync Safety
  Check", or none.
- The colour still carries the outcome: purple for done or news, amber for a
  warning, red for a failure, teal for a finished rename.

### Sync finished or failed

Every sync runs through the sync engine's pipeline, and its last stage, **Tell**, sends this message. When a transfer settles, the completion watcher started with it (`TransferCoordinator._post_transfer_completion`, polling the transfer row every 5 seconds) releases the queue slot and hands the outcome to the engine. The engine's Finish stage marks the batch's webhooks; Tell then calls `NotificationService.send_discord_notification(transfer_id, status, sync_label=...)`.

| Outcome | On Discord | Alert |
| --- | --- | --- |
| Completed | "Sync finished" (`transfer.completed`) | - |
| Failed | "Sync failed" (`transfer.failed`) | *Failed*, with Retry - not announced a second time |
| Failed because a restart lost the result - rsync was already gone when DragonCP started again, or ended where DragonCP could not read how | No "Sync failed". The *Result unknown* alert is announced instead (`sync.interrupted`) | *Result unknown*, with Retry and Mark as done |
| Cancelled | Nothing: whoever cancelled it already knows | - |

Two kinds of sync never announce, and their Tell stage says so: simulations - a restarted simulated transfer included - and backup restores. A sync that stops before it becomes a transfer never sends this message either. A safety-check refusal is told through its own alert (below); a sync the queue would not start opens a *Failed* alert, which is not announced; one whose folders could not be worked out is only recorded on its run.

A transfer with no run behind it - one started before 2.3.0 and still running or queued across the upgrade - is finished the old way: the watcher updates its webhook rows and calls `send_discord_notification(transfer_id, status)` itself, for `completed` and `failed` only.

**The headline.** The engine passes how the sync started (AUTO or MANUAL) and where from, which become the line above the title, in upper case:

| Kind of sync | Headline |
| --- | --- |
| Sonarr or Radarr webhook | AUTO SYNC - SONARR / AUTO SYNC - RADARR |
| The scheduled auto-scanner | AUTO SYNC - SCANNER |
| A press of Sync - Webhooks page, a Library tab, an alert - or `POST /api/transfer` | MANUAL SYNC - SONARR / RADARR, or MANUAL SYNC when no service is behind it |
| A Sonarr, Radarr or auto-scanner batch a person released - Sync or Go now while it was held or waiting, or a restart that joined it | MANUAL SYNC - SONARR / RADARR / SCANNER |
| Restart | MANUAL SYNC - RESTART |
| An approved Explore plan | MANUAL SYNC - EXPLORE |

A failed sync says so in the topic: AUTO SYNC FAILED - SONARR, MANUAL SYNC FAILED - EXPLORE. Without the engine's answer - only transfers with no run - the old guess applies: a movie transfer that matches a webhook row is AUTO SYNC - RADARR; a series/anime transfer that matches a webhook row is AUTO SYNC - SONARR only if that row has an `auto_sync_scheduled_at` value; everything else is MANUAL SYNC. Until 2.3.2 these read "Automated Sync", "Auto-scanner", "Manual Sync", "Manual Sync (restart)", "Explore" and "… - FAILED ❌".

**What it says** (2.3.2), in this order:

1. Title: `parsed_title` (falling back to `folder_name`), with the season added - "Example Show — Season 03".
2. **Synced (N)** - one line per media file the copy wrote, read from rsync's own log (`copied_files()`: `rsync -v` names each file, an Explore copy logs `%i|%l|%n`): the episode code, the episode title from Sonarr's file name, and "— upgrade to WEBDL-1080p" when an older file of the same episode was removed in the same copy. Ten lines at most, then "… and N more". Subtitles and artwork are not listed. A copy that wrote nothing says "Nothing new: every file was already here." A failed copy calls it **Copied before it stopped (N)**.
3. **Transfer** - the route the copy took: ⚡ FAST, SSH, or SSH FALLBACK (fast route failed). Left out for a transfer that recorded none (before 2.3.1).
4. **Size** and **Speed** from rsync's summary ("4.12 GB", "31.20 MB/s"); a failure shows **Error Details** instead.
5. **Removed** - files rsync removed that were not the old half of an upgrade, "2 files (kept in Backups)": every copy runs with `--backup`.
6. **Requested by**, when the linked webhook names someone, and **Folder**, the destination path.

The poster comes from the linked webhook notification, if there is one.

To find the linked notification the service switches on the transfer's `media_type`: `movies` searches the Radarr notification table, `series` / `anime` / `tvshows` search the Sonarr notification table. If a row is found, its `poster_url` replaces the default thumbnail and its `requested_by` is added as a field. Syncs with no webhook linked to them - the auto-scanner, a Library-tab Sync, Explore - find none.

Success embeds use purple (`11164867`) and carry Files Info and Speed Info blocks. Failure embeds use red (`15158332`), replace those with an Error Details block, and append a Partial Transfer Stats block only when the log yielded a file or delete count.

### Parsing statistics out of the rsync `--stats` output

The transfer rsync command in `services/transfer_service.py` is built with `--stats` and `--human-readable`, and every non-progress line rsync writes is appended to the transfer's stored log, so the summary block rsync prints at the end of a run is there to read. `parse_transfer_logs()` walks those lines and pulls six values with regular expressions:

| Field | Source line | Regex target |
| --- | --- | --- |
| `regular_files_transferred` | `Number of regular files transferred: 1` | integer |
| `deleted_files` | `Number of deleted files: 0` | integer |
| `total_transferred_size` | `Total transferred file size: 3.70G bytes` | the number + unit letter, e.g. `3.70G` |
| `bytes_sent`, `bytes_received`, `avg_speed` | `sent 103 bytes  received 3.70G bytes  4.68M bytes/sec` | three number+unit tokens from one line |

The speed/bytes line is only considered if it contains all of `sent`, `received`, `bytes` and `bytes/sec`, which keeps it from matching ordinary file lines. `avg_speed` is stored with the literal suffix ` bytes/sec` appended to the captured token, so the message reads `4.68M bytes/sec`.

Anything not found stays `None` and is rendered as `N/A` in the embed. If the parser throws, it returns an empty dictionary and the embed falls back to `N/A` everywhere.

The pipeline's Transfer stage writes its own one-line summary of a finished copy (files copied, deleted, size moved, speed) from the same parser.

### Error extraction for failed transfers

For a failed transfer only, `extract_rsync_errors()` scans the log forward and keeps lines that either contain `rsync:` together with `error` or `failed`, or contain any of `no space left on device`, `permission denied`, `connection refused`, or `timeout` alongside `rsync` - all case-insensitive. Only the last 10 matches are kept, joined with newlines, and truncated to 1000 characters before being wrapped in a code fence. If nothing matched, the transfer's current `progress` text is used instead, so the Error Details field is never empty.

### Alerts - what needs a person

An alert is opened by the sync engine, by its start-up recovery, by the auto-scanner, by the scheduler or by a copy that falls back from the fast route, and stays open until an admin acts on it. There is one open alert per subject: the same thing happening again while it is open bumps its count rather than opening a second. The four that watch a condition rather than report an event - *Auto-scanner*, *Integration*, *Scheduler* and *Fast transfers* - also stay closed for 24 hours once a person dismisses them or marks them wrong. Each alert is announced through the connector layer once, when it opens - except *Failed*, whose Discord message was the Tell stage's "Sync failed".

| Alert | Opens when | Discord event | Actions |
| --- | --- | --- | --- |
| After a restart | A sync was in its ready check or safety check when DragonCP stopped. Also, once, for webhooks the pre-2.3.0 scheduler had taken and a restart dropped (up to 7 days back) | `sync.interrupted` | Sync now · Mark as done · Mark as wrong · Dismiss |
| Result unknown | A restart lost the result of a copy | `sync.interrupted` | Retry · Mark as done · Dismiss |
| Stuck download | A season was let through its ready check while something for it was stuck in Sonarr | `sync.stuck` | Dismiss |
| Waited 30 minutes | A season's ready check stopped waiting after 30 minutes with Sonarr still downloading | `sync.stuck` | Dismiss |
| Safety check | The dry run stopped a sync | `autosync.blocked`, automatic syncs only | Sync anyway · Dismiss |
| Failed | A transfer failed, or the queue would not start it. A failed restore's is titled "Restore failed" and says to run it again from the Backups page | none | Retry · Mark as done · Dismiss; a restore's, Dismiss only |
| Auto-scanner | The scanner has started two syncs for a gap and still finds it | `scanner.found` | Sync now · Dismiss |
| Integration | Sonarr did not answer when a batch asked; closes itself when a later batch finds it answering | `integration.down` | Dismiss |
| Scheduler | A background job failed three times in a row; closes itself on the job's next success | `scheduler.failing` | Run now · Dismiss |
| Fast transfers | A copy failed on the fast transfer server and ran again over SSH. One alert for the route: every later fallback bumps it | `fast_route.failed` | Dismiss |

Every alert reads the same on Discord: a headline for its kind, as the table below; as the title, what it is about - the alert's own title after its "…: " (so "Sync stopped by the safety check: Example Show — Season 04" posts as "Example Show — Season 04" under SAFETY CHECK - AUTO SYNC STOPPED); its sentence as the description; whatever labelled fields that kind carries (the reason and the counts, what is stuck, how many webhooks were waiting; a Folder as a path); and a last field, **What to do**, reading "Open DragonCP → Notifications to act on it." - the Notifications page in the sidebar.

| Alert | Headline |
| --- | --- |
| After a restart | AFTER RESTART - SYNC MAY BE SKIPPED |
| Result unknown | AFTER RESTART - RESULT UNKNOWN |
| Stuck download | READY CHECK - STUCK DOWNLOAD |
| Waited 30 minutes | READY CHECK - WAITED 30 MINUTES |
| Safety check | SAFETY CHECK - AUTO SYNC STOPPED |
| Auto-scanner | AUTO-SCANNER - GAP NOT CLOSED |
| Integration | INTEGRATION DOWN - SONARR |
| Scheduler | SCHEDULER - JOB FAILING |
| Fast transfers | FAST TRANSFER FAILED - SSH FALLBACK USED |

Until 2.3.2 every alert's author line was "DragonCP Notifications"; warnings are orange (`15105570`, the colour of a partial rename).

What each action does is on [the sync engine page](../sync-engine/README.md), under *Alerts*.

### The safety-check message

This replaces the "manual-sync alert" of earlier releases. When the Safety check stage's dry run looks unsafe, the engine stops the sync before anything is written, flags its webhooks for manual sync, and opens a *Safety check* alert. The alert is announced (`autosync.blocked`) only when the sync started by itself - a Sonarr or Radarr webhook batch, or an auto-scanner find, that nobody released - because an admin who pressed Sync, or released a held or waiting batch with Sync or Go now, is already looking at it.

- Headline: `SAFETY CHECK - AUTO SYNC STOPPED`. It names what happened: an automatic sync stopped because its dry run would have deleted more files than it copied, or found fewer media files on the remote server than here. (Before 2.3.0 it read "Manual Sync Alert ⚠️", which named what a person had to do rather than what happened.)
- Title: `Example Show — Season 01`.
- Description: "Nothing was copied or deleted." The reason and the counts are in the fields, not repeated here.
- Fields: Reason; File analysis, one line each - media files on the remote server, here, would delete, would add; Folder (the local destination); What to do.

One message per batch, not per episode: a batch is one folder, so six episodes refused together are one message.

Before 2.3.0 this was a gold (`15844367`) embed titled with the series and season number, authored `Manual Sync Alert ⚠️`, footed `DRAGONCP Auto-Sync Safety Check`, and showing the remote season path. Its sender, `TransferCoordinator.send_manual_sync_discord_alert`, stayed in the file with nothing calling it until 2.3.2 removed it.

Movies are checked now too. A Radarr webhook runs the same dry run, so a film can be stopped and announced the same way; before 2.3.0 a movie webhook started its transfer with no dry run at all.

### The auto-scanner's report

After a scan that started anything, one message per service: "Auto-scanner found 3 to sync in Sonarr", listing up to ten of the syncs it started, each with its first reason ("Sonarr imported season 1 at 2026-10-05 14:02, and nothing has synced it since."), and how many were held back for the next scan. Headline AUTO-SCANNER - SYNCS STARTED, purple (the info colour). Each of those syncs then gets its own finished or failed message, headed AUTO SYNC - SCANNER. A scan that started nothing sends nothing.

The *Auto-scanner* alert uses the same event key, so routing `scanner.found` routes both.

### Rename notification

`RenameService.process_rename_webhook()` calls `send_rename_discord_notification()` after a rename batch finishes. The embed colour tracks the outcome: teal (`1752220`) for `completed`, orange (`15105570`) for `partial`, red (`15158332`) for `failed`. It lists the media type, the status, a totals block, and the first five resulting file names (prefixed `✓` or `✗`) with an "... and N more files" line beyond that, truncated to 900 characters. Headline FILE RENAME - COMPLETED (or PARTIAL, FAILED); until 2.3.2 it was authored "File Rename" and footed `DragonCP Rename Operation`.

### The app URL

The connector's **App URL** is attached as the embed's clickable `url`, but only after passing `is_valid_app_url()` - a regex accepting `http`/`https` with a domain, `localhost`, or a dotted IPv4, with an optional port and path. It is deliberately permissive because this is a private deployment and the value is routinely a Tailscale IP. Discord rejects an embed outright if the URL is malformed, so an invalid value costs the link and nothing else. The check exists once, in `adapters/discord.py`; before 2.3.0 the same regex was copied into three files.

## Behaviour worth knowing

- **The statistics can come from the wrong rsync run.** `parse_transfer_logs()` iterates the log in reverse but never breaks out of the loop, so every match overwrites the previous one and the value that survives is from the *earliest* matching line in the stored log, not the latest. A transfer that was paused and resumed (or otherwise wrote more than one `--stats` block into the same log) will report the first run's numbers - and so will the Transfer stage's summary in the pipeline, which reads the same parser.
- **Of a transfer's outcomes, only finished and failed are announced.** Cancelled and paused transfers never are. A pause is treated as "not an outcome" throughout the coordinator, and a cancelled sync's Tell stage records why it stayed quiet.
- **A restart is announced.** It runs through the pipeline as a sync of its own - safety check, queue, then the usual finish - so its result arrives labelled "Manual Sync (restart)". A restarted simulated transfer is the exception (below), and a restore is never restarted. Before 2.3.0 `TransferCoordinator.restart_transfer()` started rsync with no completion watcher, and the restarted run finished without a message.
- **A batch a person released is a manual sync.** Pressing Sync on a webhook whose batch is still open does not start a second sync: it tells that batch to go now, as Go now on the batch does, and so does a restart that joins it. From then on the batch counts as a person's: its result is announced as "Manual Sync", and if its safety check stops it, the alert opens without an `autosync.blocked` message. With automatic sync off - where every webhook opens a batch held for a person - that is every sync. A press that finds the batch already past its ready check does not release it, and the batch keeps the label of the kind that opened it. Fixed 2026-10-05: a released batch used to keep its kind, so a sync an admin started was announced as "Automated Sync", and a refusal of it as an automatic one.
- **A batch held for a person is announced once.** With automatic sync off for a library, each new batch posts `sync.held` ("Waiting for a manual sync") to Discord when it opens, and pings by default, so whoever needs to press Sync is told. Webhooks that join the batch later send nothing more, and a held batch that survives a restart is not announced again. It is not an alert on the Notifications page: the Webhooks page already shows those webhooks as **Manual**, with Sync beside them. Added in 2.3.2 (issue #35).
- **A manual sync the safety check stops is not announced.** Its alert opens on the Notifications page, where **Sync anyway** is, and any webhook linked to it reads **Manual** on the Webhooks page. Until the page arrived on 2026-10-05 the manual-sync flag on those webhooks was the only visible trace.
- **"Result unknown" covers a copy whose rsync was gone at start-up.** A `running` transfer whose rsync process no longer exists when DragonCP starts is recorded as failed with the "Result unknown: ..." sentence, so it gets the *Result unknown* alert, not "Sync failed": it may have finished before DragonCP stopped, or been cut off with it. Until 2026-10-05 it was recorded as "Transfer process was interrupted" and announced as a failed sync, with a *Failed* alert.
- **Backup restores never notify.** A restore is recorded in the pipeline (kind `restore`), and its Tell stage records that restores are not announced: the result is on the Backups page and in the activity trail. A failed restore does open an alert, which is not announced either: titled "Restore failed", saying to run it again from the Backups page, and offering only Dismiss - a restore is never retried from the transfer list.
- **Simulations do not notify.** They run through the pipeline as kind `simulation`, whose Tell stage is skipped ("Rehearsals are not announced on Discord."), and a failed simulation opens no alert. A restarted simulated transfer is treated the same: a restart is kind `restart` whatever it retries, but its run carries the simulation flag, and Tell skips any run that does. Fixed 2026-10-05; before, a restarted simulation's result was announced like real work. See [../simulation/README.md](../simulation/README.md).
- **"Result unknown" needs a run.** A transfer started before 2.3.0 whose result was lost in the upgrade restart is finished the old way, so it is still announced as "Sync failed", with the "Result unknown: ..." sentence as its Error Details.
- **Dismissing a recurring alert quiets it for a day.** Alerts are deduplicated while open. Once a person dismisses an *Auto-scanner*, *Integration* or *Scheduler* alert, or marks it wrong, the same subject opens - and announces - no new alert for 24 hours (`QUIET_AFTER_DISMISS` in `services/alert_service.py`). After that, if the cause is still there the next time it is checked - the auto-scanner looks at every scan, the scheduler at every run - the alert opens and is announced again. Alerts that each report one event - after a restart, result unknown, stuck download, waited 30 minutes, safety check, failed - are not affected. Fixed 2026-10-05: a dismissed recurring alert used to come back at the very next check, so a Sonarr season the scanner kept finding short, or a scan that kept failing, was announced again every 15 minutes at the default interval.
- **The *Integration* alert closes only when Sonarr is asked again.** That happens when a later Sonarr batch reaches its ready check. Until one does, the alert stays open however long Sonarr has been back. Only Sonarr raises it: nothing asks Radarr that question.
- **New announcements need no setup.** A route that was never configured means the default destination, so the five added in 2.3.0 go to the default webhook from the first time they fire. Each can be switched off on the Discord page's **Routing** tab (called Notifications until 2026-10-05; the name now belongs to the alerts page).
- **The "default thumbnail" is not manual-sync-only.** It is the fallback for *every* message with no image of its own; a poster URL only overrides it when a matching notification row is found. Automated syncs with no poster, alerts and the auto-scanner's report all show this image.
- **The notification lookup is a full table scan.** `send_discord_notification` calls `get_all()` on the notification model and loops looking for a matching `transfer_id`, even though both models expose an indexed `get_by_transfer_id()`. `get_all()` is called with no limit, so the cost grows with notification history.
- **A rejected message is retried once.** The transport tries again on 429 and on 500, 502, 503 and 504 only, honouring `Retry-After` up to ten seconds; anything else is given up. Each delivery's outcome is listed on the connector's Activity tab.
- **Nothing here can fail what it describes.** Every sender wraps its work in a `try/except` that prints a traceback and returns, and opening an alert never raises either, so a broken notification never fails the transfer, the rename, the scan or the scheduler job.
- **The message timestamp is send time.** Embeds are stamped at the moment of sending, not with the transfer's `end_time`. The watcher polls on a 5-second interval, so the timestamp can lag the actual finish.
- **A rename that could not be recorded does not notify.** If the rename history row fails to update, `process_rename_webhook` returns before reaching the Discord call.
- **A Discord destination must be a Discord URL.** The server posts to whatever is stored, so `DiscordConnector.validate_target` requires `https`, a host in the Discord set, and `/api/webhooks/` in the path. Before 2.3.0 there was no host restriction at all.
- **Logs are capped at 5000 lines** (`LOG_MAX_LINES` in `models/transfer.py`), trimmed from the *front*. That is deliberate so the `--stats` summary and any trailing errors survive, which is exactly what these notifications need.

## Data

| Table | Use |
| --- | --- |
| `connector`, `connector_secret`, `connector_target`, `notification_route`, `connector_delivery` | Where announcements go, and what happened to each - see [Integrations](../integrations/README.md) |
| `sync_run` | The kind of sync behind a transfer, which picks the label; the outcome sentence that marks a result lost in a restart |
| `alert` | One row per alert: kind, severity, title, sentence, state (`open`, `done`, `wrong`, `dismissed`), the deduplication key, how often it recurred while open, the actions offered, and who closed it and how |
| `transfers` | Reads `status`, `logs`, `progress`, `parsed_title`, `folder_name`, `dest_path`, `media_type`; `sync_run_id` says whether the engine finishes it |
| `radarr_webhook` | Reads `transfer_id`, `poster_url`, `requested_by` for movie transfers |
| `sonarr_webhook` | Reads `transfer_id`, `poster_url`, `requested_by`, and `auto_sync_scheduled_at` for the label guess on transfers with no run. The engine now writes `auto_sync_scheduled_at` while a batch waits - the time it will next look - so on its own it no longer means "went through the old scheduler" |
| `rename_webhook` | Not read directly - the rename embed is built from the result dictionary `RenameService` passes in |

The five `DISCORD_*` settings keys that used to appear here are gone. They became connector rows in 2.3.0 and are migrated automatically on first start.

Full schema: [../../reference/database-schema.md](../../reference/database-schema.md)

## API

Announcements are produced internally; configuring where they go is the connector API, under `/api/connectors` - see [the API reference](../../reference/api.md#connectors).

The alerts behind the Notifications page have their own endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/alerts` | Alerts, newest first. `state` = `open` (default), `done`, `wrong`, `dismissed`, several of them comma separated (the Closed tab asks for `done,wrong,dismissed`), or `all`; `kind` filters, and `total` counts what the filters match |
| GET | `/api/alerts/summary` | How many are open, by severity - the bell's dot and the sidebar count |
| POST | `/api/alerts/<alert_id>/action` | Act on one: `{"action": "sync_now"}`, or `retry`, `sync_anyway`, `run_now`, `mark_done`, `mark_wrong`, `dismiss` |

Socket event: `alerts_changed`, carrying the open counts, whenever an alert opens, recurs or closes. With realtime on, the app writes those counts straight into the bell and the sidebar, refreshes the alert lists, and shows a toast when the count rises; the page polls every 30 seconds either way. Full contracts are on [the sync engine page](../sync-engine/README.md).

`/api/discord/settings` and `/api/discord/test` were removed in 2.3.0.

## Related

- [../sync-engine/README.md](../sync-engine/README.md) - the pipeline whose Tell stage sends sync messages, and what each alert action does
- [../integrations/README.md](../integrations/README.md) - where these messages go, and how they get there
- [../queue/README.md](../queue/README.md) - the completion watcher that hands a finished transfer to the engine is the same one that releases queue slots
- [../auto-sync/README.md](../auto-sync/README.md) - the automatic-sync switches whose syncs these messages report
- [../simulation/README.md](../simulation/README.md) - rehearsals are not announced
- [../backups/README.md](../backups/README.md) - restores are not announced; retention is
- [../../architecture/system-overview.md](../../architecture/system-overview.md)
- [../../reference/api.md](../../reference/api.md)
- [../../reference/database-schema.md](../../reference/database-schema.md)
