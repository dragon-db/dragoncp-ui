# Automated Tests

Last updated: 2026-07-28
Primary files: everything under `tests/` — fourteen modules, 169 tests

## Purpose

DragonCP has a small Python test suite covering four areas: how rsync output is
stored, how transfer listings are queried, the simulation tool's safety guards,
and the rename webhook. It is deliberately narrow - it pins behaviour that
previously broke, rather than trying to cover the application.

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

At the time of writing this reports `24 passed`.

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
repository, and `tests/` has no `__init__.py`. That last point matters:
`python -m unittest discover -s tests` fails with
`Start directory is not importable`. Use pytest, or run the files directly.

Each test module inserts the repository root onto `sys.path` itself, which is
why the tests work from any working directory without an installed package.

### Why the tests hand the database a relative path

`DatabaseManager.__init__` joins whatever path it is given onto the repository
root. The modules that need a scratch database therefore pass
`os.path.relpath(db_path, REPO_ROOT)` for a database inside a temporary
directory, so that the join resolves back out to the temp dir. Nothing is
written into the checkout and no test touches `dragoncp.db`.

The tests print database paths and transfer-record chatter to stdout while they
run. That is the application's own logging, not a failure.

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

### `tests/test_transfer_listing.py` - the listing query (7 tests)

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

### `tests/test_listing_pagination.py` - paging the arrivals and transfer lists (19 tests)

Pins that filtering, searching and paging all happen in SQL rather than in
Python after the fact, that a page boundary cannot drop or duplicate a row, and
that bulk clear refuses what it should.

### `tests/test_test_mode_and_compaction.py` - the test-mode flag and log compaction (8 tests)

Pins that `TEST_MODE` is read in exactly one place and only accepts the values
documented in [`../reference/test-mode.md`](../reference/test-mode.md), and that
compacting a stored transfer log never discards a real log line.

### `tests/test_webhook_group_sync.py` - "Sync all" on a webhook group (8 tests)

Pins the rule that a group syncs as **one transfer per season**: six episode
notifications for one season must not produce six transfers, two seasons must
not be merged into one folder sync, two series stay apart, the same season
number in different libraries stays apart, and an already-completed episode
still rides along so it links to the run that fetched it.

### The Explore suite (7 modules, 105 tests)

| Module | Tests | Pins |
|---|---|---|
| `test_explore_identity.py` | 15 | Filename → episode identity, checked against the real filename shapes in the library, including anime absolute numbering and `Specials` as season 0 |
| `test_explore_compare.py` | 15 | The four labels, seasons paired by **number** not folder spelling, and local-only files not breaking a "Synced" verdict |
| `test_explore_planner.py` | 16 | What a plan does and what the safety checks refuse; multi-season plans; that only an explicit replace re-fetches a file that already matches |
| `test_explore_service.py` | 17 | An end-to-end run with the SSH boundary faked, and that approved plans are single-use, expire, and get purged |
| `test_explore_routes.py` | 9 | The HTTP layer: real status codes, rate limiting, and that a plan id is the only thing the client may quote |
| `test_explore_dryrun.py` | 24 | Reading rsync's itemised `--dry-run` output, and reconciling it with the plan — in particular that a file rsync reports as unchanged is still shown as replaced when the plan backs its local copy up first |
| `test_explore_backups.py` | 11 | Scoping backups to a series and season, including the two traps taken from real production data: a series title the parser mangles, and season numbers stored zero-padded as text |

These are the only modules that test anything under `routes/`.

## What the tests deliberately do not cover

Nothing under `routes/` is tested **except `routes/explore.py`**, which has
`test_explore_routes.py`. There are no HTTP-level tests elsewhere: no Flask test
client, no request/response assertions, no authentication or webhook-signature
tests. `auth.py`, `webhook_auth.py` and `security.py` have no test module.

No test opens an SSH connection or runs a real rsync. `ssh.py` is untested, and
the rsync command that `TransferService` builds is never asserted on - the
logging tests bypass process launch entirely by feeding a fake process into the
monitor loop.

`services/queue_manager.py`, `services/transfer_coordinator.py`,
`services/auto_sync_scheduler.py`, `services/backup_service.py` and
`services/notification_service.py` have no module under `tests/`. Path-lock and
slot-cap behaviour, queue promotion, restart recovery, auto-sync batching,
backup restore and Discord notifications are all unverified by the suite.
`services/webhook_service.py` is covered only for group sync.

The rsync command Explore builds is asserted on indirectly — the dry run runs
the same command builder — but no test launches rsync or opens an SSH
connection.

There are no frontend tests at all - no component, routing or API-client tests.

Concurrency is only touched incidentally. Nothing in `tests/` exercises two
transfers competing for the same destination.

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
frees. It writes and deletes SQLite files inside `test/` as it runs.

Because it is untracked, treat it as a local aid, not part of the suite. If
queue behaviour is worth pinning permanently, it belongs in `tests/` as a
unittest module.

## Known gaps

- pytest is not in `requirements.txt`, so the suite's own runner is not part of
  the documented install. A clean environment cannot run the tests without an
  extra step.
- There is no test configuration file, so there is no single command that is
  guaranteed to pick up the right paths - the modules patch `sys.path`
  themselves to compensate.
- `python -m unittest discover` does not work on `tests/` for want of an
  `__init__.py`, which is a surprise for anyone who assumes the standard layout.
- The queue system, which is the most concurrency-sensitive part of the
  application, is only covered by an untracked script.

## Related

- [running.md](running.md) - starting the backend and the frontend dev server
- [installation.md](installation.md) - first-time setup
- [../features/simulation/README.md](../features/simulation/README.md) - the
  simulation tool the safety tests protect
- [../features/queue/README.md](../features/queue/README.md) - queue behaviour
  the untracked script exercises
