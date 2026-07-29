#!/usr/bin/env python3
"""
Tests for the transfer listing query.

Listings show how many log lines a transfer has, never the lines themselves, so
they select everything except the log body and count it in SQL. These tests pin
the two things that makes fragile: the count has to agree with the log it is
counting, and leaving the column out must not quietly drop any other field.
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


class TransferListingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        db_path = os.path.join(self.tempdir.name, "listing.db")
        self.db = DatabaseManager(os.path.relpath(db_path, REPO_ROOT))
        self.model = Transfer(self.db)

    def make(self, transfer_id, status="completed", log_lines=0, **extra):
        self.model.create({
            "transfer_id": transfer_id,
            "media_type": "movies",
            "folder_name": f"Folder {transfer_id}",
            "source_path": f"/remote/{transfer_id}",
            "dest_path": f"/local/{transfer_id}",
            "operation_type": "folder",
            "status": status,
            **extra,
        })
        for index in range(log_lines):
            self.model.add_log(transfer_id, f"line {index}")

    def test_log_count_matches_the_stored_log(self):
        self.make("a", log_lines=7)
        self.make("b", log_lines=0)

        listed = {t["transfer_id"]: t for t in self.model.get_all(include_logs=False)}
        full = {t["transfer_id"]: t for t in self.model.get_all(include_logs=True)}

        for transfer_id in ("a", "b"):
            self.assertEqual(
                listed[transfer_id]["log_count"], len(full[transfer_id]["logs"]),
                f"{transfer_id}: counted log_count disagrees with the log itself"
            )

    def test_listing_omits_the_log_body_but_no_other_field(self):
        self.make("a", log_lines=3)

        full = self.model.get_all(include_logs=True)[0]
        listed = self.model.get_all(include_logs=False)[0]

        self.assertNotIn("logs", listed, "the log body should not be selected for a listing")
        missing = {key for key in full if key != "logs"} - set(listed)
        self.assertEqual(missing, set(), f"listing dropped fields: {sorted(missing)}")
        for key, value in full.items():
            if key != "logs":
                self.assertEqual(listed[key], value, f"{key} differs between listing and full row")

    def test_status_filtering_happens_in_sql(self):
        self.make("done1", status="completed")
        self.make("done2", status="completed")
        self.make("failed1", status="failed")
        self.make("running1", status="running")

        failed = self.model.get_all(status_filter="failed", include_logs=False)
        self.assertEqual([t["transfer_id"] for t in failed], ["failed1"])

        active = self.model.get_all(statuses=["running", "queued"], include_logs=False)
        self.assertEqual([t["transfer_id"] for t in active], ["running1"])

    def test_statuses_filter_returns_nothing_when_none_match(self):
        self.make("done", status="completed")
        self.assertEqual(self.model.get_all(statuses=["running"], include_logs=False), [])

    def test_limit_applies_after_the_status_filter(self):
        """
        Filtering used to happen after the limit, so a page of recent completed
        transfers could hide every failed one. The filter belongs in SQL.
        """
        for index in range(5):
            self.make(f"done{index}", status="completed")
        self.make("failed1", status="failed")

        failed = self.model.get_all(status_filter="failed", limit=3, include_logs=False)
        self.assertEqual([t["transfer_id"] for t in failed], ["failed1"])

    def test_log_count_survives_a_non_json_log_column(self):
        """Rows written before the column held JSON must not break the count."""
        self.make("legacy")
        with self.db.get_connection() as conn:
            conn.execute("UPDATE transfers SET logs = ? WHERE transfer_id = ?",
                         ("not json at all", "legacy"))
            conn.commit()

        listed = self.model.get_all(include_logs=False)[0]
        self.assertEqual(listed["log_count"], 0)

    def test_full_read_still_parses_logs(self):
        """The detail path still needs the lines themselves."""
        self.make("a", log_lines=4)
        transfer = self.model.get("a")
        self.assertEqual(len(transfer["logs"]), 4)
        self.assertEqual(transfer["logs"][0], "line 0")


if __name__ == "__main__":
    unittest.main()
