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
| [`getting-started/running.md`](getting-started/running.md) | What `./start.sh` and `start.py` actually do step by step (venv discovery order, the `==`-only dependency check, the placeholder frontend-build step), the full definition of `TEST_MODE` — what it changes, what it does not, and why it must be `1` and not `true` — and the frontend npm commands, the two Vite proxy targets (`dev` → local backend, `dev:prod` → live production) and the `build` ordering trap. |
| [`getting-started/testing.md`](getting-started/testing.md) | The Python test suite: how to run it (pytest, which is not in `requirements.txt`), why the modules hand the database a relative path, a test-by-test description of all four modules and which regressions each one pins, an explicit list of what is untested (all of `routes/`, SSH, rsync, the queue, backups, notifications, the whole frontend), and the untracked `test/test_queue_behaviors.py` script. |

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
| [`features/backups/README.md`](features/backups/README.md) | Every movie and episode as a slot with a version history: how rsync's staging output is sorted into an identity tree on disk, why that tree is the source of truth and the database only a rebuildable index over it, restore as a capture-before-destroy swap that is reversible because the swap is the only mechanism, keep-N-per-slot retention with pinning and a grace period, and the one-off migration from the old per-transfer folders. |
| [`features/dashboard/README.md`](features/dashboard/README.md) | The landing page, panel by panel — system ticker, storage strip, active transfers, webhook rail — with the poll intervals behind each, the fact that **no panel ever shows an error** (every failure renders as an empty state), why the ticker and rail counts saturate at their own request limits, why local disks are labelled by position rather than by configuration, and the silent GiB→GB conversion that makes remote free space read ~7.4% higher than the storage host reports. |
| [`features/explore/README.md`](features/explore/README.md) | The Explore console that replaced media browsing: one `find` over the remote instead of a call per folder, every episode labelled by comparing both libraries, an approved plan between you and anything destructive, a dry run that asks rsync itself, and a read-only view of what earlier syncs moved aside. |
| [`features/media-browser/README.md`](features/media-browser/README.md) | **Superseded by Explore** for the screen, still accurate for the backend. Browsing the remote library live over SSH — the long-lived paramiko session, host-key policy, listing media types/folders/seasons/episodes, how the "synced" badge is derived from remote mtimes versus the last completed transfer, and starting a transfer from a browsed folder. |
| [`features/notifications/README.md`](features/notifications/README.md) | Discord embeds for finished, failed, renamed and blocked-auto-sync events: the enable/URL gate, how rsync `--stats` output is parsed into the file and speed blocks, poster/requester lookup, and the Manual-versus-Automated Sync labelling rule. |
| [`features/queue/README.md`](features/queue/README.md) | The shared queue: transfer and webhook state vocabularies, `queue_reason` (`path` versus `slot`), the in-memory destination/slot maps, admission and promotion flows with diagrams, restart recovery, and known gaps. |
| [`features/renames/README.md`](features/renames/README.md) | Replaying Sonarr `Rename` events against local files — payload parsing, the deliberately narrow server→local path mapping, the four per-file outcomes (including the idempotent "already renamed" case), and the separate on-demand verification pass. |
| [`features/settings/README.md`](features/settings/README.md) | The Settings screen: the registry-driven Core Config tab and the Automation and Diagnostics tabs, and the thing that catches people out — **not everything on it is editable.** Where the media lives and how to reach the remote come from `dragoncp_env.env` and render read-only; automation, notifications, retention and the realtime timeout come from `app_settings` and take effect immediately. Also covers redacted fields, why a save is all-or-nothing, the two different clamps on wait time, and why Test Discord uses saved rather than on-screen values. |
| [`features/simulation/README.md`](features/simulation/README.md) | Running the real transfer pipeline against generated fixture files: why it is not a mock, the scenario table, the safety guards (`.simulations/` root confinement, `is_simulation` row flagging, size ceiling, busy-queue `409`), and what it deliberately does not cover (the network). |
| [`features/transfers/README.md`](features/transfers/README.md) | The life of a single transfer: request validation and path-bounds checks, queue admission, the constructed rsync command, the monitor loop and progress parsing, pause/resume/cancel/restart/delete, listing versus detail queries, how the history is searched and paged, what bulk delete refuses to take, and startup recovery. |
| [`features/webhooks/README.md`](features/webhooks/README.md) | The Radarr/Sonarr receivers: the auth matrix (secret and/or IP allowlist, fail-closed on unreadable env file), test-payload detection, what each event type does, storage, how a notification's status is kept in step with its transfer, and how the arrivals list is searched, paged and cleared across two tables. |

## reference

| Doc | What it is |
|---|---|
| [`reference/configuration.md`](reference/configuration.md) | Every setting the code reads — connection, paths, auth, webhooks, logging, gunicorn, WebSocket, storage, development — derived from the source rather than from the sample env file, which ships fewer keys. Explains the four separate env-file loaders that disagree with each other, why a value in `.env` reaches login but not `config.get()`, the parser quirks (trailing comments become part of the value), and the two-store split between the env file and the `app_settings` table. |
| [`reference/api.md`](reference/api.md) | The hand-written HTTP reference and the declared authority on the API — every `/api/*` endpoint across twelve sections with request/response bodies, status codes, the auth model, and a closing checklist counting 95 method+path endpoints verified against the route decorators. |
| [`reference/test-mode.md`](reference/test-mode.md) | What `TEST_MODE` guarantees, path by path: the single reader and the values it accepts, an audited table of every place the app can write to, rename or delete a media file and what test mode does to each, why simulations stay safe despite being exempt from the dry run, the four things test mode deliberately does **not** do, and how to confirm the flag from a running instance. |
| [`reference/openapi.yaml`](reference/openapi.yaml) | The machine-readable companion to `api.md`, for importing into an API client or generating a stub client: 95 operations with method, path, auth requirement and a one-line summary, and deliberately thin schemas. Both files are maintained by hand; when they disagree, `api.md` wins and this file is the one to fix. |
| [`reference/realtime.md`](reference/realtime.md) | The Socket.IO catalogue: every server-emitted event with its trigger, emitting call site and payload fields, the three client-to-server events, and the connection lifecycle (handshake auth, the activity ping, the browser countdown, the idle sweeper, the timeout constants and which of them are configurable). Leads with the rule that matters — realtime is opt-in and off by default, so **no event may ever be the only delivery of a fact**; pages poll regardless. Also records that the frontend subscribes to a `transfer_failed` event no server code emits. |
| [`reference/database-schema.md`](reference/database-schema.md) | Current SQLite schema: all seven tables column by column, the columns added post-v2 via `_ensure_column` rather than migrations, index summary, and legacy-rename notes. |
| [`reference/design-system.md`](reference/design-system.md) | The visual conventions the app actually follows, read out of `index.css` and the layout components: the app is dark-only (light mode exists in the stylesheet but is untested), the five brand tokens and the rule against raw hex, surfaces and borders, typography, status colours, the active-state idiom, icon and UI writing conventions. |
| [`reference/frontend.md`](reference/frontend.md) | React app reference for tooling and agents: versioned tech-stack table, the Base UI (not Radix) distinction and `asChild` shim, directory structure, available UI components and sub-exports, the shared list controls behind search/paging/bulk delete, hooks, Zustand stores, routes, and API/WebSocket wiring. |
| [`reference/path-handling.md`](reference/path-handling.md) | Write-up of the `PathService` fix that stopped dry-run and real sync computing different destinations (sanitised folder path versus raw webhook `title`), with before/after examples, the path-construction rules, a testing guide and lessons learned. |

## operations

| Doc | What it is |
|---|---|
| [`operations/known-issues.md`](operations/known-issues.md) | Defects found while writing this documentation, grouped by severity with file:line evidence — including a migration script that erases a v2 database. Most are still open; the ones since fixed are marked and kept, because knowing a behaviour used to exist is what explains an old install that still looks wrong. |
| [`operations/frontend-deployment.md`](operations/frontend-deployment.md) | Running the React frontend in its own container with nginx proxying `/api` and `/socket.io` to the backend on the host; moved out of the repository README. |
| [`operations/troubleshooting.md`](operations/troubleshooting.md) | Authentication and session problems and how to clear them; moved out of the repository README. |
| [`operations/logging.md`](operations/logging.md) | Where the backend log lives and how to read it: the single file everything lands in, rotation and retention, level and redaction settings, the record format, how `print()` output is captured and how its **severity is inferred from the message text** (which is why the ❌/✅ emoji convention has operational consequences and why an ERROR list can be wrong in both directions), the structured per-sync log shape, worked examples of healthy, failing and stuck transfers, and the two `/api/logs` endpoints including the bounded backward scan that can silently miss an older incident. |
| [`operations/maintenance-scripts.md`](operations/maintenance-scripts.md) | The three hand-run scripts in `scripts/`, each with usage, flags, whether it is destructive, whether it is reversible, and what to do before and after. Most importantly: `migrate_v1_to_v2.py` never checks that the database is actually v1, so pointing it at a live v2 installation erases the entire transfer history, and neither it nor `verify_v2_schema.py` uses its exit code as a pass/fail signal. |
| [`operations/runtime-and-deployment.md`](operations/runtime-and-deployment.md) | Record of the runtime-stability work for issues `#38`/`#39`: threaded Socket.IO mode, keepalive tuning, removing the unconditional unsafe-Werkzeug start, the `systemd + venv + gunicorn + gthread + 1 worker` contract, client reconnect fixes, files touched and verification performed. |

## plans

Everything in this folder is a proposal. Read it for intent and constraints, not
as a description of how the system behaves today.

| Doc | What it is |
|---|---|
| [`plans/explore-rebuild.md`](plans/explore-rebuild.md) | **Built.** The design behind Explore, kept for the reasoning rather than the behaviour: why add-only was rejected (it leaves duplicates on an upgrade), why the plan owns removals instead of `rsync --delete`, and why episode identity is the anchor everything hangs off. Three later additions — multi-season plans, the user-facing rsync dry run and the read-only backup view — are not in it; `features/explore/README.md` is the current reference. |
| [`plans/task-manager.md`](plans/task-manager.md) | **Not implemented.** Design for a database-backed task tracker for project work, so context survives between AI agent sessions — schema, the agent-facing CLI, the UI, and the `AGENTS.md` contract that makes agents actually write to it. `TASKS.md` at the repository root is the interim stopgap. |
| [`plans/rsync-log-streaming.md`](plans/rsync-log-streaming.md) | **Partly implemented.** The log-storage half is done (progress-line collapsing, throttled writes, capped logs — 149k stored lines down to 13.7k); still unbuilt are per-transfer log files with restart-safe read offsets, the `transfer_runtime` table, and per-transfer WebSocket rooms, so logs are still broadcast to every client. |
| [`plans/remote-connection-check.md`](plans/remote-connection-check.md) | **Not implemented.** Design for an on-demand "is the link to the server healthy and how fast" check, why it is separate from the simulation tool, and the safety rules for writing to and deleting from the remote server; parked until the planned native transfer client exists. |
| [`plans/backup-restore-rework.md`](plans/backup-restore-rework.md) | **Built.** Rebuilds backups around one idea — every movie and episode is a slot with a version history — replacing the per-transfer organisation that leaves nobody able to answer "what old copies of this episode do I have". Covers the identity tree on disk, why the index becomes a rebuildable view of it rather than the source of truth, restore as a capture-before-destroy swap that is reversible by construction, keep-N-per-slot retention, and the migration. Opens with the disk measurements that drove the decisions. Ends with what implementation changed: legacy folder names turned out to be unsplittable, and a third bucket for title-level extras was needed. Current behaviour is in `features/backups/README.md`. |
| [`plans/mobile-app-strategy.md`](plans/mobile-app-strategy.md) | **Not implemented, decided.** Whether to make the React UI an installable phone app, and how: PWA vs Capacitor vs React Native, with the line counts behind each. PWA chosen 2026-08-01. Records the one real blocker (a service worker needs HTTPS, and the deployment is plain HTTP over Tailscale), why it is a console toggle rather than code, and the service-worker rules this app needs — no runtime caching of `/api`, no navigation fallback over `/socket.io`. Tracked as TASK-013. |

## archive

| Doc | What it is |
|---|---|
| [`archive/v1-to-v2-migration-notes.md`](archive/v1-to-v2-migration-notes.md) | Historical v1→v2 migration context — table/column renames and the older drop-and-recreate cutover flow, explicitly flagged as potentially destructive and not a runtime instruction. |

---

## Coverage gaps

Honest list of what a maintainer would not find documented, based on reading the
above against the code.

1. **Two docs disagree about which UI is in production.** `operations/runtime-and-deployment.md` (dated 2026-03-14) states that "the legacy Flask/static UI is still the active production UI; treat it as the primary runtime path", while everything written since documents the React app in `frontend/` as the product. A maintainer reading the operations folder first will draw the wrong conclusion. Nothing says whether `templates/` and `static/` are still served, still supported, or awaiting removal — `reference/realtime.md` explicitly leaves them untraced, and `reference/api.md` excludes `GET /` as "the legacy UI page" without saying more.
2. **`getting-started/installation.md` is the last stale entry point.** Its project-structure tree still lists a `database.py` that no longer exists and a `templates/` UI, predating the `services/`/`routes/`/`models/` split; its Testing section describes clicking through the UI by hand and does not mention the suite now documented in `getting-started/testing.md`. It is one of the first files a newcomer opens.
3. **Stale dates on the backend-flow docs.** `architecture/system-overview.md`, `features/auto-sync/README.md` and `features/queue/README.md` are dated 2026-03-19; `operations/runtime-and-deployment.md` 2026-03-14. Everything else was rewritten on 2026-07-28. Where the two generations describe the same behaviour, nothing marks which one is current.
4. **Four feature docs carry no date at all**, so a reader cannot tell how old their claims are: `features/renames`, `features/transfers`, `features/webhooks` and `features/simulation`. The header convention is also unsettled — most docs open with `Last updated` and `Primary files`, `features/media-browser` puts its date after the intro paragraph and points at files through the template's `Where it lives` table instead, and `README.md`'s feature template mandates neither. Nothing tells an author which shape to use.
5. **`dragoncp_env_sample.env` is not maintained against the code.** `reference/configuration.md` documents keys the sample never mentions (the logging keys among them), and `getting-started/running.md` records that the sample's own comment for `TEST_MODE` — that it "enables the transfer simulator" — is simply false. The sample is what operators actually copy, and nothing keeps it honest.
6. **`api.md` and `openapi.yaml` agree today by hand, and only by hand.** Both now describe 95 operations, but they are maintained as two independent hand-written files with no generator and no check. The next endpoint change is free to desynchronise them silently.
7. **No page-level doc for Transfers, Webhooks, Backups or Media Browser.** Dashboard and Settings now have screen docs describing what an operator sees, including the failure modes the UI hides. The other four pages are covered only from the backend side in `features/`, plus short structural sections in `reference/frontend.md`. Behaviour that lives purely in the browser — empty versus error states, list caps, client-side filtering — is undocumented for them. Transfers and Webhooks are partly covered now that their list controls are described in `reference/frontend.md`.
8. **The login screen and session expiry have no operator-facing account.** `features/auth/README.md` covers tokens, storage and the interceptors thoroughly, but from the code's side. What a user sees when a session expires mid-transfer, or when a refresh silently fails, is described only as a consequence buried in that doc's `Behaviour worth knowing`.
9. **Queue behaviour is pinned only by an untracked script.** `getting-started/testing.md` documents `test/test_queue_behaviors.py` honestly, including that it is not in git and not collected by the suite. The most concurrency-sensitive part of the application therefore has no tracked regression coverage — a code gap, but one the documentation now makes visible and nobody has acted on.
10. **No doc describes the Docker path beyond the frontend.** `operations/frontend-deployment.md` covers the frontend container and `deploy-frontend.sh`. `docker-compose.yml` defines only that service; whether the backend is ever intended to be containerised, and how the compose file relates to the systemd contract, is unstated.
11. **`reference/path-handling.md` is a fix write-up doing a reference's job.** It is filed under `reference/` and is where the routing table sends you for destination-path rules, but it is structured as the history of one bug — before/after, testing guide, lessons learned — rather than as the current rules of `services/path_service.py`.
