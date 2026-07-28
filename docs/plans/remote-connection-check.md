# Remote Connection Check (Planned — Not Implemented)

## 1. Purpose

Give an admin a way to answer "is the link to the server healthy, and how fast
is it right now?" without starting a real media sync.

This is a planning document only. No code for this exists yet.

## 2. Why it is separate from the simulation tool

The simulation tool (`services/simulation_service.py`) already runs the real
transfer pipeline against local fixture files. It covers queueing, webhook
status handling, rsync, progress parsing and the UI.

What it deliberately does not cover is the network:

1. SSH authentication and the host-key policy.
2. Real throughput to the remote server.
3. Remote filesystem reachability and permissions.

These are different questions with a different failure mode, so they belong in a
separate tool rather than being folded into a scenario. Conflating them would
make the simulation slower and less safe, and the connection check less direct.

## 3. Priority and sequencing

Not a P0 item.

This is intended to be picked up alongside the **native transfer client** work —
the planned replacement that establishes its own connection to the server
instead of shelling out to rsync. A connection check written against rsync-over-
SSH would largely have to be rewritten once that lands, so building it first
would be wasted effort.

Sequencing:

1. Native client design and implementation.
2. Connection check built on that client's transport.
3. Retire or adapt whatever rsync-specific pieces remain.

If the check is ever needed sooner, section 4 stands on its own against the
current rsync/SSH transport.

## 4. Safety rules (the hard part)

The check has to write to the remote server and then remove what it wrote. Two
risks dominate, and the design exists mainly to contain them.

### 4.1 Never write anywhere near media

1. A dedicated remote probe directory, set explicitly in configuration
   (for example `REMOTE_PROBE_PATH`). No default that writes to the server.
2. Validate at runtime that the probe path is not inside `MOVIE_PATH`,
   `TVSHOW_PATH` or `ANIME_PATH`, and refuse to run if it is.
3. Default suggestion is a path under the remote user's home, which is outside
   any library root.
4. Never a media extension. Use something no scanner looks at, such as
   `.dragoncp-probe`. Radarr, Sonarr and Jellyfin then have no reason to index
   it even if the path were wrong.

### 4.2 Never delete anything the check did not create

1. Create a uniquely named directory per run.
2. Record the exact filenames and sizes written.
3. Before deleting, list the directory and confirm it contains only those files.
   Abort and report if anything else is present.
4. Delete that directory only — never a recursive delete of a path the run did
   not create.
5. Verify afterwards that it is gone. If removal fails, surface the full remote
   path loudly so an admin can remove it by hand. Never fail silently.

### 4.3 Other limits

1. Small probe size (roughly 10–50 MB), configurable, with a hard ceiling.
2. A hard timeout on every remote step.
3. Off unless the probe path is configured. No implicit remote writes.

## 5. What it measures

Real transfers pull from the server, so the download direction is the one worth
reporting.

1. Upload a probe file to the probe directory (setup cost, timed).
2. Copy it back down and time that. This is the figure to report.
3. Remove the probe under the rules in section 4.2.

Report: SSH handshake time, host-key policy in effect, upload throughput,
download throughput, and whether cleanup succeeded.

## 6. Open questions

1. Should the check reuse the transfer queue, or run outside it? It is short and
   diagnostic, so outside is probably right — unlike simulations, it is not
   trying to exercise queueing.
2. Should results be kept for trend history, or shown once and discarded?
3. Does the native client change what "connection health" even means here
   (multiplexed streams, resumable chunks), and does that change what is worth
   measuring?
