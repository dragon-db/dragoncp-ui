#!/usr/bin/env python3
"""
Scoping stored versions to the series and season you are looking at.

Explore's backup panel and the Backups page now read the same index, so this
covers the scoping rules once for both.

The trap this replaces came from real data: the previous implementation matched
a series by a title parsed from the filename by splitting at the first " - ",
so "Alpha - Bravo, Charlie of the Delta (2016)" was stored as "Alpha" and that
series' own backups were invisible to it. Identity now comes from the library
folder and the episode code, so the title is never parsed out of a filename.
"""

import sqlite3
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.explore.store import ExploreStore

AWKWARD = 'Alpha - Bravo, Charlie of the Delta (2016)'


class FakeDB:
    """An in-memory stand-in holding just the backup index."""

    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            '''
            CREATE TABLE backup_capture (
                capture_id TEXT, library TEXT, title TEXT, season_number INTEGER,
                episode_number INTEGER, release_year TEXT, slot_key TEXT,
                capture_path TEXT, captured_at TEXT, source_transfer_id TEXT,
                source_ref TEXT, reason TEXT, kind TEXT, file_count INTEGER,
                total_size INTEGER, pinned INTEGER, status TEXT
            );
            CREATE TABLE backup_capture_file (
                capture_id TEXT, relative_path TEXT, original_path TEXT,
                file_size INTEGER, modified_time INTEGER, is_media INTEGER
            );
            '''
        )

    def get_connection(self):
        outer = self

        class Ctx:
            def __enter__(self):
                return outer.conn

            def __exit__(self, *args):
                return False

        return Ctx()

    def add_capture(self, capture_id, title, season=None, episode=None,
                    library='anime', kind='slot', status='present',
                    captured_at='2026-07-30T10:00:00.000Z', pinned=0):
        code = f"S{season:02d}E{episode:02d}" if season is not None and episode is not None else ''
        self.conn.execute(
            'INSERT INTO backup_capture VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (capture_id, library, title, season, episode, None,
             f"{library}|{title.lower()}|{code}", f"{library}/{title}/{capture_id}",
             captured_at, None, 'ref', 'sync_replace', kind, 0, 0, pinned, status),
        )

    def add_file(self, capture_id, name, size=100, is_media=1):
        self.conn.execute(
            'INSERT INTO backup_capture_file VALUES (?,?,?,?,?,?)',
            (capture_id, name, f'/local/x/{name}', size, 0, is_media),
        )


class BackupScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.store = ExploreStore(self.db)

    def test_a_series_whose_title_contains_a_dash_finds_its_own_versions(self):
        self.db.add_capture('b1', AWKWARD, season=4, episode=4)
        self.db.add_file('b1', f"{AWKWARD} - S04E04 - 070.mkv")

        runs = self.store.backups('anime', AWKWARD)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['files'][0]['code'], 'S04E04')

    def test_another_series_versions_are_not_shown(self):
        self.db.add_capture('b1', 'Other Show (2019)', season=4, episode=29)
        self.db.add_file('b1', 'Other Show - S04E29.mkv')

        self.assertEqual(self.store.backups('anime', 'Another Show (2023)'), [])

    def test_the_same_folder_in_another_library_is_not_shown(self):
        self.db.add_capture('b1', 'Show', season=1, episode=1, library='anime')
        self.db.add_file('b1', 'Show - S01E01.mkv')

        self.assertEqual(self.store.backups('tvshows', 'Show'), [])

    def test_a_version_whose_files_are_gone_is_not_offered(self):
        self.db.add_capture('b1', 'Show', season=1, episode=1, status='files_removed')
        self.db.add_file('b1', 'Show - S01E01.mkv')

        self.assertEqual(self.store.backups('anime', 'Show'), [])

    def test_title_level_extras_are_not_offered_as_versions(self):
        """Artwork belongs to the series but is not a restorable episode."""
        self.db.add_capture('b1', 'Show', kind='extras')
        self.db.add_file('b1', 'poster.jpg', is_media=0)

        self.assertEqual(self.store.backups('anime', 'Show'), [])

    # --- season scoping ----------------------------------------------------

    def test_each_season_keeps_its_own_versions(self):
        """
        A series-level sync used to produce ONE backup spanning several seasons,
        which had to be filtered per file. Now every episode is its own slot, so
        the seasons were never mixed together to begin with.
        """
        self.db.add_capture('b1', 'Show', season=1, episode=1)
        self.db.add_file('b1', 'Show - S01E01.mkv')
        self.db.add_capture('b2', 'Show', season=2, episode=5)
        self.db.add_file('b2', 'Show - S02E05.mkv')

        first = self.store.backups('anime', 'Show', season_number=1)
        self.assertEqual([f['code'] for f in first[0]['files']], ['S01E01'])

        second = self.store.backups('anime', 'Show', season_number=2)
        self.assertEqual([f['code'] for f in second[0]['files']], ['S02E05'])

    def test_a_season_with_nothing_stored_returns_nothing(self):
        self.db.add_capture('b1', 'Show', season=4, episode=3)
        self.db.add_file('b1', 'Show - S04E03.mkv')

        self.assertEqual(len(self.store.backups('anime', 'Show', season_number=4)), 1)
        self.assertEqual(self.store.backups('anime', 'Show', season_number=40), [])

    def test_specials_is_season_zero_not_missing(self):
        self.db.add_capture('b1', 'Show', season=0, episode=2)
        self.db.add_file('b1', 'Show - S00E02.mkv')

        runs = self.store.backups('anime', 'Show', season_number=0)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['files'][0]['code'], 'S00E02')
        self.assertEqual(runs[0]['season_name'], 'Specials')

    # --- what the panel shows ----------------------------------------------

    def test_the_counts_describe_what_is_shown(self):
        self.db.add_capture('b1', 'Show', season=1, episode=1)
        self.db.add_file('b1', 'Show - S01E01.mkv', size=500)
        self.db.add_file('b1', 'Show - S01E01.srt', size=20, is_media=0)

        run = self.store.backups('anime', 'Show', season_number=1)[0]
        self.assertEqual(run['shown_count'], 2, 'the subtitle travels with the episode')
        self.assertEqual(run['shown_size'], 520)

    def test_versions_come_back_newest_first(self):
        self.db.add_capture('old', 'Show', season=1, episode=1,
                            captured_at='2026-01-01T00:00:00.000Z')
        self.db.add_file('old', 'a.mkv')
        self.db.add_capture('new', 'Show', season=1, episode=1,
                            captured_at='2026-07-01T00:00:00.000Z')
        self.db.add_file('new', 'b.mkv')

        self.assertEqual(
            [r['backup_id'] for r in self.store.backups('anime', 'Show')],
            ['new', 'old'],
        )

    def test_a_movie_has_no_season_layer(self):
        self.db.add_capture('b1', 'Example Film (2024)', library='movies')
        self.db.add_file('b1', 'Example Film (2024).mkv')

        runs = self.store.backups('movies', 'Example Film (2024)')
        self.assertEqual(len(runs), 1)
        self.assertIsNone(runs[0]['season_name'])


if __name__ == '__main__':
    unittest.main()
