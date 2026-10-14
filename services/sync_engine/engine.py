#!/usr/bin/env python3
"""
The sync engine: one pipeline every sync goes through.

    Receive → Identify → Batch → Ready check → Safety check
            → Queue → Transfer → Finish → Tell

A webhook, the auto-scanner, a manual press, an Explore plan, a restart, a
restore and a simulation all enter through `submit()`. What differs between
them is written in `stages.KINDS` — which stages run, which run differently,
and the sentence explaining every skip — and nowhere else.

The engine orchestrates; it does not copy files. `TransferCoordinator` and the
queue it owns still start, monitor, pause and finish rsync. The engine decides
*when* a transfer is handed over, keeps every batch in the database so a
restart cannot lose it, and writes down what each stage did in words an admin
can read.

Two rules carry most of the weight:

  * **One batch per folder.** A request for a folder that already has an open
    batch joins it. A request for a folder that is copying right now joins the
    single follow-up batch behind it. Joining and the batch starting its copy
    take the same lock, so a webhook lands in one or the other — never between.
  * **One question at a time.** A run is only ever worked on by one thread, so
    a burst of webhooks for a season never multiplies calls to Sonarr.
"""

import logging
import os
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from actor import Actor, acting_as, current_actor
from models.sync_run import (
    MOVIE_TABLE,
    SERIES_TABLE,
    SyncRunStore,
    episode_label,
    utc_now_iso,
)
from services.sync_engine import stages as S
from services.sync_engine.units import (
    IdentifyError,
    Unit,
    from_movie_notification,
    from_paths,
    from_series_notification,
    unit_key as make_unit_key,
)

log = logging.getLogger('dragoncp.sync_engine')

#: The first question waits this long, so a burst of webhooks lands in the
#: batch before Sonarr is asked anything.
SETTLE_SECONDS = 10
#: Between questions: Sonarr's own "time left", kept inside these bounds.
RECHECK_MIN_SECONDS = 10
RECHECK_MAX_SECONDS = 300
RECHECK_DEFAULT_SECONDS = 30
#: The longest a batch waits for downloads still moving (decided 2026-10-02).
READY_CAP_SECONDS = 30 * 60
#: The old timer, used whenever Sonarr cannot answer: 60 s, plus 60 s for
#: every later webhook, never past 15 minutes from the first.
TIMER_DEFAULT_SECONDS = 60
TIMER_CAP_SECONDS = 15 * 60

POOL_WORKERS = 4

#: How the transfer service words a copy whose outcome a restart lost.
UNKNOWN_RESULT_PREFIX = 'Result unknown'

#: Webhook statuses a manual sync may act on.
SYNCABLE_STATUSES = ('pending', 'failed', 'cancelled', 'MANUAL_SYNC_REQUIRED',
                     'manual_sync_required', 'READY_FOR_TRANSFER')
#: Webhook statuses that already have an outcome or a transfer in flight.
SETTLED_STATUSES = ('completed',)

#: Where a run sits while its ready check is still deciding.
READY_CHECK_STATES = (S.WAITING_STATE, S.HELD)

#: Explore's buttons, by the mode its run carries.
EXPLORE_ACTIONS = {'sync': 'Sync', 'download': 'Download', 'replace': 'Replace'}

_TRANSFER_PREFIX = {
    S.SONARR_WEBHOOK: 'series_webhook',
    S.RADARR_WEBHOOK: 'webhook',
    S.MANUAL: 'transfer',
    S.AUTO_SCANNER: 'scanner',
    S.RESTART: 'restart',
    S.EXPLORE: 'explore',
    S.SIMULATION: 'simulation',
    S.RESTORE: 'restore',
}

#: Kinds an automatic process starts. One a person released — Sync, Go now, a
#: restart joining it — is a manual sync from then on, whatever opened it.
_AUTOMATIC_KINDS = (S.SONARR_WEBHOOK, S.RADARR_WEBHOOK, S.AUTO_SCANNER)


def _started_by_a_person(run: Dict[str, Any]) -> bool:
    return run['kind'] not in _AUTOMATIC_KINDS or bool(run.get('go_now'))


def _named_files_only(operation_type: Optional[str],
                      extra: Optional[Dict[str, Any]] = None) -> bool:
    """A copy of exactly what was named (one file, or an Explore list), not the folder.

    Such a copy stands alone: it never joins a batch, and no webhook joins it.
    Joined to a batch it would be widened into a whole-folder mirror, with
    deletions nobody approved; joined by a webhook, it would mark that episode
    synced without ever looking for it. Where both want the same folder, the
    queue keeps them apart.
    """
    return (operation_type == 'file'
            or str(operation_type or '').startswith('explore_')
            or bool((extra or {}).get('explore_files_from')))


def _request_stands_alone(request: 'SyncRequest', policy: S.KindPolicy) -> bool:
    return not policy.mergeable or _named_files_only(
        request.operation_type, request.extra_fields or request.options.get('extra_fields'))


_SYNC_LABEL = {
    S.SONARR_WEBHOOK: 'Automated Sync',
    S.RADARR_WEBHOOK: 'Automated Sync',
    S.AUTO_SCANNER: 'Auto-scanner',
    S.MANUAL: 'Manual Sync',
    S.RESTART: 'Manual Sync (restart)',
    S.EXPLORE: 'Explore',
    S.RESTORE: 'Restore',
    S.SIMULATION: 'Simulation',
}


def _now_iso() -> str:
    return utc_now_iso()


def _clock_iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _hhmmss(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime('%H:%M:%S')


def _duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds} s"
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"{minutes} min"
    return f"{seconds // 3600} h {(seconds % 3600) // 60} min"


def _actor_from_run(run: Dict[str, Any]) -> Actor:
    return Actor(kind=run.get('requested_by_kind') or 'system',
                 name=run.get('requested_by_name') or 'system',
                 account_id=run.get('requested_by_account_id'))


# ---------------------------------------------------------------------------
# Requests and results
# ---------------------------------------------------------------------------

@dataclass
class SyncRequest:
    """Everything one request for a sync carries into the pipeline."""

    kind: str
    media_type: str = ''
    #: 'sonarr' or 'radarr' when a service is behind the request.
    source: Optional[str] = None
    #: Webhooks this request carries: (table, notification_id).
    webhooks: List[Tuple[str, str]] = field(default_factory=list)
    #: A unit named directly, for requests that do not come from a webhook.
    source_path: str = ''
    dest_path: str = ''
    folder_name: str = ''
    season_name: Optional[str] = None
    season_number: Optional[int] = None
    title: str = ''
    operation_type: str = 'folder'
    actor: Optional[Actor] = None
    #: Kind-specific facts kept on the run: ids, an Explore plan, a finding.
    options: Dict[str, Any] = field(default_factory=dict)
    #: Automatic sync is off: open the batch, then wait for a person.
    hold: bool = False
    #: The admin chose to go ahead even if the safety check fails.
    force_safety: bool = False
    is_simulation: bool = False
    simulation_bwlimit: Optional[int] = None
    #: Columns handed to the transfer row (Explore's file list).
    extra_fields: Dict[str, Any] = field(default_factory=dict)
    #: A transfer id to use (simulation, restore) or reuse (restart).
    transfer_id: Optional[str] = None
    #: What was already checked before this reached the engine (Explore, restore).
    safety_summary: str = ''
    #: How Receive describes this request. Derived when empty.
    note: str = ''
    #: A parent link set by the caller (restart → retry of).
    parent_run_id: Optional[str] = None
    parent_relation: Optional[str] = None


@dataclass
class SubmitResult:
    ok: bool
    run_id: Optional[str]
    #: opened | joined | follow_up | promoted | skipped | failed | held | cancelled
    action: str
    state: str
    message: str
    transfer_id: Optional[str] = None
    #: running | QUEUED_SLOT | QUEUED_PATH, when the queue was reached in-line.
    queue_state: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            'ok': self.ok, 'run_id': self.run_id, 'action': self.action,
            'state': self.state, 'message': self.message,
            'transfer_id': self.transfer_id, 'queue_state': self.queue_state,
        }


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

class SyncEngine:
    """Runs every sync through the pipeline and remembers what each stage did."""

    def __init__(self, store: SyncRunStore, coordinator=None, media_index=None,
                 settings=None, socketio=None, alerts=None, config=None,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.coordinator = coordinator
        self.media_index = media_index
        self.settings = settings
        self.socketio = socketio
        self.alerts = alerts
        self.config = config
        self.clock = clock

        self._unit_locks: Dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._inflight: set = set()
        self._rekick: set = set()
        self._inflight_lock = threading.Lock()
        self._kick: 'queue.Queue[str]' = queue.Queue()
        self._stop = threading.Event()
        self._pool: Optional[ThreadPoolExecutor] = None
        self._thread: Optional[threading.Thread] = None
        #: Synchronous mode for tests: work is done in the caller's thread.
        self.inline = False

    # ------------------------------------------------------------- lifecycle

    def start(self, recover: bool = True) -> None:
        """Begin working. Recovery runs first, so a restart says what it found."""
        if self._thread and self._thread.is_alive():
            return
        if recover:
            try:
                from services.sync_engine.recovery import recover_after_restart
                recover_after_restart(self)
            except Exception:  # noqa: BLE001 - startup must survive recovery
                log.exception('Sync engine recovery failed')
        self._stop.clear()
        self._pool = ThreadPoolExecutor(max_workers=POOL_WORKERS,
                                        thread_name_prefix='sync-engine')
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name='sync-engine')
        self._thread.start()
        log.info('Sync engine started')

    def stop(self) -> None:
        self._stop.set()
        self._kick.put('')
        if self._pool:
            self._pool.shutdown(wait=False)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                run_id = self._kick.get(timeout=1.0)
                if run_id:
                    self._dispatch(run_id)
            except queue.Empty:
                pass
            try:
                for run_id in self.store.due(self.clock()):
                    self._dispatch(run_id)
            except Exception:  # noqa: BLE001 - the loop must not die
                log.exception('Sync engine tick failed')

    def kick(self, run_id: str) -> None:
        """Ask for a run to be worked on now."""
        if self.inline:
            self._run_advance(run_id)
            return
        self._kick.put(run_id)

    def _dispatch(self, run_id: str) -> None:
        with self._inflight_lock:
            if run_id in self._inflight:
                self._rekick.add(run_id)
                return
            self._inflight.add(run_id)
        if self._pool is None:
            threading.Thread(target=self._run_advance_owned, args=(run_id,),
                             daemon=True).start()
        else:
            self._pool.submit(self._run_advance_owned, run_id)

    def _run_advance_owned(self, run_id: str) -> None:
        try:
            self._advance_as_requester(run_id)
        finally:
            with self._inflight_lock:
                self._inflight.discard(run_id)
                again = run_id in self._rekick
                self._rekick.discard(run_id)
            if again:
                self._dispatch(run_id)

    def _run_advance(self, run_id: str) -> None:
        """Inline advance (tests and synchronous kinds): same guard, same thread."""
        with self._inflight_lock:
            if run_id in self._inflight:
                self._rekick.add(run_id)
                return
            self._inflight.add(run_id)
        try:
            self._advance_as_requester(run_id)
        finally:
            with self._inflight_lock:
                self._inflight.discard(run_id)
                again = run_id in self._rekick
                self._rekick.discard(run_id)
            if again:
                self._run_advance(run_id)

    def _advance_as_requester(self, run_id: str) -> None:
        run = self.store.get(run_id)
        if not run:
            return
        try:
            with acting_as(_actor_from_run(run)):
                self._advance(run_id)
        except Exception as error:  # noqa: BLE001 - a run must fail, not the engine
            log.exception('Sync run %s failed while advancing', run_id)
            self._fail_run(run_id, run.get('current_stage') or S.READY,
                           f"Something went wrong inside the sync engine: {error}")

    def unit_lock(self, key: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._unit_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._unit_locks[key] = lock
            return lock

    def _run_lock(self, run: Dict[str, Any]) -> threading.RLock:
        return self.unit_lock(run.get('unit_key') or make_unit_key(run.get('dest_path') or ''))

    @contextmanager
    def _still(self, run_id: str, *states: str):
        """The run as it is now, under its folder's lock, or None if it moved on.

        Asking Sonarr and the dry run each take seconds, and nothing is locked
        while they do: someone can cancel the sync, or mark it done, in that
        time. What a step decides from the answer is written inside this block,
        and only while the run is still in `states`, so a late answer can never
        undo a cancel and start a copy nobody wants.
        """
        run = self.store.get(run_id)
        if not run:
            yield None
            return
        with self._run_lock(run):
            current = self.store.get(run_id)
            yield current if current and current['state'] in states else None

    # -------------------------------------------------------------- helpers

    def _setting_int(self, key: str, fallback: int) -> int:
        try:
            if self.settings is not None:
                return int(self.settings.get_int(key, fallback))
        except Exception:  # noqa: BLE001
            pass
        return fallback

    def _wait_seconds(self) -> int:
        return max(30, min(TIMER_CAP_SECONDS,
                           self._setting_int('SERIES_ANIME_SYNC_WAIT_TIME',
                                             TIMER_DEFAULT_SECONDS)))

    def _stage(self, run_id: str, stage: str, status: str, summary: Optional[str] = None,
               detail: Optional[Dict[str, Any]] = None, level: Optional[str] = None,
               event: bool = True) -> None:
        """Set a stage's outcome and write its sentence to the stage's log."""
        self.store.set_stage(run_id, stage, status, summary, detail)
        if summary and event:
            if level is None:
                level = {S.FAILED: 'error', S.REFUSED: 'warning',
                         S.PASSED: 'success'}.get(status, 'info')
            self._event(run_id, stage, summary, level, detail if detail else None)
        self._emit_run(run_id)

    def _event(self, run_id: str, stage: str, message: str, level: str = 'info',
               data: Optional[Dict[str, Any]] = None) -> None:
        event = self.store.add_event(run_id, stage, message, level, data)
        if self.socketio is not None:
            try:
                self.socketio.emit('sync_run_event', {'run_id': run_id, 'event': event})
            except Exception:  # noqa: BLE001 - a missed socket event is not a failure
                pass

    def _emit_run(self, run_id: str) -> None:
        if self.socketio is None:
            return
        try:
            run = self.store.get(run_id)
            if not run:
                return
            self.socketio.emit('sync_run_updated', self.summarise(run))
        except Exception:  # noqa: BLE001
            pass

    def _update(self, run_id: str, **fields) -> None:
        self.store.update(run_id, **fields)
        self._emit_run(run_id)

    def _set_state(self, run_id: str, state: str, stage: Optional[str] = None,
                   **fields) -> None:
        fields['state'] = state
        if stage:
            fields['current_stage'] = stage
        if state in S.TERMINAL_STATES and 'finished_at' not in fields:
            fields['finished_at'] = _now_iso()
        self._update(run_id, **fields)

    def _skip_rest(self, run_id: str, from_stage: str, reason: str) -> None:
        """Mark every stage after `from_stage` that never ran as skipped, with why."""
        stages = self.store.stages(run_id)
        after = S.STAGE_IDS[S.stage_index(from_stage) + 1:]
        for stage in after:
            if (stages.get(stage) or {}).get('status') in (S.PENDING, None):
                self.store.set_stage(run_id, stage, S.SKIPPED, reason)
        self._emit_run(run_id)

    def _fail_run(self, run_id: str, stage: str, message: str) -> None:
        run = self.store.get(run_id)
        if not run or run['state'] in S.TERMINAL_STATES:
            return
        self._stage(run_id, stage, S.FAILED, message)
        self._skip_rest(run_id, stage, 'Not reached: an earlier stage failed.')
        self._set_state(run_id, S.FAILED_STATE, stage, outcome='failed',
                        outcome_message=message)
        self.store.update_webhooks(run_id, {'status': 'failed', 'error_message': message},
                                   exclude_status=SETTLED_STATUSES)

    def _transfer_id_for(self, kind: str) -> str:
        prefix = _TRANSFER_PREFIX.get(kind, 'sync')
        return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    def _path_service(self):
        return getattr(self.coordinator, 'path_service', None)

    def _destination_roots(self) -> List[str]:
        config = self.config or getattr(self.coordinator, 'config', None)
        if config is None:
            return []
        try:
            return list(config.get_destination_paths())
        except Exception:  # noqa: BLE001
            return []

    def _webhook_row(self, table: str, notification_id: str) -> Optional[Dict[str, Any]]:
        model = None
        if self.coordinator is not None:
            model = (self.coordinator.series_webhook_model if table == SERIES_TABLE
                     else self.coordinator.webhook_model)
        if model is None:
            return None
        try:
            return model.get(notification_id)
        except Exception:  # noqa: BLE001
            return None

    # ---------------------------------------------------------------- identify

    def identify(self, request: SyncRequest) -> Unit:
        """Work out what a request is about. Raises IdentifyError when it cannot."""
        if request.webhooks and not request.dest_path:
            table, notification_id = request.webhooks[0]
            row = self._webhook_row(table, notification_id)
            if not row:
                raise IdentifyError(f"The webhook {notification_id} no longer exists")
            path_service = self._path_service()
            if path_service is None:
                raise IdentifyError('No path service is available to build the folders')
            if table == SERIES_TABLE:
                unit = from_series_notification(row, path_service)
            else:
                unit = from_movie_notification(row, path_service)
            return unit

        roots = None if request.is_simulation else self._destination_roots()
        return from_paths(
            request.media_type, request.source_path, request.dest_path,
            folder_name=request.folder_name, season_name=request.season_name,
            title=request.title, operation_type=request.operation_type,
            season_number=request.season_number, allowed_roots=roots,
            ids=request.options.get('ids'),
        )

    # ------------------------------------------------------------------ submit

    def submit(self, request: SyncRequest, wait: bool = False) -> SubmitResult:
        """Put one request into the pipeline.

        Receive, Identify and Batch happen here, in the caller's thread, under
        the folder's lock. What follows — the ready check, the dry run, the
        hand-off to the queue — runs in the engine's own workers, unless `wait`
        asks for it to happen here (Explore, simulations, restores: callers that
        need to know at once whether the queue took the transfer).
        """
        policy = S.policy(request.kind)
        actor = request.actor or current_actor()
        request.actor = actor

        try:
            unit = self.identify(request)
        except IdentifyError as error:
            return self._record_identify_failure(request, str(error))

        key = unit.unit_key
        with self.unit_lock(key):
            result = self._batch(request, unit, policy)

        # A promoted batch was kicked by `_promote` itself.
        if result.action in ('opened', 'follow_up') and result.run_id:
            if wait:
                self._run_advance(result.run_id)
                run = self.store.get(result.run_id) or {}
                result.state = run.get('state', result.state)
                result.transfer_id = run.get('transfer_id')
                result.queue_state = (run.get('options') or {}).get('queue_state')
                if run.get('state') in (S.FAILED_STATE, S.REFUSED_STATE):
                    result.ok = False
                    result.message = run.get('outcome_message') or result.message
            else:
                self.kick(result.run_id)
        return result

    def _record_identify_failure(self, request: SyncRequest, reason: str) -> SubmitResult:
        """A request that names nothing syncable is still written down."""
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        actor = request.actor or current_actor()
        self.store.create({
            'run_id': run_id, 'kind': request.kind, 'source': request.source,
            'media_type': request.media_type, 'state': S.FAILED_STATE,
            'current_stage': S.IDENTIFY, 'title': request.title or None,
            'requested_by_kind': actor.kind, 'requested_by_name': actor.name,
            'requested_by_account_id': actor.account_id,
            'is_simulation': 1 if request.is_simulation else 0,
            'outcome': 'failed', 'outcome_message': reason,
            'finished_at': _now_iso(), 'options': dict(request.options),
        })
        self._stage(run_id, S.RECEIVE, S.PASSED, self._receive_note(request, None))
        self._stage(run_id, S.IDENTIFY, S.FAILED, f"Could not work out what to sync: {reason}")
        self._skip_rest(run_id, S.IDENTIFY, 'Not reached: nothing to sync was identified.')
        for table, notification_id in request.webhooks:
            self.store.attach_webhook(table, notification_id, run_id)
        self.store.update_webhooks(run_id, {'status': 'failed', 'error_message': reason},
                                   exclude_status=SETTLED_STATUSES)
        return SubmitResult(False, run_id, 'failed', S.FAILED_STATE, reason)

    def _receive_note(self, request: SyncRequest, unit: Optional[Unit]) -> str:
        if request.note:
            return request.note
        who = request.actor.label if request.actor else 'Someone'
        what = unit.label if unit else (request.title or 'something')
        if request.kind == S.SONARR_WEBHOOK:
            labels = self._webhook_labels(request.webhooks)
            return f"Sonarr webhook for {what}{(' — ' + labels) if labels else ''}."
        if request.kind == S.RADARR_WEBHOOK:
            return f"Radarr webhook for {what}."
        if request.kind == S.AUTO_SCANNER:
            finding = request.options.get('finding') or 'found a gap'
            return f"The auto-scanner {finding} for {what}."
        if request.kind == S.MANUAL:
            return f"{who} asked to sync {what}."
        if request.kind == S.EXPLORE:
            # Named after the button that was pressed — Sync, Download or
            # Replace — because that is what the admin remembers doing.
            action = EXPLORE_ACTIONS.get((request.options or {}).get('mode'), 'Sync')
            return f"{who} pressed {action} in Explore for {what}."
        if request.kind == S.RESTART:
            return f"{who} restarted the transfer for {what}."
        if request.kind == S.RESTORE:
            return f"{who} restored {what} from a backup."
        if request.kind == S.SIMULATION:
            return f"Simulation started by {who}: {what}."
        return f"Sync requested for {what}."

    def _webhook_labels(self, webhooks: Sequence[Tuple[str, str]]) -> str:
        labels = []
        for table, notification_id in webhooks[:6]:
            row = self._webhook_row(table, notification_id)
            if row and table == SERIES_TABLE:
                labels.append(episode_label(row))
        if len(webhooks) > 6:
            labels.append(f"+{len(webhooks) - 6} more")
        return ', '.join(labels)

    # ------------------------------------------------------------------- batch

    def _batch(self, request: SyncRequest, unit: Unit, policy: S.KindPolicy) -> SubmitResult:
        """Join a batch, open a follow-up, or open a new one. Caller holds the lock."""
        key = unit.unit_key
        joins = not _request_stands_alone(request, policy)

        if joins:
            open_run = self.store.find_open(key)
            if open_run is not None and self._transfer_vanished(open_run):
                self._close_orphan(open_run)
                open_run = self.store.find_open(key)
            if open_run is not None:
                return self._join(open_run, request, unit)

        active = self.store.find_active(key) if joins else None
        if active is not None and request.kind == S.AUTO_SCANNER:
            # Already copying: whatever the scanner found arrives with it, and
            # if anything is still missing afterwards the next scan sees it.
            self._event(active['run_id'], S.BATCH,
                        'The auto-scanner also found this folder incomplete; it is '
                        'being copied right now, so nothing new was started.')
            return SubmitResult(True, active['run_id'], 'skipped', active['state'],
                                f"Already copying {unit.label}")

        run = self._open_run(request, unit, policy,
                             parent=active, relation='follow_up' if active else None)
        return SubmitResult(True, run['run_id'],
                            'follow_up' if active else ('held' if request.hold else 'opened'),
                            run['state'], self._opened_message(run, active))

    def _transfer_vanished(self, run: Dict[str, Any]) -> bool:
        """A run waiting on a transfer whose row is gone — deleted from the list."""
        if run['state'] != S.QUEUED or not run.get('transfer_id') or self.coordinator is None:
            return False
        return self.coordinator.transfer_model.get(run['transfer_id']) is None

    def _close_orphan(self, run: Dict[str, Any]) -> None:
        """Close a run whose transfer was deleted, so the folder can sync again."""
        run_id = run['run_id']
        reason = 'Its transfer was deleted from the transfer list before it started.'
        self._stage(run_id, S.QUEUE, S.FAILED, reason, level='warning')
        self._skip_rest(run_id, S.QUEUE, 'Not reached: the transfer was deleted.')
        self.store.update_webhooks(run_id, {'status': 'cancelled'},
                                   exclude_status=SETTLED_STATUSES)
        self._set_state(run_id, S.CANCELLED, S.QUEUE, outcome='cancelled',
                        outcome_message=reason)

    def _opened_message(self, run: Dict[str, Any], active: Optional[Dict[str, Any]]) -> str:
        label = run.get('title') or 'this folder'
        if run.get('season_name'):
            label = f"{label} — {run['season_name']}"
        if active:
            return (f"{label} is copying right now; this waits in a follow-up batch "
                    f"and runs straight after.")
        if run['state'] == S.HELD:
            return f"Received {label}. Automatic sync is off, so it waits for someone to press Sync."
        return f"Sync started for {label}."

    def _open_run(self, request: SyncRequest, unit: Unit, policy: S.KindPolicy,
                  parent: Optional[Dict[str, Any]] = None,
                  relation: Optional[str] = None) -> Dict[str, Any]:
        actor = request.actor or current_actor()
        now = self.clock()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        options = dict(request.options)
        options.update({k: v for k, v in unit.ids.items() if v not in (None, '')})
        if request.extra_fields:
            options['extra_fields'] = dict(request.extra_fields)
        if request.safety_summary:
            options['safety_summary'] = request.safety_summary
        if request.simulation_bwlimit:
            options['simulation_bwlimit'] = request.simulation_bwlimit

        state = S.HELD if request.hold else S.WAITING_STATE
        run = self.store.create({
            'run_id': run_id,
            'kind': request.kind,
            'source': request.source,
            'media_type': unit.media_type,
            'unit_key': unit.unit_key,
            'mergeable': 0 if _request_stands_alone(request, policy) else 1,
            'title': unit.title,
            'season_number': unit.season_number,
            'season_name': unit.season_name,
            'folder_name': unit.folder_name,
            'source_path': unit.source_path,
            'dest_path': unit.dest_path,
            'operation_type': unit.operation_type or 'folder',
            'state': state,
            'current_stage': S.READY,
            'transfer_id': request.transfer_id,
            'parent_run_id': (parent or {}).get('run_id') or request.parent_run_id,
            'parent_relation': relation or request.parent_relation,
            'requested_by_kind': actor.kind,
            'requested_by_name': actor.name,
            'requested_by_account_id': actor.account_id,
            'is_simulation': 1 if request.is_simulation else 0,
            'force_safety': 1 if request.force_safety else 0,
            'timer_due_at': now + self._wait_seconds(),
            'ready_deadline_at': now + READY_CAP_SECONDS,
            'options': options,
        })

        self._stage(run_id, S.RECEIVE, S.PASSED, self._receive_note(request, unit),
                    detail={'kind': request.kind, 'requested_by': actor.label,
                            'webhooks': len(request.webhooks)})
        mode = policy.mode(S.IDENTIFY)
        identify_text = (f"{unit.label}: {unit.source_path} → {unit.dest_path}")
        if mode == S.DIFFERENT and policy.note(S.IDENTIFY):
            identify_text += f". {policy.note(S.IDENTIFY)}"
        self._stage(run_id, S.IDENTIFY, S.PASSED, identify_text, detail=unit.as_dict())

        for table, notification_id in request.webhooks:
            self.store.attach_webhook(table, notification_id, run_id)

        if not policy.mergeable:
            self._stage(run_id, S.BATCH, S.SKIPPED, policy.note(S.BATCH) or
                        'This kind of sync always stands alone.')
        elif _request_stands_alone(request, policy):
            what = 'one file' if request.operation_type == 'file' else 'a fixed list of files'
            self._stage(run_id, S.BATCH, S.SKIPPED,
                        f"Stands alone: it copies {what} and nothing else, so it never joins "
                        f"a batch and no webhook joins it. The queue still holds it behind "
                        f"anything writing to the same folder.")
        elif parent is not None:
            self._stage(
                run_id, S.BATCH, S.PASSED,
                f"Opened a follow-up batch: {parent.get('title') or 'this folder'} is "
                f"copying right now (run {parent['run_id']}), so this waits behind it "
                f"and runs straight after.",
                detail={'follows_run_id': parent['run_id']})
            self._event(parent['run_id'], S.BATCH,
                        f"A follow-up batch was opened behind this copy (run {run_id}).")
        else:
            count = len(request.webhooks)
            extra = f" with {count} webhook{'s' if count != 1 else ''}" if count else ''
            self._stage(run_id, S.BATCH, S.PASSED,
                        f"Opened a new batch for {unit.label}{extra}.")

        self._enter_ready(run_id, request, policy)
        return self.store.get(run_id)

    def _enter_ready(self, run_id: str, request: SyncRequest, policy: S.KindPolicy) -> None:
        """Decide how the ready check runs for this run, and set it going."""
        run = self.store.get(run_id)
        if request.hold:
            media = {'tvshows': 'TV shows', 'anime': 'anime',
                     'movies': 'movies'}.get(run.get('media_type') or '', 'this library')
            self._stage(run_id, S.READY, S.WAITING,
                        f"Automatic sync is off for {media}, so this waits for "
                        f"someone to press Sync.")
            self._set_state(run_id, S.HELD, S.READY)
            return

        if self._ready_skipped(run, policy):
            self._stage(run_id, S.READY, S.SKIPPED, self._ready_skip_note(run, policy))
            self._set_state(run_id, S.CHECKING, S.SAFETY)
            return

        self._stage(run_id, S.READY, S.RUNNING,
                    'Checking whether Sonarr can be asked about this season.')
        self._set_state(run_id, S.WAITING_STATE, S.READY, next_check_at=self.clock())
        self.store.update_webhooks(run_id, {'status': 'pending'},
                                   exclude_status=SETTLED_STATUSES)

    @staticmethod
    def _ready_skipped(run: Dict[str, Any], policy: S.KindPolicy) -> bool:
        mode = policy.mode(S.READY)
        if mode == S.SKIP:
            return True
        if policy.id == S.AUTO_SCANNER and run.get('source') != 'sonarr':
            return True
        if run.get('media_type') == 'movies':
            return True
        return False

    @staticmethod
    def _ready_skip_note(run: Dict[str, Any], policy: S.KindPolicy) -> str:
        if policy.mode(S.READY) == S.SKIP:
            return policy.note(S.READY)
        return ('A Radarr find is one finished movie, so there is nothing to wait for.'
                if run.get('media_type') == 'movies'
                else 'Skipped: this sync does not wait on Sonarr.')

    def _join(self, open_run: Dict[str, Any], request: SyncRequest, unit: Unit) -> SubmitResult:
        """A request for a folder whose batch is still open."""
        run_id = open_run['run_id']
        new_ids = []
        for table, notification_id in request.webhooks:
            self.store.attach_webhook(table, notification_id, run_id)
            new_ids.append((table, notification_id))

        if request.kind == S.AUTO_SCANNER:
            self._event(run_id, S.BATCH,
                        'The auto-scanner also found this folder incomplete; this batch '
                        'already covers it, so nothing new was started.')
            return SubmitResult(True, run_id, 'skipped', open_run['state'],
                                f"Already waiting to sync {unit.label}")

        labels = self._webhook_labels(new_ids)
        what = {S.SONARR_WEBHOOK: f"Sonarr webhook{(' for ' + labels) if labels else ''}",
                S.RADARR_WEBHOOK: 'Radarr webhook',
                S.MANUAL: f"Sync request from {request.actor.label if request.actor else 'an admin'}",
                S.RESTART: f"Restart from {request.actor.label if request.actor else 'an admin'}",
                }.get(request.kind, 'Request')
        self._event(run_id, S.RECEIVE, f"{what} received.")
        total = len(self.store.webhook_ids(run_id))
        message = f"Joined this batch ({total} webhook{'s' if total != 1 else ''} in it now)."
        # The stage's sentence follows the batch as it grows; the join itself
        # is the log line written below.
        noun = f"{total} webhook{'s' if total != 1 else ''}"
        self.store.set_stage(
            run_id, S.BATCH, S.PASSED,
            f"Follow-up batch for {unit.label}, behind run {open_run['parent_run_id']}: "
            f"{noun} in it." if open_run.get('parent_relation') == 'follow_up'
            and open_run.get('parent_run_id') else
            f"One batch for {unit.label}: {noun} in it.")

        if open_run['state'] in (S.WAITING_STATE, S.HELD):
            # The old timer, kept for when Sonarr cannot answer, grows with
            # every webhook — and because it lives on the row, it is re-read
            # at every step. Holding it in a sleeping thread's local variable is
            # how the extension stopped working.
            first = (open_run.get('ready_deadline_at') or self.clock()) - READY_CAP_SECONDS
            due = min((open_run.get('timer_due_at') or self.clock()) + self._wait_seconds(),
                      first + TIMER_CAP_SECONDS)
            self._update(run_id, timer_due_at=due)
            if open_run.get('ready_mode') == 'timer':
                self._update(run_id, next_check_at=due)
                message += f" The fallback wait now ends at {_hhmmss(due)}."
            self.store.update_webhooks(run_id, {'status': 'pending'},
                                       exclude_status=SETTLED_STATUSES)
        self._event(run_id, S.BATCH, message)

        if request.kind in (S.MANUAL, S.RESTART):
            return self._promote(open_run, request.actor, request)

        if (open_run['state'] == S.HELD and not request.hold
                and request.kind in (S.SONARR_WEBHOOK, S.RADARR_WEBHOOK)):
            # Held because automatic sync was off when it opened; it is on now,
            # so this webhook sets the batch going rather than leaving it parked.
            self._event(run_id, S.READY,
                        'Automatic sync is on now, so this batch starts by itself.')
            self._enter_ready(run_id, request, S.policy(open_run['kind']))
            self.kick(run_id)
            return SubmitResult(True, run_id, 'joined', S.WAITING_STATE,
                                f"Added to the batch for {unit.label}; it starts by itself now.")

        return SubmitResult(True, run_id, 'joined', open_run['state'],
                            f"Added to the batch already open for {unit.label}.")

    def _promote(self, run: Dict[str, Any], actor: Optional[Actor],
                 request: Optional[SyncRequest] = None) -> SubmitResult:
        """An admin asked for a batch that is still waiting to go now."""
        run_id = run['run_id']
        who = actor.label if actor else 'An admin'
        label = run.get('title') or 'this folder'
        if run['state'] in (S.HELD, S.WAITING_STATE):
            fields = {'go_now': 1, 'next_check_at': self.clock()}
            if request is not None and request.force_safety:
                fields['force_safety'] = 1
            if actor is not None and run['state'] == S.HELD:
                fields.update(requested_by_kind=actor.kind, requested_by_name=actor.name,
                              requested_by_account_id=actor.account_id)
            self._update(run_id, **fields)
            self._event(run_id, S.READY, f"{who} asked for this batch to go now.")
            if run['state'] == S.HELD:
                self._update(run_id, state=S.WAITING_STATE)
            self.kick(run_id)
            return SubmitResult(True, run_id, 'promoted', S.WAITING_STATE,
                                f"Starting {label} now.")
        state_text = S.describe_state(run['state']).lower()
        return SubmitResult(True, run_id, 'promoted', run['state'],
                            f"{label} is already on its way ({state_text}).")

    # ----------------------------------------------------------------- advance

    def _advance(self, run_id: str) -> None:
        """Move a run forward until it has to wait for something."""
        for _ in range(8):
            run = self.store.get(run_id)
            if not run:
                return
            state = run['state']
            if state == S.WAITING_STATE:
                if not self._ready_step(run):
                    return
            elif state == S.HELD:
                if not run.get('go_now'):
                    return
                if not self._ready_step(run):
                    return
            elif state == S.CHECKING:
                if not self._safety_step(run):
                    return
            else:
                return

    # ------------------------------------------------------------- ready check

    def _ready_step(self, run: Dict[str, Any]) -> bool:
        """One step of the ready check. True when the run may move on to safety."""
        run_id = run['run_id']
        now = self.clock()
        policy = S.policy(run['kind'])

        if run.get('go_now'):
            who = run.get('requested_by_name') or 'an admin'
            return self._ready_passed(run_id, f"Started now: {who} pressed Go now.")

        # A kick is a request to look, not a reason to ask early. Without this,
        # every webhook joining a batch would put another question to Sonarr.
        next_at = run.get('next_check_at')
        if run.get('ready_mode') and next_at is not None and next_at > now:
            return False

        if self._ready_skipped(run, policy):
            with self._still(run_id, *READY_CHECK_STATES) as current:
                if current is None:
                    return False
                self._stage(run_id, S.READY, S.SKIPPED, self._ready_skip_note(run, policy))
                self._set_state(run_id, S.CHECKING, S.SAFETY)
            return True

        if run.get('ready_mode') is None:
            return self._ready_first_look(run, now)

        if run['ready_mode'] == 'timer':
            due = run.get('timer_due_at') or now
            if now >= due:
                waited = now - self._opened_at(run)
                return self._ready_passed(
                    run_id, f"The fallback wait ended after {_duration(waited)}.")
            self._update(run_id, next_check_at=due)
            return False

        return self._ready_ask(run, now)

    def _opened_at(self, run: Dict[str, Any]) -> float:
        return (run.get('ready_deadline_at') or self.clock()) - READY_CAP_SECONDS

    def _ready_first_look(self, run: Dict[str, Any], now: float) -> bool:
        """Is Sonarr up? Decides between asking and the old timer."""
        run_id = run['run_id']
        adapter = None
        if self.media_index is not None:
            try:
                adapter = self.media_index._adapter('sonarr')
            except Exception:  # noqa: BLE001
                adapter = None

        if adapter is None:
            return self._use_timer(
                run, 'Sonarr is not connected (Integrations → Sonarr), so the fallback '
                     'wait decides when this starts.', alert=False)

        try:
            check = adapter.check()
            ok, message = bool(check.ok), check.message
        except Exception as error:  # noqa: BLE001 - a check must never fail a sync
            ok, message = False, str(error)

        if not ok:
            if self.alerts is not None:
                self.alerts.integration_down('sonarr', message)
            return self._use_timer(
                run, f"Sonarr did not answer ({message}), so the fallback wait decides "
                     f"when this starts.", alert=True)

        if self.alerts is not None:
            self.alerts.integration_up('sonarr')
        if not (run.get('options') or {}).get('tvdb_id'):
            return self._use_timer(
                run, 'This series has no TVDB id, so Sonarr cannot be asked about it and '
                     'the fallback wait decides when this starts.', alert=False)

        first_ask = max(now, self._opened_at(run) + SETTLE_SECONDS)
        with self._still(run_id, *READY_CHECK_STATES) as current:
            if current is None:
                return False
            self._update(run_id, ready_mode='ask', next_check_at=first_ask)
            self._stage(run_id, S.READY, S.WAITING,
                        f"Sonarr is reachable ({message}). Waiting until "
                        f"{_hhmmss(first_ask)} so episodes arriving together can join, then "
                        f"asking Sonarr what is still downloading.")
            self._mark_webhooks_waiting(run_id, first_ask)
        return False

    def _use_timer(self, run: Dict[str, Any], reason: str, alert: bool) -> bool:
        run_id = run['run_id']
        with self._still(run_id, *READY_CHECK_STATES) as current:
            if current is None:
                return False
            # Re-read: webhooks that joined while Sonarr was asked moved it on.
            due = current.get('timer_due_at') or self.clock()
            self._update(run_id, ready_mode='timer', next_check_at=due)
            if self.clock() >= due:
                self._event(run_id, S.READY, reason, 'warning' if alert else 'info')
                return self._ready_passed(run_id, 'The fallback wait had already run out.')
            wait = self._wait_seconds()
            self._stage(run_id, S.READY, S.WAITING,
                        f"{reason} Starts at {_hhmmss(due)} ({wait} s after the first "
                        f"webhook, plus {wait} s for each later one, never more than 15 "
                        f"minutes).", level='warning' if alert else 'info')
            self._mark_webhooks_waiting(run_id, due)
        return False

    def _ready_ask(self, run: Dict[str, Any], now: float) -> bool:
        """Ask Sonarr whether anything for this season is still on its way."""
        run_id = run['run_id']
        options = run.get('options') or {}
        try:
            answer = self.media_index.in_flight_for_season(
                options.get('tvdb_id'), run.get('season_number'))
        except Exception as error:  # noqa: BLE001
            answer = None
            reason = f"Could not ask Sonarr: {error}"
        else:
            reason = getattr(answer, 'reason', '')

        checks = (run.get('checks_made') or 0) + 1
        self._update(run_id, checks_made=checks)

        if answer is None or not answer.known:
            with self._still(run_id, *READY_CHECK_STATES) as current:
                if current is None:
                    return False
                self._event(run_id, S.READY,
                            f"Sonarr could not answer ({reason}). Finishing on the fallback "
                            f"wait instead.", 'warning')
                return self._use_timer(current, 'Sonarr stopped answering.', alert=False)

        detail = answer.as_dict()
        if answer.blocking == 0:
            if not answer.stuck:
                return self._ready_passed(
                    run_id, f"Sonarr: nothing left to download for this season "
                            f"(asked {checks}×).", detail=detail)
            stuck = '; '.join(answer.stuck_detail) or f"{answer.stuck} stuck"
            if not self._ready_passed(
                    run_id,
                    f"Nothing is still downloading. {answer.stuck} stuck in Sonarr — not "
                    f"waited for: {stuck}.", detail=detail, level='warning'):
                return False
            if self.alerts is not None:
                self.alerts.stuck_download(self.store.get(run_id), answer)
            return True

        deadline = run.get('ready_deadline_at') or (now + READY_CAP_SECONDS)
        if now >= deadline:
            still = '; '.join(answer.detail) or f"{answer.blocking} downloading"
            if not self._ready_passed(
                    run_id,
                    f"Waited 30 minutes — syncing what is there now. Still downloading: "
                    f"{still}. Those arrive later through their own webhook or the "
                    f"auto-scanner.", detail=detail, level='warning'):
                return False
            if self.alerts is not None:
                self.alerts.ready_timeout(self.store.get(run_id), answer)
            return True

        wait = answer.eta_seconds if answer.eta_seconds is not None else RECHECK_DEFAULT_SECONDS
        wait = max(RECHECK_MIN_SECONDS, min(RECHECK_MAX_SECONDS, wait))
        next_at = min(now + wait, deadline)
        downloading = '; '.join(answer.detail)
        eta = (f"about {_duration(answer.eta_seconds)} left"
               if answer.eta_seconds is not None else 'no estimate from Sonarr')
        with self._still(run_id, *READY_CHECK_STATES) as current:
            if current is None:
                return False
            self._update(run_id, next_check_at=next_at)
            self._stage(run_id, S.READY, S.WAITING,
                        f"Sonarr: {answer.blocking} still downloading ({eta}). Asking again "
                        f"at {_hhmmss(next_at)}.",
                        detail={**detail, 'downloading': downloading})
            self._mark_webhooks_waiting(run_id, next_at)
        return False

    def _ready_passed(self, run_id: str, summary: str,
                      detail: Optional[Dict[str, Any]] = None,
                      level: Optional[str] = None) -> bool:
        """On to the dry run. False when the run was cancelled or closed meanwhile."""
        with self._still(run_id, *READY_CHECK_STATES) as current:
            if current is None:
                return False
            self._stage(run_id, S.READY, S.PASSED, summary, detail=detail, level=level)
            self._set_state(run_id, S.CHECKING, S.SAFETY, next_check_at=None)
        return True

    def _mark_webhooks_waiting(self, run_id: str, when: float) -> None:
        self.store.update_webhooks(
            run_id, {'status': 'pending', 'auto_sync_scheduled_at': _clock_iso(when)},
            exclude_status=SETTLED_STATUSES)

    # ------------------------------------------------------------ safety check

    def _safety_step(self, run: Dict[str, Any]) -> bool:
        """The dry run. True when the run may be handed to the queue."""
        run_id = run['run_id']
        with self._still(run_id, S.CHECKING) as run:
            if run is None:
                return False
            policy = S.policy(run['kind'])
            mode = policy.mode(S.SAFETY)
            options = run.get('options') or {}

            if mode == S.SKIP:
                self._stage(run_id, S.SAFETY, S.SKIPPED, policy.note(S.SAFETY))
                return self._queue_step(run_id)

            if run.get('is_simulation'):
                # A restarted rehearsal: the same sandbox files, which the media
                # server has never seen, so a dry run against it could only fail.
                self._stage(run_id, S.SAFETY, S.SKIPPED,
                            S.policy(S.SIMULATION).note(S.SAFETY))
                return self._queue_step(run_id)

            if run['kind'] == S.RESTART and run.get('transfer_id') and \
                    self.coordinator is not None:
                row = self.coordinator.transfer_model.get(run['transfer_id']) or {}
                if row.get('explore_files_from'):
                    self._stage(run_id, S.SAFETY, S.SKIPPED,
                                'Skipped: this retries a sync started from Explore. It '
                                'copies the same files as before and deletes nothing, and '
                                'Explore’s review checked them before the first try; a dry '
                                'run of the whole folder would judge a different copy.')
                    return self._queue_step(run_id)

            if run.get('operation_type') == 'file':
                self._stage(run_id, S.SAFETY, S.SKIPPED,
                            'Skipped: one file is copied, and rsync deletes nothing when it '
                            'is given a single file, so there is nothing for a dry run to '
                            'guard.')
                return self._queue_step(run_id)

            if run['kind'] in (S.EXPLORE, S.RESTORE):
                summary = options.get('safety_summary') or policy.note(S.SAFETY)
                self._stage(run_id, S.SAFETY, S.PASSED, summary)
                return self._queue_step(run_id)

            transfer_service = getattr(self.coordinator, 'transfer_service', None)
            if transfer_service is None:
                self._stage(run_id, S.SAFETY, S.SKIPPED,
                            'No transfer service is available to run a dry run.')
                return self._queue_step(run_id)

            self._stage(run_id, S.SAFETY, S.RUNNING,
                        'Dry run: asking rsync what this sync would change.')

        # The folder is not locked while rsync works this out; what it says is
        # used below only if the sync is still waiting for it.
        try:
            result = transfer_service.perform_dry_run_rsync(
                source_path=run['source_path'], dest_path=run['dest_path'])
        except Exception as error:  # noqa: BLE001
            result = {'safe_to_sync': False, 'reason': f'Dry-run execution error: {error}',
                      'deleted_count': 0, 'incoming_count': 0}

        detail = {
            'safe': bool(result.get('safe_to_sync')),
            'reason': result.get('reason'),
            'incoming_count': result.get('incoming_count', 0),
            'deleted_count': result.get('deleted_count', 0),
            'server_file_count': result.get('server_file_count', 0),
            'local_file_count': result.get('local_file_count', 0),
            'incoming_files': list(result.get('incoming_files') or [])[:50],
            'deleted_files': list(result.get('deleted_files') or [])[:50],
        }
        self._store_dry_run(run_id, result)
        counts = (f"{detail['incoming_count']} file(s) to copy, "
                  f"{detail['deleted_count']} to delete; the media server holds "
                  f"{detail['server_file_count']}, this disk {detail['local_file_count']}")

        with self._still(run_id, S.CHECKING) as run:
            if run is None:
                self._event(run_id, S.SAFETY,
                            f"The dry run answered after this sync had stopped, so its "
                            f"answer was not used ({counts}).")
                return False

            if result.get('safe_to_sync'):
                self._stage(run_id, S.SAFETY, S.PASSED, f"Safe to sync: {counts}.",
                            detail=detail)
                return self._queue_step(run_id)

            reason = result.get('reason') or 'The dry run failed'
            if run.get('force_safety'):
                who = run.get('requested_by_name') or 'an admin'
                self._stage(run_id, S.SAFETY, S.PASSED,
                            f"The safety check failed ({reason}) — {who} chose to go ahead "
                            f"anyway. {counts}.", detail=detail, level='warning')
                return self._queue_step(run_id)

            self._refuse(run, reason, detail)
        return False

    def _store_dry_run(self, run_id: str, result: Dict[str, Any]) -> None:
        import json
        try:
            payload = json.dumps({k: v for k, v in result.items() if k != 'raw_output'})
        except (TypeError, ValueError):
            return
        try:
            with self.store.db.get_connection() as conn:
                conn.execute(
                    "UPDATE sonarr_webhook SET dry_run_result = ?, dry_run_performed_at = ? "
                    "WHERE sync_run_id = ?", (payload, datetime.now().isoformat(), run_id))
                conn.commit()
        except Exception:  # noqa: BLE001 - informational only
            pass

    def _refuse(self, run: Dict[str, Any], reason: str, detail: Dict[str, Any]) -> None:
        """The dry run looked unsafe: stop, and hand it to a person."""
        run_id = run['run_id']
        automatic = not _started_by_a_person(run)
        self._stage(run_id, S.SAFETY, S.REFUSED,
                    f"Stopped before writing anything: {reason}.", detail=detail)
        self._skip_rest(run_id, S.SAFETY,
                        'Not reached: the safety check stopped this sync for a person '
                        'to decide.')
        self.store.update_webhooks(
            run_id, {'status': 'pending', 'requires_manual_sync': 1,
                     'manual_sync_reason': reason},
            exclude_status=SETTLED_STATUSES)
        self._set_state(run_id, S.REFUSED_STATE, S.SAFETY, outcome='refused',
                        outcome_message=reason)
        if self.alerts is not None:
            self.alerts.sync_refused(self.store.get(run_id), reason, detail,
                                     announce=automatic)
            self.store.set_stage(run_id, S.TELL, S.PASSED,
                                 'Opened an alert in Notifications'
                                 + (' and told Discord.' if automatic else '.'))
            self._emit_run(run_id)

    # ------------------------------------------------------------------- queue

    def _queue_step(self, run_id: str) -> bool:
        """Hand the run to the queue as one transfer. Returns False: it now waits."""
        run = self.store.get(run_id)
        if not run or self.coordinator is None:
            if run:
                self._fail_run(run_id, S.QUEUE, 'No transfer coordinator is available.')
            return False

        with self._run_lock(run):
            run = self.store.get(run_id)
            # Only a run the safety check has just passed is handed on. Anything
            # else got here late: cancelled, closed, or already queued.
            if run['state'] != S.CHECKING:
                return False
            transfer_id = run.get('transfer_id') or self._transfer_id_for(run['kind'])
            options = run.get('options') or {}
            self._set_state(run_id, S.QUEUED, S.QUEUE, transfer_id=transfer_id)
            self._stage(run_id, S.QUEUE, S.RUNNING, 'Handing this to the transfer queue.')
            self.store.update_webhooks(run_id, {'status': 'READY_FOR_TRANSFER',
                                                'transfer_id': transfer_id},
                                       exclude_status=SETTLED_STATUSES)

            existing = None
            if run['kind'] == S.RESTART:
                existing = self.coordinator.transfer_model.get(transfer_id)

            try:
                if existing is not None:
                    started, queue_state = self.coordinator.requeue_transfer(
                        transfer_id, sync_run_id=run_id)
                else:
                    extra = dict(options.get('extra_fields') or {})
                    extra['sync_run_id'] = run_id
                    started, queue_state = self.coordinator.start_transfer(
                        transfer_id, run['source_path'], run['dest_path'],
                        run.get('operation_type') or 'folder', run.get('media_type') or '',
                        run.get('folder_name') or '', run.get('season_name'),
                        is_simulation=bool(run.get('is_simulation')),
                        simulation_bwlimit=options.get('simulation_bwlimit'),
                        extra_fields=extra)
            except Exception as error:  # noqa: BLE001
                started, queue_state = False, f'error: {error}'

            self.store.merge_options(run_id, queue_state=queue_state)
            if started:
                self._link_title(run, transfer_id)

            if not started:
                transfer = self.coordinator.transfer_model.get(transfer_id) or {}
                why = transfer.get('progress') or f"The queue refused it ({queue_state})"
                # rsync may already have been asked, and refused: then the run
                # reads as copying, and the copy is what failed.
                copying = (self.store.get(run_id) or {}).get('state') == S.TRANSFERRING
                self._fail_run(run_id, S.TRANSFER if copying else S.QUEUE,
                               f"Could not start: {why}")
                if self.alerts is not None:
                    self.alerts.transfer_failed(self.store.get(run_id), why)
                return False

            run = self.store.get(run_id)
            if queue_state == 'QUEUED_SLOT':
                self._stage(run_id, S.QUEUE, S.WAITING,
                            'All transfer slots are busy (three at once). Waiting for one '
                            'to free up.')
                self.store.update_webhooks(run_id, {'status': 'QUEUED_SLOT'},
                                           exclude_status=SETTLED_STATUSES)
            elif queue_state == 'QUEUED_PATH':
                transfer = self.coordinator.transfer_model.get(transfer_id) or {}
                why = (transfer.get('progress') or '').replace('Queued: ', '')
                self._stage(run_id, S.QUEUE, S.WAITING,
                            f"Another transfer is writing to the same folder. {why}".strip())
                self.store.update_webhooks(run_id, {'status': 'QUEUED_PATH'},
                                           exclude_status=SETTLED_STATUSES)
            # 'running': before_transfer_start already moved the run on.
        return False

    def _link_title(self, run: Dict[str, Any], transfer_id: str) -> None:
        """Point the transfer at its title, so a Library tab can say when it last synced."""
        store = getattr(self.media_index, 'store', None)
        if store is None or self.coordinator is None:
            return
        options = run.get('options') or {}
        for source, key in (('sonarr', 'tvdb_id'), ('radarr', 'tmdb_id')):
            if options.get(key) in (None, ''):
                continue
            try:
                item = store.get(source, options[key])
                if item:
                    # Also teaches the index the folder the title lives in.
                    self.media_index.note_transfer(transfer_id, item['id'],
                                                   run.get('folder_name') or '')
            except Exception:  # noqa: BLE001 - a missing link must never stop a sync
                log.exception('Could not link transfer %s to its title', transfer_id)
            return

    # ------------------------------------------------- transfer lifecycle hooks

    def before_transfer_start(self, transfer_id: str) -> None:
        """Called by the coordinator right before rsync starts.

        Flips the run from queued to copying under the folder's lock. From this
        moment a webhook for the folder goes to the follow-up batch, because the
        copy may already have listed the folder.
        """
        run = self.store.by_transfer(transfer_id)
        if not run:
            return
        key = run['unit_key'] or make_unit_key(run.get('dest_path') or '')
        with self.unit_lock(key):
            run = self.store.get(run['run_id'])
            if run['state'] in S.TERMINAL_STATES:
                return
            run_id = run['run_id']
            stages = self.store.stages(run_id)
            queue_status = (stages.get(S.QUEUE) or {}).get('status')
            if queue_status == S.WAITING:
                queued_at = (stages.get(S.QUEUE) or {}).get('started_at')
                waited = ''
                if queued_at:
                    try:
                        then = datetime.fromisoformat(queued_at)
                        waited = f" after waiting {_duration((datetime.now(timezone.utc) - then).total_seconds())}"
                    except ValueError:
                        waited = ''
                summary = f"Started{waited}: a slot was free and nothing else was writing here."
            elif queue_status == S.PASSED and run['state'] == S.PAUSED:
                summary = None
            else:
                summary = 'Started straight away: a slot was free and nothing else was writing here.'
            if summary:
                self._stage(run_id, S.QUEUE, S.PASSED, summary)
            started_at = _now_iso()
            self.store.merge_options(run_id, transfer_started_at=started_at)
            self._set_state(run_id, S.TRANSFERRING, S.TRANSFER,
                            started_at=run.get('started_at') or started_at)
            self._stage(run_id, S.TRANSFER, S.RUNNING, 'Starting rsync.')
            self.store.update_webhooks(run_id, {'status': 'syncing',
                                                'completed_at': datetime.now().isoformat()},
                                       exclude_status=SETTLED_STATUSES)

    def on_transfer_started(self, transfer_id: str) -> None:
        """rsync is running: record how it reaches the media server."""
        run = self.store.by_transfer(transfer_id)
        if not run or self.coordinator is None:
            return
        transfer = self.coordinator.transfer_model.get(transfer_id) or {}
        transport = transfer.get('transport')
        if run.get('is_simulation') or transport is None:
            how = 'locally (a simulation never touches the media server)' \
                if run.get('is_simulation') else 'over the configured route'
        elif transport == 'daemon':
            how = 'over the fast transfer server'
        elif transport == 'ssh_fallback':
            how = 'over SSH, after the fast transfer server failed'
        else:
            how = 'over SSH'
        pid = transfer.get('rsync_process_id')
        self._stage(run['run_id'], S.TRANSFER, S.RUNNING,
                    f"Copying {how}{f' (rsync pid {pid})' if pid else ''}. The live "
                    f"output is in this transfer's log.",
                    detail={'transport': transport, 'pid': pid, 'transfer_id': transfer_id})

    def on_transfer_waiting(self, transfer_id: str, reason: str, message: str = '') -> None:
        """The queue re-filed a waiting transfer (a slot wait became a folder wait)."""
        run = self.store.by_transfer(transfer_id)
        if not run or run['state'] != S.QUEUED:
            return
        if reason == 'path':
            text = 'Another transfer is now writing to the same folder. ' + \
                   (message or '').replace('Queued: ', '')
        else:
            text = 'Waiting for a free transfer slot.'
        self._stage(run['run_id'], S.QUEUE, S.WAITING, text.strip())
        # Movies and series alike: the webhook list shows what it waits for.
        self.store.update_webhooks(
            run['run_id'], {'status': 'QUEUED_PATH' if reason == 'path' else 'QUEUED_SLOT'},
            exclude_status=SETTLED_STATUSES)

    def on_transfer_paused(self, transfer_id: str, message: Optional[str] = None) -> None:
        run = self.store.by_transfer(transfer_id)
        if not run or run['state'] in S.TERMINAL_STATES:
            return
        who = current_actor().label
        self._stage(run['run_id'], S.TRANSFER, S.WAITING,
                    message or f"Paused by {who}. Partial files are kept; resuming "
                               f"continues from them.")
        self._set_state(run['run_id'], S.PAUSED, S.TRANSFER)

    def on_transfer_resumed(self, transfer_id: str, queue_state: str) -> None:
        run = self.store.by_transfer(transfer_id)
        if not run or run['state'] in S.TERMINAL_STATES:
            return
        who = current_actor().label
        if queue_state == 'queued':
            self._event(run['run_id'], S.TRANSFER, f"Resumed by {who}.")
            self._stage(run['run_id'], S.QUEUE, S.WAITING,
                        'Resumed — waiting for a free transfer slot.')
            self._set_state(run['run_id'], S.QUEUED, S.QUEUE)
        else:
            self._event(run['run_id'], S.TRANSFER, f"Resumed by {who}.")

    def on_transfer_finished(self, transfer_id: str, status: str) -> None:
        """The transfer ended. Finish and Tell. Safe to call more than once."""
        run = self.store.by_transfer(transfer_id)
        if not run:
            return
        key = run['unit_key'] or make_unit_key(run.get('dest_path') or '')
        with self.unit_lock(key):
            run = self.store.get(run['run_id'])
            if run['state'] in S.TERMINAL_STATES:
                return
            self._finish(run, transfer_id, status)
        self._tell(self.store.get(run['run_id']), transfer_id, status)
        self._release_followers(run['run_id'])

    def _finish(self, run: Dict[str, Any], transfer_id: str, status: str) -> None:
        run_id = run['run_id']
        transfer = (self.coordinator.transfer_model.get(transfer_id)
                    if self.coordinator is not None else None) or {}
        # Still queued: the queue let it through and it could not start.
        never_started = run['state'] == S.QUEUED
        self._set_state(run_id, S.FINISHING, S.FINISH)

        stats = {}
        notifier = getattr(self.coordinator, 'notification_service', None)
        if notifier is not None and transfer.get('logs'):
            try:
                stats = notifier.parse_transfer_logs(transfer.get('logs') or []) or {}
            except Exception:  # noqa: BLE001
                stats = {}
        progress = transfer.get('progress') or ''

        if status == 'completed':
            moved = stats.get('regular_files_transferred')
            size = stats.get('total_transferred_size')
            speed = stats.get('avg_speed')
            bits = []
            if moved is not None:
                bits.append(f"{moved} file(s) copied")
            if stats.get('deleted_files') is not None:
                bits.append(f"{stats['deleted_files']} deleted")
            if size:
                bits.append(f"{size} moved")
            if speed:
                bits.append(f"at {speed}")
            text = ('Finished. ' + ', '.join(bits) + '.') if bits else 'Finished.'
            if 'Test mode' in progress:
                text = 'Finished as a test-mode rehearsal: rsync ran with --dry-run, so nothing was written.'
            self._stage(run_id, S.TRANSFER, S.PASSED, text, detail=stats or None)
        elif status == 'cancelled':
            self._stage(run_id, S.TRANSFER, S.FAILED,
                        progress or 'Cancelled.', level='warning')
        elif never_started:
            self._stage(run_id, S.QUEUE, S.FAILED,
                        f"Could not start: {progress or 'no reason given'}")
            self.store.set_stage(run_id, S.TRANSFER, S.SKIPPED,
                                 'Not reached: the transfer could not start.')
        else:
            self._stage(run_id, S.TRANSFER, S.FAILED,
                        f"rsync stopped without finishing: {progress or 'no reason given'}.")

        # Belt and braces for the one window the lock cannot close: a webhook
        # that joined after the copy began may not be in what was copied.
        started_at = (run.get('options') or {}).get('transfer_started_at')
        late: Dict[str, List[str]] = {}
        if started_at and status == 'completed':
            late = self.store.webhooks_attached_after(run_id, started_at)

        if status == 'completed':
            for table, ids in late.items():
                self._carry_forward(run, table, ids)
            count = self.store.update_webhooks(
                run_id, {'status': 'completed', 'completed_at': datetime.now().isoformat()},
                exclude_status=SETTLED_STATUSES)
            noun = 'webhook' if count == 1 else 'webhooks'
            self._stage(run_id, S.FINISH, S.PASSED,
                        f"Marked {count} {noun} synced." if count else
                        'No webhook is linked to this sync, so there is nothing else '
                        'to close.')
            self._set_state(run_id, S.COMPLETED, S.FINISH, outcome='completed',
                            outcome_message=progress or 'Synced')
        elif status == 'cancelled':
            count = self.store.update_webhooks(run_id, {'status': 'cancelled'},
                                               exclude_status=SETTLED_STATUSES)
            self._stage(run_id, S.FINISH, S.PASSED,
                        f"Marked {count} webhook(s) cancelled." if count else 'Closed.')
            self._set_state(run_id, S.CANCELLED, S.FINISH, outcome='cancelled',
                            outcome_message=progress or 'Cancelled')
        else:
            message = progress or 'Transfer failed'
            count = self.store.update_webhooks(
                run_id, {'status': 'failed', 'error_message': message},
                exclude_status=SETTLED_STATUSES)
            self._stage(run_id, S.FINISH, S.PASSED,
                        f"Marked {count} webhook(s) failed; Retry from the alert or the "
                        f"transfer." if count else 'Closed as failed.')
            self._set_state(run_id, S.FAILED_STATE, S.FINISH, outcome='failed',
                            outcome_message=message)

    def _carry_forward(self, run: Dict[str, Any], table: str, ids: List[str]) -> None:
        """Move webhooks that joined after the copy began onto a follow-up batch."""
        follow = self.store.find_open(run['unit_key'])
        if follow is None:
            request = SyncRequest(kind=run['kind'], source=run.get('source'),
                                  media_type=run.get('media_type') or '',
                                  source_path=run['source_path'],
                                  dest_path=run['dest_path'],
                                  folder_name=run.get('folder_name') or '',
                                  season_name=run.get('season_name'),
                                  season_number=run.get('season_number'),
                                  title=run.get('title') or '',
                                  actor=_actor_from_run(run),
                                  options={k: v for k, v in (run.get('options') or {}).items()
                                           if k in ('tvdb_id', 'tmdb_id', 'series_id')},
                                  note='Webhooks that arrived after the previous copy began.')
            unit = Unit(media_type=run.get('media_type') or '',
                        source_path=run['source_path'], dest_path=run['dest_path'],
                        folder_name=run.get('folder_name') or '',
                        season_name=run.get('season_name'),
                        season_number=run.get('season_number'),
                        title=run.get('title') or '',
                        ids={k: v for k, v in (run.get('options') or {}).items()
                             if k in ('tvdb_id', 'tmdb_id', 'series_id')})
            follow = self._open_run(request, unit, S.policy(run['kind']),
                                    parent=None, relation='follow_up')
            self._update(follow['run_id'], parent_run_id=run['run_id'])
            fresh = True
        else:
            fresh = False
        self.store.move_webhooks(table, ids, follow['run_id'])
        if fresh:
            self.kick(follow['run_id'])
        self._event(run['run_id'], S.FINISH,
                    f"{len(ids)} webhook(s) arrived after the copy began; moved to the "
                    f"follow-up batch (run {follow['run_id']}) so nothing is missed.",
                    'warning')
        self._event(follow['run_id'], S.BATCH,
                    f"{len(ids)} webhook(s) carried over from run {run['run_id']}, "
                    f"whose copy began before they arrived.")

    def _tell(self, run: Dict[str, Any], transfer_id: str, status: str) -> None:
        run_id = run['run_id']
        policy = S.policy(run['kind'])
        if run['kind'] == S.SIMULATION or run.get('is_simulation'):
            self._stage(run_id, S.TELL, S.SKIPPED, S.policy(S.SIMULATION).note(S.TELL))
        elif status == 'cancelled':
            self._stage(run_id, S.TELL, S.SKIPPED,
                        'Cancelled syncs are not announced — whoever cancelled it '
                        'already knows.')
        elif run['kind'] == S.RESTORE:
            self._stage(run_id, S.TELL, S.SKIPPED,
                        'Restores are not announced on Discord; the result is on the '
                        'Backups page and in the activity trail.')
        elif status == 'failed' and str(run.get('outcome_message') or '').startswith(
                UNKNOWN_RESULT_PREFIX):
            # Not a failure anyone saw happen: the copy's result was lost in a
            # restart. Said as what it is, by its own alert, instead of a
            # "Sync failed" that may not be true.
            if self.alerts is not None:
                self.alerts.transfer_unknown(run, transfer_id)
            self._stage(run_id, S.TELL, S.PASSED,
                        'Opened an alert: the result of this copy is unknown after a '
                        'restart.', level='warning')
            return
        else:
            notifier = getattr(self.coordinator, 'notification_service', None)
            if notifier is not None:
                try:
                    label = _SYNC_LABEL.get(run['kind'], 'Sync')
                    if run['kind'] in _AUTOMATIC_KINDS and _started_by_a_person(run):
                        label = 'Manual Sync'
                    notifier.send_discord_notification(transfer_id, status, sync_label=label)
                    event = 'Sync finished' if status == 'completed' else 'Sync failed'
                    self._stage(run_id, S.TELL, S.PASSED,
                                f"Announced “{event}” on Discord. Delivery is listed under "
                                f"Integrations → Discord → Activity.")
                except Exception as error:  # noqa: BLE001
                    self._stage(run_id, S.TELL, S.FAILED,
                                f"Could not hand the announcement over: {error}")
            else:
                self._stage(run_id, S.TELL, S.SKIPPED, 'No notification service is set up.')
        if status == 'failed' and self.alerts is not None and not (
                run['kind'] == S.SIMULATION or run.get('is_simulation')):
            self.alerts.transfer_failed(run, (run.get('outcome_message') or ''))

    def _release_followers(self, run_id: str) -> None:
        for child in self.store.children(run_id):
            if child.get('parent_relation') == 'follow_up' and child['state'] in S.OPEN_STATES:
                self._event(child['run_id'], S.QUEUE,
                            f"The copy this was waiting behind (run {run_id}) has finished.")

    # ------------------------------------------------------- manual entry points

    def sync_notifications(self, notification_ids: Sequence[str],
                           actor: Optional[Actor] = None,
                           force_safety: bool = False) -> Dict[str, Any]:
        """An admin pressed Sync on one or more webhooks.

        Grouped by folder, so six episode webhooks of one season are one sync.
        A batch already open for the folder is told to go now; one copying
        right now gets this as its follow-up. Webhooks already synced are left
        alone.
        """
        actor = actor or current_actor()
        groups: Dict[str, Dict[str, Any]] = {}
        problems: List[str] = []
        missing = 0
        for notification_id in notification_ids:
            table, row = self._find_webhook(notification_id)
            if row is None:
                missing += 1
                continue
            status = row.get('status') or ''
            if status in SETTLED_STATUSES:
                problems.append(f"{notification_id}: already synced")
                continue
            current = self.store.get(row.get('sync_run_id')) if row.get('sync_run_id') else None
            if current is not None and current['state'] in S.ACTIVE_STATES:
                # Riding on a copy that is running now. Moving it to another
                # batch would leave that copy unable to mark it synced.
                problems.append(f"{episode_label(row) if table == SERIES_TABLE else notification_id}: "
                                f"being copied right now")
                continue
            try:
                unit = (from_series_notification(row, self._path_service())
                        if table == SERIES_TABLE
                        else from_movie_notification(row, self._path_service()))
            except IdentifyError as error:
                problems.append(f"{notification_id}: {error}")
                continue
            group = groups.setdefault(unit.unit_key, {'table': table, 'ids': [],
                                                      'unit': unit, 'rows': []})
            group['ids'].append(notification_id)
            group['rows'].append(row)

        results: List[SubmitResult] = []
        for key, group in groups.items():
            rows = group['rows']
            # Rows already riding on a live run go with that run; nothing to add.
            fresh = [(group['table'], r['notification_id']) for r in rows]
            source = 'sonarr' if group['table'] == SERIES_TABLE else 'radarr'
            request = SyncRequest(kind=S.MANUAL, source=source,
                                  media_type=group['unit'].media_type,
                                  webhooks=fresh, actor=actor, force_safety=force_safety)
            results.append(self.submit(request))

        ok = any(r.ok for r in results)
        messages = [r.message for r in results] + problems
        if missing:
            messages.append(f"{missing} webhook(s) no longer exist")
        return {
            'ok': ok,
            'message': '; '.join(m for m in messages if m) or 'Nothing to sync',
            'runs': [r.as_dict() for r in results],
            'run_ids': [r.run_id for r in results if r.run_id],
        }

    def _find_webhook(self, notification_id: str) -> Tuple[Optional[str], Optional[Dict]]:
        for table in (SERIES_TABLE, MOVIE_TABLE):
            row = self._webhook_row(table, notification_id)
            if row:
                return table, row
        return None, None

    def go_now(self, run_id: str, actor: Optional[Actor] = None) -> SubmitResult:
        run = self.store.get(run_id)
        if not run:
            return SubmitResult(False, run_id, 'failed', '', 'No such sync run')
        with self._run_lock(run):
            run = self.store.get(run_id)
            if run['state'] in S.TERMINAL_STATES:
                return SubmitResult(False, run_id, 'failed', run['state'],
                                    'This sync already ended.')
            return self._promote(run, actor or current_actor())

    def sync_anyway(self, run_id: str, actor: Optional[Actor] = None) -> SubmitResult:
        """Go ahead with a sync the safety check stopped — an admin's call."""
        actor = actor or current_actor()
        run = self.store.get(run_id)
        if not run:
            return SubmitResult(False, run_id, 'failed', '', 'No such sync run')
        if run['state'] != S.REFUSED_STATE:
            return SubmitResult(False, run_id, 'failed', run['state'],
                                'Only a sync the safety check stopped can be overridden.')
        key = run['unit_key'] or ''
        with self._run_lock(run):
            run = self.store.get(run_id)
            if run['state'] != S.REFUSED_STATE:
                # Pressed twice, or cancelled in between: the first press won.
                return SubmitResult(False, run_id, 'failed', run['state'],
                                    'This sync is no longer stopped by the safety check.')
            busy = self.store.find_live(key)
            if busy is not None and busy['run_id'] != run_id:
                return SubmitResult(False, run_id, 'failed', run['state'],
                                    'Another sync for this folder is already on its way.')
            stages = self.store.stages(run_id)
            reason = (stages.get(S.SAFETY) or {}).get('summary') or run.get('outcome_message')
            self.store.update(run_id, force_safety=1, outcome=None, outcome_message=None,
                              finished_at=None, requested_by_kind=actor.kind,
                              requested_by_name=actor.name,
                              requested_by_account_id=actor.account_id)
            self._stage(run_id, S.SAFETY, S.PASSED,
                        f"{actor.label} chose to go ahead despite the safety check: {reason}",
                        level='warning')
            for stage in (S.QUEUE, S.TRANSFER, S.FINISH, S.TELL):
                self.store.reset_stage(run_id, stage)
            self.store.update_webhooks(run_id, {'requires_manual_sync': 0},
                                       exclude_status=SETTLED_STATUSES)
            self._set_state(run_id, S.CHECKING, S.QUEUE)
            self._queue_step(run_id)
        run = self.store.get(run_id)
        if run['state'] == S.FAILED_STATE:
            return SubmitResult(False, run_id, 'failed', run['state'],
                                run.get('outcome_message') or 'The queue did not take it.',
                                transfer_id=run.get('transfer_id'))
        return SubmitResult(True, run_id, 'promoted', run['state'],
                            'Going ahead despite the safety check.',
                            transfer_id=run.get('transfer_id'))

    def cancel_run(self, run_id: str, actor: Optional[Actor] = None) -> SubmitResult:
        actor = actor or current_actor()
        run = self.store.get(run_id)
        if not run:
            return SubmitResult(False, run_id, 'failed', '', 'No such sync run')
        # Decided under the folder's lock, from the run as it is now: the queue
        # takes the same lock to hand a run its transfer, so the two can never
        # cross with a copy starting that this cancel did not see.
        with self._run_lock(run):
            run = self.store.get(run_id)
            if run['state'] in S.TERMINAL_STATES:
                return SubmitResult(False, run_id, 'failed', run['state'],
                                    'This sync already ended.')
            copying = (run['state'] in (S.QUEUED, S.TRANSFERRING, S.PAUSED)
                       and bool(run.get('transfer_id')) and self.coordinator is not None
                       and self.coordinator.transfer_model.get(run['transfer_id']) is not None)
            if not copying:
                # Not handed to the queue yet, or its transfer row is gone: there
                # is no copy to stop, so the run itself is closed. A Sonarr answer
                # or dry run still on its way finds it closed and is dropped.
                stage = run.get('current_stage') or S.READY
                self._stage(run_id, stage, S.FAILED, f"Cancelled by {actor.label}.",
                            level='warning')
                self._skip_rest(run_id, stage, f"Not reached: cancelled by {actor.label}.")
                self.store.update_webhooks(run_id, {'status': 'cancelled'},
                                           exclude_status=SETTLED_STATUSES)
                self._set_state(run_id, S.CANCELLED, stage, outcome='cancelled',
                                outcome_message=f"Cancelled by {actor.label}")
                return SubmitResult(True, run_id, 'cancelled', S.CANCELLED, 'Cancelled.')
        # Stopping a copy is the queue's job, done outside the folder's lock: the
        # queue calls back into the engine, which takes that lock itself.
        ok = self.coordinator.cancel_transfer(run['transfer_id'])
        if ok:
            self.on_transfer_finished(run['transfer_id'], 'cancelled')
        return SubmitResult(ok, run_id, 'cancelled' if ok else 'failed',
                            (self.store.get(run_id) or {}).get('state', ''),
                            'Cancelled.' if ok else 'Could not cancel the transfer.')

    def mark_done(self, run_id: Optional[str], actor: Optional[Actor] = None,
                  notification_ids: Optional[Sequence[str]] = None) -> bool:
        """An admin says this is fine as it is: close the run and its webhooks."""
        actor = actor or current_actor()
        stamp = datetime.now().isoformat()
        if notification_ids:
            for notification_id in notification_ids:
                table, row = self._find_webhook(notification_id)
                if row is None:
                    continue
                model = (self.coordinator.series_webhook_model if table == SERIES_TABLE
                         else self.coordinator.webhook_model)
                model.update(notification_id, {'status': 'completed', 'completed_at': stamp,
                                               'requires_manual_sync': 0})
        if not run_id:
            return bool(notification_ids)
        run = self.store.get(run_id)
        if not run:
            return False
        note = f"Marked as done by {actor.label}."
        self.store.update_webhooks(run_id, {'status': 'completed', 'completed_at': stamp},
                                   exclude_status=SETTLED_STATUSES)
        transfer_id = run.get('transfer_id')
        if transfer_id and self.coordinator is not None:
            transfer = self.coordinator.transfer_model.get(transfer_id)
            if transfer and transfer['status'] in ('failed', 'cancelled'):
                # The transfer's own record keeps what rsync did; the run
                # records what the admin decided about it.
                note += f" The transfer itself stays recorded as {transfer['status']}."
        self._stage(run_id, S.FINISH, S.PASSED, note, level='info')
        self._set_state(run_id, S.COMPLETED, S.FINISH, outcome='completed',
                        outcome_message=note)
        return True

    def restart_transfer(self, transfer_id: str, actor: Optional[Actor] = None) -> SubmitResult:
        """Retry a failed, cancelled or finished transfer through the pipeline."""
        actor = actor or current_actor()
        if self.coordinator is None:
            return SubmitResult(False, None, 'failed', '', 'No transfer coordinator')
        transfer = self.coordinator.transfer_model.get(transfer_id)
        if not transfer:
            return SubmitResult(False, None, 'failed', '', 'Transfer not found')
        if transfer.get('operation_type') == 'restore':
            return SubmitResult(False, None, 'failed', transfer['status'],
                                'A restore is run again from the Backups page, where its '
                                'preview shows what it will replace.')
        if transfer['status'] not in ('failed', 'cancelled', 'completed'):
            return SubmitResult(False, None, 'failed', transfer['status'],
                                f"Only a failed, cancelled or finished transfer can be "
                                f"restarted (this one is {transfer['status']}).")
        previous = self.store.by_transfer(transfer_id)
        key = make_unit_key(transfer['dest_path'])
        exact = _named_files_only(transfer.get('operation_type'), transfer)

        with self.unit_lock(key):
            if previous is not None and previous['state'] in (S.QUEUED, *S.ACTIVE_STATES):
                # Handed to the queue, yet its transfer has ended: the sync was
                # never told. A start that failed could leave it at Queued or
                # Copying for good. Closed now as its transfer ended, so it
                # neither blocks the folder nor swallows this Retry.
                self.on_transfer_finished(transfer_id, transfer['status'])
                previous = self.store.get(previous['run_id'])
            if previous is not None and previous['state'] not in S.TERMINAL_STATES:
                # A Retry already on its way, still before the queue: pressed
                # twice, the second press goes with the first.
                return self._promote(previous, actor)
            live = self.store.find_live(key)
            if live is not None and live['state'] in S.ACTIVE_STATES:
                return SubmitResult(False, live['run_id'], 'failed', live['state'],
                                    'This folder is being copied right now. Retry once that '
                                    'copy has finished.')
            # A copy of named files is retried on its own, never folded into
            # the folder's batch; the queue keeps the two apart.
            open_run = None if exact else self.store.find_open(key)
            if open_run is not None:
                # Already waiting — possibly the restart pressed a moment ago,
                # still in its safety check. Join it rather than open a second.
                if previous and previous['run_id'] != open_run['run_id'] and \
                        previous['state'] in S.TERMINAL_STATES:
                    for table in (SERIES_TABLE, MOVIE_TABLE):
                        ids = [i for i in self.store.webhook_ids(previous['run_id'], table)]
                        if ids:
                            self.store.move_webhooks(table, ids, open_run['run_id'])
                    self._event(open_run['run_id'], S.BATCH,
                                f"{actor.label} restarted an earlier transfer for this "
                                f"folder; it joined this batch instead of copying twice.")
                return self._promote(open_run, actor)

            request = SyncRequest(
                kind=S.RESTART, media_type=transfer.get('media_type') or '',
                source=(previous or {}).get('source'),
                source_path=transfer['source_path'], dest_path=transfer['dest_path'],
                folder_name=transfer.get('folder_name') or '',
                season_name=transfer.get('season_name'),
                title=(previous or {}).get('title') or transfer.get('parsed_title') or '',
                operation_type=transfer.get('operation_type') or 'folder',
                actor=actor, transfer_id=transfer_id,
                is_simulation=bool(transfer.get('is_simulation')),
                options={k: v for k, v in ((previous or {}).get('options') or {}).items()
                         if k in ('tvdb_id', 'tmdb_id', 'series_id', 'extra_fields',
                                  'simulation_bwlimit')},
                parent_run_id=(previous or {}).get('run_id'),
                parent_relation='retry' if previous else None,
            )
            try:
                unit = from_paths(request.media_type, request.source_path, request.dest_path,
                                  folder_name=request.folder_name,
                                  season_name=request.season_name, title=request.title,
                                  operation_type=request.operation_type)
            except IdentifyError as error:
                return SubmitResult(False, None, 'failed', '', str(error))
            run = self._open_run(request, unit, S.policy(S.RESTART))
            if previous:
                # Webhooks go with a whole-folder copy only: one of named
                # files never looked for their episodes.
                for table in (() if exact else (SERIES_TABLE, MOVIE_TABLE)):
                    ids = self.store.webhook_ids(previous['run_id'], table)
                    if ids:
                        self.store.move_webhooks(table, ids, run['run_id'])
                self._event(previous['run_id'], S.FINISH,
                            f"{actor.label} restarted this transfer as run {run['run_id']}.")
        self.kick(run['run_id'])
        return SubmitResult(True, run['run_id'], 'opened', run['state'],
                            'Restart requested: the safety check runs first, then the queue.',
                            transfer_id=transfer_id)

    def sync_again(self, run_id: str, actor: Optional[Actor] = None) -> SubmitResult:
        """Sync now, on the alert for a sync a restart interrupted.

        Rebuilt from the run's own record, so it copies what that run would
        have: the same folder, the same single file, the same Explore list. An
        exact list is never widened into a whole-folder sync; if the list is
        gone, it says so and copies nothing.
        """
        actor = actor or current_actor()
        run = self.store.get(run_id)
        if not run:
            return SubmitResult(False, run_id, 'failed', '', 'This sync no longer exists.')
        if run['state'] not in S.TERMINAL_STATES:
            return SubmitResult(False, run_id, 'failed', run['state'],
                                'This sync is still on its way.')
        if run['kind'] == S.RESTORE or run.get('operation_type') == 'restore':
            return SubmitResult(False, run_id, 'failed', run['state'],
                                'A restore is run again from the Backups page, where its '
                                'preview shows what it will replace.')
        if run.get('transfer_id') and self.coordinator is not None and \
                self.coordinator.transfer_model.get(run['transfer_id']) is not None:
            # Its transfer was written down: retry that, exactly as it was.
            return self.restart_transfer(run['transfer_id'], actor)
        if run.get('is_simulation'):
            return SubmitResult(False, run_id, 'failed', run['state'],
                                'A simulation is started again from Transfers → Simulate.')

        options = run.get('options') or {}
        extra = dict(options.get('extra_fields') or {})
        files_from = extra.get('explore_files_from')
        if files_from and not os.path.isfile(files_from):
            return SubmitResult(False, run_id, 'failed', run['state'],
                                'The list of files this Explore sync was given is gone, so '
                                'it cannot be repeated exactly. Make the plan again in '
                                'Explore.')

        # Its webhooks come along, so the new sync marks them synced when it
        # finishes. Ones synced since, or taken by another sync, stay where
        # they are, and a copy of named files takes none.
        webhooks = []
        exact = _named_files_only(run.get('operation_type'), extra)
        for table in (() if exact else (SERIES_TABLE, MOVIE_TABLE)):
            for notification_id in self.store.webhook_ids(run_id, table):
                row = self._webhook_row(table, notification_id) or {}
                if row and row.get('status') not in SETTLED_STATUSES:
                    webhooks.append((table, notification_id))

        what = 'the same list of files' if files_from else (
            'the same file' if run.get('operation_type') == 'file' else 'the same folder')
        request = SyncRequest(
            kind=S.EXPLORE if files_from else S.MANUAL,
            source=run.get('source'), media_type=run.get('media_type') or '',
            webhooks=webhooks, source_path=run['source_path'], dest_path=run['dest_path'],
            folder_name=run.get('folder_name') or '', season_name=run.get('season_name'),
            season_number=run.get('season_number'), title=run.get('title') or '',
            operation_type=run.get('operation_type') or 'folder', actor=actor,
            options={k: v for k, v in options.items()
                     if k in ('tvdb_id', 'tmdb_id', 'series_id', 'plan_id', 'mode',
                              'files_to_fetch', 'moved_to_backup')},
            extra_fields=extra if files_from else {},
            # The Explore list's transfer never started, so its id is free;
            # keeping it keeps the plan's records pointing at this copy.
            transfer_id=run.get('transfer_id') if files_from else None,
            safety_summary=(options.get('safety_summary') or '') if files_from else '',
            note=(f"{actor.label} pressed Sync now for run {run_id}, which a restart "
                  f"interrupted. This copies {what} again."),
            parent_run_id=run_id, parent_relation='retry')
        result = self.submit(request)
        if result.ok and result.run_id and result.run_id != run_id:
            self._event(run_id, S.FINISH,
                        f"{actor.label} pressed Sync now: run {result.run_id} does it again.")
        return result

    # ---------------------------------------------- runs the engine only records

    def record_finished_run(self, request: SyncRequest, transfer_id: str,
                            summary: str) -> Optional[str]:
        """A run that ended without a transfer: Explore's removals-only plan."""
        try:
            unit = self.identify(request)
        except IdentifyError:
            return None
        policy = S.policy(request.kind)
        request.actor = request.actor or current_actor()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        actor = request.actor
        self.store.create({
            'run_id': run_id, 'kind': request.kind, 'source': request.source,
            'media_type': unit.media_type, 'unit_key': unit.unit_key,
            'mergeable': 1 if policy.mergeable else 0, 'title': unit.title,
            'season_number': unit.season_number, 'season_name': unit.season_name,
            'folder_name': unit.folder_name, 'source_path': unit.source_path,
            'dest_path': unit.dest_path, 'operation_type': unit.operation_type,
            'state': S.COMPLETED, 'current_stage': S.FINISH, 'transfer_id': transfer_id,
            'requested_by_kind': actor.kind, 'requested_by_name': actor.name,
            'requested_by_account_id': actor.account_id, 'outcome': 'completed',
            'outcome_message': summary, 'finished_at': _now_iso(),
            'options': dict(request.options),
        })
        self._stage(run_id, S.RECEIVE, S.PASSED, self._receive_note(request, unit))
        self._stage(run_id, S.IDENTIFY, S.PASSED,
                    f"{unit.label}: {unit.dest_path}. {policy.note(S.IDENTIFY)}".strip())
        self._stage(run_id, S.BATCH, S.SKIPPED, policy.note(S.BATCH) or 'Stands alone.')
        self._stage(run_id, S.READY, S.SKIPPED, policy.note(S.READY) or 'Not needed.')
        self._stage(run_id, S.SAFETY, S.PASSED,
                    request.safety_summary or policy.note(S.SAFETY) or 'Checked beforehand.')
        self._stage(run_id, S.QUEUE, S.SKIPPED, 'Nothing to copy, so nothing to queue.')
        self._stage(run_id, S.TRANSFER, S.SKIPPED, summary)
        self._stage(run_id, S.FINISH, S.PASSED, 'Recorded in history; the files moved '
                                                 'aside are restorable from Backups.')
        self._stage(run_id, S.TELL, S.SKIPPED, 'Nothing was downloaded, so nothing is '
                                               'announced.')
        return run_id

    def begin_restore(self, transfer_id: str, title: str, dest_path: str,
                      source_path: str, media_type: str, preview: str,
                      capture_id: str, actor: Optional[Actor] = None) -> Optional[str]:
        """A restore was accepted and is about to copy. Recorded through to Transfer."""
        actor = actor or current_actor()
        request = SyncRequest(kind=S.RESTORE, media_type=media_type,
                              source_path=source_path or dest_path, dest_path=dest_path,
                              title=title, actor=actor, transfer_id=transfer_id,
                              safety_summary=preview, options={'capture_id': capture_id})
        try:
            unit = from_paths(media_type, request.source_path, dest_path, title=title)
        except IdentifyError:
            return None
        policy = S.policy(S.RESTORE)
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.store.create({
            'run_id': run_id, 'kind': S.RESTORE, 'media_type': media_type,
            'unit_key': unit.unit_key, 'mergeable': 0, 'title': title,
            'folder_name': unit.folder_name, 'source_path': unit.source_path,
            'dest_path': dest_path, 'operation_type': 'restore',
            'state': S.TRANSFERRING, 'current_stage': S.TRANSFER,
            'transfer_id': transfer_id, 'requested_by_kind': actor.kind,
            'requested_by_name': actor.name, 'requested_by_account_id': actor.account_id,
            'started_at': _now_iso(), 'options': {'capture_id': capture_id},
        })
        self._stage(run_id, S.RECEIVE, S.PASSED, self._receive_note(request, unit))
        self._stage(run_id, S.IDENTIFY, S.PASSED,
                    f"{title}: into {dest_path}. {policy.note(S.IDENTIFY)}")
        self._stage(run_id, S.BATCH, S.SKIPPED, policy.note(S.BATCH))
        self._stage(run_id, S.READY, S.SKIPPED, policy.note(S.READY))
        self._stage(run_id, S.SAFETY, S.PASSED, preview or policy.note(S.SAFETY))
        self._stage(run_id, S.QUEUE, S.PASSED,
                    'The folder was free and a slot was available. ' + policy.note(S.QUEUE))
        self._stage(run_id, S.TRANSFER, S.RUNNING, policy.note(S.TRANSFER))
        return run_id

    # --------------------------------------------------------------- reading

    def summarise(self, run: Dict[str, Any],
                  strip: Optional[Dict[str, str]] = None,
                  webhook_count: Optional[int] = None,
                  current_summary: Optional[str] = None) -> Dict[str, Any]:
        """A run as a list row: what, how far, the stage strip, and what the stage
        it is on last said."""
        if strip is None:
            stages = self.store.stages(run['run_id'])
            strip = {k: v['status'] for k, v in stages.items()}
            if current_summary is None:
                current_summary = (stages.get(run.get('current_stage') or '') or {}).get('summary')
        label = run.get('title') or run.get('folder_name') or 'Sync'
        if run.get('season_name'):
            label = f"{label} — {run['season_name']}"
        return {
            'run_id': run['run_id'],
            'kind': run['kind'],
            'kind_label': S.kind_label(run['kind']),
            'label': label,
            'title': run.get('title'),
            'season_name': run.get('season_name'),
            'media_type': run.get('media_type'),
            'source': run.get('source'),
            'state': run['state'],
            'state_label': S.describe_state(run['state']),
            'current_stage': run.get('current_stage'),
            'current_summary': current_summary,
            'outcome': run.get('outcome'),
            'outcome_message': run.get('outcome_message'),
            'transfer_id': run.get('transfer_id'),
            'parent_run_id': run.get('parent_run_id'),
            'parent_relation': run.get('parent_relation'),
            'is_simulation': bool(run.get('is_simulation')),
            'requested_by': {
                'kind': run.get('requested_by_kind'), 'name': run.get('requested_by_name'),
                'label': _actor_from_run(run).label,
            },
            'stages': [{'id': stage_id, 'status': strip.get(stage_id, S.PENDING)}
                       for stage_id in S.STAGE_IDS],
            'webhook_count': webhook_count,
            'next_check_at': _clock_iso(run.get('next_check_at')),
            'created_at': run.get('created_at'),
            'updated_at': run.get('updated_at'),
            'started_at': run.get('started_at'),
            'finished_at': run.get('finished_at'),
        }

    def list_runs(self, states=None, kinds=None, search=None, limit: int = 50,
                  offset: int = 0, include_simulation: bool = True,
                  copied: Optional[bool] = None) -> Dict[str, Any]:
        runs = self.store.list(states=states, kinds=kinds, search=search, limit=limit,
                               offset=offset, include_simulation=include_simulation,
                               copied=copied)
        ids = [r['run_id'] for r in runs]
        strips = self.store.stage_strips(ids)
        counts = self.store.webhook_counts(ids)
        sentences = self.store.current_summaries(runs)
        return {
            'runs': [self.summarise(r, strips.get(r['run_id'], {}), counts.get(r['run_id'], 0),
                                    sentences.get(r['run_id']))
                     for r in runs],
            'total': self.store.count(states=states, kinds=kinds, search=search,
                                      include_simulation=include_simulation, copied=copied),
            'state_counts': self.store.state_counts(include_simulation=include_simulation),
        }

    def describe_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Everything about one run, stage by stage, for the pipeline view."""
        run = self.store.get(run_id)
        if not run:
            return None
        policy = S.policy(run['kind']) if run['kind'] in S.KINDS else None
        stage_rows = self.store.stages(run_id)
        events = self.store.events(run_id)
        by_stage: Dict[str, List[Dict[str, Any]]] = {stage_id: [] for stage_id in S.STAGE_IDS}
        for event in events:
            by_stage.setdefault(event['stage'], []).append(event)

        stages_out = []
        for stage in S.STAGES:
            row = stage_rows.get(stage.id) or {}
            stages_out.append({
                'id': stage.id,
                'label': stage.label,
                'tagline': stage.tagline,
                'description': stage.description,
                'mode': policy.mode(stage.id) if policy else S.RUN,
                'policy_note': policy.note(stage.id) if policy else '',
                'status': row.get('status') or S.PENDING,
                'summary': row.get('summary'),
                'detail': row.get('detail'),
                'started_at': row.get('started_at'),
                'finished_at': row.get('finished_at'),
                'events': by_stage.get(stage.id, []),
            })

        transfer = None
        if run.get('transfer_id') and self.coordinator is not None:
            row = self.coordinator.transfer_model.get(run['transfer_id'])
            if row:
                transfer = {
                    'transfer_id': row['transfer_id'], 'status': row['status'],
                    'progress': row.get('progress'), 'transport': row.get('transport'),
                    'progress_percent': row.get('progress_percent'),
                    'bytes_transferred': row.get('bytes_transferred'),
                    'total_bytes': row.get('total_bytes'), 'speed_bps': row.get('speed_bps'),
                    'eta_seconds': row.get('eta_seconds'),
                    'start_time': row.get('start_time'), 'end_time': row.get('end_time'),
                    'log_count': len(row.get('logs') or []),
                    'queue_reason': row.get('queue_reason'),
                }

        related = []
        if run.get('parent_run_id'):
            parent = self.store.get(run['parent_run_id'])
            if parent:
                related.append({'relation': f"{run.get('parent_relation') or 'related'}_of",
                                **self.summarise(parent)})
        for child in self.store.children(run_id):
            related.append({'relation': child.get('parent_relation') or 'related',
                            **self.summarise(child)})

        alerts = []
        if self.alerts is not None:
            try:
                alerts = self.alerts.for_run(run_id)
            except Exception:  # noqa: BLE001
                alerts = []

        summary = self.summarise(
            run, {k: v['status'] for k, v in stage_rows.items()}, None,
            (stage_rows.get(run.get('current_stage') or '') or {}).get('summary'))
        webhooks = self.store.webhooks(run_id)
        summary['webhook_count'] = len(webhooks)
        return {
            **summary,
            'source_path': run.get('source_path'),
            'dest_path': run.get('dest_path'),
            'operation_type': run.get('operation_type'),
            'ready_mode': run.get('ready_mode'),
            'checks_made': run.get('checks_made'),
            'timer_due_at': _clock_iso(run.get('timer_due_at')),
            'ready_deadline_at': _clock_iso(run.get('ready_deadline_at')),
            'force_safety': bool(run.get('force_safety')),
            'stage_detail': stages_out,
            'webhooks': webhooks,
            'transfer': transfer,
            'related': related,
            'alerts': alerts,
            'actions': self._actions_for(run),
        }

    @staticmethod
    def _actions_for(run: Dict[str, Any]) -> List[str]:
        state = run['state']
        actions = []
        if state in (S.HELD, S.WAITING_STATE):
            actions.append('go_now')
        if state in S.LIVE_STATES:
            actions.append('cancel')
        if state == S.REFUSED_STATE:
            actions.append('sync_anyway')
        if state in (S.FAILED_STATE, S.CANCELLED) and run.get('transfer_id'):
            actions.append('restart')
        return actions
