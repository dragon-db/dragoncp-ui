"""
DragonCP Routes Package
Presentation Layer - Flask blueprints for API endpoints
"""

from .auth import auth_bp
from .media import media_bp, init_media_routes
from .transfers import transfers_bp, init_transfer_routes
from .backups import backups_bp, init_backup_routes
from .webhooks import webhooks_bp, init_webhook_routes
from .debug import debug_bp, init_debug_routes
from .logs import logs_bp
from .simulation import simulation_bp, init_simulation_routes
from .explore import explore_bp, init_explore_routes
from .activity import activity_bp, init_activity_routes

__all__ = [
    'auth_bp',
    'media_bp',
    'transfers_bp',
    'backups_bp',
    'webhooks_bp',
    'debug_bp',
    'logs_bp',
    'simulation_bp',
    'explore_bp',
    'activity_bp',
    'init_media_routes',
    'init_transfer_routes',
    'init_backup_routes',
    'init_webhook_routes',
    'init_debug_routes',
    'init_simulation_routes',
    'init_explore_routes',
    'init_activity_routes'
]
