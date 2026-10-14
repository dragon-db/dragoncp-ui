#!/usr/bin/env python3
"""
Which destination an announcement goes to.

One rule decides everything: **a missing route means the default, not
silence.** A new event type added next year is delivered the day it is written,
without anyone remembering to configure it. The states where a message is
deliberately not sent are all explicit, and every one of them is recorded with
a reason — an announcement that vanishes without trace is the failure this
layer exists to remove.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from services.connectors.base import Target

# Why a message was not delivered. These strings reach the delivery log and the
# UI, so they are written for an operator reading them in a hurry.
SKIP_CONNECTOR_OFF = 'The connector is turned off'
SKIP_NOT_CONFIGURED = 'The connector has no credentials yet'
SKIP_EVENT_OFF = 'This notification is switched off'
SKIP_TARGET_DISABLED = 'The chosen destination is out of service'
SKIP_NO_DEFAULT = 'No default destination is set'


@dataclass(frozen=True)
class Resolution:
    """Where one event goes, or why it does not go anywhere."""

    connector_id: str
    deliver: bool
    target: Optional[Target] = None
    #: The row behind the target, when there is one — the caller needs
    #: `secret_ref` to fetch the credential.
    target_row: Optional[Dict[str, Any]] = None
    reason: str = ''


def resolve(store, connector_id: str, event_key: str, *,
            configured: bool = True) -> Resolution:
    """Decide where `event_key` goes for `connector_id`.

    Args:
        store: a `ConnectorStore`.
        configured: whether the adapter reports itself configured. Passed in
            rather than looked up so this stays pure row logic and can be
            tested without an adapter.
    """
    connector = store.get_connector(connector_id)
    if not connector or not connector.get('enabled'):
        return Resolution(connector_id, False, reason=SKIP_CONNECTOR_OFF)

    if not configured:
        return Resolution(connector_id, False, reason=SKIP_NOT_CONFIGURED)

    route = store.get_route(event_key, connector_id)
    if route and not route.get('enabled'):
        return Resolution(connector_id, False, reason=SKIP_EVENT_OFF)

    row = None
    if route and route.get('target_id'):
        row = store.get_target(route['target_id'])
        # A route pointing at a destination that no longer exists falls back to
        # the default rather than going quiet. `delete_target` already clears
        # these to NULL; this covers a row deleted by any other means.

    if row is None:
        row = store.default_target(connector_id)
        if row is None:
            return Resolution(connector_id, False, reason=SKIP_NO_DEFAULT)

    if not row.get('enabled'):
        # Deliberately not redirected to the default. "Out of service" is a
        # statement about this destination, and quietly sending somewhere else
        # would put messages in a channel the operator did not choose.
        return Resolution(connector_id, False, reason=SKIP_TARGET_DISABLED,
                          target_row=row, target=as_target(row))

    return Resolution(connector_id, True, target=as_target(row), target_row=row)


def as_target(row: Dict[str, Any]) -> Target:
    return Target(
        target_id=row['target_id'],
        connector_id=row['connector_id'],
        label=row['label'],
        is_default=bool(row.get('is_default')),
        enabled=bool(row.get('enabled')),
    )
