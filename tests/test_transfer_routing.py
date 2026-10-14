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
import shutil
import socket
import subprocess
import sys
import tempfile
import time
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
            # Everything except the route's own contribution, the addresses and
            # the list file — the fast route reads its own copy of the list.
            drop = {'-e', 'ssh -o StrictHostKeyChecking=accept-new', '--port=52314',
                    '--password-file', '/tmp/pw'}
            return [a for a in command if a not in drop and '::' not in a
                    and ':/srv' not in a and not a.startswith(self.tmp.name)]

        self.assertEqual(flags(ssh), flags(daemon))

    def test_the_fast_route_reads_the_list_from_the_library_root(self):
        # The transfer server fails every file of a list read from a folder
        # inside the library (rsync's 2026 no-chroot hardening), so the fast
        # route asks from the root and marks where the folder starts.
        command = self.explore_command(TransferRoute(
            DAEMON, 'dragoncp@remote.example::tvshows/Example Show/', ['--port=52314']))
        self.assertEqual(command[-2], 'dragoncp@remote.example::tvshows/')
        listed = command[command.index('--files-from') + 1]
        self.assertNotEqual(listed, self.files_from)
        with open(listed) as handle:
            self.assertEqual(handle.read(),
                             'Example Show/./Season 01/Example Show - S01E01.mkv\n')
        # The approved list itself is left exactly as the plan wrote it.
        with open(self.files_from) as handle:
            self.assertEqual(handle.read(), 'Season 01/Example Show - S01E01.mkv\n')

    def test_a_list_already_at_the_library_root_is_used_as_written(self):
        command = build_service().build_explore_rsync_command(
            '/srv/media/movies', '/local/movies', '/backups/staging',
            self.files_from, 'sync',
            TransferRoute(DAEMON, 'dragoncp@remote.example::movies/', ['--port=52314']))
        self.assertEqual(command[command.index('--files-from') + 1], self.files_from)

    def test_the_ssh_route_reads_the_list_as_written(self):
        command = self.explore_command(TransferRoute(
            SSH, 'someone@remote.example:/srv/media/tvshows/Example Show/', ['-e', 'ssh']))
        self.assertEqual(command[command.index('--files-from') + 1], self.files_from)
        self.assertEqual(command[-2], 'someone@remote.example:/srv/media/tvshows/Example Show/')

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


class ExploreAgainstARealServerTests(unittest.TestCase):
    """
    An Explore list pulled through a real rsync server, compared with the same
    list pulled from a plain path the way SSH reads it.

    The server is this machine's rsync unless DRAGONCP_TEST_RSYNC_SERVER names
    another binary. Point it at the remote server's own build (an rsync with
    the 2026 no-chroot hardening, e.g. Debian 13's) to prove the fix against
    the server that broke — that run also checks the old command still fails
    there, so the test keeps describing a real problem.
    """

    SHOW = 'Example Show'
    NAMES = ('Season 01/Example Show - S01E01.mkv', 'Season 01/Example Show - S01E02.mkv')

    @classmethod
    def setUpClass(cls):
        cls.server = os.environ.get('DRAGONCP_TEST_RSYNC_SERVER') or shutil.which('rsync')
        if not cls.server or shutil.which('rsync') is None:
            raise unittest.SkipTest('rsync is not installed')

    def setUp(self):
        patcher = patch.object(
            TransferService, '_build_ssh_host_key_options',
            return_value=['-o', 'StrictHostKeyChecking=accept-new'])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.library = os.path.join(self.tmp, 'library')
        for name in self.NAMES:
            path = os.path.join(self.library, self.SHOW, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as handle:
                handle.write(os.urandom(4096))
        self.files_from = os.path.join(self.tmp, 'files.txt')
        with open(self.files_from, 'w') as handle:
            handle.write(''.join(f"{name}\n" for name in self.NAMES))
        self.port = self._start_server()
        self.password = os.path.join(self.tmp, 'client-password')
        with open(self.password, 'w') as handle:
            handle.write('correct-horse\n')
        os.chmod(self.password, 0o600)

    def _start_server(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        secrets_file = os.path.join(self.tmp, 'secrets')
        with open(secrets_file, 'w') as handle:
            handle.write('dragoncp:correct-horse\n')
        os.chmod(secrets_file, 0o600)
        conf = os.path.join(self.tmp, 'rsyncd.conf')
        # The shape the installer generates: no chroot, read only, unlisted.
        with open(conf, 'w') as handle:
            handle.write(
                f"pid file = {self.tmp}/pid\nlock file = {self.tmp}/lock\n"
                f"log file = {self.tmp}/log\nuse chroot = no\nreverse lookup = no\n\n"
                f"[tvshows]\n    path = {self.library}\n    read only = yes\n"
                f"    list = no\n    auth users = dragoncp\n"
                f"    secrets file = {secrets_file}\n")
        proc = subprocess.Popen(
            [self.server, '--daemon', '--no-detach', f'--config={conf}', f'--port={port}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def stop():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.addCleanup(stop)
        for _ in range(50):
            probe = socket.socket()
            probe.settimeout(0.2)
            try:
                probe.connect(('127.0.0.1', port))
                break
            except OSError:
                time.sleep(0.1)
            finally:
                probe.close()
        else:
            self.skipTest('the test rsync server would not start')
        return port

    def _daemon_route(self):
        return TransferRoute(
            DAEMON, f'dragoncp@127.0.0.1::tvshows/{self.SHOW}/',
            [f'--port={self.port}', '--password-file', self.password])

    def _path_route(self):
        # What SSH reads, without SSH: the same folder as a plain path.
        return TransferRoute(SSH, os.path.join(self.library, self.SHOW) + '/', [])

    def _run(self, route, dry_run=False):
        dest = os.path.join(self.tmp, f"dest-{route.kind}-{int(dry_run)}")
        os.makedirs(dest)
        command = build_service().build_explore_rsync_command(
            os.path.join(self.library, self.SHOW), dest,
            os.path.join(self.tmp, f"backup-{route.kind}"), self.files_from, 'sync', route)
        if dry_run:
            # The same transformation run_explore_dry_run applies.
            command = [a for a in command if a not in ('--progress', '--info=progress2')]
            command[1:1] = ['--dry-run', '--out-format=%i|%l|%n']
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, timeout=60)
        return result, dest

    @staticmethod
    def _landed(dest):
        return sorted(os.path.relpath(os.path.join(root, name), dest)
                      for root, _, names in os.walk(dest) for name in names)

    def test_the_fast_route_lands_the_files_where_ssh_does(self):
        fast, fast_dest = self._run(self._daemon_route())
        self.assertEqual(fast.returncode, 0, fast.stdout)
        plain, plain_dest = self._run(self._path_route())
        self.assertEqual(plain.returncode, 0, plain.stdout)
        self.assertEqual(self._landed(fast_dest), sorted(self.NAMES))
        self.assertEqual(self._landed(fast_dest), self._landed(plain_dest))

    def test_the_fast_route_dry_run_names_files_the_way_ssh_does(self):
        # Explore's report is built from these lines; a different name for the
        # same file would read as a different file.
        def itemised(output):
            return sorted(line for line in output.splitlines() if '|' in line)
        fast, _ = self._run(self._daemon_route(), dry_run=True)
        plain, _ = self._run(self._path_route(), dry_run=True)
        self.assertEqual(fast.returncode, 0, fast.stdout)
        self.assertEqual(itemised(fast.stdout), itemised(plain.stdout))
        self.assertTrue(itemised(fast.stdout))

    def test_on_a_hardened_server_the_old_command_still_fails(self):
        if not os.environ.get('DRAGONCP_TEST_RSYNC_SERVER'):
            self.skipTest('needs DRAGONCP_TEST_RSYNC_SERVER pointing at a hardened rsync')
        route = self._daemon_route()
        dest = os.path.join(self.tmp, 'dest-old')
        os.makedirs(dest)
        old = ['rsync', '-av', '--files-from', self.files_from, *route.args,
               route.source, f"{dest}/"]
        result = subprocess.run(old, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, timeout=60)
        self.assertEqual(result.returncode, 24, result.stdout)
        self.assertIn('file has vanished', result.stdout)
        self.assertEqual(self._landed(dest), [])


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
