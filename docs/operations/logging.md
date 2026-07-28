# Backend Logging

Last updated: 2026-07-28
Primary files: `logging_setup.py`, `services/sync_logger.py`, `routes/logs.py`

## Purpose

Everything the backend has to say about itself ends up in one file. That
includes normal `logging` calls, every `print()` the application makes, warnings,
and tracebacks from threads that died without catching their own exception. The
log viewer endpoints read that same file, so what an operator sees in the browser
and what they see over SSH is the same text.

## Where The Log File Lives

By default the backend writes to `logs/dragoncp_backend.log`, resolved relative to
the directory that contains `logging_setup.py` - that is, the backend project
root, not the current working directory. The directory is created at startup if
it does not exist. `/logs/` is gitignored, so the file never ends up in a commit.

To put the log somewhere else, set `DRAGONCP_LOG_FILE`. An absolute path is used
as given; a relative path is resolved against the project root, not the working
directory. An empty or unset value falls back to the default.

Both the API routes and the startup banner ask `logging_setup` for the same
resolved path, so there is only ever one answer to "where is the log". At
startup the backend logs the path twice: once from the logging subsystem
("Logging configured at ... (level=...)") and once from the app
("Backend logging file: ..."). Grepping either line is a reliable way to confirm
which file a running instance is actually writing to.

## Rotation And Retention

The file handler rotates on size. Two settings tune it:

- `LOG_MAX_BYTES` - size at which the current file is rolled over. Default
  20 MiB (`20 * 1024 * 1024`).
- `LOG_BACKUP_COUNT` - how many rolled-over files are kept. Default `10`.

So by default the on-disk footprint is the live `dragoncp_backend.log` plus up to
ten numbered siblings (`dragoncp_backend.log.1` through `.10`), on the order of
220 MiB in total. `.1` is the most recently rotated file, `.10` the oldest. A value that is
not a valid integer is ignored and the default is used instead.

Rotation matters when chasing an old incident: the log viewer endpoints only ever
read the live file. Anything already rotated has to be read from disk.

## Levels

`LOG_LEVEL` (default `INFO`) sets the level on the root logger and on both
output handlers, and handler levels are respected, so a record below the
threshold is discarded before it reaches the file. To capture debug output the
value has to be `DEBUG` - there is no per-module override. An unrecognised value
falls back to `INFO`.

Two more switches:

- `LOG_TO_CONSOLE` (default on) also writes every record to the real process
  stdout, which is what systemd or Docker captures. Turning it off leaves the
  file as the only sink.
- `DRAGONCP_REDIRECT_STD_STREAMS` (default on) controls the `print()` capture
  described below. Turning it off means `print()` output goes to the terminal
  and never reaches the log file.

All of these are read once, from the process environment, when logging is
configured at import time. The app loads `dragoncp_env.env` (or `.env`) before
that happens and pushes its keys into the environment without overwriting
anything already set, so these can be written into the env file as well as
exported in the service unit. Boolean settings accept `1`, `true`, `yes` or `on`
as "on"; anything else is off. They are not listed in `dragoncp_env_sample.env`.

Changing any of them requires a restart.

## Record Format

Every record is one line (plus any traceback lines that follow it):

```
2026-07-28 07:04:07 | INFO     | 2602578 | Thread-30 (_monitor_transfer) | dragoncp.services.transfer_service | transfer_service:760 | 🏁 Transfer rehearsal_... completed with return code: 0
```

The fields, left to right: timestamp to the second, level, process id, thread
name, logger name, `module:line` of the call site, and the message. The thread
name is often the most useful column - transfer monitoring, post-completion work
and HTTP requests each run on their own named threads.

Writing is asynchronous. Records are put on an unbounded in-process queue and a
single background thread writes them to the file and console, so a slow disk does
not stall a transfer. The queue is drained and the streams restored on normal
process exit.

Before anything is written, a filter cleans each record: ANSI colour escapes are
stripped, `Authorization: Bearer ...` headers and bare `bearer ...` tokens are
replaced with `<redacted>`, and a `NAME=value` or `NAME: value` pair whose name
contains `SECRET`, `PASSWORD`, `TOKEN`, `API_KEY` or `WEBHOOK` has its value
replaced with `<redacted>`. Note that only the first such pair in a given message
is redacted - a single line carrying two different secrets is not fully covered.
Treat the log as sensitive when sharing it.

## Print Output Is Captured

Most of the transfer, queue and webhook code narrates itself with `print()`
rather than a logger. That output is not lost: stdout and stderr are replaced at
startup with stream objects that feed the logging system, line by line, with
per-thread buffering so concurrent transfers do not interleave mid-line.

Two things happen to each captured line.

**The logger name is inferred from the caller.** The stream walks back up the call
stack to the first frame outside `logging_setup.py` and turns that file's path
into a dotted name - a `print()` in `services/transfer_service.py` is logged as
`dragoncp.services.transfer_service`, exactly as if that module had used a logger.
Frames coming from `venv`, `.venv`, `env`, `.env` or `node_modules` are not
credited this way; those fall back to `dragoncp.stdout` or `dragoncp.stderr`.
That is why third-party chatter (Socket.IO's "emitting event ..." lines, for
example) appears under `dragoncp.stderr` while application output does not.

**The severity is inferred from the text**, not from which stream it came from.
The message is upper-cased and checked in this order:

1. contains `CRITICAL` -> CRITICAL
2. contains `TRACEBACK`, or ` EXCEPTION` (with a leading space), or the ❌
   character -> ERROR
3. contains `ERROR`, `FAILED` or `FAILURE` -> ERROR
4. contains `WARNING`, `WARN` or the ⚠ character -> WARNING
5. contains `DEBUG` -> DEBUG
6. otherwise -> INFO

This is why the codebase's emoji conventions matter operationally: a `print()`
starting with ❌ becomes an ERROR record and shows up in the default log-viewer
filter, while the same message with ✅ stays at INFO. It also means the inference
can be wrong in both directions. Writing to stderr does not make something an
error - Socket.IO's routine stderr chatter is recorded at INFO - and a cheerful
message that happens to contain the word "failed" or "error" will be recorded as
an ERROR. When a log-viewer ERROR list looks implausible, check the message text
before concluding something broke.

Note also that captured lines carry a `module:line` pointing at the `print()`
call site rather than at the logging machinery, which is genuinely useful when
hunting for where a message comes from. A Python traceback printed by application code
that caught its own exception arrives as several `dragoncp.stderr` lines pointing
at `traceback:1050` rather than at the failing code.

## Uncaught Exceptions In Threads

Yes, they are routed to the log. Both the main-thread exception hook and the
thread exception hook are installed at startup, and both log at CRITICAL to the
logger `dragoncp.crash` with the full traceback attached:

- main thread: `Unhandled exception`
- worker thread: `Unhandled exception in thread <thread name>`

`KeyboardInterrupt` is passed through to Python's original handler instead, so
Ctrl-C does not produce a crash record. Python warnings are also captured into
the log rather than printed.

The practical limit is that this only covers exceptions that escape a thread
entirely. Most DragonCP background work catches its own exceptions and prints the
traceback, so those show up through the `print()` capture described above, at
ERROR, under the module that caught them. `grep dragoncp.crash` finds the ones
nobody handled; it is not a complete list of everything that went wrong.

## The Per-Sync Log Format

`services/sync_logger.py` exists so that series and anime syncs can be followed
across the several services that touch them. It emits a single, greppable shape:

```
🎯 [TransferCoordinator] [transfer_id:rehearsal_reh_1785202435_caa5dd_0] > start_transfer() called
📁 [TransferCoordinator] [transfer_id:rehearsal_reh_1785202435_caa5dd_0] >    dest_path: /home/.../slot_0
```

The parts, in order:

- **icon** - an emoji chosen by the caller, defaulting to 📋. Purely visual, but
  the ❌/✅ convention interacts with the severity inference described above for
  ordinary `print()` output.
- **`[service]`** - the component that emitted the line, for example
  `[TransferCoordinator]`, `[WebhookService]`, `[AutoSyncScheduler]`. This is the
  field to use for "who did this", because the `module:line` column is useless
  here: all of these records are emitted from one place and always read
  `sync_logger:50`, under the logger name `dragoncp.services.sync_logger`.
- **`[notification_id:...]` and/or `[transfer_id:...]`** - present only when the
  caller passed them, notification first, transfer second, both bracketed
  separately when both are present. These are always the full, untruncated ids,
  deliberately, so the same string works as a grep pattern and as a database key.
- **`>`** - separator.
- **indent** - three spaces per indent level, used to nest a detail line under the
  step it belongs to (`dest_path:` under `start_transfer() called`).
- **message**.

Records default to INFO. This is worth knowing: a failed validation logged
through the helper gets a ❌ icon but is still an INFO record, so it will not
appear when the log viewer is filtered to ERROR. Filter on the id, not the level,
when investigating a sync.

Three helpers build on the same shape:

- batch logging appends ` (N items)` to the message and, when the batch is five
  notifications or fewer, follows it with one `   - notification_id: <id>` line
  per notification, so every id in the batch stays greppable
- validation logging picks the icon automatically: ✅ when the check passed, ❌
  when it failed
- state-change logging emits `🔄 ... State change: <old> → <new>`

Callers today are the transfer coordinator, the webhook service and the auto-sync
scheduler. See [queue management](../features/queue/README.md) for what the
states themselves mean.

### Following One Stuck Sync End To End

The structured lines are only part of the story. The rest of the lifecycle -
queue registration, rsync start, monitoring, completion, notification updates -
is narrated by plain `print()` calls that embed the bare transfer id in the
message. So the widest net is a grep for the raw id, not for the `transfer_id:`
prefix:

```
grep "<transfer-id>" logs/dragoncp_backend.log
```

That single grep picks up the sync-logger lines, the queue manager's
registration and unregistration, the transfer record creation, the rsync command,
the monitoring thread, the completion status and the notification/Discord
follow-up, because they all mention the id. Narrowing to `transfer_id:<id>` gives
only the coordinator's structured steps; use it when the wide grep is too noisy.

For a webhook-driven sync that has not produced a transfer yet, grep
`notification_id:<id>` instead - that is the id the scheduler and webhook service
carry before a transfer exists.

To follow something across a rotation, include the rotated files, remembering
that `.1` is newer than `.2`:

```
grep -h "<transfer-id>" logs/dragoncp_backend.log.2 logs/dragoncp_backend.log.1 logs/dragoncp_backend.log
```

## Reading The Logs From The API

Both endpoints require authentication and live under `/api`. Full request and
response contracts are in [the API reference](../reference/api.md#10-server-log-endpoints).

### `GET /api/logs`

Three parameters shape the result:

- **`level`** (default `ERROR`) accepts `DEBUG`, `INFO`, `WARNING`, `ERROR`,
  `CRITICAL` or `ALL`, case-insensitively. Anything unrecognised is silently
  treated as `ERROR`. Matching is not uniformly "this level and above":
  `ERROR` returns ERROR and CRITICAL, `WARNING` returns WARNING, ERROR and
  CRITICAL, `ALL` returns everything, and `DEBUG`, `INFO` and `CRITICAL` each
  match only their own level. Asking for `INFO` therefore hides errors; ask for
  `ALL` when reconstructing a timeline.
- **`limit`** (default 200) is capped at 1000. A missing, non-numeric or
  less-than-one value falls back to 200.
- **`search`** is a case-insensitive substring match applied to the whole record,
  including any traceback lines attached to it. This is where a transfer id goes.

The endpoint does not read the whole file. It seeks to the end and reads
backwards in 8 KB chunks until it has collected a scan window of lines: 25 lines
per requested result, clamped to a minimum of 1,000 and a maximum of 20,000. Those
lines are then grouped into records - a new record begins at a line starting with
a `YYYY-MM-DD HH:MM:SS |` timestamp, so a multi-line traceback stays attached to
the message that produced it - and walked newest-first, applying `search` then
`level`, stopping as soon as `limit` matches are found. The result is finally
reversed back into chronological order.

The consequence to keep in mind: results are bounded by that window, not by the
file. On a busy instance 20,000 lines can be a short stretch of wall-clock time,
and an older error simply will not be found however high the limit. When a search
comes back empty and the incident is not recent, download the file instead.

Each returned entry carries the record's level and its full text. The level is
taken from the first line of the record that contains a `| LEVEL |` marker, or
INFO if none does. The response also reports the resolved log file path, the
file's size and last-modified time, and how many entries matched. If the file
does not exist yet the call still succeeds, with an empty list and a message
saying so, rather than failing.

Requests to `/api/logs` are themselves excluded from the HTTP access logging, so
leaving the viewer open and polling does not fill the log with records about
reading the log.

### `GET /api/logs/download`

Returns the live log file as a plain-text attachment named
`dragoncp_backend.log`, and `404`s with an explanatory message when the file does
not exist. Rotated files are not served - to inspect those, read them off the
host. Each download is itself recorded at INFO ("Serving log download for ...").

Note that this streams the whole current file, which is up to `LOG_MAX_BYTES`
(20 MiB by default). It is the right tool for taking a copy away to analyse, not
for a quick look.

## Reading The Logs

### What A Healthy Transfer Looks Like

A transfer that goes well leaves a recognisable, ordered trail, all at INFO,
spread across a few named threads. Filtered to one transfer id it reads roughly
like this:

```
🎯 [TransferCoordinator] [transfer_id:...] > start_transfer() called
📋 [TransferCoordinator] [transfer_id:...] >    is_duplicate=False, existing=None
✅ Transfer ... registered as RUNNING -> /path/to/destination
📝 Creating transfer record for ...
✅ Transfer record created successfully for ...
🔄 Starting rsync: rsync -av --progress --info=progress2 --delete ...
🔍 Starting monitoring for transfer ... (PID: 2603300)
🏁 Transfer ... completed with return code: 0
✅ Transfer ... completed successfully
🏁 Transfer ... finished with status: completed
✅ Transfer ... unregistered
```

The two signals worth internalising are the pairing and the return code. Every
`registered as RUNNING` should eventually be answered by an `unregistered`, and a
successful rsync reports return code `0`. The monitoring line also gives the
rsync PID, which is what to check on the host if the log has gone quiet.

### What A Failing Transfer Looks Like

Failures come in two flavours.

**rsync ran and returned non-zero.** The pipeline reports it and then finalises
normally, at ERROR because of the ❌ and the word "failed":

```
❌ Transfer ... failed with exit code: 24
🏁 Transfer ... finished with status: failed
```

The exit code is rsync's own, so it is the first thing to look up - the transfer
machinery worked, the copy did not.

**Something threw.** The catching code prints the message and the traceback, so
the record and the following `dragoncp.stderr` lines land together at ERROR:

```
❌ Error monitoring transfer ...: 'NoneType' object is not subscriptable
Traceback (most recent call last):
...
TypeError: 'NoneType' object is not subscriptable
```

If instead the exception escaped its thread entirely, there is no ❌ line; look
for a CRITICAL record from `dragoncp.crash` naming the thread.

### What A Stuck Transfer Looks Like

A stuck transfer is defined by what is *missing*, which is why level filtering
alone will not find it - there is no ERROR to see. Grep the transfer id and look
at the last line:

- last line is `registered as RUNNING` or `Starting monitoring ... (PID: ...)`,
  with no `🏁` and no `unregistered` - the transfer still holds its destination
  path and its concurrency slot, which is what blocks everything queued behind it
- a `🏁 ... finished with status:` line with no matching `unregistered` line
  afterwards means the queue entry was not released

Both cases are queue state questions rather than logging questions; see
[queue management](../features/queue/README.md) for how paths and slots are held
and released.

### Practical Filters

- default ERROR view for "is anything broken right now"
- `level=ALL` plus `search=<transfer id>` to reconstruct one sync, since most of
  its lifecycle is INFO
- `search=dragoncp.crash` for exceptions nobody handled
- `search=Logging configured at` to confirm which file and level the running
  process picked up after a restart

## Files Most Relevant To Logging Behaviour

- `logging_setup.py` - path resolution, rotation, level, redaction, stream capture, exception hooks
- `services/sync_logger.py` - the structured per-sync record shape
- `routes/logs.py` - the two operator endpoints and the bounded backward scan
- `app.py` - calls the logging setup at startup and emits the HTTP access records
