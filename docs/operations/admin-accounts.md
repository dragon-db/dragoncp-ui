# Administrator Accounts

Last updated: 2026-08-03
Primary files: `scripts/manage_admins.py`, `models/admin_account.py`, `auth.py`, `login_guard.py`, `routes/auth.py`

## Purpose

Who is allowed to sign in to the DragonCP web interface, and how that list is maintained.

**Short answer to "how do I add an administrator?"** — on the server, from the project checkout:

```bash
venv/bin/python scripts/manage_admins.py add <username>
```

It prompts for a password twice. The change is live immediately; the application does not need restarting.

---

## The model in one paragraph

Accounts live in the `admin_account` table in `dragoncp.db`. Every account has the same powers — there is one role, `admin`, and nothing in the application reads it. Accounts are created, renamed, disabled and reset **only** from `scripts/manage_admins.py`, run on the server. The only account change available in the browser is a signed-in person changing their own password. While the database holds no account that can sign in, the `DRAGONCP_USERNAME` / `DRAGONCP_PASSWORD` credentials in `dragoncp_env.env` are accepted as a single fallback administrator, exactly as they were before named accounts existed.

## Why there is no account-management screen

The right to create administrators is the right to reach the server. That boundary already exists, it is stronger than anything the browser could enforce, and duplicating it as a "super admin" role in the UI would mean a role column checked on every account action, a management screen, and a family of edge cases — cannot demote yourself, cannot remove the last super admin, what an ordinary admin sees on a page they may not use — for a task performed a few times a year.

So the privilege boundary is left where it already was, and the script is the interface to it.

---

## `scripts/manage_admins.py`

Run from the project checkout, using the project virtualenv (the script imports application code, so a bare system Python will usually fail on it):

```bash
venv/bin/python scripts/manage_admins.py <command> [...]
```

Every command accepts `--db <path>` to act on a database other than `./dragoncp.db`.

| Command | What it does |
| --- | --- |
| `list` | Every account: name, enabled or disabled, last sign-in, whether a password change is still owed. |
| `show <username>` | The same detail for one account, including ids and timestamps. |
| `add <username>` | Create an account. Add `--disabled` when the password has to travel to someone. |
| `rename <old> <new>` | Change a username, keeping the account's id and history. |
| `reset <username>` | Set a new password for someone locked out. |
| `disable <username>` | Stop an account signing in, immediately. |
| `enable <username>` | Let a disabled account sign in again. |

There is deliberately **no delete command**. See [Why accounts are never deleted](#why-accounts-are-never-deleted).

### Password options

`add` and `reset` share three flags:

| Flag | Effect |
| --- | --- |
| *(none)* | Prompt for the password twice, hidden. The normal path. |
| `--random` | Generate a strong password and print it once. Use when handing credentials to someone else. |
| `--password <value>` | Set it directly. Avoid on a shared machine — it lands in shell history and the process list. |
| `--no-force-change` | Do not require a password change at first sign-in. |
| `--disabled` *(add only)* | Create the account switched off, so the password does nothing until `enable` runs. See [Handing a password to someone else](#handing-a-password-to-someone-else). |

By default a new or reset password is marked **must change at next sign-in**, because it was chosen by whoever ran the script rather than by the person who will use it.

That requirement is enforced on the server, not just in the browser. Until the password is replaced, every protected endpoint answers `403 PASSWORD_CHANGE_REQUIRED`; only signing out, reading your own identity, and changing the password itself are reachable. The reasoning is attribution: an account still on a handed-over password is a credential two people know, so nothing done under it is unambiguously that person's. `--no-force-change` skips this when it is not wanted.

Passwords must be at least 10 characters (`MIN_PASSWORD_LENGTH` in `models/admin_account.py`) and are stored as `pbkdf2:sha256` hashes.

### Username rules

Three to thirty-two characters, starting with a letter, containing only letters, digits, dots, dashes and underscores. Matching ignores case, so `Alice` and `alice` are the same account and cannot both exist.

Names starting with `auto` or `system` are refused. Automated activity is labelled `AUTO / <name>` (see [Automated actors](#automated-actors)), and a person called `autosync` sitting in the same column would make the record unreadable.

### Handing a password to someone else

A password chosen here has to travel to the person who will use it, and on the way
it is visible to whatever carried it: terminal scrollback, a chat message, a
ticket, an AI assistant's transcript. The first-time password change limits the
damage — the credential dies the moment the real person uses it — but only if
they get there first. Whoever uses it first sets the password and owns the
account.

**Create the account switched off, and turn it on at the moment of handover:**

```bash
venv/bin/python scripts/manage_admins.py add priya --random --disabled
#  ...contact Priya, confirm she is ready to sign in...
venv/bin/python scripts/manage_admins.py enable priya
```

Until `enable` runs the password does nothing, so the window in which a password
seen in passing could be used shrinks from however long the account sits
unclaimed to the handover itself.

Afterwards, check it went to the right person:

```bash
venv/bin/python scripts/manage_admins.py show priya
```

`last sign-in` reports when the account was first used. A time you did not
expect means somebody got there first — `reset` and start again.

### Can an AI assistant create accounts?

Yes, with the sequence above. The reasoning is worth stating plainly, because
the intuitive answer is the wrong one.

Creating an account is not the privilege boundary. Anything that can run this
script already has shell access to the server, and with that it can read
`JWT_SECRET_KEY` out of the environment file and mint a valid session for any
account without touching the script at all. It can also write to the account
table directly. If an assistant is trusted with a shell on this machine, account
creation is already inside that trust; blocking one script buys nothing.

What *is* genuinely new is the transcript. A person typing at a hidden prompt
leaves the password nowhere. An assistant cannot type at a hidden prompt — it
has to pass `--password` on the command line or read the output of `--random`,
so the password enters a conversation that may be stored, logged, or sent to a
model provider. `--disabled` is the answer: the leaked value is inert until you
enable the account, which you do when the person is in front of you.

Two remaining caveats worth holding in mind:

- **Nothing records who authorised the account.** The activity trail records what
  accounts do, not how they came to exist. An account an assistant created looks
  identical to one you asked for.
- **Keep account creation to sessions you are driving.** If an assistant ever
  processes content it did not get from you — a webhook payload, a file name, a
  web page — hostile text in there could try to talk it into creating an account.
  That risk is specific to assistants rather than people, and it is why an
  unattended or scheduled run is the wrong place for this command.

### Common tasks

```bash
# Add a colleague and hand over a generated password, safely
venv/bin/python scripts/manage_admins.py add priya --random --disabled
venv/bin/python scripts/manage_admins.py enable priya   # when they are ready

# Same, when you will type the password yourself at a prompt
venv/bin/python scripts/manage_admins.py add priya

# See who exists
venv/bin/python scripts/manage_admins.py list

# They forgot their password
venv/bin/python scripts/manage_admins.py reset priya

# They changed their name
venv/bin/python scripts/manage_admins.py rename priya priya.n

# They left the team
venv/bin/python scripts/manage_admins.py disable priya.n

# They came back
venv/bin/python scripts/manage_admins.py enable priya.n
```

---

## Sessions end when the account changes

Every sign-in token carries the account's `token_version`. Every authenticated request reads the account row and compares it. Bumping that number retires every token already issued for the account.

It is bumped by `disable`, `reset`, `rename`, and by a person changing their own password.

| Action | Effect on someone already signed in |
| --- | --- |
| `disable` | Next request fails with `ACCOUNT_DISABLED`. Their live-updates connection is dropped within about a minute. |
| `reset` | Next request fails with `SESSION_REVOKED`. |
| `rename` | Next request fails with `SESSION_REVOKED`; they sign in again under the new name. |
| `enable` | Nothing — their old password still works. Use `reset` if it should change too. |
| Self-service password change | Every *other* session for that account ends. The browser that made the change is handed a replacement token and stays signed in. |

This is what makes "we removed their access" true at the moment you run the command, rather than true within a day. The account row is read fresh on each request with no cache, the same way application settings are read.

Live connections are covered too: the account is re-checked on the client's activity ping, throttled to once a minute (`AUTH_RECHECK_SECONDS` in `websocket.py`), and again by the connection cleanup sweep for connections that have gone quiet.

## Why accounts are never deleted

The activity trail refers back to these rows. Removing one would turn recorded history into references to nobody — the exact failure the accountability work exists to prevent.

`disable` is the answer instead: the account cannot sign in, its sessions end immediately, and everything it did still reads correctly. `rename` exists for the same reason: it keeps the account's `id`, so renaming someone preserves their history where deleting and recreating would orphan it.

---

## The fallback account

While **no enabled account exists in the database**, sign-in falls back to `DRAGONCP_USERNAME` and `DRAGONCP_PASSWORD` (or `DRAGONCP_PASSWORD_HASH`) from `dragoncp_env.env`.

That single rule covers three situations:

- **A fresh install.** Nothing has been set up yet; the environment credentials work as they always did.
- **An upgrade** from the single-operator setup. Nothing changes until the first account is added.
- **A lockout.** If every account is disabled or the last password is lost, the environment credentials work again — no hand-editing of the database.

Adding or enabling the first account switches the fallback off, and any session opened against it stops validating at that moment. That handover is intended: it is what stops a stale fallback session outliving the introduction of real accounts.

A fallback session cannot change its password through the browser — there is no stored password to change. The application says so and points at this script.

Startup logs which mode is in force. With no accounts you will see:

```
No administrator accounts exist in the database. Sign-in is using the fallback
credentials from the environment file. Create real accounts with:
venv/bin/python scripts/manage_admins.py add <username>
```

---

## Sign-in throttling

Failed sign-ins are counted two ways at once, in memory (`login_guard.py`):

- **by address** — catches one source working through passwords
- **by username** — catches a distributed attempt against one known account

Either hitting the limit locks further attempts for the cooldown, and a locked caller never reaches the password check at all, so a correct password during a cooldown still fails. A successful sign-in clears both counters. Restarting the application clears all of them.

| Setting | Default | Meaning |
| --- | --- | --- |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failures within the window before locking |
| `LOGIN_WINDOW_MINUTES` | `15` | How long failures are remembered |
| `LOGIN_LOCKOUT_MINUTES` | `15` | How long a lock lasts |

Set them in `dragoncp_env.env`. The attempt that trips the limit answers `429` with `retry_after` in seconds, rather than answering "wrong password" and leaving the person to discover the lockout on their next try.

The username counter is a deliberate trade-off: someone who knows a colleague's username can lock that person out for the cooldown. For a small administrative console that is the right way round — a brief denial is recoverable, a guessed password is not.

Behind a reverse proxy the address is taken from the first entry of `X-Forwarded-For`, falling back to the socket address. Without that, the proxy would be every caller's address and one attacker would lock out the whole installation.

---

## Automated actors

Most of what this application does is not started by a person: download-manager webhooks queue syncs, the scheduler batches seasons, retention prunes old restore points, simulations create their own traffic. `actor.py` gives all of it a name so none of it is recorded as anonymous.

Every action has an actor, and an actor is one of three kinds:

| Kind | Shown as | Example |
| --- | --- | --- |
| `admin` | the person's own username | `priya` |
| `automated` | `AUTO / <name>` | `AUTO / auto-sync`, `AUTO / webhook-movies`, `AUTO / retention` |
| `system` | `AUTO / system` | the application itself, outside any request or job |

The named automation is a closed set in `actor.py` (`AUTO_SYNC_SCHEDULER`, `AUTO_WEBHOOK_MOVIES`, `AUTO_WEBHOOK_SERIES`, `AUTO_WEBHOOK_ANIME`, `AUTO_WEBHOOK_RENAME`, `AUTO_RETENTION`, `AUTO_SIMULATION`, `AUTO_QUEUE`), so the trail can be filtered by it rather than by free text.

Inside an authenticated request the actor is on `g.current_actor`, put there by `require_auth`. Background code passes an explicit automated actor instead.

**Phase 1 establishes this vocabulary and resolves the actor for every request. Writing it onto a stored activity trail is phase 2.**

---

## Where things live

| Concern | File |
| --- | --- |
| The account table | `models/database.py` (`admin_account`), `models/admin_account.py` |
| Creating, renaming, disabling, resetting | `scripts/manage_admins.py` |
| Credential check, tokens, per-request account check | `auth.py` |
| Sign-in, refresh, self-service password change | `routes/auth.py` |
| Sign-in throttling | `login_guard.py` |
| Actor vocabulary | `actor.py` |
| Live-connection re-checks | `websocket.py` |
| Browser session state | `frontend/src/stores/auth.ts` |
| Password screens | `frontend/src/components/auth/`, `frontend/src/components/settings/account-panel.tsx` |

## See also

- [`../features/auth/README.md`](../features/auth/README.md) — how sign-in works end to end
- [`../reference/database-schema.md`](../reference/database-schema.md) — the `admin_account` columns
- [`maintenance-scripts.md`](maintenance-scripts.md) — the other hand-run scripts
