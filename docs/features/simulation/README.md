# Transfer Simulation

Runs the real transfer pipeline against throwaway files generated on this
machine, so an admin can watch queueing, webhook status handling and the UI
behave without touching media or the remote server.

Implementation: `services/simulation_service.py`, `routes/simulation.py`,
`frontend/src/components/transfers/simulation-panel.tsx`; the `simulation` kind of
sync in `services/sync_engine/stages.py`.

## 1. Why it is not a mock

The previous tool (`simulator.py`, removed) wrote invented progress lines
straight to the database. It exercised none of the code a real transfer runs:
not rsync, not the command construction, not the progress parser, not the
monitor loop, not the queue. It had drifted far enough that pause and resume
needed a `transfer_id.startswith('sim_')` special case in the coordinator to
work at all.

A simulation generates fixture files and hands each copy to the sync engine
as a `simulation` sync - the same pipeline every webhook, manual sync and
Explore plan goes through ([sync engine](../sync-engine/README.md)). It waits
for the queue's answer (`submit(..., wait=True)`), and at its Queue stage the
engine calls `TransferCoordinator.start_transfer()`. Everything after that is
the production path:

- duplicate-destination detection and path queueing
- slot queueing and promotion
- rsync itself, and the command that is built for it
- progress parsing, log collapsing, the socket events
- pause, resume, stop, restart, completion handling
- webhook notification status tracking, by the same engine code that does it
  for real webhooks

The only difference on the copy is that rsync is pointed at local paths
instead of over SSH, and held to a speed limit so a copy takes long enough to
watch. That branch is a single `if is_simulation` in
`TransferService.start_rsync_process`.

What the pipeline does differently for a rehearsal is written in
`stages.KINDS` and recorded on each run, stage by stage, with the reason:

| Stage | For a simulation |
|---|---|
| Receive, Identify | Run, and marked as a simulation. Identify skips the check that the destination is inside a library folder, because the sandbox is not one; `_assert_inside_root` (below) is the boundary instead |
| Batch | Skipped: "Each rehearsal transfer stands alone, so what it exercises is the queue’s own rules — slots and folder locks." |
| Ready check | Skipped: nothing is downloading in a rehearsal |
| Safety check | Skipped: the dry run checks the media server, and a simulation copies sandbox files on this machine |
| Queue, Transfer, Finish | As for any sync. The Transfer stage records the copy as local |
| Tell | Skipped: "Rehearsals are not announced on Discord." A failed simulation opens no alert either |

Before 2.3.0 a simulation called `start_transfer()` directly, and its results
were announced on Discord like a real sync's.

## 2. What it does not cover

The network. SSH authentication, the host-key policy, real throughput to the
remote server and remote filesystem reachability are all bypassed, because the
copy never leaves this machine.

That is deliberate: it is a different question with a different failure mode.
See `../../plans/remote-connection-check.md`, which is parked until the native
transfer client work.

Nor does it cover the stages a rehearsal skips: Sonarr is never asked whether
anything is still downloading, the safety check's dry run never happens, and
nothing is batched. Those are covered by `tests/test_sync_engine.py` instead.

## 3. Scenarios

Defined in `SCENARIOS` in `services/simulation_service.py`.

| Key | What it sets up |
|---|---|
| `queue_overflow` | More copies than slots, so extras wait and are promoted |
| `path_conflict` | Two copies aimed at one destination; the second waits on the path |
| `slow_copy` | One deliberately slow copy, long enough to pause and resume |
| `failure` | Source removed mid-run, so rsync fails the way a broken transfer does |
| `season_batch` | Several episode arrivals for one season, as Sonarr imports do |

Each carries a transfer count, a fixture size, and a `bwlimit_kbps` that decides
how long it runs. Every scenario has `with_webhooks` on, so each transfer also
gets a notification row, handed to the engine with its run. The engine keeps
that row's status in step with the transfer - `READY_FOR_TRANSFER`, then
`QUEUED_SLOT` or `QUEUED_PATH` while it waits, `syncing`, then the outcome -
which is what exercises the status handling described in `../queue/README.md`.

`season_batch` does not actually batch. Each of its arrivals has its own
fixture folder, its own destination and, as a simulation, its own run, so
three arrivals are three transfers. Batching itself is pinned by
`tests/test_sync_engine.py` (`BatchTests`).

## 4. Safety

Simulations are intended to be runnable in production, so the guards matter.

**Files.** Everything is generated under `.simulations/` inside the app
directory. `_assert_inside_root` resolves any path and refuses it if it falls
outside that root, and it is called before anything is written *or deleted*.
Media paths are never read or written.

**Rows.** Every transfer, notification and sync run created is flagged
`is_simulation`. Cleanup deletes by that flag only - runs together with their
stages and log lines - so genuine history cannot be caught by it.

**Size.** `MAX_TOTAL_MB` caps what a scenario may generate, counting both copies
because the fixtures and the destination coexist on disk. Free space is checked
before starting.

**The queue.** Simulations share the real queue, which is the only way queueing
can genuinely be observed. Because that means taking a slot from real work,
`POST /simulation/start` returns `409` when real transfers are running, naming
them, and the caller must pass `confirm_busy` to proceed.

**Leftovers.** `purge_leftovers()` runs at startup, before the sync engine looks
for unfinished runs (`app.py`), so a simulation interrupted by a restart cannot
leave rows stuck as running, runs for the engine's restart recovery to raise
alerts about, or fixture files on disk.

**Restarting a simulated transfer keeps the sandbox's rules.** A restart is its
own kind of sync, `restart`, whatever it retries, but its run carries the
simulation flag from the transfer row, and the engine reads the flag rather
than the kind: the safety check is skipped with the simulation's reason, Tell
is skipped too, and a failure opens no alert. The copy itself stays local - the
transfer row still says it is a simulation. Fixed 2026-10-05: before, the
restart ran the dry run against the media server with the sandbox's source
path, and its result was announced on Discord as "Manual Sync (restart)".
Pinned by `tests/test_sync_engine.py`
(`test_a_restarted_simulation_skips_the_dry_run`,
`test_a_restarted_simulation_is_not_announced`).

## 5. Lifecycle

```text
start   -> generate fixtures under .simulations/<sim id>/source/
        -> create a webhook notification per transfer
        -> engine.submit(kind='simulation', wait=True) per transfer
             Receive, Identify      recorded, marked as a simulation
             Batch, Ready, Safety   skipped, each with its reason
             Queue                  coordinator.start_transfer(), is_simulation=True
        -> queue decides: running, QUEUED_SLOT, or QUEUED_PATH
run     -> real rsync, local paths, held to bwlimit
        -> real monitor loop: progress parsing, log collapsing, socket events
finish  -> the run's Finish stage marks the notification; Tell is skipped
stop    -> cancels anything still moving, keeps the rows to read
cleanup -> deletes is_simulation transfers, notifications and sync runs,
           and the .simulations directory
```

A simulation's own id (`sim_...`) names its folder. Each of its transfers also
has a sync run (`run_...`), so a rehearsal can be read stage by stage like any
other sync — in its transfer's detail on Transfers, where it carries a
Simulation kind badge. A restart of a simulated transfer is a Restart with a
**Rehearsal** badge. Once cleanup deletes the runs, the sync panel reads "No
such sync" for them.

## 6. Tests

`tests/test_simulation_service.py` pins the guards rather than the happy path,
because this code deletes files and runs in production: paths outside the
simulation root are refused, cleanup removes only flagged rows, every scenario
stays inside the size ceiling, and real transfers are never mistaken for
simulated ones.

Not covered: the sync-engine side. Those tests give the service a mocked
coordinator, so neither a `simulation` run nor its deletion at cleanup
(`SyncRunStore.delete_simulation_runs`) is exercised there.
`tests/test_sync_engine.py` covers only a restarted simulated transfer (the two
tests above), not a `simulation` run itself.

## Related

- [../../reference/test-mode.md](../../reference/test-mode.md) — why simulations stay safe despite being exempt from the dry run
- [../sync-engine/README.md](../sync-engine/README.md) — the pipeline a simulation runs through, and the stages it skips
- [../transfers/README.md](../transfers/README.md) — the transfer side a simulation exercises
- [../queue/README.md](../queue/README.md) — the admission rules the scenarios test
- [../notifications/README.md](../notifications/README.md) — why rehearsals are not announced
