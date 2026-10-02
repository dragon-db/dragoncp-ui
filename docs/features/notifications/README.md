# Notifications

DragonCP announces five things: a sync finished, a sync failed, a file rename finished, the retention rule deleted old backups, and an automatic sync refused to run because it looked unsafe. Each message carries the title involved, the folder it landed in, how many files moved, how fast, and - for notification-driven syncs - who requested it and the poster image for the show or film.

**Where those messages go is configured under Integrations, not here.** How the connector layer decides which destination each announcement uses, how it delivers without blocking the caller, and how credentials are stored is [the integrations page](../integrations/README.md). This page is about what each message contains and what triggers it.

Everything is off until an operator turns Discord on and adds a webhook. There is no default destination.

Last updated: 2026-08-17
Primary files: `services/notification_service.py`, `services/transfer_coordinator.py`, `services/connectors/adapters/discord.py`, `services/connectors/events.py`

## Where it lives

| Concern | File |
| --- | --- |
| What each message says, log parsing, error extraction | `services/notification_service.py` |
| Deciding when a finished transfer announces | `services/transfer_coordinator.py` (`_post_transfer_completion`) |
| The manual-sync alert | `services/transfer_coordinator.py` (`send_manual_sync_discord_alert`) |
| Trigger for the manual-sync alert | `services/auto_sync_scheduler.py` (`_execute_job`) |
| Trigger for the rename notification | `services/rename_service.py` (`process_rename_webhook`) |
| Trigger for the retention notification | `services/backups/service.py` |
| The list of announcements that exist | `services/connectors/events.py` |
| Turning an announcement into a Discord embed | `services/connectors/adapters/discord.py` |
| Where each announcement goes, and delivery | [Integrations](../integrations/README.md) |

## How it works

### Gate

There is no gate in this file any more. Every announcement is one `notify()` call describing what happened; whether it is sent, and where, is decided by the connector layer - the connector has to be on, the notification has to be switched on, and there has to be a destination. Every one of those decisions is recorded with a reason, visible on the connector's Activity tab.

A fresh install announces nothing until an operator adds a webhook.

### Transfer finished or failed

When a transfer starts, `TransferCoordinator.start_transfer()` spawns a background watcher thread, `_post_transfer_completion`, which polls the transfer row every 5 seconds until its status leaves `running`/`pending`. The same watcher is spawned by `start_queued_transfer()`, `resume_transfer()`, and at app startup for transfers restored by `resume_active_transfers()`.

When the transfer settles, the watcher releases the queue slot, updates linked webhook rows, and then calls `NotificationService.send_discord_notification(transfer_id, status)` - but only for `completed` and `failed`. `cancelled` and `paused` transfers never notify. `send_discord_notification` re-checks that guard itself, so calling it with any other status is a no-op.

The embed is assembled from three sources:

1. The transfer row: `parsed_title` (falling back to `folder_name`) becomes the embed title, `dest_path` becomes the "Folder Synced" / "Folder Path" field.
2. The parsed rsync statistics (below).
3. The linked webhook notification, if there is one, for the poster image and the requester.

To find the linked notification the service switches on the transfer's `media_type`: `movies` searches the Radarr notification table, `series` / `anime` / `tvshows` search the Sonarr notification table. If a row is found, its `poster_url` replaces the default thumbnail and its `requested_by` is added as a field.

The "Manual Sync" versus "Automated Sync" label in the embed author line is decided as follows: a movie transfer that matches a webhook row is always labelled Automated Sync; a series/anime transfer that matches a webhook row is labelled Automated Sync only if that row has an `auto_sync_scheduled_at` value, meaning it went through the wait-and-batch scheduler. Everything else - including a webhook item an operator pressed sync on by hand - is labelled Manual Sync.

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

### Error extraction for failed transfers

For a failed transfer only, `extract_rsync_errors()` scans the log forward and keeps lines that either contain `rsync:` together with `error` or `failed`, or contain any of `no space left on device`, `permission denied`, `connection refused`, or `timeout` alongside `rsync` - all case-insensitive. Only the last 10 matches are kept, joined with newlines, and truncated to 1000 characters before being wrapped in a code fence. If nothing matched, the transfer's current `progress` text is used instead, so the Error Details field is never empty.

### Manual-sync alert

This one does not live in the notification service. When the auto-sync scheduler runs a batched series/anime job it first performs a dry-run validation. If validation says the sync is not safe, `_execute_job` marks every notification in the batch with `requires_manual_sync` and then calls `TransferCoordinator.send_manual_sync_discord_alert()` **once for the whole batch**, using the first notification in the batch for the display details.

The alert is a gold embed (`15844367`) titled with the series name and season number, footed with `DRAGONCP Auto-Sync Safety Check`. It carries the season path, the validation `reason` string, and a File Analysis block with `server_file_count`, `local_file_count`, `deleted_count` ("Would Delete") and `incoming_count` ("Would Add"). The author line is `Manual Sync Alert ⚠️`, with the connector's notification icon beside it when one is configured. Before 2.3.0 the line only appeared *at all* when an icon URL was set, which was an accident of how the embed was assembled.

This code path has its own copy of the enable/URL gate, its own `_is_valid_discord_url` helper, and its own `requests.post` call; it does not go through `NotificationService`.

### Rename notification

`RenameService.process_rename_webhook()` calls `send_rename_discord_notification()` after a rename batch finishes. The embed colour tracks the outcome: teal (`1752220`) for `completed`, orange (`15105570`) for `partial`, red (`15158332`) for `failed`. It lists the media type, the status, a totals block, and the first five resulting file names (prefixed `✓` or `✗`) with an "... and N more files" line beyond that, truncated to 900 characters. Footer is `DragonCP Rename Operation`.

### The app URL

The connector's **App URL** is attached as the embed's clickable `url`, but only after passing `is_valid_app_url()` - a regex accepting `http`/`https` with a domain, `localhost`, or a dotted IPv4, with an optional port and path. It is deliberately permissive because this is a private deployment and the value is routinely a Tailscale IP. Discord rejects an embed outright if the URL is malformed, so an invalid value costs the link and nothing else. The check exists once, in `adapters/discord.py`; before 2.3.0 the same regex was copied into three files.

## Behaviour worth knowing

- **The statistics can come from the wrong rsync run.** `parse_transfer_logs()` iterates the log in reverse but never breaks out of the loop, so every match overwrites the previous one and the value that survives is from the *earliest* matching line in the stored log, not the latest. A transfer that was paused and resumed (or otherwise wrote more than one `--stats` block into the same log) will report the first run's numbers.
- **Only two outcomes notify.** Cancelled and paused transfers are deliberately silent. A pause is treated as "not an outcome" throughout the coordinator.
- **Restarting a transfer produces no notification.** `TransferCoordinator.restart_transfer()` calls straight into `TransferService.restart_transfer()` and never spawns `_post_transfer_completion`, so the restarted run finishes without a watcher and therefore without a Discord message.
- **Backup restores never notify.** A restore creates its own transfer row in `services/backups/service.py` and drives its own completion, rather than going through `start_transfer()`, so it has no completion watcher. It does reserve its destination in the queue and emit `transfer_progress` / `transfer_complete`; only the Discord side is absent.
- **Simulations do notify.** `SimulationService` starts its fake transfers through the same `start_transfer()`, so a simulation run posts real Discord messages exactly as a real sync would. See [../simulation/README.md](../simulation/README.md).
- **The "default thumbnail" is not manual-sync-only.** It is the fallback for *every* message with no image of its own; a poster URL only overrides it when a matching notification row is found. Automated syncs with no poster still show this image.
- **The notification lookup is a full table scan.** `send_discord_notification` calls `get_all()` on the notification model and loops looking for a matching `transfer_id`, even though both models expose an indexed `get_by_transfer_id()`. `get_all()` is called with no limit, so the cost grows with notification history.
- **A rejected webhook is not retried.** Any response other than HTTP 204 is printed to the server console and dropped. Discord rate limiting (429) therefore loses the message with no user-visible trace.
- **Every send path swallows its own exceptions.** All four senders wrap their work in a bare `try/except` that prints a traceback and returns, so a broken notification never fails the transfer, the rename, or the scheduler job.
- **The manual-sync alert reads notification fields without defaults.** `media_type`, `series_title`, `season_number` and `season_path`, and `validation_result['reason']`, are accessed directly. A missing key raises inside the try block and the alert is silently dropped.
- **The alert fires once per batch, not once per episode.** Several episodes batched into one auto-sync job produce a single Discord message, taken from the first notification's details.
- **The message timestamp is send time.** Embeds use `datetime.utcnow()` at the moment of sending, not the transfer's `end_time`. The watcher polls on a 5-second interval, so the timestamp can lag the actual finish.
- **A rename that could not be recorded does not notify.** If the rename history row fails to update, `process_rename_webhook` returns before reaching the Discord call.
- **A Discord destination must be a Discord URL.** The server posts to whatever is stored, so `DiscordConnector.validate_target` requires `https`, a host in the Discord set, and `/api/webhooks/` in the path. Before 2.3.0 there was no host restriction at all.
- **Logs are capped at 5000 lines** (`LOG_MAX_LINES` in `models/transfer.py`), trimmed from the *front*. That is deliberate so the `--stats` summary and any trailing errors survive, which is exactly what these notifications need.

## Data

| Table | Use |
| --- | --- |
| `connector`, `connector_secret`, `connector_target`, `notification_route` | Where announcements go - see [Integrations](../integrations/README.md) |
| `transfers` | Reads `status`, `logs`, `progress`, `parsed_title`, `folder_name`, `dest_path`, `media_type` |
| `radarr_webhook` | Reads `transfer_id`, `poster_url`, `requested_by` for movie transfers |
| `sonarr_webhook` | Reads `transfer_id`, `poster_url`, `requested_by`, `auto_sync_scheduled_at`; the manual-sync alert also reads `media_type`, `series_title`, `season_number`, `season_path` |
| `rename_webhook` | Not read directly - the rename embed is built from the result dictionary `RenameService` passes in |

The five `DISCORD_*` settings keys that used to appear here are gone. They became connector rows in 2.3.0 and are migrated automatically on first start.

Full schema: [../../reference/database-schema.md](../../reference/database-schema.md)

## API

Nothing here has endpoints of its own. Announcements are produced internally;
configuring where they go is the connector API, under `/api/connectors` -
see [the API reference](../../reference/api.md#connectors).

`/api/discord/settings` and `/api/discord/test` were removed in 2.3.0.

## Related

- [../integrations/README.md](../integrations/README.md) - where these messages go, and how they get there
- [../queue/README.md](../queue/README.md) - the completion watcher that triggers transfer notifications is the same one that releases queue slots
- [../auto-sync/README.md](../auto-sync/README.md) - the dry-run validation whose failure produces the manual-sync alert
- [../simulation/README.md](../simulation/README.md) - simulated transfers send real notifications
- [../../architecture/system-overview.md](../../architecture/system-overview.md)
- [../../reference/api.md](../../reference/api.md)
- [../../reference/database-schema.md](../../reference/database-schema.md)
