#!/usr/bin/env python3
"""
Seerr: requests, where approved ones have got to, and issues.

What these hold down:

  1. Each request says where it is in words: waiting, searching (flagged after
     three days), downloading on the remote server, held back, syncing here,
     synced, partly or fully in Jellyfin.
  2. The sync part comes from DragonCP's own arrivals, matched by TVDB/TMDB id
     and only since the request.
  3. A test instance refuses every change until "Allow changes" is on, asks
     Seerr nothing when it refuses, and logs the refusal.
  4. An edit before approving sends Seerr every field, changed or not, because
     Seerr's edit replaces them all.
  5. The webhook needs its password; a sign-in is not enough and not needed.
  6. No API key, webhook password, e-mail address or service token comes back.

Payloads are shaped from Seerr 3.2.0's own code, with made-up people and titles.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import auth
import routes.seerr as seerr_routes
from models.connector import ConnectorStore
from models.database import DatabaseManager
from services.connectors.adapters.seerr import Answer, SeerrConnector
from services.connectors.service import ConnectorService
from services.seerr.arrivals import arrivals_for, sqlite_time
from services.seerr.service import POLL_BACKOFF, POLL_INTERVAL, SeerrService
from services.seerr.titles import TitleCache, from_seerr
from services.seerr.views import (
    STUCK_AFTER_SECONDS,
    download_block,
    issue_view,
    person,
    request_view,
)

API_KEY = 'seerr-api-key-that-must-not-come-back'
WEBHOOK_SECRET = 'seerr-webhook-password-that-must-not-come-back'
NOW = 1_800_000_000.0  # 2027-01-15


def at(seconds_ago: float) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(NOW - seconds_ago))


SIGNED_IN_PAYLOAD = {'sub': 'tester', 'uid': 1, 'tv': 1, 'src': 'db', 'type': 'access'}
SIGNED_IN_IDENTITY = {
    'account_id': 1, 'username': 'tester', 'role': 'admin',
    'token_version': 1, 'must_change_password': False, 'source': 'db',
}


def user(uid=2, name='alex'):
    return {'id': uid, 'displayName': name, 'email': f'{name}@example.invalid',
            'jellyfinUsername': name, 'jellyfinAuthToken': 'token-that-must-not-come-back',
            'plexToken': 'plex-token-that-must-not-come-back'}


def a_request(rid=1, *, status=2, kind='tv', media_status=3, seasons=(1,), media_seasons=None,
              downloads=None, created=4 * 86400, updated=4 * 86400, tvdb=101, tmdb=201,
              jellyfin_id=None, is4k=False):
    media = {
        'id': 50 + rid, 'mediaType': kind, 'tmdbId': tmdb, 'tvdbId': tvdb if kind == 'tv' else None,
        'status': media_status, 'status4k': 1,
        'seasons': [{'seasonNumber': n, 'status': s} for n, s in (media_seasons or [])],
        'downloadStatus': downloads or [], 'downloadStatus4k': [],
        'jellyfinMediaId': jellyfin_id,
    }
    return {
        'id': rid, 'status': status, 'type': kind, 'is4k': is4k, 'media': media,
        'seasons': [{'id': 900 + n, 'seasonNumber': n, 'status': status} for n in seasons]
        if kind == 'tv' else [],
        'requestedBy': user(), 'modifiedBy': user(1, 'owner') if status != 1 else None,
        'createdAt': at(created), 'updatedAt': at(updated),
        'serverId': 0, 'profileId': 4, 'rootFolder': '/media/tv', 'languageProfileId': 1,
        'tags': [3], 'profileName': 'HD-1080p',
    }


def an_issue(iid=7, *, kind=3, status=1, season=1, episode=2, comments=2):
    return {
        'id': iid, 'issueType': kind, 'status': status, 'problemSeason': season,
        'problemEpisode': episode,
        'media': {'mediaType': 'tv', 'tmdbId': 201, 'tvdbId': 101, 'jellyfinMediaId': 'c' * 32},
        'createdBy': user(3, 'sam'), 'modifiedBy': None,
        'comments': [{'id': 70 + n, 'user': user(3, 'sam') if n == 0 else user(1, 'owner'),
                      'message': 'No subtitles on this one' if n == 0 else f'Reply {n}',
                      'createdAt': at(3600 - n * 60)} for n in range(comments)],
        'createdAt': at(3600), 'updatedAt': at(600),
    }


def arrival(status='completed', *, held=False, reason='', season=1, transfer_status='',
            percent=None, eta=None, when='2027-01-14 10:00:00', kind='arrival'):
    return {'kind': kind, 'at': when, 'status': status, 'held': held, 'reason': reason,
            'season': season, 'transfer_status': transfer_status, 'percent': percent,
            'eta_seconds': eta}


# ------------------------------------------------------------------ views

class RequestViewTests(unittest.TestCase):

    def view(self, raw, **kwargs):
        return request_view(raw, now=NOW, **kwargs)

    def test_a_waiting_request_offers_approve_and_decline(self):
        view = self.view(a_request(status=1))
        self.assertEqual(view['stage']['key'], 'waiting')
        self.assertEqual(view['actions'], ['approve', 'decline'])
        self.assertEqual(view['steps'][0]['state'], 'active')

    def test_a_failed_request_offers_retry(self):
        view = self.view(a_request(status=4, kind='movie'))
        self.assertEqual(view['stage']['key'], 'failed')
        self.assertIn('Radarr', view['stage']['detail'])
        self.assertEqual(view['actions'], ['retry'])

    def test_searching_is_flagged_after_three_days(self):
        fresh = self.view(a_request(updated=86400))
        self.assertEqual(fresh['stage']['label'], 'Searching')
        self.assertFalse(fresh['stage']['stuck'])
        stuck = self.view(a_request(updated=STUCK_AFTER_SECONDS + 86400))
        self.assertEqual(stuck['stage']['label'], 'Searching for 4 days')
        self.assertTrue(stuck['stage']['stuck'])
        self.assertEqual(stuck['stage']['tone'], 'warn')
        self.assertEqual(stuck['steps'][1]['state'], 'problem')

    def test_a_download_shows_percent_and_time_left(self):
        downloads = [{'downloadId': 'd1', 'size': 1000, 'sizeLeft': 250, 'status': 'downloading',
                      'estimatedCompletionTime': at(-600), 'episode': {'seasonNumber': 1, 'episodeNumber': 3}},
                     {'downloadId': 'd1', 'size': 1000, 'sizeLeft': 250, 'status': 'downloading',
                      'estimatedCompletionTime': at(-600), 'episode': {'seasonNumber': 1, 'episodeNumber': 4}}]
        view = self.view(a_request(downloads=downloads))
        self.assertEqual(view['stage']['key'], 'downloading')
        self.assertEqual(view['stage']['percent'], 75)
        self.assertIn('on the remote server', view['stage']['detail'])
        self.assertIn('10 minutes left', view['stage']['detail'])
        # One season pack is one download, not two.
        self.assertEqual(view['download']['downloads'], 1)
        self.assertTrue(view['seasons'][0]['downloading'])
        self.assertEqual(view['steps'][1]['state'], 'active')

    def test_a_download_with_a_warning_says_so(self):
        block = download_block([{'size': 10, 'sizeLeft': 5, 'status': 'warning'}], NOW)
        self.assertEqual(block['state'], 'warning')

    def test_other_seasons_do_not_move_a_request(self):
        """Season 2 asked for; only season 1 downloaded, synced and is in Jellyfin."""
        downloads = [{'downloadId': 'd1', 'size': 10, 'sizeLeft': 5, 'status': 'downloading',
                      'episode': {'seasonNumber': 1, 'episodeNumber': 3}}]
        raw = a_request(seasons=(2,), media_status=4, media_seasons=[(1, 5)],
                        downloads=downloads, updated=86400)
        view = self.view(raw, arrivals=[arrival('completed', season=1)])
        self.assertEqual(view['stage']['key'], 'searching')
        self.assertIsNone(view['download'])
        self.assertIsNone(view['sync'])
        self.assertEqual([s['state'] for s in view['steps']], ['done', 'waiting', 'todo', 'todo'])

    def test_its_own_season_does_move_it(self):
        raw = a_request(seasons=(2,), media_status=4, media_seasons=[(1, 5)])
        view = self.view(raw, arrivals=[arrival('completed', season=1),
                                         arrival('completed', season=2, when='2027-01-14 11:00:00')])
        self.assertEqual(view['stage']['key'], 'synced')

    def test_a_sync_that_names_no_season_still_counts(self):
        raw = a_request(seasons=(2,))
        view = self.view(raw, arrivals=[arrival('syncing', season=None, kind='transfer',
                                                transfer_status='running', percent=10)])
        self.assertEqual(view['stage']['key'], 'syncing')

    def test_a_held_sync_needs_you_with_the_reason(self):
        view = self.view(a_request(), arrivals=[arrival('pending', held=True, reason='files would be deleted')])
        self.assertEqual(view['stage']['key'], 'held')
        self.assertIn('files would be deleted', view['stage']['detail'])
        self.assertEqual(view['steps'][1]['state'], 'done')
        self.assertEqual(view['steps'][2]['state'], 'problem')

    def test_a_running_sync_shows_its_progress(self):
        view = self.view(a_request(), arrivals=[arrival('syncing', transfer_status='running', percent=40, eta=120)])
        self.assertEqual(view['stage']['key'], 'syncing')
        self.assertEqual(view['stage']['percent'], 40)
        self.assertIn('2 minutes left', view['stage']['detail'])

    def test_synced_but_not_yet_in_jellyfin(self):
        view = self.view(a_request(), arrivals=[arrival('completed', transfer_status='completed')])
        self.assertEqual(view['stage']['key'], 'synced')
        self.assertEqual(view['steps'][2]['state'], 'done')
        self.assertEqual(view['steps'][3]['state'], 'todo')

    def test_a_later_success_clears_an_earlier_failure(self):
        view = self.view(a_request(), arrivals=[
            arrival('failed', when='2027-01-14 09:00:00'),
            arrival('completed', when='2027-01-14 10:00:00')])
        self.assertEqual(view['stage']['key'], 'synced')

    def test_one_season_syncing_does_not_hide_another_failing(self):
        raw = a_request(seasons=(1, 2))
        view = self.view(raw, arrivals=[
            arrival('failed', season=1, when='2027-01-14 09:00:00'),
            arrival('completed', season=2, when='2027-01-14 10:00:00')])
        self.assertEqual(view['stage']['key'], 'sync_failed')

    def test_only_the_season_being_synced_shows_as_syncing(self):
        raw = a_request(seasons=(1, 2))
        view = self.view(raw, arrivals=[
            arrival('completed', season=1, when='2027-01-14 09:00:00'),
            arrival('syncing', season=2, transfer_status='running', percent=30,
                    when='2027-01-14 10:00:00')])
        self.assertEqual(view['stage']['key'], 'syncing')
        self.assertEqual([(s['number'], s['syncing']) for s in view['seasons']],
                         [(1, False), (2, True)])

    def test_a_whole_series_sync_clears_a_season_failure(self):
        raw = a_request(seasons=(1, 2))
        view = self.view(raw, arrivals=[
            arrival('failed', season=1, when='2027-01-14 09:00:00'),
            arrival('completed', season=None, kind='transfer', when='2027-01-14 10:00:00')])
        self.assertEqual(view['stage']['key'], 'synced')

    def test_available_is_in_jellyfin_with_every_step_done(self):
        view = self.view(a_request(status=5, media_status=5))
        self.assertEqual(view['stage']['key'], 'in_jellyfin')
        self.assertEqual([s['state'] for s in view['steps']], ['done'] * 4)

    def test_seasons_show_what_jellyfin_has(self):
        raw = a_request(seasons=(1, 2), media_status=4, media_seasons=[(1, 5), (2, 4)])
        title = {'title': 'Example Show', 'year': 2024, 'poster_path': '/p.jpg',
                 'seasons': [[1, 8], [2, 10]]}
        view = self.view(raw, title=title, episodes_here={1: 8, 2: 6})
        self.assertEqual(view['stage']['key'], 'partly')
        self.assertEqual([(s['number'], s['state'], s['episodes_here'], s['episodes_total'])
                          for s in view['seasons']],
                         [(1, 'available', 8, 8), (2, 'partial', 6, 10)])
        self.assertEqual(view['title']['name'], 'Example Show')
        self.assertTrue(view['title']['poster'].endswith('/p.jpg'))

    def test_every_requested_season_available_counts_as_done(self):
        raw = a_request(seasons=(1,), media_status=4, media_seasons=[(1, 5), (2, 1)])
        self.assertEqual(self.view(raw)['stage']['key'], 'in_jellyfin')

    def test_people_are_names_only(self):
        view = self.view(a_request())
        text = json.dumps(view)
        self.assertEqual(view['requested_by'], {'id': 2, 'name': 'alex'})
        for secret in ('example.invalid', 'token-that-must-not-come-back',
                       'plex-token-that-must-not-come-back'):
            self.assertNotIn(secret, text)
        self.assertEqual(person({'id': 9}), {'id': 9, 'name': 'User 9'})


class IssueViewTests(unittest.TestCase):

    def test_an_issue_reads_as_type_episode_reporter_and_thread(self):
        view = issue_view(an_issue(comments=3))
        self.assertEqual(view['type'], 'subtitles')
        self.assertEqual(view['status'], 'open')
        self.assertEqual((view['season'], view['episode']), (1, 2))
        self.assertEqual(view['reported_by']['name'], 'sam')
        self.assertEqual(view['message'], 'No subtitles on this one')
        self.assertEqual(view['replies'], 2)
        self.assertEqual([c['message'] for c in view['comments']][0], 'No subtitles on this one')
        self.assertNotIn('example.invalid', json.dumps(view))

    def test_season_zero_means_the_whole_title(self):
        view = issue_view(an_issue(season=0, episode=0))
        self.assertIsNone(view['season'])
        self.assertIsNone(view['episode'])


# ---------------------------------------------------------------- arrivals

class ArrivalTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'arrivals.db'))
        with self.db.get_connection() as conn:
            for nid, tvdb, created, status, sim, transfer in (
                    ('n-old', 101, '2026-01-01 00:00:00', 'completed', 0, None),
                    ('n-new', 101, '2027-01-14 10:00:00', 'syncing', 0, 't1'),
                    ('n-sim', 101, '2027-01-14 11:00:00', 'completed', 1, None),
                    ('n-other', 999, '2027-01-14 10:00:00', 'completed', 0, None)):
                conn.execute('''INSERT INTO sonarr_webhook (notification_id, media_type, series_title,
                                series_path, season_path, tvdb_id, season_number, status, created_at,
                                is_simulation, transfer_id)
                                VALUES (?, 'tvshows', 'Example Show', '/x', '/x/S1', ?, 1, ?, ?, ?, ?)''',
                             (nid, tvdb, status, created, sim, transfer))
            conn.execute('''INSERT INTO transfers (transfer_id, media_type, folder_name, source_path,
                            dest_path, operation_type, status, progress_percent, eta_seconds)
                            VALUES ('t1', 'tvshows', 'Example Show', '/a', '/b', 'folder', 'running', 55, 30)''')
            conn.commit()

    def test_only_this_titles_real_arrivals_since_the_request_count(self):
        found = arrivals_for(self.db, 'tv', tvdb_id=101, tmdb_id=None, since='2027-01-01 00:00:00')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['status'], 'syncing')
        self.assertEqual(found[0]['transfer_status'], 'running')
        self.assertEqual(found[0]['percent'], 55)

    def test_a_hand_started_sync_carries_its_season(self):
        with self.db.get_connection() as conn:
            conn.execute("""INSERT INTO media_item (source, external_id, title)
                            VALUES ('sonarr', '101', 'Example Show')""")
            item = conn.execute("SELECT id FROM media_item WHERE external_id = '101'").fetchone()[0]
            conn.execute("""INSERT INTO transfers (transfer_id, media_type, folder_name, season_name,
                            source_path, dest_path, operation_type, status, media_item_id, created_at)
                            VALUES ('t2', 'tvshows', 'Example Show', 'Season 02', '/a', '/b',
                            'explore_sync', 'completed', ?, '2027-01-14 12:00:00')""", (item,))
            conn.commit()
        found = arrivals_for(self.db, 'tv', tvdb_id=101, tmdb_id=None, since='2027-01-01 00:00:00')
        hand = [a for a in found if a['kind'] == 'transfer']
        self.assertEqual([(a['season'], a['status']) for a in hand], [(2, 'completed')])

    def test_seerr_time_becomes_sqlite_utc(self):
        self.assertEqual(sqlite_time('2027-01-14T10:00:27.000Z'), '2027-01-14 10:00:27')
        self.assertIsNone(sqlite_time(''))


# -------------------------------------------------------------------- titles

class TitleTests(unittest.TestCase):

    def test_a_series_answer_keeps_name_year_poster_and_seasons(self):
        row = from_seerr('tv', {'name': 'Example Show', 'firstAirDate': '2024-03-01',
                                'posterPath': '/p.jpg',
                                'seasons': [{'seasonNumber': 1, 'episodeCount': 8}]})
        self.assertEqual(row, {'title': 'Example Show', 'year': 2024, 'poster_path': '/p.jpg',
                               'seasons': [[1, 8]]})

    def test_a_kept_title_goes_stale_after_three_days(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clock = [NOW]
        cache = TitleCache(DatabaseManager(os.path.join(tmp.name, 't.db')), clock=lambda: clock[0])
        cache.put('movie', 5, {'title': 'Example Film', 'year': 2020, 'poster_path': '', 'seasons': []})
        row = cache.get_many([('movie', 5)])[('movie', 5)]
        self.assertTrue(cache.is_fresh(row))
        clock[0] += 4 * 86400
        self.assertFalse(cache.is_fresh(row))


# ------------------------------------------------------------------ adapter

class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.text = json.dumps(payload) if payload is not None else ''
        self.headers = {}


class AdapterTests(unittest.TestCase):

    def adapter(self, base='http://localhost:5055/api/v1/'):
        return SeerrConnector(config={'base_url': base},
                              secrets=lambda name: {'api_key': API_KEY}.get(name, ''))

    def test_check_proves_the_key_not_only_the_address(self):
        seen = []

        def answer(method, url, headers=None, **kwargs):
            seen.append((method, url, headers['X-Api-Key']))
            if url.endswith('/status'):
                return FakeResponse(payload={'version': '3.2.0'})
            return FakeResponse(401, {'message': 'Unauthorized'})

        with patch('services.connectors.transport.requests.request', side_effect=answer):
            result = self.adapter().check()
        self.assertFalse(result.ok)
        self.assertEqual(result.message, 'Seerr rejected the API key')
        self.assertEqual(seen[0][1], 'http://localhost:5055/api/v1/status')
        self.assertEqual(seen[1][1], 'http://localhost:5055/api/v1/auth/me')
        self.assertEqual(seen[0][2], API_KEY)

    def test_check_names_the_version(self):
        def answer(method, url, **kwargs):
            return FakeResponse(payload={'version': '3.2.0'} if url.endswith('/status') else {'id': 1})

        with patch('services.connectors.transport.requests.request', side_effect=answer):
            self.assertEqual(self.adapter().check().message, 'Connected to Seerr 3.2.0')

    def test_a_change_is_never_sent_twice(self):
        calls = MagicMock(return_value=FakeResponse(500, {'message': 'Something broke'}))
        with patch('services.connectors.transport.requests.request', calls):
            answer = self.adapter().comment(7, 'On it')
        self.assertEqual(calls.call_count, 1)
        self.assertFalse(answer.ok)
        self.assertEqual(answer.error, 'Seerr said: Something broke')

    def test_an_edit_that_changed_nothing_is_not_success(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(202, {'message': 'No seasons available to request'})):
            answer = self.adapter().update_request(1, {'mediaType': 'tv'})
        self.assertFalse(answer.ok)
        self.assertIn('No seasons available', answer.error)


# ------------------------------------------------------------------ service

class FakeSeerr:
    """Seerr as the service sees it: an adapter with canned answers."""

    def __init__(self, *, allow=False, poll=False, secret=WEBHOOK_SECRET):
        self.calls = []
        self.allow, self.poll, self.secret = allow, poll, secret
        self.requests_raw = [a_request(1, status=1), a_request(2, status=2, kind='movie', tmdb=301)]
        self.single = {1: a_request(1, status=1), 2: a_request(2, status=2, kind='movie', tmdb=301),
                       4: a_request(4, status=4)}

    def is_configured(self):
        return True

    def allows_changes(self):
        return self.allow

    def polls(self):
        return self.poll

    def webhook_secret(self):
        return self.secret

    def requests(self, **kwargs):
        self.calls.append(('requests', kwargs))
        return Answer(True, {'pageInfo': {'results': len(self.requests_raw)}, 'results': self.requests_raw})

    def request_counts(self):
        self.calls.append(('request_counts',))
        return Answer(True, {'pending': 1, 'processing': 1, 'total': 2})

    def issue_counts(self):
        self.calls.append(('issue_counts',))
        return Answer(True, {'open': 3, 'closed': 1, 'total': 4})

    def request_one(self, rid):
        self.calls.append(('request_one', rid))
        return Answer(True, self.single[rid]) if rid in self.single else Answer(False, error='gone')

    def set_request_status(self, rid, status):
        self.calls.append(('status', rid, status))
        return Answer(True, {'id': rid})

    def retry_request(self, rid):
        self.calls.append(('retry', rid))
        return Answer(True, {'id': rid})

    def update_request(self, rid, body):
        self.calls.append(('update', rid, body))
        return Answer(True, {'id': rid}, status=200)

    def issues(self, **kwargs):
        self.calls.append(('issues', kwargs))
        return Answer(True, {'pageInfo': {'results': 1}, 'results': [an_issue()]})

    def issue_one(self, iid):
        self.calls.append(('issue_one', iid))
        return Answer(True, an_issue(iid))

    def comment(self, iid, message):
        self.calls.append(('comment', iid, message))
        return Answer(True, {})

    def set_issue_status(self, iid, status):
        self.calls.append(('issue_status', iid, status))
        return Answer(True, {})

    def title(self, media_type, tmdb_id):
        self.calls.append(('title', media_type, tmdb_id))
        if media_type == 'movie':
            return Answer(True, {'title': 'Example Film', 'releaseDate': '2020-05-01', 'posterPath': '/f.jpg'})
        return Answer(True, {'name': 'Example Show', 'firstAirDate': '2024-01-01', 'posterPath': '/s.jpg',
                             'seasons': [{'seasonNumber': 1, 'episodeCount': 8}]})

    def users(self):
        return Answer(True, {'results': [user(3, 'sam'), user(2, 'alex')]})

    def writes(self):
        return [c for c in self.calls if c[0] in ('status', 'retry', 'update', 'comment', 'issue_status')]


class ServiceTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'service.db'))
        self.fake = FakeSeerr()
        self.test_mode = True
        self.socket = MagicMock()
        self.service = SeerrService(self.db, connectors=lambda: None, socketio=self.socket,
                                    clock=lambda: NOW, test_mode=lambda: self.test_mode)
        self.service.adapter = lambda: self.fake
        for name in ('record', 'record_refusal', 'record_failure'):
            patcher = patch(f'services.seerr.service.{name}')
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_a_test_instance_refuses_changes_and_asks_seerr_nothing(self):
        result = self.service.decide(1, 'approve')
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 403)
        self.assertIn('Allow changes from this instance', result['error'])
        self.assertEqual(self.fake.calls, [])
        self.record_refusal.assert_called_once()
        reply = self.service.reply(7, 'On it')
        self.assertEqual(reply['status'], 403)
        self.assertEqual(self.fake.writes(), [])

    def test_allowed_approve_is_logged_with_the_title_and_requester(self):
        self.fake.allow = True
        self.service.requests(view='waiting')  # names the title
        result = self.service.decide(1, 'approve')
        self.assertTrue(result['ok'])
        self.assertIn(('status', 1, 'approve'), self.fake.calls)
        summary = self.record.call_args[0][1]
        self.assertEqual(summary, 'Approved the request for Example Show (2024), season 1 by alex')
        self.socket.emit.assert_called_with('seerr_changed', {'kind': 'request', 'id': 1})

    def test_a_production_instance_needs_no_switch(self):
        self.test_mode = False
        self.assertTrue(self.service.decide(1, 'decline')['ok'])
        self.assertIn(('status', 1, 'decline'), self.fake.calls)

    def test_a_request_no_longer_waiting_is_not_approved(self):
        self.fake.allow = True
        result = self.service.decide(2, 'approve')
        self.assertEqual(result['status'], 409)
        self.assertIn('already approved', result['error'])
        self.assertEqual(self.fake.writes(), [])

    def test_retry_is_only_for_a_failed_request(self):
        self.fake.allow = True
        self.assertTrue(self.service.decide(4, 'retry')['ok'])
        self.assertIn(('retry', 4), self.fake.calls)

    def test_an_edit_before_approving_sends_every_field(self):
        self.fake.allow = True
        result = self.service.decide(1, 'approve', changes={'profile_id': 7, 'seasons': [1, 2]})
        self.assertTrue(result['ok'])
        update = next(c for c in self.fake.calls if c[0] == 'update')
        self.assertEqual(update[2], {
            'mediaType': 'tv', 'serverId': 0, 'profileId': 7, 'rootFolder': '/media/tv',
            'languageProfileId': 1, 'tags': [3], 'userId': 2, 'seasons': [1, 2]})
        order = [c[0] for c in self.fake.writes()]
        self.assertEqual(order, ['update', 'status'])
        # The log names what was approved, not what was first asked for.
        self.assertIn('seasons 1, 2 by alex (with changes)', self.record.call_args[0][1])

    def test_an_edit_that_changes_nothing_is_not_sent(self):
        self.fake.allow = True
        self.service.decide(1, 'approve', changes={'profile_id': 4})
        self.assertEqual([c[0] for c in self.fake.writes()], ['status'])

    def test_answers_are_reused_until_something_changes(self):
        self.service.requests(view='waiting')
        self.service.requests(view='waiting')
        self.assertEqual(sum(1 for c in self.fake.calls if c[0] == 'requests'), 1)
        self.service.webhook(WEBHOOK_SECRET, {'notification_type': 'MEDIA_PENDING'})
        self.service.requests(view='waiting')
        self.assertEqual(sum(1 for c in self.fake.calls if c[0] == 'requests'), 2)

    def test_titles_are_asked_for_once(self):
        self.service.requests(view='all')
        self.service.forget()
        self.service.requests(view='all')
        self.assertEqual(sum(1 for c in self.fake.calls if c[0] == 'title'), 2)  # one each

    def test_reply_and_resolve_does_both(self):
        self.fake.allow = True
        self.assertTrue(self.service.reply(7, 'Fixed, try again', resolve=True)['ok'])
        self.assertEqual([c[0] for c in self.fake.writes()], ['comment', 'issue_status'])
        self.assertEqual(self.service.reply(7, '   ')['status'], 400)

    def test_the_webhook_needs_its_password(self):
        self.assertEqual(self.service.webhook('wrong', {})[0], 401)
        self.assertEqual(self.service.webhook('', {})[0], 401)
        self.assertEqual(self.service.webhook(f'Bearer {WEBHOOK_SECRET}', {})[0], 200)
        self.fake.secret = ''
        self.assertEqual(self.service.webhook('', {})[0], 403)

    def test_a_webhook_tells_the_page_which_tab_changed(self):
        self.service.webhook(WEBHOOK_SECRET, {'notification_type': 'ISSUE_CREATED'})
        self.socket.emit.assert_called_with('seerr_changed', {'kind': 'issue'})
        self.assertEqual(self.service.webhook_state()['last_type'], 'ISSUE_CREATED')
        self.assertEqual(self.service.webhook_state()['last_at'], '2027-01-15T08:00:00Z')

    def test_summary_counts(self):
        summary = self.service.summary()
        self.assertEqual(summary['requests']['pending'], 1)
        self.assertEqual(summary['issues']['open'], 3)
        self.assertFalse(summary['can_change'])

    def test_the_job_only_runs_when_switched_on(self):
        self.assertIsNone(self.service.interval())
        self.fake.poll = True
        self.assertEqual(self.service.interval(), POLL_INTERVAL)
        self.fake.request_counts = lambda: Answer(False, error='down')
        self.assertFalse(self.service.run_job()['ok'])
        self.assertEqual(self.service.interval(), POLL_BACKOFF[0])

    def test_users_are_names_only(self):
        self.assertEqual(self.service.users(), [{'id': 2, 'name': 'alex'}, {'id': 3, 'name': 'sam'}])


# ------------------------------------------------------------------- routes

class RouteTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'routes.db'))
        store = ConnectorStore(self.db)
        store.upsert_connector('seerr', 'Seerr', enabled=True,
                               config={'base_url': 'http://localhost:5055'})
        store.set_secret('seerr', 'api_key', API_KEY)
        store.set_secret('seerr', 'webhook_secret', WEBHOOK_SECRET)
        connectors = ConnectorService(store, synchronous=True)
        self.service = SeerrService(self.db, connectors=lambda: connectors,
                                    test_mode=lambda: True)
        seerr_routes.init_seerr_routes(self.service)
        app = Flask(__name__)
        app.register_blueprint(seerr_routes.seerr_bp, url_prefix='/api')
        self.client = app.test_client()

    def _sign_in(self):
        for target, value in (('auth.get_token_from_request', 'token'),
                              ('auth.validate_token', SIGNED_IN_PAYLOAD)):
            patcher = patch(target, return_value=value)
            self.addCleanup(patcher.stop)
            patcher.start()
        patcher = patch('auth.resolve_identity', return_value=(SIGNED_IN_IDENTITY, auth.REASON_OK))
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_reading_and_changing_need_a_sign_in(self):
        for path in ('/api/seerr/summary', '/api/seerr/requests', '/api/seerr/issues',
                     '/api/seerr/users', '/api/seerr/requests/1/options'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in ('/api/seerr/requests/1/approve', '/api/seerr/issues/7/comment',
                     '/api/seerr/issues/7/resolve'):
            self.assertEqual(self.client.post(path, json={}).status_code, 401, path)

    def test_the_list_never_returns_secrets_or_emails(self):
        self._sign_in()

        def answer(method, url, **kwargs):
            if '/request?' in url:
                return FakeResponse(payload={'pageInfo': {'results': 1}, 'results': [a_request(1, status=1)]})
            if '/tv/' in url:
                return FakeResponse(payload={'name': 'Example Show', 'firstAirDate': '2024-01-01'})
            return FakeResponse(404, {})

        with patch('services.connectors.transport.requests.request', side_effect=answer):
            response = self.client.get('/api/seerr/requests?view=waiting')
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['requests'][0]['title']['name'], 'Example Show')
        for secret in (API_KEY, WEBHOOK_SECRET, 'example.invalid', 'token-that-must-not-come-back'):
            self.assertNotIn(secret, body)

    def test_a_change_on_the_test_instance_is_refused_before_seerr_is_asked(self):
        self._sign_in()
        calls = MagicMock()
        with patch('services.connectors.transport.requests.request', calls):
            response = self.client.post('/api/seerr/requests/1/approve', json={})
        self.assertEqual(response.status_code, 403)
        self.assertIn('Allow changes', response.get_json()['error'])
        calls.assert_not_called()

    def test_the_webhook_takes_a_password_not_a_sign_in(self):
        self.assertEqual(self.client.post('/api/webhook/seerr', json={}).status_code, 401)
        response = self.client.post('/api/webhook/seerr', json={'notification_type': 'TEST_NOTIFICATION'},
                                    headers={'Authorization': WEBHOOK_SECRET})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(WEBHOOK_SECRET, response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
