# Running the App

Last updated: 2026-07-28
Primary files: `start.sh`, `start.py`, `app.py`, `frontend/package.json`, `frontend/vite.config.ts`

## Purpose

There are two halves to running DragonCP locally: the Python backend, started by
`./start.sh`, and the React frontend dev server, started by npm inside
`frontend/`. This page describes what the launcher actually does, defines the
`TEST_MODE` flag, and lists the frontend commands.

For production - gunicorn, systemd, the served frontend build - see
[../operations/runtime-and-deployment.md](../operations/runtime-and-deployment.md).

## The launcher

`./start.sh` is a thin system-level check that then hands off to `start.py`.
Everything Python-level happens in `start.py`.

### `start.sh` - system checks

Three checks, in order. The script begins with `set -e` and `cd`s to its own
directory, so it can be run from anywhere.

1. **Python.** Prefers `python3`; falls back to `python` only if that is a
   Python 3. Requires **3.12 or higher** and aborts otherwise, printing the
   install command for Debian, RHEL and macOS. Then confirms the `venv` module
   is importable and aborts if it is not.
2. **rsync.** Prints the version if found. If rsync is missing this is a
   **warning, not a failure** - the script continues and the application starts,
   but file transfers will not work.
3. **Other dependencies.** Currently only checks for `curl`, and treats it as
   optional. The function is written as a placeholder for future checks.

It then `exec`s `python start.py "$@"` with the system Python.

`start.sh` exports `DRAGONCP_PYTHON_CMD` before the handoff, but `start.py`
never reads it. It has no effect today.

### `start.py` - Python setup

Six numbered steps. Colours are disabled automatically when stdout is not a TTY.

**[1/6] Python version.** Re-checks for 3.12+, this time against the interpreter
actually running the script.

**[2/6] Virtual environment.** This is the part worth knowing. `find_venv()`
looks for a directory named, in order: `venv`, `env`, `.venv`, `.env`, in the
repository root. A directory only counts as a virtualenv if it contains
`bin/python` (Unix) or `Scripts/python.exe` (Windows) - an empty directory with
a matching name is skipped.

If none is found, the script asks whether to create one. Answering yes creates
`venv/` with pip; answering no aborts, because the launcher will not run against
the system Python. Everything from here on uses the virtualenv's interpreter, so
whichever directory is found first is the one the application runs in.

**[3/6] Dependencies.** Parses `requirements.txt` (handling `==`, `>=`, `~=`,
bare names, `[extras]`, comments, and skipping `-r`/`-e` lines), compares it
against `pip list --format=freeze` from the virtualenv, and reports two
categories separately: packages that are **missing**, and packages installed at
a **different exact version** than a `==` pin requires. Names are normalised for
case and `-`/`_` before comparing.

If anything is missing or mismatched it offers to run
`python -m pip install -r requirements.txt`, with a five-minute timeout, then
re-checks. Declining aborts and prints the manual command.

Note that only `==` pins are version-checked. A `>=` or `~=` requirement is
treated as satisfied by any installed version.

**[4/6] Environment file.** If `dragoncp_env.env` is missing it offers to copy
`dragoncp_env_sample.env` over it, then asks whether to continue with the
defaults - answering no exits so the file can be edited first. If the sample is
also missing, it aborts.

**[5/6] Directories.** Creates `templates`, `static` and `logs` if absent.

**[5.5/6] Frontend build.** This is a **placeholder**. When `frontend/` and
`frontend/package.json` exist it prints a message and does nothing else. The
launcher does not run `npm install` or `npm run build`. Build the frontend
yourself (see below) or use the dev server.

**[6/6] Start.** Prints the access URL, then runs `python app.py` as a
subprocess and returns its exit code. Ctrl-C is caught and reported cleanly.

The banner URL uses `PORT` from the environment, validated as an integer in the
range 1-65535 and falling back to 5000 with a warning otherwise. `app.py` does
the same validation independently, so the two always agree.

### Things the launcher will not do for you

All the prompts use `input()`. Under a non-interactive shell they take their
default answer (`ask_yes_no` returns the default on `EOF`), which means a
missing virtualenv is created silently and dependencies are installed silently -
but "continue with default configuration?" defaults to *no*, so a first run with
no `dragoncp_env.env` exits rather than starting misconfigured.

`python app.py` is the direct-startup path. It logs a warning that this is not
the supported production path unless `FLASK_DEBUG` or `TEST_MODE` is on. See
[../operations/runtime-and-deployment.md](../operations/runtime-and-deployment.md).

## TEST_MODE

`TEST_MODE` is the development flag referenced throughout these docs. Set it to
`1`:

```bash
TEST_MODE=1 ./start.sh
```

It can also be set in `dragoncp_env.env`. `app.py` loads that file early and
pushes every key into the process environment with `setdefault`, so a real
environment variable always wins over the file, but a file value does reach the
code that reads `os.environ`.

### What it changes

**rsync runs dry.** `TransferService.start_rsync_process` appends `--dry-run` to
the rsync command, so no bytes move. Simulation transfers are explicitly exempt
- they copy their own local fixture files and have to actually move data for the
progress figures to mean anything.

**Directories are not created.** The destination directory, the dynamic backup
directory and its `.rsync-partial` subdirectory are printed rather than created.
`app.py` also skips creating `templates/` and `static/` on direct startup.

**Configuration is not written to disk.** `DragonCPConfig.save_config` prints
what it would have written to `dragoncp_env.env` instead of writing it. The
in-memory config is still updated.

**Backup restore is printed, not performed.** `BackupService` adds `--dry-run`,
prints the files it would delete instead of deleting them, and prints the
temporary file-list creation instead of writing the file. Because it does not
write the list, rsync then exits non-zero and the restore reports failure - so
`TEST_MODE` is not a usable dry run for restore. This is documented in
[../features/backups/README.md](../features/backups/README.md).

**Startup becomes development-shaped.** `TEST_MODE` turns on verbose Socket.IO
and engine.io logging, allows the unsafe Werkzeug development server on direct
`python app.py` startup, and is reported as `test_mode: true` in the runtime
profile - both in the startup log line and inside the `/api/runtime/status`
response (nested under `runtime_status.websocket.runtime`), so an operator can
confirm from the in-app log viewer whether production is running with it off.

### What it does not change

**The simulation endpoints are not gated by it.** `dragoncp_env_sample.env`
claims `TEST_MODE` "enables the transfer simulator", but the simulation blueprint
is registered unconditionally in `app.py`, and nothing in
`routes/simulation.py` or `services/simulation_service.py` reads `TEST_MODE`.
`/api/simulation/status`, `/start`, `/stop` and `/cleanup` are available
whatever the flag is set to - they are protected by `@require_auth`, not by
`TEST_MODE`. Simulations are safe to run against production by design; see
[../features/simulation/README.md](../features/simulation/README.md).

**Authentication is not bypassed.** Neither `auth.py` nor `webhook_auth.py`
mentions `TEST_MODE`.

### Use `1`, not `true`

The two readers disagree on what counts as "on". The startup flag in `app.py`
accepts `1`, `true`, `yes` or `on`; every behavioural check in `config.py`,
`services/transfer_service.py`, `services/backup_service.py` and the
`__main__` block compares against the exact string `"1"`.

So `TEST_MODE=true` produces the development banner and verbose logging while
rsync still runs for real. Always set it to `1`.

### When to use it

Use `TEST_MODE=1` whenever you are working on the UI, on queue behaviour, or on
transfer bookkeeping and do not want files moved. Leave it unset in production -
transfers will silently do nothing.

## Frontend

Everything below runs from `frontend/`.

**Package manager: npm.** The lockfile is `frontend/package-lock.json`. Verified
working with Node 24 and npm 11.

```bash
cd frontend
npm install
```

### Dev server

```bash
npm run dev        # DRAGONCP_BACKEND=dev  vite --host 0.0.0.0
npm run dev:prod   # DRAGONCP_BACKEND=prod vite --host 0.0.0.0 --port 5181 --strictPort
```

Vite serves on port **5173** by default (set in `vite.config.ts`); `dev:prod`
overrides that to **5181** with `--strictPort`, so the two can run side by side
and the prod-pointed one always sits on a known port instead of silently
shifting. `--host 0.0.0.0` exposes it on the LAN. `allowedHosts` additionally
permits the machine's short hostname and any `.ts.net` name, so the dev server
can be opened over Tailscale MagicDNS.

### The two proxy targets

`vite.config.ts` proxies `/api` and `/socket.io` (the latter with `ws: true` for
websocket upgrade) to one of two named backends, chosen by `DRAGONCP_BACKEND`:

| Name   | Target                  | What it is                                                       |
| ------ | ----------------------- | ---------------------------------------------------------------- |
| `dev`  | `http://localhost:5050` | a local `python app.py` from this checkout, run with `PORT=5050`  |
| `prod` | `http://localhost:5000` | the live `dragoncp-ui.service` gunicorn - real data, real transfers |

`dev` is the default when `DRAGONCP_BACKEND` is unset or unrecognised.
`DRAGONCP_BACKEND_URL` overrides the table entirely and points the proxy
anywhere.

The config prints the resolved target on startup, and flags the prod target as
`LIVE PRODUCTION — writes hit real data`. Read that line before clicking
anything: `npm run dev:prod` gives you a development UI wired to the real
backend.

To run the local backend on the port the `dev` target expects:

```bash
PORT=5050 TEST_MODE=1 ./start.sh
```

### Build, lint, format

```bash
npm run build         # vite build && tsc -b
npm run lint          # eslint .
npm run format        # prettier --write src
npm run format:check  # prettier --check src
npm run preview       # vite preview, serves the built output
```

Note the order in `build`: `vite build` runs *first* and `tsc -b` second, so
type errors surface after the bundle has already been written. A non-zero exit
from `npm run build` can still leave a `dist/` behind. Run `tsc -b` or
`npm run lint` on their own if you want the check without the artefact.

Frontend environment variables are documented in `frontend/.env.example`:
`VITE_API_URL` and `VITE_WS_URL`, both left empty in development so the Vite
proxy is used.

## Related

- [installation.md](installation.md) - first-time setup and configuration
- [testing.md](testing.md) - the automated test suite
- [../operations/runtime-and-deployment.md](../operations/runtime-and-deployment.md) - production runtime
- [../operations/frontend-deployment.md](../operations/frontend-deployment.md) - serving the built frontend
- [../reference/configuration.md](../reference/configuration.md) - configuration keys
