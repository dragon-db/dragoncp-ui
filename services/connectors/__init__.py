#!/usr/bin/env python3
"""
The connector layer — one way to talk to an outside service.

Anything in this application that wants to announce something writes this and
nothing else:

    from services.connectors import notify
    from services.connectors.events import Event, Field

    notify(Event(
        key='transfer.failed',
        severity='failure',
        title=parsed_title,
        fields=(Field('Error Details', error_text, monospace=True),),
    ))

No enabled check, no URL, no embed, no colour, no try/except. `notify()`
resolves which connector and which destination the event is routed to, hands
the work to a background thread and returns. It never raises and it never
blocks — which matters because one of its callers runs inside the HTTP request
Sonarr makes, and used to hold that request open for the length of a Discord
post.
"""

from services.connectors.base import (
    CAP_COMMAND,
    CAP_NOTIFY,
    CAP_QUERY,
    CheckResult,
    ConfigField,
    Connector,
    DeliveryResult,
    NotifyingConnector,
    Target,
)
from services.connectors.events import Event, Field
from services.connectors.service import (
    ConnectorService,
    configure,
    get_service,
    notify,
    shutdown,
)

# Last, and after everything it depends on: importing the adapters is what
# registers them. Nothing else needs editing to add a connector.
from services.connectors import adapters as _adapters  # noqa: E402,F401

__all__ = [
    'CAP_COMMAND',
    'CAP_NOTIFY',
    'CAP_QUERY',
    'CheckResult',
    'ConfigField',
    'Connector',
    'ConnectorService',
    'DeliveryResult',
    'Event',
    'Field',
    'NotifyingConnector',
    'Target',
    'configure',
    'get_service',
    'notify',
    'shutdown',
]
