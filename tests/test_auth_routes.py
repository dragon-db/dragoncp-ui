#!/usr/bin/env python3
"""
The sign-in HTTP layer: logging in, changing your own password, and being shut out.

Mounted on a bare Flask app rather than the real one so the test never touches
the live database or starts the transfer pipeline.

The cases worth stating outright:

  Changing your own password hands back a working session. The change retires
  every token the account held — including the caller's — so without a fresh
  pair in the response, succeeding would bounce the person to the sign-in screen
  for doing the right thing.

  Nothing here can change anyone else's password, or create, rename or disable
  an account. That is `scripts/manage_admins.py`, on the server, on purpose.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, g

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import auth
import login_guard
from models.admin_account import AdminAccount
from models.database import DatabaseManager
from routes.auth import auth_bp


TEST_AUTH_CONFIG = {
    'username': 'envadmin',
    'password_hash': '',
    'password_plain': 'env-fallback-password',
    'jwt_secret': 'test-secret-key-for-auth-route-tests',
    'jwt_expiry_hours': 24,
    'jwt_algorithm': 'HS256',
    'login_max_attempts': 5,
    'login_window_minutes': 15,
    'login_lockout_minutes': 15,
}

GOOD_PASSWORD = 'correct-horse-battery'


class AuthRouteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        with patch('builtins.print'):
            self.db = DatabaseManager(os.path.join(self._tmp.name, 'auth_routes.db'))

        self.store = AdminAccount(self.db)
        auth.set_account_store(self.store)
        self.addCleanup(auth.set_account_store, None)

        config_patch = patch.object(auth, 'get_auth_config', return_value=dict(TEST_AUTH_CONFIG))
        config_patch.start()
        self.addCleanup(config_patch.stop)

        print_patch = patch('builtins.print')
        print_patch.start()
        self.addCleanup(print_patch.stop)

        login_guard.reset()
        login_guard.configure(max_attempts=3, window_seconds=900, lockout_seconds=900, enabled=True)
        self.addCleanup(login_guard.reset)

        app = Flask(__name__)
        app.register_blueprint(auth_bp, url_prefix='/api')

        # A stand-in for any ordinary protected endpoint. Registered here
        # because Flask will not accept new routes once a request has been
        # served, and it lets these tests exercise the gate without dragging in
        # a real feature blueprint.
        @app.route('/api/guarded')
        @auth.require_auth
        def _guarded():
            return {'status': 'success', 'user': g.current_user}

        self.client = app.test_client()

    # ---- helpers ----

    def make_account(self, username='alice', password=GOOD_PASSWORD, **kwargs):
        return self.store.create(username, auth.hash_password(password), **kwargs)

    def login(self, username='alice', password=GOOD_PASSWORD):
        return self.client.post(
            '/api/auth/login', json={'username': username, 'password': password}
        )

    def signed_in_headers(self, username='alice', password=GOOD_PASSWORD):
        body = self.login(username, password).get_json()
        return {'Authorization': f"Bearer {body['token']}"}

    # ---- signing in ----

    def test_a_named_account_can_sign_in(self):
        self.make_account('alice')

        response = self.login()
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body['user'], 'alice')
        self.assertIsNotNone(body['token'])
        self.assertIsNotNone(body['account_id'])
        self.assertFalse(body['is_fallback_account'])

    def test_two_people_can_be_signed_in_at_once_as_themselves(self):
        self.make_account('alice', GOOD_PASSWORD, must_change_password=False)
        self.make_account('bob', 'a-different-password', must_change_password=False)

        alice = self.client.get('/api/auth/me', headers=self.signed_in_headers('alice'))
        bob = self.client.get(
            '/api/auth/me', headers=self.signed_in_headers('bob', 'a-different-password')
        )

        self.assertEqual(alice.get_json()['user'], 'alice')
        self.assertEqual(bob.get_json()['user'], 'bob')
        self.assertNotEqual(alice.get_json()['account_id'], bob.get_json()['account_id'])

    def test_a_wrong_password_is_refused(self):
        self.make_account('alice')
        response = self.login('alice', 'not-the-password')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['code'], 'INVALID_CREDENTIALS')

    def test_a_disabled_account_cannot_sign_in(self):
        account = self.make_account('alice')
        self.store.set_active(account['id'], False)

        self.assertEqual(self.login().status_code, 401)

    def test_the_fallback_account_signs_in_while_no_accounts_exist(self):
        response = self.login('envadmin', 'env-fallback-password')
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body['is_fallback_account'])
        self.assertIsNone(body['account_id'])

    def test_malformed_unicode_password_reaches_the_normal_unauthenticated_path(self):
        response = self.login('envadmin', '\ud800')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['code'], 'INVALID_CREDENTIALS')

    def test_malformed_unicode_stored_fallback_password_is_refused(self):
        malformed_config = dict(TEST_AUTH_CONFIG, password_plain='\ud800')
        with patch.object(auth, 'get_auth_config', return_value=malformed_config):
            response = self.login('envadmin', 'ordinary-password')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['code'], 'INVALID_CREDENTIALS')

    def test_a_new_account_is_asked_to_choose_its_own_password(self):
        self.make_account('alice')  # must_change_password defaults to True

        self.assertTrue(self.login().get_json()['must_change_password'])

    # ---- brute force ----

    def test_repeated_failures_are_throttled(self):
        # Three attempts are allowed. The third is the one that locks, and it
        # says so rather than answering "wrong password" and leaving the person
        # to discover the lockout on their next try.
        self.make_account('alice')

        for _ in range(2):
            self.assertEqual(self.login('alice', 'wrong-password').status_code, 401)

        locking = self.login('alice', 'wrong-password')
        self.assertEqual(locking.status_code, 429)
        self.assertEqual(locking.get_json()['code'], 'TOO_MANY_ATTEMPTS')
        self.assertGreater(locking.get_json()['retry_after'], 0)

        blocked = self.login('alice', 'wrong-password')
        self.assertEqual(blocked.status_code, 429)
        self.assertGreater(blocked.get_json()['retry_after'], 0)

    def test_a_throttled_caller_cannot_get_in_with_the_right_password(self):
        # The point of the throttle: it gates the endpoint, not just the guess.
        self.make_account('alice')

        for _ in range(3):
            self.login('alice', 'wrong-password')

        self.assertEqual(self.login('alice', GOOD_PASSWORD).status_code, 429)

    def test_signing_in_successfully_clears_the_count(self):
        self.make_account('alice')

        self.login('alice', 'wrong-password')
        self.login('alice', 'wrong-password')
        self.assertEqual(self.login().status_code, 200)

        # Back to a full allowance rather than one mistake from a lockout.
        self.login('alice', 'wrong-password')
        self.assertEqual(self.login().status_code, 200)

    # ---- sessions ending when the account changes ----

    def test_disabling_an_account_stops_its_requests_at_once(self):
        account = self.make_account('alice', GOOD_PASSWORD, must_change_password=False)
        headers = self.signed_in_headers()

        self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 200)

        self.store.set_active(account['id'], False)

        refused = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(refused.status_code, 401)
        self.assertEqual(refused.get_json()['code'], 'ACCOUNT_DISABLED')

    def test_a_disabled_account_cannot_refresh_its_way_back_in(self):
        account = self.make_account('alice', GOOD_PASSWORD, must_change_password=False)
        refresh_token = self.login().get_json()['refresh_token']

        self.store.set_active(account['id'], False)

        response = self.client.post('/api/auth/refresh', json={'refresh_token': refresh_token})
        self.assertEqual(response.status_code, 401)

    def test_verify_reports_a_revoked_session_as_invalid(self):
        account = self.make_account('alice', GOOD_PASSWORD, must_change_password=False)
        headers = self.signed_in_headers()

        self.assertTrue(self.client.get('/api/auth/verify', headers=headers).get_json()['valid'])

        self.store.set_active(account['id'], False)

        body = self.client.get('/api/auth/verify', headers=headers).get_json()
        self.assertFalse(body['valid'])

    def test_renaming_an_account_ends_its_session(self):
        self.make_account('bob', GOOD_PASSWORD, must_change_password=False)
        headers = self.signed_in_headers('bob')

        self.store.rename('bob', 'bob.smith')

        response = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['code'], 'SESSION_REVOKED')

    # ---- changing your own password ----

    def test_changing_your_password_keeps_you_signed_in(self):
        self.make_account('alice', GOOD_PASSWORD, must_change_password=False)
        headers = self.signed_in_headers()

        response = self.client.post(
            '/api/auth/change-password',
            json={'current_password': GOOD_PASSWORD, 'new_password': 'a-brand-new-password'},
            headers=headers,
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(body['token'])
        self.assertFalse(body['must_change_password'])

        # The replacement token works; the one used to make the change does not.
        new_headers = {'Authorization': f"Bearer {body['token']}"}
        self.assertEqual(self.client.get('/api/auth/me', headers=new_headers).status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 401)

    def test_the_new_password_is_what_signs_you_in_afterwards(self):
        self.make_account('alice', GOOD_PASSWORD, must_change_password=False)

        self.client.post(
            '/api/auth/change-password',
            json={'current_password': GOOD_PASSWORD, 'new_password': 'a-brand-new-password'},
            headers=self.signed_in_headers(),
        )
        login_guard.reset()

        self.assertEqual(self.login('alice', 'a-brand-new-password').status_code, 200)
        self.assertEqual(self.login('alice', GOOD_PASSWORD).status_code, 401)

    def test_changing_a_password_clears_the_must_change_flag(self):
        self.make_account('alice', GOOD_PASSWORD)  # starts flagged
        headers = self.signed_in_headers()

        body = self.client.post(
            '/api/auth/change-password',
            json={'current_password': GOOD_PASSWORD, 'new_password': 'a-brand-new-password'},
            headers=headers,
        ).get_json()

        self.assertFalse(body['must_change_password'])

    def test_the_current_password_must_be_right(self):
        self.make_account('alice', GOOD_PASSWORD, must_change_password=False)

        response = self.client.post(
            '/api/auth/change-password',
            json={'current_password': 'not-it', 'new_password': 'a-brand-new-password'},
            headers=self.signed_in_headers(),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['code'], 'INVALID_CREDENTIALS')

    def test_a_short_new_password_is_refused(self):
        self.make_account('alice', GOOD_PASSWORD, must_change_password=False)

        response = self.client.post(
            '/api/auth/change-password',
            json={'current_password': GOOD_PASSWORD, 'new_password': 'short'},
            headers=self.signed_in_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'WEAK_PASSWORD')

    def test_reusing_the_same_password_is_refused(self):
        self.make_account('alice', GOOD_PASSWORD, must_change_password=False)

        response = self.client.post(
            '/api/auth/change-password',
            json={'current_password': GOOD_PASSWORD, 'new_password': GOOD_PASSWORD},
            headers=self.signed_in_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'PASSWORD_UNCHANGED')

    def test_the_fallback_account_is_told_where_to_go_instead(self):
        # Its password lives in the environment file; there is nothing to change.
        headers = self.signed_in_headers('envadmin', 'env-fallback-password')

        response = self.client.post(
            '/api/auth/change-password',
            json={'current_password': 'env-fallback-password', 'new_password': 'something-else-1'},
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'FALLBACK_ACCOUNT')
        self.assertIn('manage_admins.py', response.get_json()['message'])

    def test_changing_a_password_needs_a_session(self):
        self.make_account('alice')

        response = self.client.post(
            '/api/auth/change-password',
            json={'current_password': GOOD_PASSWORD, 'new_password': 'a-brand-new-password'},
        )

        self.assertEqual(response.status_code, 401)

    # ---- the first password change is enforced, not merely suggested ----

    def test_an_account_owing_a_password_change_cannot_do_anything_else(self):
        # The password was chosen by whoever ran the script, so two people know
        # it and nothing done under it is unambiguously this person's. The
        # browser holds them at a password screen; this is what makes that more
        # than a suggestion.
        self.make_account('alice')  # must_change_password defaults to True
        headers = self.signed_in_headers()

        response = self.client.get('/api/guarded', headers=headers)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['code'], 'PASSWORD_CHANGE_REQUIRED')

    def test_they_can_still_reach_what_clears_it(self):
        # Blocking the password screen itself would lock them out of the only
        # thing that satisfies the requirement.
        self.make_account('alice')
        headers = self.signed_in_headers()

        self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 200)
        self.assertEqual(self.client.post('/api/auth/logout', headers=headers).status_code, 200)

    def test_changing_the_password_lifts_the_block(self):
        self.make_account('alice')
        headers = self.signed_in_headers()

        self.assertEqual(self.client.get('/api/guarded', headers=headers).status_code, 403)

        body = self.client.post(
            '/api/auth/change-password',
            json={'current_password': GOOD_PASSWORD, 'new_password': 'a-brand-new-password'},
            headers=headers,
        ).get_json()

        new_headers = {'Authorization': f"Bearer {body['token']}"}
        allowed = self.client.get('/api/guarded', headers=new_headers)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()['user'], 'alice')

    def test_an_account_created_without_the_requirement_works_immediately(self):
        self.make_account('alice', GOOD_PASSWORD, must_change_password=False)

        response = self.client.get('/api/guarded', headers=self.signed_in_headers())
        self.assertEqual(response.status_code, 200)

    # ---- status ----

    def test_status_reports_how_sign_in_is_configured(self):
        empty = self.client.get('/api/auth/status').get_json()
        self.assertTrue(empty['auth_configured'])
        self.assertEqual(empty['account_count'], 0)
        self.assertTrue(empty['using_fallback_account'])

        self.make_account('alice')

        configured = self.client.get('/api/auth/status').get_json()
        self.assertEqual(configured['account_count'], 1)
        self.assertFalse(configured['using_fallback_account'])


if __name__ == '__main__':
    unittest.main()
