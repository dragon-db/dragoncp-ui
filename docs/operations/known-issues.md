# Known Issues

Defects found by reading the code while writing this documentation. Nothing here
has been fixed — this page exists so the findings are not lost and can be
triaged.

Each entry names the file and line so it can be checked. Entries marked
**verified** were re-checked by hand against the source; the rest come from the
documentation review and should be confirmed before acting on them.

---

## Data safety

### Backups written to `/tmp` can never be restored — **verified**

`BACKUP_PATH` has two different defaults. Writing falls back to `/tmp/backup`
(`services/backup_service.py:412`, `:546`), but restore refuses outright with
`BACKUP_PATH is not configured; refusing restore` (`:145`).

With `BACKUP_PATH` unset, every sync silently backs up replaced files into
`/tmp/backup` — where the OS may clear them — and the restore path will not
touch them. Backups appear to work and are unrecoverable.

Either default should match the other, or writing should refuse the same way
restore does.

### `migrate_v1_to_v2.py` will erase a v2 database — **verified**

`scripts/migrate_v1_to_v2.py:111` runs `DROP TABLE IF EXISTS` over a table list
that includes `transfers` and `app_settings`, both of which also exist in v2.
There is no check anywhere in the script that the target database is actually
v1 (zero guard references).

Run against an already-migrated install it drops all transfer history and
settings. The v2-only tables survive, so the result is a half-empty database
that still looks structurally valid.

Related: the script always exits `0` even when its own validation fails, and it
swallows extraction errors — a `--migrate-data` run can warn, report success,
and have carried nothing across.

### `TEST_MODE=true` runs real transfers — **verified**

Two readers disagree on what counts as enabled. `app.py:_env_flag` accepts
`1`, `true`, `yes` or `on` (`app.py:109`), and drives the development banner,
verbose Socket.IO logging and `allow_unsafe_werkzeug`. Every behavioural check
compares against the exact string `'1'` (`services/transfer_service.py:470`,
`:528`, and throughout `services/backup_service.py`).

So `TEST_MODE=true` produces a UI and logs that say test mode while rsync runs
for real and moves files. The flag that looks safest is the one that isn't.

Only `TEST_MODE=1` is safe. Both readers should use the same predicate.

---

## Configuration that silently does nothing

- **`AUTO_SYNC_SERIES` and `AUTO_SYNC_ANIME` are read by nothing.**
  `routes/webhooks.py:243` and `:368` pass a hard-coded `False` default to
  `settings.get_bool`. Only `AUTO_SYNC_MOVIES` has an env fallback
  (`routes/webhooks.py:113`), and that fallback stops applying permanently the
  first time the Settings screen is saved.
- **`ALLOW_QUERY_TOKEN_AUTH`, `PORT` and the four `GUNICORN_*` keys cannot be
  set in `dragoncp_env.env`.** They are evaluated before the env file is copied
  into `os.environ` — `websocket.py:39` at import time, and
  `deploy/gunicorn.conf.py` before gunicorn imports the app. They only work as
  real process environment variables.
- **`WEBSOCKET_TIMEOUT_MINUTES` in the env file does not reach the server.**
  `websocket.py:71` reads it only from the browser session's `ui_config`.
  Setting it in the env file changes the client-side idle timer but leaves the
  server's stale-connection reaper at its 35-minute default.
- **Settings-screen overrides are invisible to actual work.** `config.py:55`
  gates the lookup on `has_request_context()`, and transfers, the scheduler and
  the queue all run on daemon threads. Overriding a destination path changes
  only what the API reports back to that one browser.
- **Four env-file loaders with different rules.** `config.py` reads
  `dragoncp_env.env` only; `app.py` and `auth.py` stop at the first of the two
  files that exists; `webhook_auth.py` merges both with `.env` winning. A value
  placed only in `.env` reaches login and webhook auth but not `config.get()`.
- **The env parser keeps trailing comments as part of the value**
  (`config.py:43-44`), and `export KEY=value` produces a key literally named
  `export KEY`.
- **`ed25519` SSH keys cannot work on the browse path.** `ssh.py:155` uses
  `paramiko.RSAKey.from_private_key_file`.
- **`DragonCPConfig.save_config()` has no callers** (`config.py:119`).

---

## Logging and observability

- **Only the first secret on a line is redacted.**
  `logging_setup._sanitize_message` breaks out of its marker loop after the
  first match, so a line carrying two secrets leaks the second.
- **Failed validations are logged at INFO.** `services/sync_logger.log_validation`
  marks failures with ❌ but logs them at INFO, so a failed dry-run never
  appears under the log viewer's default `ERROR` filter.
- **Severity is inferred from message text, not the stream.** A line reading
  `Transfer ... finished with status: failed` is recorded as ERROR purely
  because it contains "failed"; Socket.IO's routine stderr chatter lands at INFO.
- **The `/api/logs` backward scan is capped at 20,000 lines**, and every HTTP
  request is itself logged at INFO (twice, counting werkzeug). An idle instance
  burns that window quickly, so anything older is only reachable by downloading
  the file or reading it on the host.
- **Rotated logs are not downloadable.** `/api/logs/download` serves only the
  live file.
- **The React frontend has no log viewer.** The only caller of these endpoints
  in the repository is the legacy `static/modules/log-viewer.js`.

---

## Realtime

- **`transfer_failed` has a listener and no emitter.**
  `frontend/src/services/socket.ts:206-211` exposes `onTransferError()` bound to
  `transfer_failed`; no backend code emits it. Currently latent because nothing
  imports that helper — failures arrive as `transfer_complete` with
  `status: "failed"`.
- **`rename_completed` is skipped when persistence fails.**
  `services/rename_service.py` returns early if `rename_model.update()` fails,
  so the files are renamed on disk and the UI never hears about it.
- **Every event is broadcast to every client.** No emit passes `room`, `to` or
  `namespace`.
- **Emits are swallowed.** `services/backup_service.py` wraps them in bare
  `try/except: pass`, and `routes/webhooks.py` routes them through
  `emit_socketio_event()`, which does the same.
- **`TransferUpdate` overstates its payload.** The TypeScript interface marks
  `status`, `progress`, `media_type` and `folder_name` required, but
  `transfer_queued` sends only `transfer_id` and `message`.

---

## UI

- **No dashboard panel renders an error.** Failed requests fall back to empty
  states, so a dead backend looks identical to an idle system. The backend
  already returns per-disk `error` strings that the UI discards.
- **Remote storage figures are inflated ~7.4%.** `routes/debug.py:395-414`
  multiplies the remote API's values by 1.073741824 and labels the result "GB",
  assuming the source reports GiB. The percentage is unaffected; the absolute
  numbers will not match what the server reports.
- **Local disks are numbered by availability, not by config key.** If
  `DISK_PATH_1` is unreachable, `DISK_PATH_2` is displayed as "Local Disk 1".
- **Webhook counts saturate.** `total` is `len()` of the already-limited list
  (`routes/webhooks.py:461`), so the ticker caps at 10 and the rail badge at 30.
- **The Manual status filter always returns nothing.** It queries
  `MANUAL_SYNC_REQUIRED`, which nothing writes.
- **`PARTIAL_SYNC` is rendered but never returned** by any backend code.
- **Undefined CSS variables.** `webhook-bits.tsx:29` builds the poster fallback
  from `var(--surface-3)` and `var(--surface-2)`; neither is defined anywhere in
  `frontend/src`, so the tile renders transparent.
- **Settings "Save All" is three sequential calls in one `try`.** An early
  failure skips the rest, and the only feedback is a generic toast — a partial
  save is invisible.
- **Disconnect on the Diagnostics tab is global.** It tears down the
  process-wide SSH manager, affecting every operator.

---

## Scripts and tests

- **`compact_transfer_logs.py` has a lost-update window.** It reads every row up
  front and writes back after the whole scan, so lines appended by a running
  transfer in between are silently discarded. Stop the app or wait for an idle
  queue.
- **`--backup` is ignored unless `--apply` is also passed.**
- **`verify_v2_schema.py` always exits 0**, even when checks print ✗, and it
  never inspects `sonarr_webhook` or `rename_webhook`.
- **`pytest` is not in `requirements.txt`**, so a virtualenv built by
  `start.py` cannot run the test suite.
- **`tests/` has no `__init__.py`**, so `python -m unittest discover` fails;
  only pytest works.
- **`start.py`'s frontend build step does nothing.** It prints a message and
  returns — `./start.sh` never runs `npm install` or `npm run build` despite the
  step numbering.
- **The queue's own test file is untracked.** `test/test_queue_behaviors.py`
  (singular `test/`) is a hand-rolled script outside git, so the most
  concurrency-sensitive subsystem has no tracked coverage.

---

## Related

- [Configuration](../reference/configuration.md)
- [Logging](logging.md)
- [Realtime contract](../reference/realtime.md)
- [Maintenance scripts](maintenance-scripts.md)
- [Testing](../getting-started/testing.md)
