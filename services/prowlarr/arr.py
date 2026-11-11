#!/usr/bin/env python3
"""
Where a release sent from Prowlarr ends up, and whether Sonarr or Radarr will
pick it up.

Prowlarr hands a release to a download client under a category: the client
category mapped to one of the release's own categories, else the client's
default. Sonarr and Radarr each watch one category per download client and
import what finishes there. A release they did not grab themselves is imported
only if they can tell, from its name alone, which series and episodes or which
film it is, and that title is already in their library.

So before a send this answers three questions, every one of them a read:

  * which category the release lands in, for each download client it could go to;
  * whether Sonarr or Radarr watches that category on that client, with
    completed-download handling on;
  * what Sonarr or Radarr makes of the release's name (their own parser).

After a send it follows the release into their queue and history, so the page
can say "Sonarr has it" or "Sonarr imported it", or that it needs a hand.

Nothing here writes to Sonarr or Radarr: their adapters refuse anything but GET.
"""

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

#: (connector id, name on the page, the download-client field naming its category)
APPS = (
    ('sonarr', 'Sonarr', 'tvCategory'),
    ('radarr', 'Radarr', 'movieCategory'),
)
LABELS = {app: label for app, label, _ in APPS}

#: Newznab families: TV releases are Sonarr's, film releases Radarr's.
FAMILY = {5000: 'sonarr', 2000: 'radarr'}

#: How long download-client settings are reused. They change by hand, rarely.
CLIENT_SECONDS = 60.0
#: How long one app's reading of one release name is reused.
PARSE_SECONDS = 600.0
MAX_PARSES = 200
#: How long a queue-and-history check after a send is reused. The page asks
#: every 15 seconds while the sheet is open; this keeps two phones to one read.
TRACK_SECONDS = 10.0
#: Imports looked for from this long before the send, for clock drift.
TRACK_SLACK_SECONDS = 120.0

_NOT_ALNUM = re.compile(r'[^a-z0-9]+')


def _default_connectors():
    from services.connectors import get_service
    return get_service()


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fields(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {f.get('name'): f.get('value') for f in raw.get('fields') or []
            if isinstance(f, dict) and f.get('name')}


def _host(value: Any) -> str:
    return str(value or '').strip().lower().rstrip('/')


def same_name(a: str, b: str) -> bool:
    """Whether two release names are the same once dots, spaces and case are gone.

    A download client may add or drop a file extension, so one name starting
    with the other counts when it is long enough not to be a coincidence.
    """
    x, y = _NOT_ALNUM.sub('', (a or '').lower()), _NOT_ALNUM.sub('', (b or '').lower())
    if not x or not y:
        return False
    if x == y:
        return True
    short, long_ = sorted((x, y), key=len)
    return len(short) >= 12 and long_.startswith(short) and len(long_) - len(short) <= 5


# ------------------------------------------------------- the Prowlarr side

def landing_category(raw_client: Dict[str, Any], category_ids: List[int]) -> Tuple[str, str]:
    """The category Prowlarr gives a release on this client, and why.

    Returns (category, how): how is 'mapped' when one of the client's mappings
    took it, 'default' for the client's own category, 'none' when it goes in
    with no category at all. Prowlarr looks for a mapping that names one of
    the release's categories, then for one naming a family (5000, TV) the
    release's category belongs to (5070, TV/Anime), then falls back.
    """
    if raw_client.get('supportsCategories') is False:
        return '', 'none'
    wanted = {c for c in category_ids if c is not None}
    mappings = [m for m in raw_client.get('categories') or [] if isinstance(m, dict)]
    for mapping in mappings:
        if wanted & {_int(c) for c in mapping.get('categories') or []}:
            return str(mapping.get('clientCategory') or ''), 'mapped'
    for mapping in mappings:
        for family in (_int(c) for c in mapping.get('categories') or []):
            if family and family % 1000 == 0 and any(family < c < family + 1000 for c in wanted):
                return str(mapping.get('clientCategory') or ''), 'mapped'
    default = str(_fields(raw_client).get('category') or '')
    return (default, 'default') if default else ('', 'none')


def client_identity(raw: Dict[str, Any]) -> Dict[str, Any]:
    fields = _fields(raw)
    return {
        'implementation': str(raw.get('implementation') or '').lower(),
        'host': _host(fields.get('host')),
        'port': _int(fields.get('port')),
        'url_base': _host(fields.get('urlBase')),
    }


def family_app(category_ids: List[int]) -> Optional[str]:
    """Sonarr for a TV release, Radarr for a film, None for anything else."""
    for cid in category_ids or []:
        if cid is None or cid >= 100000:
            continue
        app = FAMILY.get(cid // 1000 * 1000)
        if app:
            return app
    return None


# ------------------------------------------------------------ the arr side

class ArrLink:
    """Reads Sonarr's and Radarr's download clients, parser, queue and history."""

    def __init__(self, *, connectors: Callable[[], Any] = _default_connectors,
                 clock: Callable[[], float] = time.time):
        self._connectors = connectors
        self.clock = clock
        self._lock = threading.Lock()
        self._clients: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._parses: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
        self._tracks: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}

    def adapter(self, app: str):
        """The app's adapter while it is switched on and configured, else None."""
        try:
            service = self._connectors()
            if service is None:
                return None
            row = service.store.get_connector(app)
            if not row or not row.get('enabled'):
                return None
            adapter = service.adapter(app)
            return adapter if adapter is not None and adapter.is_configured() else None
        except Exception:  # noqa: BLE001 - "cannot tell" reads as "not connected"
            return None

    def connected(self) -> List[str]:
        return [app for app, _, _ in APPS if self.adapter(app) is not None]

    # -- download clients ---------------------------------------------------

    def app_clients(self, app: str) -> Dict[str, Any]:
        """{state: ok|off|error, imports: bool, clients: [...]} for one app."""
        now = self.clock()
        with self._lock:
            hit = self._clients.get(app)
        if hit and now - hit[0] < CLIENT_SECONDS:
            return hit[1]
        adapter = self.adapter(app)
        if adapter is None:
            return {'state': 'off', 'imports': False, 'clients': []}
        field = next(f for a, _, f in APPS if a == app)
        ok, rows = adapter._get('/api/v3/downloadclient')
        cfg_ok, cfg = adapter._get('/api/v3/config/downloadclient')
        if not ok or not isinstance(rows, list):
            result = {'state': 'error', 'imports': False, 'clients': []}
        else:
            clients = []
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                clients.append(dict(
                    client_identity(raw),
                    name=str(raw.get('name') or ''),
                    enabled=bool(raw.get('enable')),
                    category=str(_fields(raw).get(field) or ''),
                ))
            imports = bool(cfg.get('enableCompletedDownloadHandling')) \
                if cfg_ok and isinstance(cfg, dict) else True
            result = {'state': 'ok', 'imports': imports, 'clients': clients}
        with self._lock:
            self._clients[app] = (now, result)
        return result

    def watchers(self, prowlarr_client: Dict[str, Any], category: str) -> List[Dict[str, Any]]:
        """Which apps import what lands in `category` on this Prowlarr client.

        The same client is the one of the same kind at the same address. When
        none shares the address, a client of the same kind may still be it
        (Prowlarr reaching it as an IP, Sonarr as a name) or may be another
        server entirely, so such a match is returned with `verified` False and
        the page says to check. A Sonarr or Radarr client with no category of
        its own watches everything in that client.
        """
        identity = client_identity(prowlarr_client)
        found = []
        for app, label, _ in APPS:
            info = self.app_clients(app)
            if info['state'] != 'ok':
                continue
            kind = [c for c in info['clients'] if c['enabled']
                    and c['implementation'] == identity['implementation']]
            here = [c for c in kind if c['host'] and c['host'] == identity['host']
                    and (c['port'] is None or identity['port'] is None or c['port'] == identity['port'])]
            for client in here or kind:
                if not client['category'] or client['category'].lower() == category.lower():
                    found.append({'app': app, 'label': label, 'client': client['name'],
                                  'imports': info['imports'],
                                  'everything': not client['category'],
                                  'verified': bool(here)})
                    break
        return found

    # -- the parser ---------------------------------------------------------

    def parse(self, app: str, title: str, release: Dict[str, Any]) -> Dict[str, Any]:
        """What the app makes of a release name, in the page's words."""
        now = self.clock()
        key = (app, title)
        with self._lock:
            hit = self._parses.get(key)
        if hit and now - hit[0] < PARSE_SECONDS:
            return hit[1]
        adapter = self.adapter(app)
        if adapter is None:
            return {'app': app, 'label': LABELS[app], 'state': 'off'}
        ok, payload = adapter._get('/api/v3/parse', {'title': title}, timeout=15.0)
        if not ok or not isinstance(payload, dict):
            result = {'app': app, 'label': LABELS[app], 'state': 'error'}
        elif app == 'sonarr':
            result = _sonarr_reading(payload, release)
        else:
            result = _radarr_reading(payload, release)
        with self._lock:
            if len(self._parses) >= MAX_PARSES:
                for old in sorted(self._parses, key=lambda k: self._parses[k][0])[:MAX_PARSES // 4]:
                    del self._parses[old]
            self._parses[key] = (now, result)
        return result

    # -- after a send -------------------------------------------------------

    def track(self, app: str, title: str, sent_at: float) -> Dict[str, Any]:
        """Where a sent release is in the app: imported, in its queue, or not seen."""
        now = self.clock()
        key = (app, title)
        with self._lock:
            hit = self._tracks.get(key)
        if hit and now - hit[0] < TRACK_SECONDS:
            return hit[1]
        adapter = self.adapter(app)
        if adapter is None:
            return {'app': app, 'label': LABELS[app], 'state': 'off'}
        result = self._track(adapter, app, title, sent_at)
        with self._lock:
            for old in [k for k, v in self._tracks.items() if now - v[0] > 300]:
                del self._tracks[old]
            self._tracks[key] = (now, result)
        return result

    def _track(self, adapter, app: str, title: str, sent_at: float) -> Dict[str, Any]:
        base = {'app': app, 'label': LABELS[app]}
        since = datetime.fromtimestamp(sent_at - TRACK_SLACK_SECONDS, timezone.utc)
        ok, imports = adapter.imports_since(since.strftime('%Y-%m-%dT%H:%M:%SZ'))
        if ok:
            done = [r for r in imports if same_name(r.get('sourceTitle') or '', title)]
            if done:
                return dict(base, state='imported', files=len(done))
        q_ok, rows = adapter.queue_all()
        if not q_ok:
            return dict(base, state='error')
        mine = [r for r in rows if same_name(r.get('title') or '', title)]
        if not mine:
            return dict(base, state='not_seen')
        row = mine[0]
        verdict = adapter.classify_row(row)
        size, left = _int(row.get('size')), _int(row.get('sizeleft'))
        known = bool(row.get('series') or row.get('seriesId') or row.get('movie') or row.get('movieId'))
        return dict(
            base,
            state='queued',
            verdict=verdict['verdict'],
            why=verdict['why'],
            known=known,
            stuck=verdict['verdict'] in adapter.STUCK_VERDICTS,
            progress=round(1 - left / size, 3) if size and left is not None else None,
            message=_first_message(row),
        )


def _first_message(row: Dict[str, Any]) -> str:
    for status in row.get('statusMessages') or []:
        for message in (status or {}).get('messages') or []:
            if message:
                return str(message)
    return str(row.get('errorMessage') or '')


def _has_file(row: Dict[str, Any], file_id: str) -> bool:
    """Whether the library has a file for it. The parse answer leaves
    `hasFile` empty in both apps but fills in the file's id."""
    return bool(row.get('hasFile')) or (_int(row.get(file_id)) or 0) > 0


def _sonarr_reading(payload: Dict[str, Any], release: Dict[str, Any]) -> Dict[str, Any]:
    base = {'app': 'sonarr', 'label': 'Sonarr'}
    parsed = payload.get('parsedEpisodeInfo')
    if not isinstance(parsed, dict):
        return dict(base, state='unreadable')
    numbers = {
        'season': _int(parsed.get('seasonNumber')),
        'episodes': [n for n in (_int(e) for e in parsed.get('episodeNumbers') or []) if n is not None],
        'absolute': [n for n in (_int(e) for e in parsed.get('absoluteEpisodeNumbers') or []) if n is not None],
        'full_season': bool(parsed.get('fullSeason')),
        'multi_season': bool(parsed.get('isMultiSeason')),
    }
    series = payload.get('series')
    if not isinstance(series, dict):
        return dict(base, state='unmatched', read_as=str(parsed.get('seriesTitle') or ''), **numbers)
    episodes = [e for e in payload.get('episodes') or [] if isinstance(e, dict)]
    tvdb = _int(series.get('tvdbId'))
    return dict(
        base,
        state='matched',
        title=str(series.get('title') or ''),
        year=_int(series.get('year')),
        anime=str(series.get('seriesType') or '').lower() == 'anime',
        monitored=bool(series.get('monitored', True)),
        other_title=bool(release.get('tvdb_id') and tvdb and release['tvdb_id'] != tvdb),
        found=len(episodes),
        have=sum(1 for e in episodes if _has_file(e, 'episodeFileId')),
        **numbers,
    )


def _radarr_reading(payload: Dict[str, Any], release: Dict[str, Any]) -> Dict[str, Any]:
    base = {'app': 'radarr', 'label': 'Radarr'}
    parsed = payload.get('parsedMovieInfo')
    if not isinstance(parsed, dict):
        return dict(base, state='unreadable')
    movie = payload.get('movie')
    if not isinstance(movie, dict):
        return dict(base, state='unmatched',
                    read_as=str(parsed.get('primaryMovieTitle') or parsed.get('movieTitle') or ''),
                    year=_int(parsed.get('year')) or None)
    tmdb, imdb = _int(movie.get('tmdbId')), str(movie.get('imdbId') or '')
    other = bool(release.get('tmdb_id') and tmdb and release['tmdb_id'] != tmdb)
    if not other and release.get('imdb_id') and imdb:
        other = _int(imdb.lower().lstrip('t')) != release['imdb_id']
    return dict(
        base,
        state='matched',
        title=str(movie.get('title') or ''),
        year=_int(movie.get('year')),
        monitored=bool(movie.get('monitored', True)),
        other_title=other,
        have=1 if _has_file(movie, 'movieFileId') else 0,
    )
