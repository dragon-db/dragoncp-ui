#!/usr/bin/env python3
"""
Tests for paging, search and bulk delete across transfers and webhook arrivals.

The pieces worth pinning are the ones a list gets quietly wrong:

- a page has to be a window on the whole set, so paging through it must yield
  every record exactly once - no repeats, no gaps;
- the total has to count matches, not the page just returned, or the caller
  cannot tell a full page from the end of the results;
- "delete everything matching" has to re-evaluate the filter rather than trust
  a list of ids, and must never take a transfer that is still running;
- notifications live in two tables, so their order has to be decided across
  both at once rather than by merging two separately-limited reads.
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
from models.webhook import (
    NotificationCatalog,
    SeriesWebhookNotification,
    WebhookNotification,
)


class TransferPagingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        db_path = os.path.join(self.tempdir.name, "paging.db")
        self.db = DatabaseManager(os.path.relpath(db_path, REPO_ROOT))
        self.model = Transfer(self.db)

    def make(self, transfer_id, status="completed", title="Placeholder", **extra):
        self.model.create({
            "transfer_id": transfer_id,
            "media_type": "movies",
            "folder_name": title,
            "source_path": f"/remote/{title}",
            "dest_path": f"/local/{title}",
            "operation_type": "folder",
            "status": status,
            **extra,
        })

    def seed(self, count=25):
        for index in range(count):
            self.make(f"t{index:03d}", title=f"Title {index:03d}")

    def test_paging_covers_every_record_once(self):
        self.seed(25)

        seen, offset = [], 0
        while True:
            page = self.model.get_all(limit=7, offset=offset, include_logs=False)
            if not page:
                break
            seen.extend(row["transfer_id"] for row in page)
            offset += 7

        self.assertEqual(len(seen), 25, "paging dropped or repeated records")
        self.assertEqual(len(set(seen)), 25)
        self.assertEqual(self.model.count(), 25)

    def test_total_counts_matches_not_the_page(self):
        self.seed(25)

        page = self.model.get_all(limit=5, include_logs=False)

        self.assertEqual(len(page), 5)
        self.assertEqual(self.model.count(), 25, "the total must survive a limit")

    def test_search_matches_title_season_and_path(self):
        self.make("a", title="The Bear")
        self.make("b", title="Severance", season_name="Season 2")
        self.make("c", title="Andor")

        self.assertEqual(self.model.count(search="bear"), 1)
        self.assertEqual(self.model.count(search="Season 2"), 1)
        # The destination path is built from the title, so it matches too.
        self.assertEqual(self.model.count(search="/local/Andor"), 1)
        self.assertEqual(self.model.count(search="nothing here"), 0)

    def test_search_and_status_filter_apply_together(self):
        self.make("a", status="failed", title="Severance")
        self.make("b", status="completed", title="Severance")
        self.make("c", status="failed", title="Andor")

        self.assertEqual(self.model.count(status_filter="failed", search="severance"), 1)

    def test_status_counts_cover_the_whole_table(self):
        self.make("a", status="completed")
        self.make("b", status="failed")
        self.make("c", status="failed")
        self.make("d", status="running")

        # Restricted to the statuses History lists, the live one is left out.
        self.assertEqual(
            self.model.status_counts(statuses=["completed", "failed", "cancelled"]),
            {"completed": 1, "failed": 2},
        )

    def test_bulk_delete_refuses_a_running_transfer(self):
        self.make("done", status="completed")
        self.make("live", status="running")

        deleted, skipped = self.model.delete_many(["done", "live"])

        self.assertEqual(deleted, 1)
        self.assertEqual(skipped, ["live"])
        self.assertIsNotNone(self.model.get("live"), "a running transfer must survive")
        self.assertIsNone(self.model.get("done"))

    def test_delete_matching_re_evaluates_the_filter_and_spares_running(self):
        self.make("keep", status="completed", title="The Bear")
        self.make("drop", status="failed", title="Severance")
        self.make("live", status="running", title="Severance")

        deleted, skipped = self.model.delete_matching(search="severance")

        self.assertEqual(deleted, 1)
        self.assertEqual(skipped, ["live"])
        self.assertIsNotNone(self.model.get("live"))
        self.assertIsNotNone(self.model.get("keep"), "the filter must not reach past its match")
        self.assertIsNone(self.model.get("drop"))

    def test_delete_matching_with_no_filter_clears_everything_finished(self):
        self.make("a", status="completed")
        self.make("b", status="cancelled")
        self.make("c", status="running")

        deleted, skipped = self.model.delete_matching()

        self.assertEqual(deleted, 2)
        self.assertEqual(skipped, ["c"])
        self.assertEqual(self.model.count(), 1)

    def test_bulk_delete_spans_more_ids_than_one_statement_allows(self):
        # More ids than SQLite's per-statement variable limit, to prove the
        # batching does not silently drop the tail.
        for index in range(1200):
            self.make(f"bulk{index:04d}")

        deleted, skipped = self.model.delete_many(
            [f"bulk{index:04d}" for index in range(1200)]
        )

        self.assertEqual(deleted, 1200)
        self.assertEqual(skipped, [])
        self.assertEqual(self.model.count(), 0)


class NotificationCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        db_path = os.path.join(self.tempdir.name, "notifications.db")
        self.db = DatabaseManager(os.path.relpath(db_path, REPO_ROOT))
        self.movies = WebhookNotification(self.db)
        self.series = SeriesWebhookNotification(self.db)
        self.catalog = NotificationCatalog(self.db, self.movies, self.series)

    def add_movie(self, notification_id, created_at, status="completed", title="A Movie"):
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO radarr_webhook (notification_id, title, folder_path, file_path,"
                " status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (notification_id, title, f"/movies/{title}", f"/movies/{title}/f.mkv",
                 status, created_at),
            )
            conn.commit()

    def add_series(self, notification_id, created_at, status="pending", title="A Series",
                   media_type="tvshows"):
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO sonarr_webhook (notification_id, media_type, series_title,"
                " series_path, season_path, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (notification_id, media_type, title, f"/tv/{title}", f"/tv/{title}/S01",
                 status, created_at),
            )
            conn.commit()

    def test_order_is_decided_across_both_tables(self):
        # Interleaved in time, so a per-table read followed by a merge would
        # rank them differently from a single ordered pass.
        self.add_movie("m1", "2026-01-04 10:00:00")
        self.add_series("s1", "2026-01-03 10:00:00")
        self.add_movie("m2", "2026-01-02 10:00:00")
        self.add_series("s2", "2026-01-01 10:00:00")

        page = self.catalog.page(limit=10)

        self.assertEqual([n["notification_id"] for n in page], ["m1", "s1", "m2", "s2"])

    def test_later_pages_reach_the_quieter_source(self):
        # Five series arrivals crowd the recent past and one movie sits far
        # behind them. Reading a fixed number from each table and merging can
        # never return more rows than that number, so the movie was unreachable
        # however far anyone looked - the first page was right and there was
        # no second one.
        for index in range(5):
            self.add_series(f"s{index}", f"2026-02-0{index + 1} 10:00:00")
        self.add_movie("old", "2020-01-01 10:00:00")

        first = [n["notification_id"] for n in self.catalog.page(limit=2)]
        last = [n["notification_id"] for n in self.catalog.page(limit=2, offset=4)]

        self.assertEqual(first, ["s4", "s3"])
        self.assertEqual(last, ["s0", "old"])
        self.assertEqual(self.catalog.count(), 6)

    def test_paging_covers_every_notification_once(self):
        for index in range(9):
            self.add_movie(f"m{index}", f"2026-03-{index + 1:02d} 10:00:00")
        for index in range(8):
            self.add_series(f"s{index}", f"2026-03-{index + 1:02d} 18:00:00")

        seen, offset = [], 0
        while True:
            page = self.catalog.page(limit=4, offset=offset)
            if not page:
                break
            seen.extend(n["notification_id"] for n in page)
            offset += 4

        self.assertEqual(len(seen), 17)
        self.assertEqual(len(set(seen)), 17, "paging repeated a notification")
        self.assertEqual(self.catalog.count(), 17)

    def test_status_and_media_type_filters(self):
        self.add_movie("m1", "2026-01-01 10:00:00", status="failed")
        self.add_series("s1", "2026-01-02 10:00:00", status="pending")
        self.add_series("s2", "2026-01-03 10:00:00", status="pending", media_type="anime")

        self.assertEqual(self.catalog.count(status="pending"), 2)
        self.assertEqual(self.catalog.count(status="failed"), 1)
        self.assertEqual(self.catalog.count(media_type="movies"), 1)
        self.assertEqual(self.catalog.count(media_type="anime"), 1)
        self.assertEqual(
            self.catalog.status_counts(), {"failed": 1, "pending": 2}
        )

    def test_legacy_series_media_type_still_matches_tvshows(self):
        self.add_series("legacy", "2026-01-01 10:00:00", media_type="series")

        self.assertEqual(self.catalog.count(media_type="tvshows"), 1)

    def test_search_spans_both_tables(self):
        self.add_movie("m1", "2026-01-01 10:00:00", title="Dune")
        self.add_series("s1", "2026-01-02 10:00:00", title="Dune Prophecy")

        self.assertEqual(self.catalog.count(search="dune"), 2)
        self.assertEqual(self.catalog.count(search="prophecy"), 1)

    def test_delete_by_id_finds_the_owning_table(self):
        self.add_movie("m1", "2026-01-01 10:00:00")
        self.add_series("s1", "2026-01-02 10:00:00")

        self.assertEqual(self.catalog.delete(["m1", "s1"]), 2)
        self.assertEqual(self.catalog.count(), 0)

    def test_delete_matching_re_evaluates_the_filter(self):
        self.add_movie("keep", "2026-01-01 10:00:00", status="completed")
        self.add_movie("drop1", "2026-01-02 10:00:00", status="failed")
        self.add_series("drop2", "2026-01-03 10:00:00", status="failed")

        deleted = self.catalog.delete_matching(status="failed")

        self.assertEqual(deleted, 2)
        self.assertEqual([n["notification_id"] for n in self.catalog.page()], ["keep"])

    def test_delete_matching_respects_search(self):
        self.add_movie("dune", "2026-01-01 10:00:00", title="Dune")
        self.add_movie("bear", "2026-01-02 10:00:00", title="The Bear")

        self.assertEqual(self.catalog.delete_matching(search="dune"), 1)
        self.assertEqual([n["notification_id"] for n in self.catalog.page()], ["bear"])

    def test_page_carries_display_fields_for_both_sources(self):
        self.add_movie("m1", "2026-01-01 10:00:00", title="Dune")
        self.add_series("s1", "2026-01-02 10:00:00", title="The Bear")
        with self.db.get_connection() as conn:
            conn.execute("UPDATE sonarr_webhook SET season_number = 2 WHERE notification_id = 's1'")
            conn.commit()

        by_id = {n["notification_id"]: n for n in self.catalog.page()}

        self.assertEqual(by_id["m1"]["media_type"], "movie")
        self.assertEqual(by_id["m1"]["display_title"], "Dune")
        self.assertEqual(by_id["s1"]["display_title"], "The Bear Season 2")
        # JSON columns are decoded, and blank ones do not become a crash.
        self.assertEqual(by_id["m1"]["languages"], [])
        self.assertEqual(by_id["s1"]["episodes"], [])


if __name__ == "__main__":
    unittest.main()
