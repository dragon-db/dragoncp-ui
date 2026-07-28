# Troubleshooting

## Authentication and sessions

- `Session expired. Please sign in again.`:
  - Refresh token is expired/invalid, or JWT secret changed.
  - Sign in again and verify `JWT_SECRET_KEY` consistency across restarts.
- `WebSocket connection failed` immediately after login:
  - Access token might be invalid or stale.
  - Sign out/sign in again and confirm backend `/api/auth/verify` returns `valid: true`.
- Repeated 401/API failures:
  - Confirm `DRAGONCP_PASSWORD`/`DRAGONCP_PASSWORD_HASH` is configured.
  - Confirm server clock is correct (JWT expiry depends on time).
- Login endpoint returns auth not configured:
  - Set `DRAGONCP_PASSWORD` (or `DRAGONCP_PASSWORD_HASH`) in `dragoncp_env.env` and restart.

## Related

- [Authentication](../features/auth/README.md)
- [Runtime and deployment](runtime-and-deployment.md)
- Server logs: `GET /api/logs`, documented in [the API reference](../reference/api.md)
