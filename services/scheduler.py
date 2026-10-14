#!/usr/bin/env python3
"""
The scheduler: one service that runs everything DragonCP does on a clock.

A job is one entry — a name, an interval, and the work. The interval is asked
for on every tick, so a job switched off in its settings stops at once and one
switched on starts without a restart; returning None means "off".

What every job gets without asking (decided 2026-10-02):

  * it never overlaps itself — a run still going means the next is skipped;
  * its last run, result and next run are kept, in memory and in the
    `scheduled_job` table, so the interface can show them after a restart;
  * failures are logged, and three in a row open an alert; one broken job
    never stops the others;
  * it can run once shortly after start-up, because a restart is exactly when
    webhooks get lost.

This release registers two jobs: the Sonarr and Radarr auto-scanners. Backup
cleanup and a disk-space check are meant to move in later as more entries.
"""

import json
import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger('dragoncp.scheduler')

TICK_SECONDS = 5.0
#: Failures in a row before an alert opens.
FAILURES_BEFORE_ALERT = 3


def _iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


@dataclass
class Job:
    name: str
    label: str
    description: str
    #: Seconds between runs, or None when the job is switched off.
    interval: Callable[[], Optional[float]]
    #: The work. Returns a dict; `ok` false or an exception counts as a failure,
    #: and `summary` is the sentence shown as the last result.
    run: Callable[[], Dict[str, Any]]
    #: How long after start-up the first run happens (None: wait a full interval).
    first_run_delay: Optional[float] = 60.0


@dataclass
class _State:
    running: bool = False
    last_run_at: Optional[float] = None
    last_finished_at: Optional[float] = None
    last_ok: Optional[bool] = None
    last_result: Dict[str, Any] = field(default_factory=dict)
    consecutive_failures: int = 0
    next_run_at: Optional[float] = None


class SchedulerService:
    def __init__(self, db_manager=None, alerts=None, clock: Callable[[], float] = time.time):
        self.db = db_manager
        self.alerts = alerts
        self.clock = clock
        self._jobs: Dict[str, Job] = {}
        self._state: Dict[str, _State] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_at: Optional[float] = None
        #: Tests run jobs in the calling thread.
        self.inline = False

    # ------------------------------------------------------------- registry

    def register(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.name] = job
            state = self._state.setdefault(job.name, _State())
            self._load(job.name, state)

    def jobs(self) -> List[str]:
        return list(self._jobs)

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._started_at = self.clock()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name='scheduler')
        self._thread.start()
        log.info('Scheduler started with %d job(s): %s', len(self._jobs),
                 ', '.join(self._jobs) or 'none')

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the scheduler must not die
                log.exception('Scheduler tick failed')
            self._stop.wait(TICK_SECONDS)

    # ----------------------------------------------------------------- tick

    def tick(self) -> None:
        now = self.clock()
        if self._started_at is None:
            self._started_at = now
        for name, job in list(self._jobs.items()):
            state = self._state[name]
            try:
                interval = job.interval()
            except Exception:  # noqa: BLE001
                log.exception('Could not read the interval for %s', name)
                interval = None
            if not interval:
                state.next_run_at = None
                continue

            if state.next_run_at is None:
                if state.last_run_at is not None:
                    state.next_run_at = max(state.last_run_at + interval,
                                            self._started_at + (job.first_run_delay or 0))
                elif job.first_run_delay is not None:
                    state.next_run_at = self._started_at + job.first_run_delay
                else:
                    state.next_run_at = now + interval

            if now >= state.next_run_at and not state.running:
                self._launch(job, interval)

    def run_now(self, name: str) -> bool:
        """Run a job now, whatever its schedule. False when it is already running."""
        job = self._jobs.get(name)
        if job is None:
            return False
        state = self._state[name]
        if state.running:
            return False
        try:
            interval = job.interval() or 0
        except Exception:  # noqa: BLE001
            interval = 0
        self._launch(job, interval)
        return True

    def _launch(self, job: Job, interval: float) -> None:
        state = self._state[job.name]
        with self._lock:
            if state.running:
                return
            state.running = True
            state.last_run_at = self.clock()
            state.next_run_at = state.last_run_at + interval if interval else None
        if self.inline:
            self._execute(job)
        else:
            threading.Thread(target=self._execute, args=(job,), daemon=True,
                             name=f"job-{job.name}").start()

    def _execute(self, job: Job) -> None:
        state = self._state[job.name]
        ok, result = False, {}
        try:
            result = job.run() or {}
            ok = bool(result.get('ok', True))
        except Exception as error:  # noqa: BLE001 - one job must not stop the others
            log.exception('Scheduled job %s failed', job.name)
            result = {'ok': False, 'summary': f"Failed: {error}",
                      'error': str(error), 'trace': traceback.format_exc()[-2000:]}
        finally:
            state.running = False
            state.last_finished_at = self.clock()
            state.last_ok = ok
            state.last_result = result
            state.consecutive_failures = 0 if ok else state.consecutive_failures + 1
            self._save(job.name, state)

        if self.alerts is not None:
            if not ok and state.consecutive_failures >= FAILURES_BEFORE_ALERT:
                self.alerts.job_failing(job.name, job.label,
                                        str(result.get('summary') or result.get('error') or ''),
                                        state.consecutive_failures)
            elif ok:
                self.alerts.job_recovered(job.name)

    # --------------------------------------------------------------- status

    def status(self) -> List[Dict[str, Any]]:
        out = []
        for name, job in self._jobs.items():
            state = self._state[name]
            try:
                interval = job.interval()
            except Exception:  # noqa: BLE001
                interval = None
            result = {k: v for k, v in (state.last_result or {}).items() if k != 'trace'}
            out.append({
                'name': name,
                'label': job.label,
                'description': job.description,
                'enabled': bool(interval),
                'interval_seconds': interval,
                'running': state.running,
                'last_run_at': _iso(state.last_run_at),
                'last_finished_at': _iso(state.last_finished_at),
                'last_ok': state.last_ok,
                'last_result': result,
                'consecutive_failures': state.consecutive_failures,
                'next_run_at': _iso(state.next_run_at) if interval else None,
            })
        return out

    def job_status(self, name: str) -> Optional[Dict[str, Any]]:
        return next((s for s in self.status() if s['name'] == name), None)

    # ---------------------------------------------------------- persistence

    def _load(self, name: str, state: _State) -> None:
        if self.db is None:
            return
        try:
            with self.db.get_connection() as conn:
                row = conn.execute("SELECT * FROM scheduled_job WHERE name = ?",
                                   (name,)).fetchone()
            if not row:
                return
            state.last_run_at = _epoch(row['last_run_at'])
            state.last_finished_at = _epoch(row['last_finished_at'])
            state.last_ok = None if row['last_ok'] is None else bool(row['last_ok'])
            try:
                state.last_result = json.loads(row['last_result'] or '{}')
            except (TypeError, ValueError):
                state.last_result = {}
            state.consecutive_failures = row['consecutive_failures'] or 0
        except Exception:  # noqa: BLE001
            log.exception('Could not load the state of job %s', name)

    def _save(self, name: str, state: _State) -> None:
        if self.db is None:
            return
        try:
            result = {k: v for k, v in (state.last_result or {}).items() if k != 'trace'}
            with self.db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO scheduled_job (name, last_run_at, last_finished_at, last_ok, "
                    "last_result, consecutive_failures, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET last_run_at = excluded.last_run_at, "
                    "last_finished_at = excluded.last_finished_at, last_ok = excluded.last_ok, "
                    "last_result = excluded.last_result, "
                    "consecutive_failures = excluded.consecutive_failures, "
                    "updated_at = excluded.updated_at",
                    (name, _iso(state.last_run_at), _iso(state.last_finished_at),
                     None if state.last_ok is None else int(state.last_ok),
                     json.dumps(result, default=str), state.consecutive_failures,
                     _iso(self.clock())))
                conn.commit()
        except Exception:  # noqa: BLE001
            log.exception('Could not save the state of job %s', name)


def _epoch(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    except (TypeError, ValueError):
        return None
