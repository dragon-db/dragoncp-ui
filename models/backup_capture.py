#!/usr/bin/env python3
"""
The backup index.

Three tables, and none of them is the source of truth. The tree under
BACKUP_PATH is; this is a queryable view over it that can be thrown away and
rebuilt by walking the disk. That is deliberate — the previous shape treated
the database as authoritative over a disk it had largely lost track of, and
what it lost track of was unrecoverable.

    backup_capture        one displaced copy, at one moment
    backup_capture_file   the files inside it
    backup_capture_key    which slots it belongs to (>1 for a double episode)
"""

import re
from typing import Dict, List, Optional, Tuple

#: The episode half of a slot key: "shows|example_show|S01E02".
_SLOT_CODE_RE = re.compile(r'\|S(\d{2,4})E(\d{2,4})$')


def _episode_from_slot_key(slot_key: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """
    Season and episode as the SLOT states them, or (None, None) for a movie.

    The slot key is the authority on which episode a summary row is about. The
    capture's own columns are not: a double episode lives under S01E01 and is
    registered against both slots, so reading them made the S01E02 row claim to
    be S01E01.
    """
    match = _SLOT_CODE_RE.search(slot_key or '')
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


class BackupCapture:
    """Reads and writes the backup index."""

    def __init__(self, db_manager):
        self.db = db_manager

    # ---- writing ----------------------------------------------------------

    def upsert(self, record: Dict, files: List[Dict], slot_keys: List[str]) -> str:
        """
        Write one capture and everything under it, replacing any previous rows.

        Replace rather than append, so a rebuild is idempotent: running it twice
        leaves the same index rather than duplicating every capture.
        """
        capture_id = record['capture_id']
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM backup_capture_file WHERE capture_id = ?', (capture_id,))
            conn.execute('DELETE FROM backup_capture_key WHERE capture_id = ?', (capture_id,))
            conn.execute('DELETE FROM backup_capture WHERE capture_id = ?', (capture_id,))
            conn.execute('''
                INSERT INTO backup_capture (
                    capture_id, library, title, season_number, episode_number,
                    release_year, slot_key, capture_path, captured_at,
                    source_transfer_id, source_ref, reason, kind,
                    file_count, total_size, pinned, status, restored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                capture_id,
                record.get('library'),
                record.get('title'),
                record.get('season_number'),
                record.get('episode_number'),
                record.get('release_year'),
                record.get('slot_key'),
                record.get('capture_path'),
                record.get('captured_at'),
                record.get('source_transfer_id'),
                record.get('source_ref'),
                record.get('reason'),
                record.get('kind', 'slot'),
                record.get('file_count', 0),
                record.get('total_size', 0),
                1 if record.get('pinned') else 0,
                record.get('status', 'present'),
                record.get('restored_at'),
            ))

            if files:
                conn.executemany('''
                    INSERT INTO backup_capture_file (
                        capture_id, relative_path, original_path, file_size,
                        modified_time, is_media
                    ) VALUES (?, ?, ?, ?, ?, ?)
                ''', [
                    (
                        capture_id,
                        f['relative_path'],
                        f.get('original_path') or '',
                        f.get('file_size', 0),
                        f.get('modified_time', 0),
                        1 if f.get('is_media') else 0,
                    )
                    for f in files
                ])

            if slot_keys:
                conn.executemany(
                    'INSERT OR IGNORE INTO backup_capture_key (capture_id, slot_key) VALUES (?, ?)',
                    [(capture_id, key) for key in dict.fromkeys(slot_keys)],
                )
            conn.commit()
        return capture_id

    #: Columns `update()` will write. The SET clause is built by interpolating
    #: key names into SQL, which parameter binding cannot protect, so the names
    #: are checked against this rather than trusted. Every caller today passes
    #: literals; the allowlist is what keeps that true when one does not.
    UPDATABLE_COLUMNS = frozenset({
        'pinned', 'status', 'restored_at', 'reason',
        'restored_by_kind', 'restored_by_name', 'restored_by_account_id',
    })

    def update(self, capture_id: str, updates: Dict) -> bool:
        allowed = {k: v for k, v in (updates or {}).items() if k in self.UPDATABLE_COLUMNS}
        rejected = set(updates or {}) - set(allowed)
        if rejected:
            print(f"⚠️  Ignoring unknown backup_capture column(s): {', '.join(sorted(rejected))}")
        if not allowed:
            return False
        clause = ', '.join(f"{k} = ?" for k in allowed)
        values = list(allowed.values()) + [capture_id]
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                f'UPDATE backup_capture SET {clause} WHERE capture_id = ?', values
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete(self, capture_id: str) -> bool:
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM backup_capture_file WHERE capture_id = ?', (capture_id,))
            conn.execute('DELETE FROM backup_capture_key WHERE capture_id = ?', (capture_id,))
            cursor = conn.execute('DELETE FROM backup_capture WHERE capture_id = ?', (capture_id,))
            conn.commit()
            return cursor.rowcount > 0

    def clear(self) -> None:
        """Drop the whole index. Only a rebuild does this, immediately before
        repopulating it from the tree."""
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM backup_capture_file')
            conn.execute('DELETE FROM backup_capture_key')
            conn.execute('DELETE FROM backup_capture')
            conn.commit()

    # ---- reading ----------------------------------------------------------

    def get(self, capture_id: str) -> Optional[Dict]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM backup_capture WHERE capture_id = ?', (capture_id,)
            ).fetchone()
            return dict(row) if row else None

    def files(self, capture_id: str) -> List[Dict]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT relative_path, original_path, file_size, modified_time, is_media '
                'FROM backup_capture_file WHERE capture_id = ? ORDER BY is_media DESC, relative_path',
                (capture_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def captures_for_slot(self, slot_key: str) -> List[Dict]:
        """
        Every version of one slot, newest first.

        Joined through backup_capture_key rather than filtered on the capture's
        own slot_key, so a double episode's capture is returned for both of the
        episodes it holds.
        """
        with self.db.get_connection() as conn:
            rows = conn.execute('''
                SELECT c.* FROM backup_capture c
                JOIN backup_capture_key k ON k.capture_id = c.capture_id
                WHERE k.slot_key = ?
                ORDER BY c.captured_at DESC, c.capture_id DESC
            ''', (slot_key,)).fetchall()
            return [dict(r) for r in rows]

    def slots(self, library: Optional[str] = None, title: Optional[str] = None,
              season: Optional[int] = None, search: Optional[str] = None,
              limit: int = 500, offset: int = 0, sort: str = 'recent') -> List[Dict]:
        """
        One row per slot that has captures, with its version count and size.

        This is the list the Backups page renders. Grouping happens in SQL
        because the answer is a summary — pulling every capture back to count
        them in Python is the shape that made the old page slow.
        """
        where = ["c.kind = 'slot'"]
        params: List = []
        if library:
            where.append('c.library = ?')
            params.append(library)
        if title:
            where.append('c.title = ?')
            params.append(title)
        if season is not None:
            where.append('c.season_number = ?')
            params.append(season)
        if search:
            where.append('LOWER(c.title) LIKE ?')
            params.append(f"%{search.lower()}%")

        # Reclaiming space means finding what is big, not what is recent, so
        # the list can be ordered either way.
        order = 'total_size DESC' if sort == 'size' else 'latest_captured_at DESC'

        query = f'''
            SELECT
                k.slot_key                     AS slot_key,
                MIN(c.library)                 AS library,
                MIN(c.title)                   AS title,
                MIN(c.season_number)           AS season_number,
                MIN(c.episode_number)          AS episode_number,
                MIN(c.release_year)            AS release_year,
                COUNT(DISTINCT c.capture_id)   AS version_count,
                SUM(c.total_size)              AS total_size,
                MAX(c.captured_at)             AS latest_captured_at,
                MAX(c.pinned)                  AS has_pinned
            FROM backup_capture c
            JOIN backup_capture_key k ON k.capture_id = c.capture_id
            WHERE {' AND '.join(where)}
            GROUP BY k.slot_key
            ORDER BY {order}
            LIMIT ? OFFSET ?
        '''
        params.extend([limit, offset])
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(query, params).fetchall()]

        # Season and episode come from the slot key, not from the capture's own
        # columns. A double episode is filed under S01E01 and registered against
        # both slots, so `MIN(c.episode_number)` answered 1 for the S01E02 group
        # as well — and the page listed the same episode twice.
        for row in rows:
            season, episode = _episode_from_slot_key(row.get('slot_key'))
            if season is not None:
                row['season_number'] = season
                row['episode_number'] = episode
        return rows

    def count_slots(self, library: Optional[str] = None, title: Optional[str] = None,
                    season: Optional[int] = None, search: Optional[str] = None) -> int:
        where = ["c.kind = 'slot'"]
        params: List = []
        if library:
            where.append('c.library = ?')
            params.append(library)
        if title:
            where.append('c.title = ?')
            params.append(title)
        if season is not None:
            where.append('c.season_number = ?')
            params.append(season)
        if search:
            where.append('LOWER(c.title) LIKE ?')
            params.append(f"%{search.lower()}%")
        query = f'''
            SELECT COUNT(*) FROM (
                SELECT k.slot_key FROM backup_capture c
                JOIN backup_capture_key k ON k.capture_id = c.capture_id
                WHERE {' AND '.join(where)}
                GROUP BY k.slot_key
            )
        '''
        with self.db.get_connection() as conn:
            return conn.execute(query, params).fetchone()[0]

    def titles(self, library: Optional[str] = None) -> List[Dict]:
        """The tree's second level: every title holding captures."""
        where = ["kind = 'slot'"]
        params: List = []
        if library:
            where.append('library = ?')
            params.append(library)
        query = f'''
            SELECT library, title,
                   COUNT(*) AS capture_count,
                   SUM(total_size) AS total_size,
                   MAX(captured_at) AS latest_captured_at
            FROM backup_capture
            WHERE {' AND '.join(where)}
            GROUP BY library, title
            ORDER BY library, title
        '''
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def seasons(self, library: str, title: str) -> List[Dict]:
        with self.db.get_connection() as conn:
            rows = conn.execute('''
                SELECT season_number,
                       COUNT(DISTINCT slot_key) AS slot_count,
                       COUNT(*) AS capture_count,
                       SUM(total_size) AS total_size
                FROM backup_capture
                WHERE kind = 'slot' AND library = ? AND title = ?
                GROUP BY season_number
                ORDER BY season_number
            ''', (library, title)).fetchall()
            return [dict(r) for r in rows]

    def recent(self, limit: int = 50) -> List[Dict]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM backup_capture ORDER BY captured_at DESC, capture_id DESC LIMIT ?', (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def by_kind(self, kind: str, limit: int = 500) -> List[Dict]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM backup_capture WHERE kind = ? ORDER BY captured_at DESC, capture_id DESC LIMIT ?',
                (kind, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def totals(self) -> Dict:
        with self.db.get_connection() as conn:
            row = conn.execute('''
                SELECT
                    COUNT(*)                                          AS capture_count,
                    COALESCE(SUM(total_size), 0)                      AS total_size,
                    COALESCE(SUM(file_count), 0)                      AS file_count,
                    COALESCE(SUM(CASE WHEN pinned = 1 THEN 1 END), 0) AS pinned_count,
                    COALESCE(SUM(CASE WHEN kind = 'unsorted' THEN 1 END), 0) AS unsorted_count
                FROM backup_capture
            ''').fetchone()
            totals = dict(row)
            slots = conn.execute(
                "SELECT COUNT(*) FROM (SELECT slot_key FROM backup_capture_key GROUP BY slot_key)"
            ).fetchone()[0]
            totals['slot_count'] = slots
            return totals

    def prunable(self, keep: int, older_than_iso: str) -> List[Dict]:
        """
        Captures a keep-N rule would remove.

        Read-only: returns the candidates so the caller can report them before
        anything is deleted. Three things protect a capture — being within the
        newest `keep` for its slot, being pinned, and being younger than the
        grace period. The grace period is what stops an accidental sync
        immediately pushing the copy you wanted off the end of the list.

        Having been restored is deliberately NOT one of them. `status` answers
        only whether the files are still on disk; when it also meant "restored"
        a restored capture became permanent and the backup disk filled with
        copies nothing would ever prune.
        """
        with self.db.get_connection() as conn:
            rows = conn.execute('''
                WITH ranked AS (
                    SELECT k.capture_id      AS capture_id,
                           k.slot_key        AS member_slot_key,
                           ROW_NUMBER() OVER (
                               PARTITION BY k.slot_key
                               ORDER BY c.captured_at DESC, c.capture_id DESC
                           )                 AS slot_rank
                    FROM backup_capture_key k
                    JOIN backup_capture c ON c.capture_id = k.capture_id
                    WHERE c.kind = 'slot'
                )
                SELECT c.*, r.member_slot_key, r.slot_rank
                FROM backup_capture c
                JOIN ranked r ON r.capture_id = c.capture_id
                WHERE c.kind = 'slot'
                  AND c.pinned = 0
                  AND c.status = 'present'
                  AND c.captured_at < ?
                  AND r.slot_rank > ?
                ORDER BY c.captured_at ASC
            ''', (older_than_iso, keep)).fetchall()

        # A double episode is ranked inside both of its slots. It may only be
        # pruned when it has fallen out of the keep window in EVERY slot it
        # belongs to, or restoring the other episode would find nothing.
        by_capture: Dict[str, List[Dict]] = {}
        for row in rows:
            by_capture.setdefault(row['capture_id'], []).append(dict(row))

        # One query for every candidate's slot count, not one per candidate.
        # A retention sweep on a full disk has hundreds of candidates, and this
        # was opening a connection for each of them.
        membership = self._slot_counts(list(by_capture))

        return [
            entries[0]
            for capture_id, entries in by_capture.items()
            if len(entries) == membership.get(capture_id, 0)
        ]

    def _slot_counts(self, capture_ids: List[str]) -> Dict[str, int]:
        """How many slots each capture belongs to, for a batch of captures."""
        if not capture_ids:
            return {}
        placeholders = ','.join('?' * len(capture_ids))
        with self.db.get_connection() as conn:
            rows = conn.execute(f'''
                SELECT capture_id, COUNT(*) AS slot_count
                FROM backup_capture_key
                WHERE capture_id IN ({placeholders})
                GROUP BY capture_id
            ''', capture_ids).fetchall()
            return {r['capture_id']: r['slot_count'] for r in rows}

    def _slot_keys_for(self, capture_id: str) -> List[str]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT slot_key FROM backup_capture_key WHERE capture_id = ?', (capture_id,)
            ).fetchall()
            return [r['slot_key'] for r in rows]

    def slot_keys_for(self, capture_id: str) -> List[str]:
        return self._slot_keys_for(capture_id)

    def captures_for_slots(self, slot_keys: List[str]) -> List[Dict]:
        """Every capture belonging to any of these slots."""
        if not slot_keys:
            return []
        placeholders = ','.join('?' * len(slot_keys))
        with self.db.get_connection() as conn:
            rows = conn.execute(f'''
                SELECT DISTINCT c.* FROM backup_capture c
                JOIN backup_capture_key k ON k.capture_id = c.capture_id
                WHERE k.slot_key IN ({placeholders})
                ORDER BY c.captured_at DESC, c.capture_id DESC
            ''', slot_keys).fetchall()
            return [dict(r) for r in rows]

    def get_many(self, capture_ids: List[str]) -> List[Dict]:
        if not capture_ids:
            return []
        placeholders = ','.join('?' * len(capture_ids))
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f'SELECT * FROM backup_capture WHERE capture_id IN ({placeholders})',
                capture_ids,
            ).fetchall()
            return [dict(r) for r in rows]
