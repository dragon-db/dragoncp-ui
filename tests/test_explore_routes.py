#!/usr/bin/env python3
"""
The HTTP layer: auth, status codes and rate limiting.

Mounted on a bare Flask app rather than the real one so the test never touches
the live database or starts the transfer pipeline.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import auth
import routes.explore as explore_routes
from services.explore.service import ExploreError

#: One signed-in administrator, as require_auth sees them.
SIGNED_IN_PAYLOAD = {'sub': 'tester', 'uid': 1, 'tv': 1, 'src': 'db', 'type': 'access'}
SIGNED_IN_IDENTITY = {
    'account_id': 1,
    'username': 'tester',
    'role': 'admin',
    'token_version': 1,
    'must_change_password': False,
    'source': 'db',
}


class FakeService:
    def __init__(self):
        self.calls = []

    def libraries(self):
        return [{'id': 'tvshows', 'label': 'TV Shows'}]

    def tree(self, media_type, refresh=False):
        self.calls.append(('tree', media_type, refresh))
        if media_type == 'podcasts':
            raise ExploreError("Unknown library 'podcasts'", 404)
        return {'media_type': media_type, 'series': [], 'checked_at': None, 'stale': False}

    def series(self, media_type, folder):
        raise ExploreError('No remote browse session. Connect in Settings and try again.', 409)

    def season(self, media_type, folder, season):
        return {'name': season, 'episodes': []}

    def history(self, media_type, folder, season=None):
        return []

    def plan(self, **kwargs):
        self.calls.append(('plan', kwargs))
        return {'plan_id': 'plan_abc', 'safe': True, 'verdict': 'downloads 1, removes nothing.'}

    def execute(self, plan_id, override=False, confirm_text=None):
        self.calls.append(('execute', plan_id, override, confirm_text))
        if plan_id == 'expired':
            raise ExploreError('That plan has expired or was already used.', 409)
        return {'message': 'Transfer started', 'transfer_id': 't1',
                'operation': 'sync_season', 'series': 'Show'}


class ExploreRouteTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()
        explore_routes.init_explore_routes(self.service)
        explore_routes._HITS.clear()

        app = Flask(__name__)
        app.register_blueprint(explore_routes.explore_bp, url_prefix='/api')
        self.client = app.test_client()

        # require_auth resolves these from the auth module at call time. A valid
        # token is no longer enough on its own: the account behind it is looked
        # up on every request, so the identity has to be stubbed as well.
        patcher_token = patch('auth.get_token_from_request', return_value='token')
        patcher_valid = patch('auth.validate_token', return_value=SIGNED_IN_PAYLOAD)
        patcher_identity = patch(
            'auth.resolve_identity',
            return_value=(SIGNED_IN_IDENTITY, auth.REASON_OK),
        )
        self.addCleanup(patcher_token.stop)
        self.addCleanup(patcher_valid.stop)
        self.addCleanup(patcher_identity.stop)
        self.token = patcher_token.start()
        self.valid = patcher_valid.start()
        patcher_identity.start()

    def test_every_endpoint_requires_a_session(self):
        self.token.return_value = None
        for path in ('/api/explore/libraries', '/api/explore/tree/tvshows',
                     '/api/explore/history/tvshows/Show'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.post('/api/explore/plan', json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/explore/transfer', json={}).status_code, 401)

    def test_reads_return_their_payload(self):
        response = self.client.get('/api/explore/tree/tvshows')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['media_type'], 'tvshows')

    def test_an_unknown_library_is_404_not_200_with_an_error_body(self):
        response = self.client.get('/api/explore/tree/podcasts')
        self.assertEqual(response.status_code, 404)

    def test_a_missing_browse_session_is_409(self):
        response = self.client.get('/api/explore/series/tvshows/Show')
        self.assertEqual(response.status_code, 409)
        self.assertIn('browse session', response.get_json()['message'])

    def test_refresh_is_rate_limited_but_cached_reads_are_not(self):
        for _ in range(explore_routes._MAX_COMPARISONS):
            self.assertEqual(self.client.get('/api/explore/tree/tvshows?refresh=1').status_code, 200)

        limited = self.client.get('/api/explore/tree/tvshows?refresh=1')
        self.assertEqual(limited.status_code, 429)
        self.assertIn('retry_after', limited.get_json())

        # Reading the cached comparison costs the media server nothing.
        self.assertEqual(self.client.get('/api/explore/tree/tvshows').status_code, 200)

    def test_plan_passes_the_request_through_and_returns_an_id(self):
        response = self.client.post('/api/explore/plan', json={
            'media_type': 'tvshows', 'operation': 'sync_season',
            'folder': 'Show', 'season': 'Season 01',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['plan']['plan_id'], 'plan_abc')
        kwargs = [c for c in self.service.calls if c[0] == 'plan'][0][1]
        self.assertEqual(kwargs['folder'], 'Show')
        self.assertEqual(kwargs['created_by'], 'tester')

    def test_transfer_needs_a_plan_id(self):
        response = self.client.post('/api/explore/transfer', json={})
        self.assertEqual(response.status_code, 400)

    def test_transfer_quotes_a_plan_rather_than_describing_the_work(self):
        response = self.client.post('/api/explore/transfer', json={'plan_id': 'plan_abc'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['transfer_id'], 't1')

    def test_a_used_or_expired_plan_is_409(self):
        response = self.client.post('/api/explore/transfer', json={'plan_id': 'expired'})
        self.assertEqual(response.status_code, 409)


if __name__ == '__main__':
    unittest.main()
