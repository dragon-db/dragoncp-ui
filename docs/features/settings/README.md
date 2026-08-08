# Settings Screen

Last updated: 2026-08-06
Primary files: `settings_registry.py`, `services/settings_service.py`, `frontend/src/components/settings/settings-panel.tsx`, `frontend/src/components/settings/backend-log-panel.tsx`, `frontend/src/components/pages/settings.tsx`, `frontend/src/hooks/useConfig.ts`, `app.py`, `config.py`, `routes/webhooks.py`, `routes/logs.py`, `models/settings.py`, `websocket.py`

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

The retired UI's flat `GET /api/config` shape, `/api/config/env-only`, and
`/api/config/reset` remain as deprecated compatibility contracts for one React
cutover soak. New clients use only the grouped configuration payload.


## Purpose

The Settings screen is where an operator sees how DragonCP is configured, turns webhook
auto-sync on or off, configures Discord notifications, and reaches the connection and
WebSocket diagnostics.

The most important thing to understand about this screen is that **not everything on it
is editable**, and the screen says which is which. Where the media lives and how to
reach the remote come from the environment file on the server; automation, notifications,
retention and the realtime timeout come from the database and can be changed here.

## Layout

### Header

Title "Settings", description "Connection, media paths, and automation". No buttons.

There is no page-level save. Each tab saves its own settings, because a single "save
everything" button spanning two stores could only ever claim to have written things it
had not. There is no `Reset to Env` either: a setting now either comes from the
environment file, in which case it is read-only, or from the database, where the stored
value is the only value there is.

### Summary tiles

Two read-only tiles across the top:

| Tile | Shows |
| --- | --- |
| SSH | `Connected` / `Disconnected`, from the runtime status poll |
| WebSockets | active WebSocket connections reported by `GET /api/websocket/status` |

The SSH tile polls `GET /api/runtime/status` every 5 seconds. If that endpoint returns
404 (older backend), the frontend falls back to `GET /api/debug` and slows the poll to
30 seconds.

### Tabs

`Core Config`, `Automation`, `Account`, `Diagnostics`.

The Account tab shows the signed-in identity and supports self-service password
changes. Diagnostics contains SSH and Socket.IO state plus the backend log
viewer, with level/search filters, manual or automatic refresh, and an
authenticated full-log download.

## Core Config tab

Generated from `settings_registry.py` — the panel walks the groups `GET /api/config`
returns rather than holding its own list of fields, so adding a setting to the registry
adds it here.

Each setting renders with its group, label and description, and with a badge saying
which store it came from:

- **Environment file** — read-only. The value is shown where it is safe to show; secrets
  are not sent to the browser at all. Change these in `dragoncp_env.env` on the server
  and restart.
- **Application setting** — editable, saved to the database, effective immediately and
  shared by every operator and every background job.

The media paths, the remote connection details and the secrets are all environment
settings. That is deliberate: the seven media paths are the path-traversal boundary that
every file operation is validated against, and widening it from a browser is not
something this application allows.

A save sends only the editable fields. If a request does contain an environment key —
an older client, or a hand-made request — the server refuses it **by name** and the
response lists which, so the UI can say what did not change instead of reporting a
success that half happened.

### Saving is all-or-nothing

The whole payload is validated before any of it is written. A single bad value fails the
request with a 400 and changes nothing, so a failed save always means the settings are
exactly as they were.

Numbers are clamped rather than rejected: typing `999` into a field that tops out at 60
saves 60, because that plainly meant "as high as it goes".

### Masked fields

Editable secrets — currently the Discord webhook URL — are sent to the browser as the
literal string `<redacted>` when a value is stored, and as an empty string when none is.
Sending `<redacted>` back means "unchanged", so saving the form without touching the
field keeps the stored value.

Clearing the box and saving stores an empty value, and an empty value is honoured as a
deliberate choice: it is not treated as "nothing saved", and it is not overwritten from
the environment file at the next restart.

Environment secrets (`SECRET_KEY`, `JWT_SECRET_KEY`, `REMOTE_PASSWORD`,
`DRAGONCP_PASSWORD`, `DRAGONCP_PASSWORD_HASH`, `WEBHOOK_SECRET`, `DISK_API_TOKEN`) are
omitted from the response entirely rather than redacted. There is nothing a reader could
do with a redacted value they cannot change, and listing them only advertises what is on
the server.

### WebSocket timeout

`WEBSOCKET_TIMEOUT_MINUTES` is a database setting, clamped to 5-60 on the way in. The
server reads it from the database when a WebSocket connects, adds a 5-minute buffer and
caps the result at its own maximum, so a change applies to the *next* realtime
connection rather than the one currently open.

It used to be read from the browser session, which meant the value an operator saved was
invisible to the server's own stale-connection reaper.

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
non-numbers (minimum 1). The registry clamps to 30-900 seconds wherever it is written.
Type `5`, save, and the stored value is `30`; the field corrects itself after the page
refetches. The bounds used to be enforced in one route only, so the same value written
through another path was accepted unclamped.

**The Test button uses saved settings, not what is on screen.** The button is enabled
only when the on-screen Enable toggle is on, but `POST /api/discord/test` reads the
webhook URL and the enabled flag out of storage. So: typing a new webhook URL and
hitting **Save Automation** first is what makes Test exercise the new URL, and flipping
the toggle on without saving makes Test fail with "Discord notifications are disabled".

## Where a save goes

Each tab writes its own settings, through the same resolver, into the same database:

| Tab | Request | Keys |
| --- | --- | --- |
| Core Config | `POST /api/config` | every editable key in the registry |
| Automation | `POST /api/webhook/settings` | the three auto-sync toggles and the wait time |
| Automation | `POST /api/discord/settings` | the five Discord fields |

All of them land in the `app_settings` table. They are global — one value for the whole
installation, visible to every operator — and they survive a restart.

They are read at the moment they are needed rather than cached: the auto-sync flags when
a webhook arrives, the Discord settings when a notification is about to be sent, the
retention rule when a transfer finishes. So a change is live for the next event with no
reconnect and no restart. That immediacy is the entire reason these live in the database
rather than the environment file, and caching them would quietly undo it.

The one wrinkle is the wait time: it is read when a batch is scheduled or extended, so a
series batch already counting down keeps the deadline it was given until the next episode
for that batch arrives.

### Adoption on first start

A setting that used to live in the environment file and now lives in the database is
copied across once, at startup, by `adopt_env_defaults()`. Without it, moving a setting
over would change behaviour on the way: the env value would keep working as a fallback
until someone saved something, and then silently stop being the source of truth.

Adoption only writes keys with no database row at all. A row holding an empty string is
a deliberate choice — that is how a value is cleared — and is left alone.

## What needs a reconnect

Only `WEBSOCKET_TIMEOUT_MINUTES`, and only because the value is read when a realtime
connection opens. Saving it switches the realtime indicator in the app header to the
config-changed state, where its button reads **Apply settings**.

The SSH connection details are environment settings and cannot be changed from a
browser, so nothing on this screen can invalidate the SSH session. Editing
`dragoncp_env.env` and restarting is what changes them; **Auto Connect** on the
Diagnostics tab rebuilds the session from the current values.

## Diagnostics tab

**Connection Controls**

- **Auto Connect** (`GET /api/auto-connect`) opens an SSH session using `REMOTE_IP`,
  `REMOTE_USER`, `REMOTE_PASSWORD` and `SSH_KEY_PATH` as they are in the environment
  file. It fails if host or user is empty.
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
| Source, destination, disk and disk-API paths | `dragoncp_env.env` | whole installation | after editing the file on the server and restarting |
| `REMOTE_IP`, `REMOTE_USER`, `REMOTE_PASSWORD`, `SSH_KEY_PATH` | `dragoncp_env.env` | whole installation | after a restart, then Auto Connect on the Diagnostics tab |
| `WEBSOCKET_TIMEOUT_MINUTES` | `app_settings` table | whole installation | on the next realtime connection (Apply settings) |
| Auto-sync toggles and wait time | `app_settings` table | whole installation | next webhook; a batch already waiting keeps its deadline |
| Discord fields | `app_settings` table | whole installation | next notification sent |
| Backup retention rule | `app_settings` table | whole installation | next time a transfer stores a version |

## Related

- [Auto-sync](../auto-sync/README.md)
- [Discord notifications](../notifications/README.md)
- [Configuration reference](../../reference/configuration.md)
- [API reference](../../reference/api.md)
