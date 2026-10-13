# Automated Tests

Last updated: 2026-10-06
Primary files: everything under `tests/` — thirty-nine modules, 1053 tests

## Purpose

DragonCP has a Python test suite. It began with four areas — how rsync output is
stored, how transfer listings are queried, the simulation tool's safety guards,
and the rename webhook — and now also covers Explore, backups, connectors and
Integrations, accounts and attribution, settings, the fast transfer server, and
(since 2.3.0) the sync engine, its scheduler, the auto-scanner and the
alerts behind the Notifications page. It is still deliberately narrow: it pins behaviour
that previously broke, or a rule that was decided, rather than trying to cover
the application.

There are no frontend tests. `frontend/package.json` has no `test` script and no
test runner in its dependencies.

## Running the tests

The runner is **pytest 9.0.3**, installed in the project virtualenv at
`venv/bin/pytest`. It is *not* listed in `requirements.txt`, so a freshly
created virtualenv built by `start.py` will not have it - install it explicitly
if the suite fails to start.

From the repository root:

```bash
./venv/bin/python -m pytest tests/ -q
```

On 2026-10-06 this reports `1053 passed, 20 subtests passed`, in about three
and a half minutes.

A single module:

```bash
./venv/bin/python -m pytest tests/test_transfer_logging.py -q
```

Every module also ends with `unittest.main()`, so a file can be run on its own
without pytest:

```bash
./venv/bin/python tests/test_transfer_listing.py
```

There is no `pytest.ini`, `pyproject.toml`, `setup.cfg` or `conftest.py` in the
repository, and `tests/` has no `__init__.py`. Even so,
`./venv/bin/python -m unittest discover -s tests` runs the whole suite: checked
on 2026-10-06 with the project's Python 3.12.3, it reports `Ran 1053 tests` and
`OK`. (An earlier revision of this page said it failed with
`Start directory is not importable`; it no longer does.)

Each test module inserts the repository root onto `sys.path` itself, which is
why the tests work from any working directory without an installed package. It
is also what lets three modules share a fixture: `test_auto_scanner.py`,
`test_sync_engine_routes.py` and `test_webhook_group_sync.py` do
`from tests.test_sync_engine import EngineTestCase`, which resolves without an
`__init__.py` because, with the root on the path, Python treats `tests` as a
namespace package. Run directly, each still works
(`./venv/bin/python tests/test_auto_scanner.py` reports `Ran 23 tests`, `OK`).

### Why the tests hand the database a relative path

`DatabaseManager.__init__` joins whatever path it is given onto the repository
root. The modules that need a scratch database therefore pass
`os.path.relpath(db_path, REPO_ROOT)` for a database inside a temporary
directory, so that the join resolves back out to the temp dir. An absolute path
works as well, because `os.path.join` discards the root when handed one; the
sync-engine and scheduler modules pass the temporary path directly. Nothing is
written into the checkout and no test touches `dragoncp.db`.

The tests print database paths and transfer-record chatter to stdout while they
run, and `test_scheduler.py` prints tracebacks for the jobs it makes fail on
purpose. That is the application's own logging, not a failure.

## What each module covers

### `tests/test_transfer_logging.py` - rsync output storage (9 tests)

This is the regression suite for the log-throttling work. rsync prints a
progress line several times a second, each one superseding the last; storing
all of them dominated the log rows and the rewrite I/O per transfer. Progress
lines are now collapsed to the newest one and their writes are throttled by
`PROGRESS_WRITE_INTERVAL` (1.0 second in `services/transfer_service.py`).

The module feeds canned rsync output through `TransferService._monitor_transfer`
using a `FakeProcess` stand-in, so no rsync and no SSH are involved.

- **`test_progress_lines_collapse_to_the_newest`** - a burst of progress lines
  leaves exactly one stored line, and it is the newest; ordinary lines around it
  survive.
- **`test_real_log_lines_are_never_replaced_by_a_progress_line`** - *pins a
  specific regression.* Deciding whether to replace the last line based on the
  in-memory tail rather than on what actually reached the database let a
  progress line overwrite the real log line before it. It only shows when the
  write interval expires between the two, so the test replaces
  `transfer_service.time.monotonic` with a scripted clock to force that timing.
- **`test_final_progress_survives_the_write_interval`** - *pins a specific
  regression.* The last figures rsync reported must be persisted even when they
  land inside the throttle window, otherwise a finished transfer displays
  whatever percentage happened to fall on a write tick.
- **`test_stats_summary_is_kept_in_full`** - the `--stats` block is retained
  line for line, and the summary line's total is stored as `total_bytes`.
- **`test_errors_are_kept`** - an rsync error line between two progress lines is
  not collapsed away.
- **`test_log_is_capped`** - `Transfer.add_log(max_lines=...)` keeps the log
  bounded and drops the *oldest* lines, because the tail holds the summary and
  any errors.

### `tests/test_transfer_listing.py` - the listing query (13 tests)

Listings show how many log lines a transfer has, never the lines themselves, so
`Transfer.get_all(include_logs=False)` leaves the log column out of the SELECT
and counts it in SQL instead. These tests pin what that makes fragile.

- **`test_log_count_matches_the_stored_log`** - the SQL count agrees with the
  log it is counting.
- **`test_listing_omits_the_log_body_but_no_other_field`** - dropping the log
  column must not quietly drop any other field, and every remaining value must
  match the full row.
- **`test_status_filtering_happens_in_sql`** - both `status_filter` and the
  multi-value `statuses` argument filter correctly.
- **`test_statuses_filter_returns_nothing_when_none_match`** - an empty result
  rather than a fallback to everything.
- **`test_limit_applies_after_the_status_filter`** - *pins a specific
  regression.* Filtering used to happen after the limit was applied, so a page
  of recent completed transfers could hide every failed one. The filter belongs
  in SQL.
- **`test_log_count_survives_a_non_json_log_column`** - *pins a specific
  regression.* Rows written before the log column held JSON must not break the
  count; the test writes literal non-JSON into the column and expects a count of
  zero, not an error.
- **`test_full_read_still_parses_logs`** - the detail path (`Transfer.get`)
  still returns the lines themselves.

A second class, `ActiveTransferListingTests` (6 tests), pins the active-transfers
listing: only unfinished transfers, queued and paused ones included, never the
whole table, and still without log bodies.

### `tests/test_simulation_service.py` - simulation safety guards (8 tests)

Simulations generate files, delete them again, and run against the live
production instance, so the guards keeping them away from real data are what is
pinned. See [../features/simulation/README.md](../features/simulation/README.md)
for the feature itself.

- **`test_refuses_paths_outside_the_simulation_directory`** - `/etc`, a real
  media path, and a `..` escape from inside the simulation root are all
  rejected by `_assert_inside_root`.
- **`test_accepts_paths_inside_the_simulation_directory`** - the guard does not
  reject legitimate paths.
- **`test_cleanup_removes_only_simulation_rows`** - cleanup deletes the row
  carrying the `is_simulation` flag and leaves a real transfer row untouched.
- **`test_cleanup_removes_generated_files`** - the generated fixture tree is
  removed.
- **`test_rejects_an_unknown_scenario`** - a path-like scenario name
  (`../../etc/passwd`) is refused by the fixed scenario table rather than
  reaching the filesystem.
- **`test_refuses_a_second_run_while_one_is_on_the_board`** - a second start is
  refused while a simulation row is still running.
- **`test_every_scenario_stays_within_the_size_ceiling`** - each scenario's
  `transfers × size_mb × 2` (source and destination copies both exist at once)
  stays under `MAX_TOTAL_MB`, which is 512.
- **`test_running_real_transfers_ignores_simulations`** - the "are real
  transfers running?" check used to warn the operator does not count
  simulations as real work.

The transfer coordinator is a `MagicMock` here, and `service.root` is redirected
into a temporary directory so nothing is written into the checkout.

### `tests/test_rename_service.py` - the rename webhook (5 tests)

Exercises `RenameService.process_rename_webhook` against a real temporary media
tree, using a realistic Sonarr-style `Rename` payload with a
`renamedEpisodeFiles` entry.

- **`test_process_rename_webhook_persists_completed_at`** - the notification is
  stored as `completed` with a `completed_at` timestamp and success/failure
  counts, the old file is gone from disk, and the recorded new path exists.
- **`test_verify_rename_notification_checks_expected_target_path`** -
  `verify_rename_notification` confirms the expected renamed file exists
  locally, rather than reporting success from stored state alone.
- **`test_process_rename_webhook_reports_persistence_failure_after_rename`** -
  *pins a specific regression.* The rename on disk and the database write are
  two separate steps. When the database write fails after the files have already
  been moved, the call must report failure with `persistence_error` set, not
  success. The test forces `RenameNotification.update` to return `False` and
  then asserts the files were still moved - so the operator gets a failure they
  can act on rather than a silent divergence between disk and database.

### `tests/test_listing_pagination.py` - paging the arrivals and transfer lists (20 tests)

Pins that filtering, searching and paging all happen in SQL rather than in
Python after the fact, that a page boundary cannot drop or duplicate a row,
that bulk clear refuses what it should, and that the Manual filter finds movie
notifications as well as series ones.

### `tests/test_test_mode_and_compaction.py` - the test-mode flag and log compaction (8 tests)

Pins that `TEST_MODE` is read in exactly one place and only accepts the values
documented in [`../reference/test-mode.md`](../reference/test-mode.md), and that
compacting a stored transfer log never discards a real log line.

### `tests/test_test_mode_sync_paths.py` - test mode through every way a sync starts (7 tests)

Builds the real `TransferCoordinator`, transfer service and queue with
`TEST_MODE=1`, replaces `subprocess.Popen` and `subprocess.run` with recorders,
and starts each kind of sync through the engine: a Sonarr webhook (released
with Go now), a Radarr webhook, a press of Sync, an auto-scanner find, a
restart (the re-queue path) and an Explore plan (the `--files-from` command
shape). Every rsync launched must carry `--dry-run`, the safety check's command
too, and no destination folder may appear. A simulation is asserted as the
deliberate exception: it copies for real, between its own sandbox paths.

### `tests/test_queued_start_failures.py` - a queued transfer that cannot start (5 tests)

Builds on `RealCoordinatorTestCase` from `test_test_mode_sync_paths.py`: the
real coordinator, transfer service and queue. A season sync waits in the queue,
then the queue lets it through (`start_queued_transfer`) and the start fails:
with no backup folder, the sync ends failed at its Queue stage; with rsync
refusing to start, at its Transfer stage; either way with one *Failed* alert
offering Retry, and Retry then copies it. A transfer queued before the sync
engine existed has no sync, so its episode is marked failed instead of left
reading syncing. A resume that cannot start rsync leaves the transfer and its
sync paused. Added 2026-10-13 with the fix: before it, the sync stayed Queued
or Copying for good.

### `tests/test_webhook_group_sync.py` - "Sync all" on a webhook group (10 tests)

Rewritten for 2.3.0 on top of `EngineTestCase` (below): the grouping moved out
of `WebhookService` into the sync engine (`SyncEngine.sync_notifications`),
which groups by the folder each webhook would be copied into, worked out on the
server rather than taken from the caller. It still pins the rule that a group
syncs as **one transfer per season**: six episode notifications for one season
produce one run, one transfer, with all six webhooks on it; two seasons are
never merged into one folder sync; two series stay apart; the same season
number in different libraries stays apart.

What the engine changed, and these tests now pin:

- **An already-completed episode is left alone.** It is not re-synced and does
  not ride on the new run (it used to ride along so it linked to the run that
  fetched it). A group made only of completed episodes starts nothing and says
  "already synced".
- **Unknown ids are reported, not fatal** ("no longer exist").
- **A group that cannot be identified is reported** even when another season in
  the same request starts.
- **A webhook whose copy is running right now is not moved** to a new run,
  because that copy could then not mark it synced ("being copied right now").
- **An empty request starts nothing.**

### `tests/test_sync_engine.py` - the sync engine (72 tests)

Drives `SyncEngine` with a real temporary database and fakes for everything
that would touch the network or start rsync: Sonarr's connection check and its
"still downloading?" answers (`FakeAdapter`, `FakeIndex`), the dry run
(`FakeTransferService`), the coordinator and queue (`FakeCoordinator`, which
writes real transfer rows but starts nothing), Discord (`FakeNotifier`) and the
clock (`Clock`). The engine runs with `inline = True`, so its work happens in
the test's own thread, and the test's `tick()` does what the engine's loop does
each second. Its `EngineTestCase` is the shared fixture three other modules
build on. See [../features/sync-engine/README.md](../features/sync-engine/README.md).

- **`BatchTests`** (5) - one batch per season: a burst of four webhooks is one
  run; joining asks Sonarr nothing before the 10-second settle and exactly once
  after it; different seasons are different batches; a webhook arriving while
  the season is copying opens **one** follow-up batch, and a later one joins
  that follow-up rather than opening a third; the follow-up waits in the queue
  behind the running copy, its webhooks marked `QUEUED_PATH`.
- **`ReadyCheckTests`** (11) - the first question waits for the settle; the
  wait follows Sonarr's time-left estimate, kept between 10 seconds and 5
  minutes; a kick never asks before the next check is due; stuck downloads do
  not hold the season (and open a *Stuck download* alert); 30 minutes is the
  most it waits, and it goes at that deadline rather than a recheck later (and
  opens a *Waited 30 minutes* alert); an unreachable Sonarr means the fallback
  timer plus an *Integration* alert, an absent Sonarr connector the timer with
  no alert, and Sonarr going quiet mid-wait a switch to the timer.
  - **`test_every_webhook_pushes_the_timer_back`** - *pins a specific
    regression.* The old in-memory scheduler read the timer's extension once
    and ignored later ones. A second webhook 30 seconds in must move the end
    from 60 to 120 seconds, and the batch must still be waiting at 70.
  - **`test_the_timer_never_runs_past_fifteen_minutes`** - 38 more webhooks
    cannot push the end past 15 minutes after the batch opened.
- **`KindTests`** (8) - a Radarr webhook never waits but still gets its dry
  run; every skipped stage carries a reason; a manual sync promotes a waiting
  batch instead of starting a second transfer; with automatic sync off the
  batch is held — an hour later it has still not started — until someone
  presses Sync; Sync on an episode being copied right now leaves it on its run;
  an auto-scanner find for a folder with an open batch is skipped, not
  duplicated; a webhook that names no folder is still recorded, as a failed run
  with the webhook marked failed; an Explore plan runs synchronously, stands
  alone even with a batch open for the same folder, keeps its own safety
  summary, and its file list and run id reach the transfer row.
- **`SafetyTests`** (4) - an unsafe dry run refuses the run before anything is
  written, flags the webhook `requires_manual_sync`, opens a *Safety check*
  alert, and **Sync anyway** on that alert sends it on to the copy; a restarted
  simulation and a single-file sync skip the dry run without calling it; and
  **Sync anyway** on a run the queue then refuses reports failure and leaves the
  run `failed`.
- **`FinishTests`** (19) - completion marks every webhook `completed` and is
  announced once, as "Automated Sync"; finishing twice is harmless; a transfer
  is linked to its title in the title index, which learns the local folder from
  it; a failure
  marks the webhooks failed and opens a *Failed* alert offering **Retry**; a
  cancel is not announced; a `Result unknown` failure opens its own *Result
  unknown* alert instead of *Failed* and is not announced; a webhook attached
  after the copy began is carried to a follow-up run rather than marked synced;
  a restart is a new `restart` run (relation `retry` to the failed run) that
  re-queues the same transfer, takes the webhooks with it, skips the ready check
  and passes the safety check; `describe_run` returns all nine stages, each with
  its own log lines. Added on 2026-10-05 with the fixes they pin:
  - **Mark as done** closes the run and its webhooks but leaves the transfer
    `failed`, and the Finish stage says it "stays recorded as failed";
  - **Go now** on a finished run is refused ("This sync already ended.");
  - a queued run whose transfer row was deleted does not strand the folder: the
    next webhook opens a fresh batch and the old run is closed as cancelled,
    its Queue stage naming the deletion; and **Cancel** on such a run closes it;
  - a movie whose wait is re-filed as a folder wait moves to `QUEUED_PATH`, and
    a refused movie carries `requires_manual_sync` and the reason;
  - a held batch released with **Go now** is announced as "Manual Sync";
  - a restarted simulation is neither announced nor alerted;
  - a restart of an Explore plan's transfer skips the folder dry run;
  - a restore is not restarted from the transfer list ("Backups page").
- **`ExactCopyTests`** (4) - a copy of named files stands alone: a Retry of a
  failed Explore copy, while a webhook batch waits for the folder, opens its
  own sync, leaves the batch alone, re-queues the same transfer with the same
  file list, and a webhook arriving after it still joins the batch; Retry
  pressed twice on it starts one copy; a single-file sync never joins a
  waiting folder batch, and a webhook never joins a waiting single-file sync.
  Added 2026-10-13.
- **`StrandedRunTests`** (2) - a sync left at Copying, or at Queued, by a
  transfer that failed without telling it is closed as failed when Retry is
  pressed, and the Retry opens a new sync instead of being refused or doing
  nothing. Added 2026-10-13.
- **`LateAnswerTests`** (2) - a cancel pressed while Sonarr is answering the
  ready check, or while the dry run runs, holds: the sync stays `cancelled`, no
  copy starts, its webhook stays cancelled, and the late answer does not mark
  the stage passed (nor open a *Safety check* alert). Added 2026-10-12.
- **`RecoveryTests`** (8) - after a restart a waiting batch becomes
  `interrupted`, its webhook is flagged for a manual sync, and one *After a
  restart* alert opens whose **Sync now** starts the copy; a held batch is left
  alone, with no alert; webhooks the old in-memory scheduler had taken
  (`auto_sync_scheduled_at` set, no run) raise one alert, once, and a row
  nobody scheduled is not counted. Added 2026-10-12: **Sync now** on the alert
  for a sync with no webhooks (the auto-scanner's) syncs the same folder, and
  the alert does not say "0 webhooks"; a single file is synced again as a single
  file; an Explore list is synced again as the same list; and an Explore list
  whose file is gone is refused, copying nothing.
  - **`test_a_copy_starting_again_after_a_restart_is_not_called_interrupted`**
    - *pins a specific regression.* A run whose transfer is still `pending`
    when recovery looks — about to start — goes back to `queued`, with its
    transfer back in the queue, and opens no *After a restart* alert. Before
    2026-10-05 a copy the queue had just started at start-up could be caught
    like that and called interrupted.
- **`QueueOverlapTests`** (5) - `QueueManager` itself: two seasons of one show
  may copy together; the same season never twice; a whole-series copy collides
  with any of its seasons, and the other way round; a folder whose name merely
  starts with another's (`Show` and `Show Two`) is not a collision.
  - **`test_after_a_restart_a_series_and_its_season_do_not_block_each_other`**
    - *pins a specific regression.* A queued whole-series copy and a queued
    copy of one of its seasons, rebuilt at start-up
    (`force_unregister_stale_transfers(promote=False)`), must not both hold a
    reservation. The rebuild itself starts nothing; `promote_waiting()`, which
    start-up calls once the sync engine's recovery is over, starts the older one
    and the season waits behind it. Before 2026-10-05 each got a reservation and
    neither ever started.

### `tests/test_scheduler.py` - the scheduler (8 tests)

Drives `SchedulerService` with a real temporary database, a real
`AlertService`, a fake clock and `inline = True`, calling `tick()` by hand. Pins
what every background job gets without asking:

- **`test_first_run_comes_shortly_after_start_then_every_interval`** - nothing
  at start, the first run 60 seconds in, the next one interval (900 seconds)
  after that.
- **`test_switched_off_means_it_never_runs`** - an interval of `None` never
  runs, and the job reports `enabled: false` with no next run.
- **`test_switching_on_needs_no_restart`** - the interval is asked for on every
  tick.
- **`test_a_running_job_is_never_started_twice`** - neither the tick nor **Run
  now** starts a job that is still running.
- **`test_three_failures_in_a_row_open_one_alert_and_success_closes_it`** -
  four failures in a row leave one open *Scheduler* alert with two occurrences
  (opened at the third, bumped at the fourth), and the next success closes it.
- **`test_a_dismissed_failing_job_stays_quiet_for_a_day`** - once dismissed, a
  job that keeps failing opens no new alert on its next run; with the
  dismissal moved more than a day into the past, the next failure opens one
  again.
- **`test_the_last_result_survives_a_restart`** - a second `SchedulerService`
  on the same database reads the last result and outcome back from
  `scheduled_job`.
- **`test_one_broken_job_does_not_stop_the_others`** - a job that raises is
  recorded as failed with the error in its last result, and the healthy job
  beside it still runs.

### `tests/test_auto_scanner.py` - the scheduled auto-scanner (23 tests)

Builds on `EngineTestCase`, so every find goes through a real engine. The
service (`FakeArr`: its connection check, switch, interval, import history and
season folder names) and the library view (`FakeLibraryIndex`) are fakes. Pins
the rules decided on 2026-10-02:

- **`test_switched_off_means_no_schedule`** - off, the scheduler gets no
  interval; on, 15 minutes becomes 900 seconds.
- **`test_an_import_nothing_synced_is_synced`** - an import starts one
  `auto_scanner` run into the right season folder; its Receive stage says the
  import was never synced, and it carries the TVDB id the ready check asks about.
- **`test_an_import_already_synced_since_is_left_alone`** - once a copy that
  started after the import has completed, the next scan finds nothing.
- **`test_a_copy_that_began_before_the_import_does_not_cover_it`** - a sync's
  copy that started before the import and finished after it is not "synced
  since", even though its transfer row ended after the import. Added 2026-10-12
  with the fix.
- **`test_a_copy_from_before_the_engine_counts_from_its_start`** and
  **`test_a_copy_from_before_the_engine_that_began_too_early_does_not`** - a
  transfer with no sync counts from its start time, not its end time.
- **`test_a_resumed_copy_counts_from_when_it_listed_the_folder_again`** - a copy
  paused before the import and resumed after it covers the import.
- **`test_a_single_file_copy_does_not_cover_the_season`** - one file copied
  after the import does not count for the season.
- **`test_a_season_already_on_its_way_is_not_duplicated`** - a season with a
  webhook batch open counts as already on its way and starts nothing.
- **`test_an_import_after_the_copy_began_is_looked_at_again`** - an import that
  lands after the season's copy began does not move the history window, and the
  scan after that copy finishes syncs it.
- **`test_a_short_season_this_disk_keeps_is_filled_in`** - 8 files here against
  10 at the service starts a sync whose Receive stage says files are missing
  here.
- **`test_a_double_episode_file_is_not_a_gap`** - 9 files holding 10 episodes
  (one double-episode file) against Sonarr's 10 is not a gap. Added 2026-10-13.
- **`test_a_short_season_is_copied_between_its_real_folders`** - a short
  season kept in `Season 1`, on the server and here, is copied between those
  folders, not rebuilt `Season 01` ones.
- **`test_a_season_folder_here_keeps_its_own_name`** - Sonarr's `Season 01`
  is copied into this disk's own `Season 1`, not a second folder beside it.
- **`test_the_backlog_is_not_a_gap`** - a season this disk holds nothing of, and
  a title it never held, start nothing.
- **`test_a_new_title_is_fetched_once_it_is_imported`** - a title this disk
  never held is fetched when the service imports something for it.
- **`test_specials_are_ignored`** - season 0 imports are not finds.
- **`test_a_path_outside_the_configured_root_is_refused`** - a service path
  outside the configured remote library root is not a find.
- **`test_the_real_season_folder_name_is_used`** - a library whose folder is
  `Season 1` is copied from that folder, not from a rebuilt `Season 01`.
- **`test_at_most_five_new_syncs_per_scan_and_the_rest_wait`** - seven finds
  start five and hold two back without moving the history window; the next scan
  starts the two.
- **`test_a_gap_tried_twice_waits_for_a_person`** - after two attempts the third
  scan starts nothing and opens one *Auto-scanner* alert.
- **`test_a_service_that_does_not_answer_is_a_failed_scan`** - the scan reports
  `ok: false`, which the scheduler counts as a failure.
- **`test_sync_one_fetches_every_short_season_on_request`** - **Sync** on one
  title in a Library tab starts a `manual` run for every season that is short or
  missing (two of three here); the backlog rule does not apply to a title a
  person named.

It replaces `tests/test_autosync_sweep.py`, which was deleted with the library
sweep in 2.3.0.

### `tests/test_sync_engine_routes.py` - the pipeline, Notifications and scheduler routes (21 tests)

Mounts `routes/sync_engine.py` on a bare Flask app over `EngineTestCase`, with
a real `SchedulerService` holding one fake `sonarr_auto_scanner` job. Sign-in is
stood in for by patching the three token checks in `auth`, except in
`SignedOutTests`. `test_runs_filter_by_whether_their_copy_started` pins the
`copied` filter the Transfers page lists its waiting and stopped syncs with.

- **`PipelineRouteTests`** (12) - `/api/sync/catalogue` serves the nine stages
  and the kinds the engine runs, with the state groups and alert actions;
  `/api/sync/runs` lists a run with its nine-stage strip, webhook count, label
  (`Example Show — Season 01`) and `current_summary` (what the run is doing
  now), and filters by state group and by one or
  several kinds; `/api/sync/runs/<run_id>` shows every stage with its own log
  lines, the run's webhooks and the actions available; a skipped stage says
  why; an unknown run is 404, for the run and for its events; `/events` honours
  `after` and `stage`; `/api/sync/lookup` finds the run from a
  `notification_id` or a `transfer_id`, and is 400 with neither and 404 for an
  unknown transfer; **Go now** skips the wait, and is 409 on a run that has
  already finished; **Cancel** works once and is 409 ("This sync already
  ended.") the second time; **Sync anyway** is 409 unless the safety check
  refused the run, and then goes ahead.
- **`AlertRouteTests`** (5) - `/api/alerts` and `/api/alerts/summary` show a
  refused sync's alert and the open count; acting on it with `sync_anyway`
  starts the copy and closes the alert; `total` follows the `kind` filter (two
  alerts open, one of them asked for, `total` 1); a dismissed alert is listed by
  `state=done,wrong,dismissed` — the Notifications page's Closed tab — and no
  longer counted as open; an unknown action is 400, an unknown alert 404, and
  acting on an alert already closed 409.
- **`SchedulerRouteTests`** (2) - `/api/scheduler/jobs` lists the job with its
  switch; **Run now** runs it once and returns its last result; an unknown job
  is 404.
- **`SignedOutTests`** (1) - signed out, the five listing GETs and all five
  POSTs answer 401.

### `tests/test_autosync_gate.py` - Sonarr's and Radarr's download queue, read safely (36 tests)

The rule it exists for: **an automatic sync must never fail, and never stall,
because a status check failed.** It reads queue payloads shaped from real
Sonarr v4 and Radarr v6 rows and pins how the connector classifies them
(`GateDecisionTests`), every way asking can fail (`GateFallbackTests`: the
service unreachable or timing out, credentials rejected, a proxy or gateway
answering instead, no address, no key, a long queue), the title index
(`MediaItemStoreTests`), that the adapters only ever read (`ReadOnlyTests`), and
that test mode makes rsync a dry run without halting automation
(`TestModeIsARehearsalNotAHaltTests`).

Changed in 2.3.0:

- **`importBlocked` and `failedPending` no longer hold a season.** They are
  counted as stuck instead (`test_stuck_states_do_not_hold_but_are_counted`);
  `downloading`, `importPending` and `importing` still hold.
- **Sonarr's time left comes back in seconds**
  (`test_the_time_left_comes_back_as_seconds`: `00:03:10` is 190).
- **`SchedulerWaitTests` is gone** with the in-memory scheduler it tested; the
  wait's tests are `ReadyCheckTests` in `test_sync_engine.py`.
- **The test-mode checks follow the code.** They now assert that the sync
  engine's source never consults test mode, and look for the film webhook
  route's hand-off to the engine (`_submit_webhook('radarr_webhook'`) rather
  than the old auto-sync log line.

### The Explore suite (8 modules, 158 tests)

| Module | Tests | Pins |
|---|---|---|
| `test_explore_identity.py` | 15 | Filename → episode identity, checked against the real filename shapes in the library, including anime absolute numbering and `Specials` as season 0 |
| `test_explore_compare.py` | 22 | The four labels, seasons paired by **number** not folder spelling, and local-only files not breaking a "Synced" verdict |
| `test_explore_planner.py` | 24 | What a plan does and what the safety checks refuse; multi-season plans; that only an explicit replace re-fetches a file that already matches |
| `test_explore_service.py` | 24 | An end-to-end run with the SSH boundary faked, and that approved plans are single-use, expire, and get purged |
| `test_explore_routes.py` | 9 | The HTTP layer: real status codes, rate limiting, and that a plan id is the only thing the client may quote |
| `test_explore_dryrun.py` | 24 | Reading rsync's itemised `--dry-run` output, and reconciling it with the plan — in particular that a file rsync reports as unchanged is still shown as replaced when the plan backs its local copy up first |
| `test_explore_backups.py` | 11 | Scoping backups to a series and season, including the two traps taken from real production data: a series title the parser mangles, and season numbers stored zero-padded as text |
| `test_explore_repair.py` | 29 | In its own words: "Repairing the files the old single-episode download stranded." |

The counts in this table were refreshed on 2026-10-05; the "Pins" column for
the first seven was written earlier and was not re-read against the grown
modules.

### Modules not described above

Counted on 2026-10-05 (`pytest --collect-only`). The right-hand column is the
first line of each module's own docstring, not a review of what it covers.

| Module | Tests | Its docstring opens with |
|---|---|---|
| `test_activity.py` | 33 | "Attribution: every consequential action has someone answerable for it." |
| `test_admin_accounts.py` | 47 | "Named administrator accounts, and the two properties that make them worth having." |
| `test_auth_routes.py` | 28 | "The sign-in HTTP layer: logging in, changing your own password, and being shut out." |
| `test_backup_preserve.py` | 14 | "Hardlink where it is safe, copy where it is not." |
| `test_backup_routes.py` | 35 | "The Backups HTTP layer, end to end." |
| `test_backups.py` | 139 | "Backups — slots, versions, and putting a version back." |
| `test_connector_routes.py` | 21 | "The connector HTTP layer." |
| `test_connectors.py` | 85 | "The connector layer: one way to talk to an outside service." |
| `test_dry_run_visibility.py` | 15 | "Saying what actually happened." |
| `test_frontend_serving.py` | 8 | "The production Flask process serves the React SPA, not the retired client." |
| `test_library_compare.py` | 27 | "One title, episode by episode — the comparison behind the Library detail view." Also `SizeMatchTests`, the list's size check |
| `test_library_rules.py` | 59 | "The Library list's verdicts, the detail view behind each card, and the History and Queue rows — through the HTTP layer, against a fake Sonarr and Radarr." |
| `test_media_library_routes.py` | 27 | "The library and history HTTP layer." |
| `test_remote_daemon.py` | 66 | "The transfer server on the remote host." |
| `test_restore_safety.py` | 12 | "A restore must never leave a live library file welded to a stored backup." |
| `test_settings_boundary.py` | 49 | "The settings boundary: two stores, and only two." |
| `test_transfer_routing.py` | 13 | "Which route a transfer takes, and what that changes about the command." |
| `test_version.py` | 7 | "One version, in one place." |

One class in that table was added on 2026-10-05 to pin a fix, so it is named
here: **`DryRunThatDidNotFinishTests`** (4) in `test_dry_run_visibility.py`. A
dry run rsync could not finish — exit 255 with "Connection refused", exit 23 for
a missing folder — is not safe, its reason says "did not finish (rsync exit
N)" with rsync's error, and the result carries `rsync_exit_code`; exit 24,
files vanishing mid-scan, still counts as a complete answer. The reason quotes
the line that names the cause: given an ssh host-key `Warning:`, a
"Could not resolve hostname" line and rsync's closing `rsync error: … (code
255)`, it carries the hostname line. rsync itself is replaced by a canned
result, so no process runs.

## What the tests deliberately do not cover

Six modules under `routes/` are tested over HTTP, each mounted on a bare Flask
app and driven through its test client: `routes/auth.py`
(`test_auth_routes.py`), `routes/backups.py` (`test_backup_routes.py`),
`routes/connectors.py` (`test_connector_routes.py`), `routes/explore.py`
(`test_explore_routes.py`), `routes/media_library.py`
(`test_media_library_routes.py`) and, since 2.3.0, `routes/sync_engine.py`
(`test_sync_engine_routes.py`). `test_settings_boundary.py` and
`test_frontend_serving.py` make HTTP requests too, but to a stand-in
`/api/config` route and to the SPA-serving helper, not to a module under
`routes/`.

The rest of `routes/` has no HTTP-level test: `activity.py`, `debug.py`,
`logs.py`, `media.py`, `remote_daemon.py`, `simulation.py`, `transfers.py` and
`webhooks.py`. That leaves the webhook receivers, starting a transfer by hand
and the transfer actions (pause, resume, cancel, restart, and delete — which
cancels a waiting transfer first) unexercised at the HTTP layer; `test_autosync_gate.py` reads the source of `routes/webhooks.py` but
sends it no request. `webhook_auth.py` and `security.py` have no test module of
their own, so webhook signature and IP checks are unverified.

No test opens an SSH connection or runs a real rsync. `ssh.py` is untested. The
rsync command that `TransferService` builds is asserted on only by
`test_transfer_routing.py`, which compares it across the SSH and fast routes;
the logging tests bypass process launch entirely by feeding a fake process into
the monitor loop.

`services/transfer_coordinator.py` has no module under `tests/`: the sync
engine tests stand a `FakeCoordinator` in its place, so the real hand-off —
`start_transfer`, `requeue_transfer`, and the finish hook that sends a run to
the Finish and Tell stages — is unverified. `services/queue_manager.py` is
covered only for which destinations collide and, since 2026-10-05, for
rebuilding queued reservations after a restart (`QueueOverlapTests`); the slot
cap and promotion when a transfer finishes are not.
`services/webhook_service.py` lost its only coverage in 2.3.0, when group sync
moved into the engine: no test imports it now. `services/notification_service.py`
is exercised only through the call-site checks in `test_connectors.py`; the
engine tests use a fake notifier. Batching, the ready check and recovering
unfinished sync runs after a restart — unverified until 2.3.0 — are now pinned
by `test_sync_engine.py`; resuming a transfer whose rsync survived a restart
still is not. The sync engine's and alert service's socket emits are not
exercised: every test builds both without a socket.

`services/backups/` is covered by `test_backups.py` (identity, sorting into the
tree, the index and its rebuild, migration, restore, retention) and
`test_backup_routes.py` (the HTTP layer, against real files on a temp disk).
Both use real directories and a real database; only auth and the transfer queue
are stood in for.

The rsync command Explore builds is asserted on indirectly — the dry run runs
the same command builder — but no test launches rsync or opens an SSH
connection.

There are no frontend tests at all - no component, routing or API-client tests.

Concurrency is only touched incidentally. `QueueOverlapTests` checks that a
second transfer for a destination already being written is seen as a
collision, and the engine's per-folder batching is tested in a single thread
(`inline = True`), but nothing in `tests/` runs two transfers at once.

## A second, untracked queue script

`test/test_queue_behaviors.py` (singular `test/`, not `tests/`) is **not tracked
in git** and is not collected by the command above. It is a hand-rolled script
rather than a unittest module: it drives `QueueManager` with a fake coordinator
and raises `AssertionError` on failure.

```bash
./venv/bin/python test/test_queue_behaviors.py [all|queued_path|queued_slot]
```

It checks that a path-queued transfer reclaims the path lock when promoted and
then blocks a late same-path request (the `#40` fix described in
[../features/queue/README.md](../features/queue/README.md)), and that a
slot-queued transfer keeps its destination reservation and starts once a slot
frees. It writes and deletes SQLite files inside `test/` as it runs. Checked on
2026-10-05 against the 2.3.0 queue manager: it still passes, and leaves nothing
behind.

Because it is untracked, treat it as a local aid, not part of the suite. If
queue behaviour is worth pinning permanently, it belongs in `tests/` as a
unittest module — which is what `QueueOverlapTests` in `test_sync_engine.py`
now does for the rule about which destinations collide and for the start-up
rebuild of queued reservations, though not yet for promotion after a transfer
finishes, or for slots.

## Known gaps

- pytest is not in `requirements.txt`, so the suite's own runner is not part of
  the documented install. A clean environment cannot run the tests without an
  extra step.
- There is no test configuration file, so there is no single command that is
  guaranteed to pick up the right paths - the modules patch `sys.path`
  themselves to compensate. Three modules also import their fixture from
  `tests.test_sync_engine`, which only resolves while the repository root is on
  `sys.path`.
- The queue system, which is the most concurrency-sensitive part of the
  application, is covered in `tests/` only for which destinations collide and
  for the start-up rebuild of queued reservations; promotion after a transfer
  finishes, and the slot cap, rest on an untracked script.
- The real `TransferCoordinator` is never run by a test, so the seam between
  the sync engine and the queue is covered only through fakes.

## Related

- [running.md](running.md) - starting the backend and the frontend dev server
- [installation.md](installation.md) - first-time setup
- [../features/simulation/README.md](../features/simulation/README.md) - the
  simulation tool the safety tests protect
- [../features/queue/README.md](../features/queue/README.md) - queue behaviour
  the untracked script exercises
- [../features/sync-engine/README.md](../features/sync-engine/README.md) - the
  pipeline, scheduler, auto-scanner and alerts the 2.3.0 modules pin
