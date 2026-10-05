"""
DragonCP Services Package
Business Logic Layer for operations orchestration

`TransferCoordinator` is resolved on first use rather than imported here.
Importing it eagerly meant that importing *any* module under `services` pulled
in the whole transfer graph — and with the sync engine's storage depending on
its stage catalogue, that turned into an import cycle.
"""

__all__ = [
    'TransferCoordinator'
]


def __getattr__(name):
    if name == 'TransferCoordinator':
        from .transfer_coordinator import TransferCoordinator
        return TransferCoordinator
    raise AttributeError(f"module 'services' has no attribute {name!r}")
