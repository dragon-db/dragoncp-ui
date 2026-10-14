#!/usr/bin/env python3
"""
A transfer the queue lets through that then cannot start.

The queue starts a waiting transfer by itself once a slot or its folder frees
up. If that start fails — nowhere to put the files it would displace, or rsync
not starting — the transfer is marked failed, and its sync has to end failed
too, with the alert that offers Retry. A resume that cannot start rsync puts
the transfer back to paused, and its sync with it.

Before 2026-10-13 (branch only) the sync stayed "Queued" or "Copying" for good,
nothing said it had failed, and Retry could not get past it.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.sync_engine import stages as S
from services.sync_engine.engine import SyncRequest
from services.transfer_service import TransferService
from tests.test_test_mode_sync_paths import REMOTE_TV, RealCoordinatorTestCase


def rsync_will_not_start(service, transfer_id, *args):
    """What start_rsync_process does when rsync dies at once."""
    service.transfer_model.update(transfer_id, {
        'status': 'failed', 'progress': 'rsync process failed to start, return code: 255'})
    return False


class QueuedStartFailureTests(RealCoordinatorTestCase):

    def season_sync(self):
        return self.engine.submit(SyncRequest(
            kind=S.MANUAL, source='manual', media_type='tvshows',
            source_path=f"{REMOTE_TV}/Example Show (2020)/Season 01",
            dest_path=self.tv_dest('Example Show (2020)', 'Season 01'),
            folder_name='Example Show (2020)', season_name='Season 01', title='Example Show'))

    def waiting_sync(self):
        """A season sync waiting in the queue for a free slot."""
        self.coordinator.queue_manager.MAX_CONCURRENT_TRANSFERS = 0
        result = self.season_sync()
        run = self.engine.store.get(result.run_id)
        self.assertEqual(run['state'], S.QUEUED)
        self.coordinator.queue_manager.MAX_CONCURRENT_TRANSFERS = 50
        return run['run_id'], run['transfer_id']

    def assert_failed_with_alert(self, run_id, transfer_id):
        self.assertEqual(self.coordinator.transfer_model.get(transfer_id)['status'], 'failed')
        self.assertEqual(self.engine.store.get(run_id)['state'], S.FAILED_STATE)
        alerts = [a for a in self.coordinator.alerts.store.list(states=['open'])
                  if a['kind'] == 'transfer_failed' and a['run_id'] == run_id]
        self.assertEqual(len(alerts), 1, 'one Failed alert, offering Retry')
        self.assertIn('retry', alerts[0]['actions'])

    def test_no_backup_folder_fails_the_sync(self):
        run_id, transfer_id = self.waiting_sync()
        with patch.object(self.coordinator, '_staging_dir', return_value=None):
            self.assertFalse(self.coordinator.start_queued_transfer(transfer_id))
        self.assert_failed_with_alert(run_id, transfer_id)
        queue = self.engine.store.stages(run_id)[S.QUEUE]
        self.assertEqual(queue['status'], S.FAILED, 'it never left the queue')
        self.assertIn('BACKUP_PATH', queue['summary'])

    def test_rsync_not_starting_fails_the_sync(self):
        run_id, transfer_id = self.waiting_sync()
        with patch.object(TransferService, 'start_rsync_process', rsync_will_not_start):
            self.assertFalse(self.coordinator.start_queued_transfer(transfer_id))
        self.assert_failed_with_alert(run_id, transfer_id)
        self.assertEqual(self.engine.store.stages(run_id)[S.TRANSFER]['status'], S.FAILED)

    def test_the_sync_is_told_before_its_folder_is_freed(self):
        """Freeing the folder can start the next transfer; this sync has ended by then."""
        run_id, transfer_id = self.waiting_sync()
        seen = []
        free = self.coordinator.queue_manager.unregister_transfer

        def unregister(*args, **kwargs):
            seen.append(self.run_state(run_id))
            return free(*args, **kwargs)

        with patch.object(self.coordinator.queue_manager, 'unregister_transfer', unregister), \
                patch.object(self.coordinator, '_staging_dir', return_value=None):
            self.coordinator.start_queued_transfer(transfer_id)
        self.assertEqual(seen[:1], [S.FAILED_STATE])

    def test_retry_after_a_failed_start_queues_it_again(self):
        run_id, transfer_id = self.waiting_sync()
        with patch.object(self.coordinator, '_staging_dir', return_value=None):
            self.coordinator.start_queued_transfer(transfer_id)
        retry = self.engine.restart_transfer(transfer_id)
        self.assertTrue(retry.ok, retry.message)
        self.assertEqual(retry.action, 'opened')
        self.assertNotEqual(retry.run_id, run_id)
        self.assertEqual(self.run_state(retry.run_id), S.TRANSFERRING)

    def test_a_transfer_queued_before_the_engine_closes_its_episode(self):
        """Queued by the old code, promoted after an upgrade: it has no sync."""
        dest = self.tv_dest('Example Show (2020)', 'Season 02')
        self.coordinator.transfer_model.create({
            'transfer_id': 'legacy_transfer', 'media_type': 'tvshows',
            'folder_name': 'Example Show (2020)', 'season_name': 'Season 02',
            'source_path': f"{REMOTE_TV}/Example Show (2020)/Season 02", 'dest_path': dest,
            'operation_type': 'folder', 'status': 'queued', 'queue_reason': 'slot'})
        webhooks = self.coordinator.series_webhook_model
        webhooks.create({
            'notification_id': 'e1', 'media_type': 'tvshows', 'series_title': 'Example Show',
            'series_title_slug': 'example-show', 'series_id': 7,
            'series_path': f"{REMOTE_TV}/Example Show (2020)", 'tvdb_id': 900001,
            'season_number': 2, 'episodes': [{'seasonNumber': 2, 'episodeNumber': 1}],
            'episode_files': [], 'season_path': f"{REMOTE_TV}/Example Show (2020)/Season 02",
            'status': 'QUEUED_SLOT'}, '{}')
        webhooks.update('e1', {'transfer_id': 'legacy_transfer'})
        with patch.object(self.coordinator, '_staging_dir', return_value=None):
            self.assertFalse(self.coordinator.start_queued_transfer('legacy_transfer'))
        self.assertEqual(webhooks.get('e1')['status'], 'failed', 'no longer reads syncing')

    def test_a_resume_that_cannot_start_rsync_leaves_the_sync_paused(self):
        result = self.season_sync()
        transfer_id = self.engine.store.get(result.run_id)['transfer_id']
        self.assertEqual(self.run_state(result.run_id), S.TRANSFERRING)
        ok, message = self.coordinator.pause_transfer(transfer_id)
        self.assertTrue(ok, message)
        self.assertEqual(self.run_state(result.run_id), S.PAUSED)
        with patch.object(TransferService, 'start_rsync_process', rsync_will_not_start):
            ok, _ = self.coordinator.resume_transfer(transfer_id)
        self.assertFalse(ok)
        self.assertEqual(self.coordinator.transfer_model.get(transfer_id)['status'], 'paused')
        self.assertEqual(self.run_state(result.run_id), S.PAUSED,
                         'paused, as its transfer is, and resumable again')


if __name__ == '__main__':
    unittest.main()
