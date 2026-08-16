#!/usr/bin/env python3
"""
Saying what actually happened.

Three separate things were reporting success for work that had not been done,
and each was only discoverable by opening a log:

  * A restore in test mode answered "Restored 2 file(s)" and wrote nothing.
  * A transfer in test mode recorded "completed successfully" and moved nothing,
    so the history could not tell a rehearsal from a real run a week later.
  * The version a restore displaced — the one to restore in order to undo that
    restore — was labelled as though an ordinary sync had displaced it.

None of these is a crash, which is why they survived. A success message that is
not true is worse than no message, because it is acted on: a restore that
appears to have worked is one nobody checks.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.backups.indexer import (
    DEFAULT_REASON,
    RESTORE_REASON,
    reason_from,
)
from services.backups.layout import CaptureLocation


def location(source_ref):
    return CaptureLocation(
        path='/backups/movies/Example Film (2024)/20260101T000000.000Z__x',
        relative_path='movies/Example Film (2024)/20260101T000000.000Z__x',
        capture_id='20260101T000000.000Z__x',
        library='movies',
        title='Example Film (2024)',
        season=None,
        episode=None,
        captured_at=None,
        source_ref=source_ref,
        kind='movie',
    )


class WhyAVersionExistsTests(unittest.TestCase):
    """
    Worked out from the folder name, not remembered in a column.

    The tree is the source of truth and the database is an index over it, so a
    reason held only in a row is invented afresh on every rebuild — which is
    exactly what was happening: every capture came back as "replaced by a sync",
    including the ones a restore had created.
    """

    def test_a_restore_capture_is_labelled_as_one(self):
        self.assertEqual(reason_from(location('restore')), RESTORE_REASON)

    def test_an_ordinary_sync_capture_keeps_the_default(self):
        # Anything else puts a transfer id there.
        self.assertEqual(reason_from(location('56548077')), DEFAULT_REASON)
        self.assertEqual(reason_from(location(None)), DEFAULT_REASON)
        self.assertEqual(reason_from(location('')), DEFAULT_REASON)

    def test_it_survives_a_rebuild_because_it_is_read_from_disk(self):
        # The point of deriving it: a rebuild walks the tree with no rows to
        # carry anything forward, and must still get this right.
        self.assertEqual(reason_from(location('RESTORE')), RESTORE_REASON)

    def test_the_interface_has_a_label_for_every_reason_produced(self):
        # A reason with no label falls back to "Displaced by a sync", which is
        # how repair captures were being described.
        labels = (REPO_ROOT / 'frontend' / 'src' / 'lib' / 'backup-types.ts').read_text()
        produced = {DEFAULT_REASON, RESTORE_REASON, 'explore_prune', 'explore_repair'}
        for reason in produced:
            self.assertIn(f'{reason}:', labels, f'{reason} has no label in the interface')


class TestModeIsVisibleTests(unittest.TestCase):
    def test_a_rehearsed_restore_does_not_claim_to_have_restored(self):
        from services.backups import restore as restore_module

        source = (REPO_ROOT / 'services' / 'backups' / 'restore.py').read_text()
        run = source.split('def run(')[1].split('\n    def ')[0]
        # The dry-run answer comes BEFORE the ordinary success line, so a
        # rehearsal can never fall through to "Restored N file(s)".
        self.assertIn('Test mode: nothing was written', run)
        self.assertLess(
            run.index('Test mode: nothing was written'),
            run.index('return True, f"Restored'),
            'the dry-run message must be returned before the success one',
        )
        self.assertIn("summary['dry_run'] = dry_run", run)
        self.assertTrue(hasattr(restore_module, 'test_mode_enabled'))

    def test_a_rehearsed_transfer_says_so_in_its_own_row(self):
        source = (REPO_ROOT / 'services' / 'transfer_service.py').read_text()
        self.assertIn('Test mode: nothing was transferred', source)

    def test_a_simulation_is_not_called_a_rehearsal(self):
        # Simulations move real bytes between local fixture files even in test
        # mode, so claiming nothing was transferred would be its own lie.
        source = (REPO_ROOT / 'services' / 'transfer_service.py').read_text()
        monitor = source.split('def _monitor_transfer')[1]
        self.assertIn('is_simulation = bool(existing.get', monitor,
                      'the monitor must read is_simulation; it is not in scope otherwise')
        self.assertIn('test_mode_enabled() and not is_simulation', monitor)

    def test_the_server_reports_test_mode_at_the_top_level(self):
        source = (REPO_ROOT / 'routes' / 'debug.py').read_text()
        self.assertIn('"test_mode": bool(socketio_runtime_info.get', source)

    def test_the_header_shows_it(self):
        navbar = (REPO_ROOT / 'frontend' / 'src' / 'components' / 'layout'
                  / 'app-navbar.tsx').read_text()
        self.assertIn('useTestMode', navbar, 'the header never asks whether test mode is on')
        self.assertIn('{testMode && (', navbar, 'the header never renders it')

    def test_the_header_badge_is_not_hidden_on_small_screens(self):
        # The version badge beside it IS hidden below sm. This one must not be:
        # a phone is exactly where somebody checks whether a sync worked, so a
        # badge that vanished at that width would be worse than none.
        import re

        navbar = (REPO_ROOT / 'frontend' / 'src' / 'components' / 'layout'
                  / 'app-navbar.tsx').read_text()
        badge = navbar.split('{testMode && (')[1].split(')}')[0]
        # Only the style classes; `aria-hidden` is an accessibility attribute on
        # the icon and has nothing to do with the breakpoint.
        classes = ' '.join(re.findall(r'className="([^"]*)"', badge)).split()
        self.assertNotIn('hidden', classes)
        self.assertNotIn('sm:inline-flex', classes)

    def test_a_rehearsed_restore_is_not_toasted_as_a_success(self):
        page = (REPO_ROOT / 'frontend' / 'src' / 'components' / 'pages' / 'backups.tsx').read_text()
        self.assertIn('result.dry_run', page)

if __name__ == '__main__':
    unittest.main()
