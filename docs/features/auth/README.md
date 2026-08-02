# Authentication

DragonCP is a single-operator tool. One administrator signs in with a username and password that live in the server's environment file, and everything the web interface does afterwards is carried by a short-lived token that the browser attaches to each request and to its live-updates connection. The three webhook receiver endpoints are the exception: Radarr and Sonarr cannot log in, so those endpoints are protected instead by a shared secret signature, a source-address allowlist, or both. A separate set of checks guards the folder and file names that arrive in requests and webhook payloads, so that no caller can steer a copy, rename, or restore outside the configured media and backup directories.

Last updated: 2026-07-28
Primary files: `auth.py`, `routes/auth.py`, `webhook_auth.py`, `security.py`, `websocket.py`

## Where it lives

| Concern | File |
| --- | --- |
| Credential check, token issue/validate, `require_auth` | `auth.py` |
| Login, logout, verify, refresh, status endpoints | `routes/auth.py` |
| Webhook receiver protection (HMAC + IP allowlist) | `webhook_auth.py` |
| Path-traversal validation helpers | `security.py` |
| WebSocket connect / re-authenticate handlers | `websocket.py` |
| Blueprint registration, CORS headers, secret-key check | `app.py` |
| Path validation at the transfer entry point | `routes/transfers.py`, `routes/media.py`, `routes/backups.py` |
| Path validation in the service layer | `services/path_service.py`, `services/rename_service.py`, `services/backups/layout.py` |
| Browser-side token storage and refresh | `frontend/src/stores/auth.ts`, `frontend/src/lib/api.ts`, `frontend/src/services/socket.ts` |

## How it works

### Where the credentials come from

`auth.py:_load_env_file()` reads `dragoncp_env.env`, or `.env` if the first is absent, and caches the result for the life of the process. `get_auth_config()` turns that into the working config: `DRAGONCP_USERNAME` (defaulting to `admin`), `DRAGONCP_PASSWORD_HASH`, `DRAGONCP_PASSWORD`, `JWT_SECRET_KEY` (falling back to `SECRET_KEY`, then to the same two names in the process environment), and `JWT_EXPIRY_HOURS` (defaulting to `24`). If no JWT secret can be found anywhere, `get_auth_config()` raises rather than signing tokens with a guessable key.

`verify_credentials()` compares the username first, then prefers the hashed password: if `DRAGONCP_PASSWORD_HASH` is set it uses Werkzeug's `check_password_hash`, otherwise it falls back to `hmac.compare_digest` against the plain-text `DRAGONCP_PASSWORD`. The constant-time comparison on the plain-text branch is deliberate — the fallback exists for simple setups, and it should still not leak the password one character at a time. With neither variable set, it logs a warning and denies. `hash_password()` is provided to generate a `pbkdf2:sha256` hash for the env file.

### Login and the two tokens

`POST /api/auth/login` (`routes/auth.py:api_login`) refuses early with `503` and code `AUTH_NOT_CONFIGURED` when `is_auth_configured()` reports no password at all, so an unconfigured install cannot be silently entered. It then requires a JSON body with `username` and `password`, verifies them, and on success issues two tokens:

- `generate_token()` builds the **access token**: claims `sub` (username), `iat`, `exp`, and `type: 'access'`, signed HS256, expiring after `JWT_EXPIRY_HOURS`.
- `generate_refresh_token()` builds the **refresh token**: the same claims but `type: 'refresh'` and a hard-coded 7-day expiry.

Both are returned along with `expires_at` and `refresh_expires_at`. The `type` claim is what keeps the two apart: `validate_token()` decodes and verifies the signature and expiry, then rejects the token if its `type` does not match the type the caller asked for. A refresh token therefore cannot be presented as an access token, even though both are signed with the same secret.

`POST /api/auth/refresh` takes `refresh_token` in the body, validates it as type `refresh`, and returns a **new access token only**. The refresh token itself is not rotated and not re-issued, so the 7-day window is absolute from login.

`GET /api/auth/verify` reports on whatever token the request carries. It answers `200` with `valid: true|false` rather than `401` — it is a status probe, not a gate. When valid it includes `remaining_seconds` from `get_token_remaining_time()`, which decodes with `verify_exp` disabled (the signature is still checked) so it can report the remaining life of a token that has just expired as `0` instead of failing.

`POST /api/auth/logout` is decorated with `require_auth` but does nothing except log. There is no server-side token store, so the real logout is the browser discarding its tokens.

`GET /api/auth/status` reports only whether a password is configured. It is intended to be called before the login form is shown.

### How requests are gated

`require_auth` in `auth.py` is a plain decorator applied per route, immediately under `@route(...)`. It calls `get_token_from_request()`, returns `401` with code `AUTH_REQUIRED` when there is no token, `401` with code `INVALID_TOKEN` when validation fails, and otherwise stashes the username on `g.current_user` and the claims on `g.token_payload` before calling the view.

`get_token_from_request()` accepts a token from the `Authorization: Bearer ...` header. It will also accept `?token=...`, but only when `_is_websocket_upgrade_request()` says the request is a WebSocket upgrade — checked via the `Upgrade` header, the `HTTP_UPGRADE` WSGI variable, or the presence of `wsgi.websocket` in the environ. This is the deliberate narrowing that keeps access tokens out of ordinary URLs, referrer headers, and proxy logs.

The decorator is applied to essentially every operational endpoint: all of `routes/transfers.py`, `routes/media.py`, `routes/backups.py`, `routes/logs.py`, `routes/simulation.py`, `routes/debug.py`, the webhook *management* endpoints in `routes/webhooks.py`, and the config/SSH endpoints defined directly in `app.py`. The unprotected surface is the login/verify/refresh/status endpoints, the three webhook receivers, and `GET /` which serves the page shell.

`optional_auth` also exists in `auth.py` and sets `g.current_user` to the username or `None` without ever rejecting. No route currently uses it.

### WebSocket connections

Live progress is delivered over Socket.IO. `websocket.py:register_websocket_handlers` registers a `connect` handler that expects the token in the Socket.IO auth payload (`auth: { token }` from the client). It passes that dict to `auth.py:validate_websocket_token()`, which validates it as an **access** token and returns the username. Returning `False` from the handler rejects the handshake, and the rejection is logged with the reason (`missing-auth-payload` or `invalid-or-missing-token`), the truncated session id, and the transport.

A query-string token is accepted for the handshake only if the environment flag `ALLOW_QUERY_TOKEN_AUTH` is truthy (`1`, `true`, `yes`, `on`); it defaults to off.

Accepted connections are recorded in an in-process map under a lock, along with the username, transport, origin, connect time, last activity, and a per-session timeout. Clients send an `activity` event to keep the timestamp fresh; a background thread started by `start_cleanup_thread()` disconnects sessions idle past their timeout (default 35 minutes, capped at 65) every five minutes.

Because the connection is authenticated once at handshake time, a token refresh would otherwise leave the socket holding a stale identity. The `authenticate` event handles that: the client re-sends the new token, `validate_websocket_token()` re-checks it, and the stored username and activity timestamp are updated. The handler acknowledges with `{success: true, user}` or `{success: false, message}`. Note it does **not** disconnect on failure — it just declines to update.

### What the browser does

`frontend/src/stores/auth.ts` keeps the access token, refresh token, username, and `expiresAt` in a Zustand store persisted to browser storage under the key `dragoncp-auth`. `shouldRefreshToken()` returns true when fewer than 30 minutes remain; `isTokenExpired()` uses a 5-minute margin.

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

The service layer repeats the checks rather than trusting its callers. `services/path_service.py:construct_destination_path()` validates components and then asserts bounds; `get_destination_path()` asserts bounds on the path it derives from a webhook's source path; `validate_destination_path()` returns `False` when no destination bases are configured at all. `services/rename_service.py` validates the webhook-supplied relative path and then asserts the assembled local path stays under the media destination base. `services/backups/layout.py` is the only place a path inside `BACKUP_PATH` is constructed: every title, season and slot segment is validated as a single path component and the assembled path is asserted to resolve inside the base, so a crafted library folder name cannot walk out of the tree. Restore validates its file selection and asserts its target stays inside a configured library.

## Behaviour worth knowing

- **Tokens cannot be revoked.** There is no blacklist and no server-side session. `POST /auth/logout` only writes a log line. An access token that leaks stays usable until its `exp` — up to `JWT_EXPIRY_HOURS`, 24 by default. Changing `DRAGONCP_PASSWORD` does not invalidate existing tokens; changing `JWT_SECRET_KEY` and restarting does, because every existing signature then fails to verify.
- **Refresh tokens are not rotated and their 7-day life is not configurable.** `JWT_EXPIRY_HOURS` affects only the access token. Refresh returns a new access token and nothing else, so exactly seven days after login the operator must log in again regardless of activity.
- **Auth config is cached for the process lifetime.** `auth.py` caches the parsed env file in `_env_config_cache` on first read and never invalidates it, so a password or JWT secret change in `dragoncp_env.env` requires a restart.
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

Authentication reads and writes no database tables. Credentials and secrets come from `dragoncp_env.env` (or `.env`) and the process environment; tokens are self-contained JWTs; WebSocket connection state is an in-process dictionary in `websocket.py` that is lost on restart. See [../../reference/database-schema.md](../../reference/database-schema.md) for the tables the rest of the application uses.

## API

| Method | Path | Auth |
| --- | --- | --- |
| POST | `/api/auth/login` | none |
| POST | `/api/auth/logout` | access token |
| GET | `/api/auth/verify` | none (reads token if present) |
| POST | `/api/auth/refresh` | refresh token in body |
| GET | `/api/auth/status` | none |
| POST | `/api/webhook/movies` | HMAC signature and/or source IP |
| POST | `/api/webhook/series` | HMAC signature and/or source IP |
| POST | `/api/webhook/anime` | HMAC signature and/or source IP |

Every other `/api/...` endpoint requires `Authorization: Bearer <access-token>`. Full request and response contracts are in [../../reference/api.md](../../reference/api.md).

## Related

- [../../reference/api.md](../../reference/api.md) — endpoint contracts and the authentication model summary
- [../../architecture/system-overview.md](../../architecture/system-overview.md) — where the auth layer sits in the request path
- [../../reference/path-handling.md](../../reference/path-handling.md) — how source and destination paths are constructed before validation
- [../queue/README.md](../queue/README.md) — what happens to a transfer once an authenticated request admits it
- [../simulation/README.md](../simulation/README.md) — the simulation endpoints, all behind `require_auth`
