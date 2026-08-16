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
3. **Two one-click answers**: update the allowed address and reinstall, or switch
   to password-only access.

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

The answer is cached briefly so a batch of queued transfers asks once rather than
once each. The Settings panel does not poll — each status read opens an SSH
connection and asks the server, which costs seconds on a long link, for a value
that changes when somebody presses a button.

## 8. Data

One column, on `transfers`:

| Column | Values | Meaning |
| --- | --- | --- |
| `transport` | `daemon`, `ssh`, `NULL` | Which route ran. `NULL` for runs predating the choice, and for simulations, which never leave this machine. |

Written when rsync starts, because the answer depends on what was true at that
moment — whether the server was up and would accept us — and cannot be
reconstructed afterwards. Without it, a transfer that fell back to the slow route
and one that never had a faster option look identical: both simply slow.

Shown as a **Fast** badge on the transfers list (only for the fast route — badging
every SSH transfer would be noise, and the badge's absence is what tells you a
transfer fell back) and named in full on the transfer detail, which is where
someone asks why a transfer took as long as it did.

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
- **No live failover.** A server that dies part-way through fails that transfer;
  the retry re-checks and normally picks SSH. Because both routes are the same
  rsync writing into the same partial directory, the retry resumes rather than
  starting over.
- **The backup area is on a different disk from the media**, so every displaced
  file is copied between disks rather than renamed. Pre-existing and unrelated to
  the route, but it costs minutes on a large film. See
  `../../plans/fast-transport.md` §7.9.

## Related

- [`../../plans/fast-transport.md`](../../plans/fast-transport.md) — the
  measurements, the options considered, and what is still planned
- [`../transfers/README.md`](../transfers/README.md) — the transfer pipeline this
  plugs into
- [`../explore/README.md`](../explore/README.md) — plans that carry an explicit
  file list, which take the same route
- [`../settings/README.md`](../settings/README.md) — where these settings live
  and why
