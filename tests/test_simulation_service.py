#!/usr/bin/env python3
"""
Tests for the simulation tool's safety guards.

Simulations generate files and delete them again, and they run in production, so
the guards that keep them away from real data are the part worth pinning: paths
must stay inside the simulation directory, cleanup must only remove rows
carrying the simulation flag, and the size ceiling must hold.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.database import DatabaseManager
from models.transfer import Transfer
from services.simulation_service import SimulationService, SCENARIOS, MAX_TOTAL_MB


class SimulationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        db_path = os.path.join(self.tempdir.name, "sim.db")
        self.db = DatabaseManager(os.path.relpath(db_path, REPO_ROOT))
        self.model = Transfer(self.db)

        self.coordinator = MagicMock()
        self.coordinator.transfer_model = self.model
        self.coordinator.db = self.db
        self.coordinator.queue_manager.MAX_CONCURRENT_TRANSFERS = 3

        self.service = SimulationService(config={}, coordinator=self.coordinator)
        # Keep generated files inside the temp dir rather than the checkout
        self.service.root = os.path.join(self.tempdir.name, ".simulations")

    # ------------------------------------------------------------------ paths

    def test_refuses_paths_outside_the_simulation_directory(self):
        """The guard standing between a bad path and someone's media library."""
        for outside in ("/etc", "/srv/media", os.path.join(self.service.root, "..", "escape")):
            with self.assertRaises(ValueError, msg=f"{outside} should be refused"):
                self.service._assert_inside_root(outside)

    def test_accepts_paths_inside_the_simulation_directory(self):
        os.makedirs(self.service.root, exist_ok=True)
        self.service._assert_inside_root(os.path.join(self.service.root, "run_1", "source"))

    # ---------------------------------------------------------------- cleanup

    def test_cleanup_removes_only_simulation_rows(self):
        self.model.create({
            "transfer_id": "real_one", "media_type": "movies", "folder_name": "Real Movie",
            "source_path": "/remote/real", "dest_path": "/local/real",
            "operation_type": "folder", "status": "completed",
        })
        self.model.create({
            "transfer_id": "sim_one", "media_type": "movies", "folder_name": "Simulation A",
            "source_path": "/sim/a", "dest_path": "/sim/a",
            "operation_type": "folder", "status": "completed", "is_simulation": True,
        })

        self.service.stop = lambda: 0  # no live processes in this test
        result = self.service.cleanup()

        self.assertEqual(result["transfers_removed"], 1)
        self.assertIsNone(self.model.get("sim_one"))
        self.assertIsNotNone(self.model.get("real_one"), "a real transfer was deleted")

    def test_cleanup_removes_generated_files(self):
        run_dir = os.path.join(self.service.root, "run_x", "source")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "simulation_1.bin"), "wb") as handle:
            handle.write(b"x" * 1024)

        self.service.stop = lambda: 0
        self.service.cleanup()

        self.assertFalse(os.path.exists(self.service.root))

    # ------------------------------------------------------------------ start

    def test_rejects_an_unknown_scenario(self):
        started, message, _ = self.service.start("../../etc/passwd")
        self.assertFalse(started)
        self.assertIn("Unknown scenario", message)

    def test_refuses_a_second_run_while_one_is_on_the_board(self):
        self.model.create({
            "transfer_id": "sim_running", "media_type": "movies", "folder_name": "Simulation A",
            "source_path": "/sim/a", "dest_path": "/sim/a",
            "operation_type": "folder", "status": "running", "is_simulation": True,
        })
        started, message, _ = self.service.start("slow_copy")
        self.assertFalse(started)
        self.assertIn("already", message.lower())

    def test_every_scenario_stays_within_the_size_ceiling(self):
        """Both copies live on disk at once, so the pair has to fit."""
        for key, scenario in SCENARIOS.items():
            peak = scenario.transfers * scenario.size_mb * 2
            self.assertLessEqual(
                peak, MAX_TOTAL_MB,
                f"scenario {key} would need {peak} MB, above the {MAX_TOTAL_MB} MB ceiling"
            )

    def test_running_real_transfers_ignores_simulations(self):
        self.model.create({
            "transfer_id": "sim_a", "media_type": "movies", "folder_name": "Simulation A",
            "source_path": "/s", "dest_path": "/d", "operation_type": "folder",
            "status": "running", "is_simulation": True,
        })
        self.assertEqual(self.service.running_real_transfers(), [])

        self.model.create({
            "transfer_id": "real_a", "media_type": "movies", "folder_name": "Real",
            "source_path": "/s", "dest_path": "/d2", "operation_type": "folder",
            "status": "running",
        })
        busy = self.service.running_real_transfers()
        self.assertEqual([t["transfer_id"] for t in busy], ["real_a"])

if __name__ == '__main__':
    unittest.main()
