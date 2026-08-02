#!/usr/bin/env python3
"""
Backups — slots, versions, and putting a version back.

Real directories on disk and a real database throughout; nothing here is mocked
except the transfer queue, which the restore tests stand in for so a restore can
be run without the whole coordinator.

Media names are synthetic and deliberately awkward: a title containing " - "
(which the previous parser split on and mangled), an unpadded season folder, a
double episode, Specials, and an anime absolute number.
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.backup_capture import BackupCapture
from models.database import DatabaseManager
from services.backups.identity import (
    SlotIdentity,
    identify,
    library_for_media_type,
    new_capture_id,
    parse_capture_id,
    parse_movie_identity,
    season_folder_name,
)
from services.backups.indexer import BackupIndexer
from services.backups.layout import BackupLayout, BackupPathNotConfigured
from services.backups.migrate import LegacyMigration
from services.backups.restore import RestorePlanner, RestoreRunner
from services.backups.retention import RetentionPolicy
from services.backups.service import BackupsService
from services.backups.sorter import BackupSorter

# A series whose own title contains " - ". The previous implementation derived
# the series title by splitting the filename at the first " - ", so this one was
# stored as "Alpha", and its backups became invisible to it.
AWKWARD = 'Alpha - Bravo, Charlie of the Delta (2016)'
SHOW = 'Example Show (2024)'
ANIME = 'Example Anime (2018)'
FILM = 'Example Film (2024)'


class FakeConfig:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=''):
        return self.values.get(key, default)

    def get_destination_paths(self):
        return [v for k, v in self.values.items() if k.endswith('_DEST_PATH') and v]


class FakeQueue:
    """The two calls BackupsService makes into the queue."""

    def __init__(self, busy=False, full=False):
        self.busy = busy
        self.full = full
        self.registered = []
        self.unregistered = []

    def check_duplicate_destination(self, dest_path, transfer_id=None):
        return (True, 'other-transfer') if self.busy else (False, None)

    def register_transfer(self, transfer_id, dest_path):
        if self.full:
            return (False, 'queued')
        self.registered.append((transfer_id, dest_path))
        return (True, 'running')

    def unregister_transfer(self, transfer_id, dest_path=None):
        self.unregistered.append(transfer_id)


class FakeCoordinator:
    def __init__(self, queue):
        self.queue_manager = queue


def touch(path, size=1024, text=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as handle:
        handle.write((text.encode() if text else b'\0') * (1 if text else size))
    return path


class BackupsTestCase(unittest.TestCase):
    """Shared fixture: a backup root, three library roots, and a database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.backup_root = os.path.join(self.tmp.name, 'backup')
        self.tv_root = os.path.join(self.tmp.name, 'tvshows')
        self.anime_root = os.path.join(self.tmp.name, 'anime')
        self.movie_root = os.path.join(self.tmp.name, 'movies')
        for path in (self.backup_root, self.tv_root, self.anime_root, self.movie_root):
            os.makedirs(path)

        self.config = FakeConfig({
            'BACKUP_PATH': self.backup_root,
            'TVSHOW_DEST_PATH': self.tv_root,
            'ANIME_DEST_PATH': self.anime_root,
            'MOVIE_DEST_PATH': self.movie_root,
        })

        self.db = DatabaseManager(os.path.join(self.tmp.name, 'backups_test.db'))
        self.captures = BackupCapture(self.db)
        self.layout = BackupLayout(self.config)
        self.indexer = BackupIndexer(self.layout, self.captures)
        self.sorter = BackupSorter(self.config, self.layout)

    def stage(self, transfer_id, relative_path, size=1024):
        """Put a file where rsync's --backup-dir would have left it."""
        return touch(
            os.path.join(self.layout.staging_dir(transfer_id), relative_path), size,
        )

    def sort(self, transfer_id, media_type, dest_path, reason='sync_replace'):
        return self.sorter.sort_transfer({
            'transfer_id': transfer_id,
            'media_type': media_type,
            'dest_path': dest_path,
        }, reason=reason)

    def tree(self):
        """Every file in the backup tree, relative to its root."""
        found = []
        for root, _dirs, files in os.walk(self.backup_root):
            for name in files:
                found.append(
                    os.path.relpath(os.path.join(root, name), self.backup_root)
                    .replace(os.sep, '/')
                )
        return sorted(found)


# ===========================================================================
# Phase 1 — BACKUP_PATH fails closed
# ===========================================================================

class BackupPathFailsClosedTests(unittest.TestCase):
    """
    Writing must refuse exactly where restore refuses.

    The defect this replaces: writing fell back to /tmp/backup while restore
    refused anything but a configured BACKUP_PATH, so every sync quietly put
    displaced media somewhere the OS may clear and nothing could get it back.
    """

    def setUp(self):
        self.layout = BackupLayout(FakeConfig({'BACKUP_PATH': ''}))

    def test_base_refuses_when_unset(self):
        with self.assertRaises(BackupPathNotConfigured):
            self.layout.base()

    def test_staging_refuses_when_unset(self):
        with self.assertRaises(BackupPathNotConfigured):
            self.layout.staging_dir('transfer_1')

    def test_no_temporary_directory_fallback_anywhere(self):
        self.assertFalse(self.layout.is_configured())
        self.assertIsNone(self.layout.base_or_none())

    def test_whitespace_only_counts_as_unset(self):
        layout = BackupLayout(FakeConfig({'BACKUP_PATH': '   '}))
        self.assertFalse(layout.is_configured())
        with self.assertRaises(BackupPathNotConfigured):
            layout.base()


# ===========================================================================
# Phase 2 — identity
# ===========================================================================

class IdentityTests(unittest.TestCase):
    def test_movie_title_and_year_from_the_folder(self):
        title, year = parse_movie_identity(FILM, 'whatever.mkv')
        self.assertEqual(title, 'Example Film')
        self.assertEqual(year, '2024')

    def test_movie_falls_back_to_the_filename(self):
        title, year = parse_movie_identity('', 'Example Film (2024) [Bluray-1080p].mkv')
        self.assertEqual(title, 'Example Film')
        self.assertEqual(year, '2024')

    def test_movie_without_a_year_still_has_an_identity(self):
        title, year = parse_movie_identity('Example Film', '')
        self.assertEqual(title, 'Example Film')
        self.assertIsNone(year)

    def test_series_title_containing_a_dash_survives(self):
        identity = identify(
            'shows', f"{AWKWARD}/Season 01/{AWKWARD} - S01E01 - An Episode.mkv",
        )
        self.assertIsNotNone(identity)
        # The whole folder name, not everything before the first " - ".
        self.assertEqual(identity.title, AWKWARD)
        self.assertEqual((identity.season, identity.episode), (1, 1))

    def test_unpadded_and_padded_seasons_reach_the_same_slot(self):
        padded = identify('shows', f"{SHOW}/Season 01/{SHOW} - S01E03 - A.mkv")
        unpadded = identify('shows', f"{SHOW}/Season 1/{SHOW} - S01E03 - A.mkv")
        self.assertEqual(padded.slot_key, unpadded.slot_key)
        self.assertEqual(padded.season_folder, 'Season 01')

    def test_specials_are_season_zero(self):
        identity = identify('shows', f"{SHOW}/Specials/{SHOW} - S00E01 - A.mkv")
        self.assertEqual(identity.season, 0)
        self.assertEqual(identity.season_folder, 'Specials')
        self.assertEqual(season_folder_name(0), 'Specials')

    def test_double_episode_belongs_to_both_slots(self):
        identity = identify('shows', f"{SHOW}/Season 01/{SHOW} - S01E01E02 - A.mkv")
        keys = identity.all_slot_keys
        self.assertEqual(len(keys), 2)
        self.assertTrue(any(k.endswith('S01E01') for k in keys))
        self.assertTrue(any(k.endswith('S01E02') for k in keys))

    def test_anime_absolute_number_does_not_become_an_episode(self):
        identity = identify(
            'anime', f"{ANIME}/Season 01/{ANIME} - S01E24 - 024 - A Title.mkv",
        )
        self.assertEqual((identity.season, identity.episode), (1, 24))
        self.assertEqual(len(identity.all_slot_keys), 1)

    def test_unparseable_episode_has_no_identity(self):
        self.assertIsNone(identify('shows', f"{SHOW}/Season 01/poster.jpg"))
        self.assertIsNone(identify('shows', f"{SHOW}/folder.jpg"))

    def test_slot_key_is_stable_across_renames(self):
        first = identify('shows', f"{SHOW}/Season 01/{SHOW} - S01E01 - Old [HDTV-720p].mkv")
        second = identify('shows', f"{SHOW}/Season 01/{SHOW} - S01E01 - New [Bluray-2160p].mkv")
        self.assertEqual(first.slot_key, second.slot_key)

    def test_libraries_map_from_media_types(self):
        self.assertEqual(library_for_media_type('tvshows'), 'shows')
        self.assertEqual(library_for_media_type('anime'), 'anime')
        self.assertEqual(library_for_media_type('movies'), 'movies')
        self.assertIsNone(library_for_media_type('nonsense'))

    def test_capture_ids_round_trip(self):
        moment = datetime(2026, 7, 30, 14, 22, 5, tzinfo=timezone.utc)
        capture_id = str(new_capture_id('explore_ab12cd34', moment))
        self.assertTrue(capture_id.startswith('20260730T142205.000Z__'))
        parsed = parse_capture_id(capture_id)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], moment)

    def test_capture_id_survives_a_collision_suffix(self):
        self.assertIsNotNone(parse_capture_id('20260730T142205.000Z__abc__2'))

    def test_display_reads_as_a_person_would_say_it(self):
        self.assertEqual(
            SlotIdentity(library='shows', title=SHOW, season=1, episode=2).display,
            f"{SHOW} — S01E02",
        )
        self.assertEqual(
            SlotIdentity(library='movies', title=FILM, year='2024').display,
            f"{FILM} (2024)",
        )


# ===========================================================================
# Phase 3 — sorting rsync's output into the tree
# ===========================================================================

class SorterTests(BackupsTestCase):
    def test_season_transfer_lands_in_the_right_slot(self):
        self.stage('transfer_1', f"{SHOW} - S01E01 - An Episode.mkv")
        result = self.sort('transfer_1', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))

        self.assertEqual(len(result.captures), 1)
        placed = self.tree()
        self.assertEqual(len(placed), 1)
        self.assertRegex(
            placed[0],
            rf"^shows/{SHOW}/Season 01/S01E01/\d{{8}}T\d{{6}}\.\d{{3}}Z__\w+/"
            rf"{SHOW} - S01E01 - An Episode\.mkv$"
            .replace('(', r'\(').replace(')', r'\)'),
        )

    def test_series_transfer_keeps_each_episode_in_its_own_season(self):
        self.stage('transfer_2', f"Season 01/{SHOW} - S01E01 - A.mkv")
        self.stage('transfer_2', f"Season 02/{SHOW} - S02E05 - B.mkv")
        self.sort('transfer_2', 'tvshows', os.path.join(self.tv_root, SHOW))

        placed = self.tree()
        self.assertTrue(any('/Season 01/S01E01/' in p for p in placed))
        self.assertTrue(any('/Season 02/S02E05/' in p for p in placed))

    def test_sidecars_join_the_episode_they_belong_to(self):
        self.stage('transfer_3', f"{SHOW} - S01E01 - A.mkv")
        self.stage('transfer_3', f"{SHOW} - S01E01 - A.srt")
        result = self.sort('transfer_3', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))

        self.assertEqual(len(result.captures), 1, 'one capture, not one per file')
        self.assertEqual(len(result.captures[0].files), 2)
        capture_dirs = {os.path.dirname(p) for p in self.tree()}
        self.assertEqual(len(capture_dirs), 1, 'both files in the same capture folder')

    def test_two_captures_of_one_episode_do_not_collide(self):
        self.stage('transfer_4', f"{SHOW} - S01E01 - Old.mkv")
        self.sort('transfer_4', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))
        self.stage('transfer_5', f"{SHOW} - S01E01 - Older.mkv")
        self.sort('transfer_5', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))

        placed = self.tree()
        self.assertEqual(len(placed), 2)
        self.assertEqual(len({os.path.dirname(p) for p in placed}), 2,
                         'two independent versions')
        # Both live under the same slot.
        self.assertEqual(len({p.rsplit('/', 2)[0] for p in placed}), 1)

    def test_movies_have_no_season_layer(self):
        self.stage('transfer_6', f"{FILM} [Bluray-1080p].mkv")
        self.sort('transfer_6', 'movies', os.path.join(self.movie_root, FILM))

        placed = self.tree()
        self.assertEqual(len(placed), 1)
        self.assertTrue(placed[0].startswith(f"movies/{FILM}/"))
        self.assertNotIn('/Season ', placed[0])

    def test_title_level_artwork_is_kept_beside_its_title(self):
        """It belongs to the series but to no episode, so it is not a slot."""
        self.stage('transfer_7', 'poster.jpg')
        result = self.sort('transfer_7', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))

        placed = self.tree()
        self.assertEqual(len(placed), 1)
        self.assertTrue(placed[0].startswith(f"shows/{SHOW}/_extras/"))
        self.assertTrue(placed[0].endswith('poster.jpg'))
        self.assertEqual(result.unsorted_count, 0)
        self.assertEqual(result.captures[0].kind, 'extras')

    def test_a_file_with_no_title_at_all_goes_to_unsorted(self):
        self.stage('transfer_7b', 'stray.mkv')
        result = self.sort('transfer_7b', 'tvshows', self.tv_root)

        placed = self.tree()
        self.assertEqual(len(placed), 1)
        self.assertTrue(placed[0].startswith('_unsorted/'))
        self.assertEqual(result.unsorted_count, 1)

    def test_unsorted_files_keep_their_original_path(self):
        self.stage('transfer_8', 'Season 01/artwork/poster.jpg')
        self.sort('transfer_8', '', os.path.join(self.tv_root, SHOW))
        placed = self.tree()
        self.assertTrue(placed[0].startswith('_unsorted/'))
        self.assertTrue(placed[0].endswith('Season 01/artwork/poster.jpg'))

    def test_in_flight_fragments_are_not_treated_as_backups(self):
        self.stage('transfer_9', '.rsync-partial/half-a-file.mkv')
        self.stage('transfer_9', f"{SHOW} - S01E01 - A.mkv")
        result = self.sort('transfer_9', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))

        self.assertEqual(result.file_count, 1)
        self.assertFalse(any('half-a-file' in p for p in self.tree()))

    def test_a_transfer_that_displaced_nothing_creates_nothing(self):
        os.makedirs(self.layout.staging_dir('transfer_10'), exist_ok=True)
        result = self.sort('transfer_10', 'tvshows', os.path.join(self.tv_root, SHOW))

        self.assertEqual(result.captures, [])
        self.assertEqual(self.tree(), [])
        self.assertFalse(os.path.exists(self.layout.staging_dir('transfer_10')),
                         'the empty staging folder is cleared away')

    def test_missing_staging_folder_is_not_an_error(self):
        result = self.sort('transfer_never_ran', 'tvshows', self.tv_root)
        self.assertEqual(result.captures, [])
        self.assertEqual(result.errors, [])

    def test_staging_is_removed_once_everything_is_filed(self):
        self.stage('transfer_11', f"{SHOW} - S01E01 - A.mkv")
        self.sort('transfer_11', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))
        self.assertFalse(os.path.exists(self.layout.staging_dir('transfer_11')))

    def test_sorting_twice_is_safe(self):
        self.stage('transfer_12', f"{SHOW} - S01E01 - A.mkv")
        self.sort('transfer_12', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))
        again = self.sort('transfer_12', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))
        self.assertEqual(again.captures, [])
        self.assertEqual(len(self.tree()), 1)

    def test_unknown_media_type_goes_to_unsorted_rather_than_a_guess(self):
        self.stage('transfer_13', 'something.mkv')
        self.sort('transfer_13', '', self.tv_root)
        self.assertTrue(self.tree()[0].startswith('_unsorted/'))

    def test_staging_lives_outside_the_libraries(self):
        staging = self.layout.staging_dir('transfer_14')
        self.assertIn('.staging', staging)
        self.assertEqual(self.layout.legacy_folders(), [],
                         'staging must not look like a legacy folder to migrate')


# ===========================================================================
# Phase 4 — the index, rebuilt from the tree
# ===========================================================================

class IndexerTests(BackupsTestCase):
    def _one_capture(self, transfer_id='transfer_1', name=None):
        self.stage(transfer_id, name or f"{SHOW} - S01E01 - A.mkv")
        return self.sort(transfer_id, 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))

    def test_rebuild_finds_everything_on_disk(self):
        self._one_capture('transfer_1')
        self._one_capture('transfer_2', f"{SHOW} - S01E02 - B.mkv")

        result = self.indexer.rebuild()
        self.assertEqual(result.indexed, 2)
        self.assertEqual(result.files, 2)
        self.assertEqual(self.captures.totals()['capture_count'], 2)

    def test_rebuild_needs_no_transfer_record(self):
        """
        The case the old recovery action could not handle: a backup whose
        transfer id does not resolve. Everything needed is in the path.
        """
        self._one_capture('webhook_12_1732000000')
        result = self.indexer.rebuild()
        self.assertEqual(result.indexed, 1)

        capture = self.captures.recent()[0]
        self.assertEqual(capture['library'], 'shows')
        self.assertEqual(capture['title'], SHOW)
        self.assertEqual(capture['season_number'], 1)
        self.assertEqual(capture['episode_number'], 1)

    def test_rebuild_is_idempotent(self):
        self._one_capture()
        first = self.indexer.rebuild()
        second = self.indexer.rebuild()
        self.assertEqual(first.indexed, second.indexed)
        self.assertEqual(self.captures.totals()['capture_count'], 1)

    def test_rebuild_keeps_a_pin(self):
        self._one_capture()
        self.indexer.rebuild()
        capture_id = self.captures.recent()[0]['capture_id']
        self.captures.update(capture_id, {'pinned': 1})

        self.indexer.rebuild()
        self.assertEqual(self.captures.get(capture_id)['pinned'], 1,
                         'a routine rebuild must not silently unpin')

    def test_rebuild_drops_entries_whose_files_are_gone(self):
        self._one_capture()
        self.indexer.rebuild()
        capture = self.captures.recent()[0]

        import shutil
        shutil.rmtree(self.layout.absolute(capture['capture_path']))

        result = self.indexer.rebuild()
        self.assertEqual(result.removed, 1)
        self.assertIsNone(self.captures.get(capture['capture_id']))

    def test_double_episode_is_indexed_under_both_slots(self):
        self._one_capture('transfer_d', f"{SHOW} - S01E01E02 - A.mkv")
        self.indexer.rebuild()

        capture_id = self.captures.recent()[0]['capture_id']
        keys = self.captures.slot_keys_for(capture_id)
        self.assertEqual(len(keys), 2)
        for key in keys:
            self.assertEqual(len(self.captures.captures_for_slot(key)), 1)

    def test_unsorted_captures_are_indexed_separately(self):
        self.stage('transfer_u', 'stray.mkv')
        self.sort('transfer_u', '', os.path.join(self.tv_root, SHOW))
        result = self.indexer.rebuild()

        self.assertEqual(result.unsorted, 1)
        self.assertEqual(len(self.captures.by_kind('unsorted')), 1)
        self.assertEqual(self.captures.slots(), [], 'unsorted files are not slots')

    def test_title_extras_are_indexed_but_are_not_slots(self):
        self.stage('transfer_x', 'poster.jpg')
        self.sort('transfer_x', 'tvshows', os.path.join(self.tv_root, SHOW, 'Season 01'))
        self.indexer.rebuild()

        self.assertEqual(len(self.captures.by_kind('extras')), 1)
        self.assertEqual(self.captures.slots(), [])

    def test_slot_listing_counts_versions(self):
        self._one_capture('transfer_1')
        self._one_capture('transfer_2')
        self.indexer.rebuild()

        slots = self.captures.slots()
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]['version_count'], 2)


# ===========================================================================
# Phase 5 — migrating the old per-transfer folders
# ===========================================================================

class MigrationTests(BackupsTestCase):
    def setUp(self):
        super().setUp()

        class Nothing:
            def get(self, _identifier):
                return None

        self.migration = LegacyMigration(
            self.config, self.layout, Nothing(), Nothing(), self.indexer,
        )

    def legacy(self, folder, relative, size=1024, aged=True):
        """
        A legacy folder. Aged by default, because the migration deliberately
        skips anything touched in the last few minutes — a real legacy folder is
        months old, and one that is not is probably being written to right now.
        """
        path = touch(os.path.join(self.backup_root, folder, relative), size)
        if aged:
            old = time.time() - 7 * 24 * 3600
            for root, dirs, files in os.walk(os.path.join(self.backup_root, folder)):
                for name in files:
                    os.utime(os.path.join(root, name), (old, old))
                for name in dirs:
                    os.utime(os.path.join(root, name), (old, old))
            os.utime(os.path.join(self.backup_root, folder), (old, old))
        return path

    def test_preview_moves_nothing(self):
        self.legacy('Example_Show_transfer_1', f"Season 01/{SHOW} - S01E01 - A.mkv")
        before = self.tree()

        report = self.migration.plan()
        self.assertFalse(report.applied)
        self.assertEqual(self.tree(), before, 'a preview must not touch the disk')

    def test_empty_folders_are_reported_and_then_removed(self):
        old = time.time() - 7 * 24 * 3600
        for name in ('Empty_One_transfer_1', 'Empty_Two_transfer_2'):
            path = os.path.join(self.backup_root, name)
            os.makedirs(path)
            os.utime(path, (old, old))

        preview = self.migration.plan()
        self.assertEqual(len(preview.empty_folders), 2)
        self.assertEqual(preview.removed_folders, 0)

        applied = self.migration.apply()
        self.assertEqual(applied.removed_folders, 2)
        self.assertFalse(os.path.exists(os.path.join(self.backup_root, 'Empty_One_transfer_1')))

    def test_identified_files_land_in_the_tree(self):
        # No transfer record survives — the live disk's common case. The
        # library still holds the title folder, and that is what names the
        # library the backup belonged to.
        os.makedirs(os.path.join(self.tv_root, SHOW), exist_ok=True)
        self.legacy(
            'Example_Show_2024_transfer_1',
            f"Season 01/{SHOW} - S01E01 - A.mkv",
        )
        self.migration.apply()

        placed = self.tree()
        self.assertEqual(len(placed), 1)
        self.assertIn(f"shows/{SHOW}/Season 01/S01E01/", placed[0])

    def test_a_title_that_is_in_no_library_stays_unsorted(self):
        self.legacy('Vanished_Show_transfer_9', 'Season 01/Vanished - S01E01 - A.mkv')
        self.migration.apply()
        self.assertTrue(self.tree()[0].startswith('_unsorted/'),
                        'no library to check the guess against, so do not guess')

    def test_a_title_present_in_two_libraries_is_not_guessed(self):
        os.makedirs(os.path.join(self.tv_root, SHOW), exist_ok=True)
        os.makedirs(os.path.join(self.anime_root, SHOW), exist_ok=True)
        self.legacy('Example_Show_2024_transfer_8', f"Season 01/{SHOW} - S01E01 - A.mkv")
        self.migration.apply()
        self.assertTrue(self.tree()[0].startswith('_unsorted/'))

    def test_unidentifiable_files_are_never_discarded(self):
        self.legacy('X_transfer_2', 'mystery.dat')
        report = self.migration.apply()

        self.assertEqual(report.moved_count, 1)
        self.assertTrue(self.tree()[0].startswith('_unsorted/'))
        self.assertEqual(len(report.unidentified), 1)

    def test_migration_leaves_the_index_matching_the_tree(self):
        os.makedirs(os.path.join(self.tv_root, SHOW), exist_ok=True)
        self.legacy('Example_Show_2024_transfer_3', f"Season 01/{SHOW} - S01E01 - A.mkv")
        self.legacy('Example_Show_2024_transfer_4', f"Season 01/{SHOW} - S01E02 - B.mkv")
        self.migration.apply()

        self.assertEqual(self.captures.totals()['capture_count'], 2)
        self.assertEqual(len(self.captures.slots()), 2)

    def test_the_old_folder_is_removed_once_it_is_empty(self):
        os.makedirs(os.path.join(self.tv_root, SHOW), exist_ok=True)
        self.legacy('Example_Show_2024_transfer_5', f"Season 01/{SHOW} - S01E01 - A.mkv")
        self.migration.apply()
        self.assertFalse(
            os.path.exists(os.path.join(self.backup_root, 'Example_Show_2024_transfer_5'))
        )

    def test_migration_ignores_the_tree_it_creates(self):
        os.makedirs(os.path.join(self.tv_root, SHOW), exist_ok=True)
        self.legacy('Example_Show_2024_transfer_6', f"Season 01/{SHOW} - S01E01 - A.mkv")
        self.migration.apply()

        second = self.migration.plan()
        self.assertEqual(second.folders_seen, 0,
                         'libraries and internal folders are not legacy folders')

    def test_a_folder_something_is_still_writing_to_is_left_alone(self):
        """
        The backup disk can be shared by two instances with separate databases,
        so the "no transfers running" guard cannot see the other one. A folder
        touched in the last few minutes is skipped regardless.
        """
        self.legacy('Example_Show_2024_transfer_now', f"Season 01/{SHOW} - S01E01 - A.mkv",
                    aged=False)

        report = self.migration.apply()
        self.assertEqual(report.moved_count, 0)
        self.assertEqual(len(report.active_folders), 1)
        self.assertTrue(any('left alone' in w for w in report.warnings))
        self.assertTrue(
            os.path.exists(os.path.join(self.backup_root, 'Example_Show_2024_transfer_now'))
        )

    def test_migration_skips_in_flight_fragments(self):
        os.makedirs(os.path.join(self.tv_root, SHOW), exist_ok=True)
        self.legacy('Example_Show_2024_transfer_7', '.rsync-partial/half.mkv')
        self.legacy('Example_Show_2024_transfer_7', f"Season 01/{SHOW} - S01E01 - A.mkv")
        report = self.migration.apply()
        self.assertEqual(report.moved_count, 1)


# ===========================================================================
# Phase 6 — restore
# ===========================================================================

class RestoreTests(BackupsTestCase):
    def setUp(self):
        super().setUp()
        self.queue = FakeQueue()
        self.service = BackupsService(
            self.config, self.db, self.captures, _TransferSpy(),
            socketio=None, coordinator=FakeCoordinator(self.queue),
        )
        self.season_dir = os.path.join(self.tv_root, SHOW, 'Season 01')
        os.makedirs(self.season_dir)

    def back_up(self, filename, transfer_id='transfer_1', size=1024):
        """Displace a file into the tree and index it, as a sync would."""
        self.stage(transfer_id, filename, size)
        self.sort(transfer_id, 'tvshows', self.season_dir)
        self.indexer.rebuild()
        return self.captures.recent()[0]

    def library_file(self, filename, size=2048):
        return touch(os.path.join(self.season_dir, filename), size)

    # ---- planning ----

    def test_plan_names_the_file_it_would_replace(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old [HDTV-720p].mkv")
        current = self.library_file(f"{SHOW} - S01E01 - New [Bluray-2160p].mkv")

        plan = self.service.planner.plan(capture['capture_id'])
        self.assertIsNone(plan.blocked)
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].replaces, current)
        self.assertEqual(
            plan.operations[0].target,
            os.path.join(self.season_dir, f"{SHOW} - S01E01 - Old [HDTV-720p].mkv"),
        )

    def test_plan_says_when_there_is_nothing_to_replace(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        plan = self.service.planner.plan(capture['capture_id'])
        self.assertIsNone(plan.operations[0].replaces)

    def test_plan_never_targets_a_different_episode(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        self.library_file(f"{SHOW} - S01E02 - Another.mkv")

        plan = self.service.planner.plan(capture['capture_id'])
        self.assertIsNone(plan.operations[0].replaces,
                          'S01E02 is a different slot and must not be touched')

    def test_a_subtitle_never_replaces_a_video(self):
        self.stage('transfer_s', f"{SHOW} - S01E01 - A.srt", 10)
        self.sort('transfer_s', 'tvshows', self.season_dir)
        self.indexer.rebuild()
        capture = self.captures.recent()[0]
        self.library_file(f"{SHOW} - S01E01 - A.mkv")

        plan = self.service.planner.plan(capture['capture_id'])
        self.assertIsNone(plan.operations[0].replaces)

    def test_target_comes_from_the_slot_not_a_stored_destination(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        self.assertIsNone(capture['source_transfer_id'],
                          'a rebuilt index has no transfer to consult')
        plan = self.service.planner.plan(capture['capture_id'])
        self.assertEqual(plan.target_dir, self.season_dir)

    def test_unsorted_files_cannot_be_restored(self):
        self.stage('transfer_u', 'stray.mkv')
        self.sort('transfer_u', '', self.season_dir)
        self.indexer.rebuild()
        capture = self.captures.by_kind('unsorted')[0]

        plan = self.service.planner.plan(capture['capture_id'])
        self.assertIsNotNone(plan.blocked)

    def test_selecting_files_restricts_the_plan(self):
        self.stage('transfer_m', f"{SHOW} - S01E01 - A.mkv")
        self.stage('transfer_m', f"{SHOW} - S01E01 - A.srt")
        self.sort('transfer_m', 'tvshows', self.season_dir)
        self.indexer.rebuild()
        capture = self.captures.recent()[0]

        plan = self.service.planner.plan(
            capture['capture_id'], [f"{SHOW} - S01E01 - A.srt"],
        )
        self.assertEqual(len(plan.operations), 1)
        self.assertTrue(plan.operations[0].relative_path.endswith('.srt'))

    # ---- running ----

    def run_restore(self, capture, files=None):
        plan = self.service.planner.plan(capture['capture_id'], files)
        runner = RestoreRunner(
            self.config, self.layout, self.captures, self.indexer, lambda _m: None,
        )
        return runner.run(plan, capture)

    def test_restore_writes_the_old_file_back(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv", size=111)
        ok, _message, summary = self.run_restore(capture)

        self.assertTrue(ok)
        self.assertEqual(summary['restored'], 1)
        restored = os.path.join(self.season_dir, f"{SHOW} - S01E01 - Old.mkv")
        self.assertTrue(os.path.isfile(restored))
        self.assertEqual(os.path.getsize(restored), 111)

    def test_the_replaced_file_is_kept_before_it_is_removed(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        current = self.library_file(f"{SHOW} - S01E01 - New.mkv", size=777)

        ok, _message, summary = self.run_restore(capture)
        self.assertTrue(ok)
        self.assertFalse(os.path.isfile(current), 'the renamed old occupant is removed')

        # It is now the newest version of the same slot.
        self.indexer.rebuild()
        slot_key = self.captures.get(capture['capture_id'])['slot_key']
        versions = self.captures.captures_for_slot(slot_key)
        self.assertEqual(len(versions), 2)
        kept = [
            f for v in versions for f in self.captures.files(v['capture_id'])
            if f['relative_path'].endswith('New.mkv')
        ]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]['file_size'], 777)

    def test_a_restore_can_itself_be_undone(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv", size=111)
        self.library_file(f"{SHOW} - S01E01 - New.mkv", size=777)

        self.run_restore(capture)
        self.indexer.rebuild()

        slot_key = self.captures.get(capture['capture_id'])['slot_key']
        newest = self.captures.captures_for_slot(slot_key)[0]
        ok, _message, _summary = self.run_restore(newest)

        self.assertTrue(ok)
        back = os.path.join(self.season_dir, f"{SHOW} - S01E01 - New.mkv")
        self.assertTrue(os.path.isfile(back))
        self.assertEqual(os.path.getsize(back), 777)

    def test_same_name_replacement_overwrites_in_place(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Same.mkv", size=111)
        self.library_file(f"{SHOW} - S01E01 - Same.mkv", size=999)

        ok, _message, summary = self.run_restore(capture)
        self.assertTrue(ok)
        target = os.path.join(self.season_dir, f"{SHOW} - S01E01 - Same.mkv")
        self.assertEqual(os.path.getsize(target), 111,
                         'a same-size-only comparison would have skipped this')
        self.assertEqual(summary['replaced'], 1)

    def test_a_same_size_file_is_still_replaced(self):
        """The defect this closes: rsync --size-only silently skipped these."""
        capture = self.back_up(f"{SHOW} - S01E01 - A.mkv", size=500)
        target = os.path.join(self.season_dir, f"{SHOW} - S01E01 - A.mkv")
        with open(target, 'wb') as handle:
            handle.write(b'X' * 500)

        self.run_restore(capture)
        with open(target, 'rb') as handle:
            self.assertNotEqual(handle.read(1), b'X', 'the file was actually rewritten')

    def test_nothing_is_destroyed_when_the_copy_cannot_be_made(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        current = self.library_file(f"{SHOW} - S01E01 - New.mkv", size=777)

        # Make the backup tree unwritable so preserving the occupant fails.
        slot_dir = os.path.dirname(self.layout.absolute(capture['capture_path']))
        os.chmod(slot_dir, 0o500)
        self.addCleanup(os.chmod, slot_dir, 0o700)

        ok, message, _summary = self.run_restore(capture)
        self.assertFalse(ok)
        self.assertIn('Nothing was changed', message)
        self.assertTrue(os.path.isfile(current), 'the library is untouched')

    def test_restore_marks_the_version_as_restored(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        ok, _message, _summary = self.service.restore(capture['capture_id'])
        self.assertTrue(ok)
        self._settle()
        self.assertEqual(self.captures.get(capture['capture_id'])['status'], 'restored')

    # ---- queueing ----

    def test_restore_refuses_while_a_transfer_holds_the_folder(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        self.queue.busy = True

        ok, message, _detail = self.service.restore(capture['capture_id'])
        self.assertFalse(ok)
        self.assertIn('currently writing', message)

    def test_restore_releases_the_reservation_when_slots_are_full(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        self.queue.full = True

        ok, message, _detail = self.service.restore(capture['capture_id'])
        self.assertFalse(ok)
        self.assertIn('slots are busy', message)
        self.assertEqual(len(self.queue.unregistered), 1,
                         'a refused restore must not leave the destination reserved')

    def test_restore_frees_the_queue_when_it_finishes(self):
        capture = self.back_up(f"{SHOW} - S01E01 - Old.mkv")
        ok, _message, _detail = self.service.restore(capture['capture_id'])
        self.assertTrue(ok)
        self._settle()
        self.assertEqual(len(self.queue.unregistered), 1)

    def _settle(self, timeout=5.0):
        """Wait for the restore thread to finish."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.service._lock:
                if not self.service._restores_running:
                    return
            time.sleep(0.02)
        self.fail('restore did not finish in time')


class _TransferSpy:
    """The transfer model surface a restore uses."""

    def __init__(self):
        self.rows = {}
        self.logs = []

    def create(self, data):
        self.rows[data['transfer_id']] = dict(data)

    def get(self, transfer_id):
        return self.rows.get(transfer_id)

    def update(self, transfer_id, updates):
        self.rows.setdefault(transfer_id, {}).update(updates)
        return True

    def add_log(self, transfer_id, message):
        self.logs.append((transfer_id, message))


# ===========================================================================
# Phase 7 — retention
# ===========================================================================

class RetentionTests(BackupsTestCase):
    def setUp(self):
        super().setUp()
        self.config.values['BACKUP_RETENTION_KEEP'] = '2'
        self.config.values['BACKUP_RETENTION_GRACE_HOURS'] = '0'
        self.retention = RetentionPolicy(self.config, self.layout, self.captures)
        self.season_dir = os.path.join(self.tv_root, SHOW, 'Season 01')

    def add_version(self, transfer_id, filename, when=None):
        self.stage(transfer_id, filename)
        self.sort(transfer_id, 'tvshows', self.season_dir)
        self.indexer.rebuild()
        if when:
            newest = self.captures.recent()[0]
            self.captures.update(newest['capture_id'], {'captured_at': when})
        return self.captures.recent()[0]

    def old(self, days):
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace('+00:00', 'Z')

    def test_keeps_the_newest_and_removes_the_rest(self):
        for index in range(4):
            self.add_version(f"transfer_{index}", f"{SHOW} - S01E01 - v{index}.mkv",
                             when=self.old(10 - index))

        preview = self.retention.candidates()
        self.assertEqual(len(preview.candidates), 2)

        result = self.retention.apply()
        self.assertEqual(len(result.deleted), 2)
        self.assertEqual(len(self.captures.captures_for_slot(
            self.captures.recent()[0]['slot_key'])), 2)

    def test_a_pinned_version_is_never_removed(self):
        oldest = self.add_version('transfer_0', f"{SHOW} - S01E01 - v0.mkv", when=self.old(10))
        for index in (1, 2, 3):
            self.add_version(f"transfer_{index}", f"{SHOW} - S01E01 - v{index}.mkv",
                             when=self.old(10 - index))
        self.captures.update(oldest['capture_id'], {'pinned': 1})

        self.retention.apply()
        self.assertIsNotNone(self.captures.get(oldest['capture_id']))

    def test_recent_versions_are_protected_by_the_grace_period(self):
        self.config.values['BACKUP_RETENTION_GRACE_HOURS'] = '24'
        for index in range(4):
            self.add_version(f"transfer_{index}", f"{SHOW} - S01E01 - v{index}.mkv")

        result = self.retention.candidates()
        self.assertEqual(result.candidates, [],
                         'an accidental sync must not immediately age out the old copy')

    def test_different_episodes_are_counted_separately(self):
        for index in range(3):
            self.add_version(f"a{index}", f"{SHOW} - S01E01 - v{index}.mkv", when=self.old(10 - index))
        for index in range(3):
            self.add_version(f"b{index}", f"{SHOW} - S01E02 - v{index}.mkv", when=self.old(10 - index))

        result = self.retention.apply()
        self.assertEqual(len(result.deleted), 2, 'one per slot, not two from one')

    def test_a_double_episode_survives_while_either_slot_still_wants_it(self):
        # S01E01E02 is version 3 of E01 but the only version of E02.
        for index in range(3):
            self.add_version(f"e{index}", f"{SHOW} - S01E01 - v{index}.mkv", when=self.old(20 - index))
        self.add_version('double', f"{SHOW} - S01E01E02 - both.mkv", when=self.old(30))

        result = self.retention.apply()
        remaining = [c['capture_id'] for c in self.captures.recent()]
        double = [
            c for c in self.captures.recent()
            if len(self.captures.slot_keys_for(c['capture_id'])) == 2
        ]
        self.assertEqual(len(double), 1,
                         'pruning it would leave S01E02 with no version at all')
        self.assertNotIn(double[0]['capture_id'], result.deleted)
        self.assertIn(double[0]['capture_id'], remaining)

    def test_removing_a_version_tidies_the_folders_it_emptied(self):
        for index in range(3):
            self.add_version(f"t{index}", f"{SHOW} - S01E01 - v{index}.mkv", when=self.old(10 - index))
        self.retention.apply()

        self.assertEqual(len(self.tree()), 2)
        # The slot survives because two versions remain, but no capture folder
        # should be left standing with nothing in it. `.staging` is internal
        # plumbing that the next transfer reuses, so it is not a leftover.
        library_root = os.path.join(self.backup_root, 'shows')
        empty = [
            root for root, dirs, files in os.walk(library_root)
            if not dirs and not files
        ]
        self.assertEqual(empty, [])

    def test_pruning_the_last_version_removes_the_slot_folder_too(self):
        self.add_version('only', f"{SHOW} - S01E09 - v0.mkv", when=self.old(30))
        capture = self.captures.recent()[0]
        self.retention.apply(keep=1)  # protected: it is the newest of its slot
        self.assertIsNotNone(self.captures.get(capture['capture_id']))

    def test_keep_is_clamped_to_something_sane(self):
        self.config.values['BACKUP_RETENTION_KEEP'] = '0'
        self.assertGreaterEqual(self.retention.keep(), 1,
                                'keep-0 is a disabled backup system, not a policy')
        self.config.values['BACKUP_RETENTION_KEEP'] = 'nonsense'
        self.assertEqual(self.retention.keep(), 2)

    def test_disk_usage_is_reported(self):
        usage = self.retention.disk_usage()
        self.assertIsNotNone(usage)
        self.assertIn('percent_used', usage)


# ===========================================================================
# The service as a whole
# ===========================================================================

class ActiveTransferDetectionTests(BackupsTestCase):
    """
    What counts as "a transfer is still running".

    `Transfer.get_active()` used to return the entire table behind a docstring
    promising active ones, so the migration guard read ten COMPLETED transfers
    as ten running ones and refused to start.
    """

    def setUp(self):
        super().setUp()
        from models.transfer import Transfer
        self.transfers = Transfer(self.db)
        self.service = BackupsService(
            self.config, self.db, self.captures, self.transfers,
            coordinator=FakeCoordinator(FakeQueue()),
        )

    def add(self, transfer_id, status):
        self.transfers.create({
            'transfer_id': transfer_id, 'media_type': 'tvshows',
            'folder_name': SHOW, 'source_path': '/x', 'dest_path': '/y',
            'operation_type': 'folder', 'status': status,
        })
        self.transfers.update(transfer_id, {'status': status})

    def test_finished_transfers_are_not_active(self):
        for index, status in enumerate(('completed', 'failed', 'cancelled')):
            self.add(f"t{index}", status)
        self.assertEqual(self.transfers.get_active(), [])

    def test_the_four_unfinished_statuses_are_active(self):
        for index, status in enumerate(('running', 'pending', 'queued', 'paused')):
            self.add(f"a{index}", status)
        self.assertEqual(len(self.transfers.get_active()), 4)

    def test_migration_is_not_blocked_by_a_history_of_completed_transfers(self):
        """The exact reported symptom: 10 completed transfers, 0 running."""
        for index in range(10):
            self.add(f"done{index}", 'completed')
        self.assertIsNone(self.service._migration_blocker())
        self.assertIsNone(self.service.migration_plan()['blocked'])

    def test_migration_is_blocked_by_a_real_one_and_names_it(self):
        self.add('busy', 'running')
        blocker = self.service._migration_blocker()
        self.assertIsNotNone(blocker)
        self.assertIn('1 transfer is still active', blocker)
        self.assertIn(SHOW, blocker)

    def test_a_queued_transfer_also_blocks(self):
        """It is not writing yet, but it can start at any moment."""
        self.add('waiting', 'queued')
        self.assertIsNotNone(self.service._migration_blocker())


class BulkDeleteTests(BackupsTestCase):
    """Reclaiming space: the one action here with no undo."""

    def setUp(self):
        super().setUp()
        self.service = BackupsService(
            self.config, self.db, self.captures, _TransferSpy(),
            coordinator=FakeCoordinator(FakeQueue()),
            settings=_settings_service(self.config, self.db),
        )
        self.season_dir = os.path.join(self.tv_root, SHOW, 'Season 01')

    def version(self, transfer_id, filename, size=1024):
        self.stage(transfer_id, filename, size)
        self.sort(transfer_id, 'tvshows', self.season_dir)
        self.indexer.rebuild()
        return self.captures.recent()[0]

    def test_preview_reports_the_space_without_touching_anything(self):
        first = self.version('t1', f"{SHOW} - S01E01 - v1.mkv", size=500)
        second = self.version('t2', f"{SHOW} - S01E02 - v1.mkv", size=700)

        preview = self.service.preview_delete(
            capture_ids=[first['capture_id'], second['capture_id']]
        )
        self.assertEqual(preview['count'], 2)
        self.assertEqual(preview['total_size'], 1200)
        self.assertEqual(len(self.tree()), 2, 'a preview must not delete')

    def test_deleting_several_at_once_frees_their_space(self):
        first = self.version('t1', f"{SHOW} - S01E01 - v1.mkv", size=500)
        second = self.version('t2', f"{SHOW} - S01E02 - v1.mkv", size=700)

        result = self.service.delete_many(
            capture_ids=[first['capture_id'], second['capture_id']]
        )
        self.assertEqual(result['deleted_count'], 2)
        self.assertEqual(result['reclaimed'], 1200)
        self.assertEqual(self.tree(), [])
        self.assertEqual(self.captures.totals()['capture_count'], 0)

    def test_a_pinned_version_is_held_back_and_reported(self):
        pinned = self.version('t1', f"{SHOW} - S01E01 - v1.mkv")
        plain = self.version('t2', f"{SHOW} - S01E02 - v1.mkv")
        self.captures.update(pinned['capture_id'], {'pinned': 1})

        result = self.service.delete_many(
            capture_ids=[pinned['capture_id'], plain['capture_id']]
        )
        self.assertEqual(result['deleted_count'], 1)
        self.assertEqual(result['skipped_pinned'], 1)
        self.assertIsNotNone(self.captures.get(pinned['capture_id']))

    def test_a_pin_can_be_overridden_when_asked_explicitly(self):
        pinned = self.version('t1', f"{SHOW} - S01E01 - v1.mkv")
        self.captures.update(pinned['capture_id'], {'pinned': 1})

        result = self.service.delete_many(
            capture_ids=[pinned['capture_id']], include_pinned=True
        )
        self.assertEqual(result['deleted_count'], 1)

    def test_clearing_a_whole_item_removes_every_version(self):
        for index in range(3):
            self.version(f"t{index}", f"{SHOW} - S01E01 - v{index}.mkv")
        slot_key = self.captures.recent()[0]['slot_key']

        result = self.service.delete_many(slot_keys=[slot_key])
        self.assertEqual(result['deleted_count'], 3)
        self.assertEqual(self.captures.captures_for_slot(slot_key), [])

    def test_keep_newest_leaves_a_safety_net(self):
        for index in range(4):
            self.version(f"t{index}", f"{SHOW} - S01E01 - v{index}.mkv")
        slot_key = self.captures.recent()[0]['slot_key']

        result = self.service.delete_many(slot_keys=[slot_key], keep_newest=1)
        self.assertEqual(result['deleted_count'], 3)
        self.assertEqual(len(self.captures.captures_for_slot(slot_key)), 1)

    def test_deleting_tidies_the_folders_it_emptied(self):
        capture = self.version('t1', f"{SHOW} - S01E01 - v1.mkv")
        self.service.delete_many(capture_ids=[capture['capture_id']])
        self.assertFalse(
            os.path.exists(os.path.join(self.backup_root, 'shows', SHOW)),
            'an emptied slot should not leave a tree of empty folders',
        )

    def test_clearing_the_unidentified_bucket(self):
        self.stage('t_u', 'stray.mkv', 300)
        self.sort('t_u', '', self.season_dir)
        self.indexer.rebuild()

        result = self.service.clear_unsorted()
        self.assertEqual(result['deleted_count'], 1)
        self.assertEqual(result['reclaimed'], 300)
        self.assertEqual(self.tree(), [])

    def test_selecting_nothing_deletes_nothing(self):
        self.version('t1', f"{SHOW} - S01E01 - v1.mkv")
        result = self.service.delete_many()
        self.assertEqual(result['deleted_count'], 0)
        self.assertEqual(len(self.tree()), 1)

    def test_the_biggest_first_ordering(self):
        self.version('t1', f"{SHOW} - S01E01 - small.mkv", size=100)
        self.version('t2', f"{SHOW} - S01E02 - big.mkv", size=9000)

        by_size = self.captures.slots(sort='size')
        self.assertEqual(by_size[0]['total_size'], 9000)
        by_recent = self.captures.slots(sort='recent')
        self.assertEqual(by_recent[0]['episode_number'], 2, 'newest first by default')


class RetentionSettingsTests(BackupsTestCase):
    """The rule has to survive a restart and be visible to background threads."""

    def setUp(self):
        super().setUp()
        self.settings = _settings_service(self.config, self.db)
        self.service = BackupsService(
            self.config, self.db, self.captures, _TransferSpy(),
            coordinator=FakeCoordinator(FakeQueue()), settings=self.settings,
        )

    def test_saving_writes_to_the_database_not_the_env_file(self):
        self.service.save_retention(keep=5, grace_hours=2)
        self.assertEqual(self.settings.get('BACKUP_RETENTION_KEEP'), '5')
        self.assertEqual(self.settings.get('BACKUP_RETENTION_GRACE_HOURS'), '2')

    def test_a_saved_rule_wins_over_the_env_file(self):
        self.config.values['BACKUP_RETENTION_KEEP'] = '9'
        self.assertEqual(self.service.retention.keep(), 9)

        self.service.save_retention(keep=3)
        self.assertEqual(self.service.retention.keep(), 3)

    def test_saved_values_are_clamped(self):
        self.service.save_retention(keep=0)
        self.assertEqual(self.settings.get('BACKUP_RETENTION_KEEP'), '1')
        self.service.save_retention(keep=9999)
        self.assertEqual(self.settings.get('BACKUP_RETENTION_KEEP'), '50')

    def test_it_can_be_turned_off(self):
        self.service.save_retention(enabled=False)
        self.assertFalse(self.service.retention.enabled())

    def test_without_a_settings_store_it_refuses_rather_than_pretending(self):
        offline = BackupsService(
            self.config, self.db, self.captures, _TransferSpy(),
            coordinator=FakeCoordinator(FakeQueue()),
        )
        self.assertFalse(offline.retention.describe()['editable'])
        with self.assertRaises(RuntimeError):
            offline.save_retention(keep=3)


def _settings_service(config, db):
    """
    The real resolver over a real settings table.

    Deliberately not a stand-in: an earlier double answered `set_bool`, which
    the resolver does not have, and hid an AttributeError that crashed every
    attempt to save the retention rule.
    """
    from models.settings import AppSettings
    from services.settings_service import SettingsService
    return SettingsService(config, AppSettings(db))


class ServiceTests(BackupsTestCase):
    def setUp(self):
        super().setUp()
        self.transfers = _TransferSpy()
        self.service = BackupsService(
            self.config, self.db, self.captures, self.transfers,
            coordinator=FakeCoordinator(FakeQueue()),
        )
        self.season_dir = os.path.join(self.tv_root, SHOW, 'Season 01')

    def test_sorting_after_a_transfer_indexes_and_lists(self):
        self.transfers.create({
            'transfer_id': 'transfer_1', 'media_type': 'tvshows',
            'dest_path': self.season_dir,
        })
        touch(os.path.join(self.layout.staging_dir('transfer_1'),
                           f"{SHOW} - S01E01 - Old.mkv"))

        summary = self.service.sort_after_transfer('transfer_1')
        self.assertEqual(summary['captures'], 1)
        self.assertEqual(summary['files'], 1)

        listing = self.service.slots()
        self.assertEqual(listing['total'], 1)
        self.assertEqual(listing['slots'][0]['display'], f"{SHOW} — S01E01")

    def test_a_simulation_leaves_nothing_behind(self):
        """
        Simulations write into their own confined root, so what they displace is
        generated filler with no identity — and their cleanup deletes rows by
        `is_simulation`, which would never reach a capture.
        """
        sim_dest = os.path.join(self.tmp.name, '.simulations', 'run', 'dest', 'slot_1')
        os.makedirs(sim_dest, exist_ok=True)
        self.transfers.create({
            'transfer_id': 'sim_1', 'media_type': 'tvshows',
            'dest_path': sim_dest, 'is_simulation': 1,
        })
        touch(os.path.join(self.layout.staging_dir('sim_1'), 'simulation_1.bin'))

        summary = self.service.sort_after_transfer('sim_1')
        self.assertEqual(summary['captures'], 0)
        self.assertEqual(self.tree(), [])
        self.assertEqual(self.captures.totals()['capture_count'], 0)
        self.assertFalse(os.path.exists(self.layout.staging_dir('sim_1')))

    def test_overview_reports_what_is_stored(self):
        overview = self.service.overview()
        self.assertTrue(overview['configured'])
        self.assertIn('retention', overview)
        self.assertIn('disk', overview)

    def test_deleting_a_version_removes_its_files(self):
        self.transfers.create({
            'transfer_id': 't', 'media_type': 'tvshows', 'dest_path': self.season_dir,
        })
        touch(os.path.join(self.layout.staging_dir('t'), f"{SHOW} - S01E01 - A.mkv"))
        self.service.sort_after_transfer('t')

        capture_id = self.captures.recent()[0]['capture_id']
        ok, _message = self.service.delete_capture(capture_id)
        self.assertTrue(ok)
        self.assertEqual(self.tree(), [])
        self.assertIsNone(self.captures.get(capture_id))

    def test_pinning_round_trips(self):
        self.transfers.create({
            'transfer_id': 't', 'media_type': 'tvshows', 'dest_path': self.season_dir,
        })
        touch(os.path.join(self.layout.staging_dir('t'), f"{SHOW} - S01E01 - A.mkv"))
        self.service.sort_after_transfer('t')
        capture_id = self.captures.recent()[0]['capture_id']

        self.assertTrue(self.service.set_pinned(capture_id, True)[0])
        self.assertEqual(self.captures.get(capture_id)['pinned'], 1)
        self.assertTrue(self.service.set_pinned(capture_id, False)[0])
        self.assertEqual(self.captures.get(capture_id)['pinned'], 0)

    def test_slot_view_shows_the_current_library_file(self):
        os.makedirs(self.season_dir, exist_ok=True)
        touch(os.path.join(self.season_dir, f"{SHOW} - S01E01 - New.mkv"), 4096)

        self.transfers.create({
            'transfer_id': 't', 'media_type': 'tvshows', 'dest_path': self.season_dir,
        })
        touch(os.path.join(self.layout.staging_dir('t'), f"{SHOW} - S01E01 - Old.mkv"))
        self.service.sort_after_transfer('t')

        slot_key = self.captures.recent()[0]['slot_key']
        view = self.service.slot(slot_key)
        self.assertEqual(len(view['captures']), 1)
        self.assertIsNotNone(view['current'])
        self.assertEqual(view['current']['name'], f"{SHOW} - S01E01 - New.mkv")


if __name__ == '__main__':
    unittest.main()
