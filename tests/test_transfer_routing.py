#!/usr/bin/env python3
"""
Which route a transfer takes, and what that changes about the command.

The claim this whole feature rests on is that the fast route is *a change of
address, not a change of transport*: same rsync, same flags, same output, same
safety. These tests are what stop that claim quietly becoming false — if a
future edit adds a flag to one route and not the other, the comparison test
below fails.

The other half is the fallback. Every reason the fast route might be
unavailable has to end with a working SSH transfer rather than a failed one,
because the alternative is a library that silently stops updating.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.transfer_service import DAEMON, SSH, TransferRoute, TransferService


class FakeConfig:
    def __init__(self, values=None):
        self.values = {
            'REMOTE_USER': 'someone',
            'REMOTE_IP': 'remote.example',
            'SSH_KEY_PATH': '',
            'SSH_HOST_KEY_CHECKING': 'accept-new',
            'BACKUP_PATH': '/tmp/backups',
        }
        self.values.update(values or {})

    def get(self, key, default=''):
        return self.values.get(key, default)


class FakeDaemon:
    """Stands in for the transfer server: either it offers a route or it does not."""

    def __init__(self, route=None, explode=False):
        self.route = route
        self.explode = explode
        self.asked = []

    def route_for(self, source_path, trailing_slash=True):
        self.asked.append((source_path, trailing_slash))
        if self.explode:
            raise RuntimeError('the transfer server is having a bad day')
        return self.route


def build_service(daemon=None, config=None):
    return TransferService(
        FakeConfig(config), MagicMock(), MagicMock(), None, None, remote_daemon=daemon)


class RouteChoiceTests(unittest.TestCase):
    def setUp(self):
        # The host-key options touch the filesystem; keep the tests off it.
        patcher = patch.object(
            TransferService, '_build_ssh_host_key_options',
            return_value=['-o', 'StrictHostKeyChecking=accept-new'])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_with_no_transfer_server_at_all_it_uses_ssh(self):
        route = build_service().resolve_route('/srv/media/movies/A Film')
        self.assertEqual(route.kind, SSH)
        self.assertEqual(route.source, 'someone@remote.example:/srv/media/movies/A Film/')
        self.assertIn('-e', route.args)

    def test_when_the_server_offers_a_route_it_is_taken(self):
        daemon = FakeDaemon(('dragoncp@remote.example::movies/A Film/',
                             ['--port=52314', '--password-file', '/tmp/pw']))
        route = build_service(daemon).resolve_route('/srv/media/movies/A Film')
        self.assertEqual(route.kind, DAEMON)
        self.assertEqual(route.source, 'dragoncp@remote.example::movies/A Film/')
        self.assertIn('--port=52314', route.args)
        # The SSH transport option must be gone, not merely unused.
        self.assertNotIn('-e', route.args)

    def test_when_the_server_declines_it_falls_back_to_ssh(self):
        route = build_service(FakeDaemon(route=None)).resolve_route('/srv/media/movies/A Film')
        self.assertEqual(route.kind, SSH)

    def test_when_asking_the_server_raises_it_still_falls_back(self):
        # A transfer must never fail because the check failed. This is the
        # difference between "slower tonight" and "the library stopped updating".
        route = build_service(FakeDaemon(explode=True)).resolve_route('/srv/media/movies/A Film')
        self.assertEqual(route.kind, SSH)

    def test_a_simulation_never_asks_the_remote_host(self):
        daemon = FakeDaemon(('dragoncp@remote.example::movies/', []))
        route = build_service(daemon).resolve_route('/tmp/fixtures', allow_daemon=False)
        self.assertEqual(route.kind, SSH)
        self.assertEqual(daemon.asked, [])

    def test_the_trailing_slash_is_passed_through_to_the_server(self):
        daemon = FakeDaemon(route=None)
        service = build_service(daemon)
        service.resolve_route('/srv/media/movies/A Film.mkv', trailing_slash=False)
        self.assertEqual(daemon.asked[-1][1], False)
        # ...and the SSH fallback honours it too.
        route = service.resolve_route('/srv/media/movies/A Film.mkv', trailing_slash=False)
        self.assertTrue(route.source.endswith('A Film.mkv'))


class CommandShapeTests(unittest.TestCase):
    """
    The two routes must differ in the address and nothing else.
    """

    def setUp(self):
        patcher = patch.object(
            TransferService, '_build_ssh_host_key_options',
            return_value=['-o', 'StrictHostKeyChecking=accept-new'])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.files_from = os.path.join(self.tmp.name, 'files.txt')
        with open(self.files_from, 'w') as handle:
            handle.write('Season 01/Example Show - S01E01.mkv\n')

    def explore_command(self, route):
        return build_service().build_explore_rsync_command(
            '/srv/media/tvshows/Example Show', '/local/tv/Example Show',
            '/backups/staging', self.files_from, 'sync', route)

    def test_an_explore_plan_is_the_same_command_on_both_routes(self):
        ssh = self.explore_command(TransferRoute(
            SSH, 'someone@remote.example:/srv/media/tvshows/Example Show/',
            ['-e', 'ssh -o StrictHostKeyChecking=accept-new']))
        daemon = self.explore_command(TransferRoute(
            DAEMON, 'dragoncp@remote.example::tvshows/Example Show/',
            ['--port=52314', '--password-file', '/tmp/pw']))

        def flags(command):
            # Everything except the route's own contribution and the addresses.
            drop = {'-e', 'ssh -o StrictHostKeyChecking=accept-new', '--port=52314',
                    '--password-file', '/tmp/pw'}
            return [a for a in command if a not in drop and '::' not in a and ':/srv' not in a]

        self.assertEqual(flags(ssh), flags(daemon))

    def test_the_safety_flags_survive_on_the_fast_route(self):
        command = self.explore_command(TransferRoute(
            DAEMON, 'dragoncp@remote.example::tvshows/Example Show/', ['--port=52314']))
        # The plan owns removals and the backup of anything it displaces. Losing
        # either of these on one route only would be silent and destructive.
        self.assertIn('--backup', command)
        self.assertIn('--backup-dir', command)
        self.assertIn('--files-from', command)
        self.assertNotIn('--delete', command)
        self.assertNotIn('--size-only', command)
        self.assertNotIn('--update', command)

    def test_download_mode_still_refuses_to_overwrite_on_the_fast_route(self):
        command = build_service().build_explore_rsync_command(
            '/srv/media/movies', '/local/movies', '/backups/staging',
            self.files_from, 'download',
            TransferRoute(DAEMON, 'dragoncp@remote.example::movies/', ['--port=52314']))
        self.assertIn('--ignore-existing', command)

    def test_the_address_is_the_last_source_argument_on_both_routes(self):
        for route in (
            TransferRoute(SSH, 'someone@remote.example:/srv/media/movies/', ['-e', 'ssh']),
            TransferRoute(DAEMON, 'dragoncp@remote.example::movies/', ['--port=52314']),
        ):
            command = build_service().build_explore_rsync_command(
                '/srv/media/movies', '/local/movies', '/backups/staging',
                self.files_from, 'sync', route)
            self.assertEqual(command[-2], route.source)
            self.assertEqual(command[-1], '/local/movies/')


class RouteRecordingTests(unittest.TestCase):
    def test_the_route_is_written_onto_the_transfer(self):
        model = MagicMock()
        service = TransferService(FakeConfig(), MagicMock(), model, None, None)
        service._record_route('t1', TransferRoute(DAEMON, 'x', []))
        model.update.assert_called_with('t1', {'transport': 'daemon'})

    def test_a_simulation_records_no_route(self):
        model = MagicMock()
        service = TransferService(FakeConfig(), MagicMock(), model, None, None)
        service._record_route('t1', None)
        model.update.assert_called_with('t1', {'transport': None})

    def test_a_failure_to_record_does_not_stop_the_transfer(self):
        model = MagicMock()
        model.update.side_effect = RuntimeError('database is busy')
        service = TransferService(FakeConfig(), MagicMock(), model, None, None)
        service._record_route('t1', TransferRoute(SSH, 'x', []))  # must not raise

if __name__ == '__main__':
    unittest.main()
