# Tasks

Interim task tracker for work on this project. Kept at the repository root so
both operators and AI agents find it without looking.

This is a stopgap. The database-backed version is designed in
[`docs/plans/task-manager.md`](docs/plans/task-manager.md) and will replace it.
Until then, this file is the single source of truth for what is in flight.

## How to use this file

**Before starting work**, read the In progress section. If your work matches an
existing task, use it. Otherwise add one.

**While working**, keep the task's notes current — decisions as you make them,
not reconstructed at the end.

**Before finishing**, leave a `Handoff:` line saying where you stopped and what
comes next. That line is what the next session reads first, and it is the whole
point of this file.

Point at documentation rather than restating it: link the relevant page under
[`docs/`](docs/README.md).

Task format:

```
### TASK-nnn — Title
Status: in progress | blocked | planned | done      Priority: low|medium|high|urgent
Tags: area, area                                     Branch: branch-name
Docs: docs/features/x/README.md

Plan: what this is and what done looks like.

Steps:
- [x] finished step
- [ ] remaining step

Notes:
- 2026-07-28 (claude): what happened
- Handoff: where this stopped and what is next
```

---

## In progress

_None._

## Planned

### TASK-001 — In-app task manager
Status: planned      Priority: medium
Tags: backend, frontend, tooling
Docs: [docs/plans/task-manager.md](docs/plans/task-manager.md)

Plan: replace this file with a database-backed tracker — `task`, `task_step`
and `task_note` tables, a `scripts/task.py` CLI for agents, HTTP endpoints for
the UI, and a Tasks page. Full design, including the open questions, is in the
plan document.

Steps:
- [ ] schema and model
- [ ] `scripts/task.py` CLI (the agent-facing path — matters most)
- [ ] HTTP endpoints
- [ ] Tasks page in the UI
- [ ] `AGENTS.md` contract so agents actually write to it
- [ ] migrate the contents of this file, then retire it

Notes:
- 2026-07-28: an initial implementation was started (schema, model, routes) and
  backed out to keep the current branch scoped to the transfers page. Nothing
  was committed; the design survives in the plan document.
- Handoff: start from the plan document. Build the CLI before the UI — a tracker
  agents cannot easily write to will go stale, and that is the failure mode the
  whole thing exists to avoid.

### TASK-002 — Remote connection check
Status: planned      Priority: low
Tags: backend, diagnostics
Docs: [docs/plans/remote-connection-check.md](docs/plans/remote-connection-check.md)

Plan: a diagnostic that measures the link to the media server — SSH auth,
host-key policy, real throughput — as opposed to the simulation tool, which
exercises the software locally and never touches the network.

Notes:
- Parked until the native transfer client exists; a check written against
  rsync-over-SSH would largely be rewritten. The safety rules for writing to and
  deleting from the remote server are recorded in the plan.

### TASK-003 — Per-transfer socket rooms
Status: planned      Priority: medium
Tags: backend, performance, realtime
Docs: [docs/plans/rsync-log-streaming.md](docs/plans/rsync-log-streaming.md), [docs/reference/realtime.md](docs/reference/realtime.md)

Plan: `transfer_progress` carries a 100-line log tail and is broadcast to every
connected client, roughly 3 MB/min each with three transfers running. Scope the
emits to per-transfer subscription rooms, as designed in section 6 of the log
streaming plan.

Notes:
- The storage half of that plan is done (progress lines no longer accumulate in
  the database). This is the streaming half and is untouched.

---

## Backlog

### TASK-004 — Triage the known issues
Status: backlog      Priority: high
Tags: backend, correctness
Docs: [docs/operations/known-issues.md](docs/operations/known-issues.md)

Plan: 79 defects were found while writing the documentation. Three are verified
data-safety issues and should be handled first:

Steps:
- [ ] `BACKUP_PATH` unset writes backups to `/tmp/backup` while restore refuses
      them — backups appear to work and cannot be restored
- [ ] `migrate_v1_to_v2.py` has no v1 check and drops `transfers` and
      `app_settings` regardless, erasing history on a live v2 install
- [ ] `TEST_MODE=true` shows the development banner while rsync still runs for
      real, because the banner accepts `1/true/yes/on` and every safety check
      compares against exactly `'1'`
- [ ] work through the remaining findings by section

### TASK-005 — Close the remaining documentation gaps
Status: backlog      Priority: low
Tags: docs
Docs: [docs/INDEX.md](docs/INDEX.md)

Plan: the catalogue's Coverage gaps section lists what is still undocumented.
Work from there.

---

## Done

### TASK-006 — Transfers page rework
Status: done      Priority: high
Tags: frontend, backend, transfers
Branch: feature/transfer-progress-stats-controls
Docs: [docs/features/transfers/README.md](docs/features/transfers/README.md)

Plan: speed/size/ETA statistics, pause and resume, a rebuilt Transfers page, and
a simulation tool that runs the real pipeline against throwaway files.

Steps:
- [x] parse rsync progress into structured columns
- [x] pause/resume via partial-file resume
- [x] rebuild the page on the webhooks layout
- [x] stop storing every rsync progress line
- [x] replace the fake simulator with real simulated transfers
- [x] documentation library and gap closure

Notes:
- Production runs the stats and pause/resume commit (`9c2e51d`); the later
  commits are on the branch and not deployed.
