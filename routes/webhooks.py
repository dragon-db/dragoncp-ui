#!/usr/bin/env python3
"""
DragonCP Webhook Routes
Handles webhook receivers for Radarr/Sonarr and webhook management
"""

from datetime import datetime
from flask import Blueprint, jsonify, request
import requests

webhooks_bp = Blueprint('webhooks', __name__)

# Global references to be set by app.py
config = None
transfer_coordinator = None


def init_webhook_routes(app_config, app_transfer_coordinator):
    """Initialize route dependencies"""
    global config, transfer_coordinator
    config = app_config
    transfer_coordinator = app_transfer_coordinator


# ===== WEBHOOK RECEIVER ENDPOINTS =====

@webhooks_bp.route('/webhook/movies', methods=['POST'])
def api_webhook_movies_receiver():
    """Webhook receiver endpoint for movie notifications from Radarr"""
    try:
        print("🎬 Webhook received")
        
        # Validate content type
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400
        
        webhook_data = request.json
        if not webhook_data:
            return jsonify({"status": "error", "message": "Empty JSON payload"}), 400
        
        print(f"🎬 Webhook data received: {webhook_data.get('movie', {}).get('title', 'Unknown')}")
        
        # Check if this is a TEST notification first
        movie = webhook_data.get('movie', {})
        event_type = webhook_data.get('eventType', '')
        title = movie.get('title', '')
        folder_path = movie.get('folderPath', '')
        
        is_test = (
            event_type == 'Test' or
            title == 'Test Title' or
            'testpath' in folder_path
        )
        
        if is_test:
            print(f"🧪 TEST webhook received - webhook connectivity verified")
            # Emit toast notification via WebSocket
            if transfer_coordinator.socketio:
                transfer_coordinator.socketio.emit('test_webhook_received', {
                    'message': 'TEST webhook received - webhook connectivity verified',
                    'timestamp': datetime.now().isoformat()
                })
            return jsonify({
                "status": "success",
                "message": "TEST webhook received - webhook connectivity verified",
                "is_test": True
            })
        
        # Parse webhook data according to specification
        parsed_data = transfer_coordinator.parse_webhook_data(webhook_data)
        
        # Store notification in database
        notification_id = transfer_coordinator.webhook_model.create(parsed_data)
        
        # Check if auto-sync is enabled (prefer DB app_settings, fallback to env)
        try:
            auto_sync_enabled = transfer_coordinator.settings.get_bool('AUTO_SYNC_MOVIES', default=(config.get("AUTO_SYNC_MOVIES", "false").lower() == "true"))
        except Exception:
            auto_sync_enabled = config.get("AUTO_SYNC_MOVIES", "false").lower() == "true"
        
        if auto_sync_enabled:
            print(f"🎬 Auto-sync enabled, triggering sync for {parsed_data['title']}")
            # Trigger automatic sync
            success, message = transfer_coordinator.trigger_webhook_sync(notification_id)
            if success:
                return jsonify({
                    "status": "success",
                    "message": f"Webhook received and auto-sync started for {parsed_data['title']}",
                    "notification_id": notification_id,
                    "auto_sync": True
                })
            else:
                return jsonify({
                    "status": "warning",
                    "message": f"Webhook received but auto-sync failed: {message}",
                    "notification_id": notification_id,
                    "auto_sync": False
                })
        else:
            print(f"🎬 Auto-sync disabled, storing notification for manual sync")
            return jsonify({
                "status": "success",
                "message": f"Webhook received for {parsed_data['title']}. Manual sync required.",
                "notification_id": notification_id,
                "auto_sync": False
            })
        
    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Failed to process webhook: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/series', methods=['POST'])
def api_webhook_series_receiver():
    """Webhook receiver endpoint for series notifications from Sonarr"""
    try:
        print("📺 Series webhook received")
        
        # Validate content type
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400
        
        webhook_data = request.json
        if not webhook_data:
            return jsonify({"status": "error", "message": "Empty JSON payload"}), 400
        
        print(f"📺 Series webhook data received: {webhook_data.get('series', {}).get('title', 'Unknown')}")
        
        # Check if this is a TEST notification first
        series = webhook_data.get('series', {})
        event_type = webhook_data.get('eventType', '')
        title = series.get('title', '')
        series_path = series.get('path', '')
        
        is_test = (
            event_type == 'Test' or
            title == 'Test Title' or
            'testpath' in series_path
        )
        
        if is_test:
            print(f"🧪 TEST series webhook received - webhook connectivity verified")
            if transfer_coordinator.socketio:
                transfer_coordinator.socketio.emit('test_webhook_received', {
                    'message': 'TEST series webhook received - webhook connectivity verified',
                    'timestamp': datetime.now().isoformat()
                })
            return jsonify({
                "status": "success",
                "message": "TEST series webhook received - webhook connectivity verified",
                "is_test": True
            })
        
        # Parse series webhook data
        parsed_data = transfer_coordinator.parse_series_webhook_data(webhook_data, 'tvshows')
        
        # Store notification in database
        notification_id = transfer_coordinator.series_webhook_model.create(parsed_data)
        
        # For series, auto-sync is disabled by default as per requirements
        print(f"📺 Series auto-sync disabled by default, storing notification for manual sync")
        return jsonify({
            "status": "success",
            "message": f"Series webhook received for {parsed_data['series_title']} Season {parsed_data.get('season_number', 'Unknown')}. Manual sync required.",
            "notification_id": notification_id,
            "auto_sync": False
        })
        
    except Exception as e:
        print(f"❌ Error processing series webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Failed to process series webhook: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/anime', methods=['POST'])
def api_webhook_anime_receiver():
    """Webhook receiver endpoint for anime notifications from Sonarr"""
    try:
        print("🍙 Anime webhook received")
        
        # Validate content type
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400
        
        webhook_data = request.json
        if not webhook_data:
            return jsonify({"status": "error", "message": "Empty JSON payload"}), 400
        
        print(f"🍙 Anime webhook data received: {webhook_data.get('series', {}).get('title', 'Unknown')}")
        
        # Check if this is a TEST notification first
        series = webhook_data.get('series', {})
        event_type = webhook_data.get('eventType', '')
        title = series.get('title', '')
        series_path = series.get('path', '')
        
        is_test = (
            event_type == 'Test' or
            title == 'Test Title' or
            'testpath' in series_path
        )
        
        if is_test:
            print(f"🧪 TEST anime webhook received - webhook connectivity verified")
            if transfer_coordinator.socketio:
                transfer_coordinator.socketio.emit('test_webhook_received', {
                    'message': 'TEST anime webhook received - webhook connectivity verified',
                    'timestamp': datetime.now().isoformat()
                })
            return jsonify({
                "status": "success",
                "message": "TEST anime webhook received - webhook connectivity verified",
                "is_test": True
            })
        
        # Parse anime webhook data
        parsed_data = transfer_coordinator.parse_series_webhook_data(webhook_data, 'anime')
        
        # Store notification in database
        notification_id = transfer_coordinator.series_webhook_model.create(parsed_data)
        
        # For anime, auto-sync is disabled by default as per requirements
        print(f"🍙 Anime auto-sync disabled by default, storing notification for manual sync")
        return jsonify({
            "status": "success",
            "message": f"Anime webhook received for {parsed_data['series_title']} Season {parsed_data.get('season_number', 'Unknown')}. Manual sync required.",
            "notification_id": notification_id,
            "auto_sync": False
        })
        
    except Exception as e:
        print(f"❌ Error processing anime webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Failed to process anime webhook: {str(e)}"
        }), 500


# ===== WEBHOOK NOTIFICATION MANAGEMENT =====

@webhooks_bp.route('/webhook/notifications')
def api_webhook_notifications():
    """Get all webhook notifications (movies, series, and anime)"""
    try:
        status_filter = request.args.get('status')
        limit = request.args.get('limit', 50, type=int)
        
        # Get movie notifications
        movie_notifications = transfer_coordinator.webhook_model.get_all(status_filter=status_filter, limit=limit)
        
        # Get series/anime notifications
        series_notifications = transfer_coordinator.series_webhook_model.get_all(status_filter=status_filter, limit=limit)
        
        # Format notifications for consistent display
        all_notifications = []
        
        # Add movie notifications with type indicator
        for notification in movie_notifications:
            notification['media_type'] = 'movie'
            notification['display_title'] = notification['title']
            all_notifications.append(notification)
        
        # Add series/anime notifications with type indicator
        for notification in series_notifications:
            season_text = f" Season {notification['season_number']}" if notification.get('season_number') else ""
            notification['display_title'] = f"{notification['series_title']}{season_text}"
            all_notifications.append(notification)
        
        # Sort by creation date (most recent first)
        all_notifications.sort(key=lambda x: x['created_at'], reverse=True)
        
        # Apply limit to combined results
        if limit:
            all_notifications = all_notifications[:limit]
        
        return jsonify({
            "status": "success",
            "notifications": all_notifications,
            "total": len(all_notifications)
        })
        
    except Exception as e:
        print(f"❌ Error getting webhook notifications: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get notifications: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/series/notifications')
def api_series_webhook_notifications():
    """Get series webhook notifications only"""
    try:
        status_filter = request.args.get('status')
        limit = request.args.get('limit', 50, type=int)
        
        notifications = transfer_coordinator.series_webhook_model.get_all(
            media_type_filter='tvshows', 
            status_filter=status_filter, 
            limit=limit
        )
        
        return jsonify({
            "status": "success",
            "notifications": notifications,
            "total": len(notifications)
        })
        
    except Exception as e:
        print(f"❌ Error getting series webhook notifications: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get series notifications: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/anime/notifications')
def api_anime_webhook_notifications():
    """Get anime webhook notifications only"""
    try:
        status_filter = request.args.get('status')
        limit = request.args.get('limit', 50, type=int)
        
        notifications = transfer_coordinator.series_webhook_model.get_all(
            media_type_filter='anime', 
            status_filter=status_filter, 
            limit=limit
        )
        
        return jsonify({
            "status": "success",
            "notifications": notifications,
            "total": len(notifications)
        })
        
    except Exception as e:
        print(f"❌ Error getting anime webhook notifications: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get anime notifications: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/notifications/<notification_id>')
def api_webhook_notification_details(notification_id):
    """Get specific webhook notification details (handles both movies and series/anime)"""
    try:
        # First try movie notifications
        notification = transfer_coordinator.webhook_model.get(notification_id)
        if notification:
            notification['media_type'] = 'movie'  # Add media type for consistency
            return jsonify({
                "status": "success",
                "notification": notification
            })
        
        # If not found, try series/anime notifications
        notification = transfer_coordinator.series_webhook_model.get(notification_id)
        if notification:
            return jsonify({
                "status": "success",
                "notification": notification
            })
        
        return jsonify({"status": "error", "message": "Notification not found"}), 404
        
    except Exception as e:
        print(f"❌ Error getting notification details: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get notification details: {str(e)}"
        }), 500


# ===== WEBHOOK SYNC OPERATIONS =====

@webhooks_bp.route('/webhook/notifications/<notification_id>/sync', methods=['POST'])
def api_webhook_sync(notification_id):
    """Manually trigger sync for a webhook notification (movies)"""
    try:
        success, message = transfer_coordinator.trigger_webhook_sync(notification_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": message
            })
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400
            
    except Exception as e:
        print(f"❌ Error triggering webhook sync: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to trigger sync: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/series/notifications/<notification_id>/sync', methods=['POST'])
def api_series_webhook_sync(notification_id):
    """Manually trigger sync for a series webhook notification"""
    try:
        success, message = transfer_coordinator.trigger_series_webhook_sync(notification_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": message
            })
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400
            
    except Exception as e:
        print(f"❌ Error triggering series webhook sync: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to trigger series sync: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/anime/notifications/<notification_id>/sync', methods=['POST'])
def api_anime_webhook_sync(notification_id):
    """Manually trigger sync for an anime webhook notification"""
    try:
        success, message = transfer_coordinator.trigger_series_webhook_sync(notification_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": message
            })
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400
            
    except Exception as e:
        print(f"❌ Error triggering anime webhook sync: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to trigger anime sync: {str(e)}"
        }), 500


# ===== WEBHOOK DELETION =====

@webhooks_bp.route('/webhook/series/notifications/<notification_id>/delete', methods=['POST'])
def api_series_webhook_delete_notification(notification_id):
    """Delete a series webhook notification"""
    try:
        success = transfer_coordinator.series_webhook_model.delete(notification_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": "Series notification deleted successfully"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to delete series notification"
            }), 400
            
    except Exception as e:
        print(f"❌ Error deleting series notification: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to delete series notification: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/anime/notifications/<notification_id>/delete', methods=['POST'])
def api_anime_webhook_delete_notification(notification_id):
    """Delete an anime webhook notification"""
    try:
        success = transfer_coordinator.series_webhook_model.delete(notification_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": "Anime notification deleted successfully"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to delete anime notification"
            }), 400
            
    except Exception as e:
        print(f"❌ Error deleting anime notification: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to delete anime notification: {str(e)}"
        }), 500


@webhooks_bp.route('/webhook/notifications/<notification_id>/delete', methods=['POST'])
def api_webhook_delete_notification(notification_id):
    """Delete a webhook notification"""
    try:
        success = transfer_coordinator.webhook_model.delete(notification_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": "Notification deleted successfully"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to delete notification"
            }), 400
            
    except Exception as e:
        print(f"❌ Error deleting notification: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to delete notification: {str(e)}"
        }), 500


# ===== WEBHOOK SETTINGS =====

@webhooks_bp.route('/webhook/settings', methods=['GET', 'POST'])
def api_webhook_settings():
    """Get or update webhook settings"""
    if request.method == 'GET':
        try:
            # Prefer DB app_settings value when present, fallback to env
            db_val = None
            try:
                db_val = transfer_coordinator.settings.get('AUTO_SYNC_MOVIES')
            except Exception:
                db_val = None
            env_val = config.get("AUTO_SYNC_MOVIES", "false").lower() == "true"
            settings = {
                "auto_sync_movies": (str(db_val).lower() in ('true','1','yes','on')) if db_val is not None else env_val
            }
            return jsonify({
                "status": "success",
                "settings": settings
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"Failed to get settings: {str(e)}"
            }), 500
    
    else:  # POST
        try:
            data = request.json
            if not data:
                return jsonify({"status": "error", "message": "No data provided"}), 400
            
            # Update auto-sync setting (store only in DB; no .env write)
            if "auto_sync_movies" in data:
                new_val = bool(data["auto_sync_movies"])
                # Save to DB app_settings
                transfer_coordinator.settings.set_bool('AUTO_SYNC_MOVIES', new_val)
                print(f"🎬 Auto-sync movies setting updated (DB): {new_val}")
            
            return jsonify({
                "status": "success",
                "message": "Settings updated successfully"
            })
            
        except Exception as e:
            print(f"❌ Error updating webhook settings: {e}")
            return jsonify({
                "status": "error",
                "message": f"Failed to update settings: {str(e)}"
            }), 500


# ===== DISCORD SETTINGS =====

@webhooks_bp.route('/discord/settings', methods=['GET', 'POST'])
def api_discord_settings():
    """Get or update Discord notification settings"""
    if request.method == 'GET':
        try:
            settings = {
                "webhook_url": transfer_coordinator.settings.get('DISCORD_WEBHOOK_URL', ''),
                "app_url": transfer_coordinator.settings.get('DISCORD_APP_URL', 'http://localhost:5000'),
                "manual_sync_thumbnail_url": transfer_coordinator.settings.get('DISCORD_MANUAL_SYNC_THUMBNAIL_URL', ''),
                "icon_url": transfer_coordinator.settings.get('DISCORD_ICON_URL', ''),
                "enabled": transfer_coordinator.settings.get_bool('DISCORD_NOTIFICATIONS_ENABLED', False)
            }
            return jsonify({
                "status": "success",
                "settings": settings
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"Failed to get Discord settings: {str(e)}"
            }), 500
    
    else:  # POST
        try:
            data = request.json
            if not data:
                return jsonify({"status": "error", "message": "No data provided"}), 400
            
            # Update Discord settings
            if "enabled" in data:
                transfer_coordinator.settings.set_bool('DISCORD_NOTIFICATIONS_ENABLED', data["enabled"])
                print(f"🎮 Discord notifications enabled: {data['enabled']}")
            
            if "webhook_url" in data:
                transfer_coordinator.settings.set('DISCORD_WEBHOOK_URL', data["webhook_url"])
                print(f"🎮 Discord webhook URL updated")
            
            if "app_url" in data:
                transfer_coordinator.settings.set('DISCORD_APP_URL', data["app_url"])
                print(f"🎮 Discord app URL updated")
            
            if "manual_sync_thumbnail_url" in data:
                transfer_coordinator.settings.set('DISCORD_MANUAL_SYNC_THUMBNAIL_URL', data["manual_sync_thumbnail_url"])
                print(f"🎮 Discord manual sync thumbnail URL updated")
            
            if "icon_url" in data:
                transfer_coordinator.settings.set('DISCORD_ICON_URL', data["icon_url"])
                print(f"🎮 Discord icon URL updated")
            
            return jsonify({
                "status": "success",
                "message": "Discord settings updated successfully"
            })
            
        except Exception as e:
            print(f"❌ Error updating Discord settings: {e}")
            return jsonify({
                "status": "error",
                "message": f"Failed to update Discord settings: {str(e)}"
            }), 500


@webhooks_bp.route('/discord/test', methods=['POST'])
def api_discord_test():
    """Test Discord webhook with a sample notification"""
    try:
        # Check if Discord notifications are enabled
        notifications_enabled = transfer_coordinator.settings.get_bool('DISCORD_NOTIFICATIONS_ENABLED', False)
        if not notifications_enabled:
            return jsonify({
                "status": "error",
                "message": "Discord notifications are disabled. Please enable them first."
            }), 400
        
        # Get Discord webhook URL from settings
        discord_webhook_url = transfer_coordinator.settings.get('DISCORD_WEBHOOK_URL')
        if not discord_webhook_url:
            return jsonify({
                "status": "error",
                "message": "Discord webhook URL not configured"
            }), 400
        
        # Get other Discord settings
        app_url = transfer_coordinator.settings.get('DISCORD_APP_URL', 'http://localhost:5000')
        manual_sync_thumbnail_url = transfer_coordinator.settings.get('DISCORD_MANUAL_SYNC_THUMBNAIL_URL', '')
        icon_url = transfer_coordinator.settings.get('DISCORD_ICON_URL', '')
        
        # Create test embed
        embed = {
            'title': 'DragonCP Test Notification',
            'color': 11164867,  # Purple color
            'fields': [
                {
                    'name': 'Folder Synced',
                    'value': '/test/path/sample_movie',
                    'inline': False
                },
                {
                    'name': 'Files Info',
                    'value': '```Transferred files: 1\nDeleted Files: 2```',
                    'inline': True
                },
                {
                    'name': 'Speed Info',
                    'value': '```Transferred: 3.84G\nAvg Speed: 7.31M bytes/sec```',
                    'inline': True
                },
                {
                    'name': 'Requested by',
                    'value': 'test',
                    'inline': True
                }
            ],
            'author': {
                'name': 'Test Notification',
                'icon_url': icon_url
            },
            'timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            'footer': {
                'text': 'This is a test notification from DragonCP'
            }
        }
        
        # Add URL only if it's a valid format (Discord is strict about URL validation)
        if app_url and _is_valid_discord_url(app_url):
            embed['url'] = app_url
        
        # Add thumbnail if configured
        if manual_sync_thumbnail_url:
            embed['thumbnail'] = {
                'url': manual_sync_thumbnail_url
            }
        
        # Prepare Discord payload
        payload = {
            'embeds': [embed]
        }
        
        # Send test notification
        response = requests.post(
            discord_webhook_url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 204:
            return jsonify({
                "status": "success",
                "message": "Test Discord notification sent successfully!"
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Discord webhook test failed: {response.status_code} - {response.text}"
            }), 400
            
    except Exception as e:
        print(f"❌ Error testing Discord webhook: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to test Discord webhook: {str(e)}"
        }), 500


def _is_valid_discord_url(url: str) -> bool:
    """Validate URL format for Discord embeds"""
    try:
        import re
        # Discord accepts http/https URLs with proper domain format
        # Allow localhost, IP addresses, and proper domain names
        url_pattern = r'^https?://(?:(?:[a-zA-Z0-9-]+\.)*[a-zA-Z0-9-]+|localhost|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d{1,5})?(?:/.*)?$'
        return bool(re.match(url_pattern, url))
    except Exception:
        return False

