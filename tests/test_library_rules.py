#!/usr/bin/env python3
"""
The Library list's verdicts, the detail view behind each card, and the History
and Queue rows — through the HTTP layer, against a fake Sonarr and Radarr.

The list may make no call per title, so it judges from three cheap reads:

  (a) the service's per-season count of episodes with a file, against the
      distinct episodes here;
  (b) the service's imports of the last two weeks, against the last completed
      sync of each season's folder;
  (c) for a film, the file size the catalogue already carries.

The case that started this is pinned first: Sonarr holds E08 alone (the media
server deleted the rest after they synced), this disk holds E01–E07. The old
list called that "Synced"; it must be out of sync, and the ordinary cleanup —
the same picture minus the unsynced import — must not be.

Synthetic names only; every outbound call must be a GET.
"""

import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import auth
import routes.media_library as media_routes
from models.connector import ConnectorStore
from models.database import DatabaseManager
from models.media_item import SOURCE_RADARR, SOURCE_SONARR
from services.connectors.service import ConnectorService
from services.media_index import EXACT_TTL_SECONDS, IMPORTS_TTL_SECONDS, MediaIndex

SIGNED_IN_PAYLOAD = {'sub': 'tester', 'uid': 1, 'tv': 1, 'src': 'db', 'type': 'access'}
SIGNED_IN_IDENTITY = {
    'account_id': 1, 'username': 'tester', 'role': 'admin',
    'token_version': 1, 'must_change_password': False, 'source': 'db',
}

SHOW_FOLDER = 'Example Show (2021)'
FILM_FOLDER = 'Example Film (2024)'


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ''
        self.headers = {}


class FakeArr:
    """Answers the way Sonarr and Radarr do, from what a test puts in it."""

    def __init__(self):
        self.series = []
        self.movies = []
        self.episodes = {}
        self.files = {}
        self.imports = []
        self.imports_ok = True
        self.history = {'page': 1, 'pageSize': 25, 'totalRecords': 0, 'records': []}
        self.queue = []
        self.title_history = {}
        self.down = False
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method.upper(), url))
        if self.down:
            import requests
            raise requests.ConnectionError('down')
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        one = re.match(r'^/api/v3/(series|movie)/(\d+)$', path)
        if one:
            rows = self.series if one.group(1) == 'series' else self.movies
            for row in rows:
                if str(row['id']) == one.group(2):
                    return FakeResponse(200, row)
            return FakeResponse(404, {'message': 'NotFound'})
        series_id = int((query.get('seriesId') or ['0'])[0])
        answers = {
            '/api/v3/series': lambda: self.series,
            '/api/v3/movie': lambda: self.movies,
            '/api/v3/episode': lambda: self.episodes.get(series_id, []),
            '/api/v3/episodefile': lambda: self.files.get(series_id, []),
            '/api/v3/history': lambda: self.history,
            '/api/v3/queue/details': lambda: self.queue,
            '/api/v3/system/status': lambda: {'appName': 'Sonarr', 'version': '4.0'},
        }
        if path in ('/api/v3/history/series', '/api/v3/history/movie'):
            key = int((query.get('seriesId') or query.get('movieId') or ['0'])[0])
            return FakeResponse(200, self.title_history.get(key, []))
        if path == '/api/v3/history/since':
            return FakeResponse(200 if self.imports_ok else 500,
                                self.imports if self.imports_ok else {'message': 'boom'})
        if path in answers:
            return FakeResponse(200, answers[path]())
        return FakeResponse(404, {'message': 'NotFound'})

    def urls(self, fragment):
        return [url for _, url in self.calls if fragment in url]


def ago(**delta):
    return datetime.now(timezone.utc) - timedelta(**delta)


def iso(moment):
    return moment.isoformat().replace('+00:00', 'Z')


def series_row(counts, series_id=219, tvdb=900001, title='Example Show', specials=0,
               sizes=None):
    """`sizes`, by season: Sonarr's `sizeOnDisk`, the combined size of its files."""
    seasons = []
    if specials:
        seasons.append({'seasonNumber': 0, 'monitored': False,
                        'statistics': {'episodeCount': specials, 'episodeFileCount': specials}})
    for number, files in sorted(counts.items()):
        statistics = {'episodeCount': max(files, 8), 'episodeFileCount': files}
        if sizes and number in sizes:
            statistics['sizeOnDisk'] = sizes[number]
        seasons.append({'seasonNumber': number, 'monitored': True, 'statistics': statistics})
    total = sum(counts.values()) + specials
    return {
        'id': series_id, 'tvdbId': tvdb, 'title': title, 'year': 2021,
        'titleSlug': 'example-show', 'monitored': True, 'status': 'continuing',
        'network': 'Example Network', 'path': f'/media/tv/{SHOW_FOLDER}',
        'images': [{'coverType': 'poster', 'remoteUrl': 'http://img/poster.jpg'}],
        'statistics': {'episodeCount': total, 'episodeFileCount': total, 'sizeOnDisk': 1},
        'seasons': seasons,
    }


def ep_name(season, number):
    return f"Example Show (2021) - S{season:02d}E{number:02d} - Episode {number} [WEBDL-1080p].mkv"


def imported(season, number, when, size=None, series_id=219):
    record = {'seriesId': series_id, 'eventType': 'downloadFolderImported', 'date': iso(when),
              'episode': {'seasonNumber': season, 'episodeNumber': number}, 'data': {}}
    if size:
        record['data']['size'] = str(size)
    return record


class LibraryTestCase(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.db = DatabaseManager(os.path.join(tmp.name, 'rules.db'))
        store = ConnectorStore(self.db)
        for source in (SOURCE_SONARR, SOURCE_RADARR):
            store.upsert_connector(source, source.title(), enabled=True,
                                   config={'base_url': f'http://{source}.test'})
            store.set_secret(source, 'api_key', f'{source}-key-that-must-not-come-back')
        self.service = ConnectorService(store, synchronous=True)

        self.tv = os.path.join(tmp.name, 'tv')
        self.movies = os.path.join(tmp.name, 'movies')
        os.makedirs(self.tv)
        os.makedirs(self.movies)
        config = _Config({'TVSHOW_DEST_PATH': self.tv, 'MOVIE_DEST_PATH': self.movies,
                          'TVSHOW_PATH': '/media/tv', 'MOVIE_PATH': '/media/movies'})
        self.index = MediaIndex(self.db, self.service, config=config)
        self.now = [10_000.0]
        self.index.clock = lambda: self.now[0]
        self.index.store.upsert(SOURCE_SONARR, 900001, title='Example Show', year=2021,
                                service_item_id=219)

        media_routes.init_media_library_routes(self.index)
        app = Flask(__name__)
        app.register_blueprint(media_routes.media_library_bp, url_prefix='/api')
        self.client = app.test_client()

        self.arr = FakeArr()
        for target, kwargs in (
            ('auth.get_token_from_request', {'return_value': 'token'}),
            ('auth.validate_token', {'return_value': SIGNED_IN_PAYLOAD}),
            ('auth.resolve_identity', {'return_value': (SIGNED_IN_IDENTITY, auth.REASON_OK)}),
            ('services.connectors.transport.requests.request', {'side_effect': self.arr}),
        ):
            patcher = patch(target, **kwargs)
            self.addCleanup(patcher.stop)
            patcher.start()

    # -- the disk ------------------------------------------------------------

    def keep(self, season, number, size=None, folder=SHOW_FOLDER, name=None):
        path = os.path.join(self.tv, folder, f'Season {season:02d}')
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, name or ep_name(season, number)), 'wb') as handle:
            handle.write(b'\0' * (size if size is not None else 100 + number))

    def rescan(self):
        self.index.local.scan(force=True)

    def season_dir(self, season=1):
        return os.path.join(self.tv, SHOW_FOLDER, f'Season {season:02d}')

    # -- the record of syncs ---------------------------------------------------

    def completed_run(self, dest_path, started):
        stamp = started.isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO sync_run (run_id, kind, source, unit_key, dest_path, state, "
                "created_at, updated_at, started_at, finished_at) "
                "VALUES (?, 'sonarr_webhook', 'sonarr', ?, ?, 'completed', ?, ?, ?, ?)",
                (f"run_{abs(hash((dest_path, stamp)))}", dest_path, dest_path,
                 stamp, stamp, stamp, stamp))
            conn.commit()

    def legacy_transfer(self, dest_path, ended):
        local = ended.astimezone().replace(tzinfo=None).isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO transfers (transfer_id, media_type, folder_name, season_name, "
                "source_path, dest_path, operation_type, status, start_time, end_time) "
                "VALUES (?, 'tvshows', ?, 'Season 01', '/media/tv/x', ?, 'folder', "
                "'completed', ?, ?)",
                (f"t_{abs(hash(local))}", SHOW_FOLDER, dest_path, local, local))
            conn.commit()

    # -- reading -----------------------------------------------------------------

    def library(self, source='sonarr'):
        payload = self.client.get(f'/api/library/{source}').get_json()
        self.assertTrue(payload['success'])
        return payload

    def item(self, source='sonarr'):
        return self.library(source)['items'][0]

    def detail(self, external_id='900001', source='sonarr'):
        return self.client.get(f'/api/library/{source}/{external_id}')

    def real_case(self):
        """Sonarr holds E08 alone; this disk holds E01–E07."""
        self.arr.series = [series_row({1: 1})]
        self.arr.episodes[219] = [
            {'id': 1000 + n, 'seriesId': 219, 'seasonNumber': 1, 'episodeNumber': n,
             'title': 'Episode Eight' if n == 8 else f'Episode {n}',
             'airDate': f'2026-09-{n:02d}', 'hasFile': n == 8,
             'episodeFileId': 508 if n == 8 else 0, 'monitored': True}
            for n in range(1, 9)]
        self.arr.files[219] = [{
            'id': 508, 'seriesId': 219, 'seasonNumber': 1,
            'relativePath': f'Season 01/{ep_name(1, 8)}', 'size': 808,
            'quality': {'quality': {'name': 'WEBDL-1080p'}},
            'customFormats': [{'id': 1, 'name': 'WEB Tier 01'}], 'customFormatScore': 1700,
        }]
        for number in range(1, 8):
            self.keep(1, number)
        self.rescan()


class _Config:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=''):
        return self.values.get(key, default)


# =============================================================================
# The list
# =============================================================================

class ListRuleTests(LibraryTestCase):

    def test_the_real_case_is_out_of_sync(self):
        self.real_case()
        self.arr.imports = [imported(1, 8, ago(days=2))]
        item = self.item()
        self.assertEqual(item['sync_state'], 'out_of_sync')
        self.assertEqual(item['attention'][0]['kind'], 'new_import')
        self.assertEqual(item['attention'][0]['episodes'], ['S01E08'])
        self.assertIn('1 new episode on Sonarr', item['state_reason'])
        self.assertEqual((item['service_files_counted'], item['episodes_here']), (1, 7),
                         'the card reads "Sonarr 1 · here 7"')

    def test_the_cleanup_case_is_kept_here(self):
        """E07 was imported, synced, then cleaned up there: the normal case."""
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 8):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 7, ago(days=6))]
        self.completed_run(self.season_dir(), ago(days=5))
        item = self.item()
        self.assertEqual(item['sync_state'], 'kept_here')
        self.assertEqual(item['kept_here_count'], 6)
        self.assertEqual(item['attention'], [])

    def test_an_import_after_the_last_sync_is_out_of_sync(self):
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=2))]
        self.completed_run(self.season_dir(), ago(days=3))
        item = self.item()
        self.assertEqual(item['sync_state'], 'out_of_sync',
                         'a file imported after the copy started may not be in it')
        self.assertEqual(item['attention'][0]['kind'], 'new_file')

    def test_a_new_episode_is_out_of_sync_even_with_a_sync_on_record_after_it(self):
        """Sonarr holds E08 alone, this disk E01–E07, and a sync of the season
        finished after E08 was imported — a test-mode dry run, or a sync that
        left it out. The record says synced; the sizes say E08 is not here."""
        self.arr.series = [series_row({1: 1}, sizes={1: 808})]
        for number in range(1, 8):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=2))]
        self.completed_run(self.season_dir(), ago(days=1))
        item = self.item()
        self.assertEqual(item['sync_state'], 'out_of_sync')
        self.assertEqual(item['attention'][0]['kind'], 'not_matching')
        self.assertIn('has a file for season 1 that is not here', item['state_reason'])

    def test_a_new_episode_with_no_import_in_the_window_is_out_of_sync_too(self):
        self.arr.series = [series_row({1: 1}, sizes={1: 808})]
        for number in range(1, 8):
            self.keep(1, number)
        self.rescan()
        self.assertEqual(self.item()['sync_state'], 'out_of_sync')

    def test_the_cleanup_case_matched_by_size_is_kept_here(self):
        self.arr.series = [series_row({1: 1}, sizes={1: 107})]   # E07's size here
        for number in range(1, 8):
            self.keep(1, number)
        self.rescan()
        item = self.item()
        self.assertEqual(item['sync_state'], 'kept_here')
        self.assertEqual(item['attention'], [])

    def test_one_file_holding_two_episodes_is_matched(self):
        # Sonarr counts episodes with a file: a double episode is two of them
        # and one file. Matching two files to the size would flag it wrongly.
        self.arr.series = [series_row({1: 2}, sizes={1: 300})]
        for number in range(1, 7):
            self.keep(1, number)
        self.keep(1, 7, size=300, name=ep_name(1, 7).replace('E07', 'E07E08'))
        self.rescan()
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_more_than_three_episodes_there_are_left_to_the_other_rules(self):
        self.arr.series = [series_row({1: 4}, sizes={1: 999_999})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_an_import_before_the_last_sync_is_not(self):
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=2))]
        self.completed_run(self.season_dir(), ago(days=1))
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_a_sync_of_the_whole_series_covers_its_seasons(self):
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=2))]
        self.completed_run(os.path.join(self.tv, SHOW_FOLDER), ago(days=1))
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_a_transfer_from_before_the_engine_counts_too(self):
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=2))]
        self.legacy_transfer(self.season_dir(), ago(days=1))
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_the_very_file_already_here_is_not_flagged(self):
        """Put here by hand, never synced: the same size says it is the same file."""
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=2), size=108)]
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_an_upgrade_is_judged_by_its_latest_import_only(self):
        """E08 imported twice — the first file replaced by an upgrade. The file
        here is the upgrade, so the older import's size must not flag it."""
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=3), size=95),
                            imported(1, 8, ago(days=2), size=108)]
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_an_upgrade_not_yet_here_is_out_of_sync(self):
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=3), size=108),
                            imported(1, 8, ago(days=2), size=150)]
        item = self.item()
        self.assertEqual(item['sync_state'], 'out_of_sync')
        self.assertEqual(item['attention'][0]['kind'], 'new_file')
        self.assertEqual(item['attention'][0]['episodes'], ['S01E08'])

    def test_a_simulated_sync_does_not_count(self):
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        self.arr.imports = [imported(1, 8, ago(days=2))]
        self.completed_run(self.season_dir(), ago(days=1))
        with self.db.get_connection() as conn:
            conn.execute("UPDATE sync_run SET is_simulation = 1")
            conn.commit()
        self.assertEqual(self.item()['sync_state'], 'out_of_sync')

    def test_a_short_season_is_out_of_sync(self):
        self.arr.series = [series_row({1: 10})]
        for number in range(1, 9):
            self.keep(1, number)
        self.rescan()
        item = self.item()
        self.assertEqual(item['sync_state'], 'out_of_sync')
        self.assertEqual(item['attention'][0], {
            'kind': 'short', 'season_number': 1, 'count': 2, 'theirs': 10, 'ours': 8})
        self.assertIn('Sonarr has 10 episode files for season 1; 8 here', item['state_reason'])

    def test_episodes_are_counted_not_files(self):
        """Five double-episode files are ten episodes, as Sonarr counts them."""
        self.arr.series = [series_row({1: 10})]
        for first in range(1, 11, 2):
            self.keep(1, first, name=f"Example Show (2021) - S01E{first:02d}E{first + 1:02d}.mkv")
        self.rescan()
        item = self.item()
        self.assertEqual(item['sync_state'], 'in_sync')
        self.assertEqual(item['seasons'][0]['episodes_here'], 10)
        self.assertEqual(item['seasons'][0]['files_here'], 5,
                         'files_here keeps its meaning for the auto-scanner')

    def test_specials_do_not_make_the_list_out_of_sync(self):
        self.arr.series = [series_row({1: 3}, specials=2)]
        for number in range(1, 4):
            self.keep(1, number)
        self.rescan()
        self.assertEqual(self.item()['sync_state'], 'in_sync')

    def test_without_the_history_the_counts_still_judge(self):
        self.arr.imports_ok = False
        self.arr.series = [series_row({1: 10})]
        self.keep(1, 1)
        self.rescan()
        payload = self.library()
        self.assertFalse(payload['history_checked'])
        self.assertEqual(payload['items'][0]['sync_state'], 'out_of_sync')

    def test_the_history_is_read_once_a_minute_at_most(self):
        self.arr.series = [series_row({1: 1})]
        self.keep(1, 1)
        self.rescan()
        self.library()
        self.library()
        self.assertEqual(len(self.arr.urls('/history/since')), 1)
        self.now[0] += IMPORTS_TTL_SECONDS + 1
        self.library()
        self.assertEqual(len(self.arr.urls('/history/since')), 2)
        since = parse_qs(urlsplit(self.arr.urls('/history/since')[0]).query)
        self.assertEqual(since['eventType'], ['3'])
        window = datetime.fromisoformat(since['date'][0])
        self.assertAlmostEqual((datetime.now(timezone.utc) - window).days, 14, delta=1)

    def test_the_list_borrows_the_exact_answer_for_ten_minutes(self):
        """No import in the window: the counts alone call the real case kept-here.
        Once someone opens it, the exact answer — E08 missing — is what the
        card says, until it is ten minutes old."""
        self.real_case()
        self.assertEqual(self.item()['sync_state'], 'kept_here')

        self.assertEqual(self.detail().status_code, 200)
        item = self.item()
        self.assertEqual(item['sync_state'], 'out_of_sync')
        self.assertTrue(item['state_exact'])
        self.assertIn('S01E08', item['state_reason'])

        self.now[0] += EXACT_TTL_SECONDS + 1
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_an_import_after_the_exact_answer_sets_it_aside(self):
        self.arr.series = [series_row({1: 1})]
        self.arr.episodes[219] = [{'id': 1, 'seasonNumber': 1, 'episodeNumber': 1,
                                   'hasFile': True, 'episodeFileId': 7}]
        self.arr.files[219] = [{'id': 7, 'seasonNumber': 1, 'size': 101,
                                'relativePath': f'Season 01/{ep_name(1, 1)}'}]
        self.keep(1, 1)
        self.rescan()
        self.detail()
        self.assertEqual(self.item()['sync_state'], 'in_sync')

        self.arr.imports = [imported(1, 2, datetime.now(timezone.utc) + timedelta(seconds=5))]
        self.now[0] += IMPORTS_TTL_SECONDS + 1
        self.assertEqual(self.item()['sync_state'], 'out_of_sync')

    def test_a_series_sonarr_holds_nothing_of_but_kept_here_is_kept_here(self):
        self.arr.series = [series_row({1: 0})]
        self.keep(1, 1)
        self.rescan()
        self.assertEqual(self.item()['sync_state'], 'kept_here')

    def test_a_service_that_does_not_answer_is_not_read_as_holding_nothing(self):
        """Down is not "it holds no files": the title here must not read as kept."""
        self.keep(1, 1)
        self.rescan()
        self.arr.down = True
        payload = self.library()
        self.assertFalse(payload['live'])
        item = payload['items'][0]
        self.assertEqual(item['sync_state'], 'unknown')
        self.assertIn('did not send', item['state_reason'])

    def test_a_series_not_here_at_all_is_never(self):
        self.arr.series = [series_row({1: 3})]
        self.assertEqual(self.item()['sync_state'], 'never')


class RadarrListTests(LibraryTestCase):

    def setUp(self):
        super().setUp()
        self.index.store.upsert(SOURCE_RADARR, 900002, title='Example Film', year=2024,
                                service_item_id=5)

    def film(self, has_file=True, size=4000):
        return {'id': 5, 'tmdbId': 900002, 'title': 'Example Film', 'year': 2024,
                'path': f'/media/movies/{FILM_FOLDER}', 'hasFile': has_file,
                'sizeOnDisk': size if has_file else 0, 'monitored': True,
                'movieFile': {'id': 9, 'relativePath': f'{FILM_FOLDER}.mkv', 'size': size,
                              'quality': {'quality': {'name': 'Bluray-1080p'}}}
                if has_file else None}

    def keep_film(self, size):
        folder = os.path.join(self.movies, FILM_FOLDER)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f'{FILM_FOLDER}.mkv'), 'wb') as handle:
            handle.write(b'\0' * size)
        self.index.local.scan(force=True)

    def test_the_same_size_is_in_sync_exactly(self):
        self.arr.movies = [self.film(size=4000)]
        self.keep_film(4000)
        item = self.item('radarr')
        self.assertEqual(item['sync_state'], 'in_sync')
        self.assertTrue(item['state_exact'])
        self.assertEqual((item['service_file_size'], item['local_file_size']), (4000, 4000))

    def test_a_different_size_is_out_of_sync(self):
        self.arr.movies = [self.film(size=5000)]
        self.keep_film(4000)
        item = self.item('radarr')
        self.assertEqual(item['sync_state'], 'out_of_sync')
        self.assertEqual(item['attention'][0]['kind'], 'different')

    def test_a_film_not_here_is_never_and_one_cleaned_up_there_is_kept(self):
        self.arr.movies = [self.film()]
        self.assertEqual(self.item('radarr')['sync_state'], 'never')
        self.arr.movies = [self.film(has_file=False)]
        self.keep_film(4000)
        self.assertEqual(self.item('radarr')['sync_state'], 'kept_here')


# =============================================================================
# The detail view
# =============================================================================

class DetailTests(LibraryTestCase):

    def test_the_real_case_episode_by_episode(self):
        self.real_case()
        response = self.detail()
        self.assertEqual(response.status_code, 200)
        view = response.get_json()
        self.assertTrue(view['live'])
        self.assertEqual(view['state'], 'out_of_sync')
        self.assertIn('S01E08 “Episode Eight”', view['summary'])
        season = view['seasons'][0]
        states = {row['code']: row['state'] for row in season['episodes']}
        self.assertEqual(states['S01E08'], 'missing_here')
        self.assertEqual([states[f'S01E{n:02d}'] for n in range(1, 8)], ['only_here'] * 7)
        e08 = next(row for row in season['episodes'] if row['code'] == 'S01E08')
        self.assertEqual(e08['service_file']['quality'], 'WEBDL-1080p')
        self.assertEqual(e08['service_file']['custom_formats'], ['WEB Tier 01'])
        e01 = season['episodes'][0]
        self.assertEqual(e01['local_file']['size'], 101)
        self.assertEqual(view['title']['title'], 'Example Show')
        self.assertEqual(view['title']['poster'], 'http://img/poster.jpg')

    def test_it_points_at_explore_and_holds_the_title_sync_back(self):
        self.real_case()
        view = self.detail().get_json()
        self.assertEqual(view['actions']['explore'], {
            'media_type': 'tvshows', 'series': SHOW_FOLDER, 'season': 'Season 01'})
        self.assertFalse(view['actions']['sync']['offered'])
        self.assertIn('kept only here', view['actions']['sync']['reason'])

    def test_the_last_sync_of_each_season_is_shown(self):
        self.real_case()
        moment = ago(days=3)
        self.completed_run(self.season_dir(), moment)
        view = self.detail().get_json()
        self.assertEqual(view['seasons'][0]['last_synced_at'][:16], moment.isoformat()[:16])

    def test_a_stale_service_id_is_found_again_by_its_external_id(self):
        self.real_case()
        self.index.store.upsert(SOURCE_SONARR, 900001, service_item_id=999)
        view = self.detail().get_json()
        self.assertEqual(view['state'], 'out_of_sync')
        self.assertEqual(self.index.store.get(SOURCE_SONARR, 900001)['service_item_id'], 219)

    def test_a_title_nothing_knows_is_a_404(self):
        self.arr.series = [series_row({1: 1})]
        self.assertEqual(self.detail('123456').status_code, 404)

    def test_a_title_id_must_be_a_number(self):
        self.assertEqual(self.detail('not-a-number').status_code, 400)

    def test_history_and_queue_keep_their_own_routes(self):
        history = self.client.get('/api/library/sonarr/history').get_json()
        queue = self.client.get('/api/library/sonarr/queue').get_json()
        self.assertIn('records', history)
        self.assertIn('rows', queue)

    def test_a_dead_service_is_said_not_raised(self):
        self.arr.down = True
        response = self.detail()
        self.assertEqual(response.status_code, 200)
        view = response.get_json()
        self.assertFalse(view['live'])
        self.assertIn('did not answer', view['message'])

    def test_a_film(self):
        self.index.store.upsert(SOURCE_RADARR, 900002, title='Example Film', year=2024,
                                service_item_id=5)
        self.arr.movies = [{
            'id': 5, 'tmdbId': 900002, 'title': 'Example Film', 'year': 2024, 'hasFile': True,
            'path': f'/media/movies/{FILM_FOLDER}',
            'movieFile': {'id': 9, 'relativePath': f'{FILM_FOLDER}.mkv', 'size': 5000,
                          'quality': {'quality': {'name': 'Bluray-2160p'}}}}]
        folder = os.path.join(self.movies, FILM_FOLDER)
        os.makedirs(folder)
        with open(os.path.join(folder, f'{FILM_FOLDER}.mkv'), 'wb') as handle:
            handle.write(b'\0' * 4000)
        self.index.local.scan(force=True)
        view = self.detail('900002', 'radarr').get_json()
        self.assertEqual(view['state'], 'out_of_sync')
        self.assertEqual(view['movie']['state'], 'different')
        self.assertEqual(view['movie']['service_file']['quality'], 'Bluray-2160p')
        self.assertEqual(view['movie']['local_file']['size'], 4000)
        self.assertEqual(view['actions']['explore']['media_type'], 'movies')
        self.assertEqual(view['actions']['explore']['series'], FILM_FOLDER)

    def test_only_reads_go_out_and_the_key_stays_home(self):
        self.real_case()
        body = self.detail().get_data(as_text=True)
        self.assertNotIn('sonarr-key-that-must-not-come-back', body)
        self.assertTrue(self.arr.calls)
        self.assertEqual({method for method, _ in self.arr.calls}, {'GET'})


# =============================================================================
# One title's history
# =============================================================================

def sonarr_event(event, season, number, when, record_id, **data):
    record = {'id': record_id, 'seriesId': 219, 'eventType': event, 'date': iso(when),
              'sourceTitle': 'Example.Show.S01E08.1080p.WEB', 'data': {k: str(v) for k, v in data.items()},
              'quality': {'quality': {'name': 'WEBDL-1080p'}},
              'episode': {'seasonNumber': season, 'episodeNumber': number,
                          'title': f'Episode {number}'}}
    return record


class TitleHistoryTests(LibraryTestCase):

    def setUp(self):
        super().setUp()
        self.arr.series = [series_row({1: 1})]
        for number in range(1, 8):
            self.keep(1, number)
        self.rescan()

    def run_row(self, dest, state, when, outcome='', kind='sonarr_webhook', simulation=0):
        stamp = when.isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO sync_run (run_id, kind, source, unit_key, dest_path, state, "
                "season_name, outcome_message, is_simulation, requested_by_name, "
                "created_at, updated_at, started_at, finished_at) "
                "VALUES (?, ?, 'sonarr', ?, ?, ?, 'Season 01', ?, ?, 'admin', ?, ?, ?, ?)",
                (f"run_{abs(hash((dest, stamp, state)))}", kind, dest, dest, state, outcome,
                 simulation, stamp, stamp, stamp, stamp))
            conn.commit()

    def history(self, external_id='900001', source='sonarr'):
        return self.client.get(f'/api/library/{source}/{external_id}/history')

    def test_the_services_events_and_our_syncs_read_newest_first(self):
        self.arr.title_history[219] = [
            sonarr_event('downloadFolderImported', 1, 8, ago(days=2), 1, size=808),
            sonarr_event('grabbed', 1, 8, ago(days=2, hours=1), 2, indexer='Example Indexer'),
            sonarr_event('downloadFailed', 1, 9, ago(days=1), 3, message='Stalled with no peers'),
            sonarr_event('episodeFileDeleted', 1, 1, ago(days=5), 4, reason='Upgrade'),
        ]
        self.run_row(self.season_dir(), 'refused', ago(hours=20),
                     'Would delete 7 media files but only receive 1')
        self.run_row(self.season_dir(), 'completed', ago(days=3), 'Synced')
        self.legacy_transfer(self.season_dir(), ago(days=10))

        response = self.history()
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['live'])
        entries = body['entries']
        self.assertEqual([e['title'] for e in entries], [
            'Sync of Season 01 was stopped by the safety check',
            "Sonarr's download of S01E09 failed",
            'Sonarr imported S01E08',
            'Sonarr grabbed S01E08',
            'Synced Season 01',
            'Sonarr deleted its file for S01E01',
            'Copied Season 01',
        ])
        by_title = {e['title']: e for e in entries}
        self.assertEqual(by_title['Sync of Season 01 was stopped by the safety check']['status'],
                         'not_done')
        self.assertIn('Would delete 7', by_title[
            'Sync of Season 01 was stopped by the safety check']['detail'])
        self.assertTrue(by_title['Sync of Season 01 was stopped by the safety check']['run_id'])
        self.assertEqual(by_title["Sonarr's download of S01E09 failed"]['status'], 'failed')
        self.assertIn('Stalled', by_title["Sonarr's download of S01E09 failed"]['detail'])
        imported = by_title['Sonarr imported S01E08']
        self.assertEqual(imported['episodes'], ['S01E08'])
        self.assertIn('Episode 8', imported['detail'])
        self.assertIn('WEBDL-1080p', imported['detail'])
        self.assertEqual(by_title['Synced Season 01']['status'], 'done')
        self.assertIn('Replaced by an upgrade',
                      by_title['Sonarr deleted its file for S01E01']['detail'])
        self.assertIn('Before sync records', by_title['Copied Season 01']['detail'])
        self.assertEqual(body['total'], 7)

    def test_an_event_naming_its_episode_by_id_is_read_back_as_its_code(self):
        # What Sonarr's per-series history really sends: an episodeId, no episode.
        record = sonarr_event('downloadFolderImported', 1, 8, ago(days=2), 1, size=808)
        record.pop('episode')
        record['episodeId'] = 1008
        self.arr.title_history[219] = [record]
        self.arr.episodes[219] = [{'id': 1008, 'seriesId': 219, 'seasonNumber': 1,
                                   'episodeNumber': 8, 'title': 'Episode Eight'}]
        entry = self.history().get_json()['entries'][0]
        self.assertEqual(entry['title'], 'Sonarr imported S01E08')
        self.assertEqual(entry['episodes'], ['S01E08'])
        self.assertIn('Episode Eight', entry['detail'])

    def test_a_burst_of_deletions_reads_as_one_entry(self):
        self.arr.title_history[219] = [
            sonarr_event('episodeFileDeleted', 1, number, ago(days=3, minutes=number), number,
                         reason='Manual')
            for number in range(1, 8)
        ]
        entries = self.history().get_json()['entries']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['title'], 'Sonarr deleted its files for S01E01 to S01E07')
        self.assertEqual(len(entries[0]['episodes']), 7)
        self.assertEqual(entries[0]['detail'], 'Deleted by hand')

    def test_a_sync_entry_names_its_season(self):
        self.run_row(self.season_dir(), 'failed', ago(days=2), 'rsync exit 23')
        entry = self.history().get_json()['entries'][0]
        self.assertEqual(entry['season'], 'Season 01')

    def test_another_folder_and_rehearsals_are_left_out(self):
        self.run_row(os.path.join(self.tv, 'Example Show (2021) Extras', 'Season 01'),
                     'failed', ago(days=1), 'Not this one')
        self.run_row(os.path.join(self.tv, 'Another Show (2020)', 'Season 01'),
                     'failed', ago(days=1), 'Not this one either')
        self.run_row(self.season_dir(), 'completed', ago(days=1), 'Rehearsed',
                     kind='simulation', simulation=1)
        self.assertEqual(self.history().get_json()['entries'], [])

    def test_only_reads_go_out(self):
        self.history()
        self.assertTrue(self.arr.urls('/api/v3/history/series'))
        self.assertTrue(all(method in ('GET', 'HEAD') for method, _ in self.arr.calls))

    def test_a_dead_service_still_shows_our_side(self):
        self.run_row(self.season_dir(), 'completed', ago(days=1), 'Synced')
        self.arr.down = True
        body = self.history().get_json()
        self.assertFalse(body['live'])
        self.assertEqual([e['title'] for e in body['entries']], ['Synced Season 01'])

    def test_a_title_nothing_knows_is_a_404_and_the_id_must_be_a_number(self):
        self.assertEqual(self.history('999999').status_code, 404)
        self.assertEqual(self.history('not-a-number').status_code, 400)


# =============================================================================
# History and Queue rows
# =============================================================================

class HistoryTests(LibraryTestCase):

    def record(self, **extra):
        record = {
            'id': 77, 'seriesId': 219, 'episodeId': 1008, 'eventType': 'downloadFolderImported',
            'date': '2026-10-05T14:02:11Z',
            'sourceTitle': 'Example.Show.S01E08.Episode.Eight.1080p.WEB-DL',
            'quality': {'quality': {'name': 'WEBDL-1080p'}},
            'customFormats': [{'id': 1, 'name': 'WEB Tier 01'}], 'customFormatScore': 1700,
            'data': {'downloadClientName': 'client-a', 'releaseGroup': 'GROUP', 'size': '808'},
            'episode': {'seasonNumber': 1, 'episodeNumber': 8, 'title': 'Episode Eight',
                        'absoluteEpisodeNumber': 8},
            'series': {'id': 219, 'tvdbId': 900001, 'title': 'Example Show', 'year': 2021},
        }
        record.update(extra)
        return record

    def page(self, *records):
        self.arr.history = {'page': 1, 'pageSize': 25, 'totalRecords': len(records),
                            'records': list(records)}

    def test_a_row_reads_like_sonarrs_own_history(self):
        self.page(self.record())
        row = self.client.get('/api/library/sonarr/history').get_json()['records'][0]
        self.assertEqual(row['event'], 'imported')
        self.assertEqual(row['event_label'], 'Imported')
        self.assertEqual(row['title'], 'Example Show')
        self.assertEqual(row['episode_label'], '1x08')
        self.assertEqual(row['episode_code'], 'S01E08')
        self.assertEqual(row['episode_title'], 'Episode Eight')
        self.assertEqual(row['quality'], 'WEBDL-1080p')
        self.assertEqual(row['custom_formats'], ['WEB Tier 01'])
        self.assertEqual(row['custom_format_score'], 1700)
        self.assertEqual(row['download_client'], 'client-a')
        self.assertEqual(row['size'], 808)
        self.assertEqual(row['external_id'], '900001')
        self.assertTrue(row['known_here'])

    def test_a_title_dragoncp_has_never_heard_of_still_links_to_its_detail(self):
        self.page(self.record(seriesId=555, series={'id': 555, 'tvdbId': 900003,
                                                    'title': 'Alpha - Bravo', 'year': 2020}))
        row = self.client.get('/api/library/sonarr/history').get_json()['records'][0]
        self.assertFalse(row['known_here'])
        self.assertEqual(row['title'], 'Alpha - Bravo')
        self.assertEqual(row['external_id'], '900003')

    def test_the_service_is_asked_to_fold_in_series_and_episode(self):
        self.client.get('/api/library/sonarr/history')
        query = parse_qs(urlsplit(self.arr.urls('/api/v3/history?')[0]).query)
        self.assertEqual(query['includeSeries'], ['true'])
        self.assertEqual(query['includeEpisode'], ['true'])

    def test_the_event_filter_is_applied_by_the_service(self):
        self.client.get('/api/library/sonarr/history?event=imported')
        self.client.get('/api/library/radarr/history?event=deleted')
        sonarr = parse_qs(urlsplit(self.arr.urls('sonarr.test/api/v3/history?')[0]).query)
        radarr = parse_qs(urlsplit(self.arr.urls('radarr.test/api/v3/history?')[0]).query)
        self.assertEqual(sonarr['eventType'], ['3'])
        self.assertEqual(radarr['eventType'], ['6'], 'Radarr numbers deletions differently')
        self.assertEqual(radarr['includeMovie'], ['true'])

    def test_an_unknown_event_is_refused(self):
        self.assertEqual(
            self.client.get('/api/library/sonarr/history?event=nonsense').status_code, 400)

    def test_a_deletion_says_why_in_words(self):
        self.page(self.record(eventType='episodeFileDeleted', data={'reason': 'Upgrade'}))
        row = self.client.get('/api/library/sonarr/history').get_json()['records'][0]
        self.assertEqual(row['event'], 'deleted')
        self.assertEqual(row['reason'], 'Replaced by an upgrade')

    def test_a_radarr_row_names_the_film(self):
        self.arr.history = {'page': 1, 'pageSize': 25, 'totalRecords': 1, 'records': [{
            'id': 3, 'movieId': 5, 'eventType': 'grabbed', 'date': '2026-10-05T10:00:00Z',
            'sourceTitle': 'Example.Film.2024.1080p', 'quality': {'quality': {'name': 'Bluray-1080p'}},
            'data': {'indexer': 'indexer-a', 'downloadClient': 'client-b'},
            'movie': {'id': 5, 'tmdbId': 900002, 'title': 'Example Film', 'year': 2024}}]}
        row = self.client.get('/api/library/radarr/history').get_json()['records'][0]
        self.assertEqual((row['title'], row['year']), ('Example Film', 2024))
        self.assertIsNone(row['episode_code'])
        self.assertEqual(row['indexer'], 'indexer-a')
        self.assertEqual(row['download_client'], 'client-b')


class QueueTests(LibraryTestCase):

    def row(self, **extra):
        row = {
            'id': 1, 'seriesId': 219, 'episodeId': 1008, 'seasonNumber': 1,
            'title': 'Example.Show.S01E08.1080p.WEB-DL',
            'trackedDownloadState': 'downloading', 'trackedDownloadStatus': 'ok',
            'status': 'downloading', 'size': 1000, 'sizeleft': 400, 'timeleft': '00:12:00',
            'downloadClient': 'client-a', 'protocol': 'usenet',
            'quality': {'quality': {'name': 'WEBDL-1080p'}},
            'customFormats': [{'id': 1, 'name': 'WEB Tier 01'}],
            'episode': {'seasonNumber': 1, 'episodeNumber': 8, 'title': 'Episode Eight'},
            'series': {'id': 219, 'tvdbId': 900001, 'title': 'Example Show', 'year': 2021},
        }
        row.update(extra)
        return row

    def rows(self):
        return self.client.get('/api/library/sonarr/queue').get_json()['rows']

    def test_a_row_names_the_episode_and_says_what_it_is_doing(self):
        self.arr.queue = [self.row()]
        row = self.rows()[0]
        self.assertEqual(row['title'], 'Example Show')
        self.assertEqual(row['episode_code'], 'S01E08')
        self.assertEqual(row['episode_title'], 'Episode Eight')
        self.assertEqual(row['quality'], 'WEBDL-1080p')
        self.assertEqual(row['custom_formats'], ['WEB Tier 01'])
        self.assertEqual(row['status_text'], 'Downloading')
        self.assertEqual(row['tone'], 'brand')
        self.assertEqual(row['seconds_left'], 720)
        self.assertEqual(row['progress'], 60.0)
        self.assertEqual(row['external_id'], '900001')

    def test_a_stuck_row_says_stuck_and_why(self):
        self.arr.queue = [self.row(sizeleft=1000,
                                   errorMessage='The download is stalled with no connections')]
        row = self.rows()[0]
        self.assertEqual(row['status_label'], 'Stuck')
        self.assertEqual(row['status_text'], 'Stuck: The download is stalled with no connections')
        self.assertEqual(row['tone'], 'warn')

    def test_waiting_to_import_and_failed_in_plain_words(self):
        self.arr.queue = [self.row(id=1, trackedDownloadState='importPending', sizeleft=0),
                          self.row(id=2, trackedDownloadState='failedPending',
                                   errorMessage='Download client reported an error')]
        by_id = {row['id']: row for row in self.rows()}
        self.assertEqual(by_id[1]['status_text'], 'Waiting to import')
        self.assertEqual(by_id[2]['status_label'], 'Failed')
        self.assertEqual(by_id[2]['tone'], 'crit')

    def test_the_queue_asks_for_series_and_episode_but_the_ready_check_does_not(self):
        self.client.get('/api/library/sonarr/queue')
        query = parse_qs(urlsplit(self.arr.urls('/queue/details')[0]).query)
        self.assertEqual(query['includeEpisode'], ['true'])
        self.assertEqual(query['includeSeries'], ['true'])

        self.service.adapter('sonarr').in_flight(219, 1)
        gate = parse_qs(urlsplit(self.arr.urls('/queue/details')[-1]).query)
        self.assertEqual(gate, {'seriesId': ['219']},
                         "the Ready check's own read is left exactly as it was")


if __name__ == '__main__':
    unittest.main()
