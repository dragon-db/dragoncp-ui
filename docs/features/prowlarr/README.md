# Prowlarr

Search every indexer Prowlarr knows from a phone: all of them, only torrent or
only usenet ones, or a hand-picked few, narrowed by category, as a plain, TV
(season and episode) or film search, or by IMDb, TVDB or TMDB id. Results
appear as each indexer answers. Sorting and filtering then happen on the
phone, so they are instant. A release can be sent to one of Prowlarr's download
clients, its magnet link copied, or its .torrent or .nzb saved. The
**Indexers** tab shows which indexers work: healthy, failing, paused by
Prowlarr after failures, or off, with how fast each answers and how often it
fails.

Adding, editing and removing indexers, apps and download clients stays in
Prowlarr.

Last updated: 2026-11-06
Primary files: `services/connectors/adapters/prowlarr.py`, `services/prowlarr/`,
`routes/prowlarr.py`, `frontend/src/components/integrations/prowlarr-search-panel.tsx`,
`frontend/src/components/integrations/prowlarr-indexers-panel.tsx`

## Where it lives

| Concern | File |
| --- | --- |
| Address, API key, the test-instance switch, every call to Prowlarr | `services/connectors/adapters/prowlarr.py` |
| Fetching a release file, or the magnet link Prowlarr redirects to | `services/connectors/transport.py` (`fetch_download`) |
| A release, an indexer, a health warning, in the page's words | `services/prowlarr/views.py` |
| Searching one indexer at a time, kept searches, sending, the guard | `services/prowlarr/service.py` |
| Endpoints | `routes/prowlarr.py` |
| Search tab, filter sheet, indexer picker | `frontend/src/components/integrations/prowlarr-search-panel.tsx` |
| A release, from below | `frontend/src/components/integrations/prowlarr-release-sheet.tsx` |
| Where a release lands, who imports it, what they read (server) | `services/prowlarr/arr.py` |
| The same, in the release sheet | `frontend/src/components/integrations/prowlarr-import-check.tsx` |
| Indexers tab | `frontend/src/components/integrations/prowlarr-indexers-panel.tsx` |
| Quality words in a name, sorting, filtering | `frontend/src/components/integrations/prowlarr-vocab.ts` |
| The search on screen, recent searches | `frontend/src/stores/prowlarr-search.ts` |

## How it works

### 1. Connecting

**Integrations → Prowlarr → Connection** takes the address (the one this
server reaches Prowlarr at, HTTPS on another machine is fine) and the API key
from Prowlarr's Settings → General. Test reads Prowlarr's status and refuses
anything that is not Prowlarr. The page opens on **Search**.

### 2. Choosing the search

One box, then one line each for what to search (Anything, TV, Film), which
indexers (All, Torrent, Usenet, Pick…), and categories (Movies, TV, Anime,
Audio, Books, PC, Console, Other; several at once). TV adds Season and
Episode; TV and Film add **Search by id**. Ids and episodes are passed the way
Prowlarr's own search box takes them (`{ImdbId:tt…}`, `{Season:01}`); the
same tokens typed into the box by hand are dropped. After a search, these
choices fold into one line so the results start higher on a phone; **Change**
opens them again. The last 10 searches are kept on the device under the box.

### 3. Asking the indexers

The server works out which indexers the search goes to, then asks Prowlarr
once per indexer, at most 6 at a time across all searches, instead of making
one all-indexer search. Prowlarr's own search answers only when its slowest
indexer does; this way each indexer's results show up as soon as they arrive.
Each indexer is asked once, as Prowlarr's own search would ask it. Not asked at all:

- an indexer switched off in Prowlarr;
- an indexer Prowlarr has paused after failures (shown as **skipped**);
- an indexer with none of the chosen categories (**skipped**).

The page asks the server every 0.6 s for what is new, and only new releases
travel. The line above the results says how many indexers answered, failed
and were skipped; tapping it lists each one with its count and time, or why
it failed.

### 4. Reading the results

Each result shows its name, the quality words in it (resolution, source,
HDR, codec, audio), size, age, seeders and leechers (red when nobody seeds) or
grabs for usenet, freeleech, and the indexer. 60 are drawn at first, with
**Show more** below. The word box filters by words in any order; `-word`
excludes. The sheet behind the sliders button filters by kind, resolution,
minimum seeders, age, size range, freeleech, and indexer. None of it asks
Prowlarr again.

### 5. Doing something with a release

Tapping a result opens it from below: the whole name (selectable, with Copy
name), the facts, and:

- **Send to …**: hands the release to a download client in Prowlarr,
  choosing among the enabled ones for its kind (torrent or usenet), after a
  confirm. It then reads **Sent** in the sheet and the list.
  Above the button, **where it lands**: see below.
- **Copy magnet**: torrents only. Prowlarr hands magnet links out as a
  redirect, so the server follows it; the copy works on iPhone Safari because
  the clipboard is given the link while it is still being fetched.
- **Save .torrent / .nzb**: fetched through the server.
- **Indexer page**, and IMDb, TMDB and TVDB links when the release names them.

### 6. Will Sonarr or Radarr import it?

A release sent from here was not grabbed by Sonarr or Radarr, so they import
it only when it lands in a category they watch and they can tell from its
name alone which show and episodes, or which film, it is. The release sheet
checks both before **Send**, for the download client chosen:

1. **Where it lands.** Prowlarr puts the release in the client category
   mapped to one of the release's categories (or to the family it belongs to:
   TV/Anime goes where TV goes), else in the client's own default category.
2. **Who watches that.** Sonarr's and Radarr's download clients of the same
   kind at the same address (any of that kind, if none shares the address)
   and the category each watches; one with no category watches everything.
   Also whether their automatic import of finished downloads is on. A
   warning when nobody watches it: it would download and stay there. Another
   when a TV release lands where only Radarr looks, or the reverse.
3. **What they read.** Sonarr's or Radarr's own name check: which show,
   season and episodes, or which film; a warning when that title is not in
   their library, when the name cannot be read, when the indexer tags the
   release as a different title, or when Sonarr knows the show but has no
   such episode (an anime-style episode count on a show not set as Anime is
   the usual reason). If the library already has the file, it says the
   import happens only as an upgrade.

After **Send**, the sheet asks every 15 seconds while it is open: waiting for
Sonarr or Radarr to see it, downloading and how far, importing, stuck (with
their reason), in their queue but not recognised (import it by hand), or
imported. A release is recognised in their queue and history by its name.

All of it only reads from Prowlarr, Sonarr and Radarr. Download-client
settings are reused for a minute and each name check for ten. When neither
Sonarr nor Radarr is connected in DragonCP, the sheet shows the category and
says so.

### 7. Indexers tab

Prowlarr's own health warnings first, then counts of healthy, failing,
paused and off indexers, then the list: kind, public or private, priority,
which search types it supports, its site, and over the last 30 days its
average answer time, searches, grabs and failure rate (amber from 5 %, red
from 20 %). A paused indexer says until when. **Test** asks Prowlarr to test
that one indexer. There is no "test all". Below the list are Prowlarr's
download clients, each with the client category every kind of release goes
in. The tab reads only Prowlarr's records: opening it asks no
indexer anything.

## Behaviour worth knowing

- **The same search within 5 minutes is not asked again.** It is answered
  from what was found, and the line says "from 2 min ago". **Again** asks
  afresh. This protects private trackers' API limits.
- **Nothing is retried.** A failed indexer shows as failed with Prowlarr's
  own words; a second try would be a second hit on the tracker.
- **Searches are kept 25 minutes.** Prowlarr only keeps a found release for
  about half an hour, so after 25 minutes Send, magnet and file say "Search
  again" instead of Prowlarr failing.
- **On a test instance (TEST_MODE on), Send is refused** until **Allow sending
  releases from this instance** is on in Connection, because it starts a real
  download. Searching, magnets and files are always allowed.
- **Behind a proxy**, Prowlarr writes its download links with the address it
  thinks it has. DragonCP keeps only the path and sends it to the saved
  address, so a download can only go to the configured Prowlarr.
- **No credential reaches the page.** Prowlarr's download and magnet links
  carry its API key, and some trackers put the passkey in a release's guid;
  all three stay on the server, and the page names a release by its search
  and its number in it.
- **A finished search survives tab switches** and moving to another page;
  a server restart forgets every search (the page then says to search again).
- Prowlarr is asked about indexers, health and stats at most every 30 seconds
  between the two tabs; **Refresh** on Indexers asks now.

## Data

Nothing in the database. Searches live in the server's memory: at most 8,
each forgotten 25 minutes after it started. The connector's address, key and
switch are in `connector` and `connector_secret` like every connector. Every
send, failure to send, and refusal goes to the activity log as
`prowlarr.grab`. Recent searches are kept in the browser
(`dragoncp-prowlarr-recent`).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/prowlarr/overview` | Indexers with health and 30-day numbers, warnings, download clients, whether Send is allowed (`?fresh=1` skips the 30-second copy) |
| POST | `/api/prowlarr/indexers/<id>/test` | Prowlarr's test of one indexer |
| POST | `/api/prowlarr/search` | Start a search, or get the same one from the last 5 minutes |
| GET | `/api/prowlarr/search/<id>?cursor=n` | Releases since `cursor`, and each indexer's state |
| POST | `/api/prowlarr/search/<id>/releases/<n>/grab` | Send to a download client (`download_client_id` optional) |
| GET | `/api/prowlarr/search/<id>/releases/<n>/route` | Where it lands, whether Sonarr or Radarr imports it, and after a send where it is |
| GET | `/api/prowlarr/search/<id>/releases/<n>/magnet` | The magnet link |
| GET | `/api/prowlarr/search/<id>/releases/<n>/file` | The .torrent or .nzb (or `{"magnet"}` when that is what it is) |

Details: [API reference](../../reference/api.md#prowlarr).

## Related

- [Integrations](../integrations/README.md): the connector framework.
- [Activity](../activity/README.md): where sends are recorded.
