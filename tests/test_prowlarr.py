#!/usr/bin/env python3
"""
Prowlarr: search every indexer from DragonCP, and see which are healthy.

What these hold down:

  1. A search is one question per indexer, each answered on its own, so one
     slow or failing indexer neither holds nor ends the rest.
  2. Nothing is asked twice: no retry, the same search within five minutes is
     answered from what was found, and an indexer Prowlarr has paused or one
     without the chosen categories is not asked at all.
  3. No download address, magnet address, guid or API key reaches the page.
  4. Downloads only ever go to the saved Prowlarr address, even when Prowlarr
     writes its links with another one.
  5. A test instance refuses "Send to download client" until allowed, asks
     Prowlarr nothing when it refuses, and logs the refusal.
  6. Every address needs a sign-in.
  7. Before a send, the page is told where a release lands and whether Sonarr
     or Radarr will import it from there, the way Prowlarr and they decide;
     after it, where it is in their queue. Sonarr and Radarr are only read.

Payloads are shaped from Prowlarr's v1 API, with made-up indexers and releases.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import auth
import routes.prowlarr as prowlarr_routes
from models.connector import ConnectorStore
from models.database import DatabaseManager
from services.connectors import transport
from services.prowlarr.arr import ArrLink, landing_category, same_name
from services.connectors.adapters.prowlarr import Answer, ProwlarrConnector
from services.connectors.service import ConnectorService
from services.prowlarr.service import ProwlarrService, REUSE_SECONDS, _read_params, SearchError
from services.prowlarr.views import covers_categories, indexer_view, release_view

API_KEY = 'prowlarr-api-key-that-must-not-come-back'
PASSKEY = 'tracker-passkey-that-must-not-come-back'
NOW = 1_800_000_000.0
SIGNED_IN_PAYLOAD = {'sub': 'tester', 'uid': 1, 'tv': 1, 'src': 'db', 'type': 'access'}
SIGNED_IN_IDENTITY = {
    'account_id': 1, 'username': 'tester', 'role': 'admin',
    'token_version': 1, 'must_change_password': False, 'source': 'db',
}


def indexer(iid, name, protocol='torrent', enable=True, categories=(2000, 5000)):
    return {
        'id': iid, 'name': name, 'protocol': protocol, 'privacy': 'private',
        'enable': enable, 'priority': 25, 'definitionName': name.lower(),
        'indexerUrls': [f'https://{name.lower()}.example/'],
        'capabilities': {
            'categories': [{'id': c, 'name': {2000: 'Movies', 5000: 'TV', 3000: 'Audio'}.get(c, 'Other'),
                            'subCategories': [{'id': c + 40, 'name': 'HD'}]} for c in categories],
            'searchParams': ['q'], 'tvSearchParams': ['q', 'season', 'ep'], 'movieSearchParams': ['q'],
        },
    }


def release(n, indexer_id=1, protocol='torrent'):
    return {
        'guid': f'https://tracker.example/details/{n}?passkey={PASSKEY}',
        'title': f'Example.Show.S01E0{n}.1080p.WEB-DL.x264-GRP',
        'size': 1_500_000_000 + n, 'publishDate': '2027-01-14T10:00:00Z',
        'indexerId': indexer_id, 'indexer': f'Indexer {indexer_id}', 'protocol': protocol,
        'seeders': 40 + n, 'leechers': 2, 'grabs': 100,
        'downloadUrl': f'https://prowlarr.example/{indexer_id}/download?apikey={API_KEY}&link=abc{n}',
        'magnetUrl': f'https://prowlarr.example/{indexer_id}/download?apikey={API_KEY}&link=mag{n}',
        'infoUrl': f'https://tracker.example/details/{n}',
        'categories': [{'id': 5040, 'name': 'TV/HD'}],
        'indexerFlags': ['freeleech'], 'infoHash': 'ABCDEF',
    }


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.text = json.dumps(payload) if payload is not None else ''
        self.headers = {}


class Immediate:
    """An executor that runs each job on submit, so a search finishes at once."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, **kwargs):
        pass


# ------------------------------------------------------------------ adapter

class AdapterTests(unittest.TestCase):

    def adapter(self, base='https://prowlarr.example/'):
        return ProwlarrConnector(config={'base_url': base},
                                 secrets=lambda name: {'api_key': API_KEY}.get(name, ''))

    def test_check_names_the_version_and_refuses_another_app(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(payload={'appName': 'Prowlarr', 'version': '1.30.0'})):
            self.assertEqual(self.adapter().check().message, 'Connected to Prowlarr 1.30.0')
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(payload={'appName': 'Sonarr', 'version': '4.0'})):
            self.assertFalse(self.adapter().check().ok)

    def test_a_search_lists_ids_as_repeated_keys_and_is_never_retried(self):
        calls = MagicMock(return_value=FakeResponse(500, {'message': 'Indexer down'}))
        with patch('services.connectors.transport.requests.request', calls):
            answer = self.adapter().search('example', search_type='tvsearch',
                                           indexer_ids=[4], categories=[5000, 2000])
        self.assertEqual(calls.call_count, 1)
        url = calls.call_args.args[1]
        self.assertTrue(url.startswith('https://prowlarr.example/api/v1/search?'))
        self.assertIn('indexerIds=4', url)
        self.assertIn('categories=5000&categories=2000', url)
        self.assertIn('type=tvsearch', url)
        self.assertEqual(answer.error, 'Prowlarr said: Indexer down')

    def test_downloads_only_go_to_the_saved_address(self):
        adapter = self.adapter('https://media.example/prowlarr')
        # Prowlarr behind a proxy writes http:// and its own host name.
        self.assertEqual(
            adapter.download_url('http://prowlarr:9696/prowlarr/3/download?apikey=k&link=x'),
            'https://media.example/prowlarr/3/download?apikey=k&link=x')
        self.assertEqual(
            adapter.download_url('http://evil.example/3/download?link=x'),
            'https://media.example/prowlarr/3/download?link=x')
        self.assertEqual(adapter.download_url('file:///etc/passwd'), '')

    def test_a_validation_failure_is_said_in_words(self):
        with patch('services.connectors.transport.requests.request',
                   side_effect=[FakeResponse(payload={'id': 3, 'name': 'X'}),
                                FakeResponse(400, [{'propertyName': 'BaseUrl',
                                                    'errorMessage': 'Unable to connect to indexer'}])]):
            answer = self.adapter().test_indexer(3)
        self.assertFalse(answer.ok)
        self.assertEqual(answer.error, 'Prowlarr said: Unable to connect to indexer')


class DownloadTests(unittest.TestCase):

    def test_a_redirect_to_a_magnet_is_the_answer(self):
        response = MagicMock(status_code=302, headers={'Location': 'magnet:?xt=urn:btih:abc'})
        response.__enter__ = lambda self: self
        response.__exit__ = lambda self, *a: None
        with patch('services.connectors.transport.requests.get', return_value=response):
            result = transport.fetch_download('https://prowlarr.example/1/download')
        self.assertTrue(result.ok)
        self.assertEqual(result.magnet, 'magnet:?xt=urn:btih:abc')

    def test_the_key_is_not_carried_to_a_tracker(self):
        hop = MagicMock(status_code=302, headers={'Location': 'https://tracker.example/file'})
        done = MagicMock(status_code=200, headers={'Content-Type': 'application/x-bittorrent'})
        done.iter_content = lambda size: [b'd8:announce']
        for r in (hop, done):
            r.__enter__ = lambda self: self
            r.__exit__ = lambda self, *a: None
        get = MagicMock(side_effect=[hop, done])
        with patch('services.connectors.transport.requests.get', get):
            result = transport.fetch_download('https://prowlarr.example/1/download',
                                              headers={'X-Api-Key': API_KEY})
        self.assertEqual(result.content, b'd8:announce')
        self.assertEqual(get.call_args_list[0].kwargs['headers'], {'X-Api-Key': API_KEY})
        self.assertIsNone(get.call_args_list[1].kwargs['headers'])


# -------------------------------------------------------------------- views

class ViewTests(unittest.TestCase):

    def test_a_release_view_carries_no_credential(self):
        view = release_view(release(1), 0)
        text = json.dumps(view)
        self.assertNotIn(API_KEY, text)
        self.assertNotIn(PASSKEY, text)
        self.assertNotIn('guid', view)
        self.assertEqual(view['flags'], ['freeleech'])
        self.assertTrue(view['can_magnet'])
        self.assertEqual(view['info_hash'], 'abcdef')

    def test_usenet_has_no_seeders(self):
        view = release_view(dict(release(1), protocol='usenet'), 0)
        self.assertIsNone(view['seeders'])

    def test_categories_cover_parents_and_children(self):
        tree = [{'id': 5000, 'name': 'TV', 'subs': [5040]}]
        self.assertTrue(covers_categories(tree, [5040]))
        self.assertTrue(covers_categories(tree, [5070]))  # TV/Anime under TV
        self.assertFalse(covers_categories(tree, [2000]))
        self.assertTrue(covers_categories([], [2000]))  # no list: benefit of the doubt
        self.assertTrue(covers_categories([{'id': 100001, 'name': 'x', 'subs': [5040]}], [5000]))

    def test_an_indexer_says_whether_it_works(self):
        now = datetime.fromtimestamp(NOW, timezone.utc)
        paused = indexer_view(indexer(1, 'Alpha'), {'disabledTill': '2030-01-01T00:00:00Z',
                                                    'initialFailure': '2027-01-14T00:00:00Z',
                                                    'mostRecentFailure': '2027-01-15T00:00:00Z'},
                              None, now)
        self.assertEqual(paused['state'], 'paused')
        off = indexer_view(indexer(2, 'Bravo', enable=False), None, None, now)
        self.assertEqual(off['state'], 'off')
        ok = indexer_view(indexer(3, 'Charlie'), None,
                          {'numberOfQueries': 200, 'numberOfFailedQueries': 10,
                           'averageResponseTime': 640}, now)
        self.assertEqual(ok['state'], 'ok')
        self.assertEqual(ok['stats']['failure_rate'], 0.05)
        self.assertEqual(ok['search_types'], ['search', 'tvsearch', 'movie'])


class ParamTests(unittest.TestCase):

    def test_episode_and_ids_become_prowlarr_tokens(self):
        query, kind, cats, scope, picked = _read_params({
            'query': 'Example Show', 'type': 'tvsearch', 'season': '1', 'episode': '2',
            'imdb_id': '0000001', 'categories': [5000, '5000'],
        })
        self.assertEqual(query, 'Example Show {ImdbId:tt0000001} {Season:01} {Episode:02}')
        self.assertEqual(cats, [5000])

    def test_tokens_typed_by_hand_are_not_passed_through(self):
        query, *_ = _read_params({'query': 'Example {Season:99}', 'type': 'search'})
        self.assertEqual(query, 'Example')

    def test_bad_searches_are_refused_in_words(self):
        for params, words in (({'query': ''}, 'Type something'),
                              ({'query': 'x', 'type': 'tvsearch', 'episode': '2'}, 'season'),
                              ({'query': 'x', 'imdb_id': 'nope', 'type': 'movie'}, 'IMDb'),
                              ({'query': 'x', 'scope': 'picked'}, 'Pick at least one')):
            with self.assertRaises(SearchError) as caught:
                _read_params(params)
            self.assertIn(words, str(caught.exception))


# ------------------------------------------------------------------ service

# ------------------------------------------------- Sonarr and Radarr side

def prowlarr_client(cid, impl, protocol, default, mappings, host='box.example', port=443):
    return {'id': cid, 'name': impl, 'implementation': impl, 'protocol': protocol,
            'enable': True, 'priority': 1, 'supportsCategories': True,
            'fields': [{'name': 'host', 'value': host}, {'name': 'port', 'value': port},
                       {'name': 'category', 'value': default}],
            'categories': [{'clientCategory': c, 'categories': ids} for c, ids in mappings]}


QBIT = prowlarr_client(9, 'QBittorrent', 'torrent', 'prowlarr',
                       [('tv-sonarr', [5000]), ('radarr', [2000])])


class FakeArr:
    """Sonarr or Radarr as `ArrLink` sees it: GET only, canned answers."""

    STUCK_VERDICTS = frozenset({'stalled', 'blocked', 'failed'})

    def __init__(self, field, category, *, host='box.example', parse=None, cdh=True):
        self.calls = []
        self.clients = [{'name': 'qBit', 'implementation': 'QBittorrent', 'enable': True,
                         'fields': [{'name': 'host', 'value': host}, {'name': 'port', 'value': 443},
                                    {'name': field, 'value': category}]}]
        self.cdh = cdh
        self.parsed = parse or {}
        self.queue = []
        self.imports = []

    def is_configured(self):
        return True

    def _get(self, path, params=None, timeout=12.0):
        self.calls.append(path)
        if path == '/api/v3/downloadclient':
            return True, self.clients
        if path == '/api/v3/config/downloadclient':
            return True, {'enableCompletedDownloadHandling': self.cdh}
        if path == '/api/v3/parse':
            return True, self.parsed
        return False, None

    def imports_since(self, since):
        self.calls.append('history')
        return True, self.imports

    def queue_all(self):
        self.calls.append('queue')
        return True, self.queue

    def classify_row(self, row):
        state = row.get('trackedDownloadState')
        return {'verdict': state, 'why': f'Still {state}', 'holds': True}


class FakeConnectors:
    def __init__(self, adapters):
        self.adapters = adapters
        self.store = self

    def get_connector(self, app):
        return {'enabled': True} if app in self.adapters else None

    def adapter(self, app):
        return self.adapters.get(app)


SONARR_MATCH = {
    'parsedEpisodeInfo': {'seriesTitle': 'Example Show', 'seasonNumber': 1, 'episodeNumbers': [2]},
    'series': {'title': 'Example Show', 'year': 2020, 'tvdbId': 77, 'seriesType': 'standard'},
    'episodes': [{'seasonNumber': 1, 'episodeNumber': 2, 'hasFile': None, 'episodeFileId': 31}],
}


class ArrLinkTests(unittest.TestCase):

    def test_landing_category_follows_prowlarr_mapping_then_family_then_default(self):
        self.assertEqual(landing_category(QBIT, [5000]), ('tv-sonarr', 'mapped'))
        self.assertEqual(landing_category(QBIT, [5070, 100123]), ('tv-sonarr', 'mapped'))
        self.assertEqual(landing_category(QBIT, [2040]), ('radarr', 'mapped'))
        self.assertEqual(landing_category(QBIT, [8000]), ('prowlarr', 'default'))
        self.assertEqual(landing_category(QBIT, [100123]), ('prowlarr', 'default'))
        bare = dict(QBIT, categories=[], fields=[])
        self.assertEqual(landing_category(bare, [5000]), ('', 'none'))

    def test_release_names_match_without_dots_case_or_an_extension(self):
        self.assertTrue(same_name('Example.Show.S01E02.1080p-GRP', 'example show s01e02 1080p grp'))
        self.assertTrue(same_name('Example.Show.S01E02.1080p-GRP', 'Example.Show.S01E02.1080p-GRP.mkv'))
        self.assertFalse(same_name('Example.Show.S01E02.1080p-GRP', 'Example.Show.S01E03.1080p-GRP'))
        self.assertFalse(same_name('', ''))

    def link(self, **adapters):
        return ArrLink(connectors=lambda: FakeConnectors(adapters), clock=lambda: NOW)

    def test_the_app_watching_the_landing_category_on_the_same_client_is_found(self):
        link = self.link(sonarr=FakeArr('tvCategory', 'tv-sonarr'),
                         radarr=FakeArr('movieCategory', 'radarr'))
        self.assertEqual([w['app'] for w in link.watchers(QBIT, 'tv-sonarr')], ['sonarr'])
        self.assertEqual([w['app'] for w in link.watchers(QBIT, 'radarr')], ['radarr'])
        self.assertEqual(link.watchers(QBIT, 'prowlarr'), [])

    def test_a_client_at_another_address_still_counts_and_no_category_watches_all(self):
        link = self.link(sonarr=FakeArr('tvCategory', 'tv-sonarr', host='localhost'),
                         radarr=FakeArr('movieCategory', ''))
        watchers = {w['app']: w for w in link.watchers(QBIT, 'tv-sonarr')}
        self.assertEqual(set(watchers), {'sonarr', 'radarr'})
        self.assertTrue(watchers['radarr']['everything'])

    def test_completed_download_handling_off_is_reported(self):
        link = self.link(sonarr=FakeArr('tvCategory', 'tv-sonarr', cdh=False))
        (watcher,) = link.watchers(QBIT, 'tv-sonarr')
        self.assertFalse(watcher['imports'])

    def test_sonarr_reading_says_which_show_and_episodes_and_flags_another_show(self):
        link = self.link(sonarr=FakeArr('tvCategory', 'tv-sonarr', parse=SONARR_MATCH))
        reading = link.parse('sonarr', 'Example.Show.S01E02', {'tvdb_id': 77})
        self.assertEqual((reading['state'], reading['title'], reading['season'], reading['episodes']),
                         ('matched', 'Example Show', 1, [2]))
        self.assertEqual((reading['found'], reading['have']), (1, 1))
        self.assertFalse(reading['other_title'])
        other = self.link(sonarr=FakeArr('tvCategory', 'x', parse=SONARR_MATCH)).parse(
            'sonarr', 'Example.Show.S01E02', {'tvdb_id': 78})
        self.assertTrue(other['other_title'])

    def test_unmatched_and_unreadable_names(self):
        unmatched = self.link(sonarr=FakeArr('tvCategory', 'x', parse={
            'parsedEpisodeInfo': {'seriesTitle': 'Alpha Bravo', 'absoluteEpisodeNumbers': [12]}}))
        reading = unmatched.parse('sonarr', 'Alpha Bravo - 12', {})
        self.assertEqual((reading['state'], reading['read_as'], reading['absolute']),
                         ('unmatched', 'Alpha Bravo', [12]))
        nothing = self.link(radarr=FakeArr('movieCategory', 'x', parse={'title': 'zzz'}))
        self.assertEqual(nothing.parse('radarr', 'zzz', {})['state'], 'unreadable')

    def test_a_name_is_read_once_per_app(self):
        sonarr = FakeArr('tvCategory', 'x', parse=SONARR_MATCH)
        link = self.link(sonarr=sonarr)
        link.parse('sonarr', 'A.B.C', {})
        link.parse('sonarr', 'A.B.C', {})
        self.assertEqual(sonarr.calls.count('/api/v3/parse'), 1)

    def test_after_a_send_history_then_queue_say_where_it_is(self):
        sonarr = FakeArr('tvCategory', 'tv-sonarr')
        link = self.link(sonarr=sonarr)
        self.assertEqual(link.track('sonarr', 'Example.Show.S01E02', NOW)['state'], 'not_seen')
        sonarr.queue = [{'title': 'Example.Show.S01E02', 'trackedDownloadState': 'downloading',
                         'size': 100, 'sizeleft': 25, 'seriesId': 3}]
        link._tracks.clear()
        queued = link.track('sonarr', 'Example.Show.S01E02', NOW)
        self.assertEqual((queued['state'], queued['progress'], queued['known']), ('queued', 0.75, True))
        sonarr.imports = [{'sourceTitle': 'Example.Show.S01E02'}]
        link._tracks.clear()
        self.assertEqual(link.track('sonarr', 'Example.Show.S01E02', NOW)['state'], 'imported')

    def test_nothing_but_reads_reach_sonarr_or_radarr(self):
        source = (REPO_ROOT / 'services' / 'prowlarr' / 'arr.py').read_text()
        self.assertNotIn('_request(', source)
        self.assertNotIn('command(', source)


class FakeProwlarr:
    """The adapter as the service sees it: canned answers, every call counted."""

    def __init__(self, *, allow=False):
        self.allow = allow
        self.searched = []
        self.grabs = []
        self.indexer_list = [indexer(1, 'Alpha'), indexer(2, 'Bravo'),
                             indexer(3, 'Charlie', protocol='usenet'),
                             indexer(4, 'Delta', categories=(3000,)),
                             indexer(5, 'Echo', enable=False)]
        self.status_list = [{'indexerId': 2, 'disabledTill': '2030-01-01T00:00:00Z',
                             'initialFailure': '2027-01-14T00:00:00Z',
                             'mostRecentFailure': '2027-01-15T00:00:00Z'}]
        self.failing = set()

    def allows_grabs(self):
        return self.allow

    def indexers(self):
        return Answer(True, data=self.indexer_list)

    def indexer_status(self):
        return Answer(True, data=self.status_list)

    def indexer_stats(self, start=None):
        return Answer(True, data={'indexers': []})

    def health(self):
        return Answer(True, data=[{'source': 'IndexerStatusCheck', 'type': 'warning',
                                   'message': 'Indexers unavailable due to failures: Bravo'}])

    def download_clients(self):
        return Answer(True, data=[{'id': 9, 'name': 'Client', 'protocol': 'torrent', 'enable': True}])

    def status(self):
        return Answer(True, data={'version': '1.30.0'})

    def search(self, query, *, search_type, indexer_ids, categories, limit):
        (iid,) = indexer_ids
        self.searched.append(iid)
        if iid in self.failing:
            return Answer(False, error='Prowlarr said: Indexer timed out', duration_ms=30000)
        return Answer(True, data=[release(n, iid) for n in range(1, 3)], duration_ms=400)

    def grab(self, guid, indexer_id, client=None):
        self.grabs.append((guid, indexer_id, client))
        return Answer(True, data={})

    def download(self, url):
        return transport.DownloadResult(True, magnet='magnet:?xt=urn:btih:abc')


class ServiceTests(unittest.TestCase):

    def setUp(self):
        self.fake = FakeProwlarr()
        self.clock = [NOW]
        self.test_mode = [True]
        self.service = ProwlarrService(connectors=lambda: None, clock=lambda: self.clock[0],
                                       test_mode=lambda: self.test_mode[0], executor=Immediate())
        self.service.adapter = lambda: self.fake
        for name in ('record', 'record_failure', 'record_refusal'):
            patcher = patch(f'services.prowlarr.service.{name}')
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def start(self, **params):
        answer = self.service.start_search(dict({'query': 'Example Show'}, **params))
        self.assertTrue(answer['ok'], answer)
        return answer['search_id']

    def test_each_indexer_is_asked_once_and_paused_or_off_ones_not_at_all(self):
        search = self.service.poll(self.start(), 0)
        self.assertEqual(sorted(self.fake.searched), [1, 3, 4])
        states = {r['id']: r['state'] for r in search['indexers']}
        self.assertEqual(states, {1: 'done', 2: 'skipped', 3: 'done', 4: 'done'})
        self.assertFalse(search['running'])
        self.assertEqual(search['total'], 6)

    def test_route_says_where_a_release_lands_who_imports_it_and_then_where_it_is(self):
        self.fake.download_clients = lambda: Answer(True, data=[QBIT])
        sonarr = FakeArr('tvCategory', 'tv-sonarr', parse=SONARR_MATCH)
        radarr = FakeArr('movieCategory', 'radarr')
        self.service.arr = ArrLink(connectors=lambda: FakeConnectors(
            {'sonarr': sonarr, 'radarr': radarr}), clock=lambda: self.clock[0])
        search_id = self.start()
        route = self.service.release_route(search_id, 0)
        (client,) = route['clients']
        self.assertEqual((client['category'], client['how']), ('tv-sonarr', 'mapped'))
        self.assertEqual([w['app'] for w in client['watchers']], ['sonarr'])
        self.assertEqual([r['app'] for r in route['readings']], ['sonarr'])
        self.assertEqual(route['readings'][0]['state'], 'matched')
        self.assertIsNone(route['sent'])
        self.assertNotIn('queue', sonarr.calls)
        self.assertNotIn('box.example', json.dumps(route))

        self.fake.allow = True
        self.assertTrue(self.service.grab(search_id, 0, 9)['ok'])
        route = self.service.release_route(search_id, 0)
        self.assertEqual(route['sent']['client_id'], 9)
        self.assertEqual([(t['app'], t['state']) for t in route['tracking']], [('sonarr', 'not_seen')])
        self.assertEqual(radarr.calls.count('queue'), 0)

    def test_categories_and_scope_narrow_who_is_asked(self):
        self.start(categories=[5000], scope='torrent')
        self.assertEqual(self.fake.searched, [1])  # Delta has no TV; Charlie is usenet

    def test_one_failing_indexer_does_not_end_the_search(self):
        self.fake.failing = {3}
        search = self.service.poll(self.start(), 0)
        failed = [r for r in search['indexers'] if r['id'] == 3][0]
        self.assertEqual(failed['state'], 'failed')
        self.assertIn('timed out', failed['error'])
        self.assertEqual(search['total'], 4)

    def test_the_same_search_is_answered_from_what_was_found(self):
        first = self.start()
        self.clock[0] += REUSE_SECONDS - 1
        self.assertEqual(self.start(), first)
        self.assertEqual(len(self.fake.searched), 3)
        self.assertNotEqual(self.start(fresh=True), first)
        self.assertEqual(len(self.fake.searched), 6)

    def test_polling_returns_only_what_is_new(self):
        sid = self.start()
        self.assertEqual(len(self.service.poll(sid, 4)['releases']), 2)
        self.assertEqual(self.service.poll(sid, 6)['releases'], [])

    def test_no_credential_reaches_a_poll(self):
        text = json.dumps(self.service.poll(self.start(), 0))
        self.assertNotIn(API_KEY, text)
        self.assertNotIn(PASSKEY, text)

    def test_a_test_instance_refuses_to_send_and_asks_nothing(self):
        sid = self.start()
        answer = self.service.grab(sid, 0)
        self.assertFalse(answer['ok'])
        self.assertEqual(answer['status'], 403)
        self.assertEqual(self.fake.grabs, [])
        self.record_refusal.assert_called_once()

    def test_sending_passes_the_guid_server_side_and_is_logged(self):
        self.fake.allow = True
        sid = self.start()
        answer = self.service.grab(sid, 0, 9)
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(answer['message'], 'Sent to Client')
        self.assertIn(PASSKEY, self.fake.grabs[0][0])
        self.assertEqual(self.fake.grabs[0][2], 9)
        self.record.assert_called_once()
        self.assertEqual(self.service.poll(sid, 0)['grabbed'], [0])

    def test_an_unknown_download_client_is_refused(self):
        self.test_mode[0] = False
        answer = self.service.grab(self.start(), 0, 77)
        self.assertFalse(answer['ok'])
        self.assertEqual(self.fake.grabs, [])

    def test_an_expired_search_says_search_again(self):
        self.test_mode[0] = False
        sid = self.start()
        self.clock[0] += 26 * 60
        self.assertEqual(self.service.grab(sid, 0)['status'], 410)

    def test_a_magnet_comes_from_the_redirect(self):
        self.assertEqual(self.service.magnet(self.start(), 0)['magnet'], 'magnet:?xt=urn:btih:abc')


# ------------------------------------------------------------------- routes

class RouteTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'routes.db'))
        store = ConnectorStore(self.db)
        store.upsert_connector('prowlarr', 'Prowlarr', enabled=True,
                               config={'base_url': 'https://prowlarr.example'})
        store.set_secret('prowlarr', 'api_key', API_KEY)
        connectors = ConnectorService(store, synchronous=True)
        self.service = ProwlarrService(connectors=lambda: connectors, clock=lambda: NOW,
                                       test_mode=lambda: True, executor=Immediate())
        prowlarr_routes.init_prowlarr_routes(self.service)
        app = Flask(__name__)
        app.register_blueprint(prowlarr_routes.prowlarr_bp, url_prefix='/api')
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

    def test_everything_needs_a_sign_in(self):
        for path in ('/api/prowlarr/overview', '/api/prowlarr/search/abc',
                     '/api/prowlarr/search/abc/releases/0/magnet', '/api/prowlarr/search/abc/releases/0/route',
                     '/api/prowlarr/search/abc/releases/0/file'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in ('/api/prowlarr/search', '/api/prowlarr/indexers/1/test',
                     '/api/prowlarr/search/abc/releases/0/grab'):
            self.assertEqual(self.client.post(path, json={}).status_code, 401, path)

    def test_a_search_through_the_routes(self):
        self._sign_in()

        def answer(method, url, **kwargs):
            if '/api/v1/indexer' in url and 'status' not in url and 'stats' not in url:
                return FakeResponse(payload=[indexer(1, 'Alpha')])
            if '/api/v1/search' in url:
                return FakeResponse(payload=[release(1)])
            if '/api/v1/indexerstats' in url:
                return FakeResponse(payload={'indexers': []})
            if '/api/v1/system/status' in url:
                return FakeResponse(payload={'version': '1.30.0'})
            return FakeResponse(payload=[])

        with patch('services.connectors.transport.requests.request', side_effect=answer):
            overview = self.client.get('/api/prowlarr/overview').get_json()
            self.assertEqual(overview['indexers'][0]['name'], 'Alpha')
            self.assertFalse(overview['can_grab'])
            started = self.client.post('/api/prowlarr/search', json={'query': 'Example'}).get_json()
            self.assertTrue(started['success'], started)
            polled = self.client.get(f"/api/prowlarr/search/{started['search_id']}").get_data(as_text=True)
        self.assertIn('Example.Show.S01E01', polled)
        self.assertNotIn(API_KEY, polled)
        self.assertNotIn(PASSKEY, polled)
        self.assertNotIn(API_KEY, json.dumps(overview))

    def test_an_unknown_search_has_expired(self):
        self._sign_in()
        self.assertEqual(self.client.get('/api/prowlarr/search/nope').status_code, 410)


if __name__ == '__main__':
    unittest.main()
