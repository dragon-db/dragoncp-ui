# Activity and Attribution

Every consequential action in DragonCP is recorded against whoever is answerable for it — a signed-in administrator, or a named piece of automation. The Activity screen reads that record back, filterable by person, by kind of action, and by outcome. Ownership is also stamped onto the things people ask about directly: a sync says who started it, a restored backup says who put it back.

Reads are deliberately not recorded. Browsing the library is nobody's business to answer for, and recording it would bury the actions that matter.

Last updated: 2026-08-06
Primary files: `activity_log.py`, `actor.py`, `models/activity.py`, `routes/activity.py`, `frontend/src/components/pages/activity.tsx`

## Where it lives

| Concern | File |
| --- | --- |
| The one call the app makes to record something | `activity_log.py` |
| Who is responsible, and how that is resolved | `actor.py` |
| The table, the action vocabulary, and querying | `models/activity.py` |
| Reading the trail over HTTP | `routes/activity.py` |
| The Activity screen | `frontend/src/components/pages/activity.tsx` |
| The person-versus-automation badge | `frontend/src/components/activity/actor-badge.tsx` |
| Ownership stamped on a run | `models/transfer.py` |
| Ownership stamped on a restore | `services/backups/service.py` |

## How it works

### Three kinds of actor

Everything that happens has an actor, and an actor is one of three kinds:

| Kind | Shown as | When |
| --- | --- | --- |
| `admin` | the person's own username | a signed-in administrator made a request |
| `automated` | `AUTO / <name>` | a named background process: `auto-sync`, `webhook-movies`, `webhook-series`, `webhook-anime`, `webhook-rename`, `retention` |
| `system` | `AUTO / system` | nobody could be established |

`system` is not a fallback that means "nobody did it" — it means **nobody was identified**. That distinction is the point: an entry that cannot name a responsible party says so, rather than guessing or leaving a blank that reads as innocent.

Usernames may not begin with `auto` or `system` (enforced in `models/admin_account.py`), so a person can never be mistaken for automation in the actor column. The badge in the UI is the other half of that rule.

### The actor is ambient, not passed around

`activity_log.record()` normally takes no actor. It resolves one, in order of how specific the answer is:

1. `g.current_actor` — the signed-in administrator, put there by `require_auth`
2. a thread declaration made with `acting_as(...)`
3. `system`

This is why adding a new recorded action does not mean threading an actor parameter down through the service layer, and why the ordinary call site cannot get attribution wrong: there is nothing to get wrong.

There is an `actor=` override, used where the responsible party is known but the ambient answer would be absent or wrong — sign-in, which establishes the person before any of the above is set, and the restore worker, which runs on a thread the request does not reach. It is a narrow escape hatch, not the normal path.

Background work declares itself once at its entry point:

```python
with acting_as(AUTO_SYNC_SCHEDULER):
    coordinator.start_transfer(...)
```

Declarations nest and unwind, including when the work raises — otherwise the next job on that thread would inherit the wrong identity.

The webhook receivers are a special case: they run inside a request but nobody is signed in, so each sets `g.current_actor` for the whole handler. That covers not just storing the notification but the sync it may start automatically, which is the part that would otherwise look anonymous.

### One choke point for run ownership

`Transfer.create()` resolves the actor itself. Every path that starts a run funnels through it — the manual one, the webhook receivers, the scheduler, Explore, simulation — so all of them are stamped without each having to remember. A caller that knows better can pass `started_by` explicitly.

Restore is stamped where `restored_at` is written, for the same reason: "who put this back" is asked while looking at the version history, and restore is the one action that overwrites the live library.

Both store three columns rather than one. `*_account_id` is the stable identity that survives a rename; `*_name` is the name as it read at the time; `*_kind` separates a person from automation without having to recognise names. A rename therefore does not rewrite history, and old entries stay traceable to the person they belong to.

### Recording never breaks the work

`record()` catches everything. A restore that happened is a fact whether or not the trail caught it, and turning a bookkeeping failure into a failed request would be the wrong trade. Failures go to the log.

For the same reason, the store being unset (tests, any context without a database) makes recording a silent no-op rather than an error.

### The vocabulary is closed

`models/activity.py:ACTIONS` lists every action the application records, with a human label. Keeping it closed means the Activity screen can offer the full set as filters, and a typo at a call site shows up as an unknown action rather than quietly creating a category nobody filters by. A test scans production Python sources and asserts that every literal action passed to `record()` is declared.

## Behaviour worth knowing

- **The trail starts empty.** Nothing before this feature was recorded, because nothing was capturing it. Existing transfers and backups show their owner as "not recorded" — unknown, rather than nobody. Backfilling was deliberately not attempted: inventing an owner for past actions is exactly the kind of false confidence an audit trail exists to prevent.
- **Entries are never edited or deleted by the application.** There is no endpoint that writes to the trail and none that removes an entry. An audit record you can alter from the console it audits is not worth keeping. The table grows until someone prunes it on the server.
- **A failed sign-in is recorded as `system`, not as the account named.** Nobody has proved they are that person; putting their name in the actor column would attribute a stranger's guess to them. The attempted username is in the summary and `target_label`.
- **Automatic retention names itself.** It runs on the transfer pipeline's thread after a capture is added, and declares `AUTO / retention` rather than inheriting whoever started the sync — otherwise deleting old backups would be attributed to whoever happened to trigger the run that preceded it.
- **A queued run keeps its original starter.** Promotion out of the queue does not re-attribute it; the person who asked for it is still the answer.
- **`request_ip` honours one proxy hop** via `X-Forwarded-For`, the same as the sign-in throttle. Behind the Vite dev proxy that header is not set, so dev entries all show the proxy's address.
- **Simulation runs are attributed to the person who started them**, and there is deliberately no `AUTO / simulation` actor. A person clicked the button, so the person is the honest answer; the rows are already flagged `is_simulation` for telling them apart. For the same reason there is no `AUTO / queue`: promotion does not begin anything, and the run it releases already carries whoever asked for it. A name in the closed set that nothing can produce would offer a filter that always comes back empty.
- **A rename is attributed to `AUTO / webhook-rename`,** even though it arrives on the series or anime endpoint. It is its own kind of automated work with its own failure modes, and naming it separately is what lets the trail answer "what has the rename path been doing" without wading through ordinary syncs.
- **The deprecated backup compatibility endpoints record too.** `/backups/<id>/restore`, `/backups/<id>/delete` and `/backups/reindex` remain for the React cutover soak and do the same work as their current counterparts; their entries carry `legacy_endpoint: true` so compatibility traffic can be identified before those routes are removed.
- **Previews, plans and dry runs are not recorded**, because they change nothing: the backup and retention previews, the Explore plan and dry run, the media and notification dry runs, and the legacy config reset (which is a no-op that returns a message). Token refresh is not recorded either — it is not a user action, and every refresh would be noise.
- **Timestamps are UTC**, written by SQLite's `CURRENT_TIMESTAMP` without a zone marker. The API accepts ISO-8601 `since` and `until` values, normalises offsets to UTC and converts them to SQLite's `YYYY-MM-DD HH:MM:SS` comparison shape. Invalid timestamps return `400`. The UI appends `Z` before parsing stored values.

## Where it shows in the UI

| Screen | What it shows |
| --- | --- |
| **Activity** | The whole trail, filterable by person, action family and outcome, with search and paging |
| **Transfers list** | "by <name>" on each row, as text — this line is for scanning, and a coloured pill per row would compete with the status |
| **Transfer detail** | "Started by" as a badge, placed first, because when something has gone wrong in the library that is the question being asked |
| **Backups version list** | Who restored a version, beside the Restored mark |

Rows that predate attribution show "not recorded" on the detail, and simply omit
the fact in the list — better a missing fact than an invented one.

## Data

One table, `activity`, documented column by column in [../../reference/database-schema.md](../../reference/database-schema.md). Plus three columns on `transfers` (`started_by_*`) and three on `backup_capture` (`restored_by_*`).

## API

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/activity` | access token |
| GET | `/api/activity/for/<target_type>/<target_id>` | access token |
| GET | `/api/activity/filters` | access token |

All read-only. Filters on `/api/activity`: `actor`, `actor_kind`, `account_id`, `action`, `group`, `target_type`, `target_id`, `outcome`, `since`, `until`, `search`, `limit`, `offset` — all optional, combined with AND.

## Related

- [../auth/README.md](../auth/README.md) — how the signed-in identity is established in the first place
- [../../operations/admin-accounts.md](../../operations/admin-accounts.md) — accounts, and why they are disabled rather than deleted
- [../../reference/database-schema.md](../../reference/database-schema.md) — the `activity` table
