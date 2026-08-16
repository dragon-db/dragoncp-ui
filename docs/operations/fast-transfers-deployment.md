# Deploying fast transfers to production

Last updated: 2026-08-16

Getting the fast transfer route onto the production instance without breaking
the transfers that already work.

The whole thing is reversible at every step, and the slow route keeps working
throughout — that is the point of the design, and it is what makes this safe to
do on a normal evening rather than at 3am.

## Before you start: the one thing that will bite

**Only ONE instance may own the transfer server on the media host.**

The remote install location is fixed: `~/.dragoncp/` and one service named
`dragoncp-rsyncd.service`. Two instances installing means the second overwrites
the first — the configuration, the service definition, and the password.

Each instance generates its own password in `dragoncp_rsyncd.secret`. Whoever
installed last set the password on the remote host, so the other instance's
stored password no longer matches. Its transfers then fall back to SSH and its
panel reports **"not accepting our password"**.

Nothing is damaged by this and nothing is lost. It is simply confusing to
diagnose if you are not expecting it.

**Decide now, and the rest of this document assumes production wins:**

| | What to do |
| --- | --- |
| **Production owns it** *(recommended)* | Follow this guide. Then either turn the fast route off in development, or copy production's `dragoncp_rsyncd.secret` into the development checkout so both hold the same one. |
| Development keeps it | Do not install from production. Leave `FAST_TRANSPORT_ENABLED` off there. |

Copying the secret is enough to make both work, because a password is only
generated when the file is missing — with the same file, either instance
installs the same password.

## What production looks like today

Confirmed on 2026-08-16, so you are not guessing:

- Runs from `/home/dragondb/dragondev/dragoncp-ui` on `main`, as
  `dragoncp-ui.service` under gunicorn.
- Its database has **600 transfers** and **no `transport` column** yet — the
  migration adds it on the next start.
- Its environment file has **neither** of the two new keys.
- **Auto-sync is on** for movies, series and anime, so a webhook can start a
  transfer at any moment, including in the middle of a deployment.
- Its backup area is still the SSD. Development has been moved to the media
  disk; production has not. That is a separate piece of work — see
  `../plans/backups-on-one-disk.md` — and nothing here depends on it.

## The deployment

`deploy.sh` already does the general part: snapshot the database, build the
React app, run the test suite, restart the service, check it answers. A failing
step aborts before the restart, so a bad build never reaches production.

Only the steps around it are specific to this feature.

### 1. Merge, and check nothing is running

```bash
cd /home/dragondb/dragondev/dragoncp-ui
git fetch origin && git log --oneline -1 origin/main
```

Then confirm the queue is empty on the Transfers page — nothing running, queued
or pending. A transfer that starts during the restart is interrupted and has to
be restarted afterwards.

Auto-sync is on, so this is a window, not a guarantee. If a webhook lands
mid-deploy the transfer fails and can be started again from the Transfers page;
nothing is lost.

### 2. Add the two settings

```bash
cd /home/dragondb/dragondev/dragoncp-ui
cp dragoncp_env.env dragoncp_env.env.bak-before-fast-transfers
```

Then add to `dragoncp_env.env`:

```
RSYNC_DAEMON_PORT="52314"
RSYNC_DAEMON_ALLOWED_IP="<your fixed address>"
```

Both instances run on the same machine, so the address is the one already in the
development environment file. Copy it from there rather than looking it up.

The port must match what is installed on the remote host. If development
installed on 52314, production must use 52314 as well.

### 3. Pull and deploy

```bash
git pull origin main
./deploy.sh
```

`deploy.sh` snapshots the database first, so the `transport` column migration
has a copy to go back to. The migration itself is additive — a new column on
`transfers`, nothing rewritten.

If the test suite fails, the deployment stops before the restart and production
is untouched.

### 4. Check the panel before turning anything on

Settings → **Connections** → Fast transfers.

At this point the fast route is **off** and nothing has changed about how
transfers run. What you are checking is that production can see the remote host:

- "Detect my address" returns the address you put in the environment file.
- Status reports the transfer server as installed and answering, if development
  installed it and you copied the secret. Otherwise press **Install**.

If you press Install here, production takes ownership of the remote server and
development's password stops matching. That is the decision from the top of this
document.

### 5. Turn it on, and watch one transfer

Switch **"Use it for transfers"** on.

Then start one transfer by hand — a single season or a film, not a whole
library. Watch for:

- a green **Fast** badge on the transfer,
- a speed around **30 MB/s** rather than 10,
- the file arriving, and the transfer finishing as `completed`.

If the badge is absent, the transfer went over SSH. That is the fallback
working, not a failure. The panel says why.

### 6. Leave it for a day before trusting it

Let the normal webhook-driven transfers run overnight and check the Transfers
page in the morning. Look for the badge on the runs you did not start yourself,
and for anything that failed.

## Rolling back

In increasing order of severity. The first one covers almost everything.

| Problem | What to do | Effect |
| --- | --- | --- |
| Transfers are slow, wrong, or you want to stop | Switch **"Use it for transfers"** off | Immediate. Next transfer uses SSH. No restart |
| The remote server is misbehaving | Press **Stop**, or **Remove** | Removes everything it put on the media host |
| The release itself is bad | `git checkout <previous commit> && ./deploy.sh` | Back to the previous release |
| The database migration is suspect | Restore the snapshot `deploy.sh` took, then redeploy | The column is additive, so this should never be needed |

**The switch is the real rollback.** It is a database setting, read when a
transfer chooses its route, so turning it off takes effect on the next transfer
with no restart and no deployment.

## What can go wrong, and what it looks like

| Symptom | Cause | Fix |
| --- | --- | --- |
| Panel: "not accepting our password" | The other instance installed last and set a different password | Copy one `dragoncp_rsyncd.secret` to the other checkout, then **Install** |
| Panel: "comes from a different address than the one it allows" | Your fixed address changed | Update `RSYNC_DAEMON_ALLOWED_IP`, restart, **Install**. Or switch to password-only and **Install** |
| Transfers run but never show the Fast badge | The route is off, or the server is not answering | The panel's summary line says which |
| Panel: "settings are older than the ones here" | A setting was changed but not applied | Press **Install** |
| Install reports the port is still open | The server would not stop after installing | Press **Stop**. It is set to run only during transfers |

None of these stops transfers. Every one of them falls back to SSH.

## What this does not change

Worth stating, because it is what makes the rollback cheap:

- The rsync command, its flags, its output, and the progress figures.
- Backups: still `--backup-dir`, still nothing deleted outright.
- The queue, path conflicts, pause and resume.
- Where the backup area lives on production — still the SSD.
- Explore, webhooks and the dry-run safety checks, other than which address they
  use.

## Related

- [`../features/fast-transfers/README.md`](../features/fast-transfers/README.md)
  — how the feature works, the security model, and the known gaps
- [`../plans/fast-transport.md`](../plans/fast-transport.md) — the measurements
  and why SSH was the limit
- [`runtime-and-deployment.md`](runtime-and-deployment.md) — the general
  production runtime
- [`../plans/backups-on-one-disk.md`](../plans/backups-on-one-disk.md) — the
  separate backup-disk work production has not had yet
