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
from typing import Any, Dict, List, Optional

from services.connectors import events as event_catalogue
from services.connectors.base import Mention, Target

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


def ping_rule(route: Optional[Dict[str, Any]], event_key: str) -> str:
    """When `event_key` pings: the route's choice, else the catalogue's default."""
    when = (route or {}).get('ping_when')
    if when in event_catalogue.PING_CHOICES:
        return when
    entry = event_catalogue.get(event_key)
    return entry.default_ping if entry else event_catalogue.PING_NEVER


def mentions_for(store, connector_id: str, event_key: str, severity: str,
                 target_row: Dict[str, Any]) -> List[Mention]:
    """Who one message pings, given where it is going.

    The route decides when (never, on a warning or a failure, or always) and,
    if it named anyone, whom. A route that named nobody uses the webhook's own
    pings, so "ping Admins for everything in the alerts channel" is set once.
    """
    route = store.get_route(event_key, connector_id)
    if not event_catalogue.should_ping(ping_rule(route, event_key), severity):
        return []
    ids = (route or {}).get('mention_ids')
    if ids is None:
        ids = target_row.get('mention_ids') or []
    return [as_mention(row) for row in store.mentions_by_ids(connector_id, ids)]


def as_mention(row: Dict[str, Any]) -> Mention:
    return Mention(mention_id=row['mention_id'], label=row['label'],
                   kind=row['kind'], value=row.get('value') or '')
