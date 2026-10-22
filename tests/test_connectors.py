#!/usr/bin/env python3
"""
The connector layer: one way to talk to an outside service.

Five things these tests exist to hold down, in order of how much it would cost
to get them wrong:

  1. A credential never leaves the server. A Discord webhook URL *is* the
     credential — there is no separate token to hide — and the code this
     replaced printed it beside the response body on every failure.
  2. Nothing raises. Every caller is a background thread or an HTTP request
     that must survive Discord being down.
  3. A missing route means the default, not silence. The whole point of the
     layer is that an announcement cannot vanish without trace.
  4. The upgrade is invisible. An operator with a working webhook must not
     notice anything changed.
  5. Discord's own limits are respected, so one long path cannot cost the
     operator an entire message.
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.connector import DELIVERY_HISTORY_LIMIT, ConnectorStore
from models.database import DatabaseManager
from services.connectors import registry, routing, transport
from services.connectors.adapters.discord import (
    MAX_FIELD_VALUE,
    DiscordConnector,
    is_valid_app_url,
)
from services.connectors.base import (
    CheckResult,
    ConfigField,
    Connector,
    DeliveryResult,
    Mention,
    NotifyingConnector,
    Target,
)
from services.connectors.dispatch import Dispatcher
from services.connectors.events import (
    ACCENT_RENAME,
    CATALOGUE,
    EVENT_KEYS,
    FAILURE,
    SUCCESS,
    WARNING,
    Event,
    Field,
)
from services.connectors.service import ConnectorService
from services.connectors.transport import TransportResult, redact_url

SECRET_URL = 'https://discord.com/api/webhooks/123456789/super-secret-token-value'


class FakeResponse:
    def __init__(self, status_code=204, text='', headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def store_with_db(case):
    """A ConnectorStore backed by a throwaway database."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    db = DatabaseManager(os.path.join(tmp.name, 'connectors_test.db'))
    return ConnectorStore(db), db


# ===========================================================================
# Transport
# ===========================================================================

class RedactionTests(unittest.TestCase):
    def test_a_webhook_token_is_not_in_the_redacted_url(self):
        redacted = redact_url(SECRET_URL)
        self.assertNotIn('super-secret-token-value', redacted)
        self.assertNotIn('123456789', redacted)
        # Still says which service, which is the point of keeping any of it.
        self.assertIn('discord.com', redacted)

    def test_a_query_string_is_dropped_entirely(self):
        self.assertNotIn('token', redact_url('https://host.invalid/api/x?token=abc'))

    def test_nonsense_does_not_raise(self):
        self.assertEqual(redact_url('not a url'), '<invalid url>')
        self.assertEqual(redact_url(''), '')
        self.assertEqual(redact_url(None), '')


class TransportTests(unittest.TestCase):
    def test_a_refused_connection_returns_rather_than_raising(self):
        import requests as real_requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=real_requests.ConnectionError('boom')):
            result = transport.send('POST', SECRET_URL, max_retries=0)
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)

    def test_a_timeout_returns_rather_than_raising(self):
        import requests as real_requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=real_requests.Timeout()):
            result = transport.send('POST', SECRET_URL, max_retries=0)
        self.assertFalse(result.ok)
        self.assertIn('did not answer', result.error)

    def test_no_error_message_anywhere_contains_the_credential(self):
        """The single most important assertion in this file."""
        import requests as real_requests
        cases = [
            {'side_effect': real_requests.ConnectionError(SECRET_URL)},
            {'side_effect': real_requests.Timeout(SECRET_URL)},
            {'side_effect': ValueError(SECRET_URL)},
            {'return_value': FakeResponse(404, 'not found')},
            {'return_value': FakeResponse(401, 'unauthorized')},
            {'return_value': FakeResponse(500, 'server error')},
        ]
        for case in cases:
            with patch('services.connectors.transport.requests.request', **case):
                result = transport.send('POST', SECRET_URL, max_retries=0, expect=(204,))
            self.assertFalse(result.ok)
            self.assertNotIn('super-secret-token-value', result.error or '')

    def test_a_429_is_retried_once_and_the_wait_is_honoured(self):
        responses = [FakeResponse(429, headers={'Retry-After': '0.01'}),
                     FakeResponse(204)]
        with patch('services.connectors.transport.requests.request',
                   side_effect=responses) as request:
            with patch('services.connectors.transport.time.sleep') as sleep:
                result = transport.send('POST', SECRET_URL, expect=(204,))
        self.assertTrue(result.ok)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    def test_a_wait_longer_than_the_cap_is_shortened(self):
        """A multi-minute Retry-After would stall every message behind it."""
        responses = [FakeResponse(429, headers={'Retry-After': '600'}),
                     FakeResponse(204)]
        with patch('services.connectors.transport.requests.request',
                   side_effect=responses):
            with patch('services.connectors.transport.time.sleep') as sleep:
                transport.send('POST', SECRET_URL, expect=(204,))
        self.assertLessEqual(sleep.call_args[0][0], transport.MAX_RETRY_AFTER)

    def test_a_404_is_not_retried(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(404)) as request:
            transport.send('POST', SECRET_URL, expect=(204,))
        self.assertEqual(request.call_count, 1, 'a wrong request stays wrong')

    def test_discord_answering_200_is_not_success(self):
        """A webhook answers 204. Anything else is not the endpoint it claims."""
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(200, 'a login page')):
            result = transport.send('POST', SECRET_URL, expect=(204,), max_retries=0)
        self.assertFalse(result.ok)

    def test_a_long_json_body_still_parses(self):
        """The cap is for what a human reads, not for what a parser gets.

        Sonarr's status document is 836 bytes. Capping before parsing truncated
        it mid-object, `json` came back None, and every read reported "something
        answered, but it was not this service" against a service that had
        answered perfectly.
        """
        document = {'appName': 'Sonarr', 'version': '4.0.0.0',
                    'padding': 'x' * (transport.MAX_BODY_CHARS * 2)}
        text = json.dumps(document)
        self.assertGreater(len(text), transport.MAX_BODY_CHARS)

        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(200, text)):
            result = transport.send('GET', SECRET_URL, max_retries=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.json['version'], '4.0.0.0')

    def test_the_kept_body_is_still_capped(self):
        """Parsing the whole response must not mean storing the whole response."""
        text = json.dumps({'padding': 'x' * (transport.MAX_BODY_CHARS * 3)})
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(200, text)):
            result = transport.send('GET', SECRET_URL, max_retries=0)
        self.assertLessEqual(len(result.body), transport.MAX_BODY_CHARS)

    def test_a_body_that_is_not_json_reads_as_none(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(200, '<html>a login page</html>')):
            result = transport.send('GET', SECRET_URL, max_retries=0)
        self.assertIsNone(result.json)

    def test_a_long_error_document_is_readable_too(self):
        """A service that explains itself in JSON should be readable when it fails."""
        text = json.dumps({'message': 'y' * (transport.MAX_BODY_CHARS * 2),
                            'reason': 'unauthorised'})
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(401, text)):
            result = transport.send('GET', SECRET_URL, max_retries=0)
        self.assertFalse(result.ok)
        self.assertEqual(result.json['reason'], 'unauthorised')


# ===========================================================================
# Events and registry
# ===========================================================================

class EventTests(unittest.TestCase):
    def test_an_unknown_key_is_refused_at_construction(self):
        """A typo would route nowhere and be dropped silently, which is the
        one failure this whole layer exists to remove."""
        with self.assertRaises(ValueError):
            Event(key='transfer.exploded', severity=SUCCESS, title='x')

    def test_an_unknown_severity_is_refused(self):
        with self.assertRaises(ValueError):
            Event(key='transfer.completed', severity='catastrophic', title='x')

    def test_the_catalogue_has_no_duplicates(self):
        self.assertEqual(len(EVENT_KEYS), len(set(EVENT_KEYS)))

    def test_every_catalogue_entry_describes_itself_for_an_operator(self):
        for entry in CATALOGUE:
            self.assertTrue(entry.label, entry.key)
            self.assertGreater(len(entry.description), 20, entry.key)


class RegistryTests(unittest.TestCase):
    def test_the_four_connectors_are_registered(self):
        self.assertEqual(
            sorted(registry.known_ids()),
            ['discord', 'jellyfin', 'radarr', 'sonarr'],
        )

    def test_two_adapters_cannot_claim_one_id(self):
        """Import order would otherwise decide which one is reachable."""
        with self.assertRaises(ValueError):
            @registry.register
            class Impostor(Connector):
                id = 'discord'

    def test_an_adapter_without_an_id_is_refused(self):
        with self.assertRaises(ValueError):
            @registry.register
            class Nameless(Connector):
                pass


# ===========================================================================
# The Discord adapter
# ===========================================================================

class DiscordRenderingTests(unittest.TestCase):
    def setUp(self):
        self.adapter = DiscordConnector(
            config={'app_url': 'http://localhost:5000',
                    'icon_url': 'https://example.invalid/icon.png'},
            secrets=lambda name: '',
        )

    def embed(self, event):
        return self.adapter.render(event)['embeds'][0]

    def test_a_finished_sync_keeps_the_colour_it_always_had(self):
        embed = self.embed(Event(key='transfer.completed', severity=SUCCESS,
                                 title='Example Show'))
        self.assertEqual(embed['color'], 11164867)

    def test_a_failed_sync_keeps_the_colour_it_always_had(self):
        embed = self.embed(Event(key='transfer.failed', severity=FAILURE,
                                 title='Example Show'))
        self.assertEqual(embed['color'], 15158332)

    def test_a_finished_rename_is_a_different_colour_from_a_finished_sync(self):
        """They are both successes and were deliberately told apart."""
        rename = self.embed(Event(key='rename.finished', severity=SUCCESS,
                                  title='Example Show', accent=ACCENT_RENAME))
        sync = self.embed(Event(key='transfer.completed', severity=SUCCESS,
                                title='Example Show'))
        self.assertEqual(rename['color'], 1752220)
        self.assertNotEqual(rename['color'], sync['color'])

    def test_a_monospace_field_is_a_code_block(self):
        embed = self.embed(Event(
            key='transfer.failed', severity=FAILURE, title='Example Show',
            fields=(Field('Error Details', 'rsync: some failure', monospace=True),),
        ))
        value = embed['fields'][0]['value']
        self.assertTrue(value.startswith('```\n'))
        self.assertTrue(value.endswith('\n```'))
        self.assertIn('rsync: some failure', value)

    def test_a_long_field_fits_inside_the_limit_with_its_fences(self):
        """Truncating and then wrapping is how a message gets rejected for
        being 1030 characters long."""
        embed = self.embed(Event(
            key='transfer.failed', severity=FAILURE, title='Example Show',
            fields=(Field('Error Details', 'x' * 5000, monospace=True),),
        ))
        self.assertLessEqual(len(embed['fields'][0]['value']), MAX_FIELD_VALUE)

    def test_a_long_plain_field_is_clipped_too(self):
        embed = self.embed(Event(
            key='transfer.completed', severity=SUCCESS, title='Example Show',
            fields=(Field('Folder Synced', '/' + 'a' * 5000),),
        ))
        self.assertLessEqual(len(embed['fields'][0]['value']), MAX_FIELD_VALUE)

    def test_a_very_long_title_is_clipped(self):
        embed = self.embed(Event(key='transfer.completed', severity=SUCCESS,
                                 title='A' * 900))
        self.assertLessEqual(len(embed['title']), 256)

    def test_no_more_than_discord_accepts(self):
        fields = tuple(Field(f'F{i}', str(i)) for i in range(40))
        embed = self.embed(Event(key='transfer.completed', severity=SUCCESS,
                                 title='Example Show', fields=fields))
        self.assertLessEqual(len(embed['fields']), 25)

    def test_the_author_icon_comes_from_the_connector_settings(self):
        embed = self.embed(Event(key='transfer.completed', severity=SUCCESS,
                                 title='Example Show', author='Manual sync - Explore'))
        # Upper case however a sender wrote it: one style on every message.
        self.assertEqual(embed['author']['name'], 'MANUAL SYNC - EXPLORE')
        self.assertEqual(embed['author']['icon_url'], 'https://example.invalid/icon.png')

    def test_a_bad_app_url_costs_the_link_and_nothing_else(self):
        """Discord rejects the whole message for a malformed embed URL."""
        adapter = DiscordConnector(config={'app_url': 'not a url'}, secrets=lambda n: '')
        embed = adapter.render(Event(key='transfer.completed', severity=SUCCESS,
                                     title='Example Show'))['embeds'][0]
        self.assertNotIn('url', embed)
        self.assertEqual(embed['title'], 'Example Show')

    def test_an_event_poster_beats_the_default_thumbnail(self):
        adapter = DiscordConnector(
            config={'manual_sync_thumbnail_url': 'https://example.invalid/default.png'},
            secrets=lambda n: '',
        )
        embed = adapter.render(Event(
            key='transfer.completed', severity=SUCCESS, title='Example Show',
            thumbnail_url='https://example.invalid/poster.png',
        ))['embeds'][0]
        self.assertEqual(embed['thumbnail']['url'], 'https://example.invalid/poster.png')

    def test_an_empty_field_value_reads_as_not_available(self):
        embed = self.embed(Event(key='transfer.completed', severity=SUCCESS,
                                 title='Example Show', fields=(Field('Speed', ''),)))
        self.assertEqual(embed['fields'][0]['value'], 'N/A')


class DiscordTargetValidationTests(unittest.TestCase):
    """The server posts to whatever is stored, so this is where it is decided
    where it may be pointed."""

    def setUp(self):
        self.adapter = DiscordConnector()

    def test_a_real_webhook_url_is_accepted(self):
        self.assertIsNone(self.adapter.validate_target(SECRET_URL))
        self.assertIsNone(self.adapter.validate_target(
            'https://discordapp.com/api/webhooks/1/abc'))
        self.assertIsNone(self.adapter.validate_target(
            'https://canary.discord.com/api/webhooks/1/abc'))

    def test_somewhere_else_entirely_is_refused(self):
        for url in ('https://evil.invalid/api/webhooks/1/abc',
                    'https://192.168.1.1/api/webhooks/1/abc',
                    'https://discord.com.evil.invalid/api/webhooks/1/abc'):
            self.assertIsNotNone(self.adapter.validate_target(url), url)

    def test_plain_http_is_refused(self):
        self.assertIsNotNone(self.adapter.validate_target(
            'http://discord.com/api/webhooks/1/abc'))

    def test_a_discord_link_that_is_not_a_webhook_is_refused(self):
        self.assertIsNotNone(self.adapter.validate_target(
            'https://discord.com/channels/1/2'))

    def test_nothing_is_refused_with_a_useful_message(self):
        reason = self.adapter.validate_target('')
        self.assertIn('webhook URL', reason)

    def test_discord_does_not_claim_to_have_a_connection_to_test(self):
        """Its settings form holds presentation, not credentials — a webhook
        URL carries its own. A test button here would pass no matter what."""
        self.assertFalse(self.adapter.supports_check)
        self.assertEqual(self.adapter.settings_label, 'Appearance')
        self.assertFalse(self.adapter.check().ok)

    def test_a_service_reached_by_address_still_calls_it_a_connection(self):
        from services.connectors.adapters.sonarr import SonarrConnector

        sonarr = SonarrConnector()
        self.assertTrue(sonarr.supports_check)
        self.assertEqual(sonarr.settings_label, 'Connection')

    def test_the_app_url_check_still_allows_a_private_address(self):
        """This is a private deployment; the app URL is routinely a LAN IP."""
        self.assertTrue(is_valid_app_url('http://localhost:5000'))
        self.assertTrue(is_valid_app_url('http://100.64.0.1:5000'))
        self.assertFalse(is_valid_app_url('javascript:alert(1)'))


class DiscordDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.adapter = DiscordConnector()
        self.target = Target('tgt_1', 'discord', 'alerts')
        self.event = Event(key='transfer.completed', severity=SUCCESS, title='Example Show')

    def test_a_204_is_success(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)):
            result = self.adapter.deliver(self.event, self.target, SECRET_URL)
        self.assertTrue(result.ok)

    def test_a_failure_never_carries_the_credential(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(404, SECRET_URL)):
            result = self.adapter.deliver(self.event, self.target, SECRET_URL)
        self.assertFalse(result.ok)
        self.assertNotIn('super-secret-token-value', result.error)


# ===========================================================================
# The store
# ===========================================================================

class TargetStoreTests(unittest.TestCase):
    def setUp(self):
        self.store, _ = store_with_db(self)
        self.store.upsert_connector('discord', 'Discord', enabled=True)

    def test_the_first_destination_becomes_the_default(self):
        """A connector with destinations but no default cannot deliver, and
        arriving there by adding one webhook would be a trap."""
        self.store.create_target('discord', 'alerts', SECRET_URL)
        self.assertEqual(self.store.default_target('discord')['label'], 'alerts')

    def test_only_one_destination_is_ever_the_default(self):
        self.store.create_target('discord', 'alerts', SECRET_URL)
        second = self.store.create_target('discord', 'quiet', SECRET_URL)
        self.store.update_target(second, make_default=True)

        defaults = [t for t in self.store.list_targets('discord') if t['is_default']]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0]['label'], 'quiet')

    def test_deleting_the_default_promotes_another(self):
        first = self.store.create_target('discord', 'alerts', SECRET_URL)
        self.store.create_target('discord', 'quiet', SECRET_URL)
        self.store.delete_target(first)

        self.assertEqual(self.store.default_target('discord')['label'], 'quiet')

    def test_deleting_a_destination_takes_its_credential_with_it(self):
        target_id = self.store.create_target('discord', 'alerts', SECRET_URL)
        ref = self.store.get_target(target_id)['secret_ref']
        self.store.delete_target(target_id)
        self.assertEqual(self.store.secret('discord', ref), '')

    def test_a_route_pointing_at_a_deleted_destination_falls_back(self):
        """It must not go silent — that is the failure this layer removes."""
        keep = self.store.create_target('discord', 'alerts', SECRET_URL)
        doomed = self.store.create_target('discord', 'quiet', SECRET_URL)
        self.store.set_route('transfer.failed', 'discord', doomed)

        self.store.delete_target(doomed)

        route = self.store.get_route('transfer.failed', 'discord')
        self.assertIsNone(route['target_id'])
        resolution = routing.resolve(self.store, 'discord', 'transfer.failed')
        self.assertTrue(resolution.deliver)
        self.assertEqual(resolution.target.target_id, keep)


class ConnectorStoreTests(unittest.TestCase):
    def setUp(self):
        self.store, _ = store_with_db(self)

    def test_saving_one_part_of_a_form_leaves_the_rest_alone(self):
        self.store.upsert_connector('discord', 'Discord', enabled=True,
                                    config={'app_url': 'http://a.invalid'})
        self.store.upsert_connector('discord', 'Discord',
                                    config={'icon_url': 'http://b.invalid'})

        row = self.store.get_connector('discord')
        self.assertEqual(row['config']['app_url'], 'http://a.invalid')
        self.assertEqual(row['config']['icon_url'], 'http://b.invalid')
        self.assertTrue(row['enabled'], 'enabled=None means leave alone')

    def test_the_delivery_log_is_bounded(self):
        self.store.upsert_connector('discord', 'Discord')
        for i in range(DELIVERY_HISTORY_LIMIT + 25):
            self.store.record_delivery('discord', ok=True, event_key='transfer.completed',
                                       title=f"Example Show {i}")
        rows = self.store.list_deliveries('discord', limit=DELIVERY_HISTORY_LIMIT)
        self.assertEqual(len(rows), DELIVERY_HISTORY_LIMIT)
        # The newest survive, which is what "why didn't I get told" needs.
        self.assertIn('124', rows[0]['title'])


# ===========================================================================
# Routing
# ===========================================================================

class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.store, _ = store_with_db(self)
        self.store.upsert_connector('discord', 'Discord', enabled=True)
        self.default = self.store.create_target('discord', 'general', SECRET_URL)
        self.alerts = self.store.create_target('discord', 'alerts', SECRET_URL)

    def test_no_route_means_the_default(self):
        """A notification added next year is delivered the day it is written."""
        resolution = routing.resolve(self.store, 'discord', 'transfer.completed')
        self.assertTrue(resolution.deliver)
        self.assertEqual(resolution.target.target_id, self.default)

    def test_a_route_sends_somewhere_else(self):
        self.store.set_route('transfer.failed', 'discord', self.alerts)
        resolution = routing.resolve(self.store, 'discord', 'transfer.failed')
        self.assertEqual(resolution.target.target_id, self.alerts)

    def test_a_route_with_no_destination_means_the_default(self):
        self.store.set_route('transfer.failed', 'discord', None)
        resolution = routing.resolve(self.store, 'discord', 'transfer.failed')
        self.assertEqual(resolution.target.target_id, self.default)

    def test_a_switched_off_notification_is_skipped_with_a_reason(self):
        self.store.set_route('transfer.failed', 'discord', self.alerts, enabled=False)
        resolution = routing.resolve(self.store, 'discord', 'transfer.failed')
        self.assertFalse(resolution.deliver)
        self.assertEqual(resolution.reason, routing.SKIP_EVENT_OFF)

    def test_a_disabled_connector_sends_nothing(self):
        self.store.set_enabled('discord', False)
        resolution = routing.resolve(self.store, 'discord', 'transfer.completed')
        self.assertFalse(resolution.deliver)
        self.assertEqual(resolution.reason, routing.SKIP_CONNECTOR_OFF)

    def test_a_destination_out_of_service_is_not_quietly_redirected(self):
        """Sending somewhere the operator did not choose is worse than not
        sending."""
        self.store.set_route('transfer.failed', 'discord', self.alerts)
        self.store.update_target(self.alerts, enabled=False)
        resolution = routing.resolve(self.store, 'discord', 'transfer.failed')
        self.assertFalse(resolution.deliver)
        self.assertEqual(resolution.reason, routing.SKIP_TARGET_DISABLED)

    def test_no_default_at_all_is_visible_rather_than_silent(self):
        store, _ = store_with_db(self)
        store.upsert_connector('discord', 'Discord', enabled=True)
        resolution = routing.resolve(store, 'discord', 'transfer.completed')
        self.assertFalse(resolution.deliver)
        self.assertEqual(resolution.reason, routing.SKIP_NO_DEFAULT)

    def test_an_unconfigured_connector_says_so(self):
        resolution = routing.resolve(self.store, 'discord', 'transfer.completed',
                                     configured=False)
        self.assertFalse(resolution.deliver)
        self.assertEqual(resolution.reason, routing.SKIP_NOT_CONFIGURED)


# ===========================================================================
# Pings (issue #35)
# ===========================================================================

ROLE_ID = '112233445566778899'
USER_ID = '998877665544332211'


class DiscordMentionTests(unittest.TestCase):
    """A ping is written in the message text, and nothing else can ping."""

    def setUp(self):
        self.adapter = DiscordConnector()
        self.event = Event(key='transfer.failed', severity=FAILURE,
                           title='@everyone Example Show')

    def test_a_role_ping_goes_in_the_message_text(self):
        admins = Mention('men_1', 'Admins', 'role', ROLE_ID)
        payload = self.adapter.render(self.event, [admins])
        self.assertEqual(payload['content'], f"<@&{ROLE_ID}>")
        self.assertEqual(payload['allowed_mentions'], {'parse': [], 'roles': [ROLE_ID]})

    def test_a_message_with_no_ping_still_forbids_every_ping(self):
        """A title containing "@everyone" must never ping the whole server."""
        payload = self.adapter.render(self.event)
        self.assertNotIn('content', payload)
        self.assertEqual(payload['allowed_mentions'], {'parse': []})

    def test_users_and_here_are_allowed_exactly(self):
        payload = self.adapter.render(self.event, [
            Mention('men_1', 'Me', 'user', USER_ID),
            Mention('men_2', 'Online', 'here'),
        ])
        self.assertEqual(payload['content'], f"<@{USER_ID}> @here")
        self.assertEqual(payload['allowed_mentions'],
                         {'parse': ['everyone'], 'users': [USER_ID]})

    def test_a_role_needs_a_discord_id(self):
        self.assertIsNone(self.adapter.validate_mention('role', ROLE_ID))
        self.assertIn('ID', self.adapter.validate_mention('role', 'Admins'))
        self.assertIn('ID', self.adapter.validate_mention('user', ''))
        self.assertIsNone(self.adapter.validate_mention('here', ''))
        self.assertIsNotNone(self.adapter.validate_mention('channel', ROLE_ID))


class PingRoutingTests(unittest.TestCase):
    """When a message pings, and whom."""

    def setUp(self):
        self.store, _ = store_with_db(self)
        self.store.upsert_connector('discord', 'Discord', enabled=True)
        self.admins = self.store.create_mention('discord', 'Admins', 'role', ROLE_ID)
        self.me = self.store.create_mention('discord', 'Me', 'user', USER_ID)
        self.target = self.store.create_target('discord', 'general', SECRET_URL)
        self.store.update_target(self.target, mention_ids=[self.admins])

    def pinged(self, key, severity):
        row = self.store.get_target(self.target)
        return [m.label for m in routing.mentions_for(self.store, 'discord', key,
                                                     severity, row)]

    def test_a_failure_pings_the_webhooks_people(self):
        self.assertEqual(self.pinged('transfer.failed', FAILURE), ['Admins'])

    def test_a_finished_sync_pings_nobody_by_default(self):
        self.assertEqual(self.pinged('transfer.completed', SUCCESS), [])

    def test_a_report_under_the_needs_a_person_rule_pings_only_on_a_warning(self):
        """The auto-scanner starting syncs is news; it failing to close a gap
        needs someone."""
        self.assertEqual(self.pinged('scanner.found', 'info'), [])
        self.assertEqual(self.pinged('scanner.found', WARNING), ['Admins'])

    def test_a_route_can_ping_someone_else(self):
        self.store.set_route('transfer.failed', 'discord', None, mention_ids=[self.me])
        self.assertEqual(self.pinged('transfer.failed', FAILURE), ['Me'])

    def test_a_route_can_ping_nobody(self):
        self.store.set_route('transfer.failed', 'discord', None, mention_ids=[])
        self.assertEqual(self.pinged('transfer.failed', FAILURE), [])

    def test_a_route_can_ping_on_every_message(self):
        self.store.set_route('transfer.completed', 'discord', None, ping_when='always')
        self.assertEqual(self.pinged('transfer.completed', SUCCESS), ['Admins'])

    def test_a_route_can_turn_pings_off(self):
        self.store.set_route('transfer.failed', 'discord', None, ping_when='never')
        self.assertEqual(self.pinged('transfer.failed', FAILURE), [])

    def test_removing_someone_takes_them_out_of_every_list(self):
        self.store.set_route('transfer.failed', 'discord', None,
                             mention_ids=[self.admins, self.me])
        self.store.delete_mention(self.admins)
        self.assertEqual(self.store.get_target(self.target)['mention_ids'], [])
        self.assertEqual(self.store.get_route('transfer.failed', 'discord')['mention_ids'],
                         [self.me])
        self.assertEqual(self.pinged('transfer.failed', FAILURE), ['Me'])

    def test_a_delivered_message_pings_and_the_log_says_who(self):
        service = ConnectorService(self.store, synchronous=True)
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)) as request:
            service.notify(Event(key='transfer.failed', severity=FAILURE,
                                 title='Example Show'))
        sent = request.call_args.kwargs['json']
        self.assertEqual(sent['content'], f"<@&{ROLE_ID}>")
        self.assertEqual(self.store.list_deliveries('discord')[0]['mentions'], 'Admins')


# ===========================================================================
# Dispatch
# ===========================================================================

class DispatchTests(unittest.TestCase):
    def test_work_runs_on_the_worker_not_the_caller(self):
        seen = []
        dispatcher = Dispatcher(seen.append)
        self.addCleanup(dispatcher.stop)
        for i in range(5):
            dispatcher.submit(i)
        dispatcher.join()
        self.assertEqual(sorted(seen), [0, 1, 2, 3, 4])

    def test_a_handler_that_raises_does_not_kill_the_worker(self):
        """Otherwise one bad notification silences every later one."""
        seen = []

        def handler(item):
            if item == 'bad':
                raise RuntimeError('boom')
            seen.append(item)

        dispatcher = Dispatcher(handler)
        self.addCleanup(dispatcher.stop)
        dispatcher.submit('bad')
        dispatcher.submit('good')
        dispatcher.join()
        self.assertEqual(seen, ['good'])

    def test_a_full_queue_drops_the_oldest_rather_than_growing(self):
        """An outage with an unbounded queue is a slow leak that looks like
        nothing until it does not.

        Reproduced the way it actually happens: the worker is stuck on one
        slow send while more announcements arrive behind it.
        """
        entered = threading.Event()
        release = threading.Event()

        def handler(item):
            entered.set()
            release.wait(timeout=5)

        dispatcher = Dispatcher(handler, maxsize=2)
        self.addCleanup(dispatcher.stop)
        self.addCleanup(release.set)

        dispatcher.submit('stuck')
        self.assertTrue(entered.wait(timeout=5), 'the worker never picked anything up')

        dispatcher.submit('a')
        dispatcher.submit('b')
        self.assertTrue(dispatcher.submit('c'), 'the newest must survive')
        self.assertEqual(dispatcher.dropped, 1)
        self.assertEqual(dispatcher.pending, 2)

    def test_synchronous_mode_runs_inline(self):
        seen = []
        dispatcher = Dispatcher(seen.append, synchronous=True)
        dispatcher.submit('now')
        self.assertEqual(seen, ['now'])


# ===========================================================================
# The service
# ===========================================================================

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.store, _ = store_with_db(self)
        self.store.upsert_connector('discord', 'Discord', enabled=True)
        self.target = self.store.create_target('discord', 'general', SECRET_URL)
        self.service = ConnectorService(self.store, synchronous=True)

    def test_an_announcement_is_delivered_and_recorded(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)):
            self.service.notify(Event(key='transfer.completed', severity=SUCCESS,
                                      title='Example Show'))
        deliveries = self.store.list_deliveries('discord')
        self.assertEqual(len(deliveries), 1)
        self.assertTrue(deliveries[0]['ok'])
        self.assertEqual(deliveries[0]['target_label'], 'general')

    def test_a_skipped_announcement_says_why(self):
        self.store.set_route('transfer.failed', 'discord', None, enabled=False)
        self.service.notify(Event(key='transfer.failed', severity=FAILURE,
                                  title='Example Show'))
        deliveries = self.store.list_deliveries('discord')
        self.assertEqual(deliveries[0]['skipped_reason'], routing.SKIP_EVENT_OFF)

    def test_a_turned_off_connector_does_not_fill_the_log(self):
        """A fresh install has every connector off; recording each skip would
        bury the entries that mean something."""
        self.store.set_enabled('discord', False)
        self.service.notify(Event(key='transfer.completed', severity=SUCCESS,
                                  title='Example Show'))
        self.assertEqual(self.store.list_deliveries('discord'), [])

    def test_notify_survives_the_service_being_down(self):
        import requests as real_requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=real_requests.ConnectionError('down')):
            self.service.notify(Event(key='transfer.completed', severity=SUCCESS,
                                      title='Example Show'))
        delivery = self.store.list_deliveries('discord')[0]
        self.assertFalse(delivery['ok'])
        self.assertNotIn('super-secret-token-value', delivery['error'] or '')

    def test_a_described_connector_carries_no_credential(self):
        described = self.service.describe('discord')
        blob = json.dumps(described)
        self.assertNotIn('super-secret-token-value', blob)
        self.assertNotIn('secret_ref', json.dumps(described.get('config', {})))

    def test_every_registered_connector_is_described_even_when_unsaved(self):
        """A fresh install must not show an empty Integrations section."""
        ids = {c['id'] for c in self.service.describe_all()}
        self.assertEqual(ids, {'discord', 'jellyfin', 'radarr', 'sonarr'})

    def test_an_unconfigured_query_connector_is_not_checked_over_the_wire(self):
        with patch('services.connectors.transport.requests.request') as request:
            result = self.service.check('sonarr')
        request.assert_not_called()
        self.assertFalse(result.ok)

    def test_a_connector_with_nowhere_to_send_is_not_called_configured(self):
        """Discord needs no credential of its own — a webhook carries one — so
        asking the adapter alone would say yes for a connector that cannot
        deliver anything."""
        store, _ = store_with_db(self)
        store.upsert_connector('discord', 'Discord', enabled=True)
        service = ConnectorService(store, synchronous=True)

        self.assertFalse(service.describe('discord')['configured'])
        store.create_target('discord', 'general', SECRET_URL)
        self.assertTrue(service.describe('discord')['configured'])

    def test_a_test_send_is_not_logged_as_a_finished_transfer(self):
        from services.connectors.events import TEST_EVENT_KEY

        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)):
            self.service.send_test(
                'discord', self.target,
                Event(key=TEST_EVENT_KEY, severity=SUCCESS, title='Test'),
            )
        self.assertEqual(self.store.list_deliveries('discord')[0]['event_key'],
                         TEST_EVENT_KEY)

    def test_the_test_event_is_not_offered_for_routing(self):
        """It ignores routing by design; listing it would offer a choice that
        does nothing."""
        from services.connectors.events import TEST_EVENT_KEY

        self.assertNotIn(TEST_EVENT_KEY, EVENT_KEYS)

    def test_a_test_send_ignores_routing(self):
        """The question is "does this webhook work", not "where would a sync
        notification go"."""
        elsewhere = self.store.create_target('discord', 'alerts', SECRET_URL)
        self.store.set_route('transfer.completed', 'discord', self.target)
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)):
            result = self.service.send_test(
                'discord', elsewhere,
                Event(key='transfer.completed', severity=SUCCESS, title='Test'),
            )
        self.assertTrue(result.ok)
        self.assertEqual(self.store.list_deliveries('discord')[0]['target_label'], 'alerts')


# ===========================================================================
# The upgrade
# ===========================================================================

class MigrationTests(unittest.TestCase):
    """An operator with a working webhook must not notice anything changed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'migrate_test.db')

    def seed_old_settings(self, values):
        DatabaseManager(self.path)
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM connector")
            conn.execute("DELETE FROM connector_target")
            conn.execute("DELETE FROM connector_secret")
            for key, value in values.items():
                conn.execute(
                    'INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)',
                    (key, value),
                )
            conn.commit()

    def test_the_existing_webhook_becomes_the_default_destination(self):
        self.seed_old_settings({
            'DISCORD_WEBHOOK_URL': SECRET_URL,
            'DISCORD_NOTIFICATIONS_ENABLED': 'true',
            'DISCORD_APP_URL': 'http://localhost:5000',
            'DISCORD_ICON_URL': 'https://example.invalid/icon.png',
        })
        store = ConnectorStore(DatabaseManager(self.path))

        connector = store.get_connector('discord')
        self.assertTrue(connector['enabled'])
        self.assertEqual(connector['config']['app_url'], 'http://localhost:5000')

        target = store.default_target('discord')
        self.assertEqual(target['label'], 'Default')
        self.assertEqual(store.secret('discord', target['secret_ref']), SECRET_URL)

    def test_nothing_is_routed_so_behaviour_is_unchanged(self):
        self.seed_old_settings({'DISCORD_WEBHOOK_URL': SECRET_URL,
                                'DISCORD_NOTIFICATIONS_ENABLED': 'true'})
        store = ConnectorStore(DatabaseManager(self.path))
        self.assertEqual(store.list_routes(), [])
        for key in EVENT_KEYS:
            resolution = routing.resolve(store, 'discord', key)
            self.assertTrue(resolution.deliver, key)
            self.assertEqual(resolution.target.label, 'Default')

    def test_the_old_settings_are_removed_so_no_value_has_two_homes(self):
        self.seed_old_settings({'DISCORD_WEBHOOK_URL': SECRET_URL,
                                'DISCORD_NOTIFICATIONS_ENABLED': 'true'})
        DatabaseManager(self.path)
        with sqlite3.connect(self.path) as conn:
            left = conn.execute(
                "SELECT COUNT(*) FROM app_settings WHERE key LIKE 'DISCORD_%'"
            ).fetchone()[0]
        self.assertEqual(left, 0)

    def test_running_twice_changes_nothing(self):
        self.seed_old_settings({'DISCORD_WEBHOOK_URL': SECRET_URL,
                                'DISCORD_NOTIFICATIONS_ENABLED': 'true'})
        store = ConnectorStore(DatabaseManager(self.path))
        first = store.default_target('discord')['target_id']

        DatabaseManager(self.path)
        DatabaseManager(self.path)

        self.assertEqual(len(store.list_targets('discord')), 1)
        self.assertEqual(store.default_target('discord')['target_id'], first)

    def test_an_install_that_never_used_discord_gets_no_connector_row(self):
        """Otherwise Integrations shows Discord as configured-and-empty."""
        self.seed_old_settings({'DISCORD_WEBHOOK_URL': '',
                                'DISCORD_NOTIFICATIONS_ENABLED': 'false'})
        store = ConnectorStore(DatabaseManager(self.path))
        self.assertIsNone(store.get_connector('discord'))

    def test_notifications_left_switched_off_stay_switched_off(self):
        self.seed_old_settings({'DISCORD_WEBHOOK_URL': SECRET_URL,
                                'DISCORD_NOTIFICATIONS_ENABLED': 'false'})
        store = ConnectorStore(DatabaseManager(self.path))
        self.assertFalse(store.get_connector('discord')['enabled'])
        resolution = routing.resolve(store, 'discord', 'transfer.completed')
        self.assertFalse(resolution.deliver)


# ===========================================================================
# What every caller writes
# ===========================================================================

class CallSiteTests(unittest.TestCase):
    """The four converted senders, exercised through the real service."""

    def setUp(self):
        self.store, _ = store_with_db(self)
        self.store.upsert_connector('discord', 'Discord', enabled=True)
        self.store.create_target('discord', 'general', SECRET_URL)
        self.service = ConnectorService(self.store, synchronous=True)

        patcher = patch('services.connectors.service._service', self.service)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sent_payloads(self):
        return [call.kwargs['json'] for call in self.request.call_args_list]

    def run_and_capture(self, fn):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(204)) as request:
            self.request = request
            fn()
        return self.sent_payloads()

    def test_a_failed_transfer_announces_with_its_errors(self):
        from services.notification_service import NotificationService

        class FakeTransfers:
            def get(self, transfer_id):
                return {
                    'parsed_title': 'Example Show', 'dest_path': '/library/Example Show',
                    'media_type': 'tvshows',
                    'logs': ['rsync: error: some failure', 'Number of deleted files: 2'],
                    'progress': 'stopped',
                }

        class FakeWebhooks:
            def get_all(self):
                return []

        service = NotificationService(None, None, FakeTransfers(), FakeWebhooks(),
                                      FakeWebhooks())
        payloads = self.run_and_capture(
            lambda: service.send_discord_notification('t1', 'failed')
        )

        embed = payloads[0]['embeds'][0]
        self.assertEqual(embed['color'], 15158332)
        self.assertEqual(embed['author']['name'], 'MANUAL SYNC FAILED')
        names = [f['name'] for f in embed['fields']]
        self.assertIn('Folder', names)
        self.assertIn('Error Details', names)

    def finished(self, logs, transport='daemon', **kwargs):
        from services.notification_service import NotificationService

        class FakeTransfers:
            def get(self, transfer_id):
                return {'parsed_title': 'Example Show', 'season_name': 'Season 03',
                        'dest_path': '/library/Example Show/Season 03',
                        'media_type': 'tvshows', 'transport': transport, 'logs': logs}

        class FakeWebhooks:
            def get_all(self):
                return []

        service = NotificationService(None, None, FakeTransfers(), FakeWebhooks(),
                                      FakeWebhooks())
        payloads = self.run_and_capture(
            lambda: service.send_discord_notification('t1', 'completed', **kwargs))
        embed = payloads[0]['embeds'][0]
        return embed, {f['name']: f['value'] for f in embed['fields']}

    UPGRADE_LOG = [
        'Season 03/',
        'deleting Example Show - S03E10 - 059 - Alpha - Bravo, Charlie of the Delta [HDTV-720p].mkv',
        'Example Show - S03E10 - 059 - Alpha - Bravo, Charlie of the Delta [WEBDL-1080p].mkv',
        'Example Show - S03E11 - 060 - Episode Eleven [WEBDL-1080p].mkv',
        'Example Show - S03E11 - 060 - Episode Eleven [WEBDL-1080p].en.srt',
        'Number of deleted files: 1',
        'Total transferred file size: 3.70G bytes',
        'sent 1.20K bytes  received 3.70G bytes  31.20M bytes/sec',
    ]

    def test_a_finished_sync_names_how_it_started_and_where_from(self):
        """One scheme for every sync: "MANUAL SYNC - EXPLORE", not "Explore"."""
        embed, _ = self.finished(self.UPGRADE_LOG, sync_mode='MANUAL', sync_source='EXPLORE')
        self.assertEqual(embed['author']['name'], 'MANUAL SYNC - EXPLORE')
        self.assertEqual(embed['title'], 'Example Show — Season 03')

    def test_a_finished_sync_lists_the_episodes_it_copied(self):
        _, fields = self.finished(self.UPGRADE_LOG, sync_mode='AUTO', sync_source='SONARR')
        synced = fields['Synced (2)']
        self.assertIn('`S03E10` Alpha - Bravo, Charlie of the Delta — upgrade to WEBDL-1080p',
                      synced)
        self.assertIn('`S03E11` Episode Eleven', synced)
        self.assertNotIn('srt', synced)
        # The deleted file was the old half of the upgrade, not a removal.
        self.assertNotIn('Removed', fields)
        self.assertEqual(fields['Size'], '3.70 GB')
        self.assertEqual(fields['Speed'], '31.20 MB/s')

    def test_a_finished_sync_says_which_route_it_took(self):
        for transport, label in (('daemon', '⚡ FAST'), ('ssh', 'SSH'),
                                 ('ssh_fallback', 'SSH FALLBACK (fast route failed)')):
            _, fields = self.finished(self.UPGRADE_LOG, transport=transport)
            self.assertEqual(fields['Transfer'], label)
        _, fields = self.finished(self.UPGRADE_LOG, transport=None)
        self.assertNotIn('Transfer', fields)

    def test_a_long_list_is_cut_short(self):
        logs = [f"Example Show - S03E{n:02d} - Episode {n} [WEBDL-1080p].mkv"
                for n in range(1, 15)]
        _, fields = self.finished(logs)
        self.assertTrue(fields['Synced (14)'].endswith('… and 4 more'))

    def test_a_sync_with_nothing_to_copy_says_so(self):
        _, fields = self.finished(['Number of regular files transferred: 0'])
        self.assertIn('already here', fields['Synced'])

    def test_every_message_carries_the_same_footer(self):
        from services.connectors.adapters.discord import FOOTER
        embed, _ = self.finished(self.UPGRADE_LOG)
        self.assertEqual(embed['footer']['text'], FOOTER)
        self.assertTrue(FOOTER.startswith('DragonCP v'))

    def test_a_cancelled_transfer_announces_nothing(self):
        from services.notification_service import NotificationService

        class FakeTransfers:
            def get(self, transfer_id):
                return {'parsed_title': 'Example Show', 'media_type': 'movies', 'logs': []}

        service = NotificationService(None, None, FakeTransfers(), None, None)
        payloads = self.run_and_capture(
            lambda: service.send_discord_notification('t1', 'cancelled')
        )
        self.assertEqual(payloads, [])

    def test_a_retention_sweep_announces_what_it_deleted(self):
        from services.notification_service import NotificationService

        service = NotificationService(None, None, None, None, None)
        payloads = self.run_and_capture(lambda: service.send_backup_retention_notification({
            'deleted_count': 2, 'reclaimed_bytes': 4 * 1024 ** 3,
            'items': [{'display': 'Example Show - S01E01', 'total_size': 2 * 1024 ** 3,
                       'files': [{'original_path': '/library/Example Show/S01E01.mkv'}]}],
            'keep': 2, 'grace_hours': 24,
        }))

        embed = payloads[0]['embeds'][0]
        self.assertEqual(embed['color'], 15105570)
        self.assertIn('cannot be undone', embed['description'])
        names = [f['name'] for f in embed['fields']]
        self.assertIn('Deleted Media', names)
        self.assertIn('Retention Rule', names)

    def test_a_retention_sweep_that_deleted_nothing_stays_quiet(self):
        from services.notification_service import NotificationService

        service = NotificationService(None, None, None, None, None)
        payloads = self.run_and_capture(
            lambda: service.send_backup_retention_notification({'deleted_count': 0, 'items': []})
        )
        self.assertEqual(payloads, [])

    def test_a_finished_rename_announces_the_new_names(self):
        from services.notification_service import NotificationService

        service = NotificationService(None, None, None, None, None)
        payloads = self.run_and_capture(lambda: service.send_rename_discord_notification({
            'series_title': 'Example Show', 'total_files': 2, 'success_count': 2,
            'failed_count': 0, 'status': 'completed', 'media_type': 'tvshows',
            'renamed_files': [{'new_name': 'Example Show - S01E01.mkv', 'status': 'success'}],
        }))

        embed = payloads[0]['embeds'][0]
        self.assertEqual(embed['color'], 1752220, 'renames keep their own colour')
        self.assertEqual(embed['author']['name'], 'FILE RENAME - COMPLETED')
        self.assertTrue(embed['footer']['text'].startswith('DragonCP v'))

    def test_notify_without_a_configured_layer_does_nothing_and_does_not_raise(self):
        from services.connectors import service as service_module

        with patch.object(service_module, '_service', None):
            service_module.notify(Event(key='transfer.completed', severity=SUCCESS,
                                        title='Example Show'))


if __name__ == '__main__':
    unittest.main()
