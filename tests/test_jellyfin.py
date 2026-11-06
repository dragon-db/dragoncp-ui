#!/usr/bin/env python3
"""
Jellyfin: what is playing, and the record DragonCP keeps of every play.

What these hold down:

  1. A converted stream says why. The reasons Jellyfin gives are kept, every
     one seen during the play, not only the first.
  2. A play is one row, however many times it was seen, and a stream missing
     from one answer does not split it in two.
  3. Watched time counts only time somebody was watching: not paused time,
     and not the gap while DragonCP was not looking.
  4. A restart neither loses an open play nor leaves it open forever.
  5. Nothing is recorded unless "Record plays" is on, and the API key never
     comes back in a response.

Sessions are shaped from Jellyfin 10.11's own API description, with made-up
people and titles.
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
import routes.jellyfin as jellyfin_routes
from models.connector import ConnectorStore
from models.database import DatabaseManager
from services.connectors.adapters.jellyfin import JellyfinConnector
from services.connectors.service import ConnectorService
from services.jellyfin.recorder import GRACE_SECONDS, MAX_STEP_SECONDS, PlayRecorder
from services.jellyfin.service import ACTIVE_INTERVAL, BACKOFF, IDLE_INTERVAL, JellyfinService
from services.jellyfin.sessions import heavier, network_of, stream_from_session, streams_from_sessions

API_KEY = 'jellyfin-api-key-that-must-not-come-back'
ITEM_EPISODE = 'a' * 32
ITEM_MOVIE = 'b' * 32
SERIES_ID = 'c' * 32

SIGNED_IN_PAYLOAD = {'sub': 'tester', 'uid': 1, 'tv': 1, 'src': 'db', 'type': 'access'}
SIGNED_IN_IDENTITY = {
    'account_id': 1, 'username': 'tester', 'role': 'admin',
    'token_version': 1, 'must_change_password': False, 'source': 'db',
}


def episode_session(session_id='s1', *, method='Transcode', reasons=('SubtitleCodecNotSupported',),
                    paused=False, position=600, subtitle_index=3, address='8.8.8.8'):
    session = {
        'Id': session_id, 'UserId': 'u1', 'UserName': 'alex',
        'Client': 'Jellyfin Web', 'ApplicationVersion': '10.11.11',
        'DeviceId': 'd1', 'DeviceName': 'Living room TV', 'RemoteEndPoint': address,
        'PlayState': {'PositionTicks': position * 10_000_000, 'IsPaused': paused,
                      'PlayMethod': method, 'AudioStreamIndex': 1,
                      'SubtitleStreamIndex': subtitle_index},
        'NowPlayingItem': {
            'Id': ITEM_EPISODE, 'Type': 'Episode', 'Name': 'Pilot',
            'SeriesName': 'Example Show', 'SeriesId': SERIES_ID,
            'SeriesPrimaryImageTag': 'tag', 'ParentIndexNumber': 1, 'IndexNumber': 1,
            'ProductionYear': 2021, 'RunTimeTicks': 1440 * 10_000_000,
            'Container': 'mkv', 'Path': '/data/tvshows/Example Show/Season 01/x.mkv',
            'ProviderIds': {'Tvdb': '900001', 'Tmdb': ''},
            'MediaStreams': [
                {'Type': 'Video', 'Index': 0, 'Codec': 'hevc', 'Width': 1920, 'Height': 1080,
                 'BitDepth': 10, 'VideoRangeType': 'SDR'},
                {'Type': 'Audio', 'Index': 1, 'Codec': 'aac', 'Channels': 2,
                 'Language': 'jpn', 'IsDefault': True},
                {'Type': 'Audio', 'Index': 2, 'Codec': 'flac', 'Channels': 2},
                {'Type': 'Subtitle', 'Index': 3, 'Codec': 'ass', 'Language': 'eng',
                 'DisplayTitle': 'English - ASS'},
            ],
        },
    }
    if method != 'DirectPlay':
        session['TranscodingInfo'] = {
            'VideoCodec': 'h264', 'AudioCodec': 'aac', 'Container': 'ts',
            'IsVideoDirect': False, 'IsAudioDirect': True, 'Bitrate': 8_000_000,
            'Width': 1920, 'Height': 1080, 'HardwareAccelerationType': 'nvenc',
            'TranscodeReasons': list(reasons),
        }
    return session


def movie_session(session_id='s2'):
    return {
        'Id': session_id, 'UserId': 'u2', 'UserName': 'sam', 'Client': 'Infuse',
        'DeviceId': 'd2', 'DeviceName': 'Phone', 'RemoteEndPoint': '192.168.1.20',
        'PlayState': {'PositionTicks': 0, 'IsPaused': False, 'PlayMethod': 'DirectPlay'},
        'NowPlayingItem': {'Id': ITEM_MOVIE, 'Type': 'Movie', 'Name': 'Example Film',
                           'ProductionYear': 2020, 'ImageTags': {'Primary': 'p'},
                           'RunTimeTicks': 6000 * 10_000_000},
        # Left behind by an earlier conversion; a direct play must not show it.
        'TranscodingInfo': {'TranscodeReasons': ['ContainerNotSupported']},
    }


class SessionTests(unittest.TestCase):

    def test_a_converted_stream_carries_its_reasons_and_tracks(self):
        stream = stream_from_session(episode_session(
            reasons=['VideoCodecNotSupported', 'SubtitleCodecNotSupported']))
        self.assertEqual(stream['play_method'], 'Transcode')
        self.assertEqual(stream['transcode']['reasons'],
                         ['SubtitleCodecNotSupported', 'VideoCodecNotSupported'])
        self.assertTrue(stream['transcode']['video'])
        self.assertFalse(stream['transcode']['audio'])
        self.assertEqual(stream['transcode']['hardware'], 'nvenc')
        self.assertEqual(stream['source']['subtitle']['codec'], 'ass')
        self.assertEqual(stream['source']['audio']['codec'], 'aac')
        self.assertEqual(stream['source']['video']['bit_depth'], 10)
        self.assertEqual(stream['item']['series'], 'Example Show')
        self.assertEqual((stream['item']['season'], stream['item']['episode']), (1, 1))
        self.assertEqual(stream['item']['poster_id'], SERIES_ID)
        self.assertEqual(stream['item']['provider_ids'], {'Tvdb': '900001'})
        self.assertEqual(stream['position_seconds'], 600)

    def test_reasons_sent_as_one_string_are_split(self):
        session = episode_session()
        session['TranscodingInfo']['TranscodeReasons'] = 'ContainerNotSupported, AudioCodecNotSupported'
        stream = stream_from_session(session)
        self.assertEqual(stream['transcode']['reasons'],
                         ['AudioCodecNotSupported', 'ContainerNotSupported'])

    def test_a_direct_play_drops_leftover_conversion_details(self):
        stream = stream_from_session(movie_session())
        self.assertEqual(stream['play_method'], 'DirectPlay')
        self.assertIsNone(stream['transcode'])
        self.assertEqual(stream['item']['poster_id'], ITEM_MOVIE)

    def test_subtitles_switched_off_read_as_none(self):
        stream = stream_from_session(episode_session(subtitle_index=-1))
        self.assertIsNone(stream['source']['subtitle'])

    def test_a_session_playing_nothing_is_not_a_stream(self):
        idle = {'Id': 's9', 'UserName': 'alex', 'PlayState': {}}
        self.assertIsNone(stream_from_session(idle))

    def test_converted_streams_come_first(self):
        streams = streams_from_sessions([movie_session(), episode_session()])
        self.assertEqual([s['play_method'] for s in streams], ['Transcode', 'DirectPlay'])

    def test_the_home_network_and_the_tailnet_are_local(self):
        self.assertEqual(network_of('192.168.1.20'), 'local')
        self.assertEqual(network_of('100.101.102.103'), 'local')
        self.assertEqual(network_of('[::1]:8096'), 'local')
        self.assertEqual(network_of('::ffff:10.0.0.4'), 'local')
        self.assertEqual(network_of('8.8.8.8:51234'), 'remote')
        self.assertEqual(network_of('not an address'), '')

    def test_the_heavier_method_wins_and_unknown_never_does(self):
        self.assertEqual(heavier('DirectPlay', 'Transcode'), 'Transcode')
        self.assertEqual(heavier('Transcode', 'DirectStream'), 'Transcode')
        self.assertEqual(heavier(None, 'DirectPlay'), 'DirectPlay')
        self.assertEqual(heavier('DirectStream', ''), 'DirectStream')


class RecorderTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'plays.db'))
        self.recorder = PlayRecorder(self.db, clock=lambda: 1000.0)

    def _rows(self):
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM jellyfin_play ORDER BY id")]

    def test_one_play_is_one_row_however_often_it_is_seen(self):
        for moment in (1000, 1010, 1020, 1030):
            self.recorder.observe([stream_from_session(episode_session())], now=moment)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['watched_seconds'], 30)
        self.assertIsNone(rows[0]['ended_at'])
        self.assertEqual(rows[0]['user_name'], 'alex')
        self.assertEqual(rows[0]['play_method'], 'Transcode')
        self.assertTrue(rows[0]['video_transcoded'])

    def test_every_reason_seen_is_kept(self):
        self.recorder.observe([stream_from_session(episode_session(
            reasons=['SubtitleCodecNotSupported']))], now=1000)
        self.recorder.observe([stream_from_session(episode_session(
            reasons=['ContainerBitrateExceedsLimit']))], now=1010)
        reasons = json.loads(self._rows()[0]['transcode_reasons'])
        self.assertEqual(reasons, ['ContainerBitrateExceedsLimit', 'SubtitleCodecNotSupported'])

    def test_a_play_converted_halfway_through_counts_as_converted(self):
        self.recorder.observe([stream_from_session(episode_session(method='DirectPlay'))], now=1000)
        self.recorder.observe([stream_from_session(episode_session(method='Transcode'))], now=1010)
        self.recorder.observe([stream_from_session(episode_session(method='DirectPlay'))], now=1020)
        row = self._rows()[0]
        self.assertEqual(row['play_method'], 'Transcode')
        self.assertIsNotNone(row['transcode'])

    def test_paused_time_and_gaps_are_not_watched_time(self):
        self.recorder.observe([stream_from_session(episode_session())], now=1000)
        self.recorder.observe([stream_from_session(episode_session(paused=True))], now=1010)
        self.recorder.observe([stream_from_session(episode_session(paused=True))], now=1020)
        self.recorder.observe([stream_from_session(episode_session())], now=1030)
        # The poller was not looking for a while: only one step counts.
        self.recorder.observe([stream_from_session(episode_session())], now=1030 + 40)
        self.assertEqual(self._rows()[0]['watched_seconds'], 10 + MAX_STEP_SECONDS)

    def test_a_stream_missing_from_one_answer_is_not_split_in_two(self):
        self.recorder.observe([stream_from_session(episode_session())], now=1000)
        self.recorder.observe([], now=1010)
        self.recorder.observe([stream_from_session(episode_session())], now=1020)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['ended_at'])

    def test_a_play_closes_at_its_last_sighting_once_gone_long_enough(self):
        self.recorder.observe([stream_from_session(episode_session())], now=1000)
        summary = self.recorder.observe([], now=1000 + GRACE_SECONDS + 1)
        self.assertEqual(summary['closed'], 1)
        row = self._rows()[0]
        self.assertEqual(row['ended_at'], row['last_seen_at'])

    def test_a_stream_back_after_the_grace_is_a_new_play(self):
        """Answers at +10..+40 without it do not reach the grace; the one at +50
        has it again. Gone 50 s is over the 45 s grace, so that is two plays."""
        self.recorder.observe([stream_from_session(episode_session())], now=1000)
        for moment in (1010, 1020, 1030, 1040):
            self.recorder.observe([], now=moment)
        summary = self.recorder.observe([stream_from_session(episode_session())], now=1050)
        self.assertEqual((summary['opened'], summary['closed']), (1, 1))
        first, second = self._rows()
        self.assertEqual(first['ended_at'], first['last_seen_at'])
        self.assertIsNone(second['ended_at'])

    def test_back_within_the_grace_is_the_same_play(self):
        self.recorder.observe([stream_from_session(episode_session())], now=1000)
        self.recorder.observe([], now=1030)
        self.recorder.observe([stream_from_session(episode_session())], now=1000 + GRACE_SECONDS)
        self.assertEqual(len(self._rows()), 1)

    def test_the_next_episode_is_a_new_play(self):
        self.recorder.observe([stream_from_session(episode_session())], now=1000)
        nxt = episode_session()
        nxt['NowPlayingItem']['Id'] = 'd' * 32
        self.recorder.observe([stream_from_session(nxt)], now=1010)
        self.assertEqual(len(self._rows()), 2)

    def test_a_play_still_going_after_a_restart_carries_on(self):
        self.recorder.observe([stream_from_session(episode_session())], now=1000)
        restarted = PlayRecorder(self.db, clock=lambda: 1020.0)
        restarted.observe([stream_from_session(episode_session())], now=1020)
        restarted.observe([stream_from_session(episode_session())], now=1030)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        # The gap across the restart is not counted; the step after it is.
        self.assertEqual(rows[0]['watched_seconds'], 10)

    def test_a_play_that_ended_while_down_is_closed_after_the_restart(self):
        self.recorder.observe([stream_from_session(episode_session())], now=1000)
        restarted = PlayRecorder(self.db)
        restarted.observe([], now=5000)
        row = self._rows()[0]
        self.assertIsNotNone(row['ended_at'])
        self.assertEqual(restarted.open_count(), 0)

    def test_the_history_filters(self):
        self.recorder.observe([stream_from_session(episode_session()),
                               stream_from_session(movie_session())], now=1000)
        everything = self.recorder.plays()
        self.assertEqual(everything['total'], 2)
        self.assertEqual(set(everything['users']), {'alex', 'sam'})
        converted = self.recorder.plays(converted=True)['plays']
        self.assertEqual([p['user'] for p in converted], ['alex'])
        self.assertEqual(converted[0]['reasons'], ['SubtitleCodecNotSupported'])
        self.assertEqual(self.recorder.plays(converted=False)['plays'][0]['user'], 'sam')
        self.assertEqual(self.recorder.plays(user='sam')['total'], 1)
        self.assertEqual(self.recorder.plays(search='Example Show')['total'], 1)


class FakeAdapter:
    def __init__(self, sessions=None, ok=True, record=True):
        self._sessions = sessions or []
        self._ok = ok
        self._record = record
        self.calls = 0

    def sessions(self):
        self.calls += 1
        if not self._ok:
            return False, [], 'Could not reach http://localhost:8096'
        return True, self._sessions, ''

    def record_plays(self):
        return self._record


class ServiceTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'service.db'))
        self.now = 1000.0
        self.service = JellyfinService(self.db, secret='test-secret', connectors=lambda: None,
                                       clock=lambda: self.now)

    def _with(self, adapter):
        self.service.adapter = lambda: adapter

    def _count(self):
        with self.db.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM jellyfin_play").fetchone()[0]

    def test_switched_off_reads_as_off_and_schedules_nothing(self):
        snapshot = self.service.poll()
        self.assertEqual(snapshot['state'], 'off')
        self.assertIsNone(self.service.interval())

    def test_switching_recording_off_mid_play_closes_the_play(self):
        adapter = FakeAdapter([episode_session()])
        self._with(adapter)
        self.service.poll()
        adapter._record = False
        # The scheduler stops; the Plays tab is what notices.
        self.now += 60
        page = self.service.plays()
        self.assertEqual(page['total'], 1)
        self.assertIsNotNone(page['plays'][0]['ended_at'])
        self.assertEqual(self.service.recorder.open_count(), 0)

    def test_jellyfin_switched_off_mid_play_closes_the_play(self):
        self._with(FakeAdapter([episode_session()]))
        self.service.poll()
        self._with(None)
        self.now += 5
        self.assertEqual(self.service.poll()['state'], 'off')
        self.assertEqual(self.service.recorder.open_count(), 0)

    def test_nothing_is_recorded_while_recording_is_off(self):
        self._with(FakeAdapter([episode_session()], record=False))
        snapshot = self.service.poll()
        self.assertEqual(len(snapshot['streams']), 1)
        self.assertFalse(snapshot['recording'])
        self.assertEqual(self._count(), 0)
        self.assertIsNone(self.service.interval())

    def test_recording_on_records_and_asks_more_often_while_playing(self):
        self._with(FakeAdapter([episode_session()]))
        self.assertEqual(self.service.interval(), IDLE_INTERVAL)
        self.service.run_job()
        self.assertEqual(self._count(), 1)
        self.assertEqual(self.service.interval(), ACTIVE_INTERVAL)

    def test_two_questions_at_once_ask_jellyfin_once(self):
        adapter = FakeAdapter([episode_session()])
        self._with(adapter)
        self.service.poll()
        self.service.poll()
        self.assertEqual(adapter.calls, 1)
        self.now += 5
        self.service.poll()
        self.assertEqual(adapter.calls, 2)

    def test_it_backs_off_while_jellyfin_is_not_answering(self):
        self._with(FakeAdapter(ok=False))
        intervals = []
        for _ in range(4):
            result = self.service.run_job()
            self.assertFalse(result['ok'])
            intervals.append(self.service.interval())
            self.now += 10
        self.assertEqual(intervals, [BACKOFF[0], BACKOFF[1], BACKOFF[2], BACKOFF[2]])

    def test_poster_addresses_are_signed(self):
        url = self.service.poster_url(SERIES_ID)
        signature = url.split('s=')[1]
        self.assertTrue(self.service.signature_ok(SERIES_ID, signature))
        self.assertFalse(self.service.signature_ok(ITEM_MOVIE, signature))
        self.assertFalse(self.service.signature_ok(SERIES_ID, ''))


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.text = json.dumps(payload) if payload is not None else ''
        self.headers = {}


class AdapterTests(unittest.TestCase):

    def _adapter(self, **config):
        return JellyfinConnector(config={'base_url': 'http://localhost:8096/', **config},
                                 secrets=lambda name: API_KEY if name == 'api_key' else '')

    def test_episode_counts_leave_out_episodes_without_a_file(self):
        """Seerr's Requests tab shows "6 of 10 episodes" from this."""
        seen = {}

        def answer(method, url, **kwargs):
            seen['url'] = url
            return FakeResponse(payload={'Items': [
                {'ParentIndexNumber': 1, 'IndexNumber': 1, 'LocationType': 'FileSystem'},
                {'ParentIndexNumber': 1, 'IndexNumber': 2, 'LocationType': 'FileSystem'},
                {'ParentIndexNumber': 2, 'IndexNumber': 1, 'LocationType': 'FileSystem'},
                {'ParentIndexNumber': 2, 'IndexNumber': 2, 'LocationType': 'Virtual'},
            ]})

        with patch('services.connectors.transport.requests.request', side_effect=answer):
            counts = self._adapter().episode_counts(SERIES_ID)
        self.assertEqual(counts, {1: 2, 2: 1})
        self.assertIn(f'/Shows/{SERIES_ID}/Episodes?isMissing=false', seen['url'])
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(500, {})):
            self.assertIsNone(self._adapter().episode_counts(SERIES_ID))

    def test_it_uses_the_documented_authorization_header(self):
        seen = {}

        def answer(method, url, headers=None, **kwargs):
            seen['url'], seen['headers'] = url, headers
            return FakeResponse(payload={'Version': '10.11.11', 'ServerName': 'Home'})

        with patch('services.connectors.transport.requests.request', side_effect=answer):
            result = self._adapter().check()
        self.assertTrue(result.ok)
        self.assertEqual(result.message, 'Connected to Home 10.11.11')
        self.assertEqual(seen['url'], 'http://localhost:8096/System/Info')
        self.assertEqual(seen['headers']['Authorization'], f'MediaBrowser Token="{API_KEY}"')
        self.assertNotIn('X-Emby-Token', seen['headers'])

    def test_a_rejected_key_says_so(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(401)):
            self.assertEqual(self._adapter().check().message, 'The API key was rejected')
            ok, _, error = self._adapter().sessions()
        self.assertFalse(ok)
        self.assertEqual(error, 'Jellyfin rejected the API key')

    def test_sessions_that_are_not_a_list_are_refused(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(payload={'not': 'a list'})):
            ok, sessions, _ = self._adapter().sessions()
        self.assertFalse(ok)
        self.assertEqual(sessions, [])

    def test_recording_is_off_unless_switched_on(self):
        self.assertFalse(self._adapter().record_plays())
        self.assertTrue(self._adapter(record_plays='true').record_plays())

    def test_the_page_shows_its_own_tabs(self):
        self.assertEqual(self._adapter().describe()['views'], ['now_playing', 'plays'])


class RouteTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'routes.db'))
        store = ConnectorStore(self.db)
        store.upsert_connector('jellyfin', 'Jellyfin', enabled=True,
                               config={'base_url': 'http://localhost:8096',
                                       'record_plays': 'true'})
        store.set_secret('jellyfin', 'api_key', API_KEY)
        connectors = ConnectorService(store, synchronous=True)
        self.service = JellyfinService(self.db, secret='route-secret',
                                       connectors=lambda: connectors)
        jellyfin_routes.init_jellyfin_routes(self.service)
        app = Flask(__name__)
        app.register_blueprint(jellyfin_routes.jellyfin_bp, url_prefix='/api')
        self.client = app.test_client()

    def _sign_in(self):
        for target, value in (('auth.get_token_from_request', 'token'),
                              ('auth.validate_token', SIGNED_IN_PAYLOAD)):
            patcher = patch(target, return_value=value)
            self.addCleanup(patcher.stop)
            patcher.start()
        patcher = patch('auth.resolve_identity',
                        return_value=(SIGNED_IN_IDENTITY, auth.REASON_OK))
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_reading_needs_a_sign_in(self):
        self.assertEqual(self.client.get('/api/jellyfin/now-playing').status_code, 401)
        self.assertEqual(self.client.get('/api/jellyfin/plays').status_code, 401)

    def test_now_playing_records_and_never_returns_the_key(self):
        self._sign_in()
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(payload=[episode_session(), movie_session()])):
            response = self.client.get('/api/jellyfin/now-playing')
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(API_KEY, body)
        data = response.get_json()
        self.assertEqual(len(data['streams']), 2)
        self.assertTrue(data['recording'])
        self.assertTrue(data['streams'][0]['item']['poster'].startswith('/api/jellyfin/image/'))
        plays = self.client.get('/api/jellyfin/plays?converted=1').get_json()
        self.assertEqual(plays['total'], 1)
        self.assertNotIn(API_KEY, json.dumps(plays))

    def test_an_image_needs_a_valid_signature_not_a_sign_in(self):
        self.assertEqual(self.client.get(f'/api/jellyfin/image/{SERIES_ID}?s=wrong').status_code,
                         404)
        self.assertEqual(self.client.get('/api/jellyfin/image/not-an-id?s=x').status_code, 404)
        url = self.service.poster_url(SERIES_ID)

        class Streamed:
            status_code = 200
            headers = {'Content-Type': 'image/jpeg'}

            def iter_content(self, size):
                yield b'\xff\xd8poster'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with patch('services.connectors.transport.requests.get', return_value=Streamed()) as get:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'\xff\xd8poster')
        self.assertEqual(response.mimetype, 'image/jpeg')
        self.assertIn(f'/Items/{SERIES_ID}/Images/Primary', get.call_args[0][0])


if __name__ == '__main__':
    unittest.main()
