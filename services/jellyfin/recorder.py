#!/usr/bin/env python3
"""
Every play, kept — the history Jellyfin does not.

Jellyfin's activity log says who started playing what, and when. It does not
say whether the file was played as it is or converted, why it was converted,
or how long anyone watched. Those exist only while the play is live, in the
session list, so this records them from there: one row per play, opened the
first time a stream is seen and closed once it has been gone a while.

A play is (session, item). The same person moving to the next episode is a new
play; the same stream briefly missing from one answer — Jellyfin drops the
item for a moment when a track is switched — is not, because a play only
closes after `GRACE_SECONDS` without a sighting. A play that was open when
DragonCP stopped is closed at its last sighting by the first answer after the
restart, unless it is still playing, in which case it simply carries on.
"""

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from services.jellyfin.sessions import heavier

#: How long a stream may be missing before its play is closed.
GRACE_SECONDS = 45.0
#: The most one gap between sightings adds to watched time. Gaps longer than
#: this mean the poller was not looking (a restart, Jellyfin not answering),
#: and counting them would invent viewing nobody saw.
MAX_STEP_SECONDS = 30.0


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='seconds')


def epoch(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


class PlayRecorder:
    def __init__(self, db_manager, clock: Callable[[], float] = time.time):
        self.db = db_manager
        self.clock = clock
        self._lock = threading.Lock()
        #: (session id, item id) → what the open play looked like last time.
        self._open: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._loaded = False

    # ------------------------------------------------------------ recording

    def open_count(self) -> int:
        with self._lock:
            self._load_open()
            return len(self._open)

    def observe(self, streams: List[Dict[str, Any]],
                now: Optional[float] = None) -> Dict[str, int]:
        """Fold one answer from Jellyfin into the record. Returns what changed."""
        now = self.clock() if now is None else now
        opened = closed = 0
        with self._lock:
            self._load_open()
            seen = set()
            with self.db.get_connection() as conn:
                for stream in streams:
                    key = (stream['session_id'], stream['item']['id'])
                    if not key[1] or key in seen:
                        continue
                    seen.add(key)
                    state = self._open.get(key)
                    if state is None:
                        self._open[key] = self._insert(conn, stream, now)
                        opened += 1
                    else:
                        self._update(conn, state, stream, now)
                for key, state in list(self._open.items()):
                    if key not in seen and now - state['last_seen'] > GRACE_SECONDS:
                        conn.execute("UPDATE jellyfin_play SET ended_at = ? WHERE id = ?",
                                     (iso(state['last_seen']), state['id']))
                        del self._open[key]
                        closed += 1
                conn.commit()
        return {'opened': opened, 'closed': closed, 'open': len(self._open)}

    def _load_open(self) -> None:
        """The plays a previous process left open, so they can carry on or close."""
        if self._loaded:
            return
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM jellyfin_play WHERE ended_at IS NULL AND source = 'live'"
            ).fetchall()
        for row in rows:
            last_seen = epoch(row['last_seen_at']) or epoch(row['started_at']) or self.clock()
            self._open[(row['session_id'] or '', row['item_id'] or '')] = {
                'id': row['id'],
                'last_seen': last_seen,
                'paused': True,  # unknown; never counts the gap as watched
                'method': row['play_method'],
                'reasons': set(json.loads(row['transcode_reasons'] or '[]')),
                'video': bool(row['video_transcoded']),
                'audio': bool(row['audio_transcoded']),
                'watched': float(row['watched_seconds'] or 0),
                'max_position': int(row['max_position_seconds'] or 0),
            }
        self._loaded = True

    def _insert(self, conn, stream: Dict[str, Any], now: float) -> Dict[str, Any]:
        item = stream['item']
        transcode = stream.get('transcode') or {}
        method = stream.get('play_method') or None
        reasons = set(transcode.get('reasons') or [])
        video = method == 'Transcode' and transcode.get('video') is True
        audio = method == 'Transcode' and transcode.get('audio') is True
        cursor = conn.execute(
            "INSERT INTO jellyfin_play (source, session_id, user_id, user_name, client, "
            "app_version, device_id, device_name, address, network, item_id, item_type, title, "
            "series_name, series_id, season, episode, year, runtime_seconds, path, provider_ids, "
            "started_at, last_seen_at, watched_seconds, max_position_seconds, paused, play_method, "
            "video_transcoded, audio_transcoded, transcode_reasons, transcode, source_media) "
            "VALUES ('live', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "0, ?, ?, ?, ?, ?, ?, ?, ?)",
            (stream['session_id'], stream['user']['id'], stream['user']['name'],
             stream['client'], stream['app_version'], stream['device']['id'],
             stream['device']['name'], stream['address'], stream['network'],
             item['id'], item['type'], item['title'], item['series'], item['series_id'],
             item['season'], item['episode'], item['year'], item['runtime_seconds'],
             item['path'], json.dumps(item['provider_ids'], sort_keys=True),
             iso(now), iso(now), stream['position_seconds'], int(stream['paused']), method,
             int(video), int(audio), json.dumps(sorted(reasons)),
             json.dumps(stream.get('transcode')) if stream.get('transcode') else None,
             json.dumps(stream.get('source'))),
        )
        return {
            'id': cursor.lastrowid, 'last_seen': now, 'paused': stream['paused'],
            'method': method, 'reasons': reasons, 'video': video, 'audio': audio,
            'watched': 0.0, 'max_position': stream['position_seconds'],
        }

    def _update(self, conn, state: Dict[str, Any], stream: Dict[str, Any], now: float) -> None:
        # The time since the last sighting counts when it was playing then:
        # pressing pause ends the watching, it does not undo it.
        if not state['paused']:
            state['watched'] += min(max(0.0, now - state['last_seen']), MAX_STEP_SECONDS)
        transcode = stream.get('transcode') or {}
        method = stream.get('play_method') or None
        state['method'] = heavier(state['method'], method)
        state['reasons'] |= set(transcode.get('reasons') or [])
        if method == 'Transcode':
            state['video'] = state['video'] or transcode.get('video') is True
            state['audio'] = state['audio'] or transcode.get('audio') is True
        state['max_position'] = max(state['max_position'], stream['position_seconds'])
        state['last_seen'] = now
        state['paused'] = stream['paused']
        # The latest details win: a play switched to a converted stream halfway
        # through should show what it was converted to, not the file as it was.
        conn.execute(
            "UPDATE jellyfin_play SET last_seen_at = ?, watched_seconds = ?, "
            "max_position_seconds = ?, paused = ?, play_method = ?, video_transcoded = ?, "
            "audio_transcoded = ?, transcode_reasons = ?, "
            "transcode = COALESCE(?, transcode), source_media = ?, address = ?, network = ? "
            "WHERE id = ?",
            (iso(now), int(state['watched']), state['max_position'], int(stream['paused']),
             state['method'], int(state['video']), int(state['audio']),
             json.dumps(sorted(state['reasons'])),
             json.dumps(stream['transcode']) if stream.get('transcode') else None,
             json.dumps(stream.get('source')), stream['address'], stream['network'],
             state['id']),
        )

    # -------------------------------------------------------------- reading

    def plays(self, *, limit: int = 50, offset: int = 0, user: str = '',
              converted: Optional[bool] = None, search: str = '') -> Dict[str, Any]:
        """Plays newest first, with the filters the History tab offers."""
        where, args = [], []
        if user:
            where.append('user_name = ?')
            args.append(user)
        if converted is True:
            where.append("play_method = 'Transcode'")
        elif converted is False:
            where.append("(play_method IS NULL OR play_method != 'Transcode')")
        if search:
            where.append('(title LIKE ? OR series_name LIKE ? OR device_name LIKE ? '
                         'OR client LIKE ?)')
            needle = f"%{search}%"
            args.extend([needle] * 4)
        clause = f"WHERE {' AND '.join(where)}" if where else ''
        with self.db.get_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM jellyfin_play {clause}",
                                 args).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM jellyfin_play {clause} ORDER BY started_at DESC, id DESC "
                f"LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
            users = [r[0] for r in conn.execute(
                "SELECT user_name FROM jellyfin_play WHERE user_name != '' "
                "GROUP BY user_name ORDER BY MAX(started_at) DESC").fetchall()]
        return {'plays': [_play(row) for row in rows], 'total': total, 'users': users}


def _loads(text: Optional[str], fallback: Any) -> Any:
    if not text:
        return fallback
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return fallback


def _play(row) -> Dict[str, Any]:
    runtime = row['runtime_seconds']
    reached = row['max_position_seconds'] or 0
    return {
        'id': row['id'],
        'source': row['source'],
        'user': row['user_name'],
        'client': row['client'],
        'app_version': row['app_version'],
        'device': row['device_name'],
        'address': row['address'],
        'network': row['network'],
        'item': {
            'id': row['item_id'],
            'type': row['item_type'],
            'title': row['title'],
            'series': row['series_name'],
            'series_id': row['series_id'],
            'season': row['season'],
            'episode': row['episode'],
            'year': row['year'],
            'runtime_seconds': runtime,
        },
        'started_at': row['started_at'],
        'last_seen_at': row['last_seen_at'],
        'ended_at': row['ended_at'],
        'watched_seconds': row['watched_seconds'] or 0,
        'reached_seconds': reached,
        'finished': bool(runtime) and reached >= runtime * 0.9,
        'play_method': row['play_method'],
        'video_converted': bool(row['video_transcoded']),
        'audio_converted': bool(row['audio_transcoded']),
        'reasons': _loads(row['transcode_reasons'], []),
        'transcode': _loads(row['transcode'], None),
        'source_media': _loads(row['source_media'], None),
    }
