#!/usr/bin/env python3
"""
DragonCP Webhook Service
Handles webhook data parsing and sync triggering for movies, series, and anime
"""

from datetime import datetime
from typing import Dict, Tuple


class WebhookService:
    """Service for webhook processing and sync triggering"""
    
    def __init__(self, config, webhook_model, series_webhook_model, transfer_coordinator):
        self.config = config
        self.webhook_model = webhook_model
        self.series_webhook_model = series_webhook_model
        self.transfer_coordinator = transfer_coordinator
    
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
            episode_files = webhook_json.get('episodeFiles', [])
            release = webhook_json.get('release', {})
            
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
            
            # Determine season number from episodes or destination path
            season_number = None
            if episodes:
                season_number = episodes[0].get('seasonNumber')
            
            # Calculate season path at season level
            season_path = webhook_json.get('destinationPath', '')
            
            # Extract release information
            release_title = release.get('releaseTitle', '')
            release_indexer = release.get('indexer', '')
            release_size = release.get('size', 0)
            
            # Extract download information
            download_client = webhook_json.get('downloadClient', '')
            
            # Generate unique notification ID
            notification_id = f"{media_type}_{series_id or int(datetime.now().timestamp())}_s{season_number or 'unknown'}_{int(datetime.now().timestamp())}"
            
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
                'status': 'pending'
            }
            
            print(f"📋 Parsed {media_type} webhook data for: {series_title} Season {season_number}")
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
            
            # Extract movie details
            folder_name = notification['title']
            if notification.get('year'):
                folder_name = f"{notification['title']} ({notification['year']})"
            
            # Use folder_path as source_path and determine destination
            source_path = notification['folder_path']
            
            # Get movie destination path from config
            dest_base = self.config.get("MOVIE_DEST_PATH")
            if not dest_base:
                self.webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': 'Movie destination path not configured'
                })
                return False, "Movie destination path not configured"
            
            dest_path = f"{dest_base}/{folder_name}"
            
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
            series_title = notification['series_title']
            season_number = notification.get('season_number')
            media_type = notification['media_type']
            
            # Determine folder name (series title with year if available)
            if notification.get('year'):
                folder_name = f"{series_title} ({notification['year']})"
            else:
                folder_name = series_title
            
            # Use season_path as the final destination for this season
            dest_path = notification['season_path']
            
            # For source path, use the series_path + season
            source_path = notification['series_path']
            if season_number:
                # Add season folder to source path
                source_path = f"{source_path}/Season {season_number:02d}"
            
            # Get the correct destination base path from config
            dest_base_map = {
                "anime": self.config.get("ANIME_DEST_PATH"),
                "series": self.config.get("TVSHOW_DEST_PATH"),
                "tvshows": self.config.get("TVSHOW_DEST_PATH")
            }
            
            dest_base = dest_base_map.get(media_type)
            if not dest_base:
                self.series_webhook_model.update(notification_id, {
                    'status': 'failed',
                    'error_message': f'{media_type.title()} destination path not configured'
                })
                return False, f"{media_type.title()} destination path not configured"
            
            # Override destination to use config destination + folder + season
            season_name = f"Season {season_number:02d}" if season_number else "Season Unknown"
            dest_path = f"{dest_base}/{folder_name}/{season_name}"
            
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
            else:
                print(f"⚠️  No webhook notification found for transfer {transfer_id} (media_type: {media_type})")
                    
        except Exception as e:
            print(f"❌ Error updating webhook transfer status: {e}")

