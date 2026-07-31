#!/usr/bin/env python3
"""
The comparison engine — the labels every Explore decision is built from.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.explore.compare import (
    IN_SYNC, LOCAL_ONLY, MISSING, UPGRADED,
    NO_INFO, OUT_OF_SYNC, PARTIAL_SYNC, SYNCED,
    compare_library,
)
from services.explore.inventory import StaticInventory

GB = 1024 ** 3


def ep(series, season_folder, code, quality='WEBDL-1080p', group='HONE'):
    return f"{series}/{season_folder}/{series} - {code} - Title [{quality}][{group}-Dragon DB].mkv"


def build(media_type, remote_rows, local_rows, remote_dirs=None, local_dirs=None):
    remote = StaticInventory(remote_rows, remote_dirs, side='remote').read(media_type, '/remote')
    local = StaticInventory(local_rows, local_dirs, side='local').read(media_type, '/local')
    return compare_library(media_type, remote, local)


class SeasonPairingTests(unittest.TestCase):
    def test_padded_and_unpadded_season_folders_pair_up(self):
        # "Season 01" remote against "Season 1" local is one season, not two.
        diff = build(
            'tvshows',
            [(ep('Example Show', 'Season 01', 'S01E15'), 2 * GB, 100)],
            [(ep('Example Show', 'Season 1', 'S01E15'), 2 * GB, 90)],
        )
        series = diff.find('Example Show')
        self.assertEqual(len(series.seasons), 1)
        self.assertEqual(series.status, SYNCED)
        self.assertEqual(series.seasons[0].remote_folder, 'Season 01')
        self.assertEqual(series.seasons[0].local_folder, 'Season 1')

    def test_specials_pairs_with_season_zero(self):
        diff = build(
            'tvshows',
            [(ep('Show', 'Specials', 'S00E01'), GB, 100)],
            [(ep('Show', 'Season 00', 'S00E01'), GB, 100)],
        )
        series = diff.find('Show')
        self.assertEqual(len(series.seasons), 1)
        self.assertEqual(series.seasons[0].season, 0)
        self.assertEqual(series.status, SYNCED)


class LabelTests(unittest.TestCase):
    def test_remote_grew_so_the_new_episodes_are_missing(self):
        # Your scenario A: remote went 5 -> 10, local still has the first 5.
        remote = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 11)]
        local = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 6)]
        season = build('tvshows', remote, local).find('Show').seasons[0]

        self.assertEqual(season.counts.in_sync, 5)
        self.assertEqual(season.counts.missing, 5)
        self.assertEqual(season.counts.upgraded, 0)
        self.assertEqual(season.counts.local_only, 0)
        self.assertEqual(season.status, PARTIAL_SYNC)
        self.assertEqual(season.counts.incoming_bytes, 10 * GB)

    def test_same_episode_different_file_is_an_upgrade_not_a_download(self):
        # The duplicate trap: the upgraded file has a DIFFERENT name, so a
        # filename comparison would call it missing and leave two copies.
        season = build(
            'tvshows',
            [(ep('Show', 'Season 01', 'S01E23', 'Bluray-2160p', 'NEW'), 8 * GB, 200)],
            [(ep('Show', 'Season 01', 'S01E23', 'WEBDL-1080p', 'OLD'), 2 * GB, 100)],
        ).find('Show').seasons[0]

        self.assertEqual(season.counts.upgraded, 1)
        self.assertEqual(season.counts.missing, 0)
        self.assertEqual(season.counts.local_only, 0)
        episode = season.episodes[0]
        self.assertEqual(episode.label, UPGRADED)
        self.assertIn('NEW', episode.remote.name)
        self.assertIn('OLD', episode.local.name)

    def test_rename_at_the_same_size_is_left_alone(self):
        # Sonarr renames without changing content. Re-downloading it would be
        # pointless; calling it missing would create a duplicate.
        season = build(
            'tvshows',
            [(ep('Show', 'Season 01', 'S01E01', 'WEBDL-1080p', 'NEWGROUP'), 2 * GB, 200)],
            [(ep('Show', 'Season 01', 'S01E01', 'WEBDL-1080p', 'OLDGROUP'), 2 * GB, 100)],
        ).find('Show').seasons[0]

        self.assertEqual(season.counts.in_sync, 1)
        self.assertEqual(season.counts.upgraded, 0)
        self.assertTrue(season.episodes[0].renamed)
        self.assertEqual(season.status, SYNCED)

    def test_remote_shrank_so_local_extras_are_removal_candidates(self):
        # Your scenario B: remote has 2, local has 10.
        remote = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 3)]
        local = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 11)]
        season = build('tvshows', remote, local).find('Show').seasons[0]

        self.assertEqual(season.counts.in_sync, 2)
        self.assertEqual(season.counts.missing, 0)
        self.assertEqual(season.counts.local_only, 8)
        self.assertEqual(season.counts.removable_bytes, 16 * GB)
        # Holding everything the remote holds is still "synced"; the extras are
        # reported separately and warned about when a sync would remove them.
        self.assertEqual(season.status, SYNCED)

    def test_nothing_local_reads_as_out_of_sync(self):
        remote = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 4)]
        season = build('tvshows', remote, []).find('Show').seasons[0]
        self.assertEqual(season.status, OUT_OF_SYNC)
        self.assertEqual(season.counts.missing, 3)

    def test_multi_episode_file_covers_both_episodes(self):
        remote = [(ep('Show', 'Season 01', 'S01E01E02'), 4 * GB, 100)]
        local = [(ep('Show', 'Season 01', 'S01E01E02'), 4 * GB, 100)]
        season = build('tvshows', remote, local).find('Show').seasons[0]
        self.assertEqual(season.counts.in_sync, 2)
        self.assertEqual(season.status, SYNCED)


class AncillaryTests(unittest.TestCase):
    def test_artwork_and_subtitles_do_not_affect_status(self):
        season = build(
            'tvshows',
            [
                (ep('Show', 'Season 01', 'S01E01'), 2 * GB, 100),
                ('Show/Season 01/poster.jpg', 1000, 100),
                ('Show/Season 01/ep.nfo', 500, 100),
            ],
            [(ep('Show', 'Season 01', 'S01E01'), 2 * GB, 100)],
        ).find('Show').seasons[0]

        self.assertEqual(season.status, SYNCED)
        self.assertEqual(season.counts.missing, 0)
        self.assertEqual(season.ancillary_missing, 2)


class MovieTests(unittest.TestCase):
    def test_movie_main_file_swap_is_an_upgrade(self):
        season = build(
            'movies',
            [('Example Movie (2025)/Example Movie (2025) Bluray-2160p [NEW-Dragon DB].mkv', 20 * GB, 200)],
            [('Example Movie (2025)/Example Movie (2025) Bluray-1080p [PSA-Dragon DB].mkv', 8 * GB, 100)],
        ).find('Example Movie (2025)').seasons[0]

        self.assertEqual(season.counts.upgraded, 1)
        self.assertEqual(season.counts.missing, 0)
        self.assertEqual(season.counts.local_only, 0)

    def test_missing_movie_is_a_download(self):
        diff = build(
            'movies',
            [('Sample Movie (2026)/Sample Movie (2026) WEBDL-1080p [FLUX-Dragon DB].mkv', 6 * GB, 100)],
            [],
        )
        series = diff.find('Sample Movie (2026)')
        self.assertEqual(series.status, OUT_OF_SYNC)
        self.assertEqual(series.counts.missing, 1)
        self.assertFalse(series.exists_locally)


class MisplacedTests(unittest.TestCase):
    def test_file_nested_inside_a_directory_named_after_it_is_flagged(self):
        # Exactly the damage the old single-episode download left behind:
        # "Season 01/ep.mkv/ep.mkv", invisible to a media server.
        name = 'Short Anime (2010) - S01E18 - 018 - Eighteenth Night [Bluray-1080p][X-Dragon DB].mkv'
        season = build(
            'anime',
            [(f'Short Anime (2010)/Season 01/{name}', 2 * GB, 100)],
            [(f'Short Anime (2010)/Season 01/{name}/{name}', 2 * GB, 100)],
        ).find('Short Anime (2010)').seasons[0]

        self.assertEqual(len(season.misplaced), 1)
        self.assertTrue(season.misplaced[0].endswith(f'{name}/{name}'))


class RollupTests(unittest.TestCase):
    def test_series_status_covers_every_season_not_just_the_newest(self):
        # The old code took the newest season's status for the whole show, so a
        # show with a current S02 read "Synced" with S01 entirely absent.
        remote = (
            [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 10) for i in range(1, 4)]
            + [(ep('Show', 'Season 02', f'S02E{i:02d}'), 2 * GB, 999) for i in range(1, 4)]
        )
        local = [(ep('Show', 'Season 02', f'S02E{i:02d}'), 2 * GB, 999) for i in range(1, 4)]
        series = build('tvshows', remote, local).find('Show')

        self.assertEqual(len(series.seasons), 2)
        self.assertEqual(series.counts.missing, 3)
        self.assertEqual(series.counts.in_sync, 3)
        self.assertEqual(series.status, PARTIAL_SYNC)

    def test_empty_remote_series_has_no_information(self):
        series = build('tvshows', [], [(ep('Show', 'Season 01', 'S01E01'), GB, 100)]).find('Show')
        self.assertEqual(series.status, NO_INFO)
        self.assertEqual(series.counts.local_only, 1)


class ErrorPropagationTests(unittest.TestCase):
    def test_a_failed_remote_listing_is_reported_not_treated_as_empty(self):
        remote = StaticInventory([], side='remote', exists=False,
                                 error='No remote browse session').read('tvshows', '/remote')
        local = StaticInventory([], side='local').read('tvshows', '/local')
        diff = compare_library('tvshows', remote, local)
        self.assertFalse(diff.remote_ok)
        self.assertEqual(diff.remote_error, 'No remote browse session')




class SeasonFolderNamingTests(unittest.TestCase):
    """
    Sonarr writes `Season {season:00}`. Anything else still works — seasons pair
    by number, so "Season 1" lines up with "Season 01" — but the drift is worth
    surfacing rather than leaving to be discovered.
    """

    def _series(self, remote_folder, local_folder):
        return build(
            'tvshows',
            [(ep('Show', remote_folder, 'S01E01'), GB, 100)],
            [(ep('Show', local_folder, 'S01E01'), GB, 100)],
        ).find('Show')

    def test_the_padded_form_is_not_flagged(self):
        season = self._series('Season 01', 'Season 01').seasons[0]
        self.assertEqual(season.odd_folders, [])
        self.assertEqual(season.standard_name, 'Season 01')

    def test_an_unpadded_folder_is_flagged_on_whichever_side_has_it(self):
        season = self._series('Season 01', 'Season 1').seasons[0]
        self.assertEqual(season.odd_folders, ['Season 1'])

    def test_both_sides_using_the_same_odd_spelling_report_it_once(self):
        season = self._series('Season 1', 'Season 1').seasons[0]
        self.assertEqual(season.odd_folders, ['Season 1'])

    def test_each_side_is_reported_when_they_differ(self):
        season = self._series('Season 1', 'Season 001').seasons[0]
        self.assertEqual(season.odd_folders, ['Season 001', 'Season 1'])

    def test_specials_is_the_standard_name_for_season_zero(self):
        season = self._series('Specials', 'Specials').seasons[0]
        self.assertEqual(season.standard_name, 'Specials')
        self.assertEqual(season.odd_folders, [])

    def test_the_series_rolls_up_every_odd_folder_once(self):
        remote = [(ep('Show', 'Season 1', 'S01E01'), GB, 100),
                  (ep('Show', 'Season 2', 'S02E01'), GB, 100)]
        series = build('tvshows', remote, remote).find('Show')
        self.assertEqual(series.odd_folders, ['Season 1', 'Season 2'])

    def test_a_flagged_season_still_compares_and_syncs_normally(self):
        season = self._series('Season 01', 'Season 1').seasons[0]
        self.assertEqual(season.counts.in_sync, 1, 'pairing is by number, not spelling')
        self.assertEqual(season.status, 'SYNCED')

if __name__ == '__main__':
    unittest.main()
