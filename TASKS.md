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

### TASK-010 — Explore rebuild
Status: in progress      Priority: high
Tags: backend, frontend, explore                     Branch: explore-page
Docs: [docs/features/explore/README.md](docs/features/explore/README.md), [docs/plans/explore-rebuild.md](docs/plans/explore-rebuild.md)

Plan: replace Browse Media with a comparison-driven Explore page — inventory both
libraries, label every episode, and turn the difference into a reviewable plan.
Done looks like: sync/download/replace all working through the plan gate, with the
old sync-status guessing removed.

Steps:
- [x] Phase 1 — identity parser, inventory, comparison, snapshot cache
- [x] Phase 2 — planning, safety verdict, plan tokens, executor, rsync file lists
- [x] Phase 3 — per-file history records and endpoint
- [x] Phase 4 — rate limiting, real status codes, session check
- [x] Phase 5 — UI: tree, contents table, inspector, review dialog
- [x] Verify against the real remote — full TV comparison in 0.69s; walked a
      season through plan → review → transfer under TEST_MODE
- [x] UI matched 1:1 to the demo (measured, not eyeballed): added the missing
      `--well`/`--elevated`/`--foreground-2`/`--foreground-3` tokens, corrected
      ~20 metric deltas, and fixed the app shell (navbar 58px, rail 226px, inset
      gutters, `min-w-0` on SidebarInset, no max-width cap on full-bleed pages)
- [x] Mobile: one pane at a time, inspector in a sheet, progressive columns
- [x] Movies skip the season layer entirely (leaf rows → files)
- [x] Mobile round two, from use on a real phone: dead gutter before the file
      name removed, tick box actually toggles, tapping an unselectable file
      opens the actions, a floating bar carries the selection below `xl`,
      breadcrumb and remote path scroll instead of truncating, and switching
      library clears the selection
- [x] Mobile round three: film icon in the movie rows' empty chevron slot, tick
      boxes on every row and on season rows regardless of sync state, the header
      strip splits in two below `sm`
- [x] Dry run — rsync asked with `--dry-run` using the plan's own command, its
      itemised output parsed and reconciled against the plan, for a series, a set
      of seasons, one season, or ticked files
- [x] `sync_seasons` — ticking several seasons builds ONE plan and one transfer
- [x] Backup view in the actions panel, scoped to the series or season being
      looked at, read-only, with a link through to the Backups page
- [x] A removals-only run now writes a completed transfer row and indexes its
      backup — it previously appeared in no history and no backup list
- [ ] Restore from Explore itself, once the Backups feature is reworked: the
      destination match and the confirmation live there, so this stays a link
      until that work lands
- [ ] Retire the old `/api/folders|seasons|episodes|sync-status` endpoints and
      `get_sync_status` / `get_folder_sync_status_summary` once this is proven
- [ ] Repair action for the 22 misplaced files the old download bug left behind

Notes:
- 2026-07-30 (claude): 63 tests cover identity (against real library filenames),
  comparison, planning/safety, an end-to-end run with ssh faked, and the HTTP
  layer. 119 tests pass overall; nothing pre-existing changed behaviour.
- The old single-episode download was creating a DIRECTORY named after the
  episode and putting the file inside it. 22 files in the live library are
  stranded that way and are invisible to the media server. Explore detects and
  reports them; it does not move them.
- 2026-07-30 (claude): `SidebarInset` had no `min-w-0`, so any wide child pushed
  the whole shell past the sidebar and clipped it — latent before Explore, which
  is simply the first page wide enough to trigger it.
- 2026-07-31 (claude): the tick box never toggled. Base UI's `Checkbox` renders
  a hidden `input` as a SIBLING of the box and forwards the click to it; that
  click bubbled to the row, which toggled the same file straight back. Stopping
  propagation on the box alone could never work — the guard has to wrap both.
- 2026-07-31 (claude): the desktop table is deliberately untouched. The tick
  gutter only narrows below `sm`, so the demo geometry (36 / flex / 72 / 96 /
  104, pane rules at 404 and 1247) still measures identical.
- 2026-07-31 (claude): the dry run is built from the SAME command function as
  the real run (`build_explore_rsync_command`) with `--dry-run` in front. It has
  to be, or the rehearsal is theatre. Writing it immediately found a real trap:
  rsync is asked before the plan moves superseded files to backup, so it reports
  "nothing to do" for exactly the files that are about to be overwritten. The
  report reconciles the two and folds those back in; every other disagreement
  becomes a warning.
- 2026-07-31 (claude): backups are matched to a series by the backup's
  `folder_name`, NEVER by `context_series_title`. That column is parsed by
  splitting the filename at the first " - ", so prod stores "Re - ZERO, Starting
  Life in Another World (2016)" as "Re" — matching on it hides a series' backups
  from itself. Season narrowing uses each FILE's `context_season` (stored padded
  and as text), because one series sync makes one backup spanning many seasons.
  Verified against the 160 real backups in the prod database, read-only.
- 2026-07-31 (claude): the plan dialog never clipped its own list — `ScrollArea`
  resolves `height: 100%` against a parent sized only by `max-height`, so the
  viewport grew to its content and long plans ran behind the footer. Swapped for
  a plain overflow container. The three page panes were unaffected; their parents
  have definite heights.
- Handoff: verified end to end against the real remote under TEST_MODE, and the
  mobile pass was checked on a 390px viewport rather than by reading CSS. Next:
  retire the old browse endpoints once this is trusted in prod, then the repair
  action for the 22 misplaced files. Consider `@tanstack/react-virtual` before
  anyone opens a 500-episode series.

### TASK-011 — "Sync all" creates one transfer per episode
Status: done (unreleased)      Priority: high
Tags: backend, frontend, webhooks                    Branch: explore-page
Docs: [docs/features/webhooks/README.md](docs/features/webhooks/README.md)

Plan: "Sync all" on a webhook group posted one sync per notification, so a
six-episode season grab created six transfers against one destination. Done
looks like: one transfer per season, every notification in the group linked to
it.

Steps:
- [x] `WebhookService.sync_notification_group` — re-derives the grouping from
      `(media_type, series_title_slug, season_number)` and calls
      `trigger_series_webhook_sync(primary, all_ids)` once per season
- [x] `POST /api/webhook/series/notifications/sync-batch`
- [x] `syncAllInGroup` makes one request instead of `Promise.all` over N
- [x] 8 tests in `tests/test_webhook_group_sync.py`
- [ ] Collapse duplicate folder transfers in `QueueManager`: when a pending or
      running folder transfer already targets the same `dest_path`, attach the
      new notification ids to it and return it rather than queueing another row
- [ ] Same treatment for the Radarr/movie path, which has the identical shape

Notes:
- 2026-07-30 (claude): found in prod on "The Falcon and The Winter Soldier"
  S01 — 7 transfers, ONE distinct dest path. The first moved 7.14 GB; the other
  six were serialised on the path conflict and moved 0 bytes each (rsync
  reported `speedup is 13,133,675`). No data damage, just six junk rows. Live
  instance needed no repair — everything had already completed by the time it
  was investigated.
- The batching capability already existed (`batched_notification_ids`, used by
  `auto_sync_scheduler`); only the manual path never reached it.
- The grouping is deliberately re-derived server-side: the resulting rsync runs
  with `--delete`, so the client must not get to name the folder.
- Handoff: the queue-collapse step is the durable fix — it also closes the
  auto-sync-vs-manual race that produced the 7th row. Own branch, own tests.

### TASK-012 — The UI reloads itself when you switch back to the browser
Status: done (unreleased)      Priority: medium
Tags: frontend, tooling                              Branch: explore-page
Docs: [docs/getting-started/running.md](docs/getting-started/running.md#do-not-open-the-dev-server-on-a-phone)

Plan: reported as "on mobile the whole page reloads every time I switch apps
back to Chrome or Firefox, once in three times, worse on Firefox". Done looks
like: a way to open the UI on a phone that stays where you left it.

Steps:
- [x] Establish it is not the app — `refetchOnWindowFocus` is off, the socket
      reconnects in place, and the only `location.reload()` anywhere is Vite's
- [x] `preview` block in `vite.config.ts` (it does not inherit `server.proxy`)
- [x] `npm run serve:prod` — build, then serve `dist/` on 5181
- [x] Documented in `running.md` and the frontend README

Notes:
- 2026-07-31 (claude): cause is the Vite dev client. Port 5181 was running
  `npm run dev:prod`, so the page carried `/@vite/client`. That client holds a
  websocket to the dev server; a phone drops it when the tab backgrounds, and
  the client's handler for a dropped socket polls until the server answers and
  then calls `location.reload()`. It waits for `document.visibilityState` to be
  `visible` first, which is why the reload lands exactly as you switch back.
  Firefox on Android suspends background sockets sooner than Chrome — hence
  "worse on Firefox".
  Verified: `curl :5181` returns `/@vite/client`; `curl :5002` (the nginx
  container) and `vite preview` do not.
- The container on 5002 was already a reload-free prod UI; it just needs
  `./deploy-frontend.sh` to pick up new code. `serve:prod` is the lighter option.
- Handoff: nothing outstanding. If the dev server is ever wanted on a phone,
  the only lever is `server.hmr: false`, which costs hot reload for everyone.

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


---

### TASK-008 — Compact the stored transfer logs on production
Status: planned      Priority: medium
Tags: operations, database
Docs: [docs/plans/rsync-log-streaming.md](docs/plans/rsync-log-streaming.md)

Plan: new transfers collapse rsync progress lines as they are written, but rows
created before that still hold every tick. Run the compaction over what is
already stored, once this branch is deployed.

Measured against a snapshot of production: 150,870 lines across 521 transfers,
5.5 MB of log occupying 38% of a 15.4 MB database, going to 13,842 lines and
574 KB — the file drops from 14.7 MB to 8.8 MB after `VACUUM`.

Steps:
- [ ] deploy this branch to production
- [ ] `python scripts/compact_transfer_logs.py` — report first, confirm the figures
- [ ] `python scripts/compact_transfer_logs.py --apply --backup`
- [ ] check the reported skip list is empty, or re-run for those rows

Notes:
- Safe to run while transfers are in flight: each row is rewritten only if its
  log is still exactly what was read, and any row that moved is named so it can
  be re-run.
- Handoff: this is the only follow-up left from the rsync log storage work.

### TASK-009 — Rebind transfer socket listeners without churn
Status: planned      Priority: medium
Tags: frontend, realtime
Docs: [docs/reference/frontend.md](docs/reference/frontend.md)

Plan: the Transfers page binds its five socket listeners in an effect that
depends on the `useQuery` result objects. Those are new on every render, so the
effect re-runs continuously and each progress tick tears down and rebinds every
listener, with a window in between where events land on nothing. Raised in
review on PR #54.

The obvious fix - depend on `queryClient` only and invalidate by key - was
implemented and reverted: with realtime enabled the Activity list stopped
showing running transfers entirely, reproducibly, while the same page on the
previous code kept working. The data reached the browser (a hand-issued fetch
returned the running row) but the rendered list stayed empty, so something about
binding once rather than continuously changes what the query cache ends up
holding. Root cause not found.

Steps:
- [ ] reproduce with a minimal case and find why the cache empties
- [ ] rebind on socket identity rather than on render
- [ ] verify with realtime on *and* off, on a freshly loaded page

Notes:
- Verify on a fresh page load. A page left open across a Vite HMR cycle shows
  the same symptom for unrelated reasons and will send you chasing ghosts.
- Handoff: the reverted attempt is in the PR #54 review discussion.

## Backlog

### TASK-004 — Triage the known issues
Status: in progress      Priority: high
Tags: backend, correctness
Docs: [docs/operations/known-issues.md](docs/operations/known-issues.md)

Plan: 79 defects were found while writing the documentation. Three are verified
data-safety issues and should be handled first:

Steps:
- [ ] `BACKUP_PATH` unset writes backups to `/tmp/backup` while restore refuses
      them — backups appear to work and cannot be restored
- [ ] `migrate_v1_to_v2.py` has no v1 check and drops `transfers` and
      `app_settings` regardless, erasing history on a live v2 install
- [x] `TEST_MODE=true` shows the development banner while rsync still runs for
      real — every reader now goes through `env_flags.test_mode_enabled()`
- [x] `transfer_failed` listener with no emitter — helper deleted
- [x] `TransferUpdate` overstated its payload — only `transfer_id` is required
- [x] `compact_transfer_logs.py` lost-update window — compare-and-set on the log
- [x] `--backup` silently ignored without `--apply` — it now says so
- [ ] work through the remaining findings by section

### TASK-005 — Close the remaining documentation gaps
Status: backlog      Priority: low
Tags: docs
Docs: [docs/INDEX.md](docs/INDEX.md)

Plan: the catalogue's Coverage gaps section lists what is still undocumented.
Work from there.

---

## Done

### TASK-007 — Pagination, search and bulk clear
Status: done      Priority: high
Tags: backend, frontend, transfers, webhooks
Branch: feature/transfer-progress-stats-controls
Docs: [docs/reference/api.md](docs/reference/api.md),
[docs/reference/frontend.md](docs/reference/frontend.md)

Plan: both long lists were capped slices narrowed in the browser. With 519
transfers and 806 webhook notifications in production, 61% of the transfer
history could not be reached, and the "Failed" filter showed nothing while 15
failed transfers existed further back.

Steps:
- [x] `search`, `offset`, real `count()` and `status_counts()` on the transfer model
- [x] `NotificationCatalog` — one ordered, paged, counted view across both webhook tables
- [x] `POST /transfers/bulk-delete` and `POST /webhook/notifications/bulk-delete`,
      each taking explicit ids or a filter to re-run
- [x] shared `list-controls.tsx`: search, filter chips with counts, pager, selection bar
- [x] History tab and Media sync tab rebuilt on them
- [x] 17 tests in `tests/test_listing_pagination.py`
- [x] api.md, openapi.yaml, both feature docs and frontend.md

Notes:
- Bulk delete refuses a `running` transfer and names it in `skipped`; the row has
  a live rsync process behind it.
- Deleting completed transfers clears the sync history behind the SYNCED badges
  in Browse Media. The confirmation says so.
- Webhook rows are grouped by season *after* paging, so a season straddling a
  page boundary shows on both pages. Documented rather than fixed - the fix
  would mean grouping in SQL across two differently-shaped tables.
- Handoff: done and verified against a seeded dev database (123 transfers, 156
  notifications), then the seed rows were removed.

### TASK-003 — Per-transfer socket rooms
Status: done      Priority: medium
Tags: backend, frontend, performance, realtime
Branch: feature/transfer-progress-stats-controls
Docs: [docs/reference/realtime.md](docs/reference/realtime.md)

Plan: rsync output was riding on every `transfer_progress` broadcast — 93% of
the payload — and reaching every connected client whether or not anyone had that
transfer open.

Steps:
- [x] subscription registry and room handlers in `websocket.py`
- [x] split the log body onto a room-scoped `transfer_logs` event
- [x] skip building the payload when nobody is subscribed
- [x] subscribe/unsubscribe as rows expand, with replay on reconnect
- [x] documented in `docs/reference/realtime.md`

Notes:
- Verified with a real socket client: a non-subscribed client receives progress
  events with no log body and zero log events; subscribing starts the stream and
  unsubscribing stops it.
- The proposed three-event design (snapshot/chunk/end) was reduced to one event.
  The snapshot already arrives over HTTP when a row opens, and the end state is
  already carried by `transfer_complete`, so the extra events would have
  duplicated both.

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
