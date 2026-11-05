#!/usr/bin/env python3
"""
The name, year and poster of each title Seerr has a request or issue for.

Seerr's rows carry a TMDB id and nothing to show a person. The name is a
second question per title, which Seerr answers from TMDB; the answer is kept
in `seerr_title` and asked again after a few days (a series gains seasons).
"""

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

#: How long a title's answer is trusted. Seasons and episode counts change as
#: a series airs; a name and poster rarely do.
MAX_AGE_SECONDS = 3 * 24 * 3600

#: TMDB's image host, at a size that suits a list row on a phone and a desktop.
POSTER_BASE = 'https://image.tmdb.org/t/p/w185'

Key = Tuple[str, int]


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _epoch(value: str) -> float:
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def poster_url(path: Optional[str]) -> str:
    path = (path or '').strip()
    if not path.startswith('/'):
        return ''
    return f"{POSTER_BASE}{path}"


def from_seerr(media_type: str, payload: Any) -> Optional[Dict[str, Any]]:
    """What is kept from Seerr's `/movie/{id}` or `/tv/{id}` answer."""
    if not isinstance(payload, dict):
        return None
    if media_type == 'movie':
        name = payload.get('title') or payload.get('originalTitle')
        date = payload.get('releaseDate') or ''
    else:
        name = payload.get('name') or payload.get('originalName')
        date = payload.get('firstAirDate') or ''
    year = None
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        year = int(date[:4])
    seasons: List[List[int]] = []
    for season in payload.get('seasons') or []:
        if not isinstance(season, dict):
            continue
        number = season.get('seasonNumber')
        count = season.get('episodeCount')
        if isinstance(number, int) and isinstance(count, int):
            seasons.append([number, count])
    return {
        'title': str(name or '').strip(),
        'year': year,
        'poster_path': payload.get('posterPath') or '',
        'seasons': seasons,
    }


class TitleCache:
    def __init__(self, db_manager, clock: Callable[[], float] = time.time):
        self.db = db_manager
        self.clock = clock

    def get_many(self, keys: Iterable[Key]) -> Dict[Key, Dict[str, Any]]:
        keys = list({(str(t), int(i)) for t, i in keys})
        if not keys:
            return {}
        found: Dict[Key, Dict[str, Any]] = {}
        with self.db.get_connection() as conn:
            for start in range(0, len(keys), 200):
                chunk = keys[start:start + 200]
                where = ' OR '.join('(media_type = ? AND tmdb_id = ?)' for _ in chunk)
                params = [v for key in chunk for v in key]
                rows = conn.execute(
                    f'SELECT media_type, tmdb_id, title, year, poster_path, seasons, fetched_at '
                    f'FROM seerr_title WHERE {where}', params).fetchall()
                for row in rows:
                    try:
                        seasons = json.loads(row[5] or '[]')
                    except (TypeError, ValueError):
                        seasons = []
                    found[(row[0], int(row[1]))] = {
                        'title': row[2] or '', 'year': row[3], 'poster_path': row[4] or '',
                        'seasons': seasons, 'fetched_at': row[6],
                    }
        return found

    def is_fresh(self, row: Optional[Dict[str, Any]]) -> bool:
        if not row:
            return False
        return self.clock() - _epoch(row.get('fetched_at') or '') < MAX_AGE_SECONDS

    def put(self, media_type: str, tmdb_id: int, row: Dict[str, Any]) -> Dict[str, Any]:
        stored = dict(row, fetched_at=_iso(self.clock()))
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO seerr_title (media_type, tmdb_id, title, year, poster_path, seasons, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_type, tmdb_id) DO UPDATE SET
                    title = excluded.title, year = excluded.year,
                    poster_path = excluded.poster_path, seasons = excluded.seasons,
                    fetched_at = excluded.fetched_at
            ''', (media_type, int(tmdb_id), stored.get('title') or '', stored.get('year'),
                  stored.get('poster_path') or '', json.dumps(stored.get('seasons') or []),
                  stored['fetched_at']))
            conn.commit()
        return stored
