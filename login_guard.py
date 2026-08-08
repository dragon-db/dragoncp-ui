#!/usr/bin/env python3
"""
DragonCP Login Guard
Brute-force protection for the sign-in endpoint.

Sign-in was previously unlimited: an attacker could try passwords as fast as the
server would answer. With one shared account that was a single guessable secret;
with named accounts there are several, and a username that leaks — from a log
line, an activity trail, or a colleague — is half the credential.

Two counters run side by side, and either one can lock:

    by address   catches a single source working through passwords
    by username  catches a distributed attempt against one known account

The username counter is a deliberate trade-off. Someone who knows a colleague's
username can lock that person out for the cooldown by failing often enough. For
a small administrative console that is the right way round: a brief denial is
recoverable, a guessed password is not. The cooldown is short and the limits are
configurable.

State is in memory. The application runs as one process, so that is sufficient,
and a restart clearing the counters is acceptable — it takes a deliberate
restart, which an attacker cannot cause.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple


DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_WINDOW_SECONDS = 15 * 60
DEFAULT_LOCKOUT_SECONDS = 15 * 60

_config = {
    'max_attempts': DEFAULT_MAX_ATTEMPTS,
    'window_seconds': DEFAULT_WINDOW_SECONDS,
    'lockout_seconds': DEFAULT_LOCKOUT_SECONDS,
    'enabled': True,
}

_lock = threading.RLock()
_failures: Dict[str, deque] = defaultdict(deque)
_locked_until: Dict[str, float] = {}


def configure(
    max_attempts: Optional[int] = None,
    window_seconds: Optional[int] = None,
    lockout_seconds: Optional[int] = None,
    enabled: Optional[bool] = None,
) -> Dict:
    """
    Set the limits, usually once at startup from the environment file.

    Any argument left as None keeps its current value.
    """
    with _lock:
        if max_attempts is not None:
            _config['max_attempts'] = max(1, int(max_attempts))
        if window_seconds is not None:
            _config['window_seconds'] = max(30, int(window_seconds))
        if lockout_seconds is not None:
            _config['lockout_seconds'] = max(30, int(lockout_seconds))
        if enabled is not None:
            _config['enabled'] = bool(enabled)
        return dict(_config)


def current_config() -> Dict:
    """The limits in force, for diagnostics."""
    with _lock:
        return dict(_config)


def _keys(username: str, address: str) -> Tuple[str, ...]:
    """The counters one sign-in attempt touches."""
    keys = []
    if username:
        keys.append(f'user:{username.strip().lower()}')
    if address:
        keys.append(f'addr:{address}')
    return tuple(keys)


def _prune(key: str, now: float) -> deque:
    """Drop failures that have aged out of the window."""
    window = _config['window_seconds']
    hits = _failures[key]
    while hits and now - hits[0] > window:
        hits.popleft()
    return hits


def retry_after(username: str, address: str) -> Optional[int]:
    """
    Seconds until this attempt would be allowed, or None if it may proceed.

    Call before checking the password, so a locked-out caller never reaches the
    credential check at all.
    """
    with _lock:
        if not _config['enabled']:
            return None

        now = time.monotonic()
        longest = None

        for key in _keys(username, address):
            unlock_at = _locked_until.get(key)
            if unlock_at is None:
                continue
            if unlock_at <= now:
                # Cooldown served. Clear it and the failures that caused it, so
                # the next mistake starts from a clean slate rather than
                # re-locking on the first try.
                _locked_until.pop(key, None)
                _failures.pop(key, None)
                continue
            remaining = int(unlock_at - now) + 1
            longest = remaining if longest is None else max(longest, remaining)

        return longest


def record_failure(username: str, address: str) -> Optional[int]:
    """
    Note a failed sign-in. Returns the cooldown in seconds if this one locked.
    """
    with _lock:
        if not _config['enabled']:
            return None

        now = time.monotonic()
        locked_for = None

        for key in _keys(username, address):
            hits = _prune(key, now)
            hits.append(now)

            if len(hits) >= _config['max_attempts']:
                unlock_at = now + _config['lockout_seconds']
                _locked_until[key] = unlock_at
                locked_for = _config['lockout_seconds']

        return locked_for


def record_success(username: str, address: str) -> None:
    """Clear the counters after a sign-in that worked."""
    with _lock:
        for key in _keys(username, address):
            _failures.pop(key, None)
            _locked_until.pop(key, None)


def failure_count(username: str, address: str) -> int:
    """Failures currently counted against the stricter of the two keys."""
    with _lock:
        now = time.monotonic()
        return max(
            (len(_prune(key, now)) for key in _keys(username, address)),
            default=0,
        )


def reset() -> None:
    """Forget every counter. For tests and for an operator unlocking by hand."""
    with _lock:
        _failures.clear()
        _locked_until.clear()
