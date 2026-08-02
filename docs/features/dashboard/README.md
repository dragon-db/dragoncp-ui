# Dashboard

Last updated: 2026-07-28
Primary files: `frontend/src/components/pages/dashboard.tsx`, `frontend/src/components/dashboard/system-ticker.tsx`, `frontend/src/components/dashboard/storage-strip.tsx`, `frontend/src/components/dashboard/transfers-panel.tsx`, `frontend/src/components/dashboard/webhook-rail.tsx`, `frontend/src/components/dashboard/disk-utils.ts`, `routes/debug.py`

## Purpose

The Dashboard is the landing page. Signing in sends you here: the root route
redirects an authenticated visitor to `/dashboard` and everyone else to
`/login` (`frontend/src/routes/index.tsx`).

It is a read-and-react screen. It answers "is anything wrong, is anything
moving, is anything waiting" in one glance, and gives you the small set of
controls you would reach for immediately: pause, resume, stop, refresh.
Anything deeper - full history, logs per transfer, the whole webhook backlog -
lives on its own page and is linked from here.

The page stacks four panels top to bottom (`dashboard.tsx`):

1. the system ticker (one line)
2. the storage strip
3. active transfers and the webhook rail, side by side on wide screens and
   stacked on narrow ones

## How the page stays current

Every panel polls. None of them listen to the websocket - the dashboard
components contain no socket code, so realtime being on or off makes no
difference to what you see here.

| Data | Endpoint | Poll interval |
| --- | --- | --- |
| Active transfers + queue counts | `GET /api/transfers/active` | 5 seconds |
| Webhook notifications | `GET /api/webhook/notifications` | 10 seconds |
| Local disk usage | `GET /api/disk-usage/local` | 60 seconds |
| Remote disk usage | `GET /api/disk-usage/remote` | 60 seconds |

Intervals are set on the hooks: `useActiveTransfers` and
`useWebhookNotifications` in `frontend/src/hooks/useTransfers.ts` and
`useWebhooks.ts`, `useLocalDiskUsage` and `useRemoteDiskUsage` in
`useConfig.ts`. Failed requests are retried once and results are considered
fresh for a minute (`frontend/src/lib/query-client.ts`); the page does not
refetch when you switch back to the browser tab, so on returning to a tab that
has been in the background you may briefly see figures up to one poll interval
old.

The webhook endpoint is called three times over with different limits, because
three consumers want different windows: the ticker asks for 10, the rail asks
for 30, and poster art resolution asks for the default 50
(`frontend/src/hooks/useTransferPosters.ts`). Each is a separate cached query,
so the browser issues three requests per cycle.

### One thing to know about errors

**No panel on this page shows an error.** If a backend call fails, the panel
falls back to its empty state - "No active transfers", "No webhook activity",
"No disk information available". There is no toast and no error banner: the
only global response to a failed request is a 401, which logs you out and sends
you to the login page (`frontend/src/lib/api.ts`).

The practical consequence: a dead backend, a broken disk API or a database
problem looks exactly like a quiet, idle system. If the dashboard suddenly
reads as completely empty when you expect activity, suspect the connection
before you conclude nothing is running.

## Panel 1 - System ticker

A single line across the top. Left to right:

- **Status light and word.** Green pulse and "Operational / All systems
  nominal" normally. Amber pulse and "Attention / N disks near full" as soon as
  any one disk - local or remote - is at or above 78% used. Disk fullness is
  the only thing that flips this indicator; failed transfers, a backed-up queue
  and an unreachable server do not.
- **Peak disk.** The highest usage percentage across every disk the storage
  strip knows about, coloured by the same severity thresholds. Shows `—` when
  no disk data is available.
- **Queue.** Running transfers against the concurrency cap, for example `2/3`.
  Both numbers come from `queue_status` on `/api/transfers/active`; the cap is
  `MAX_CONCURRENT_TRANSFERS` in `services/queue_manager.py`, currently 3. While
  the first request is in flight, or if it fails, this reads `0/3` - the `3` is
  a hardcoded frontend fallback, not a value from the server.
- **Queued.** Count of transfers in `queued` state, from the same response.
- **Webhooks.** The `total` from the webhook notifications query. Because the
  ticker requests a limit of 10 and the endpoint returns `total` as the length
  of the list it just returned (`routes/webhooks.py`), **this number stops at
  10.** It is "10 or more recent webhook records", not a backlog count.
- **updated HH:MM:SS.** The time this line was last drawn, not the time the
  data was fetched. It is recomputed on every re-render, so it tracks the
  fastest poll on the page (5 seconds) rather than the age of the disk figures
  beside it, which can be up to a minute old.

## Panel 2 - Storage strip

One cell per disk, up to four across. Each cell shows an icon (a drive for
local, a cloud for remote), a name, the usage percentage, a fill bar, the mount
point, and "X used / Y free". Hovering the path line shows the mount point and
the backing device together.

The heading carries a count like "2 local · 1 remote".

Data comes from `useDisks` (`frontend/src/components/dashboard/disk-utils.ts`),
which merges the two disk endpoints. Local entries with `available: false` are
dropped, and the remote entry only appears if the response reports
`available: true`.

**Local disks are named by position, not by configuration.** The first
reachable local disk is labelled "Local Disk 1", the second "Local Disk 2", and
so on. If `DISK_PATH_1` is unset or unreachable, the disk configured as
`DISK_PATH_2` is displayed as "Local Disk 1". Read the mount point under the
bar, not the label, when you need to know which disk you are looking at. The
remote entry is always named "Remote Storage" and shows "remote endpoint" where
a local disk shows its mount point.

### Severity thresholds

`diskSeverity` in `disk-utils.ts` maps a percentage to three bands:

| Usage | Band | Appearance |
| --- | --- | --- |
| below 78% | ok | brand-coloured bar and figure |
| 78% to 91% | warn | amber bar and figure |
| 92% and above | crit | rose bar and figure, and the "free" figure also turns rose |

The same 78% line is what makes the ticker say "Attention". These are display
thresholds only - nothing in the transfer path consults them, so a disk at 99%
will not stop or refuse a sync.

### Empty and loading states

While the first request is outstanding the strip shows four grey placeholder
blocks. Afterwards, if no disk qualified, it shows "No disk information
available". That single message covers all of: nothing configured, configured
paths that do not exist, `df` failing or timing out, the remote API being
unset, unreachable, or returning an unexpected body. The strip does not
distinguish between them.

To tell them apart you have to call the endpoints directly - both return a
per-disk `error` string (local) or a `message` (remote) that the dashboard
never renders. See [the API reference](../../reference/api.md).

### What an operator must configure

Local disks (`routes/debug.py`, `api_local_disk_usage`):

- `DISK_PATH_1`, `DISK_PATH_2`, `DISK_PATH_3` - up to three paths to watch.
  Set in the environment file (see `dragoncp_env_sample.env`). The Settings
  page shows them read-only: they are environment settings, so changing one
  means editing the file on the server and restarting.
- `DISK_PATH_1` defaults to `/home` when unset or empty. `DISK_PATH_2` and
  `DISK_PATH_3` have no default and are simply skipped.
- Each path must exist as seen by the backend process. The endpoint shells out
  to `df -h <path>` with a 10-second timeout and parses the first data row:
  filesystem, size, used, available, use percent, mount point. A path inside a
  container that does not map to the host filesystem will report the
  container's view, not the host's.
- The percentage shown is `df`'s own `Use%` column, unmodified. The used/free
  strings are `df -h`'s human-readable output verbatim, so they are the same
  values you would read from a shell on that machine.

Remote storage (`routes/debug.py`, `api_remote_disk_usage`):

- `DISK_API_ENDPOINT` - an HTTP(S) URL the backend fetches with a 10-second
  timeout. Without it the endpoint returns an error and no remote cell appears.
- `DISK_API_TOKEN` - optional; when set it is sent as
  `Authorization: Bearer <token>`.
- The response must be JSON containing a `service_stats_info` object with
  `total_storage_value`, `used_storage_value` and `free_storage_gb`. Any other
  shape is rejected as "Invalid API response format" and, again, the cell just
  does not appear.

### Remote figures are converted, and will not match the remote server

This one matters, because the discrepancy is silent.

The backend assumes the remote API reports in **GiB** - including
`free_storage_gb`, despite its name (there is an explicit code comment to that
effect). It multiplies total, used and free by 1.073741824 and labels the
results "GB":

```
total_gb = round(total_gib * 1.073741824)
```

So if the remote server itself says it has 466 free, the dashboard shows
**500 GB free**. The figure is roughly 7.4% higher than the number the remote
machine reports, and neither the strip nor the tooltip says a conversion
happened. When you are reconciling the dashboard against the storage host, do
the conversion by hand or you will conclude the two disagree.

Two follow-on notes:

- The usage percentage is computed after conversion, from converted used over
  converted total, so it is unaffected by the conversion except for rounding.
  The percentage is trustworthy even when the absolute figures surprise you.
- If your remote API genuinely reports `free_storage_gb` in GB rather than GiB,
  the free figure is simply inflated by 7.4% with no way to turn the conversion
  off. There is no configuration flag for this.

## Panel 3 - Active transfers

The wide panel on the left. It lists transfers the backend considers active -
`running`, `pending`, `queued` and `paused` (`ACTIVE_STATUSES` in
`services/transfer_coordinator.py`). Completed, failed and cancelled transfers
never appear here; they are on the [Transfers page](../transfers/README.md).

Header: a "N running" badge and an "N queued" badge, both taken from
`queue_status` on the same response, plus "Pause all", a refresh button and a
"New transfer" button that opens the movies media browser.

Body: the **first 8** transfers in the response. Non-queued rows are listed
first; queued rows are collected below a "Queued · N" divider, because a queued
transfer is waiting rather than progressing.

Note the asymmetry: the header badges count everything the backend has, while
the list is capped at 8. If the header says 12 queued and you count 3 rows,
nothing is broken - the rest are off the bottom of the list, and the divider's
own count only ever describes the visible rows.

Each row shows:

- poster art, a title (the parsed title, falling back to the folder name) and
  the season name where there is one
- a progress bar and percentage; queued rows show `—` and an empty bar rather
  than 0%
- speed and ETA for running rows, "Paused" for paused rows, a "Queued" badge
  for queued rows
- bytes transferred against the total
- source path to destination path, in small monospace

Sizes and speeds are formatted in powers of 1000, deliberately, so they agree
with the raw rsync log lines shown elsewhere in the app
(`frontend/src/lib/transfer-progress.ts`).

Poster art is borrowed from webhooks. Transfers store no artwork of their own;
each Radarr/Sonarr notification records the transfer it was synced under, and
that join is what supplies the image (`useTransferPosters`). Transfers you
started by hand from the media browser have no webhook and therefore always
show the placeholder, and so does any transfer older than the 50 most recent
notifications.

### Controls

- **Pause** (running rows) and **Resume** (paused rows) call
  `POST /api/transfer/<id>/pause` and `/resume`. Both raise a toast on success
  or failure; resume echoes the server's own message, which is how a resume
  that had to re-queue tells you so.
- **Pause all** pauses only the running rows currently visible in the panel -
  that is, within the first 8. If some fail, the toast reports how many of the
  attempted set succeeded.
- The **⋯ menu** offers "View logs", which navigates to the Transfers page (the
  whole page, not that transfer's log), and "Stop transfer".
- **Stop** opens a confirmation dialog first. Its wording is the operative
  documentation: the transfer stops mid-flight and is marked cancelled, files
  already copied stay in place, remaining files are not transferred, and you
  should use Pause instead if you intend to continue later.
- While any of these requests is in flight, the pause and resume buttons on
  every row are disabled.

Several transfer endpoints report failure as HTTP 200 with an `error` status;
the hooks detect that and treat it as a failure, so a red toast here is
trustworthy and a green one is not merely "the request completed"
(`assertSuccess` in `useTransfers.ts`).

### Empty and loading states

Three grey placeholder rows while loading. When there is genuinely nothing
active - or when the request failed, as described above - the panel shows "No
active transfers" with a button through to the media browser.

## Panel 4 - Webhook rail

The narrow panel on the right: the five most recent items of Radarr/Sonarr
activity, newest first, with a "View all webhooks →" link to the
[Webhooks page](../webhooks/README.md).

The header badge is `total` from the query, which requests a limit of 30 - so
like the ticker's figure, it saturates, at 30 here.

The rail pulls 30 notifications and groups them before trimming to five
(`frontend/src/lib/webhook-grouping.ts`). Series and anime collapse into one
row per show and season so a season pack cannot flood the rail; movies stay
standalone. This is why the badge and the row count are unrelated numbers: 30
notifications may be five rows.

Each row shows poster art, title and year, a status badge, a media-type badge,
a detail line ("Season 2 · 6 episodes" for a group, quality or year for a
movie), and a footer with who requested it, the total size, and how long ago it
arrived.

A grouped row takes the most urgent status among its episodes, in this order:
syncing, failed, queued (path), queued (slot), ready, pending, manual sync
required - and shows "Completed" only when none of those are present. So a
season showing "Failed" means at least one episode failed, not that the whole
season did.

Sizes count the imported file per episode rather than the release size, which
would otherwise be counted once per episode of a season pack, and an episode
that was upgraded is counted once at its newest size.

Loading shows four placeholder rows; otherwise "No webhook activity" - which,
again, is also what a failed request looks like.

## Related

- [Queue behaviour](../queue/README.md) - what running, queued and the
  `queue_reason` values actually mean
- [Transfers](../transfers/README.md) - the full history and per-transfer logs
- [Webhooks](../webhooks/README.md) - the full notification list and its actions
- [API reference](../../reference/api.md) - the endpoints listed above
- [Frontend reference](../../reference/frontend.md) - hooks and component layout

## Known gaps

- No panel surfaces an error. Every failure mode renders as an empty panel, and
  the per-disk `error` strings the backend already returns are discarded by the
  UI.
- The ticker's "Webhooks" figure and the rail's badge are both capped by their
  own request limits (10 and 30), so neither is a true total.
- The ticker's "updated" stamp is a render time, not a data timestamp, and is
  therefore optimistic for the disk figures next to it.
- Remote storage figures are silently converted from GiB to GB and will not
  match what the storage host reports.
- Not verified: whether the storage strip's four-column layout hides a fifth
  disk. Only three local paths and one remote endpoint are configurable, so
  four is the maximum reachable today and the case does not arise.
