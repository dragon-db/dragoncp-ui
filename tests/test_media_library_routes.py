#!/usr/bin/env python3
"""
The library and history HTTP layer.

Two rules this file exists to hold:

  **Nothing here can change anything on the other side.** Every route reaches
  Sonarr or Radarr through adapters that refuse any verb but GET, and no route
  starts a transfer. The structural test at the bottom fails if a later edit
  adds one.

  **No response body carries the API key.** Same rule the connector routes
  keep, checked the same way.

Mounted on a bare Flask app, so nothing here touches the live database or the
transfer pipeline.
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
import routes.media_library as media_routes
from models.connector import ConnectorStore
from models.database import DatabaseManager
from models.media_item import SOURCE_SONARR
from services.connectors.service import ConnectorService
from services.media_index import MediaIndex

SECRET_KEY = 'sonarr-api-key-that-must-not-come-back'

SIGNED_IN_PAYLOAD = {'sub': 'tester', 'uid': 1, 'tv': 1, 'src': 'db', 'type': 'access'}
SIGNED_IN_IDENTITY = {
    'account_id': 1, 'username': 'tester', 'role': 'admin',
    'token_version': 1, 'must_change_password': False, 'source': 'db',
}

SERIES = [{
    'id': 219, 'tvdbId': 900001, 'title': 'Example Show', 'year': 2021,
    'titleSlug': 'example-show', 'monitored': True, 'status': 'continuing',
    'images': [{'coverType': 'poster', 'remoteUrl': 'http://img/p.jpg'}],
    'statistics': {'seasonCount': 2, 'episodeCount': 20,
                   'episodeFileCount': 20, 'sizeOnDisk': 123},
    'seasons': [
        {'seasonNumber': 0, 'monitored': False,
         'statistics': {'episodeCount': 2, 'episodeFileCount': 2}},
        {'seasonNumber': 1, 'monitored': True,
         'statistics': {'episodeCount': 10, 'episodeFileCount': 10}},
        {'seasonNumber': 2, 'monitored': True,
         'statistics': {'episodeCount': 10, 'episodeFileCount': 10}},
    ],
}]

HISTORY = {
    'page': 1, 'pageSize': 25, 'totalRecords': 2,
    'records': [
        {'id': 1, 'eventType': 'downloadFolderImported', 'date': '2026-08-21T15:46:02Z',
         'seriesId': 219, 'sourceTitle': 'Example.Show.S01E01',
         'quality': {'quality': {'name': 'WEBDL-1080p'}}},
        {'id': 2, 'eventType': 'grabbed', 'date': '2026-08-21T15:45:05Z',
         'seriesId': 999, 'sourceTitle': 'Unknown.Show.S01E01',
         'quality': {'quality': {'name': 'HDTV-720p'}}},
    ],
}


#: Shaped from rows seen live. Every one of these is stuck in a different way,
#: and each was sitting in a real queue when this was written.
QUEUE = [
    # Downloaded a week and a half ago, still not filed, and the library
    # already has the episode — the queue row is simply stale.
    {'id': 1, 'seriesId': 219, 'seasonNumber': 4, 'title': 'Example.Show.S04E03',
     'trackedDownloadState': 'importPending', 'trackedDownloadStatus': 'warning',
     'episodeHasFile': True, 'size': 100, 'sizeleft': 0,
     'downloadClient': 'client-a', 'protocol': 'usenet',
     'added': '2026-08-12T07:22:17Z',
     'statusMessages': [{'title': 'Example.Show.S04E03',
                         'messages': ['Unable to determine if file is a sample']}]},
    # Reports "downloading" and has not moved a byte.
    {'id': 2, 'seriesId': 219, 'seasonNumber': 4, 'title': 'Example.Show.S04E04',
     'trackedDownloadState': 'downloading', 'trackedDownloadStatus': 'ok',
     'size': 100, 'sizeleft': 100, 'downloadClient': 'client-b', 'protocol': 'torrent',
     'errorMessage': 'The download is stalled with no connections'},
    # Blocked, and the service left the sentence that says what to do.
    {'id': 3, 'title': 'Something.Nobody.Matched',
     'trackedDownloadState': 'importBlocked', 'trackedDownloadStatus': 'warning',
     'size': 100, 'sizeleft': 0, 'downloadClient': 'client-b', 'protocol': 'torrent',
     'statusMessages': [{'title': 'Something.Nobody.Matched',
                         'messages': ['Title mismatch, automatic import is not '
                                      'possible. Manual Import required.']}]},
]


class _Config:
    """The smallest thing `LocalLibrary` needs: somewhere to look."""

    def __init__(self, values):
        self.values = values

    def get(self, key, default=''):
        return self.values.get(key, default)


class FakeResponse:
    def __init__(self, status_code=200, text='', headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def _answer(method, url, **kwargs):
    """`requests.request(method, url, ...)` — both are positional."""
    if '/series' in url:
        return FakeResponse(200, json.dumps(SERIES))
    if '/history' in url:
        return FakeResponse(200, json.dumps(HISTORY))
    if '/queue/details' in url:
        return FakeResponse(200, json.dumps(QUEUE))
    return FakeResponse(200, json.dumps({'appName': 'Sonarr', 'version': '4.0'}))


class MediaLibraryRouteTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = tmp.name
        self.db = DatabaseManager(os.path.join(tmp.name, 'library_routes.db'))
        self.store = ConnectorStore(self.db)
        self.store.upsert_connector('sonarr', 'Sonarr', enabled=True,
                                    config={'base_url': 'http://localhost:8989'})
        self.store.set_secret('sonarr', 'api_key', SECRET_KEY)
        self.service = ConnectorService(self.store, synchronous=True)
        # An empty library root: present, and holding nothing.
        empty_root = os.path.join(tmp.name, 'empty')
        os.makedirs(empty_root, exist_ok=True)
        self.index = MediaIndex(self.db, self.service,
                                config=_Config({'TVSHOW_DEST_PATH': empty_root}))
        self.index.store.upsert(SOURCE_SONARR, 900001, title='Example Show',
                                service_item_id=219)

        media_routes.init_media_library_routes(self.index)
        app = Flask(__name__)
        app.register_blueprint(media_routes.media_library_bp, url_prefix='/api')
        self.client = app.test_client()

        for target, value in (
            ('auth.get_token_from_request', 'token'),
            ('auth.validate_token', SIGNED_IN_PAYLOAD),
        ):
            patcher = patch(target, return_value=value)
            self.addCleanup(patcher.stop)
            patcher.start()
        patcher = patch('auth.resolve_identity',
                        return_value=(SIGNED_IN_IDENTITY, auth.REASON_OK))
        self.addCleanup(patcher.stop)
        patcher.start()

    # -- the invariants ------------------------------------------------------

    def test_no_endpoint_hands_back_the_api_key(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            for path in ('/api/library/sonarr', '/api/library/sonarr/history',
                         '/api/library/sonarr/queue'):
                body = self.client.get(path).get_data(as_text=True)
                self.assertNotIn(SECRET_KEY, body, path)

    def test_every_outbound_call_a_route_makes_is_a_read(self):
        seen = []

        def record(method, url, **kwargs):
            seen.append(method.upper())
            return _answer(method, url, **kwargs)

        with patch('services.connectors.transport.requests.request', side_effect=record):
            self.client.get('/api/library/sonarr')
            self.client.get('/api/library/sonarr/history')
            self.client.get('/api/library/sonarr/queue')
            self.client.post('/api/library/sonarr/refresh')

        self.assertTrue(seen, 'the routes should have reached the service')
        self.assertEqual(set(seen), {'GET'},
                         f'a route sent something other than GET: {set(seen)}')

    def test_no_route_in_this_file_can_start_a_transfer(self):
        import inspect
        source = inspect.getsource(media_routes)
        for forbidden in ('trigger_series_webhook_sync', 'trigger_webhook_sync',
                          'schedule_job', 'sync_notification_group',
                          'start_transfer'):
            self.assertNotIn(forbidden, source)

    # -- the library view ----------------------------------------------------

    def test_library_reports_what_the_service_holds(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            payload = self.client.get('/api/library/sonarr').get_json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['live'])
        self.assertTrue(payload['read_only'])
        self.assertEqual(payload['total'], 1)
        item = payload['items'][0]
        self.assertEqual(item['title'], 'Example Show')
        self.assertEqual(item['service_episode_file_count'], 20)

    def test_a_title_absent_from_the_disk_reads_as_missing(self):
        """The service holds 20 files; the temporary library holds none."""
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            payload = self.client.get('/api/library/sonarr').get_json()
        self.assertEqual(payload['items'][0]['sync_state'], 'never')

    def test_a_title_the_service_holds_no_files_for_is_not_judged(self):
        """Of 129 series in one real Sonarr, 99 had no files at all.

        Judging those as "never synced" turned two genuine gaps into a hundred
        warnings, which is the same as having no warnings.
        """
        empty = [dict(SERIES[0], statistics={'seasonCount': 1, 'episodeCount': 10,
                                             'episodeFileCount': 0, 'sizeOnDisk': 0},
                      seasons=[{'seasonNumber': 1, 'monitored': True,
                                'statistics': {'episodeCount': 10, 'episodeFileCount': 0}}])]

        def answer(method, url, **kwargs):
            if '/series' in url:
                return FakeResponse(200, json.dumps(empty))
            return _answer(method, url, **kwargs)

        with patch('services.connectors.transport.requests.request', side_effect=answer):
            payload = self.client.get('/api/library/sonarr').get_json()
        item = payload['items'][0]
        self.assertEqual(item['sync_state'], 'no_files')
        self.assertFalse(item['service_has_files'])

    def test_presence_is_read_from_the_disk_not_the_transfer_log(self):
        """A folder with files reads as present even with no transfer recorded.

        Files put there by hand, restored from a backup, or synced by another
        instance sharing the disk are present either way. Deriving this from the
        transfer log reported a whole library as missing.
        """
        library = os.path.join(self.tmpdir, 'tv')
        season = os.path.join(library, 'Example Show (2021)', 'Season 01')
        os.makedirs(season, exist_ok=True)
        for n in range(1, 11):
            open(os.path.join(season, f'Example Show - S01E{n:02d}.mkv'), 'w').close()
        season2 = os.path.join(library, 'Example Show (2021)', 'Season 02')
        os.makedirs(season2, exist_ok=True)
        for n in range(1, 11):
            open(os.path.join(season2, f'Example Show - S02E{n:02d}.mkv'), 'w').close()

        self.index.local.config = _Config({'TVSHOW_DEST_PATH': library})
        self.index.local.scan(force=True)

        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            payload = self.client.get('/api/library/sonarr').get_json()
        item = payload['items'][0]
        self.assertEqual(item['sync_state'], 'synced')
        self.assertTrue(item['present_locally'])
        self.assertEqual(item['transfers'], 0, 'no transfer was ever recorded')

    def test_a_season_the_service_has_and_we_do_not_reads_as_partial(self):
        library = os.path.join(self.tmpdir, 'tv2')
        season = os.path.join(library, 'Example Show (2021)', 'Season 01')
        os.makedirs(season, exist_ok=True)
        for n in range(1, 11):
            open(os.path.join(season, f'Example Show - S01E{n:02d}.mkv'), 'w').close()

        self.index.local.config = _Config({'TVSHOW_DEST_PATH': library})
        self.index.local.scan(force=True)

        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            payload = self.client.get('/api/library/sonarr').get_json()
        item = payload['items'][0]
        self.assertEqual(item['sync_state'], 'partial')
        outstanding = [s['season_number'] for s in item['seasons']
                       if s['counts_towards_state'] and not s['synced_here']]
        self.assertEqual(outstanding, [2])

    def test_the_poster_is_carried_through(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            item = self.client.get('/api/library/sonarr').get_json()['items'][0]
        self.assertEqual(item['poster'], 'http://img/p.jpg')

    def test_specials_are_listed_but_do_not_decide_the_state(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            item = self.client.get('/api/library/sonarr').get_json()['items'][0]
        specials = [s for s in item['seasons'] if s['specials']]
        self.assertEqual(len(specials), 1, 'season 0 should still be shown')
        self.assertFalse(specials[0]['counts_towards_state'])

    def test_the_view_says_when_the_service_did_not_answer(self):
        import requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=requests.ConnectionError('down')):
            payload = self.client.get('/api/library/sonarr').get_json()
        self.assertTrue(payload['success'], 'a dead service is not a 500')
        self.assertFalse(payload['live'], 'it must not claim to be live')

    # -- the queue -----------------------------------------------------------

    def test_the_queue_explains_why_each_row_is_waiting(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            payload = self.client.get('/api/library/sonarr/queue').get_json()
        self.assertTrue(payload['live'])
        self.assertEqual(payload['total'], 3)
        verdicts = {r['verdict'] for r in payload['rows']}
        self.assertEqual(verdicts, {'stale', 'stalled', 'blocked'})

    def test_the_services_own_sentence_is_carried_through(self):
        """`importBlocked` says nothing an operator can act on; the message does."""
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            rows = self.client.get('/api/library/sonarr/queue').get_json()['rows']
        blocked = next(r for r in rows if r['verdict'] == 'blocked')
        self.assertIn('Manual Import required', blocked['why'])

    def test_a_row_naming_no_title_is_flagged_and_holds_nothing(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            rows = self.client.get('/api/library/sonarr/queue').get_json()['rows']
        orphan = next(r for r in rows if r['unattributed'])
        self.assertFalse(orphan['holds_sync'],
                         'a row that names no title cannot be holding one back')

    def test_a_stalled_row_is_not_holding_a_sync(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            rows = self.client.get('/api/library/sonarr/queue').get_json()['rows']
        stalled = next(r for r in rows if r['verdict'] == 'stalled')
        self.assertFalse(stalled['holds_sync'])
        self.assertTrue(stalled['needs_attention'])

    def test_the_queue_and_the_gate_agree(self):
        """Both read the same classifier, so they cannot drift apart.

        If they did, the screen would say a row is holding a sync while the
        scheduler had already released it — or worse, the other way round.
        """
        adapter = self.service.adapter('sonarr')
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            rows = self.client.get('/api/library/sonarr/queue').get_json()['rows']
            answer = adapter.in_flight(219, 4)
        holding = sum(1 for r in rows if r['holds_sync'] and r['season_number'] == 4)
        self.assertEqual(holding, answer.blocking)

    def test_everything_stuck_is_sorted_to_the_top(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            rows = self.client.get('/api/library/sonarr/queue').get_json()['rows']
        attention = [r['needs_attention'] for r in rows]
        self.assertEqual(attention, sorted(attention, reverse=True))

    def test_the_queue_says_so_when_the_service_is_down(self):
        import requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=requests.ConnectionError('down')):
            payload = self.client.get('/api/library/sonarr/queue').get_json()
        self.assertFalse(payload['live'])
        self.assertEqual(payload['rows'], [])

    # -- the sync button -----------------------------------------------------

    def test_sync_without_a_sweep_wired_is_a_503_not_a_crash(self):
        response = self.client.post('/api/library/sonarr/sync',
                                    json={'external_id': '900001'})
        self.assertEqual(response.status_code, 503)

    def test_sync_requires_an_external_id(self):
        import routes.media_library as media_routes

        class _StubSweep:
            def sync_one(self, source, external_id):
                return {'success': True, 'transfers_started': 1}

        media_routes.init_media_library_routes(self.index, scanner=_StubSweep())
        self.addCleanup(media_routes.init_media_library_routes, self.index)
        response = self.client.post('/api/library/sonarr/sync', json={})
        self.assertEqual(response.status_code, 400)

    def test_a_click_with_nothing_to_fetch_is_a_409_with_the_reason(self):
        import routes.media_library as media_routes

        class _StubSweep:
            def sync_one(self, source, external_id):
                return {'success': False,
                        'error': 'Everything the service holds is already here'}

        media_routes.init_media_library_routes(self.index, scanner=_StubSweep())
        self.addCleanup(media_routes.init_media_library_routes, self.index)
        response = self.client.post('/api/library/sonarr/sync',
                                    json={'external_id': '900001'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('already here', response.get_json()['error'])

    def test_an_unknown_source_is_refused(self):
        self.assertEqual(self.client.get('/api/library/nope').status_code, 404)

    # -- history -------------------------------------------------------------

    def test_history_matches_our_titles_and_flags_the_ones_it_cannot(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            payload = self.client.get('/api/library/sonarr/history').get_json()
        self.assertTrue(payload['live'])
        known = {r['known_here'] for r in payload['records']}
        self.assertEqual(known, {True, False},
                         'an import for a title we have never seen is the '
                         'shape a lost notification leaves behind')

    def test_history_rejects_nonsense_paging(self):
        response = self.client.get('/api/library/sonarr/history?page=abc')
        self.assertEqual(response.status_code, 400)

    def test_history_says_so_when_the_service_is_down(self):
        import requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=requests.ConnectionError('down')):
            payload = self.client.get('/api/library/sonarr/history').get_json()
        self.assertFalse(payload['live'])
        self.assertEqual(payload['records'], [])

    # -- refresh -------------------------------------------------------------

    def test_refresh_reads_the_catalogue_into_the_index(self):
        with patch('services.connectors.transport.requests.request', side_effect=_answer):
            payload = self.client.post('/api/library/sonarr/refresh').get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['titles_seen'], 1)

    def test_refresh_reports_a_dead_service_rather_than_pretending(self):
        import requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=requests.ConnectionError('down')):
            response = self.client.post('/api/library/sonarr/refresh')
        self.assertEqual(response.status_code, 502)


if __name__ == '__main__':
    unittest.main()
