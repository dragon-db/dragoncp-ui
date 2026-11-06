#!/usr/bin/env python3
"""
Seerr's rows, in the shape the Requests and Issues tabs show.

Everything here is a plain function of what Seerr said, what DragonCP's own
history says, and the time, so every case can be tested without a server.

Where an approved request is, in the order it gets there:

    approved  ->  downloaded on the remote server  ->  synced here  ->  in Jellyfin

Seerr only knows the first and the last; between them it says "processing".
The download comes from Seerr's own copy of the Sonarr/Radarr queue (refreshed
every minute by Seerr, so DragonCP asks the remote server nothing), the sync
from DragonCP's own arrivals and transfers.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from services.seerr.arrivals import SYNCING, TRANSFER_ACTIVE
from services.seerr.titles import poster_url

#: Seerr's request statuses.
REQUEST_STATUS = {1: 'pending', 2: 'approved', 3: 'declined', 4: 'failed', 5: 'completed'}
#: Seerr's media statuses.
MEDIA_UNKNOWN, MEDIA_PENDING, MEDIA_PROCESSING, MEDIA_PARTIAL, MEDIA_AVAILABLE = 1, 2, 3, 4, 5
MEDIA_BLOCKLISTED, MEDIA_DELETED = 6, 7
#: Seerr's issue types and statuses.
ISSUE_TYPE = {1: 'video', 2: 'audio', 3: 'subtitles', 4: 'other'}
ISSUE_STATUS = {1: 'open', 2: 'resolved'}

#: An approved request with nothing found after this long is flagged.
STUCK_AFTER_SECONDS = 3 * 24 * 3600

SEASON_STATE = {
    MEDIA_AVAILABLE: 'available',
    MEDIA_PARTIAL: 'partial',
    MEDIA_PROCESSING: 'processing',
    MEDIA_PENDING: 'pending',
    MEDIA_DELETED: 'deleted',
}


# ----------------------------------------------------------------- helpers

def epoch(value: Any) -> Optional[float]:
    """An ISO time (Seerr's, with Z), SQLite's UTC text or seconds, as seconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not value:
        return None
    text = str(value).strip()
    try:
        if 'T' in text:
            moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
        else:
            moment = datetime.strptime(text[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def iso(value: Any) -> Optional[str]:
    seconds = epoch(value)
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def person(user: Any) -> Optional[Dict[str, Any]]:
    """Who, by name only. Seerr's user rows carry e-mail and service tokens;
    none of that leaves the server."""
    if not isinstance(user, dict) or user.get('id') is None:
        return None
    name = (user.get('displayName') or user.get('jellyfinUsername') or user.get('username')
            or user.get('plexUsername') or '')
    name = str(name).strip() or f"User {user.get('id')}"
    return {'id': user.get('id'), 'name': name}


def days(seconds: float) -> str:
    whole = int(seconds // 86400)
    if whole >= 1:
        return f"{whole} day{'s' if whole != 1 else ''}"
    hours = int(seconds // 3600)
    if hours >= 1:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    minutes = max(1, int(seconds // 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def eta_text(seconds: Optional[float]) -> str:
    if seconds is None or seconds <= 0:
        return ''
    if seconds < 60:
        return 'under a minute left'
    return f"{days(seconds)} left"


def _title_block(raw_media: Dict[str, Any], media_type: str,
                 title: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    title = title or {}
    return {
        'tmdb_id': raw_media.get('tmdbId'),
        'tvdb_id': raw_media.get('tvdbId'),
        'type': media_type,
        'name': title.get('title') or '',
        'year': title.get('year'),
        'poster': poster_url(title.get('poster_path')),
    }


# ---------------------------------------------------------------- download

def download_block(items: Iterable[Any], now: float) -> Optional[Dict[str, Any]]:
    """Seerr's copy of the Sonarr/Radarr queue for one title, summed up."""
    items = [i for i in (items or []) if isinstance(i, dict)]
    if not items:
        return None
    by_download: Dict[str, Dict[str, Any]] = {}
    episodes: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        key = str(item.get('downloadId') or f"item-{index}")
        by_download.setdefault(key, item)
        episode = item.get('episode')
        if isinstance(episode, dict):
            episodes.append({'season': episode.get('seasonNumber'),
                             'episode': episode.get('episodeNumber')})
    size = sum(float(d.get('size') or 0) for d in by_download.values())
    left = sum(float(d.get('sizeLeft') or 0) for d in by_download.values())
    percent = int(round((size - left) / size * 100)) if size > 0 else None
    finishes = [epoch(d.get('estimatedCompletionTime')) for d in by_download.values()]
    remaining = [f - now for f in finishes if f and f > now]
    statuses = {str(d.get('status') or '').lower() for d in by_download.values()}
    if 'warning' in statuses or 'failed' in statuses:
        state = 'warning'
    elif statuses <= {'completed'} or (percent is not None and percent >= 100):
        state = 'importing'
    elif 'downloading' in statuses:
        state = 'downloading'
    elif statuses & {'paused'}:
        state = 'paused'
    else:
        state = 'queued'
    return {
        'state': state,
        'percent': percent,
        'eta_seconds': int(max(remaining)) if remaining and state == 'downloading' else None,
        'downloads': len(by_download),
        'episodes': sorted(episodes, key=lambda e: (e['season'] or 0, e['episode'] or 0)),
        'seasons': sorted({e['season'] for e in episodes if isinstance(e['season'], int)}),
    }


# -------------------------------------------------------------------- sync

def _fixed_later(failure: Dict[str, Any], done: List[Dict[str, Any]]) -> bool:
    """A failure stops counting once the same season syncs later. A sync that
    names no season (a whole series, or a film) covers every season."""
    after = failure['at'] or ''
    return any((d['at'] or '') > after
               and (d.get('season') is None or d.get('season') == failure.get('season'))
               for d in done)


def _season_numbers(rows: List[Dict[str, Any]]) -> List[int]:
    return sorted({r['season'] for r in rows if isinstance(r.get('season'), int)})


def sync_block(arrivals: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """DragonCP's side: arrived on the remote server, syncing, synced, held."""
    if not arrivals:
        return None
    held = [a for a in arrivals if a['status'] == 'pending' and a['held']]
    failed = [a for a in arrivals if a['status'] == 'failed']
    active = [a for a in arrivals
              if a['status'] in SYNCING
              or (a['transfer_status'] in TRANSFER_ACTIVE
                  and a['status'] not in ('completed', 'failed', 'cancelled'))]
    waiting = [a for a in arrivals if a['status'] == 'pending' and not a['held']
               and a['kind'] == 'arrival' and not a['transfer_status']]
    done = [a for a in arrivals if a['status'] == 'completed']
    last = arrivals[-1]
    failed = [f for f in failed if not _fixed_later(f, done)]
    # 'seasons' names the seasons in the state reported, so a season already
    # synced is not shown as syncing because another one is.
    if held:
        return {'state': 'held', 'reason': held[-1]['reason'] or '', 'seasons': _season_numbers(held),
                'at': iso(held[-1]['at'])}
    if active:
        current = active[-1]
        return {'state': 'syncing', 'percent': current.get('percent'),
                'eta_seconds': current.get('eta_seconds'), 'seasons': _season_numbers(active),
                'at': iso(current['at'])}
    if waiting:
        return {'state': 'arrived', 'seasons': _season_numbers(waiting), 'at': iso(waiting[-1]['at'])}
    if failed:
        return {'state': 'failed', 'seasons': _season_numbers(failed), 'at': iso(failed[-1]['at'])}
    if done:
        return {'state': 'synced', 'seasons': _season_numbers(done), 'at': iso(done[-1]['at'])}
    return {'state': 'arrived', 'seasons': _season_numbers(arrivals), 'at': iso(last['at'])}


# --------------------------------------------------------------- requests

def _seasons(raw: Dict[str, Any], is4k: bool, title: Optional[Dict[str, Any]],
             here: Optional[Dict[int, int]], download: Optional[Dict[str, Any]],
             sync: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    media = raw.get('media') or {}
    states = {}
    for season in media.get('seasons') or []:
        if isinstance(season, dict) and isinstance(season.get('seasonNumber'), int):
            states[season['seasonNumber']] = season.get('status4k' if is4k else 'status')
    totals = {n: c for n, c in ((title or {}).get('seasons') or []) if isinstance(n, int)}
    downloading = set((download or {}).get('seasons') or [])
    syncing = set((sync or {}).get('seasons') or []) if (sync or {}).get('state') == 'syncing' else set()
    rows = []
    for season in raw.get('seasons') or []:
        number = season.get('seasonNumber') if isinstance(season, dict) else None
        if not isinstance(number, int):
            continue
        rows.append({
            'number': number,
            'state': SEASON_STATE.get(states.get(number), 'waiting'),
            'episodes_total': totals.get(number),
            'episodes_here': (here or {}).get(number) if here is not None else None,
            'downloading': number in downloading,
            'syncing': number in syncing,
        })
    rows.sort(key=lambda s: s['number'])
    return rows


def _requested_seasons(raw: Dict[str, Any]) -> set:
    return {s.get('seasonNumber') for s in raw.get('seasons') or []
            if isinstance(s, dict) and isinstance(s.get('seasonNumber'), int)}


def _queue_season(item: Any) -> Optional[int]:
    episode = item.get('episode') if isinstance(item, dict) else None
    season = episode.get('seasonNumber') if isinstance(episode, dict) else None
    return season if isinstance(season, int) else None


def request_view(raw: Dict[str, Any], *, title: Optional[Dict[str, Any]] = None,
                 arrivals: Optional[List[Dict[str, Any]]] = None,
                 episodes_here: Optional[Dict[int, int]] = None,
                 now: float) -> Dict[str, Any]:
    """One Seerr request, with where it has got to, in words."""
    media = raw.get('media') or {}
    media_type = raw.get('type') or media.get('mediaType') or 'movie'
    is4k = bool(raw.get('is4k'))
    status = REQUEST_STATUS.get(raw.get('status'), 'unknown')
    media_status = media.get('status4k' if is4k else 'status')
    queue = media.get('downloadStatus4k' if is4k else 'downloadStatus') or []
    arrivals = arrivals or []
    requested = _requested_seasons(raw) if media_type == 'tv' else set()
    if requested:
        # The queue and the arrivals are the whole series'. A request for
        # season 2 must not read as synced because season 1 was. A row that
        # does not say its season (a whole-series sync) still counts.
        queue = [i for i in queue if _queue_season(i) in requested or _queue_season(i) is None]
        arrivals = [a for a in arrivals if a.get('season') in requested or a.get('season') is None]
    download = download_block(queue, now)
    sync = sync_block(arrivals)
    seasons = _seasons(raw, is4k, title, episodes_here, download, sync) if media_type == 'tv' else []
    requested_at = epoch(raw.get('createdAt'))
    decided_at = epoch(raw.get('updatedAt'))
    service = 'Sonarr' if media_type == 'tv' else 'Radarr'

    all_here = bool(seasons) and all(s['state'] == 'available' for s in seasons)
    available = media_status == MEDIA_AVAILABLE or status == 'completed' or all_here
    if seasons:
        # Partly here means part of what was asked for, not of the series.
        partial = any(s['state'] in ('available', 'partial') for s in seasons)
    else:
        partial = media_status == MEDIA_PARTIAL

    stage = _stage(status, available=available, partial=partial, download=download, sync=sync,
                   decided_at=decided_at, now=now, service=service, deleted=media_status == MEDIA_DELETED)
    steps = _steps(status, available=available, partial=partial, download=download,
                   sync=sync, stuck=bool(stage.get('stuck')))
    actions: List[str] = []
    if status == 'pending':
        actions = ['approve', 'decline']
    elif status == 'failed':
        actions = ['retry']

    return {
        'id': raw.get('id'),
        'status': status,
        'type': media_type,
        'is4k': is4k,
        'title': _title_block(media, media_type, title),
        'jellyfin_id': media.get('jellyfinMediaId4k' if is4k else 'jellyfinMediaId') or None,
        'seasons': seasons,
        'requested_by': person(raw.get('requestedBy')),
        'requested_at': iso(raw.get('createdAt')),
        'decided_by': person(raw.get('modifiedBy')),
        'updated_at': iso(raw.get('updatedAt')),
        'profile': raw.get('profileName') or None,
        'stage': stage,
        'steps': steps,
        'download': download,
        'sync': sync,
        'actions': actions,
        'requested_ago_seconds': int(now - requested_at) if requested_at else None,
    }


def _stage(status: str, *, available: bool, partial: bool, download, sync, decided_at,
           now: float, service: str, deleted: bool) -> Dict[str, Any]:
    """The one line that says where a request is now."""
    if status == 'pending':
        return {'key': 'waiting', 'label': 'Waiting for approval', 'tone': 'warn', 'detail': ''}
    if status == 'declined':
        return {'key': 'declined', 'label': 'Declined', 'tone': 'muted', 'detail': ''}
    if status == 'failed':
        return {'key': 'failed', 'label': 'Failed', 'tone': 'crit',
                'detail': f"Seerr could not hand it to {service}. Retry sends it again."}
    if deleted:
        return {'key': 'removed', 'label': 'Removed', 'tone': 'muted',
                'detail': 'Seerr says the title was removed from the library.'}
    if available:
        return {'key': 'in_jellyfin', 'label': 'In Jellyfin', 'tone': 'ok', 'detail': ''}
    sync_state = (sync or {}).get('state')
    if sync_state == 'held':
        reason = (sync or {}).get('reason') or 'the safety check held it back'
        return {'key': 'held', 'label': 'Needs you', 'tone': 'warn',
                'detail': f"On the remote server, not synced here: {reason}"}
    if sync_state == 'syncing':
        percent = (sync or {}).get('percent')
        left = eta_text((sync or {}).get('eta_seconds'))
        bits = [f"{percent}%" if isinstance(percent, int) else '', left]
        return {'key': 'syncing', 'label': 'Syncing here', 'tone': 'brand',
                'detail': ' · '.join(b for b in bits if b), 'percent': percent}
    if download:
        percent = download.get('percent')
        left = eta_text(download.get('eta_seconds'))
        words = {
            'downloading': 'Downloading',
            'importing': f"Downloaded, {service} is importing it",
            'paused': 'Download paused',
            'queued': 'Waiting to download',
            'warning': f"Download has a problem in {service}",
        }[download['state']]
        bits = [f"{percent}%" if isinstance(percent, int) and download['state'] != 'importing' else '', left]
        return {'key': 'downloading', 'label': words,
                'tone': 'warn' if download['state'] == 'warning' else 'brand',
                'detail': ' · '.join(b for b in ['on the remote server', *bits] if b),
                'percent': percent}
    if sync_state == 'arrived':
        return {'key': 'arrived', 'label': 'On the remote server', 'tone': 'info',
                'detail': 'Downloaded there; the sync here has not started yet.'}
    if sync_state == 'failed':
        return {'key': 'sync_failed', 'label': 'Sync failed', 'tone': 'crit',
                'detail': 'It arrived on the remote server, and the sync here failed. See Transfers.'}
    if partial:
        return {'key': 'partly', 'label': 'Partly in Jellyfin', 'tone': 'info', 'detail': ''}
    if sync_state == 'synced':
        return {'key': 'synced', 'label': 'Synced here', 'tone': 'info',
                'detail': 'Waiting for Jellyfin to add it. Seerr checks Jellyfin every few minutes.'}
    waited = now - decided_at if decided_at else 0
    stuck = waited >= STUCK_AFTER_SECONDS
    return {'key': 'searching', 'label': f"Searching for {days(waited)}" if stuck else 'Searching',
            'tone': 'warn' if stuck else 'muted', 'stuck': stuck,
            'detail': f"Approved; {service} has not found a download yet."}


def _steps(status: str, *, available: bool, partial: bool, download, sync,
           stuck: bool) -> List[Dict[str, Any]]:
    """The four steps, each done, in progress, waiting or a problem."""
    if status in ('pending', 'declined', 'failed'):
        first = {'pending': 'active', 'declined': 'problem', 'failed': 'problem'}[status]
        return [
            {'key': 'approved', 'state': first},
            {'key': 'download', 'state': 'todo'},
            {'key': 'sync', 'state': 'todo'},
            {'key': 'jellyfin', 'state': 'todo'},
        ]
    sync_state = (sync or {}).get('state')
    downloaded = bool(sync) or available or partial
    if download and download['state'] != 'importing':
        download_state = 'problem' if download['state'] == 'warning' else 'active'
    elif download:
        download_state = 'active'
    elif downloaded:
        download_state = 'done'
    else:
        download_state = 'problem' if stuck else 'waiting'
    if available or sync_state == 'synced' or (partial and not sync):
        sync_step = 'done'
    elif sync_state in ('held', 'failed'):
        sync_step = 'problem'
    elif sync_state in ('syncing', 'arrived'):
        sync_step = 'active'
    else:
        sync_step = 'todo'
    jellyfin = 'done' if available else 'active' if partial else 'todo'
    return [
        {'key': 'approved', 'state': 'done'},
        {'key': 'download', 'state': download_state},
        {'key': 'sync', 'state': sync_step},
        {'key': 'jellyfin', 'state': jellyfin},
    ]


# ------------------------------------------------------------------ issues

def _comment(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': raw.get('id'),
        'by': person(raw.get('user')),
        'message': str(raw.get('message') or ''),
        'at': iso(raw.get('createdAt')),
    }


def issue_view(raw: Dict[str, Any], *, title: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One Seerr issue: what is wrong with what, who said so, and the thread."""
    media = raw.get('media') or {}
    media_type = media.get('mediaType') or 'movie'
    comments = sorted((_comment(c) for c in raw.get('comments') or [] if isinstance(c, dict)),
                      key=lambda c: (c['at'] or '', c['id'] or 0))
    season = raw.get('problemSeason') or None
    episode = raw.get('problemEpisode') or None
    first = comments[0]['message'] if comments else ''
    return {
        'id': raw.get('id'),
        'type': ISSUE_TYPE.get(raw.get('issueType'), 'other'),
        'status': ISSUE_STATUS.get(raw.get('status'), 'open'),
        'title': _title_block(media, media_type, title),
        'jellyfin_id': media.get('jellyfinMediaId') or None,
        'season': season if isinstance(season, int) else None,
        'episode': episode if isinstance(episode, int) else None,
        'reported_by': person(raw.get('createdBy')),
        'reported_at': iso(raw.get('createdAt')),
        'updated_at': iso(raw.get('updatedAt')),
        'modified_by': person(raw.get('modifiedBy')),
        'message': first,
        'replies': max(0, len(comments) - 1),
        'comments': comments,
    }
