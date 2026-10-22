#!/usr/bin/env python3
"""
The scheduled auto-scanner: what a webhook never delivered.

Pins the rules decided on 2026-10-02 (Sync it):
  * imports since the last scan that nothing has synced since are synced;
  * seasons this disk keeps but is short of are filled in;
  * a title this disk has never held is NOT fetched just because the service
    has it — only when the service imports something for it;
  * every find goes through the engine (no duplicates, the usual checks);
  * at most five new syncs per scan; a gap tried twice waits for a person.

And Alert only, the default since 2026-10-19: a find opens one alert, copies
nothing, and comes back only when something new is imported.
"""

import os
import sys
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.auto_scanner import MAX_NEW_RUNS_PER_SCAN, AutoScanner
from services.connectors.base import CheckResult
from services.sync_engine import stages as S
from services.sync_engine.engine import SETTLE_SECONDS
from services.sync_engine.units import unit_key
from tests.test_sync_engine import REMOTE_TV, EngineTestCase


class FakeArr:
    def __init__(self):
        self.ok = True
        self.enabled = True
        self.minutes = 15
        self.records = []
        self.history_ok = True
        self.folders = {}
        # The rules below are Sync it's; Alert only has its own tests.
        self.mode = 'sync'

    def check(self):
        return CheckResult(self.ok, 'Connected' if self.ok else 'connection refused')

    def auto_scanner_enabled(self):
        return self.enabled

    def auto_scanner_interval_minutes(self):
        return self.minutes

    def auto_scanner_mode(self):
        return self.mode

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


class ScannerTestCase(EngineTestCase):
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

    def finished_copy(self, started_hours_ago, ended_hours_ago=0, owned=True,
                      operation_type='folder', resumed_hours_ago=None):
        """A finished copy of season 1, written down the way the database keeps it."""
        now = datetime.now(timezone.utc)
        started = now - timedelta(hours=started_hours_ago)
        ended = now - timedelta(hours=ended_hours_ago)
        dest = os.path.join(self.config.get('TVSHOW_DEST_PATH'), 'Example Show (2020)',
                            'Season 01')
        source = f"{REMOTE_TV}/Example Show (2020)/Season 01"
        transfer_id = f"copy_{started_hours_ago}_{operation_type}_{int(owned)}"
        run_id = None
        if owned:
            run_id = f"run_{transfer_id}"
            options = {}
            if resumed_hours_ago is not None:
                options['transfer_started_at'] = (
                    now - timedelta(hours=resumed_hours_ago)).isoformat()
            self.store.create({
                'run_id': run_id, 'kind': S.MANUAL, 'source': 'manual',
                'media_type': 'tvshows', 'unit_key': unit_key(dest), 'dest_path': dest,
                'source_path': source, 'operation_type': operation_type,
                'state': S.COMPLETED, 'current_stage': S.FINISH, 'transfer_id': transfer_id,
                'started_at': started.isoformat(), 'finished_at': ended.isoformat(),
                'options': options})
        # The transfers table keeps local time with no zone.
        local = lambda moment: moment.astimezone().replace(tzinfo=None).isoformat()  # noqa: E731
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO transfers (transfer_id, media_type, folder_name, season_name, "
                "source_path, dest_path, operation_type, status, start_time, end_time, "
                "sync_run_id) VALUES (?, 'tvshows', 'Example Show (2020)', 'Season 01', ?, ?, "
                "?, 'completed', ?, ?, ?)",
                (transfer_id, source, dest, operation_type, local(started), local(ended),
                 run_id))
            conn.commit()


class ScannerTests(ScannerTestCase):
    """Sync it: every find goes through the engine."""

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

    def test_a_copy_that_began_before_the_import_does_not_cover_it(self):
        """It listed the folder before the episode landed, though it ended after."""
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=2)]
        self.finished_copy(started_hours_ago=3, ended_hours_ago=1)
        result = self.scan()
        self.assertEqual(result['found'], 1)
        self.assertEqual(result['started'], 1)

    def test_a_copy_from_before_the_engine_counts_from_its_start(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=3)]
        self.finished_copy(started_hours_ago=2, ended_hours_ago=1, owned=False)
        self.assertEqual(self.scan()['found'], 0)

    def test_a_copy_from_before_the_engine_that_began_too_early_does_not(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=2)]
        self.finished_copy(started_hours_ago=3, ended_hours_ago=1, owned=False)
        self.assertEqual(self.scan()['found'], 1)

    def test_a_resumed_copy_counts_from_when_it_listed_the_folder_again(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=2)]
        self.finished_copy(started_hours_ago=3, resumed_hours_ago=1)
        self.assertEqual(self.scan()['found'], 0)

    def test_a_single_file_copy_does_not_cover_the_season(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=2)]
        self.finished_copy(started_hours_ago=1, operation_type='file')
        self.assertEqual(self.scan()['found'], 1)

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

    def test_a_double_episode_file_is_not_a_gap(self):
        """One S01E01E02 file is two of Sonarr's episodes, and both are here."""
        self.library.items = [show(seasons=[
            {'season_number': 1, 'episode_file_count': 10, 'files_here': 9,
             'episodes_here': 10, 'counts_towards_state': True}])]
        self.assertEqual(self.scan()['found'], 0)

    def test_a_short_season_is_copied_between_its_real_folders(self):
        self.arr.folders[(219, 1)] = 'Season 1'
        self.library.items = [show(seasons=[
            {'season_number': 1, 'episode_file_count': 10, 'files_here': 8,
             'episodes_here': 8, 'folder_here': 'Season 1', 'counts_towards_state': True}])]
        self.assertEqual(self.scan()['started'], 1)
        run = self.scanner_runs()[0]
        self.assertTrue(run['source_path'].endswith('/Example Show (2020)/Season 1'))
        self.assertTrue(run['dest_path'].endswith('/Example Show (2020)/Season 1'))

    def test_a_season_folder_here_keeps_its_own_name(self):
        """Sonarr's folder is "Season 01", this disk's is "Season 1": no second folder."""
        self.arr.folders[(219, 1)] = 'Season 01'
        self.library.items = [show(seasons=[
            {'season_number': 1, 'episode_file_count': 10, 'files_here': 10,
             'episodes_here': 10, 'folder_here': 'Season 1', 'counts_towards_state': True}])]
        self.arr.records = [imported()]
        self.scan()
        run = self.scanner_runs()[0]
        self.assertTrue(run['source_path'].endswith('/Example Show (2020)/Season 01'))
        self.assertTrue(run['dest_path'].endswith('/Example Show (2020)/Season 1'))

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


class AlertOnlyTests(ScannerTestCase):
    """Alert only: say what nothing has synced, and copy nothing."""

    def setUp(self):
        super().setUp()
        self.arr.mode = 'alert'

    def missed(self):
        return self.open_alerts('missed_sync')

    def scan_announcing(self):
        with patch('services.connectors.notify') as notify:
            result = self.scan()
        return result, [c.args[0] for c in notify.call_args_list
                        if c.args[0].key == 'scanner.missed']

    def test_alert_only_is_the_default(self):
        from services.connectors.adapters.sonarr import SonarrConnector
        self.assertEqual(SonarrConnector(config={}).auto_scanner_mode(), 'alert')
        self.assertEqual(SonarrConnector(config={'auto_scanner_mode': 'sync'})
                         .auto_scanner_mode(), 'sync')
        self.assertEqual(SonarrConnector(config={'auto_scanner_mode': 'nonsense'})
                         .auto_scanner_mode(), 'alert')
        self.arr.mode = ''
        self.assertEqual(AutoScanner.mode(self.arr), 'alert')

    def test_an_import_nothing_synced_is_alerted_not_copied(self):
        self.library.items = [show()]
        self.arr.records = [imported()]
        result, messages = self.scan_announcing()
        self.assertTrue(result['ok'])
        self.assertEqual(result['alerted'], 1)
        self.assertEqual(self.scanner_runs(), [], 'nothing is copied')
        self.assertEqual(self.store.list(limit=10), [])
        alerts = self.missed()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['title'], 'Missed auto-sync: Example Show — Season 01')
        self.assertIn('Explore', alerts[0]['message'])
        self.assertEqual(alerts[0]['actions'], ['dismiss'])
        self.assertEqual(alerts[0]['data']['explore'],
                         {'media_type': 'tvshows', 'series': 'Example Show (2020)',
                          'season': 'Season 01'})
        self.assertEqual(len(messages), 1, 'one Discord message per scan')
        self.assertIn('Example Show — Season 01', messages[0].fields[0].value)

    def test_the_same_import_found_again_stays_one_quiet_alert(self):
        self.library.items = [show()]
        self.arr.records = [imported()]
        self.scan()
        result, messages = self.scan_announcing()
        self.assertEqual(result['already_alerted'], 1)
        self.assertEqual(messages, [])
        self.assertEqual(self.missed()[0]['occurrences'], 1)

    def test_a_newer_import_updates_the_open_alert_without_a_message(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=3)]
        self.scan()
        self.arr.records = [imported(hours_ago=3), imported(hours_ago=1)]
        result, messages = self.scan_announcing()
        self.assertEqual(result['updated'], 1)
        self.assertEqual(messages, [])
        self.assertEqual(self.missed()[0]['occurrences'], 2)

    def test_a_dismissed_alert_comes_back_only_on_a_new_import(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=2)]
        self.scan()
        self.alerts.act(self.missed()[0]['alert_id'], 'dismiss')
        result = self.scan()
        self.assertEqual(result['dismissed'], 1)
        self.assertEqual(self.missed(), [])

        self.arr.records = [imported(hours_ago=2), imported(hours_ago=-0.01)]
        result, messages = self.scan_announcing()
        self.assertEqual(result['alerted'], 1)
        self.assertEqual(len(self.missed()), 1)
        self.assertEqual(len(messages), 1)

    def test_an_import_between_the_scan_and_the_dismiss_comes_back(self):
        """The person dismissed the import they were shown, not one that landed since."""
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=3)]
        self.scan()
        self.arr.records = [imported(hours_ago=3), imported(hours_ago=1)]
        self.alerts.act(self.missed()[0]['alert_id'], 'dismiss')
        self.assertEqual(self.scan()['alerted'], 1)
        self.assertEqual(self.scan()['already_alerted'], 1)

    def test_a_short_season_dismissed_comes_back_when_the_service_has_more(self):
        def short(theirs):
            return [show(seasons=[{'season_number': 1, 'episode_file_count': theirs,
                                   'files_here': 8, 'counts_towards_state': True}])]
        self.library.items = short(10)
        self.assertEqual(self.scan()['alerted'], 1)
        self.alerts.act(self.missed()[0]['alert_id'], 'dismiss')
        self.assertEqual(self.scan()['dismissed'], 1)
        self.library.items = short(11)
        self.assertEqual(self.scan()['alerted'], 1)

    def test_a_sync_cancelled_after_a_scan_saw_it_is_alerted_later(self):
        """Skipped: the scan that saw it waiting must not be the last to look."""
        self.series_webhook('e1', 1)
        run = self.sonarr('e1')
        self.library.items = [show()]
        self.arr.records = [imported()]
        result = self.scan()
        self.assertEqual(result['already_on_its_way'], 1)
        self.assertEqual(self.missed(), [])

        self.engine.cancel_run(run.run_id)
        result = self.scan()
        self.assertEqual(result['alerted'], 1)
        self.assertEqual(len(self.missed()), 1)

    def test_it_reads_a_week_back_every_scan(self):
        self.library.items = [show()]
        self.scan()
        self.scan()
        since = datetime.fromisoformat(self.arr.since)
        self.assertLess(since, datetime.now(timezone.utc) - timedelta(days=6, hours=23))

    def test_look_back_is_the_services_setting(self):
        self.arr.auto_scanner_lookback_days = lambda: 3
        self.library.items = [show()]
        self.scan()
        ago = datetime.now(timezone.utc) - datetime.fromisoformat(self.arr.since)
        self.assertTrue(timedelta(days=2, hours=23) < ago < timedelta(days=3, hours=1), ago)

    def test_look_back_is_kept_between_1_and_30_days(self):
        from services.connectors.adapters.radarr import RadarrConnector
        days = lambda value: RadarrConnector(  # noqa: E731
            config={'auto_scanner_lookback_days': value}).auto_scanner_lookback_days()
        self.assertEqual(days(''), 7)
        self.assertEqual(days('14'), 14)
        self.assertEqual(days('0'), 1)
        self.assertEqual(days('90'), 30)
        self.assertEqual(days('soon'), 7)

    def test_a_folder_with_another_open_alert_is_not_alerted_twice(self):
        dest = os.path.join(self.config.get('TVSHOW_DEST_PATH'), 'Example Show (2020)',
                            'Season 01')
        self.alerts.raise_alert('sync_refused', 'Sync stopped by the safety check: x',
                                unit_key=unit_key(dest), dedupe_key='refused:x')
        self.library.items = [show()]
        self.arr.records = [imported()]
        self.assertEqual(self.scan()['already_alerted'], 1)
        self.assertEqual(self.missed(), [])

    def test_the_alert_closes_itself_once_the_folder_is_synced(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=2)]
        self.scan()
        self.assertEqual(len(self.missed()), 1)
        self.finished_copy(started_hours_ago=1)
        result = self.scan()
        self.assertEqual(result['found'], 0)
        self.assertEqual(self.missed(), [])
        closed = self.alerts.store.list(states=['done'], kinds=['missed_sync'])
        self.assertEqual(closed[0]['resolved_action'], 'auto')

    def test_switching_to_sync_does_not_sync_what_was_alerted(self):
        self.library.items = [show()]
        self.arr.records = [imported(hours_ago=2)]
        self.scan()
        self.arr.mode = 'sync'
        self.arr.records = []
        self.assertEqual(self.scan()['started'], 0)
        self.assertGreater(datetime.fromisoformat(self.arr.since),
                           datetime.now(timezone.utc) - timedelta(minutes=5))


if __name__ == '__main__':
    unittest.main()
