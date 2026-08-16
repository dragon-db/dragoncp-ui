# Fast Transport: getting past the transfer speed ceiling

Last updated: 2026-08-13
Status: **built and in use.** Steps 1–3 of section 7.5 are done: install and
control, route selection, and transfers actually taking the faster route.
Current behaviour is documented in
[`../features/fast-transfers/README.md`](../features/fast-transfers/README.md);
this document is kept for the measurements and the options that were rejected.

> **End to end on the real library, 2026-08-13.** A transfer started through the
> normal pipeline chose the fast route on its own, ran at **29.6 MB/s**, recorded
> `transport=daemon`, and the transfer server switched itself off when the queue
> emptied. A separate 902 MB file pulled over the same route came back
> **md5-identical** to the copy on the media host, at 30.5 MB/s.

> **Measured against the real library on 2026-08-13.** A 10.1 GB film pulled
> over the installed transfer server arrived complete and byte-exact at
> **34.8 MB/s**, against 10.7 MB/s over SSH — 3.25×, and better than the
> synthetic figures in section 1 predicted. The same file takes about sixteen
> minutes over SSH and took four minutes fifty.
>
> Install, status, start, stop, password rotation and removal were all exercised
> against the real host. Removal was verified independently: nothing left in the
> home directory, no service known to the supervisor, nothing listening on the
> port, and the six other applications on that machine untouched.
>
> The fallback in section 7.7 was exercised rather than assumed. With the server
> told to allow an address that was no longer ours, the panel reported *"Running,
> but this connection now comes from a different address than the one it allows"*
> and the pre-transfer check refused the fast route — so transfers would fall
> back to SSH rather than fail. Switching to password-only recovered it in one
> step, and a deliberately wrong password was correctly told apart from a
> refused address.

## 1. Summary — the cause is not what we thought

Transfers run at 10–15 MB/s on a link capable of 30–40. The working assumption
was an ISP-imposed cap on SSH.

**Measured on 2026-08-10, that is not what is happening. There is no cap on
SSH.** The ceiling is SSH's own internal flow control interacting with a
154 ms round trip, and it is entirely self-inflicted.

The evidence, all taken back-to-back against the real server:

| What was measured | Throughput |
| --- | --- |
| One rsync over SSH — **what we do today** | **10.7 MB/s** |
| One raw SSH stream, no rsync involved | 10.8 MB/s |
| One SSH stream, forced to `aes128-gcm` | 11.4 MB/s |
| One SSH stream, forced to `chacha20-poly1305` | 10.3 MB/s |
| One SSH stream, forced to `aes128-ctr` | 11.3 MB/s |
| Four rsyncs over SSH at once | 28.9 MB/s combined |
| Four raw SSH streams at once | 29.5 MB/s combined |
| **One plain HTTP stream, no SSH** | **29.5 MB/s** |
| Four plain HTTP streams at once | 33.9 MB/s combined |
| One file pulled as 8 parallel byte ranges over HTTP | 30.6 MB/s |
| **One rsync over rsync's own daemon, no SSH** | **26.9 MB/s** |
| Three rsyncs over the daemon at once | 32.4 MB/s combined |

Read the three bolded rows together. The same file, the same machines, the same
minutes: 10.7 MB/s through SSH, 29.5 MB/s without it. **The network was never
the limit.** The real ceiling of the link is around 33 MB/s and a single
non-SSH connection already reaches it.

### 1.1 Why SSH does this

SSH allows only about 2 MB of data to be in flight on a channel before it stops
and waits to be told the other end has consumed it. Over a 154 ms round trip
that is a hard ceiling of roughly 13 MB/s no matter how fast the line is:

    2 MiB ÷ 0.154 s ≈ 13.6 MB/s theoretical, 10.7 MB/s measured after overhead

This has nothing to do with the ISP and nothing to do with rsync. It is a
constant in OpenSSH that cannot be configured from either end. It is why the ISP
found nothing when asked — from their side there is genuinely nothing there.

Three findings rule out every other candidate:

- **Not rsync.** A raw SSH stream with rsync completely out of the picture gives
  the same 10.8 MB/s.
- **Not encryption or a slow remote CPU.** Three ciphers with very different
  costs all land within 1 MB/s of each other, and the remote is a 128-core EPYC
  with hardware AES. This was the risk that would have killed the whole plan,
  and it is dead.
- **Not a per-host cap.** Four streams give four times one stream. Nothing is
  limiting the account or the address.

### 1.2 What this changes about the plan

The original proposal — a custom Python agent on the remote server doing
transfers over its own tunnels — **would work, but it is not needed to fix the
speed.** Anything that is not SSH already reaches the line rate, including
rsync's own daemon mode, which needs no new software written at all.

The measurements also killed the case for the most complicated part of the idea:
splitting one file across many parallel connections. One plain connection gets
29.5 MB/s and eight parallel ranges of the same file get 30.6. **There is
nothing left for parallelism to win.**

The agent is still worth building, but for different reasons — encryption,
manageability and library listings — and as a later phase, not as the fix.

## 2. The environment, as measured

Recorded so nobody has to rediscover it.

**The link:** 154 ms round trip, extremely stable (0.4 ms deviation, no packet
loss over 10 probes). Real ceiling about 33 MB/s. Local TCP buffers are large
enough for this distance; the remote's are larger still. TCP itself is not a
limit at any speed we care about.

**The remote server:** Debian 11, AMD EPYC 7702P, 128 cores, hardware AES
present, 503 GB RAM, 8.5 TB free on the media volume. OpenSSH 8.4, rsync 3.2.3,
Python 3.9.2. `screen`, `tmux` and `cron` all available.

**Three things that make the agent idea viable when it is wanted:**

1. **Arbitrary high ports are reachable from the internet.** Verified by binding
   listeners on the remote and connecting to them from here. The firewall is not
   in the way.
2. **Background processes survive logout and reboot.** The account has user-level
   service support enabled, so the agent can be a proper managed service rather
   than a shell trick — and can still be started on demand from a button here.
3. **Python 3.9 is present**, which is enough for a dependency-free agent. Worth
   noting the agent's ceiling was measured, not guessed: the throughput test above
   was served by a plain Python 3.9 standard-library HTTP server, and it saturated
   the link.

**One caution.** The test used ports in the 52308–52309 range, which were free at
the time. Before committing to a port, pick one from the range the hosting
provider has actually allocated to the account — several are already in use by
other applications on that box.

## 3. What we already have that this reuses

The hard part is already built. Explore does exactly the planning work the
proposal describes:

- Both libraries are read and turned into a flat list of every file with its
  size and modification time.
- The two sides are compared into a plan — what arrives, what is replaced, what
  is removed.
- That plan is put in front of the real rsync with `--dry-run` and an itemised
  output format, and rsync's answer is parsed back and held against the plan.
  Disagreements become warnings the operator sees before approving.
- On approval, everything being replaced or removed is moved into backup
  staging *first*, then a literal file list is written, then rsync is handed that
  list and nothing else.

So an approved plan is already a concrete instruction set, and **nothing about
it is rsync-specific**. Whatever moves the bytes only has to consume the list.
We are not building a sync engine and never need to.

The gap: the webhook and manual paths do not produce such a list. They hand
rsync a whole directory and let it decide. Their safety check is also much
weaker than Explore's — it compares file counts and refuses if a sync would
delete more than it receives. Moving those paths onto the planner is an upgrade
worth making on its own merits.

## 4. The recommendation

### 4.1 Switch the transfer address to rsync's daemon — 2.5× for a few days' work

rsync does not need SSH. It has a native protocol that speaks straight to a
port, and the daemon runs fine as an unprivileged user with no root, no
installer and no system changes.

**This was tested end to end, including every command shape the application
actually uses**, and the results were:

- Single stream **26.9 MB/s**, versus 10.7 today. Three at once, 32.4 MB/s.
- `--dry-run` with the itemised output format produces **byte-identical output**
  to the SSH path, so the existing parser needs no changes at all.
- `--files-from` works — the Explore path is unaffected.
- `--backup-dir` works — a displaced local file was verified to be preserved
  with its original contents.
- `--delete` works, and the deleted file was verified to land in the backup
  directory rather than being destroyed.
- `--partial-dir`, `--update`, `--size-only`, `--whole-file`, the progress
  output and the statistics block all behave identically.

From the application's point of view this is **a change of address, not a change
of transport**. The same command, the same flags, the same output, the same
parser, the same safety guarantees. Every correctness property rsync gives us
today is preserved because it is still rsync.

The work is: a setting for the daemon address and port, building the source
address in the new form when the daemon is configured and reachable, a
reachability check before each transfer, and falling back to the SSH form when
it is not. Plus the remote-side daemon configuration and a way to start and stop
it from here.

**Two things to decide before this ships.**

*Encryption.* Daemon traffic is not encrypted, and its authentication is a shared
secret with weak hashing. The media is not secret, but the transfer would be
visible in transit and the password should not be treated as strong. Mitigations,
in order of preference: restrict the port to this end's address in the daemon
configuration; keep the module strictly read-only so nothing can be written even
with the secret; and treat the secret as a low-value credential that is rotated
rather than a real one. If encrypted transport is a requirement, that is an
argument for section 4.3, not against this.

*A stable address to allow.* Restricting by source address only works if this end
has a stable public address. If it does not, that mitigation is unavailable and
the read-only module plus the secret are all there is — which is probably still
acceptable for read-only access to media, but it should be a decision rather than
an oversight.

### 4.2 Then let big files use more than one stream — where it still helps

With the daemon in place a single stream already reaches 27 MB/s and the link
tops out near 33, so parallelism is now worth a few MB/s rather than a
multiplier. The queue already runs three transfers at once and Explore already
splits a series into one transfer per season, so most of this exists.

Do it because it is nearly free, not because it is load-bearing. It is no longer
the point.

### 4.3 The custom agent — still worth building, for different reasons

With speed solved, the agent's remaining case is:

- **Encrypted transport** with a certificate we control, replacing a plaintext
  channel and a weak shared secret.
- **The management story the proposal asked for**: knowing it is online, what
  version it runs, pushing a new version from here, restarting it from a button.
  rsync's daemon has none of this — updating it means editing a file over SSH.
- **Native library listings**, which would make Explore noticeably faster and
  remove the remote shell commands entirely.

It was measured to be capable: the throughput test in section 1 was served by a
standard-library Python HTTP server on that exact machine and it saturated the
link. Encryption should be free given hardware AES on both ends, but that should
be measured before committing.

This is now a phase 4 project with a clear and modest justification, not the
centrepiece. Design in section 6.

### 4.4 What the provider offers instead of rclone

rclone is **not** available on this account. The provider offers Syncthing and
Resilio Sync, and neither is the right shape.

Both are continuous two-way mirrors: they exist to keep two folders identical
forever, deciding for themselves what moves and when. This application decides
what to sync, from webhooks and from plans an operator approves, and it keeps a
queue, a history, and a backup of everything it displaces. Handing that to a
mirror would mean giving up the approval step, pulling the entire remote library
rather than the parts we want, and losing the backup and history trail. That is
precisely the sync engine this project deliberately does not build.

They are worth remembering for a different problem — mirroring a folder between
two machines we control — but not for this one.

**If encryption is wanted without building the full agent**, there is a middle
option: a small TLS-terminating proxy in front of the daemon, which the Python
standard library can do in a few dozen lines with no packages to install. It
adds a hop and should be measured before being trusted, but it would close the
encryption gap without owning a transfer protocol. Consider it only if section
7.5's decision goes that way.

### 4.5 What is now off the table

- **Moving traffic off TCP.** This was the last resort for a per-host cap. There
  is no per-host cap. Drop it.
- **Splitting one file across many connections.** Measured to gain nothing.
- **Changing SSH ciphers or tuning.** Measured to gain nothing; the window is not
  configurable.
- **Keeping SSH for bulk transfer at all.** It costs a factor of 2.5 and there is
  no way to fix it from either end.

## 5. What changes in this application

### 5.1 A transport is a thing that can be chosen

Today the transfer service *is* the rsync-over-SSH coupling — building the
command, starting the process, tracking its process id, killing that id to pause
or cancel, and looking for it again after a restart.

For the daemon switch, three of those four are untouched, because it is still an
rsync process. Only the address changes. That is what makes it cheap and it is
why it should go first.

The larger refactor — a transport with a small interface behind which either
rsync or an agent can sit — should still happen, but it is now phase 3 and it is
justified by the agent, not by the speed fix. When it does happen: the monitor
should consume a stream of events rather than reading rsync's output directly,
and the rsync transport becomes the thing that turns rsync's output into those
events. Everything downstream — the stored figures, the live updates, the log
collapsing, the UI — then keeps working untouched.

### 5.2 Choosing an address, and falling back

Before a transfer starts: is the daemon configured, reachable and enabled? If
yes, use it. If anything is no, use SSH exactly as today.

Three rules:

1. **Record the choice on the transfer.** History, restart and after-reboot
   recovery all need to know which route ran.
2. **Decide once, at start.** Re-deciding mid-transfer produces transfers that
   are half one thing and half another.
3. **A mid-transfer daemon failure fails the transfer, and the retry falls back
   to SSH.** No live failover. Because both routes are rsync writing into the
   same partial directory, the retry resumes rather than restarting — which is
   a genuine advantage of doing it this way.

What the operator sees: transfers about two and a half times faster, and a badge
saying which route each took. If the daemon is down, transfers still run at
today's speed and the status panel says why. Nothing ever stops working.

### 5.3 Smaller pieces

- A column on the transfer recording the route, and a badge in the UI.
- Daemon address and port in the environment file with the other
  security-boundary settings; the on/off switch in the database where an
  operator can change it without a restart. The password is in neither — it is
  generated and kept in its own owner-only file.
- A remote status panel: daemon reachable or not, with buttons to start and stop
  it over the existing SSH connection. This is the "manage it from here"
  requirement, and it applies to the daemon just as much as to a custom agent.
- Tests: route selection and fallback, refusal of a path outside the library, and
  a mid-transfer disconnect leaving the library exactly as it was.

### 5.4 What this unblocks elsewhere

The on-demand "is the link healthy and how fast is it right now" check
(`remote-connection-check.md`) is parked waiting for this work. Once a route can
be asked to probe, that check is a small addition — and its awkward part, writing
a probe file to the remote and deleting it safely, disappears entirely if the
probe reads rather than writes.

## 6. Design for the agent, when it is wanted

Kept from the original plan, now scoped to phase 4.

**Two channels.** The agent dials *out* to this application and holds the
connection open with a heartbeat — that is what makes the status indicator
instant and honest rather than a timeout, and it is the channel for telling the
agent to update itself. Bulk data flows the other way, this application
connecting to the agent's port.

**Read-only, deliberately.** Version one answers four questions: who are you and
what version; what is in this library; what do you know about this file; give me
these bytes. No write endpoint, no delete endpoint, no way to name a command. It
cannot modify the library, so a compromise of it is a read of media and nothing
worse. Everything destructive stays here, where the path validation and backup
machinery already live.

**Standard library only.** No third-party packages on a machine where we cannot
install anything system-wide, and no build step. Measured to be enough: a
standard-library threaded server saturated the link.

**Access control.** Encryption with a certificate this application generates and
pins — we control both ends, so pinning is stronger than a public certificate and
needs no renewal story. A token on every request, in the environment file, never
in the database and never sent to the browser. The agent refuses any path that
does not resolve inside its configured library roots. Every path that comes back
is re-validated here before anything is written.

**Correctness — what rsync gives us that we would have to re-earn.** Nothing is
written directly into the library: every file lands in a temporary file on the
same filesystem as its destination and is renamed into place only when complete
and size-verified, so a crash leaves the old file intact rather than a truncated
new one. Nothing is ever deleted, only moved into backup staging, exactly as
Explore does today, so the existing backup sorter indexes it and the Backups page
can restore it. Content hashing is available but off by default — reading every
byte twice to guard against a risk that encryption already covers is not worth
the cost until we see a bad file.

**Managing it from here.** Upload a new version into a versioned directory, point
a link at it, tell the agent to restart through the control channel, keep the
previous version, and put the link back automatically if the new one does not
reconnect within a timeout. An update that bricks the agent must never require a
hand fix on a machine we do not have root on. The account supports user-level
services that survive reboot, so supervision is straightforward.

## 7. Implementation plan

### 7.1 What gets installed on the remote, and who owns it

Everything this application puts on that server lives in exactly two places:

- `~/.dragoncp/` — the daemon configuration, its secret, and its log, pid and
  lock files.
- `~/.config/systemd/user/dragoncp-rsyncd.service` — the service definition.

Both are generated **here**, from the configured settings, and pushed over the
SSH connection that already exists. Nothing is edited by hand on the server, so
what is installed always matches what this application believes is installed —
and it can say so when the two drift apart.

Port **52314**, from the allocated range, with **52315** held back in case a
control agent is ever built.

Three modules, one per library, each rooted at its configured remote path and
each strictly **read only**. No module is ever rooted at the home directory. The
daemon runs as the normal user without the isolation option that needs root.

**Keeping it alive is systemd's job, not ours.** The service is declared to
restart on failure and to start at boot, and the account already permits user
services that survive logout — verified, along with the fact that user services
respond correctly over a non-interactive connection, which is how this
application will drive them. Every other application on that box is run exactly
this way.

That is the honest answer to "a lightweight process that keeps rsync running":
it already exists, it is what the rest of the server uses, and it is better than
anything we would write. A supervisor of our own would need a supervisor.

### 7.2 Controlling it from here

A new remote-control service, driving the existing SSH connection:

- **Install** — render the configuration and the service definition from current
  settings, upload both, reload, enable, start, and confirm by connecting to the
  port.
- **Start / Stop / Restart.**
- **Status** — is the port answering, is the service running, which libraries are
  published, and does what is installed still match what we would generate now.
- **Uninstall** — stop, disable, remove the service definition and the directory.
  Written at the same time as install, not bolted on later.

Health is answered by connecting to the rsync port and asking it to list its
libraries. That is a direct question about the thing we actually depend on rather
than asking something else whether it thinks that thing is up. It costs one round
trip, and the answer is held briefly so a burst of queued transfers does not
re-ask for every one.

### 7.3 Choosing the route, and falling back

Before a transfer starts: is the fast route enabled, installed, and answering? If
yes, use it. If anything is no, use SSH exactly as today.

If the port is not answering and the operator has allowed it, make **one**
bounded attempt to start the service, re-check, and proceed either way. That
covers "if it's down, start it" without letting a dead server turn every transfer
into a long wait.

The chosen route is recorded on the transfer, because history, restart and
after-reboot recovery all need to know which one ran. The choice is made once, at
the start — never re-decided mid-transfer.

A failure part-way through fails that transfer, and the retry re-checks and will
normally pick SSH. Because both routes are the same rsync writing into the same
partial directory, the retry **resumes** rather than starting over.

### 7.4 The changes here

The source address is built in three places today — the main transfer, the
Explore transfer (which its dry run also uses), and the webhook safety dry run.
All three get the same treatment: when the fast route is chosen, the address
takes the daemon form, the SSH option is dropped, and a password file is passed
instead. **Every other flag stays exactly as it is**, which is the whole reason
this is cheap and safe: the command, the output, the parser, the progress
figures, the backups and the deletions are unchanged.

Around that:

- A column recording the route, and a badge on the transfer so an operator can
  see at a glance which one ran.
- Connection details in the environment file with the other security settings —
  port, user, secret, and optionally the address allowed to connect. The on/off
  switch and the auto-start toggle go in the database, where they can be changed
  without a restart.
- A remote panel in Settings: a status light, the port, what is published, when
  it was last checked, and buttons to install, start, stop, restart and remove.
- Tests: mapping a library path to its published address, refusing a path that
  is not under any configured library, choosing correctly and falling back when
  the port is dead, the exact command shape for both routes in all three places,
  and refusing to run with a world-readable secret.

### 7.5 Order of work

1. **Install and control, with nothing using it yet.** The panel can install,
   start, stop, report status and uninstall. Entirely reversible and testable on
   its own, and it touches no transfer.
2. **Route selection and command building, behind a switch that starts off.**
   Verified against a real transfer before anyone depends on it.
3. **Turn it on.** Watch a few real transfers, confirm the speed and that
   backups and deletions still behave, then make it the default.
4. **Prove the fallback before relying on it** — deliberately break the address
   restriction and confirm transfers keep running over SSH, the alert appears,
   and both one-click answers work. A fallback that has never been exercised is
   not a fallback.

Steps 1 and 2 are independently useful and independently safe. Nothing in step 1
can affect a transfer, and step 2 cannot affect one until step 3.

### 7.6 Access control

This end has a fixed address, so the transfer server is restricted to it. That
is the strongest protection available here and it costs nothing.

**The address never has to be typed or shared.** The remote server can report
which address a connection arrives from, so this application can ask it "what do
you see me as?" and fill the value in itself. Verified working. Typing it by hand
stays available for anyone who prefers it.

It is held in the environment file — already excluded from version control —
and marked so the Settings page never sends it to the browser, not even in a
masked form. It ends up in exactly two places: that file, and the transfer
server's configuration on the remote. It never appears in a transfer command, a
transfer log, a notification, or anything that reaches a browser or a repository.

The remote copy sits in a directory this application creates as owner-only,
inside a home directory that was verified to be closed to the eight other
accounts on that machine.

**Four independent layers, not one.** Losing any single one still leaves the
library closed:

1. **Address restriction** — everything refused by default, with only the one
   address allowed.
2. **A password** that this application generates as a long random value rather
   than letting anyone choose a weak one, kept owner-readable only, and
   rotatable from the panel with one click.
3. **Read-only publication** — nothing can be written, replaced or deleted
   through it regardless of who connects.
4. **Not discoverable** — the libraries are not listed to anyone who has not
   authenticated, so a port scan learns nothing about what is there.

Refused connection attempts are surfaced in the panel, so anyone probing the
port is visible rather than silent.

**It is only listening while it is needed.** Because this application already
has to be able to start and stop it, the default is to start it when a transfer
needs it and stop it when the queue empties. That costs about a second per batch
and takes the exposure window from permanent down to the small fraction of the
day transfers actually run. Leaving it running permanently stays available as a
setting.

### 7.7 The fallback, for when the address changes

The address is fixed today, but plans change and ISPs change them for you. The
design assumes it will break eventually.

**Three modes, one switch:**

- **Restricted** — address plus password. The default.
- **Password only** — no address restriction, for when the fixed address is gone.
- **Off** — the fast route disabled entirely; everything runs over SSH as it does
  today.

**What happens automatically when the address stops matching.** This application
periodically asks the remote what address it sees, and compares. On a mismatch it:

1. **Keeps transfers working.** They fall back to SSH immediately and run at
   today's speed. Nothing stops, nothing fails, nothing needs attention to keep
   the library up to date.
2. **Says exactly what happened** — that the address changed, what it is now, and
   that transfers are running on the slower route until it is resolved.
3. **Offers two one-click answers**: update the restriction to the current
   address, or switch to password-only.

**It never downgrades itself.** Dropping the address restriction is always a
deliberate human action, because a system that quietly weakens its own security
to keep working is worse than one that tells you it is slow.

The switch is applied over the SSH connection, not through the transfer server,
so it works even when the transfer server is unreachable — which is exactly the
situation where it is needed.

**Away from home**, the same thing happens: the address will not match, transfers
run over SSH, and nothing breaks.

### 7.8 If encryption is later wanted

Traffic on the fast route is not encrypted. With the port answering only one
address, and publishing only read-only media, the practical exposure is small.

If that changes — the address restriction is lost, or encryption becomes a
requirement — section 4.4's small encrypting layer is the next step, and the
custom agent after that. Neither is needed now.

### 7.9 Separately: the backup disk

Found while checking this: the backup and partial-file location is on a different
disk from the media. Every file a transfer displaces is therefore **copied**
between disks rather than renamed instantly, and every paused transfer copies its
partial file across and back again on resume. On a large film that is minutes of
disk work and a large amount of writing that buys nothing.

This is happening today and is not caused by anything in this plan. It is worth
fixing on its own — putting the partial and backup staging area on the same disk
as the media would make both operations instant — and it should be its own piece
of work rather than folded in here.

## 8. Risks

| Risk | Consequence | Mitigation |
| --- | --- | --- |
| Daemon traffic is unencrypted | Media visible in transit | Restricted to one address, read-only, and only listening during transfers. Section 7.8 if that changes |
| The fixed address is lost or changes | Fast route stops working | Detected automatically; transfers fall back to SSH and keep running; two one-click answers offered. Never downgrades itself — section 7.7 |
| The address leaks into a log, a notification or the repository | Exposes something the operator treats as private | Held only in the excluded environment file and the remote configuration; never in a command, log, notification or browser response. Covered by a test |
| Port collides with the provider's allocation | Daemon fails to bind, or displaces another app | Use a port from the account's allocated range |
| Daemon stops and nobody notices | Transfers silently drop back to 10 MB/s | Phase 2 status panel; record the route on every transfer so the drop is visible |
| Provider disallows a long-running listener | Approach unavailable | Confirm against the hosting terms before building |
| Two routes diverge over time | The fallback quietly stops being equivalent | Both routes are the same rsync command with a different address — keep it that way |

## 9. Questions, answered and outstanding

Answered on 2026-08-10:

- **Which ports are available?** 52314–52349 are allocated and unused. The plan
  takes 52314 and reserves 52315.
- **Can user services be controlled from here?** Yes. The user service manager
  responds over a non-interactive connection, the account keeps services running
  after logout, and every other application on that server is run this way.
- **Is rclone an option?** No — not available on this account. Syncthing and
  Resilio Sync are offered instead, and both are the wrong shape (section 4.4).
- **Is the backup area on the same disk as the media?** No. See section 7.7.

- **Does this end have a fixed public address?** Yes. The fast route is
  restricted to it, and section 7.7 covers losing it.
- **Is that home directory exposed to the other accounts on the shared machine?**
  No. It is owner-and-group only, and other accounts' homes were confirmed
  unreadable from it, so an owner-only password file there is safe.
- **Can the address be discovered rather than typed?** Yes — the remote reports
  the address a connection arrives from.

Still outstanding:

1. Do the hosting terms permit a long-running listener? Worth a glance; the
   account already runs six of them, so this is close to certain.
2. Should a control agent, if ever built, serve library listings too? It would
   make Explore faster and remove the remote shell commands — but it would also
   make it load-bearing for browsing rather than just for speed, which weakens
   the fallback story.

## Appendix: reproducing the measurements

Everything in section 1 was measured against the live server on 2026-08-10 using
four 512 MiB files of random data in a temporary directory on the remote, pulled
to a temporary directory here. The rsync daemon and the test HTTP server were run
as the normal user on unprivileged ports, both were stopped afterwards, and the
temporary directories on both ends were removed. Nothing was written outside
those directories and no media file was touched.

Worth re-running if the hosting provider moves the server, since the entire
diagnosis turns on the round-trip time.
