#!/usr/bin/env python3
"""
One row per title, and the only place that says which folder it lives in.

Every link between tables in this application used to be a title string, and
title strings do not survive the trip. Measured on the production database
before this table existed:

    sonarr_webhook.series_title -> transfers.folder_name       2 of 59
    sonarr_webhook.series_title -> transfers.parsed_title     45 of 59
    transfers.folder_name       -> backup_capture.title       39 of 117

The cause is not sloppiness. A library folder is derived from a title by
stripping the characters a filesystem cannot hold and appending a year, and
that transformation cannot be reversed:

    Example Show: The Sequel   ->   Example Show - The Sequel (2024)

So a mapping already existed here. It was simply never written down — it was
re-guessed by string munging at every call site, and the guesses disagreed
between tables. `local_folder` is that mapping, stored once.

What anchors it
---------------
`external_id` is the service's *external* identifier — `tvdbId` for Sonarr,
`tmdbId` for Radarr. Both are present and unique across the whole library, and
both survive the three things that break every other candidate:

  * a title changing upstream. `tvdb_id` 900001 was recorded under two
    different spellings a week apart; the id never moved.
  * a title being removed and re-added. The service's own row id is *not*
    reused — Radarr's 90 films span ids 117 to 576, leaving 486 permanent
    holes — so a re-added film comes back with a new one.
  * the service being rebuilt from scratch.

`service_item_id` — Sonarr's `seriesId`, Radarr's `movieId` — is kept because
the queue endpoints need it, but it is a **cache**. Nothing joins on it, and
anything that reads it must be able to re-resolve it from `external_id` when
the service answers 404.

What is deliberately not here
-----------------------------
A sync status column. Status is derived at read time from the facts recorded
elsewhere, because a stored status is wrong the moment anything happens
outside this application — a manual sync, a file removed on disk. Caches that
do exist carry `refreshed_at` so a reader can see how old the answer is.
"""

import sqlite3
from typing import Any, Dict, List, Optional

SOURCE_SONARR = 'sonarr'
SOURCE_RADARR = 'radarr'
SOURCES = (SOURCE_SONARR, SOURCE_RADARR)

#: Which external identifier each source is keyed by. Written down rather than
#: inferred so a third source cannot quietly pick a weaker one.
EXTERNAL_ID_FIELD = {
    SOURCE_SONARR: 'tvdbId',
    SOURCE_RADARR: 'tmdbId',
}


class MediaItemStore:
    """Reads and writes the title index. Never raises on a missing row."""

    def __init__(self, db_manager):
        self.db = db_manager

    # -- reading -------------------------------------------------------------

    def get(self, source: str, external_id: Any) -> Optional[Dict[str, Any]]:
        """One title by its durable identity."""
        if not source or external_id in (None, ''):
            return None
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM media_item WHERE source = ? AND external_id = ?',
                (source, str(external_id)),
            ).fetchone()
        return dict(row) if row else None

    def get_by_id(self, media_item_id: int) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM media_item WHERE id = ?', (media_item_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_by_folder(self, local_folder: str) -> Optional[Dict[str, Any]]:
        """
        A title by the folder it occupies.

        The fallback path, and the only one that matches on a name. It exists
        for transfers started by hand or by Explore, which never carried an
        external id — 43 of 612 rows at the time this was written.
        """
        if not local_folder:
            return None
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM media_item WHERE local_folder = ? '
                'ORDER BY updated_at DESC LIMIT 1',
                (local_folder,),
            ).fetchone()
        return dict(row) if row else None

    def list_items(self, source: Optional[str] = None,
                   media_type: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = 'SELECT * FROM media_item'
        params: List[Any] = []
        where = []
        if source:
            where.append('source = ?')
            params.append(source)
        if media_type:
            where.append('media_type = ?')
            params.append(media_type)
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY title COLLATE NOCASE'
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def count(self) -> int:
        with self.db.get_connection() as conn:
            return conn.execute('SELECT COUNT(*) FROM media_item').fetchone()[0]

    # -- writing -------------------------------------------------------------

    def upsert(self, source: str, external_id: Any, **fields) -> Optional[int]:
        """
        Record what we now know about a title, and return its row id.

        Keyed on `(source, external_id)`, so a title that was removed from the
        service and later re-added lands on the row it already had — with its
        sync history intact — rather than becoming a second entry. That is the
        whole reason the key is the external id and not the service's own.

        Only non-empty values overwrite. A webhook that carries a title but no
        folder must not blank the folder a transfer established.
        """
        if not source or external_id in (None, ''):
            return None
        external_id = str(external_id)

        allowed = (
            'media_type', 'service_item_id', 'service_item_id_seen_at',
            'title', 'year', 'title_slug', 'imdb_id', 'local_folder',
            'present_in_service', 'last_seen_in_service_at',
        )
        values = {k: v for k, v in fields.items()
                  if k in allowed and v not in (None, '')}

        try:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    'SELECT id FROM media_item WHERE source = ? AND external_id = ?',
                    (source, external_id),
                ).fetchone()

                if row:
                    item_id = row[0]
                    if values:
                        sets = ', '.join(f'{k} = ?' for k in values)
                        conn.execute(
                            f'UPDATE media_item SET {sets}, updated_at = CURRENT_TIMESTAMP '
                            f'WHERE id = ?',
                            (*values.values(), item_id),
                        )
                    conn.commit()
                    return item_id

                cols = ['source', 'external_id', *values.keys()]
                conn.execute(
                    f"INSERT INTO media_item ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})",
                    (source, external_id, *values.values()),
                )
                conn.commit()
                return conn.execute(
                    'SELECT id FROM media_item WHERE source = ? AND external_id = ?',
                    (source, external_id),
                ).fetchone()[0]
        except sqlite3.Error as exc:
            print(f"⚠️  media_item upsert failed for {source}:{external_id}: {exc}")
            return None

    def forget_service_item_id(self, media_item_id: int) -> None:
        """
        Drop the cached service id after the service says it does not exist.

        Called when a query 404s. The next read resolves it again from the
        external id, which is the point of keeping the two apart.
        """
        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    'UPDATE media_item SET service_item_id = NULL, '
                    'updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (media_item_id,),
                )
                conn.commit()
        except sqlite3.Error:
            pass

    def mark_absent_from_service(self, source: str, seen_external_ids) -> int:
        """
        Flag titles the service no longer lists.

        Kept as its own fact rather than deleting the row: files synced from a
        title that has since been removed upstream are still on the disk, and a
        library view that only walks the service's side cannot show them.
        """
        seen = {str(x) for x in seen_external_ids if x not in (None, '')}
        if not seen:
            return 0
        try:
            with self.db.get_connection() as conn:
                placeholders = ', '.join('?' * len(seen))
                cur = conn.execute(
                    f'UPDATE media_item SET present_in_service = 0, '
                    f'updated_at = CURRENT_TIMESTAMP '
                    f'WHERE source = ? AND present_in_service = 1 '
                    f'AND external_id NOT IN ({placeholders})',
                    (source, *seen),
                )
                conn.commit()
                return cur.rowcount or 0
        except sqlite3.Error:
            return 0

    # -- seasons -------------------------------------------------------------

    def upsert_season(self, media_item_id: int, season_number: int,
                      **fields) -> None:
        """A season's counts, stamped with when they were true."""
        if not media_item_id or season_number is None:
            return
        allowed = ('episodes_total', 'episodes_with_file', 'episodes_monitored',
                   'refreshed_at', 'last_synced_transfer_id', 'last_synced_at')
        values = {k: v for k, v in fields.items()
                  if k in allowed and v is not None}
        try:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    'SELECT id FROM media_item_season '
                    'WHERE media_item_id = ? AND season_number = ?',
                    (media_item_id, season_number),
                ).fetchone()
                if row:
                    if values:
                        sets = ', '.join(f'{k} = ?' for k in values)
                        conn.execute(
                            f'UPDATE media_item_season SET {sets}, '
                            f'updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                            (*values.values(), row[0]),
                        )
                else:
                    cols = ['media_item_id', 'season_number', *values.keys()]
                    conn.execute(
                        f"INSERT INTO media_item_season ({', '.join(cols)}) "
                        f"VALUES ({', '.join('?' * len(cols))})",
                        (media_item_id, season_number, *values.values()),
                    )
                conn.commit()
        except sqlite3.Error as exc:
            print(f"⚠️  media_item_season upsert failed: {exc}")

    def seasons(self, media_item_id: int) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                'SELECT * FROM media_item_season WHERE media_item_id = ? '
                'ORDER BY season_number',
                (media_item_id,),
            ).fetchall()]

    # -- linking existing rows ----------------------------------------------

    def attach_transfer(self, transfer_id: str, media_item_id: int) -> None:
        if not transfer_id or not media_item_id:
            return
        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    'UPDATE transfers SET media_item_id = ? WHERE transfer_id = ?',
                    (media_item_id, transfer_id),
                )
                conn.commit()
        except sqlite3.Error:
            pass
