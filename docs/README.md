# DragonCP Documentation Index

Use this file as the primary index for documentation under `docs/`. If you need feature context, implementation history, API details, or deployment notes, start here and then open the most relevant doc.

## How To Use This Index

- Start with the topic table in the next section.
- If the work is runtime, deployment, websocket, or service related, read `docs/runtime-stability/RUNTIME_STABILITY_IMPLEMENTATION.md` first.
- If the work is transfer, queue, rsync, or webhook related, read `docs/SYNC_APPLICATION_ANALYSIS.md` and `docs/queue-management/QUEUE_MANAGEMENT_IMPLEMENTATION.md` first.
- If the work is React/frontend specific, read `docs/frontend/FRONTEND_REFERENCE.md` first.
- If you are unsure, scan the feature sections below for the closest match.

## Quick Topic Map

| Topic | Start Here |
|---|---|
| Runtime, deployment, systemd, websocket stability | `docs/runtime-stability/RUNTIME_STABILITY_IMPLEMENTATION.md` |
| Sync architecture, webhooks, rsync flow | `docs/SYNC_APPLICATION_ANALYSIS.md` |
| Queueing and transfer promotion | `docs/queue-management/QUEUE_MANAGEMENT_IMPLEMENTATION.md` |
| Testing transfers end to end without touching media | `docs/simulation/SIMULATION_IMPLEMENTATION.md` |
| Path handling and destination rules | `docs/path-service/PATHSERVICE_IMPLEMENTATION_SUMMARY.md` |
| React frontend structure and usage | `docs/frontend/FRONTEND_REFERENCE.md` |
| HTTP/API endpoints | `docs/api/API_REFERENCE.md` |
| Architecture and refactoring history | `docs/refactoring/REFACTORING_GUIDE.md` |
| Database schema | `docs/database/v2_schema.md` |
| Auto-sync redesign notes | `docs/auto-sync/v3_autosync_implementation.md` |
| Future/planned rsync log streaming work | `docs/plans/RSYNC_LOG_STREAMING_REDESIGN.md` |
| Planned remote connection check (with the native client) | `docs/plans/REMOTE_CONNECTION_CHECK.md` |
| Agent/frontend-design skill notes | `docs/SKILLS/frontend-design/SKILL.md` |

## Documentation By Feature Area

### Root-Level Docs

- `docs/SYNC_APPLICATION_ANALYSIS.md`
  - End-to-end backend sync architecture, webhook flow, queueing behavior, rsync execution model, and QoS recommendations.
- `docs/README.md`
  - This index file.

### `/runtime-stability/`

- `docs/runtime-stability/RUNTIME_STABILITY_IMPLEMENTATION.md`
  - Runtime hardening for issues `#38` and `#39`, including Socket.IO stability, Gunicorn/systemd deployment, touched files, and verification notes.

### `/queue-management/`

- `docs/queue-management/QUEUE_MANAGEMENT_IMPLEMENTATION.md`
  - Queue behavior, duplicate detection, concurrent transfer limits, and promotion behavior.

### `/simulation/`

- `docs/simulation/SIMULATION_IMPLEMENTATION.md`
  - Running the real transfer pipeline against throwaway local files: scenarios,
    the safety guards that make it usable in production, and what it
    deliberately does not cover.

### `/path-service/`

- `docs/path-service/PATHSERVICE_IMPLEMENTATION_SUMMARY.md`
  - Path normalization and destination-path construction behavior used by transfer logic.

### `/frontend/`

- `docs/frontend/FRONTEND_REFERENCE.md`
  - React frontend architecture, route structure, state usage, and current frontend implementation notes.

### `/api/`

- `docs/api/API_REFERENCE.md`
  - API endpoint reference and request/response details.

### `/auto-sync/`

- `docs/auto-sync/v3_autosync_implementation.md`
  - Auto-sync redesign details, queue conversion behavior, and webhook-driven sync decisions.

### `/database/`

- `docs/database/v2_schema.md`
  - Current database schema documentation.
- `docs/database/LEGACY_V2_MIGRATION_NOTES.md`
  - Legacy v1-to-v2 migration notes, including older destructive migration assumptions.

### `/plans/`

- `docs/plans/RSYNC_LOG_STREAMING_REDESIGN.md`
  - Log streaming redesign. The storage half is implemented; per-transfer log
    files, a runtime table and per-transfer websocket rooms are not.
- `docs/plans/REMOTE_CONNECTION_CHECK.md`
  - Planned check of the link to the remote server, parked until the native
    transfer client exists. Holds the safety rules for writing to and deleting
    from the server.

### `/refactoring/`

- `docs/refactoring/REFACTORING_GUIDE.md`
  - Refactoring history and architectural decomposition from monolith to services/routes/models.

### `/SKILLS/frontend-design/`

- `docs/SKILLS/frontend-design/SKILL.md`
  - Skill-specific notes for frontend design work.

## Recommended Starting Points

1. New to the project: read `docs/refactoring/REFACTORING_GUIDE.md`
2. Investigating sync/webhook/rsync behavior: read `docs/SYNC_APPLICATION_ANALYSIS.md`
3. Investigating runtime/socket/service issues: read `docs/runtime-stability/RUNTIME_STABILITY_IMPLEMENTATION.md`
4. Working on React UI: read `docs/frontend/FRONTEND_REFERENCE.md`
5. Working on queue behavior: read `docs/queue-management/QUEUE_MANAGEMENT_IMPLEMENTATION.md`

## Last Updated

- Documentation index refreshed for runtime stability and current docs structure: March 13, 2026
- Transfer progress/pause/resume, log storage, listing queries and the simulation
  tool documented; simulation section added: July 28, 2026
