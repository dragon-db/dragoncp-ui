#!/usr/bin/env python3
"""
Which connectors exist.

An adapter registers itself with `@register`. Nothing keeps a second list that
could disagree with this one, and nothing outside `adapters/` needs editing to
add a service — importing the module is what makes it real.

    @register
    class DiscordConnector(NotifyingConnector):
        id = 'discord'

The registry holds classes, not instances. An instance needs this operator's
configuration and secrets, which is `ConnectorService`'s job.
"""

from typing import Dict, Optional, Tuple, Type

from services.connectors.base import Connector

_REGISTRY: Dict[str, Type[Connector]] = {}


def register(cls: Type[Connector]) -> Type[Connector]:
    """Class decorator that adds an adapter to the registry."""
    connector_id = getattr(cls, 'id', '')
    if not connector_id:
        raise ValueError(f"{cls.__name__} must set a non-empty id")
    existing = _REGISTRY.get(connector_id)
    if existing is not None and existing is not cls:
        # Two adapters claiming one id would make "which one is configured"
        # depend on import order, and the loser would be silently unreachable.
        raise ValueError(
            f"Connector id {connector_id!r} is already registered by "
            f"{existing.__name__}"
        )
    _REGISTRY[connector_id] = cls
    return cls


def get_class(connector_id: str) -> Optional[Type[Connector]]:
    return _REGISTRY.get(connector_id)


def known_ids() -> Tuple[str, ...]:
    """Every registered id, in registration order."""
    return tuple(_REGISTRY.keys())


def classes() -> Tuple[Type[Connector], ...]:
    return tuple(_REGISTRY.values())


def _reset() -> None:
    """Empty the registry. Tests only."""
    _REGISTRY.clear()
