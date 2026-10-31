#!/usr/bin/env python3
"""
Episode titles from TMDB, for what Sonarr has no title for.

Read only, through the one transport every outbound call uses. The key is the
API Read Access Token from themoviedb.org, sent in a header so it never appears
in an address that could be logged. The older short API key also works; it
travels as a query parameter, which the transport strips from every logged
address.

Answers are kept for an hour: a season's titles do not change minute to minute,
and the same season is asked about by the title check, the preview and the
rename that follows it.
"""

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from services.connectors import transport

API = 'https://api.themoviedb.org/3'

#: Seconds an answer is reused.
CACHE_SECONDS = 3600

#: Seconds between two requests. TMDB allows far more; this keeps a title
#: check of a whole library a gentle trickle.
SPACING = 0.25

_SHORT_KEY = re.compile(r'^[0-9a-f]{32}$', re.IGNORECASE)

_cache: Dict[Tuple[str, str], Tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_pace_lock = threading.Lock()
_last_call = [0.0]


class TmdbClient:
    def __init__(self, token: str, language: str = 'en-US'):
        self.token = (token or '').strip()
        self.language = language

    # -- plumbing ----------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None,
             cache: bool = True) -> Tuple[bool, Any, str]:
        """One read. Returns (usable, parsed, words). Never raises."""
        if not self.token:
            return False, None, 'No TMDB key is set'
        query = {k: v for k, v in (params or {}).items() if v not in (None, '')}
        headers = {'Accept': 'application/json'}
        if _SHORT_KEY.match(self.token):
            query['api_key'] = self.token
        else:
            headers['Authorization'] = f"Bearer {self.token}"
        url = f"{API}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        key = (self.token[-8:], url.replace(self.token, ''))
        if cache:
            with _cache_lock:
                hit = _cache.get(key)
            if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
                return True, hit[1], ''

        with _pace_lock:
            wait = SPACING - (time.monotonic() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            result = transport.send('GET', url, headers=headers, timeout=12.0)
            _last_call[0] = time.monotonic()

        if not result.ok:
            if result.status_code in (401, 403):
                return False, None, 'TMDB rejected the key'
            if result.status_code == 404:
                return False, None, 'TMDB has no such entry'
            return False, None, result.error or 'TMDB did not answer'
        parsed = result.json
        if parsed is None:
            return False, None, 'TMDB answered with something unreadable'
        if cache:
            with _cache_lock:
                if len(_cache) > 2000:
                    _cache.clear()
                _cache[key] = (time.monotonic(), parsed)
        return True, parsed, ''

    # -- the questions -------------------------------------------------------

    def check(self) -> Tuple[bool, str]:
        ok, payload, words = self._get('/authentication', cache=False)
        if ok and isinstance(payload, dict) and payload.get('success'):
            return True, 'TMDB key works'
        return False, words or 'TMDB did not accept the key'

    def find_by_tvdb(self, tvdb_id: Any) -> Optional[Dict[str, Any]]:
        """The TMDB show for a TVDB id — how a Sonarr series is matched."""
        if tvdb_id in (None, '', 0):
            return None
        ok, payload, _ = self._get(f"/find/{quote(str(tvdb_id))}",
                                   {'external_source': 'tvdb_id'})
        if not ok or not isinstance(payload, dict):
            return None
        results = payload.get('tv_results') or []
        return _show(results[0]) if results and isinstance(results[0], dict) else None

    def search(self, query: str, year: Optional[int] = None) -> Tuple[bool, List[Dict[str, Any]], str]:
        """Shows matching a name, best first."""
        query = (query or '').strip()
        if not query:
            return False, [], 'Type a name to search for'
        ok, payload, words = self._get('/search/tv', {
            'query': query, 'first_air_date_year': year, 'language': self.language,
            'include_adult': 'false',
        })
        if not ok or not isinstance(payload, dict):
            return False, [], words
        rows = [_show(r) for r in payload.get('results') or [] if isinstance(r, dict)]
        return True, rows[:8], ''

    def show(self, tmdb_id: Any) -> Optional[Dict[str, Any]]:
        """A show with its seasons and how many episodes each holds."""
        ok, payload, _ = self._get(f"/tv/{int(tmdb_id)}", {'language': self.language})
        if not ok or not isinstance(payload, dict):
            return None
        out = _show(payload)
        out['seasons'] = {
            int(s['season_number']): int(s.get('episode_count') or 0)
            for s in payload.get('seasons') or []
            if isinstance(s, dict) and isinstance(s.get('season_number'), int)
        }
        return out

    def season(self, tmdb_id: Any, season_number: int) -> Optional[Dict[int, Dict[str, Any]]]:
        """Every episode of one season: {number: {'title', 'air_date'}}. None when unknown."""
        ok, payload, _ = self._get(f"/tv/{int(tmdb_id)}/season/{int(season_number)}",
                                   {'language': self.language})
        if not ok or not isinstance(payload, dict):
            return None
        out: Dict[int, Dict[str, Any]] = {}
        for episode in payload.get('episodes') or []:
            if not isinstance(episode, dict) or not isinstance(episode.get('episode_number'), int):
                continue
            out[episode['episode_number']] = {
                'title': (episode.get('name') or '').strip(),
                'air_date': episode.get('air_date') or None,
            }
        return out


def _show(row: Dict[str, Any]) -> Dict[str, Any]:
    first = row.get('first_air_date') or ''
    year = int(first[:4]) if first[:4].isdigit() else None
    return {
        'tmdb_id': row.get('id'),
        'name': row.get('name') or row.get('original_name') or '',
        'year': year,
        'first_air_date': first or None,
        'overview': (row.get('overview') or '')[:240],
        'poster_path': row.get('poster_path'),
    }


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
