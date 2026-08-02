# Settings Screen

Last updated: 2026-08-01
Primary files: `settings_registry.py`, `services/settings_service.py`, `frontend/src/components/settings/settings-panel.tsx`, `frontend/src/components/pages/settings.tsx`, `frontend/src/hooks/useConfig.ts`, `app.py`, `config.py`, `routes/webhooks.py`, `models/settings.py`, `websocket.py`

## Where a setting lives

Two stores, and only two — see
[`../../reference/configuration.md`](../../reference/configuration.md#where-a-setting-lives).

The **Config** tab is now generated from `settings_registry.py`. Environment
settings render read-only, with a note saying they come from
`dragoncp_env.env`; database settings are editable and take effect immediately.
A save that includes an environment key refuses it **by name** rather than
ignoring it.

The **Automation** tab keeps its purpose-built controls for auto-sync and
Discord. Those are database settings too, written through the same resolver, so
the two tabs cannot disagree.

**The old warning on this page no longer applies.** The two tabs used to save to
different places — Core Config to a per-browser Flask session that background
threads never read, Automation to the database. That session store is gone.
Everything writable now goes to one place.

**The legacy static UI still works.** It reads a flat key -> value map from
`GET /api/config`, which is returned alongside the grouped payload, and it
still calls `/api/config/env-only` and `/api/config/reset`. Its settings form
now reports which fields it could not change rather than claiming a full save.


## Purpose

The Settings screen is where an operator points DragonCP at a remote server, tells it
where media comes from and goes to, turns webhook auto-sync on or off, and configures
Discord notifications. It also carries the connection and WebSocket diagnostics.

The single most important thing to understand about this screen is that **the two tabs
that hold editable values do not save to the same place**, and only one of them survives
a browser change or a `Reset to Env`. That is covered in
[Two save paths](#two-save-paths) below.

## Layout

### Header

Title "Settings", description "Connection, media paths, and automation", and two buttons:

- **Reset to Env** - discards saved Core Config overrides (see below).
- **Save All** - saves everything on the Core Config and Automation tabs in one click.

### Summary tiles

Four read-only tiles across the top:

| Tile | Shows |
| --- | --- |
| SSH | `Connected` / `Disconnected`, from the runtime status poll |
| Timeout | the WebSocket timeout currently typed in the Core Config tab, or `30` if blank |
| Modified | how many Core Config fields differ from the values in the env file |
| WebSockets | active WebSocket connections reported by `GET /api/websocket/status` |

The SSH tile polls `GET /api/runtime/status` every 5 seconds. If that endpoint returns
404 (older backend), the frontend falls back to `GET /api/debug` and slows the poll to
30 seconds.

The **Modified** count is not a count of unsaved edits. It compares the current value of
each field against `GET /api/config/env-only`, which is the env-file value with no
session override applied. A field you changed and saved yesterday still counts as
modified today. The same comparison drives the amber `Modified` badge on each field and
the `N modified` badge on each Core Config card.

### Tabs

`Core Config`, `Automation`, `Diagnostics`.

## Core Config tab

Four cards, each holding a fixed set of fields. Every field shows the env-file value
underneath it as `Env: <value>` or `Env: Not set`.

**Connection & Access**: Server Host/IP (`REMOTE_IP`), SSH Username (`REMOTE_USER`),
SSH Password (`REMOTE_PASSWORD`), SSH Key Path (`SSH_KEY_PATH`), WebSocket Timeout
(minutes) (`WEBSOCKET_TIMEOUT_MINUTES`).

**Source Paths**: Movie (`MOVIE_PATH`), TV Show (`TVSHOW_PATH`), Anime (`ANIME_PATH`),
Backup (`BACKUP_PATH`).

**Destination Paths**: Movie (`MOVIE_DEST_PATH`), TV Show (`TVSHOW_DEST_PATH`), Anime
(`ANIME_DEST_PATH`).

**Storage & Disk API**: Disk Path 1/2/3 (`DISK_PATH_1`, `DISK_PATH_2`, `DISK_PATH_3`),
Remote Disk API Endpoint (`DISK_API_ENDPOINT`), Remote Disk API Token
(`DISK_API_TOKEN`).

### Masked fields

`REMOTE_PASSWORD` and `DISK_API_TOKEN` are masked inputs, and the backend redacts them
on the way out: `GET /api/config` returns the literal string `<redacted>` for any key
whose name contains `SECRET`, `PASSWORD`, `API_KEY`, `TOKEN` or `CLIENT_SECRET`, unless
the stored value is empty.

Consequences for an operator:

- Saving without touching these two fields is safe. The page sends `<redacted>` back and
  the backend substitutes the value it already had.
- Clearing the box and saving does store an empty value. There is no "leave unchanged"
  affordance separate from "make it blank".
- When the env file already has a password or token, both the field and its `Env:` line
  read `<redacted>`, so these two fields never light up the `Modified` badge even when a
  session override is in force. The only way to tell an override is present is that you
  put it there.

### WebSocket timeout

Before sending, the page clamps `WEBSOCKET_TIMEOUT_MINUTES` to 5-60 and falls back to 30
if the box is not a number. The server clamps again to the same 5-60 range, adds a
5-minute buffer, and caps the result at its own maximum. The value is read when a
WebSocket connects, so a change applies to the *next* realtime session, not the one
currently running.

## Automation tab

Two cards. Neither is documented in depth here.

- **Webhook Auto-Sync** - Auto-sync Movies, Auto-sync TV Shows, Auto-sync Anime, and
  Series/Anime Wait Time (seconds). See [auto-sync](../auto-sync/README.md) for what
  these actually drive.
- **Discord Settings** - Enable Discord Notifications, Discord Webhook URL, App URL, Icon
  URL, Manual Sync Thumbnail URL, and a **Test Discord Notification** button. See
  [notifications](../notifications/README.md).

Two behaviours belong to this screen rather than to those features:

**Wait time is clamped differently at each end.** The page only guards against zero and
non-numbers (minimum 1). The server clamps to 30-900 seconds. Type `5`, save, and the
stored value is `30`; the field corrects itself after the page refetches.

**The Test button uses saved settings, not what is on screen.** The button is enabled
only when the on-screen Enable toggle is on, but `POST /api/discord/test` reads the
webhook URL and the enabled flag out of storage. So: typing a new webhook URL and
hitting Test without pressing Save All first tests the *old* URL, and flipping the toggle
on without saving makes Test fail with "Discord notifications are disabled".

## Two save paths

`Save All` fires three requests, in this order:

1. `POST /api/config` - every Core Config field.
2. `POST /api/webhook/settings` - the three auto-sync toggles and the wait time.
3. `POST /api/discord/settings` - all five Discord fields.

They are awaited in sequence, so if the first one fails the second and third never run.
The failure toast says only "Failed to save settings" - it does not say how far the save
got. After a failed save, reopen the page before assuming anything about which values are
live.

### Path 1: Core Config goes into your browser session

`POST /api/config` calls `update_session_config`, which writes into the Flask session
under `ui_config`. It does not write `dragoncp_env.env`. This means:

- The override belongs to **your login session in this browser**. Another operator, or the
  same operator in a different browser, still sees the env-file values.
- `Reset to Env` (`POST /api/config/reset`) deletes `ui_config` outright. Every Core
  Config override goes away at once; there is no per-field revert.
- Server code reads the override only while handling a request from that session. Outside
  a request - background transfer threads, schedulers, anything not serving your HTTP
  call - `config.get()` falls back to the env file. Treat Core Config edits as a way to
  steer what *you* trigger from the UI, not as a way to reconfigure the running service.

To make a Core Config value permanent and process-wide, edit `dragoncp_env.env` and
restart. See [configuration reference](../../reference/configuration.md) for the env file
itself.

> Not verified: whether a saved Core Config override survives a backend restart. No
> server-side session store is configured, which points at Flask's default signed-cookie
> session (and therefore survival while `SECRET_KEY` is unchanged), but this was not
> tested.

### Path 2: Automation goes into the database

The auto-sync and Discord settings are written through `AppSettings` into the
`app_settings` table in SQLite, under these keys:

`AUTO_SYNC_MOVIES`, `AUTO_SYNC_SERIES`, `AUTO_SYNC_ANIME`,
`SERIES_ANIME_SYNC_WAIT_TIME`, `DISCORD_NOTIFICATIONS_ENABLED`, `DISCORD_WEBHOOK_URL`,
`DISCORD_APP_URL`, `DISCORD_ICON_URL`, `DISCORD_MANUAL_SYNC_THUMBNAIL_URL`.

These are global - one value for the whole installation, visible to every operator - and
they persist across restarts. **`Reset to Env` does not touch them.** It only deletes the
session config; the Automation tab looks unchanged afterwards because nothing about it
changed.

They are also read at the moment they are needed: the auto-sync flags are read when a
webhook arrives, the Discord settings are read when a notification is about to be sent.
So an Automation change is live for the next event with no reconnect and no restart. The
one wrinkle is the wait time: it is read when a batch is scheduled or extended, so a
series batch already counting down keeps the deadline it was given until the next episode
for that batch arrives.

## What needs a reconnect

Five Core Config keys are treated as critical:

`REMOTE_IP`, `REMOTE_USER`, `REMOTE_PASSWORD`, `SSH_KEY_PATH`, `WEBSOCKET_TIMEOUT_MINUTES`.

If a save changes any of them, the toast reads "Critical configuration changed. Reconnect
is required to apply updates." instead of "Settings saved", and the realtime indicator in
the app header switches to the config-changed state, where its button reads **Apply
settings** instead of Reconnect. Every other field saves with a plain "Settings saved" and
no prompt.

The comparison is made against what was actually sent, after the timeout clamp, so
clamping a value back to what was already stored does not count as a change.

Two things to know about clearing that prompt:

- **Apply settings reconnects the realtime socket, not SSH.** That is the right action for
  `WEBSOCKET_TIMEOUT_MINUTES`. For the four SSH keys, the connection is rebuilt by
  **Auto Connect** on the Diagnostics tab, which constructs a fresh SSH session from the
  current host, user, password and key path. Auto Connect also clears the prompt.
- **A second Save All clears the prompt without reconnecting anything.** The check
  compares the draft against the config as last fetched, and the first save refetched it.
  So save, see the reconnect prompt, press Save All again with no further edits, and the
  prompt disappears while the old SSH session is still in use. If you see the prompt,
  reconnect - do not save again.

## Diagnostics tab

**Connection Controls**

- **Auto Connect** (`GET /api/auto-connect`) opens an SSH session using `REMOTE_IP`,
  `REMOTE_USER`, `REMOTE_PASSWORD` and `SSH_KEY_PATH`, honouring your session overrides.
  It fails if host or user is empty.
- **Disconnect** (`POST /api/disconnect`) closes it.
- A status line repeats SSH state and active WebSocket session count.

The SSH session is a single process-wide connection, not one per operator. Disconnecting
here disconnects browsing and any SSH-dependent work for everyone using the installation.

**WebSocket Diagnostics**

A read-only JSON dump of `GET /api/websocket/status`, refreshed automatically every 5
seconds and on demand with **Refresh Status**. It reports active connection count, the
server default and maximum timeout in minutes, per-connection detail (truncated session
id, minutes since connect, minutes since last activity, that connection's timeout,
transport), Socket.IO runtime info, whether the cleanup thread is alive, and a timestamp.
It shows `{"status": "no data"}` before the first successful response.

## Quick reference

| Change | Where it is stored | Scope | When it takes effect |
| --- | --- | --- | --- |
| Source, destination, disk and disk-API fields | Flask session (`ui_config`) | your browser session | on requests you make afterwards; background work still reads the env file |
| `REMOTE_IP`, `REMOTE_USER`, `REMOTE_PASSWORD`, `SSH_KEY_PATH` | Flask session (`ui_config`) | your browser session | after Auto Connect on the Diagnostics tab |
| `WEBSOCKET_TIMEOUT_MINUTES` | Flask session (`ui_config`) | your browser session | on the next realtime connection (Apply settings) |
| Auto-sync toggles and wait time | `app_settings` table | whole installation | next webhook; a batch already waiting keeps its deadline |
| Discord fields | `app_settings` table | whole installation | next notification sent |

## Related

- [Auto-sync](../auto-sync/README.md)
- [Discord notifications](../notifications/README.md)
- [Configuration reference](../../reference/configuration.md)
- [API reference](../../reference/api.md)
