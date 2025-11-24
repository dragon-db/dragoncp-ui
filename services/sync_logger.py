#!/usr/bin/env python3
"""
DragonCP Sync Logger
Provides enhanced logging with service/notification/transfer tracking for series/anime sync
"""


def log_sync(service: str, message: str, icon: str = "📋", 
             notification_id: str = None, transfer_id: str = None, 
             indent: int = 0):
    """
    Enhanced logging for series/anime sync with ID tracking
    
    Args:
        service: Service name (e.g., "AutoSyncScheduler", "WebhookService")
        message: Log message
        icon: Emoji icon for visual identification
        notification_id: Optional notification ID (shows full ID)
        transfer_id: Optional transfer ID (shows full ID)
        indent: Number of spaces to indent (for hierarchical logs)
    
    Example:
        log_sync("AutoSyncScheduler", "Scheduled auto-sync", icon="📅", 
                 notification_id="tvshows_267_s1_ef76577")
        Output: 📅 [AutoSyncScheduler] [notification_id:tvshows_267_s1_ef76577] > Scheduled auto-sync
    """
    # Build ID string with FULL IDs for database queries
    ids = []
    if notification_id:
        ids.append(f"notification_id:{notification_id}")
    if transfer_id:
        ids.append(f"transfer_id:{transfer_id}")
    
    id_str = f"[{']['.join(ids)}]" if ids else ""
    
    # Build final log message
    indent_str = "   " * indent
    service_str = f"[{service}]"
    separator = " >" if id_str else ">"
    
    print(f"{icon} {service_str} {id_str}{separator} {indent_str}{message}")


def log_batch(service: str, message: str, batch_size: int, icon: str = "📦",
              notification_ids: list = None, transfer_id: str = None):
    """
    Log batch operations with count
    
    Args:
        service: Service name
        message: Log message
        batch_size: Number of items in batch
        icon: Emoji icon
        notification_ids: Optional list of notification IDs
        transfer_id: Optional transfer ID
    """
    log_sync(service, f"{message} ({batch_size} items)", icon=icon, transfer_id=transfer_id)
    
    if notification_ids and len(notification_ids) <= 5:
        # Show full IDs for database queries
        for notif_id in notification_ids:
            print(f"   - notification_id: {notif_id}")


def log_validation(service: str, result: bool, message: str, icon: str = None,
                   notification_id: str = None, transfer_id: str = None):
    """
    Log validation results with appropriate icon
    
    Args:
        service: Service name
        result: Validation result (True/False)
        message: Log message
        icon: Optional custom icon (auto-selected if None)
        notification_id: Optional notification ID
        transfer_id: Optional transfer ID
    """
    if icon is None:
        icon = "✅" if result else "❌"
    
    log_sync(service, message, icon=icon, 
             notification_id=notification_id, transfer_id=transfer_id)


def log_state_change(service: str, old_state: str, new_state: str, 
                     notification_id: str = None, transfer_id: str = None):
    """
    Log state transitions
    
    Args:
        service: Service name
        old_state: Previous state
        new_state: New state
        notification_id: Optional notification ID
        transfer_id: Optional transfer ID
    """
    log_sync(service, f"State change: {old_state} → {new_state}", icon="🔄",
             notification_id=notification_id, transfer_id=transfer_id)

