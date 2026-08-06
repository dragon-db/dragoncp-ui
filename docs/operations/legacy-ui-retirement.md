# Legacy UI retirement

Last updated: 2026-08-06
Primary files: `app.py`, `frontend_serving.py`, `start.py`, `frontend/`, `deploy/dragoncp-ui.service.example`

The Jinja/Bootstrap client under `templates/` and `static/` has been retired.
DragonCP now serves the built React application from the same Flask/Gunicorn
process and port as `/api` and `/socket.io`. This page records why the cutover
was safe, how deployment works now, what compatibility remains, and how to
validate or roll back a release.

## Decision

The cutover is same-origin and single-service. Gunicorn remains the production
process, Flask serves `frontend/dist/index.html` and its hashed assets, and the
React client continues to use relative `/api` and `/socket.io` URLs. No reverse
proxy, second public port, CORS change, or multi-worker change is required.

The build output is deliberately not committed. A deployment builds it with
`npm ci` and `npm run build`; the example systemd unit refuses to start if
`frontend/dist/index.html` is absent. `./start.sh` builds automatically when the
output is missing or older than the React source.

## Capability audit

| Retired screen or control | React replacement | Result |
|---|---|---|
| Sign-in and token refresh | Login route and persisted auth store | Replaced; also supports named accounts and forced first password change |
| Disk monitor and status bar | Dashboard ticker, storage strip and realtime status | Replaced |
| Active/history transfers and controls | Transfers page and dashboard transfer panel | Replaced; includes queueing, pause/resume, paging and simulation |
| Transfer log tabs | Expandable transfer details | Replaced with HTTP snapshots plus per-transfer Socket.IO rooms |
| Webhook arrivals, manual sync and rename history | Webhooks page | Replaced; adds grouping, paging, bulk actions and rename verification |
| Browse Media | Explore | Superseded by a comparison, server-owned plan and dry-run gate |
| Per-transfer backup browser | Backups | Superseded by the slot/version model, retention, migration and reversible restore |
| Configuration, Discord and auto-sync | Settings | Replaced; environment-owned values are visibly read-only |
| SSH and WebSocket diagnostics | Settings → Diagnostics and the header realtime control | Replaced |
| Backend application logs | Settings → Diagnostics → Backend logs | Added for this cutover: severity/search filters, refresh and authenticated download |
| Account identity and action history | Settings → Account and Activity | React-only features that could not work correctly in the retired client |

The backend log viewer was the only operational capability missing from React
when this audit began. It was added before the old files were removed.

## Request routing

- `/` serves `frontend/dist/index.html`.
- Existing files under the build directory are served directly. Hashed
  `/assets/*` responses receive a one-year immutable cache policy.
- Extensionless client routes such as `/activity` and `/media/movies` fall back
  to `index.html`, allowing TanStack Router to resolve a page reload.
- Unknown `/api/*`, `/socket.io/*`, missing assets and missing files with an
  extension return a real 404; they never receive the SPA shell.
- If the build is missing, `/` returns `503 FRONTEND_BUILD_MISSING` with the
  exact build command. The backend does not silently revive the retired UI.

## Deployment

After pulling a release:

```bash
cd frontend
npm ci
npm run build
cd ..
venv/bin/python -m pytest tests/ -q
sudo systemctl restart dragoncp-ui
```

The supported runtime remains:

```bash
venv/bin/gunicorn --config deploy/gunicorn.conf.py app:app
```

The standalone nginx container remains useful as an optional preview or proxy,
but it is no longer required to make React the production UI.

## Compatibility retained for the soak period

Removing a browser does not require deleting its backend contracts in the same
release. The following are deprecated but retained for one production soak:

- the flat keys alongside the grouped `GET /api/config` response;
- `POST /api/config/reset` and `GET /api/config/env-only`;
- the old media-browse endpoints superseded by Explore;
- the old `/api/backups/<id>` compatibility endpoints backed by the current
  capture store.

Keeping them does not expose the retired HTML/JavaScript and makes rollback of
the browser layer possible without rolling back the additive account/activity
schema. Remove them in a later task only after production has completed login,
transfer, webhook, Explore, backup/restore, settings, diagnostics and Activity
checks on React.

## Release validation

Before calling the cutover trusted:

1. Build the frontend from a clean dependency install.
2. Start the supported single-worker Gunicorn service.
3. Load `/`, then reload `/activity` directly to verify SPA fallback.
4. Sign in with a named account that owes a password change and complete it.
5. Enable realtime, restart the service, and verify reconnect/fallback.
6. Exercise one safe simulated transfer and read its live and stored logs.
7. Open backend logs in Settings and download the full file.
8. Inspect webhook, Explore, backup and Activity pages against production data.
9. Disable a test administrator and confirm HTTP access stops immediately and
   the live socket closes within the five-second account sweep.

## Rollback

The removed client remains recoverable from Git history. Roll back the code
revision, rebuild/restart, and the previous `/` route returns. No database
rollback is required: the account and activity schema changes are additive, and
the retained compatibility endpoints still understand the old requests.

## Related

- [Runtime and deployment](runtime-and-deployment.md)
- [Frontend deployment](frontend-deployment.md)
- [Running the app](../getting-started/running.md)
- [Frontend reference](../reference/frontend.md)
