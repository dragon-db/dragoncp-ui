#!/usr/bin/env python3
"""
Tests for the test-mode gate and for compacting logs while transfers run.

Both cover failures that are silent by nature. A test-mode gate that reads
`TEST_MODE=true` as off copies and deletes files while the UI says it is only
pretending; a log compaction that writes unconditionally throws away lines a
running transfer produced after the read, and reports success either way.
"""

import json
import os
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Imported as a module: `from env_flags import test_mode_enabled` would have
# pytest collect the function itself as a test case.
import env_flags


class TestModeFlagTests(unittest.TestCase):
    def setUp(self):
        self.original = os.environ.get('TEST_MODE')
        self.addCleanup(self.restore)

    def restore(self):
        if self.original is None:
            os.environ.pop('TEST_MODE', None)
        else:
            os.environ['TEST_MODE'] = self.original

    def test_the_ways_people_write_yes(self):
        for value in ('1', 'true', 'TRUE', 'True', 'yes', 'on', '  true  '):
            os.environ['TEST_MODE'] = value
            self.assertTrue(env_flags.test_mode_enabled(), f"{value!r} should enable test mode")

    def test_the_ways_people_write_no(self):
        for value in ('0', 'false', 'no', 'off', ''):
            os.environ['TEST_MODE'] = value
            self.assertFalse(env_flags.test_mode_enabled(), f"{value!r} should not enable test mode")

    def test_unset_is_off(self):
        os.environ.pop('TEST_MODE', None)
        self.assertFalse(env_flags.test_mode_enabled())
        self.assertTrue(env_flags.env_flag('TEST_MODE', default=True), "the default must be honoured")

    def test_no_module_compares_test_mode_against_a_literal_again(self):
        """
        The defect this guards against was two readings of one variable: the
        banner accepted `true`, every safety gate demanded exactly `'1'`. A
        stray strict comparison reintroduces it, and nothing else would notice.
        """
        offenders = []
        for path in list(REPO_ROOT.glob('*.py')) + list(REPO_ROOT.glob('services/*.py')) \
                + list(REPO_ROOT.glob('routes/*.py')) + list(REPO_ROOT.glob('models/*.py')):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if 'TEST_MODE' in line and '==' in line and 'env_flag' not in line:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")

        self.assertEqual(
            offenders, [],
            "read TEST_MODE through env_flags.test_mode_enabled(), not a string comparison:\n"
            + "\n".join(offenders),
        )


class LogCompactionTests(unittest.TestCase):
    """The compaction script, run against a database something else is writing."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "compact.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE transfers (transfer_id TEXT PRIMARY KEY,"
                     " folder_name TEXT, logs TEXT)")
        conn.commit()
        conn.close()

    def add(self, transfer_id, lines):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO transfers (transfer_id, folder_name, logs) VALUES (?, ?, ?)",
                     (transfer_id, transfer_id, json.dumps(lines)))
        conn.commit()
        conn.close()

    def logs_of(self, transfer_id):
        conn = sqlite3.connect(self.db_path)
        raw = conn.execute("SELECT logs FROM transfers WHERE transfer_id = ?",
                           (transfer_id,)).fetchone()[0]
        conn.close()
        return json.loads(raw)

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "compact_transfer_logs.py"),
             "--db", self.db_path, *args],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )

    def ticks(self, count):
        """A run of rsync progress lines, the kind that collapse to one."""
        return [f"  1,234,{index:03d}  {index}%  10.00MB/s    0:00:10" for index in range(count)]

    def test_report_only_changes_nothing(self):
        self.add("t1", self.ticks(50))

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.logs_of("t1")), 50, "a report must not write")

    def test_apply_collapses_progress_and_keeps_everything_else(self):
        self.add("t1", ["Starting rsync", *self.ticks(40), "sent 1,234 bytes", "done"])

        result = self.run_script("--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        kept = self.logs_of("t1")
        self.assertIn("Starting rsync", kept)
        self.assertIn("sent 1,234 bytes", kept)
        self.assertIn("done", kept)
        self.assertLess(len(kept), 10, "the run of ticks should have collapsed")

    def test_a_row_written_during_the_run_is_left_alone(self):
        """
        The window: the script reads every row, then writes. A transfer that
        appends between the two would have its new lines replaced by a copy
        taken before they existed.

        Driven directly through the script's own two phases, so the gap is real
        rather than simulated: plan, then a write from elsewhere, then apply.
        """
        self.add("running", self.ticks(60))
        self.add("finished", self.ticks(60))

        import scripts.compact_transfer_logs as compactor

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        *_, changed = compactor.plan(conn)
        self.assertEqual(len(changed), 2, "both rows should be candidates")

        # The running transfer writes a line after the read and before the write.
        writer = sqlite3.connect(self.db_path)
        writer.execute("UPDATE transfers SET logs = ? WHERE transfer_id = 'running'",
                       (json.dumps(self.ticks(60) + ["a line written while compacting"]),))
        writer.commit()
        writer.close()

        skipped = compactor.apply_changes(conn, changed)
        conn.close()

        self.assertEqual(skipped, ["running"], "the row that moved must be reported")
        self.assertIn("a line written while compacting", self.logs_of("running"),
                      "the concurrent write must survive")
        self.assertLess(len(self.logs_of("finished")), 10,
                        "the untouched row should still have been compacted")

    def test_the_guard_is_what_saves_it(self):
        """
        Without the compare-and-set the previous test would pass silently, so
        pin that an unconditional write does lose the line - the guard is doing
        the work, not the ordering.
        """
        self.add("running", self.ticks(60))

        import scripts.compact_transfer_logs as compactor

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        *_, changed = compactor.plan(conn)

        writer = sqlite3.connect(self.db_path)
        writer.execute("UPDATE transfers SET logs = ? WHERE transfer_id = 'running'",
                       (json.dumps(self.ticks(60) + ["a line written while compacting"]),))
        writer.commit()
        writer.close()

        # The old, unconditional form.
        transfer_id, _folder, _before, _after, new_raw, _original = changed[0]
        with conn:
            conn.execute("UPDATE transfers SET logs = ? WHERE transfer_id = ?",
                         (new_raw, transfer_id))
        conn.close()

        self.assertNotIn("a line written while compacting", self.logs_of("running"))

if __name__ == '__main__':
    unittest.main()
