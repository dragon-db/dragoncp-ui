#!/usr/bin/env python3
"""
The browse session to the remote server, and the rules that keep it from
getting this address banned (operator, 2026-10-20).

Pins:
  * a missing or dead session is reopened with the saved login when
    Auto-connect is on, and never when it is off;
  * one attempt at a time, however many requests ask at once;
  * after a failed automatic attempt the next waits 30 s, then longer;
  * a refused login or a host key that does not match stops automatic
    attempts until a person connects; a person's own attempts are spaced;
  * the old session is closed when a new one opens.
"""

import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.remote_session import RETRY_DELAYS, RemoteSession, SessionUnavailable
from ssh import FAILED_AUTH, FAILED_HOST_KEY, FAILED_NETWORK


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Config:
    def __init__(self, **values):
        self.values = {'REMOTE_IP': 'remote.example', 'REMOTE_USER': 'media', **values}

    def get(self, key, default=''):
        return self.values.get(key, default)


class Settings:
    def __init__(self, auto=True):
        self.auto = auto

    def get_bool(self, key, default=False):
        assert key == 'SSH_AUTO_CONNECT'
        return self.auto


class Factory:
    """Builds fake managers whose connect() answers from a script."""

    def __init__(self):
        self.script = []        # each: None for success, or a FAILED_* kind
        self.built = []
        self.delay = 0.0

    def __call__(self, host, username, password, key_path, **kwargs):
        factory = self

        class Manager:
            def __init__(self):
                self.host = host
                self.connected = False
                self.closed = False
                self.last_error_kind = None
                self.last_error = ''

            def connect(self):
                if factory.delay:
                    time.sleep(factory.delay)
                outcome = factory.script.pop(0) if factory.script else None
                if outcome is None:
                    self.connected = True
                    return True
                self.last_error_kind = outcome
                self.last_error = {FAILED_AUTH: 'Authentication failed.',
                                   FAILED_HOST_KEY: 'host key mismatch'}.get(outcome, 'timed out')
                return False

            def is_alive(self):
                return self.connected and not self.closed

            def disconnect(self):
                self.closed = True
                self.connected = False

        manager = Manager()
        self.built.append(manager)
        return manager


class RemoteSessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.factory = Factory()
        self.settings = Settings()
        self.changes = []
        self.session = RemoteSession(Config(), settings=self.settings,
                                     on_change=self.changes.append,
                                     factory=self.factory, clock=self.clock)

    def attempts(self):
        return len(self.factory.built)

    def test_no_session_is_opened_when_asked_for(self):
        manager = self.session.ensure()
        self.assertTrue(manager.is_alive())
        self.assertIs(self.session.ensure(), manager, 'a live session is reused')
        self.assertEqual(self.attempts(), 1)
        self.assertEqual(self.changes, [manager])

    def test_a_dead_session_is_reopened_and_the_old_one_closed(self):
        first = self.session.ensure()
        first.connected = False      # the server reset it
        second = self.session.ensure()
        self.assertIsNot(first, second)
        self.assertTrue(first.closed)
        self.assertEqual(self.attempts(), 2)

    def test_auto_connect_off_never_tries(self):
        self.settings.auto = False
        with self.assertRaises(SessionUnavailable) as caught:
            self.session.ensure()
        self.assertEqual(caught.exception.reason, 'off')
        self.assertEqual(self.attempts(), 0)
        ok, _ = self.session.connect()
        self.assertTrue(ok, 'connecting by hand still works')

    def test_a_failure_waits_before_the_next_automatic_try(self):
        self.factory.script = [FAILED_NETWORK, FAILED_NETWORK, None]
        with self.assertRaises(SessionUnavailable):
            self.session.ensure()
        for _ in range(5):
            with self.assertRaises(SessionUnavailable) as caught:
                self.session.ensure()
        self.assertEqual(self.attempts(), 1, 'nothing is retried before the wait is over')
        self.assertIn('Trying again at', caught.exception.message)

        self.clock.now += RETRY_DELAYS[0]
        with self.assertRaises(SessionUnavailable):
            self.session.ensure()
        self.assertEqual(self.attempts(), 2)

        self.clock.now += RETRY_DELAYS[0]
        with self.assertRaises(SessionUnavailable):
            self.session.ensure()
        self.assertEqual(self.attempts(), 2, 'the second wait is longer than the first')
        self.clock.now += RETRY_DELAYS[1] - RETRY_DELAYS[0]
        self.assertTrue(self.session.ensure().is_alive())
        self.assertEqual(self.attempts(), 3)

    def test_the_wait_never_grows_past_five_minutes(self):
        self.assertEqual(max(RETRY_DELAYS), 300)
        self.factory.script = [FAILED_NETWORK] * 10
        for _ in range(8):
            with self.assertRaises(SessionUnavailable):
                self.session.ensure()
            self.clock.now += 300
        self.assertEqual(self.attempts(), 8)

    def test_a_refused_login_stops_automatic_attempts(self):
        self.factory.script = [FAILED_AUTH]
        with self.assertRaises(SessionUnavailable):
            self.session.ensure()
        self.clock.now += 3600
        with self.assertRaises(SessionUnavailable) as caught:
            self.session.ensure()
        self.assertEqual(caught.exception.reason, 'paused')
        self.assertIn('refused the login', caught.exception.message)
        self.assertEqual(self.attempts(), 1, 'a wrong password is never retried by itself')
        self.assertTrue(self.session.status()['paused'])

    def test_a_host_key_mismatch_stops_automatic_attempts(self):
        self.factory.script = [FAILED_HOST_KEY]
        with self.assertRaises(SessionUnavailable):
            self.session.ensure()
        self.clock.now += 3600
        with self.assertRaises(SessionUnavailable):
            self.session.ensure()
        self.assertEqual(self.attempts(), 1)

    def test_a_person_is_spaced_too_after_a_refused_login(self):
        self.factory.script = [FAILED_AUTH, FAILED_AUTH, None]
        ok, _ = self.session.connect()
        self.assertFalse(ok)
        ok, message = self.session.connect()
        self.assertFalse(ok)
        self.assertIn('next try is allowed at', message)
        self.assertEqual(self.attempts(), 1, 'the second press made no attempt')
        self.clock.now += 60
        self.assertFalse(self.session.connect()[0])
        self.assertEqual(self.attempts(), 2)
        self.clock.now += 60
        self.assertTrue(self.session.connect()[0])
        self.assertFalse(self.session.status()['paused'], 'a good login lifts the pause')
        self.session.manager.connected = False
        self.assertTrue(self.session.ensure().is_alive(), 'automatic attempts resume')

    def test_a_person_waits_ten_seconds_after_an_unreachable_server(self):
        self.factory.script = [FAILED_NETWORK, None]
        self.assertFalse(self.session.connect()[0])
        self.clock.now += 9
        self.assertFalse(self.session.connect()[0])
        self.assertEqual(self.attempts(), 1)
        self.clock.now += 1
        self.assertTrue(self.session.connect()[0])

    def test_many_requests_at_once_make_one_attempt(self):
        self.factory.delay = 0.2
        results = []

        def ask():
            results.append(self.session.ensure())

        threads = [threading.Thread(target=ask) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.attempts(), 1)
        self.assertEqual(len({id(r) for r in results}), 1)

    def test_many_requests_while_failing_make_one_attempt(self):
        self.factory.delay = 0.2
        self.factory.script = [FAILED_NETWORK]
        errors = []

        def ask():
            try:
                self.session.ensure()
            except SessionUnavailable as error:
                errors.append(error)

        threads = [threading.Thread(target=ask) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.attempts(), 1)
        self.assertEqual(len(errors), 6)

    def test_disconnect_closes_and_says_so(self):
        manager = self.session.ensure()
        self.session.disconnect()
        self.assertTrue(manager.closed)
        self.assertIsNone(self.session.manager)
        self.assertEqual(self.changes[-1], None)
        self.assertFalse(self.session.status()['connected'])

    def test_no_remote_configured_is_not_counted_as_a_failure(self):
        session = RemoteSession(Config(REMOTE_IP=''), settings=self.settings,
                                factory=self.factory, clock=self.clock)
        with self.assertRaises(SessionUnavailable) as caught:
            session.ensure()
        self.assertIn('No remote server is configured', caught.exception.message)
        self.assertEqual(self.attempts(), 0)
        self.assertEqual(session.failures, 0)

    def test_status_says_when_it_may_try_again(self):
        self.factory.script = [FAILED_NETWORK]
        with self.assertRaises(SessionUnavailable):
            self.session.ensure()
        status = self.session.status()
        self.assertFalse(status['connected'])
        self.assertEqual(status['last_error_kind'], FAILED_NETWORK)
        self.assertIsNotNone(status['retry_at'])


class SSHManagerTests(unittest.TestCase):
    """The pieces of SSHManager the session relies on, without a network."""

    def test_is_alive_asks_the_transport(self):
        from ssh import SSHManager

        class Transport:
            active = True

            def is_active(self):
                return self.active

        class Client:
            transport = Transport()

            def get_transport(self):
                return self.transport

        manager = SSHManager('remote.example', 'media')
        self.assertFalse(manager.is_alive())
        manager.client = Client()
        manager.connected = True
        self.assertTrue(manager.is_alive())
        Client.transport.active = False
        self.assertFalse(manager.is_alive(), 'reset by the server, though still flagged')

    def test_a_refused_login_is_recorded_as_one(self):
        from unittest.mock import patch

        import paramiko
        from ssh import SSHManager
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # Its own known_hosts, so the app's real one is never read or written.
            manager = SSHManager('remote.example', 'media', password='wrong',
                                 known_hosts_file=f"{tmp}/known_hosts")
            self._refuse(manager, patch, paramiko)
        self.assertEqual(manager.last_error_kind, FAILED_AUTH)

    def _refuse(self, manager, patch, paramiko):
        with patch.object(paramiko.SSHClient, 'connect',
                          side_effect=paramiko.AuthenticationException('Authentication failed.')):
            self.assertFalse(manager.connect())


if __name__ == '__main__':
    unittest.main()
