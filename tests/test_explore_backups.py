#!/usr/bin/env python3
"""
Scoping backups to the series and season you are looking at.

Two traps here, both from real data in the production library:

  * `context_series_title` is parsed by splitting the filename at the first
    " - ", so "Alpha - Bravo, Charlie of the Delta (2016)" is stored as
    "Alpha". Matching on it would hide that series' backups from itself.
  * `context_season` and `context_episode` are stored zero-padded as TEXT
    ('03', not 3), so comparing them to a season number needs a conversion.
"""

import sqlite3
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.explore.store import ExploreStore


class FakeDB:
    """An in-memory stand-in with just the two backup tables."""

    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            '''
            CREATE TABLE backup (
                backup_id TEXT, transfer_id TEXT, media_type TEXT, folder_name TEXT,
                season_name TEXT, backup_path TEXT, dest_path TEXT, file_count INTEGER,
                total_size INTEGER, status TEXT, created_at TEXT, restored_at TEXT
            );
            CREATE TABLE backup_file (
                backup_id TEXT, relative_path TEXT, original_path TEXT, file_size INTEGER,
                modified_time INTEGER, context_season TEXT, context_episode TEXT,
                context_absolute TEXT, context_display TEXT
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

    def add_backup(self, backup_id, folder_name, season_name=None,
                   media_type='anime', status='ready', created_at='2026-07-30T10:00:00Z'):
        self.conn.execute(
            'INSERT INTO backup VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (backup_id, backup_id, media_type, folder_name, season_name,
             f'/backup/{backup_id}', '/local/x', 0, 0, status, created_at, None),
        )

    def add_file(self, backup_id, name, season=None, episode=None, size=100):
        self.conn.execute(
            'INSERT INTO backup_file VALUES (?,?,?,?,?,?,?,?,?)',
            (backup_id, name, f'/local/x/{name}', size, 0, season, episode, None, name),
        )


class BackupScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.store = ExploreStore(self.db)

    def test_a_series_whose_title_the_parser_mangles_still_finds_its_backups(self):
        # The context columns say "Alpha"; the folder says the real name.
        self.db.add_backup('b1', 'Alpha - Bravo, Charlie of the Delta (2016)',
                           season_name='Season 04')
        self.db.add_file('b1', 'Alpha - Bravo ... - S04E04 - 070.mkv', season='04', episode='04')

        runs = self.store.backups('anime', 'Alpha - Bravo, Charlie of the Delta (2016)')
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['files'][0]['code'], 'S04E04')

    def test_another_series_backups_are_not_shown(self):
        self.db.add_backup('b1', 'Other Show (2019)', season_name='Season 04')
        self.db.add_file('b1', 'Other Show - S04E29.mkv', season='04', episode='29')

        self.assertEqual(self.store.backups('anime', 'Another Show (2023)'), [])

    def test_the_same_folder_in_another_library_is_not_shown(self):
        self.db.add_backup('b1', 'Show', media_type='anime')
        self.db.add_file('b1', 'Show - S01E01.mkv', season='01', episode='01')

        self.assertEqual(self.store.backups('tvshows', 'Show'), [])

    def test_a_deleted_backup_is_not_offered(self):
        self.db.add_backup('b1', 'Show', status='deleted')
        self.db.add_file('b1', 'Show - S01E01.mkv', season='01', episode='01')

        self.assertEqual(self.store.backups('anime', 'Show'), [])

    # --- season scoping ----------------------------------------------------

    def test_a_series_sync_backup_is_split_by_the_season_each_file_belongs_to(self):
        # ONE backup holding two seasons — what a series-level sync produces.
        self.db.add_backup('b1', 'Show', season_name=None)
        self.db.add_file('b1', 'Show - S01E01.mkv', season='01', episode='01')
        self.db.add_file('b1', 'Show - S02E05.mkv', season='02', episode='05')

        first = self.store.backups('anime', 'Show', season_number=1, season_name='Season 01')
        self.assertEqual(len(first), 1)
        self.assertEqual([f['code'] for f in first[0]['files']], ['S01E01'])

        second = self.store.backups('anime', 'Show', season_number=2, season_name='Season 02')
        self.assertEqual([f['code'] for f in second[0]['files']], ['S02E05'])

    def test_the_padded_text_season_matches_the_season_number(self):
        self.db.add_backup('b1', 'Show', season_name='Season 04')
        self.db.add_file('b1', 'Show - S04E03.mkv', season='04', episode='03')

        self.assertEqual(len(self.store.backups('anime', 'Show', season_number=4,
                                                season_name='Season 04')), 1)
        self.assertEqual(self.store.backups('anime', 'Show', season_number=40,
                                            season_name='Season 40'), [])

    def test_a_file_with_no_parsed_season_falls_back_to_the_runs_own_folder(self):
        # Artwork and .nfo files carry no episode number.
        self.db.add_backup('b1', 'Show', season_name='Season 02')
        self.db.add_file('b1', 'poster.jpg')

        self.assertEqual(len(self.store.backups('anime', 'Show', season_number=2,
                                                season_name='Season 02')), 1)
        self.assertEqual(self.store.backups('anime', 'Show', season_number=3,
                                            season_name='Season 03'), [])

    def test_a_run_with_nothing_left_after_filtering_is_dropped_entirely(self):
        self.db.add_backup('b1', 'Show', season_name='Season 01')
        self.db.add_file('b1', 'Show - S01E01.mkv', season='01', episode='01')

        self.assertEqual(self.store.backups('anime', 'Show', season_number=9,
                                            season_name='Season 09'), [])

    def test_specials_is_season_zero_not_missing(self):
        self.db.add_backup('b1', 'Show', season_name='Specials')
        self.db.add_file('b1', 'Show - S00E02.mkv', season='00', episode='02')

        runs = self.store.backups('anime', 'Show', season_number=0, season_name='Specials')
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['files'][0]['code'], 'S00E02')

    # --- what the panel shows ----------------------------------------------

    def test_the_counts_describe_what_is_shown_not_the_whole_run(self):
        self.db.add_backup('b1', 'Show', season_name=None)
        self.db.add_file('b1', 'Show - S01E01.mkv', season='01', episode='01', size=500)
        self.db.add_file('b1', 'Show - S02E05.mkv', season='02', episode='05', size=900)

        run = self.store.backups('anime', 'Show', season_number=1, season_name='Season 01')[0]
        self.assertEqual(run['shown_count'], 1)
        self.assertEqual(run['shown_size'], 500)

    def test_runs_come_back_newest_first(self):
        self.db.add_backup('old', 'Show', created_at='2026-01-01T00:00:00Z')
        self.db.add_file('old', 'a.mkv', season='01', episode='01')
        self.db.add_backup('new', 'Show', created_at='2026-07-01T00:00:00Z')
        self.db.add_file('new', 'b.mkv', season='01', episode='01')

        self.assertEqual([r['backup_id'] for r in self.store.backups('anime', 'Show')],
                         ['new', 'old'])


if __name__ == '__main__':
    unittest.main()
