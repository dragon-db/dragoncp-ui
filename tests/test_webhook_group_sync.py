#!/usr/bin/env python3
"""
"Sync all" on a webhook group must produce ONE transfer per season.

Sonarr sends one webhook per episode, so a six-episode grab arrives as six
notifications for the same season. A series transfer is scoped to the season
FOLDER, not to an episode, so one run brings the whole season down. Syncing
each notification separately produced six transfers against one destination —
the queue serialised them on the path conflict and five moved zero bytes.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.webhook_service import WebhookService


def notification(nid, season, status='pending', slug='falcon', media_type='tvshows'):
    return {
        'notification_id': nid,
        'series_title_slug': slug,
        'series_title': slug.title(),
        'season_number': season,
        'media_type': media_type,
        'status': status,
        'transfer_id': None,
    }


class GroupSyncTests(unittest.TestCase):
    def setUp(self):
        self.rows = {}
        model = MagicMock()
        model.get.side_effect = lambda nid: self.rows.get(nid)
        self.model = model

        self.service = WebhookService.__new__(WebhookService)
        self.service.series_webhook_model = model
        self.calls = []

        def trigger(primary, batched=None):
            self.calls.append((primary, tuple(batched or ())))
            self.rows[primary]['transfer_id'] = f"transfer_for_{primary}"
            return True, f"started {primary}"

        self.service.trigger_series_webhook_sync = trigger

    def load(self, notifications):
        for n in notifications:
            self.rows[n['notification_id']] = n
        return [n['notification_id'] for n in notifications]

    def test_one_season_produces_exactly_one_transfer(self):
        ids = self.load([notification(f"ep{i}", 1) for i in range(1, 7)])

        ok, message, transfers = self.service.sync_notification_group(ids)

        self.assertTrue(ok)
        self.assertEqual(len(self.calls), 1, "six episodes must not start six transfers")
        self.assertEqual(len(transfers), 1)
        # every episode rides on the one transfer
        primary, batched = self.calls[0]
        self.assertEqual(set(batched), set(ids))
        self.assertIn('6 episode(s)', message)

    def test_two_seasons_are_never_merged_into_one_folder_sync(self):
        ids = self.load(
            [notification(f"s1e{i}", 1) for i in range(1, 4)]
            + [notification(f"s2e{i}", 2) for i in range(1, 3)]
        )

        ok, _message, transfers = self.service.sync_notification_group(ids)

        self.assertTrue(ok)
        self.assertEqual(len(self.calls), 2, "each season is its own folder transfer")
        self.assertEqual(len(transfers), 2)
        for _primary, batched in self.calls:
            seasons = {self.rows[n]['season_number'] for n in batched}
            self.assertEqual(len(seasons), 1, "a transfer must not span seasons")

    def test_two_series_are_kept_apart(self):
        ids = self.load(
            [notification('a1', 1, slug='falcon'), notification('b1', 1, slug='loki')]
        )
        ok, _message, _t = self.service.sync_notification_group(ids)
        self.assertTrue(ok)
        self.assertEqual(len(self.calls), 2)

    def test_same_season_number_across_media_types_is_not_merged(self):
        ids = self.load([
            notification('tv1', 1, slug='show', media_type='tvshows'),
            notification('an1', 1, slug='show', media_type='anime'),
        ])
        self.service.sync_notification_group(ids)
        self.assertEqual(len(self.calls), 2)

    def test_already_completed_notifications_are_not_resynced(self):
        ids = self.load([notification(f"ep{i}", 1, status='completed') for i in range(1, 4)])
        ok, message, transfers = self.service.sync_notification_group(ids)
        self.assertFalse(ok)
        self.assertEqual(self.calls, [])
        self.assertEqual(transfers, [])
        self.assertIn('nothing to sync', message.lower())

    def test_a_completed_episode_still_rides_along_when_others_need_syncing(self):
        # The season folder is fetched whole, so a completed episode belongs on
        # the same transfer — it must not be left pointing at an older run.
        ids = self.load([
            notification('ep1', 1, status='completed'),
            notification('ep2', 1, status='pending'),
        ])
        ok, _message, _t = self.service.sync_notification_group(ids)
        self.assertTrue(ok)
        primary, batched = self.calls[0]
        self.assertEqual(primary, 'ep2', "the primary must be one that needs syncing")
        self.assertEqual(set(batched), {'ep1', 'ep2'})

    def test_unknown_ids_are_reported_not_fatal(self):
        ids = self.load([notification('ep1', 1)]) + ['does-not-exist']
        ok, message, _t = self.service.sync_notification_group(ids)
        self.assertTrue(ok)
        self.assertIn('no longer exist', message)

    def test_a_failing_group_is_reported_even_when_another_succeeds(self):
        # One good season, one that refuses to start. Reporting only the
        # success would tell the operator everything is running.
        ids = self.load(
            [notification('a1', 1, slug='falcon'), notification('b1', 2, slug='falcon')]
        )

        def trigger(primary, batched=None):
            self.calls.append((primary, tuple(batched or ())))
            if primary == 'b1':
                return False, 'remote path not found'
            self.rows[primary]['transfer_id'] = f"transfer_for_{primary}"
            return True, f"started {primary}"

        self.service.trigger_series_webhook_sync = trigger

        ok, message, transfers = self.service.sync_notification_group(ids)

        self.assertTrue(ok, 'one season did start')
        self.assertEqual(len(transfers), 1)
        self.assertIn('remote path not found', message)
        self.assertIn('S2', message, 'the failing season is named')

    def test_a_group_with_nothing_to_sync_is_named_alongside_the_successes(self):
        ids = self.load([
            notification('a1', 1, slug='falcon'),
            notification('done', 2, slug='falcon', status='completed'),
        ])
        ok, message, _t = self.service.sync_notification_group(ids)
        self.assertTrue(ok)
        self.assertEqual(len(self.calls), 1, 'the completed season starts nothing')
        self.assertIn('nothing to sync', message)

    def test_the_episode_count_only_covers_seasons_that_started(self):
        ids = self.load(
            [notification(f'ep{i}', 1) for i in range(1, 4)]
            + [notification('skip', 2, status='completed')]
        )
        ok, message, _t = self.service.sync_notification_group(ids)
        self.assertTrue(ok)
        self.assertIn('3 episode(s)', message, 'the completed one is not counted as started')

    def test_a_notification_already_in_flight_is_not_relinked(self):
        # Its transfer is still running; repointing it at the new run would
        # leave that transfer with nothing tracking its outcome.
        ids = self.load([
            notification('running', 1, status='syncing'),
            notification('queued', 1, status='QUEUED_PATH'),
            notification('todo', 1, status='pending'),
        ])
        ok, _message, _t = self.service.sync_notification_group(ids)

        self.assertTrue(ok)
        primary, batched = self.calls[0]
        self.assertEqual(primary, 'todo')
        self.assertEqual(set(batched), {'todo'},
                         'only the notification that needed syncing is relinked')

    def test_empty_input_is_rejected(self):
        ok, _message, transfers = self.service.sync_notification_group([])
        self.assertFalse(ok)
        self.assertEqual(transfers, [])


if __name__ == '__main__':
    unittest.main()
