#!/usr/bin/env python3
"""
The settings boundary: two stores, and only two.

  ENV — what an installation is built with. Read-only at runtime.
  DB  — what an operator changes while running it.

A third store used to exist — a per-browser Flask session — and it was a
persistent lie: `config.get()` only consulted it when an HTTP request was in
flight, so background threads fell through to the env file. Sixteen settings
looked editable and were ignored by the machinery that used them. These tests
pin the boundary so it cannot come back by accident.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import settings_registry as registry
from config import DragonCPConfig
from models.database import DatabaseManager
from models.settings import AppSettings
from services.settings_service import SettingsService


class FakeConfig:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=''):
        return self.values.get(key, default)


class RegistryTests(unittest.TestCase):
    def test_every_setting_belongs_to_exactly_one_store(self):
        for setting in registry.SETTINGS:
            self.assertIn(setting.store, (registry.ENV, registry.DB), setting.key)

    def test_no_key_is_registered_twice(self):
        keys = [s.key for s in registry.SETTINGS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_path_boundary_stays_in_the_env_file(self):
        """
        These seven are what `get_all_allowed_paths()` returns, and every
        traversal check validates against them. A web form must not be able to
        widen the only boundary stopping a crafted webhook writing outside the
        media directories.
        """
        for key in ('MOVIE_PATH', 'TVSHOW_PATH', 'ANIME_PATH',
                    'MOVIE_DEST_PATH', 'TVSHOW_DEST_PATH', 'ANIME_DEST_PATH',
                    'BACKUP_PATH'):
            self.assertFalse(registry.is_editable(key), f"{key} must not be editable")

    def test_secrets_stay_in_the_env_file(self):
        for key in ('SECRET_KEY', 'JWT_SECRET_KEY', 'DRAGONCP_PASSWORD',
                    'DRAGONCP_PASSWORD_HASH', 'WEBHOOK_SECRET', 'DISK_API_TOKEN',
                    'REMOTE_PASSWORD'):
            self.assertFalse(registry.is_editable(key), f"{key} must not be editable")

    def test_the_operator_facing_settings_are_editable(self):
        for key in ('AUTO_SYNC_MOVIES', 'AUTO_SYNC_SERIES', 'AUTO_SYNC_ANIME',
                    'SERIES_ANIME_SYNC_WAIT_TIME', 'DISCORD_NOTIFICATIONS_ENABLED',
                    'DISCORD_WEBHOOK_URL', 'BACKUP_RETENTION_KEEP',
                    'BACKUP_RETENTION_GRACE_HOURS', 'BACKUP_RETENTION_ENABLED',
                    'WEBSOCKET_TIMEOUT_MINUTES'):
            self.assertTrue(registry.is_editable(key), f"{key} should be editable")

    def test_the_sync_wait_time_is_in_seconds(self):
        """
        `AutoSyncScheduler.schedule_job` adds it straight to `time.time()`.
        Its bounds were previously enforced in one route and nowhere else.
        """
        setting = registry.get('SERIES_ANIME_SYNC_WAIT_TIME')
        self.assertIn('second', setting.label.lower())
        self.assertEqual((setting.minimum, setting.maximum), (30, 900))

    def test_numbers_are_clamped_rather_than_rejected(self):
        setting = registry.get('BACKUP_RETENTION_KEEP')
        self.assertEqual(registry.coerce(setting, 0), '1')
        self.assertEqual(registry.coerce(setting, 9999), '50')
        with self.assertRaises(ValueError):
            registry.coerce(setting, 'lots')

    def test_booleans_accept_how_people_write_them(self):
        setting = registry.get('AUTO_SYNC_MOVIES')
        for truthy in (True, 'true', 'TRUE', 'yes', 'on', '1'):
            self.assertEqual(registry.coerce(setting, truthy), 'true', truthy)
        for falsy in (False, 'false', 'no', 'off', '0', ''):
            self.assertEqual(registry.coerce(setting, falsy), 'false', falsy)


class ConfigHasNoSessionStoreTests(unittest.TestCase):
    """The env reader must not know about requests at all."""

    def test_there_is_no_session_overlay_left(self):
        source = (REPO_ROOT / 'config.py').read_text()
        for gone in ('ui_config', 'has_request_context', 'update_session_config',
                     'save_config'):
            self.assertNotIn(gone, source, f"{gone} should be gone from config.py")

    def test_nothing_in_the_app_reads_a_session_config(self):
        offenders = []
        for path in REPO_ROOT.glob('*.py'):
            if 'ui_config' in path.read_text():
                offenders.append(path.name)
        for path in (REPO_ROOT / 'routes').glob('*.py'):
            if 'ui_config' in path.read_text():
                offenders.append(f"routes/{path.name}")
        for path in (REPO_ROOT / 'services').rglob('*.py'):
            if 'ui_config' in path.read_text():
                offenders.append(f"services/{path.name}")
        self.assertEqual(offenders, [])

    def test_the_env_reader_works_with_no_request_context(self):
        """It used to need one to see half its values."""
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / 'test.env'
            env.write_text('REMOTE_IP="10.0.0.1"\n')
            config = DragonCPConfig(str(env))
            self.assertEqual(config.get('REMOTE_IP'), '10.0.0.1')


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = DatabaseManager(os.path.join(self.tmp.name, 'settings_test.db'))
        self.model = AppSettings(self.db)
        self.config = FakeConfig()
        self.service = SettingsService(self.config, self.model)

    def test_an_env_setting_comes_from_the_file(self):
        self.config.values['REMOTE_IP'] = '10.0.0.1'
        self.assertEqual(self.service.get('REMOTE_IP'), '10.0.0.1')

    def test_an_env_setting_cannot_be_written(self):
        saved, refused, errors = self.service.set_many({'REMOTE_IP': '10.0.0.2'})
        self.assertEqual(saved, {})
        self.assertEqual(refused, ['REMOTE_IP'])
        self.assertEqual(errors, [])
        self.assertEqual(self.service.get('REMOTE_IP'), '')

    def test_a_db_setting_round_trips(self):
        self.service.set('BACKUP_RETENTION_KEEP', 5)
        self.assertEqual(self.service.get_int('BACKUP_RETENTION_KEEP'), 5)

    def test_a_db_setting_falls_back_to_the_env_file_then_its_default(self):
        self.assertEqual(self.service.get_int('BACKUP_RETENTION_KEEP'), 2, 'built-in default')

        self.config.values['BACKUP_RETENTION_KEEP'] = '7'
        self.assertEqual(self.service.get_int('BACKUP_RETENTION_KEEP'), 7, 'env file default')

        self.service.set('BACKUP_RETENTION_KEEP', 3)
        self.assertEqual(self.service.get_int('BACKUP_RETENTION_KEEP'), 3, 'saved value wins')

    def test_saved_values_are_clamped_on_the_way_in(self):
        self.service.set('WEBSOCKET_TIMEOUT_MINUTES', 999)
        self.assertEqual(self.service.get_int('WEBSOCKET_TIMEOUT_MINUTES'), 60)

    def test_a_redacted_placeholder_means_unchanged(self):
        self.service.set('DISCORD_WEBHOOK_URL', 'https://example.invalid/hook')
        self.service.set_many({'DISCORD_WEBHOOK_URL': registry.REDACTED})
        self.assertEqual(self.service.get('DISCORD_WEBHOOK_URL'), 'https://example.invalid/hook')

    def test_a_value_can_be_deliberately_cleared(self):
        """
        Emptying a field is an answer, not an absence.

        A stored empty string used to read as "nothing saved", so the resolver
        went back to the env file: clearing the Discord webhook in the UI
        looked like it worked and notifications kept going to the old one.
        """
        self.config.values['DISCORD_WEBHOOK_URL'] = 'https://example.invalid/from-env'
        self.assertEqual(
            self.service.get('DISCORD_WEBHOOK_URL'), 'https://example.invalid/from-env',
        )

        self.service.set('DISCORD_WEBHOOK_URL', '')
        self.assertEqual(self.service.get('DISCORD_WEBHOOK_URL'), '')

    def test_a_cleared_value_survives_a_restart(self):
        """Startup adoption used to put the env value back over it every time."""
        self.config.values['DISCORD_WEBHOOK_URL'] = 'https://example.invalid/from-env'
        self.service.set('DISCORD_WEBHOOK_URL', '')

        self.service.adopt_env_defaults()

        self.assertEqual(self.service.get('DISCORD_WEBHOOK_URL'), '')

    def test_nothing_is_written_when_any_value_in_the_payload_is_invalid(self):
        """
        Saving a form is one decision, so it is one write.

        Coercing and committing key by key meant a bad value at the end left
        every setting before it already changed, behind a response saying the
        save had failed.
        """
        self.service.set('BACKUP_RETENTION_KEEP', 2)

        saved, _refused, errors = self.service.set_many({
            'BACKUP_RETENTION_KEEP': 9,
            'WEBSOCKET_TIMEOUT_MINUTES': 'not a number',
        })

        self.assertTrue(errors)
        self.assertEqual(saved, {})
        self.assertEqual(self.service.get_int('BACKUP_RETENTION_KEEP'), 2,
                         'the earlier setting was not written')

    def test_an_unknown_key_is_refused(self):
        _saved, refused, _errors = self.service.set_many({'NONSENSE': 'x'})
        self.assertEqual(refused, ['NONSENSE'])

    def test_a_db_setting_is_re_read_every_time(self):
        """No caching: a change has to take effect without a restart."""
        self.service.set('AUTO_SYNC_MOVIES', True)
        self.assertTrue(self.service.get_bool('AUTO_SYNC_MOVIES'))
        self.model.set('AUTO_SYNC_MOVIES', 'false')
        self.assertFalse(self.service.get_bool('AUTO_SYNC_MOVIES'))

    # ---- adoption ----

    def test_env_values_are_adopted_into_the_database_once(self):
        self.config.values['AUTO_SYNC_MOVIES'] = 'true'
        self.config.values['SERIES_ANIME_SYNC_WAIT_TIME'] = '120'

        adopted = self.service.adopt_env_defaults()
        self.assertIn('AUTO_SYNC_MOVIES', adopted)
        self.assertEqual(self.model.get('AUTO_SYNC_MOVIES'), 'true')
        self.assertEqual(self.model.get('SERIES_ANIME_SYNC_WAIT_TIME'), '120')

    def test_adoption_never_overwrites_a_saved_choice(self):
        self.service.set('AUTO_SYNC_MOVIES', False)
        self.config.values['AUTO_SYNC_MOVIES'] = 'true'

        self.service.adopt_env_defaults()
        self.assertFalse(self.service.get_bool('AUTO_SYNC_MOVIES'))

    def test_adoption_ignores_env_only_settings(self):
        self.config.values['REMOTE_IP'] = '10.0.0.1'
        adopted = self.service.adopt_env_defaults()
        self.assertNotIn('REMOTE_IP', adopted)
        self.assertIsNone(self.model.get('REMOTE_IP'))

    def test_adoption_is_safe_to_run_on_every_start(self):
        self.config.values['AUTO_SYNC_MOVIES'] = 'true'
        self.assertEqual(len(self.service.adopt_env_defaults()), 1)
        self.assertEqual(self.service.adopt_env_defaults(), [])

    # ---- describing ----

    def test_the_description_says_which_store_each_setting_came_from(self):
        described = self.service.describe()
        flat = {s['key']: s for g in described['groups'] for s in g['settings']}

        self.assertEqual(flat['REMOTE_IP']['store'], 'env')
        self.assertFalse(flat['REMOTE_IP']['editable'])
        self.assertEqual(flat['BACKUP_RETENTION_KEEP']['store'], 'db')
        self.assertTrue(flat['BACKUP_RETENTION_KEEP']['editable'])

    def test_env_secrets_are_not_sent_to_the_client_at_all(self):
        self.config.values['JWT_SECRET_KEY'] = 'very-secret'
        described = self.service.describe()
        flat = {s['key']: s for g in described['groups'] for s in g['settings']}

        self.assertNotIn('JWT_SECRET_KEY', flat)
        self.assertNotIn('DRAGONCP_PASSWORD', flat)
        self.assertNotIn('REMOTE_PASSWORD', flat)

    def test_an_editable_secret_is_redacted_not_omitted(self):
        self.service.set('DISCORD_WEBHOOK_URL', 'https://example.invalid/hook')
        described = self.service.describe()
        flat = {s['key']: s for g in described['groups'] for s in g['settings']}
        self.assertEqual(flat['DISCORD_WEBHOOK_URL']['value'], registry.REDACTED)

    def test_a_setting_with_nothing_saved_shows_its_default_value(self):
        """
        Not an empty box. Passing '' as the read default suppressed the
        registry's own, so a setting with a real default rendered blank.
        """
        described = self.service.describe()
        flat = {s['key']: s for g in described['groups'] for s in g['settings']}
        self.assertEqual(flat['BACKUP_RETENTION_KEEP']['value'], '2')
        self.assertIs(flat['BACKUP_RETENTION_ENABLED']['value'], True)
        self.assertEqual(flat['WEBSOCKET_TIMEOUT_MINUTES']['value'], '30')

    def test_a_setting_with_nothing_saved_says_it_is_on_the_default(self):
        described = self.service.describe()
        flat = {s['key']: s for g in described['groups'] for s in g['settings']}
        self.assertTrue(flat['BACKUP_RETENTION_KEEP']['is_default'])

        self.service.set('BACKUP_RETENTION_KEEP', 4)
        described = self.service.describe()
        flat = {s['key']: s for g in described['groups'] for s in g['settings']}
        self.assertFalse(flat['BACKUP_RETENTION_KEEP']['is_default'])


class WebsocketTimeoutTests(unittest.TestCase):
    """
    The idle timeout moved from a per-browser session to the database. The
    number the server enforces must not have changed on the way.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = DatabaseManager(os.path.join(self.tmp.name, 'ws_test.db'))
        self.service = SettingsService(FakeConfig(), AppSettings(self.db))

        import websocket
        self.websocket = websocket
        self.addCleanup(websocket.set_settings_service, None)
        websocket.set_settings_service(self.service)

    def test_the_default_is_what_it_always_was(self):
        self.assertEqual(
            self.websocket.get_websocket_timeout_for_session(),
            self.websocket.WEBSOCKET_TIMEOUT_DEFAULT,
        )

    def test_a_saved_value_is_honoured_with_the_server_buffer(self):
        self.service.set('WEBSOCKET_TIMEOUT_MINUTES', 15)
        # The server holds on five minutes longer than the client is told to,
        # so a client about to reconnect is not cut off mid-handshake.
        self.assertEqual(self.websocket.get_websocket_timeout_for_session(), 20 * 60)

    def test_it_is_capped(self):
        self.service.set('WEBSOCKET_TIMEOUT_MINUTES', 999)
        self.assertEqual(
            self.websocket.get_websocket_timeout_for_session(),
            self.websocket.WEBSOCKET_TIMEOUT_MAX,
        )

    def test_without_a_settings_service_it_falls_back(self):
        self.websocket.set_settings_service(None)
        self.assertEqual(
            self.websocket.get_websocket_timeout_for_session(),
            self.websocket.WEBSOCKET_TIMEOUT_DEFAULT,
        )

    def test_it_no_longer_reads_the_callers_session(self):
        """A browser session must not be able to set the server's own timeout."""
        self.service.set('WEBSOCKET_TIMEOUT_MINUTES', 10)
        pretend_session = {'ui_config': {'WEBSOCKET_TIMEOUT_MINUTES': 60}}
        self.assertEqual(
            self.websocket.get_websocket_timeout_for_session(pretend_session), 15 * 60
        )


class ConfigRouteTests(unittest.TestCase):
    """The HTTP surface, which is where the refusal has to be legible."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = DatabaseManager(os.path.join(self.tmp.name, 'routes_test.db'))
        self.service = SettingsService(
            FakeConfig({'REMOTE_IP': '10.0.0.1'}), AppSettings(self.db),
        )

        app = Flask(__name__)
        service = self.service

        @app.route('/api/config', methods=['GET', 'POST'])
        def api_config():
            from flask import jsonify, request
            if request.method == 'GET':
                return jsonify({
                    'status': 'success', **service.flat(), **service.describe(),
                })
            saved, refused, errors = service.set_many(request.json or {})
            if errors:
                return jsonify({'status': 'error', 'message': '; '.join(errors)}), 400
            message = f"Saved {len(saved)} setting(s)" if saved else 'Nothing to save'
            if refused:
                message += (
                    f". {len(refused)} setting(s) come from the environment file and were "
                    f"not changed: {', '.join(sorted(refused))}"
                )
            return jsonify({'status': 'success', 'message': message,
                            'saved': sorted(saved), 'refused': sorted(refused)})

        self.client = app.test_client()

    def test_a_save_that_touched_env_keys_says_which(self):
        response = self.client.post('/api/config', json={
            'BACKUP_RETENTION_KEEP': 4,
            'REMOTE_IP': '10.0.0.2',
        })
        body = response.get_json()
        self.assertEqual(body['saved'], ['BACKUP_RETENTION_KEEP'])
        self.assertEqual(body['refused'], ['REMOTE_IP'])
        self.assertIn('environment file', body['message'])
        self.assertEqual(self.service.get('REMOTE_IP'), '10.0.0.1', 'unchanged')

    def test_an_invalid_number_fails_the_whole_save(self):
        response = self.client.post('/api/config', json={'BACKUP_RETENTION_KEEP': 'lots'})
        self.assertEqual(response.status_code, 400)

    def test_a_failed_save_changes_nothing_at_all(self):
        """A 400 has to mean the settings are exactly as they were."""
        self.client.post('/api/config', json={'BACKUP_RETENTION_KEEP': 4})

        response = self.client.post('/api/config', json={
            'BACKUP_RETENTION_KEEP': 9,
            'WEBSOCKET_TIMEOUT_MINUTES': 'lots',
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.service.get_int('BACKUP_RETENTION_KEEP'), 4)

    def test_the_response_is_grouped_for_the_ui(self):
        body = self.client.get('/api/config').get_json()
        self.assertIn('groups', body)
        self.assertIn('stores', body)
        self.assertTrue(all('label' in group for group in body['groups']))

    def test_groups_is_always_a_list_of_lists(self):
        """
        The shape the frontend walks. `useRuntimeConnection` wraps every
        authenticated route and reads it, so a response missing `groups` — or
        holding a group with no `settings` — white-screens the whole app.
        """
        body = self.client.get('/api/config').get_json()
        self.assertIsInstance(body['groups'], list)
        self.assertTrue(body['groups'], 'never empty, or the UI has nothing to show')
        for group in body['groups']:
            self.assertIsInstance(group.get('settings'), list, group.get('id'))
            self.assertTrue(group['settings'])
            for setting in group['settings']:
                for field in ('key', 'store', 'editable', 'value', 'kind', 'label'):
                    self.assertIn(field, setting, f"{group['id']}.{setting.get('key')}")

    def test_the_realtime_timeout_is_always_present(self):
        """The one setting the app shell looks up by name on every page."""
        body = self.client.get('/api/config').get_json()
        keys = [s['key'] for g in body['groups'] for s in g['settings']]
        self.assertIn('WEBSOCKET_TIMEOUT_MINUTES', keys)

    def test_the_flat_shape_the_legacy_ui_reads_is_still_returned(self):
        """
        The deprecated compatibility client reads a flat key -> value
        map and would show an empty settings form without one.
        """
        body = self.client.get('/api/config').get_json()
        self.assertEqual(body['REMOTE_IP'], '10.0.0.1')
        self.assertIn('BACKUP_RETENTION_KEEP', body)


class StartupLoggingTests(unittest.TestCase):
    """
    What reading the environment file is allowed to say out loud.

    Every value in it used to be printed on every start, which put the operator
    password, the token-signing key, the Flask secret, the storage API token and
    the address allowed to reach the transfer server into the backend log in
    plain text. That log is shown on the Settings page, downloaded with one
    button, and pasted into bug reports.
    """

    SECRETS = {
        'DRAGONCP_PASSWORD': 'sup3r-secret-pw',
        'JWT_SECRET_KEY': 'jwt-signing-key-value',
        'SECRET_KEY': 'flask-secret-value',
        'DISK_API_TOKEN': 'storage-api-token-value',
        'RSYNC_DAEMON_ALLOWED_IP': '198.51.100.7',
    }
    PLAIN = {'REMOTE_USER': 'someone', 'MOVIE_PATH': '/srv/media/movies'}

    def _load(self):
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.env'
            lines = [f'{k}="{v}"' for k, v in {**self.SECRETS, **self.PLAIN}.items()]
            path.write_text('\n'.join(lines) + '\n')
            captured = io.StringIO()
            with patch('config.os.path.dirname', return_value=folder), \
                    contextlib.redirect_stdout(captured):
                config = DragonCPConfig('test.env')
            return config, captured.getvalue()

    def test_no_secret_is_printed_while_reading_the_environment_file(self):
        config, printed = self._load()
        for key, value in self.SECRETS.items():
            self.assertEqual(config.get(key), value, f'{key} should still be readable')
            self.assertNotIn(value, printed, f'{key} was printed in the clear')

    def test_ordinary_settings_are_still_readable_in_the_log(self):
        # Redacting everything would be safe and useless — the reason to print
        # any of it is being able to see which media directories were picked up.
        _, printed = self._load()
        for value in self.PLAIN.values():
            self.assertIn(value, printed)

    def test_a_setting_the_registry_does_not_know_is_redacted(self):
        # Fails closed. Something added later is far likelier to be a credential
        # than to be worth reading in a startup log.
        from config import _for_logging

        self.assertEqual(_for_logging('SOME_NEW_KEY', 'value'), '<redacted>')

    def test_every_sensitive_registered_setting_is_covered(self):
        from config import _for_logging

        for setting in registry.SETTINGS:
            if setting.sensitive or setting.hidden:
                self.assertEqual(
                    _for_logging(setting.key, 'a-value'), '<redacted>', setting.key)

if __name__ == '__main__':
    unittest.main()
