#!/usr/bin/env python3
"""
Reading rsync's dry run.

The itemised change string is the whole signal, and getting it wrong is
dangerous in a specific way: mistaking a replacement for a new arrival would
tell an operator nothing is at risk when a local file is about to be overwritten.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.explore import dryrun


class ClassifyTests(unittest.TestCase):
    def test_all_plus_signs_mean_a_new_file(self):
        self.assertEqual(dryrun.classify('>f+++++++++'), dryrun.NEW)

    def test_a_differing_attribute_means_the_local_file_is_overwritten(self):
        self.assertEqual(dryrun.classify('>f..t......'), dryrun.REPLACED)
        self.assertEqual(dryrun.classify('>f.st......'), dryrun.REPLACED)

    def test_no_flags_at_all_means_rsync_leaves_it_alone(self):
        self.assertEqual(dryrun.classify('.f         '), dryrun.UNCHANGED)
        self.assertEqual(dryrun.classify('.f.........'), dryrun.UNCHANGED)

    def test_directories_are_reported_separately(self):
        self.assertEqual(dryrun.classify('cd+++++++++'), dryrun.DIRECTORY)

    def test_deletions_are_recognised(self):
        self.assertEqual(dryrun.classify('*deleting  '), dryrun.DELETED)

    def test_non_item_lines_are_ignored(self):
        for line in ('', 'sending incremental file list', 'total size is 1,234', 'Number of files: 3'):
            self.assertIsNone(dryrun.classify(line), line)


SAMPLE = """sending incremental file list
>f+++++++++|4823891234|Season 01/Show - S01E01 - Pilot.mkv
>f..t......|2311885320|Season 01/Show - S01E02 - Second.mkv
.f         |1998221114|Season 01/Show - S01E03 - Third.mkv
cd+++++++++|0|Season 02/
>f+++++++++|51200|Season 01/Show - S01E01 - Pilot.en.srt

Number of files: 5
Total file size: 9.13G bytes
"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.report = dryrun.DryRunReport(files=dryrun.parse(SAMPLE))

    def test_every_item_line_is_read_and_nothing_else_is(self):
        self.assertEqual(len(self.report.files), 5)

    def test_sizes_come_from_rsync_not_from_our_own_listing(self):
        pilot = next(f for f in self.report.files if f.rel.endswith('Pilot.mkv'))
        self.assertEqual(pilot.size, 4823891234)

    def test_a_name_containing_the_separator_survives(self):
        files = dryrun.parse('>f+++++++++|123|Season 01/Weird | Name.mkv')
        self.assertEqual(files[0].rel, 'Season 01/Weird | Name.mkv')
        self.assertEqual(files[0].size, 123)

    def test_summary_counts_what_the_operator_asked_about(self):
        summary = self.report.summary()
        self.assertEqual(summary['new'], 2)         # one mkv, one srt
        self.assertEqual(summary['replaced'], 1)
        self.assertEqual(summary['unchanged'], 1)
        self.assertEqual(summary['directories'], 1)

    def test_subtitles_do_not_count_towards_the_media_totals(self):
        summary = self.report.summary()
        self.assertEqual(summary['media_new'], 1, 'the .srt is not a media file')

    def test_incoming_bytes_exclude_files_rsync_would_skip(self):
        self.assertEqual(
            self.report.incoming_bytes,
            4823891234 + 2311885320 + 51200,
            'an unchanged file moves no bytes',
        )

    def test_verdict_reads_as_a_sentence(self):
        self.assertIn('would be downloaded', self.report.verdict())
        self.assertIn('would be replaced', self.report.verdict())


class VerdictTests(unittest.TestCase):
    def test_nothing_to_do_says_so_plainly(self):
        report = dryrun.DryRunReport(files=dryrun.parse('.f         |100|a.mkv'))
        self.assertIn('Nothing would change', report.verdict())

    def test_a_replacement_is_not_counted_twice_as_a_backup(self):
        report = dryrun.DryRunReport(
            files=[dryrun.DryRunFile(change=dryrun.REPLACED, rel='a.mkv', size=5)],
            backups=[{'rel': 'a.mkv', 'local_size': 5}])
        verdict = report.verdict()
        self.assertIn('1 would be replaced', verdict)
        self.assertNotIn('backed up first,', verdict)

    def test_a_removals_only_plan_does_not_claim_rsync_said_so(self):
        report = dryrun.DryRunReport(ran=False, removals=[{'local_size': 1}])
        self.assertNotIn('rsync', report.verdict())
        self.assertIn('Nothing would be downloaded', report.verdict())

    def test_a_failure_reports_its_own_reason(self):
        report = dryrun.DryRunReport(ok=False, error='rsync exited with code 23')
        self.assertEqual(report.verdict(), 'rsync exited with code 23')

    def test_removals_are_named_as_backup_then_removal(self):
        report = dryrun.DryRunReport(removals=[{'local_size': 10}])
        self.assertIn('moved to backup', report.verdict())


class TailTests(unittest.TestCase):
    def test_the_stats_block_is_kept_and_the_file_lines_are_not(self):
        kept = dryrun.tail(SAMPLE)
        self.assertIn('Number of files: 5', kept)
        self.assertNotIn('Pilot.mkv', kept)



class ReconcileTests(unittest.TestCase):
    """
    rsync is asked before the plan moves the superseded files aside, so it says
    there is nothing to do for them. Reporting that as-is would tell an operator
    a file is safe when it is about to be overwritten.
    """

    def test_a_superseded_file_rsync_skipped_is_still_reported_as_replaced(self):
        report = dryrun.DryRunReport(files=[])
        dryrun.reconcile(report, planned={'S01E01.mkv': 900}, superseded={'S01E01.mkv': 900})

        self.assertEqual(len(report.files), 1)
        self.assertEqual(report.files[0].change, dryrun.REPLACED)
        self.assertEqual(report.files[0].size, 900)
        self.assertEqual(report.warnings, [], 'this gap is expected, not a problem')

    def test_a_skipped_file_the_plan_does_not_back_up_is_a_warning(self):
        report = dryrun.DryRunReport(files=[])
        dryrun.reconcile(report, planned={'S01E02.mkv': 900}, superseded={})

        self.assertEqual(report.files, [])
        self.assertEqual(len(report.warnings), 1)
        self.assertIn('already there', report.warnings[0])

    def test_a_file_rsync_would_move_that_is_not_in_the_plan_is_a_warning(self):
        report = dryrun.DryRunReport(
            files=[dryrun.DryRunFile(change=dryrun.NEW, rel='stranger.mkv', size=5)])
        dryrun.reconcile(report, planned={}, superseded={})

        self.assertEqual(len(report.warnings), 1)
        self.assertIn('not in the approved plan', report.warnings[0])

    def test_agreement_produces_no_warnings(self):
        report = dryrun.DryRunReport(
            files=[dryrun.DryRunFile(change=dryrun.NEW, rel='a.mkv', size=5)])
        dryrun.reconcile(report, planned={'a.mkv': 5}, superseded={})
        self.assertEqual(report.warnings, [])

    def test_an_unchanged_file_rsync_reported_is_not_double_counted(self):
        report = dryrun.DryRunReport(
            files=[dryrun.DryRunFile(change=dryrun.UNCHANGED, rel='a.mkv', size=5)])
        dryrun.reconcile(report, planned={'a.mkv': 5}, superseded={'a.mkv': 5})
        self.assertEqual(len(report.files), 1, 'rsync already spoke for this one')

if __name__ == '__main__':
    unittest.main()
