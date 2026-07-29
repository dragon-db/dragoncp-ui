# Configuration

Last updated: 2026-07-28
Primary files: `config.py`, `app.py`, `auth.py`, `webhook_auth.py`, `logging_setup.py`, `websocket.py`, `ssh.py`, `models/settings.py`, `deploy/gunicorn.conf.py`

Every setting DragonCP reads, where it comes from, and what an operator sees
when it is wrong. This page is derived from the code, not from the sample env
file — the code reads considerably more than the sample ships.

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

Read through `config.get(...)`, so session overrides apply inside a request (see
[Precedence](#the-three-stores-and-which-one-wins)).

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
| `BACKUP_PATH` | Root under which each sync gets its own directory of overwritten and deleted files. | `/tmp/backup` when building or rescanning backup directories (`services/backup_service.py:546`, `:412`); no default on the restore path (`:142`) | The two paths disagree when it is unset: backups are written under `/tmp/backup`, but a restore refuses with "BACKUP_PATH is not configured; refusing restore". So backups appear to work and then cannot be restored — and `/tmp` may be cleared out from under them. See [Backups](../features/backups/README.md). |

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
| `AUTO_SYNC_MOVIES` | Fallback only. Used as the default when the `app_settings` table has no `AUTO_SYNC_MOVIES` row (`routes/webhooks.py:113`, `:903-904`). Compared as the lowercase string `true`. | `false` | Once the toggle has ever been saved from the Settings screen, a database row exists and this key stops having any effect. Details in [Precedence](#the-three-stores-and-which-one-wins). |

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
| `WEBSOCKET_TIMEOUT_MINUTES` | Idle timeout, in minutes. Server-side it is read **only from the browser session's overrides**, never from the env file (`websocket.py:63-81`): the value is clamped to 5-60, five minutes of slack is added, and the result is capped at 65 minutes. The client-side idle timer reads it from `GET /api/config` and defaults to 30 (`frontend/src/hooks/useRuntime.ts:170`). | server: 35 minutes; client: 30 minutes | Putting it in the env file changes the browser's idle timer but leaves the server's stale-connection reaper at 35 minutes. Set too low, the realtime connection drops while a long transfer is still running and the progress bar stops updating until you reload. The Settings screen clamps input to 5-60 before saving. |
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
| `TEST_MODE` | Set to `1`, `true`, `yes` or `on` and rsync runs with `--dry-run`, rename webhooks report what they would rename without touching the file (`services/rename_service.py:342`), destination and backup directories are described rather than created, and config writes are skipped (`services/transfer_service.py:497`, `:555`, `:599`; `services/rename_service.py:342`; `services/backup_service.py:169` and six others; `config.py:124`). Simulations are exempt from the dry-run so they still move their own fixture bytes. Also turns on verbose Socket.IO logging and permits the unsafe Werkzeug server. | off | Left on in production, every transfer reports success while **no files are actually copied**. The startup log warns `Runtime is using development/test flags`. Path-by-path guarantees are in [test-mode.md](test-mode.md). Every reader goes through `env_flags.test_mode_enabled()`; until this was unified the banner accepted `true` while every safety gate demanded exactly `'1'`, so `TEST_MODE=true` announced test mode and copied and deleted for real. |
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

## The three stores, and which one wins

Configuration lives in three places with different lifetimes and different
reach.

### 1. The env file, read once at startup

`DragonCPConfig` reads `dragoncp_env.env` when the process starts and never
re-reads it (`config.py:31`). Editing the file has no effect until you restart
the service. This is the authoritative source for connection details, paths and
credentials, and it is the only store that background work can see.

`save_config()` exists on the config object and would rewrite the file, but no
route calls it; it is marked legacy in the code (`config.py:119-135`).

### 2. Per-session overrides from the Settings screen

`POST /api/config` writes into the Flask session cookie under `ui_config`
(`config.py:77-82`), and `config.get()` consults that first — **but only when a
request context is active** (`config.py:54-58`). `POST /api/config/reset`
deletes the override map.

This has a consequence that surprises people: transfers, the auto-sync
scheduler and the queue all run on background threads
(`services/transfer_service.py:643`, `services/transfer_coordinator.py:71` and
others), where there is no request context. **Session overrides therefore do
not affect any actual sync.** Changing a destination path in Settings changes
what the API reports back to that one browser and nothing else. Restarting the
backend, or simply opening the app in a different browser, discards them.

The Settings screen submits only the seventeen fields it lists
(`frontend/src/components/pages/settings.tsx:49-67`) — the connection keys, the
six media paths, `BACKUP_PATH`, the disk keys, and `WEBSOCKET_TIMEOUT_MINUTES`.
No other key can be overridden from the UI.

`GET /api/config` returns the env file merged with the session overrides;
`GET /api/config/env-only` returns the env file alone, which is what the
Settings screen compares against to show its "modified" count.

### 3. The `app_settings` table

A two-column key-value table in `dragoncp.db` (`models/database.py:174-182`,
`models/settings.py`). Values persist across restarts and — unlike session
overrides — they *are* visible to background work, because they are read
straight from SQLite with no request context needed.

Nine keys legitimately live here. All nine are written by the Settings screen
and by nothing else:

| Key | Written by | Read default when the row is absent |
|---|---|---|
| `AUTO_SYNC_MOVIES` | `POST /api/webhook/settings` (`routes/webhooks.py:928`) | the env file's `AUTO_SYNC_MOVIES`, else false |
| `AUTO_SYNC_SERIES` | `:933` | `False` |
| `AUTO_SYNC_ANIME` | `:938` | `False` |
| `SERIES_ANIME_SYNC_WAIT_TIME` | `:948`, clamped to 30-900 seconds | `60` seconds |
| `DISCORD_NOTIFICATIONS_ENABLED` | `POST /api/discord/settings` (`:997`) | `False` |
| `DISCORD_WEBHOOK_URL` | `:1001` | none — notifications are skipped |
| `DISCORD_APP_URL` | `:1005` | `http://localhost:5000` |
| `DISCORD_MANUAL_SYNC_THUMBNAIL_URL` | `:1009` | empty |
| `DISCORD_ICON_URL` | `:1013` | empty |

Nothing else belongs in this table. In particular, none of the connection,
path, auth, logging or runtime keys are read from it.

### The movie auto-sync toggle is the odd one out

The three auto-sync toggles do not resolve the same way, and it is worth being
precise about it because the difference is invisible in the UI.

Movies (`routes/webhooks.py:113`):

```python
auto_sync_enabled = transfer_coordinator.settings.get_bool(
    'AUTO_SYNC_MOVIES',
    default=(config.get("AUTO_SYNC_MOVIES", "false").lower() == "true"))
```

Series (`:243`) and anime (`:368`):

```python
auto_sync_enabled = transfer_coordinator.settings.get_bool('AUTO_SYNC_SERIES', False)
```

`get_bool` returns its default only when the database row is missing
(`models/settings.py:31-36`). So:

- **Movies.** Database row if one exists; otherwise the env file's
  `AUTO_SYNC_MOVIES`; otherwise off. The env value is a genuine fallback — but
  only until someone saves the Settings screen once. Saving writes a row for
  all three toggles, and from that moment `AUTO_SYNC_MOVIES` in the env file is
  permanently ignored. An operator who sets it in the file, toggles it in the
  UI, then later edits the file again will see no effect and no error.
- **Series and anime.** Database row if one exists; otherwise off, full stop.
  `AUTO_SYNC_SERIES` and `AUTO_SYNC_ANIME` in the env file are read by nothing.

One further wrinkle for movies: the default expression is evaluated eagerly on
every webhook, so `config.get("AUTO_SYNC_MOVIES", ...)` runs even when the
database row exists. Webhook requests carry no session cookie, so the session
layer is empty and it reads the env file. The visible side effect is a routine
`Configuration key 'AUTO_SYNC_MOVIES' not found` line in the log for anyone who
never set the key.

See [Auto-sync](../features/auto-sync/README.md) for what the toggles actually
trigger.

### Summary of precedence

For a key read through `config.get(...)`:

1. Session override, if one exists **and** a request is in flight
2. The env file as loaded at startup
3. The caller's default

For the nine `app_settings` keys: the database row, then the caller's default —
which for `AUTO_SYNC_MOVIES` alone is itself a `config.get(...)` lookup.

For keys read through `os.environ` (logging, `TEST_MODE`, `FLASK_DEBUG`,
`PORT`, `SOCKETIO_VERBOSE_LOGGING`): a real environment variable, then the env
file's copy, then the caller's default — except `ALLOW_QUERY_TOKEN_AUTH` and
the Gunicorn keys, which never see the env file at all.

There is no path by which a setting changed in the UI is written back to
`dragoncp_env.env`.

---

## Not verified

- The exact behaviour of `WEBSOCKET_TIMEOUT_MINUTES` when a Socket.IO
  connection is established without the Flask session cookie present. The code
  reads `session.get('ui_config', {})` at connect time (`websocket.py:71`) and
  falls back to 35 minutes on any error, but whether the cookie reliably
  accompanies the upgrade in every deployment topology was not tested.
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
