# Settings Screen

Last updated: 2026-10-21
Primary files: `frontend/src/components/pages/settings.tsx`, `frontend/src/components/settings/` (`remote-server-tab.tsx`, `syncing-tab.tsx`, `account-tab.tsx`, `system-tab.tsx`, `remote-transfer-panel.tsx`, `backend-log-panel.tsx`, `settings-bits.tsx`, `settings-model.ts`), `frontend/src/routes/_authenticated/settings.tsx`, `settings_registry.py`, `services/settings_service.py`, `frontend/src/hooks/useConfig.ts`, `app.py`, `config.py`, `routes/webhooks.py`, `routes/logs.py`, `models/settings.py`, `websocket.py`

## Where a setting lives

Two stores, and only two — see
[`../../reference/configuration.md`](../../reference/configuration.md#where-a-setting-lives).
Values from the environment file are shown with a lock and cannot be changed
here; values in the database have a control and save from this screen.

The retired UI's flat `GET /api/config` shape, `/api/config/env-only`, and
`/api/config/reset` remain as deprecated compatibility contracts for one React
cutover soak. New clients use only the grouped configuration payload.

## Purpose

Where an operator checks how DragonCP is set up and changes the few things that
can be changed from a browser: the SSH session to the remote server and the
fast transfer route, automatic sync and backup retention, their own password,
and the realtime timeout; and where they read the backend log. Discord and the
Sonarr and Radarr auto-scanners are configured under
[Integrations](../integrations/README.md) instead.

## Layout

Rebuilt on 2026-10-21 (2.3.2, TASK-026) so it looks like the rest of the app —
the underlined page tabs, bordered section cards and status colours of
[the design system](../../reference/design-system.md) — and so each topic lives
in one place. It used to be five tabs by mechanism (Core Config, Connections,
Automation, Account, Diagnostics): the remote login sat on one tab and Connect
on another, the fast-transfer options appeared twice, and every value the
environment file sets was drawn as a greyed-out input.

**Header:** the title only. No buttons, no description.

**Tabs**, each a stack of section cards. The tab is in the address
(`/settings?tab=remote|syncing|account|system`; anything else opens Remote
server), so other pages can link to one. On a phone the first reads **Remote**
so all four fit.

| Tab | Sections |
| --- | --- |
| Remote server | Connection, Fast transfers |
| Syncing | Automatic sync, Library folders, Backup retention |
| Account | Signed in as, Password, Administrators, Sign-in and access |
| System | Runtime, Live connections, Disk usage, Backend log, Other settings |

**Rows.** A setting is a row: name and what it does on the left, its control or
value on the right (under it on a phone, except switches and short values, which
stay on the right). A value from the environment file reads as text with a lock,
or *Not set*; the section says once, at its foot, that locked values come from
`dragoncp_env.env` and need a restart. Values that need no explaining (the
remote login, the disk paths) are a compact two-column list instead of rows.

**Coloured icons mean a state**, in the app's four-note vocabulary: green
healthy, amber needs a look, rose broken, brand on, grey off — the connection,
the fast transfer server, each library's auto-sync, test mode.

**One save model.** A switch or a choice saves the moment it changes, with a
toast that says what changed. A number saves on Enter or when the field loses
focus; Escape puts it back. A number outside the setting's range is refused on
the page ("Use a number from 30 to 900") and not sent. There is no page-level
save and no Reset to Env.

**Other settings.** Any setting the server describes that no tab places
(`PLACED_KEYS` in `settings-model.ts`) appears on System under **Other
settings**, so a key added to the registry later is never invisible. Nothing
lands there today, and the section is then hidden.

**Secrets are never shown.** Environment secrets (`SECRET_KEY`,
`JWT_SECRET_KEY`, `REMOTE_PASSWORD`, `DRAGONCP_PASSWORD`,
`DRAGONCP_PASSWORD_HASH`, `WEBHOOK_SECRET`, `DISK_API_TOKEN`,
`RSYNC_DAEMON_ALLOWED_IP`) are omitted from the response entirely.

## Remote server tab

**Connection** — the SSH session Explore reads the remote server through.

- At the top, what state it is in, as a coloured icon and a sentence:
  *Connected to <server>*; *Not connected* (with whether Explore will connect
  by itself); *Cannot reach <server>* with the reason and when it tries again;
  or *The remote server refused the login*, in rose, when automatic connecting
  is paused (see [Explore → The SSH session](../explore/README.md#the-ssh-session)).
  Read from `GET /api/explore/session` every 15 seconds; that asks nothing of
  the remote server.
- **Connect** (`GET /api/auto-connect`) or **Disconnect**
  (`POST /api/disconnect`), whichever applies. Connect is greyed out with
  "Connect at 14:03:00" while a refused login's 60-second spacing runs.
- **Auto-connect** switch (`SSH_AUTO_CONNECT`, on by default): Explore opens the
  session by itself whenever it needs it. Off: nobody connects but a person.
- Locked: Server, User, SSH key (*Not set* means the password is used),
  Host-key checking (with what the policy means; `no` is flagged unsafe in
  amber), Known hosts file (*Not set* means `dragoncp_known_hosts` in the app
  folder).

The SSH session is a single process-wide connection, not one per operator.
Disconnecting here disconnects browsing for everyone using the installation.
Transfers open their own connections and are not affected.

**Fast transfers** — the transfer server on the remote server; see
[fast transfers](../fast-transfers/README.md). Its state as a coloured icon and
sentence, the warnings (address changed, not configured), the actions (Install
or Reinstall, Start, Stop, New password, Remove — pressed twice), the three
choices (Use it for transfers, Who may connect, When it runs; each saves on
change), the facts (installed, running, answering, settings match, address
matches, port, libraries published, stored password problems), and **Which
address do we connect from?** Its status light no longer pulses.

## Syncing tab

**Automatic sync** — one switch per library (Movies, TV shows, Anime), the icon
in brand when on, and **Fallback wait**. These are the same settings as the
Auto-sync popover on the Webhooks page, saved through the same request; see
[auto-sync](../auto-sync/README.md) for what they drive.

**Library folders** — each library as a pair: where it is on the remote server,
an arrow, where it lands on this machine; then the Backups folder. All locked:
the seven media paths are the path-traversal boundary every file operation is
checked against, and widening it from a browser is not something this
application allows.

**Backup retention** — **Delete old versions** (switch), **Versions to keep**
(1-50) and **Grace period** (0-720 hours). The two numbers are greyed out while
the switch is off. See [backups](../backups/README.md) for what protects a
version.

Behaviours that belong to this screen rather than to those features:

**The wait time is a fallback now.** Since 2.3.0 it decides when a TV or anime season
starts only when Sonarr cannot be asked — the Sonarr connector is off or has no address
or key, Sonarr does not answer (or stops answering partway through the wait), or the
series carries no TVDB id. When Sonarr answers,
its own "time left" decides, for at most 30 minutes; see
[the sync engine](../sync-engine/README.md). As a fallback the timer runs from the first
webhook of a batch, each later webhook adds the same again, and it never runs past
15 minutes after the first. The deadline is stored on the batch and re-read at every
step, so a later webhook really does extend it.

**The screen says so.** The field reads **Fallback wait**, "Only used when Sonarr
can't be asked: how long a season waits for more episodes before it syncs, up to 15
minutes in all." The auto-sync popover on the Webhooks page says "TV & anime start once
Sonarr has nothing more for the season; if Sonarr cannot be asked, Ns after the last
episode." Both used to describe the old fixed wait. The sentence is written into the
tab rather than read from the registry, so nothing keeps the two in step.

**The wait's range is checked on the page too.** Since 2026-10-21 the field refuses a
number outside the registry's 30-900 seconds and says so, instead of sending it. The
registry still clamps to 30-900 wherever the value is written, so another client
sending `5` stores `30`.

**There is no switch for asking Sonarr.** Pre-release builds of 2.3.0 had one,
`AUTOSYNC_GATE_ENABLED` ("Wait for the download instead of the clock"), with
`AUTOSYNC_GATE_POLL_SECONDS` and `AUTOSYNC_GATE_SETTLE_SECONDS` beside it. All three are
gone from the registry and nothing reads them: whether Sonarr's API answers decides, the
pause before the first question is a fixed 10 seconds, and the next question follows
Sonarr's own estimate. A value one of those builds saved stays in `app_settings`, unread.

**Turning auto-sync on does not release what is already held.** With a switch off, each
webhook still opens a batch, held for a person. Switching it on leaves those batches held
until another webhook for the same folder arrives — that webhook sets its batch going — or
someone presses Sync.

**Discord is not configured here any more.** It became a connector in 2.3.0, with named
webhooks and a choice of destination per notification, and it lives under Integrations →
Discord in the sidebar. Until 2026-10-21 this screen carried a card that only linked
there; it was removed.

**Neither is the auto-scanner.** Its switch and interval are per service, on the Sonarr
and Radarr Connection tabs under Integrations, where an Auto-scanner card shows its next
scan and what the last one found.

## Account tab

- **Signed in as** — an initial tile, the username, and *Administrator, account #N* or
  *Fallback sign-in from the server's environment file*.
- **Password** — change your own; see [auth](../auth/README.md).
- **Administrators** — why there is no screen for it, and the
  `scripts/manage_admins.py` commands; see [admin accounts](../../operations/admin-accounts.md).
- **Sign-in and access**, locked: Sign-in lasts (`JWT_EXPIRY_HOURS`), Fallback
  username (`DRAGONCP_USERNAME`, used only while no account exists), Webhook senders
  (`WEBHOOK_ALLOWED_IPS`, with what happens when it and the webhook secret are set or
  not), Allowed origins (`CORS_ORIGINS`).

## System tab

- **Runtime** — **Test mode** (on: amber icon, "transfers are rehearsed and nothing is
  written", and the Backups page caveat; from the runtime status, which reads
  `TEST_MODE` at start-up) and **Live updates time out after** (`WEBSOCKET_TIMEOUT_MINUTES`,
  5-60 minutes).
- **Live connections** — one row per browser holding a realtime connection: its
  shortened session id, when it connected, when it was last active, and how long it may
  idle. Polled every 5 seconds from `GET /api/websocket/status`. With none: "No browser
  is connected live". Until 2026-10-21 this was a raw JSON dump.
- **Disk usage** — the three disk paths and the remote server's disk API address, as a
  compact list.
- **Backend log** — level (Errors, Warnings and errors, Info only, Debug only,
  Everything; as `routes/logs.py` filters them), search, Keep refreshing, Refresh and
  Download. Error lines are rose, warnings amber, the rest quiet.
- **Other settings** — only when a setting has no other place (see Layout).

## Saving

### Saving is all-or-nothing

The whole payload is validated before any of it is written. A single bad value fails the
request with a 400 and changes nothing, so a failed save always means the settings are
exactly as they were.

On the server, numbers are clamped rather than rejected: a request carrying `999` for a
field that tops out at 60 saves 60. This page never sends one: since 2026-10-21 it
refuses an out-of-range number before saving and says the range.

### Masked fields

Editable secrets are sent to the browser as the literal string `<redacted>` when a value
is stored, and as an empty string when none is. Sending `<redacted>` back means
"unchanged", so saving the form without touching the field keeps the stored value. No
database setting is a secret today — the Discord webhook URL, which was, became a
connector credential in 2.3.0 — but the rule stands for any that becomes one.

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

## Where a save goes

Every save goes through the same resolver into the same database:

| Section | Request | Keys |
| --- | --- | --- |
| Automatic sync | `POST /api/webhook/settings` | the three auto-sync toggles and the fallback wait (the Webhooks page's popover uses the same request) |
| Everything else editable | `POST /api/config` | one key per save: `SSH_AUTO_CONNECT`, the three `FAST_TRANSPORT_*`, the three `BACKUP_RETENTION_*`, `WEBSOCKET_TIMEOUT_MINUTES` |

Connectors write elsewhere — `POST /api/connectors/<id>` and the destination routes,
into the `connector` tables rather than `app_settings`. That includes Discord and the
Sonarr and Radarr auto-scanner switches. See [Integrations](../integrations/README.md).

They all land in the `app_settings` table. They are global — one value for the
whole installation, visible to every operator — and they survive a restart.

They are read at the moment they are needed rather than cached: the auto-sync flags when
a webhook arrives, the fallback wait when a batch opens or a webhook joins one, the
retention rule when a transfer finishes. So a change is live for the next event with no
reconnect and no restart. That immediacy is the entire reason these live in the database
rather than the environment file, and caching them would quietly undo it.

Two wrinkles. The fallback wait is read when a batch opens and each time a webhook joins
it, so a batch already counting down keeps its deadline until the next webhook for that
folder arrives — and the wait matters at all only when Sonarr cannot be asked. An
auto-sync flag is read when a webhook arrives, so a batch held while it was off stays
held after it is switched on, until another webhook for that folder or a press of Sync.

### Adoption on first start

A setting that used to live in the environment file and now lives in the database is
copied across once, at startup, by `adopt_env_defaults()`. Without it, moving a setting
over would change behaviour on the way: the env value would keep working as a fallback
until someone saved something, and then silently stop being the source of truth.

Adoption only writes keys with no database row at all. A row holding an empty string is
a deliberate choice — that is how a value is cleared — and is left alone.

## What needs a reconnect

Only `WEBSOCKET_TIMEOUT_MINUTES`, and only because the value is read when a realtime
connection opens, so a change applies from the next live connection; the field says
so. Nothing on screen prompts for it. (This page used to say saving it switched the
header's realtime indicator to **Apply settings**; checked 2026-10-21, nothing in the
frontend sets that state.)

The SSH connection details are environment settings and cannot be changed from a
browser, so nothing on this screen can invalidate the SSH session. Editing
`dragoncp_env.env` and restarting is what changes them; **Connect** on the Remote
server tab rebuilds the session from the current values.

## Quick reference

| Change | Where it is stored | Scope | When it takes effect |
| --- | --- | --- | --- |
| Source, destination, disk and disk-API paths | `dragoncp_env.env` | whole installation | after editing the file on the server and restarting |
| `REMOTE_IP`, `REMOTE_USER`, `REMOTE_PASSWORD`, `SSH_KEY_PATH` | `dragoncp_env.env` | whole installation | after a restart, then Connect on the Remote server tab (or the next Explore read, with Auto-connect on) |
| `WEBSOCKET_TIMEOUT_MINUTES` | `app_settings` table | whole installation | on the next realtime connection |
| `SSH_AUTO_CONNECT` | `app_settings` table | whole installation | the next time Explore needs the remote server |
| Auto-sync toggles | `app_settings` table | whole installation | next webhook; a batch already held stays held until another webhook for its folder or a press of Sync |
| Fallback wait (`SERIES_ANIME_SYNC_WAIT_TIME`) | `app_settings` table | whole installation | the next batch, or the next webhook joining one; used only when Sonarr cannot be asked |
| Discord destinations and routing | connector tables (Integrations → Discord) | whole installation | next announcement |
| Auto-scanner switch and interval | connector settings (Integrations → Sonarr / Radarr → Connection) | per service | noticed within 5 seconds; the next scan comes then, or one interval after the previous scan if that is later |
| Backup retention rule | `app_settings` table | whole installation | next time a transfer stores a version |

## Related

- [Auto-sync](../auto-sync/README.md)
- [Sync engine](../sync-engine/README.md) — when the fallback wait applies
- [Integrations](../integrations/README.md) — Discord and the auto-scanner
- [Design system](../../reference/design-system.md) — the cards, tabs and colours this screen uses
- [Discord notifications](../notifications/README.md)
- [Configuration reference](../../reference/configuration.md)
- [API reference](../../reference/api.md)
