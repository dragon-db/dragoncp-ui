#!/usr/bin/env python3
"""
What the title check found, which TMDB show a folder is, and which episodes
were named from TMDB. Tables are created in `models/database.py`.
"""

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


class TitleStore:
    def __init__(self, db_manager):
        self.db = db_manager

    # -- title checks --------------------------------------------------------

    def save_check(self, media_type: str, folder: str, summary: Dict[str, Any],
                   detail: Dict[str, Any]) -> None:
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO title_check (media_type, folder, state, placeholders, ready,
                    waiting, skipped, sonarr_series_id, message, detail, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_type, folder) DO UPDATE SET
                    state = excluded.state, placeholders = excluded.placeholders,
                    ready = excluded.ready, waiting = excluded.waiting,
                    skipped = excluded.skipped, sonarr_series_id = excluded.sonarr_series_id,
                    message = excluded.message, detail = excluded.detail,
                    checked_at = excluded.checked_at,
                    notified_ready = MIN(title_check.notified_ready, excluded.ready)
            ''', (
                media_type, folder, summary.get('state') or 'unknown',
                int(summary.get('placeholders') or 0), int(summary.get('ready') or 0),
                int(summary.get('waiting') or 0), int(summary.get('skipped') or 0),
                summary.get('sonarr_series_id'), summary.get('message') or '',
                json.dumps(detail, ensure_ascii=False), _now(),
            ))
            conn.commit()

    def checks(self, media_type: Optional[str] = None) -> List[Dict[str, Any]]:
        sql, params = 'SELECT * FROM title_check', []
        if media_type:
            sql += ' WHERE media_type = ?'
            params.append(media_type)
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for row in rows:
            row['detail'] = _json(row.get('detail'), {})
        return rows

    def check(self, media_type: str, folder: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT * FROM title_check WHERE media_type = ? AND folder = ?',
                               (media_type, folder)).fetchone()
        if not row:
            return None
        out = dict(row)
        out['detail'] = _json(out.get('detail'), {})
        return out

    def forget_checks_except(self, media_type: str, folders: Iterable[str]) -> int:
        """Drop the checks of folders that no longer hold anything to rename."""
        keep = list(folders)
        with self.db.get_connection() as conn:
            if keep:
                marks = ', '.join('?' for _ in keep)
                cursor = conn.execute(
                    f'DELETE FROM title_check WHERE media_type = ? AND folder NOT IN ({marks})',
                    [media_type, *keep])
            else:
                cursor = conn.execute('DELETE FROM title_check WHERE media_type = ?',
                                      (media_type,))
            conn.commit()
            return cursor.rowcount

    def forget_check(self, media_type: str, folder: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM title_check WHERE media_type = ? AND folder = ?',
                         (media_type, folder))
            conn.commit()

    def mark_notified(self, media_type: str, folder: str, ready: int) -> None:
        with self.db.get_connection() as conn:
            conn.execute('UPDATE title_check SET notified_ready = ? '
                         'WHERE media_type = ? AND folder = ?', (ready, media_type, folder))
            conn.commit()

    # -- TMDB links ------------------------------------------------------------

    def link(self, media_type: str, folder: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT * FROM title_link WHERE media_type = ? AND folder = ?',
                               (media_type, folder)).fetchone()
        return dict(row) if row else None

    def save_link(self, media_type: str, folder: str, tmdb_id: int, name: str,
                  year: Optional[int], source: str = 'manual',
                  linked_by: Optional[str] = None) -> None:
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO title_link (media_type, folder, tmdb_id, tmdb_name, tmdb_year,
                    source, linked_by, linked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_type, folder) DO UPDATE SET
                    tmdb_id = excluded.tmdb_id, tmdb_name = excluded.tmdb_name,
                    tmdb_year = excluded.tmdb_year, source = excluded.source,
                    linked_by = excluded.linked_by, linked_at = excluded.linked_at
            ''', (media_type, folder, int(tmdb_id), name, year, source, linked_by, _now()))
            conn.commit()

    def remove_link(self, media_type: str, folder: str) -> bool:
        with self.db.get_connection() as conn:
            cursor = conn.execute('DELETE FROM title_link WHERE media_type = ? AND folder = ?',
                                  (media_type, folder))
            conn.commit()
            return cursor.rowcount > 0

    # -- titles taken from TMDB ------------------------------------------------

    def episode_titles(self, media_type: str, folder: str) -> Dict[tuple, Dict[str, Any]]:
        """{(season, episode): row} for one series folder."""
        with self.db.get_connection() as conn:
            rows = conn.execute('SELECT * FROM episode_title WHERE media_type = ? AND folder = ?',
                                (media_type, folder)).fetchall()
        return {(r['season'], r['episode']): dict(r) for r in rows}

    def tmdb_titled_folders(self, media_type: str) -> List[str]:
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT folder FROM episode_title "
                                "WHERE media_type = ? AND source = 'tmdb'",
                                (media_type,)).fetchall()
        return [r['folder'] for r in rows]

    def record_title(self, media_type: str, folder: str, season: int, episode: int,
                     title: str, source: str, file_name: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO episode_title (media_type, folder, season, episode, title,
                    source, file_name, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_type, folder, season, episode) DO UPDATE SET
                    title = excluded.title, source = excluded.source,
                    file_name = excluded.file_name, updated_at = excluded.updated_at
            ''', (media_type, folder, season, episode, title, source, file_name, _now()))
            conn.commit()

    def forget_title(self, media_type: str, folder: str, season: int, episode: int) -> None:
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM episode_title WHERE media_type = ? AND folder = ? '
                         'AND season = ? AND episode = ?', (media_type, folder, season, episode))
            conn.commit()


def _json(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default
