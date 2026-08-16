# DragonCP Documentation

The front desk. Two jobs: tell you **where to start reading**, and tell you
**how to add a doc** so the next reader can find it.

[`INDEX.md`](INDEX.md) is the full listing of every document. This file is the
map; `INDEX.md` is the catalogue.

---

## 1. How to explore

### What each folder is for

| Folder | Contains |
|---|---|
| `getting-started/` | Getting the app running for the first time: install, configuration, environment, the launcher and `TEST_MODE`, the frontend dev server, and the test suite. |
| `features/<area>/README.md` | One folder per user-visible capability. What it does, where the code is, how it behaves, its endpoints and its data. This is where most answers live. Screens count as capabilities: `dashboard/` and `settings/` describe pages rather than backend flows. |
| `reference/` | Contracts and lookups: API endpoints, database schema, frontend structure, socket events, path rules, configuration keys, design system. Things you check rather than read. `openapi.yaml` — the machine-readable API spec — lives here too, alongside its prose version `reference/api.md`. |
| `architecture/` | System-wide shape: how the pieces fit, how the codebase got decomposed. Nothing feature-specific. |
| `operations/` | Running it in production: runtime, deployment, systemd, websocket stability, backend logging, and the hand-run maintenance scripts. |
| `plans/` | Designs for work that is **not built yet**, or only half built. Never describes current behaviour without saying so. |
| `archive/` | Superseded material kept for history. Do not trust it as current. |

### If you are working on X, read Y first

| You are working on | Read first | Then |
|---|---|---|
| A specific feature (transfers, backups, renames, webhooks, auth, notifications, explore, queue, auto-sync, simulation) | `features/<area>/README.md` | The `Related` links at the bottom of that doc |
| Anything touching rsync, progress, pause/resume | `features/transfers/README.md` | `features/queue/README.md` |
| Why a transfer was fast or slow, or the transfer server on the media host | `features/fast-transfers/README.md` | `plans/fast-transport.md` |
| Browsing the library, comparing it with the remote, or planning a sync | `features/explore/README.md` | `features/transfers/README.md` |
| Why a transfer is stuck, queued, or not starting | `features/queue/README.md` | `features/transfers/README.md` |
| Radarr/Sonarr webhook payloads and what they trigger | `features/webhooks/README.md` | `features/auto-sync/README.md` |
| Adding or changing an HTTP endpoint | `reference/api.md` | `reference/openapi.yaml`, then the owning feature doc |
| Adding or changing a database column | `reference/database-schema.md` | The owning feature doc's `Data` section |
| Adding or changing a Socket.IO event | `reference/realtime.md` | The owning feature doc's `API` section |
| React UI work | `reference/frontend.md` | `reference/design-system.md` |
| The landing page — what the panels show, poll, and hide | `features/dashboard/README.md` | `features/queue/README.md` |
| SSH credentials, media paths, auto-sync toggles, and where a setting is stored | `features/settings/README.md` | `reference/configuration.md` |
| A configuration key: what reads it, what it defaults to, what wins | `reference/configuration.md` | `getting-started/installation.md` |
| Where files land on disk, destination paths, name normalization | `reference/path-handling.md` | `features/transfers/README.md` |
| Deployment, systemd, gunicorn, socket drops in production | `operations/runtime-and-deployment.md` | `architecture/system-overview.md` |
| Putting the fast transfer route into production | `operations/fast-transfers-deployment.md` | `features/fast-transfers/README.md` |
| Why the old HTML UI was removed, how React is served, or how to roll the cutover back | `operations/legacy-ui-retirement.md` | `operations/frontend-deployment.md` |
| Reading the backend log, or working out why a sync went quiet | `operations/logging.md` | `features/queue/README.md` |
| Something behaves oddly — check whether it is already known | `operations/known-issues.md` | `operations/logging.md` |
| Picking up work, or leaving it for the next session | `../TASKS.md` | `plans/task-manager.md` |
| Migrating, verifying or compacting the database by hand | `operations/maintenance-scripts.md` | `reference/database-schema.md` |
| Adding an administrator, resetting a password, removing someone's access | `operations/admin-accounts.md` | `features/auth/README.md` |
| Who did something — a deleted backup, a sync nobody admits to starting | `features/activity/README.md` | `operations/admin-accounts.md` |
| First time in the codebase | `architecture/system-overview.md` | `architecture/service-decomposition.md` |
| Setting the app up locally | `getting-started/installation.md` | `../AGENTS.md` |
| Starting the backend and the frontend dev server, or using `TEST_MODE` | `getting-started/running.md` | `getting-started/installation.md` |
| Running or adding automated tests | `getting-started/testing.md` | The owning feature doc |
| Testing a transfer end to end without touching real media | `features/simulation/README.md` | `reference/test-mode.md` |
| Whether a test instance can touch real media, and which paths are gated | `reference/test-mode.md` | `getting-started/running.md` |
| Something that does not exist yet | `plans/` | — |

Operator conventions and runtime rules that are not documentation (single
gunicorn worker, TEST_MODE, attribution policy) live in `../AGENTS.md`, not here.

---

## 2. How to document

### Where a new doc goes

| Kind of material | Location |
|---|---|
| A user-visible capability | `features/<area>/README.md` — new folder if the area is new |
| A contract someone looks up: endpoints, schema, frontend structure, path rules | `reference/<topic>.md` |
| Running or deploying the app | `operations/<topic>.md` |
| How the whole system fits together | `architecture/<topic>.md` |
| Work that is not built yet | `plans/<topic>.md` |
| Material replaced by something newer | move it to `archive/`, do not delete |

If a doc could plausibly go in two places, put it in `features/` and link to it
from the others. Feature docs are the default home.

### The feature doc template

Every `features/<area>/README.md` uses these sections, in this order. Skip a
section only when it genuinely does not apply.

```
# <Feature name>

<One paragraph: what this does for the operator, in plain terms. No file names.>

## Where it lives
| Concern | File |    <- one row per responsibility, pointing at the real file

## How it works
### 1. <Step>            <- numbered stages in the order they happen
### 2. <Step>

## Behaviour worth knowing
- Bullets. Surprises, edge cases, known gaps and bugs. Say what the
  operator sees, not what the code does.

## Data
<Which tables/columns/files this feature writes, and what writes them.>

## API
| Method | Path | Purpose |    <- plus any socket events emitted

## Related
- Links to neighbouring docs, relative paths.
```

`features/transfers/README.md` is the reference implementation of this shape.
`features/queue/`, `features/auto-sync/` and `features/simulation/` predate it
and do not match — bring them into line when you next touch them.

Docs outside `features/` are free-form, but still lead with a paragraph saying
what the doc is for.

### Naming

- Filenames are `lowercase-kebab-case.md`. No spaces, no underscores, no dates
  in the name.
- A folder's entry point is always `README.md`. A folder with one doc still uses
  `README.md`.
- Folder names are lowercase-kebab-case, singular or plural by what reads
  naturally (`backups`, `auth`).
- Link between docs with relative paths, so links survive being read outside the
  repo.

### Every doc must be in INDEX.md

A doc that is not listed in [`INDEX.md`](INDEX.md) does not exist — nobody will
find it. Adding a file and updating `INDEX.md` are one change, not two. If you
move or delete a doc, fix `INDEX.md` in the same commit.

### Claims must be checkable

- Every statement must be verifiable against the code as it is now. If you
  cannot point at the file that makes it true, do not write it.
- Do not guess. If you believe something is true but did not confirm it, write
  the claim and mark it **`Not verified:`** — an honest gap is useful, a
  confident wrong answer is not.
- Document what actually happens, including bugs and gaps. "Deleting a queued
  transfer leaks its reservation" belongs in `Behaviour worth knowing`; it does
  not belong in `plans/` just because it is unwelcome.
- Aspirational behaviour goes in `plans/`, clearly labelled as unbuilt. Never
  describe planned behaviour in a feature doc's present tense.
- Prefer describing what the operator sees over narrating code paths. Name files
  in `Where it lives` and where a reader needs to go next — not as a substitute
  for explaining the behaviour.

### When to update

| You changed | Update |
|---|---|
| An HTTP endpoint (added, removed, path, request or response shape) | `reference/api.md`, `reference/openapi.yaml`, and the owning `features/<area>/README.md` `API` section |
| A database column or table | `reference/database-schema.md` and the owning feature doc's `Data` section |
| A feature's behaviour | That feature's `README.md` — `How it works` if the flow changed, `Behaviour worth knowing` if the visible outcome did |
| A socket event | `reference/realtime.md`, the owning feature doc's `API` section, and `reference/frontend.md` |
| Where a responsibility lives (moved or renamed a file) | The `Where it lives` table in every feature doc that names it |
| Config, env vars, install steps | `getting-started/installation.md`, and `operations/runtime-and-deployment.md` if it affects production |
| Something a `plans/` doc described, now built | Move the content into the feature doc; leave the plan only if part of it is still unbuilt |
| Added, moved, renamed or deleted any doc | `INDEX.md` |

Doc updates ship in the same commit as the code change. A doc that describes
last week's behaviour is worse than no doc.
