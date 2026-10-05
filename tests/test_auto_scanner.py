#!/usr/bin/env python3
"""
The scheduled auto-scanner: what a webhook never delivered.

Pins the rules decided on 2026-10-02:
  * imports since the last scan that nothing has synced since are synced;
  * seasons this disk keeps but is short of are filled in;
  * a title this disk has never held is NOT fetched just because the service
    has it — only when the service imports something for it;
  * every find goes through the engine (no duplicates, the usual checks);
  * at most five new syncs per scan; a gap tried twice waits for a person.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.auto_scanner import MAX_NEW_RUNS_PER_SCAN, AutoScanner
from services.connectors.base import CheckResult
from services.sync_engine import stages as S
from services.sync_engine.engine import SETTLE_SECONDS
from tests.test_sync_engine import REMOTE_TV, EngineTestCase


class FakeArr:
    def __init__(self):
        self.ok = True
        self.enabled = True
        self.minutes = 15
        self.records = []
        self.history_ok = True
        self.folders = {}

    def check(self):
        return CheckResult(self.ok, 'Connected' if self.ok else 'connection refused')

    def auto_scanner_enabled(self):
        return self.enabled

    def auto_scanner_interval_minutes(self):
        return self.minutes

    def imports_since(self, since):
        self.since = since
        return self.history_ok, list(self.records)

    def season_folder(self, series_id, season):
        return self.folders.get((series_id, season))


class FakeLibraryIndex:
    def __init__(self, adapter):
        self.adapter = adapter
        self.items = []
        self.live = True

    def _adapter(self, source):
        return self.adapter

    def library_view(self, source, refresh=False):
        return {'live': self.live, 'total': len(self.items), 'items': list(self.items)}


def show(external_id='900001', service_id=219, title='Example Show',
         folder='Example Show (2020)', present=True, seasons=None, media_type='tvshows'):
    return {
        'external_id': external_id, 'service_item_id': service_id, 'title': title,
        'service_path': f"{REMOTE_TV}/{folder}", 'local_folder': folder if present else None,
        'media_type': media_type, 'present_locally': present, 'service_has_files': True,
        'seasons': seasons if seasons is not None else [
            {'season_number': 1, 'episode_file_count': 10, 'files_here': 10,
             'counts_towards_state': True},
        ],
    }


def imported(series_id=219, season=1, hours_ago=1):
    when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {'seriesId': series_id, 'episode': {'seasonNumber': season},
            'date': when.isoformat().replace('+00:00', 'Z')}


class ScannerTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.arr = FakeArr()
        self.library = FakeLibraryIndex(self.arr)
        self.scanner = AutoScanner(self.db, self.library, self.engine, self.config,
                                   alerts=self.alerts)

    def scan(self):
        return self.scanner.scan('sonarr')

    def scanner_runs(self):
        return [r for r in self.store.list(limit=100) if r['kind'] == S.AUTO_SCANNER]

    def test_switched_off_means_no_schedule(self):
        self.arr.enabled = False
        self.assertIsNone(self.scanner.interval_seconds('sonarr'))
        self.arr.enabled = True
        self.assertEqual(self.scanner.interval_seconds('sonarr'), 15 * 60)

    def test_an_import_nothing_synced_is_synced(self):
        self.library.items = [show()]
        self.arr.records = [imported()]
        result = self.scan()
        self.assertTrue(result['ok'])
        self.assertEqual(result['started'], 1)
        runs = self.scanner_runs()
        self.assertEqual(len(runs), 1)
        receive = self.store.stages(runs[0]['run_id'])[S.RECEIVE]['summary']
        self.assertIn('never synced', receive)
        self.assertTrue(runs[0]['dest_path'].endswith('Example Show (2020)/Season 01'))
        self.assertEqual(runs[0]['options'].get('tvdb_id'), '900001',
                         'Sonarr finds keep the id the ready check asks about')

    def test_an_import_already_synced_since_is_left_alone(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=3)]
        self.scan()
        run_id = self.scanner_runs()[0]['run_id']
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.coordinator.finish(self.get_run(run_id)['transfer_id'], 'completed')
        result = self.scan()
        self.assertEqual(result['found'], 0)
        self.assertEqual(len(self.scanner_runs()), 1)

    def test_a_season_already_on_its_way_is_not_duplicated(self):
        self.series_webhook('e1', 1)
        self.sonarr('e1')
        self.library.items = [show()]
        self.arr.records = [imported()]
        result = self.scan()
        self.assertEqual(result['started'], 0)
        self.assertEqual(result['already_on_its_way'], 1)
        self.assertEqual(self.scanner_runs(), [])

    def test_an_import_after_the_copy_began_is_looked_at_again(self):
        self.series_webhook('e1', 1)
        first = self.sonarr('e1')
        self.clock.advance(SETTLE_SECONDS)
        self.tick()
        self.assertEqual(self.get_run(first.run_id)['state'], S.TRANSFERRING)
        self.library.items = [show()]
        # Imported a moment after the copy began listing the folder.
        self.arr.records = [imported(hours_ago=-0.001)]
        before = self.scanner._last_scan_at('sonarr')

        result = self.scan()
        self.assertEqual(result['already_on_its_way'], 1)
        self.assertEqual(self.scanner._last_scan_at('sonarr'), before,
                         'the copy may have missed it, so the window stays put')

        self.coordinator.finish(self.get_run(first.run_id)['transfer_id'], 'completed')
        result = self.scan()
        self.assertEqual(result['started'], 1, 'the copy began before the import')

    def test_a_short_season_this_disk_keeps_is_filled_in(self):
        self.library.items = [show(seasons=[
            {'season_number': 1, 'episode_file_count': 10, 'files_here': 8,
             'counts_towards_state': True}])]
        result = self.scan()
        self.assertEqual(result['started'], 1)
        run = self.scanner_runs()[0]
        self.assertIn('missing here', self.store.stages(run['run_id'])[S.RECEIVE]['summary'])

    def test_the_backlog_is_not_a_gap(self):
        """A season this disk does not keep, or a title it never held, is left alone."""
        self.library.items = [
            show(seasons=[{'season_number': 2, 'episode_file_count': 10, 'files_here': 0,
                           'counts_towards_state': True}]),
            show(external_id='900002', service_id=220, title='Another Show',
                 folder='Another Show (2021)', present=False),
        ]
        result = self.scan()
        self.assertEqual(result['found'], 0)
        self.assertEqual(self.scanner_runs(), [])

    def test_a_new_title_is_fetched_once_it_is_imported(self):
        self.library.items = [show(external_id='900002', service_id=220, title='Another Show',
                                   folder='Another Show (2021)', present=False)]
        self.arr.records = [imported(series_id=220)]
        result = self.scan()
        self.assertEqual(result['started'], 1)

    def test_specials_are_ignored(self):
        self.library.items = [show()]
        self.arr.records = [imported(season=0)]
        self.assertEqual(self.scan()['found'], 0)

    def test_a_path_outside_the_configured_root_is_refused(self):
        item = show()
        item['service_path'] = '/somewhere/else/Example Show (2020)'
        self.library.items = [item]
        self.arr.records = [imported()]
        self.assertEqual(self.scan()['found'], 0)

    def test_the_real_season_folder_name_is_used(self):
        self.arr.folders[(219, 1)] = 'Season 1'
        self.library.items = [show()]
        self.arr.records = [imported()]
        self.scan()
        run = self.scanner_runs()[0]
        self.assertTrue(run['source_path'].endswith('/Season 1'))

    def test_at_most_five_new_syncs_per_scan_and_the_rest_wait(self):
        self.library.items = [
            show(external_id=f"9{i:05d}", service_id=300 + i, title=f"Show {i}",
                 folder=f"Show {i} (2020)") for i in range(7)]
        self.arr.records = [imported(series_id=300 + i) for i in range(7)]
        before = self.scanner._last_scan_at('sonarr')
        result = self.scan()
        self.assertEqual(result['started'], MAX_NEW_RUNS_PER_SCAN)
        self.assertEqual(result['held_back'], 2)
        self.assertEqual(self.scanner._last_scan_at('sonarr'), before,
                         'the history window must not move past what was held back')
        result = self.scan()
        self.assertEqual(result['started'], 2)
        self.assertEqual(result['already_on_its_way'], MAX_NEW_RUNS_PER_SCAN)

    def test_a_gap_tried_twice_waits_for_a_person(self):
        self.library.items = [show(seasons=[
            {'season_number': 1, 'episode_file_count': 10, 'files_here': 8,
             'counts_towards_state': True}])]
        for _ in range(2):
            self.scan()
            for run in self.scanner_runs():
                if run['state'] not in S.TERMINAL_STATES:
                    self.engine.cancel_run(run['run_id'])
        result = self.scan()
        self.assertEqual(result['started'], 0)
        self.assertEqual(result['needs_a_person'], 1)
        alerts = [a for a in self.alerts.store.list(states=['open'])
                  if a['kind'] == 'scanner_gap']
        self.assertEqual(len(alerts), 1)

    def test_a_service_that_does_not_answer_is_a_failed_scan(self):
        self.arr.ok = False
        result = self.scan()
        self.assertFalse(result['ok'])
        self.assertIn('did not answer', result['summary'])

    def test_sync_one_fetches_every_short_season_on_request(self):
        self.library.items = [show(seasons=[
            {'season_number': 1, 'episode_file_count': 10, 'files_here': 10,
             'counts_towards_state': True},
            {'season_number': 2, 'episode_file_count': 10, 'files_here': 0,
             'counts_towards_state': True},
            {'season_number': 3, 'episode_file_count': 10, 'files_here': 4,
             'counts_towards_state': True}])]
        result = self.scanner.sync_one('sonarr', '900001')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['transfers_started'], 2)
        kinds = {r['kind'] for r in self.store.list(limit=10)}
        self.assertEqual(kinds, {S.MANUAL})


if __name__ == '__main__':
    unittest.main()
