#!/usr/bin/env python3
"""
Planning and safety — what a sync will actually do, before it does it.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.explore.compare import compare_library
from services.explore.inventory import StaticInventory
from services.explore.planner import (
    FETCH, REMOVE, SUPERSEDE,
    evaluate, plan_download, plan_replace, plan_season_sync, plan_seasons_sync,
    plan_series_sync,
)

GB = 1024 ** 3
REMOTE_ROOT = '/remote/tv'
LOCAL_ROOT = '/local/tv'


def ep(series, folder, code, quality='WEBDL-1080p', group='HONE'):
    return f"{series}/{folder}/{series} - {code} - Title [{quality}][{group}-Dragon DB].mkv"


def diff_for(remote_rows, local_rows, media_type='tvshows'):
    remote = StaticInventory(remote_rows, side='remote').read(media_type, REMOTE_ROOT)
    local = StaticInventory(local_rows, side='local').read(media_type, LOCAL_ROOT)
    return compare_library(media_type, remote, local)


class SeasonSyncTests(unittest.TestCase):
    def test_new_episodes_are_fetched_and_nothing_is_removed(self):
        # Scenario A: remote went 5 -> 10.
        remote = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 11)]
        local = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 6)]
        series = diff_for(remote, local).find('Show')

        plan = plan_season_sync('tvshows', series, series.seasons[0], REMOTE_ROOT, LOCAL_ROOT)
        evaluate(plan, series.seasons[0], local_media_total=5)

        self.assertEqual(len(plan.fetches), 5)
        self.assertEqual(len(plan.supersedes), 0)
        self.assertEqual(len(plan.removals), 0)
        self.assertTrue(plan.safe)
        self.assertEqual(plan.incoming_bytes, 10 * GB)
        self.assertIn('downloads 5', plan.verdict())
        self.assertIn('removes nothing', plan.verdict())
        # rsync gets bare filenames relative to the season folder.
        self.assertTrue(all('/' not in rel for rel in plan.transfer_rels))

    def test_an_upgrade_backs_up_the_old_file_first(self):
        plan_series = diff_for(
            [(ep('Show', 'Season 01', 'S01E23', 'Bluray-2160p', 'NEW'), 8 * GB, 200)],
            [(ep('Show', 'Season 01', 'S01E23', 'WEBDL-1080p', 'OLD'), 2 * GB, 100)],
        ).find('Show')

        plan = plan_season_sync('tvshows', plan_series, plan_series.seasons[0],
                                REMOTE_ROOT, LOCAL_ROOT)

        self.assertEqual(len(plan.supersedes), 1)
        action = plan.supersedes[0]
        self.assertEqual(action.action, SUPERSEDE)
        self.assertIn('NEW', action.rel)          # what arrives
        self.assertIn('OLD', action.local_rel)    # what is backed up
        self.assertEqual(plan.backup_rels, [action.local_rel])

    def test_remote_shrinking_is_stopped_for_review(self):
        # Scenario B: remote has 2, local has 10.
        remote = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 3)]
        local = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 11)]
        series = diff_for(remote, local).find('Show')

        plan = plan_season_sync('tvshows', series, series.seasons[0], REMOTE_ROOT, LOCAL_ROOT)
        evaluate(plan, series.seasons[0], local_media_total=10)

        self.assertEqual(len(plan.removals), 8)
        self.assertEqual(len(plan.fetches), 0)
        self.assertFalse(plan.safe)

        failed = {c.id for c in plan.checks if not c.passed}
        self.assertIn('removals_vs_arrivals', failed)
        self.assertIn('removal_share', failed)
        self.assertIn('remote_shrunk', failed)
        self.assertIn('removes 8', plan.verdict())

    def test_download_and_replace_only_mode_leaves_extras_alone(self):
        remote = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 3)]
        local = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 11)]
        series = diff_for(remote, local).find('Show')

        plan = plan_season_sync('tvshows', series, series.seasons[0],
                                REMOTE_ROOT, LOCAL_ROOT, include_removals=False)
        evaluate(plan, series.seasons[0], local_media_total=10)

        self.assertEqual(len(plan.removals), 0)
        self.assertTrue(plan.safe)
        self.assertTrue(plan.is_empty)

    def test_new_files_go_into_the_existing_local_season_folder(self):
        # Local spells it "Season 1"; a fetch must not create "Season 01"
        # alongside it and split the season across two folders.
        series = diff_for(
            [(ep('Show', 'Season 01', 'S01E02'), 2 * GB, 100),
             (ep('Show', 'Season 01', 'S01E01'), 2 * GB, 100)],
            [(ep('Show', 'Season 1', 'S01E01'), 2 * GB, 100)],
        ).find('Show')

        plan = plan_season_sync('tvshows', series, series.seasons[0], REMOTE_ROOT, LOCAL_ROOT)
        self.assertTrue(plan.dest_root.endswith('Season 1'))
        self.assertTrue(plan.source_root.endswith('Season 01'))


class SeriesSyncTests(unittest.TestCase):
    def test_one_plan_grouped_by_season_with_removals_first(self):
        remote = (
            [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 10) for i in range(1, 6)]
            + [(ep('Show', 'Season 02', 'S02E01'), 2 * GB, 99)]
        )
        local = (
            [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 10) for i in range(1, 3)]
            + [(ep('Show', 'Season 02', f'S02E{i:02d}'), 2 * GB, 99) for i in range(1, 6)]
        )
        series = diff_for(remote, local).find('Show')

        plan = plan_series_sync('tvshows', series, REMOTE_ROOT, LOCAL_ROOT)
        evaluate(plan, series, local_media_total=7)

        self.assertEqual(len(plan.fetches), 3)   # S01E03..05
        self.assertEqual(len(plan.removals), 4)  # S02E02..05

        groups = plan.grouped()
        # The season that loses files is presented first.
        self.assertEqual(groups[0]['season_label'], 'Season 02')
        self.assertEqual(groups[0]['remove'], 4)
        self.assertEqual(groups[1]['season_label'], 'Season 01')
        self.assertEqual(groups[1]['fetch'], 3)
        # Each season is its own transfer, rooted at its own folder, so the
        # file list is bare names rather than season-prefixed paths.
        self.assertEqual([u.season_label for u in plan.units], ['Season 01', 'Season 02'],
                         'a season that only loses files still needs a run to back them up')
        self.assertTrue(all('/' not in rel for rel in plan.transfer_rels))


class DownloadTests(unittest.TestCase):
    def test_download_only_takes_the_selected_missing_episodes(self):
        remote = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 6)]
        series = diff_for(remote, []).find('Show')

        plan = plan_download('tvshows', series, series.seasons[0],
                             REMOTE_ROOT, LOCAL_ROOT, codes=['S01E02', 'S01E04'])

        self.assertEqual(len(plan.actions), 2)
        self.assertEqual({a.code for a in plan.actions}, {'S01E02', 'S01E04'})
        self.assertTrue(all(a.action == FETCH for a in plan.actions))
        self.assertFalse(plan.is_destructive)

    def test_download_will_not_replace_an_upgraded_episode(self):
        # An upgrade needs the local file moved aside; that is the replace
        # operation, and download must refuse to do it silently.
        series = diff_for(
            [(ep('Show', 'Season 01', 'S01E01', 'Bluray-2160p', 'NEW'), 8 * GB, 200)],
            [(ep('Show', 'Season 01', 'S01E01', 'WEBDL-1080p', 'OLD'), 2 * GB, 100)],
        ).find('Show')

        plan = plan_download('tvshows', series, series.seasons[0],
                             REMOTE_ROOT, LOCAL_ROOT, codes=['S01E01'])
        self.assertTrue(plan.is_empty)


class ReplaceTests(unittest.TestCase):
    def test_replace_touches_only_the_selected_episode(self):
        remote = [(ep('Show', 'Season 01', 'S01E23', 'Bluray-2160p', 'NEW'), 8 * GB, 200)]
        local = [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 24)]
        local[-1] = (ep('Show', 'Season 01', 'S01E23', 'WEBDL-1080p', 'OLD'), 2 * GB, 100)
        series = diff_for(remote, local).find('Show')

        plan = plan_replace('tvshows', series, series.seasons[0],
                            REMOTE_ROOT, LOCAL_ROOT, codes=['S01E23'])
        evaluate(plan, series.seasons[0], local_media_total=23)

        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].action, SUPERSEDE)
        self.assertEqual(len(plan.removals), 0)
        # The other 22 local episodes are untouched — the whole point of this
        # operation, versus a season sync which would list them for removal.
        self.assertTrue(plan.safe)


class FreeSpaceTests(unittest.TestCase):
    def test_free_space_check_runs_against_a_real_directory(self):
        series = diff_for(
            [(ep('Show', 'Season 01', 'S01E01'), 2 * GB, 100)], []
        ).find('Show')
        plan = plan_season_sync('tvshows', series, series.seasons[0], REMOTE_ROOT, '/tmp')
        evaluate(plan, series.seasons[0], local_media_total=0)
        space = [c for c in plan.checks if c.id == 'free_space']
        self.assertEqual(len(space), 1)




class SelectedSeasonsTests(unittest.TestCase):
    """Ticking seasons in the list produces ONE plan, not one plan per season."""

    def setUp(self):
        remote = (
            [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 4)]
            + [(ep('Show', 'Season 02', f'S02E{i:02d}'), 2 * GB, 100) for i in range(1, 4)]
            + [(ep('Show', 'Season 03', f'S03E{i:02d}'), 2 * GB, 100) for i in range(1, 4)]
        )
        local = [(ep('Show', 'Season 01', 'S01E01'), 2 * GB, 100)]
        self.series = diff_for(remote, local).find('Show')
        self.by_name = {s.display_name: s for s in self.series.seasons}

    def test_only_the_ticked_seasons_are_in_the_plan(self):
        picked = [self.by_name['Season 01'], self.by_name['Season 03']]
        plan = plan_seasons_sync('tvshows', self.series, picked, REMOTE_ROOT, LOCAL_ROOT)

        seasons_in_plan = {a.season_label for a in plan.actions}
        self.assertEqual(seasons_in_plan, {'Season 01', 'Season 03'})
        self.assertEqual(len(plan.fetches), 5, 'two from S01, three from S03')

    def test_each_ticked_season_becomes_its_own_transfer(self):
        picked = [self.by_name['Season 01'], self.by_name['Season 03']]
        plan = plan_seasons_sync('tvshows', self.series, picked, REMOTE_ROOT, LOCAL_ROOT)

        # The plan's own roots describe its scope; the work happens per season.
        self.assertTrue(plan.source_root.endswith('/Show'))
        self.assertEqual([u.season_label for u in plan.units], ['Season 01', 'Season 03'])
        for unit in plan.units:
            self.assertTrue(unit.dest_root.endswith(unit.season_label))
            self.assertTrue(all('/' not in rel for rel in unit.transfer_rels))

    def test_one_ticked_season_still_produces_one_plan(self):
        plan = plan_seasons_sync(
            'tvshows', self.series, [self.by_name['Season 02']], REMOTE_ROOT, LOCAL_ROOT)
        self.assertEqual(len(plan.fetches), 3)
        self.assertEqual({a.season_label for a in plan.actions}, {'Season 02'})


class ReplaceAnInSyncFileTests(unittest.TestCase):
    """Any file can be ticked, so replace has to mean something for all of them."""

    def setUp(self):
        row = [(ep('Show', 'Season 01', 'S01E01'), 2 * GB, 100)]
        self.series = diff_for(row, row).find('Show')
        self.season = self.series.seasons[0]

    def test_replacing_a_matching_file_backs_it_up_and_fetches_it_again(self):
        code = self.season.episodes[0].code
        plan = plan_replace('tvshows', self.series, self.season,
                            REMOTE_ROOT, LOCAL_ROOT, [code])

        self.assertEqual(len(plan.supersedes), 1)
        self.assertEqual(len(plan.removals), 0, 'a re-fetch never removes anything')
        self.assertTrue(plan.supersedes[0].local_rel, 'the local copy is preserved first')
        self.assertIn('already matches', plan.supersedes[0].reason)

    def test_downloading_a_matching_file_is_still_a_no_op(self):
        # download is defined as "never overwrites"; that has not changed.
        code = self.season.episodes[0].code
        plan = plan_download('tvshows', self.series, self.season,
                             REMOTE_ROOT, LOCAL_ROOT, [code])
        self.assertTrue(plan.is_empty)

    def test_a_season_sync_never_re_fetches_a_matching_file(self):
        plan = plan_season_sync('tvshows', self.series, self.season, REMOTE_ROOT, LOCAL_ROOT)
        self.assertTrue(plan.is_empty, 'in-sync files are only re-fetched when asked for')

class SeasonFanOutTests(unittest.TestCase):
    """
    A transfer is a season folder everywhere else in the app — it is what the
    queue locks on and what a webhook produces. So a plan spanning seasons is a
    plan for several transfers, one each, not one big one.
    """

    def setUp(self):
        remote = (
            [(ep('Show', 'Season 01', f'S01E{i:02d}'), 2 * GB, 100) for i in range(1, 3)]
            + [(ep('Show', 'Season 02', f'S02E{i:02d}'), 2 * GB, 100) for i in range(1, 3)]
            + [(ep('Show', 'Season 03', f'S03E{i:02d}'), 2 * GB, 100) for i in range(1, 3)]
        )
        self.series = diff_for(remote, []).find('Show')

    def test_a_series_sync_produces_one_unit_per_season(self):
        plan = plan_series_sync('tvshows', self.series, REMOTE_ROOT, LOCAL_ROOT)
        self.assertEqual(len(plan.units), 3)
        self.assertEqual([u.season_label for u in plan.units],
                         ['Season 01', 'Season 02', 'Season 03'])

    def test_each_unit_is_rooted_at_its_own_season_on_both_sides(self):
        plan = plan_series_sync('tvshows', self.series, REMOTE_ROOT, LOCAL_ROOT)
        for unit in plan.units:
            self.assertTrue(unit.source_root.endswith(unit.season_label))
            self.assertTrue(unit.dest_root.endswith(unit.season_label))
            self.assertTrue(all('/' not in rel for rel in unit.transfer_rels),
                            'bare filenames, so no path can recreate a folder')

    def test_the_plan_is_still_reviewed_as_one_decision(self):
        plan = plan_series_sync('tvshows', self.series, REMOTE_ROOT, LOCAL_ROOT)
        self.assertEqual(len(plan.fetches), 6, 'every season in one verdict')
        self.assertEqual({g['season_label'] for g in plan.grouped()},
                         {'Season 01', 'Season 02', 'Season 03'})

    def test_a_season_with_nothing_to_do_gets_no_transfer(self):
        # Season 02 already matches, so it should not produce a run at all.
        remote = (
            [(ep('Show', 'Season 01', 'S01E01'), 2 * GB, 100)]
            + [(ep('Show', 'Season 02', 'S02E01'), 2 * GB, 100)]
        )
        local = [(ep('Show', 'Season 02', 'S02E01'), 2 * GB, 100)]
        series = diff_for(remote, local).find('Show')

        plan = plan_series_sync('tvshows', series, REMOTE_ROOT, LOCAL_ROOT)
        self.assertEqual([u.season_label for u in plan.units], ['Season 01'])

    def test_ticked_seasons_fan_out_the_same_way(self):
        by_name = {s.display_name: s for s in self.series.seasons}
        plan = plan_seasons_sync('tvshows', self.series,
                                 [by_name['Season 01'], by_name['Season 03']],
                                 REMOTE_ROOT, LOCAL_ROOT)
        self.assertEqual([u.season_label for u in plan.units], ['Season 01', 'Season 03'])

    def test_a_single_season_plan_is_one_unit(self):
        plan = plan_season_sync('tvshows', self.series, self.series.seasons[0],
                                REMOTE_ROOT, LOCAL_ROOT)
        self.assertEqual(len(plan.units), 1)
        self.assertEqual(plan.units[0].source_root, plan.source_root)


class SeasonSpellingTests(unittest.TestCase):
    """
    "Season 01" remotely and "Season 1" locally is the same season. Because each
    unit is rooted at its own folder on each side, this needs no special case —
    the run reads from one and writes into the other.
    """

    def _series(self, remote_folder, local_folder):
        return diff_for(
            [(ep('Show', remote_folder, 'S01E01'), 2 * GB, 100)],
            [(ep('Show', local_folder, 'S01E02'), 2 * GB, 100)],
        ).find('Show')

    def test_a_series_sync_reads_the_remote_name_and_writes_the_local_one(self):
        series = self._series('Season 01', 'Season 1')
        plan = plan_series_sync('tvshows', series, REMOTE_ROOT, LOCAL_ROOT)

        self.assertEqual(len(plan.units), 1)
        unit = plan.units[0]
        self.assertTrue(unit.source_root.endswith('Season 01'), 'reads the remote name')
        self.assertTrue(unit.dest_root.endswith('Season 1'), 'writes into the local one')
        self.assertTrue(all('/' not in rel for rel in unit.transfer_rels),
                        'nothing in the list can recreate the remote folder name')

    def test_the_season_scoped_sync_behaves_identically(self):
        series = self._series('Season 01', 'Season 1')
        plan = plan_season_sync('tvshows', series, series.seasons[0], REMOTE_ROOT, LOCAL_ROOT)
        self.assertTrue(plan.source_root.endswith('Season 01'))
        self.assertTrue(plan.dest_root.endswith('Season 1'))

if __name__ == '__main__':
    unittest.main()
