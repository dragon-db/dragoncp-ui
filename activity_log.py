#!/usr/bin/env python3
"""
DragonCP Activity Recording
The one call the rest of the application makes to say what just happened.

    from activity_log import record
    record('backup.restore', f"Restored {label}", target_type='backup_capture',
           target_id=capture_id, target_label=label)

Who did it is not passed in. It is resolved from context — the signed-in
administrator on this request, or whatever a background thread declared with
`acting_as` — so a call site cannot attribute an action to the wrong person by
passing the wrong argument, and adding a new action does not mean threading an
actor down to it.

Nothing here raises. A restore that happened is a fact whether or not the trail
caught it, and a failure to write bookkeeping must not turn into a failed
request.
"""

from typing import Dict, Optional

from actor import Actor, current_actor
from models.activity import OUTCOME_FAILED, OUTCOME_OK, OUTCOME_REFUSED


#: Set by app.py once the database exists. Left as None in tests and any context
#: without one, where recording is a no-op.
_store = None


def set_store(store) -> None:
    """Give the recorder its table. Called once during startup."""
    global _store
    _store = store


def get_store():
    """The activity table, or None when running without a database."""
    return _store


def _request_ip() -> Optional[str]:
    """The caller's address, honouring a single proxy hop, if there is one."""
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return None

        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return request.remote_addr
    except Exception:
        return None


def record(
    action: str,
    summary: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    target_label: Optional[str] = None,
    detail: Optional[Dict] = None,
    outcome: str = OUTCOME_OK,
    actor: Optional[Actor] = None,
) -> None:
    """
    Record one action against whoever is responsible for it.

    `summary` should be a finished sentence in the past tense, naming what was
    affected — it is what a person reads on the activity screen, and it has to
    still make sense after the thing it refers to is gone.

    `actor` is an escape hatch for the rare case where the responsible party is
    known but is not the one running the code. Leave it unset otherwise.
    """
    if _store is None:
        return

    try:
        _store.record(
            actor=actor or current_actor(),
            action=action,
            summary=summary,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            detail=detail,
            outcome=outcome,
            request_ip=_request_ip(),
        )
    except Exception as error:  # noqa: BLE001 - see module docstring
        print(f"⚠️  Activity recording failed for '{action}': {error}")


def record_failure(
    action: str,
    summary: str,
    **kwargs,
) -> None:
    """Record an action that was attempted and did not succeed."""
    kwargs['outcome'] = OUTCOME_FAILED
    record(action, summary, **kwargs)


def record_refusal(
    action: str,
    summary: str,
    **kwargs,
) -> None:
    """Record an action the application declined to carry out."""
    kwargs['outcome'] = OUTCOME_REFUSED
    record(action, summary, **kwargs)


__all__ = [
    'record',
    'record_failure',
    'record_refusal',
    'set_store',
    'get_store',
    'OUTCOME_OK',
    'OUTCOME_FAILED',
    'OUTCOME_REFUSED',
]
