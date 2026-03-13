# Runtime Stability Implementation

Last updated: 2026-03-14
Related issues: `#38`, `#39`
Branch context: `feature/runtime-stability`

## Purpose

This document records the production-runtime and Socket.IO stability work completed for the runtime-stability feature so other agents can quickly review what changed and why.

## Objectives Covered

- Harden the production run path so non-debug runs do not rely on unconditional `allow_unsafe_werkzeug`.
- Standardize the intended production runtime on `systemd + venv + gunicorn + gthread + 1 worker`.
- Make backend Socket.IO runtime behavior explicit and easier to diagnose.
- Improve legacy production UI reconnect/fallback behavior for Socket.IO.
- Keep the React Socket.IO client aligned with the same backend/runtime assumptions.
- Add AI/operator-facing documentation for deployment, usage conditions, and future reverse-proxy notes.

## Implementation Steps Taken

### 1. Backend runtime contract and hardening

- Explicitly set Socket.IO runtime mode to threaded mode.
- Replaced implicit Socket.IO runtime auto-detection assumptions with fixed runtime metadata.
- Gated verbose Socket.IO and Engine.IO logging to test/debug-oriented environments.
- Replaced the previous long ping interval/timeout values with more production-friendly keepalive settings.
- Changed direct `python app.py` startup so unsafe Werkzeug mode is no longer enabled unconditionally.
- Added startup/runtime diagnostics that expose Socket.IO mode, keepalive settings, and websocket transport readiness.

### 2. Backend websocket reliability

- Added guarded/shared-state handling around the websocket connection registry.
- Added cleanup-thread single-start protection.
- Tightened websocket auth handling to prefer Socket.IO auth payloads and disable query-string token fallback unless explicitly enabled.
- Improved connection, disconnect, re-authentication, and stale-cleanup logging.
- Extended debug endpoints to expose runtime metadata, cleanup-thread status, transport type, and connection details.

### 3. Legacy production UI Socket.IO stability

- Fixed the legacy client reconnect behavior so it no longer disables reconnection.
- Adjusted transport preference to allow safer fallback behavior.
- Disabled sticky upgrade memory to avoid repeatedly preferring a bad websocket path.
- Improved status messaging so reconnecting/fallback states are shown differently from hard failure.
- Added reconnect-attempt and transport-upgrade diagnostics in the client.
- Improved token-refresh re-authentication behavior so the socket can recover more cleanly.

### 4. React client alignment

- Reworked the React socket service to use a single reusable socket instance.
- Applied the same polling-first / upgrade-enabled / no-rememberUpgrade strategy used in the legacy client.
- Added reconnect and transport diagnostics.
- Re-authenticate the socket after token refresh from the HTTP client layer.
- Disconnect the socket on auth failure/401 so auth state and realtime state stay in sync.

### 5. Production deployment and operator docs

- Added an AI-facing `AGENTS.md` with deployment assumptions, runtime constraints, UI reality, networking guidance, and stability priorities.
- Added a committed Gunicorn config for the supported production runtime.
- Added a committed example systemd service file for production.
- Updated main docs to describe:
  - dev/test vs production startup
  - single-worker production expectation
  - venv requirement
  - current production UI reality
  - future same-origin reverse-proxy guidance

### 6. Follow-up review fixes

- Hardened `/api/connect` JSON parsing so malformed non-object payloads now fail with a controlled `400` response instead of risking attribute errors.
- Changed the example systemd service to mount `~/.ssh` as read-only rather than writable.
- Updated debug routes to use controlled `503` responses when dependent services are not initialized.
- Fixed debug timeout reporting to use the actual Flask session when computing websocket timeout.
- Updated websocket connection setup to use Flask's session proxy instead of unsupported `request.environ['flask.session']` access.
- Switched stale websocket cleanup to disconnect through the Socket.IO server API before removing local registry state.
- Added a defensive React socket re-authentication ack guard for missing/undefined callback responses.

## Files Touched For This Feature

### Backend runtime and websocket

- `app.py`
- `websocket.py`
- `routes/debug.py`
- `requirements.txt`

### Legacy production UI realtime client

- `static/modules/websocket-manager.js`

### React alignment

- `frontend/src/services/socket.ts`
- `frontend/src/lib/api.ts`

### Deployment and AI/operator docs

- `AGENTS.md`
- `deploy/gunicorn.conf.py`
- `deploy/dragoncp-ui.service.example`
- `README.md`
- `SETUP.md`
- `frontend/README.md`
- `frontend/package.json`
- `docs/runtime-stability/RUNTIME_STABILITY_IMPLEMENTATION.md`

## Verification Performed

- Python syntax compilation check for key backend/runtime files succeeded.
- Frontend production build was verified after Node/npm became available.
- The React build workflow was adjusted so TanStack Router can generate `src/routeTree.gen.ts` before TypeScript validation runs.
- A React Socket.IO typing issue caused by a readonly `transports` tuple was fixed so TypeScript accepts the client options.
- Legacy Socket.IO client syntax was checked with Node after the reconnect/fallback changes.
- A clean React build was verified by removing the generated route tree first, then running the updated build command successfully.

## Frontend Verification Fixes

- `frontend/package.json`
  - Kept the build order as `vite build && tsc -b` because TanStack Router generates `src/routeTree.gen.ts` during the Vite step; reversing the order breaks clean builds when the generated route tree is absent.
- `frontend/src/services/socket.ts`
  - Changed the `transports` option typing from a readonly tuple to a mutable `string[]` so the Socket.IO client options satisfy TypeScript.

## Remaining Operator Validation

- Install updated Python dependencies inside the project venv.
- Update the production systemd service to use the committed Gunicorn-based ExecStart.
- Restart the service and verify:
  - login
  - initial realtime connect
  - reconnect after service restart
  - reconnect after token refresh
  - background transfer monitoring while UI is idle

## Notes For Future Agents

- The legacy Flask/static UI is still the active production UI; treat it as the primary runtime path.
- The React client has been aligned but is not yet the served production UI.
- The app is intentionally single-worker today; do not raise worker count without redesigning process-local Socket.IO/background coordination.
- Same-origin proxying is the preferred future path if the app is later exposed through Traefik or Cloudflared.
