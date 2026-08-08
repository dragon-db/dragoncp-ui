# Test mode

Last updated: 2026-08-06

What `TEST_MODE` guarantees, path by path. This is the lookup you check before
trusting a test installation with a real media library — or before deciding
whether an incident on a test box could have touched real files.

For how to turn it on and what it is for day to day, see
[../getting-started/running.md](../getting-started/running.md). For the key
itself alongside every other setting, see
[configuration.md](configuration.md).

## The one-line answer

With test mode on, nothing in this application writes to, renames or deletes a
media file. Simulations are the single deliberate exception, and they are
confined to their own directory — see [Simulations](#simulations) below.

## How the flag is read

One function, `env_flags.test_mode_enabled()`, used by every gate. It accepts
`1`, `true`, `yes` and `on`, in any case, with surrounding whitespace ignored.
Anything else — including unset — is off.

The permissive reading is deliberate. Of the two ways to misread the flag, only
one loses data: treating a truthy value as *off* runs real copies and deletes
while the interface says otherwise, whereas treating it as *on* runs a dry run
when someone wanted a real copy.

`app.py` loads `dragoncp_env.env` early and pushes each key into the process
environment with `setdefault`, so a real environment variable wins over the
file, but a file value still reaches every reader.

> Until 2026-07-29 there were two readers that disagreed, and `TEST_MODE=true`
> produced an installation that announced test mode and copied for real. That
> defect and its history are recorded in
> [../operations/known-issues.md](../operations/known-issues.md).
> `tests/test_test_mode_and_compaction.py` fails the build if any module
> compares `TEST_MODE` against a literal again.

## Every path that can write to a media library

Audited 2026-07-31 by reading every `os.rename`, `os.remove`, `os.unlink`,
`shutil.rmtree`, `shutil.move`, `os.makedirs` and `subprocess` call under
`services/`, `routes/` and `config.py`. Nothing outside this table touches
media.

| What it does | Where | With test mode on |
|---|---|---|
| Transfer rsync — copies from the remote, and `--delete` removes destination files absent from the source | `services/transfer_service.py:599` | `--dry-run` appended; no bytes move and nothing is deleted |
| Destination directory creation | `services/transfer_service.py:497` | Printed, not created |
| Backup staging directory and its `.rsync-partial` | `services/transfer_service.py:555` | Printed, not created |
| Rename webhook — `os.rename` on a local media file | `services/rename_service.py:342` | Skipped; reported as `Renamed successfully (dry run)` |
| Restore — keeping the file it is about to replace | `services/backups/restore.py` (`_capture_current`) | Skipped; logged as `would store N replaced file(s)` |
| Restore — writing the restored file | `services/backups/restore.py` (`_restore_one`) | Skipped; logged as `would write <path>` |
| Restore — removing the file it replaced | `services/backups/restore.py` (`_restore_one`) | Skipped; logged as `would remove <path>` |
| Restore destination directory creation | `services/backups/restore.py` (`RestoreRunner.run`) | Skipped |
| Explore — moving superseded/removed local files into backup before a run | `services/explore/executor.py:87` | Skipped, printed as `TEST_MODE: would move to backup`. **This gate is load-bearing:** the rsync is dry, so moving the local copies anyway would strand them — old copy gone, new one never fetched |
| Explore transfer rsync | `services/transfer_service.py:838` | `--dry-run` inserted into the same command the real run uses |
| Config file write | `config.py:124` | Printed; in-memory config still updates |
| React production build | `start.py:build_frontend` | Unchanged by test mode; writes production assets under `frontend/dist/` and may regenerate `frontend/src/routeTree.gen.ts`; neither location is a media path |

Two paths need no gate because they are never destructive:

| What it does | Where | Why it is safe in every mode |
|---|---|---|
| Media validation rsync, behind `POST /api/media/dry-run` | `services/transfer_service.py:299` | `--dry-run` is hardcoded into the command, not conditional |
| Explore dry run, behind `POST /api/explore/dry-run` | `services/transfer_service.py` (`run_explore_dry_run`) | `--dry-run` is inserted unconditionally; the plan is read without being consumed |
| Explore plan and dry-run file lists | `services/explore/executor.py` (`_work_dir`), `services/explore/service.py` (`_files_from`) | Writes only a list of filenames under `BACKUP_PATH/.explore-plans/`; never touches a media directory |
| Disk and tooling probes — `df -h`, `which rsync`, `rsync --version` | `routes/debug.py:134`, `:135`, `:288` | Read-only commands |

Nothing deletes anything on the remote server. The only remote access is
paramiko for browsing (`ssh.py`) and rsync pulling *from* the remote.

## Simulations

Simulations are **exempt from the dry run by design** and stay exempt with test
mode on: they have to move real bytes for the speed, size and ETA figures to
mean anything.

They are safe regardless of the flag because of containment, not gating. Every
path a simulation writes to or deletes is passed through
`SimulationService._assert_inside_root()`
(`services/simulation_service.py:142`), which resolves the real path and refuses
outright if it falls outside `<app_dir>/.simulations`. It guards the run
directory, both ends of the copy, the deliberate mid-run source deletion used by
the failure scenario, and the cleanup that removes the whole tree
(`:259`, `:300`, `:301`, `:419`, `:462`).

So a simulation cannot reach a real media path even though it is not running
dry. This is why simulations are safe to run against production — see
[../features/simulation/README.md](../features/simulation/README.md).

## What test mode does not do

- **It does not gate the simulation endpoints.** `/api/simulation/status`,
  `/start`, `/stop` and `/cleanup` are registered unconditionally and protected
  by `@require_auth`. Nothing in `routes/simulation.py` or
  `services/simulation_service.py` reads `TEST_MODE`.
- **It does not bypass authentication.** Neither `auth.py` nor
  `webhook_auth.py` mentions it.
- **Restore IS a usable rehearsal.** A restore under test mode reports success
  and logs, line by line, which file it would keep, which it would write and
  which it would remove — the whole plan, without touching anything. It no
  longer builds an rsync command around a file list it deliberately did not
  write, which is what used to make every test-mode restore fail. See
  [../features/backups/README.md](../features/backups/README.md).
- **It does not stop retention or the backup sorter.** Both only ever move or
  remove files inside `BACKUP_PATH`, never in a media library. A test-mode
  transfer displaces nothing, so there is nothing for them to sort.
- **It does not stop the database being written.** Transfers, notifications and
  logs are recorded exactly as normal. Test mode protects files, not rows. An
  Explore run in test mode still creates its transfer row, its per-file records
  and its history entry — they will say the run completed, because it did; it
  simply moved no bytes.
- **It does not stop Discord notifications.** `services/notification_service.py`
  never reads the flag, so a completed test-mode transfer sends a real "transfer
  finished" embed to the configured webhook. Repeated rehearsals will post
  repeatedly. Turn the Discord webhook off in Settings while testing if that
  matters.

## Confirming it from a running instance

The runtime profile reports the flag as it was actually read, so an operator can
check rather than assume:

- the startup log line `Runtime profile initialized: ... test_mode=...`, and a
  `WARNING` line when it is on;
- `GET /api/runtime/status`, under `runtime_status.websocket.runtime`, readable
  from the in-app log viewer.

A transfer running dry also says so in its own log:
`🧪 TEST_MODE enabled - rsync will run in dry-run mode (no actual file transfers)`.

## Related

- [../getting-started/running.md](../getting-started/running.md) — turning it on, and what it is for
- [configuration.md](configuration.md) — the key alongside every other setting
- [../features/simulation/README.md](../features/simulation/README.md) — the deliberate exception
- [../features/backups/README.md](../features/backups/README.md) — what a restore reports when it runs dry
- [../features/renames/README.md](../features/renames/README.md) — the rename path this gates
- [../operations/known-issues.md](../operations/known-issues.md) — the two defects behind this page
