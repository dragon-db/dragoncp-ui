#!/usr/bin/env python3
"""
The pipeline, Notifications and scheduler routes.

Mounted on a bare Flask app over the engine test fixtures: a real database,
fakes for Sonarr, the dry run and the queue. Pins what the interface relies
on — every run lists its nine stages, a stage's log lines can be read on their
own, every action answers with what happened, and nothing answers anyone who
is not signed in.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import auth
import routes.sync_engine as sync_routes
from services.scheduler import Job, SchedulerService
from services.sync_engine import stages as S
from services.sync_engine.engine import SETTLE_SECONDS
from tests.test_sync_engine import EngineTestCase

SIGNED_IN_PAYLOAD = {'sub': 'tester', 'uid': 1, 'tv': 1, 'src': 'db', 'type': 'access'}
SIGNED_IN_IDENTITY = {
    'account_id': 1, 'username': 'tester', 'role': 'admin',
    'token_version': 1, 'must_change_password': False, 'source': 'db',
}


class RouteTestCase(EngineTestCase):
    signed_in = True

    def setUp(self):
        super().setUp()
        self.scheduler = SchedulerService(self.db, alerts=self.alerts, clock=self.clock)
        self.scheduler.inline = True
        self.job_runs = 0

        def run():
            self.job_runs += 1
            return {'ok': True, 'summary': 'Checked 0 titles.'}
        self.scheduler.register(Job(name='sonarr_auto_scanner', label='Sonarr auto-scanner',
                                    description='', interval=lambda: 900, run=run))
        self.coordinator.sync_engine = self.engine
        self.coordinator.alerts = self.alerts
        self.coordinator.scheduler = self.scheduler
        self.alerts.scheduler = self.scheduler

        sync_routes.init_sync_engine_routes(self.coordinator)
        self.addCleanup(sync_routes.init_sync_engine_routes, None)
        app = Flask(__name__)
        app.register_blueprint(sync_routes.sync_engine_bp, url_prefix='/api')
        self.client = app.test_client()

        if self.signed_in:
            for target, value in (
                ('auth.get_token_from_request', 'token'),
                ('auth.validate_token', SIGNED_IN_PAYLOAD),
                ('auth.resolve_identity', (SIGNED_IN_IDENTITY, auth.REASON_OK)),
            ):
                patcher = patch(target, return_value=value)
                self.addCleanup(patcher.stop)
                patcher.start()

    def waiting_run(self):
        return self.sonarr(self.series_webhook('e1', 1)).run_id


class PipelineRouteTests(RouteTestCase):
    def test_the_catalogue_is_the_pipeline_the_engine_runs(self):
        body = self.client.get('/api/sync/catalogue').get_json()
        self.assertEqual([s['id'] for s in body['stages']], list(S.STAGE_IDS))
        kinds = {k['id']: k for k in body['kinds']}
        self.assertIn(S.AUTO_SCANNER, kinds)
        self.assertIn('open', body['state_groups'])
        self.assertIn('dismiss', body['alert_actions'])

    def test_runs_list_with_their_stage_strip(self):
        run_id = self.waiting_run()
        body = self.client.get('/api/sync/runs').get_json()
        self.assertEqual(body['total'], 1)
        row = body['runs'][0]
        self.assertEqual(row['run_id'], run_id)
        self.assertEqual(len(row['stages']), 9)
        self.assertEqual(row['webhook_count'], 1)
        self.assertEqual(row['label'], 'Example Show — Season 01')
        self.assertTrue(row['current_summary'], 'a row says what the run is doing now')

    def test_runs_filter_by_state_group_and_kind(self):
        self.waiting_run()
        self.assertEqual(self.client.get('/api/sync/runs?state=open').get_json()['total'], 1)
        self.assertEqual(self.client.get('/api/sync/runs?state=finished').get_json()['total'], 0)
        self.assertEqual(self.client.get('/api/sync/runs?kind=manual').get_json()['total'], 0)
        self.assertEqual(
            self.client.get('/api/sync/runs?kind=manual,sonarr_webhook').get_json()['total'], 1)

    def test_runs_filter_by_whether_their_copy_started(self):
        # The Transfers page lists syncs that never became a copy beside its
        # transfers; one that reached the copy already has a transfer row.
        waiting = self.waiting_run()
        copying = self.engine.submit(self._manual_request()).run_id
        self.assertEqual(self.get_run(copying)['state'], S.TRANSFERRING)

        def ids(query):
            return [r['run_id'] for r in self.client.get(f'/api/sync/runs?{query}')
                    .get_json()['runs']]

        self.assertEqual(ids('copied=0'), [waiting])
        self.assertEqual(ids('copied=1'), [copying])
        self.assertEqual(sorted(ids('state=all')), sorted([waiting, copying]))
        self.assertEqual(
            self.client.get('/api/sync/runs?copied=0').get_json()['total'], 1)

    def test_one_run_shows_every_stage_with_its_own_log_lines(self):
        run_id = self.waiting_run()
        response = self.client.get(f'/api/sync/runs/{run_id}')
        self.assertEqual(response.status_code, 200)
        run = response.get_json()['run']
        stages = {s['id']: s for s in run['stage_detail']}
        self.assertEqual(list(stages), list(S.STAGE_IDS))
        self.assertEqual(stages[S.RECEIVE]['status'], S.PASSED)
        self.assertIn('Sonarr webhook', stages[S.RECEIVE]['summary'])
        self.assertEqual(run['webhooks'][0]['notification_id'], 'e1')
        self.assertIn('go_now', run['actions'])
        self.assertIn('cancel', run['actions'])

    def test_a_skipped_stage_says_why(self):
        run_id = self.engine.submit(self._manual_request()).run_id
        stages = {s['id']: s for s in
                  self.client.get(f'/api/sync/runs/{run_id}').get_json()['run']['stage_detail']}
        self.assertEqual(stages[S.READY]['status'], S.SKIPPED)
        self.assertTrue(stages[S.READY]['summary'])

    def _manual_request(self):
        from services.sync_engine.engine import SyncRequest
        return SyncRequest(kind=S.MANUAL, source='manual', media_type='tvshows',
                           source_path='/remote/tv/Example Show (2020)/Season 02',
                           dest_path=f"{self.config.get('TVSHOW_DEST_PATH')}/"
                                     f"Example Show (2020)/Season 02",
                           folder_name='Example Show (2020)', season_name='Season 02',
                           title='Example Show', operation_type='folder')

    def test_an_unknown_run_is_404(self):
        self.assertEqual(self.client.get('/api/sync/runs/run_nothing').status_code, 404)
        self.assertEqual(self.client.get('/api/sync/runs/run_nothing/events').status_code, 404)

    def test_log_lines_can_be_read_after_an_id_and_by_stage(self):
        run_id = self.waiting_run()
        self.sonarr(self.series_webhook('e2', 2))
        events = self.client.get(f'/api/sync/runs/{run_id}/events').get_json()['events']
        self.assertTrue(events)
        last = events[-1]['id']
        self.assertEqual(
            self.client.get(f'/api/sync/runs/{run_id}/events?after={last}').get_json()['events'],
            [])
        batch_only = self.client.get(
            f'/api/sync/runs/{run_id}/events?stage={S.BATCH}').get_json()['events']
        self.assertTrue(batch_only)
        self.assertTrue(all(e['stage'] == S.BATCH for e in batch_only))

    def test_a_webhook_or_a_transfer_leads_to_its_run(self):
        run_id = self.waiting_run()
        body = self.client.get('/api/sync/lookup?notification_id=e1').get_json()
        self.assertEqual(body['run_id'], run_id)
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        transfer_id = self.get_run(run_id)['transfer_id']
        body = self.client.get(f'/api/sync/lookup?transfer_id={transfer_id}').get_json()
        self.assertEqual(body['run_id'], run_id)
        self.assertEqual(self.client.get('/api/sync/lookup').status_code, 400)
        self.assertEqual(self.client.get('/api/sync/lookup?transfer_id=nope').status_code, 404)

    def test_go_now_skips_the_wait(self):
        run_id = self.waiting_run()
        response = self.client.post(f'/api/sync/runs/{run_id}/go-now')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.get_run(run_id)['state'], S.TRANSFERRING)

    def test_go_now_on_a_finished_sync_is_409(self):
        run_id = self.waiting_run()
        self.client.post(f'/api/sync/runs/{run_id}/cancel')
        response = self.client.post(f'/api/sync/runs/{run_id}/go-now')
        self.assertEqual(response.status_code, 409)

    def test_cancel_then_cancel_again(self):
        run_id = self.waiting_run()
        self.assertEqual(self.client.post(f'/api/sync/runs/{run_id}/cancel').status_code, 200)
        self.assertEqual(self.get_run(run_id)['state'], S.CANCELLED)
        response = self.client.post(f'/api/sync/runs/{run_id}/cancel')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['message'], 'This sync already ended.')

    def test_sync_anyway_only_for_a_refused_sync(self):
        run_id = self.waiting_run()
        self.assertEqual(
            self.client.post(f'/api/sync/runs/{run_id}/sync-anyway').status_code, 409)

        self.coordinator.transfer_service.result.update(
            safe_to_sync=False, reason='Would delete 40 files here', deleted_count=40)
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertEqual(self.get_run(run_id)['state'], S.REFUSED_STATE)
        response = self.client.post(f'/api/sync/runs/{run_id}/sync-anyway')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.get_run(run_id)['state'], S.TRANSFERRING)


class AlertRouteTests(RouteTestCase):
    def refused(self):
        run_id = self.waiting_run()
        self.coordinator.transfer_service.result.update(
            safe_to_sync=False, reason='Would delete 40 files here', deleted_count=40)
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        return run_id

    def test_open_alerts_and_the_badge(self):
        self.refused()
        body = self.client.get('/api/alerts').get_json()
        self.assertEqual(len(body['alerts']), 1)
        self.assertEqual(body['alerts'][0]['kind'], 'sync_refused')
        self.assertEqual(self.client.get('/api/alerts/summary').get_json()['open'], 1)

    def test_acting_on_an_alert_closes_it(self):
        run_id = self.refused()
        alert_id = self.client.get('/api/alerts').get_json()['alerts'][0]['alert_id']
        response = self.client.post(f'/api/alerts/{alert_id}/action',
                                    json={'action': 'sync_anyway'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.get_run(run_id)['state'], S.TRANSFERRING)
        self.assertEqual(self.client.get('/api/alerts/summary').get_json()['open'], 0)

    def test_the_total_follows_the_kind_filter(self):
        self.refused()
        self.alerts.job_failing('sonarr_auto_scanner', 'Sonarr auto-scanner', 'timeout', 3)
        self.assertEqual(self.client.get('/api/alerts').get_json()['total'], 2)
        body = self.client.get('/api/alerts?kind=sync_refused').get_json()
        self.assertEqual(len(body['alerts']), 1)
        self.assertEqual(body['total'], 1)

    def test_closed_alerts_list_together(self):
        self.refused()
        alert_id = self.client.get('/api/alerts').get_json()['alerts'][0]['alert_id']
        self.client.post(f'/api/alerts/{alert_id}/action', json={'action': 'dismiss'})
        body = self.client.get('/api/alerts?state=done,wrong,dismissed').get_json()
        self.assertEqual([a['alert_id'] for a in body['alerts']], [alert_id])
        self.assertEqual(body['total'], 1)
        self.assertEqual(self.client.get('/api/alerts').get_json()['total'], 0)

    def test_a_closed_or_unknown_alert_or_action_is_refused(self):
        self.refused()
        alert_id = self.client.get('/api/alerts').get_json()['alerts'][0]['alert_id']
        self.assertEqual(self.client.post(f'/api/alerts/{alert_id}/action',
                                          json={'action': 'explode'}).status_code, 400)
        self.assertEqual(self.client.post('/api/alerts/nope/action',
                                          json={'action': 'dismiss'}).status_code, 404)
        self.client.post(f'/api/alerts/{alert_id}/action', json={'action': 'dismiss'})
        self.assertEqual(self.client.post(f'/api/alerts/{alert_id}/action',
                                          json={'action': 'dismiss'}).status_code, 409)


class SchedulerRouteTests(RouteTestCase):
    def test_jobs_are_listed_with_their_schedule(self):
        jobs = self.client.get('/api/scheduler/jobs').get_json()['jobs']
        self.assertEqual(jobs[0]['name'], 'sonarr_auto_scanner')
        self.assertTrue(jobs[0]['enabled'])

    def test_run_now(self):
        response = self.client.post('/api/scheduler/jobs/sonarr_auto_scanner/run')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.job_runs, 1)
        self.assertEqual(response.get_json()['job']['last_result']['summary'],
                         'Checked 0 titles.')
        self.assertEqual(self.client.post('/api/scheduler/jobs/nope/run').status_code, 404)


class SignedOutTests(RouteTestCase):
    signed_in = False

    def test_nothing_answers_without_signing_in(self):
        for path in ('/api/sync/catalogue', '/api/sync/runs', '/api/alerts',
                     '/api/alerts/summary', '/api/scheduler/jobs'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in ('/api/sync/runs/x/go-now', '/api/sync/runs/x/cancel',
                     '/api/sync/runs/x/sync-anyway', '/api/alerts/x/action',
                     '/api/scheduler/jobs/x/run'):
            self.assertEqual(self.client.post(path).status_code, 401, path)


if __name__ == '__main__':
    unittest.main()
