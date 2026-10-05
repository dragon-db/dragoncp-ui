#!/usr/bin/env python3
"""
Alerts: everything that needs a person, in one place.

The sync engine opens them; an admin closes them by acting — Sync now, Retry,
Sync anyway, Mark as done, Mark as wrong, Dismiss. Every alert is also
announced through the connector layer (Discord today), once, when it opens;
the same thing happening again while it is open bumps the alert rather than
sending a second message.

Each kind of alert is a method here, so the wording, the severity, the actions
offered and the Discord event live together and cannot drift between the
places that raise them.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from activity_log import record
from actor import current_actor
from models.alert import DISMISSED, DONE, OPEN, WRONG, AlertStore

log = logging.getLogger('dragoncp.alerts')

INFO = 'info'
WARNING = 'warning'
FAILURE = 'failure'

#: How long a dismissed alert for a recurring condition stays quiet.
QUIET_AFTER_DISMISS = timedelta(hours=24)

#: What each action is called on a button.
ACTION_LABELS = {
    'sync_now': 'Sync now',
    'retry': 'Retry',
    'sync_anyway': 'Sync anyway',
    'run_now': 'Run now',
    'mark_done': 'Mark as done',
    'mark_wrong': 'Mark as wrong',
    'dismiss': 'Dismiss',
}

#: What closing an alert with each action leaves it as.
_RESOLVES_TO = {
    'sync_now': DONE, 'retry': DONE, 'sync_anyway': DONE, 'run_now': DONE,
    'mark_done': DONE, 'mark_wrong': WRONG, 'dismiss': DISMISSED,
}

#: Kinds of alert, for the interface's filter.
KINDS = {
    'restart_unfinished': 'After a restart',
    'transfer_unknown': 'Result unknown',
    'stuck_download': 'Stuck download',
    'ready_timeout': 'Waited 30 minutes',
    'sync_refused': 'Safety check',
    'transfer_failed': 'Failed',
    'scanner_gap': 'Auto-scanner',
    'integration_down': 'Integration',
    'job_failing': 'Scheduler',
}


def _run_label(run: Dict[str, Any]) -> str:
    label = run.get('title') or run.get('folder_name') or 'A sync'
    if run.get('season_name'):
        label = f"{label} — {run['season_name']}"
    return label


def _run_link(run_id: Optional[str]) -> Optional[str]:
    return f"/pipeline/{run_id}" if run_id else None


class AlertService:
    def __init__(self, store: AlertStore, socketio=None):
        self.store = store
        self.socketio = socketio
        #: Set once the engine and the scheduler exist; actions need them.
        self.engine = None
        self.scheduler = None

    # ------------------------------------------------------------- the core

    def raise_alert(self, kind: str, title: str, message: str = '',
                    severity: str = WARNING, dedupe_key: Optional[str] = None,
                    run_id: Optional[str] = None, transfer_id: Optional[str] = None,
                    unit_key: Optional[str] = None, link: Optional[str] = None,
                    actions: Sequence[str] = ('dismiss',), data: Optional[Dict] = None,
                    announce_event: Optional[str] = None,
                    fields: Sequence[Tuple[str, str]] = (),
                    quiet_after_dismiss: bool = False) -> Optional[Dict[str, Any]]:
        """Open an alert, or bump the open one with the same key. Never raises.

        `quiet_after_dismiss` is for conditions checked on a schedule — a gap
        the scanner keeps finding, a job that keeps failing, a service that
        stays down. Dismissed or marked wrong, such an alert stays closed for a
        day rather than coming back, and back to Discord, every scan.
        """
        try:
            existing = self.store.find_open(dedupe_key) if dedupe_key else None
            if existing is None and dedupe_key and quiet_after_dismiss and \
                    self.store.closed_by_a_person_since(dedupe_key, QUIET_AFTER_DISMISS):
                return None
            if existing is not None:
                alert = self.store.bump(existing['alert_id'], message=message,
                                        data=data, run_id=run_id)
                self._emit()
                return alert
            alert = self.store.create(kind, severity, title, message, dedupe_key=dedupe_key,
                                      run_id=run_id, transfer_id=transfer_id,
                                      unit_key=unit_key, link=link or _run_link(run_id),
                                      actions=actions, data=data)
            log.info('Alert opened: %s — %s', kind, title)
            if announce_event:
                self._announce(announce_event, severity, title, message, fields)
            self._emit()
            return alert
        except Exception:  # noqa: BLE001 - raising an alert must never break a sync
            log.exception('Could not open alert %s', kind)
            return None

    def _announce(self, event_key: str, severity: str, title: str, message: str,
                  fields: Sequence[Tuple[str, str]]) -> None:
        try:
            from services.connectors import notify
            from services.connectors.events import Event, Field
            event_fields = [Field(name, value) for name, value in fields if value]
            event_fields.append(Field('What to do',
                                      'Open DragonCP → Notifications to act on it.'))
            notify(Event(
                key=event_key, severity=severity if severity in
                ('info', 'success', 'warning', 'failure') else 'warning',
                title=title, summary=message[:900] if message else '',
                fields=tuple(event_fields), author='DragonCP Notifications',
            ))
        except Exception:  # noqa: BLE001
            log.exception('Could not announce alert %s', title)

    def _emit(self) -> None:
        if self.socketio is None:
            return
        try:
            self.socketio.emit('alerts_changed', self.summary())
        except Exception:  # noqa: BLE001
            pass

    def summary(self) -> Dict[str, Any]:
        return {'open': self.store.count([OPEN]),
                'by_severity': self.store.open_counts_by_severity()}

    def list(self, state: Optional[str] = 'open', kinds=None, limit: int = 50,
             offset: int = 0) -> Dict[str, Any]:
        states = None if state in (None, '', 'all') else [state]
        rows = self.store.list(states=states, kinds=kinds, limit=limit, offset=offset)
        return {'alerts': [self.present(r) for r in rows],
                'total': self.store.count(states, kinds), **self.summary()}

    def present(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(alert)
        out['kind_label'] = KINDS.get(alert.get('kind'), alert.get('kind'))
        out['action_buttons'] = [{'id': a, 'label': ACTION_LABELS.get(a, a)}
                                 for a in alert.get('actions') or []]
        return out

    def for_run(self, run_id: str) -> List[Dict[str, Any]]:
        return [self.present(a) for a in self.store.list(run_id=run_id, limit=20)]

    # -------------------------------------------------------------- acting

    def act(self, alert_id: str, action: str, actor=None) -> Tuple[bool, str, Optional[Dict]]:
        """An admin acted on an alert. Does the thing, then closes the alert."""
        actor = actor or current_actor()
        alert = self.store.get(alert_id)
        if not alert:
            return False, 'No such alert', None
        if alert['state'] != OPEN:
            return False, 'This alert is already closed', self.present(alert)
        if action not in (alert.get('actions') or []) and action not in ('dismiss',):
            return False, f"“{ACTION_LABELS.get(action, action)}” is not offered on this alert", \
                self.present(alert)

        ok, message = self._perform(alert, action, actor)
        if not ok:
            return False, message, self.present(alert)
        closed = self.store.resolve(alert_id, _RESOLVES_TO.get(action, DONE), action, actor)
        record('alert.resolve',
               f"{ACTION_LABELS.get(action, action)}: {alert['title']}",
               target_type='alert', target_id=alert_id, target_label=alert['title'],
               detail={'kind': alert['kind'], 'action': action, 'result': message})
        self._emit()
        return True, message, self.present(closed)

    def _perform(self, alert: Dict[str, Any], action: str, actor) -> Tuple[bool, str]:
        data = alert.get('data') or {}
        engine = self.engine
        if action in ('dismiss', 'mark_wrong'):
            return True, 'Closed.'

        if action == 'mark_done':
            if engine is not None and alert['kind'] in (
                    'transfer_unknown', 'restart_unfinished', 'transfer_failed'):
                engine.mark_done(
                    alert.get('run_id'), actor,
                    notification_ids=(data.get('notification_ids')
                                      if alert['kind'] == 'restart_unfinished' else None))
            return True, 'Marked as done.'

        if engine is None:
            return False, 'The sync engine is not running'

        if action == 'sync_now':
            ids = data.get('notification_ids') or []
            if ids:
                result = engine.sync_notifications(ids, actor)
                return bool(result.get('ok')), result.get('message') or 'Sync requested.'
            unit = data.get('unit') or {}
            if unit.get('source_path') and unit.get('dest_path'):
                from services.sync_engine.engine import SyncRequest
                result = engine.submit(SyncRequest(
                    kind='manual', source=data.get('source'),
                    media_type=unit.get('media_type') or '',
                    source_path=unit['source_path'], dest_path=unit['dest_path'],
                    folder_name=unit.get('folder_name') or '',
                    season_name=unit.get('season_name'), title=unit.get('title') or '',
                    actor=actor))
                return result.ok, result.message
            return False, 'This alert does not say what to sync'

        if action == 'retry':
            transfer_id = alert.get('transfer_id') or data.get('transfer_id')
            if not transfer_id:
                return False, 'This alert does not name a transfer'
            result = engine.restart_transfer(transfer_id, actor)
            return result.ok, result.message

        if action == 'sync_anyway':
            if not alert.get('run_id'):
                return False, 'This alert does not name a sync'
            result = engine.sync_anyway(alert['run_id'], actor)
            return result.ok, result.message

        if action == 'run_now':
            if self.scheduler is None or not data.get('job'):
                return False, 'No scheduler job to run'
            ok = self.scheduler.run_now(data['job'])
            return ok, 'Started.' if ok else 'That job is already running.'

        return False, f"Unknown action {action}"

    # ----------------------------------------------------- the kinds of alert

    def integration_down(self, source: str, message: str) -> None:
        name = source.title()
        self.raise_alert(
            'integration_down', f"{name} isn’t answering",
            f"Automatic sync fell back to the fixed timer. {name} said: {message}",
            WARNING, dedupe_key=f"integration_down:{source}",
            link=f"/integrations/{source}", actions=('dismiss',),
            data={'source': source}, announce_event='integration.down',
            quiet_after_dismiss=True)

    def integration_up(self, source: str) -> None:
        """A service answered again: close its open "not answering" alert."""
        try:
            existing = self.store.find_open(f"integration_down:{source}")
            if existing:
                from actor import SYSTEM_ACTOR
                self.store.resolve(existing['alert_id'], DONE, 'auto', SYSTEM_ACTOR)
                self._emit()
        except Exception:  # noqa: BLE001
            pass

    def stuck_download(self, run: Dict[str, Any], answer) -> None:
        label = _run_label(run)
        stuck = '\n'.join(getattr(answer, 'stuck_detail', ()) or ()) or \
            f"{getattr(answer, 'stuck', 0)} stuck"
        self.raise_alert(
            'stuck_download', f"Synced without a stuck download: {label}",
            f"{label} synced, but something for it is stuck in Sonarr and was not waited "
            f"for:\n{stuck}\nIt syncs on its own once it arrives.",
            WARNING, dedupe_key=f"stuck:{run.get('unit_key')}", run_id=run['run_id'],
            unit_key=run.get('unit_key'), actions=('dismiss',),
            data={'stuck': list(getattr(answer, 'stuck_detail', ()) or ())},
            announce_event='sync.stuck', fields=(('Stuck in Sonarr', stuck),))

    def ready_timeout(self, run: Dict[str, Any], answer) -> None:
        label = _run_label(run)
        still = '\n'.join(getattr(answer, 'detail', ()) or ()) or 'still downloading'
        self.raise_alert(
            'ready_timeout', f"Synced after 30 minutes of waiting: {label}",
            f"Sonarr still had downloads for {label} after 30 minutes, so the season "
            f"synced with what was there:\n{still}\nThe rest arrives through its own "
            f"webhook or the auto-scanner.",
            WARNING, dedupe_key=f"ready_timeout:{run.get('unit_key')}",
            run_id=run['run_id'], unit_key=run.get('unit_key'), actions=('dismiss',),
            data={'still_downloading': list(getattr(answer, 'detail', ()) or ())},
            announce_event='sync.stuck', fields=(('Still downloading', still),))

    def sync_refused(self, run: Dict[str, Any], reason: str, detail: Dict[str, Any],
                     announce: bool = True) -> None:
        label = _run_label(run)
        counts = (f"Media server: {detail.get('server_file_count', 0)} files · "
                  f"this disk: {detail.get('local_file_count', 0)} · would delete "
                  f"{detail.get('deleted_count', 0)} · would add "
                  f"{detail.get('incoming_count', 0)}")
        self.raise_alert(
            'sync_refused', f"Sync stopped by the safety check: {label}",
            f"{reason}. Nothing was written. {counts}.",
            WARNING, dedupe_key=f"refused:{run['run_id']}", run_id=run['run_id'],
            unit_key=run.get('unit_key'), actions=('sync_anyway', 'dismiss'),
            data={'reason': reason, 'counts': counts,
                  'explore': {'media_type': run.get('media_type'),
                              'folder': run.get('folder_name'),
                              'season': run.get('season_name')}},
            announce_event='autosync.blocked' if announce else None,
            fields=(('Reason', reason), ('Folder', run.get('dest_path') or ''),
                    ('File analysis', counts)))

    def transfer_failed(self, run: Dict[str, Any], message: str) -> None:
        label = _run_label(run)
        restore = run.get('kind') == 'restore'
        self.raise_alert(
            'transfer_failed', f"{'Restore' if restore else 'Transfer'} failed: {label}",
            (message or 'rsync stopped without finishing.') +
            (' Run it again from the Backups page.' if restore else ''),
            FAILURE, dedupe_key=f"failed:{run.get('transfer_id') or run['run_id']}",
            run_id=run['run_id'], transfer_id=run.get('transfer_id'),
            unit_key=run.get('unit_key'),
            actions=('dismiss',) if restore else ('retry', 'mark_done', 'dismiss'),
            data={'transfer_id': run.get('transfer_id')},
            # The failure itself was announced by the pipeline's Tell stage.
            announce_event=None)

    def restart_unfinished(self, unit_key: str, label: str, notification_ids: List[str],
                           run_id: Optional[str] = None, what: str = '') -> None:
        count = len(notification_ids)
        noun = 'webhook' if count == 1 else 'webhooks'
        message = (what or f"{count} {noun} for {label} were waiting to sync when "
                           f"DragonCP stopped. Nothing restarts by itself: sync now if "
                           f"they still need copying, or mark this done.")
        self.raise_alert(
            'restart_unfinished', f"Some syncs might have been skipped: {label}",
            message, WARNING, dedupe_key=f"restart:{unit_key}", run_id=run_id,
            unit_key=unit_key,
            actions=('sync_now', 'mark_done', 'mark_wrong', 'dismiss'),
            data={'notification_ids': list(notification_ids)},
            announce_event='sync.interrupted', fields=(('Waiting', f"{count} {noun}"),))

    def transfer_unknown(self, run: Dict[str, Any], transfer_id: str) -> None:
        label = _run_label(run)
        self.raise_alert(
            'transfer_unknown', f"Result unknown after a restart: {label}",
            f"DragonCP restarted while {label} was copying, and the copy's result could "
            f"not be read. Check the folder, then retry it or mark it done.",
            WARNING, dedupe_key=f"unknown:{transfer_id}", run_id=run.get('run_id'),
            transfer_id=transfer_id, unit_key=run.get('unit_key'),
            actions=('retry', 'mark_done', 'dismiss'), data={'transfer_id': transfer_id},
            announce_event='sync.interrupted')

    def scanner_gap(self, source: str, label: str, unit: Dict[str, Any], why: str) -> None:
        self.raise_alert(
            'scanner_gap', f"The auto-scanner can’t close a gap: {label}",
            f"{why} Syncing it failed twice, so the scanner will not retry it by itself.",
            WARNING, dedupe_key=f"gap:{unit.get('dest_path')}",
            unit_key=unit.get('dest_path'), actions=('sync_now', 'dismiss'),
            data={'unit': unit, 'source': source}, announce_event='scanner.found',
            quiet_after_dismiss=True)

    def job_failing(self, job: str, label: str, error: str, failures: int) -> None:
        self.raise_alert(
            'job_failing', f"Background job failing: {label}",
            f"{label} failed {failures} times in a row. Last error: {error}",
            WARNING, dedupe_key=f"job:{job}", actions=('run_now', 'dismiss'),
            data={'job': job, 'error': error}, announce_event='scheduler.failing',
            quiet_after_dismiss=True)

    def job_recovered(self, job: str) -> None:
        try:
            existing = self.store.find_open(f"job:{job}")
            if existing:
                from actor import SYSTEM_ACTOR
                self.store.resolve(existing['alert_id'], DONE, 'auto', SYSTEM_ACTOR)
                self._emit()
        except Exception:  # noqa: BLE001
            pass
