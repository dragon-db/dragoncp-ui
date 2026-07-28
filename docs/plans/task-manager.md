# In-App Task Manager (Planned — Not Implemented)

A lightweight task tracker built into DragonCP, for tracking work on the project
itself rather than media transfers.

This is a planning document. No code for it exists — an initial implementation
was started and backed out to keep the current branch scoped to the transfers
page. The interim tracker is [`TASKS.md`](../../TASKS.md) at the repository root.

## 1. The problem

Work on this project is spread across separate AI agent conversations that share
no memory. Each new session starts blind: it cannot answer what is in flight,
how far along it is, what was decided and why, or where the last session
stopped. Today the only record is the git log and whatever the operator
remembers, which makes multi-session features unreliable to carry forward.

A task list solves this only if both the human and the agent write to it. That
constraint drives most of the design below.

## 2. What it is not

Not a project management tool. No sprints, estimates, burndown or assignment
between people — there are one to three operators. The single job is: a fresh
agent reads one thing and knows where the work stands.

## 3. Data model

Three tables, deliberately separate from the media tables.

### `task`

| Column | Purpose |
|---|---|
| `task_key` | `TASK-001`. Short and quotable, so "carry on with TASK-014" resolves |
| `title` | One line |
| `description` | The durable plan. Edited deliberately |
| `status` | `backlog`, `planned`, `in_progress`, `blocked`, `done`, `cancelled` |
| `priority` | `low`, `medium`, `high`, `urgent` |
| `tags` | JSON array, for filtering |
| `doc_refs` | JSON array of paths into `docs/`, so a task points at its own reference material |
| `branch` | The git branch the work lives on |
| `assignee` | Who or what is working it |
| `blocked_reason` | Set alongside `status = blocked` |
| `created_at`, `updated_at`, `started_at`, `completed_at` | `updated_at` is what makes a stale in-progress task visible as stale |

### `task_step`

A checklist under a task: `position`, `text`, `done`, `completed_at`.

Progress should be countable. "3 of 7 steps" is information; a status word that
has said *in progress* for a week is not.

### `task_note`

Append-only activity log: `author`, `kind`, `body`, `created_at`.

`kind` is one of `progress`, `decision`, `blocker`, `handoff`, `note`.

## 4. The two rules that matter

**The plan and the log are separate.** `description` is edited; notes are only
ever appended. Several agents touch the same task without ever seeing each
other, and an agent that can only append cannot destroy what a previous one
wrote. This is the single most important property of the design.

**`handoff` is a first-class note kind.** It records where a session stopped and
what comes next. It is what the next session reads first, and it is the thing
that actually closes the context gap.

## 5. How an agent uses it

The reliability of this depends entirely on the interface being trivial to call.
An agent in a shell that has to obtain a JWT and construct an authenticated
request will skip the step. So the agent-facing path is a CLI that talks to the
database directly:

```
scripts/task.py briefing              # what is in flight, and the last handoff on each
scripts/task.py show TASK-007
scripts/task.py new "Title" --priority high --tag frontend --doc docs/features/x/README.md
scripts/task.py start TASK-007
scripts/task.py note TASK-007 --kind progress "..."
scripts/task.py note TASK-007 --kind handoff "stopped at X; next is Y"
scripts/task.py step TASK-007 --done 3
scripts/task.py done TASK-007
```

`briefing` is the first call of a session and must stay cheap: live tasks, step
counts, and one note each — not every task's full history.

The same operations are exposed over HTTP for the UI (`/api/tasks`, with
`/api/tasks/briefing` mirroring the CLI's briefing).

## 6. The UI

A **Tasks** section in the sidebar, built on the existing page primitives —
`PageHeader`, `PageTabsList`, `StatTiles`, `SectionCard`, and rows that expand
in place, matching the transfers and webhooks pages.

- Tabs: **Active** (live work), **Backlog**, **Done**
- Tiles: in progress, blocked, backlog, done this week
- Row: key, title, priority, tags, step progress, last-updated
- Expanded: the plan, the checklist with tickable steps, the activity log
  newest-first with handoffs marked, and links to any referenced docs
- Create/edit form: title, description, priority, tags, doc references, steps

Filtering by tag and status, since tags are the mechanism for grouping work
across a feature.

## 7. Making agents actually use it

A tracker nobody writes to is worse than none, because it looks authoritative
while being stale. `AGENTS.md` needs an explicit, short contract:

1. Before starting work, run `scripts/task.py briefing`.
2. If the work matches an existing task, use it. Otherwise create one.
3. Mark it `in_progress` when starting.
4. Record decisions as they are made, not at the end.
5. Before finishing, leave a `handoff` note saying where things stopped and what
   is next.
6. Point `doc_refs` at the relevant documentation rather than restating it.

Rule 5 is the one that pays for the whole system.

## 8. Open questions

1. Should completing a task be able to require that its steps are all ticked, or
   is that friction that will be worked around?
2. Should tasks link to git commits or branches automatically, or is the
   `branch` field enough?
3. Does the interim `TASKS.md` survive alongside the database, or is it migrated
   in and retired? Two sources of truth for the same thing is the failure mode
   to avoid.
4. Should the briefing surface tasks that are `in_progress` but untouched for
   some number of days as a separate "possibly abandoned" group?

## 9. Related

- [`TASKS.md`](../../TASKS.md) — the interim tracker this replaces
- [Database schema](../reference/database-schema.md) — where these tables would be documented
- [API reference](../reference/api.md) — where the endpoints would be documented
- [Frontend reference](../reference/frontend.md) — the page primitives the UI would reuse
