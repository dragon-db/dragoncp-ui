#!/usr/bin/env python3
"""
Tests for how rsync output is stored.

rsync prints a progress line several times a second, each superseding the last.
Storing all of them cost 91% of the log rows and hundreds of megabytes of
rewrite I/O per transfer, so progress lines are collapsed to the newest one and
their writes are throttled. These tests pin the behaviour that makes that safe:
real log lines must never be lost, and the final figures must never be left
showing whatever percentage happened to land on the write interval.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.database import DatabaseManager
from models.transfer import Transfer
import services.transfer_service as transfer_service


class FakeProcess:
    """Feeds canned rsync output through the monitor loop."""

    def __init__(self, lines, pid=4242):
        self._lines = list(lines)
        self.pid = pid
        self.stdout = self
        self.returncode = 0

    def readline(self):
        return self._lines.pop(0) + "\n" if self._lines else ""

    def wait(self):
        return 0


class TransferLoggingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        db_path = os.path.join(self.tempdir.name, "test.db")
        self.db = DatabaseManager(os.path.relpath(db_path, REPO_ROOT))
        self.model = Transfer(self.db)
        self.model.create({
            "transfer_id": "t1",
            "media_type": "movies",
            "folder_name": "Example",
            "source_path": "/remote/Example",
            "dest_path": "/local/Example",
            "operation_type": "folder",
            "status": "running",
        })
        self.service = transfer_service.TransferService(
            config={}, db_manager=self.db, transfer_model=self.model, socketio=None
        )

    def logs(self):
        return self.model.get("t1")["logs"]

    def service_clock_patch(self, clock, steps):
        """Drive the write interval from a scripted clock instead of wall time."""
        original = transfer_service.time.monotonic

        def fake_monotonic():
            try:
                clock["t"] = next(steps)
            except StopIteration:
                pass
            return clock["t"]

        transfer_service.time.monotonic = fake_monotonic
        self.addCleanup(setattr, transfer_service.time, "monotonic", original)

    def test_progress_lines_collapse_to_the_newest(self):
        self.service._monitor_transfer("t1", FakeProcess([
            "sending incremental file list",
            "movie.mkv",
            "  1.00G  10%  10.00MB/s    0:01:00",
            "  2.00G  20%  10.00MB/s    0:00:50",
            "  3.00G  30%  10.00MB/s    0:00:40",
        ]))

        logs = self.logs()
        ticks = [line for line in logs if transfer_service.parse_rsync_progress(line)]
        self.assertEqual(len(ticks), 1, f"expected one progress line, got {logs}")
        self.assertIn("30%", ticks[0])
        self.assertIn("sending incremental file list", logs)
        self.assertIn("movie.mkv", logs)

    def test_real_log_lines_are_never_replaced_by_a_progress_line(self):
        """
        Regression: deciding to replace based on the in-memory tail rather than
        on what actually reached the database let a progress line overwrite the
        log line before it.

        It only shows when the write interval expires between the two, so the
        clock is driven here: a file name is written, the next tick is skipped
        by the interval, and the tick after it is written a full interval later.
        The file name must still be there.
        """
        clock = {"t": 0.0}
        steps = iter([0.0, 0.1, 2.0])  # durable, skipped tick, tick after the interval
        self.service_clock_patch(clock, steps)

        self.service._monitor_transfer("t1", FakeProcess([
            "first.mkv",
            "  2.00G  20%  10.00MB/s    0:00:50",
            "  3.00G  30%  10.00MB/s    0:00:40",
        ]))

        logs = self.logs()
        self.assertIn("first.mkv", logs, f"the file name was overwritten by a progress line: {logs}")
        ticks = [line for line in logs if transfer_service.parse_rsync_progress(line)]
        self.assertEqual(len(ticks), 1)
        self.assertIn("30%", ticks[0])

    def test_final_progress_survives_the_write_interval(self):
        """The last thing rsync reported must be persisted even if it lands
        inside the throttle window, or a finished transfer shows a stale %."""
        self.service._monitor_transfer("t1", FakeProcess([
            "movie.mkv",
            "  1.00G  10%  10.00MB/s    0:01:00",
            " 10.00G 100%  10.00MB/s    0:00:00",
        ]))

        row = self.model.get("t1")
        self.assertEqual(row["progress_percent"], 100)
        self.assertEqual(row["bytes_transferred"], 10_000_000_000)

    def test_stats_summary_is_kept_in_full(self):
        """The --stats block is the part of an rsync log worth keeping."""
        self.service._monitor_transfer("t1", FakeProcess([
            "  1.00G  10%  10.00MB/s    0:01:00",
            "Number of files: 3 (reg: 2, dir: 1)",
            "Number of regular files transferred: 2",
            "Total transferred file size: 10.00G bytes",
            "total size is 10.00G  speedup is 1.00",
        ]))

        logs = self.logs()
        for expected in (
            "Number of files: 3 (reg: 2, dir: 1)",
            "Number of regular files transferred: 2",
            "Total transferred file size: 10.00G bytes",
        ):
            self.assertIn(expected, logs)
        # The summary line also carries the authoritative total
        self.assertEqual(self.model.get("t1")["total_bytes"], 10_000_000_000)

    def test_errors_are_kept(self):
        self.service._monitor_transfer("t1", FakeProcess([
            "  1.00G  10%  10.00MB/s    0:01:00",
            "rsync: [receiver] mkstemp failed: Permission denied (13)",
            "  2.00G  20%  10.00MB/s    0:00:50",
        ]))

        self.assertIn("rsync: [receiver] mkstemp failed: Permission denied (13)", self.logs())

    def test_log_is_capped(self):
        """A pathological transfer must not grow the row without bound."""
        cap = 50
        logs = self.model.get("t1")["logs"]
        for index in range(cap + 25):
            self.model.add_log("t1", f"file_{index}.mkv", max_lines=cap)

        logs = self.logs()
        self.assertEqual(len(logs), cap)
        # The tail is what survives: it holds the summary and any errors
        self.assertEqual(logs[-1], f"file_{cap + 24}.mkv")


if __name__ == "__main__":
    unittest.main()


class IntentionalStopWindowTests(unittest.TestCase):
    """
    Cancelling or pausing a transfer whose rsync has already exited.

    `has_process` is a point-in-time answer. rsync can be gone while its monitor
    thread is still parked in `process.wait()`, about to write a terminal
    status. If the stop intent is not recorded on that path, the monitor pops
    nothing and overwrites the operator's cancellation with 'completed' or
    'failed'.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        db_path = os.path.join(self.tempdir.name, "stops.db")
        self.db = DatabaseManager(os.path.relpath(db_path, REPO_ROOT))
        self.model = Transfer(self.db)
        self.service = transfer_service.TransferService({}, self.db, self.model)

    def make(self, transfer_id, status):
        self.model.create({
            "transfer_id": transfer_id, "media_type": "movies",
            "folder_name": "Fixture", "source_path": "/s", "dest_path": "/d",
            "operation_type": "folder", "status": status,
            # No pid, so has_process is False - the window under test.
        })

    def test_cancel_records_intent_with_no_live_process(self):
        self.make("gone", "running")

        self.assertTrue(self.service.cancel_transfer("gone"))
        self.assertEqual(self.model.get("gone")["status"], "cancelled")
        # The monitor would read this and leave the row alone.
        self.assertEqual(self.service._take_intentional_stop("gone"), "cancelled")

    def test_pause_keeps_intent_with_no_live_process(self):
        self.make("gone", "running")

        ok, _message = self.service.pause_transfer("gone")

        self.assertTrue(ok)
        self.assertEqual(self.model.get("gone")["status"], "paused")
        self.assertEqual(self.service._take_intentional_stop("gone"), "paused")

    def test_a_stale_intent_does_not_leak_into_the_next_run(self):
        """What makes recording it unconditionally safe."""
        self.make("again", "running")
        self.service.cancel_transfer("again")
        self.assertIsNotNone(self.service._take_intentional_stop("again"))

        self.service._mark_intentional_stop("again", "cancelled")
        self.service._clear_intentional_stop("again")
        self.assertIsNone(self.service._take_intentional_stop("again"))
