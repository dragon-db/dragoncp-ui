#!/usr/bin/env python3
"""
The sync engine: one pipeline every sync goes through.

These tests drive the engine with a real database and fakes for the pieces
that would touch the network or start rsync: Sonarr's answers, the dry run,
the queue, and the clock. Each test names the behaviour it pins, in the words
the plan used (planning/sync-system, decided 2026-10-02).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.alert import AlertStore
from models.database import DatabaseManager
from models.sync_run import SyncRunStore
from models.transfer import Transfer
from models.webhook import SeriesWebhookNotification, WebhookNotification
from services.alert_service import AlertService
from services.connectors.adapters._arr import InFlight
from services.connectors.base import CheckResult
from services.path_service import PathService
from services.sync_engine import stages as S
from services.sync_engine.engine import (
    READY_CAP_SECONDS,
    RECHECK_MAX_SECONDS,
    RECHECK_MIN_SECONDS,
    SETTLE_SECONDS,
    SyncEngine,
    SyncRequest,
)

REMOTE_TV = '/remote/tv'
REMOTE_MOVIES = '/remote/movies'


class Clock:
    def __init__(self, start=1_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeConfig:
    def __init__(self, root):
        self.values = {
            'TVSHOW_PATH': REMOTE_TV, 'MOVIE_PATH': REMOTE_MOVIES, 'ANIME_PATH': '/remote/anime',
            'TVSHOW_DEST_PATH': os.path.join(root, 'tv'),
            'MOVIE_DEST_PATH': os.path.join(root, 'movies'),
            'ANIME_DEST_PATH': os.path.join(root, 'anime'),
        }
        for key in ('TVSHOW_DEST_PATH', 'MOVIE_DEST_PATH', 'ANIME_DEST_PATH'):
            os.makedirs(self.values[key], exist_ok=True)

    def get(self, key, default=''):
        return self.values.get(key, default)

    def get_destination_paths(self):
        return [self.values[k] for k in ('MOVIE_DEST_PATH', 'TVSHOW_DEST_PATH',
                                         'ANIME_DEST_PATH')]


class FakeTransferService:
    def __init__(self):
        self.result = {
            'safe_to_sync': True, 'reason': 'All safety checks passed',
            'incoming_count': 2, 'deleted_count': 0, 'server_file_count': 2,
            'local_file_count': 0, 'incoming_files': ['a.mkv', 'b.mkv'], 'deleted_files': [],
        }
        self.calls = []

    def perform_dry_run_rsync(self, source_path, dest_path):
        self.calls.append((source_path, dest_path))
        return dict(self.result)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send_discord_notification(self, transfer_id, status, sync_label=None):
        self.sent.append((transfer_id, status, sync_label))

    def parse_transfer_logs(self, logs):
        return {}


class FakeCoordinator:
    """Creates transfer rows the way the real coordinator does, without rsync."""

    def __init__(self, db, config):
        self.transfer_model = Transfer(db)
        self.webhook_model = WebhookNotification(db)
        self.series_webhook_model = SeriesWebhookNotification(db)
        self.path_service = PathService(config)
        self.config = config
        self.transfer_service = FakeTransferService()
        self.notification_service = FakeNotifier()
        self.queue_state = 'running'
        self.engine = None
        self.started = []
        self.requeued = []

    def start_transfer(self, transfer_id, source_path, dest_path, operation_type='folder',
                       media_type='', folder_name='', season_name=None, is_simulation=False,
                       simulation_bwlimit=None, extra_fields=None):
        state = self.queue_state
        data = {
            'transfer_id': transfer_id, 'media_type': media_type, 'folder_name': folder_name,
            'season_name': season_name, 'source_path': source_path, 'dest_path': dest_path,
            'operation_type': operation_type,
            'status': 'queued' if state.startswith('QUEUED') else 'pending',
            'progress': ('Queued: Waiting for "Example Show - Season 01" to complete '
                         '(same destination path)') if state == 'QUEUED_PATH' else '',
            'is_simulation': is_simulation,
        }
        data.update(extra_fields or {})
        self.transfer_model.create(data)
        self.started.append(transfer_id)
        if state == 'running':
            self.launch(transfer_id)
        return True, state

    def launch(self, transfer_id):
        self.engine.before_transfer_start(transfer_id)
        self.transfer_model.update(transfer_id, {'status': 'running', 'transport': 'ssh',
                                                 'rsync_process_id': 4242})
        self.engine.on_transfer_started(transfer_id)

    def requeue_transfer(self, transfer_id, sync_run_id=None):
        self.requeued.append(transfer_id)
        self.transfer_model.update(transfer_id, {'status': 'queued',
                                                 'sync_run_id': sync_run_id})
        return True, 'QUEUED_SLOT'

    def cancel_transfer(self, transfer_id):
        self.transfer_model.update(transfer_id, {'status': 'cancelled'})
        return True

    def finish(self, transfer_id, status, progress=''):
        self.transfer_model.update(transfer_id, {'status': status, 'progress': progress})
        self.engine.on_transfer_finished(transfer_id, status)


class FakeAdapter:
    def __init__(self, ok=True, message='Connected to Sonarr 4'):
        self.ok = ok
        self.message = message
        self.checks = 0

    def check(self):
        self.checks += 1
        return CheckResult(self.ok, self.message)


class FakeIndex:
    def __init__(self):
        self.adapter = FakeAdapter()
        self.answers = []
        self.asked = 0

    def _adapter(self, source):
        return self.adapter

    def in_flight_for_season(self, tvdb_id, season_number):
        self.asked += 1
        if self.answers:
            return self.answers.pop(0)
        return InFlight(known=True, reason='nothing in flight')


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = DatabaseManager(os.path.join(self.tmp.name, 'engine.db'))
        self.config = FakeConfig(self.tmp.name)
        self.clock = Clock()
        self.coordinator = FakeCoordinator(self.db, self.config)
        self.index = FakeIndex()
        self.alerts = AlertService(AlertStore(self.db))
        self.store = SyncRunStore(self.db)
        self.engine = SyncEngine(self.store, coordinator=self.coordinator,
                                 media_index=self.index, alerts=self.alerts,
                                 config=self.config, clock=self.clock)
        self.engine.inline = True
        self.alerts.engine = self.engine
        self.coordinator.engine = self.engine

    # -- helpers -------------------------------------------------------------

    def series_webhook(self, nid, episode, season=1, title='Example Show',
                       folder='Example Show (2020)', tvdb=900001, media_type='tvshows',
                       auto_sync_scheduled_at=None, created_at=None):
        model = self.coordinator.series_webhook_model
        model.create({
            'notification_id': nid, 'media_type': media_type, 'series_title': title,
            'series_title_slug': 'example-show', 'series_id': 7,
            'series_path': f"{REMOTE_TV}/{folder}", 'tvdb_id': tvdb,
            'season_number': season,
            'episodes': [{'seasonNumber': season, 'episodeNumber': episode}],
            'episode_files': [],
            'season_path': f"{REMOTE_TV}/{folder}/Season {season:02d}",
            'status': 'pending',
        }, '{}')
        updates = {}
        if auto_sync_scheduled_at:
            updates['auto_sync_scheduled_at'] = auto_sync_scheduled_at
        if created_at:
            updates['created_at'] = created_at
        if updates:
            model.update(nid, updates)
        return nid

    def movie_webhook(self, nid, title='Example Film', year=2024):
        self.coordinator.webhook_model.create({
            'notification_id': nid, 'title': title, 'year': year,
            'folder_path': f"{REMOTE_MOVIES}/{title} ({year})",
            'file_path': f"{REMOTE_MOVIES}/{title} ({year})/{title}.mkv",
            'tmdb_id': 900002, 'status': 'pending',
        }, '{}')
        return nid

    def sonarr(self, *nids, hold=False):
        return self.engine.submit(SyncRequest(
            kind=S.SONARR_WEBHOOK, source='sonarr', media_type='tvshows',
            webhooks=[('sonarr_webhook', n) for n in nids], hold=hold))

    def tick(self):
        """What the engine's loop does each second: work on every run that is due."""
        for run_id in self.store.due(self.clock()):
            self.engine._run_advance(run_id)

    def get_run(self, run_id):
        return self.store.get(run_id)

    def stage(self, run_id, stage):
        return self.store.stages(run_id)[stage]

    def webhook(self, nid):
        return self.coordinator.series_webhook_model.get(nid)

    def open_alerts(self, kind=None):
        return [a for a in self.alerts.store.list(states=['open'])
                if kind is None or a['kind'] == kind]


class BatchTests(EngineTestCase):
    """One batch per Series + Season; N webhooks → 1 transfer."""

    def test_a_burst_of_webhooks_becomes_one_batch(self):
        first = self.sonarr(self.series_webhook('e1', 1))
        self.assertEqual(first.action, 'opened')
        for n in (2, 3, 4):
            joined = self.sonarr(self.series_webhook(f"e{n}", n))
            self.assertEqual(joined.action, 'joined')
            self.assertEqual(joined.run_id, first.run_id)

        self.assertEqual(self.store.count(), 1)
        self.assertEqual(len(self.store.webhook_ids(first.run_id)), 4)

    def test_joining_asks_sonarr_nothing_extra(self):
        """One question at a time: joins never trigger a question of their own."""
        run = self.sonarr(self.series_webhook('e1', 1))
        for n in (2, 3):
            self.sonarr(self.series_webhook(f"e{n}", n))
        self.assertEqual(self.index.asked, 0, 'nothing is asked before the settle')
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertEqual(self.index.asked, 1)
        self.assertEqual(self.get_run(run.run_id)['state'], S.TRANSFERRING)

    def test_different_seasons_are_different_batches(self):
        a = self.sonarr(self.series_webhook('s1', 1, season=1))
        b = self.sonarr(self.series_webhook('s2', 1, season=2))
        self.assertNotEqual(a.run_id, b.run_id)

    def test_a_webhook_during_the_copy_opens_one_follow_up(self):
        first = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertEqual(self.get_run(first.run_id)['state'], S.TRANSFERRING)

        upgrade = self.sonarr(self.series_webhook('e3-upgrade', 3))
        self.assertEqual(upgrade.action, 'follow_up')
        follow = self.get_run(upgrade.run_id)
        self.assertEqual(follow['parent_run_id'], first.run_id)
        self.assertEqual(follow['parent_relation'], 'follow_up')

        another = self.sonarr(self.series_webhook('e4-upgrade', 4))
        self.assertEqual(another.run_id, upgrade.run_id, 'never a third transfer')
        self.assertEqual(another.action, 'joined')

    def test_a_follow_up_waits_behind_the_running_copy(self):
        first = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.coordinator.queue_state = 'QUEUED_PATH'
        follow = self.sonarr(self.series_webhook('e2', 2))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertEqual(self.get_run(follow.run_id)['state'], S.QUEUED)
        queue = self.stage(follow.run_id, S.QUEUE)
        self.assertEqual(queue['status'], S.WAITING)
        self.assertIn('same folder', queue['summary'])
        self.assertEqual(self.webhook('e2')['status'], 'QUEUED_PATH')
        self.assertNotEqual(first.run_id, follow.run_id)


class ReadyCheckTests(EngineTestCase):
    """Ask Sonarr, wait by its time left, never more than 30 minutes."""

    def opened(self):
        run = self.sonarr(self.series_webhook('e1', 1))
        return run.run_id

    def test_first_question_waits_for_the_settle(self):
        run_id = self.opened()
        run = self.get_run(run_id)
        self.assertEqual(run['ready_mode'], 'ask')
        self.assertAlmostEqual(run['next_check_at'], self.clock() + SETTLE_SECONDS, delta=0.01)
        self.assertEqual(self.stage(run_id, S.READY)['status'], S.WAITING)

    def test_waits_for_the_time_sonarr_says_is_left(self):
        run_id = self.opened()
        self.index.answers = [InFlight(known=True, blocking=2, eta_seconds=180,
                                       detail=('S01E05: Still downloading',))]
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        run = self.get_run(run_id)
        self.assertEqual(run['state'], S.WAITING_STATE)
        self.assertAlmostEqual(run['next_check_at'], self.clock() + 180, delta=0.01)
        self.assertIn('2 still downloading', self.stage(run_id, S.READY)['summary'])

        self.clock.advance(180)
        self.tick()
        self.assertEqual(self.get_run(run_id)['state'], S.TRANSFERRING)
        self.assertEqual(self.index.asked, 2)

    def test_the_wait_is_kept_between_ten_seconds_and_five_minutes(self):
        run_id = self.opened()
        self.index.answers = [InFlight(known=True, blocking=1, eta_seconds=2)]
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertAlmostEqual(self.get_run(run_id)['next_check_at'],
                               self.clock() + RECHECK_MIN_SECONDS, delta=0.01)

        self.index.answers = [InFlight(known=True, blocking=1, eta_seconds=4000)]
        self.clock.advance(RECHECK_MIN_SECONDS)
        self.tick()
        self.assertAlmostEqual(self.get_run(run_id)['next_check_at'],
                               self.clock() + RECHECK_MAX_SECONDS, delta=0.01)

    def test_a_kick_never_asks_before_the_next_check(self):
        run_id = self.opened()
        self.clock.advance(SETTLE_SECONDS)
        self.index.answers = [InFlight(known=True, blocking=1, eta_seconds=120)]
        self.tick()
        asked = self.index.asked
        self.engine._run_advance(run_id)
        self.engine._run_advance(run_id)
        self.assertEqual(self.index.asked, asked)

    def test_stuck_downloads_do_not_hold_the_season(self):
        run_id = self.opened()
        self.index.answers = [InFlight(known=True, blocking=0, stuck=1,
                                       stuck_detail=('S01E05: stalled with no connections',))]
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertEqual(self.get_run(run_id)['state'], S.TRANSFERRING)
        ready = self.stage(run_id, S.READY)
        self.assertEqual(ready['status'], S.PASSED)
        self.assertIn('stuck', ready['summary'])
        self.assertEqual(len(self.open_alerts('stuck_download')), 1)

    def test_thirty_minutes_is_the_most_it_waits(self):
        run_id = self.opened()
        opened_at = self.clock()
        still = InFlight(known=True, blocking=1, eta_seconds=300,
                         detail=('S01E06: Still downloading — 10%',))
        self.clock.advance(SETTLE_SECONDS)
        for _ in range(20):
            self.index.answers = [still]
            self.tick()
            if self.get_run(run_id)['state'] != S.WAITING_STATE:
                break
            self.clock.now = self.get_run(run_id)['next_check_at']
        run = self.get_run(run_id)
        self.assertEqual(run['state'], S.TRANSFERRING)
        self.assertIn('30 minutes', self.stage(run_id, S.READY)['summary'])
        self.assertEqual(len(self.open_alerts('ready_timeout')), 1)
        # It went at the deadline, not a full recheck after it.
        self.assertAlmostEqual(self.clock() - opened_at, READY_CAP_SECONDS, delta=1)

    def test_sonarr_down_means_the_old_timer(self):
        self.index.adapter = FakeAdapter(ok=False, message='connection refused')
        run_id = self.opened()
        run = self.get_run(run_id)
        self.assertEqual(run['ready_mode'], 'timer')
        self.assertEqual(len(self.open_alerts('integration_down')), 1)
        self.assertIn('fixed timer', self.stage(run_id, S.READY)['summary'])

    def test_every_webhook_pushes_the_timer_back(self):
        """The regression: the extension used to be read once and ignored."""
        self.index.adapter = FakeAdapter(ok=False, message='down')
        run_id = self.opened()
        opened_at = self.clock()
        self.assertAlmostEqual(self.get_run(run_id)['timer_due_at'], opened_at + 60, delta=0.01)

        self.clock.advance(30)
        self.sonarr(self.series_webhook('e2', 2))
        self.assertAlmostEqual(self.get_run(run_id)['timer_due_at'], opened_at + 120, delta=0.01)

        self.clock.advance(40)  # +70: past the original 60 s
        self.tick()
        self.assertEqual(self.get_run(run_id)['state'], S.WAITING_STATE,
                         'the batch must wait for the extended timer')

        self.clock.advance(50)  # +120
        self.tick()
        self.assertEqual(self.get_run(run_id)['state'], S.TRANSFERRING)

    def test_the_timer_never_runs_past_fifteen_minutes(self):
        self.index.adapter = FakeAdapter(ok=False, message='down')
        run_id = self.opened()
        opened_at = self.clock()
        for n in range(2, 40):
            self.sonarr(self.series_webhook(f"e{n}", n))
        self.assertLessEqual(self.get_run(run_id)['timer_due_at'], opened_at + 15 * 60 + 0.01)

    def test_sonarr_stops_answering_mid_wait(self):
        run_id = self.opened()
        self.index.answers = [InFlight(known=True, blocking=1, eta_seconds=60),
                              InFlight(known=False, reason='Sonarr did not answer')]
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.clock.advance(60)
        self.tick()
        # 70 s in: the 60 s timer has already run out, so it goes now.
        self.assertEqual(self.get_run(run_id)['ready_mode'], 'timer')
        self.assertEqual(self.get_run(run_id)['state'], S.TRANSFERRING)

    def test_no_sonarr_connector_means_the_timer_without_an_alert(self):
        self.index.adapter = None
        run_id = self.opened()
        self.assertEqual(self.get_run(run_id)['ready_mode'], 'timer')
        self.assertEqual(self.open_alerts('integration_down'), [])


class KindTests(EngineTestCase):
    """Each kind takes the stages its policy says, and explains every skip."""

    def test_radarr_never_waits(self):
        result = self.engine.submit(SyncRequest(
            kind=S.RADARR_WEBHOOK, source='radarr', media_type='movies',
            webhooks=[('radarr_webhook', self.movie_webhook('m1'))]))
        run = self.get_run(result.run_id)
        self.assertEqual(run['state'], S.TRANSFERRING)
        ready = self.stage(result.run_id, S.READY)
        self.assertEqual(ready['status'], S.SKIPPED)
        self.assertIn('nothing to wait for', ready['summary'])
        self.assertEqual(self.index.asked, 0)
        self.assertEqual(len(self.coordinator.transfer_service.calls), 1, 'dry run still runs')

    def test_every_skipped_stage_says_why(self):
        result = self.engine.submit(SyncRequest(
            kind=S.RADARR_WEBHOOK, source='radarr', media_type='movies',
            webhooks=[('radarr_webhook', self.movie_webhook('m1'))]))
        self.coordinator.finish(self.get_run(result.run_id)['transfer_id'], 'completed')
        for stage, row in self.store.stages(result.run_id).items():
            if row['status'] == S.SKIPPED:
                self.assertTrue(row['summary'], f"{stage} skipped without a reason")

    def test_a_manual_sync_promotes_a_waiting_batch(self):
        waiting = self.sonarr(self.series_webhook('e1', 1))
        self.assertEqual(self.get_run(waiting.run_id)['state'], S.WAITING_STATE)
        result = self.engine.sync_notifications(['e1'])
        self.assertTrue(result['ok'])
        self.assertEqual(result['run_ids'], [waiting.run_id], 'no second transfer')
        self.assertEqual(self.get_run(waiting.run_id)['state'], S.TRANSFERRING)
        self.assertIn('did not want to wait', self.stage(waiting.run_id, S.READY)['summary'])

    def test_automatic_sync_off_holds_the_batch_for_a_person(self):
        held = self.sonarr(self.series_webhook('e1', 1), hold=True)
        self.assertEqual(held.action, 'held')
        self.assertEqual(self.get_run(held.run_id)['state'], S.HELD)
        self.sonarr(self.series_webhook('e2', 2), hold=True)
        self.assertEqual(len(self.store.webhook_ids(held.run_id)), 2)
        self.clock.advance(3600)
        self.tick()
        self.assertEqual(self.get_run(held.run_id)['state'], S.HELD, 'nothing starts by itself')

        result = self.engine.sync_notifications(['e1', 'e2'])
        self.assertTrue(result['ok'])
        self.assertEqual(self.get_run(held.run_id)['state'], S.TRANSFERRING)

    def test_a_manual_sync_of_a_copying_episode_is_left_alone(self):
        first = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        result = self.engine.sync_notifications(['e1'])
        self.assertFalse(result['ok'])
        self.assertIn('being copied right now', result['message'])
        self.assertEqual(self.webhook('e1')['sync_run_id'], first.run_id)

    def test_the_scanner_never_duplicates_a_batch(self):
        self.sonarr(self.series_webhook('e1', 1))
        dest = os.path.join(self.config.get('TVSHOW_DEST_PATH'), 'Example Show (2020)',
                            'Season 01')
        result = self.engine.submit(SyncRequest(
            kind=S.AUTO_SCANNER, source='sonarr', media_type='tvshows',
            source_path=f"{REMOTE_TV}/Example Show (2020)/Season 01", dest_path=dest,
            title='Example Show', season_name='Season 01'))
        self.assertEqual(result.action, 'skipped')
        self.assertEqual(self.store.count(), 1)

    def test_an_identify_failure_is_still_written_down(self):
        model = self.coordinator.series_webhook_model
        model.create({'notification_id': 'bad', 'media_type': 'tvshows',
                      'series_title': 'Example Show', 'series_path': '',
                      'season_path': '', 'status': 'pending'}, '{}')
        result = self.sonarr('bad')
        self.assertFalse(result.ok)
        self.assertEqual(self.stage(result.run_id, S.IDENTIFY)['status'], S.FAILED)
        self.assertEqual(self.webhook('bad')['status'], 'failed')

    def test_explore_runs_synchronously_and_stands_alone(self):
        dest = os.path.join(self.config.get('TVSHOW_DEST_PATH'), 'Example Show (2020)',
                            'Season 01')
        self.sonarr(self.series_webhook('e1', 1))
        result = self.engine.submit(SyncRequest(
            kind=S.EXPLORE, media_type='tvshows',
            source_path=f"{REMOTE_TV}/Example Show (2020)/Season 01", dest_path=dest,
            folder_name='Example Show (2020)', season_name='Season 01',
            transfer_id='explore_abc', safety_summary='Plan judged safe',
            extra_fields={'explore_files_from': '/tmp/files.txt', 'explore_mode': 'sync'}),
            wait=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.queue_state, 'running')
        self.assertEqual(self.stage(result.run_id, S.BATCH)['status'], S.SKIPPED)
        self.assertEqual(self.stage(result.run_id, S.SAFETY)['summary'], 'Plan judged safe')
        row = self.coordinator.transfer_model.get('explore_abc')
        self.assertEqual(row['explore_files_from'], '/tmp/files.txt')
        self.assertEqual(row['sync_run_id'], result.run_id)


class SafetyTests(EngineTestCase):
    def test_an_unsafe_dry_run_stops_for_a_person(self):
        self.coordinator.transfer_service.result.update(
            safe_to_sync=False, reason='Would delete 40 media files but only receive 1',
            deleted_count=40)
        run = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        row = self.get_run(run.run_id)
        self.assertEqual(row['state'], S.REFUSED_STATE)
        self.assertEqual(self.stage(run.run_id, S.SAFETY)['status'], S.REFUSED)
        self.assertEqual(self.coordinator.started, [], 'nothing is written')
        hook = self.webhook('e1')
        self.assertEqual(hook['requires_manual_sync'], 1)
        alerts = self.open_alerts('sync_refused')
        self.assertEqual(len(alerts), 1)

        ok, message, _alert = self.alerts.act(alerts[0]['alert_id'], 'sync_anyway')
        self.assertTrue(ok, message)
        self.assertEqual(self.get_run(run.run_id)['state'], S.TRANSFERRING)
        self.assertIn('go ahead', self.stage(run.run_id, S.SAFETY)['summary'])

    def test_a_restarted_simulation_skips_the_dry_run(self):
        run = self.engine.submit(SyncRequest(
            kind=S.RESTART, media_type='tvshows',
            source_path=os.path.join(self.tmp.name, 'sandbox', 'Season 01'),
            dest_path=os.path.join(self.tmp.name, 'sandbox-out', 'Season 01'),
            folder_name='sandbox', season_name='Season 01', is_simulation=True))
        self.assertEqual(self.stage(run.run_id, S.SAFETY)['status'], S.SKIPPED)
        self.assertEqual(self.coordinator.transfer_service.calls, [])

    def test_a_single_file_needs_no_dry_run(self):
        dest = f"{self.config.get('TVSHOW_DEST_PATH')}/Example Show (2020)/Season 01/e1.mkv"
        run = self.engine.submit(SyncRequest(
            kind=S.MANUAL, media_type='tvshows',
            source_path=f"{REMOTE_TV}/Example Show (2020)/Season 01/e1.mkv", dest_path=dest,
            folder_name='Example Show (2020)', season_name='Season 01',
            operation_type='file'))
        self.assertEqual(self.stage(run.run_id, S.SAFETY)['status'], S.SKIPPED)
        self.assertEqual(self.coordinator.transfer_service.calls, [])

    def test_sync_anyway_says_so_when_the_queue_will_not_take_it(self):
        self.coordinator.transfer_service.result.update(
            safe_to_sync=False, reason='Would delete 40 media files but only receive 1',
            deleted_count=40)
        run = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.coordinator.start_transfer = lambda *args, **kwargs: (False, 'failed')
        result = self.engine.sync_anyway(run.run_id)
        self.assertFalse(result.ok)
        self.assertEqual(self.get_run(run.run_id)['state'], S.FAILED_STATE)


class FinishTests(EngineTestCase):
    def started(self):
        run = self.sonarr(self.series_webhook('e1', 1))
        self.sonarr(self.series_webhook('e2', 2))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        return run.run_id, self.get_run(run.run_id)['transfer_id']

    def test_completion_marks_every_webhook_and_announces(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'completed', 'Transfer completed successfully!')
        self.assertEqual(self.get_run(run_id)['state'], S.COMPLETED)
        self.assertEqual(self.webhook('e1')['status'], 'completed')
        self.assertEqual(self.webhook('e2')['status'], 'completed')
        self.assertEqual(self.coordinator.notification_service.sent,
                         [(transfer_id, 'completed', 'Automated Sync')])
        for stage in (S.TRANSFER, S.FINISH, S.TELL):
            self.assertEqual(self.stage(run_id, stage)['status'], S.PASSED, stage)

    def test_finishing_twice_is_harmless(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'completed')
        self.coordinator.finish(transfer_id, 'completed')
        self.assertEqual(len(self.coordinator.notification_service.sent), 1)

    def test_a_failure_opens_a_retry_alert(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'failed', 'Transfer failed with exit code: 23')
        self.assertEqual(self.get_run(run_id)['state'], S.FAILED_STATE)
        self.assertEqual(self.webhook('e1')['status'], 'failed')
        alerts = self.open_alerts('transfer_failed')
        self.assertEqual(len(alerts), 1)
        self.assertIn('retry', alerts[0]['actions'])

    def test_a_cancel_is_not_announced(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'cancelled', 'Transfer cancelled by user')
        self.assertEqual(self.get_run(run_id)['state'], S.CANCELLED)
        self.assertEqual(self.coordinator.notification_service.sent, [])
        self.assertEqual(self.stage(run_id, S.TELL)['status'], S.SKIPPED)

    def test_mark_as_done_closes_the_run_but_keeps_the_transfer_history(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'failed', 'Transfer failed with exit code: 23')
        alert = self.open_alerts('transfer_failed')[0]
        ok, message, _closed = self.alerts.act(alert['alert_id'], 'mark_done')
        self.assertTrue(ok, message)
        self.assertEqual(self.get_run(run_id)['state'], S.COMPLETED)
        self.assertEqual(self.webhook('e1')['status'], 'completed')
        self.assertEqual(self.coordinator.transfer_model.get(transfer_id)['status'], 'failed',
                         'what rsync did is not rewritten')
        self.assertIn('stays recorded as failed', self.stage(run_id, S.FINISH)['summary'])

    def test_go_now_on_a_finished_sync_is_refused(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'completed')
        result = self.engine.go_now(run_id)
        self.assertFalse(result.ok)
        self.assertEqual(result.message, 'This sync already ended.')

    def test_a_deleted_queued_transfer_does_not_strand_the_folder(self):
        self.coordinator.queue_state = 'QUEUED_SLOT'
        first = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertEqual(self.get_run(first.run_id)['state'], S.QUEUED)
        self.coordinator.transfer_model.delete(self.get_run(first.run_id)['transfer_id'])

        later = self.sonarr(self.series_webhook('e2', 2))
        self.assertEqual(later.action, 'opened', 'a fresh batch, not one that can never start')
        self.assertEqual(self.get_run(first.run_id)['state'], S.CANCELLED)
        self.assertIn('deleted', self.stage(first.run_id, S.QUEUE)['summary'])

    def test_cancelling_a_run_whose_transfer_was_deleted_closes_it(self):
        self.coordinator.queue_state = 'QUEUED_SLOT'
        run = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.coordinator.transfer_model.delete(self.get_run(run.run_id)['transfer_id'])
        result = self.engine.cancel_run(run.run_id)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.get_run(run.run_id)['state'], S.CANCELLED)

    def test_a_movie_waiting_for_its_folder_says_so(self):
        self.coordinator.queue_state = 'QUEUED_SLOT'
        run = self.engine.submit(SyncRequest(
            kind=S.RADARR_WEBHOOK, source='radarr', media_type='movies',
            webhooks=[('radarr_webhook', self.movie_webhook('m1'))]))
        transfer_id = self.get_run(run.run_id)['transfer_id']
        self.assertEqual(self.coordinator.webhook_model.get('m1')['status'], 'QUEUED_SLOT')
        self.engine.on_transfer_waiting(transfer_id, 'path', 'Queued: Waiting for "x" to complete')
        self.assertEqual(self.coordinator.webhook_model.get('m1')['status'], 'QUEUED_PATH')

    def test_a_refused_movie_carries_the_needs_a_person_flag(self):
        self.coordinator.transfer_service.result.update(
            safe_to_sync=False, reason='Server has fewer media files (0) than local (1)')
        self.engine.submit(SyncRequest(
            kind=S.RADARR_WEBHOOK, source='radarr', media_type='movies',
            webhooks=[('radarr_webhook', self.movie_webhook('m1'))]))
        movie = self.coordinator.webhook_model.get('m1')
        self.assertEqual(movie['requires_manual_sync'], 1)
        self.assertIn('fewer media files', movie['manual_sync_reason'])

    def test_a_held_batch_a_person_released_is_a_manual_sync(self):
        run = self.sonarr(self.series_webhook('e1', 1), hold=True)
        self.engine.go_now(run.run_id)
        transfer_id = self.get_run(run.run_id)['transfer_id']
        self.coordinator.finish(transfer_id, 'completed')
        self.assertEqual(self.coordinator.notification_service.sent,
                         [(transfer_id, 'completed', 'Manual Sync')])

    def test_a_restarted_simulation_is_not_announced(self):
        self.coordinator.transfer_model.create({
            'transfer_id': 'simulation_1', 'media_type': 'tvshows', 'folder_name': 'sandbox',
            'season_name': 'Season 01', 'operation_type': 'folder', 'status': 'failed',
            'source_path': os.path.join(self.tmp.name, 'sandbox', 'Season 01'),
            'dest_path': os.path.join(self.tmp.name, 'sandbox-out', 'Season 01'),
            'is_simulation': True})
        result = self.engine.restart_transfer('simulation_1')
        self.assertTrue(result.ok, result.message)
        self.coordinator.finish('simulation_1', 'failed', 'rsync error')
        self.assertEqual(self.coordinator.notification_service.sent, [])
        self.assertEqual(self.open_alerts('transfer_failed'), [])

    def test_a_retried_explore_plan_is_not_judged_by_a_folder_dry_run(self):
        self.coordinator.transfer_model.create({
            'transfer_id': 'explore_1', 'media_type': 'tvshows',
            'folder_name': 'Example Show (2020)', 'season_name': 'Season 01',
            'operation_type': 'folder', 'status': 'failed',
            'source_path': f"{REMOTE_TV}/Example Show (2020)/Season 01",
            'dest_path': f"{self.config.get('TVSHOW_DEST_PATH')}/Example Show (2020)/Season 01",
            'explore_files_from': '/tmp/plan-files.txt', 'explore_mode': 'download'})
        result = self.engine.restart_transfer('explore_1')
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.stage(result.run_id, S.SAFETY)['status'], S.SKIPPED)
        self.assertEqual(self.coordinator.transfer_service.calls, [])

    def test_retry_pressed_twice_starts_one_copy(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'failed', 'Transfer failed with exit code: 12')
        # The first press is still in its safety check when the second lands:
        # the transfer still reads failed, so only the open sync can say no.
        self.engine.inline = False
        first = self.engine.restart_transfer(transfer_id)
        self.assertEqual(self.get_run(first.run_id)['state'], S.CHECKING)
        second = self.engine.restart_transfer(transfer_id)
        self.engine.inline = True
        self.assertTrue(second.ok, second.message)
        self.assertEqual(second.run_id, first.run_id, 'the second press joins the first')
        restarts = [r for r in self.store.list(limit=20) if r['kind'] == S.RESTART]
        self.assertEqual(len(restarts), 1, 'one retry, so one rsync')

    def test_retry_while_the_folder_is_copying_is_refused(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'failed', 'Transfer failed with exit code: 12')
        other = self.sonarr(self.series_webhook('e9', 9))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertEqual(self.get_run(other.run_id)['state'], S.TRANSFERRING)
        result = self.engine.restart_transfer(transfer_id)
        self.assertFalse(result.ok)
        self.assertIn('being copied right now', result.message)

    def test_a_follow_up_batch_keeps_saying_it_is_one(self):
        first = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        follow = self.sonarr(self.series_webhook('e2', 2))
        self.sonarr(self.series_webhook('e3', 3))
        summary = self.stage(follow.run_id, S.BATCH)['summary']
        self.assertIn('Follow-up batch', summary)
        self.assertIn(first.run_id, summary)

    def test_a_restore_is_not_restarted_from_the_transfer_list(self):
        self.coordinator.transfer_model.create({
            'transfer_id': 'restore_1', 'media_type': 'movies', 'folder_name': 'Example Film (2024)',
            'operation_type': 'restore', 'status': 'failed',
            'source_path': '/backups/movies/Example Film (2024)',
            'dest_path': f"{self.config.get('MOVIE_DEST_PATH')}/Example Film (2024)"})
        result = self.engine.restart_transfer('restore_1')
        self.assertFalse(result.ok)
        self.assertIn('Backups page', result.message)

    def test_a_transfer_is_linked_to_its_title(self):
        from models.media_item import MediaItemStore
        from services.media_index import MediaIndex
        store = MediaItemStore(self.db)
        item_id = store.upsert('sonarr', '900001', title='Example Show')
        self.index.store = store
        self.index.note_transfer = MediaIndex.note_transfer.__get__(self.index)
        run_id, transfer_id = self.started()
        row = self.coordinator.transfer_model.get(transfer_id)
        self.assertEqual(row.get('media_item_id'), item_id)
        self.assertEqual(store.get('sonarr', '900001')['local_folder'], 'Example Show (2020)',
                         'the folder is learned from what the transfer used')

    def test_an_unknown_result_becomes_its_own_alert(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'failed',
                                'Result unknown: DragonCP restarted while this was copying')
        self.assertEqual(len(self.open_alerts('transfer_unknown')), 1)
        self.assertEqual(self.open_alerts('transfer_failed'), [])
        self.assertEqual(self.coordinator.notification_service.sent, [])

    def test_a_webhook_that_joined_after_the_copy_began_is_carried_forward(self):
        run_id, transfer_id = self.started()
        # Simulate the one window the lock cannot close: attached to this run
        # with a time after the copy began.
        self.series_webhook('late', 7)
        self.store.attach_webhook('sonarr_webhook', 'late', run_id)
        self.coordinator.finish(transfer_id, 'completed')
        late = self.webhook('late')
        self.assertNotEqual(late['sync_run_id'], run_id)
        self.assertNotEqual(late['status'], 'completed')
        follow = self.get_run(late['sync_run_id'])
        self.assertEqual(follow['parent_run_id'], run_id)

    def test_restart_is_a_new_run_through_the_queue(self):
        run_id, transfer_id = self.started()
        self.coordinator.finish(transfer_id, 'failed', 'Transfer failed with exit code: 12')
        result = self.engine.restart_transfer(transfer_id)
        self.assertTrue(result.ok, result.message)
        retry = self.get_run(result.run_id)
        self.assertEqual(retry['kind'], S.RESTART)
        self.assertEqual(retry['parent_run_id'], run_id)
        self.assertEqual(retry['parent_relation'], 'retry')
        self.assertEqual(self.coordinator.requeued, [transfer_id])
        self.assertEqual(self.webhook('e1')['sync_run_id'], result.run_id)
        self.assertEqual(self.stage(result.run_id, S.READY)['status'], S.SKIPPED)
        self.assertEqual(self.stage(result.run_id, S.SAFETY)['status'], S.PASSED)

    def test_describe_run_lists_all_nine_stages_with_their_logs(self):
        run_id, transfer_id = self.started()
        described = self.engine.describe_run(run_id)
        self.assertEqual([s['id'] for s in described['stage_detail']], list(S.STAGE_IDS))
        ready = next(s for s in described['stage_detail'] if s['id'] == S.READY)
        self.assertTrue(ready['events'], 'each stage carries its own log lines')
        self.assertEqual(described['webhook_count'], 2)
        self.assertEqual(described['transfer']['transfer_id'], transfer_id)


class RecoveryTests(EngineTestCase):
    def test_a_waiting_batch_becomes_an_alert_after_a_restart(self):
        from services.sync_engine.recovery import recover_after_restart
        run = self.sonarr(self.series_webhook('e1', 1))
        found = recover_after_restart(self.engine)
        self.assertEqual(found['interrupted'], 1)
        self.assertEqual(self.get_run(run.run_id)['state'], S.INTERRUPTED)
        self.assertEqual(self.webhook('e1')['requires_manual_sync'], 1)
        alerts = self.open_alerts('restart_unfinished')
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['data']['notification_ids'], ['e1'])

        ok, message, _ = self.alerts.act(alerts[0]['alert_id'], 'sync_now')
        self.assertTrue(ok, message)
        self.assertEqual(self.webhook('e1')['status'], 'syncing')

    def test_a_copy_starting_again_after_a_restart_is_not_called_interrupted(self):
        from services.sync_engine.recovery import recover_after_restart
        run = self.sonarr(self.series_webhook('e1', 1))
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        transfer_id = self.get_run(run.run_id)['transfer_id']
        self.coordinator.transfer_model.update(transfer_id, {'status': 'pending'})
        recover_after_restart(self.engine)
        self.assertEqual(self.get_run(run.run_id)['state'], S.QUEUED)
        self.assertEqual(self.open_alerts('restart_unfinished'), [])
        self.assertEqual(self.coordinator.transfer_model.get(transfer_id)['status'], 'queued',
                         'back in the queue, where it starts normally')

    def test_held_batches_survive_a_restart_untouched(self):
        from services.sync_engine.recovery import recover_after_restart
        held = self.sonarr(self.series_webhook('e1', 1), hold=True)
        recover_after_restart(self.engine)
        self.assertEqual(self.get_run(held.run_id)['state'], S.HELD)
        self.assertEqual(self.open_alerts(), [])

    def test_webhooks_the_old_scheduler_dropped_are_alerted_once(self):
        from services.sync_engine.recovery import recover_after_restart
        from models.sync_run import utc_now_iso
        self.series_webhook('old1', 1, auto_sync_scheduled_at=utc_now_iso())
        self.series_webhook('old2', 2, auto_sync_scheduled_at=utc_now_iso())
        self.series_webhook('manual-only', 3)  # automatic sync was off: not stranded
        found = recover_after_restart(self.engine)
        self.assertEqual(found['legacy_alerts'], 1)
        alerts = self.open_alerts('restart_unfinished')
        self.assertEqual(sorted(alerts[0]['data']['notification_ids']), ['old1', 'old2'])
        recover_after_restart(self.engine)
        self.assertEqual(len(self.open_alerts('restart_unfinished')), 1, 'not repeated')


class QueueOverlapTests(unittest.TestCase):
    """One writer per season; a whole series collides with any of its seasons."""

    def setUp(self):
        from services.queue_manager import QueueManager

        class _Model:
            def get_all(self, **kwargs):
                return []

        self.queue = QueueManager(_Model())

    def test_two_seasons_of_one_show_may_copy_together(self):
        self.assertEqual(self.queue.register_transfer('a', '/lib/Show/Season 01'), (True, 'running'))
        self.assertEqual(self.queue.register_transfer('b', '/lib/Show/Season 02'), (True, 'running'))

    def test_the_same_season_never_twice(self):
        self.queue.register_transfer('a', '/lib/Show/Season 01')
        self.assertEqual(self.queue.check_duplicate_destination('/lib/Show/Season 01', 'b'),
                         (True, 'a'))

    def test_a_whole_series_collides_with_its_seasons(self):
        self.queue.register_transfer('a', '/lib/Show/Season 01')
        self.assertEqual(self.queue.check_duplicate_destination('/lib/Show', 'b'), (True, 'a'))
        self.queue.register_transfer('c', '/lib/Other')
        self.assertEqual(self.queue.check_duplicate_destination('/lib/Other/Season 03', 'd'),
                         (True, 'c'))

    def test_a_similar_name_is_not_a_collision(self):
        self.queue.register_transfer('a', '/lib/Show')
        self.assertEqual(self.queue.check_duplicate_destination('/lib/Show Two/Season 01', 'b'),
                         (False, None))

    def test_after_a_restart_a_series_and_its_season_do_not_block_each_other(self):
        from services.queue_manager import QueueManager

        rows = [
            {'transfer_id': 'series', 'dest_path': '/lib/Show', 'status': 'queued',
             'queue_reason': 'path', 'created_at': '2026-10-05T10:00:00'},
            {'transfer_id': 'season', 'dest_path': '/lib/Show/Season 01', 'status': 'queued',
             'queue_reason': 'path', 'created_at': '2026-10-05T10:01:00'},
        ]

        class _Model:
            def get_all(self, statuses=None, **kwargs):
                return [r for r in rows if not statuses or r['status'] in statuses]

            def get(self, transfer_id):
                return next((r for r in rows if r['transfer_id'] == transfer_id), None)

            def update(self, transfer_id, fields):
                self.get(transfer_id).update(fields)

        started = []

        class _Coordinator:
            series_webhook_model = None

            def start_queued_transfer(self, transfer_id):
                started.append(transfer_id)

            def _hook(self, *args):
                pass

        queue = QueueManager(_Model())
        queue.set_coordinator(_Coordinator())
        queue.force_unregister_stale_transfers(promote=False)
        self.assertEqual(queue.running_transfers, {},
                         'nothing starts before the sync engine has looked at the restart')
        queue.promote_waiting()
        self.assertIn('series', queue.running_transfers,
                      'the oldest starts; the season waits behind it instead of both waiting')
        self.assertNotIn('season', queue.running_transfers)


if __name__ == '__main__':
    unittest.main()
