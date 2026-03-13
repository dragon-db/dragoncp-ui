# DragonCP Agent Notes

## Operational Scope

- DragonCP is an admin-only operations app, not an end-user product.
- Expected operators: 1-3 trusted admins.
- Typical access path is private network access such as `TAILSCALE_IP:PORT`.
- The UI may be idle for long periods while webhook-driven sync, queueing, and rsync activity continue in the background.
- Long-term uptime and transfer stability are higher priority than horizontal scale.

## Current UI Reality

- The currently served production UI is the legacy Flask/static UI from `templates/index.html` and `static/`.
- The React frontend in `frontend/` exists and should stay aligned, but it is not the active production UI yet.
- When fixing realtime issues, update the legacy Socket.IO client first, then mirror the same behavior in the React client.

## Runtime Expectations

- Production runtime target: `systemd + venv + gunicorn + gthread + 1 worker`.
- Recommended production command: `venv/bin/gunicorn --config deploy/gunicorn.conf.py app:app`.
- Keep the app single-worker for now. Do not increase Gunicorn workers above `1` unless the architecture is changed to support multi-process Socket.IO coordination and process-local background state.
- Keep Python dependencies inside the project virtual environment. Do not move installs to system Python unless explicitly requested.

## Development vs Production

- Development/test path: `TEST_MODE=1 ./start.sh`.
- Direct `python app.py` startup is acceptable for local debug/test only.
- Production should not rely on `allow_unsafe_werkzeug`.
- Production should use the committed systemd example at `deploy/dragoncp-ui.service.example` as the reference shape.

## Networking Assumptions

- No reverse proxy is required for the normal deployment model.
- Backend API and Socket.IO endpoints should stay on trusted/private network access unless explicitly redesigned.
- Publicly intended endpoints are webhook receivers only unless additional hardening is added.

## Future Reverse Proxy / Tunnel Guidance

- If the app is later exposed through Traefik, Cloudflared, or another proxy, keep it same-origin when possible.
- Proxy these paths together: `/`, `/api`, and `/socket.io`.
- "Expose React UI only" is not enough on its own; the browser still needs backend HTTP and Socket.IO access.
- If UI and backend ever move to different origins, update CORS/origin settings and explicit frontend API/socket URLs.

## Stability Priorities

- Preserve queue correctness and rsync process reliability.
- Avoid changes that assume high concurrency or internet-scale traffic.
- Prefer clear diagnostics around Socket.IO mode, reconnect behavior, and fallback transport state.
- Protect unattended operation: backend restarts, token refresh, websocket reconnect, and transfer monitoring should degrade gracefully.

## Documentation Lookup

- Use `docs/README.md` as the primary documentation index before searching individual docs.
- `docs/README.md` maps feature areas to the most relevant implementation/reference docs.
- When working on a feature, check the matching section in `docs/README.md` first, then open the targeted doc file.
- Useful common entry points:
  - runtime and deployment: `docs/runtime-stability/RUNTIME_STABILITY_IMPLEMENTATION.md`
  - transfer flow and architecture: `docs/SYNC_APPLICATION_ANALYSIS.md`
  - queue behavior: `docs/queue-management/QUEUE_MANAGEMENT_IMPLEMENTATION.md`
  - frontend React details: `docs/frontend/FRONTEND_REFERENCE.md`
  - API endpoints: `docs/api/API_REFERENCE.md`
