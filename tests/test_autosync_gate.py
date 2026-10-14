#!/usr/bin/env python3
"""
The gate, the title index, and every way they are allowed to fail.

The rule these tests exist to protect: **an automatic sync must never fail, and
never stall, because a status check failed.** Every unusable answer has to
degrade to the behaviour this application had before the gate existed.

The queue payloads below are shaped from rows observed live on Sonarr v4 and
Radarr v6 — including three that break the naive version of this feature and
were only visible because the real queue happened to contain them.
"""

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import DatabaseManager
from models.media_item import SOURCE_RADARR, SOURCE_SONARR, MediaItemStore
from services.connectors.adapters.radarr import RadarrConnector
from services.connectors.adapters.sonarr import SonarrConnector


class FakeResponse:
    def __init__(self, status_code=200, text='', headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def sonarr(base='http://sonarr.test'):
    return SonarrConnector({'base_url': base}, lambda name: 'a-key')


def radarr(base='http://radarr.test'):
    return RadarrConnector({'base_url': base}, lambda name: 'a-key')


def answering(payload):
    """Patch the transport so every call returns this JSON."""
    import json
    return patch('services.connectors.transport.requests.request',
                 return_value=FakeResponse(200, json.dumps(payload)))


def row(**kw):
    base = {'title': 'an item', 'seriesId': 219, 'seasonNumber': 4,
            'trackedDownloadState': 'downloading', 'size': 100, 'sizeleft': 50}
    base.update(kw)
    return base


# ===========================================================================
# What holds a sync, and what does not
# ===========================================================================

class GateDecisionTests(unittest.TestCase):

    def test_a_downloading_episode_holds_the_season(self):
        with answering([row(trackedDownloadState='downloading')]):
            answer = sonarr().in_flight(219, 4)
        self.assertTrue(answer.known)
        self.assertEqual(answer.blocking, 1)
        self.assertFalse(answer.clear)

    def test_every_blocking_state_holds(self):
        for state in ('downloading', 'importPending', 'importing'):
            with self.subTest(state=state), answering([row(trackedDownloadState=state)]):
                answer = sonarr().in_flight(219, 4)
            self.assertEqual(answer.blocking, 1, f'{state} should hold')

    def test_stuck_states_do_not_hold_but_are_counted(self):
        """Stuck does not block (decided 2026-10-02).

        A download blocked from importing, or failed and waiting on a retry
        decision, will not finish on its own. Holding the season for it means
        the season never syncs; the sync goes and says what it went without.
        """
        for state in ('importBlocked', 'failedPending'):
            with self.subTest(state=state), answering([row(trackedDownloadState=state)]):
                answer = sonarr().in_flight(219, 4)
            self.assertEqual(answer.blocking, 0, f'{state} must not hold')
            self.assertEqual(answer.stuck, 1, f'{state} is stuck')
            self.assertTrue(answer.stuck_detail)

    def test_the_time_left_comes_back_as_seconds(self):
        with answering([row(trackedDownloadState='downloading', timeleft='00:03:10')]):
            answer = sonarr().in_flight(219, 4)
        self.assertEqual(answer.eta_seconds, 190)

    def test_imported_does_not_hold(self):
        """The load-bearing one.

        A torrent client keeps seeding after the file is filed and the queue row
        stays for the whole of it. Holding on `imported` would make every season
        sync wait out a seed ratio — worse than the timer it replaces.
        """
        with answering([row(trackedDownloadState='imported')]):
            answer = sonarr().in_flight(219, 4)
        self.assertTrue(answer.clear)

    def test_a_stale_row_whose_file_already_arrived_does_not_hold(self):
        """Seen live: six days in importPending, episodeHasFile already true."""
        with answering([row(trackedDownloadState='importPending',
                            episodeHasFile=True)]):
            answer = sonarr().in_flight(219, 4)
        self.assertTrue(answer.clear)
        self.assertIn('stale', ' '.join(answer.detail))

    def test_a_stalled_download_does_not_hold(self):
        """Seen live: 0% with "The download is stalled with no connections"."""
        with answering([row(trackedDownloadState='downloading', size=100,
                            sizeleft=100,
                            errorMessage='The download is stalled with no connections')]):
            answer = sonarr().in_flight(219, 4)
        self.assertTrue(answer.clear)
        self.assertEqual(answer.stalled, 1)

    def test_an_unrecognised_state_does_not_hold(self):
        """A state a later Sonarr adds must not stall syncs silently.

        Not holding degrades to what the fixed timer already does. Holding
        degrades to a season that never syncs again and says nothing.
        """
        with answering([row(trackedDownloadState='somethingNew')]):
            answer = sonarr().in_flight(219, 4)
        self.assertTrue(answer.clear)

    def test_only_the_asked_for_season_counts(self):
        with answering([row(seasonNumber=3), row(seasonNumber=4)]):
            answer = sonarr().in_flight(219, 4)
        self.assertEqual(answer.blocking, 1)

    def test_a_row_naming_no_film_cannot_hold_one(self):
        """Seen live: a Radarr row in importBlocked with no movieId at all."""
        with answering([{'title': 'x', 'trackedDownloadState': 'importBlocked'}]):
            answer = radarr().in_flight(510)
        self.assertTrue(answer.clear)

    def test_a_row_for_another_film_cannot_hold_this_one(self):
        """Guards the `movieIds` trap.

        Radarr accepts the plural parameter, ignores it, and answers 200 with
        the whole queue. If that ever happens again, obeying the response would
        hold every film behind somebody else's download.
        """
        with answering([{'title': 'x', 'movieId': 999,
                         'trackedDownloadState': 'downloading'}]):
            answer = radarr().in_flight(510)
        self.assertTrue(answer.clear)

    def test_radarr_asks_with_the_singular_parameter(self):
        self.assertEqual(RadarrConnector.queue_filter_param, 'movieId')
        self.assertEqual(SonarrConnector.queue_filter_param, 'seriesId')


# ===========================================================================
# Every way an answer can be unusable
# ===========================================================================

class GateFallbackTests(unittest.TestCase):

    def assert_unknown(self, answer):
        self.assertFalse(answer.known)
        self.assertFalse(answer.clear, 'an unknown answer must not read as "go"')

    def test_service_unreachable(self):
        import requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=requests.ConnectionError('nope')):
            self.assert_unknown(sonarr().in_flight(219, 4))

    def test_service_timing_out(self):
        import requests
        with patch('services.connectors.transport.requests.request',
                   side_effect=requests.Timeout('slow')):
            self.assert_unknown(sonarr().in_flight(219, 4))

    def test_credentials_rejected(self):
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(401, '{"error":"no"}')):
            self.assert_unknown(sonarr().in_flight(219, 4))

    def test_a_proxy_answering_instead_of_the_service(self):
        """200, but HTML. A login page or a gateway, not Sonarr."""
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(200, '<html>sign in</html>')):
            self.assert_unknown(sonarr().in_flight(219, 4))

    def test_a_gateway_error(self):
        """Observed for real mid-development: Radarr answering 502 HTML."""
        with patch('services.connectors.transport.requests.request',
                   return_value=FakeResponse(502, '<html>bad gateway</html>')):
            self.assert_unknown(radarr().in_flight(510))

    def test_no_address_configured(self):
        connector = SonarrConnector({'base_url': ''}, lambda name: 'k')
        self.assert_unknown(connector.in_flight(219, 4))

    def test_no_api_key(self):
        connector = SonarrConnector({'base_url': 'http://x'}, lambda name: '')
        self.assert_unknown(connector.in_flight(219, 4))

    def test_a_long_queue_still_parses(self):
        """Regression: bodies were truncated before parsing, so any real queue
        response read as empty and every season looked clear."""
        rows = [row(title='x' * 200) for _ in range(6)]
        with answering(rows):
            answer = sonarr().in_flight(219, 4)
        self.assertTrue(answer.known)
        self.assertEqual(answer.blocking, 6)


# ===========================================================================
# The title index
# ===========================================================================

class MediaItemStoreTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'index_test.db'))
        self.store = MediaItemStore(self.db)

    def test_a_title_changing_upstream_does_not_create_a_second_row(self):
        """Observed: one tvdb_id recorded under two spellings a week apart."""
        first = self.store.upsert(SOURCE_SONARR, 900001, title='Example Show (2021)')
        again = self.store.upsert(SOURCE_SONARR, 900001, title='EXAMPLE SHOW (2021)')
        self.assertEqual(first, again)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get(SOURCE_SONARR, 900001)['title'],
                         'EXAMPLE SHOW (2021)')

    def test_a_removed_and_re_added_title_keeps_its_row(self):
        """The service's own id is reassigned; the external id is not.

        Radarr's 90 films span ids 117-576 — 486 permanent holes — so a re-added
        film always comes back with a new one. Keying on it would orphan the
        sync history every time.
        """
        first = self.store.upsert(SOURCE_RADARR, 900002, service_item_id=510,
                                  local_folder='Example Film (2024)')
        again = self.store.upsert(SOURCE_RADARR, 900002, service_item_id=577)
        self.assertEqual(first, again)
        item = self.store.get(SOURCE_RADARR, 900002)
        self.assertEqual(item['service_item_id'], 577)
        self.assertEqual(item['local_folder'], 'Example Film (2024)',
                         'the learned folder must survive a re-add')

    def test_the_same_external_id_on_two_services_is_two_titles(self):
        self.store.upsert(SOURCE_SONARR, 42, title='A series')
        self.store.upsert(SOURCE_RADARR, 42, title='A film')
        self.assertEqual(self.store.count(), 2)

    def test_an_empty_value_never_overwrites_a_known_one(self):
        self.store.upsert(SOURCE_SONARR, 1, title='Known', local_folder='Known (2020)')
        self.store.upsert(SOURCE_SONARR, 1, local_folder=None)
        self.assertEqual(self.store.get(SOURCE_SONARR, 1)['local_folder'],
                         'Known (2020)')

    def test_a_missing_external_id_is_refused_rather_than_guessed(self):
        self.assertIsNone(self.store.upsert(SOURCE_SONARR, None, title='x'))
        self.assertIsNone(self.store.upsert(SOURCE_SONARR, '', title='x'))
        self.assertEqual(self.store.count(), 0)

    def test_titles_absent_from_the_service_are_flagged_not_deleted(self):
        self.store.upsert(SOURCE_SONARR, 1, title='Still there')
        self.store.upsert(SOURCE_SONARR, 2, title='Removed upstream')
        self.store.mark_absent_from_service(SOURCE_SONARR, ['1'])
        self.assertEqual(self.store.count(), 2, 'the files are still on disk')
        self.assertEqual(self.store.get(SOURCE_SONARR, 2)['present_in_service'], 0)
        self.assertEqual(self.store.get(SOURCE_SONARR, 1)['present_in_service'], 1)

    def test_a_stale_service_id_can_be_dropped(self):
        item_id = self.store.upsert(SOURCE_SONARR, 9, service_item_id=100)
        self.store.forget_service_item_id(item_id)
        self.assertIsNone(self.store.get(SOURCE_SONARR, 9)['service_item_id'])

    def test_season_counts_record_when_they_were_true(self):
        item_id = self.store.upsert(SOURCE_SONARR, 7, title='x')
        self.store.upsert_season(item_id, 4, episodes_total=8,
                                 episodes_with_file=3, refreshed_at='2026-08-22T00:00:00')
        seasons = self.store.seasons(item_id)
        self.assertEqual(len(seasons), 1)
        self.assertEqual(seasons[0]['episodes_with_file'], 3)
        self.assertTrue(seasons[0]['refreshed_at'])

    def test_the_migration_runs_twice_without_duplicating(self):
        self.store.upsert(SOURCE_SONARR, 1, title='x')
        before = self.store.count()
        self.db.init_database()
        self.assertEqual(self.store.count(), before)


# ===========================================================================
# The wait itself
# ===========================================================================
#
# The wait moved from the in-memory AutoSyncScheduler into the sync engine,
# which keeps it in the database. Its tests are in tests/test_sync_engine.py
# (ReadyCheckTests): the settle, waiting by Sonarr's time left, the 30-minute
# cap, the timer fallback and the extension that used to be ignored.


# ===========================================================================
# Test mode: read-only outward, and no automation
# ===========================================================================

class ReadOnlyTests(unittest.TestCase):
    """These connectors hold an API key that could change the other side."""

    def test_a_write_verb_is_refused_outright(self):
        connector = sonarr()
        with patch('services.connectors.transport.requests.request') as request:
            for verb in ('POST', 'PUT', 'DELETE', 'PATCH'):
                with self.subTest(verb=verb):
                    ok, body = connector._request(verb, '/api/v3/series')
                    self.assertFalse(ok)
                    self.assertIsNone(body)
        self.assertEqual(request.call_count, 0,
                         'a write must never reach the network at all')

    def test_a_write_is_refused_in_test_mode_too(self):
        with patch.dict(os.environ, {'TEST_MODE': '1'}):
            with patch('services.connectors.transport.requests.request') as request:
                ok, _ = radarr()._request('DELETE', '/api/v3/movie/1')
            self.assertFalse(ok)
            self.assertEqual(request.call_count, 0)

    def test_reads_still_work_in_test_mode(self):
        """Read-only must mean read-only, not useless."""
        with patch.dict(os.environ, {'TEST_MODE': '1'}):
            with answering([row(trackedDownloadState='downloading')]):
                answer = sonarr().in_flight(219, 4)
        self.assertTrue(answer.known)
        self.assertEqual(answer.blocking, 1)

    def test_every_call_the_adapters_make_is_a_read(self):
        """A structural check, not a behavioural one.

        Catches a later edit that adds a write helper without going through the
        guard — the failure this whole class exists to make impossible.
        """
        import inspect

        from services.connectors.adapters import _arr
        source = inspect.getsource(_arr)
        for verb in ("'POST'", "'PUT'", "'DELETE'", "'PATCH'"):
            self.assertNotIn(f'transport.send({verb}', source,
                             f'{verb} sent directly, bypassing the guard')
        self.assertEqual(_arr.READ_ONLY_METHODS, frozenset({'GET', 'HEAD'}))


class TestModeIsARehearsalNotAHaltTests(unittest.TestCase):
    """Test mode changes how a sync is carried out, not whether it happens.

    An earlier version stopped automation dead in test mode. That was the wrong
    line: it made the whole recovery story untestable, because the sweep, the
    gate and the queue reads are all things you most want to exercise while
    rehearsing. What test mode means is `rsync --dry-run` — the reads all run,
    the decisions are all made and logged, and nothing is written.

    Outward calls to Sonarr and Radarr are a separate matter and are refused for
    every verb but GET regardless of mode; see `ReadOnlyTests`.
    """

    def test_the_engine_does_not_consult_test_mode(self):
        import inspect

        from services.sync_engine import engine
        self.assertNotIn('test_mode_enabled',
                         inspect.getsource(engine),
                         'the sync engine must not gate automation on test mode')

    def test_the_film_webhook_route_does_not_either(self):
        import inspect

        import routes.webhooks as webhook_routes
        source = inspect.getsource(webhook_routes)
        trigger = source.index("_submit_webhook('radarr_webhook'")
        window = source[max(0, trigger - 1500):trigger]
        self.assertNotIn('test_mode_enabled()', window)

    def test_rsync_is_still_put_into_dry_run(self):
        """The one place test mode does bite, and the reason it is safe."""
        import inspect

        from services import transfer_service
        source = inspect.getsource(transfer_service)
        self.assertIn('--dry-run', source)
        self.assertIn('test_mode_enabled()', source)
