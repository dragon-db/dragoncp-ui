#!/usr/bin/env python3
"""
Prowlarr's answers, in the shape the Search and Indexers tabs show.

Plain functions of what Prowlarr said and the time, so every case can be
tested without a server. A release's download address, magnet address and
guid never appear in a view: the first two carry Prowlarr's API key, and for
some trackers the guid carries the operator's passkey. They stay on the server
and the page names a release by its place in the search.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

#: Search types Prowlarr understands, and the capability list that says an
#: indexer supports each.
SEARCH_TYPES = {
    'search': 'searchParams',
    'tvsearch': 'tvSearchParams',
    'movie': 'movieSearchParams',
    'music': 'musicSearchParams',
    'book': 'bookSearchParams',
}


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _url(value: Any) -> Optional[str]:
    text = str(value or '').strip()
    return text if text.startswith(('http://', 'https://')) else None


def parse_time(value: Any) -> Optional[datetime]:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(value: Any) -> Optional[str]:
    return stamp(parse_time(value))


# --------------------------------------------------------------- releases

def release_view(raw: Dict[str, Any], release_id: int) -> Dict[str, Any]:
    """One search result, without anything that could carry a credential."""
    protocol = str(raw.get('protocol') or '').lower()
    categories = [c for c in raw.get('categories') or [] if isinstance(c, dict)]
    flags = raw.get('indexerFlags') or []
    magnet = str(raw.get('magnetUrl') or '')
    return {
        'id': release_id,
        'title': str(raw.get('title') or raw.get('fileName') or 'Untitled release'),
        'size': _int(raw.get('size')),
        'published': iso(raw.get('publishDate')),
        'grabs': _int(raw.get('grabs')),
        'files': _int(raw.get('files')),
        'seeders': _int(raw.get('seeders')) if protocol == 'torrent' else None,
        'leechers': _int(raw.get('leechers')) if protocol == 'torrent' else None,
        'protocol': protocol if protocol in ('torrent', 'usenet') else 'unknown',
        'indexer_id': _int(raw.get('indexerId')),
        'indexer': str(raw.get('indexer') or ''),
        'categories': [str(c.get('name') or '') for c in categories if c.get('name')],
        'category_ids': [cid for cid in (_int(c.get('id')) for c in categories) if cid is not None],
        'flags': sorted({str(f).strip().lower() for f in flags if str(f).strip()}),
        'info_url': _url(raw.get('infoUrl')) or _url(raw.get('commentUrl')),
        'info_hash': str(raw.get('infoHash') or '').lower() or None,
        'imdb_id': _int(raw.get('imdbId')) or None,
        'tmdb_id': _int(raw.get('tmdbId')) or None,
        'tvdb_id': _int(raw.get('tvdbId')) or None,
        'can_download': bool(raw.get('downloadUrl')),
        'can_magnet': bool(magnet) or (protocol == 'torrent' and bool(raw.get('downloadUrl'))),
        'grabbed': False,
    }


def release_private(raw: Dict[str, Any]) -> Dict[str, Any]:
    """What the server keeps of a release to download or grab it later."""
    return {
        'guid': str(raw.get('guid') or ''),
        'indexer_id': _int(raw.get('indexerId')),
        'download_url': str(raw.get('downloadUrl') or ''),
        'magnet_url': str(raw.get('magnetUrl') or ''),
        'protocol': str(raw.get('protocol') or '').lower(),
        'title': str(raw.get('title') or ''),
        'file_name': str(raw.get('fileName') or ''),
    }


# --------------------------------------------------------------- indexers

def _category_tree(capabilities: Dict[str, Any]) -> List[Dict[str, Any]]:
    tree = []
    for top in capabilities.get('categories') or []:
        if not isinstance(top, dict) or _int(top.get('id')) is None:
            continue
        subs = [_int(s.get('id')) for s in top.get('subCategories') or [] if isinstance(s, dict)]
        tree.append({'id': _int(top.get('id')), 'name': str(top.get('name') or ''),
                     'subs': [s for s in subs if s is not None]})
    return tree


def covers_categories(tree: Iterable[Dict[str, Any]], wanted: Iterable[int]) -> bool:
    """Whether an indexer has any of the wanted categories.

    A standard top-level category (2000 Movies) covers its subcategories
    (2040 Movies/HD) and the other way round, which is how Prowlarr itself
    decides which indexers a category search goes to. An indexer that lists
    no categories at all is given the benefit of the doubt.
    """
    wanted = [int(w) for w in wanted]
    tree = list(tree)
    if not wanted or not tree:
        return True
    have = set()
    for top in tree:
        have.add(top['id'])
        have.update(top['subs'])
    for want in wanted:
        if want in have:
            return True
        parent = want // 1000 * 1000
        if parent in have:
            return True
        if want % 1000 == 0 and any(h // 1000 * 1000 == want for h in have if h < 100000):
            return True
    return False


def indexer_view(raw: Dict[str, Any], status: Optional[Dict[str, Any]],
                 stats: Optional[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """One indexer: what it is, whether it works now, and how it has done lately."""
    capabilities = raw.get('capabilities') if isinstance(raw.get('capabilities'), dict) else {}
    tree = _category_tree(capabilities)
    enabled = bool(raw.get('enable'))
    paused_until = parse_time((status or {}).get('disabledTill'))
    failing_since = parse_time((status or {}).get('initialFailure'))
    last_failure = parse_time((status or {}).get('mostRecentFailure'))
    if not enabled:
        state = 'off'
    elif paused_until and paused_until > now:
        state = 'paused'
    elif last_failure and failing_since:
        # Failed recently but the pause has run out: Prowlarr will try it
        # again, and the next failure pauses it for longer.
        state = 'failing'
    else:
        state = 'ok'

    queries = _int((stats or {}).get('numberOfQueries')) or 0
    failed = _int((stats or {}).get('numberOfFailedQueries')) or 0
    urls = [u for u in (raw.get('indexerUrls') or []) if _url(u)]
    return {
        'id': _int(raw.get('id')),
        'name': str(raw.get('name') or ''),
        'definition': str(raw.get('definitionName') or raw.get('implementationName') or ''),
        'protocol': str(raw.get('protocol') or '').lower() or 'unknown',
        'privacy': str(raw.get('privacy') or '').lower() or 'unknown',
        'enabled': enabled,
        'priority': _int(raw.get('priority')),
        'state': state,
        'paused_until': stamp(paused_until),
        'failing_since': stamp(failing_since),
        'last_failure': stamp(last_failure),
        'site': urls[0] if urls else None,
        'categories': [{'id': t['id'], 'name': t['name']} for t in tree],
        'category_tree': tree,
        'search_types': [kind for kind, key in SEARCH_TYPES.items() if capabilities.get(key)],
        'stats': {
            'queries': queries,
            'grabs': _int((stats or {}).get('numberOfGrabs')) or 0,
            'failed_queries': failed,
            'failed_grabs': _int((stats or {}).get('numberOfFailedGrabs')) or 0,
            'avg_ms': _int((stats or {}).get('averageResponseTime')),
            'failure_rate': round(failed / queries, 3) if queries else None,
        } if stats else None,
    }


def stamp(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') if value else None


def health_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(raw.get('type') or '').lower()
    return {
        'source': str(raw.get('source') or ''),
        'level': kind if kind in ('ok', 'notice', 'warning', 'error') else 'warning',
        'message': str(raw.get('message') or ''),
        'wiki_url': _url(raw.get('wikiUrl')),
    }


def client_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': _int(raw.get('id')),
        'name': str(raw.get('name') or ''),
        'protocol': str(raw.get('protocol') or '').lower() or 'unknown',
        'enabled': bool(raw.get('enable')),
        'priority': _int(raw.get('priority')),
        'kind': str(raw.get('implementationName') or raw.get('implementation') or ''),
        # The category a release goes in: one mapped to its own category, else
        # the client's default. Shown so the operator can see what Sonarr and
        # Radarr will find there.
        'category': str(next((f.get('value') for f in raw.get('fields') or []
                              if isinstance(f, dict) and f.get('name') == 'category'), '') or ''),
        'mappings': [
            {'category': str(m.get('clientCategory') or ''),
             'ids': [i for i in (_int(c) for c in m.get('categories') or []) if i is not None]}
            for m in raw.get('categories') or [] if isinstance(m, dict) and m.get('clientCategory')
        ],
    }
