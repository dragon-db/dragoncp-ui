#!/usr/bin/env python3
"""
"Sync all" on a webhook group must produce ONE transfer per season.

Sonarr sends one webhook per episode, so a six-episode grab arrives as six
notifications for the same season. A series transfer is scoped to the season
FOLDER, not to an episode, so one run brings the whole season down. Syncing
each notification separately produced six transfers against one destination —
the queue serialised them on the path conflict and five moved zero bytes.

The grouping now lives in the sync engine (`SyncEngine.sync_notifications`),
which groups by the folder each webhook would be copied into — re-derived on
the server, never taken from the caller.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.sync_engine import stages as S
from tests.test_sync_engine import EngineTestCase


class GroupSyncTests(EngineTestCase):
    def runs(self):
        return self.store.list(limit=100)

    def test_one_season_produces_exactly_one_transfer(self):
        ids = [self.series_webhook(f"ep{i}", i) for i in range(1, 7)]
        result = self.engine.sync_notifications(ids)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['run_ids']), 1, 'six episodes must not start six runs')
        self.assertEqual(len(self.coordinator.started), 1, 'one transfer')
        self.assertEqual(len(self.store.webhook_ids(result['run_ids'][0])), 6,
                         'every episode rides on the one run')

    def test_two_seasons_are_never_merged_into_one_folder_sync(self):
        ids = ([self.series_webhook(f"s1e{i}", i, season=1) for i in range(1, 4)]
               + [self.series_webhook(f"s2e{i}", i, season=2) for i in range(1, 3)])
        result = self.engine.sync_notifications(ids)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['run_ids']), 2, 'each season is its own folder transfer')
        for run_id in result['run_ids']:
            seasons = {self.webhook(n)['season_number']
                       for n in self.store.webhook_ids(run_id)}
            self.assertEqual(len(seasons), 1, 'a transfer must not span seasons')

    def test_two_series_are_kept_apart(self):
        a = self.series_webhook('a1', 1, title='Example Show', folder='Example Show (2020)')
        b = self.series_webhook('b1', 1, title='Another Show', folder='Another Show (2021)')
        result = self.engine.sync_notifications([a, b])
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['run_ids']), 2)

    def test_same_season_number_across_media_types_is_not_merged(self):
        self.config.values['ANIME_PATH'] = '/remote/tv'
        tv = self.series_webhook('tv1', 1, media_type='tvshows')
        anime = self.series_webhook('an1', 1, media_type='anime')
        result = self.engine.sync_notifications([tv, anime])
        self.assertEqual(len(result['run_ids']), 2, 'different libraries, different folders')

    def test_already_completed_notifications_are_not_resynced(self):
        ids = [self.series_webhook(f"ep{i}", i) for i in range(1, 4)]
        for nid in ids:
            self.coordinator.series_webhook_model.update(nid, {'status': 'completed'})
        result = self.engine.sync_notifications(ids)
        self.assertFalse(result['ok'])
        self.assertEqual(self.coordinator.started, [])
        self.assertIn('already synced', result['message'])

    def test_a_completed_episode_is_left_alone_while_the_rest_sync(self):
        done = self.series_webhook('ep1', 1)
        self.coordinator.series_webhook_model.update(done, {'status': 'completed'})
        todo = self.series_webhook('ep2', 2)
        result = self.engine.sync_notifications([done, todo])
        self.assertTrue(result['ok'])
        self.assertEqual(self.store.webhook_ids(result['run_ids'][0]), ['ep2'])
        self.assertEqual(self.webhook('ep1')['status'], 'completed')

    def test_unknown_ids_are_reported_not_fatal(self):
        nid = self.series_webhook('ep1', 1)
        result = self.engine.sync_notifications([nid, 'does-not-exist'])
        self.assertTrue(result['ok'])
        self.assertIn('no longer exist', result['message'])

    def test_a_failing_group_is_reported_even_when_another_succeeds(self):
        good = self.series_webhook('a1', 1)
        model = self.coordinator.series_webhook_model
        model.create({'notification_id': 'bad', 'media_type': 'tvshows',
                      'series_title': 'Example Show', 'series_path': '',
                      'season_path': '', 'status': 'pending'}, '{}')
        result = self.engine.sync_notifications([good, 'bad'])
        self.assertTrue(result['ok'], 'one season did start')
        self.assertIn('neither a season folder nor a series folder', result['message'])

    def test_a_notification_already_in_flight_is_not_relinked(self):
        """Its transfer is running; moving it would leave that copy unable to close it."""
        first = self.sonarr(self.series_webhook('running', 1))
        self.clock.advance(10)
        self.tick()
        self.assertEqual(self.get_run(first.run_id)['state'], S.TRANSFERRING)
        todo = self.series_webhook('todo', 2)
        result = self.engine.sync_notifications(['running', todo])
        self.assertTrue(result['ok'])
        self.assertEqual(self.webhook('running')['sync_run_id'], first.run_id)
        self.assertIn('being copied right now', result['message'])

    def test_empty_input_is_rejected(self):
        result = self.engine.sync_notifications([])
        self.assertFalse(result['ok'])
        self.assertEqual(result['run_ids'], [])


if __name__ == '__main__':
    unittest.main()
