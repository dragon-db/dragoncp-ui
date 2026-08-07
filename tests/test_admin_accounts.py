#!/usr/bin/env python3
"""
Named administrator accounts, and the two properties that make them worth having.

  Sign-in resolves against the account table, with the environment-file
  credentials accepted only while no account there can sign in.

  A session does not outlive the account behind it. Disabling an account,
  renaming it, or changing its password retires the tokens already issued —
  which is what lets "we removed their access" be a true statement rather than
  one that becomes true within a day.

The second property is the one worth guarding. Before it, a token was a bearer
credential valid until its own expiry: an administrator removed on Monday kept
working until Tuesday, and the activity trail phase 2 builds on top of this
would have been recording actions by someone who had supposedly been locked out.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import auth
import login_guard
from actor import (
    ACTOR_ADMIN,
    ACTOR_AUTOMATED,
    AUTO_SYNC_SCHEDULER,
    SYSTEM_ACTOR,
    admin_actor,
    automated_actor,
    webhook_actor,
)
from models.admin_account import (
    AdminAccount,
    AdminAccountError,
    validate_password,
    validate_username,
)
from models.database import DatabaseManager


TEST_AUTH_CONFIG = {
    'username': 'envadmin',
    'password_hash': '',
    'password_plain': 'env-fallback-password',
    'jwt_secret': 'test-secret-key-for-admin-account-tests',
    'jwt_expiry_hours': 24,
    'jwt_algorithm': 'HS256',
    'login_max_attempts': 5,
    'login_window_minutes': 15,
    'login_lockout_minutes': 15,
}


class AuthConfigParsingTests(unittest.TestCase):
    def read_config(self, values):
        env = {'JWT_SECRET_KEY': 'test-secret', **values}
        with patch.object(auth, '_load_env_file', return_value=env), \
                patch('builtins.print') as warning:
            return auth.get_auth_config(), warning

    def test_nonpositive_auth_settings_use_their_defaults(self):
        expected = {
            'jwt_expiry_hours': 24,
            'login_max_attempts': 5,
            'login_window_minutes': 15,
            'login_lockout_minutes': 15,
        }
        keys = {
            'JWT_EXPIRY_HOURS': 'jwt_expiry_hours',
            'LOGIN_MAX_ATTEMPTS': 'login_max_attempts',
            'LOGIN_WINDOW_MINUTES': 'login_window_minutes',
            'LOGIN_LOCKOUT_MINUTES': 'login_lockout_minutes',
        }

        for invalid in ('0', '-2'):
            with self.subTest(value=invalid):
                config, warning = self.read_config({key: invalid for key in keys})
                for setting, result_key in keys.items():
                    self.assertEqual(config[result_key], expected[result_key])
                    self.assertTrue(any(setting in str(call) for call in warning.call_args_list))

    def test_positive_and_blank_auth_settings_keep_existing_behavior(self):
        keys = {
            'JWT_EXPIRY_HOURS': 'jwt_expiry_hours',
            'LOGIN_MAX_ATTEMPTS': 'login_max_attempts',
            'LOGIN_WINDOW_MINUTES': 'login_window_minutes',
            'LOGIN_LOCKOUT_MINUTES': 'login_lockout_minutes',
        }
        positive, warning = self.read_config({key: '1' for key in keys})
        self.assertTrue(all(positive[result_key] == 1 for result_key in keys.values()))
        warning.assert_not_called()

        blank, warning = self.read_config({key: ' ' for key in keys})
        self.assertEqual(blank['jwt_expiry_hours'], 24)
        self.assertEqual(blank['login_max_attempts'], 5)
        self.assertEqual(blank['login_window_minutes'], 15)
        self.assertEqual(blank['login_lockout_minutes'], 15)
        warning.assert_not_called()


class AccountTestCase(unittest.TestCase):
    """A throwaway database with the account table, wired into the auth layer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp.name, 'test.db')

        with patch('builtins.print'):
            self.db = DatabaseManager(db_path)

        self.store = AdminAccount(self.db)
        auth.set_account_store(self.store)

        self._config_patch = patch.object(auth, 'get_auth_config', return_value=dict(TEST_AUTH_CONFIG))
        self._config_patch.start()

        self._print_patch = patch('builtins.print')
        self._print_patch.start()

        login_guard.reset()
        login_guard.configure(max_attempts=5, window_seconds=900, lockout_seconds=900, enabled=True)

    def tearDown(self):
        self._print_patch.stop()
        self._config_patch.stop()
        auth.set_account_store(None)
        login_guard.reset()
        self._tmp.cleanup()

    def make_account(self, username='alice', password='correct-horse-battery', **kwargs):
        return self.store.create(username, auth.hash_password(password), **kwargs)


class UsernameRulesTests(unittest.TestCase):
    def test_accepts_ordinary_names(self):
        for name in ('alice', 'bob.smith', 'priya_n', 'ops-lead'):
            self.assertEqual(validate_username(name), name)

    def test_rejects_names_that_could_pass_for_automation(self):
        # Automated activity is labelled "AUTO / <name>". A human called
        # "autosync" sitting in the same column would make the trail unreadable.
        for name in ('auto', 'automated', 'autosync', 'auto-sync', 'system', 'systemd'):
            with self.assertRaises(AdminAccountError):
                validate_username(name)

    def test_rejects_malformed_names(self):
        for name in ('', 'ab', '1alice', 'has space', 'a' * 33, 'em@il'):
            with self.assertRaises(AdminAccountError):
                validate_username(name)

    def test_rejects_short_passwords(self):
        with self.assertRaises(AdminAccountError):
            validate_password('short')
        self.assertEqual(validate_password('long-enough-password'), 'long-enough-password')


class AccountStoreTests(AccountTestCase):
    def test_usernames_are_unique_regardless_of_case(self):
        self.make_account('alice')
        with self.assertRaises(AdminAccountError):
            self.make_account('ALICE')

    def test_lookup_ignores_case(self):
        created = self.make_account('alice')
        self.assertEqual(self.store.find_by_username('ALICE')['id'], created['id'])

    def test_rename_keeps_the_id_so_history_survives(self):
        created = self.make_account('bob')
        renamed = self.store.rename('bob', 'bob.smith')

        self.assertEqual(renamed['id'], created['id'])
        self.assertEqual(renamed['username'], 'bob.smith')
        self.assertIsNone(self.store.find_by_username('bob'))

    def test_rename_rejects_a_name_already_taken(self):
        self.make_account('alice')
        self.make_account('bob')
        with self.assertRaises(AdminAccountError):
            self.store.rename('bob', 'alice')

    def test_rename_can_correct_capitalisation(self):
        self.make_account('alice')
        renamed = self.store.rename('alice', 'Alice')
        self.assertEqual(renamed['username'], 'Alice')

    def test_an_account_can_be_created_switched_off(self):
        # The safe handover: the temporary password does nothing until someone
        # enables the account, so seeing it in passing is not enough to use it.
        account = self.make_account('priya', is_active=False)

        self.assertFalse(account['is_active'])
        self.assertEqual(self.store.count_all(), 1)
        self.assertEqual(self.store.count_enabled(), 0)

    def test_a_password_for_a_disabled_new_account_does_not_work_yet(self):
        self.make_account('priya', 'handed-over-password', is_active=False)

        self.assertIsNone(auth.authenticate('priya', 'handed-over-password'))

    def test_enabling_makes_the_handed_over_password_work(self):
        account = self.make_account('priya', 'handed-over-password', is_active=False)

        self.store.set_active(account['id'], True)

        identity = auth.authenticate('priya', 'handed-over-password')
        self.assertIsNotNone(identity)
        self.assertEqual(identity['username'], 'priya')
        self.assertTrue(identity['must_change_password'])

    def test_creating_a_disabled_account_leaves_the_fallback_in_place(self):
        # Adding someone who cannot yet sign in must not lock out whoever is
        # currently getting in with the environment credentials.
        self.make_account('priya', is_active=False)

        self.assertTrue(auth.env_fallback_active())
        self.assertIsNotNone(auth.authenticate('envadmin', 'env-fallback-password'))

    def test_disabling_does_not_remove_the_row(self):
        created = self.make_account('alice')
        self.store.set_active(created['id'], False)

        still_there = self.store.find_by_id(created['id'])
        self.assertIsNotNone(still_there)
        self.assertFalse(still_there['is_active'])
        self.assertEqual(self.store.count_all(), 1)
        self.assertEqual(self.store.count_enabled(), 0)


class EnvFallbackTests(AccountTestCase):
    def test_env_account_works_while_no_accounts_exist(self):
        self.assertTrue(auth.env_fallback_active())

        identity = auth.authenticate('envadmin', 'env-fallback-password')

        self.assertIsNotNone(identity)
        self.assertEqual(identity['source'], auth.SOURCE_ENV)
        self.assertIsNone(identity['account_id'])

    def test_adding_the_first_account_switches_the_fallback_off(self):
        self.make_account('alice')

        self.assertFalse(auth.env_fallback_active())
        self.assertIsNone(auth.authenticate('envadmin', 'env-fallback-password'))

    def test_fallback_returns_when_every_account_is_disabled(self):
        # The way back in after a lockout, without hand-editing the database.
        account = self.make_account('alice')
        self.store.set_active(account['id'], False)

        self.assertTrue(auth.env_fallback_active())
        self.assertIsNotNone(auth.authenticate('envadmin', 'env-fallback-password'))

    def test_fallback_recovers_when_a_disabled_account_has_the_same_name(self):
        account = self.make_account('envadmin', 'database-password')
        self.store.set_active(account['id'], False)

        self.assertTrue(auth.env_fallback_active())
        self.assertIsNone(auth.authenticate('envadmin', 'database-password'))

        identity = auth.authenticate('envadmin', 'env-fallback-password')
        self.assertIsNotNone(identity)
        self.assertEqual(identity['source'], auth.SOURCE_ENV)

    def test_fallback_session_stops_validating_once_a_real_account_exists(self):
        identity = auth.authenticate('envadmin', 'env-fallback-password')
        token, _ = auth.generate_token(identity)

        payload = auth.validate_token(token)
        resolved, reason = auth.resolve_identity(payload)
        self.assertEqual(reason, auth.REASON_OK)

        self.make_account('alice')

        resolved, reason = auth.resolve_identity(payload)
        self.assertIsNone(resolved)
        self.assertEqual(reason, auth.REASON_REVOKED)

    def test_a_revoked_fallback_session_does_not_resurrect_after_lockout(self):
        identity = auth.authenticate('envadmin', 'env-fallback-password')
        token, _ = auth.generate_token(identity)
        payload = auth.validate_token(token)

        account = self.make_account('alice')
        self.store.set_active(account['id'], False)

        resolved, reason = auth.resolve_identity(payload)
        self.assertIsNone(resolved)
        self.assertEqual(reason, auth.REASON_REVOKED)

        replacement = auth.authenticate('envadmin', 'env-fallback-password')
        replacement_token, _ = auth.generate_token(replacement)
        replacement_payload = auth.validate_token(replacement_token)
        resolved, reason = auth.resolve_identity(replacement_payload)
        self.assertEqual(reason, auth.REASON_OK)
        self.assertEqual(resolved['source'], auth.SOURCE_ENV)


class SignInTests(AccountTestCase):
    def test_correct_password_returns_the_identity(self):
        self.make_account('alice', 'correct-horse-battery')

        identity = auth.authenticate('alice', 'correct-horse-battery')

        self.assertIsNotNone(identity)
        self.assertEqual(identity['username'], 'alice')
        self.assertEqual(identity['source'], auth.SOURCE_DATABASE)
        self.assertIsNotNone(identity['account_id'])

    def test_wrong_password_is_refused(self):
        self.make_account('alice', 'correct-horse-battery')
        self.assertIsNone(auth.authenticate('alice', 'wrong-password-here'))

    def test_disabled_account_cannot_sign_in_even_with_the_right_password(self):
        account = self.make_account('alice', 'correct-horse-battery')
        self.store.set_active(account['id'], False)

        self.assertIsNone(auth.authenticate('alice', 'correct-horse-battery'))

    def test_disabled_account_does_not_fall_through_to_the_env_credentials(self):
        # With every account disabled the fallback is active again, but that must
        # not turn a disabled person's own name into a working sign-in.
        account = self.make_account('alice', 'correct-horse-battery')
        self.store.set_active(account['id'], False)

        self.assertTrue(auth.env_fallback_active())
        self.assertIsNone(auth.authenticate('alice', 'correct-horse-battery'))
        self.assertIsNone(auth.authenticate('alice', 'env-fallback-password'))


class SessionRevocationTests(AccountTestCase):
    """A token is only as good as the account it was minted for."""

    def issue_token_for(self, username, password):
        identity = auth.authenticate(username, password)
        self.assertIsNotNone(identity)
        token, _ = auth.generate_token(identity)
        return auth.validate_token(token)

    def test_a_live_session_resolves(self):
        self.make_account('alice', 'correct-horse-battery')
        payload = self.issue_token_for('alice', 'correct-horse-battery')

        identity, reason = auth.resolve_identity(payload)

        self.assertEqual(reason, auth.REASON_OK)
        self.assertEqual(identity['username'], 'alice')

    def test_disabling_an_account_kills_its_existing_session(self):
        account = self.make_account('alice', 'correct-horse-battery')
        payload = self.issue_token_for('alice', 'correct-horse-battery')

        self.store.set_active(account['id'], False)

        identity, reason = auth.resolve_identity(payload)
        self.assertIsNone(identity)
        self.assertEqual(reason, auth.REASON_DISABLED)

    def test_changing_a_password_kills_existing_sessions(self):
        account = self.make_account('alice', 'correct-horse-battery')
        payload = self.issue_token_for('alice', 'correct-horse-battery')

        self.store.set_password(account['id'], auth.hash_password('a-brand-new-password'))

        identity, reason = auth.resolve_identity(payload)
        self.assertIsNone(identity)
        self.assertEqual(reason, auth.REASON_REVOKED)

    def test_renaming_an_account_kills_existing_sessions(self):
        self.make_account('bob', 'correct-horse-battery')
        payload = self.issue_token_for('bob', 'correct-horse-battery')

        self.store.rename('bob', 'bob.smith')

        identity, reason = auth.resolve_identity(payload)
        self.assertIsNone(identity)
        self.assertEqual(reason, auth.REASON_REVOKED)

    def test_a_refresh_token_is_revoked_alongside_the_access_token(self):
        account = self.make_account('alice', 'correct-horse-battery')
        identity = auth.authenticate('alice', 'correct-horse-battery')
        refresh, _ = auth.generate_refresh_token(identity)

        self.store.set_active(account['id'], False)

        payload = auth.validate_token(refresh, token_type='refresh')
        resolved, reason = auth.resolve_identity(payload)
        self.assertIsNone(resolved)
        self.assertEqual(reason, auth.REASON_DISABLED)

    def test_live_connections_are_checked_the_same_way(self):
        account = self.make_account('alice', 'correct-horse-battery')
        identity = auth.authenticate('alice', 'correct-horse-battery')

        self.assertTrue(auth.websocket_identity_still_valid(
            identity['account_id'], identity['token_version'], identity['source']
        ))

        self.store.set_active(account['id'], False)

        self.assertFalse(auth.websocket_identity_still_valid(
            identity['account_id'], identity['token_version'], identity['source']
        ))

    def test_revoked_live_connection_is_reaped_on_the_fast_sweep(self):
        import websocket

        account = self.make_account('alice', 'correct-horse-battery')
        identity = auth.authenticate('alice', 'correct-horse-battery')

        class FakeServer:
            def __init__(self):
                self.disconnected = []

            def disconnect(self, sid, namespace):
                self.disconnected.append((sid, namespace))

        class FakeSocketIO:
            server = FakeServer()

        with websocket.websocket_connections_lock:
            websocket.websocket_connections['review-sid'] = {
                'connected_at': datetime.now(),
                'last_activity': datetime.now(),
                'timeout_seconds': websocket.WEBSOCKET_TIMEOUT_DEFAULT,
                'username': identity['username'],
                'account_id': identity['account_id'],
                'token_version': identity['token_version'],
                'auth_source': identity['source'],
            }
        self.addCleanup(websocket.websocket_connections.clear)

        self.store.set_active(account['id'], False)

        socketio = FakeSocketIO()
        self.assertEqual(websocket.reap_stale_connections(socketio), 1)
        self.assertEqual(socketio.server.disconnected, [('review-sid', '/')])
        self.assertNotIn('review-sid', websocket.websocket_connections)

    def test_reaper_preserves_a_connection_refreshed_during_validation(self):
        import websocket

        identity = {'username': 'alice', 'account_id': 7, 'token_version': 1, 'source': 'db'}

        class FakeServer:
            def __init__(self):
                self.disconnected = []

            def disconnect(self, sid, namespace):
                self.disconnected.append((sid, namespace))

        class FakeSocketIO:
            server = FakeServer()

        with websocket.websocket_connections_lock:
            websocket.websocket_connections['refresh-sid'] = {
                'connected_at': datetime.now(),
                'last_activity': datetime.now(),
                'timeout_seconds': websocket.WEBSOCKET_TIMEOUT_DEFAULT,
                'username': identity['username'],
                'account_id': identity['account_id'],
                'token_version': identity['token_version'],
                'auth_source': identity['source'],
            }
        self.addCleanup(websocket.websocket_connections.clear)

        def refresh_identity(*_args):
            with websocket.websocket_connections_lock:
                websocket.websocket_connections['refresh-sid']['token_version'] = 2
            return False

        socketio = FakeSocketIO()
        with patch.object(websocket, 'websocket_identity_still_valid', refresh_identity):
            self.assertEqual(websocket.reap_stale_connections(socketio), 0)

        self.assertEqual(socketio.server.disconnected, [])
        self.assertEqual(websocket.websocket_connections['refresh-sid']['token_version'], 2)

    def test_reaper_removes_revoked_connection_after_concurrent_activity(self):
        import websocket

        class FakeServer:
            def __init__(self):
                self.disconnected = []

            def disconnect(self, sid, namespace):
                self.disconnected.append((sid, namespace))

        class FakeSocketIO:
            def __init__(self):
                self.handlers = {}
                self.server = FakeServer()

            def on(self, event):
                def register(handler):
                    self.handlers[event] = handler
                    return handler
                return register

        socketio = FakeSocketIO()
        websocket.register_websocket_handlers(socketio)
        with websocket.websocket_connections_lock:
            websocket.websocket_connections['ping-sid'] = {
                'connected_at': datetime.now(),
                'last_activity': datetime(2026, 1, 1, 0, 9),
                'last_auth_check': datetime.now(),
                'timeout_seconds': websocket.WEBSOCKET_TIMEOUT_DEFAULT,
                'username': 'alice',
                'account_id': 7,
                'token_version': 1,
                'auth_source': 'db',
            }
        self.addCleanup(websocket.websocket_connections.clear)

        def fail_after_activity(*_args):
            socketio.handlers['activity']()
            return False

        with patch.object(websocket, 'request', SimpleNamespace(sid='ping-sid')), \
                patch.object(
                    websocket, 'websocket_identity_still_valid', fail_after_activity,
                ):
            self.assertEqual(
                websocket.reap_stale_connections(
                    socketio, current_time=datetime(2026, 1, 1, 0, 10),
                ),
                1,
            )

        self.assertEqual(socketio.server.disconnected, [('ping-sid', '/')])
        self.assertNotIn('ping-sid', websocket.websocket_connections)

    def test_activity_check_preserves_a_connection_refreshed_during_validation(self):
        import websocket

        class FakeSocketIO:
            def __init__(self):
                self.handlers = {}

            def on(self, event):
                def register(handler):
                    self.handlers[event] = handler
                    return handler
                return register

        socketio = FakeSocketIO()
        websocket.register_websocket_handlers(socketio)
        with websocket.websocket_connections_lock:
            websocket.websocket_connections['activity-sid'] = {
                'connected_at': datetime.now(),
                'last_activity': datetime.now(),
                'timeout_seconds': websocket.WEBSOCKET_TIMEOUT_DEFAULT,
                'username': 'alice',
                'account_id': 7,
                'token_version': 1,
                'auth_source': 'db',
            }
        self.addCleanup(websocket.websocket_connections.clear)

        def refresh_identity(*_args):
            with websocket.websocket_connections_lock:
                websocket.websocket_connections['activity-sid']['token_version'] = 2
            return False

        with patch.object(websocket, 'request', SimpleNamespace(sid='activity-sid')), \
                patch.object(websocket, 'websocket_identity_still_valid', refresh_identity), \
                patch.object(websocket, 'disconnect') as disconnect_socket:
            socketio.handlers['activity']()

        disconnect_socket.assert_not_called()
        self.assertEqual(websocket.websocket_connections['activity-sid']['token_version'], 2)


class LoginGuardTests(unittest.TestCase):
    def setUp(self):
        login_guard.reset()
        login_guard.configure(max_attempts=3, window_seconds=900, lockout_seconds=900, enabled=True)

    def tearDown(self):
        login_guard.reset()
        login_guard.configure(
            max_attempts=login_guard.DEFAULT_MAX_ATTEMPTS,
            window_seconds=login_guard.DEFAULT_WINDOW_SECONDS,
            lockout_seconds=login_guard.DEFAULT_LOCKOUT_SECONDS,
            enabled=True,
        )

    def test_attempts_are_allowed_until_the_limit(self):
        self.assertIsNone(login_guard.retry_after('alice', '10.0.0.1'))
        login_guard.record_failure('alice', '10.0.0.1')
        login_guard.record_failure('alice', '10.0.0.1')
        self.assertIsNone(login_guard.retry_after('alice', '10.0.0.1'))

    def test_the_limit_locks_further_attempts(self):
        for _ in range(3):
            login_guard.record_failure('alice', '10.0.0.1')

        wait = login_guard.retry_after('alice', '10.0.0.1')
        self.assertIsNotNone(wait)
        self.assertGreater(wait, 0)

    def test_a_lock_by_address_catches_attempts_on_other_usernames(self):
        for _ in range(3):
            login_guard.record_failure('alice', '10.0.0.1')

        self.assertIsNotNone(login_guard.retry_after('bob', '10.0.0.1'))

    def test_a_lock_by_username_catches_attempts_from_other_addresses(self):
        for index in range(3):
            login_guard.record_failure('alice', f'10.0.0.{index}')

        self.assertIsNotNone(login_guard.retry_after('alice', '10.9.9.9'))

    def test_an_unrelated_user_from_an_unrelated_address_is_unaffected(self):
        for _ in range(3):
            login_guard.record_failure('alice', '10.0.0.1')

        self.assertIsNone(login_guard.retry_after('bob', '10.0.0.2'))

    def test_success_clears_the_counters(self):
        login_guard.record_failure('alice', '10.0.0.1')
        login_guard.record_failure('alice', '10.0.0.1')
        login_guard.record_success('alice', '10.0.0.1')

        self.assertEqual(login_guard.failure_count('alice', '10.0.0.1'), 0)
        self.assertIsNone(login_guard.retry_after('alice', '10.0.0.1'))


class ActorTests(unittest.TestCase):
    """The vocabulary phase 2 records against."""

    def test_a_person_is_shown_under_their_own_name(self):
        actor = admin_actor('alice', 7)
        self.assertEqual(actor.kind, ACTOR_ADMIN)
        self.assertEqual(actor.label, 'alice')
        self.assertTrue(actor.is_human)
        self.assertEqual(actor.to_dict()['actor_account_id'], 7)

    def test_automation_is_badged_so_it_never_reads_as_a_colleague(self):
        actor = automated_actor('retention')
        self.assertEqual(actor.kind, ACTOR_AUTOMATED)
        self.assertEqual(actor.label, 'AUTO / retention')
        self.assertFalse(actor.is_human)

    def test_the_scheduler_and_webhooks_have_named_identities(self):
        self.assertEqual(AUTO_SYNC_SCHEDULER.label, 'AUTO / auto-sync')
        self.assertEqual(webhook_actor('movies').label, 'AUTO / webhook-movies')
        self.assertEqual(webhook_actor('series').label, 'AUTO / webhook-series')

    def test_the_application_itself_is_an_actor_too(self):
        self.assertEqual(SYSTEM_ACTOR.label, 'AUTO / system')
        self.assertFalse(SYSTEM_ACTOR.is_human)

    def test_no_account_id_is_ever_attached_to_automation(self):
        for actor in (AUTO_SYNC_SCHEDULER, SYSTEM_ACTOR, webhook_actor('anime')):
            self.assertIsNone(actor.to_dict()['actor_account_id'])


if __name__ == '__main__':
    unittest.main()
