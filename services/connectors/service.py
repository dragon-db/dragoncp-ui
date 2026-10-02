#!/usr/bin/env python3
"""
The facade the rest of the application talks to.

`notify(event)` is the whole public surface for announcing something. It
resolves which connectors want the event and which destination each one uses,
hands the work to a background thread, and returns. It never raises.

Adapters are built fresh on every use rather than cached. That is the same rule
the settings layer follows and for the same reason: an operator changing a
webhook URL or turning a connector off expects the next notification to obey,
not the one after a restart.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.connectors import registry, routing
from services.connectors.base import (
    CAP_NOTIFY,
    CheckResult,
    Connector,
    DeliveryResult,
    NotifyingConnector,
)
from services.connectors.dispatch import Dispatcher
from services.connectors.events import Event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Job:
    event: Event
    connector_id: str


class ConnectorService:
    """Owns the adapters, the routing decision and the delivery worker."""

    def __init__(self, store, *, synchronous: bool = False):
        self.store = store
        self.dispatcher = Dispatcher(self._deliver_job, synchronous=synchronous)

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.dispatcher.start()

    def stop(self) -> None:
        self.dispatcher.stop()

    # ---- adapters ----------------------------------------------------------

    def adapter(self, connector_id: str) -> Optional[Connector]:
        """This connector as a live adapter, with current config and secrets."""
        adapter_class = registry.get_class(connector_id)
        if adapter_class is None:
            return None
        row = self.store.get_connector(connector_id)
        return adapter_class(
            config=(row or {}).get('config') or {},
            secrets=self.store.secret_reader(connector_id),
        )

    def known(self) -> List[str]:
        return list(registry.known_ids())

    def describe(self, connector_id: str) -> Optional[Dict[str, Any]]:
        """Everything the UI needs for one connector, minus every secret."""
        adapter = self.adapter(connector_id)
        if adapter is None:
            return None
        row = self.store.get_connector(connector_id) or {}
        targets = (
            self.store.list_targets(connector_id)
            if isinstance(adapter, NotifyingConnector) else []
        )
        # For something that sends, "configured" means it has somewhere to send.
        # Discord needs no connector-level credential — a webhook carries its
        # own — so asking the adapter alone would answer yes for a connector
        # that cannot deliver anything.
        configured = adapter.is_configured()
        if isinstance(adapter, NotifyingConnector):
            configured = configured and any(t['is_default'] for t in targets)

        described = adapter.describe()
        described.update({
            'enabled': bool(row.get('enabled')),
            'configured': configured,
            'config': self._public_config(adapter, row.get('config') or {}),
            'secrets_set': {
                f.name: self.store.has_secret(connector_id, f.name)
                for f in adapter.config_fields if f.secret
            },
            'last_check_at': row.get('last_check_at'),
            'last_check_ok': row.get('last_check_ok'),
            'last_check_message': row.get('last_check_message'),
            'exists': bool(row),
        })
        if isinstance(adapter, NotifyingConnector):
            described['target_noun'] = adapter.target_noun
            described['targets'] = targets
        return described

    def describe_all(self) -> List[Dict[str, Any]]:
        """Every registered connector, configured or not.

        Driven by the registry rather than by database rows, so a connector
        that has never been saved still appears — otherwise a fresh install
        would show an empty Integrations section.
        """
        out = []
        for connector_id in registry.known_ids():
            described = self.describe(connector_id)
            if described:
                out.append(described)
        return out

    # ---- checking ----------------------------------------------------------

    def check(self, connector_id: str) -> CheckResult:
        adapter = self.adapter(connector_id)
        if adapter is None:
            return CheckResult(False, f"No connector called {connector_id}")
        if not adapter.is_configured():
            result = CheckResult(False, 'Not configured yet')
        else:
            try:
                result = adapter.check()
            except Exception as exc:  # noqa: BLE001 - a check must not raise
                logger.exception("Connector check failed for %s", connector_id)
                result = CheckResult(False, f"Check failed: {type(exc).__name__}")
        if self.store.get_connector(connector_id):
            self.store.record_check(connector_id, result.ok, result.message)
        return result

    # ---- announcing --------------------------------------------------------

    def notify(self, event: Event) -> None:
        """Announce something. Returns immediately; never raises."""
        try:
            for connector_id in self._notifying_connector_ids():
                self.dispatcher.submit(_Job(event=event, connector_id=connector_id))
        except Exception:
            logger.exception("Failed to queue notification %s", getattr(event, 'key', '?'))

    def send_test(self, connector_id: str, target_id: str,
                  event: Event) -> DeliveryResult:
        """Deliver one event to one destination now, ignoring routing.

        Used by the Test buttons, where somebody is watching and waiting for
        the answer, and where the point is to prove *this* destination works
        rather than to find out where routing would have sent it.
        """
        adapter = self.adapter(connector_id)
        if adapter is None or not isinstance(adapter, NotifyingConnector):
            return DeliveryResult(False, error=f"{connector_id} cannot send notifications")

        row = self.store.get_target(target_id)
        if not row or row['connector_id'] != connector_id:
            return DeliveryResult(False, error='That destination no longer exists')

        result = self._deliver(adapter, event, row, connector_id)
        return result

    # ---- internals ---------------------------------------------------------

    def _notifying_connector_ids(self) -> List[str]:
        ids = []
        for connector_id in registry.known_ids():
            adapter_class = registry.get_class(connector_id)
            if adapter_class and CAP_NOTIFY in getattr(adapter_class, 'capabilities', frozenset()):
                ids.append(connector_id)
        return ids

    def _deliver_job(self, job: _Job) -> None:
        """One queued announcement. Runs on the dispatch thread."""
        connector_id = job.connector_id
        event = job.event

        adapter = self.adapter(connector_id)
        if adapter is None or not isinstance(adapter, NotifyingConnector):
            return

        resolution = routing.resolve(
            self.store, connector_id, event.key,
            configured=adapter.is_configured(),
        )

        if not resolution.deliver:
            # A connector that was never set up is the ordinary state of a
            # fresh install; recording every skipped notification for it would
            # fill the log with noise nobody asked about. Everything else is
            # a decision the operator made, and is worth being able to see.
            if resolution.reason != routing.SKIP_CONNECTOR_OFF:
                self.store.record_delivery(
                    connector_id, ok=False, event_key=event.key,
                    title=event.title, skipped_reason=resolution.reason,
                    target_id=(resolution.target.target_id if resolution.target else None),
                    target_label=(resolution.target.label if resolution.target else None),
                )
            return

        self._deliver(adapter, event, resolution.target_row, connector_id)

    def _deliver(self, adapter: NotifyingConnector, event: Event,
                 target_row: Dict[str, Any], connector_id: str) -> DeliveryResult:
        target = routing.as_target(target_row)
        credential = self.store.secret(connector_id, target_row['secret_ref'])
        if not credential:
            result = DeliveryResult(False, error='That destination has no address stored')
        else:
            try:
                result = adapter.deliver(event, target, credential)
            except Exception as exc:  # noqa: BLE001 - delivery must not raise
                logger.exception("Delivery failed for %s", connector_id)
                result = DeliveryResult(False, error=f"Delivery failed: {type(exc).__name__}")

        self.store.record_send(target.target_id, result.ok, result.error)
        self.store.record_delivery(
            connector_id, ok=result.ok, target_id=target.target_id,
            target_label=target.label, event_key=event.key, title=event.title,
            status_code=result.status_code, error=result.error,
            duration_ms=result.duration_ms,
        )
        return result

    @staticmethod
    def _public_config(adapter: Connector, config: Dict[str, Any]) -> Dict[str, Any]:
        """Config with every secret-backed field removed.

        Secrets are not stored in the config blob, but a field declared secret
        is dropped here as well so a stray write can never surface one.
        """
        secret_names = {f.name for f in adapter.config_fields if f.secret}
        return {k: v for k, v in config.items() if k not in secret_names}


# ---------------------------------------------------------------------------
# The module-level singleton
#
# Wired once at startup. Everything that announces something imports `notify`
# and never sees the service, the store or the database.
# ---------------------------------------------------------------------------

_service: Optional[ConnectorService] = None


def configure(store, *, synchronous: bool = False) -> ConnectorService:
    """Install the connector service. Called once, from app startup."""
    global _service
    if _service is not None:
        _service.stop()
    _service = ConnectorService(store, synchronous=synchronous)
    _service.start()
    return _service


def get_service() -> Optional[ConnectorService]:
    return _service


def notify(event: Event) -> None:
    """Announce something.

    A no-op when the connector layer has not been configured — which is the
    case in unit tests that exercise a service in isolation, and must not be
    the case anywhere an operator can see.
    """
    service = _service
    if service is None:
        logger.debug("notify(%s) before the connector layer was configured", event.key)
        return
    service.notify(event)


def shutdown() -> None:
    global _service
    if _service is not None:
        _service.stop()
        _service = None
