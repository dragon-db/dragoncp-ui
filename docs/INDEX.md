# Documentation Catalogue

Every documentation file under `docs/`, with what it actually contains and when
to reach for it.

**Entry points:** [`docs/README.md`](README.md) is the curated index — a topic
map and recommended reading order for common tasks. This file
(`docs/INDEX.md`) is the exhaustive catalogue: every file, one line each, no
omissions. Start with `README.md` if you know your topic; use this page if you
are looking for something and do not know where it lives.

---

## getting-started

| Doc | What it is |
|---|---|
| [`getting-started/usage.md`](getting-started/usage.md) | Walkthrough of the main operator flows — connecting, browsing the library, starting a transfer and watching it — moved out of the repository README. |
| [`getting-started/installation.md`](getting-started/installation.md) | Manual virtualenv setup, the supported Gunicorn + systemd production path, port and env-file configuration, troubleshooting, and a development section whose project-structure tree and testing advice both predate the current `services/`/`routes/`/`models/` layout and the React frontend. |

## architecture

| Doc | What it is |
|---|---|
| [`architecture/system-overview.md`](architecture/system-overview.md) | End-to-end walkthrough of the backend sync engine — manual, movie-webhook, series/anime-webhook and rename-only flows, queueing, rsync execution and QoS notes — with file:line anchors into the source (last updated 2026-03-19). |
| [`architecture/service-decomposition.md`](architecture/service-decomposition.md) | Completed-refactor record (October 2025) explaining how two monolithic files became the Models / Services / Routes layering, with a per-file purpose-and-line-count table; history, not current behaviour. |

## features

| Doc | What it is |
|---|---|
| [`features/auth/README.md`](features/auth/README.md) | How the single-operator login works: credentials from the env file, the access/refresh token pair and their `type` claim, `require_auth` gating, WebSocket authentication, and the separate HMAC + IP-allowlist protection on the three webhook receivers. |
| [`features/auto-sync/README.md`](features/auto-sync/README.md) | The series/anime "V3" auto-sync path — batching webhooks by series+season, the dry-run safety gate, queueing and promotion, restart recovery — and an explicit list of where the implementation still diverges from the V3 target (e.g. no real `MANUAL_SYNC_REQUIRED` status, in-memory scheduler jobs). |
| [`features/backups/README.md`](features/backups/README.md) | Why every sync gets its own `--backup-dir`, how overwritten and deleted files are indexed with title/season/episode detected from filenames, and how a full or partial restore is previewed, executed, deleted or reindexed. |
| [`features/media-browser/README.md`](features/media-browser/README.md) | Browsing the remote library live over SSH — the long-lived paramiko session, host-key policy, listing media types/folders/seasons/episodes, how the "synced" badge is derived from remote mtimes versus the last completed transfer, and starting a transfer from a browsed folder. |
| [`features/notifications/README.md`](features/notifications/README.md) | Discord embeds for finished, failed, renamed and blocked-auto-sync events: the enable/URL gate, how rsync `--stats` output is parsed into the file and speed blocks, poster/requester lookup, and the Manual-versus-Automated Sync labelling rule. |
| [`features/queue/README.md`](features/queue/README.md) | The shared queue: transfer and webhook state vocabularies, `queue_reason` (`path` versus `slot`), the in-memory destination/slot maps, admission and promotion flows with diagrams, restart recovery, and known gaps. |
| [`features/renames/README.md`](features/renames/README.md) | Replaying Sonarr `Rename` events against local files — payload parsing, the deliberately narrow server→local path mapping, the four per-file outcomes (including the idempotent "already renamed" case), and the separate on-demand verification pass. |
| [`features/simulation/README.md`](features/simulation/README.md) | Running the real transfer pipeline against generated fixture files: why it is not a mock, the scenario table, the safety guards (`.simulations/` root confinement, `is_simulation` row flagging, size ceiling, busy-queue `409`), and what it deliberately does not cover (the network). |
| [`features/transfers/README.md`](features/transfers/README.md) | The life of a single transfer: request validation and path-bounds checks, queue admission, the constructed rsync command, the monitor loop and progress parsing, pause/resume/cancel/restart/delete, listing versus detail queries, and startup recovery. |
| [`features/webhooks/README.md`](features/webhooks/README.md) | The Radarr/Sonarr receivers: the auth matrix (secret and/or IP allowlist, fail-closed on unreadable env file), test-payload detection, what each event type does, storage, and how a notification's status is kept in step with its transfer. |

## reference

| Doc | What it is |
|---|---|
| [`reference/configuration.md`](reference/configuration.md) | The settings that control the app and the three places they live (env file, session overrides, `app_settings`). Explicitly marked incomplete: covers the sample env file's keys, not the logging, gunicorn, WebSocket-timeout or storage keys the code also reads. |
| [`reference/api.md`](reference/api.md) | The 1,600-line hand-written HTTP reference — every `/api/*` endpoint grouped into ten sections with request/response bodies, status codes and the auth model; the closing checklist claims 84 endpoints, but the two server-log endpoints it counts have no section in the body. |
| [`reference/database-schema.md`](reference/database-schema.md) | Current SQLite schema: all seven tables column by column, the columns added post-v2 via `_ensure_column` rather than migrations, index summary, and legacy-rename notes. |
| [`reference/design-system.md`](reference/design-system.md) | Not a DragonCP design system — this is a verbatim copy of the generic `frontend-design` agent skill (aesthetic direction, typography, motion advice) with its YAML frontmatter intact, containing nothing project-specific. |
| [`reference/frontend.md`](reference/frontend.md) | React app reference for tooling and agents: versioned tech-stack table, the Base UI (not Radix) distinction and `asChild` shim, directory structure, available UI components and sub-exports, hooks, Zustand stores, routes, and API/WebSocket wiring. |
| [`reference/path-handling.md`](reference/path-handling.md) | Write-up of the `PathService` fix that stopped dry-run and real sync computing different destinations (sanitised folder path versus raw webhook `title`), with before/after examples, the path-construction rules, a testing guide and lessons learned. |

## operations

| Doc | What it is |
|---|---|
| [`operations/frontend-deployment.md`](operations/frontend-deployment.md) | Running the React frontend in its own container with nginx proxying `/api` and `/socket.io` to the backend on the host; moved out of the repository README. |
| [`operations/troubleshooting.md`](operations/troubleshooting.md) | Authentication and session problems and how to clear them; moved out of the repository README. |
| [`operations/runtime-and-deployment.md`](operations/runtime-and-deployment.md) | Record of the runtime-stability work for issues `#38`/`#39`: threaded Socket.IO mode, keepalive tuning, removing the unconditional unsafe-Werkzeug start, the `systemd + venv + gunicorn + gthread + 1 worker` contract, client reconnect fixes, files touched and verification performed. |

## plans

Everything in this folder is a proposal. Read it for intent and constraints, not
as a description of how the system behaves today.

| Doc | What it is |
|---|---|
| [`plans/rsync-log-streaming.md`](plans/rsync-log-streaming.md) | **Partly implemented.** The log-storage half is done (progress-line collapsing, throttled writes, capped logs — 149k stored lines down to 13.7k); still unbuilt are per-transfer log files with restart-safe read offsets, the `transfer_runtime` table, and per-transfer WebSocket rooms, so logs are still broadcast to every client. |
| [`plans/remote-connection-check.md`](plans/remote-connection-check.md) | **Not implemented.** Design for an on-demand "is the link to the server healthy and how fast" check, why it is separate from the simulation tool, and the safety rules for writing to and deleting from the remote server; parked until the planned native transfer client exists. |

## archive

| Doc | What it is |
|---|---|
| [`archive/v1-to-v2-migration-notes.md`](archive/v1-to-v2-migration-notes.md) | Historical v1→v2 migration context — table/column renames and the older drop-and-recreate cutover flow, explicitly flagged as potentially destructive and not a runtime instruction. |

---

## Coverage gaps

Honest list of what a maintainer would not find documented, based on reading the
above against the code.

1. **Server log viewer.** `routes/logs.py` (`GET /api/logs`, `GET /api/logs/download`), `services/sync_logger.py` and `logging_setup.py` have no feature doc and no section in `reference/api.md` — the API checklist counts two log endpoints that are never described.
2. **Configuration reference.** There is no single list of environment keys. `dragoncp_env_sample.env` is the de-facto source; individual variables are mentioned in passing across `installation.md` and several feature docs.
3. **Frontend build and deployment.** No doc anywhere mentions `npm`, Vite, or `deploy-frontend.sh`. `installation.md` still describes the legacy `templates/` + `static/app.js` UI and a `database.py` that no longer exists.
4. **Dashboard and Settings pages.** `frontend/src/components/pages/dashboard.tsx` appears only as a row in `reference/frontend.md`; the Settings page is described only insofar as it configures Discord notifications. SSH credentials, path configuration and the auto-sync toggles have no page-level doc.
5. **WebSocket event catalogue.** Socket.IO events (`test_webhook_received`, `rename_webhook_received`, transfer progress and log events) are named across five documents, but nothing lists the event names, payloads and who emits them.
6. **Testing.** The `tests/` suite (`test_rename_service`, `test_simulation_service`, `test_transfer_listing`, `test_transfer_logging`) is referenced from feature docs but never explained; `installation.md`'s Testing section describes manual clicking only and does not mention pytest.
7. **`reference/openapi.yaml`.** A 2,114-line spec covering 72 paths sits unlinked from any index, while `reference/api.md` documents 83 endpoints. Which is authoritative, and whether the spec is current, is undocumented.
8. **Operator scripts.** `scripts/compact_transfer_logs.py`, `scripts/migrate_v1_to_v2.py` and `scripts/verify_v2_schema.py` are named in passing with no usage, prerequisites or safety notes.
9. **Startup path.** `start.py` / `start.sh` and the `TEST_MODE` flag are used in examples but their behaviour (venv detection, what differs under test mode) is never described.
11. **Staleness signals.** `architecture/system-overview.md`, `features/auto-sync/README.md` and `features/queue/README.md` were last dated 2026-03-19 and `operations/runtime-and-deployment.md` 2026-03-14, while the feature docs rewritten on 2026-07-28 describe behaviour the older set may contradict. `features/renames`, `features/transfers` and `features/webhooks` carry no date at all.
12. **`reference/design-system.md` is misfiled.** It is a copied agent skill, not documentation of this project's design system; the actual Tailwind/Base UI conventions live in `reference/frontend.md`.
