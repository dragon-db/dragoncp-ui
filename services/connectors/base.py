#!/usr/bin/env python3
"""
What a connector is.

A connector is a named, configurable, testable link to one outside service.
Every one of them answers the same four questions and nothing more:

    Am I configured?    enough credentials to be worth trying
    Do I work?          reach the service now and say what happened
    What can I do?      notify, query, command
    Deliver this        and report the outcome as a value

Everything else — timeouts, retries, redaction, failure reporting, the
delivery log — lives below this line and is decided once. An adapter says how
to render a payload for its service and which HTTP calls to make. That is all
it says.

Nothing here raises on a service being down, misconfigured or slow. A connector
failing is an ordinary outcome that gets recorded, never something that can
take down a transfer.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Optional

from services.connectors.events import Event

#: How an adapter asks for one of its own secrets, by name. Adapters never
#: touch the database and never see the whole secret table — which is what
#: makes "no read path reaches a response body" a property of the code rather
#: than a rule somebody has to remember.
SecretReader = Callable[[str], str]


# --- capabilities -----------------------------------------------------------
#
# What a connector is *for*. The Integrations UI groups by these, and phase 2's
# auto-sync gating asks for CAP_QUERY specifically rather than naming Sonarr.

CAP_NOTIFY = 'notify'      # can be sent announcements
CAP_QUERY = 'query'        # can be asked questions
CAP_COMMAND = 'command'    # can be told to do something

CAPABILITIES = (CAP_NOTIFY, CAP_QUERY, CAP_COMMAND)


@dataclass(frozen=True)
class CheckResult:
    """The answer to "does this work right now"."""

    ok: bool
    #: Operator-facing and plain English. This is rendered verbatim in the UI,
    #: so it says "API key was rejected", not "401".
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {'ok': self.ok, 'message': self.message, 'detail': dict(self.detail)}


@dataclass(frozen=True)
class DeliveryResult:
    """What happened when one announcement was handed to one destination."""

    ok: bool
    status_code: Optional[int] = None
    #: Never contains a secret. The transport redacts before this is built —
    #: a Discord webhook URL *is* the credential, and the code this replaces
    #: printed it next to the response body.
    error: Optional[str] = None
    duration_ms: int = 0
    #: Set when the service asked us to wait, so the UI can say how long.
    retry_after: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            'ok': self.ok,
            'status_code': self.status_code,
            'error': self.error,
            'duration_ms': self.duration_ms,
            'retry_after': self.retry_after,
        }


@dataclass(frozen=True)
class Target:
    """One destination belonging to a connector — a named Discord webhook.

    The label is an identifier an operator chose and can reason about, which
    is why it is unique per connector and why routing stores it in messages.
    """

    target_id: str
    connector_id: str
    label: str
    is_default: bool = False
    enabled: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            'target_id': self.target_id,
            'connector_id': self.connector_id,
            'label': self.label,
            'is_default': self.is_default,
            'enabled': self.enabled,
        }


class ConfigField:
    """One input on a connector's settings form.

    Declared by the adapter so the UI can render a connector it has never heard
    of. Adding a connector must not mean writing a bespoke form — that is the
    difference between a connector framework and four hand-built pages.
    """

    def __init__(self, name: str, label: str, description: str = '',
                 kind: str = 'text', secret: bool = False,
                 required: bool = False, placeholder: str = ''):
        self.name = name
        self.label = label
        self.description = description
        self.kind = kind            # text | password | url | boolean | number
        self.secret = secret        # stored in connector_secret, never returned
        self.required = required
        self.placeholder = placeholder

    def as_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'label': self.label,
            'description': self.description,
            'kind': self.kind,
            'secret': self.secret,
            'required': self.required,
            'placeholder': self.placeholder,
        }


class Connector:
    """The base every adapter subclasses."""

    #: Stable identifier. Appears in the database, the API and the URL, so it
    #: is chosen once and never changed.
    id: str = ''
    display_name: str = ''
    #: One line under the title on the connector's page.
    description: str = ''
    capabilities: FrozenSet[str] = frozenset()
    #: What the settings form shows.
    config_fields: tuple = ()

    #: What that form is *called*, and what it says it does. Most connectors
    #: are reached with an address and a key, so the default is right for them.
    #: Discord is not: a webhook URL carries its own credential, so its form
    #: holds only presentation and calling it "Connection" would describe
    #: something that does not exist.
    settings_label: str = 'Connection'
    settings_description: str = ''

    #: Whether `check()` reaches anything. False means the connector has no
    #: endpoint to test at this level, and the UI must not offer a button that
    #: cannot fail — a test that always passes is worse than no test.
    supports_check: bool = True

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 secrets: Optional[SecretReader] = None):
        self.config = dict(config or {})
        self._secrets = secrets or (lambda name: '')

    # -- helpers for adapters ------------------------------------------------

    def secret(self, name: str) -> str:
        """This connector's secret, by name. Returns '' when unset."""
        try:
            return self._secrets(name) or ''
        except Exception:
            return ''

    def setting(self, name: str, default: str = '') -> str:
        value = self.config.get(name)
        return default if value in (None, '') else str(value)

    # -- the surface ---------------------------------------------------------

    def is_configured(self) -> bool:
        """Enough credentials to be worth trying."""
        return all(
            (self.secret(f.name) if f.secret else self.setting(f.name))
            for f in self.config_fields if f.required
        )

    def check(self) -> CheckResult:
        """Reach the service now and say what happened."""
        raise NotImplementedError

    def describe(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'display_name': self.display_name,
            'description': self.description,
            'capabilities': sorted(self.capabilities),
            'config_fields': [f.as_dict() for f in self.config_fields],
            'settings_label': self.settings_label,
            'settings_description': (
                self.settings_description
                or f"How DragonCP reaches {self.display_name}."
            ),
            'supports_check': self.supports_check,
        }


class NotifyingConnector(Connector):
    """A connector that can be sent announcements."""

    capabilities = frozenset({CAP_NOTIFY})

    #: What one destination is called on this service, for the UI. Discord has
    #: webhooks; something else might have channels or topics.
    target_noun = 'webhook'
    #: The secret name a target's credential is stored under.
    target_secret_kind = 'url'

    def render(self, event: Event) -> Dict[str, Any]:
        """Turn a neutral event into this service's payload shape."""
        raise NotImplementedError

    def deliver(self, event: Event, target: Target,
                credential: str) -> DeliveryResult:
        """Send one rendered event to one destination."""
        raise NotImplementedError

    def validate_target(self, credential: str) -> Optional[str]:
        """Reject a bad destination credential before it is stored.

        Returns an operator-facing reason, or None when it is acceptable.
        """
        return None
