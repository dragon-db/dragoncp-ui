#!/usr/bin/env python3
"""
The Backups HTTP layer, end to end.

Real service, real index, real files on a temp disk — only auth and the
transfer queue are stood in for. Mounted on a bare Flask app so the test never
touches the live database or starts the transfer pipeline.

This is the layer where the two selection rules matter, and they differ on
purpose: sending no `files` key means "everything", while sending an empty list
means "you ticked nothing" and is refused. The previous plan endpoint treated
`[]` as falsy and planned a restore of every file in the backup, which is the
opposite of what ticking nothing asks for.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import routes.backups as backup_routes
from models.backup_capture import BackupCapture
from models.database import DatabaseManager
from models.settings import AppSettings
from services.backups.service import BackupsService
from services.settings_service import SettingsService

SHOW = 'Example Show (2024)'


class Config:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=''):
        return self.values.get(key, default)

    def get_destination_paths(self):
        return [v for k, v in self.values.items() if k.endswith('_DEST_PATH') and v]


class Queue:
    def check_duplicate_destination(self, dest_path, transfer_id=None):
        return (False, None)

    def register_transfer(self, transfer_id, dest_path):
        return (True, 'running')

    def unregister_transfer(self, transfer_id, dest_path=None):
        pass


class Coordinator:
    def __init__(self):
        self.queue_manager = Queue()


class Transfers:
    def __init__(self):
        self.rows = {}

    def create(self, data):
        self.rows[data['transfer_id']] = dict(data)

    def get(self, transfer_id):
        return self.rows.get(transfer_id)

    def update(self, transfer_id, updates):
        self.rows.setdefault(transfer_id, {}).update(updates)
        return True

    def add_log(self, transfer_id, message):
        pass

    def get_active(self):
        return []


class BackupRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.backup_root = os.path.join(self.tmp.name, 'backup')
        self.tv_root = os.path.join(self.tmp.name, 'tvshows')
        os.makedirs(self.backup_root)
        self.season_dir = os.path.join(self.tv_root, SHOW, 'Season 01')
        os.makedirs(self.season_dir)

        self.config = Config({
            'BACKUP_PATH': self.backup_root,
            'TVSHOW_DEST_PATH': self.tv_root,
        })
        self.db = DatabaseManager(os.path.join(self.tmp.name, 'routes_test.db'))
        self.captures = BackupCapture(self.db)
        self.transfers = Transfers()
        self.service = BackupsService(
            self.config, self.db, self.captures, self.transfers,
            coordinator=Coordinator(),
            # The real resolver over a real table — a stand-in here previously
            # answered a method the resolver does not have and hid a crash.
            settings=SettingsService(self.config, AppSettings(self.db)),
        )

        backup_routes.init_backup_routes(_CoordinatorShim(self.service, self.captures))

        app = Flask(__name__)
        app.register_blueprint(backup_routes.backups_bp, url_prefix='/api')
        self.client = app.test_client()

        patcher_token = patch('auth.get_token_from_request', return_value='token')
        patcher_valid = patch('auth.validate_token', return_value={'sub': 'tester'})
        self.addCleanup(patcher_token.stop)
        self.addCleanup(patcher_valid.stop)
        self.token = patcher_token.start()
        patcher_valid.start()

    # ---- fixtures ----

    def displace(self, filename, transfer_id='transfer_1', size=1024):  # noqa: D401
        """Put a file where rsync would, then run the sort the same way the
        transfer pipeline does."""
        staging = self.service.staging_dir(transfer_id)
        os.makedirs(staging, exist_ok=True)
        with open(os.path.join(staging, filename), 'wb') as handle:
            handle.write(b'\0' * size)
        self.transfers.create({
            'transfer_id': transfer_id, 'media_type': 'tvshows',
            'dest_path': self.season_dir,
        })
        self.service.sort_after_transfer(transfer_id)
        return self.captures.recent()[0]

    def library_file(self, filename, size=2048):
        path = os.path.join(self.season_dir, filename)
        with open(path, 'wb') as handle:
            handle.write(b'X' * size)
        return path

    # ---- auth ----

    def test_every_endpoint_requires_a_session(self):
        self.token.return_value = None
        for path in ('/api/backups/overview', '/api/backups/titles',
                     '/api/backups/slots', '/api/backups/unsorted', '/api/backups'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.post('/api/backups/rebuild').status_code, 401)
        self.assertEqual(
            self.client.post('/api/backups/captures/x/restore', json={}).status_code, 401
        )

    # ---- browsing ----

    def test_overview_reports_configuration_and_totals(self):
        self.displace(f"{SHOW} - S01E01 - Old.mkv")
        body = self.client.get('/api/backups/overview').get_json()

        self.assertEqual(body['status'], 'success')
        self.assertTrue(body['configured'])
        self.assertEqual(body['totals']['capture_count'], 1)
        self.assertEqual(body['totals']['slot_count'], 1)
        self.assertIn('retention', body)

    def test_the_static_routes_are_not_swallowed_by_the_legacy_id_route(self):
        """`/backups/overview` must not be read as a backup called "overview"."""
        for path in ('/api/backups/overview', '/api/backups/titles', '/api/backups/slots'):
            self.assertEqual(self.client.get(path).get_json()['status'], 'success', path)

    def test_titles_and_slots_narrow_together(self):
        self.displace(f"{SHOW} - S01E01 - A.mkv", 'transfer_1')
        self.displace(f"{SHOW} - S01E02 - B.mkv", 'transfer_2')

        titles = self.client.get('/api/backups/titles?library=shows').get_json()['titles']
        self.assertEqual(len(titles), 1)
        self.assertEqual(titles[0]['title'], SHOW)

        slots = self.client.get(
            f"/api/backups/slots?library=shows&title={SHOW}"
        ).get_json()
        self.assertEqual(slots['total'], 2)
        self.assertTrue(all(s['display'].startswith(SHOW) for s in slots['slots']))

    def test_a_slot_returns_its_versions_and_what_is_current(self):
        capture = self.displace(f"{SHOW} - S01E01 - Old.mkv")
        self.library_file(f"{SHOW} - S01E01 - New.mkv")

        body = self.client.get(
            f"/api/backups/slot?slot_key={capture['slot_key']}"
        ).get_json()
        self.assertEqual(len(body['captures']), 1)
        self.assertEqual(body['current']['name'], f"{SHOW} - S01E01 - New.mkv")

    def test_an_unknown_slot_is_404(self):
        response = self.client.get('/api/backups/slot?slot_key=shows|nothing|S01E01')
        self.assertEqual(response.status_code, 404)

    def test_a_slot_key_is_required(self):
        self.assertEqual(self.client.get('/api/backups/slot').status_code, 400)

    # ---- planning ----

    def test_the_plan_names_what_it_would_replace(self):
        capture = self.displace(f"{SHOW} - S01E01 - Old.mkv")
        current = self.library_file(f"{SHOW} - S01E01 - New.mkv")

        plan = self.client.post(
            f"/api/backups/captures/{capture['capture_id']}/plan", json={}
        ).get_json()['plan']

        self.assertIsNone(plan['blocked'])
        self.assertEqual(len(plan['operations']), 1)
        self.assertEqual(plan['operations'][0]['replaces'], current)
        self.assertEqual(plan['replaces_count'], 1)

    def test_an_empty_selection_is_refused_rather_than_meaning_everything(self):
        capture = self.displace(f"{SHOW} - S01E01 - Old.mkv")
        for endpoint in ('plan', 'restore'):
            response = self.client.post(
                f"/api/backups/captures/{capture['capture_id']}/{endpoint}",
                json={'files': []},
            )
            self.assertEqual(response.status_code, 400, endpoint)

    def test_a_traversal_path_in_the_selection_is_rejected(self):
        capture = self.displace(f"{SHOW} - S01E01 - Old.mkv")
        response = self.client.post(
            f"/api/backups/captures/{capture['capture_id']}/plan",
            json={'files': ['../../etc/passwd']},
        )
        self.assertEqual(response.status_code, 400)

    def test_planning_an_unknown_backup_says_so(self):
        plan = self.client.post('/api/backups/captures/nope/plan', json={}).get_json()['plan']
        self.assertIsNotNone(plan['blocked'])

    # ---- restoring ----

    def test_restore_starts_and_reports_the_transfer(self):
        capture = self.displace(f"{SHOW} - S01E01 - Old.mkv")
        response = self.client.post(
            f"/api/backups/captures/{capture['capture_id']}/restore", json={}
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['status'], 'success')
        self.assertIn('transfer_id', body)
        self._settle()

        self.assertTrue(
            os.path.isfile(os.path.join(self.season_dir, f"{SHOW} - S01E01 - Old.mkv"))
        )

    def test_restoring_twice_at_once_is_refused(self):
        capture = self.displace(f"{SHOW} - S01E01 - Old.mkv")
        with self.service._lock:
            self.service._restores_running[capture['capture_id']] = 'busy'
        try:
            response = self.client.post(
                f"/api/backups/captures/{capture['capture_id']}/restore", json={}
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn('already being restored', response.get_json()['message'])
        finally:
            with self.service._lock:
                self.service._restores_running.clear()

    # ---- managing ----

    def test_pinning_round_trips(self):
        capture = self.displace(f"{SHOW} - S01E01 - A.mkv")
        path = f"/api/backups/captures/{capture['capture_id']}/pin"

        self.assertEqual(self.client.post(path, json={'pinned': True}).status_code, 200)
        self.assertEqual(self.captures.get(capture['capture_id'])['pinned'], 1)
        self.assertEqual(self.client.post(path, json={'pinned': False}).status_code, 200)
        self.assertEqual(self.captures.get(capture['capture_id'])['pinned'], 0)

    def test_pinning_something_that_is_gone_is_404(self):
        response = self.client.post('/api/backups/captures/nope/pin', json={'pinned': True})
        self.assertEqual(response.status_code, 404)

    def test_deleting_removes_the_files_and_the_entry(self):
        capture = self.displace(f"{SHOW} - S01E01 - A.mkv")
        response = self.client.post(
            f"/api/backups/captures/{capture['capture_id']}/delete", json={}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.captures.get(capture['capture_id']))

    # ---- reclaiming space ----

    def test_delete_preview_reads_only(self):
        capture = self.displace(f"{SHOW} - S01E01 - A.mkv", size=4096)
        body = self.client.post(
            '/api/backups/delete/preview', json={'capture_ids': [capture['capture_id']]}
        ).get_json()

        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['total_size'], 4096)
        self.assertIsNotNone(self.captures.get(capture['capture_id']))

    def test_bulk_delete_frees_the_space(self):
        first = self.displace(f"{SHOW} - S01E01 - A.mkv", 'transfer_1', size=1000)
        second = self.displace(f"{SHOW} - S01E02 - B.mkv", 'transfer_2', size=2000)

        body = self.client.post('/api/backups/delete', json={
            'capture_ids': [first['capture_id'], second['capture_id']],
        }).get_json()
        self.assertEqual(body['deleted_count'], 2)
        self.assertEqual(body['reclaimed'], 3000)
        self.assertEqual(self.captures.totals()['capture_count'], 0)

    def test_deleting_a_whole_item_by_slot(self):
        self.displace(f"{SHOW} - S01E01 - v1.mkv", 'transfer_1')
        self.displace(f"{SHOW} - S01E01 - v2.mkv", 'transfer_2')
        slot_key = self.captures.recent()[0]['slot_key']

        body = self.client.post('/api/backups/delete', json={'slot_keys': [slot_key]}).get_json()
        self.assertEqual(body['deleted_count'], 2)

    def test_keep_newest_is_honoured_over_http(self):
        for index in range(3):
            self.displace(f"{SHOW} - S01E01 - v{index}.mkv", f"transfer_{index}")
        slot_key = self.captures.recent()[0]['slot_key']

        body = self.client.post('/api/backups/delete', json={
            'slot_keys': [slot_key], 'keep_newest': 1,
        }).get_json()
        self.assertEqual(body['deleted_count'], 2)
        self.assertEqual(len(self.captures.captures_for_slot(slot_key)), 1)

    def test_a_pinned_version_is_reported_not_silently_kept(self):
        capture = self.displace(f"{SHOW} - S01E01 - A.mkv")
        self.client.post(f"/api/backups/captures/{capture['capture_id']}/pin",
                         json={'pinned': True})

        body = self.client.post('/api/backups/delete', json={
            'capture_ids': [capture['capture_id']],
        }).get_json()
        self.assertEqual(body['deleted_count'], 0)
        self.assertEqual(body['skipped_pinned'], 1)
        self.assertIn('pinned', body['message'])

    def test_deleting_nothing_is_refused(self):
        self.assertEqual(self.client.post('/api/backups/delete', json={}).status_code, 400)
        self.assertEqual(
            self.client.post('/api/backups/delete', json={'capture_ids': []}).status_code, 400
        )

    def test_clearing_the_unidentified_bucket_must_be_confirmed(self):
        self.assertEqual(
            self.client.post('/api/backups/unsorted/delete', json={}).status_code, 400
        )

    def test_sorting_by_size_puts_the_biggest_first(self):
        self.displace(f"{SHOW} - S01E01 - small.mkv", 'transfer_1', size=100)
        self.displace(f"{SHOW} - S01E02 - big.mkv", 'transfer_2', size=9000)

        by_size = self.client.get('/api/backups/slots?sort=size').get_json()
        self.assertEqual(by_size['sort'], 'size')
        self.assertEqual(by_size['slots'][0]['total_size'], 9000)

    # ---- settings ----

    def test_retention_saves_to_the_database(self):
        body = self.client.post('/api/backups/retention',
                                json={'keep': 4, 'grace_hours': 6}).get_json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['retention']['keep'], 4)

        # And it is visible immediately, without a restart.
        again = self.client.get('/api/backups/retention').get_json()
        self.assertEqual(again['retention']['keep'], 4)

    def test_a_bad_retention_value_is_rejected(self):
        self.assertEqual(
            self.client.post('/api/backups/retention', json={'keep': 'lots'}).status_code, 400
        )

    # ---- housekeeping ----

    def test_rebuild_reports_what_it_indexed(self):
        self.displace(f"{SHOW} - S01E01 - A.mkv")
        self.captures.clear()

        body = self.client.post('/api/backups/rebuild').get_json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['indexed'], 1)
        self.assertEqual(self.captures.totals()['capture_count'], 1)

    def test_retention_preview_does_not_delete(self):
        self.displace(f"{SHOW} - S01E01 - A.mkv")
        body = self.client.post(
            '/api/backups/retention/preview', json={'keep': 1, 'grace_hours': 0}
        ).get_json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(self.captures.totals()['capture_count'], 1)

    def test_migration_must_be_confirmed(self):
        response = self.client.post('/api/backups/migration/apply', json={})
        self.assertEqual(response.status_code, 400)

    def test_migration_preview_moves_nothing(self):
        legacy = os.path.join(self.backup_root, 'Example_Show_2024_transfer_9')
        os.makedirs(legacy)
        with open(os.path.join(legacy, f"{SHOW} - S01E01 - A.mkv"), 'wb') as handle:
            handle.write(b'\0' * 10)

        body = self.client.post('/api/backups/migration/plan').get_json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['folders_seen'], 1)
        self.assertTrue(os.path.exists(legacy), 'a preview must not move anything')

    # ---- the legacy surface ----

    def test_the_old_endpoints_still_list_and_restore(self):
        """The legacy static UI is still what production serves."""
        capture = self.displace(f"{SHOW} - S01E01 - Old.mkv")

        listing = self.client.get('/api/backups').get_json()
        self.assertEqual(listing['status'], 'success')
        self.assertEqual(listing['backups'][0]['backup_id'], capture['capture_id'])
        self.assertEqual(listing['backups'][0]['folder_name'], SHOW)
        self.assertEqual(listing['backups'][0]['status'], 'ready')

        files = self.client.get(f"/api/backups/{capture['capture_id']}/files").get_json()
        self.assertEqual(len(files['files']), 1)

        plan = self.client.post(
            f"/api/backups/{capture['capture_id']}/plan", json={'files': []}
        ).get_json()['plan']
        self.assertEqual(len(plan['operations']), 1,
                         'the old page sends [] to mean everything')

    def test_the_old_reindex_name_still_works(self):
        self.displace(f"{SHOW} - S01E01 - A.mkv")
        body = self.client.post('/api/backups/reindex').get_json()
        self.assertEqual(body['status'], 'success')
        self.assertIn('imported', body)

    def _settle(self, timeout=5.0):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.service._lock:
                if not self.service._restores_running:
                    return
            time.sleep(0.02)
        self.fail('restore did not finish in time')


class _CoordinatorShim:
    """What routes/backups.py reaches for on the coordinator."""

    def __init__(self, service, capture_model):
        self.backups = service
        self.capture_model = capture_model


if __name__ == '__main__':
    unittest.main()
