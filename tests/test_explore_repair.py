#!/usr/bin/env python3
"""
Repairing the files the old single-episode download stranded.

The local library here is a real directory on disk — the repair is a rename and
an rmdir, so faking the filesystem would test nothing. The remote side never
comes into it: a repair does not ask the remote anything, and one of the tests
below pins that by running with the browse session down.
"""

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.backup_capture import BackupCapture
from models.database import DatabaseManager
from models.transfer import Transfer
from services.backups.service import BackupsService
from services.explore.service import ExploreError, ExploreService
from tests.test_explore_service import MB, FakeConfig, FakeCoordinator, FakeSSH


class RepairTests(unittest.TestCase):
    """
    Composed from the service suite's fakes rather than inheriting its test
    class — subclassing would re-run its thirty tests here for no extra
    coverage, since both files run anyway.
    """

    SERIES = 'Test Show (2024)'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.local_root = os.path.join(self.tmp.name, 'tv_shows')
        self.backup_root = os.path.join(self.tmp.name, 'backup')
        os.makedirs(self.local_root)
        os.makedirs(self.backup_root)

        self.config = FakeConfig({
            'TVSHOW_PATH': '/remote/TV Shows',
            'TVSHOW_DEST_PATH': self.local_root,
            'MOVIE_PATH': '/remote/Movies',
            'MOVIE_DEST_PATH': os.path.join(self.tmp.name, 'movies'),
            'ANIME_PATH': '/remote/Anime',
            'ANIME_DEST_PATH': os.path.join(self.tmp.name, 'anime'),
            'BACKUP_PATH': self.backup_root,
        })

        self.db = DatabaseManager(os.path.join(self.tmp.name, 'explore_repair.db'))
        self.coordinator = FakeCoordinator(self.backup_root)

        # A real BackupsService over a real tree and a real index. The whole
        # claim of the delete path is that the file is recoverable afterwards,
        # and a stub agreeing that it saved something would not test that.
        self.coordinator.backups = BackupsService(
            self.config, self.db, BackupCapture(self.db), Transfer(self.db),
        )

    def backup_filenames(self):
        """Every file now sitting in the backup tree, by name."""
        found = []
        for dirpath, _, filenames in os.walk(self.backup_root):
            found.extend(filenames)
        return found

    #: Small by default — most of these tests care where a file ends up, not how
    #: big it is, and writing megabytes per file adds up across the suite. Tests
    #: that assert on sizes pass their own.
    def write_local(self, rel, size=4096):
        path = os.path.join(self.local_root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as handle:
            handle.write(b'\0' * size)
        return path

    def stranded(self, season, filename, size=4096):
        """Write a file the way the old download bug did: inside a directory
        named after the file."""
        rel = f"{self.SERIES}/{season}/{filename}/{filename}"
        self.write_local(rel, size)
        return rel

    def placed(self, season, filename, size=4096):
        rel = f"{self.SERIES}/{season}/{filename}"
        self.write_local(rel, size)
        return rel

    def repair_service(self, connected=True):
        return ExploreService(self.config, self.db, self.coordinator,
                              FakeSSH([], connected=connected))

    def exists(self, rel):
        return os.path.exists(os.path.join(self.local_root, rel))

    # ---- planning ---------------------------------------------------------

    def test_plan_names_the_destination_and_moves_nothing(self):
        rel = self.stranded('Season 01', 'Show - S01E01 - Title.mkv')

        plan = self.repair_service().repair_plan('tvshows', self.SERIES)

        self.assertEqual(plan['action_count'], 1)
        action = plan['actions'][0]
        self.assertEqual(action['relative_path'], rel)
        self.assertEqual(
            action['destination'],
            f"{self.SERIES}/Season 01/Show - S01E01 - Title.mkv")
        self.assertEqual(action['season_folder'], 'Season 01')
        self.assertIsNone(plan['blocker'])
        # Read-only: the file is still where it was.
        self.assertTrue(self.exists(rel))

    def test_plan_works_with_the_browse_session_down(self):
        """The stranded file is invisible to the media server right now. Making
        the fix wait on a remote it never touches would be a made-up blocker."""
        self.stranded('Season 01', 'Show - S01E01 - Title.mkv')
        plan = self.repair_service(connected=False).repair_plan('tvshows', self.SERIES)
        self.assertEqual(plan['action_count'], 1)

    def test_season_narrows_the_scope(self):
        self.stranded('Season 01', 'Show - S01E01 - Title.mkv')
        self.stranded('Season 02', 'Show - S02E01 - Title.mkv')

        service = self.repair_service()
        self.assertEqual(service.repair_plan('tvshows', self.SERIES)['action_count'], 2)

        narrowed = service.repair_plan('tvshows', self.SERIES, 'Season 02')
        self.assertEqual(narrowed['action_count'], 1)
        self.assertIn('S02E01', narrowed['actions'][0]['relative_path'])

    def test_a_correctly_placed_library_needs_no_repair(self):
        self.placed('Season 01', 'Show - S01E01 - Title.mkv')
        plan = self.repair_service().repair_plan('tvshows', self.SERIES)
        self.assertEqual(plan['action_count'], 0)
        self.assertEqual(plan['blocked_count'], 0)

    # ---- what it refuses to do -------------------------------------------

    def test_an_occupied_destination_needs_a_decision_and_moves_nothing(self):
        """A second copy buried under some other folder wants the place a real
        episode already holds. Neither is touched until someone chooses."""
        name = 'Show - S01E01 - Title.mkv'
        good = self.placed('Season 01', name, size=20 * MB)
        stranded = f"{self.SERIES}/Season 01/leftovers/{name}"
        self.write_local(stranded, size=5 * MB)

        service = self.repair_service()
        plan = service.repair_plan('tvshows', self.SERIES)
        self.assertEqual(plan['action_count'], 0)
        self.assertEqual(plan['contested_count'], 1)
        self.assertEqual(plan['actions'][0]['rival']['relative_path'], good)

        with self.assertRaises(ExploreError) as caught:
            service.repair_apply('tvshows', self.SERIES)
        self.assertEqual(caught.exception.status, 400)

        # Both copies untouched, and the good one is still the 20 MB one.
        self.assertTrue(self.exists(stranded))
        self.assertEqual(os.path.getsize(os.path.join(self.local_root, good)), 20 * MB)

    def test_a_rival_is_found_by_episode_not_by_filename(self):
        """
        The whole point. A competing copy is a different release, so it carries
        a different name — matching on the path would report no conflict, move
        the file up, and leave the episode in the folder twice.
        """
        existing = self.placed('Season 01', 'Show - S01E01 - Title [Bluray-1080p].mkv',
                               size=20 * MB)
        self.stranded('Season 01', 'Show - S01E01 - Title [WEBDL-720p].mkv', size=5 * MB)

        plan = self.repair_service().repair_plan('tvshows', self.SERIES)

        self.assertEqual(plan['contested_count'], 1)
        rival = plan['actions'][0]['rival']
        self.assertEqual(rival['relative_path'], existing)
        self.assertEqual(rival['size'], 20 * MB)
        self.assertFalse(rival['same_name'])
        self.assertEqual(plan['reclaimable'], 5 * MB)

    def test_a_movie_folder_holding_any_media_file_is_a_rival(self):
        """A movie folder is the slot, so whatever is in it is that film —
        there is no episode code to compare."""
        movie_root = self.config.values['MOVIE_DEST_PATH']
        title = 'Example Film (2024)'
        for rel, size in ((f"{title}/Example Film (2024) [Bluray-1080p].mkv", 30 * MB),
                          (f"{title}/Example Film (2024) [WEBDL-720p].mkv/"
                           f"Example Film (2024) [WEBDL-720p].mkv", 8 * MB)):
            path = os.path.join(movie_root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as handle:
                handle.write(b'\0' * size)

        plan = self.repair_service().repair_plan('movies', title)

        self.assertEqual(plan['contested_count'], 1)
        self.assertIn('Bluray-1080p', plan['actions'][0]['rival']['name'])

    def test_a_different_episode_beside_it_is_not_a_rival(self):
        """Only the same episode counts. The rest of the season is not a
        conflict, and treating it as one would block every repair."""
        self.placed('Season 01', 'Show - S01E02 - Other.mkv')
        self.placed('Season 01', 'Show - S01E03 - Another.mkv')
        self.stranded('Season 01', 'Show - S01E01 - Title.mkv')

        plan = self.repair_service().repair_plan('tvshows', self.SERIES)
        self.assertEqual(plan['action_count'], 1)
        self.assertEqual(plan['contested_count'], 0)

    # ---- deciding between two copies -------------------------------------

    def test_keeping_the_existing_copy_deletes_the_stranded_one_into_backups(self):
        existing = self.placed('Season 01', 'Show - S01E01 - Title [Bluray-1080p].mkv',
                               size=20 * MB)
        stranded_name = 'Show - S01E01 - Title [WEBDL-720p].mkv'
        stranded = self.stranded('Season 01', stranded_name, size=5 * MB)

        service = self.repair_service()
        result = service.repair_apply(
            'tvshows', self.SERIES,
            decisions={stranded: {'choice': 'keep_existing', 'rival': existing}})

        self.assertEqual(result['deleted_count'], 1)
        self.assertEqual(result['moved_count'], 0)
        self.assertEqual(result['freed_size'], 5 * MB)

        self.assertFalse(self.exists(stranded))
        self.assertTrue(self.exists(existing))
        self.assertEqual(os.path.getsize(os.path.join(self.local_root, existing)), 20 * MB)
        # The wrapper folder went with it.
        self.assertFalse(self.exists(f"{self.SERIES}/Season 01/{stranded_name}"))
        # And it is recoverable rather than gone: on disk in the backup tree,
        # and in the index, which is what puts it on the Backups page.
        self.assertIn(stranded_name, self.backup_filenames())
        captures = self.coordinator.backups.slots(library='shows')
        self.assertTrue(captures, 'the kept copy was not indexed, so nothing can restore it')

    def test_replacing_puts_the_stranded_copy_in_and_keeps_the_old_one(self):
        existing_name = 'Show - S01E01 - Title [WEBDL-720p].mkv'
        existing = self.placed('Season 01', existing_name, size=5 * MB)
        stranded_name = 'Show - S01E01 - Title [Bluray-1080p].mkv'
        stranded = self.stranded('Season 01', stranded_name, size=20 * MB)

        result = self.repair_service().repair_apply(
            'tvshows', self.SERIES,
            decisions={stranded: {'choice': 'replace', 'rival': existing}})

        self.assertEqual(result['moved_count'], 1)
        self.assertEqual(result['replaced_count'], 1)

        # The better copy is now the one in the season folder...
        self.assertTrue(self.exists(f"{self.SERIES}/Season 01/{stranded_name}"))
        self.assertEqual(
            os.path.getsize(os.path.join(self.local_root, self.SERIES, 'Season 01',
                                         stranded_name)),
            20 * MB)
        # ...the one it displaced is gone from the library...
        self.assertFalse(self.exists(existing))
        # ...but kept, so the swap can be undone.
        self.assertIn(existing_name, self.backup_filenames())

    def test_a_contested_file_with_no_choice_is_reported_not_guessed(self):
        self.placed('Season 01', 'Show - S01E01 - A [Bluray-1080p].mkv')
        contested = self.stranded('Season 01', 'Show - S01E01 - A [WEBDL-720p].mkv')
        clean = self.stranded('Season 01', 'Show - S01E02 - B.mkv')

        result = self.repair_service().repair_apply('tvshows', self.SERIES)

        # The uncontested one still runs; the contested one is named.
        self.assertEqual(result['moved_count'], 1)
        self.assertEqual(result['failed_count'], 1)
        self.assertEqual(result['failed'][0]['relative_path'], contested)
        self.assertIn('no choice was made', result['failed'][0]['error'])
        self.assertTrue(self.exists(contested))
        self.assertFalse(self.exists(clean))

    def test_a_decision_about_a_copy_that_has_since_changed_is_refused(self):
        """
        The choice was made looking at one specific other copy. If a different
        one is there by the time it runs, the choice was about something else —
        and this deletes files, so it asks again rather than assuming.
        """
        self.placed('Season 01', 'Show - S01E01 - A [Bluray-1080p].mkv')
        stranded = self.stranded('Season 01', 'Show - S01E01 - A [WEBDL-720p].mkv')

        result = self.repair_service().repair_apply(
            'tvshows', self.SERIES,
            decisions={stranded: {
                'choice': 'keep_existing',
                'rival': f"{self.SERIES}/Season 01/Show - S01E01 - A [something else].mkv",
            }})

        self.assertEqual(result['deleted_count'], 0)
        self.assertEqual(result['failed_count'], 1)
        self.assertIn('has changed since you looked', result['failed'][0]['error'])
        self.assertTrue(self.exists(stranded))

    def test_a_replace_that_cannot_finish_says_where_the_other_copy_went(self):
        """
        Once the copy in place is captured and removed, a later failure leaves
        the episode only in Backups. The operator has to be told that, or they
        are left with a rename error and a missing episode.
        """
        existing = self.placed('Season 01', 'Show - S01E01 - A [WEBDL-720p].mkv')
        stranded = self.stranded('Season 01', 'Show - S01E01 - A [Bluray-1080p].mkv')

        service = self.repair_service()
        real_rename = os.rename
        calls = {'n': 0}

        def flaky(src, dst):
            # Let the rival's removal and the staging rename through, then fail
            # the one that would put the stranded copy in place.
            calls['n'] += 1
            if calls['n'] >= 2:
                raise OSError('disk went away')
            return real_rename(src, dst)

        with unittest.mock.patch('services.explore.repair.os.rename', flaky):
            result = service.repair_apply(
                'tvshows', self.SERIES,
                decisions={stranded: {'choice': 'replace', 'rival': existing}})

        self.assertEqual(result['moved_count'], 0)
        # Not reported as a completed replacement, because it did not complete.
        self.assertEqual(result['replaced_count'], 0)
        self.assertEqual(result['failed_count'], 1)
        self.assertIn('already been moved to Backups', result['failed'][0]['error'])
        # And the copy that was displaced really is recoverable.
        self.assertIn('Show - S01E01 - A [WEBDL-720p].mkv', self.backup_filenames())

    def test_nothing_is_deleted_when_the_copy_cannot_be_preserved(self):
        """
        The backup capture is what makes deletion reversible, so a failure to
        capture has to stop the deletion rather than proceed without it.
        """
        rival = self.placed('Season 01', 'Show - S01E01 - A [Bluray-1080p].mkv')
        stranded = self.stranded('Season 01', 'Show - S01E01 - A [WEBDL-720p].mkv')

        service = self.repair_service()
        # No backups service behind the coordinator: nowhere to preserve into.
        del self.coordinator.backups

        result = service.repair_apply(
            'tvshows', self.SERIES,
            decisions={stranded: {'choice': 'keep_existing', 'rival': rival}})

        self.assertEqual(result['deleted_count'], 0)
        self.assertEqual(result['failed_count'], 1)
        self.assertIn('could not keep a copy', result['failed'][0]['error'])
        self.assertTrue(self.exists(stranded))

    def test_two_stranded_copies_wanting_one_path_stop_after_the_first(self):
        """Which copy to keep is a decision, not a repair. The second is
        reported rather than silently dropped or silently preferred."""
        name = 'Show - S01E01 - Title.mkv'
        self.write_local(f"{self.SERIES}/Season 01/{name}/{name}")
        self.write_local(f"{self.SERIES}/Season 01/copy/{name}")

        plan = self.repair_service().repair_plan('tvshows', self.SERIES)
        self.assertEqual(plan['action_count'], 1)
        self.assertEqual(plan['blocked_count'], 1)
        self.assertIn('same path', plan['blocked'][0]['reason'])

    def test_a_file_above_its_season_folder_is_reported_not_guessed(self):
        """It carries no season, and reading one off the filename would be a
        rename wearing a repair's clothes."""
        self.write_local(f"{self.SERIES}/Show - S01E01 - Title.mkv")

        plan = self.repair_service().repair_plan('tvshows', self.SERIES)
        self.assertEqual(plan['action_count'], 0)
        self.assertEqual(plan['blocked_count'], 1)
        self.assertIn('which season', plan['blocked'][0]['reason'])

    def test_an_active_transfer_on_the_same_title_blocks_the_repair(self):
        self.stranded('Season 01', 'Show - S01E01 - Title.mkv')
        self.coordinator.active = [
            {'media_type': 'tvshows', 'folder_name': self.SERIES, 'status': 'running'},
        ]

        service = self.repair_service()
        self.assertIn('still active', service.repair_plan('tvshows', self.SERIES)['blocker'])
        with self.assertRaises(ExploreError) as caught:
            service.repair_apply('tvshows', self.SERIES)
        self.assertEqual(caught.exception.status, 409)

    def test_a_transfer_on_another_title_does_not_block(self):
        self.stranded('Season 01', 'Show - S01E01 - Title.mkv')
        self.coordinator.active = [
            {'media_type': 'tvshows', 'folder_name': 'Other Show (2020)', 'status': 'running'},
            {'media_type': 'movies', 'folder_name': self.SERIES, 'status': 'running'},
        ]

        result = self.repair_service().repair_apply('tvshows', self.SERIES)
        self.assertEqual(result['moved_count'], 1)

    def test_not_being_able_to_check_blocks_too(self):
        self.stranded('Season 01', 'Show - S01E01 - Title.mkv')
        self.coordinator.active = RuntimeError('database is locked')

        service = self.repair_service()
        self.assertIn('Could not check', service.repair_plan('tvshows', self.SERIES)['blocker'])
        with self.assertRaises(ExploreError):
            service.repair_apply('tvshows', self.SERIES)

    # ---- applying ---------------------------------------------------------

    def test_apply_moves_the_file_and_removes_the_wrapper(self):
        name = 'Show - S01E01 - Title.mkv'
        rel = self.stranded('Season 01', name, size=7 * MB)

        result = self.repair_service().repair_apply('tvshows', self.SERIES)

        self.assertEqual(result['moved_count'], 1)
        self.assertEqual(result['failed_count'], 0)
        self.assertEqual(result['moved_size'], 7 * MB)
        self.assertEqual(result['directories_removed'], 1)

        self.assertFalse(self.exists(rel))
        destination = f"{self.SERIES}/Season 01/{name}"
        self.assertTrue(self.exists(destination))
        self.assertEqual(os.path.getsize(os.path.join(self.local_root, destination)), 7 * MB)
        # The season folder itself survives — it still holds the episode.
        self.assertTrue(self.exists(f"{self.SERIES}/Season 01"))

    def test_an_empty_folder_beside_it_blocks_the_move_at_preview_time(self):
        """
        `rmdir` will not remove a folder holding an empty subfolder, so the
        wrapper could never come down and the move could only fail. Caught in
        the preview rather than reported as a failure afterwards.
        """
        name = 'Show - S01E01 - Title.mkv'
        rel = self.stranded('Season 01', name)
        os.makedirs(os.path.join(self.local_root, self.SERIES, 'Season 01', name, 'subs'))

        service = self.repair_service()
        plan = service.repair_plan('tvshows', self.SERIES)
        self.assertEqual(plan['action_count'], 0)
        self.assertEqual(plan['blocked_count'], 1)

        with self.assertRaises(ExploreError):
            service.repair_apply('tvshows', self.SERIES)
        self.assertTrue(self.exists(rel))

    def test_a_wrapper_holding_anything_else_is_reported_not_emptied(self):
        """The folder has to come down for the file to take its name, so a
        folder with something else in it is a question, not a repair."""
        name = 'Show - S01E01 - Title.mkv'
        rel = self.stranded('Season 01', name)
        self.write_local(f"{self.SERIES}/Season 01/{name}/notes.txt", size=16)

        service = self.repair_service()
        plan = service.repair_plan('tvshows', self.SERIES)
        self.assertEqual(plan['action_count'], 0)
        self.assertEqual(plan['blocked_count'], 1)
        self.assertIn('holds other files', plan['blocked'][0]['reason'])

        with self.assertRaises(ExploreError):
            service.repair_apply('tvshows', self.SERIES)
        self.assertTrue(self.exists(rel))
        self.assertTrue(self.exists(f"{self.SERIES}/Season 01/{name}/notes.txt"))

    def test_apply_repairs_every_stranded_file_in_one_run(self):
        for index in range(1, 4):
            self.stranded('Season 01', f"Show - S01E{index:02d} - Title.mkv")

        result = self.repair_service().repair_apply('tvshows', self.SERIES)

        self.assertEqual(result['moved_count'], 3)
        self.assertEqual(result['directories_removed'], 3)
        for index in range(1, 4):
            self.assertTrue(
                self.exists(f"{self.SERIES}/Season 01/Show - S01E{index:02d} - Title.mkv"))

    def test_apply_with_nothing_to_do_is_a_400_not_a_silent_success(self):
        self.placed('Season 01', 'Show - S01E01 - Title.mkv')
        with self.assertRaises(ExploreError) as caught:
            self.repair_service().repair_apply('tvshows', self.SERIES)
        self.assertEqual(caught.exception.status, 400)

    def test_a_movie_has_no_season_layer(self):
        movie_root = self.config.values['MOVIE_DEST_PATH']
        title = 'Test Movie (2024)'
        name = 'Test Movie (2024) [WEBDL-1080p].mkv'
        path = os.path.join(movie_root, title, name, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as handle:
            handle.write(b'\0' * MB)

        result = self.repair_service().repair_apply('movies', title)

        self.assertEqual(result['moved_count'], 1)
        self.assertTrue(os.path.isfile(os.path.join(movie_root, title, name)))

    # ---- names and traversal ---------------------------------------------

    def test_a_traversal_attempt_in_the_folder_name_is_refused(self):
        service = self.repair_service()
        for folder in ('../etc', 'Show/../..', '..'):
            with self.assertRaises(ExploreError) as caught:
                service.repair_plan('tvshows', folder)
            self.assertEqual(caught.exception.status, 400)

    def test_an_unknown_library_is_a_404(self):
        with self.assertRaises(ExploreError) as caught:
            self.repair_service().repair_plan('books', self.SERIES)
        self.assertEqual(caught.exception.status, 404)


if __name__ == '__main__':
    unittest.main()
