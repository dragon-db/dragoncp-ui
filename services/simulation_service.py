#!/usr/bin/env python3
"""
DragonCP Simulation Service

Runs the real transfer pipeline against throwaway files on this machine, so an
admin can watch queueing, webhook status handling and the UI behave without
touching media or the remote server.

What makes it worth having is that it is not a mock. A simulation generates
fixture files locally, then hands them to transfer_coordinator.start_transfer()
- the same entry point a webhook or a manual sync uses. Everything downstream is
the production code: duplicate-destination detection, slot and path queueing,
promotion, rsync itself, progress parsing, pause, resume, cancel and completion.
The only difference is that rsync is pointed at local paths instead of over SSH,
and held to a speed limit so a copy takes long enough to watch.

Safety
------
- Fixtures live under a dedicated directory and nowhere else. Media paths are
  never read or written.
- Every row created is flagged is_simulation, so it can be told apart from real
  history and removed afterwards.
- Cleanup deletes only the simulation directory and only rows carrying the flag.
- Leftovers from a previous process are purged at startup.
- Total fixture size is capped, so a simulation cannot fill the disk.
"""

import os
import shutil
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# Everything a simulation writes lives under this directory, inside the app dir.
SIMULATION_DIRNAME = ".simulations"

# Hard ceiling on what one simulation may generate, whatever the caller asks for.
MAX_TOTAL_MB = 512
MAX_TRANSFERS = 8

# Written in 1 MB blocks of random bytes; --whole-file means rsync moves all of
# it regardless, so the content only has to be incompressible.
_BLOCK = None


def _block() -> bytes:
    global _BLOCK
    if _BLOCK is None:
        _BLOCK = os.urandom(1024 * 1024)
    return _BLOCK


class Scenario:
    """A named situation worth rehearsing."""

    def __init__(self, key: str, name: str, description: str, transfers: int,
                 size_mb: int, bwlimit_kbps: int, same_destination: bool = False,
                 with_webhooks: bool = True, media_type: str = "tvshows",
                 fail: bool = False):
        self.key = key
        self.name = name
        self.description = description
        self.transfers = transfers
        self.size_mb = size_mb
        self.bwlimit_kbps = bwlimit_kbps
        self.same_destination = same_destination
        self.with_webhooks = with_webhooks
        self.media_type = media_type
        self.fail = fail

    def to_dict(self) -> Dict:
        return {
            'key': self.key,
            'name': self.name,
            'description': self.description,
            'transfers': self.transfers,
            'size_mb': self.size_mb,
            'bwlimit_kbps': self.bwlimit_kbps,
            'same_destination': self.same_destination,
            'with_webhooks': self.with_webhooks,
            'fail': self.fail,
        }


SCENARIOS: Dict[str, Scenario] = {
    'queue_overflow': Scenario(
        key='queue_overflow',
        name='Fill the queue',
        description='Starts more copies than there are slots, so the extras wait '
                    'and are promoted as slots free up.',
        transfers=5, size_mb=24, bwlimit_kbps=2000,
    ),
    'path_conflict': Scenario(
        key='path_conflict',
        name='Same destination twice',
        description='Two copies aimed at one destination. The second waits for '
                    'the path rather than running alongside.',
        transfers=2, size_mb=24, bwlimit_kbps=2000, same_destination=True,
    ),
    'slow_copy': Scenario(
        key='slow_copy',
        name='Slow copy',
        description='One deliberately slow copy, long enough to pause, resume '
                    'and stop while it runs.',
        transfers=1, size_mb=48, bwlimit_kbps=600,
    ),
    'failure': Scenario(
        key='failure',
        name='Failed copy',
        description='A copy whose source disappears mid-run, so it fails the way '
                    'a broken transfer does and can be retried.',
        transfers=1, size_mb=32, bwlimit_kbps=1200, fail=True,
    ),
    'season_batch': Scenario(
        key='season_batch',
        name='Episode batch',
        description='Several episode arrivals for one season, batched onto a '
                    'single copy the way Sonarr imports do.',
        transfers=3, size_mb=16, bwlimit_kbps=1500, media_type='tvshows',
    ),
}


class SimulationService:
    """Creates, runs and cleans up simulations."""

    def __init__(self, config, coordinator, socketio=None):
        self.config = config
        self.coordinator = coordinator
        self.socketio = socketio
        self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.root = os.path.join(self.app_dir, SIMULATION_DIRNAME)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ paths

    def _run_dir(self, run_id: str) -> str:
        return os.path.join(self.root, run_id)

    def _assert_inside_root(self, path: str):
        """
        Refuse to touch anything outside the simulation directory.

        Cleanup deletes directories, so this is the check that stands between a
        bug in a path and someone's media library.
        """
        resolved = os.path.realpath(path)
        root = os.path.realpath(self.root)
        if resolved != root and not resolved.startswith(root + os.sep):
            raise ValueError(f"Refusing to touch a path outside {root}: {resolved}")

    # --------------------------------------------------------------- fixtures

    def _write_fixture(self, path: str, size_mb: int):
        block = _block()
        with open(path, 'wb') as handle:
            for _ in range(size_mb):
                handle.write(block)

    def _build_fixtures(self, run_dir: str, name: str, files: int, size_mb: int) -> str:
        source = os.path.join(run_dir, 'source', name)
        os.makedirs(source, exist_ok=True)
        per_file = max(1, size_mb // max(files, 1))
        for index in range(files):
            self._write_fixture(os.path.join(source, f"simulation_{index + 1}.bin"), per_file)
        return source

    # ------------------------------------------------------------------ state

    def running_real_transfers(self) -> List[Dict]:
        """Genuine (non-simulation) transfers currently occupying the queue."""
        return [
            transfer for transfer in self.coordinator.transfer_model.get_all(
                statuses=['running', 'pending', 'queued'], include_logs=False)
            if not transfer.get('is_simulation')
        ]

    def active(self) -> List[Dict]:
        """Every simulation row currently on the board, running or finished."""
        return [
            transfer for transfer in self.coordinator.transfer_model.get_all(include_logs=False)
            if transfer.get('is_simulation')
        ]

    def status(self) -> Dict:
        """
        What the Simulate tab needs in one call: the scenarios on offer, what is
        on the board and in which states, how much disk the fixtures hold, and
        whether real transfers are running - which decides whether starting one
        needs confirming.
        """
        rows = self.active()
        by_status: Dict[str, int] = {}
        for row in rows:
            by_status[row['status']] = by_status.get(row['status'], 0) + 1

        disk = 0
        if os.path.isdir(self.root):
            for base, _dirs, files in os.walk(self.root):
                for name in files:
                    try:
                        disk += os.path.getsize(os.path.join(base, name))
                    except OSError:
                        pass

        return {
            'scenarios': [scenario.to_dict() for scenario in SCENARIOS.values()],
            'total': len(rows),
            'by_status': by_status,
            'finished': all(
                row['status'] in ('completed', 'failed', 'cancelled') for row in rows
            ) if rows else True,
            'disk_bytes': disk,
            'real_transfers_running': len(self.running_real_transfers()),
            'max_concurrent': self.coordinator.queue_manager.MAX_CONCURRENT_TRANSFERS,
        }

    # ------------------------------------------------------------------- start

    def start(self, scenario_key: str) -> Tuple[bool, str, Dict]:
        """
        Generate the fixtures for a scenario and hand each transfer to the
        coordinator, the same way a webhook or a manual sync does.

        Refuses when a simulation is already on the board, when the scenario
        would exceed the size ceiling, or when the disk is too full. Anything
        created before a failure is cleaned up rather than left behind.

        Returns (started, message, {run_id, transfer_ids}).
        """
        scenario = SCENARIOS.get(scenario_key)
        if not scenario:
            return False, f"Unknown scenario: {scenario_key}", {}

        with self._lock:
            if self.active():
                return False, "A simulation is already on the board. Clear it first.", {}

            transfers = min(scenario.transfers, MAX_TRANSFERS)
            # Both copies sit on disk at once - the fixtures and what rsync
            # writes - so the ceiling has to count the pair, not just the source.
            peak_mb = transfers * scenario.size_mb * 2
            if peak_mb > MAX_TOTAL_MB:
                return False, (
                    f"That needs {peak_mb} MB of free space, above the {MAX_TOTAL_MB} MB limit"
                ), {}

            free_mb = shutil.disk_usage(self.app_dir).free // (1024 * 1024)
            if free_mb < peak_mb * 2:
                return False, (
                    f"Not enough free space: the simulation needs about {peak_mb} MB "
                    f"and only {free_mb} MB is free"
                ), {}

            run_id = f"sim_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
            run_dir = self._run_dir(run_id)
            self._assert_inside_root(run_dir)
            os.makedirs(run_dir, exist_ok=True)

            started: List[str] = []
            try:
                for index in range(transfers):
                    started.append(
                        self._start_one(scenario, run_id, run_dir, index, transfers)
                    )
            except Exception as error:
                print(f"❌ Simulation failed to start: {error}")
                import traceback
                traceback.print_exc()
                self.cleanup()
                return False, f"Could not start the simulation: {error}", {}

            if scenario.fail:
                # Pull the source out from under the copy once it is moving, so
                # rsync fails the way a genuinely broken transfer does.
                threading.Thread(
                    target=self._break_source, args=(run_dir,), daemon=True
                ).start()

            return True, (
                f"{scenario.name} started with {len(started)} transfer"
                f"{'' if len(started) == 1 else 's'}"
            ), {'run_id': run_id, 'transfer_ids': started}

    def _start_one(self, scenario: Scenario, run_id: str, run_dir: str,
                   index: int, total: int) -> str:
        title = f"Simulation {chr(ord('A') + index)}"
        season = f"Season {index + 1:02d}" if scenario.media_type != 'movies' else None

        # A path-conflict simulation deliberately aims everything at one folder.
        slot = 0 if scenario.same_destination else index
        folder_name = f"{title if not scenario.same_destination else 'Simulation Shared'}"

        source_path = self._build_fixtures(
            run_dir, f"slot_{slot}", files=2, size_mb=scenario.size_mb
        )
        dest_path = os.path.join(run_dir, 'dest', f"slot_{slot}")
        self._assert_inside_root(source_path)
        self._assert_inside_root(dest_path)
        os.makedirs(dest_path, exist_ok=True)

        transfer_id = f"simulation_{run_id}_{index}"

        notification_id = None
        if scenario.with_webhooks:
            notification_id = self._create_notification(
                scenario, transfer_id, folder_name, season, dest_path
            )

        started, state = self.coordinator.start_transfer(
            transfer_id=transfer_id,
            source_path=source_path,
            dest_path=dest_path,
            operation_type='folder',
            media_type=scenario.media_type,
            folder_name=folder_name,
            season_name=season,
            is_simulation=True,
            simulation_bwlimit=scenario.bwlimit_kbps,
        )
        if not started:
            raise RuntimeError(f"coordinator refused the transfer ({state})")

        # Mirror what the webhook service does once a transfer exists, so the
        # notification's status tracks the transfer through the queue.
        if notification_id:
            self._link_notification(scenario, notification_id, transfer_id, state)

        print(f"🎭 Simulation transfer {transfer_id} -> {state}")
        return transfer_id

    # ---------------------------------------------------------------- webhooks

    def _create_notification(self, scenario: Scenario, transfer_id: str,
                             folder_name: str, season: Optional[str],
                             dest_path: str) -> Optional[str]:
        """
        Create a webhook notification the same shape a real import produces, so
        the status handling between a notification and its transfer is
        exercised rather than assumed.
        """
        try:
            now = datetime.now().isoformat()
            if scenario.media_type == 'movies':
                model = self.coordinator.webhook_model
                notification_id = f"sim_movie_{transfer_id}"
                model.create({
                    'notification_id': notification_id,
                    'title': folder_name,
                    'year': 2024,
                    'folder_path': dest_path,
                    'file_path': os.path.join(dest_path, 'simulation_1.bin'),
                    'quality': 'Simulation-1080p',
                    'size': scenario.size_mb * 1024 * 1024,
                    'requested_by': 'simulation',
                    'status': 'pending',
                    'created_at': now,
                }, '{"eventType": "Simulation"}')
            else:
                model = self.coordinator.series_webhook_model
                notification_id = f"sim_series_{transfer_id}"
                model.create({
                    'notification_id': notification_id,
                    'media_type': scenario.media_type,
                    'series_title': folder_name,
                    'series_path': os.path.dirname(dest_path),
                    'season_path': dest_path,
                    'season_number': 1,
                    'episode_count': 2,
                    'requested_by': 'simulation',
                    'release_title': f"{folder_name}.S01.Simulation",
                    'status': 'pending',
                    'created_at': now,
                }, '{"eventType": "Simulation"}')

            self._flag_notification(scenario, notification_id)
            return notification_id
        except Exception as error:
            # A simulation is still useful without the notification half
            print(f"⚠️  Simulation notification could not be created: {error}")
            return None

    def _flag_notification(self, scenario: Scenario, notification_id: str):
        table = 'radarr_webhook' if scenario.media_type == 'movies' else 'sonarr_webhook'
        with self.coordinator.db.get_connection() as conn:
            conn.execute(
                f"UPDATE {table} SET is_simulation = 1 WHERE notification_id = ?",
                (notification_id,)
            )
            conn.commit()

    def _link_notification(self, scenario: Scenario, notification_id: str,
                           transfer_id: str, state: str):
        """Track the transfer's queue state on the notification, as the real
        webhook path does."""
        status = {
            'running': 'syncing',
            'QUEUED_SLOT': 'QUEUED_SLOT',
            'QUEUED_PATH': 'QUEUED_PATH',
        }.get(state, 'syncing')

        model = (self.coordinator.webhook_model if scenario.media_type == 'movies'
                 else self.coordinator.series_webhook_model)
        try:
            model.update(notification_id, {'transfer_id': transfer_id, 'status': status})
        except Exception as error:
            print(f"⚠️  Could not link simulation notification: {error}")

    # ----------------------------------------------------------------- failure

    def _break_source(self, run_dir: str):
        """Delete the fixture files mid-copy so rsync reports a real failure."""
        import time
        time.sleep(4)
        source_root = os.path.join(run_dir, 'source')
        try:
            self._assert_inside_root(source_root)
            for base, _dirs, files in os.walk(source_root):
                for name in files:
                    os.remove(os.path.join(base, name))
            print("🎭 Simulation source removed to force a failure")
        except Exception as error:
            print(f"⚠️  Could not force the simulation failure: {error}")

    # ----------------------------------------------------------------- cleanup

    def stop(self) -> int:
        """Cancel anything still moving, leaving the rows for inspection."""
        stopped = 0
        for transfer in self.active():
            if transfer['status'] in ('running', 'pending', 'queued', 'paused'):
                if self.coordinator.cancel_transfer(transfer['transfer_id']):
                    stopped += 1
        return stopped

    def cleanup(self) -> Dict:
        """
        Remove every simulation row and every generated file.

        Rows are deleted by the is_simulation flag and files only from inside
        the simulation directory, so neither can reach real data.
        """
        self.stop()

        with self.coordinator.db.get_connection() as conn:
            transfers = conn.execute(
                "DELETE FROM transfers WHERE is_simulation = 1"
            ).rowcount
            movies = conn.execute(
                "DELETE FROM radarr_webhook WHERE is_simulation = 1"
            ).rowcount
            series = conn.execute(
                "DELETE FROM sonarr_webhook WHERE is_simulation = 1"
            ).rowcount
            conn.commit()

        removed_files = False
        if os.path.isdir(self.root):
            try:
                self._assert_inside_root(self.root)
                shutil.rmtree(self.root)
                removed_files = True
            except Exception as error:
                print(f"⚠️  Could not remove the simulation directory: {error}")

        print(f"🧹 Simulation cleared: {transfers} transfer(s), "
              f"{movies + series} notification(s), files removed: {removed_files}")

        return {
            'transfers_removed': transfers,
            'notifications_removed': movies + series,
            'files_removed': removed_files,
        }

    def purge_leftovers(self):
        """
        Clear anything a previous process left behind.

        Called at startup: a simulation interrupted by a restart would otherwise
        leave rows stuck as running and fixture files on disk forever.
        """
        try:
            leftovers = self.active()
            if leftovers or os.path.isdir(self.root):
                print(f"🧹 Clearing {len(leftovers)} simulation row(s) from a previous run")
                self.cleanup()
        except Exception as error:
            print(f"⚠️  Could not clear old simulations: {error}")
