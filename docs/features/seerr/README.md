# Seerr

DragonCP shows the admin side of Seerr: requests waiting for a yes or no, where
every approved request has got to, and the issues users reported. Waiting
requests can be approved (as asked, or after changing the quality, folder or
seasons) or declined, failed ones retried, and issues answered, resolved or
reopened. Seerr itself only says "processing" between approved and available;
DragonCP fills in the steps between: downloading on the remote server, held
back, syncing here, synced, partly or fully in Jellyfin.

Discover, making requests, Seerr's users and settings stay in Seerr.

Last updated: 2026-11-02
Primary files: `services/connectors/adapters/seerr.py`, `services/seerr/`,
`routes/seerr.py`, `frontend/src/components/integrations/seerr-requests-panel.tsx`,
`frontend/src/components/integrations/seerr-issues-panel.tsx`

## Where it lives

| Concern | File |
| --- | --- |
| Address, API key, webhook password, the two switches, every call to Seerr | `services/connectors/adapters/seerr.py` |
| Where a request has got to, an issue's thread, in words | `services/seerr/views.py` |
| DragonCP's own arrivals and syncs of a requested title | `services/seerr/arrivals.py` |
| Names, years and posters of requested titles, kept | `services/seerr/titles.py`, table `seerr_title` |
| Kept answers, the guard on changes, the activity log, the webhook, the job | `services/seerr/service.py` |
| Endpoints | `routes/seerr.py` |
| Requests tab | `frontend/src/components/integrations/seerr-requests-panel.tsx` |
| Change, then approve | `frontend/src/components/integrations/seerr-approve-dialog.tsx` |
| Issues tab and the issue panel | `frontend/src/components/integrations/seerr-issues-panel.tsx` |
| Webhook instructions on the Connection tab | `frontend/src/components/integrations/seerr-webhook-card.tsx` |
| Words, data, types | `seerr-vocab.ts`, `hooks/useSeerr.ts`, `lib/seerr-types.ts` |

## How it works

### 1. Connecting

**Integrations → Seerr → Connection** takes Seerr's address and its API key
(Seerr: Settings → General → API Key). Test connection asks Seerr's
`/status` for its version and `/auth/me` to prove the key, since `/status`
answers without one. The key acts as Seerr's owner account, so a reply sent
from DragonCP shows in Seerr under the owner's name. Seerr runs on the media
server; every call is local.

### 2. Requests

The **Requests** tab has five filters: **Waiting** (Seerr's pending),
**In progress** (approved, not yet available), **Failed**, **Done** and
**All**, with the counts from Seerr's `/request/count`, plus films or series,
who asked, and newest or last changed. Each row shows the poster, title,
seasons, who asked and when, who approved it and the quality profile.

A waiting request has **Approve**, **Change, then approve** and **Decline**,
each behind a confirm. A failed one has **Retry**. Before any of them, the
server reads the request again and refuses with "already approved" (or
declined, or done) if someone acted on it in Seerr meanwhile.

**Change, then approve** opens the same choices Seerr's own dialog offers:
the server (when there is more than one), quality profile, folder on the
remote server with its free space, and for a series the seasons (ones already
in Jellyfin cannot be picked). Seerr's edit replaces every field, so DragonCP
sends the request's current server, profile, folder, language profile, tags
and requester along with whatever changed; nothing is sent when nothing
changed. Opening it makes Seerr ask that Sonarr or Radarr live, which is why
the plain Approve button does not.

### 3. Where an approved request is

Four steps, each done, in progress, waiting or a problem: **Approved → On the
remote server → Synced here → In Jellyfin**. One line says where it is now,
first match wins:

| Stage | When | From |
| --- | --- | --- |
| In Jellyfin | Seerr says available, the request is done, or every requested season is available | Seerr |
| Needs you | It arrived on the remote server and the sync here is held back (safety check, restart); the reason is shown | DragonCP's arrivals |
| Syncing here | A sync of it is queued or running here, with percent and time left | DragonCP's arrivals and transfers |
| Downloading | Sonarr or Radarr has it in the download queue, with percent and time left; also "paused", "waiting to download", "importing" and "has a problem" | Seerr's copy of the queue |
| On the remote server | It arrived there and no sync has started | DragonCP's arrivals |
| Sync failed | It arrived and the sync here failed (a later sync of the same season, or of the whole series, clears this) | DragonCP's arrivals |
| Partly in Jellyfin | Some of a series is in Jellyfin | Seerr |
| Synced here | Synced, and Jellyfin has not picked it up yet (Seerr checks every few minutes) | DragonCP's arrivals |
| Searching | Approved, nothing found yet. After 3 days: **Searching for N days**, in amber | Seerr |

A series also gets a chip per requested season: in Jellyfin, partly,
downloading, syncing or not yet, with "6/10" episodes when Jellyfin is
connected (Jellyfin's episode list for that series, files only, kept 10
minutes).

The download comes from Seerr's own copy of the Sonarr/Radarr queue, which
Seerr refreshes every minute, so DragonCP asks the remote server nothing for
it. The sync comes from DragonCP's own webhook rows (Sonarr and Radarr call
DragonCP when a file is imported on the remote server) and the transfers they
started, plus transfers started by hand or from Explore that the title index
ties to the title. Both sides name the title by its TVDB id (series) or TMDB
id (films); only arrivals since the request was made count.

For a series, only the **requested seasons** count, in all three places: a
request for season 2 is not moved by season 1 downloading, syncing or being
in Jellyfin ("Partly in Jellyfin" means part of what was asked for). A queue
entry or sync that names no season (a whole-series sync from Explore) still
counts. Syncs started by hand carry their season from the transfer's folder
("Season 02").

### 4. Issues

The **Issues** tab lists **Open**, **Resolved** or **All**, by who reported
and newest or last changed. A row shows the type (Video, Audio, Subtitles,
Other), the title and episode ("S01E02", "Season 1", or the whole series),
the report's first lines, who, when and how many replies.

Opening one shows the whole conversation in a side panel, with **Reply**,
**Reply and resolve**, and **Resolve** or **Reopen** (behind a confirm).
Seerr tells the reporter on Discord or Telegram as it always does.

### 5. Staying up to date

- Seerr's answers are kept for 20 seconds (lists) and a minute (counts), so
  two tabs or a quick refresh do not ask twice.
- **Seerr's webhook** drops them at once and tells every open page over the
  socket (`seerr_changed`), which refetches. The Connection tab shows the
  address to paste into Seerr (Settings → Notifications → Webhook), what to
  tick, and when Seerr was last heard from. The receiver,
  `POST /api/webhook/seerr`, needs the **Webhook password** in Seerr's
  "Authorization Header"; with no password set it refuses everything.
- **Check every 5 minutes** (off by default) runs the scheduler job
  `seerr_updates`: it asks for the two counts and tells open pages when they
  moved. While Seerr does not answer it waits 5, 10, then 15 minutes.
- Open pages also refetch: In progress every 20 seconds, the others every
  minute. The sidebar shows Seerr's count (waiting requests plus open issues)
  in amber.

## Behaviour worth knowing

- **A test instance refuses every change** (approve, decline, retry, reply,
  resolve, reopen) until **Allow changes from this instance** is on, because
  approving from the beta starts a real download on the remote server. The
  refusal happens before Seerr is asked, and is logged. An instance without
  TEST_MODE always allows changes.
- **Every change goes into the activity log** under the signed-in admin:
  "Approved the request for Example Show (2024), season 1 by alex", including
  failures and refusals.
- **No e-mail or token leaves the server.** Seerr's user rows carry e-mail
  addresses and service tokens; DragonCP passes on an id and a display name
  only.
- **Listing requests costs the remote server about one call an hour.** Seerr
  looks up Sonarr's and Radarr's quality profiles for every request list,
  through its own rolling one-hour cache.
- **Titles are named once every three days.** Seerr's rows carry only a TMDB
  id; the name, year, poster and episode counts come from Seerr's `/movie` or
  `/tv` and are kept in `seerr_title`. At most 30 are looked up per page load,
  four at a time. Posters load from TMDB's image host.
- **A change made in Seerr itself** shows on the next refresh, or at once
  with the webhook on.
- Seerr's request list has no "declined" filter; declined requests show under
  All.

## Data

`seerr_title`, the name, year, poster path and season episode counts per
requested title, written by `TitleCache` in `services/seerr/titles.py`.
Everything else is read from Seerr when asked. Columns:
[database schema](../../reference/database-schema.md#table-seerr_title).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/seerr/summary` | Counts for the tabs and sidebar, whether changes are allowed here, the webhook's state |
| GET | `/api/seerr/requests` | Requests by filter, each with where it has got to |
| GET | `/api/seerr/requests/<id>` | One request |
| GET | `/api/seerr/requests/<id>/options` | What can be changed before approving (asks Sonarr or Radarr through Seerr) |
| POST | `/api/seerr/requests/<id>/approve`, `/decline`, `/retry` | Change a request; approve takes optional `changes` |
| GET | `/api/seerr/issues`, `/api/seerr/issues/<id>` | Issues by filter; one issue with its thread |
| POST | `/api/seerr/issues/<id>/comment` | Reply, optionally resolving |
| POST | `/api/seerr/issues/<id>/resolve`, `/reopen` | Change an issue's state |
| GET | `/api/seerr/users` | Seerr's users by name, for the filters |
| POST | `/api/webhook/seerr` | Seerr's webhook; the webhook password, not a sign-in |

Details: [API reference](../../reference/api.md#seerr). Socket event:
`seerr_changed` (`kind`: `request`, `issue`, `poll` or `test`).

## Related

- [Integrations](../integrations/README.md): connectors, the Connection tab, the scheduler
- [Jellyfin](../jellyfin/README.md): lends its connection for episode counts
- [Webhooks](../webhooks/README.md): the Sonarr and Radarr arrivals the sync step reads
- [Activity](../activity/README.md): where every change is recorded
