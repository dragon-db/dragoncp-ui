#!/usr/bin/env python3
"""
End-to-end backend test: remote listing -> comparison -> plan -> execution.

The remote side is faked at the ssh boundary (one command in, one listing out),
the local side is a real directory on disk, and the transfer pipeline is faked
at the coordinator boundary — so everything in between is the real code.
"""

import os
import shlex
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from datetime import datetime, timedelta

from models.database import DatabaseManager
from services.explore.store import ExploreStore
from services.explore.service import ExploreError, ExploreService

MB = 1024 * 1024


class FakeSSH:
    """Answers the one `find` command RemoteInventory issues."""

    def __init__(self, rows, directories=(), connected=True):
        self.rows = rows
        self.directories = list(directories)
        self.connected = connected
        self.commands = []

    @staticmethod
    def _quote_remote_path(path):
        return shlex.quote(path)

    def execute_command(self, command):
        self.commands.append(command)
        if not self.connected:
            return 1, '', 'Not connected'
        payload = ''
        for directory in self.directories:
            payload += f"D\t0\t0\t{directory}\0"
        for rel, size, mtime in self.rows:
            payload += f"F\t{size}\t{mtime}\t{rel}\0"
        return 0, payload, ''


class FakeBackupService:
    def __init__(self, root):
        self.root = root

    def _get_dynamic_backup_dir(self, transfer):
        safe = ''.join(c if c.isalnum() else '_' for c in (transfer.get('folder_name') or 'x'))
        return os.path.join(self.root, f"{safe}_{transfer['transfer_id']}")


class FakeCoordinator:
    def __init__(self, backup_root, succeed=True):
        self.backup_service = FakeBackupService(backup_root)
        self.calls = []
        self.succeed = succeed

    def start_transfer(self, transfer_id, source_path, dest_path, operation_type='folder',
                       media_type='', folder_name='', season_name=None,
                       is_simulation=False, simulation_bwlimit=None, extra_fields=None):
        self.calls.append({
            'transfer_id': transfer_id,
            'source_path': source_path,
            'dest_path': dest_path,
            'operation_type': operation_type,
            'media_type': media_type,
            'folder_name': folder_name,
            'season_name': season_name,
            'extra_fields': extra_fields or {},
        })
        return (True, 'running') if self.succeed else (False, 'failed')


class FakeConfig:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=''):
        return self.values.get(key, default)

    def get_destination_paths(self):
        return [v for k, v in self.values.items() if k.endswith('_DEST_PATH') and v]


def ep(series, folder, code, quality='WEBDL-1080p', group='HONE'):
    return f"{series}/{folder}/{series} - {code} - Title [{quality}][{group}-Dragon DB].mkv"


class ExploreServiceTests(unittest.TestCase):
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

        self.db = DatabaseManager(os.path.join(self.tmp.name, 'explore_test.db'))
        self.coordinator = FakeCoordinator(self.backup_root)

    # ---- helpers ----------------------------------------------------------

    def write_local(self, rel, size=10 * MB):
        path = os.path.join(self.local_root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as handle:
            handle.write(b'\0' * size)
        return path

    def service(self, remote_rows, directories=()):
        ssh = FakeSSH(remote_rows, directories)
        return ExploreService(self.config, self.db, self.coordinator, ssh)

    # ---- reads ------------------------------------------------------------

    def test_tree_reports_status_and_caches_the_result(self):
        remote = [(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'), 10 * MB, 100) for i in range(1, 6)]
        self.write_local(ep(self.SERIES, 'Season 01', 'S01E01'))
        self.write_local(ep(self.SERIES, 'Season 01', 'S01E02'))

        service = self.service(remote)
        tree = service.tree('tvshows', refresh=True)

        self.assertEqual(len(tree['series']), 1)
        entry = tree['series'][0]
        self.assertEqual(entry['name'], self.SERIES)
        self.assertEqual(entry['status'], 'PARTIAL_SYNC')
        self.assertEqual(entry['counts']['in_sync'], 2)
        self.assertEqual(entry['counts']['missing'], 3)

        # Second read comes from the snapshot without touching the remote.
        service.ssh_manager.commands.clear()
        cached = service.tree('tvshows')
        self.assertTrue(cached['stale'])
        self.assertEqual(cached['series'][0]['counts']['missing'], 3)
        self.assertEqual(service.ssh_manager.commands, [])

    def test_no_browse_session_is_a_409_not_an_empty_library(self):
        service = ExploreService(self.config, self.db, self.coordinator,
                                 FakeSSH([], connected=False))
        with self.assertRaises(ExploreError) as caught:
            service.tree('tvshows', refresh=True)
        self.assertEqual(caught.exception.status, 409)

    def test_unknown_library_is_a_404(self):
        service = self.service([])
        with self.assertRaises(ExploreError) as caught:
            service.tree('podcasts', refresh=True)
        self.assertEqual(caught.exception.status, 404)

    def test_season_view_lists_episodes_with_labels(self):
        remote = [(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'), 10 * MB, 100) for i in range(1, 4)]
        self.write_local(ep(self.SERIES, 'Season 01', 'S01E01'))
        season = self.service(remote).season('tvshows', self.SERIES, 'Season 01')

        labels = {e['code']: e['label'] for e in season['episodes']}
        self.assertEqual(labels['S01E01'], 'IN_SYNC')
        self.assertEqual(labels['S01E02'], 'MISSING')
        self.assertEqual(labels['S01E03'], 'MISSING')

    # ---- planning ---------------------------------------------------------

    def test_season_sync_plan_downloads_what_is_missing(self):
        remote = [(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'), 10 * MB, 100) for i in range(1, 6)]
        for i in range(1, 3):
            self.write_local(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'))

        plan = self.service(remote).plan(
            'tvshows', 'sync_season', self.SERIES, season_label='Season 01')

        self.assertEqual(plan['counts']['fetch'], 3)
        self.assertEqual(plan['counts']['remove'], 0)
        self.assertTrue(plan['safe'])
        self.assertIn('plan_id', plan)
        self.assertIn('downloads 3', plan['verdict'])

    def test_shrinking_remote_fails_its_checks(self):
        remote = [(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'), 10 * MB, 100) for i in range(1, 3)]
        for i in range(1, 11):
            self.write_local(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'))

        plan = self.service(remote).plan(
            'tvshows', 'sync_season', self.SERIES, season_label='Season 01')

        self.assertEqual(plan['counts']['remove'], 8)
        self.assertFalse(plan['safe'])
        self.assertTrue(plan['requires_override'])
        failed = {c['id'] for c in plan['checks'] if not c['passed']}
        self.assertIn('removals_vs_arrivals', failed)

    # ---- execution --------------------------------------------------------

    def test_execute_writes_the_file_list_and_starts_a_transfer(self):
        remote = [(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'), 10 * MB, 100) for i in range(1, 4)]
        self.write_local(ep(self.SERIES, 'Season 01', 'S01E01'))

        service = self.service(remote)
        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')
        result = service.execute(plan['plan_id'])

        self.assertEqual(len(self.coordinator.calls), 1)
        call = self.coordinator.calls[0]
        self.assertEqual(call['operation_type'], 'explore_sync')
        self.assertEqual(call['folder_name'], self.SERIES)
        self.assertTrue(call['dest_path'].endswith('Season 01'))

        files_from = call['extra_fields']['explore_files_from']
        self.assertTrue(os.path.isfile(files_from))
        with open(files_from) as handle:
            listed = handle.read().strip().split('\n')
        self.assertEqual(len(listed), 2)                      # E02 and E03
        self.assertTrue(all('/' not in name for name in listed))
        self.assertEqual(call['extra_fields']['explore_mode'], 'sync')
        self.assertIsNotNone(result['transfer_id'])

    def test_upgrade_moves_the_old_file_to_backup_before_transferring(self):
        # The anti-duplicate rule, end to end: same episode, different filename.
        old = ep(self.SERIES, 'Season 01', 'S01E01', 'WEBDL-1080p', 'OLD')
        new = ep(self.SERIES, 'Season 01', 'S01E01', 'Bluray-2160p', 'NEW')
        local_path = self.write_local(old, size=5 * MB)

        service = self.service([(new, 20 * MB, 200)])
        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')
        self.assertEqual(plan['counts']['supersede'], 1)

        service.execute(plan['plan_id'])

        # The old file is gone from the library and present in the backup.
        self.assertFalse(os.path.exists(local_path))
        moved = []
        for root, _dirs, files in os.walk(self.backup_root):
            moved.extend(files)
        self.assertIn(os.path.basename(old), moved)

        # And only the new file is queued to arrive.
        with open(self.coordinator.calls[0]['extra_fields']['explore_files_from']) as handle:
            listed = handle.read().split('\n')
        self.assertIn(os.path.basename(new), [line for line in listed if line])

    def test_download_never_removes_and_uses_ignore_existing_mode(self):
        remote = [(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'), 10 * MB, 100) for i in range(1, 4)]
        self.write_local(ep(self.SERIES, 'Season 01', 'S01E01'))

        service = self.service(remote)
        plan = service.plan('tvshows', 'download', self.SERIES,
                            season_label='Season 01', codes=['S01E02'])
        self.assertEqual(plan['counts']['fetch'], 1)
        self.assertEqual(plan['counts']['remove'], 0)
        self.assertEqual(plan['counts']['supersede'], 0)

        service.execute(plan['plan_id'])
        self.assertEqual(self.coordinator.calls[0]['extra_fields']['explore_mode'], 'download')

    def test_replace_leaves_the_rest_of_the_season_alone(self):
        old = ep(self.SERIES, 'Season 01', 'S01E23', 'WEBDL-1080p', 'OLD')
        new = ep(self.SERIES, 'Season 01', 'S01E23', 'Bluray-2160p', 'NEW')
        for i in range(1, 23):
            self.write_local(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'))
        self.write_local(old, size=5 * MB)

        service = self.service([(new, 20 * MB, 200)])
        plan = service.plan('tvshows', 'replace', self.SERIES,
                            season_label='Season 01', codes=['S01E23'])

        # A season sync here would list 22 removals; replace lists none.
        self.assertEqual(plan['counts']['remove'], 0)
        self.assertEqual(plan['counts']['supersede'], 1)
        self.assertTrue(plan['safe'])

        service.execute(plan['plan_id'])
        remaining = os.listdir(os.path.join(self.local_root, self.SERIES, 'Season 01'))
        self.assertEqual(len(remaining), 22)   # the 22 untouched episodes

    # ---- the plan gate ----------------------------------------------------

    def test_a_plan_can_only_be_executed_once(self):
        remote = [(ep(self.SERIES, 'Season 01', 'S01E01'), 10 * MB, 100)]
        service = self.service(remote)
        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')

        service.execute(plan['plan_id'])
        with self.assertRaises(ExploreError) as caught:
            service.execute(plan['plan_id'])
        self.assertEqual(caught.exception.status, 409)

    def test_an_unsafe_plan_needs_an_override_and_the_typed_name(self):
        remote = [(ep(self.SERIES, 'Season 01', 'S01E01'), 10 * MB, 100)]
        for i in range(1, 11):
            self.write_local(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'))

        service = self.service(remote)
        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')
        self.assertFalse(plan['safe'])

        with self.assertRaises(ExploreError) as caught:
            service.execute(plan['plan_id'])
        self.assertEqual(caught.exception.status, 422)

        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')
        with self.assertRaises(ExploreError):
            service.execute(plan['plan_id'], override=True, confirm_text='wrong')

        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')
        result = service.execute(plan['plan_id'], override=True, confirm_text='Season 01')
        self.assertIsNotNone(result)

    def test_a_failed_start_rolls_the_backup_moves_back(self):
        old = ep(self.SERIES, 'Season 01', 'S01E01', 'WEBDL-1080p', 'OLD')
        new = ep(self.SERIES, 'Season 01', 'S01E01', 'Bluray-2160p', 'NEW')
        local_path = self.write_local(old, size=5 * MB)

        self.coordinator.succeed = False
        service = self.service([(new, 20 * MB, 200)])
        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')

        with self.assertRaises(ExploreError):
            service.execute(plan['plan_id'])

        # Nothing was lost: the library is exactly as it was.
        self.assertTrue(os.path.exists(local_path))

    # ---- test mode --------------------------------------------------------

    def test_test_mode_does_not_move_local_files(self):
        """
        TEST_MODE puts rsync into --dry-run. The backup moves have to be
        skipped too, or a rehearsal deletes the local file and never fetches
        its replacement.
        """
        old = ep(self.SERIES, 'Season 01', 'S01E01', 'WEBDL-1080p', 'OLD')
        new = ep(self.SERIES, 'Season 01', 'S01E01', 'Bluray-2160p', 'NEW')
        local_path = self.write_local(old, size=5 * MB)

        service = self.service([(new, 20 * MB, 200)])
        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')
        self.assertEqual(plan['counts']['supersede'], 1)

        with unittest.mock.patch.dict(os.environ, {'TEST_MODE': '1'}):
            service.execute(plan['plan_id'])

        # The local file is exactly where it was.
        self.assertTrue(os.path.exists(local_path))
        self.assertEqual(os.path.getsize(local_path), 5 * MB)

    # ---- history ----------------------------------------------------------

    def test_history_records_what_a_run_did_file_by_file(self):
        remote = [(ep(self.SERIES, 'Season 01', f'S01E{i:02d}'), 10 * MB, 100) for i in range(1, 3)]
        service = self.service(remote)
        plan = service.plan('tvshows', 'sync_season', self.SERIES, season_label='Season 01')
        result = service.execute(plan['plan_id'])

        files = service.store.files_for(result['transfer_id'])
        self.assertEqual(len(files), 2)
        self.assertTrue(all(f['action'] == 'fetch' for f in files))




class PlanHousekeepingTests(unittest.TestCase):
    """Approved plans are single-use and short-lived; their rows should not
    accumulate for the life of the install."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = DatabaseManager(os.path.join(self.tmp.name, 'plans.db'))
        self.store = ExploreStore(self.db)

    def _insert(self, plan_id, expires_at):
        with self.db.get_connection() as conn:
            conn.execute(
                '''INSERT INTO explore_plan (plan_id, media_type, operation, series,
                       season_label, payload, safe, consumed, created_by, expires_at)
                   VALUES (?, 'tvshows', 'sync_season', 'Show', 'Season 01', '{}', 1, 0, NULL, ?)''',
                (plan_id, expires_at),
            )
            conn.commit()

    def _count(self):
        with self.db.get_connection() as conn:
            return conn.execute('SELECT COUNT(*) FROM explore_plan').fetchone()[0]

    def test_saving_a_plan_clears_out_the_expired_ones(self):
        self._insert('stale', (datetime.now() - timedelta(hours=2)).isoformat())
        self._insert('fresh', (datetime.now() + timedelta(minutes=10)).isoformat())
        self.assertEqual(self._count(), 2)

        self.store.save_plan(_FakePlan(), {'transfers': []}, created_by='admin')

        with self.db.get_connection() as conn:
            remaining = {row[0] for row in conn.execute('SELECT plan_id FROM explore_plan')}
        self.assertNotIn('stale', remaining)
        self.assertIn('fresh', remaining, 'a plan still inside its window must survive')
        self.assertEqual(len(remaining), 2, 'the fresh one plus the new one')

    def test_an_expired_plan_cannot_be_used_even_before_it_is_purged(self):
        self._insert('stale', (datetime.now() - timedelta(hours=2)).isoformat())
        self.assertIsNone(self.store.take_plan('stale'))
        self.assertIsNone(self.store.peek_plan('stale'))


class _FakePlan:
    media_type = 'tvshows'
    operation = 'sync_season'
    series = 'Show'
    season_label = 'Season 01'
    safe = True

    def to_dict(self):
        return {}

if __name__ == '__main__':
    unittest.main()
