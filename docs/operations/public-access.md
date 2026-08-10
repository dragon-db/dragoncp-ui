# Public access over a Cloudflare Tunnel

Last updated: 2026-08-10
Primary files: `app.py`, `frontend_serving.py`, `webhook_auth.py`, `auth.py`, `login_guard.py`, `deploy/gunicorn.conf.py`

How DragonCP is exposed on a public HTTPS hostname, and the four settings that
have to be right before it is. Everything here assumes the same-origin serving
model established by the [React cutover](legacy-ui-retirement.md).

## One origin, one port

The tunnel points at a single port and that port carries everything:

```yaml
ingress:
  - hostname: cp.example.tld
    service: http://localhost:5000
  - service: http_status:404
```

It is worth being explicit about a thing that sounds achievable and is not:
**there is no configuration in which the UI is public and the API is private.**
The React bundle runs in the browser, so the browser is the client of the API.
Whatever is exposed must carry `/api` and `/socket.io` or the page loads and
then does nothing. "Backend internal" can only mean "port 5000 is not itself a
tunnel route" — the API surface is public either way, behind JWT.

The bundle asks for both relative to wherever it was served from:

- `frontend/src/lib/api.ts` — `baseURL: import.meta.env.VITE_API_URL || "/api"`
- `frontend/src/services/socket.ts` — `getSocketUrl()` falls back to
  `window.location.origin`

Neither `VITE_*` variable is set in a normal build, and neither should be.
Because the origin is discovered at runtime, changing the public hostname needs
no rebuild — only the CORS entry below.

## `CORS_ORIGINS` must list the public origin

This is the one that fails in a way that does not look like its cause. Set a
list and it replaces Socket.IO's default of accepting its own origin, so the
public hostname has to be named explicitly:

```
CORS_ORIGINS="http://dragondb:5000,https://cp.example.tld"
```

Exact scheme and host, no trailing slash, no port for the tunnel entry. Omit it
and the symptom is *not* a CORS error in the console: browsers do not send
`Origin` on a same-origin GET, so the Socket.IO handshake succeeds, and they do
send it on every POST, so the next request is rejected with a bare `400`. The
socket connects and drops in a permanent loop.

`cors_origins` is read once at import (`app.py:146`), so a change needs a
service restart. Verify per origin rather than trusting the file:

```bash
for o in https://cp.example.tld https://not-listed.example; do
  printf '%-32s ' "$o"
  curl -sS -o /dev/null -w '%{http_code}\n' -H "Origin: $o" \
    "http://localhost:5000/socket.io/?EIO=4&transport=polling"
done
# 200 = accepted, 400 = refused
```

## The webhook receiver becomes reachable too

`/api/webhook/movies`, `/api/webhook/series` and `/api/webhook/anime` are the
three routes carrying `@require_webhook_auth`. With neither `WEBHOOK_SECRET`
nor `WEBHOOK_ALLOWED_IPS` set they accept anything — harmless on an internal
port, not harmless on a public origin, where an unauthenticated POST can queue
a real transfer.

HMAC is the stronger control but is not usable here: Radarr and Sonarr cannot
compute a signature, so the IP allowlist is what actually works.

```
WEBHOOK_ALLOWED_IPS="100.64.0.0/10"
```

Two things make that the right value rather than a single `/32`. Deliveries
arrive over Tailscale, and a re-issued tailnet address would otherwise break
auto-sync silently. And `webhook_auth.py` reads `request.remote_addr` with no
`ProxyFix`, so anything arriving through the tunnel presents as `127.0.0.1` and
is rejected by a rule that trusts only the tailnet — **do not add `127.0.0.1`
to this list.** Confirm with a POST from the host itself, which should be
refused:

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{}' \
  http://localhost:5000/api/webhook/movies
# {"code":"WEBHOOK_IP_REJECTED", ...}
```

## Sign-in, once anyone can reach it

- **Use `DRAGONCP_PASSWORD_HASH`, not `DRAGONCP_PASSWORD`.** The hash wins when
  both are present; remove the plain-text key once the hash is in place.
- **Create named accounts.** The environment-file credentials are a recovery
  path, not an operating mode — see [admin-accounts.md](admin-accounts.md). The
  application logs a warning on every boot until the first account exists.
- **Sign-in throttling counts by address and by username** (`LOGIN_MAX_ATTEMPTS`,
  `LOGIN_WINDOW_MINUTES`, `LOGIN_LOCKOUT_MINUTES`, defaulting to 5 / 15 / 15).
  `routes/auth.py:_client_address()` trusts the first `X-Forwarded-For` entry,
  which is correct for one proxy hop and forgeable by anything that can reach
  port 5000 directly. Keeping that port off the public interface is part of the
  control.
- **`ALLOW_QUERY_TOKEN_AUTH` must stay off.** It would let the socket token
  travel in a query string, where every proxy and access log along the path
  records it. It defaults to `False` and, per
  [known-issues.md](known-issues.md), can only be set as a real process
  environment variable anyway.

## Timeouts

Gunicorn's `timeout` is 120s (`deploy/gunicorn.conf.py`), which is longer than
Cloudflare's origin response limit of roughly 100s. A genuinely slow request
therefore surfaces as a `524` at the edge before the worker gives up. Nothing
in normal use approaches it — transfers report over the socket rather than
holding a request open — but the authenticated backend-log download is the one
endpoint that can, on a large log.

WebSockets survive: Socket.IO pings every 25s, comfortably inside Cloudflare's
idle window, and polling remains as a fallback.

## The second front door is closed

The `dragoncp-ui-frontend-1` nginx container published the same React app on
`:5002` and proxied `/api` to the backend. It is stopped. Its compose and
Dockerfile are kept for the optional topology described in
[frontend-deployment.md](frontend-deployment.md), but it is no longer part of
production: it holds its own copy of the bundle baked at image build time, so
leaving it running after a deploy serves a stale client against a current API.

## Related

- [Legacy UI retirement](legacy-ui-retirement.md) — the same-origin model
- [Frontend deployment](frontend-deployment.md) — build and cache requirements
- [Administrator accounts](admin-accounts.md) — accounts and the fallback rule
- [Configuration reference](../reference/configuration.md) — every setting
