# DragonCP React Frontend

Frontend client for DragonCP admin operations.

## Scope (Current)

This UI is intended for trusted administrators only.

- Small operator group (typically 1-3 admins)
- No end-user account system
- No multi-tenant authorization model
- No public user-facing workflows

As of March 3, 2026, the product scope is admin-only.

## Production Reality (Current)

- The active production UI is still the legacy Flask/static interface from `templates/index.html` and `static/`.
- This React app should stay aligned with backend and realtime behavior, but it is not the served production UI yet.

## Network and Exposure Model

- Backend API and Socket.IO endpoints are expected to be reachable only by admins (localhost/LAN/Tailscale/VPN or controlled reverse proxy).
- Webhook receiver endpoints may be exposed publicly for Radarr/Sonarr:
  - `POST /api/webhook/movies`
  - `POST /api/webhook/series`
  - `POST /api/webhook/anime`

## Auth Behavior

- HTTP API calls must include `Authorization: Bearer <access-token>`.
- Query-string token auth (`?token=...`) is not supported for normal HTTP endpoints.
- WebSocket auth uses Socket.IO auth payload (`auth: { token }`).

## Development

```bash
npm install
npm run dev
```

## Build

```bash
npm run build
```

## Docker

This repo includes a production-style Docker setup for the React frontend.

- The frontend builds into static assets and runs behind nginx in a container.
- nginx serves the React app and reverse-proxies `/api` plus `/socket.io` to the existing backend on the host at `http://host.docker.internal:5000`.
- This keeps the browser same-origin, so the default frontend API and Socket.IO behavior works without baking custom `VITE_API_URL` or `VITE_WS_URL` values into the build.

### Start the frontend container

From the project root:

```bash
docker compose up -d --build frontend
```

### Redeploy after frontend changes

From the project root:

```bash
./deploy-frontend.sh
```

The deploy script validates Docker availability, stops the running frontend container if present, rebuilds the image from the latest checked-out frontend source, and starts the container again.

Default access URL:

```text
http://localhost:5002
```

### Requirements

- The backend must already be running on the host at port `5000`.
- This compose setup is intended for Linux hosts and uses Docker's `host-gateway` mapping for `host.docker.internal`.

### Optional port override

You can change the exposed frontend port without editing `docker-compose.yml`:

```bash
DRAGONCP_FRONTEND_PORT=3000 docker compose up -d --build frontend
```
