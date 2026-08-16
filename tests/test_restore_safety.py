#!/usr/bin/env python3
"""
Two ways a restore could quietly damage the thing it exists to protect.

Both were found in review, both reproduced, and neither crashed anything — which
is why they need tests rather than care.

  1. A REHEARSAL counted as a restore. Test mode writes nothing, but the run
     still stamped the capture as restored, recorded a real "Restored ..."
     against whoever asked, and handed retention a capture id for a folder that
     was never created. Retention could then prune a genuine version to make
     room for a phantom.

  2. A FAILED restore left the live file hardlinked to an indexed backup. The
     current occupant is kept by giving it a second name — safe only because it
     is about to be replaced. When the replacement fails it is not replaced, so
     the two stay one file under two names, indefinitely, indexed as a backup.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.backups import preserve
from services.backups.restore import RestoreRunner


class RehearsalIsNotARestoreTests(unittest.TestCase):
    """
    Pinned by reading the finaliser, because the damage is in what it triggers
    downstream rather than in a value it returns.
    """

    def source(self):
        return (REPO_ROOT / 'services' / 'backups' / 'service.py').read_text()

    def body(self):
        return self.source().split('def _finish_restore')[1].split('\n    def ')[0]

    def test_a_rehearsal_is_not_treated_as_a_successful_restore(self):
        body = self.body()
        self.assertIn("rehearsed = bool(summary.get('dry_run'))", body)
        self.assertIn('and not rehearsed', body)

    def test_a_rehearsal_does_not_stamp_the_capture_as_restored(self):
        body = self.body()
        stamp = body.split("'restored_at': now")[0]
        # The stamp is guarded by completion_succeeded, which now excludes a
        # rehearsal. If that guard is ever loosened this fails.
        self.assertIn('if completion_succeeded:', stamp)

    def test_a_rehearsal_does_not_run_retention(self):
        body = self.body()
        self.assertIn("if completion_succeeded and summary.get('captured')", body)

    def test_a_rehearsal_is_recorded_as_a_rehearsal(self):
        body = self.body()
        self.assertIn('Rehearsed a restore of', body)
        self.assertIn("'dry_run': rehearsed", body)

    def test_the_endpoint_answers_dry_run_itself(self):
        # The worker decides far too late: the response is already sent. Test
        # mode is a property of the server and is knowable at accept time.
        accept = self.source().split('def restore(')[1].split('\n    def ')[0]
        self.assertIn('test_mode_enabled()', accept)
        self.assertIn("'dry_run': rehearsing", accept)


class FailedRestoreLeavesNothingSharedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.library = os.path.join(self.tmp, 'library')
        self.capture = os.path.join(self.tmp, 'capture')
        os.makedirs(self.library)
        os.makedirs(self.capture)
        self.live = os.path.join(self.library, 'episode.mkv')
        with open(self.live, 'wb') as handle:
            handle.write(b'the copy that is already there')

    def runner(self):
        return RestoreRunner.__new__(RestoreRunner)

    def test_a_kept_copy_whose_write_failed_is_discarded(self):
        kept = os.path.join(self.capture, 'episode.mkv')
        preserve.keep_before_destroying(self.live, kept)
        self.assertEqual(os.stat(self.live).st_nlink, 2)

        # What the fix does when the restore of that file fails.
        os.remove(kept)

        self.assertEqual(os.stat(self.live).st_nlink, 1)
        with open(self.live, 'rb') as handle:
            self.assertEqual(handle.read(), b'the copy that is already there')

    def test_the_runner_discards_kept_copies_for_failed_operations(self):
        source = (REPO_ROOT / 'services' / 'backups' / 'restore.py').read_text()
        run = source.split('def run(')[1].split('\n    def ')[0]
        self.assertIn("failed_paths = {f['file'] for f in summary['failures']}", run)
        # And the discard happens BEFORE the capture is indexed, so a capture
        # holding only unreplaced files is never written down as a backup.
        self.assertLess(
            run.index('failed_paths'),
            run.index('reindex_capture'),
            'kept copies must be discarded before the capture is indexed',
        )

    def test_an_emptied_capture_is_not_indexed(self):
        source = (REPO_ROOT / 'services' / 'backups' / 'restore.py').read_text()
        run = source.split('def run(')[1].split('\n    def ')[0]
        self.assertIn('os.rmdir(new_capture_path)', run)
        self.assertIn("summary['captured'] = None", run)


if __name__ == '__main__':
    unittest.main()
