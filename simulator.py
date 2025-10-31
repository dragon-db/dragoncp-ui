#!/usr/bin/env python3
"""
Transfer Simulator

Generates simulated transfers that write logs to the database and emit
Socket.IO events identical to real transfers. Useful for testing multi
transfer UI/log tabs without running rsync.
"""

from __future__ import annotations

import threading
import time
import random
from datetime import datetime
from typing import Dict, List, Optional


class TransferSimulator:
    """Simulate multiple concurrent transfers with periodic log updates."""

    def __init__(self, transfer_coordinator, socketio):
        self.transfer_coordinator = transfer_coordinator
        self.socketio = socketio
        self._threads: Dict[str, threading.Thread] = {}
        self._stops: Dict[str, threading.Event] = {}

    def start_simulations(
        self,
        count: int = 3,
        steps: int = 40,
        interval_seconds: float = 0.5,
        media_type_cycle: Optional[List[str]] = None,
        failure_rate: float = 0.0,
        min_duration_seconds: float = 300.0,
    ) -> List[str]:
        """Start N simulated transfers in background threads.

        Returns list of transfer_ids started.
        """
        media_types = media_type_cycle or ["movies", "tvshows", "anime"]

        # Ensure total runtime per transfer is at least min_duration_seconds
        # by increasing steps if needed (keep interval as provided for UI tick rate)
        try:
            total_duration = steps * float(interval_seconds)
            if total_duration < float(min_duration_seconds):
                import math
                steps = int(math.ceil(float(min_duration_seconds) / max(float(interval_seconds), 0.01)))
        except Exception:
            # Fallback to 5 minutes with default interval when inputs are invalid
            steps = int(300 / 0.5)

        started_ids: List[str] = []
        base_ts = int(time.time() * 1000)
        for i in range(count):
            transfer_id = f"sim_{base_ts}_{i}"
            media_type = media_types[i % len(media_types)]
            stop_event = threading.Event()
            self._stops[transfer_id] = stop_event

            thread = threading.Thread(
                target=self._simulate_transfer,
                args=(transfer_id, media_type, steps, interval_seconds, failure_rate, stop_event),
                daemon=True,
            )
            self._threads[transfer_id] = thread
            thread.start()
            started_ids.append(transfer_id)

        return started_ids

    def stop_all(self) -> int:
        """Signal all simulations to stop. Returns number signaled."""
        for stop in self._stops.values():
            stop.set()
        return len(self._stops)

    # Internal
    def _simulate_transfer(
        self,
        transfer_id: str,
        media_type: str,
        steps: int,
        interval_seconds: float,
        failure_rate: float,
        stop_event: threading.Event,
    ):
        # Pick names
        folder_name = self._pick_folder_name(media_type)
        season_name = None
        if media_type in ("tvshows", "anime"):
            season_name = f"Season {random.randint(1, 5)}"

        # Build paths
        source_path = f"/remote/{media_type}/{folder_name}"
        dest_path = f"/local/{media_type}/{folder_name}"
        
        # Register with queue manager to track this simulated transfer
        can_start, queue_status = self.transfer_coordinator.queue_manager.register_transfer(transfer_id, dest_path)
        
        # Create DB record
        self.transfer_coordinator.transfer_model.create({
            "transfer_id": transfer_id,
            "media_type": media_type,
            "folder_name": folder_name,
            "season_name": season_name,
            "episode_name": None,
            "source_path": source_path,
            "dest_path": dest_path,
            "transfer_type": "folder",
            "status": "pending",
        })

        # If queued (shouldn't happen in simulation but handle it)
        if queue_status == 'queued':
            self.transfer_coordinator.transfer_model.update(transfer_id, {
                "status": "queued",
                "progress": "Waiting in queue (simulated)...",
            })
            # For simulation, we'll still run it (not realistic but good for testing queue display)
        
        # Update to running
        self.transfer_coordinator.transfer_model.update(transfer_id, {
            "status": "running",
            "progress": "Transfer started (simulated)...",
            "start_time": datetime.now().isoformat(),
        })

        bytes_transferred = 0
        bytes_step = random.randint(2_000_000, 10_000_000)

        for step_index in range(1, steps + 1):
            if stop_event.is_set():
                self._finalize(transfer_id, status="cancelled", message="Simulation cancelled by user")
                return

            percent = int(step_index * 100 / steps)
            bytes_transferred += bytes_step
            speed = self._random_speed()
            log_line = f"{bytes_transferred:,}  {percent}%  {speed}/s"

            # Persist log and emit progress
            self.transfer_coordinator.transfer_model.add_log(transfer_id, log_line)
            transfer = self.transfer_coordinator.transfer_model.get(transfer_id)
            if self.socketio:
                self.socketio.emit(
                    "transfer_progress",
                    {
                        "transfer_id": transfer_id,
                        "progress": log_line,
                        "logs": transfer["logs"][-100:],
                        "log_count": len(transfer["logs"]),
                        "status": transfer.get("status", "running"),
                    },
                )

            time.sleep(interval_seconds)

        # Complete or fail
        if random.random() < max(0.0, min(failure_rate, 1.0)):
            self._finalize(transfer_id, status="failed", message="Transfer failed (simulated)")
        else:
            self._finalize(transfer_id, status="completed", message="Transfer completed successfully! (simulated)")

    def _finalize(self, transfer_id: str, status: str, message: str):
        # Unregister from queue manager when simulation completes
        self.transfer_coordinator.queue_manager.unregister_transfer(transfer_id)
        
        self.transfer_coordinator.transfer_model.update(
            transfer_id,
            {"status": status, "progress": message, "end_time": datetime.now().isoformat()},
        )
        transfer = self.transfer_coordinator.transfer_model.get(transfer_id)
        if self.socketio:
            self.socketio.emit(
                "transfer_complete",
                {
                    "transfer_id": transfer_id,
                    "status": status,
                    "message": message,
                    "logs": transfer["logs"][-100:],
                    "log_count": len(transfer["logs"]),
                },
            )

    def _random_speed(self) -> str:
        # Produce speeds like 1.23MB, 450KB, 2.5GB
        units = ["KB", "MB", "GB"]
        unit = random.choice(units)
        if unit == "KB":
            value = round(random.uniform(200, 900), 2)
        elif unit == "MB":
            value = round(random.uniform(1.0, 50.0), 2)
        else:
            value = round(random.uniform(0.5, 2.0), 2)
        # Present without trailing zeros if possible
        return f"{value:g}{unit}"

    def _pick_folder_name(self, media_type: str) -> str:
        movie_samples = [
            "Example.Movie.2024",
            "Test.Film.2023",
            "Sample.Title.2022",
        ]
        show_samples = [
            "Example.Show",
            "Demo.Series",
            "Sample.Anime",
        ]
        if media_type == "movies":
            return random.choice(movie_samples)
        return random.choice(show_samples)


