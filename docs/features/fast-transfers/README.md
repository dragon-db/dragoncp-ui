# Fast Transfers

Pulls media over a small transfer server installed on the media host instead of
over SSH, which is about three times faster on this link. Every transfer decides
for itself which route to take and falls back to SSH whenever the faster one is
not available, so nothing stops working when it is off, broken or uninstalled.

Implementation: `services/remote_daemon/`, `services/transfer_service.py`
(`resolve_route`), `routes/remote_daemon.py`,
`frontend/src/components/settings/remote-transfer-panel.tsx`.

Measured against the production library: **34.8 MB/s versus 10.7 MB/s**, on a
10.1 GB file that arrived byte-identical. Sixteen minutes became four minutes
fifty.

## 1. Why SSH was the problem

The link can do about 33 MB/s. Transfers sat at 10–15. The assumption was an
ISP cap on SSH; it was not.

SSH allows only about 2 MB of data in flight on a channel before it stops and
waits to be told the other end has consumed it. The media host is 154 ms away.
Two megabytes divided by 154 milliseconds is roughly 13 MB/s, and no amount of
bandwidth changes it. It is a constant inside OpenSSH that neither end can
configure.

Everything else was ruled out by measurement:

| Measured, back to back | Throughput |
| --- | --- |
| One rsync over SSH | 10.7 MB/s |
| One raw SSH stream, no rsync | 10.8 MB/s |
| SSH forced to three different ciphers | 10.3 – 11.4 MB/s |
| Four SSH streams at once | 28.9 MB/s combined |
| **One plain connection, no SSH** | **29.5 MB/s** |
| One rsync over the transfer server | 26.9 MB/s |

Not rsync — a bare SSH stream is just as slow. Not encryption or a weak remote
CPU — three very different ciphers land within 1 MB/s of each other, on a
128-core machine with hardware AES. Not a cap on the account — four streams give
four times one stream.

Full workings, and the options that were rejected, in
[`../../plans/fast-transport.md`](../../plans/fast-transport.md).

## 2. What actually changed

**A change of address, not a change of transport.** The fast route is still
rsync, still the same command, still the same flags. Only two things differ:

| | SSH route | Fast route |
| --- | --- | --- |
| Source | `user@host:/absolute/path/` | `dragoncp@host::library/path/` |
| Extra arguments | `-e "ssh …"` | `--port=…  --password-file …` |

Everything else — `--delete`, `--backup-dir`, `--partial`, `--files-from`, the
progress output, the `--stats` block, the itemised dry-run format — is byte for
byte identical. That is why this was a small change and why none of the safety
behaviour needed re-proving: the backups, the deletions, the queue, the progress
parser and the dry-run reconciliation do not know which route ran.

`tests/test_transfer_routing.py` compares the two commands flag by flag, so a
future edit that adds something to one route and not the other fails the build.

**One exception, since October 2026: an Explore file list.** On the fast route
the list is read from the library root, and each line is marked where the
plan's folder starts — `Example Show/./Season 01/<file>` against
`dragoncp@host::tvshows/` rather than `Season 01/<file>` against
`dragoncp@host::tvshows/Example Show/`. rsync names a file by what follows the
`/./`, so it lands in the same place and a dry run prints the same name. The
approved list is untouched; the fast-route copy is written beside it as
`<list>.fast-route.txt`. Why: [§12](#12-what-broke-in-august-2026).

## 3. Choosing a route

Decided in `TransferService.resolve_route()`, which every launch path goes
through — a first start, a promotion from the queue, and a restart.

**Asked at the moment rsync is about to run, not when a transfer is queued.** A
transfer can wait hours in the queue, and whether the fast route is available is
only worth knowing at the moment it is used.

**Decided once.** Re-deciding mid-transfer would produce transfers that are half
one thing and half another.

The fast route is used only when all of these hold:

1. "Use it for transfers" is on.
2. A port and, in restricted mode, an allowed address are configured.
3. A password has been generated.
4. The source path resolves inside a published library. A path that cannot be
   placed gets no route — failing closed, because a path we cannot place is one
   we should not be inventing an address for.
5. The server is running, or could be started, and will serve us.

Anything else falls back to SSH, silently and by design. The Settings panel
explains why the fast route is unavailable; a transfer's job is to run. Even an
unexpected error while checking falls back rather than failing — the difference
between "slower tonight" and "the library stopped updating".

A simulation never asks at all: it copies fixture files on this machine and
never touches the media host.

### When the fast route fails during a copy

Choosing the route only covers a server that is down **before** a copy starts.
A copy that then fails on it — the server dies, the connection drops, or the
server refuses the files as in [§12](#12-what-broke-in-august-2026) — runs
again **once, over SSH, as the same transfer**: same flags, same backup folder,
same partial folder, so files already copied are skipped and a half-copied one
carries on. It is not retried when rsync was stopped on purpose — pause,
cancel, or a signal (exit 19 or 20). A failure over SSH is final.

The two dry runs (the safety check and Explore's rehearsal) do the same: one
that fails or times out on the fast route is asked again over SSH, so a broken
fast route can slow the library down but cannot block a sync.

A fallback is never silent. The copy's route is recorded as `ssh_fallback`
("SSH (fast route failed)" on the transfer), its log says why in rsync's own
words, the sync's Transfer stage is re-stated, and one **Fast transfers** alert
opens — announced once as `fast_route.failed`, then bumped by every later
fallback instead of messaging again.

## 4. What is on the media host

Two things, and nothing else:

- `~/.dragoncp/` — configuration, password, log, pid and lock files.
- `~/.config/systemd/user/dragoncp-rsyncd.service` — the service definition.

Both are generated **here** and pushed over SSH, so what is installed always
matches what this application believes is installed, and it can say so when the
two drift apart. `services/remote_daemon/layout.py` lists them; `uninstall`
removes exactly that list.

Three libraries are published, one per configured media directory, each locked
to its own folder and each **read only**. The published names (`movies`,
`tvshows`, `anime`) are deliberately not the directory names — a library name
appears in the transfer command and in the server's log, and neither needs to
carry the layout of somebody's disk.

**Keeping it running is systemd's job, not ours.** The service restarts on
failure, and the account permits user services that survive logout. Every other
application on that host is run the same way. A supervisor of our own would need
a supervisor.

## 5. Security

Four independent layers. Losing any one still leaves the library closed.

1. **Address restriction.** In restricted mode the server names one address, and
   rsync refuses everything that does not match — naming one address *is*
   deny-by-default. This also refuses the other accounts on the shared host,
   which is verified by test rather than assumed.
2. **A generated password.** Long, random, never chosen by a person, kept
   owner-only in `dragoncp_rsyncd.secret` (excluded from version control), and
   pushed over SFTP rather than on a command line — a command line is readable
   by every account on the host through `ps`.
3. **Read only.** Nothing can be written, replaced or deleted through this
   channel whatever else goes wrong. Every destructive action stays on this side,
   where path validation and the backup machinery already live.
4. **Not discoverable.** Libraries are not listed to anyone who has not
   authenticated, so a port scan learns that something is there and nothing about
   what.

The allowed address lives in the environment file only. It is never written to
the database, never returned by any endpoint, and never printed to a log —
`config.py` redacts every setting the registry marks sensitive, and anything it
does not recognise, so a setting added later is protected by default.

**On demand by default.** The server is started when a transfer needs it and
stopped when the queue empties, so the port is open for the minutes a day
transfers actually run rather than permanently. Setting it to run always is a
supported choice and a reasonable one — the address restriction is in force
either way.

## 6. When your address changes

This is the failure this feature was designed around, because a fixed address is
a thing ISPs take away.

rsync will not distinguish "you may not see this library" from "it is not there"
— it refuses to confirm that a hidden library exists. That is a good property, so
the probe does not guess. The **service** works it out from what it holds on this
side: whether it published that library, and whether the address the media host
sees us arriving from still matches the one it allows.

What happens, in order:

1. **Transfers keep working.** They fall back to SSH and run at the old speed.
   Nothing fails, nothing needs attention to keep the library up to date.
2. **The panel says exactly what happened** — that the address changed, and that
   transfers are on the slower route until it is resolved.
3. **Two ways back**, and neither is a single click — the change has to be
   pushed to the remote host before it means anything:
   - Put the new address in the environment file, restart the application, and
     press **Install**. Three steps, because the address is a security boundary
     that lives outside the database on purpose.
   - Or switch access to password-only in the panel and press **Install**. Two
     steps, and the one to reach for when the speed matters more than waiting to
     find out what the new address is.

**It never downgrades itself.** Dropping the address restriction is always a
deliberate human action. A system that quietly weakens its own security to keep
working is worse than one that tells you it is slow.

Password-only is meant to be temporary. Left running permanently it is an
internet-reachable port protected by a password alone, using rsync's weak
challenge-response — the address restriction is the real lock.

## 7. Health

Asked with **rsync itself**, not a hand-written conversation over a socket. Two
reasons, both learned against the real server:

- A hand-rolled check cannot authenticate without reimplementing rsync's
  challenge-response, so it named a library and hung up — which the server logged
  as `auth failed`, once per check, before every transfer. The log used to spot
  someone probing the port would have been buried under our own noise.
- A check that is not the thing doing the work can be wrong about it. Same
  client, same password file, same address form as a real transfer, so "the check
  passed" and "a transfer would work" cannot come apart.

Five answers, each needing a different response:

| Answer | Means |
| --- | --- |
| `ready` | Authenticated; a transfer would run |
| `blocked` | Up, and will not serve us — usually the address |
| `auth_failed` | Up, reached, and our password is wrong. Reinstall pushes the current one |
| `unreachable` | Nothing answered |
| `error` | Something else, in rsync's own words |

`blocked` and `auth_failed` never trigger a restart: the server is running
perfectly well and restarting it would throw away what the check established.

**Stopped is not down.** On demand, a healthy server spends most of the day
stopped, so the panel reports that as **Ready. It starts for each transfer and
stops when they finish.** with a green icon (`standing_by` in the status), not as
"Installed but not running" in amber, which is what it said until 2026-10-21. It
counts as ready only when everything the status read can establish over SSH holds:
installed, the service stopped cleanly (not `failed`), settings current, the boot
setting as asked, a password stored and readable, and no sign our address changed.
The one thing a stopped server cannot show is that it accepts our password right
now; each start checks that, and a refusal sends the transfer over SSH. With **Use
it for transfers** off it reads "Installed and stopped" in grey instead. A server
set to run always and found stopped is still amber.

The answer is cached briefly so a batch of queued transfers asks once rather than
once each. The Settings panel does not poll — each status read opens an SSH
connection and asks the server, which costs seconds on a long link, for a value
that changes when somebody presses a button.

## 8. Data

One column, on `transfers`:

| Column | Values | Meaning |
| --- | --- | --- |
| `transport` | `daemon`, `ssh`, `ssh_fallback`, `NULL` | Which route ran. `ssh_fallback`: started on the fast route, failed, finished over SSH. `NULL` for runs predating the choice, and for simulations, which never leave this machine. |

Written when rsync starts, because the answer depends on what was true at that
moment — whether the server was up and would accept us — and cannot be
reconstructed afterwards. Without it, a transfer that fell back to the slow route
and one that never had a faster option look identical: both simply slow.

Shown as a route badge on every row that lists a transfer — the dashboard's
Active Transfers, and the Transfers page's Activity and History: green **Fast**,
blue **SSH**, amber **SSH fallback**. Until 2026-10-14 only the fast route was
badged, so "no badge" could mean SSH, not started yet, or a run from before
routes were recorded; the operator asked to see the route at a glance. A queued
copy still has none — the route is chosen when rsync starts — and neither does a
run from before August 2026. Named in full on the transfer detail, which is where
someone asks why a transfer took as long as it did. On a phone the dashboard
shows the badge under the title, on the path line, so the title keeps its room.

## 9. Settings

| Setting | Store | What it does |
| --- | --- | --- |
| `RSYNC_DAEMON_PORT` | env | The port the server listens on. Use one the host has allocated. |
| `RSYNC_DAEMON_ALLOWED_IP` | env, hidden | The only address permitted to connect. Never sent to a browser, never in the database, never logged. |
| `FAST_TRANSPORT_ENABLED` | database | Whether transfers use it at all. |
| `FAST_TRANSPORT_ACCESS_MODE` | database | `restricted` or `password`. |
| `FAST_TRANSPORT_LIFECYCLE` | database | `on_demand` or `always`. |

The address is in the environment file because a value held in one place can only
leak from one place. The three below it are in the database because they are the
fallback controls: the whole point is that they can be changed from the panel, at
the moment transfers have already dropped to the slow route, without editing a
file on the server and restarting.

**Not all of them take effect the same way**, and the difference matters when
something has gone wrong and you are trying to fix it:

- `FAST_TRANSPORT_ENABLED` applies **immediately** — it is read when a transfer
  chooses its route, so switching it off stops the next transfer using the fast
  route with nothing else to do.
- `FAST_TRANSPORT_ACCESS_MODE` and `FAST_TRANSPORT_LIFECYCLE` are saved
  immediately but describe what gets **generated on the remote host**, so they
  apply on the next **Install**. Switching to password-only and not reinstalling
  changes nothing on the server.
- The environment-file settings need the application restarted as well.

The panel reports when what is installed no longer matches what is configured —
including when its start-at-boot setting has drifted from the lifecycle you
chose.

## 10. Endpoints

All admin-only, all under `/api`. None returns the allowed address; `status`
reports only whether one is set and whether it still matches.

| Endpoint | Does |
| --- | --- |
| `GET /remote-transfer/status` | Configured, installed, running, willing to serve us, up to date |
| `POST /remote-transfer/install` | Generate, push, register, start. Also how a settings change is applied |
| `POST /remote-transfer/start`, `/stop`, `/restart` | Run control |
| `POST /remote-transfer/uninstall` | Stop, unregister, remove everything |
| `POST /remote-transfer/rotate-password` | New password, then reinstall to push it |
| `GET /remote-transfer/detect-address` | What address the media host sees us arriving from |

`detect-address` is deliberately not recorded on the activity screen: it changes
nothing, and this application's rule is that reads are nobody's business to
answer for.

## 11. Known gaps

- **No encryption on the fast route.** The practical exposure is a read-only
  media library behind an address restriction. If encryption becomes a
  requirement, `../../plans/fast-transport.md` §4.4 is the next step.
- **One fallback per copy.** A copy that fails on the fast route runs again
  over SSH once ([§3](#when-the-fast-route-fails-during-a-copy)). A failure
  over SSH is final, as it always was.
- **The remote server's rsync is not ours to choose.** Its provider upgrades
  it. Anything that changes server behaviour again lands on the fallback first;
  the alert is what tells you.
- **The backup area is on a different disk from the media**, so every displaced
  file is copied between disks rather than renamed. Pre-existing and unrelated to
  the route, but it costs minutes on a large film. See
  `../../plans/fast-transport.md` §7.9.

## 12. What broke in August 2026

On 2026-08-20 the remote server moved from Debian 11 to Debian 13, and its rsync
from 3.2.3 to `3.4.1+ds1-5+deb13u4`. That build carries the May 2026 fix for
CVE-2026-29518: a server running with `use chroot = no` — which ours must, the
account has no root — now opens files from the library root instead of trusting
`chdir()`.

It broke one shape of request. A `--files-from` pull whose source is a folder
**inside** the library (`::tvshows/Example Show/`) reports every file as
`file has vanished` and copies nothing (exit 24). A pull of a whole folder, and
a `--files-from` pull from the library root, are unaffected. Only Explore uses
`--files-from`, so only Explore copies failed — normal transfers kept running at
full speed. A dry run never opens a file, so Explore's rehearsal passed and only
the real copy failed.

Reproduced on this machine against Debian's own builds: `deb13u2` (before the
fix) works; `deb13u4`, upstream 3.5.0 and 3.5.1 all fail, with a matching client
too — so it is a server bug, not a version mismatch. No rsync version needs
changing anywhere; §2's exception works on both kinds of server.

To run the tests against a hardened server, extract an rsync binary from the
`.deb` (`dpkg-deb -x`) and point `DRAGONCP_TEST_RSYNC_SERVER` at it:

```bash
DRAGONCP_TEST_RSYNC_SERVER=/path/to/usr/bin/rsync \
  venv/bin/python -m pytest tests/test_transfer_routing.py -k RealServer
```

That run also checks the old command still fails there, so the test keeps
describing a real problem.

## Related

- [`../../plans/fast-transport.md`](../../plans/fast-transport.md) — the
  measurements, the options considered, and what is still planned
- [`../transfers/README.md`](../transfers/README.md) — the transfer pipeline this
  plugs into
- [`../explore/README.md`](../explore/README.md) — plans that carry an explicit
  file list, which take the same route
- [`../settings/README.md`](../settings/README.md) — where these settings live
  and why
