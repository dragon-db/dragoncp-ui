# Configuration

Last updated: 2026-08-02
Primary files: `settings_registry.py`, `services/settings_service.py`, `config.py`, `app.py`, `auth.py`, `webhook_auth.py`, `logging_setup.py`, `websocket.py`, `ssh.py`, `models/settings.py`, `deploy/gunicorn.conf.py`

Every setting DragonCP reads, where it comes from, and what an operator sees
when it is wrong. This page is derived from the code, not from the sample env
file — the code reads considerably more than the sample ships.

## Where a setting lives

Two stores, and only two. `settings_registry.py` is the list.

| | **Environment file** (`dragoncp_env.env`) | **Application settings** (`app_settings` table) |
|---|---|---|
| Holds | What an installation is built with | What an operator changes while running it |
| Changing it | Edit on the server, restart | Settings page, effective immediately |
| At runtime | **Read-only.** The UI shows these and refuses to write them | Editable |
| Visible to background threads | Yes | Yes |

**Environment file:** the remote host and SSH key, the six media directories,
`BACKUP_PATH`, the disk-reporting paths and API, `TEST_MODE`, and every
credential, secret and security control.

The seven path settings are there for a specific reason: `get_all_allowed_paths()`
returns exactly those, and every path-traversal check validates against them.
They are the only boundary stopping a crafted webhook writing outside the media
directories, and it should not be possible to widen it from a browser. Secrets
are there for a related reason — the database is not an encrypted store, and a
key editable from a web form is editable by anyone who reaches that form, using
a session minted by the very key they would be changing.

**Application settings:** the three auto-sync toggles, the batch wait time, the
five Discord settings, the three backup-retention settings, and the realtime
idle timeout.

### The store that used to exist

A third store — a per-browser Flask session — was removed. `config.get()` only
consulted it when an HTTP request was in flight, so every background thread (the
transfer monitor, the auto-sync scheduler, the backup sorter) fell through to
the env file regardless. Sixteen settings appeared editable in the Settings page
and were ignored by the machinery that used them.

`DragonCPConfig.save_config` went with it — it rewrote the whole env file from
a dict, dropping every comment, and nothing called it.

`POST /api/config/reset` and `GET /api/config/env-only` are **kept**, because
the legacy static UI calls both and that UI is what production serves. They now
mean what is left of what they meant: `env-only` returns the environment half,
and `reset` answers honestly that there is nothing to reset. For the same
reason `GET /api/config` returns the flat key -> value map **as well as** the
grouped payload — the old page reads the flat one, the React page reads the
groups.

### Moving a setting across

Adding a row to `settings_registry.py` is the whole change. On the next start,
any database-eligible key still sitting in the env file is copied into the
database once, so behaviour does not change on the way over. After that the
database is authoritative and the env value is only a default for a fresh
install.


## The env file

Configuration lives in `dragoncp_env.env`, which must sit in the project root
next to `app.py`. Copy `dragoncp_env_sample.env` to that name to start.

Four separate loaders read it, and they do not agree with each other:

| Loader | Files it reads | Notes |
|---|---|---|
| `DragonCPConfig` (`config.py:20-31`) | `dragoncp_env.env` only | No `.env` fallback at all. This is the loader behind every `config.get(...)` in the routes and services. |
| Early loader (`app.py:46-72`) | `dragoncp_env.env`, else `.env` | Stops at the first file that exists. Feeds Flask/Socket.IO setup. |
| Auth loader (`auth.py:22-56`) | `dragoncp_env.env`, else `.env` | Same stop-at-first behaviour. Cached for the life of the process. |
| Webhook auth loader (`webhook_auth.py:51-86`) | Both, merged, `.env` wins | Refuses to start the request if a file exists but cannot be read, rather than falling through to allow-all. |

So a value placed only in `.env` reaches login and webhook authentication but
**not** `config.get(...)` — paths and SSH credentials will read as unset. Keep
everything in `dragoncp_env.env`.

The parser is deliberately simple (`config.py:34-50`): it skips blank lines and
lines whose first character is `#`, splits on the first `=`, and strips one
surrounding layer of quotes. Two consequences worth knowing:

- **Trailing comments become part of the value.** `PORT=5000  # backend` yields
  the literal string `5000  # backend`, which then fails to parse as a port and
  falls back to 5000 with a warning in the log.
- **`export KEY=value` produces a key named `export KEY`**, which nothing reads.

At startup `app.py:79-80` copies every env-file value into the process
environment with `setdefault`, which is how keys read via `os.environ` (the
logging and TEST_MODE keys) can be set in the env file at all. A real process
environment variable always wins over the env file for those keys, because
`setdefault` will not overwrite one.

Two exceptions to that, both covered again below: `ALLOW_QUERY_TOKEN_AUTH` is
evaluated during module import, before the copy happens, and the Gunicorn keys
are read by Gunicorn before the application is imported at all. Neither can be
set from the env file.

Whenever `config.get(...)` resolves to an empty value it prints
`Configuration key 'X' not found, using default` (`config.py:62-63`). It does
this even when a default was supplied, so the line appears routinely for
optional keys and is not on its own a fault.

---

## Connection

Read from the env file and read-only at runtime (see
[Precedence](#the-two-stores-and-which-one-wins)).

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `REMOTE_IP` | Hostname or IP of the media server (`app.py:424`, `services/transfer_service.py:238`, `:493`). | empty | Auto-connect returns "SSH credentials not configured" and the media browser stays empty. A transfer started anyway fails immediately with the same message in its progress line. |
| `REMOTE_USER` | SSH account on that server (`app.py:425`). | empty | Same as `REMOTE_IP`. |
| `REMOTE_PASSWORD` | Password used when no usable key file is found (`app.py:426`, `services/transfer_service.py:494`). | empty | Connection fails with an authentication error unless `SSH_KEY_PATH` is valid. Optional if you use a key. |
| `SSH_KEY_PATH` | Path to a private key. Relative paths are resolved against the project root; a path that does not exist is discarded and the connection falls back to the password (`services/transfer_service.py:512-523`). | empty | A wrong path is silently ignored — the log shows `SSH key file not found` and the connection either falls back to the password or fails. Note `ssh.py:155` loads it as an RSA key, so ed25519 keys do not work on the browse path. |
| `SSH_HOST_KEY_CHECKING` | Host-key policy for both browsing and rsync: `strict`, `accept-new`, or `no` (`ssh.py:47-61`). Accepted spellings are `strict`/`yes`, `accept-new`/`acceptnew`/`tofu`, and `no`/`off`/`none`/`false`/`disable`/`disabled`. | `accept-new` | An unrecognised value logs a warning and falls back to `accept-new`. Under `strict`, a host whose key was never provisioned refuses to connect with "not in known_hosts". Under `no`, every connection logs a man-in-the-middle warning. |
| `SSH_KNOWN_HOSTS_FILE` | Path to the managed known_hosts file used by both paramiko and rsync (`ssh.py:64-74`). | `dragoncp_known_hosts` in the project root | If the path is unwritable, first-connect keys are not persisted and a warning is logged. The path must not contain spaces — rsync splits the `-e` option string on spaces (`services/transfer_service.py:214-216`). |

When the server's key changes after being recorded, connections fail with a
host-key mismatch and the log names the known_hosts file to edit. See
[Media browser](../features/media-browser/README.md).

## Paths

All seven also define the filesystem security boundary: every read, write,
rename, backup and restore must resolve inside one of them
(`config.py:84-101`).

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `MOVIE_PATH` | Movies directory on the remote server. | empty | The Movies section of the browser lists nothing. |
| `TVSHOW_PATH` | TV directory on the remote server. | empty | The TV Shows section lists nothing. |
| `ANIME_PATH` | Anime directory on the remote server. | empty | The Anime section lists nothing. |
| `MOVIE_DEST_PATH` | Local destination for movies (`services/path_service.py:145`). | empty | Transfers of that type fail the destination check. |
| `TVSHOW_DEST_PATH` | Local destination for TV. Also serves the `series` alias (`services/path_service.py:148`). | empty | As above. |
| `ANIME_DEST_PATH` | Local destination for anime. | empty | As above. |
| `BACKUP_PATH` | Root of the backup tree: every movie and episode a sync has replaced, grouped by what it is. | **None. Required.** | Unset, transfers refuse to start, resume or restart, and say so. There is deliberately no fallback anywhere — writing to a temporary directory that a restore then refuses to read is what made backups look like they worked and be unrecoverable. See [Backups](../features/backups/README.md). |
| `BACKUP_RETENTION_KEEP` | How many previous versions of each movie or episode to keep. Older ones are removed once a new one is stored. | `2` (clamped to 1–50) | Pinned versions are never removed, and neither is anything newer than the grace period. |
| `BACKUP_RETENTION_GRACE_HOURS` | How long a newly stored version is protected from the rule above. | `24` | This is what stops an accidental sync immediately pushing the copy you wanted off the end of the list. |
| `BACKUP_RETENTION_ENABLED` | Set falsey to keep every version forever. | `true` | The backup disk fills. Usage is shown on the Backups page but never acted on automatically. |

## Authentication and web session

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `SECRET_KEY` | Flask session signing key (`app.py:86`, `:165`). Doubles as the JWT secret when `JWT_SECRET_KEY` is absent. | none — required | The process refuses to start: `Missing SECRET_KEY. Set SECRET_KEY in dragoncp_env.env, .env, or environment.` Changing it invalidates existing browser sessions, discarding any session config overrides. |
| `JWT_SECRET_KEY` | Signing key for access and refresh tokens (`auth.py:63-72`). | falls back to `SECRET_KEY` | If neither is set, every login attempt fails with an internal error. Rotating it logs everyone out immediately. |
| `JWT_EXPIRY_HOURS` | Access-token lifetime in hours (`auth.py:79`). Refresh tokens are fixed at 7 days (`auth.py:148`). | `24` | A non-numeric value raises on the first login attempt rather than falling back. A very small value makes the UI refresh constantly. |
| `DRAGONCP_USERNAME` | The single operator account name (`auth.py:75`). | `admin` | Login is rejected for any other name. |
| `DRAGONCP_PASSWORD` | Plain-text password, compared in constant time (`auth.py:105`). | empty | With neither this nor the hash set, `POST /api/auth/login` returns 503 "Authentication not configured. Set DRAGONCP_PASSWORD in environment." |
| `DRAGONCP_PASSWORD_HASH` | Werkzeug password hash. **Takes precedence** over the plain-text key when both are set (`auth.py:98-105`). | empty | A malformed hash makes every login fail while the plain-text value is ignored. |
| `CORS_ORIGINS` | Comma-separated allowed origins for the React frontend and Socket.IO (`app.py:93-100`, `:184-192`, `:284-301`). `*` allows everything. | `*` | If the frontend's origin is missing from the list, API calls fail in the browser with CORS errors and the realtime connection never establishes. Note that with `*` no credentials header is sent. |
| `ALLOW_QUERY_TOKEN_AUTH` | Allows a Socket.IO connection to authenticate with `?token=` instead of the auth payload (`websocket.py:32-39`). | `false` | Off by default; a connection with no auth payload is rejected and logged as `missing-auth-payload`. **This key cannot be set in the env file** — `websocket.py` is imported at `app.py:22`, which runs before the env-file values are copied into the process environment at `app.py:79-80`. It must be a real environment variable. |

HTTP endpoints only accept `Authorization: Bearer <token>`; a `?token=` query
parameter is accepted solely on WebSocket upgrade requests
(`auth.py:209-226`). See [Authentication](../features/auth/README.md).

`GET /api/config` redacts any key whose name contains `SECRET`, `PASSWORD`,
`API_KEY`, `TOKEN` or `CLIENT_SECRET`, returning `<redacted>` (`app.py:120-144`).
Posting `<redacted>` back is recognised and leaves the stored value untouched
(`app.py:147-160`), so saving the Settings screen does not blank out your
password.

## Webhooks

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `WEBHOOK_SECRET` | Shared secret for HMAC-SHA256 verification of the `X-DragonCP-Signature` header, format `sha256=<hex>` (`webhook_auth.py:188-224`). | unset | With neither this nor the IP list set, the three webhook receivers accept **anything** and log a startup warning that they are UNAUTHENTICATED. With it set and no IP list, an unsigned request gets 401 `WEBHOOK_SIGNATURE_MISSING` and a bad signature gets 401 `WEBHOOK_SIGNATURE_INVALID`. |
| `WEBHOOK_ALLOWED_IPS` | Comma-separated IPs and CIDR ranges permitted to post webhooks (`webhook_auth.py:122-152`). IPv4 and IPv6. | unset | An unparseable entry is dropped with a warning and the rest still apply. A caller outside the list gets 403 `WEBHOOK_IP_REJECTED`. Behind a reverse proxy, `request.remote_addr` is the proxy's address unless ProxyFix is applied, so legitimate callers are rejected. |
| `AUTO_SYNC_MOVIES` | Seed value only. Copied into `app_settings` at first start if no row exists, and used as the resolver's fallback until one does. | `false` | Once a row exists — which adoption creates on the first start after upgrading — this key stops having any effect. Details in [Precedence](#the-two-stores-and-which-one-wins). |

When both `WEBHOOK_SECRET` and `WEBHOOK_ALLOWED_IPS` are set, a request passes
if **either** check succeeds (`webhook_auth.py:384-411`). The config is cached
on first use; `reload_webhook_config()` exists to clear it without a restart.
See [Webhooks](../features/webhooks/README.md).

There are no env keys for `AUTO_SYNC_SERIES` or `AUTO_SYNC_ANIME`. Those two
resolve from the database with a hard-coded `False` default and read nothing
from the env file.

## Logging

All read from the process environment, which the env file feeds via
`app.py:79-80`.

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `LOG_LEVEL` | Threshold for the root logger, file handler and console handler (`logging_setup.py:303-304`). Also becomes Gunicorn's own `loglevel`, lowercased (`deploy/gunicorn.conf.py:19`). | `INFO` | An unrecognised name silently falls back to `INFO` (`getattr` on the logging module). `DEBUG` makes the log file grow fast and rotate often. |
| `LOG_MAX_BYTES` | Size at which the log file rotates (`logging_setup.py:306`). | `20971520` (20 MB) | A non-numeric value falls back to the default. Very small values rotate so fast the Logs screen shows almost nothing. |
| `LOG_BACKUP_COUNT` | Number of rotated files kept (`logging_setup.py:307`). | `10` | Non-numeric falls back to the default. `0` deletes history on every rotation. |
| `LOG_TO_CONSOLE` | Also write to the real stdout, in addition to the file (`logging_setup.py:326`). Accepts `1`/`true`/`yes`/`on`. | on | Turning it off leaves `journalctl` empty for the service; everything only reaches the log file. |
| `DRAGONCP_LOG_FILE` | Log file path. Relative paths resolve against the project root (`logging_setup.py:190-199`). | `logs/dragoncp_backend.log` | If the directory cannot be created the process fails at startup. Moving the file also moves what the in-app Logs screen reads (`routes/logs.py:136`, `:192`). |
| `DRAGONCP_REDIRECT_STD_STREAMS` | Route `print()` output through the logging system, inferring a level from the text (`logging_setup.py:239-245`). | on | Turning it off means most of the backend's `print`-based progress commentary disappears from the log file entirely, since much of the codebase logs by printing. |

Log records are sanitised before writing: values following a key whose name
contains `SECRET`, `PASSWORD`, `TOKEN`, `API_KEY` or `WEBHOOK` are replaced with
`<redacted>`, as are bearer tokens (`logging_setup.py:202-214`).

## Runtime and Gunicorn

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `PORT` | The port the backend listens on. Read twice, in two different places: `deploy/gunicorn.conf.py:4` builds the bind address, and `app.py:486-498` uses it for a direct `python app.py` start. | `5000` | For the direct start, a non-numeric or out-of-range value logs a warning and falls back to 5000. **For Gunicorn it cannot be set in the env file** — Gunicorn evaluates its config file before importing the app, so the env-file copy at `app.py:79-80` has not happened yet. Set it in the systemd unit (`deploy/dragoncp-ui.service.example` does exactly this). |
| `GUNICORN_THREADS` | Threads in the single `gthread` worker (`deploy/gunicorn.conf.py:10`). | `8` | Env-file values are ignored, as above. A non-numeric value stops Gunicorn from starting. Too few threads and concurrent API calls queue behind long-running ones. |
| `GUNICORN_TIMEOUT` | Seconds before Gunicorn kills a worker it considers hung (`:12`). | `120` | Too low and the worker is killed mid-request during slow SSH listings, dropping every open realtime connection. |
| `GUNICORN_GRACEFUL_TIMEOUT` | Seconds allowed for a clean shutdown (`:13`). | `30` | Too low and a restart cuts in-flight rsync monitoring short. |
| `GUNICORN_KEEPALIVE` | Seconds an idle keep-alive connection is held (`:14`). | `5` | Very low values cause avoidable reconnects for polling clients. |

`workers` is pinned to `1` in code and must stay there: Socket.IO state and the
background scheduler are process-local. See
[Runtime and deployment](../operations/runtime-and-deployment.md).

## WebSocket and Socket.IO

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `WEBSOCKET_TIMEOUT_MINUTES` *(an application setting, not env)* | Idle timeout, in minutes. Read from `app_settings` when a connection is established (`websocket.py`): the value is clamped to 5-60, five minutes of slack is added, and the result is capped at 65 minutes. The client-side idle timer reads the same key from `GET /api/config`. | server and client: 30 minutes, plus the server's 5-minute buffer | Set too low, the realtime connection drops while a long transfer is still running and the progress bar stops updating until you reload. It used to be read from the browser session, so the server's stale-connection reaper never saw a saved value and stayed at 35 minutes. |
| `SOCKETIO_VERBOSE_LOGGING` | Turns on Socket.IO and Engine.IO internal logging (`app.py:112-113`, `:184-192`). Also switched on implicitly by `TEST_MODE` or `FLASK_DEBUG`. | off | Leaving it on in production floods the log with per-packet lines. |

The Socket.IO ping interval (25s), ping timeout (60s) and async mode
(`threading`) are constants in `app.py:175-177`, not settings. If
`simple-websocket` is not installed the app logs a warning at startup and falls
back to polling.

## Storage monitoring

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `DISK_PATH_1` | First local mount reported by `GET /api/disk-usage/local`, via `df -h` (`routes/debug.py:270`). | `/home` | A path that does not exist is reported in the response as "Path not found or not configured" rather than failing the request. |
| `DISK_PATH_2` | Second monitored mount (`:271`). | empty | Shown as unavailable, same as above. |
| `DISK_PATH_3` | Third monitored mount (`:272`). | empty | Shown as unavailable, same as above. |
| `DISK_API_ENDPOINT` | URL of an external disk-usage API queried by `GET /api/disk-usage/remote` (`routes/debug.py:372`). | empty | The endpoint returns "Remote disk API endpoint not configured" and the remote storage panel stays empty. |
| `DISK_API_TOKEN` | Sent as `Authorization: Bearer <token>` to that endpoint (`routes/debug.py:373`, `:383`). | empty | Omitted entirely when unset; if the endpoint requires it the call fails with the upstream's status. |

Exactly three local paths are supported — the list is hard-coded.

## Development and test

| Key | What it does | Default when unset | If wrong or missing |
|---|---|---|---|
| `TEST_MODE` | Set to `1`, `true`, `yes` or `on` and rsync runs with `--dry-run`, rename webhooks report what they would rename without touching the file (`services/rename_service.py:342`), destination and backup directories are described rather than created, and config writes are skipped (`services/transfer_service.py:497`, `:555`, `:599`; `services/rename_service.py:342`; `services/backups/restore.py`; `config.py:124`). Simulations are exempt from the dry-run so they still move their own fixture bytes. Also turns on verbose Socket.IO logging and permits the unsafe Werkzeug server. | off | Left on in production, every transfer reports success while **no files are actually copied**. The startup log warns `Runtime is using development/test flags`. Path-by-path guarantees are in [test-mode.md](test-mode.md). Every reader goes through `env_flags.test_mode_enabled()`; until this was unified the banner accepted `true` while every safety gate demanded exactly `'1'`, so `TEST_MODE=true` announced test mode and copied and deleted for real. |
| `FLASK_DEBUG` | Enables Flask debug mode on a direct `python app.py` start and permits the unsafe Werkzeug server (`app.py:510-512`). | off | Never appropriate in production; exposes the interactive debugger. Same startup warning as above. |
| `DRAGONCP_DB` | Database path for `scripts/verify_v2_schema.py` only (`scripts/verify_v2_schema.py:6`). | `dragoncp.db` | The running application does not read this. `models/database.py:22-25` hard-codes `dragoncp.db` in the project root; there is no setting for it. |

These are read by tooling around the app rather than by the backend itself:

| Key | Where | What it does |
|---|---|---|
| `DRAGONCP_FRONTEND_PORT` | `docker-compose.yml:8`, `deploy-frontend.sh:9` | Host port for the frontend container. Defaults to `5002`. |
| `DRAGONCP_BACKEND` | `frontend/vite.config.ts` | Names the dev-server proxy target: `dev` (localhost:5050) or `prod` (localhost:5000). Defaults to `dev`. `prod` proxies to the live service — writes hit real data. |
| `DRAGONCP_BACKEND_URL` | `frontend/vite.config.ts` | An explicit proxy target that overrides `DRAGONCP_BACKEND`. |
| `VITE_API_URL` | `frontend/src/lib/api.ts:7` | API base URL baked in at build time. Defaults to `/api`. |
| `VITE_WS_URL` | `frontend/src/services/socket.ts:66` | Socket.IO URL baked in at build time. Defaults to the page's own origin. |
| `DRAGONCP_PYTHON_CMD` | `start.sh:168` | The interpreter `start.sh` hands to `start.py`. |

---

## The two stores, and which one wins

Configuration lives in two places, and the registry says which one owns each
key. Nothing else in the application needs to know.

### 1. The env file, read once at startup

`DragonCPConfig` reads `dragoncp_env.env` when the process starts and never
re-reads it (`config.py:31`). Editing the file has no effect until you restart
the service. This is the authoritative source for connection details, paths and
credentials.

There is no path by which a setting changed in the UI is written back to
`dragoncp_env.env`. `save_config()` was removed along with the session store —
a route that rewrites the file the process only reads at startup can only
produce a value that disagrees with the running service.

### 2. The `app_settings` table

A two-column key-value table in `dragoncp.db` (`models/database.py`,
`models/settings.py`). Values persist across restarts and are visible to
background work, because they are read straight from SQLite with no request
context needed. That is the whole reason a setting lives here.

Thirteen keys live here, all of them listed in `settings_registry.py`:

| Key | Default when no row exists | Bounds |
|---|---|---|
| `AUTO_SYNC_MOVIES` | `false` | — |
| `AUTO_SYNC_SERIES` | `false` | — |
| `AUTO_SYNC_ANIME` | `false` | — |
| `SERIES_ANIME_SYNC_WAIT_TIME` | `60` **seconds** | 30-900 |
| `DISCORD_NOTIFICATIONS_ENABLED` | `false` | — |
| `DISCORD_WEBHOOK_URL` | empty — notifications are skipped | — |
| `DISCORD_APP_URL` | `http://localhost:5000` | — |
| `DISCORD_ICON_URL` | empty | — |
| `DISCORD_MANUAL_SYNC_THUMBNAIL_URL` | empty | — |
| `BACKUP_RETENTION_ENABLED` | `true` | — |
| `BACKUP_RETENTION_KEEP` | `2` | 1-50 |
| `BACKUP_RETENTION_GRACE_HOURS` | `24` | 0-720 |
| `WEBSOCKET_TIMEOUT_MINUTES` | `30` | 5-60 |

Bounds are enforced in the registry, so they apply wherever the key is written
rather than only in the one route that happened to check.

Nothing else belongs in this table. In particular, none of the connection,
path, auth, logging or runtime keys are read from it.

### How a database setting resolves

`SettingsService.get()` answers in this order:

1. **The stored row, if there is one** — including a row holding an empty
   string. An empty value is a deliberate choice (it is how a webhook URL is
   cleared), not an absence, and treating it as missing meant a cleared Discord
   webhook silently kept posting to the env file's old URL.
2. **The env file**, as the default for a fresh or upgraded installation.
3. **The registry default.**

At startup, `adopt_env_defaults()` copies env-file values for database keys
into the table once, for keys with no row at all. Without it, moving a setting
across the boundary would change behaviour on the way over: the env value would
keep working as a fallback until someone saved something, then silently stop
being the source of truth.

### Writes are all-or-nothing

`POST /api/config` validates the entire payload before writing any of it, and
writes what survives in one transaction. A request that fails validation
returns 400 and changes nothing.

Environment keys in a payload are refused **by name** and reported in the
response's `refused` list, so a client can say which fields it could not change
rather than claiming a save that half happened.

### Summary of precedence

For a key read through the settings resolver: the database row, then the env
file, then the registry default.

For a key read through `config.get(...)` directly: the env file as loaded at
startup, then the caller's default.

For keys read through `os.environ` (logging, `TEST_MODE`, `FLASK_DEBUG`,
`PORT`, `SOCKETIO_VERBOSE_LOGGING`): a real environment variable, then the env
file's copy, then the caller's default — except `ALLOW_QUERY_TOKEN_AUTH` and
the Gunicorn keys, which never see the env file at all.

See [Auto-sync](../features/auto-sync/README.md) for what the toggles actually
trigger.

---

## Not verified

- Whether `SSH_KEY_PATH` pointing at a non-RSA key produces a clear operator
  message. `ssh.py:155` calls `paramiko.RSAKey.from_private_key_file`, and the
  failure is caught by the broad handler at `ssh.py:199`, but the resulting
  message was not observed.

## Related

- [Installation](../getting-started/installation.md)
- [Runtime and deployment](../operations/runtime-and-deployment.md)
- [Troubleshooting](../operations/troubleshooting.md)
- [API reference](api.md) — `/api/config`, `/api/webhook/settings`, `/api/discord/settings`
- [Database schema](database-schema.md) — the `app_settings` table
- [Authentication](../features/auth/README.md)
- [Webhooks](../features/webhooks/README.md)
- [Auto-sync](../features/auto-sync/README.md)
- [Notifications](../features/notifications/README.md) — what the Discord keys do
- [System overview](../architecture/system-overview.md)
