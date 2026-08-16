#!/usr/bin/env python3
"""
Hardlink where it is safe, copy where it is not.

Once the backup area shares a disk with the media, a file can be kept by giving
it a second name instead of copying it — instant, whatever the size, and costing
no space. The catch is that two names mean one file: writing through either
changes both.

So the rule is about how long the two names coexist.

  * A file about to be replaced or deleted shares bytes for SECONDS. Link it.
  * A file restored into the library goes back to being ordinary library media
    and stays that way for months, exposed to anything that ever writes to it in
    place — a tag editor, a remux that strips an audio track. Copy it.

The second half is the one worth a test, because linking there would be faster,
smaller, and quietly wrong: the backup would still be listed, still look
restorable, and no longer be what was backed up.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.backups import preserve
from services.backups.layout import BackupLayout


class FakeConfig:
    def __init__(self, backup_path='', destinations=()):
        self.values = {'BACKUP_PATH': backup_path}
        self.destinations = list(destinations)

    def get(self, key, default=''):
        return self.values.get(key, default)

    def get_destination_paths(self):
        return self.destinations


class KeepBeforeDestroyingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.source = os.path.join(self.tmp, 'episode.mkv')
        with open(self.source, 'wb') as handle:
            handle.write(b'the original bytes')

    def test_it_links_rather_than_copying_on_one_filesystem(self):
        target = os.path.join(self.tmp, 'kept.mkv')
        how, size = preserve.keep_before_destroying(self.source, target)

        self.assertEqual(how, preserve.LINKED)
        self.assertEqual(size, len(b'the original bytes'))
        # One file, two names: same inode, and a link count of two.
        self.assertEqual(os.stat(self.source).st_ino, os.stat(target).st_ino)
        self.assertEqual(os.stat(target).st_nlink, 2)

    def test_destroying_the_original_leaves_the_kept_copy_intact(self):
        # The whole point. The caller deletes the original straight after.
        target = os.path.join(self.tmp, 'kept.mkv')
        preserve.keep_before_destroying(self.source, target)
        os.remove(self.source)

        with open(target, 'rb') as handle:
            self.assertEqual(handle.read(), b'the original bytes')
        self.assertEqual(os.stat(target).st_nlink, 1)

    def test_replacing_the_original_the_way_rsync_does_leaves_it_intact(self):
        # rsync never writes in place: it writes a temporary file and renames
        # it over the target. That breaks the link and the backup keeps the old
        # bytes, which is what makes linking safe here at all.
        target = os.path.join(self.tmp, 'kept.mkv')
        preserve.keep_before_destroying(self.source, target)

        temporary = self.source + '.tmp'
        with open(temporary, 'wb') as handle:
            handle.write(b'a brand new version')
        os.replace(temporary, self.source)

        with open(target, 'rb') as handle:
            self.assertEqual(handle.read(), b'the original bytes')

    def test_writing_in_place_would_reach_both_names(self):
        # Documents the hazard the rule exists for, rather than asserting it is
        # impossible. Nothing in this application does this; something outside
        # it could.
        target = os.path.join(self.tmp, 'kept.mkv')
        preserve.keep_before_destroying(self.source, target)

        with open(self.source, 'r+b') as handle:
            handle.seek(0)
            handle.write(b'REWRITTEN')

        with open(target, 'rb') as handle:
            self.assertTrue(handle.read().startswith(b'REWRITTEN'))

    def test_it_falls_back_to_copying_when_a_link_is_impossible(self):
        # Different filesystems, a filesystem without hardlinks, a hit link
        # limit — all the same answer. This is what keeps the code correct if
        # the backup area is ever moved back off the media disk.
        target = os.path.join(self.tmp, 'kept.mkv')
        with patch('services.backups.preserve.os.link', side_effect=OSError('EXDEV')):
            how, size = preserve.keep_before_destroying(self.source, target)

        self.assertEqual(how, preserve.COPIED)
        self.assertNotEqual(os.stat(self.source).st_ino, os.stat(target).st_ino)
        with open(target, 'rb') as handle:
            self.assertEqual(handle.read(), b'the original bytes')

    def test_a_failure_raises_so_the_caller_does_not_destroy_anything(self):
        target = os.path.join(self.tmp, 'nowhere', 'kept.mkv')
        with self.assertRaises(OSError):
            preserve.keep_before_destroying(self.source, target)

    def test_same_filesystem_is_answered_on_a_target_that_does_not_exist_yet(self):
        # The target is what we are about to create, so the check has to work
        # from its parent directory.
        self.assertTrue(preserve.same_filesystem(
            self.source, os.path.join(self.tmp, 'not-created-yet.mkv')))


class RestoreStaysACopyTests(unittest.TestCase):
    """
    A restored file must not share bytes with the backup it came from.

    Enforced by reading the code rather than by running a restore, because what
    is being pinned is a deliberate choice not to optimise — and the failure it
    prevents is invisible at runtime until somebody needs the backup.
    """

    def source(self):
        return (REPO_ROOT / 'services' / 'backups' / 'restore.py').read_text()

    @staticmethod
    def code_only(text: str) -> str:
        """Drop comment lines, so the comment explaining the rule cannot satisfy it."""
        return '\n'.join(
            line for line in text.splitlines() if not line.strip().startswith('#'))

    def test_the_restore_write_is_a_copy_not_a_link(self):
        write_step = self.code_only(
            self.source().split('def _restore_one')[1].split('def ')[0])
        self.assertIn('shutil.copy2', write_step)
        self.assertNotIn('os.link', write_step)
        self.assertNotIn('keep_before_destroying(', write_step)

    def test_the_reason_is_written_down_next_to_it(self):
        # This is the kind of thing someone optimises away in good faith two
        # years later. The comment is the guard.
        write_step = self.source().split('def _restore_one')[1].split('def ')[0]
        self.assertIn('DELIBERATELY A COPY', write_step)

    def test_capturing_the_file_being_replaced_does_link(self):
        capture_step = self.source().split('def _capture_current')[1].split('def ')[0]
        self.assertIn('keep_before_destroying', capture_step)


class BackupAreaPlacementTests(unittest.TestCase):
    """
    The backup area belongs beside the libraries, not inside one.

    Explore walks the library directories to work out what is on this machine.
    A backup area inside one would have every stored version read as a misplaced
    library file.
    """

    def test_a_backup_area_beside_the_libraries_is_fine(self):
        layout = BackupLayout(FakeConfig(
            backup_path='/media_external/sync_backup',
            destinations=['/media_external/media/movies', '/media_external/media/tv_shows'],
        ))
        self.assertIsNone(layout.misplaced_inside_library())

    def test_a_backup_area_inside_a_library_is_reported(self):
        layout = BackupLayout(FakeConfig(
            backup_path='/media_external/media/movies/backups',
            destinations=['/media_external/media/movies'],
        ))
        self.assertEqual(layout.misplaced_inside_library(), '/media_external/media/movies')

    def test_a_sibling_sharing_a_name_prefix_is_not_inside(self):
        # "/media/tv-backups" starts with "/media/tv" as a string but is a
        # different directory. A prefix test would report it wrongly.
        layout = BackupLayout(FakeConfig(
            backup_path='/media/tv-backups',
            destinations=['/media/tv'],
        ))
        self.assertIsNone(layout.misplaced_inside_library())

    def test_an_unconfigured_backup_area_is_not_an_error_here(self):
        layout = BackupLayout(FakeConfig(backup_path='', destinations=['/media/tv']))
        self.assertIsNone(layout.misplaced_inside_library())

if __name__ == '__main__':
    unittest.main()
