# DragonCP React Frontend

Frontend client for DragonCP admin operations.

## Scope (Current)

This UI is intended for trusted administrators only.

- Small operator group (typically 1-3 admins)
- No end-user account system
- No multi-tenant authorization model
- No public user-facing workflows

As of March 3, 2026, the product scope is admin-only.

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
