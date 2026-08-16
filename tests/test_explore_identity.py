#!/usr/bin/env python3
"""
Identity parsing, exercised against the filename shapes that actually exist in
the library rather than invented ones.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.explore.identity import (
    EpisodeKey,
    is_ancillary_file,
    is_media_file,
    parse_absolute_number,
    parse_episode_keys,
    season_number_from_folder,
    split_library_path,
)


class SeasonFolderTests(unittest.TestCase):
    def test_padded_and_unpadded_are_the_same_season(self):
        # Both spellings exist in the library; matching on the string would
        # leave "Example Show/Season 1" permanently unpaired.
        self.assertEqual(season_number_from_folder('Season 01'), 1)
        self.assertEqual(season_number_from_folder('Season 1'), 1)
        self.assertEqual(season_number_from_folder('season 2'), 2)
        self.assertEqual(season_number_from_folder('Season 17'), 17)

    def test_specials_is_season_zero(self):
        self.assertEqual(season_number_from_folder('Specials'), 0)
        self.assertEqual(season_number_from_folder('specials'), 0)

    def test_unrecognised_folder_has_no_number(self):
        self.assertIsNone(season_number_from_folder('Extras'))
        self.assertIsNone(season_number_from_folder(''))
        self.assertIsNone(season_number_from_folder(None))


class EpisodeKeyTests(unittest.TestCase):
    def test_tv_with_and_without_year_in_title(self):
        self.assertEqual(
            parse_episode_keys('A.B.C. - S02E03 - An Episode Title [WEBDL-1080p][DUS-Dragon DB].mkv'),
            (EpisodeKey(2, 3),),
        )
        self.assertEqual(
            parse_episode_keys('Another Series (2024) - S01E03 - A Third Episode [WEBDL-1080p][HONE].mkv'),
            (EpisodeKey(1, 3),),
        )

    def test_anime_absolute_number_is_not_a_second_episode(self):
        # "- S01E24 - 024 -" must be one episode, not S01E24 plus S01E024.
        name = ('Example Anime (2018) - S01E24 - 024 - Another Episode Title '
                '[Anime Dual-Audio Bluray-1080p][JA+EN][Chotab-Dragon DB].mkv')
        self.assertEqual(parse_episode_keys(name), (EpisodeKey(1, 24),))
        self.assertEqual(parse_absolute_number(name), 24)

    def test_high_season_and_absolute_number(self):
        name = 'Long Anime (2004) - S17E22 - 388 - AN EPISODE IN CAPS [Anime].mkv'
        self.assertEqual(parse_episode_keys(name), (EpisodeKey(17, 22),))
        self.assertEqual(parse_absolute_number(name), 388)

    def test_legacy_name_without_sonarr_tags(self):
        self.assertEqual(
            parse_episode_keys('Example Show - S01E15 - 1080p x265.mkv'),
            (EpisodeKey(1, 15),),
        )

    def test_multi_episode_files(self):
        self.assertEqual(
            parse_episode_keys('Show - S01E01E02 - Double [x264].mkv'),
            (EpisodeKey(1, 1), EpisodeKey(1, 2)),
        )
        self.assertEqual(
            parse_episode_keys('Show - S01E01-E02 - Double.mkv'),
            (EpisodeKey(1, 1), EpisodeKey(1, 2)),
        )

    def test_absolute_numbered_anime_without_a_code(self):
        # Un-renamed scene release: the season comes from the folder.
        name = '[SubsPlease] Maou no Musume wa Yasashi Sugiru!! - 07 (1080p) [5F530970].mkv'
        self.assertEqual(parse_episode_keys(name, season_hint=1), (EpisodeKey(1, 7),))
        # Without a season hint there is nothing to anchor to.
        self.assertEqual(parse_episode_keys(name), ())

    def test_movie_has_no_episode_identity(self):
        self.assertEqual(
            parse_episode_keys('A Movie (2025) Bluray-1080p [PSA-Dragon DB].mkv'),
            (),
        )

    def test_v2_release_tag_does_not_confuse_the_parser(self):
        name = ('Alpha - Bravo, Charlie of the Delta (2016) - S01E16 - 016 - '
                'The Greed of a Pig [v2 (anime) Bluray-1080p v2][EN+JA][SCY-Dragon DB].mkv')
        self.assertEqual(parse_episode_keys(name), (EpisodeKey(1, 16),))


class FileKindTests(unittest.TestCase):
    def test_media_and_ancillary_are_distinguished(self):
        self.assertTrue(is_media_file('ep.mkv'))
        self.assertTrue(is_media_file('ep.MP4'))
        self.assertFalse(is_media_file('poster.jpg'))
        # The library holds ~2x as many .nfo/.jpg as episodes, so these must
        # never count towards a safety threshold.
        self.assertTrue(is_ancillary_file('ep.nfo'))
        self.assertTrue(is_ancillary_file('ep.srt'))
        self.assertFalse(is_ancillary_file('ep.mkv'))


class PathSplitTests(unittest.TestCase):
    def test_series_season_file(self):
        self.assertEqual(
            split_library_path('Show (2024)/Season 01/ep.mkv'),
            ('Show (2024)', 'Season 01', 'ep.mkv'),
        )

    def test_movie_folder(self):
        self.assertEqual(
            split_library_path('Movie (2024)/movie.mkv'),
            ('Movie (2024)', None, 'movie.mkv'),
        )

    def test_extra_depth_is_preserved(self):
        # This is the shape the old single-episode bug produced.
        self.assertEqual(
            split_library_path('Show/Season 01/ep.mkv/ep.mkv'),
            ('Show', 'Season 01/ep.mkv', 'ep.mkv'),
        )

if __name__ == '__main__':
    unittest.main()
