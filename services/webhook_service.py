#!/usr/bin/env python3
"""
DragonCP Webhook Service
Handles webhook data parsing and sync triggering for movies, series, and anime
"""

from datetime import datetime
from typing import Dict, Tuple
from services.path_service import PathService


class WebhookService:
    """Service for webhook processing and sync triggering"""
    
    def __init__(self, config, webhook_model, series_webhook_model, transfer_coordinator):
        self.config = config
        self.webhook_model = webhook_model
        self.series_webhook_model = series_webhook_model
        self.transfer_coordinator = transfer_coordinator
        self.path_service = PathService(config)
    
    def parse_webhook_data(self, webhook_json: Dict) -> Dict:
        """Parse webhook JSON data according to specification"""
        try:
            movie = webhook_json.get('movie', {})
            movie_file = webhook_json.get('movieFile', {})
            release = webhook_json.get('release', {})
            
            # Extract title and year
            title = movie.get('title', 'Unknown Movie')
            year = movie.get('year')
            
            # Extract folder path
            folder_path = movie.get('folderPath', '')
            
            # Extract poster URL from images
            poster_url = None
            images = movie.get('images', [])
            for image in images:
                if image.get('coverType') == 'poster':
                    poster_url = image.get('remoteUrl')
                    break
            
            # Extract requested by from tags (format: <number> - <name>)
            requested_by = None
            tags = movie.get('tags', [])
            for tag in tags:
                if isinstance(tag, str) and ' - ' in tag:
                    parts = tag.split(' - ', 1)
                    if len(parts) == 2 and parts[0].strip().isdigit():
                        requested_by = parts[1].strip()
                        break
            
            # Extract file information
            file_path = movie_file.get('path', '')
            quality = movie_file.get('quality', '')
            size = movie_file.get('size', 0)
            
            # Extract languages
            languages = []
            movie_file_languages = movie_file.get('languages', [])
            for lang in movie_file_languages:
                if isinstance(lang, dict) and 'name' in lang:
                    languages.append(lang['name'])
            
            # Extract subtitles from mediaInfo
            subtitles = []
            media_info = movie_file.get('mediaInfo', {})
            if 'subtitles' in media_info:
                subtitles = media_info['subtitles']
            
            # Extract release information
            release_title = release.get('releaseTitle', '')
            release_indexer = release.get('indexer', '')
            release_size = release.get('size', 0)
            
            # Extract TMDB and IMDB IDs
            tmdb_id = movie.get('tmdbId')
            imdb_id = movie.get('imdbId')
            
            # Generate unique notification ID
            # FORMAT: movie_{movie_id}_{timestamp}
            # 
            # NOTE: Movies use second-precision timestamps because each movie has a unique
            # movie_id from Radarr. Unlike series where the same series/season can have
            # multiple episodes processed simultaneously, movies are processed one at a time
            # per movie_id, making collisions extremely unlikely.
            # 
            # Example: "movie_123_1732103526"
            notification_id = f"movie_{movie.get('id', int(datetime.now().timestamp()))}_{int(datetime.now().timestamp())}"
            
            parsed_data = {
                'notification_id': notification_id,
                'title': title,
                'year': year,
                'folder_path': folder_path,
                'poster_url': poster_url,
                'requested_by': requested_by,
                'file_path': file_path,
                'quality': quality,
                'size': size,
                'languages': languages,
                'subtitles': subtitles,
                'release_title': release_title,
                'release_indexer': release_indexer,
                'release_size': release_size,
                'tmdb_id': tmdb_id,
                'imdb_id': imdb_id,
                'status': 'pending'
            }
            
            print(f"📋 Parsed webhook data for movie: {title} ({year})")
            return parsed_data
            
        except Exception as e:
            print(f"❌ Error parsing webhook data: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def parse_series_webhook_data(self, webhook_json: Dict, media_type: str) -> Dict:
        """Parse series/anime webhook JSON data according to specification"""
        try:
            series = webhook_json.get('series', {})
            episodes = webhook_json.get('episodes', [])
            episode_file = webhook_json.get('episodeFile', {})  # Fixed: singular, not plural
            release = webhook_json.get('release', {})
            is_upgrade = webhook_json.get('isUpgrade', False)
            
            # Extract series information
            series_title = series.get('title', 'Unknown Series')
            series_title_slug = series.get('titleSlug', '')
            series_id = series.get('id')
            series_path = series.get('path', '')
            year = series.get('year')
            
            # Extract IDs
            tvdb_id = series.get('tvdbId')
            tv_maze_id = series.get('tvMazeId')
            tmdb_id = series.get('tmdbId')
            imdb_id = series.get('imdbId')
            
            # Extract series metadata
            tags = series.get('tags', [])
            original_language = series.get('originalLanguage', {}).get('name', '')
            
            # Extract poster and banner URLs from images
            poster_url = None
            banner_url = None
            images = series.get('images', [])
            for image in images:
                if image.get('coverType') == 'poster':
                    poster_url = image.get('remoteUrl')
                elif image.get('coverType') == 'banner':
                    banner_url = image.get('remoteUrl')
            
            # Extract requested by from tags (format: <number> - <name>)
            requested_by = None
            for tag in tags:
                if isinstance(tag, str) and ' - ' in tag:
                    parts = tag.split(' - ', 1)
                    if len(parts) == 2 and parts[0].strip().isdigit():
                        requested_by = parts[1].strip()
                        break
            
            # Determine season number from episodes
            season_number = None
            if episodes:
                season_number = episodes[0].get('seasonNumber')
            
            # Build episode_files array with current episode file only
            episode_files = []
            if episode_file:
                episode_files.append(episode_file)
            
            # Calculate season_path from episode file path or construct from series path
            season_path = ''
            if episode_file and episode_file.get('path'):
                # Extract directory from the episode file path
                import os
                file_path = episode_file['path']
                season_path = os.path.dirname(file_path)
            elif series_path and season_number is not None:
                # Fallback: construct from series path + season number
                season_path = f"{series_path}/Season {season_number:02d}"
            
            # Extract release information
            release_title = release.get('releaseTitle', '')
            release_indexer = release.get('indexer', '')
            release_size = release.get('size', 0)
            
            # Extract download information
            download_client = webhook_json.get('downloadClient', '')
            
            # Generate unique notification ID
            # FORMAT: {media_type}_{series_id}_s{season_number}_ef{episode_file_id}
            # 
            # WHY: Previously used second-precision timestamps which caused UNIQUE constraint
            # violations when multiple episodes from the same series/season were processed
            # within the same second (common during batch imports/season packs).
            # 
            # SOLUTION: Use episode_file_id from Sonarr (unique per file) as primary identifier.
            # If episode_file_id is unavailable, fallback to microsecond-precision timestamp
            # to ensure uniqueness even for rapid consecutive webhooks.
            # 
            # Examples:
            #   - With episode_file_id: "tvshows_123_s2_ef456"
            #   - Fallback (no file_id): "tvshows_123_s2_1732103526789456"
            episode_file_id = episode_file.get('id') if episode_file else None
            
            if episode_file_id:
                # Primary method: Use Sonarr's episode file ID (guaranteed unique)
                notification_id = f"{media_type}_{series_id or 'unknown'}_s{season_number or 0}_ef{episode_file_id}"
            else:
                # Fallback: Use microsecond-precision timestamp for uniqueness
                # (Season packs or cases where episode_file is not provided)
                timestamp_microseconds = int(datetime.now().timestamp() * 1000000)
                notification_id = f"{media_type}_{series_id or 'unknown'}_s{season_number or 0}_{timestamp_microseconds}"
            
            parsed_data = {
                'notification_id': notification_id,
                'media_type': media_type,
                'series_title': series_title,
                'series_title_slug': series_title_slug,
                'series_id': series_id,
                'series_path': series_path,
                'year': year,
                'tvdb_id': tvdb_id,
                'tv_maze_id': tv_maze_id,
                'tmdb_id': tmdb_id,
                'imdb_id': imdb_id,
                'poster_url': poster_url,
                'banner_url': banner_url,
                'tags': tags,
                'original_language': original_language,
                'requested_by': requested_by,
                'season_number': season_number,
                'episode_count': len(episodes),
                'episodes': episodes,
                'episode_files': episode_files,
                'season_path': season_path,
                'release_title': release_title,
                'release_indexer': release_indexer,
                'release_size': release_size,
                'download_client': download_client,
                'is_upgrade': is_upgrade,
                'status': 'pending'
            }
            
            print(f"📋 Parsed {media_type} webhook data for: {series_title} Season {season_number}")
            print(f"   Episode files: {len(episode_files)} file(s), Season path: {season_path}")
            return parsed_data
            
        except Exception as e:
            print(f"❌ Error parsing {media_type} webhook data: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def trigger_webhook_sync(self, notification_id: str) -> Tuple[bool, str]:
        """Trigger sync for a webhook notification (movies)"""
        try:
            # Get notification details
            notification = self.webhook_model.get(notification_id)
            if not notification:
                return False, "Notification not found"
            
            if notification['status'] == 'syncing':
                return False, "Sync already in progress"
            
            if notification['status'] == 'completed':
                return False, "Already synced"
            
            # Update notification status to syncing
            self.webhook_model.update(notification_id, {
                'status': 'syncing',
                'synced_at': datetime.now().isoformat()
            })
            
            # Generate transfer ID
            transfer_id = f"webhook_{notification_id}_{int(datetime.now().timestamp())}"
            
            # Use folder_path as source_path (contains actual folder name from remote server)
            source_path = notification['folder_path']
            if not source_path:
                self.webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': 'Missing folder_path in notification'
                })
                return False, "Missing folder_path in notification"
            
            # Use PathService to construct destination path consistently
            # This ensures folder names match the remote server (already sanitized by Radarr)
            try:
                dest_path = self.path_service.get_destination_path(source_path, 'movies')
            except ValueError as e:
                self.webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': str(e)
                })
                return False, str(e)
            
            # Extract folder name for transfer record (from actual path, not title)
            import os
            folder_name = os.path.basename(source_path.rstrip('/'))
            
            # Store transfer ID in notification
            self.webhook_model.update(notification_id, {'transfer_id': transfer_id})
            
            # Start the transfer using transfer coordinator
            success = self.transfer_coordinator.start_transfer(
                transfer_id=transfer_id,
                source_path=source_path,
                dest_path=dest_path,
                transfer_type="folder",
                media_type="movies",
                folder_name=folder_name,
                season_name=None,
                episode_name=None
            )
            
            if success:
                print(f"✅ Webhook sync started for {notification['title']} (Transfer ID: {transfer_id})")
                return True, f"Sync started for {notification['title']}"
            else:
                # Update notification status back to pending on failure
                self.webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': 'Failed to start transfer'
                })
                return False, "Failed to start transfer"
                
        except Exception as e:
            print(f"❌ Error triggering webhook sync: {e}")
            import traceback
            traceback.print_exc()
            
            # Update notification status to failed
            self.webhook_model.update(notification_id, {
                'status': 'failed',
                'error_message': str(e)
            })
            return False, f"Sync failed: {str(e)}"
    
    def trigger_series_webhook_sync(self, notification_id: str) -> Tuple[bool, str]:
        """Trigger sync for a series/anime webhook notification"""
        try:
            # Get notification details
            notification = self.series_webhook_model.get(notification_id)
            if not notification:
                return False, "Notification not found"
            
            if notification['status'] == 'syncing':
                return False, "Sync already in progress"
            
            if notification['status'] == 'completed':
                return False, "Already synced"
            
            # Update notification status to syncing
            self.series_webhook_model.update(notification_id, {
                'status': 'syncing',
                'synced_at': datetime.now().isoformat()
            })
            
            # Generate transfer ID
            transfer_id = f"series_webhook_{notification_id}_{int(datetime.now().timestamp())}"
            
            # Extract series details
            series_path = notification.get('series_path')
            season_path = notification.get('season_path')
            season_number = notification.get('season_number')
            media_type = notification['media_type']
            
            # Determine source path - prefer the actual season_path from webhook
            # (extracted from real episode file path on remote server)
            if season_path:
                # PRIMARY: Use the actual season path from webhook notification
                # This is extracted from the episode file path and represents the real folder on disk
                source_path = season_path
                print(f"📁 Using actual season_path from webhook: {source_path}")
            elif series_path and season_number is not None:
                # FALLBACK: Reconstruct season path if season_path is not available
                # This is a fallback only, assumes Sonarr's standard "Season XX" format
                source_path = f"{series_path.rstrip('/')}/Season {season_number:02d}"
                print(f"⚠️  season_path not in notification, reconstructed: {source_path}")
            elif series_path:
                # Whole series sync (rare case, no season specified)
                source_path = series_path
                print(f"📁 Using series_path for whole series sync: {source_path}")
            else:
                self.series_webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': 'Missing series_path and season_path in notification'
                })
                return False, "Missing series_path and season_path in notification"
            
            # Use PathService to construct destination path consistently
            # This ensures folder names match the remote server (already sanitized by Sonarr)
            try:
                dest_path = self.path_service.get_destination_path(source_path, media_type)
            except ValueError as e:
                self.series_webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': str(e)
                })
                return False, str(e)
            
            # Extract folder and season names for transfer record (from actual paths, not title)
            import os
            folder_name, season_name = self.path_service.extract_folder_components(source_path, media_type)
            
            # Store transfer ID in notification
            self.series_webhook_model.update(notification_id, {'transfer_id': transfer_id})
            
            # Start the transfer using transfer coordinator
            success = self.transfer_coordinator.start_transfer(
                transfer_id=transfer_id,
                source_path=source_path,
                dest_path=dest_path,
                transfer_type='folder',
                media_type=media_type,
                folder_name=folder_name,
                season_name=season_name,
                episode_name=None
            )
            
            if success:
                series_title = notification['series_title']
                print(f"✅ Series webhook sync started: {series_title} Season {season_number}")
                return True, f"Sync started for {series_title} Season {season_number}"
            else:
                self.series_webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': 'Failed to start transfer'
                })
                return False, "Failed to start transfer"
                
        except Exception as e:
            print(f"❌ Error triggering series webhook sync: {e}")
            self.series_webhook_model.update(notification_id, {
                'status': 'failed',
                'error_message': str(e)
            })
            return False, f"Failed to trigger sync: {str(e)}"
    
    def update_webhook_transfer_status(self, transfer_id: str, status: str, transfer_model):
        """Update webhook notification status based on transfer completion"""
        try:
            # Get the transfer record to determine media_type
            transfer = transfer_model.get(transfer_id)
            if not transfer:
                print(f"⚠️  Transfer {transfer_id} not found, skipping webhook status update")
                return
            
            media_type = transfer.get('media_type', '')
            webhook_notification = None
            
            # Search the appropriate webhook table based on transfer media_type
            if media_type == 'movies':
                # Search movie webhook notifications
                notifications = self.webhook_model.get_all()
                for notification in notifications:
                    if notification.get('transfer_id') == transfer_id:
                        webhook_notification = notification
                        break
            elif media_type in ['anime', 'tvshows', 'series']:
                # Search series/anime webhook notifications
                notifications = self.series_webhook_model.get_all()
                for notification in notifications:
                    if notification.get('transfer_id') == transfer_id:
                        webhook_notification = notification
                        break
            else:
                print(f"⚠️  Unknown media_type '{media_type}' for transfer {transfer_id}, skipping webhook status update")
                return
            
            if webhook_notification:
                update_data = {}
                if status == 'completed':
                    update_data = {
                        'status': 'completed',
                        'synced_at': datetime.now().isoformat()
                    }
                elif status == 'failed':
                    update_data = {
                        'status': 'failed',
                        'error_message': 'Transfer failed'
                    }
                
                if update_data:
                    # Update the appropriate model based on media_type
                    if media_type == 'movies':
                        self.webhook_model.update(webhook_notification['notification_id'], update_data)
                        print(f"📋 Updated movie webhook notification status to {status} for {webhook_notification['title']}")
                    elif media_type in ['anime', 'tvshows', 'series']:
                        self.series_webhook_model.update(webhook_notification['notification_id'], update_data)
                        title = webhook_notification.get('series_title', webhook_notification.get('title', 'Unknown'))
                        print(f"📋 Updated {media_type} webhook notification status to {status} for {title}")
                        
                        # After successful series/anime season sync, mark all PENDING notifications for the same season as COMPLETED
                        if status == 'completed' and transfer.get('transfer_type') == 'folder':
                            self._mark_pending_season_notifications_completed(transfer, webhook_notification)
            else:
                print(f"⚠️  No webhook notification found for transfer {transfer_id} (media_type: {media_type})")
                
                # For manual syncs without linked notification, still mark pending notifications as completed
                if status == 'completed' and media_type in ['anime', 'tvshows', 'series'] and transfer.get('transfer_type') == 'folder':
                    self._mark_pending_season_notifications_completed_from_transfer(transfer)
                    
        except Exception as e:
            print(f"❌ Error updating webhook transfer status: {e}")
    
    def _mark_pending_season_notifications_completed(self, transfer: Dict, completed_notification: Dict):
        """Mark all pending notifications for the same series/season as completed"""
        try:
            series_title = completed_notification.get('series_title')
            season_number = completed_notification.get('season_number')
            media_type = completed_notification.get('media_type')
            
            if not series_title or season_number is None:
                return
            
            print(f"🔄 Checking for other PENDING notifications for {series_title} Season {season_number}")
            updated_count = self.series_webhook_model.mark_pending_by_series_season_completed(
                series_title=series_title,
                season_number=season_number,
                media_type=media_type
            )
            
            if updated_count > 0:
                print(f"✅ Marked {updated_count} additional PENDING notification(s) as COMPLETED")
        except Exception as e:
            print(f"❌ Error marking pending season notifications: {e}")
            import traceback
            traceback.print_exc()
    
    def _mark_pending_season_notifications_completed_from_transfer(self, transfer: Dict):
        """Mark pending notifications based on manual sync transfer details"""
        try:
            # Extract series details from transfer
            media_type = transfer.get('media_type')
            folder_name = transfer.get('folder_name')  # e.g., "Series Name (2023)"
            season_name = transfer.get('season_name')  # e.g., "Season 01"

            #TODO: improve this function to match only SEASON PATH insted of parsing season number and series title
            
            if not folder_name or not season_name or not media_type:
                return
            
            # Parse season number from season_name (e.g., "Season 01" -> 1)
            import re
            season_match = re.search(r'Season\s+(\d+)', season_name, re.IGNORECASE)
            if not season_match:
                return
            
            season_number = int(season_match.group(1))
            
            # Parse series_title from folder_name (remove year if present)
            # e.g., "Series Name (2023)" -> "Series Name"
            series_title = re.sub(r'\s*\(\d{4}\)\s*$', '', folder_name).strip()
            
            print(f"🔄 Checking for PENDING notifications for manual sync: {series_title} Season {season_number}")
            updated_count = self.series_webhook_model.mark_pending_by_series_season_completed(
                series_title=series_title,
                season_number=season_number,
                media_type=media_type
            )
            
            if updated_count > 0:
                print(f"✅ Marked {updated_count} PENDING notification(s) as COMPLETED for manual sync")
        except Exception as e:
            print(f"❌ Error marking pending notifications from manual sync: {e}")
            import traceback
            traceback.print_exc()

