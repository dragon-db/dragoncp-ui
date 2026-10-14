#!/usr/bin/env python3
"""
A copy that fails on the fast route runs once more over SSH.

The fast route can break in ways nobody sees coming — the 2026 rsync security
fix made the remote server fail every file of an Explore list, and the first
anyone knew was a failed copy. A broken fast route must cost speed, never a
copy. These run real rsync stand-ins (`sh -c`) so the monitor sees real exit
codes and real output.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.alert_service import AlertService
from services.transfer_service import (
    DAEMON, SSH, SSH_FALLBACK, TransferRoute, TransferService, route_failed)


class FakeConfig:
    def get(self, key, default=''):
        return {'REMOTE_USER': 'someone', 'REMOTE_IP': 'remote.example',
                'BACKUP_PATH': '/tmp/backups'}.get(key, default)


class FakeModel:
    """Just enough of the transfers table to watch what the monitor writes."""

    def __init__(self, status='running'):
        self.row = {'transfer_id': 't1', 'status': status, 'logs': []}
        self.updates = []

    def get(self, transfer_id):
        return dict(self.row, logs=list(self.row['logs']))

    def update(self, transfer_id, fields):
        self.updates.append(dict(fields))
        self.row.update(fields)

    def add_log(self, transfer_id, line, stats=None, replace_last=False):
        self.row['logs'].append(line)


def sh(script):
    return ['sh', '-c', script]


def start(script):
    return subprocess.Popen(sh(script), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True, bufsize=1)


class MonitorFallbackTests(unittest.TestCase):
    def setUp(self):
        self.model = FakeModel()
        self.service = TransferService(FakeConfig(), MagicMock(), self.model, None, None)
        self.told = []
        self.service.on_route_fallback = lambda *args: self.told.append(args)

    def monitor(self, first_script, fallback_script=None):
        if fallback_script is not None:
            self.service._set_ssh_fallback('t1', sh(fallback_script))
        return self.service._monitor_transfer('t1', start(first_script))

    def test_a_failed_fast_copy_finishes_over_ssh(self):
        status = self.monitor(
            'echo "file has vanished: \\"/Example Show/Season 01/x.mkv\\" (in tvshows)"; exit 24',
            'echo copied over ssh; exit 0')
        self.assertEqual(status, 'completed')
        self.assertEqual(self.model.row['status'], 'completed')
        self.assertEqual(self.model.row['transport'], SSH_FALLBACK)
        self.assertIn('copied over ssh', self.model.row['logs'])
        self.assertTrue(any('Running this again over SSH' in line
                            for line in self.model.row['logs']))
        self.assertEqual(len(self.told), 1)
        transfer_id, code, reason = self.told[0]
        self.assertEqual((transfer_id, code), ('t1', 24))
        self.assertTrue(reason.startswith('file has vanished'))

    def test_it_falls_back_only_once(self):
        status = self.monitor('exit 10', 'echo still broken; exit 23')
        self.assertEqual(status, 'failed')
        self.assertEqual(self.model.row['status'], 'failed')
        self.assertIn('exit code: 23', self.model.row['progress'])
        self.assertEqual(len(self.told), 1)

    def test_a_copy_already_on_ssh_is_not_retried(self):
        status = self.monitor('exit 23')  # no fallback registered: it was SSH
        self.assertEqual(status, 'failed')
        self.assertEqual(self.told, [])
        self.assertNotIn('transport', self.model.row)

    def test_a_copy_stopped_from_outside_is_not_retried(self):
        # 20 is rsync saying it was signalled: somebody meant it to stop.
        status = self.monitor('exit 20', 'echo should not run; exit 0')
        self.assertEqual(status, 'failed')
        self.assertNotIn('should not run', self.model.row['logs'])
        self.assertEqual(self.told, [])

    def test_a_cancelled_copy_is_not_retried(self):
        self.service._mark_intentional_stop('t1', 'cancelled')
        status = self.monitor('exit 20', 'echo should not run; exit 0')
        self.assertEqual(status, 'cancelled')
        self.assertNotIn('should not run', self.model.row['logs'])

    def test_a_copy_cancelled_while_rsync_was_exiting_is_not_retried(self):
        # The cancel lands just after the monitor looked for one: it finds no
        # rsync to stop, marks the row cancelled, and leaves its intent behind.
        real_take = self.service._take_intentional_stop
        looked = []

        def take(transfer_id):
            looked.append(transfer_id)
            if len(looked) == 1:
                self.model.row['status'] = 'cancelled'
                self.service._mark_intentional_stop(transfer_id, 'cancelled')
                return None
            return real_take(transfer_id)
        self.service._take_intentional_stop = take

        status = self.monitor('exit 24', 'echo should not run; exit 0')
        self.assertEqual(status, 'cancelled')
        self.assertEqual(self.model.row['status'], 'cancelled')
        self.assertNotIn('should not run', self.model.row['logs'])
        self.assertEqual(self.told, [])

    def test_a_cancel_that_lands_during_the_switch_stops_the_ssh_copy(self):
        real_update = self.model.update

        def update(transfer_id, fields):
            real_update(transfer_id, fields)
            if fields.get('transport') == SSH_FALLBACK:
                # The cancel arrives just as the SSH rsync starts.
                self.service._mark_intentional_stop('t1', 'cancelled')
        self.model.update = update

        status = self.monitor('exit 12', 'sleep 30; echo should not finish')
        self.assertEqual(status, 'cancelled')
        self.assertNotIn('should not finish', self.model.row['logs'])

    def test_a_successful_fast_copy_leaves_no_fallback_behind(self):
        status = self.monitor('exit 0', 'echo should not run; exit 0')
        self.assertEqual(status, 'completed')
        self.assertIsNone(self.service._take_ssh_fallback('t1'))
        self.assertNotIn('transport', self.model.row)


class RouteFailedTests(unittest.TestCase):
    def test_which_exit_codes_count_as_the_route_failing(self):
        for code in (1, 5, 10, 12, 23, 24, 30, 35):
            self.assertTrue(route_failed(code), code)
        for code in (0, 19, 20, -9, -15):
            self.assertFalse(route_failed(code), code)


class StartRegistersTheFallbackTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(TransferService, '_build_ssh_host_key_options',
                               return_value=['-o', 'StrictHostKeyChecking=accept-new'])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def service_with(self, route):
        model = MagicMock()
        model.get.return_value = {
            'transfer_id': 't1', 'operation_type': 'folder', 'is_simulation': 0}
        service = TransferService(FakeConfig(), MagicMock(), model, None, None)
        service.resolve_route = lambda *args, **kwargs: route
        return service

    def start(self, service):
        process = MagicMock()
        process.poll.return_value = None
        process.pid = 4242
        with patch('services.transfer_service.subprocess.Popen', return_value=process) as popen, \
                patch('services.transfer_service.threading.Thread'), \
                patch('services.transfer_service.test_mode_enabled', return_value=False):
            started = service.start_rsync_process(
                't1', '/srv/media/tvshows/Example Show/Season 01',
                os.path.join(self.tmp.name, 'Example Show', 'Season 01'), 'folder',
                os.path.join(self.tmp.name, 'staging', 't1'))
        self.assertTrue(started)
        return popen.call_args[0][0]

    def test_a_fast_copy_keeps_the_same_command_over_ssh_ready(self):
        service = self.service_with(TransferRoute(
            DAEMON, 'dragoncp@remote.example::tvshows/Example Show/Season 01/',
            ['--port=52314', '--password-file', '/tmp/pw']))
        command = self.start(service)
        fallback = service._take_ssh_fallback('t1')
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback[-2],
                         'someone@remote.example:/srv/media/tvshows/Example Show/Season 01/')
        self.assertEqual(fallback[-1], command[-1])
        # Same flags apart from the route's own.
        route_bits = {'--port=52314', '--password-file', '/tmp/pw', '-e'}
        self.assertEqual(
            [a for a in command[:-2] if a not in route_bits],
            [a for a in fallback[:-2] if a not in route_bits and not a.startswith('ssh ')])

    def test_a_copy_that_starts_on_ssh_has_nothing_to_fall_back_to(self):
        service = self.service_with(TransferRoute(
            SSH, 'someone@remote.example:/srv/media/tvshows/Example Show/Season 01/',
            ['-e', 'ssh']))
        self.start(service)
        self.assertIsNone(service._take_ssh_fallback('t1'))


class DryRunFallbackTests(unittest.TestCase):
    """A safety check that fails on the fast route is asked again over SSH."""

    def setUp(self):
        patcher = patch.object(TransferService, '_build_ssh_host_key_options',
                               return_value=['-o', 'StrictHostKeyChecking=accept-new'])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = TransferService(FakeConfig(), MagicMock(), MagicMock(), None, None)
        self.fast = TransferRoute(DAEMON, 'dragoncp@remote.example::movies/A Film/',
                                  ['--port=52314'])

    def run_with(self, results, route=None, ok_codes=(0, 24)):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            outcome = results[len(calls) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return subprocess.CompletedProcess(command, outcome, 'out', '')

        def build(chosen):
            return ['rsync', '--dry-run', chosen.source]

        with patch('services.transfer_service.subprocess.run', side_effect=fake_run):
            result = self.service._dry_run_with_fallback(
                'dry run', build, route or self.fast, '/srv/media/movies/A Film', ok_codes)
        return result, calls

    def test_a_fast_route_failure_is_asked_again_over_ssh(self):
        result, calls = self.run_with([10, 0])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][-1], 'someone@remote.example:/srv/media/movies/A Film/')

    def test_a_fast_route_that_hangs_is_asked_again_over_ssh(self):
        result, calls = self.run_with([subprocess.TimeoutExpired('rsync', 300), 0])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)

    def test_an_accepted_answer_is_not_asked_again(self):
        result, calls = self.run_with([24])
        self.assertEqual(result.returncode, 24)
        self.assertEqual(len(calls), 1)

    def test_an_ssh_failure_stands(self):
        ssh = TransferRoute(SSH, 'someone@remote.example:/srv/media/movies/A Film/', ['-e', 'ssh'])
        result, calls = self.run_with([10], route=ssh)
        self.assertEqual(result.returncode, 10)
        self.assertEqual(len(calls), 1)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_with([subprocess.TimeoutExpired('rsync', 300)], route=ssh)


class AlertTests(unittest.TestCase):
    def test_every_fallback_lands_on_one_alert(self):
        store = MagicMock()
        store.find_open.return_value = None
        store.closed_by_a_person_since.return_value = False
        alerts = AlertService(store)
        with patch.object(AlertService, '_announce') as announce:
            alerts.fast_route_failed(
                {'transfer_id': 't1', 'folder_name': 'Example Show', 'season_name': 'Season 01',
                 'sync_run_id': 'run1'}, 24, 'file has vanished: x')
            kind, severity, title, message = store.create.call_args[0][:4]
            self.assertEqual(kind, 'fast_route_failed')
            self.assertIn('Example Show — Season 01', message)
            self.assertIn('file has vanished: x', message)
            self.assertEqual(store.create.call_args[1]['dedupe_key'], 'fast_route_failed')
            announce.assert_called_once()

            # The next copy that falls back bumps it instead of announcing again.
            store.find_open.return_value = {'alert_id': 'a1'}
            alerts.fast_route_failed({'transfer_id': 't2'}, 10, '')
            store.bump.assert_called_once()
            announce.assert_called_once()


if __name__ == '__main__':
    unittest.main()
