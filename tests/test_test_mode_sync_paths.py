#!/usr/bin/env python3
"""
Test mode, through every way a sync can start.

Since the sync engine, every sync — a Sonarr or Radarr webhook, the
auto-scanner, a press of Sync, an Explore plan, a restart — reaches rsync
through the same few calls. These tests build the real coordinator, transfer
service and queue with TEST_MODE on, start each kind of sync through the
engine, and capture the rsync command instead of running it. Each must carry
`--dry-run`, and no destination folder may be created.

The one deliberate exception is a simulation, which copies its own sandbox
files for real; it is asserted here too, so the exception stays visible.
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.database import DatabaseManager
from services.sync_engine import stages as S
from services.sync_engine.engine import SyncRequest
from services.transfer_coordinator import TransferCoordinator
from services.transfer_service import TransferService

REMOTE_TV = '/remote/tv'
REMOTE_MOVIES = '/remote/movies'


class FakeConfig:
    def __init__(self, root):
        self.values = {
            'REMOTE_USER': 'someone', 'REMOTE_IP': 'remote.example', 'SSH_KEY_PATH': '',
            'SSH_HOST_KEY_CHECKING': 'accept-new',
            'TVSHOW_PATH': REMOTE_TV, 'MOVIE_PATH': REMOTE_MOVIES, 'ANIME_PATH': '/remote/anime',
            'TVSHOW_DEST_PATH': os.path.join(root, 'library', 'tv'),
            'MOVIE_DEST_PATH': os.path.join(root, 'library', 'movies'),
            'ANIME_DEST_PATH': os.path.join(root, 'library', 'anime'),
            'BACKUP_PATH': os.path.join(root, 'backups'),
        }
        # The library roots exist, as on a real installation; what must not
        # appear in test mode is anything inside them.
        for key in ('TVSHOW_DEST_PATH', 'MOVIE_DEST_PATH', 'ANIME_DEST_PATH'):
            os.makedirs(self.values[key], exist_ok=True)

    def get(self, key, default=''):
        return self.values.get(key, default)

    def get_destination_paths(self):
        return [self.values[k] for k in ('MOVIE_DEST_PATH', 'TVSHOW_DEST_PATH',
                                         'ANIME_DEST_PATH')]

    def get_all_allowed_paths(self):
        return self.get_destination_paths()


class FakeProcess:
    """An rsync that started, printed nothing and finished cleanly."""

    def __init__(self, args, **_kwargs):
        self.args = args
        self.pid = 4_000_000
        self.returncode = None
        self.stdout = io.StringIO('')

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -15

    kill = terminate


class RealCoordinatorTestCase(unittest.TestCase):
    """The real coordinator, transfer service and queue, TEST_MODE on, with the
    rsync commands captured instead of run. Holds no tests itself."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.launched = []      # rsync commands Popen was asked to run
        self.dry_checks = []    # the safety check's commands

        def popen(args, **kwargs):
            self.launched.append(list(args))
            return FakeProcess(args, **kwargs)

        def run(args, **kwargs):
            self.dry_checks.append(list(args))
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

        for target, value in (
            ('os.environ', {'TEST_MODE': '1'}),
        ):
            patcher = patch.dict(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, replacement in (
            ('services.transfer_service.subprocess.Popen', popen),
            ('services.transfer_service.subprocess.run', run),
        ):
            patcher = patch(target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(TransferService, '_build_ssh_host_key_options',
                               return_value=['-o', 'StrictHostKeyChecking=accept-new'])
        patcher.start()
        self.addCleanup(patcher.stop)
        # What is checked here is the command rsync is given. The thread that
        # would watch it run outlives the test and writes to a deleted database.
        patcher = patch.object(TransferService, '_monitor_transfer', lambda *args: None)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.config = FakeConfig(self.root)
        self.db = DatabaseManager(os.path.join(self.root, 'paths.db'))
        self.coordinator = TransferCoordinator(self.config, self.db)
        self.coordinator.queue_manager.MAX_CONCURRENT_TRANSFERS = 50
        self.engine = self.coordinator.sync_engine
        self.engine.inline = True
        # The completion watchers poll every few seconds and these copies end
        # at once; there is nothing for a watcher to do in a test.
        self.coordinator._post_transfer_completion = lambda *args, **kwargs: None

    # -- helpers -------------------------------------------------------------

    def tv_dest(self, folder, season=None):
        path = os.path.join(self.config.get('TVSHOW_DEST_PATH'), folder)
        return os.path.join(path, season) if season else path

    def last_rsync(self):
        self.assertTrue(self.launched, 'rsync was never launched')
        return self.launched[-1]

    def assert_dry(self, command, dest):
        self.assertIn('--dry-run', command, f"not a dry run: {command}")
        self.assertFalse(os.path.exists(dest), f"test mode created {dest}")

    def run_state(self, run_id):
        return self.engine.store.get(run_id)['state']



class SyncPathsInTestMode(RealCoordinatorTestCase):

    # -- every kind --------------------------------------------------------

    def test_a_sonarr_webhook_runs_dry(self):
        self.coordinator.series_webhook_model.create({
            'notification_id': 'e1', 'media_type': 'tvshows', 'series_title': 'Example Show',
            'series_title_slug': 'example-show', 'series_id': 7,
            'series_path': f"{REMOTE_TV}/Example Show (2020)", 'tvdb_id': 900001,
            'season_number': 1, 'episodes': [{'seasonNumber': 1, 'episodeNumber': 1}],
            'episode_files': [], 'season_path': f"{REMOTE_TV}/Example Show (2020)/Season 01",
            'status': 'pending'}, '{}')
        run = self.engine.submit(SyncRequest(kind=S.SONARR_WEBHOOK, source='sonarr',
                                             media_type='tvshows',
                                             webhooks=[('sonarr_webhook', 'e1')]))
        # No Sonarr is connected here, so the fallback timer would wait a
        # minute; Go now is the same path from the ready check on.
        self.engine.go_now(run.run_id)
        self.assertEqual(self.run_state(run.run_id), S.TRANSFERRING)
        self.assert_dry(self.last_rsync(), self.tv_dest('Example Show (2020)', 'Season 01'))
        self.assertTrue(all('--dry-run' in c for c in self.dry_checks),
                        'the safety check is always a dry run')

    def test_a_radarr_webhook_runs_dry(self):
        self.coordinator.webhook_model.create({
            'notification_id': 'm1', 'title': 'Example Film', 'year': 2024,
            'folder_path': f"{REMOTE_MOVIES}/Example Film (2024)",
            'file_path': f"{REMOTE_MOVIES}/Example Film (2024)/Example Film (2024).mkv",
            'tmdb_id': 900002, 'status': 'pending'}, '{}')
        run = self.engine.submit(SyncRequest(kind=S.RADARR_WEBHOOK, source='radarr',
                                             media_type='movies',
                                             webhooks=[('radarr_webhook', 'm1')]))
        self.assertEqual(self.run_state(run.run_id), S.TRANSFERRING)
        self.assert_dry(self.last_rsync(), os.path.join(
            self.config.get('MOVIE_DEST_PATH'), 'Example Film (2024)'))

    def test_a_press_of_sync_runs_dry(self):
        dest = self.tv_dest('Example Show (2020)', 'Season 02')
        run = self.engine.submit(SyncRequest(
            kind=S.MANUAL, source='manual', media_type='tvshows',
            source_path=f"{REMOTE_TV}/Example Show (2020)/Season 02", dest_path=dest,
            folder_name='Example Show (2020)', season_name='Season 02', title='Example Show'))
        self.assertEqual(self.run_state(run.run_id), S.TRANSFERRING)
        self.assert_dry(self.last_rsync(), dest)

    def test_an_auto_scanner_find_runs_dry(self):
        dest = os.path.join(self.config.get('MOVIE_DEST_PATH'), 'Another Film (2023)')
        run = self.engine.submit(SyncRequest(
            kind=S.AUTO_SCANNER, source='radarr', media_type='movies',
            source_path=f"{REMOTE_MOVIES}/Another Film (2023)", dest_path=dest,
            folder_name='Another Film (2023)', title='Another Film',
            options={'tmdb_id': '900003'}))
        self.assertEqual(self.run_state(run.run_id), S.TRANSFERRING)
        self.assert_dry(self.last_rsync(), dest)

    def test_a_restart_runs_dry(self):
        dest = self.tv_dest('Example Show (2020)', 'Season 03')
        self.coordinator.transfer_model.create({
            'transfer_id': 'transfer_1', 'media_type': 'tvshows',
            'folder_name': 'Example Show (2020)', 'season_name': 'Season 03',
            'source_path': f"{REMOTE_TV}/Example Show (2020)/Season 03", 'dest_path': dest,
            'operation_type': 'folder', 'status': 'failed'})
        result = self.engine.restart_transfer('transfer_1')
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.run_state(result.run_id), S.TRANSFERRING)
        self.assert_dry(self.last_rsync(), dest)

    def test_an_explore_plan_runs_dry(self):
        dest = self.tv_dest('Example Show (2020)', 'Season 04')
        files_from = os.path.join(self.root, 'plan-files.txt')
        with open(files_from, 'w', encoding='utf-8') as handle:
            handle.write('Example Show - S04E01.mkv\n')
        result = self.engine.submit(SyncRequest(
            kind=S.EXPLORE, source='explore', media_type='tvshows',
            source_path=f"{REMOTE_TV}/Example Show (2020)/Season 04", dest_path=dest,
            folder_name='Example Show (2020)', season_name='Season 04', title='Example Show',
            extra_fields={'explore_files_from': files_from, 'explore_mode': 'sync'},
            safety_summary='Reviewed in Explore.'), wait=True)
        self.assertTrue(result.ok, result.message)
        command = self.last_rsync()
        self.assertTrue(any(arg.startswith('--files-from') for arg in command),
                        'the Explore command shape, not a folder mirror')
        self.assert_dry(command, dest)

    def test_a_simulation_is_the_one_real_copy_and_stays_in_its_sandbox(self):
        sandbox = os.path.join(self.root, '.simulations', 'run_1')
        source = os.path.join(sandbox, 'source')
        dest = os.path.join(sandbox, 'dest')
        os.makedirs(source)
        result = self.engine.submit(SyncRequest(
            kind=S.SIMULATION, media_type='tvshows', source_path=source, dest_path=dest,
            folder_name='Simulation A', title='Simulation A', is_simulation=True), wait=True)
        self.assertTrue(result.ok, result.message)
        command = self.last_rsync()
        self.assertNotIn('--dry-run', command, 'rehearsals copy for real, by design')
        self.assertEqual(command[-2:], [f"{source}/", f"{dest}/"])


if __name__ == '__main__':
    unittest.main()
