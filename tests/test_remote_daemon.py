#!/usr/bin/env python3
"""
The transfer server on the remote host.

Three things are worth pinning here, and they are the three that would hurt:

  1. Which local paths map to which published library. Getting this wrong sends
     a transfer to the wrong place or, worse, publishes a route to a directory
     that is not a library at all.
  2. What the generated configuration says. The access rule is the main thing
     protecting the media, and it is a generated file — so the generator is
     where it has to be checked.
  3. That the allowed address never leaves this machine through the API. The
     operator treats it as private and it is only useful to us.
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
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.remote_daemon import layout, probe, render
from services.remote_daemon.service import RemoteDaemonError, RemoteDaemonService


class FakeSettings:
    def __init__(self, values=None):
        self.values = {
            'MOVIE_PATH': '/srv/media/movies',
            'TVSHOW_PATH': '/srv/media/tv',
            'ANIME_PATH': '/srv/media/anime',
            'RSYNC_DAEMON_PORT': '52314',
            'FAST_TRANSPORT_ACCESS_MODE': 'restricted',
            'FAST_TRANSPORT_LIFECYCLE': 'on_demand',
            'FAST_TRANSPORT_ENABLED': 'false',
        }
        self.values.update(values or {})

    def get(self, key, default=''):
        return self.values.get(key, default)

    def get_bool(self, key, default=False):
        return str(self.values.get(key, default)).strip().lower() in ('1', 'true', 'yes', 'on')


class FakeConfig:
    def __init__(self, values=None):
        self.values = {
            'REMOTE_IP': 'remote.example',
            'REMOTE_USER': 'someone',
            'RSYNC_DAEMON_ALLOWED_IP': '198.51.100.7',
        }
        self.values.update(values or {})

    def get(self, key, default=''):
        return self.values.get(key, default)


# ---------------------------------------------------------------------------
# Mapping a path to a published library
# ---------------------------------------------------------------------------

class SourceMappingTests(unittest.TestCase):
    def setUp(self):
        self.settings = FakeSettings()

    def test_a_path_inside_a_library_maps_to_it(self):
        found = layout.source_for(self.settings, '/srv/media/tv/Example Show/Season 01')
        self.assertEqual(found, ('tvshows', 'Example Show/Season 01'))

    def test_the_library_root_itself_maps_with_an_empty_remainder(self):
        self.assertEqual(layout.source_for(self.settings, '/srv/media/movies'),
                         ('movies', ''))

    def test_a_path_outside_every_library_is_refused(self):
        self.assertIsNone(layout.source_for(self.settings, '/srv/other/thing'))
        self.assertIsNone(layout.source_for(self.settings, '/etc/passwd'))
        self.assertIsNone(layout.source_for(self.settings, ''))

    def test_a_sibling_directory_sharing_a_prefix_is_not_inside(self):
        # /srv/media/tv-archive starts with /srv/media/tv as a STRING but is a
        # different directory. A prefix test would publish a route into it.
        self.assertIsNone(
            layout.source_for(self.settings, '/srv/media/tv-archive/Example Show'))

    def test_a_library_with_no_directory_configured_is_not_published(self):
        settings = FakeSettings({'ANIME_PATH': ''})
        names = [name for name, _ in layout.module_roots(settings)]
        self.assertEqual(names, ['movies', 'tvshows'])
        # And nothing maps into it, rather than mapping to the filesystem root.
        self.assertIsNone(layout.source_for(settings, '/anything'))

    def test_trailing_slashes_do_not_change_the_answer(self):
        settings = FakeSettings({'MOVIE_PATH': '/srv/media/movies/'})
        self.assertEqual(layout.source_for(settings, '/srv/media/movies/A Film (2024)'),
                         ('movies', 'A Film (2024)'))

    def test_the_source_address_keeps_the_path_as_written(self):
        # Media names carry spaces, brackets and ampersands. The address form
        # used here has no encoding layer, so they must survive untouched.
        address = layout.daemon_source(
            'remote.example', 'tvshows', 'Alpha & Bravo [2024]/S01E01.mkv')
        self.assertEqual(
            address, 'dragoncp@remote.example::tvshows/Alpha & Bravo [2024]/S01E01.mkv')

    def test_the_trailing_slash_is_the_callers_decision(self):
        # To rsync, "source/" means the CONTENTS of a folder and "source" means
        # the folder itself, landing inside the destination. Getting it wrong
        # nests a season inside itself, so neither can be the silent default.
        self.assertEqual(
            layout.daemon_source('remote.example', 'tvshows', 'Example Show'),
            'dragoncp@remote.example::tvshows/Example Show')
        self.assertEqual(
            layout.daemon_source('remote.example', 'tvshows', 'Example Show', True),
            'dragoncp@remote.example::tvshows/Example Show/')
        self.assertEqual(layout.daemon_source('remote.example', 'movies'),
                         'dragoncp@remote.example::movies')
        self.assertEqual(layout.daemon_source('remote.example', 'movies', '', True),
                         'dragoncp@remote.example::movies/')


# ---------------------------------------------------------------------------
# The generated configuration
# ---------------------------------------------------------------------------

class RenderTests(unittest.TestCase):
    def setUp(self):
        self.roots = [('movies', '/srv/media/movies'), ('tvshows', '/srv/media/tv')]

    def render(self, mode=render.ACCESS_RESTRICTED, address='198.51.100.7'):
        return render.render_conf('/home/someone', 52314, mode, address, self.roots)

    def test_restricted_mode_names_the_allowed_address(self):
        text = self.render()
        self.assertIn('hosts allow = 198.51.100.7', text)

    def test_password_only_mode_names_no_address(self):
        text = self.render(mode=render.ACCESS_PASSWORD_ONLY)
        self.assertNotIn('hosts allow', text)
        self.assertNotIn('198.51.100.7', text)

    def test_restricted_mode_with_no_address_does_not_publish_an_empty_rule(self):
        # An empty "hosts allow" would be read by rsync as a rule matching
        # nothing at all. Better to emit no rule than a broken one — and the
        # service refuses this combination before it ever gets here.
        text = self.render(address='')
        self.assertNotIn('hosts allow', text)

    def test_every_library_is_read_only_and_unlisted(self):
        text = self.render()
        for name, root in self.roots:
            self.assertIn(f"[{name}]", text)
            self.assertIn(f"path = {root}", text)
        self.assertEqual(text.count('read only = yes'), len(self.roots))
        self.assertEqual(text.count('list = no'), len(self.roots))

    def test_no_library_is_ever_the_home_directory(self):
        text = self.render()
        self.assertNotIn('path = /home/someone\n', text)

    def test_the_password_never_appears_in_the_configuration(self):
        self.assertNotIn('hunter2', self.render())
        self.assertIn('hunter2', render.render_secrets('hunter2'))

    def test_the_fingerprint_changes_when_the_settings_change(self):
        base = render.fingerprint(52314, 'restricted', '198.51.100.7', self.roots)
        self.assertNotEqual(base, render.fingerprint(52315, 'restricted', '198.51.100.7', self.roots))
        self.assertNotEqual(base, render.fingerprint(52314, 'password', '198.51.100.7', self.roots))
        self.assertNotEqual(base, render.fingerprint(52314, 'restricted', '203.0.113.9', self.roots))
        self.assertNotEqual(base, render.fingerprint(52314, 'restricted', '198.51.100.7', []))

    def test_the_fingerprint_can_be_read_back_out_of_the_configuration(self):
        text = self.render()
        expected = render.fingerprint(52314, 'restricted', '198.51.100.7', self.roots)
        self.assertEqual(render.installed_fingerprint(text), expected)
        self.assertIsNone(render.installed_fingerprint('nothing here'))
        self.assertIsNone(render.installed_fingerprint(None))

    def test_the_service_definition_supervises_a_process_that_stays_put(self):
        unit = render.render_unit('/home/someone', '/usr/bin/rsync', 52314)
        # Without --no-detach the daemon forks away and the supervisor watches a
        # process that has already exited, so it never restarts anything.
        self.assertIn('--no-detach', unit)
        self.assertIn('Restart=always', unit)
        self.assertIn('WantedBy=default.target', unit)
        self.assertIn('--port=52314', unit)


# ---------------------------------------------------------------------------
# Asking the server whether it will talk to us
# ---------------------------------------------------------------------------

class ClassifyTests(unittest.TestCase):
    """
    rsync's answers, mapped to ours.

    Kept apart from anything that needs a server so the mapping is pinned even
    where rsync is not installed — and so an unfamiliar failure is checked to
    surface rsync's own words rather than a reassuring guess.
    """

    def test_success_is_ready(self):
        self.assertEqual(probe.classify(0, 'drwxr-xr-x 4,096 .').state, probe.READY)

    def test_a_hidden_or_missing_library_is_blocked(self):
        # rsync says "unknown module" BOTH for a library that is not published
        # and for one the asking address may not see — it will not confirm that
        # a hidden library exists. This layer does not guess between them.
        result = probe.classify(5, "@ERROR: Unknown module 'movies'")
        self.assertEqual(result.state, probe.BLOCKED)
        self.assertTrue(result.running)

    def test_a_wrong_password_is_its_own_answer(self):
        result = probe.classify(5, '@ERROR: auth failed on module movies')
        self.assertEqual(result.state, probe.AUTH_FAILED)
        self.assertTrue(result.running)
        self.assertIn('reinstall', result.detail.lower())

    def test_nothing_listening_is_unreachable(self):
        result = probe.classify(10, 'rsync: failed to connect: Connection refused (111)')
        self.assertEqual(result.state, probe.UNREACHABLE)
        self.assertFalse(result.running)

    def test_a_name_that_does_not_resolve_is_unreachable(self):
        result = probe.classify(10, 'rsync: Name or service not known')
        self.assertEqual(result.state, probe.UNREACHABLE)

    def test_an_unfamiliar_failure_keeps_rsyncs_own_words(self):
        result = probe.classify(5, '@ERROR: chdir failed')
        self.assertEqual(result.state, probe.ERROR)
        self.assertIn('chdir failed', result.detail)

    def test_the_probe_asks_for_nothing_it_does_not_need(self):
        command = probe.build_command('remote.example', 52314, 'movies', '/tmp/pw')
        # Without this it would fetch a listing of the top of a media library
        # every time, for no gain.
        self.assertIn('--exclude=*', command)
        self.assertIn('--list-only', command)
        self.assertIn('--port=52314', command)
        self.assertIn('dragoncp@remote.example::movies', command)


class ProbeAgainstARealDaemonTests(unittest.TestCase):
    """
    The mapping above, against a real rsync daemon.

    A hand-written stand-in would only prove that our idea of rsync agrees with
    itself. This runs the actual client against the actual server, on this
    machine, so the answers are the ones production will get.
    """

    @classmethod
    def setUpClass(cls):
        if shutil.which('rsync') is None:
            raise unittest.SkipTest('rsync is not installed')

    def start_daemon(self, allow_us=True):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        served = os.path.join(tmp, 'library')
        os.makedirs(served)
        open(os.path.join(served, 'placeholder.txt'), 'w').close()

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()

        secrets_file = os.path.join(tmp, 'secrets')
        with open(secrets_file, 'w') as handle:
            handle.write('dragoncp:correct-horse\n')
        os.chmod(secrets_file, 0o600)

        # "hosts allow" naming an address that is not us is exactly what a
        # changed home address looks like from the server's side.
        access = '127.0.0.1' if allow_us else '203.0.113.99'
        conf = os.path.join(tmp, 'rsyncd.conf')
        with open(conf, 'w') as handle:
            handle.write(
                f"pid file = {tmp}/pid\nlock file = {tmp}/lock\nlog file = {tmp}/log\n"
                f"use chroot = no\nreverse lookup = no\nhosts allow = {access}\n\n"
                f"[movies]\n    path = {served}\n    read only = yes\n    list = no\n"
                f"    auth users = dragoncp\n    secrets file = {secrets_file}\n"
            )

        proc = subprocess.Popen(
            ['rsync', '--daemon', '--no-detach', f'--config={conf}', f'--port={port}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self._stop, proc)
        for _ in range(50):
            probe_sock = socket.socket()
            probe_sock.settimeout(0.2)
            try:
                probe_sock.connect(('127.0.0.1', port))
                probe_sock.close()
                break
            except OSError:
                time.sleep(0.1)
            finally:
                probe_sock.close()
        else:
            self.skipTest('the test rsync daemon would not start')
        return port, tmp

    @staticmethod
    def _stop(proc):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def password_file(self, tmp, value='correct-horse'):
        path = os.path.join(tmp, 'client-password')
        with open(path, 'w') as handle:
            handle.write(value + '\n')
        os.chmod(path, 0o600)
        return path

    def test_the_right_password_from_an_allowed_address_is_ready(self):
        port, tmp = self.start_daemon(allow_us=True)
        result = probe.probe('127.0.0.1', port, 'movies', self.password_file(tmp))
        self.assertEqual(result.state, probe.READY, result.detail)

    def test_an_address_the_server_does_not_allow_reads_as_blocked(self):
        # The fallback depends on this: the server is up, so restarting it would
        # achieve nothing, and saying "it is down" would send an operator after
        # the wrong problem entirely.
        port, tmp = self.start_daemon(allow_us=False)
        result = probe.probe('127.0.0.1', port, 'movies', self.password_file(tmp))
        self.assertEqual(result.state, probe.BLOCKED, result.detail)
        self.assertTrue(result.running)

    def test_a_wrong_password_is_told_apart_from_being_blocked(self):
        port, tmp = self.start_daemon(allow_us=True)
        result = probe.probe('127.0.0.1', port, 'movies',
                             self.password_file(tmp, 'wrong'))
        self.assertEqual(result.state, probe.AUTH_FAILED, result.detail)

    def test_nothing_listening_is_unreachable(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        spare = socket.socket()
        spare.bind(('127.0.0.1', 0))
        port = spare.getsockname()[1]
        spare.close()
        result = probe.probe('127.0.0.1', port, 'movies', self.password_file(tmp),
                             timeout=3)
        self.assertEqual(result.state, probe.UNREACHABLE, result.detail)

    def test_the_probe_never_sends_a_password_it_does_not_have(self):
        result = probe.probe('127.0.0.1', 873, 'movies', '/nonexistent/password')
        self.assertEqual(result.state, probe.ERROR)

    def test_an_unconfigured_server_is_not_probed_at_all(self):
        self.assertEqual(probe.probe('', 0, '', '/tmp/x').state, probe.UNREACHABLE)


# ---------------------------------------------------------------------------
# The service itself
# ---------------------------------------------------------------------------

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch('services.remote_daemon.service._app_dir',
                        return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self, config=None, settings=None):
        return RemoteDaemonService(FakeConfig(config), FakeSettings(settings))

    def test_the_password_is_generated_owner_only_and_reused(self):
        service = self.build()
        first = service.password()
        self.assertTrue(len(first) >= 32)
        self.assertEqual(service.password(), first)
        self.assertTrue(service.password_file_ok())

        mode = os.stat(os.path.join(self.tmp.name, 'dragoncp_rsyncd.secret')).st_mode
        self.assertEqual(mode & 0o077, 0)

    def test_rotating_produces_a_different_password(self):
        service = self.build()
        first = service.password()
        second = service.rotate_password()
        self.assertNotEqual(first, second)
        self.assertEqual(service.password(), second)

    def test_a_readable_password_file_is_reported_as_insecure(self):
        service = self.build()
        service.password()
        os.chmod(os.path.join(self.tmp.name, 'dragoncp_rsyncd.secret'), 0o644)
        self.assertFalse(service.password_file_ok())

    def test_asking_for_the_password_without_creating_one_does_not_create_one(self):
        service = self.build()
        self.assertEqual(service.password(create=False), '')
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, 'dragoncp_rsyncd.secret')))

    def test_restricted_access_without_an_address_refuses_to_install(self):
        service = self.build(config={'RSYNC_DAEMON_ALLOWED_IP': ''})
        ok, why = service.configured()
        self.assertFalse(ok)
        self.assertIn('allowed address', why.lower())

    def test_password_only_access_needs_no_address(self):
        service = self.build(
            config={'RSYNC_DAEMON_ALLOWED_IP': ''},
            settings={'FAST_TRANSPORT_ACCESS_MODE': 'password'})
        ok, _ = service.configured()
        self.assertTrue(ok)

    def test_no_libraries_configured_refuses_to_install(self):
        service = self.build(settings={
            'MOVIE_PATH': '', 'TVSHOW_PATH': '', 'ANIME_PATH': ''})
        ok, why = service.configured()
        self.assertFalse(ok)
        self.assertIn('media directories', why.lower())

    def test_an_unrecognised_access_mode_falls_back_to_the_safe_one(self):
        service = self.build(settings={'FAST_TRANSPORT_ACCESS_MODE': 'nonsense'})
        self.assertEqual(service.access_mode, render.ACCESS_RESTRICTED)

    def test_on_demand_is_the_default_so_the_port_is_not_open_all_day(self):
        self.assertFalse(self.build().start_at_boot)
        self.assertTrue(self.build(settings={'FAST_TRANSPORT_LIFECYCLE': 'always'}).start_at_boot)

    def test_the_allowed_address_is_never_in_what_the_panel_is_sent(self):
        # It is private to the operator and useless to a reader. The panel only
        # needs to know whether one is set and whether it still matches.
        service = self.build()
        with patch.object(RemoteDaemonService, '_ssh', side_effect=RuntimeError('no ssh')), \
                patch.object(RemoteDaemonService, '_probe_now',
                             return_value=probe.ProbeResult(probe.UNREACHABLE, 'not checked')):
            state = service.status(refresh=False)
        self.assertNotIn('198.51.100.7', repr(state))
        self.assertTrue(state['has_allowed_address'])

    def test_the_fast_route_is_refused_until_it_is_switched_on(self):
        service = self.build()
        service.password()
        with patch.object(RemoteDaemonService, 'ensure_running', return_value=(True, 'Ready')):
            self.assertIsNone(service.route_for('/srv/media/movies/A Film'))

    def test_a_path_outside_every_library_never_gets_a_fast_route(self):
        # Failing closed. A path we cannot place inside a published library is
        # one we must not invent an address for.
        service = self.build(settings={'FAST_TRANSPORT_ENABLED': 'true'})
        service.password()
        with patch.object(RemoteDaemonService, 'ensure_running', return_value=(True, 'Ready')):
            self.assertIsNone(service.route_for('/etc/passwd'))
            self.assertIsNone(service.route_for('/srv/other/thing'))

    def test_a_server_that_will_not_answer_falls_back(self):
        service = self.build(settings={'FAST_TRANSPORT_ENABLED': 'true'})
        service.password()
        with patch.object(RemoteDaemonService, 'ensure_running', return_value=(False, 'blocked')):
            self.assertIsNone(service.route_for('/srv/media/movies/A Film'))

    def test_no_generated_password_means_no_fast_route(self):
        service = self.build(settings={'FAST_TRANSPORT_ENABLED': 'true'})
        with patch.object(RemoteDaemonService, 'ensure_running', return_value=(True, 'Ready')):
            self.assertIsNone(service.route_for('/srv/media/movies/A Film'))

    def test_a_usable_route_carries_the_port_and_the_password_file(self):
        service = self.build(settings={'FAST_TRANSPORT_ENABLED': 'true'})
        service.password()
        with patch.object(RemoteDaemonService, 'ensure_running', return_value=(True, 'Ready')):
            # The directory on disk is /srv/media/tv; the published name is
            # 'tvshows'. The address carries the published name, never the
            # layout of somebody's disk.
            source, args = service.route_for('/srv/media/tv/Example Show', True)
        self.assertEqual(source, 'dragoncp@remote.example::tvshows/Example Show/')
        self.assertIn('--port=52314', args)
        self.assertIn('--password-file', args)

    def test_it_stays_up_when_told_to_run_always(self):
        service = self.build(settings={'FAST_TRANSPORT_LIFECYCLE': 'always'})
        with patch.object(RemoteDaemonService, 'stop') as stop:
            service.release(lambda: False)
        stop.assert_not_called()

    def test_it_stops_once_nothing_needs_it(self):
        service = self.build()
        with patch.object(RemoteDaemonService, 'stop', return_value=(True, 'stopped')) as stop, \
                patch.object(RemoteDaemonService, 'health',
                             return_value=probe.ProbeResult(probe.READY, 'Ready')):
            service.release(lambda: False)
        stop.assert_called_once()

    def test_it_is_left_alone_while_a_transfer_still_needs_it(self):
        service = self.build()
        with patch.object(RemoteDaemonService, 'stop') as stop, \
                patch.object(RemoteDaemonService, 'health',
                             return_value=probe.ProbeResult(probe.READY, 'Ready')):
            service.release(lambda: True)
        stop.assert_not_called()

    def test_a_failure_while_stopping_is_swallowed(self):
        # This runs after a transfer has already finished. A server left up
        # costs a listening port; raising here would turn a completed transfer
        # into an error.
        service = self.build()
        with patch.object(RemoteDaemonService, 'health', side_effect=RuntimeError('boom')):
            service.release(lambda: False)  # must not raise

    def test_status_always_answers_even_when_the_remote_is_unreachable(self):
        service = self.build()
        with patch.object(RemoteDaemonService, '_ssh', side_effect=RuntimeError('boom')), \
                patch.object(RemoteDaemonService, '_probe_now',
                             return_value=probe.ProbeResult(probe.UNREACHABLE, 'not checked')):
            state = service.status(refresh=False)
        self.assertFalse(state['reachable_over_ssh'])
        self.assertTrue(state['summary'])


if __name__ == '__main__':
    unittest.main()


class ReviewFindingsTests(unittest.TestCase):
    """
    Failure and lifecycle paths raised in review. Each one reported success
    while leaving the installation in a state the operator was not told about.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch('services.remote_daemon.service._app_dir', return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self, config=None, settings=None):
        return RemoteDaemonService(FakeConfig(config), FakeSettings(settings))

    # ---- a filesystem root must never be published ------------------------

    def test_a_root_library_is_not_published(self):
        # '/' survived the truthiness check and then became '' — an empty root
        # that matches every path on the machine.
        settings = FakeSettings({'MOVIE_PATH': '/', 'TVSHOW_PATH': '', 'ANIME_PATH': '  '})
        self.assertEqual(layout.module_roots(settings), [])

    def test_nothing_maps_onto_an_empty_root(self):
        settings = FakeSettings({'MOVIE_PATH': '/', 'TVSHOW_PATH': '', 'ANIME_PATH': ''})
        for path in ('/etc/shadow', '/', '/home/someone/private'):
            self.assertIsNone(layout.source_for(settings, path), path)

    def test_a_trailing_slash_still_publishes_normally(self):
        settings = FakeSettings({'MOVIE_PATH': '/srv/media/movies/'})
        self.assertIn(('movies', '/srv/media/movies'), layout.module_roots(settings))

    # ---- uninstall must not lie -------------------------------------------

    def test_uninstall_refuses_when_the_service_will_not_stop(self):
        service = self.build()
        with patch.object(RemoteDaemonService, '_ssh'), \
                patch.object(RemoteDaemonService, '_home', return_value='/home/someone'), \
                patch.object(RemoteDaemonService, '_run', return_value=(1, '', 'stop failed')):
            ok, message = service.uninstall()
        self.assertFalse(ok)
        self.assertIn('nothing was removed', message)

    def test_uninstall_refuses_while_it_is_still_answering(self):
        service = self.build()
        with patch.object(RemoteDaemonService, '_ssh'), \
                patch.object(RemoteDaemonService, '_home', return_value='/home/someone'), \
                patch.object(RemoteDaemonService, '_run', return_value=(0, '', '')), \
                patch.object(RemoteDaemonService, '_probe_now',
                             return_value=probe.ProbeResult(probe.READY, 'Ready')):
            ok, message = service.uninstall()
        self.assertFalse(ok)
        self.assertIn('still answering', message)

    # ---- lifecycle drift must be visible ----------------------------------

    def test_a_boot_setting_that_did_not_apply_is_not_reported_as_up_to_date(self):
        service = self.build(settings={'FAST_TRANSPORT_LIFECYCLE': 'always'})
        state = {
            'installed': True, 'service_enabled': 'disabled', 'start_at_boot': True,
            'up_to_date': True, 'configured': True, 'reachable_over_ssh': True,
            'lifecycle_matches': False, 'configuration_problem': '',
            'health': probe.ProbeResult(probe.READY, 'Ready').to_dict(),
            'service_state': 'active',
        }
        self.assertIn('boot', RemoteDaemonService._summarise(state))

    def test_status_survives_an_unreadable_password_file(self):
        service = self.build()
        with patch.object(RemoteDaemonService, 'password',
                          side_effect=RemoteDaemonError('permission denied')):
            self.assertFalse(service._password_present())

    # ---- the stored password is never briefly readable --------------------

    def test_rotating_over_a_readable_file_narrows_before_writing(self):
        service = self.build()
        path = os.path.join(self.tmp.name, 'dragoncp_rsyncd.secret')
        with open(path, 'w') as handle:
            handle.write('old\n')
        os.chmod(path, 0o644)

        service.rotate_password()
        self.assertEqual(os.stat(path).st_mode & 0o077, 0)
        self.assertTrue(service.password_file_ok())
