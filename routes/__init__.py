"""
DragonCP Routes Package
Presentation Layer - Flask blueprints for API endpoints
"""

from .media import media_bp, init_media_routes
from .transfers import transfers_bp, init_transfer_routes
from .backups import backups_bp, init_backup_routes
from .webhooks import webhooks_bp, init_webhook_routes
from .debug import debug_bp, init_debug_routes

__all__ = [
    'media_bp',
    'transfers_bp',
    'backups_bp',
    'webhooks_bp',
    'debug_bp',
    'init_media_routes',
    'init_transfer_routes',
    'init_backup_routes',
    'init_webhook_routes',
    'init_debug_routes'
]