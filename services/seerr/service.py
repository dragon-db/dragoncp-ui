#!/usr/bin/env python3
"""
Seerr, for the people running it: requests waiting for approval, where the
approved ones have got to, and the issues users reported.

Seerr is asked when a page asks, and its answers are kept for a few seconds so
two tabs or a quick refresh do not ask twice. Its webhook and DragonCP's own
changes drop those answers at once, so what the page shows next is current.

Changes (approve, decline, retry, reply, resolve, reopen) all pass one guard:
on a test instance they are refused unless "Allow changes from this instance"
is on, because approving from the beta starts a real download on the remote
server. Every change, and every refusal, goes into the activity log.
"""

import hmac
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from activity_log import record, record_failure, record_refusal
from env_flags import test_mode_enabled
from services.seerr.arrivals import arrivals_for, sqlite_time
from services.seerr.titles import TitleCache, from_seerr
from services.seerr.views import (
    MEDIA_AVAILABLE,
    issue_view,
    iso,
    person,
    request_view,
)

log = logging.getLogger('dragoncp.seerr')

#: How long one of Seerr's answers is reused. Download progress in it moves
#: once a minute (Seerr's own refresh), so this costs nothing in freshness.
LIST_SECONDS = 20.0
COUNT_SECONDS = 60.0
USERS_SECONDS = 600.0
EPISODES_SECONDS = 600.0
#: Titles named per page load before the rest wait for the next one.
TITLE_LOOKUPS_PER_PAGE = 30
LOOKUP_WORKERS = 4

POLL_INTERVAL = 300.0
#: While Seerr is not answering: 5, 10, then every 15 minutes.
POLL_BACKOFF = (300.0, 600.0, 900.0)

#: The Requests tab's filters, in Seerr's words.
REQUEST_FILTERS = {
    'waiting': 'pending',
    'progress': 'processing',
    'failed': 'failed',
    'done': 'completed',
    'all': 'all',
}
ISSUE_FILTERS = ('open', 'resolved', 'all')
MAX_MESSAGE = 2000

#: Which tab a webhook concerns, from Seerr's notification type.
_ISSUE_EVENTS = ('ISSUE_CREATED', 'ISSUE_COMMENT', 'ISSUE_RESOLVED', 'ISSUE_REOPENED')


def _default_connectors():
    from services.connectors import get_service
    return get_service()


def _page(data: Any) -> Tuple[List[Dict[str, Any]], int]:
    if not isinstance(data, dict):
        return [], 0
    results = [r for r in data.get('results') or [] if isinstance(r, dict)]
    info = data.get('pageInfo') or {}
    total = info.get('results') if isinstance(info, dict) else None
    return results, int(total) if isinstance(total, int) else len(results)


class SeerrService:
    def __init__(self, db_manager, *, connectors: Callable[[], Any] = _default_connectors,
                 jellyfin: Optional[Callable[[], Any]] = None, socketio=None,
                 clock: Callable[[], float] = time.time,
                 test_mode: Callable[[], bool] = test_mode_enabled):
        self.db = db_manager
        self.titles = TitleCache(db_manager, clock=clock)
        self._connectors = connectors
        self._jellyfin = jellyfin or (lambda: None)
        self.socketio = socketio
        self.clock = clock
        self._test_mode = test_mode
        self._lock = threading.Lock()
        self._cache: Dict[Any, Tuple[float, Any]] = {}
        self._episodes: Dict[str, Tuple[float, Optional[Dict[int, int]]]] = {}
        self._last_webhook: Optional[Dict[str, Any]] = None
        self._last_counts: Optional[Tuple[int, int]] = None
        self._failures = 0

    # ------------------------------------------------------------- adapter

    def adapter(self):
        """Seerr's adapter while it is switched on and configured, else None."""
        try:
            service = self._connectors()
            if service is None:
                return None
            row = service.store.get_connector('seerr')
            if not row or not row.get('enabled'):
                return None
            adapter = service.adapter('seerr')
            return adapter if adapter is not None and adapter.is_configured() else None
        except Exception:  # noqa: BLE001 - "cannot tell" reads as "not connected"
            return None

    def can_change(self, adapter=None) -> Tuple[bool, str]:
        adapter = adapter or self.adapter()
        if adapter is None:
            return False, 'Seerr is off or not set up in DragonCP.'
        if self._test_mode() and not adapter.allows_changes():
            return False, ('This is a test instance, so changes in Seerr are off. Switch on '
                           '"Allow changes from this instance" on the Connection tab first.')
        return True, ''

    # --------------------------------------------------------------- cache

    def _cached(self, key: Any, ttl: float, fetch: Callable[[], Any]):
        now = self.clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        answer = fetch()
        if getattr(answer, 'ok', False):
            with self._lock:
                self._cache[key] = (now, answer)
        return answer

    def forget(self) -> None:
        """Drop every kept answer; the next page load asks Seerr again."""
        with self._lock:
            self._cache.clear()

    def _changed(self, kind: str, **detail) -> None:
        self.forget()
        if self.socketio is not None:
            try:
                self.socketio.emit('seerr_changed', {'kind': kind, **detail})
            except Exception:  # noqa: BLE001 - a missed push is not a failed change
                log.debug('Could not announce a Seerr change', exc_info=True)

    # ------------------------------------------------------------- summary

    def summary(self) -> Dict[str, Any]:
        """The counts for the tabs and the sidebar, and what this instance may do."""
        adapter = self.adapter()
        allowed, why = self.can_change(adapter)
        base = {
            'can_change': allowed, 'why_not': why, 'test_mode': self._test_mode(),
            'webhook': self.webhook_state(adapter),
            'polling': bool(adapter is not None and adapter.polls()),
        }
        if adapter is None:
            return {**base, 'state': 'off', 'message': 'Seerr is off or not set up yet.',
                    'requests': None, 'issues': None}
        requests = self._cached('request_count', COUNT_SECONDS, adapter.request_counts)
        issues = self._cached('issue_count', COUNT_SECONDS, adapter.issue_counts)
        if not requests.ok:
            return {**base, 'state': 'unreachable', 'message': requests.error,
                    'requests': None, 'issues': None}
        counts = requests.data if isinstance(requests.data, dict) else {}
        issue_counts = issues.data if issues.ok and isinstance(issues.data, dict) else {}
        return {
            **base, 'state': 'ok', 'message': '',
            'requests': {k: int(counts.get(k) or 0) for k in
                         ('pending', 'processing', 'approved', 'declined', 'completed',
                          'available', 'total', 'movie', 'tv')},
            'issues': {k: int(issue_counts.get(k) or 0) for k in
                       ('open', 'closed', 'total', 'video', 'audio', 'subtitles', 'others')}
                      if issue_counts else None,
        }

    def webhook_state(self, adapter=None) -> Dict[str, Any]:
        adapter = adapter if adapter is not None else self.adapter()
        last = self._last_webhook or {}
        return {
            'password_set': bool(adapter is not None and adapter.webhook_secret()),
            'last_at': last.get('at'),
            'last_type': last.get('type'),
            'path': '/api/webhook/seerr',
        }

    # ------------------------------------------------------------- titles

    def _titles_for(self, adapter, keys: List[Tuple[str, int]]) -> Dict[Tuple[str, int], Dict]:
        keys = [(t, int(i)) for t, i in keys if t in ('movie', 'tv') and isinstance(i, int)]
        known = self.titles.get_many(keys)
        wanted = [k for k in dict.fromkeys(keys) if not self.titles.is_fresh(known.get(k))]
        wanted = wanted[:TITLE_LOOKUPS_PER_PAGE]
        if not wanted:
            return known

        def look(key):
            answer = adapter.title(*key)
            return key, from_seerr(key[0], answer.data) if answer.ok else None

        with ThreadPoolExecutor(max_workers=LOOKUP_WORKERS) as pool:
            for key, row in pool.map(look, wanted):
                if row is not None:
                    try:
                        known[key] = self.titles.put(key[0], key[1], row)
                    except Exception:  # noqa: BLE001 - a name not kept is asked again
                        known[key] = row
        return known

    def _label(self, media_type: str, tmdb_id: Any) -> str:
        """A title as a person would say it, for the activity log."""
        row = None
        if isinstance(tmdb_id, int):
            row = self.titles.get_many([(media_type, tmdb_id)]).get((media_type, tmdb_id))
        if row and row.get('title'):
            return f"{row['title']} ({row['year']})" if row.get('year') else row['title']
        return f"{'a film' if media_type == 'movie' else 'a series'} (TMDB {tmdb_id})"

    # ----------------------------------------------------------- episodes

    def _episodes_for(self, jellyfin_ids: List[str]) -> Dict[str, Optional[Dict[int, int]]]:
        jellyfin_ids = [j for j in dict.fromkeys(jellyfin_ids) if j]
        if not jellyfin_ids:
            return {}
        jellyfin = None
        try:
            jellyfin = self._jellyfin()
        except Exception:  # noqa: BLE001 - no Jellyfin means no counts, not an error
            jellyfin = None
        if jellyfin is None:
            return {}
        now = self.clock()
        found: Dict[str, Optional[Dict[int, int]]] = {}
        wanted = []
        for jid in jellyfin_ids:
            hit = self._episodes.get(jid)
            if hit and now - hit[0] < EPISODES_SECONDS:
                found[jid] = hit[1]
            else:
                wanted.append(jid)
        if wanted:
            with ThreadPoolExecutor(max_workers=LOOKUP_WORKERS) as pool:
                for jid, counts in zip(wanted, pool.map(jellyfin.episode_counts, wanted)):
                    self._episodes[jid] = (now, counts)
                    found[jid] = counts
        return found

    # ------------------------------------------------------------ requests

    def requests(self, *, view: str = 'waiting', take: int = 20, skip: int = 0,
                 sort: str = 'added', media_type: str = 'all',
                 requested_by: Optional[int] = None) -> Dict[str, Any]:
        adapter = self.adapter()
        allowed, why = self.can_change(adapter)
        base = {'can_change': allowed, 'why_not': why, 'requests': [], 'total': 0}
        if adapter is None:
            return {**base, 'state': 'off', 'message': 'Seerr is off or not set up yet.'}
        seerr_filter = REQUEST_FILTERS.get(view, 'pending')
        sort = 'modified' if sort == 'modified' else 'added'
        media_type = media_type if media_type in ('movie', 'tv') else 'all'
        key = ('requests', seerr_filter, take, skip, sort, media_type, requested_by)
        answer = self._cached(key, LIST_SECONDS, lambda: adapter.requests(
            filter=seerr_filter, take=take, skip=skip, sort=sort,
            media_type=media_type, requested_by=requested_by))
        if not answer.ok:
            return {**base, 'state': 'unreachable', 'message': answer.error}
        rows, total = _page(answer.data)
        return {**base, 'state': 'ok', 'message': '', 'total': total,
                'requests': self._request_views(adapter, rows)}

    def _request_views(self, adapter, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = self.clock()
        keys = []
        for raw in rows:
            media = raw.get('media') or {}
            keys.append((raw.get('type') or media.get('mediaType'), media.get('tmdbId')))
        titles = self._titles_for(adapter, keys)

        def unfinished_tv(raw):
            media = raw.get('media') or {}
            status = media.get('status4k' if raw.get('is4k') else 'status')
            return raw.get('type') == 'tv' and raw.get('status') in (2, 5) and status != MEDIA_AVAILABLE

        jellyfin_ids = []
        for raw in rows:
            media = raw.get('media') or {}
            if unfinished_tv(raw):
                jellyfin_ids.append(media.get('jellyfinMediaId4k' if raw.get('is4k') else 'jellyfinMediaId'))
        episodes = self._episodes_for(jellyfin_ids)

        views = []
        for raw, key in zip(rows, keys):
            media = raw.get('media') or {}
            arrivals = []
            if raw.get('status') in (2, 5):
                arrivals = arrivals_for(self.db, key[0], tvdb_id=media.get('tvdbId'),
                                        tmdb_id=media.get('tmdbId'),
                                        since=sqlite_time(raw.get('createdAt')))
            jid = media.get('jellyfinMediaId4k' if raw.get('is4k') else 'jellyfinMediaId')
            here = episodes.get(jid) if unfinished_tv(raw) and jid in episodes else None
            try:
                views.append(request_view(raw, title=titles.get(key), arrivals=arrivals,
                                          episodes_here=here, now=now))
            except Exception:  # noqa: BLE001 - one odd row must not empty the page
                log.exception('Could not read Seerr request %s', raw.get('id'))
        return views

    def request(self, request_id: int) -> Dict[str, Any]:
        adapter = self.adapter()
        if adapter is None:
            return {'ok': False, 'error': 'Seerr is off or not set up yet.', 'status': 409}
        answer = adapter.request_one(request_id)
        if not answer.ok or not isinstance(answer.data, dict):
            return {'ok': False, 'error': answer.error or 'Seerr did not answer', 'status': 502}
        views = self._request_views(adapter, [answer.data])
        return {'ok': True, 'request': views[0] if views else None}

    def request_options(self, request_id: int, server_id: Optional[int] = None) -> Dict[str, Any]:
        """What can be changed before approving: server, quality, folder, seasons.

        Asking Seerr for one server's choices makes Seerr ask that Sonarr or
        Radarr (on the remote server) live, so this is only fetched when the
        operator opens "Change before approving".
        """
        adapter = self.adapter()
        if adapter is None:
            return {'ok': False, 'error': 'Seerr is off or not set up yet.', 'status': 409}
        current = adapter.request_one(request_id)
        if not current.ok or not isinstance(current.data, dict):
            return {'ok': False, 'error': current.error or 'Seerr did not answer', 'status': 502}
        raw = current.data
        media_type = raw.get('type') or 'movie'
        kind = 'sonarr' if media_type == 'tv' else 'radarr'
        servers_answer = self._cached(('services', kind), USERS_SECONDS,
                                      lambda: adapter.services(kind))
        if not servers_answer.ok:
            return {'ok': False, 'error': servers_answer.error, 'status': 502}
        is4k = bool(raw.get('is4k'))
        servers = [s for s in servers_answer.data or [] if isinstance(s, dict)
                   and bool(s.get('is4k')) == is4k]
        chosen = server_id if server_id is not None else raw.get('serverId')
        if chosen is None or not any(s.get('id') == chosen for s in servers):
            default = next((s for s in servers if s.get('isDefault')), servers[0] if servers else None)
            chosen = default.get('id') if default else None
        detail = {}
        if chosen is not None:
            answer = adapter.service_detail(kind, chosen)
            if not answer.ok:
                return {'ok': False, 'error': answer.error, 'status': 502}
            detail = answer.data if isinstance(answer.data, dict) else {}
        server = detail.get('server') or {}
        title = self._titles_for(adapter, [(media_type, (raw.get('media') or {}).get('tmdbId'))])
        title = title.get((media_type, (raw.get('media') or {}).get('tmdbId'))) or {}
        requested = {s.get('seasonNumber') for s in raw.get('seasons') or [] if isinstance(s, dict)}
        media_seasons = {s.get('seasonNumber'): s.get('status4k' if is4k else 'status')
                         for s in (raw.get('media') or {}).get('seasons') or [] if isinstance(s, dict)}
        seasons = [{'number': n, 'episodes': c, 'requested': n in requested,
                    'available': media_seasons.get(n) == MEDIA_AVAILABLE}
                   for n, c in (title.get('seasons') or []) if isinstance(n, int)]
        if not seasons:
            seasons = [{'number': n, 'episodes': None, 'requested': True, 'available': False}
                       for n in sorted(x for x in requested if isinstance(x, int))]
        return {
            'ok': True,
            'service': kind,
            'servers': [{'id': s.get('id'), 'name': s.get('name') or f"Server {s.get('id')}",
                         'is_default': bool(s.get('isDefault'))} for s in servers],
            'server_id': chosen,
            'profiles': [{'id': p.get('id'), 'name': p.get('name')}
                         for p in detail.get('profiles') or [] if isinstance(p, dict)],
            'root_folders': [{'path': f.get('path'), 'free_bytes': f.get('freeSpace')}
                             for f in detail.get('rootFolders') or [] if isinstance(f, dict)],
            'current': {
                'profile_id': raw.get('profileId') if raw.get('serverId') == chosen
                else server.get('activeProfileId'),
                'root_folder': raw.get('rootFolder') if raw.get('serverId') == chosen
                else server.get('activeDirectory'),
            },
            'seasons': seasons if media_type == 'tv' else [],
        }

    # ------------------------------------------------------------- changes

    def _writable(self, action: str, label: str, target: str, target_id: Any):
        adapter = self.adapter()
        if adapter is None:
            return None, {'ok': False, 'error': 'Seerr is off or not set up yet.', 'status': 409}
        allowed, why = self.can_change(adapter)
        if not allowed:
            record_refusal(action, f"Refused to {label}: changes are off on this test instance",
                           target_type=target, target_id=str(target_id))
            return None, {'ok': False, 'error': why, 'status': 403}
        return adapter, None

    def _request_words(self, raw: Dict[str, Any]) -> Tuple[str, str]:
        media = raw.get('media') or {}
        media_type = raw.get('type') or media.get('mediaType') or 'movie'
        label = self._label(media_type, media.get('tmdbId'))
        who = ((raw.get('requestedBy') or {}).get('displayName')
               or (raw.get('requestedBy') or {}).get('jellyfinUsername') or 'someone')
        seasons = sorted(s.get('seasonNumber') for s in raw.get('seasons') or []
                         if isinstance(s, dict) and isinstance(s.get('seasonNumber'), int))
        if media_type == 'tv' and seasons:
            label = f"{label}, season{'s' if len(seasons) > 1 else ''} {', '.join(map(str, seasons))}"
        return label, who

    def decide(self, request_id: int, decision: str,
               changes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Approve or decline a waiting request, or retry a failed one."""
        verbs = {'approve': ('seerr.request_approve', 'approve', 'Approved'),
                 'decline': ('seerr.request_decline', 'decline', 'Declined'),
                 'retry': ('seerr.request_retry', 'retry', 'Retried')}
        if decision not in verbs:
            return {'ok': False, 'error': f"Unknown action: {decision}", 'status': 400}
        action, verb, done = verbs[decision]
        adapter, refusal = self._writable(action, f"{verb} Seerr request {request_id}",
                                          'seerr_request', request_id)
        if refusal:
            return refusal
        current = adapter.request_one(request_id)
        if not current.ok or not isinstance(current.data, dict):
            return {'ok': False, 'error': current.error or 'Seerr did not answer', 'status': 502}
        raw = current.data
        label, who = self._request_words(raw)
        expected = {'approve': 1, 'decline': 1, 'retry': 4}[decision]
        if raw.get('status') != expected:
            state = {1: 'waiting', 2: 'already approved', 3: 'already declined',
                     4: 'failed', 5: 'already done'}.get(raw.get('status'), 'changed')
            return {'ok': False, 'status': 409,
                    'error': f"This request is {state} in Seerr now. The list has been refreshed."}

        edited = ''
        if changes and decision == 'approve':
            body, problem = self._edit_body(raw, changes)
            if problem:
                return {'ok': False, 'error': problem, 'status': 400}
            if body is not None:
                updated = adapter.update_request(request_id, body)
                if not updated.ok:
                    record_failure(action, f"Could not change the request for {label} before approving",
                                   target_type='seerr_request', target_id=str(request_id),
                                   target_label=label, detail={'error': updated.error})
                    self._changed('request', id=request_id)
                    return {'ok': False, 'error': updated.error, 'status': 502}
                edited = ' (with changes)'
                # Name what was approved, not what was first asked for.
                label, who = self._request_words(dict(raw, seasons=[
                    {'seasonNumber': n} for n in body.get('seasons') or []
                ]) if body.get('seasons') else raw)

        if decision == 'retry':
            answer = adapter.retry_request(request_id)
        else:
            answer = adapter.set_request_status(request_id, decision)
        self._changed('request', id=request_id)
        if not answer.ok:
            record_failure(action, f"Could not {verb} the request for {label} by {who}",
                           target_type='seerr_request', target_id=str(request_id),
                           target_label=label, detail={'error': answer.error})
            return {'ok': False, 'error': answer.error, 'status': 502}
        record(action, f"{done} the request for {label} by {who}{edited}",
               target_type='seerr_request', target_id=str(request_id), target_label=label,
               detail={'changes': changes} if edited else None)
        return {'ok': True}

    @staticmethod
    def _edit_body(raw: Dict[str, Any], changes: Dict[str, Any]):
        """Seerr's edit replaces every field, so unchanged ones are sent as they are."""
        if not isinstance(changes, dict):
            return None, 'Changes must be an object'
        media_type = raw.get('type') or 'movie'
        body = {
            'mediaType': media_type,
            'serverId': raw.get('serverId'),
            'profileId': raw.get('profileId'),
            'rootFolder': raw.get('rootFolder'),
            'languageProfileId': raw.get('languageProfileId'),
            'tags': raw.get('tags') if isinstance(raw.get('tags'), list) else [],
            'userId': (raw.get('requestedBy') or {}).get('id'),
        }
        changed = False
        for field, key in (('server_id', 'serverId'), ('profile_id', 'profileId')):
            if changes.get(field) is not None:
                try:
                    value = int(changes[field])
                except (TypeError, ValueError):
                    return None, f"{field} must be a number"
                changed = changed or value != body[key]
                body[key] = value
        if changes.get('root_folder') is not None:
            folder = str(changes['root_folder']).strip()
            if not folder or len(folder) > 500:
                return None, 'root_folder must be a folder path'
            changed = changed or folder != body['rootFolder']
            body['rootFolder'] = folder
        if media_type == 'tv':
            current = sorted(s.get('seasonNumber') for s in raw.get('seasons') or []
                             if isinstance(s, dict) and isinstance(s.get('seasonNumber'), int))
            seasons = current
            if changes.get('seasons') is not None:
                try:
                    seasons = sorted({int(n) for n in changes['seasons']})
                except (TypeError, ValueError):
                    return None, 'seasons must be a list of season numbers'
                if not seasons or any(n < 0 for n in seasons):
                    return None, 'Pick at least one season'
                changed = changed or seasons != current
            body['seasons'] = seasons
        return (body if changed else None), ''

    # -------------------------------------------------------------- issues

    def issues(self, *, view: str = 'open', take: int = 20, skip: int = 0,
               sort: str = 'added', created_by: Optional[int] = None) -> Dict[str, Any]:
        adapter = self.adapter()
        allowed, why = self.can_change(adapter)
        base = {'can_change': allowed, 'why_not': why, 'issues': [], 'total': 0}
        if adapter is None:
            return {**base, 'state': 'off', 'message': 'Seerr is off or not set up yet.'}
        view = view if view in ISSUE_FILTERS else 'open'
        sort = 'modified' if sort == 'modified' else 'added'
        key = ('issues', view, take, skip, sort, created_by)
        answer = self._cached(key, LIST_SECONDS, lambda: adapter.issues(
            filter=view, take=take, skip=skip, sort=sort, created_by=created_by))
        if not answer.ok:
            return {**base, 'state': 'unreachable', 'message': answer.error}
        rows, total = _page(answer.data)
        return {**base, 'state': 'ok', 'message': '', 'total': total,
                'issues': self._issue_views(adapter, rows)}

    def _issue_views(self, adapter, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        keys = [((r.get('media') or {}).get('mediaType'), (r.get('media') or {}).get('tmdbId'))
                for r in rows]
        titles = self._titles_for(adapter, keys)
        views = []
        for raw, key in zip(rows, keys):
            try:
                views.append(issue_view(raw, title=titles.get(key)))
            except Exception:  # noqa: BLE001 - one odd row must not empty the page
                log.exception('Could not read Seerr issue %s', raw.get('id'))
        return views

    def issue(self, issue_id: int) -> Dict[str, Any]:
        adapter = self.adapter()
        if adapter is None:
            return {'ok': False, 'error': 'Seerr is off or not set up yet.', 'status': 409}
        answer = adapter.issue_one(issue_id)
        if not answer.ok or not isinstance(answer.data, dict):
            return {'ok': False, 'error': answer.error or 'Seerr did not answer', 'status': 502}
        views = self._issue_views(adapter, [answer.data])
        allowed, why = self.can_change(adapter)
        return {'ok': True, 'issue': views[0] if views else None,
                'can_change': allowed, 'why_not': why}

    def _issue_words(self, adapter, issue_id: int) -> Tuple[Optional[Dict[str, Any]], str]:
        answer = adapter.issue_one(issue_id)
        if not answer.ok or not isinstance(answer.data, dict):
            return None, answer.error or 'Seerr did not answer'
        raw = answer.data
        media = raw.get('media') or {}
        label = self._label(media.get('mediaType') or 'movie', media.get('tmdbId'))
        season, episode = raw.get('problemSeason') or 0, raw.get('problemEpisode') or 0
        if season:
            label = f"{label} S{season:02d}" + (f"E{episode:02d}" if episode else '')
        return raw, label

    def reply(self, issue_id: int, message: str, *, resolve: bool = False) -> Dict[str, Any]:
        message = (message or '').strip()
        if not message:
            return {'ok': False, 'error': 'Write something to send', 'status': 400}
        if len(message) > MAX_MESSAGE:
            return {'ok': False, 'error': f"Keep it under {MAX_MESSAGE} characters", 'status': 400}
        adapter, refusal = self._writable('seerr.issue_comment', f"reply to Seerr issue {issue_id}",
                                          'seerr_issue', issue_id)
        if refusal:
            return refusal
        raw, label = self._issue_words(adapter, issue_id)
        if raw is None:
            return {'ok': False, 'error': label, 'status': 502}
        answer = adapter.comment(issue_id, message)
        if not answer.ok:
            self._changed('issue', id=issue_id)
            record_failure('seerr.issue_comment', f"Could not reply to the issue on {label}",
                           target_type='seerr_issue', target_id=str(issue_id), target_label=label,
                           detail={'error': answer.error})
            return {'ok': False, 'error': answer.error, 'status': 502}
        record('seerr.issue_comment', f"Replied to the issue on {label}",
               target_type='seerr_issue', target_id=str(issue_id), target_label=label)
        if resolve:
            result = self._set_issue(adapter, issue_id, 'resolved', label)
            if not result['ok']:
                result['error'] = f"The reply was sent, but resolving failed: {result['error']}"
                return result
        self._changed('issue', id=issue_id)
        return {'ok': True}

    def set_issue(self, issue_id: int, status: str) -> Dict[str, Any]:
        if status not in ('resolved', 'open'):
            return {'ok': False, 'error': f"Unknown issue state: {status}", 'status': 400}
        action = 'seerr.issue_resolve' if status == 'resolved' else 'seerr.issue_reopen'
        verb = 'resolve' if status == 'resolved' else 'reopen'
        adapter, refusal = self._writable(action, f"{verb} Seerr issue {issue_id}",
                                          'seerr_issue', issue_id)
        if refusal:
            return refusal
        raw, label = self._issue_words(adapter, issue_id)
        if raw is None:
            return {'ok': False, 'error': label, 'status': 502}
        result = self._set_issue(adapter, issue_id, status, label)
        self._changed('issue', id=issue_id)
        return result

    def _set_issue(self, adapter, issue_id: int, status: str, label: str) -> Dict[str, Any]:
        action = 'seerr.issue_resolve' if status == 'resolved' else 'seerr.issue_reopen'
        answer = adapter.set_issue_status(issue_id, status)
        if not answer.ok:
            record_failure(action, f"Could not {'resolve' if status == 'resolved' else 'reopen'} "
                                   f"the issue on {label}",
                           target_type='seerr_issue', target_id=str(issue_id), target_label=label,
                           detail={'error': answer.error})
            return {'ok': False, 'error': answer.error, 'status': 502}
        record(action, f"{'Resolved' if status == 'resolved' else 'Reopened'} the issue on {label}",
               target_type='seerr_issue', target_id=str(issue_id), target_label=label)
        return {'ok': True}

    # --------------------------------------------------------------- users

    def users(self) -> List[Dict[str, Any]]:
        """Seerr's users by name, for the "who" filters. Nothing else about them."""
        adapter = self.adapter()
        if adapter is None:
            return []
        answer = self._cached('users', USERS_SECONDS, adapter.users)
        rows, _ = _page(answer.data) if answer.ok else ([], 0)
        people = [p for p in (person(r) for r in rows) if p]
        return sorted(people, key=lambda p: p['name'].lower())

    # ------------------------------------------------------------- webhook

    def webhook(self, authorization: str, payload: Any) -> Tuple[int, Dict[str, Any]]:
        """Seerr saying something changed. Only the password is checked; the
        body is a hint about which tab to refresh, never trusted beyond that."""
        adapter = self.adapter()
        if adapter is None:
            return 403, {'ok': False, 'error': 'Seerr is off in DragonCP'}
        secret = adapter.webhook_secret()
        if not secret:
            return 403, {'ok': False, 'error': 'No webhook password is set in DragonCP'}
        given = (authorization or '').strip()
        if given.lower().startswith('bearer '):
            given = given[7:].strip()
        if not hmac.compare_digest(given.encode('utf-8'), secret.encode('utf-8')):
            return 401, {'ok': False, 'error': 'Wrong webhook password'}
        kind_name = ''
        if isinstance(payload, dict):
            kind_name = str(payload.get('notification_type') or '').strip().upper()[:40]
        self._last_webhook = {'at': iso(self.clock()), 'type': kind_name or 'UNKNOWN'}
        if kind_name == 'TEST_NOTIFICATION':
            self._changed('test')
        elif kind_name in _ISSUE_EVENTS:
            self._changed('issue')
        else:
            self._changed('request')
        return 200, {'ok': True}

    # ----------------------------------------------------------- scheduler

    def interval(self) -> Optional[float]:
        adapter = self.adapter()
        if adapter is None or not adapter.polls():
            return None
        if self._failures:
            return POLL_BACKOFF[min(self._failures, len(POLL_BACKOFF)) - 1]
        return POLL_INTERVAL

    def run_job(self) -> Dict[str, Any]:
        adapter = self.adapter()
        if adapter is None:
            return {'ok': True, 'summary': 'Seerr is off'}
        requests = adapter.request_counts()
        issues = adapter.issue_counts()
        if not requests.ok:
            self._failures += 1
            return {'ok': False, 'summary': requests.error}
        self._failures = 0
        request_counts = requests.data if isinstance(requests.data, dict) else {}
        issue_counts = issues.data if issues.ok and isinstance(issues.data, dict) else {}
        waiting = int(request_counts.get('pending') or 0)
        open_issues = int(issue_counts.get('open') or 0)
        counts = (waiting, open_issues)
        with self._lock:
            self._cache['request_count'] = (self.clock(), requests)
            if issues.ok:
                self._cache['issue_count'] = (self.clock(), issues)
        if self._last_counts is not None and counts != self._last_counts:
            self._changed('poll')
        self._last_counts = counts
        return {'ok': True, 'waiting': waiting, 'open_issues': open_issues,
                'summary': f"{waiting} waiting, {open_issues} open issue{'s' if open_issues != 1 else ''}"}

    def scheduler_job(self):
        from services.scheduler import Job
        return Job(
            name='seerr_updates', label='Seerr updates',
            description=('Asks Seerr how many requests are waiting and how many issues are open, '
                         'in case a webhook went missing. Seerr is on this machine; nothing '
                         'reaches the remote server.'),
            interval=self.interval,
            run=self.run_job,
            first_run_delay=30.0,
        )
