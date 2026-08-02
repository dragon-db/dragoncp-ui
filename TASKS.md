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

### TASK-014 — Backup and restore rework
Status: done (unreleased)      Priority: high
Tags: backend, frontend, backups                     Branch: backup-and-rename
Docs: [docs/features/backups/README.md](docs/features/backups/README.md), [docs/plans/backup-restore-rework.md](docs/plans/backup-restore-rework.md)

Plan: backups are organised by the transfer that produced them, which is why
nothing can answer "what old copies of this episode do I have". Reorganise them
by what the file *is*: every movie and episode is a slot with a version history,
the library holds the current version, the backup area holds the rest.

Done looks like: a restore that names the exact episode and the exact file it
will replace before it runs, is reversible because the swap is the only
mechanism, and cannot fill the disk.

Steps:
- [x] Phase 1 — `BACKUP_PATH` fails closed. One place resolves the base and it
      raises; transfers refuse to start, resume or restart without it. The
      `/tmp/backup` fallback is gone, and `services/backup_service.py` with it
- [x] Phase 2 — identity: Explore's episode parser reused as-is, movie identity
      added, slot keys, capture ids with millisecond ordering
- [x] Phase 3 — sorting: rsync stages into `.staging/<transfer>`, then every
      file is renamed into `<library>/<title>/<season>/<SxxEyy>/<capture>/`.
      Extras and unsorted buckets for what carries no episode identity
- [x] Phase 4 — three index tables, rebuild-from-disk carrying pins forward
- [x] Phase 5 — migration with a preview, library-prefix title matching, and a
      guard that refuses while transfers are running
- [x] Phase 6 — restore: capture-before-destroy, queued, exact preview
- [x] Phase 7 — retention: keep N per slot, grace period, pinning, reporting
- [x] Phase 8 — UI shaped like Explore: titles, slots, version inspector,
      restore preview, retention/migration/rebuild housekeeping
- [x] Phase 9 — Explore's backup panel reads the same index, by slot
- [x] Phase 10 — admin cleanup: bulk delete by version or by whole item, with
      `keep_newest` as a safety net, a preview of the space it frees, pinned
      versions held back and reported, a Largest-first sort to find what is
      worth deleting, and one action to clear the unidentified bucket
- [x] Retention settings are saved to `app_settings`, so the rule can be
      changed from the UI and takes effect without a restart
- [ ] Verify on the live instance: preview the migration, apply it, then walk
      one restore end to end. Nothing has been run against the real disk yet
      beyond the read-only preview
- [ ] Retire the legacy `backup` / `backup_file` tables once the migration has
      run and been trusted for a while — migration still reads them

Notes:
- 2026-08-01 (operator): three decisions taken — reorganise on disk rather than
  grouping only in the index, migrate the existing data after a dry run, and
  prune by keeping N versions per slot.
- 2026-08-01 (claude): measured the live backup area before designing anything.
  864 folders on disk, **687 of them empty**; 330 files totalling 367 GB; this
  checkout's index knows about **19**. The disk is 68% full with no pruning of
  any kind. That ratio is the argument for making the tree authoritative and the
  index rebuildable — the current shape has already lost track of the disk.
- The backup area and the library are on **different devices**, so displacing a
  file is a real copy but reorganising within the backup area is a rename. That
  asymmetry is what makes the sorting step cheap and why restore has to be
  queued rather than run inside the request.
- Reversibility falls out rather than being built: if the only primitive is
  "displace the occupant, put something else in the slot", then undoing a
  restore is restoring the capture the restore itself created.
- Do not write a second episode parser. Explore's already handles the four
  things that break naive ones here, and the current backup parser splits titles
  at the first " - ", which mis-parses any title containing one.
- Sonarr/Radarr API integration is deliberately out of scope; renames wait for
  it. Backups do not depend on it, which is why they go first.
- 2026-08-01 (claude): the migration preview was run read-only against the live
  backup disk twice while tuning it. First pass identified 77 of 301 files;
  after two fixes it identifies **271**, leaving 30 (26 pieces of artwork, 2
  `.nfo`, 2 hand-made pre-restore movie files). The two fixes were: legacy
  folder names cannot be split reliably (real ids look like
  `series_webhook_tvshows_301_s1_ef92`), so the name is matched against the
  library's own title folders by longest prefix instead; and a stray
  `.rsync-partial` sat at the top of the backup disk and would have had
  half-finished downloads migrated in as if they were backups.
- 2026-08-01 (claude): the live disk holds 147 distinct slots with up to 3
  stored versions each — which is the case the old per-transfer shape could not
  express at all.
- 131 new tests across `tests/test_backups.py` (identity, sorting, index,
  migration, restore, retention, bulk delete, settings) and
  `tests/test_backup_routes.py` (the HTTP layer end to end). 328 pass overall;
  nothing pre-existing changed behaviour.
- 2026-08-01 (claude): writing the bulk-delete tests found a real bug in the
  folder tidy-up — it started walking at the directory it had just removed, hit
  the first error and gave up, so every deletion left the empty slot, season and
  title folders behind. Retention had been doing this since it was written.
- 2026-08-02 (review): an external review of the branch found a release blocker
  and eight smaller defects. All are fixed; the blocker is worth recording
  because it would have destroyed data on the very first run.

  **Capture ids were reused within one transfer.** One id was minted per
  transfer and used for every capture it produced — a slot per episode, the
  title's extras, the unsorted bucket. The id is the index's primary key and
  the upsert replaces on conflict, so indexing the second capture deleted the
  first. A transfer displacing a whole season left one episode listed and every
  other one on disk, invisible and unrestorable. Migration had the same shape
  (a legacy folder often held a whole season) and a rebuild reproduced it,
  because it derives the id from the folder name. Fixed by making ids unique
  across the whole tree: `unique_capture_dir` now takes a set of ids already
  handed out in the current run, and the rebuild renames any folder whose name
  is already in use rather than indexing over it. Two restores at once could
  collide the same way — same millisecond, same `restore` reference, different
  slots — so a restore now reserves its id against the index too.

  The rest, in one line each:
  - a successful restore marked the capture `restored`, and the planner only
    reads `present` ones, so a restore could not be repeated and retention
    skipped it forever. `status` now means "are the files there"; `restored_at`
    records when, and only for a fully successful run.
  - the retention dialog applied the current form values, not the previewed
    ones — preview keep-10, type 1, delete the keep-1 set unseen.
  - "Clear unidentified" deleted the whole bucket on one click with no preview.
  - a settings save committed key by key, so a bad value at the end left the
    earlier ones written behind a 400.
  - a stored empty string read as "nothing saved", so clearing the Discord
    webhook fell back to the env value and kept posting to the old URL.
  - the legacy UI offered env-owned fields as editable and dropped the realtime
    connection announcing a save the server had refused.
  - `delete_files: false` removed the index row and left the files, so the
    entry came back at the next rebuild. Record-only deletion is gone.
  - the migration guard failed *open* when it could not read the transfer
    table. It now refuses.
  - five documents still described the removed session store.

- 2026-08-02 (review, second round): a follow-up review raised ~40 further
  points. Most were fixed; a few were verified as already-correct and left
  alone, with the reasons recorded in the response rather than here. The three
  worth remembering:
  1. `slots()` read season and episode off the capture, but a double episode is
     filed under its first episode and registered against both slots — so the
     S01E02 row displayed S01E01 and the page listed the same episode twice.
     Season and episode now come from the slot key, which is the authority.
  2. A rebuild deleted the index row of any capture it could not READ this time
     round, not just ones whose files were gone. A permission blip cost the pin,
     the reason and the restore time — none of which the path holds, so a
     rebuild could not put them back.
  3. Explore still built its `.explore-plans` paths as `BACKUP_PATH or '/tmp'`
     — the same fail-open the backup tree was fixed for, missed because it lives
     outside `services/backups/`. Both call sites now go through `BackupLayout`,
     so they fail closed with everything else and are bounds-checked.
- 2026-08-02 (claude): running the smoke test against the live instance
  **repaired 44 real duplicate-id collisions** on the backup disk. Seven
  transfers had each given one capture id to every episode they displaced,
  covering 51 folders; only 7 were reachable through the index and the other 44
  were sitting there unlistable. The rebuild renamed them apart. No media moved
  — 334 files before and after, newest file mtime unchanged.
- Handoff: built, tested (406), and verified against the live disk read-only.
  What has NOT happened is the migration itself — preview it in the UI, read the
  mapping, then apply. Do it with no transfers running; the code refuses
  otherwise. Deploy to prod before adopting: both instances share `BACKUP_PATH`
  but keep separate databases, so adopting from either side moves folders the
  other's index still names.

### TASK-015 — One settings boundary: env for constants, database for the rest
Status: done (unreleased)      Priority: high
Tags: backend, frontend, settings                    Branch: backup-and-rename
Docs: [docs/reference/configuration.md](docs/reference/configuration.md#where-a-setting-lives)

Plan: settings lived in three places and one of them was a lie. Establish two
stores with a written boundary, and delete the third.

Done looks like: every setting declared in one registry, the UI showing which
store each came from, and no field that appears editable and silently is not.

Steps:
- [x] `settings_registry.py` — one row per setting: store, type, default,
      bounds, whether it is a secret. 28 env, 13 database
- [x] `services/settings_service.py` — reads either store, writes only the
      database half, refuses env keys by name
- [x] Removed the per-browser session store, `save_config`, `/api/config/reset`
      and `/api/config/env-only`
- [x] `WEBSOCKET_TIMEOUT_MINUTES` moved out of the session into the database —
      it lived nowhere else, so it was per-operator and invisible to the
      cleanup thread that enforces it
- [x] Every consumer repointed at the resolver, so the env fallback is applied
      in one place instead of per call site
- [x] Startup adoption: database-eligible values still in the env file are
      copied in once, so nothing changes behaviour on the way over
- [x] Settings page generated from the registry — env read-only with
      provenance, database editable
- [x] 31 tests pinning the boundary, including that the path settings and the
      secrets cannot become editable

Notes:
- 2026-08-01 (operator): boundary chosen — remote connection, the six media
  directories, `BACKUP_PATH`, disk paths/API and `TEST_MODE` are constants;
  everything else variable.
- 2026-08-01 (claude): kept the 11 credential/secret/security keys in the env
  file against that instruction, and said so. The database is not encrypted, and
  a key editable from a web form is editable by anyone reaching that form using
  a session minted by the key they would be changing. The seven path settings
  are also the path-traversal boundary — `get_all_allowed_paths()` returns
  exactly those.
- 2026-08-01 (claude): writing the registry found `SERIES_ANIME_SYNC_WAIT_TIME`
  is in **seconds**, not minutes — the scheduler adds it straight to
  `time.time()`. Its 30–900 bounds were enforced in one route and nowhere else,
  so any other path wrote it unchecked.
- 2026-08-01 (claude): `AUTO_SYNC_MOVIES` read the env file as a fallback while
  `AUTO_SYNC_SERIES` and `AUTO_SYNC_ANIME` did not, so the same setting was
  configured two different ways depending on media type. One reader now.
- 2026-08-01 (claude): regression sweep over the whole branch after a reported
  UI crash. Four real defects found and fixed:
  1. `useRuntimeConnection` read `settings?.groups.flatMap(...)` — the optional
     chain stopped at `settings`, so any response without `groups` threw. That
     hook wraps every authenticated route, so it white-screened the entire app,
     not just Settings. It now tolerates the grouped shape, the previous flat
     shape and anything else, which is what a partial deploy actually looks
     like.
  2. The legacy static UI calls `/api/config/env-only` and `/api/config/reset`
     and reads a FLAT config map. Both endpoints had been deleted and the shape
     changed — that is the production UI. Both restored, and `/api/config` now
     returns the flat map alongside the grouped payload.
  3. `RetentionPolicy.save()` called `set_bool` on the settings resolver, which
     has no such method — every attempt to save the retention rule would have
     raised AttributeError. Hidden by a test double that answered `set_bool`;
     the tests now use the real service over a real table.
  4. Discord and auto-sync settings were still read and written through the raw
     model in five places, bypassing the registry's defaults and bounds. Every
     settings path now goes through the resolver.
- Verified with an in-process sweep of 27 endpoints against the real app and
  the live database: no 5xx, no duplicate route rules. The realtime idle
  timeout still resolves to the same 35 minutes it did before it moved stores.
- 2026-08-01 (claude): reported as "Core Config is empty". Diagnosed, not
  guessed: the dev backend on :5050 had been up 28 hours and was still serving
  the previous `/api/config`, while Vite had hot-reloaded the new frontend. So
  the cause was a missing restart — but two things about that were my fault and
  are fixed:
  1. The defensive guard added for the earlier crash rendered a BLANK panel
     when it did not recognise the response. Silence is not tolerance. It now
     says the backend is running an older version and to restart it, and has
     separate states for a failed request and a genuinely empty list.
  2. The page header still carried a "Save Automation" button, left over from
     "Save All" when one button saved every tab. A page-level button that saves
     one tab is worse than none — moved to the end of the Automation tab, next
     to what it saves.
- Verified against the restarted backend: Core Config renders 6 cards / 25
  settings, env keys refuse writes by name, the automation and Discord round
  trips are byte-identical, and the 9 stored settings survived the restart
  untouched.
- 2026-08-01 (claude): reported as "migration says 10 transfers are running when
  none are". `Transfer.get_active()` was `get_all(status_filter=None)` — the
  whole table — behind a docstring promising active transfers, with a comment
  saying filtering happened in memory that was never written. The dev database
  holds 10 completed transfers, so the guard read 10 running ones. Pre-existing,
  and dead code until the guard called it.
  Fixed at the model, not worked around at the call site: `get_active()` now
  filters on the four unfinished statuses, and `get_active_transfers()`
  delegates to it so `/api/transfers/active` and the guard share one definition.
  That delegation is byte-identical to what the listing returned before —
  pinned by `tests/test_transfer_listing.py::ActiveTransferListingTests`.
  Note the contract choice: the old docstring said running/pending, and
  implementing it literally would have dropped queued and paused transfers out
  of the Activity panel. The four-status set the coordinator already used won,
  and the docstring was corrected to match.
- 2026-08-02 (review): three more defects on this boundary, all fixed.
  1. A save committed each key as it went, so an invalid value part-way through
     left everything before it written while the response was a 400. The whole
     payload is validated first now, then written in one transaction.
  2. A stored empty string was treated as "nothing saved", so the resolver fell
     back to the env file. Clearing the Discord webhook in the UI looked like it
     worked and notifications kept going to the old URL; startup adoption then
     wrote the env value back over the blank on every restart. An empty row is
     now a deliberate choice, distinct from no row at all.
  3. The legacy static UI — which is what production serves — still rendered
     env-owned fields as editable, and after a refused save it compared what it
     had *typed* against what was loaded, dropped the realtime connection and
     announced that critical changes were saved. It now disables those fields
     using the `editable` flag the server already sends, and only reacts to keys
     in the server's `saved` list.
- Handoff: done and verified live. The Settings page's Automation tab still has
  its own controls for auto-sync and Discord; they write through the same
  resolver, so they cannot disagree with the Config tab.

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
  splitting the filename at the first " - ", so a series whose own name contains
  " - " is stored as just its first word — matching on it hides that series'
  backups from itself. Season narrowing uses each FILE's `context_season` (stored padded
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
- 2026-07-30 (claude): found in prod on "Example Series"
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

### TASK-013 — Install the React UI as a PWA on the phone
Status: planned      Priority: medium
Tags: frontend, tooling, deployment                  Branch: —
Docs: [docs/plans/mobile-app-strategy.md](docs/plans/mobile-app-strategy.md)

Plan: the UI is already a working phone UI but only ever a browser tab. Make it
installable — home-screen icon, its own task-switcher card, no URL bar, launches
from cache. Decided 2026-08-01 in favour of a PWA over Capacitor and React
Native; the plan doc holds the comparison and the numbers behind it.

Done looks like: the app opens from the home screen, survives an app switch, and
updates when new files are deployed.

Steps:
- [ ] Enable HTTPS certificates in the tailnet admin console, then put
      `tailscale serve` in front of the nginx container on 5002 — a service
      worker cannot register over plain HTTP. No code in this step
- [ ] `vite-plugin-pwa`, manifest, icon set, `display: standalone`
- [ ] Deny-list `/api` and `/socket.io` from the navigation fallback, and keep
      API responses out of the runtime cache
- [ ] Update prompt on a new build, so a cached shell cannot run against a newer
      API
- [ ] Live with it before deciding anything else
- [ ] Optional, only if it turns out to be the point: Web Push — VAPID keys, a
      subscription table, a sender beside the existing socket emits

Notes:
- 2026-08-01 (claude): the client is a remote control. rsync, SSH, the queue and
  the database are all server-side, so there is no native capability to gain —
  only notifications, which an installed Android PWA already gets. React Native
  would rewrite ~15,000 lines of components against ~4,600 portable, because
  Base UI and Tailwind are both DOM-only.
- The blocker is a secure context, not code. Tailscale is already running and
  the phone is already on the tailnet; `tailscale cert` reports no cert domains,
  which means HTTPS Certificates is simply switched off in the admin console.
- Sequenced after the backups/rename work. Do not start this first.
- Two things worth settling before an icon lands on a home screen: the React app
  is not the production UI yet, and an installed PWA is sticky. The bundle is
  also one 962 KB chunk — route-level code splitting would cut install and
  update cost.
- Handoff: not started. Step 1 is a console toggle and costs nothing to try.

## Backlog

### TASK-004 — Triage the known issues
Status: in progress      Priority: high
Tags: backend, correctness
Docs: [docs/operations/known-issues.md](docs/operations/known-issues.md)

Plan: 79 defects were found while writing the documentation. Three are verified
data-safety issues and should be handled first:

Steps:
- [x] `BACKUP_PATH` unset wrote backups to `/tmp/backup` while restore refused
      them — writing now refuses the same way, with no fallback anywhere
      (TASK-014 phase 1)
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
