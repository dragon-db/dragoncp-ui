# Authentication

DragonCP supports any number of named administrators. Each signs in with their own username and password, and everything the web interface does afterwards is carried by a short-lived token that the browser attaches to each request and to its live-updates connection. Accounts live in the database and are created, renamed, disabled and reset from the server with `scripts/manage_admins.py`; while no account exists there, the credentials in the environment file are accepted as a single fallback administrator, exactly as they were before named accounts. The three webhook receiver endpoints are the exception to all of this: Radarr and Sonarr cannot log in, so those endpoints are protected instead by a shared secret signature, a source-address allowlist, or both. A separate set of checks guards the folder and file names that arrive in requests and webhook payloads, so that no caller can steer a copy, rename, or restore outside the configured media and backup directories.

**Managing accounts is documented in [../../operations/admin-accounts.md](../../operations/admin-accounts.md).** That is the page to read to add, rename, disable or reset an administrator; this one covers how sign-in works.

Last updated: 2026-08-03
Primary files: `auth.py`, `routes/auth.py`, `models/admin_account.py`, `login_guard.py`, `actor.py`, `webhook_auth.py`, `security.py`, `websocket.py`

## Where it lives

| Concern | File |
| --- | --- |
| Credential check, token issue/validate, `require_auth` | `auth.py` |
| The account table and its rules | `models/admin_account.py`, `models/database.py` |
| Creating, renaming, disabling, resetting accounts | `scripts/manage_admins.py` |
| Sign-in throttling | `login_guard.py` |
| Who is responsible for an action (person or automation) | `actor.py` |
| Login, logout, verify, refresh, status, change-password endpoints | `routes/auth.py` |
| Webhook receiver protection (HMAC + IP allowlist) | `webhook_auth.py` |
| Path-traversal validation helpers | `security.py` |
| WebSocket connect / re-authenticate handlers | `websocket.py` |
| Blueprint registration, CORS headers, secret-key check | `app.py` |
| Path validation at the transfer entry point | `routes/transfers.py`, `routes/media.py`, `routes/backups.py` |
| Path validation in the service layer | `services/path_service.py`, `services/rename_service.py`, `services/backups/layout.py` |
| Browser-side token storage and refresh | `frontend/src/stores/auth.ts`, `frontend/src/lib/api.ts`, `frontend/src/services/socket.ts` |

## How it works

### Where the accounts come from

Accounts live in the `admin_account` table. `auth.py` holds a pointer to it, set once by `app.py:set_account_store()`, and `authenticate()` resolves a username and password against it first: the account must exist, be enabled, and match its stored `pbkdf2:sha256` hash. A disabled account fails exactly like a wrong password rather than announcing that it exists but is switched off.

The environment file is the fallback. `auth.py:_load_env_file()` reads `dragoncp_env.env`, or `.env` if the first is absent, and caches the result for the life of the process. `get_auth_config()` turns that into the working config: `DRAGONCP_USERNAME` (defaulting to `admin`), `DRAGONCP_PASSWORD_HASH`, `DRAGONCP_PASSWORD`, `JWT_SECRET_KEY` (falling back to `SECRET_KEY`, then to the same two names in the process environment), `JWT_EXPIRY_HOURS` (defaulting to `24`), and the three `LOGIN_*` throttle settings. If no JWT secret can be found anywhere, `get_auth_config()` raises rather than signing tokens with a guessable key.

`env_fallback_active()` is the single rule that decides whether those environment credentials are accepted: **true while no enabled account exists in the database.** That covers a fresh install, an upgrade from the single-operator setup, and a lockout where every account has been disabled. Adding or enabling the first account switches it off, and sessions opened against the fallback stop validating at that moment. On the plain-text branch the comparison is `hmac.compare_digest`, deliberately constant-time so the fallback does not leak its password one character at a time.

A username that does not exist is still checked against a throwaway hash (`_waste_time_like_a_real_check`) so that a wrong username costs the same time as a wrong password and cannot be told apart by how quickly it is rejected.

### Login and the two tokens

`POST /api/auth/login` (`routes/auth.py:api_login`) refuses early with `503` and code `AUTH_NOT_CONFIGURED` when `is_auth_configured()` reports that nobody can sign in at all. It then requires a JSON body with `username` and `password`, consults `login_guard` before touching the credentials, verifies them, and on success issues two tokens:

- `generate_token()` builds the **access token**: claims `sub` (username), `uid` (the stable account id), `tv` (the account's token version), `src` (`db` or `env`), `role`, `iat`, `exp`, and `type: 'access'`, signed HS256, expiring after `JWT_EXPIRY_HOURS`.
- `generate_refresh_token()` builds the **refresh token**: the same claims but `type: 'refresh'` and a hard-coded 7-day expiry.

`uid` and `tv` are what make sessions revocable. `uid` is the identity that survives a rename; `tv` is compared against the account row on every request, so bumping it retires every token already issued. See [Sessions end when the account changes](../../operations/admin-accounts.md#sessions-end-when-the-account-changes).

Both are returned along with `expires_at` and `refresh_expires_at`. The `type` claim is what keeps the two apart: `validate_token()` decodes and verifies the signature and expiry, then rejects the token if its `type` does not match the type the caller asked for. A refresh token therefore cannot be presented as an access token, even though both are signed with the same secret.

`POST /api/auth/refresh` takes `refresh_token` in the body, validates it as type `refresh`, re-checks the account behind it, and returns a **new access token only**. The refresh token itself is not rotated and not re-issued, so the 7-day window is absolute from login. A refresh token whose account has since been disabled, renamed or had its password changed will not mint anything.

`GET /api/auth/verify` reports on whatever token the request carries. It answers `200` with `valid: true|false` rather than `401` — it is a status probe, not a gate. It applies the same account check as `require_auth`, so a well-formed token for a revoked account reports `valid: false`. When valid it includes `remaining_seconds` from `get_token_remaining_time()`, which decodes with `verify_exp` disabled (the signature is still checked) so it can report the remaining life of a token that has just expired as `0` instead of failing.

`GET /api/auth/me` returns the caller's own identity: username, account id, role, whether a password change is still owed, and whether this is the fallback account.

`POST /api/auth/change-password` changes the caller's **own** password and nobody else's. It verifies the current password, applies the minimum-length rule, and refuses a new password identical to the old one. Succeeding retires every token the account held — including the caller's — so the response carries a fresh token pair for that browser to adopt. The fallback account is refused with code `FALLBACK_ACCOUNT` and pointed at `scripts/manage_admins.py`, because its password lives in the environment file and there is nothing stored to change.

`POST /api/auth/logout` is decorated with `require_auth` but does nothing except log. Server-side revocation exists, but it is the account's token version rather than a per-session record, so the real logout is still the browser discarding its tokens.

`GET /api/auth/status` reports whether anyone can sign in, how many accounts exist, and whether the environment fallback is currently in force. It is intended to be called before the login form is shown.

### How requests are gated

`require_auth` in `auth.py` is a plain decorator applied per route, immediately under `@route(...)`. It calls `get_token_from_request()`, returns `401` with code `AUTH_REQUIRED` when there is no token and `401` with code `INVALID_TOKEN` when the token itself does not validate.

It then calls `resolve_identity()`, which reads the account row and confirms the account may still act. That read is **fresh on every request and deliberately not cached**, the same way application settings are read; it is what makes a disable or a password change take effect at once instead of whenever the person's token happens to run out. Three further rejections come from it, all `401`:

| Code | Meaning |
| --- | --- |
| `ACCOUNT_DISABLED` | The account exists but has been switched off |
| `SESSION_REVOKED` | The token's version no longer matches the account — disabled, renamed, or password changed |
| `UNKNOWN_ACCOUNT` | No such account |

A fourth rejection is `403` with code `PASSWORD_CHANGE_REQUIRED`, returned while the account still owes its first password change. An account on a password somebody else chose is a credential two people know, so anything it does is not unambiguously that person's; the work is refused rather than recorded against a shared secret. `require_auth_pending_ok` is the exemption, applied to `/auth/me`, `/auth/logout` and `/auth/change-password` — blocking those would lock people out of the only thing that satisfies the requirement.

On success it stashes the username on `g.current_user`, the stable id on `g.current_account_id`, the whole identity on `g.current_account`, the claims on `g.token_payload`, and the responsible party on `g.current_actor` before calling the view.

### Who is responsible for an action

`actor.py` names the party behind every action, so nothing the application does is anonymous. An actor is one of three kinds — `admin` (a signed-in person, shown under their own username), `automated` (a named background process, shown as `AUTO / <name>`), or `system` (the application itself). Usernames are forbidden from starting with `auto` or `system` so the two can never be confused.

`require_auth` puts the person on `g.current_actor`; background entry points pass one of the named constants instead. Phase 1 establishes this vocabulary and resolves it per request; writing it onto a stored activity trail is phase 2.

### Sign-in throttling

`login_guard.py` counts failed sign-ins two ways at once — by client address and by username — and either hitting the limit locks further attempts for a cooldown. The check runs *before* the credential check, so a locked caller cannot use the endpoint to test passwords at all, and a correct password during a cooldown still fails. Defaults are five failures in fifteen minutes and a fifteen-minute lock, configurable through `LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_MINUTES` and `LOGIN_LOCKOUT_MINUTES`. State is in memory and clears on restart. Behind a proxy the address is taken from the first `X-Forwarded-For` entry. Full rationale, including why locking by username is an accepted trade-off, is in [../../operations/admin-accounts.md](../../operations/admin-accounts.md#sign-in-throttling).

`get_token_from_request()` accepts a token from the `Authorization: Bearer ...` header. It will also accept `?token=...`, but only when `_is_websocket_upgrade_request()` says the request is a WebSocket upgrade — checked via the `Upgrade` header, the `HTTP_UPGRADE` WSGI variable, or the presence of `wsgi.websocket` in the environ. This is the deliberate narrowing that keeps access tokens out of ordinary URLs, referrer headers, and proxy logs.

The decorator is applied to essentially every operational endpoint: all of `routes/transfers.py`, `routes/media.py`, `routes/backups.py`, `routes/logs.py`, `routes/simulation.py`, `routes/debug.py`, the webhook *management* endpoints in `routes/webhooks.py`, and the config/SSH endpoints defined directly in `app.py`. The unprotected surface is the login/verify/refresh/status endpoints, the three webhook receivers, and `GET /` which serves the page shell.

`optional_auth` also exists in `auth.py` and sets `g.current_user` to the username or `None` without ever rejecting. No route currently uses it.

### WebSocket connections

Live progress is delivered over Socket.IO. `websocket.py:register_websocket_handlers` registers a `connect` handler that expects the token in the Socket.IO auth payload (`auth: { token }` from the client). It passes that dict to `auth.py:validate_websocket_token()`, which validates it as an **access** token, applies the same account check as `require_auth`, and returns the identity. Returning `False` from the handler rejects the handshake, and the rejection is logged with the reason (`missing-auth-payload` or `invalid-or-missing-token`), the truncated session id, and the transport.

A query-string token is accepted for the handshake only if the environment flag `ALLOW_QUERY_TOKEN_AUTH` is truthy (`1`, `true`, `yes`, `on`); it defaults to off.

Accepted connections are recorded in an in-process map under a lock, along with the username, the account id, the token version, the auth source, transport, origin, connect time, last activity, and a per-session timeout. Clients send an `activity` event to keep the timestamp fresh; a background thread started by `start_cleanup_thread()` disconnects sessions idle past their timeout (default 35 minutes, capped at 65) every five minutes.

A socket authenticates once at handshake, so without further checks a disabled administrator would keep receiving updates until they happened to disconnect. Two things close that gap, both calling `auth.py:websocket_identity_still_valid()` with the account id and token version recorded at handshake:

- The `activity` ping re-checks the account, throttled to once a minute per connection (`AUTH_RECHECK_SECONDS`). A revoked account is dropped from the map and disconnected. This is the fast path — roughly a minute for an active client.
- The cleanup sweep re-checks connections that have stopped pinging, so a quiet socket cannot outlive its account either.

Because the connection is authenticated once at handshake time, a token refresh would otherwise leave the socket holding a stale identity. The `authenticate` event handles that: the client re-sends the new token, `validate_websocket_token()` re-checks it, and the stored username, account id, token version and activity timestamp are updated. The handler acknowledges with `{success: true, user}` or `{success: false, message}`. Note it does **not** disconnect on failure — it just declines to update; the activity re-check is what closes a socket whose account has gone.

### What the browser does

`frontend/src/stores/auth.ts` keeps the access token, refresh token, username, `expiresAt`, the account id, the role, whether a password change is owed, and whether this is the fallback account in a Zustand store persisted to browser storage under the key `dragoncp-auth`. `shouldRefreshToken()` returns true when fewer than 30 minutes remain; `isTokenExpired()` uses a 5-minute margin.

When `mustChangePassword` is set, `routes/_authenticated.tsx` renders `PasswordChangeGate` instead of the application and does not open the live connection. The check lives in the route rather than at sign-in so it survives a page reload and cannot be stepped around by navigating straight to a page; only signing out leads away from it. Changing the password swaps the returned token pair into the store and re-authenticates the socket, so succeeding does not bounce the person to the login screen.

`frontend/src/components/settings/account-panel.tsx` is the Account tab on Settings: who you are signed in as, the self-service password form, and a plain statement that adding or removing administrators happens on the server, with the commands to do it.

The axios request interceptor in `frontend/src/lib/api.ts` is where refresh actually happens: before each API call, if a refresh is due it posts to `/auth/refresh`, stores the new access token, and calls `reAuthenticateSocket()` so the live connection picks up the same token. If the refresh call fails it logs a warning and proceeds with the existing token rather than blocking the request. The response interceptor treats any `401` as terminal — it destroys the socket, clears the store, and redirects to `/login`.

`useVerifyAuth()` in `frontend/src/hooks/useAuth.ts` polls `/auth/verify` every five minutes while a token is present.

### Webhook receivers

`POST /api/webhook/movies`, `/api/webhook/series`, and `/api/webhook/anime` are decorated with `require_webhook_auth` from `webhook_auth.py`. Two settings drive it, read from the env file or the process environment and cached: `WEBHOOK_SECRET` and `WEBHOOK_ALLOWED_IPS`.

The decorator branches on which of the two are present:

| `WEBHOOK_SECRET` | `WEBHOOK_ALLOWED_IPS` | Behaviour |
| --- | --- | --- |
| unset | unset | Allow everything, log a warning once |
| unset | set | IP must match, else `403` `WEBHOOK_IP_REJECTED` |
| set | unset | Signature must verify, else `401` `WEBHOOK_SIGNATURE_MISSING` or `WEBHOOK_SIGNATURE_INVALID` |
| set | set | Pass if **either** check succeeds, else `403` `WEBHOOK_AUTH_FAILED` |

Signature verification (`verify_webhook_signature`) reads the `X-DragonCP-Signature` header, requires the `sha256=<hex>` form used by GitHub and similar providers, computes HMAC-SHA256 over the raw request body with the shared secret, and compares with `hmac.compare_digest`. The decorator calls `request.get_data()` before the view runs so it hashes the exact bytes received; Flask caches that body, so `request.json` inside the handler still works.

IP checking (`_parse_allowed_ips` / `is_ip_allowed`) accepts a comma-separated mix of single addresses and CIDR ranges, IPv4 or IPv6, parsed with `strict=False` so `192.168.1.100/24` is tolerated. Unparseable entries are logged and skipped rather than failing the whole list. The client address comes from `request.remote_addr`.

`_log_auth_status()` prints and logs the active posture once, on the first webhook that arrives, so an operator can see from the log whether the endpoints are unauthenticated, IP-only, signature-only, or both.

### Path validation

`security.py` is the boundary for anything that becomes a filesystem path. It exposes four checks and one exception:

- `validate_path_component()` — for a single segment such as a folder, season, or episode name. Rejects non-strings, empty or whitespace-only values, null bytes, `.` and `..`, any embedded `..`, and both `/` and `\`. Unicode, colons, brackets, and parentheses pass, because real media folder names contain them.
- `validate_relative_path()` — for multi-segment relative paths such as `Season 01/episode.mkv` from a Sonarr rename payload or a backup restore selection. Slashes are allowed; rejected are null bytes, embedded CR/LF, leading `/` or `\`, Windows drive-letter paths, and any segment equal to `..`. The CR/LF rejection exists because these paths are written into downstream file-list files, where a newline would split one entry into two.
- `validate_resolved_path()` — the real boundary check. Runs `os.path.realpath()` on both the candidate and each allowed base, then requires the candidate to equal a base or start with base + separator. The separator is appended on purpose so `/home/user` does not match `/home/username`.
- `assert_path_within_bounds()` — the preferred service-layer form. Refuses an empty path, refuses to proceed if the allowed-base list is empty after filtering (fail closed rather than allow), and raises `PathTraversalError` with the offending and resolved paths logged at warning level. Returns the canonical path for the caller to use.
- `PathTraversalError` subclasses `ValueError`, so existing `except ValueError` blocks in `services/path_service.py` catch it without change, while security-conscious callers can catch it specifically.

The two layers are used together. `routes/transfers.py:api_transfer` validates `folder_name`, `season_name`, and `episode_name` individually with `validate_path_component()` and returns `400` for any failure, then builds the destination path and calls `assert_path_within_bounds(dest_path, [base_dest])`. The comment there states the reason for doing both: component validation stops literal `..` in the request, and the realpath check catches an escape through a symlink that was already on disk. `routes/media.py` does the same for its browse and dry-run endpoints; `routes/backups.py:api_restore_backup` validates each entry of the `files` list with `validate_relative_path()`.

The service layer repeats the checks rather than trusting its callers. `services/path_service.py:construct_destination_path()` validates components and then asserts bounds; `get_destination_path()` asserts bounds on the path it derives from a webhook's source path; `validate_destination_path()` returns `False` when no destination bases are configured at all. `services/rename_service.py` validates the webhook-supplied relative path and then asserts the assembled local path stays under the media destination base. `services/backups/layout.py` is the only place a path inside `BACKUP_PATH` is constructed — the backup tree, the staging area and Explore's plan directories all go through it. Every title, season and slot segment is validated as a single path component and the assembled path is asserted to resolve inside the base, so a crafted library folder name cannot walk out of the tree. Explore used to build its plan paths itself as `BACKUP_PATH or '/tmp'`, which both skipped that check and wrote outside the backup area when the setting was unset. Restore validates its file selection and asserts its target stays inside a configured library.

## Behaviour worth knowing

- **Tokens are revoked per account, not per session.** Every token carries the account's `token_version`, and every request compares it against the row, so disabling an account, renaming it, or changing its password retires all of that account's tokens at once. What there is *no* mechanism for is retiring one session while leaving the others: `POST /auth/logout` still only writes a log line, and a leaked token stays usable until its `exp` unless something bumps the account's version. Changing `JWT_SECRET_KEY` and restarting still invalidates everything for everyone.
- **The fallback account cannot be revoked this way,** because it has no row to bump. Its sessions end when a real account is added or enabled — `env_fallback_active()` goes false and every fallback token stops resolving — or when `JWT_SECRET_KEY` changes.
- **Account changes take effect immediately; environment changes still need a restart.** Accounts are read from the database on every request, so `manage_admins.py` needs no restart. `auth.py` still caches the parsed env file in `_env_config_cache` on first read and never invalidates it, so changing `DRAGONCP_PASSWORD`, `JWT_SECRET_KEY` or the `LOGIN_*` throttle settings does require one.
- **Refresh tokens are not rotated and their 7-day life is not configurable.** `JWT_EXPIRY_HOURS` affects only the access token. Refresh returns a new access token and nothing else, so exactly seven days after login the operator must log in again regardless of activity.
- **Every authenticated request reads the account row.** This is a local SQLite read and deliberately uncached — the same pattern the settings resolver uses — and it is the price of revocation working at all. It has not been profiled under load.
- **Sign-in throttle state is per process and in memory.** A restart clears every counter and every lockout. Running more than one worker process would give each its own counters, multiplying the effective attempt allowance by the worker count.
- **Locking by username is a denial-of-service vector, accepted knowingly.** Someone who knows a colleague's username can keep that account locked by failing often enough. The reasoning is in [../../operations/admin-accounts.md](../../operations/admin-accounts.md#sign-in-throttling).
- **Webhook config is cached too, and its reload hook is unused.** `webhook_auth.reload_webhook_config()` exists to clear the cache after editing the env file, but nothing in the codebase calls it. In practice a restart is needed there as well.
- **The two env-file loaders behave differently on purpose.** `auth.py` reads the first file that exists and stops, and swallows read errors. `webhook_auth.py` reads and merges both files, with `.env` overriding `dragoncp_env.env`, and raises on a read error — the comment states this is so a broken file can never fall through to the unauthenticated allow-all path.
- **Unconfigured webhook auth is allowed, loudly.** With neither `WEBHOOK_SECRET` nor `WEBHOOK_ALLOWED_IPS` set, the receivers accept anything. This is stated as intentional backward compatibility, and the first request logs a `WARNING` and prints to stdout. Anyone who can reach those three URLs can queue transfers.
- **When both webhook checks are configured, they are OR'd, not AND'd.** A request from an allowlisted address is accepted with no signature at all. That is a convenience for LAN-local Radarr/Sonarr instances, not defence in depth against an attacker who is already inside the allowlisted range.
- **IP allowlisting depends on `remote_addr` being real.** Behind nginx, Traefik, or cloudflared, every request appears to come from the proxy unless `ProxyFix` is applied to the WSGI app. The `webhook_auth.py` docstring calls this out. Not verified: whether any shipped deployment configuration in `deploy/` applies `ProxyFix`.
- **`ALLOW_QUERY_TOKEN_AUTH` is read at import time from the process environment only.** `app.py` copies env-file values into `os.environ` with `setdefault`, but it does so *after* it imports `websocket.py`, and `websocket.py` evaluates the flag at module level. Setting `ALLOW_QUERY_TOKEN_AUTH` in `dragoncp_env.env` therefore has no effect; it must be a real environment variable. The safe default (off) is what you get from the env file either way.
- **`/auth/verify` never returns 401.** It answers `200` with `valid: false` for a missing, malformed, or expired token. Clients must read the body, not the status code.
- **A failed WebSocket re-authentication leaves the socket connected.** The `authenticate` handler returns `{success: false}` and logs, but does not disconnect; the connection keeps its previously validated username until it goes idle or the client disconnects.
- **A failed token refresh in the browser is not surfaced.** The request interceptor logs a warning and sends the old token; the user sees the consequence only as the subsequent `401`-driven redirect to the login page.
- **Tokens live in persisted browser storage** under `dragoncp-auth`, which is why a page reload keeps the session — and why anything with script access to the origin can read them.
- **CORS is permissive by default.** `app.py:get_cors_origins()` falls back to `*` when `CORS_ORIGINS` is unset, and the `after_request` hook then sets `Access-Control-Allow-Origin: *`. Credentials are only allowed when a specific origin is configured and echoed. Because the browser sends the token as an explicit `Authorization` header rather than a cookie, a wildcard origin does not by itself enable cross-site requests with the operator's credentials.
- **The app refuses to start without `SECRET_KEY`,** raising at import time in `app.py`. `JWT_SECRET_KEY` is separate and falls back to `SECRET_KEY` if unset.
- **`..` is rejected anywhere in a single path component, not only as a whole segment.** `validate_path_component()` rejects `foo..bar` as well as `..`. A legitimate media folder containing a literal double dot would be refused.
- **Path checks fail closed when nothing is configured.** `assert_path_within_bounds()` raises if the allowed-base list is empty, and `PathService.validate_destination_path()` returns `False` if no destination paths are set, so a half-configured install rejects transfers rather than writing to an unbounded location.

## Data

Authentication owns one table, `admin_account`, documented column by column in [../../reference/database-schema.md](../../reference/database-schema.md). Rows are never deleted; a departed administrator is disabled, because the activity trail refers back to these rows and the account `id` is the identity that survives a rename.

Everything else is outside the database. Secrets and the fallback credentials come from `dragoncp_env.env` (or `.env`) and the process environment; tokens are self-contained JWTs; sign-in throttle counters and WebSocket connection state are in-process and lost on restart.

## API

| Method | Path | Auth |
| --- | --- | --- |
| POST | `/api/auth/login` | none |
| POST | `/api/auth/logout` | access token |
| GET | `/api/auth/verify` | none (reads token if present) |
| GET | `/api/auth/me` | access token |
| POST | `/api/auth/change-password` | access token |
| POST | `/api/auth/refresh` | refresh token in body |
| GET | `/api/auth/status` | none |
| POST | `/api/webhook/movies` | HMAC signature and/or source IP |
| POST | `/api/webhook/series` | HMAC signature and/or source IP |
| POST | `/api/webhook/anime` | HMAC signature and/or source IP |

Every other `/api/...` endpoint requires `Authorization: Bearer <access-token>`. Full request and response contracts are in [../../reference/api.md](../../reference/api.md).

## Related

- [../../operations/admin-accounts.md](../../operations/admin-accounts.md) — **how to add, rename, disable or reset an administrator**, the fallback account, throttle tuning, and the automated-actor vocabulary
- [../../reference/api.md](../../reference/api.md) — endpoint contracts and the authentication model summary
- [../../architecture/system-overview.md](../../architecture/system-overview.md) — where the auth layer sits in the request path
- [../../reference/path-handling.md](../../reference/path-handling.md) — how source and destination paths are constructed before validation
- [../queue/README.md](../queue/README.md) — what happens to a transfer once an authenticated request admits it
- [../simulation/README.md](../simulation/README.md) — the simulation endpoints, all behind `require_auth`
