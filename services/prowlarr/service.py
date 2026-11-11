#!/usr/bin/env python3
"""
Prowlarr, for searching from a phone: every indexer at once or a chosen few,
results as each indexer answers, and which indexers are healthy.

A search is one question per indexer, asked in the background a few at a time,
rather than Prowlarr's single all-indexer search. Prowlarr's own search answers
only when its slowest indexer has, so one slow tracker held the whole page; this
way the page shows each indexer's results as they land and says which indexer
failed and why. The indexers are asked exactly as often as Prowlarr's own search
would ask them: once each.

What protects the trackers:

  * nothing searches until the operator presses Search, and nothing retries;
  * the same search within a few minutes is answered from what was found, not
    asked again, unless the operator asks for a fresh one;
  * an indexer Prowlarr has paused after failures, or one with none of the
    chosen categories, is not asked at all;
  * no "test every indexer" — one indexer, by hand.

"Send to download client" passes one guard: on a test instance it is refused
unless "Allow sending releases from this instance" is on, because it starts a
real download. Every send, and every refusal, goes into the activity log.
"""

import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from activity_log import record, record_failure, record_refusal
from env_flags import test_mode_enabled
from services.prowlarr.arr import ArrLink, family_app, landing_category
from services.prowlarr.views import (
    SEARCH_TYPES,
    parse_time,
    client_view,
    covers_categories,
    health_view,
    indexer_view,
    release_private,
    release_view,
)

log = logging.getLogger('dragoncp.prowlarr')

#: How long Prowlarr's indexer list, health and stats are reused. The Search
#: tab reads the list for its indexer picker, so this also keeps a phone that
#: opens and closes the page from asking the other machine every time.
OVERVIEW_SECONDS = 30.0
#: The same search again within this long is answered from what was found.
REUSE_SECONDS = 300.0
#: Searches kept for paging, downloads and grabs. Prowlarr keeps a release it
#: found for about half an hour, after which a grab of it fails; ours go a
#: little sooner so the page says "search again" rather than Prowlarr failing.
KEEP_SECONDS = 25 * 60.0
MAX_SEARCHES = 8
#: Indexers asked at the same time, across every search in progress.
SEARCH_WORKERS = 6
#: Results asked of each indexer. Prowlarr's own page asks for 100.
PER_INDEXER_LIMIT = 100
#: How far back the Indexers tab's numbers go.
STATS_DAYS = 30
MAX_QUERY = 300
#: How far before our question an entry in Prowlarr's history may be dated
#: and still be taken for it: the two machines' clocks need not agree.
HISTORY_SLACK_SECONDS = 30.0

SCOPES = ('all', 'torrent', 'usenet', 'picked')

_DIGITS = re.compile(r'^\d{1,9}$')
_IMDB = re.compile(r'^(?:tt)?(\d{5,10})$', re.IGNORECASE)
#: Prowlarr's query tokens, which carry an id or episode into a search the way
#: its own search box does ("{ImdbId:tt0000000}", "{Season:01}").
_TOKEN = re.compile(r'\{[A-Za-z]+:[^{}]*\}')


def _default_connectors():
    from services.connectors import get_service
    return get_service()


class SearchError(ValueError):
    """A search that cannot be asked as given; the message is for the operator."""


class Search:
    """One search in progress or finished, and everything found so far."""

    def __init__(self, search_id: str, key: Tuple, query: str, search_type: str,
                 categories: List[int], indexers: List[Dict[str, Any]], started: float):
        self.id = search_id
        self.key = key
        self.query = query
        self.type = search_type
        self.categories = categories
        self.started = started
        self.finished: Optional[float] = None
        self.lock = threading.Lock()
        #: One row per indexer: waiting, done, failed or skipped.
        self.indexers = indexers
        self.releases: List[Dict[str, Any]] = []
        self.private: List[Dict[str, Any]] = []

    @property
    def running(self) -> bool:
        return self.finished is None


class ProwlarrService:
    def __init__(self, *, connectors: Callable[[], Any] = _default_connectors,
                 clock: Callable[[], float] = time.time,
                 test_mode: Callable[[], bool] = test_mode_enabled,
                 executor: Optional[ThreadPoolExecutor] = None,
                 arr: Optional[ArrLink] = None):
        self._connectors = connectors
        self.arr = arr or ArrLink(connectors=connectors, clock=clock)
        self.clock = clock
        self._test_mode = test_mode
        self._executor = executor or ThreadPoolExecutor(
            max_workers=SEARCH_WORKERS, thread_name_prefix='prowlarr-search')
        self._lock = threading.Lock()
        self._overview: Optional[Tuple[float, Dict[str, Any]]] = None
        #: Prowlarr's download clients as it sent them, with their categories
        #: and addresses, which the page is not given.
        self._raw_clients: Optional[Tuple[float, List[Dict[str, Any]]]] = None
        self._searches: Dict[str, Search] = {}

    # ------------------------------------------------------------- adapter

    def adapter(self):
        """Prowlarr's adapter while it is switched on and configured, else None."""
        try:
            service = self._connectors()
            if service is None:
                return None
            row = service.store.get_connector('prowlarr')
            if not row or not row.get('enabled'):
                return None
            adapter = service.adapter('prowlarr')
            return adapter if adapter is not None and adapter.is_configured() else None
        except Exception:  # noqa: BLE001 - "cannot tell" reads as "not connected"
            return None

    def can_grab(self, adapter=None) -> Tuple[bool, str]:
        adapter = adapter or self.adapter()
        if adapter is None:
            return False, 'Prowlarr is off or not set up in DragonCP.'
        if self._test_mode() and not adapter.allows_grabs():
            return False, ('This is a test instance, so sending releases is off. Switch on '
                           '"Allow sending releases from this instance" on the Connection tab first.')
        return True, ''

    # ------------------------------------------------------------ overview

    def overview(self, *, fresh: bool = False) -> Dict[str, Any]:
        """Indexers with their health and numbers, Prowlarr's warnings, and the
        download clients a release can be sent to."""
        adapter = self.adapter()
        if adapter is None:
            return {'state': 'off', 'message': 'Prowlarr is off or not set up in DragonCP.'}
        now = self.clock()
        with self._lock:
            hit = self._overview
        if hit and not fresh and now - hit[0] < OVERVIEW_SECONDS:
            return dict(hit[1], **self._grab_words(adapter))

        indexers = adapter.indexers()
        if not indexers.ok:
            return {'state': 'error', 'message': indexers.error}
        status = adapter.indexer_status()
        start = (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=STATS_DAYS))
        stats = adapter.indexer_stats(start.strftime('%Y-%m-%dT%H:%M:%SZ'))
        health = adapter.health()
        clients = adapter.download_clients()
        version = adapter.status()

        by_status = {s.get('indexerId'): s for s in _rows(status.data) if status.ok}
        stats_rows = (stats.data or {}).get('indexers') if stats.ok and isinstance(stats.data, dict) else []
        by_stats = {s.get('indexerId'): s for s in _rows(stats_rows)}
        moment = datetime.fromtimestamp(now, timezone.utc)
        views = [indexer_view(raw, by_status.get(raw.get('id')), by_stats.get(raw.get('id')), moment)
                 for raw in _rows(indexers.data)]
        views.sort(key=lambda v: (not v['enabled'], v['priority'] or 25, v['name'].lower()))
        result = {
            'state': 'ok',
            'version': (version.data or {}).get('version') if version.ok and isinstance(version.data, dict) else None,
            'indexers': views,
            'health': [health_view(h) for h in _rows(health.data)] if health.ok else [],
            'download_clients': [client_view(c) for c in _rows(clients.data)] if clients.ok else [],
            'stats_days': STATS_DAYS,
            'stats_available': bool(stats.ok),
            'read_at': moment.isoformat().replace('+00:00', 'Z'),
        }
        with self._lock:
            self._overview = (now, result)
            if clients.ok:
                self._raw_clients = (now, _rows(clients.data))
        return dict(result, **self._grab_words(adapter))

    def _prowlarr_clients(self, adapter) -> List[Dict[str, Any]]:
        now = self.clock()
        with self._lock:
            hit = self._raw_clients
        if hit and now - hit[0] < OVERVIEW_SECONDS * 2:
            return hit[1]
        answer = adapter.download_clients()
        if not answer.ok:
            return []
        rows = _rows(answer.data)
        with self._lock:
            self._raw_clients = (now, rows)
        return rows

    def _grab_words(self, adapter) -> Dict[str, Any]:
        allowed, why = self.can_grab(adapter)
        return {'can_grab': allowed, 'why_not': why}

    def test_indexer(self, indexer_id: int) -> Dict[str, Any]:
        adapter = self.adapter()
        if adapter is None:
            return {'ok': False, 'status': 503, 'error': 'Prowlarr is off or not set up in DragonCP.'}
        answer = adapter.test_indexer(indexer_id)
        with self._lock:
            self._overview = None  # a test that passed lifts Prowlarr's pause
        if answer.ok:
            return {'ok': True, 'message': 'The indexer answered Prowlarr\'s test.',
                    'duration_ms': answer.duration_ms}
        return {'ok': False, 'status': 502 if not answer.status or answer.status >= 500 else 400,
                'error': answer.error or 'The test failed'}

    # -------------------------------------------------------------- search

    def start_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Start a search, or hand back the same search from a few minutes ago."""
        adapter = self.adapter()
        if adapter is None:
            return {'ok': False, 'status': 503, 'error': 'Prowlarr is off or not set up in DragonCP.'}
        try:
            query, search_type, categories, scope, picked = _read_params(params)
        except SearchError as problem:
            return {'ok': False, 'status': 400, 'error': str(problem)}

        overview = self.overview()
        if overview.get('state') != 'ok':
            return {'ok': False, 'status': 502, 'error': overview.get('message') or 'Prowlarr did not answer'}
        rows = _choose_indexers(overview['indexers'], scope, picked, categories)
        if not any(r['state'] == 'waiting' for r in rows):
            reason = ('None of the chosen indexers can be asked right now.' if rows
                      else 'No indexer is switched on for that choice.')
            return {'ok': False, 'status': 400, 'error': reason}

        key = (query, search_type, tuple(sorted(categories)),
               tuple(sorted(r['id'] for r in rows if r['state'] == 'waiting')))
        now = self.clock()
        if not params.get('fresh'):
            with self._lock:
                for existing in self._searches.values():
                    if existing.key == key and now - existing.started < REUSE_SECONDS:
                        return {'ok': True, 'search_id': existing.id, 'reused': True}

        search = Search(uuid.uuid4().hex[:12], key, query, search_type, categories, rows, now)
        with self._lock:
            self._prune(now)
            self._searches[search.id] = search
        waiting = [r for r in rows if r['state'] == 'waiting']
        for row in waiting:
            self._executor.submit(self._ask_one, adapter, search, row)
        log.info('Prowlarr search %s started: %d indexers (%d skipped), type %s',
                 search.id, len(waiting), len(rows) - len(waiting), search_type)
        return {'ok': True, 'search_id': search.id, 'reused': False}

    def _ask_one(self, adapter, search: Search, row: Dict[str, Any]) -> None:
        """Ask one indexer through Prowlarr and file what it found."""
        asked_at = self.clock()
        try:
            answer = adapter.search(search.query, search_type=search.type,
                                    indexer_ids=[row['id']], categories=search.categories,
                                    limit=PER_INDEXER_LIMIT)
        except Exception as exc:  # noqa: BLE001 - one indexer must not end the search
            log.exception('Prowlarr search %s: indexer %s raised', search.id, row['id'])
            answer = None
            error = f"DragonCP failed asking it ({type(exc).__name__})"
        found = [r for r in (answer.data or []) if isinstance(r, dict)] \
            if answer is not None and answer.ok and isinstance(answer.data, list) else []
        empty = None
        if answer is not None and answer.ok and not found:
            empty = self._why_empty(adapter, row['id'], asked_at)
        with search.lock:
            if empty and empty[0] == 'failed':
                row.update(state='failed', count=0, ms=answer.duration_ms, error=empty[1])
            elif answer is not None and answer.ok:
                for raw in found:
                    release_id = len(search.releases)
                    search.releases.append(release_view(raw, release_id))
                    search.private.append(release_private(raw))
                row.update(state='done', count=len(found), ms=answer.duration_ms,
                           error=empty[1] if empty else None)
            else:
                row.update(state='failed', count=0,
                           ms=answer.duration_ms if answer is not None else None,
                           error=(answer.error if answer is not None else error) or 'It did not answer')
            if all(r['state'] != 'waiting' for r in search.indexers):
                search.finished = self.clock()

    def _why_empty(self, adapter, indexer_id: int, asked_at: float) -> Optional[Tuple[str, str]]:
        """Whether "nothing found" was the indexer's answer or a failure.

        Prowlarr answers an indexer that failed (timed out, refused, broke)
        with an empty list, exactly like one that found nothing; only its
        history says which. Its record of this search is the one dated after
        we asked. Returns None when the search worked, ('failed', why) when
        Prowlarr recorded it as failed, ('unsure', why) when Prowlarr kept no
        record of it, which is what an indexer at its API limit looks like.
        """
        try:
            answer = adapter.indexer_history(indexer_id)
        except Exception:  # noqa: BLE001 - cannot tell is not a failure
            return None
        if not answer.ok or not isinstance(answer.data, list):
            return None
        since = asked_at - HISTORY_SLACK_SECONDS
        mine = []
        for record in answer.data:
            if not isinstance(record, dict):
                continue
            if str(record.get('eventType') or '').lower() != 'indexerquery':
                continue
            when = parse_time(record.get('date'))
            if when is not None and when.timestamp() >= since:
                mine.append(record)
        if not mine:
            return ('unsure', 'Nothing found, and Prowlarr kept no record of asking it. '
                              'It may be at its API limit, or the search never reached it.')
        if any(r.get('successful') for r in mine):
            return None
        return ('failed', 'Prowlarr recorded this search as failed. It shows a failed '
                          'indexer as "nothing found"; Test on the Indexers tab says why.')

    def poll(self, search_id: str, cursor: int = 0) -> Optional[Dict[str, Any]]:
        """What a search has found since `cursor`, and how each indexer is doing."""
        with self._lock:
            search = self._searches.get(search_id)
        if search is None:
            return None
        with search.lock:
            cursor = max(0, min(int(cursor), len(search.releases)))
            return {
                'id': search.id,
                'query': search.query,
                'type': search.type,
                'categories': list(search.categories),
                'running': search.running,
                'started': _stamp(search.started),
                'finished': _stamp(search.finished) if search.finished else None,
                'indexers': [dict(r) for r in search.indexers],
                'total': len(search.releases),
                'cursor': len(search.releases),
                'releases': [dict(r) for r in search.releases[cursor:]],
                # Grabs made since the page last asked, so a second phone sees them.
                'grabbed': [r['id'] for r in search.releases if r['grabbed']],
            }

    def _prune(self, now: float) -> None:
        """Forget searches past their time, and the oldest beyond the cap. Holds `_lock`."""
        for search_id, search in list(self._searches.items()):
            if now - search.started > KEEP_SECONDS and not search.running:
                del self._searches[search_id]
        if len(self._searches) >= MAX_SEARCHES:
            for search_id, _ in sorted(self._searches.items(), key=lambda kv: kv[1].started)[
                    :len(self._searches) - MAX_SEARCHES + 1]:
                del self._searches[search_id]

    def _release(self, search_id: str, release_id: int):
        with self._lock:
            search = self._searches.get(search_id)
        if search is None:
            return None, None, None
        with search.lock:
            if not 0 <= release_id < len(search.releases):
                return search, None, None
            return search, search.releases[release_id], search.private[release_id]

    # ------------------------------------------------- sending and fetching

    def grab(self, search_id: str, release_id: int,
             download_client_id: Optional[int] = None) -> Dict[str, Any]:
        """Send a release to Prowlarr's download client."""
        search, view, private = self._release(search_id, release_id)
        if search is None:
            return {'ok': False, 'status': 410, 'error': 'This search has expired. Search again.'}
        if view is None:
            return {'ok': False, 'status': 404, 'error': 'No such release in this search.'}
        label = view['title']
        adapter = self.adapter()
        allowed, why = self.can_grab(adapter)
        if not allowed:
            record_refusal('prowlarr.grab', 'Refused to send a release: sending is off on this test instance'
                           if adapter is not None else 'Refused to send a release: Prowlarr is off',
                           target_type='prowlarr_release', target_label=label)
            return {'ok': False, 'status': 403, 'error': why}
        if self.clock() - search.started > KEEP_SECONDS:
            return {'ok': False, 'status': 410, 'error': 'This search is too old for Prowlarr to send from. Search again.'}
        if not private['guid'] or private['indexer_id'] is None:
            return {'ok': False, 'status': 400, 'error': 'Prowlarr gave no way to send this release.'}

        client_name = ''
        if download_client_id:
            overview = self.overview()
            match = [c for c in overview.get('download_clients') or [] if c['id'] == download_client_id]
            if not match:
                return {'ok': False, 'status': 400, 'error': 'Prowlarr has no such download client.'}
            client_name = match[0]['name']

        answer = adapter.grab(private['guid'], private['indexer_id'], download_client_id)
        detail = {'indexer': view['indexer'], 'protocol': view['protocol'],
                  'download_client': client_name or None}
        if not answer.ok:
            record_failure('prowlarr.grab', f"Could not send {label} to a download client",
                           target_type='prowlarr_release', target_label=label,
                           detail=dict(detail, error=answer.error))
            return {'ok': False, 'status': 502, 'error': answer.error or 'Prowlarr did not send it'}
        with search.lock:
            view['grabbed'] = True
            private['sent_at'] = self.clock()
            private['client_id'] = download_client_id
        where = client_name or "Prowlarr's download client"
        record('prowlarr.grab', f"Sent {label} to {where}", target_type='prowlarr_release',
               target_label=label, detail=detail)
        return {'ok': True, 'message': f"Sent to {where}"}

    def release_route(self, search_id: str, release_id: int) -> Dict[str, Any]:
        """Where the release would land, who imports it from there, and what
        Sonarr or Radarr make of its name; after a send, where it is now.

        Only reads. Each client it could be sent to gets its landing category
        and the apps watching that category; each app concerned reads the name
        once (kept ten minutes).
        """
        search, view, private = self._release(search_id, release_id)
        if search is None:
            return {'ok': False, 'status': 410, 'error': 'This search has expired. Search again.'}
        if view is None:
            return {'ok': False, 'status': 404, 'error': 'No such release in this search.'}
        adapter = self.adapter()
        if adapter is None:
            return {'ok': False, 'status': 503, 'error': 'Prowlarr is off or not set up in DragonCP.'}

        connected = self.arr.connected()
        usable = [c for c in self._prowlarr_clients(adapter)
                  if c.get('enable') and str(c.get('protocol') or '').lower() == view['protocol']]
        usable.sort(key=lambda c: (c.get('priority') or 1, c.get('id') or 0))
        clients = []
        for raw in usable:
            category, how = landing_category(raw, view['category_ids'])
            clients.append({
                'id': raw.get('id'),
                'name': str(raw.get('name') or ''),
                'category': category,
                'how': how,
                'watchers': self.arr.watchers(raw, category) if connected else [],
            })

        family = family_app(view['category_ids'])
        asked = [w['app'] for c in clients for w in c['watchers']]
        if family:
            asked.append(family)
        asked = [app for app in dict.fromkeys(asked) if app in connected]
        readings = [self.arr.parse(app, view['title'], view) for app in asked]

        sent = None
        tracking = []
        if private.get('sent_at'):
            client_id = private.get('client_id') or (clients[0]['id'] if clients else None)
            sent_to = next((c for c in clients if c['id'] == client_id), None)
            sent = {'client_id': client_id, 'at': _stamp(private['sent_at'])}
            watching = [w['app'] for w in (sent_to or {}).get('watchers') or []]
            for app in dict.fromkeys(watching or ([family] if family in connected else [])):
                tracking.append(self.arr.track(app, view['title'], private['sent_at']))

        return {'ok': True, 'connected': connected, 'family': family, 'clients': clients,
                'readings': readings, 'sent': sent, 'tracking': tracking}

    def release_file(self, search_id: str, release_id: int) -> Dict[str, Any]:
        """The release's .torrent or .nzb, fetched through Prowlarr."""
        search, view, private = self._release(search_id, release_id)
        if search is None:
            return {'ok': False, 'status': 410, 'error': 'This search has expired. Search again.'}
        if view is None:
            return {'ok': False, 'status': 404, 'error': 'No such release in this search.'}
        adapter = self.adapter()
        if adapter is None:
            return {'ok': False, 'status': 503, 'error': 'Prowlarr is off or not set up in DragonCP.'}
        if not private['download_url']:
            return {'ok': False, 'status': 400, 'error': 'Prowlarr gave no file for this release.'}
        result = adapter.download(private['download_url'])
        if not result.ok:
            return {'ok': False, 'status': 502, 'error': result.error or 'Prowlarr did not send the file'}
        if result.magnet:
            return {'ok': True, 'magnet': result.magnet}
        extension = '.nzb' if private['protocol'] == 'usenet' else '.torrent'
        return {'ok': True, 'content': result.content,
                'content_type': result.content_type or (
                    'application/x-nzb' if extension == '.nzb' else 'application/x-bittorrent'),
                'filename': result.filename or _file_name(private['title'] or 'release', extension)}

    def magnet(self, search_id: str, release_id: int) -> Dict[str, Any]:
        """The release's magnet link. Prowlarr hands it out as a redirect."""
        search, view, private = self._release(search_id, release_id)
        if search is None:
            return {'ok': False, 'status': 410, 'error': 'This search has expired. Search again.'}
        if view is None:
            return {'ok': False, 'status': 404, 'error': 'No such release in this search.'}
        if private['protocol'] != 'torrent':
            return {'ok': False, 'status': 400, 'error': 'Usenet releases have no magnet link.'}
        if private['magnet_url'].lower().startswith('magnet:'):
            return {'ok': True, 'magnet': private['magnet_url']}
        adapter = self.adapter()
        if adapter is None:
            return {'ok': False, 'status': 503, 'error': 'Prowlarr is off or not set up in DragonCP.'}
        source = private['magnet_url'] or private['download_url']
        if not source:
            return {'ok': False, 'status': 400, 'error': 'This release has no magnet link.'}
        result = adapter.download(source)
        if not result.ok:
            return {'ok': False, 'status': 502, 'error': result.error or 'Prowlarr did not answer'}
        if not result.magnet:
            return {'ok': False, 'status': 400,
                    'error': 'This indexer gives a .torrent file, not a magnet link. Download the file instead.'}
        return {'ok': True, 'magnet': result.magnet}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


# ------------------------------------------------------------------ helpers

def _rows(data: Any) -> List[Dict[str, Any]]:
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def _file_name(title: str, extension: str) -> str:
    safe = re.sub(r'[^\w.\- ()\[\]]+', '_', title).strip(' ._') or 'release'
    return safe[:180] + extension


def _read_params(params: Dict[str, Any]) -> Tuple[str, str, List[int], str, List[int]]:
    """A search as the page sent it, checked, with its ids folded into the query."""
    text = _TOKEN.sub('', str(params.get('query') or '')).strip()
    if len(text) > MAX_QUERY:
        raise SearchError(f"Keep the search under {MAX_QUERY} characters.")
    search_type = str(params.get('type') or 'search')
    if search_type not in SEARCH_TYPES:
        raise SearchError('Unknown search type.')

    tokens = []

    def number(name: str, label: str) -> Optional[str]:
        value = str(params.get(name) or '').strip()
        if not value:
            return None
        if not _DIGITS.match(value):
            raise SearchError(f"{label} must be a number.")
        return value

    imdb = str(params.get('imdb_id') or '').strip()
    if imdb:
        match = _IMDB.match(imdb)
        if not match:
            raise SearchError('An IMDb id looks like tt0000000.')
        tokens.append(f"{{ImdbId:tt{match.group(1)}}}")
    tmdb = number('tmdb_id', 'The TMDB id')
    if tmdb:
        tokens.append(f"{{TmdbId:{tmdb}}}")
    if search_type == 'tvsearch':
        tvdb = number('tvdb_id', 'The TVDB id')
        if tvdb:
            tokens.append(f"{{TvdbId:{tvdb}}}")
        season = number('season', 'Season')
        episode = number('episode', 'Episode')
        if episode and not season:
            raise SearchError('Give a season with the episode.')
        if season:
            tokens.append(f"{{Season:{int(season):02d}}}")
        if episode:
            tokens.append(f"{{Episode:{int(episode):02d}}}")
    if not text and not tokens:
        raise SearchError('Type something to search for.')
    if tokens and search_type == 'search':
        raise SearchError('Ids and episodes need a TV or film search.')
    query = ' '.join([text] + tokens).strip() if text else ''.join(tokens)

    categories = []
    for value in params.get('categories') or []:
        try:
            number_value = int(value)
        except (TypeError, ValueError):
            raise SearchError('Categories must be numbers.')
        if number_value <= 0:
            raise SearchError('Categories must be numbers.')
        categories.append(number_value)

    scope = str(params.get('scope') or 'all')
    if scope not in SCOPES:
        raise SearchError('Unknown choice of indexers.')
    picked = []
    if scope == 'picked':
        for value in params.get('indexer_ids') or []:
            try:
                picked.append(int(value))
            except (TypeError, ValueError):
                raise SearchError('Indexer ids must be numbers.')
        if not picked:
            raise SearchError('Pick at least one indexer.')
    return query, search_type, sorted(set(categories)), scope, sorted(set(picked))


def _choose_indexers(indexers: List[Dict[str, Any]], scope: str, picked: List[int],
                     categories: List[int]) -> List[Dict[str, Any]]:
    """The indexers a search goes to, each marked waiting or skipped with why."""
    rows = []
    for indexer in indexers:
        if not indexer['enabled']:
            continue
        if scope == 'torrent' and indexer['protocol'] != 'torrent':
            continue
        if scope == 'usenet' and indexer['protocol'] != 'usenet':
            continue
        if scope == 'picked' and indexer['id'] not in picked:
            continue
        row = {'id': indexer['id'], 'name': indexer['name'], 'protocol': indexer['protocol'],
               'state': 'waiting', 'count': 0, 'ms': None, 'error': None}
        if indexer['state'] == 'paused':
            row.update(state='skipped', error='Prowlarr has paused it after failures')
        elif not covers_categories(indexer.get('category_tree') or [], categories):
            row.update(state='skipped', error='It has none of the chosen categories')
        rows.append(row)
    return rows
