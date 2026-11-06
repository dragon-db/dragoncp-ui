# Jellyfin

DragonCP shows what Jellyfin is playing right now — who, what, on which
device, how far in — and, for every stream Jellyfin converts instead of
sending the file as it is, the reasons in plain words with what usually avoids
them. With **Record plays** on it also keeps a record of every play, which
Jellyfin itself does not: Jellyfin's activity log says who started what, but
not whether it was converted, why, or how long anyone watched.

Last updated: 2026-11-02
Primary files: `services/connectors/adapters/jellyfin.py`, `services/jellyfin/`,
`routes/jellyfin.py`, `frontend/src/components/integrations/now-playing-panel.tsx`,
`frontend/src/components/integrations/plays-panel.tsx`

## Where it lives

| Concern | File |
| --- | --- |
| Address, API key, the Record plays switch, the calls to Jellyfin | `services/connectors/adapters/jellyfin.py` |
| One Jellyfin session as a stream: who, what, how it is played, why | `services/jellyfin/sessions.py` |
| One row per play, opened, updated and closed | `services/jellyfin/recorder.py` |
| Asking Jellyfin, the scheduler job, poster addresses | `services/jellyfin/service.py` |
| Endpoints | `routes/jellyfin.py` |
| The table | `models/database.py` (`_create_jellyfin_tables`), table `jellyfin_play` |
| Now playing and Plays tabs | `frontend/src/components/integrations/now-playing-panel.tsx`, `plays-panel.tsx` |
| The words for play methods and reasons | `frontend/src/components/integrations/jellyfin-vocab.ts` |
| Data | `frontend/src/hooks/useJellyfin.ts`, `frontend/src/lib/jellyfin-types.ts` |

## How it works

### 1. Connecting

**Integrations → Jellyfin → Connection** takes Jellyfin's address and an API
key (Jellyfin: Dashboard → API Keys). Test connection asks Jellyfin for its
name and version. DragonCP sends the key in the `Authorization: MediaBrowser
Token="…"` header, the form Jellyfin 10.11 documents, so it keeps working if
Jellyfin's "legacy authorization" setting is turned off. Every call goes to
Jellyfin on the media server; nothing here reaches the remote server.

### 2. Now playing

The **Now playing** tab asks Jellyfin's session list every 5 seconds while it
is on screen. Each stream shows:

- the title (series, episode code and episode title, or film and year) with
  its poster;
- who, the device, the app and its version, and **At home** or **Away**
  (home network and tailnet addresses count as home);
- a progress bar with position and length, dimmed while paused;
- how it is played: **Direct** (the file as it is), **Repackaged** (Jellyfin's
  direct stream: a new container, same picture), **Sound converted** (only the
  audio is converted) or **Converting** (the picture is converted — the
  expensive kind). Converted streams come first and are tinted;
- for a converted stream, **each reason** Jellyfin gives, with what it means
  and what usually avoids it — "Subtitles. The app cannot draw these subtitles
  (styled ASS, or picture-based PGS), so Jellyfin burns them into the picture.
  A plain-text subtitle track, or an app that draws styled subtitles itself.";
- three quiet lines: the file's tracks (container, video, the audio that is
  playing), the subtitles that are on, and what Jellyfin sends instead
  (codec, size, bitrate, on the GPU or the CPU).

### 3. Recording plays

With **Record plays** on, the scheduler job `jellyfin_plays` asks Jellyfin
every 10 seconds while something plays and every 30 seconds when nothing does.
Every answer — the job's, and the Now playing tab's while it is open — is
folded into the record:

- A play is one (session, item). The next episode is a new play.
- A play stays open until it has been missing for 45 seconds, so a stream that
  drops out of one answer (Jellyfin does this for a moment when a track is
  switched) is not split in two. It is closed at its last sighting.
- Watched time adds the time since the last sighting when the stream was
  playing then, at most 30 seconds per gap. Paused time is not counted, nor is
  time DragonCP was not looking.
- The play method kept is the heaviest seen: a play that was converted at any
  point counts as converted. Every reason seen during the play is kept.
- A stream seen again after more than 45 seconds unseen is a new play, and
  the old one is closed at its last sighting, even when no answer in between
  was late enough to close it (answers at +40 and +50 s, say).
- After a restart, a play still going carries on in the same row if it was
  last seen less than 45 seconds before; one that ended while DragonCP was
  down is closed at its last sighting by the first answer.
- Switching **Record plays** off, or Jellyfin off, closes every open play at
  its last sighting, so none is left reading "Playing". The Plays tab and the
  Now playing tab both do this when they find recording off.

While Jellyfin is not answering, the job asks after 60 seconds, then 120, then
every 5 minutes, and three failures in a row open the scheduler's alert. With
Record plays off, the job does not run, and Now playing still works.

### 4. Plays

The **Plays** tab lists the record, newest first: poster, title, who, device,
app, when, how long was watched (and "to the end" past 90%), **Playing** while
it is still open, how it was played, and a chip per reason (hover for what it
means). Filters: **All / Converted / Not converted**, a person, and a search
over title, device and app. It reads DragonCP's own table, so it works with
Jellyfin off or down.

## Behaviour worth knowing

- **Nothing is recorded until Record plays is switched on**, and nothing from
  before then can be recovered from Jellyfin with the play method or reasons.
  Both tabs say so while it is off, with a link to the switch.
- **Posters come through DragonCP.** The browser cannot reach Jellyfin's
  address, and an `<img>` cannot carry the sign-in token, so a poster address is
  signed by the server instead. Only addresses DragonCP handed to a signed-in
  page load; any other answers "not found".
- **A play shorter than one check may be missed** while nothing else is
  playing: the job asks every 30 seconds when idle.
- **The Converting tint is the picture being converted.** A stream converting
  only its sound is labelled Sound converted and is not tinted; it costs little.
- Not verified: whether a repackaged stream (Jellyfin's direct stream) carries
  reasons. The tab shows them when Jellyfin sends them.
- Not verified: whether Jellyfin 10.11 includes the file's tracks in the session
  list. When it does not, the File and Subtitles lines are left out.
- The scheduler's alert for three failures in a row is the general one
  (`scheduler.failing`), not an "integration down" alert.
- **Seerr borrows this connection** to count the episodes Jellyfin has of a
  half-finished requested series ("6 of 10" on Seerr's Requests tab): one
  read of that series' episode list, files only, kept 10 minutes. See
  [Seerr](../seerr/README.md).

## Data

`jellyfin_play`, one row per play, written by `PlayRecorder` in
`services/jellyfin/recorder.py`. Columns and indexes:
[database schema](../../reference/database-schema.md#table-jellyfin_play).
The scheduler keeps the job's last run in `scheduled_job` under
`jellyfin_plays`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/jellyfin/now-playing` | Every stream playing now, converted first; recorded when Record plays is on |
| GET | `/api/jellyfin/plays` | Recorded plays, newest first, with filters |
| GET | `/api/jellyfin/image/<item_id>?s=…` | A poster, guarded by a signature rather than a sign-in |

Details: [API reference](../../reference/api.md#jellyfin). No socket events.

## Related

- [Integrations](../integrations/README.md) — connectors, the Connection tab, the scheduler
- [Sync engine](../sync-engine/README.md) — the scheduler the recorder runs on
- [Frontend reference](../../reference/frontend.md#integrations-page) — how the page picks its tabs
- [Seerr](../seerr/README.md) — requests and issues; uses Jellyfin's episode counts
