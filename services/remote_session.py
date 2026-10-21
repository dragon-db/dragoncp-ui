#!/usr/bin/env python3
"""
The one browse session to the remote server, and every rule about opening it.

Explore reads the remote library over a single SSH session. It used to be
opened only when someone pressed Auto Connect in Settings, was gone after every
restart, and was believed open after the server had reset it — so Re-check
failed at once and the fix was a trip to Settings (operator, 2026-10-20).

Now Explore asks this for a session and gets a live one: reconnected with the
saved login when it is missing or dead, if the **Auto-connect** setting is on.

The rule that matters more than the convenience: **never hammer the remote
server** (operator, 2026-10-20). A run of failed logins is what gets an address
banned, and a ban stops every sync, not just Explore. So:

* one connect at a time — concurrent requests wait for it and share the result;
* after a failed automatic attempt, the next waits 30 s, then 1, 2, 4, 5 min;
* a refused login or a host key that does not match **stops** automatic
  attempts until a person connects by hand — retrying a wrong password
  achieves nothing but the ban;
* a person's own attempts are spaced too: 60 s after a refused login, 10 s
  after any other failure.

The sync engine does not use this session: rsync opens its own, and the fast
transfer server's set-up opens short-lived ones of its own.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from ssh import FAILED_AUTH, FAILED_HOST_KEY, SSHManager

log = logging.getLogger('dragoncp.remote_session')

#: Wait before the next automatic attempt, after the 1st, 2nd, … failure.
RETRY_DELAYS = (30, 60, 120, 240, 300)

#: The least a person waits between their own attempts, by why the last failed.
MANUAL_SPACING = {FAILED_AUTH: 60, FAILED_HOST_KEY: 60}
MANUAL_SPACING_OTHER = 10

#: Failures that stop automatic attempts until a person connects.
PAUSING = (FAILED_AUTH, FAILED_HOST_KEY)


def _clock_text(moment: float) -> str:
    return datetime.fromtimestamp(moment).strftime('%H:%M:%S')


class SessionUnavailable(Exception):
    """No live session, and none may be opened right now. Says why, for a person."""

    def __init__(self, message: str, reason: str, retry_at: Optional[float] = None):
        super().__init__(message)
        self.message = message
        #: off | not_configured | paused | waiting | failed
        self.reason = reason
        self.retry_at = retry_at


class RemoteSession:
    def __init__(self, config, settings=None,
                 on_change: Optional[Callable[[Optional[SSHManager]], None]] = None,
                 factory: Optional[Callable[..., Any]] = None,
                 clock: Callable[[], float] = time.time):
        self.config = config
        self.settings = settings
        self.on_change = on_change
        self.factory = factory or SSHManager
        self.clock = clock
        self.manager = None
        self._lock = threading.Lock()
        self.failures = 0
        self.last_failure_at: Optional[float] = None
        self.last_error = ''
        self.last_error_kind: Optional[str] = None
        self.next_attempt_at = 0.0
        self.paused = False

    # ------------------------------------------------------------ reading

    def auto_connect(self) -> bool:
        if self.settings is None:
            return True
        try:
            return self.settings.get_bool('SSH_AUTO_CONNECT', True)
        except Exception:  # noqa: BLE001
            return True

    def alive(self) -> bool:
        manager = self.manager
        if manager is None:
            return False
        check = getattr(manager, 'is_alive', None)
        return bool(check()) if check is not None else bool(getattr(manager, 'connected', False))

    def status(self) -> Dict[str, Any]:
        connected = self.alive()
        now = self.clock()

        def iso(moment: Optional[float]) -> Optional[str]:
            if not moment or moment <= now:
                return None
            return datetime.fromtimestamp(moment, timezone.utc).isoformat()

        failing = not connected and self.last_failure_at is not None
        return {
            'connected': connected,
            'auto_connect': self.auto_connect(),
            'host': (self.config.get('REMOTE_IP') if self.config else '') or '',
            'last_error': '' if connected else self.last_error,
            'last_error_kind': None if connected else self.last_error_kind,
            'paused': self.paused and not connected,
            #: When it tries again by itself (None when paused or not failing).
            'retry_at': iso(self.next_attempt_at) if failing and not self.paused else None,
            #: When a person may press Connect again.
            'manual_retry_at': iso(self._manual_allowed_at()) if failing else None,
        }

    # ------------------------------------------------------------ opening

    def ensure(self):
        """A live session, opening one with the saved login if that is allowed now."""
        if self.alive():
            return self.manager
        if not self.auto_connect():
            raise SessionUnavailable(
                'Not connected to the remote server. Auto-connect is off, so connect by hand.',
                'off')
        ok, message = self._connect(manual=False)
        if ok:
            return self.manager
        raise SessionUnavailable(message, self._reason(), self._retry_at())

    def connect(self, credentials: Optional[Dict[str, str]] = None) -> Tuple[bool, str]:
        """A person asked to connect: Connect in Settings, or on the Explore page."""
        return self._connect(manual=True, credentials=credentials)

    def _connect(self, manual: bool,
                 credentials: Optional[Dict[str, str]] = None) -> Tuple[bool, str]:
        # One attempt at a time. Whoever waited here finds the session the
        # first one opened, or the reason it could not, and does not try again.
        with self._lock:
            if self.alive() and credentials is None:
                return True, 'Connected'
            now = self.clock()
            if manual:
                allowed = self._manual_allowed_at()
                if now < allowed:
                    return False, (f"{self._failure_text()} To keep the remote server from "
                                   f"banning this address, the next try is allowed at "
                                   f"{_clock_text(allowed)}.")
            else:
                if self.paused:
                    return False, (f"{self._failure_text()} Automatic connecting is paused "
                                   f"so repeated attempts cannot get this address banned. "
                                   f"Check the login, then connect by hand.")
                if now < self.next_attempt_at:
                    return False, (f"{self._failure_text()} Trying again at "
                                   f"{_clock_text(self.next_attempt_at)}.")

            host = (credentials or {}).get('host') or self.config.get('REMOTE_IP')
            username = (credentials or {}).get('username') or self.config.get('REMOTE_USER')
            if not host or not username:
                return False, 'No remote server is configured (REMOTE_IP and REMOTE_USER).'
            password = (credentials or {}).get('password') if credentials else \
                self.config.get('REMOTE_PASSWORD', '')
            key_path = (credentials or {}).get('key_path') if credentials else \
                self.config.get('SSH_KEY_PATH', '')

            manager = self.factory(
                host, username, password or '', key_path or '',
                host_key_policy=self.config.get('SSH_HOST_KEY_CHECKING', 'accept-new'),
                known_hosts_file=self.config.get('SSH_KNOWN_HOSTS_FILE', ''))
            how = 'by hand' if manual else 'automatically'
            if manager.connect():
                previous, self.manager = self.manager, manager
                self.failures = 0
                self.last_failure_at = None
                self.last_error = ''
                self.last_error_kind = None
                self.next_attempt_at = 0.0
                self.paused = False
                if previous is not None and previous is not manager:
                    # The old one, dead or not, is closed rather than left open.
                    try:
                        previous.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                log.info('Connected to the remote server %s (%s)', host, how)
                self._changed()
                return True, 'Connected'

            self.failures += 1
            self.last_failure_at = now
            self.last_error = getattr(manager, 'last_error', '') or 'Connection failed'
            self.last_error_kind = getattr(manager, 'last_error_kind', None)
            delay = RETRY_DELAYS[min(self.failures, len(RETRY_DELAYS)) - 1]
            self.next_attempt_at = now + delay
            if self.last_error_kind in PAUSING:
                self.paused = True
            log.warning('Could not connect to the remote server %s (%s, failure %d): %s',
                        host, how, self.failures, self.last_error)
            return False, self._failure_text()

    def disconnect(self) -> None:
        """A person closed the session. Auto-connect may open it again when needed."""
        with self._lock:
            manager, self.manager = self.manager, None
            if manager is not None:
                try:
                    manager.disconnect()
                except Exception:  # noqa: BLE001
                    pass
        self._changed()

    # ------------------------------------------------------------ helpers

    def _manual_allowed_at(self) -> float:
        if self.last_failure_at is None:
            return 0.0
        return self.last_failure_at + MANUAL_SPACING.get(self.last_error_kind,
                                                         MANUAL_SPACING_OTHER)

    def _failure_text(self) -> str:
        if self.last_error_kind == FAILED_AUTH:
            return f"The remote server refused the login ({self.last_error})."
        if self.last_error_kind == FAILED_HOST_KEY:
            return f"{self.last_error}; not connecting to it."
        return f"Could not reach the remote server ({self.last_error or 'no answer'})."

    def _reason(self) -> str:
        if self.paused:
            return 'paused'
        if self.last_failure_at is not None and self.clock() < self.next_attempt_at:
            return 'waiting'
        return 'failed'

    def _retry_at(self) -> Optional[float]:
        if self.paused:
            return self._manual_allowed_at()
        return self.next_attempt_at or None

    def _changed(self) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change(self.manager)
        except Exception:  # noqa: BLE001
            log.exception('Could not hand the new session to the routes')
