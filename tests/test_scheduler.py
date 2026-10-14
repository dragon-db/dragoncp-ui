#!/usr/bin/env python3
"""
The scheduler: one service for everything DragonCP does on a clock.

Pins what every job gets without asking: an on/off switch read on every tick,
a first run shortly after start-up, no overlapping runs, a remembered last
result, and an alert after three failures in a row.
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
from services.alert_service import AlertService
from services.scheduler import FAILURES_BEFORE_ALERT, Job, SchedulerService


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'scheduler.db'))
        self.clock = Clock()
        self.alerts = AlertService(AlertStore(self.db))
        self.scheduler = SchedulerService(self.db, alerts=self.alerts, clock=self.clock)
        self.scheduler.inline = True
        self.runs = 0
        self.enabled = True
        self.fail = False

    def job(self, name='scan', interval=900, first=60):
        def run():
            self.runs += 1
            if self.fail:
                raise RuntimeError('the service did not answer')
            return {'ok': True, 'summary': f'run {self.runs}'}
        self.scheduler.register(Job(name=name, label='Scan', description='',
                                    interval=lambda: interval if self.enabled else None,
                                    run=run, first_run_delay=first))

    def test_first_run_comes_shortly_after_start_then_every_interval(self):
        self.job()
        self.scheduler.tick()
        self.assertEqual(self.runs, 0)
        self.clock.now += 60
        self.scheduler.tick()
        self.assertEqual(self.runs, 1)
        self.clock.now += 899
        self.scheduler.tick()
        self.assertEqual(self.runs, 1)
        self.clock.now += 1
        self.scheduler.tick()
        self.assertEqual(self.runs, 2)

    def test_switched_off_means_it_never_runs(self):
        self.enabled = False
        self.job()
        for _ in range(5):
            self.clock.now += 1000
            self.scheduler.tick()
        self.assertEqual(self.runs, 0)
        self.assertFalse(self.scheduler.status()[0]['enabled'])
        self.assertIsNone(self.scheduler.status()[0]['next_run_at'])

    def test_switching_on_needs_no_restart(self):
        self.enabled = False
        self.job()
        self.scheduler.tick()
        self.enabled = True
        self.clock.now += 61
        self.scheduler.tick()
        self.assertEqual(self.runs, 1)

    def test_a_running_job_is_never_started_twice(self):
        self.job()
        state = self.scheduler._state['scan']
        state.running = True
        self.clock.now += 100
        self.scheduler.tick()
        self.assertEqual(self.runs, 0)
        self.assertFalse(self.scheduler.run_now('scan'))

    def test_three_failures_in_a_row_open_one_alert_and_success_closes_it(self):
        self.job(first=0)
        self.fail = True
        for _ in range(FAILURES_BEFORE_ALERT + 1):
            self.scheduler.run_now('scan')
        open_alerts = self.alerts.store.list(states=['open'])
        self.assertEqual(len(open_alerts), 1)
        self.assertEqual(open_alerts[0]['kind'], 'job_failing')
        self.assertEqual(open_alerts[0]['occurrences'], 2, 'bumped, not stacked')

        self.fail = False
        self.scheduler.run_now('scan')
        self.assertEqual(self.alerts.store.list(states=['open']), [])

    def test_a_dismissed_failing_job_stays_quiet_for_a_day(self):
        self.job(first=0)
        self.fail = True
        for _ in range(FAILURES_BEFORE_ALERT):
            self.scheduler.run_now('scan')
        alert = self.alerts.store.list(states=['open'])[0]
        self.alerts.act(alert['alert_id'], 'dismiss')
        self.scheduler.run_now('scan')
        self.assertEqual(self.alerts.store.list(states=['open']), [],
                         'not reopened, and not re-announced, every run')

        with self.db.get_connection() as conn:
            conn.execute("UPDATE alert SET resolved_at = '2000-01-01T00:00:00+00:00'")
            conn.commit()
        self.scheduler.run_now('scan')
        self.assertEqual(len(self.alerts.store.list(states=['open'])), 1,
                         'a day later, still failing, it says so again')

    def test_the_last_result_survives_a_restart(self):
        self.job(first=0)
        self.scheduler.run_now('scan')
        again = SchedulerService(self.db, clock=self.clock)
        again.register(Job(name='scan', label='Scan', description='', interval=lambda: 900,
                           run=lambda: {'ok': True}))
        status = again.status()[0]
        self.assertEqual(status['last_result']['summary'], 'run 1')
        self.assertTrue(status['last_ok'])

    def test_one_broken_job_does_not_stop_the_others(self):
        self.scheduler.register(Job(name='broken', label='Broken', description='',
                                    interval=lambda: 60, run=lambda: 1 / 0,
                                    first_run_delay=0))
        self.job(name='fine', first=0)
        self.clock.now += 1
        self.scheduler.tick()
        self.assertEqual(self.runs, 1)
        broken = self.scheduler.job_status('broken')
        self.assertFalse(broken['last_ok'])
        self.assertIn('division by zero', broken['last_result']['summary'])


if __name__ == '__main__':
    unittest.main()
