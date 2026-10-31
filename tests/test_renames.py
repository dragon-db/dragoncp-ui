#!/usr/bin/env python3
"""
Renames from Explore: episodes still named TBA get their real titles.

The library is a real directory of empty files: a rename is a rename, and
faking the filesystem would test nothing. Sonarr and TMDB are fakes that answer
the way the real services were seen to answer. Every name is synthetic.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.database import DatabaseManager
from models.title_store import TitleStore
from models.webhook import RenameNotification
from services.renames import naming
from services.renames.service import RenamesError, RenamesService

SERIES = 'Example Show (2024)'
SEASON = 'Season 01'


def name(episode: int, title: str, ext: str = '.mkv') -> str:
    return f"Example Show (2024) - S01E{episode:02d} - {title} [WEBDL-1080p][GRP]{ext}"


class NamingTests(unittest.TestCase):
    def test_a_placeholder_is_found_in_both_shapes(self):
        self.assertTrue(naming.is_placeholder(name(5, 'TBA')))
        self.assertTrue(naming.is_placeholder(name(5, 'TBD')))
        self.assertTrue(naming.is_placeholder(
            'Example Anime (2024) - S01E05 - 005 - TBA [CF WEBDL-1080p][JA][GRP].mkv'))
        self.assertTrue(naming.is_placeholder('Example Show - S01E05 - TBA.mkv'))

    def test_a_real_title_or_a_sidecar_is_not_a_placeholder(self):
        self.assertFalse(naming.is_placeholder(name(5, 'A Real Title')))
        self.assertFalse(naming.is_placeholder(name(5, 'TBA', '.nfo')))
        self.assertFalse(naming.is_placeholder('Example Movie (2024) [Bluray-1080p].mkv'))
        # A title that merely contains the letters is a real title.
        self.assertFalse(naming.is_placeholder(name(5, 'TBA Returns')))

    def test_only_the_title_changes(self):
        new, why = naming.retitle(
            'Example Anime (2024) - S01E05 - 005 - TBA [CF WEBDL-1080p][JA][GRP].mkv',
            'The Real Title')
        self.assertEqual(why, '')
        self.assertEqual(
            new, 'Example Anime (2024) - S01E05 - 005 - The Real Title [CF WEBDL-1080p][JA][GRP].mkv')

    def test_titles_are_cleaned_the_way_sonarr_cleans_them(self):
        cases = {
            "Who's There?": 'Whos There',
            'Alpha: Bravo': 'Alpha Bravo',
            'Alpha & Bravo': 'Alpha and Bravo',
            'Alpha / Bravo / Charlie': 'Alpha Bravo Charlie',
            'Alpha... Bravo!': 'Alpha. Bravo!',
            'Alpha (Part 1)': 'Alpha Part 1',
            'Day 2 - Alpha': 'Day 2 Alpha',
            'Alpha 10:30': 'Alpha 10-30',
            'Alpha – Bravo’s Charlie': 'Alpha – Bravos Charlie',
            "Don't Stop": 'Dont Stop',
            'Ünïcode Title…': 'Ünïcode Title…',
        }
        for title, written in cases.items():
            with self.subTest(title=title):
                self.assertEqual(naming.episode_title(title), written)

    def test_a_tmdb_number_is_not_a_title(self):
        for title in ('Episode 5', 'Episode 12', 'TBA', '', None, '  '):
            self.assertFalse(naming.is_real_title(title), title)
        self.assertTrue(naming.is_real_title('Episode Five Returns'))

    def test_a_name_off_the_format_is_refused_with_a_reason(self):
        new, why = naming.retitle('Example Show 1080p x265.mkv', 'A Title')
        self.assertIsNone(new)
        self.assertIn('naming format', why)

    def test_a_name_too_long_for_the_disk_is_refused(self):
        new, why = naming.retitle(name(1, 'TBA'), 'A' * 300)
        self.assertIsNone(new)
        self.assertIn('too long', why)

    def test_sidecars_travel_and_other_videos_do_not(self):
        old, new = name(1, 'TBA'), name(1, 'Real')
        stem_old, stem_new = old[:-4], new[:-4]
        pairs = naming.sidecars(old, new, [
            old, f"{stem_old}.nfo", f"{stem_old}.en.srt", f"{stem_old}-thumb.jpg",
            f"{stem_old}-other.mkv", name(2, 'TBA', '.nfo'),
        ])
        self.assertEqual(dict(pairs), {
            f"{stem_old}.nfo": f"{stem_new}.nfo",
            f"{stem_old}.en.srt": f"{stem_new}.en.srt",
            f"{stem_old}-thumb.jpg": f"{stem_new}-thumb.jpg",
        })

    def test_same_file_named_twice_is_recognised(self):
        self.assertTrue(naming.same_apart_from_title(name(1, 'TBA'), name(1, 'Real')))
        self.assertFalse(naming.same_apart_from_title(
            name(1, 'TBA'), name(1, 'TBA').replace('WEBDL-1080p', 'Bluray-2160p')))

    def test_colon_rules_follow_sonarr_settings(self):
        rules = naming.NamingRules.from_sonarr(
            {'replaceIllegalCharacters': True, 'colonReplacementFormat': 1})
        self.assertEqual(rules.colon, 'dash')
        self.assertEqual(naming.episode_title('Alpha 10:30', rules), 'Alpha 10-30')
        rules = naming.NamingRules.from_sonarr({'replaceIllegalCharacters': False})
        self.assertEqual(naming.episode_title('Alpha 10:30 *', rules), 'Alpha 1030')


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

class FakeConfig(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeSonarr:
    def __init__(self):
        self.series = [{'id': 7, 'title': 'Example Show', 'year': 2024,
                        'path': f'/remote/tv/{SERIES}', 'tvdbId': 1001, 'tmdbId': 2002}]
        self.eps = []
        self.files = []
        self.preview = []
        self.commands = []
        self.calls = []
        self.token = 'a-read-access-token'

    def is_configured(self):
        return True

    def tmdb_token(self):
        return self.token

    def title_check_hours(self):
        return 6

    def library(self):
        self.calls.append('series')
        return True, self.series

    def episodes(self, series_id):
        self.calls.append('episodes')
        return True, self.eps

    def episode_files(self, series_id):
        self.calls.append('files')
        return True, self.files

    def rename_preview(self, series_id):
        self.calls.append('preview')
        return True, self.preview

    def naming_config(self):
        self.calls.append('naming')
        return {'replaceIllegalCharacters': True, 'colonReplacementFormat': 4}

    def command(self, command, body=None):
        self.commands.append((command, body))
        return True, {'id': 99}, 'accepted'

    def command_status(self, command_id):
        return 'completed'


class FakeConnectors:
    def __init__(self, adapter):
        self._adapter = adapter
        self.store = self

    def get_connector(self, connector_id):
        return {'enabled': 1}

    def adapter(self, connector_id):
        return self._adapter


class FakeTmdb:
    """Two seasons' worth of episodes; the class attribute is set per test."""
    seasons = {}

    def __init__(self, token):
        self.token = token

    def show(self, tmdb_id):
        return {'tmdb_id': tmdb_id, 'name': 'Example Show', 'year': 2024,
                'seasons': {n: len(eps) for n, eps in self.seasons.get(tmdb_id, {}).items()}}

    def find_by_tvdb(self, tvdb_id):
        return {'tmdb_id': 2002, 'name': 'Example Show'}

    def season(self, tmdb_id, season):
        return self.seasons.get(tmdb_id, {}).get(season)

    def search(self, query, year=None):
        return True, [{'tmdb_id': 3003, 'name': 'Another Show', 'year': 2020}], ''


class FakeAlerts:
    def __init__(self):
        self.raised = []

    def raise_alert(self, kind, title, message='', severity='warning', **kwargs):
        self.raised.append((kind, title, message))


# --------------------------------------------------------------------------
# the service
# --------------------------------------------------------------------------

class RenamesServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, 'tv_shows')
        self.season_dir = os.path.join(self.root, SERIES, SEASON)
        os.makedirs(self.season_dir)
        self.config = FakeConfig({'TVSHOW_DEST_PATH': self.root,
                                  'ANIME_DEST_PATH': os.path.join(self.tmp.name, 'anime')})
        self.db = DatabaseManager(os.path.join(self.tmp.name, 'renames.db'))
        self.store = TitleStore(self.db)
        self.history = RenameNotification(self.db)
        self.sonarr = FakeSonarr()
        self.alerts = FakeAlerts()
        self.active = []
        self.service = RenamesService(
            self.config, self.db, self.history, self.store,
            connectors=lambda: FakeConnectors(self.sonarr),
            active_transfers=lambda: self.active, alerts=self.alerts,
            sleep=lambda seconds: None)
        tmdb = patch('services.renames.service.TmdbClient', FakeTmdb)
        tmdb.start()
        self.addCleanup(tmdb.stop)
        FakeTmdb.seasons = {}
        env = patch.dict(os.environ, {'TEST_MODE': '0'})
        env.start()
        self.addCleanup(env.stop)

        # E01: Sonarr holds it and its rename gives the real title.
        # E02: Sonarr has the title, no longer holds the file.
        # E03: Sonarr still says TBA; TMDB has the title, same air date.
        # E04: Sonarr still says TBA; TMDB's episode aired on another day.
        # E05: already titled — never touched.
        for episode, title in ((1, 'TBA'), (2, 'TBA'), (3, 'TBA'), (4, 'TBA'), (5, 'Fifth')):
            self.touch(name(episode, title))
        self.touch(name(1, 'TBA', '.nfo'))
        self.touch(name(1, 'TBA', '.en.srt'))
        self.sonarr.eps = [
            self.episode(1, 'Pilot: Part One', file_id=501, air='2024-01-01'),
            self.episode(2, 'Second Thing', air='2024-01-08'),
            self.episode(3, 'TBA', air='2024-01-15'),
            self.episode(4, 'TBA', air='2024-01-22'),
            self.episode(5, 'Fifth', air='2024-01-29'),
        ]
        self.sonarr.files = [{'id': 501, 'seasonNumber': 1,
                              'relativePath': f"{SEASON}/{name(1, 'TBA')}"}]
        self.sonarr.preview = [{'episodeFileId': 501, 'seasonNumber': 1,
                                'existingPath': f"{SEASON}/{name(1, 'TBA')}",
                                'newPath': f"{SEASON}/{name(1, 'Pilot - Part One')}"}]
        FakeTmdb.seasons = {2002: {1: {
            3: {'title': 'Third From TMDB', 'air_date': '2024-01-16'},
            4: {'title': 'Fourth From TMDB', 'air_date': '2024-03-01'},
        }}}

    def touch(self, file_name: str, folder: str = None) -> str:
        path = os.path.join(folder or self.season_dir, file_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as handle:
            handle.write('x')
        return path

    def here(self, file_name: str) -> bool:
        return os.path.exists(os.path.join(self.season_dir, file_name))

    @staticmethod
    def episode(number, title, file_id=None, air=None):
        return {'seasonNumber': 1, 'episodeNumber': number, 'title': title,
                'hasFile': bool(file_id), 'episodeFileId': file_id or 0, 'airDate': air}

    def items(self, plan):
        return {i['code']: i for i in plan['items']}

    # -- the plan ----------------------------------------------------------

    def test_each_episode_gets_its_title_from_the_right_place(self):
        plan = self.service.plan('tvshows', SERIES)
        items = self.items(plan)
        self.assertEqual(set(items), {'S01E01', 'S01E02', 'S01E03', 'S01E04'})

        first = items['S01E01']
        self.assertEqual(first['state'], 'ready')
        self.assertEqual(first['new_name'], name(1, 'Pilot - Part One'),
                         "Sonarr's own new name, so both ends match")
        self.assertTrue(first['sonarr_rename'])
        self.assertEqual(first['sonarr_file_id'], 501)
        self.assertEqual(len(first['sidecars']), 2)

        second = items['S01E02']
        self.assertEqual((second['state'], second['source']), ('ready', 'sonarr'))
        self.assertEqual(second['new_name'], name(2, 'Second Thing'))
        self.assertFalse(second['sonarr_rename'])

        third = items['S01E03']
        self.assertEqual((third['state'], third['source']), ('ready', 'tmdb'))
        self.assertEqual(third['new_name'], name(3, 'Third From TMDB'))

        fourth = items['S01E04']
        self.assertEqual(fourth['state'], 'waiting')
        self.assertIn('another day', fourth['reason'])

        self.assertEqual(plan['counts']['ready'], 3)
        self.assertEqual(plan['counts']['sonarr_files'], 1)
        self.assertEqual(plan['sonarr']['state'], 'found')

    def test_sonarr_is_asked_even_when_its_copy_is_another_release(self):
        # Sonarr upgraded its copy; this disk still has the older release.
        upgraded = name(1, 'TBA').replace('WEBDL-1080p', 'Bluray-2160p')
        self.sonarr.files[0]['relativePath'] = f"{SEASON}/{upgraded}"
        self.sonarr.preview[0]['existingPath'] = f"{SEASON}/{upgraded}"
        self.sonarr.preview[0]['newPath'] = f"{SEASON}/" + upgraded.replace('TBA', 'Pilot - Part One')
        first = self.items(self.service.plan('tvshows', SERIES))['S01E01']
        # Its own quality, and the title cleaned the way Sonarr cleans it.
        self.assertEqual(first['new_name'], name(1, 'Pilot Part One'))
        self.assertTrue(first['sonarr_rename'])
        self.service.apply('tvshows', SERIES)
        self.assertEqual(self.sonarr.commands,
                         [('RenameFiles', {'seriesId': 7, 'files': [501]})])

    def test_a_preview_changes_nothing(self):
        self.service.plan('tvshows', SERIES)
        self.assertTrue(self.here(name(1, 'TBA')))
        self.assertEqual(self.sonarr.commands, [])

    def test_without_a_tmdb_key_sonarr_titles_still_rename(self):
        self.sonarr.token = ''
        items = self.items(self.service.plan('tvshows', SERIES))
        self.assertEqual(items['S01E02']['state'], 'ready')
        self.assertEqual(items['S01E03']['state'], 'waiting')
        self.assertEqual(items['S01E03']['reason'], 'Sonarr still says TBA')

    def test_a_name_already_taken_is_never_overwritten(self):
        self.touch(name(2, 'Second Thing'))
        items = self.items(self.service.plan('tvshows', SERIES))
        self.assertEqual(items['S01E02']['state'], 'skipped')
        self.assertIn('already exists', items['S01E02']['reason'])

    # -- renaming ------------------------------------------------------------

    def test_rename_renames_here_and_asks_sonarr_for_its_copy(self):
        result = self.service.apply('tvshows', SERIES, actor='admin')

        self.assertEqual(result['success_count'], 3)
        self.assertTrue(self.here(name(1, 'Pilot - Part One')))
        self.assertTrue(self.here(name(1, 'Pilot - Part One', '.nfo')))
        self.assertTrue(self.here(name(1, 'Pilot - Part One', '.en.srt')))
        self.assertTrue(self.here(name(2, 'Second Thing')))
        self.assertTrue(self.here(name(3, 'Third From TMDB')))
        self.assertTrue(self.here(name(4, 'TBA')), 'a waiting episode keeps its name')
        self.assertTrue(self.here(name(5, 'Fifth')))

        self.assertEqual(self.sonarr.commands,
                         [('RenameFiles', {'seriesId': 7, 'files': [501]})])
        self.assertTrue(result['sonarr']['ok'])

        row = self.history.get(result['notification_id'])
        self.assertEqual(row['trigger_kind'], 'manual')
        self.assertEqual(row['triggered_by'], 'admin')
        self.assertEqual(row['success_count'], 3)

        titled = self.store.episode_titles('tvshows', SERIES)
        self.assertEqual(titled[(1, 3)]['source'], 'tmdb')
        self.assertEqual(titled[(1, 3)]['file_name'], name(3, 'Third From TMDB'))

    def test_test_mode_rehearses_and_changes_nothing(self):
        with patch.dict(os.environ, {'TEST_MODE': '1'}):
            result = self.service.apply('tvshows', SERIES)
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['success_count'], 3)
        self.assertTrue(self.here(name(1, 'TBA')))
        self.assertTrue(self.here(name(1, 'TBA', '.nfo')))
        self.assertEqual(self.sonarr.commands, [])
        self.assertIn('Test mode', result['sonarr']['message'])

    def test_only_the_files_the_preview_showed_are_renamed(self):
        result = self.service.apply('tvshows', SERIES, picks=[
            {'path': f"{SEASON}/{name(2, 'TBA')}", 'new_name': name(2, 'Second Thing')}])
        self.assertEqual(result['success_count'], 1)
        self.assertTrue(self.here(name(1, 'TBA')))
        self.assertEqual(self.sonarr.commands, [])

    def test_a_name_that_changed_since_the_preview_is_refused(self):
        with self.assertRaises(RenamesError) as caught:
            self.service.apply('tvshows', SERIES, picks=[
                {'path': f"{SEASON}/{name(2, 'TBA')}", 'new_name': name(2, 'Something Else')}])
        self.assertEqual(caught.exception.status, 409)
        self.assertTrue(self.here(name(2, 'TBA')))

    def test_one_stale_name_refuses_the_whole_rename(self):
        # Three approved; one title changed since the preview. Nothing moves.
        picks = [{'path': f"{SEASON}/{name(1, 'TBA')}", 'new_name': name(1, 'Pilot - Part One')},
                 {'path': f"{SEASON}/{name(2, 'TBA')}", 'new_name': name(2, 'Second Thing')},
                 {'path': f"{SEASON}/{name(3, 'TBA')}", 'new_name': name(3, 'Third From TMDB')}]
        self.sonarr.eps[1]['title'] = 'Second Thing Renamed'
        with self.assertRaises(RenamesError) as caught:
            self.service.apply('tvshows', SERIES, picks=picks)
        self.assertEqual(caught.exception.status, 409)
        self.assertIn('1 of 3', caught.exception.message)
        for episode in (1, 2, 3):
            self.assertTrue(self.here(name(episode, 'TBA')), episode)
        self.assertEqual(self.sonarr.commands, [])

    def test_a_transfer_into_the_series_blocks_a_rename(self):
        self.active = [{'media_type': 'tvshows', 'folder_name': SERIES}]
        with self.assertRaises(RenamesError) as caught:
            self.service.apply('tvshows', SERIES)
        self.assertEqual(caught.exception.status, 409)
        self.assertTrue(self.here(name(2, 'TBA')))

    def test_a_folder_name_cannot_escape_the_library(self):
        for folder in ('..', '../etc', 'a/b'):
            with self.assertRaises(RenamesError):
                self.service.plan('tvshows', folder)

    # -- Undo ----------------------------------------------------------------

    def test_undo_puts_every_name_back(self):
        result = self.service.apply('tvshows', SERIES)
        undone = self.service.undo(result['notification_id'])

        self.assertEqual(undone['restored_count'], 3)
        for episode in (1, 2, 3):
            self.assertTrue(self.here(name(episode, 'TBA')), episode)
        self.assertTrue(self.here(name(1, 'TBA', '.nfo')))
        self.assertTrue(self.here(name(1, 'TBA', '.en.srt')))
        self.assertIn('Sonarr', undone['message'])
        self.assertEqual(self.store.episode_titles('tvshows', SERIES), {})
        self.assertIsNotNone(self.history.get(result['notification_id'])['undone_at'])

        with self.assertRaises(RenamesError) as caught:
            self.service.undo(result['notification_id'])
        self.assertEqual(caught.exception.status, 409)

    def test_a_partial_undo_can_be_retried(self):
        result = self.service.apply('tvshows', SERIES)
        blocker = self.touch(name(2, 'TBA'))
        first = self.service.undo(result['notification_id'])
        self.assertEqual(first['restored_count'], 2)
        self.assertEqual(len(first['failed']), 1)
        self.assertIsNone(self.history.get(result['notification_id'])['undone_at'])
        self.assertTrue(self.here(name(2, 'Second Thing')))

        os.remove(blocker)
        second = self.service.undo(result['notification_id'])
        self.assertEqual((second['restored_count'], second['failed']), (1, []))
        self.assertTrue(self.here(name(2, 'TBA')))
        self.assertTrue(self.here(name(1, 'TBA', '.nfo')), 'sidecars were put back once')
        self.assertIsNotNone(self.history.get(result['notification_id'])['undone_at'])

    def test_a_stuck_sidecar_keeps_the_run_open(self):
        result = self.service.apply('tvshows', SERIES)
        blocker = self.touch(name(1, 'TBA', '.nfo'))
        first = self.service.undo(result['notification_id'])
        self.assertEqual(first['restored_count'], 3)
        self.assertEqual(len(first['failed']), 1)
        self.assertIsNone(self.history.get(result['notification_id'])['undone_at'])

        os.remove(blocker)
        second = self.service.undo(result['notification_id'])
        self.assertEqual((second['restored_count'], second['failed']), (0, []))
        self.assertTrue(self.here(name(1, 'TBA', '.nfo')))
        self.assertIsNotNone(self.history.get(result['notification_id'])['undone_at'])

    def test_no_history_means_no_rename(self):
        with patch.object(self.history, 'create', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RenamesError) as caught:
                self.service.apply('tvshows', SERIES)
        self.assertEqual(caught.exception.status, 500)
        for episode in (1, 2, 3):
            self.assertTrue(self.here(name(episode, 'TBA')), episode)
        self.assertEqual(self.history.get_all(), [])

    def test_a_rename_stops_when_its_history_cannot_be_saved(self):
        with patch.object(self.history, 'update', return_value=False):
            with self.assertRaises(RenamesError) as caught:
                self.service.apply('tvshows', SERIES)
        self.assertEqual(caught.exception.status, 500)
        self.assertIn('Renamed 1 file(s)', caught.exception.message)
        self.assertEqual(self.sonarr.commands, [], 'Sonarr is not asked after a stop')
        moved = [e for e in (1, 2, 3) if not self.here(name(e, 'TBA'))]
        self.assertEqual(len(moved), 1)

        # The run was written before the file moved, so Undo still finds it.
        [row] = self.history.get_all()
        undone = self.service.undo(row['notification_id'])
        self.assertEqual((undone['restored_count'], undone['failed']), (1, []))
        for episode in (1, 2, 3):
            self.assertTrue(self.here(name(episode, 'TBA')), episode)

    def test_undo_stops_when_its_progress_cannot_be_saved_and_resumes(self):
        result = self.service.apply('tvshows', SERIES)
        with patch.object(self.history, 'update', return_value=False):
            with self.assertRaises(RenamesError) as caught:
                self.service.undo(result['notification_id'])
        self.assertEqual(caught.exception.status, 500)
        self.assertIn('Put back 1 name(s)', caught.exception.message)
        self.assertIsNone(self.history.get(result['notification_id'])['undone_at'])

        again = self.service.undo(result['notification_id'])
        self.assertEqual((again['restored_count'], again['failed']), (3, []))
        for episode in (1, 2, 3):
            self.assertTrue(self.here(name(episode, 'TBA')), episode)
        self.assertTrue(self.here(name(1, 'TBA', '.nfo')))
        self.assertIsNotNone(self.history.get(result['notification_id'])['undone_at'])

    def test_undo_of_a_sonarr_retitle_brings_the_tmdb_title_back(self):
        self.service.apply('tvshows', SERIES)
        self.sonarr.eps[2]['title'] = 'Third From Sonarr'
        retitle = self.service.apply('tvshows', SERIES)
        self.assertTrue(self.here(name(3, 'Third From Sonarr')))
        self.assertEqual(self.store.episode_titles('tvshows', SERIES), {})

        self.service.undo(retitle['notification_id'])
        self.assertTrue(self.here(name(3, 'Third From TMDB')))
        row = self.store.episode_titles('tvshows', SERIES)[(1, 3)]
        self.assertEqual((row['source'], row['file_name']), ('tmdb', name(3, 'Third From TMDB')))
        third = self.items(self.service.plan('tvshows', SERIES))['S01E03']
        self.assertEqual((third['state'], third['new_name']), ('ready', name(3, 'Third From Sonarr')))

    # -- Sonarr's own rename webhook -------------------------------------------

    def webhook_service(self):
        from services.rename_service import RenameService
        replay = RenameService(self.config, self.history)
        replay.renames = self.service
        return replay

    @staticmethod
    def rename_payload(previous: str, new: str):
        base = f'/remote/tv/{SERIES}'
        return {'eventType': 'Rename', 'series': {'id': 7, 'title': 'Example Show', 'path': base},
                'renamedEpisodeFiles': [{
                    'id': 1, 'previousPath': f"{base}/{SEASON}/{previous}",
                    'previousRelativePath': f"{SEASON}/{previous}",
                    'path': f"{base}/{SEASON}/{new}", 'relativePath': f"{SEASON}/{new}"}]}

    def test_undo_skips_what_the_webhook_found_already_renamed(self):
        self.service.apply('tvshows', SERIES)
        with patch.object(self.service, 'check_later') as check_later:
            ok, result = self.webhook_service().process_rename_webhook(
                self.rename_payload(name(2, 'TBA'), name(2, 'Second Thing')), 'tvshows')
        self.assertTrue(ok)
        check_later.assert_not_called()
        with self.assertRaises(RenamesError) as caught:
            self.service.undo(result['notification_id'])
        self.assertEqual(caught.exception.status, 400)
        self.assertTrue(self.here(name(2, 'Second Thing')))

    def test_a_webhook_rename_retires_the_tmdb_title_and_checks_again(self):
        self.service.apply('tvshows', SERIES)
        self.assertIn((1, 3), self.store.episode_titles('tvshows', SERIES))
        with patch.object(self.service, 'check_later') as check_later:
            ok, result = self.webhook_service().process_rename_webhook(
                self.rename_payload(name(3, 'TBA'), name(3, 'Third From Sonarr')), 'tvshows')
        self.assertTrue(ok)
        self.assertTrue(self.here(name(3, 'Third From Sonarr')))
        self.assertEqual(self.store.episode_titles('tvshows', SERIES), {})
        check_later.assert_called_once_with('tvshows', SERIES)

        self.service.undo(result['notification_id'])
        self.assertTrue(self.here(name(3, 'Third From TMDB')))
        self.assertEqual(self.store.episode_titles('tvshows', SERIES)[(1, 3)]['source'], 'tmdb')

    # -- background work, for a page with live updates off ----------------------

    def test_jobs_report_a_finished_check_and_rename_all(self):
        self.assertEqual(self.service.jobs()['checks_finished'], 0)
        self.service.check_all(trigger='manual')
        jobs = self.service.jobs()
        self.assertEqual((jobs['checking'], jobs['checks_finished']), (False, 1))

        started = self.service.apply_library('tvshows', [SERIES])
        for _ in range(200):
            run = self.service.jobs()['rename_all']['tvshows']
            if not run['running']:
                break
            time.sleep(0.01)
        self.assertEqual(run['run_id'], started['run_id'])
        self.assertEqual(run['finished']['run_id'], started['run_id'])
        self.assertEqual(run['finished']['renamed'], 3)

    # -- titles from TMDB, later replaced by Sonarr's ---------------------------

    def test_sonarr_title_is_offered_once_sonarr_has_one(self):
        self.service.apply('tvshows', SERIES)
        self.assertTrue(self.here(name(3, 'Third From TMDB')))

        self.sonarr.eps[2]['title'] = 'Third From Sonarr'
        items = self.items(self.service.plan('tvshows', SERIES))
        third = items['S01E03']
        self.assertEqual((third['state'], third['source']), ('ready', 'sonarr'))
        self.assertTrue(third['retitle'])
        self.assertEqual(third['new_name'], name(3, 'Third From Sonarr'))

    def test_a_tmdb_title_is_never_replaced_by_another_tmdb_title(self):
        self.service.apply('tvshows', SERIES)
        FakeTmdb.seasons[2002][1][3]['title'] = 'Renamed On TMDB'
        items = self.items(self.service.plan('tvshows', SERIES))
        self.assertNotIn('S01E03', items)

    # -- series Sonarr does not have ---------------------------------------------

    def test_a_series_not_in_sonarr_waits_for_a_tmdb_link(self):
        other = 'Another Show (2020)'
        folder = os.path.join(self.root, other, SEASON)
        self.touch('Another Show (2020) - S01E01 - TBA [HDTV-720p][GRP].mkv', folder)
        plan = self.service.plan('tvshows', other)
        self.assertEqual(plan['sonarr']['state'], 'missing')
        self.assertEqual(plan['items'][0]['state'], 'waiting')
        self.assertIn('Find it on TMDB', plan['items'][0]['reason'])

        FakeTmdb.seasons[3003] = {1: {1: {'title': 'Opening Night', 'air_date': '2020-02-01'},
                                      2: {'title': 'Second Night', 'air_date': '2020-02-08'}}}
        self.service.tmdb_link('tvshows', other, 3003, actor='admin')
        plan = self.service.plan('tvshows', other)
        self.assertEqual(plan['items'][0]['state'], 'ready')
        self.assertEqual(plan['items'][0]['new_name'],
                         'Another Show (2020) - S01E01 - Opening Night [HDTV-720p][GRP].mkv')

    def test_a_season_longer_here_than_on_tmdb_is_not_matched(self):
        other = 'Another Show (2020)'
        folder = os.path.join(self.root, other, SEASON)
        self.touch('Another Show (2020) - S01E01 - TBA [HDTV-720p][GRP].mkv', folder)
        self.touch('Another Show (2020) - S01E03 - Third [HDTV-720p][GRP].mkv', folder)
        FakeTmdb.seasons[3003] = {1: {1: {'title': 'Opening Night', 'air_date': None}}}
        self.service.tmdb_link('tvshows', other, 3003)
        plan = self.service.plan('tvshows', other)
        self.assertEqual(plan['items'][0]['state'], 'waiting')
        self.assertIn('more episodes here than on TMDB', plan['items'][0]['reason'])

    # -- the title check -----------------------------------------------------------

    def test_the_check_stores_what_it_found_and_asks_little(self):
        result = self.service.check_all(trigger='manual')
        self.assertTrue(result['ok'])
        self.assertEqual(result['ready'], 3)
        status = self.service.library_status('tvshows')[SERIES]
        self.assertEqual((status['ready'], status['waiting']), (3, 1))
        self.assertEqual(status['seasons'][SEASON]['ready'], 3)
        # A check reads the episode list, never the files or the rename preview.
        self.assertNotIn('files', self.sonarr.calls)
        self.assertNotIn('preview', self.sonarr.calls)
        files = self.service.season_titles('tvshows', SERIES, SEASON)
        self.assertEqual(files[name(2, 'TBA')]['new_name'], name(2, 'Second Thing'))
        self.assertEqual(self.alerts.raised, [], 'a check someone pressed does not alert')

    def test_a_scheduled_check_alerts_once_for_new_titles(self):
        self.service.check_all(trigger='scheduled')
        self.assertEqual(len(self.alerts.raised), 1)
        self.assertEqual(self.alerts.raised[0][0], 'titles_ready')
        self.service.check_all(trigger='scheduled')
        self.assertEqual(len(self.alerts.raised), 1, 'nothing new, no second alert')

        self.sonarr.eps[3]['title'] = 'Fourth From Sonarr'
        self.service.check_all(trigger='scheduled')
        self.assertEqual(len(self.alerts.raised), 2)

    def test_a_renamed_series_leaves_the_check(self):
        self.service.check_all()
        self.sonarr.eps[3]['title'] = 'Fourth From Sonarr'
        self.service.apply('tvshows', SERIES)
        status = self.service.library_status('tvshows')[SERIES]
        self.assertEqual((status['state'], status['placeholders']), ('clear', 0),
                         'kept at zero, so the tag goes before the next walk')
        # An episode named from TMDB keeps the series watched, at zero, so
        # Sonarr's own title is offered once it has one.
        self.service.check_all()
        self.assertEqual(self.service.library_status('tvshows')[SERIES]['state'], 'clear')

    def test_a_series_with_nothing_left_leaves_the_check(self):
        self.sonarr.token = ''
        self.sonarr.eps[2]['title'] = 'Third'
        self.sonarr.eps[3]['title'] = 'Fourth'
        self.service.check_all()
        self.service.apply('tvshows', SERIES)
        self.service.check_all()
        self.assertNotIn(SERIES, self.service.library_status('tvshows'))

    def test_the_scheduled_check_is_off_until_switched_on(self):
        from services.connectors.adapters.sonarr import SonarrConnector
        config = {'base_url': 'http://sonarr.local'}
        adapter = SonarrConnector(config=config, secrets=lambda n: 'key')
        self.sonarr.title_check_hours = adapter.title_check_hours
        job = self.service.scheduler_job()
        self.assertIsNone(job.interval(), 'off by default: titles are checked by hand')
        config['title_check_enabled'] = 'true'
        adapter.config = dict(config)
        self.assertEqual(job.interval(), 6 * 3600)
        adapter.config['title_check_hours'] = '12'
        self.assertEqual(job.interval(), 12 * 3600)

    def test_refresh_asks_sonarr_for_fresh_titles(self):
        with patch('threading.Thread') as thread:
            result = self.service.refresh('tvshows', SERIES)
        self.assertTrue(result['asked_sonarr'])
        self.assertEqual(self.sonarr.commands, [('RefreshSeries', {'seriesId': 7})])
        thread.return_value.start.assert_called_once()


class SonarrCommandTests(unittest.TestCase):
    def adapter(self, **config):
        from services.connectors.adapters.sonarr import SonarrConnector
        secrets = {'api_key': 'key', 'tmdb_token': config.pop('tmdb', '')}
        return SonarrConnector(config={'base_url': 'http://sonarr.local', **config},
                               secrets=lambda n: secrets.get(n, ''))

    def test_only_the_two_allowed_commands_are_ever_sent(self):
        from services.connectors import transport
        with patch.dict(os.environ, {'TEST_MODE': '0'}), \
                patch.object(transport, 'send') as send:
            send.return_value = transport.TransportResult(True, 201, '{"id": 4}')
            sent, answer, _ = self.adapter().command('RenameFiles', {'seriesId': 1, 'files': [2]})
            refused, _, words = self.adapter().command('DeleteSeries', {'seriesId': 1})
        self.assertTrue(sent)
        self.assertEqual(answer, {'id': 4})
        self.assertFalse(refused)
        self.assertIn('never', words)
        self.assertEqual(send.call_count, 1)
        args, kwargs = send.call_args
        self.assertEqual(args[0], 'POST')
        self.assertEqual(kwargs['json'], {'seriesId': 1, 'files': [2], 'name': 'RenameFiles'})
        self.assertEqual(kwargs['max_retries'], 0)

    def test_test_mode_never_sends_a_command(self):
        from services.connectors import transport
        with patch.dict(os.environ, {'TEST_MODE': '1'}), patch.object(transport, 'send') as send:
            sent, _, words = self.adapter().command('RefreshSeries', {'seriesId': 1})
        self.assertFalse(sent)
        self.assertIn('Test mode', words)
        send.assert_not_called()

    def test_reads_stay_read_only(self):
        ok, _ = self.adapter()._request('POST', '/api/v3/series')
        self.assertFalse(ok)

    def test_the_check_reports_sonarr_and_tmdb_on_their_own_lines(self):
        from services.connectors import transport
        status = transport.TransportResult(True, 200, '{"version": "4.0.0", "appName": "Sonarr"}')
        rejected = transport.TransportResult(False, 401, '', error='rejected')
        with patch.object(transport, 'send', side_effect=[status, rejected]):
            result = self.adapter(tmdb='token-value-long-enough').check()
        self.assertFalse(result.ok)
        self.assertEqual(result.message.split('\n'), ['Connected to Sonarr 4.0.0',
                                                      'TMDB rejected the key'])

    def test_the_tmdb_key_travels_in_a_header(self):
        from services.connectors import transport
        from services.renames.tmdb import TmdbClient, clear_cache
        clear_cache()
        with patch.object(transport, 'send') as send:
            send.return_value = transport.TransportResult(True, 200, '{"success": true}')
            ok, _ = TmdbClient('eyJ-a-long-read-access-token').check()
        self.assertTrue(ok)
        args, kwargs = send.call_args
        self.assertNotIn('eyJ', args[1])
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer eyJ-a-long-read-access-token')


class WebhookReplayTests(unittest.TestCase):
    """Sonarr's own rename webhook, matched by episode."""

    def setUp(self):
        from services.rename_service import RenameService
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, 'tv_shows')
        self.season_dir = os.path.join(self.root, SERIES, SEASON)
        os.makedirs(self.season_dir)
        self.db = DatabaseManager(os.path.join(self.tmp.name, 'webhook.db'))
        self.service = RenameService({'TVSHOW_DEST_PATH': self.root,
                                      'ANIME_DEST_PATH': os.path.join(self.tmp.name, 'a')},
                                     RenameNotification(self.db))
        env = patch.dict(os.environ, {'TEST_MODE': '0'})
        env.start()
        self.addCleanup(env.stop)

    def webhook(self, previous: str, new: str):
        base = f'/remote/tv/{SERIES}'
        return {'eventType': 'Rename', 'series': {'id': 7, 'title': 'Example Show', 'path': base},
                'renamedEpisodeFiles': [{
                    'id': 1, 'previousPath': f"{base}/{SEASON}/{previous}",
                    'previousRelativePath': f"{SEASON}/{previous}",
                    'path': f"{base}/{SEASON}/{new}", 'relativePath': f"{SEASON}/{new}"}]}

    def touch(self, file_name):
        with open(os.path.join(self.season_dir, file_name), 'w') as handle:
            handle.write('x')

    def here(self, file_name):
        return os.path.exists(os.path.join(self.season_dir, file_name))

    def test_a_file_under_another_name_is_found_by_its_episode(self):
        # Named from TMDB here; Sonarr renames its TBA copy to its own title.
        self.touch(name(3, 'Third From TMDB'))
        self.touch(name(3, 'Third From TMDB', '.nfo'))
        ok, result = self.service.process_rename_webhook(
            self.webhook(name(3, 'TBA'), name(3, 'Third From Sonarr')), 'tvshows')
        self.assertTrue(ok)
        self.assertEqual(result['success_count'], 1)
        self.assertTrue(self.here(name(3, 'Third From Sonarr')))
        self.assertTrue(self.here(name(3, 'Third From Sonarr', '.nfo')), 'the sidecar moved too')
        self.assertFalse(self.here(name(3, 'Third From TMDB')))

    def test_a_file_this_disk_never_had_is_not_a_failure(self):
        ok, result = self.service.process_rename_webhook(
            self.webhook(name(4, 'TBA'), name(4, 'Fourth')), 'tvshows')
        self.assertTrue(ok)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['failed_count'], 0)
        self.assertEqual(result['not_here_count'], 1)

    def test_a_file_explore_already_renamed_counts_as_done(self):
        self.touch(name(1, 'Pilot'))
        ok, result = self.service.process_rename_webhook(
            self.webhook(name(1, 'TBA'), name(1, 'Pilot')), 'tvshows')
        self.assertTrue(ok)
        self.assertEqual(result['success_count'], 1)
        self.assertIn('already renamed', result['renamed_files'][0]['message'])


if __name__ == '__main__':
    unittest.main()
