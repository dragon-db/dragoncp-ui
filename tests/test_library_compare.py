#!/usr/bin/env python3
"""
One title, episode by episode — the comparison behind the Library detail view.

The rule these tests exist to hold: **a series is out of sync exactly when one
of its episodes is on the service and not here, or here as a different file.**
The case that broke the old list is pinned first: the service holds one file
for a season (the newest episode, after the media server cleaned up the rest)
and this disk holds the six before it. "Some file here" was true; the newest
episode was not here.

Pure functions, so nothing here needs a service, a database or a disk.
Synthetic names only.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import library_compare as cmp
from services.local_library import episode_keys, has_episode_code


def episode(season, number, file_id=0, title=None, absolute=None, monitored=True):
    return {
        'id': 1000 + season * 100 + number, 'seriesId': 219,
        'seasonNumber': season, 'episodeNumber': number,
        'title': title or f'Episode {number}', 'airDate': f'2026-09-{number:02d}',
        'hasFile': bool(file_id), 'episodeFileId': file_id, 'monitored': monitored,
        'absoluteEpisodeNumber': absolute,
    }


def service_file(file_id, season, name, size, quality='WEBDL-1080p', formats=()):
    return {
        'id': file_id, 'seriesId': 219, 'seasonNumber': season,
        'relativePath': f"Season {season:02d}/{name}", 'size': size,
        'quality': {'quality': {'name': quality}},
        'customFormats': [{'id': i, 'name': n} for i, n in enumerate(formats)],
        'customFormatScore': 100 if formats else 0,
    }


def local_file(season, name, size, folder=None):
    folder = folder or ('Specials' if season == 0 else f"Season {season:02d}")
    return {
        'name': name, 'relative_path': f"{folder}/{name}", 'folder': folder,
        'folder_season': season, 'size': size,
        'keys': list(episode_keys(name, season)), 'coded': has_episode_code(name),
    }


def local(*files, folders=None):
    season_folders = {}
    for entry in files:
        season_folders.setdefault(entry['folder_season'], [entry['folder']])
    if folders:
        season_folders.update(folders)
    return {'path': '/library/tv/Example Show (2021)', 'folder': 'Example Show (2021)',
            'media_type': 'tvshows', 'season_folders': season_folders,
            'files': list(files), 'loose': []}


def ep_name(season, number, extra='WEBDL-1080p'):
    return f"Example Show (2021) - S{season:02d}E{number:02d} - Episode {number} [{extra}].mkv"


def by_code(result):
    return {row['code']: row for season in result['seasons'] for row in season['episodes']}


class EpisodeStateTests(unittest.TestCase):

    def test_every_state_in_one_season(self):
        episodes = [episode(1, 1, 11), episode(1, 2, 12), episode(1, 3, 13),
                    episode(1, 4), episode(1, 5)]
        files = [service_file(11, 1, ep_name(1, 1), 100),
                 service_file(12, 1, ep_name(1, 2, 'Bluray-1080p'), 200),
                 service_file(13, 1, ep_name(1, 3), 300)]
        here = local(local_file(1, ep_name(1, 1), 100),
                     local_file(1, ep_name(1, 2), 150),
                     local_file(1, ep_name(1, 4), 400))

        result = cmp.compare_series(episodes, files, here)
        rows = by_code(result)
        self.assertEqual(rows['S01E01']['state'], cmp.IN_SYNC)
        self.assertEqual(rows['S01E02']['state'], cmp.DIFFERENT,
                         'same episode, different size: an upgrade over there')
        self.assertEqual(rows['S01E03']['state'], cmp.MISSING_HERE)
        self.assertEqual(rows['S01E04']['state'], cmp.ONLY_HERE)
        self.assertEqual(rows['S01E05']['state'], cmp.NOT_DOWNLOADED)
        self.assertEqual(result['state'], cmp.OUT_OF_SYNC)
        self.assertEqual(result['counts'], {
            cmp.MISSING_HERE: 1, cmp.DIFFERENT: 1, cmp.NESTED: 0, cmp.IN_SYNC: 1,
            cmp.ONLY_HERE: 1, cmp.NOT_DOWNLOADED: 1})

    def test_the_service_file_details_are_carried(self):
        episodes = [episode(1, 8, 18, title='Episode Eight')]
        files = [service_file(18, 1, ep_name(1, 8), 800, formats=('WEB Tier 01',))]
        result = cmp.compare_series(episodes, files, local())
        row = by_code(result)['S01E08']
        self.assertEqual(row['title'], 'Episode Eight')
        self.assertEqual(row['air_date'], '2026-09-08')
        self.assertEqual(row['service_file']['quality'], 'WEBDL-1080p')
        self.assertEqual(row['service_file']['custom_formats'], ['WEB Tier 01'])
        self.assertEqual(row['service_file']['size'], 800)
        self.assertIsNone(row['local_file'])

    def test_a_renamed_file_of_the_same_size_is_in_sync(self):
        """Sonarr renames without changing contents; the size decides, not the name."""
        episodes = [episode(1, 1, 11)]
        files = [service_file(11, 1, ep_name(1, 1, 'WEBDL-1080p][NEW'), 100)]
        here = local(local_file(1, ep_name(1, 1, 'WEBDL-1080p][OLD'), 100))
        self.assertEqual(by_code(cmp.compare_series(episodes, files, here))['S01E01']['state'],
                         cmp.IN_SYNC)


class TheRealCaseTests(unittest.TestCase):
    """Sonarr holds E08 only; this disk holds E01 to E07."""

    def setUp(self):
        self.episodes = [episode(1, n, 18 if n == 8 else 0,
                                 title='Episode Eight' if n == 8 else None)
                         for n in range(1, 9)]
        self.files = [service_file(18, 1, ep_name(1, 8), 800)]
        self.here = local(*[local_file(1, ep_name(1, n), 100 + n) for n in range(1, 8)])
        self.result = cmp.compare_series(self.episodes, self.files, self.here)

    def test_it_is_out_of_sync(self):
        self.assertEqual(self.result['state'], cmp.OUT_OF_SYNC)
        self.assertEqual(by_code(self.result)['S01E08']['state'], cmp.MISSING_HERE)
        self.assertEqual(self.result['counts'][cmp.ONLY_HERE], 7,
                         'the seven kept here are neutral, not a problem')

    def test_the_sentence_names_the_episode(self):
        self.assertIn('1 episode on Sonarr is not here yet', self.result['summary'])
        self.assertIn('S01E08 “Episode Eight”', self.result['summary'])

    def test_the_title_sync_is_not_offered_and_says_why(self):
        """A whole-folder sync would remove E01–E07; the safety check stops it."""
        sync = self.result['sync']
        self.assertFalse(sync['offered'])
        self.assertIn('kept only here', sync['reason'])
        self.assertIn('Explore', sync['reason'])

    def test_the_season_knows_its_folder_on_both_sides(self):
        season = self.result['seasons'][0]
        self.assertEqual(season['service_folder'], 'Season 01')
        self.assertEqual(season['folder_here'], 'Season 01')
        self.assertEqual(season['state'], cmp.OUT_OF_SYNC)


class CleanupAndMultiEpisodeTests(unittest.TestCase):

    def test_kept_only_here_after_a_cleanup_is_not_a_problem(self):
        """Sonarr kept E07 — the same file as here — and dropped E01–E06."""
        episodes = [episode(1, n, 17 if n == 7 else 0) for n in range(1, 8)]
        files = [service_file(17, 1, ep_name(1, 7), 107)]
        here = local(*[local_file(1, ep_name(1, n), 100 + n) for n in range(1, 8)])
        result = cmp.compare_series(episodes, files, here)
        self.assertEqual(result['state'], cmp.KEPT_HERE)
        self.assertEqual(result['counts'][cmp.ONLY_HERE], 6)
        self.assertIn('kept only here', result['summary'])
        self.assertFalse(result['sync']['offered'])

    def test_a_double_episode_file_covers_both_episodes(self):
        episodes = [episode(1, 1, 10), episode(1, 2, 10)]
        name = "Example Show (2021) - S01E01E02 - Episode 1 + Episode 2 [WEBDL-1080p].mkv"
        files = [service_file(10, 1, name, 500)]
        here = local(local_file(1, name, 500))
        result = cmp.compare_series(episodes, files, here)
        rows = by_code(result)
        self.assertEqual(rows['S01E01']['state'], cmp.IN_SYNC)
        self.assertEqual(rows['S01E02']['state'], cmp.IN_SYNC)
        self.assertEqual(rows['S01E01']['local_file']['covers'], ['S01E01', 'S01E02'])
        self.assertEqual(result['state'], cmp.TITLE_IN_SYNC)
        self.assertEqual(result['seasons'][0]['episodes_here'], 2)

    def test_a_double_episode_here_against_two_files_there(self):
        """Here one file holds E03 and E04; there they are two. Both read as here."""
        episodes = [episode(1, 3, 13), episode(1, 4, 14)]
        files = [service_file(13, 1, ep_name(1, 3), 300), service_file(14, 1, ep_name(1, 4), 400)]
        here = local(local_file(1, "Example Show (2021) - S01E03-E04 - Two Parts.mkv", 700))
        rows = by_code(cmp.compare_series(episodes, files, here))
        self.assertEqual(rows['S01E03']['state'], cmp.DIFFERENT)
        self.assertEqual(rows['S01E04']['state'], cmp.DIFFERENT)


class SpecialsTests(unittest.TestCase):

    def test_specials_are_compared_but_never_decide_the_verdict(self):
        episodes = [episode(0, 1, 1), episode(1, 1, 11)]
        files = [service_file(1, 0, "Example Show (2021) - S00E01 - A Special.mkv", 50),
                 service_file(11, 1, ep_name(1, 1), 100)]
        here = local(local_file(1, ep_name(1, 1), 100))
        result = cmp.compare_series(episodes, files, here)
        self.assertEqual(result['state'], cmp.TITLE_IN_SYNC,
                         'a special missing here must not make the series out of sync')
        self.assertEqual(result['counts'][cmp.MISSING_HERE], 0)
        specials = next(s for s in result['seasons'] if s['specials'])
        self.assertFalse(specials['counts_towards_state'])
        self.assertEqual(specials['counts'][cmp.MISSING_HERE], 1, 'still shown')

    def test_a_series_with_files_only_in_specials_here_reads_as_not_here(self):
        episodes = [episode(0, 1), episode(1, 1, 11)]
        files = [service_file(11, 1, ep_name(1, 1), 100)]
        here = local(local_file(0, "Example Show (2021) - S00E01 - A Special.mkv", 50))
        self.assertEqual(cmp.compare_series(episodes, files, here)['state'], cmp.NEVER)


class EdgeTests(unittest.TestCase):

    def test_nothing_here_at_all_is_never(self):
        episodes = [episode(1, 1, 11), episode(1, 2, 12)]
        files = [service_file(11, 1, ep_name(1, 1), 100), service_file(12, 1, ep_name(1, 2), 200)]
        result = cmp.compare_series(episodes, files, None)
        self.assertEqual(result['state'], cmp.NEVER)
        self.assertTrue(result['sync']['offered'], 'nothing here to lose')
        self.assertEqual(result['sync']['seasons'], [1])

    def test_missing_episodes_with_nothing_kept_offers_the_sync(self):
        episodes = [episode(1, n, 10 + n) for n in range(1, 4)]
        files = [service_file(10 + n, 1, ep_name(1, n), 100 * n) for n in range(1, 4)]
        here = local(local_file(1, ep_name(1, 1), 100))
        result = cmp.compare_series(episodes, files, here)
        self.assertEqual(result['state'], cmp.OUT_OF_SYNC)
        self.assertTrue(result['sync']['offered'])
        self.assertIn('2 episodes on Sonarr are not here yet', result['summary'])

    def test_a_different_file_alone_points_to_explore(self):
        """The title's Sync fetches short seasons; a same-count upgrade is not one."""
        episodes = [episode(1, 1, 11)]
        files = [service_file(11, 1, ep_name(1, 1, 'Bluray-2160p'), 900)]
        here = local(local_file(1, ep_name(1, 1), 100))
        result = cmp.compare_series(episodes, files, here)
        self.assertEqual(result['state'], cmp.OUT_OF_SYNC)
        self.assertFalse(result['sync']['offered'])
        self.assertIn('Explore', result['sync']['reason'])

    def test_a_file_with_no_episode_code_is_kept_and_makes_the_sync_unsafe(self):
        episodes = [episode(1, 1, 11), episode(1, 2, 12)]
        files = [service_file(11, 1, ep_name(1, 1), 100), service_file(12, 1, ep_name(1, 2), 200)]
        here = local(local_file(1, ep_name(1, 1), 100),
                     local_file(1, "Example Show behind the scenes.mkv", 30))
        result = cmp.compare_series(episodes, files, here)
        season = result['seasons'][0]
        self.assertEqual(len(season['unidentified_here']), 1)
        self.assertEqual(season['local_only_files'], 1)
        self.assertFalse(result['sync']['offered'])

    def test_absolute_numbered_anime_is_matched_through_sonarr(self):
        """"- 25 -" in Season 02 is S02E01 when Sonarr says episode 25 is."""
        episodes = [episode(2, 1, 21, absolute=25)]
        name = "[Group] Example Anime - 25 (1080p) [5F530970].mkv"
        files = [service_file(21, 2, name, 250)]
        here = local(local_file(2, name, 250))
        rows = by_code(cmp.compare_series(episodes, files, here))
        self.assertEqual(rows['S02E01']['state'], cmp.IN_SYNC)

    def test_an_episode_here_that_sonarr_does_not_list_is_only_here(self):
        episodes = [episode(1, 1, 11)]
        files = [service_file(11, 1, ep_name(1, 1), 100)]
        here = local(local_file(1, ep_name(1, 1), 100), local_file(1, ep_name(1, 9), 900))
        rows = by_code(cmp.compare_series(episodes, files, here))
        self.assertEqual(rows['S01E09']['state'], cmp.ONLY_HERE)
        self.assertIsNone(rows['S01E09']['title'])


def nested_file(season, name, size, folder=None):
    """`Season 01/ep.mkv/ep.mkv` — what the old single-episode download left."""
    entry = local_file(season, name, size, folder)
    entry['relative_path'] = f"{entry['folder']}/{name}/{name}"
    entry['nested'] = True
    return entry


class NestedTests(unittest.TestCase):
    """A file one folder too deep: here, but not where a media server looks.

    Explore calls it Nested; this view has to say the same, not "Not here".
    """

    def test_an_episode_only_a_nested_copy_holds_is_nested_not_missing(self):
        episodes = [episode(1, 37, 137), episode(1, 38, 138)]
        files = [service_file(138, 1, ep_name(1, 38), 2000)]
        here = local(local_file(1, ep_name(1, 37), 1900), nested_file(1, ep_name(1, 38), 2000))

        result = cmp.compare_series(episodes, files, here)
        row = by_code(result)['S01E38']
        self.assertEqual(row['state'], cmp.NESTED)
        self.assertTrue(row['local_file']['nested'])
        self.assertTrue(row['local_file']['relative_path'].endswith(
            f"{ep_name(1, 38)}/{ep_name(1, 38)}"))
        self.assertEqual(result['state'], cmp.NEEDS_REPAIR)
        self.assertEqual(result['nested_files'], 1)
        self.assertIn('S01E38', result['summary'])
        self.assertIn('nested folder', result['summary'])
        self.assertIn('Explore', result['summary'])
        self.assertEqual(result['seasons'][0]['state'], cmp.NEEDS_REPAIR)
        self.assertFalse(result['sync']['offered'])

    def test_a_copy_in_place_wins_and_the_stranded_one_still_counts(self):
        episodes = [episode(1, 1, 11)]
        files = [service_file(11, 1, ep_name(1, 1), 100)]
        here = local(nested_file(1, ep_name(1, 1), 100), local_file(1, ep_name(1, 1), 100))

        result = cmp.compare_series(episodes, files, here)
        row = by_code(result)['S01E01']
        self.assertEqual(row['state'], cmp.IN_SYNC)
        self.assertFalse(row['local_file']['nested'])
        self.assertEqual(result['state'], cmp.NEEDS_REPAIR)
        self.assertIn('1 file here is inside a nested folder', result['summary'])

    def test_something_missing_too_is_still_out_of_sync(self):
        episodes = [episode(1, 1, 11), episode(1, 2, 12)]
        files = [service_file(11, 1, ep_name(1, 1), 100),
                 service_file(12, 1, ep_name(1, 2), 200)]
        here = local(nested_file(1, ep_name(1, 1), 100))

        result = cmp.compare_series(episodes, files, here)
        self.assertEqual(result['state'], cmp.OUT_OF_SYNC)
        self.assertIn('S01E02', result['summary'])
        self.assertIn('nested folder', result['summary'])
        self.assertFalse(result['sync']['offered'])
        self.assertIn('nested folder', result['sync']['reason'])

    def test_a_season_with_a_nested_file_is_not_counted_twice(self):
        episodes = [episode(1, 1, 11)]
        files = [service_file(11, 1, ep_name(1, 1), 100)]
        here = local(nested_file(1, ep_name(1, 1), 100))
        season = cmp.compare_series(episodes, files, here)['seasons'][0]
        self.assertEqual(season['episodes_here'], 0, 'what a media server can see')
        self.assertEqual(season['nested_here'], [here['files'][0]['relative_path']])


class MovieTests(unittest.TestCase):

    def movie(self, has_file=True, size=4000):
        return {'id': 5, 'tmdbId': 900002, 'title': 'Example Film', 'year': 2024,
                'hasFile': has_file,
                'movieFile': {'id': 9, 'relativePath': 'Example Film (2024).mkv', 'size': size,
                              'quality': {'quality': {'name': 'WEBDL-1080p'}}}
                if has_file else None}

    def here(self, *sizes):
        return {'loose': [{'name': f'Example Film (2024) v{i}.mkv',
                           'relative_path': f'Example Film (2024) v{i}.mkv', 'size': s}
                          for i, s in enumerate(sizes)]}

    def test_every_state(self):
        cases = [
            (self.movie(), self.here(4000), cmp.IN_SYNC, cmp.TITLE_IN_SYNC),
            (self.movie(), self.here(3000), cmp.DIFFERENT, cmp.OUT_OF_SYNC),
            (self.movie(), None, cmp.MISSING_HERE, cmp.NEVER),
            (self.movie(has_file=False), self.here(3000), cmp.ONLY_HERE, cmp.KEPT_HERE),
            (self.movie(has_file=False), None, cmp.NOT_DOWNLOADED, cmp.NO_FILES),
        ]
        for movie, here, film_state, title_state in cases:
            with self.subTest(film_state):
                result = cmp.compare_movie(movie, here)
                self.assertEqual(result['movie']['state'], film_state)
                self.assertEqual(result['state'], title_state)

    def test_the_matching_file_wins_among_several(self):
        result = cmp.compare_movie(self.movie(size=4000), self.here(100, 4000))
        self.assertEqual(result['movie']['state'], cmp.IN_SYNC)
        self.assertEqual(len(result['movie']['other_files_here']), 1)

    def test_a_film_only_in_a_nested_folder_needs_repair(self):
        stranded = {'loose': [], 'nested_loose': [
            {'name': 'Example Film (2024).mkv',
             'relative_path': 'Example Film (2024).mkv/Example Film (2024).mkv', 'size': 4000}]}
        result = cmp.compare_movie(self.movie(size=4000), stranded)
        self.assertEqual(result['movie']['state'], cmp.NESTED)
        self.assertEqual(result['state'], cmp.NEEDS_REPAIR)
        self.assertFalse(result['sync']['offered'], 'copying it again would not fix it')
        self.assertIn('nested folder', result['summary'])

    def test_a_film_in_place_with_a_stranded_second_copy_needs_repair(self):
        here = self.here(4000)
        here['nested_loose'] = [{'name': 'old.mkv', 'relative_path': 'Extras/old.mkv',
                                 'size': 3000}]
        result = cmp.compare_movie(self.movie(size=4000), here)
        self.assertEqual(result['movie']['state'], cmp.IN_SYNC)
        self.assertEqual(result['state'], cmp.NEEDS_REPAIR)
        self.assertIn('second copy', result['summary'])

    def test_only_a_film_not_here_offers_the_sync(self):
        self.assertTrue(cmp.compare_movie(self.movie(), None)['sync']['offered'])
        different = cmp.compare_movie(self.movie(), self.here(3000))
        self.assertFalse(different['sync']['offered'])
        self.assertIn('Explore', different['sync']['reason'])



class SizeMatchTests(unittest.TestCase):
    """The Library list's size check: are the service's files among those here?"""

    def test_one_file_there_not_among_the_files_here(self):
        self.assertFalse(cmp.holds_files_of_size([101, 102, 103, 104, 105, 106, 107], 1, 808))

    def test_one_file_there_that_is_here(self):
        self.assertTrue(cmp.holds_files_of_size([101, 102, 103, 104, 105, 106, 107], 1, 107))

    def test_two_episodes_in_one_file(self):
        self.assertTrue(cmp.holds_files_of_size([101, 102, 300], 2, 300))

    def test_two_and_three_files(self):
        self.assertTrue(cmp.holds_files_of_size([101, 102, 103], 2, 203))
        self.assertTrue(cmp.holds_files_of_size([101, 102, 103, 104], 3, 101 + 102 + 104))
        self.assertFalse(cmp.holds_files_of_size([101, 102, 103, 104], 3, 1))

    def test_a_file_is_used_once(self):
        self.assertTrue(cmp.holds_files_of_size([100, 100], 2, 200))
        self.assertFalse(cmp.holds_files_of_size([100], 2, 200))

    def test_it_says_when_it_cannot_tell(self):
        self.assertIsNone(cmp.holds_files_of_size([101], 4, 101), 'past the limit')
        self.assertIsNone(cmp.holds_files_of_size([], 1, 5), 'nothing here to size')
        self.assertIsNone(cmp.holds_files_of_size([1, 2], 1, 0), 'no size there')

if __name__ == '__main__':
    unittest.main()
