# Versioning

Last updated: 2026-08-11

Where the version number lives, how to choose the next one, and when to change
it. Current release: see [`VERSION`](../../VERSION).

## One file, read by everything

```
VERSION          ← the only place the number is written
```

Everything else reads it. Nothing else states it.

| Consumer | How it gets the number |
| --- | --- |
| `config.py` (`APP_VERSION`) | Reads `VERSION` at import |
| `/api/runtime/status` | Returns `APP_VERSION` |
| The navbar badge | Prefers the running server's value, falls back to the build's |
| The frontend bundle | `vite.config.ts` reads `VERSION` and defines `__APP_VERSION__` |
| `frontend/package.json` and its lockfile | Bumped to match; a test enforces it |

**Why this exists.** The number used to be written out three times — in
`config.py`, in `frontend/package.json`, and as a constant in the navbar — and
nothing read the Python one. Keeping three copies in step by hand is not a
discipline anyone sustains: they drifted, the screen showed a number the backend
did not agree with, and eventually it stopped being updated at all. It sat at
2.1.4 across several releases' worth of work.

`tests/test_version.py` is what makes a single source actually single. It fails
the build when `package.json` or the lockfile falls behind, and when any file
under `frontend/src` or `config.py` hard-codes a version-shaped string on a line
mentioning "version" — which is how a fourth copy would sneak back in.

Reading the file never raises. A missing or empty `VERSION` reads as `unknown`:
a packaging mistake should not stop the application starting, since the number
is only ever displayed.

## When to bump it

**Every change that ships bumps the version.** Not every commit — every set of
work that lands on `main`.

| Bump | When | Example from 2.2.0 |
| --- | --- | --- |
| **Major** `3.0.0` | An operator has to do something to keep working: a setting is renamed or removed, a stored format changes without a migration, an endpoint the UI depends on is dropped | none yet |
| **Minor** `2.3.0` | A new feature, or a set of them. Anything that adds a screen, a tab, an action or a report | the Backups History tab; Explore's three views |
| **Patch** `2.2.1` | A fix or a set of them, with nothing new to learn | the asset-caching fix; the delete-preview crash |

When a release carries both features and fixes — most of them do — it is a minor
bump. The rule is the highest applicable, not the most numerous.

Pre-1.0 conventions do not apply here; this is a deployed application on 2.x and
the numbers mean what the table says.

## Making a release

1. Edit `VERSION`. One line, `MAJOR.MINOR.PATCH`, nothing else.
2. Bump `frontend/package.json` and `frontend/package-lock.json` to match — both
   the top-level `version` and `packages[""].version` in the lockfile.
3. Add a `CHANGELOG.md` entry describing what an operator would *notice*, not
   what the diff did. Group it under the area it affects.
4. Run `python -m pytest tests/test_version.py`. It catches every copy that did
   not move.
5. Rebuild the frontend so the bundle carries the new number
   (`npm run build` in `frontend/`, or `./start.sh`, which does it for you).

Step 5 matters less than it looks: the navbar prefers the version the *server*
reports, so a stale bundle still shows the truth as soon as the backend answers.
The built-in value is the fallback for before that first response lands.

## Related

- [`CHANGELOG.md`](../../CHANGELOG.md) — what changed in each release
- [`../operations/runtime-and-deployment.md`](../operations/runtime-and-deployment.md) — how a release reaches the server
