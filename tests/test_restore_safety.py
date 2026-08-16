#!/usr/bin/env python3
"""
A restore must never leave a live library file welded to a stored backup.

These RUN the restore rather than reading the code that performs it. The
previous version of this file mostly asserted on source strings, and that is
exactly why it passed while a real hole stayed open: reading the code only ever
proves the code says what you expected it to say.

A file is kept by giving it a SECOND NAME when the backup area shares a disk
with the media — instant, and free. That is safe only while the caller really
does destroy the original immediately afterwards. Three things can stop it:

  1. the write of the replacement fails,
  2. the write succeeds but removing the OLD filename fails, which is reported
     as a success with a warning, and
  3. a rehearsal, which writes nothing at all by design.

All three end with the original still in the library, and in each case the kept
copy must not survive as an indexed backup pointing at the same bytes.
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

from services.backups.restore import RestoreOperation, RestorePlan, RestoreRunner


class RestoreOnDiskTestCase(unittest.TestCase):
    """A real backup tree, a real library, and a real RestoreRunner."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.library = os.path.join(self.tmp, 'library')
        self.backups = os.path.join(self.tmp, 'backups')
        os.makedirs(self.library)
        os.makedirs(self.backups)

        # What is in the library now, and the older version being restored.
        self.live = os.path.join(self.library, 'Show - S01E01 [WEBDL-1080p].mkv')
        with open(self.live, 'wb') as handle:
            handle.write(b'the copy currently in the library')

        self.stored_dir = os.path.join(self.backups, 'stored')
        os.makedirs(self.stored_dir)
        self.stored = os.path.join(self.stored_dir, 'Show - S01E01 [HDTV-720p].mkv')
        with open(self.stored, 'wb') as handle:
            handle.write(b'the older version being restored')

        self.captured_dir = os.path.join(self.backups, 'movies', 'Show', 'newcapture')

    def build_runner(self):
        runner = RestoreRunner.__new__(RestoreRunner)
        runner.log = lambda *a, **k: None
        runner.layout = MagicMock()
        runner.layout.slot_dir.return_value = os.path.dirname(self.captured_dir)
        runner.captures = MagicMock()
        runner.captures.get.return_value = None
        runner.indexer = MagicMock()
        runner.config = MagicMock()
        # The library really is the boundary here, so the bounds check is real.
        runner.config.get_destination_paths.return_value = [self.library]
        return runner

    def plan(self, target=None, replaces=None):
        current = replaces if replaces is not None else self.live
        operation = RestoreOperation(
            relative_path='Show - S01E01.mkv',
            source=self.stored,
            target=target or self.live,
            replaces=current,
            replaces_size=os.path.getsize(current) if current else 0,
            file_size=os.path.getsize(self.stored),
            is_media=True,
            display='Show - S01E01',
        )
        return RestorePlan(
            capture_id='cap1', slot_display='Show S01E01', library='shows',
            target_dir=self.library, operations=[operation],
        )

    def run_restore(self, plan, dry_run=False):
        runner = self.build_runner()

        def reserve(*_args, **_kwargs):
            # The real one creates the folder; a stub that only returns a path
            # makes every keep fail for the wrong reason.
            os.makedirs(self.captured_dir, exist_ok=True)
            return self.captured_dir, 'newcapture'

        with patch('services.backups.restore.test_mode_enabled', return_value=dry_run), \
                patch('services.backups.restore.new_capture_id', return_value='newcapture'), \
                patch.object(RestoreRunner, '_reserve', side_effect=reserve):
            return runner.run(plan, {'library': 'shows', 'title': 'Show'}, None)

    def kept_copies(self):
        if not os.path.isdir(self.captured_dir):
            return []
        return sorted(os.listdir(self.captured_dir))

    def shares_bytes_with_live(self, name):
        kept = os.path.join(self.captured_dir, name)
        return os.stat(kept).st_ino == os.stat(self.live).st_ino


class AFailedWriteLeavesNothingSharedTests(RestoreOnDiskTestCase):
    def test_the_kept_copy_is_discarded_when_the_write_fails(self):
        plan = self.plan()
        with patch('services.backups.restore.shutil.copy2', side_effect=OSError('disk full')):
            ok, message, summary = self.run_restore(plan)

        self.assertEqual(summary['failed'], 1)
        self.assertEqual(self.kept_copies(), [],
                         'a copy kept for a file that was never replaced must not survive')
        self.assertEqual(os.stat(self.live).st_nlink, 1)
        with open(self.live, 'rb') as handle:
            self.assertEqual(handle.read(), b'the copy currently in the library')

    def test_an_emptied_capture_is_not_indexed(self):
        plan = self.plan()
        runner_indexer = {}

        with patch('services.backups.restore.shutil.copy2', side_effect=OSError('disk full')):
            ok, message, summary = self.run_restore(plan)

        self.assertIsNone(summary['captured'])
        self.assertFalse(os.path.isdir(self.captured_dir))


class ARenamedRestoreThatCouldNotTidyUpTests(RestoreOnDiskTestCase):
    """
    The case the first fix missed.

    An upgrade renamed the file, so the restore writes a DIFFERENT name and then
    removes the old one. When that removal fails the operation still counts as
    restored — with a warning — so a fix that only looked at the failure list
    left the old file in the library, still sharing bytes with an indexed backup.
    """

    def test_the_kept_copy_is_discarded_when_the_old_name_cannot_be_removed(self):
        renamed_target = os.path.join(self.library, 'Show - S01E01 [HDTV-720p].mkv')
        plan = self.plan(target=renamed_target, replaces=self.live)

        real_remove = os.remove

        def refuse_to_remove_the_live_file(path, *args, **kwargs):
            if os.path.abspath(path) == os.path.abspath(self.live):
                raise OSError('permission denied')
            return real_remove(path, *args, **kwargs)

        with patch('services.backups.restore.os.remove',
                   side_effect=refuse_to_remove_the_live_file):
            ok, message, summary = self.run_restore(plan)

        # The restore itself worked: the older version is now in the library.
        self.assertTrue(ok)
        self.assertEqual(summary['restored'], 1)
        self.assertTrue(os.path.exists(renamed_target))
        # And the file it could not remove is still there — which is precisely
        # why its kept copy must not remain linked to it.
        self.assertTrue(os.path.exists(self.live))
        self.assertEqual(self.kept_copies(), [])
        self.assertEqual(os.stat(self.live).st_nlink, 1)

    def test_a_successful_rename_restore_keeps_its_backup(self):
        # The control case. When the removal DOES work, the kept copy is the
        # only remaining name for those bytes and must survive.
        renamed_target = os.path.join(self.library, 'Show - S01E01 [HDTV-720p].mkv')
        plan = self.plan(target=renamed_target, replaces=self.live)

        ok, message, summary = self.run_restore(plan)

        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.live), 'the old name should have been removed')
        self.assertEqual(self.kept_copies(), ['Show - S01E01 [WEBDL-1080p].mkv'])
        with open(os.path.join(self.captured_dir, self.kept_copies()[0]), 'rb') as handle:
            self.assertEqual(handle.read(), b'the copy currently in the library')

    def test_an_in_place_replacement_keeps_its_backup(self):
        # The other control case, and the one an inode test could get wrong: the
        # restore overwrote the same path, so a file still exists there — but it
        # is a NEW file, and the kept copy is the only name for the old bytes.
        ok, message, summary = self.run_restore(self.plan())

        self.assertTrue(ok)
        self.assertEqual(self.kept_copies(), ['Show - S01E01 [WEBDL-1080p].mkv'])
        kept = os.path.join(self.captured_dir, self.kept_copies()[0])
        with open(kept, 'rb') as handle:
            self.assertEqual(handle.read(), b'the copy currently in the library')
        with open(self.live, 'rb') as handle:
            self.assertEqual(handle.read(), b'the older version being restored')


class ARehearsalWritesNothingTests(RestoreOnDiskTestCase):
    def test_a_rehearsal_changes_nothing_on_disk(self):
        ok, message, summary = self.run_restore(self.plan(), dry_run=True)

        self.assertTrue(ok)
        self.assertTrue(summary['dry_run'])
        self.assertIn('Test mode', message)
        self.assertEqual(self.kept_copies(), [])
        with open(self.live, 'rb') as handle:
            self.assertEqual(handle.read(), b'the copy currently in the library')


class RehearsalHasNoSideEffectsTests(unittest.TestCase):
    """
    The finaliser's downstream effects, which are what actually caused damage:
    a stamped capture, a recorded restore, and retention run against a capture
    that was never created.
    """

    def build(self):
        from services.backups.service import BackupsService

        service = BackupsService.__new__(BackupsService)
        service.transfer_model = MagicMock()
        service.captures = MagicMock()
        service.coordinator = None
        service.socketio = None
        service._lock = __import__('threading').Lock()
        service._restores_running = {}
        service._apply_retention_quietly = MagicMock()
        return service

    def finish(self, service, summary):
        plan = MagicMock()
        plan.slot_display = 'Show S01E01'
        plan.target_dir = '/library'
        with patch('services.backups.service.record') as record:
            service._finish_restore(
                't1', 'cap1', {}, plan, True, 'Test mode: nothing was written', summary)
        return record

    def test_a_rehearsal_does_not_stamp_prune_or_record_a_restore(self):
        service = self.build()
        record = self.finish(service, {
            'restored': 2, 'failed': 0, 'captured': 'cap-never-created', 'dry_run': True,
        })

        service.captures.update.assert_not_called()
        service._apply_retention_quietly.assert_not_called()
        self.assertIn('Rehearsed', record.call_args[0][1])

    def test_a_real_restore_still_stamps_prunes_and_records(self):
        service = self.build()
        record = self.finish(service, {
            'restored': 2, 'failed': 0, 'captured': 'cap2', 'dry_run': False,
        })

        service.captures.update.assert_called_once()
        service._apply_retention_quietly.assert_called_once()
        self.assertIn('Restored', record.call_args[0][1])
class ACrossDeviceBackupIsNeverMistakenForALinkTests(RestoreOnDiskTestCase):
    """
    An inode number is unique only WITHIN a filesystem.

    When the backup area is on a different disk the keep falls back to a real
    copy, and two unrelated files on two devices can share an inode number by
    coincidence. Comparing inode numbers alone then deletes a perfectly good
    backup. `os.path.samefile` compares the device too.
    """

    def test_a_backup_kept_as_a_copy_survives_a_successful_restore(self):
        # The real cross-device situation, with nothing faked: when the backup
        # area is on another disk the keep falls back to a COPY, so the two
        # files are independent from the start. The cleanup must recognise that
        # and leave it alone — an inode-number comparison would not, because
        # those numbers are only unique within one filesystem.
        with patch('services.backups.preserve.same_filesystem', return_value=False):
            ok, message, summary = self.run_restore(self.plan())

        self.assertTrue(ok)
        self.assertEqual(
            self.kept_copies(), ['Show - S01E01 [WEBDL-1080p].mkv'],
            'a backup kept as a copy is independent and must never be discarded')
        kept = os.path.join(self.captured_dir, self.kept_copies()[0])
        self.assertNotEqual(os.stat(kept).st_ino, os.stat(self.live).st_ino)
        with open(kept, 'rb') as handle:
            self.assertEqual(handle.read(), b'the copy currently in the library')

    def test_the_same_inode_number_on_two_devices_does_not_delete_the_backup(self):
        """
        The collision itself, made deterministic.

        Inode numbers are unique only within one filesystem, so two unrelated
        files on two devices can share one. Reporting real files with a matching
        inode number and DIFFERENT device ids is the only way to reproduce that
        on demand — and it is what tells an implementation comparing `st_ino`
        alone apart from one comparing device and inode together.
        """
        kept = os.path.join(self.captured_dir, os.path.basename(self.live))
        real_stat = os.stat
        collided = {'ino': 4242}

        def stat_with_a_collision(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            try:
                target = os.fspath(path)
            except TypeError:  # a file descriptor, used by the copy itself
                return result
            if os.path.abspath(target) not in (os.path.abspath(kept),
                                               os.path.abspath(self.live)):
                return result
            # A REAL stat_result, so everything that reads one keeps working.
            fields = list(result)
            fields[1] = collided['ino']                                  # st_ino
            fields[2] = 1 if 'backups' in target else 2                  # st_dev
            return os.stat_result(fields, {
                'st_atime_ns': result.st_atime_ns,
                'st_mtime_ns': result.st_mtime_ns,
                'st_ctime_ns': result.st_ctime_ns,
            })

        # Kept as a copy, as it would be across devices, then given colliding
        # inode numbers on different devices.
        with patch('services.backups.preserve.same_filesystem', return_value=False):
            with patch('os.stat', side_effect=stat_with_a_collision):
                ok, message, summary = self.run_restore(self.plan())

        self.assertTrue(ok, message)
        self.assertEqual(
            self.kept_copies(), ['Show - S01E01 [WEBDL-1080p].mkv'],
            'an inode-number collision across devices must not delete a real backup')


class DiscardingAKeptCopyTests(unittest.TestCase):
    """
    Withdrawing a keep has to remove the FILES, not just the row.

    Deleting the index entry while the file remains turns a visible problem into
    an invisible one: a second name for a live library file, sitting in the
    backup tree, listed nowhere and reachable by nothing.
    """

    def build(self):
        from services.backups.service import BackupsService

        service = BackupsService.__new__(BackupsService)
        service.captures = MagicMock()
        service.captures.get.return_value = {'capture_id': 'cap1'}
        return service

    def test_a_failed_file_removal_keeps_the_index_entry(self):
        service = self.build()
        service._remove_capture_files = MagicMock(
            return_value=(False, 'permission denied', False))

        self.assertFalse(service.discard_capture('cap1'))
        service.captures.delete.assert_not_called()

    def test_a_successful_removal_deletes_the_index_entry(self):
        service = self.build()
        service._remove_capture_files = MagicMock(return_value=(True, '', True))

        self.assertTrue(service.discard_capture('cap1'))
        service.captures.delete.assert_called_once_with('cap1')

if __name__ == '__main__':
    unittest.main()
