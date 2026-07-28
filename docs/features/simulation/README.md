# Transfer Simulation

Runs the real transfer pipeline against throwaway files generated on this
machine, so an admin can watch queueing, webhook status handling and the UI
behave without touching media or the remote server.

Implementation: `services/simulation_service.py`, `routes/simulation.py`,
`frontend/src/components/transfers/simulation-panel.tsx`.

## 1. Why it is not a mock

The previous tool (`simulator.py`, removed) wrote invented progress lines
straight to the database. It exercised none of the code a real transfer runs:
not rsync, not the command construction, not the progress parser, not the
monitor loop, not the queue. It had drifted far enough that pause and resume
needed a `transfer_id.startswith('sim_')` special case in the coordinator to
work at all.

A simulation now generates fixture files and hands them to
`TransferCoordinator.start_transfer()` - the same entry point a webhook or a
manual sync uses. Everything after that is the production path:

- duplicate-destination detection and path queueing
- slot queueing and promotion
- rsync itself, and the command that is built for it
- progress parsing, log collapsing, the socket events
- pause, resume, stop, restart, completion handling
- webhook notification status tracking

The only difference is that rsync is pointed at local paths instead of over SSH,
and held to a speed limit so a copy takes long enough to watch. That branch is a
single `if is_simulation` in `TransferService.start_rsync_process`.

## 2. What it does not cover

The network. SSH authentication, the host-key policy, real throughput to the
remote server and remote filesystem reachability are all bypassed, because the
copy never leaves this machine.

That is deliberate: it is a different question with a different failure mode.
See `../../plans/remote-connection-check.md`, which is parked until the native
transfer client work.

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
how long it runs. A scenario with `with_webhooks` also creates notification rows
and drives the real trigger path, which is what exercises the
`QUEUED_SLOT`/`QUEUED_PATH` status handling described in
`../queue/README.md`.

## 4. Safety

Simulations are intended to be runnable in production, so the guards matter.

**Files.** Everything is generated under `.simulations/` inside the app
directory. `_assert_inside_root` resolves any path and refuses it if it falls
outside that root, and it is called before anything is written *or deleted*.
Media paths are never read or written.

**Rows.** Every transfer and notification created is flagged `is_simulation`.
Cleanup deletes by that flag only, so genuine history cannot be caught by it.

**Size.** `MAX_TOTAL_MB` caps what a scenario may generate, counting both copies
because the fixtures and the destination coexist on disk. Free space is checked
before starting.

**The queue.** Simulations share the real queue, which is the only way queueing
can genuinely be observed. Because that means taking a slot from real work,
`POST /simulation/start` returns `409` when real transfers are running, naming
them, and the caller must pass `confirm_busy` to proceed.

**Leftovers.** `purge_leftovers()` runs at startup, so a simulation interrupted
by a restart cannot leave rows stuck as running or fixture files on disk.

## 5. Lifecycle

```text
start   -> generate fixtures under .simulations/<run_id>/source/
        -> create webhook notifications (if the scenario asks for them)
        -> coordinator.start_transfer() per transfer, is_simulation=True
        -> queue decides: running, QUEUED_SLOT, or QUEUED_PATH
run     -> real rsync, local paths, held to bwlimit
        -> real monitor loop: progress parsing, log collapsing, socket events
stop    -> cancels anything still moving, keeps the rows to read
cleanup -> deletes is_simulation rows and the .simulations directory
```

## 6. Tests

`tests/test_simulation_service.py` pins the guards rather than the happy path,
because this code deletes files and runs in production: paths outside the
simulation root are refused, cleanup removes only flagged rows, every scenario
stays inside the size ceiling, and real transfers are never mistaken for
simulated ones.
