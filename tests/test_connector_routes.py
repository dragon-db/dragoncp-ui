#!/usr/bin/env python3
"""
The connector HTTP layer.

One rule, and it is why this file exists separately from `test_connectors.py`:
**no response body ever contains a credential.** Every endpoint is exercised
against a store holding a real-looking webhook URL, and every byte that comes
back is searched for it.

Mounted on a bare Flask app rather than the real one, so nothing here touches
the live database or starts the transfer pipeline.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import auth
import routes.connectors as connector_routes
from models.connector import ConnectorStore
from models.database import DatabaseManager
from services.connectors.service import ConnectorService
from settings_registry import REDACTED

SECRET_URL = 'https://discord.com/api/webhooks/123456789/super-secret-token-value'
SECRET_KEY = 'sonarr-api-key-that-must-not-come-back'

SIGNED_IN_PAYLOAD = {'sub': 'tester', 'uid': 1, 'tv': 1, 'src': 'db', 'type': 'access'}
SIGNED_IN_IDENTITY = {
    'account_id': 1,
    'username': 'tester',
    'role': 'admin',
    'token_version': 1,
    'must_change_password': False,
    'source': 'db',
}


class FakeResponse:
    def __init__(self, status_code=204, text='', headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class ConnectorRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ConnectorStore(DatabaseManager(os.path.join(tmp.name, 'routes.db')))
        self.service = ConnectorService(self.store, synchronous=True)

        self.store.upsert_connector('discord', 'Discord', enabled=True)
        self.target = self.store.create_target('discord', 'general', SECRET_URL)
        self.store.upsert_connector('sonarr', 'Sonarr', enabled=True,
                                    config={'base_url': 'http://localhost:8989'})
        self.store.set_secret('sonarr', 'api_key', SECRET_KEY)

        connector_routes.init_connector_routes(self.service, self.store)

        app = Flask(__name__)
        app.register_blueprint(connector_routes.connectors_bp, url_prefix='/api')
        self.client = app.test_client()

        patcher_token = patch('auth.get_token_from_request', return_value='token')
        patcher_valid = patch('auth.validate_token', return_value=SIGNED_IN_PAYLOAD)
        patcher_identity = patch('auth.resolve_identity',
                                 return_value=(SIGNED_IN_IDENTITY, auth.REASON_OK))
        self.addCleanup(patcher_token.stop)
        self.addCleanup(patcher_valid.stop)
        self.addCleanup(patcher_identity.stop)
        self.token = patcher_token.start()
        patcher_valid.start()
        patcher_identity.start()

    def assertNoSecret(self, response, where):
        body = response.get_data(as_text=True)
        self.assertNotIn('super-secret-token-value', body, where)
        self.assertNotIn(SECRET_KEY, body, where)

    # -- the invariant -------------------------------------------------------

    def test_no_endpoint_hands_back_a_credential(self):
        """The single most important assertion in this file."""
        reads = [
            '/api/connectors',
            '/api/connectors/events',
            '/api/connectors/discord',
            '/api/connectors/sonarr',
            '/api/connectors/discord/deliveries',
        ]
        for path in reads:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNoSecret(response, path)

        saved = self.client.post('/api/connectors/sonarr',
                                 json={'config': {'base_url': 'http://localhost:8989'}})
        self.assertEqual(saved.status_code, 200)
        self.assertNoSecret(saved, 'save response')

        added = self.client.post('/api/connectors/discord/targets',
                                 json={'label': 'alerts', 'credential': SECRET_URL})
        self.assertEqual(added.status_code, 200)
        self.assertNoSecret(added, 'add target response')

    def test_a_stored_secret_is_reported_as_set_not_shown(self):
        response = self.client.get('/api/connectors/sonarr')
        connector = response.get_json()['connector']
        self.assertTrue(connector['secrets_set']['api_key'])
        self.assertNotIn('api_key', connector['config'])

    def test_the_redaction_placeholder_leaves_a_secret_alone(self):
        response = self.client.post('/api/connectors/sonarr',
                                    json={'config': {'api_key': REDACTED}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.secret('sonarr', 'api_key'), SECRET_KEY)

    def test_an_emptied_secret_really_is_cleared(self):
        """Disconnecting a service is an answer, not a declined change."""
        response = self.client.post('/api/connectors/sonarr', json={'config': {'api_key': ''}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.secret('sonarr', 'api_key'), '')

    # -- auth ----------------------------------------------------------------

    def test_every_endpoint_requires_a_session(self):
        self.token.return_value = None
        self.assertEqual(self.client.get('/api/connectors').status_code, 401)
        self.assertEqual(self.client.get('/api/connectors/discord').status_code, 401)
        self.assertEqual(self.client.post('/api/connectors/discord', json={}).status_code, 401)
        self.assertEqual(
            self.client.post('/api/connectors/discord/targets', json={}).status_code, 401)
        self.assertEqual(self.client.put('/api/connectors/routes', json={}).status_code, 401)

    # -- validation ----------------------------------------------------------

    def test_a_webhook_pointing_somewhere_else_is_refused(self):
        response = self.client.post('/api/connectors/discord/targets',
                                    json={'label': 'evil',
                                          'credential': 'https://evil.invalid/api/webhooks/1/x'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Discord', response.get_json()['message'])
        self.assertEqual(len(self.store.list_targets('discord')), 1)

    def test_two_destinations_cannot_share_a_name(self):
        response = self.client.post('/api/connectors/discord/targets',
                                    json={'label': 'General', 'credential': SECRET_URL})
        self.assertEqual(response.status_code, 400)
        self.assertIn('already', response.get_json()['message'])

    def test_a_connector_that_does_not_notify_has_no_destinations(self):
        response = self.client.post('/api/connectors/sonarr/targets',
                                    json={'label': 'x', 'credential': 'y'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('does not send notifications', response.get_json()['message'])

    def test_a_connector_with_nothing_to_reach_refuses_a_check(self):
        """Rather than answering OK. A test that cannot fail is worse than no
        test — it puts a green badge on something nothing verified."""
        response = self.client.post('/api/connectors/discord/check')
        self.assertEqual(response.status_code, 400)
        self.assertIn('webhook', response.get_json()['message'])

    def test_a_connector_describes_what_its_settings_form_is_called(self):
        """So the tab is named by the adapter rather than assumed to be
        "Connection" for a form that holds no connection details."""
        discord = self.client.get('/api/connectors/discord').get_json()['connector']
        self.assertEqual(discord['settings_label'], 'Appearance')
        self.assertFalse(discord['supports_check'])

        sonarr = self.client.get('/api/connectors/sonarr').get_json()['connector']
        self.assertEqual(sonarr['settings_label'], 'Connection')
        self.assertTrue(sonarr['supports_check'])

    def test_an_unknown_connector_is_a_404(self):
        self.assertEqual(self.client.get('/api/connectors/plex').status_code, 404)
        self.assertEqual(
            self.client.post('/api/connectors/plex', json={}).status_code, 404)

    def test_a_setting_the_connector_does_not_have_is_refused(self):
        response = self.client.post('/api/connectors/sonarr',
                                    json={'config': {'sudo_password': 'x'}})
        self.assertEqual(response.status_code, 400)
        self.assertIn('sudo_password', response.get_json()['message'])

    # -- testing what the form holds -------------------------------------------

    SONARR_STATUS = json.dumps({'appName': 'Sonarr', 'version': '4.0.0.0'})

    def _check(self, config=None):
        """Press Test connection, with the form's values when given."""
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(200, self.SONARR_STATUS)) as request:
            response = self.client.post('/api/connectors/sonarr/check',
                                        json=None if config is None else {'config': config})
        self.assertEqual(response.status_code, 200)
        self.assertNoSecret(response, 'check')
        return response.get_json()['result'], request

    def test_test_connection_reaches_the_address_typed_in_the_form(self):
        """Issue #63: it used to test only what was saved, and answered "Not
        configured yet" for a form someone had just filled in."""
        result, request = self._check({'base_url': 'http://elsewhere:8989',
                                       'api_key': REDACTED})
        self.assertTrue(result['ok'])
        self.assertTrue(result['unsaved'])
        url = request.call_args.args[1]
        self.assertTrue(url.startswith('http://elsewhere:8989/'), url)
        # The placeholder stands for the saved key, which the browser never had.
        self.assertEqual(request.call_args.kwargs['headers']['X-Api-Key'], SECRET_KEY)

    def test_testing_unsaved_values_saves_nothing(self):
        self._check({'base_url': 'http://elsewhere:8989', 'api_key': 'typed-but-not-saved'})
        saved = self.store.get_connector('sonarr')
        self.assertEqual(saved['config']['base_url'], 'http://localhost:8989')
        self.assertEqual(self.store.secret('sonarr', 'api_key'), SECRET_KEY)
        # The badge describes the saved connection, which nothing has tested.
        self.assertIsNone(saved['last_check_at'])

    def test_a_typed_key_is_the_one_tested(self):
        _, request = self._check({'base_url': 'http://localhost:8989',
                                  'api_key': 'typed-but-not-saved'})
        self.assertEqual(request.call_args.kwargs['headers']['X-Api-Key'],
                         'typed-but-not-saved')

    def test_testing_the_saved_values_records_the_last_check(self):
        result, _ = self._check({'base_url': 'http://localhost:8989', 'api_key': REDACTED,
                                 'auto_scanner_enabled': 'true'})
        self.assertFalse(result['unsaved'])
        self.assertTrue(self.store.get_connector('sonarr')['last_check_ok'])

    def test_a_check_with_no_form_tests_the_saved_settings(self):
        result, _ = self._check()
        self.assertTrue(result['ok'])
        self.assertFalse(result['unsaved'])
        self.assertTrue(self.store.get_connector('sonarr')['last_check_ok'])

    def test_a_form_without_a_key_is_not_tried_over_the_wire(self):
        with patch('services.connectors.transport.requests.request') as request:
            response = self.client.post('/api/connectors/radarr/check', json={
                'config': {'base_url': 'http://localhost:7878', 'api_key': ''}})
        request.assert_not_called()
        result = response.get_json()['result']
        self.assertFalse(result['ok'])
        self.assertEqual(result['message'], 'Not configured yet')

    def test_the_scanner_mode_saves_and_refuses_anything_else(self):
        fields = {f['name']: f for f in self.client.get('/api/connectors/sonarr')
                  .get_json()['connector']['config_fields']}
        mode = fields['auto_scanner_mode']
        self.assertEqual(mode['kind'], 'choice')
        self.assertEqual(mode['default'], 'alert')
        self.assertEqual([c['value'] for c in mode['choices']], ['alert', 'sync'])

        response = self.client.post('/api/connectors/sonarr',
                                    json={'config': {'auto_scanner_mode': 'sync'}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.get_connector('sonarr')['config']['auto_scanner_mode'],
                         'sync')
        response = self.client.post('/api/connectors/sonarr',
                                    json={'config': {'auto_scanner_mode': 'always'}})
        self.assertEqual(response.status_code, 400)
        self.assertIn('alert, sync', response.get_json()['message'])
        self.assertEqual(self.store.get_connector('sonarr')['config']['auto_scanner_mode'],
                         'sync')

    def test_a_check_refuses_a_setting_the_connector_does_not_have(self):
        response = self.client.post('/api/connectors/sonarr/check',
                                    json={'config': {'sudo_password': 'x'}})
        self.assertEqual(response.status_code, 400)
        self.assertIn('sudo_password', response.get_json()['message'])

    def test_the_activity_log_says_why_a_test_failed(self):
        """It said "Could not reach Sonarr" even when nothing was attempted."""
        with patch('routes.connectors.record_failure') as failed:
            self.client.post('/api/connectors/radarr/check', json={
                'config': {'base_url': 'http://localhost:7878', 'api_key': ''}})
        summary = failed.call_args.args[1]
        self.assertIn('Not configured yet', summary)
        self.assertNotIn('Could not reach', summary)

    def test_saving_a_new_address_forgets_the_last_check(self):
        self.store.record_check('sonarr', True, 'Connected to Sonarr 4.0.0.0')
        self.client.post('/api/connectors/sonarr',
                         json={'config': {'auto_scanner_enabled': 'true'}})
        self.assertTrue(self.store.get_connector('sonarr')['last_check_ok'])

        self.client.post('/api/connectors/sonarr',
                         json={'config': {'base_url': 'http://elsewhere:8989',
                                          'api_key': REDACTED}})
        self.assertIsNone(self.store.get_connector('sonarr')['last_check_at'])

    # -- who a message pings (issue #35) --------------------------------------

    ROLE_ID = '112233445566778899'

    def _add_admins(self):
        response = self.client.post('/api/connectors/discord/mentions', json={
            'label': 'Admins', 'kind': 'role', 'value': self.ROLE_ID})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['mention_id']

    def test_someone_to_ping_is_added_and_described(self):
        admins = self._add_admins()
        discord = self.client.get('/api/connectors/discord').get_json()['connector']
        self.assertTrue(discord['supports_mentions'])
        self.assertIn('role', discord['mention_kinds'])
        self.assertEqual([(m['mention_id'], m['label'], m['value'])
                          for m in discord['mentions']], [(admins, 'Admins', self.ROLE_ID)])

    def test_a_role_without_a_discord_id_is_refused(self):
        response = self.client.post('/api/connectors/discord/mentions', json={
            'label': 'Admins', 'kind': 'role', 'value': '@Admins'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('ID', response.get_json()['message'])

    def test_two_mentions_cannot_share_a_name(self):
        self._add_admins()
        response = self.client.post('/api/connectors/discord/mentions', json={
            'label': 'admins', 'kind': 'here'})
        self.assertEqual(response.status_code, 400)

    def test_a_service_that_cannot_ping_has_no_mentions(self):
        response = self.client.post('/api/connectors/sonarr/mentions', json={
            'label': 'Admins', 'kind': 'role', 'value': self.ROLE_ID})
        self.assertEqual(response.status_code, 400)

    def test_a_webhook_pings_its_own_people_and_its_test_says_so(self):
        admins = self._add_admins()
        response = self.client.patch(f'/api/connectors/discord/targets/{self.target}',
                                     json={'mention_ids': [admins]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.get_target(self.target)['mention_ids'], [admins])

        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)) as request:
            response = self.client.post(f'/api/connectors/discord/targets/{self.target}/test')
        self.assertNoSecret(response, 'target test')
        self.assertIn('pinging Admins', response.get_json()['message'])
        self.assertEqual(request.call_args.kwargs['json']['content'], f"<@&{self.ROLE_ID}>")

    def test_a_webhook_cannot_ping_someone_not_in_the_list(self):
        response = self.client.patch(f'/api/connectors/discord/targets/{self.target}',
                                     json={'mention_ids': ['men_nobody']})
        self.assertEqual(response.status_code, 400)

    def test_a_test_ping_reaches_the_chosen_webhook(self):
        admins = self._add_admins()
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)) as request:
            response = self.client.post(f'/api/connectors/discord/mentions/{admins}/test',
                                        json={'target_id': self.target})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNoSecret(response, 'mention test')
        sent = request.call_args.kwargs['json']
        self.assertEqual(sent['content'], f"<@&{self.ROLE_ID}>")
        self.assertEqual(sent['allowed_mentions']['roles'], [self.ROLE_ID])

    def test_routing_saves_when_and_whom_a_notification_pings(self):
        admins = self._add_admins()
        response = self.client.put('/api/connectors/routes', json={'routes': [{
            'event_key': 'transfer.completed', 'connector_id': 'discord',
            'target_id': None, 'enabled': True,
            'ping_when': 'always', 'mention_ids': [admins]}]})
        self.assertEqual(response.status_code, 200, response.get_json())

        catalogue = self.client.get('/api/connectors/events').get_json()
        done = next(e for e in catalogue['events'] if e['key'] == 'transfer.completed')
        self.assertEqual(done['default_ping'], 'never')
        self.assertEqual(done['routes']['discord']['ping_when'], 'always')
        self.assertEqual(done['routes']['discord']['mention_ids'], [admins])
        held = next(e for e in catalogue['events'] if e['key'] == 'sync.held')
        self.assertEqual(held['default_ping'], 'attention')
        self.assertIsNone(held['routes']['discord']['mention_ids'])

    def test_routing_refuses_an_unknown_ping_rule_or_person(self):
        for row in ({'ping_when': 'sometimes'}, {'mention_ids': ['men_nobody']}):
            response = self.client.put('/api/connectors/routes', json={'routes': [{
                'event_key': 'transfer.failed', 'connector_id': 'discord',
                'target_id': None, 'enabled': True, **row}]})
            self.assertEqual(response.status_code, 400, row)

    def test_removing_someone_clears_them_everywhere(self):
        admins = self._add_admins()
        self.store.update_target(self.target, mention_ids=[admins])
        response = self.client.delete(f'/api/connectors/discord/mentions/{admins}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.get_target(self.target)['mention_ids'], [])

    # -- destinations --------------------------------------------------------

    def test_setting_a_new_default_clears_the_old_one(self):
        added = self.client.post('/api/connectors/discord/targets',
                                 json={'label': 'alerts', 'credential': SECRET_URL})
        alerts = added.get_json()['target_id']

        self.client.patch(f'/api/connectors/discord/targets/{alerts}',
                          json={'make_default': True})

        targets = self.store.list_targets('discord')
        self.assertEqual([t['label'] for t in targets if t['is_default']], ['alerts'])

    def test_removing_the_default_promotes_another(self):
        self.client.post('/api/connectors/discord/targets',
                         json={'label': 'alerts', 'credential': SECRET_URL})
        response = self.client.delete(f'/api/connectors/discord/targets/{self.target}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.default_target('discord')['label'], 'alerts')

    def test_a_test_send_reports_what_discord_said(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)):
            ok = self.client.post(f'/api/connectors/discord/targets/{self.target}/test')
        self.assertEqual(ok.status_code, 200)

        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(404, SECRET_URL)):
            failed = self.client.post(f'/api/connectors/discord/targets/{self.target}/test')
        self.assertEqual(failed.status_code, 400)
        self.assertNoSecret(failed, 'failed test send')

    # -- routing -------------------------------------------------------------

    def test_the_catalogue_lists_every_notification(self):
        events = self.client.get('/api/connectors/events').get_json()['events']
        keys = {e['key'] for e in events}
        self.assertIn('transfer.failed', keys)
        self.assertIn('backup.retention_deleted', keys)
        # Every one says when it fires, because the routing table renders it.
        for event in events:
            self.assertTrue(event['description'])
            self.assertIn('discord', event['routes'])

    def test_routes_save_and_come_back(self):
        added = self.client.post('/api/connectors/discord/targets',
                                 json={'label': 'alerts', 'credential': SECRET_URL})
        alerts = added.get_json()['target_id']

        response = self.client.put('/api/connectors/routes', json={'routes': [
            {'event_key': 'transfer.failed', 'connector_id': 'discord',
             'target_id': alerts, 'enabled': True},
            {'event_key': 'transfer.completed', 'connector_id': 'discord',
             'target_id': None, 'enabled': False},
        ]})
        self.assertEqual(response.status_code, 200)

        events = {e['key']: e for e in
                  self.client.get('/api/connectors/events').get_json()['events']}
        self.assertEqual(events['transfer.failed']['routes']['discord']['target_id'], alerts)
        self.assertFalse(events['transfer.completed']['routes']['discord']['enabled'])
        self.assertTrue(events['transfer.completed']['routes']['discord']['using_default'])

    def test_an_unknown_notification_is_refused(self):
        response = self.client.put('/api/connectors/routes', json={'routes': [
            {'event_key': 'transfer.exploded', 'connector_id': 'discord',
             'target_id': None, 'enabled': True},
        ]})
        self.assertEqual(response.status_code, 400)

    def test_a_route_cannot_point_at_another_connectors_destination(self):
        response = self.client.put('/api/connectors/routes', json={'routes': [
            {'event_key': 'transfer.failed', 'connector_id': 'sonarr',
             'target_id': self.target, 'enabled': True},
        ]})
        self.assertEqual(response.status_code, 400)

    # -- listing -------------------------------------------------------------

    def test_every_connector_appears_even_when_never_saved(self):
        connectors = self.client.get('/api/connectors').get_json()['connectors']
        self.assertEqual({c['id'] for c in connectors},
                         {'discord', 'jellyfin', 'radarr', 'sonarr'})
        jellyfin = next(c for c in connectors if c['id'] == 'jellyfin')
        self.assertFalse(jellyfin['exists'])
        self.assertFalse(jellyfin['enabled'])

    def test_a_connectors_form_is_described_so_the_client_need_not_know_it(self):
        """A connector added on the backend must get a working settings page
        without the frontend being taught about it."""
        sonarr = self.client.get('/api/connectors/sonarr').get_json()['connector']
        names = {f['name']: f for f in sonarr['config_fields']}
        self.assertTrue(names['api_key']['secret'])
        self.assertTrue(names['api_key']['required'])
        self.assertFalse(names['base_url']['secret'])


if __name__ == '__main__':
    unittest.main()
