#!/usr/bin/env python3
"""
DragonCP Webhook Service
Handles webhook data parsing and sync triggering for movies, series, and anime
"""

from datetime import datetime
from typing import Dict, Tuple, List
from services.path_service import PathService
from services.sync_logger import log_sync, log_batch, log_validation, log_state_change


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
    
    # ---- starting a sync --------------------------------------------------
    #
    # Every way a webhook gets synced goes through the sync engine now: the
    # automatic path from the receivers, and these manual ones. They used to
    # start transfers directly — no batch, no safety check for movies, and a
    # race with the waiting automatic batch that marked its webhooks failed
    # while the manual copy ran. The names stay because callers use them.

    def _engine(self):
        return getattr(self.transfer_coordinator, 'sync_engine', None)

    def trigger_webhook_sync(self, notification_id: str) -> Tuple[bool, str]:
        """Sync one movie notification, through the pipeline."""
        result = self._engine().sync_notifications([notification_id])
        return bool(result.get('ok')), result.get('message') or ''

    def sync_notification_group(self, notification_ids: List[str]) -> Tuple[bool, str, List[str]]:
        """
        Sync a group of series/anime notifications as ONE transfer per season.

        Sonarr sends one webhook per episode, so a six-episode grab produces six
        notifications for the same season. The engine groups them by the folder
        they would be copied into — re-derived on the server, never taken from
        the caller — so the client cannot decide which folder gets synced.

        Returns (success, message, run_ids). Transfers are created once each
        batch passes its safety check, so the ids returned are the runs to
        follow.
        """
        if not notification_ids:
            return False, "No notifications given", []
        result = self._engine().sync_notifications(notification_ids)
        return bool(result.get('ok')), result.get('message') or '', list(result.get('run_ids') or [])

    def trigger_series_webhook_sync(self, notification_id: str, batched_notification_ids: List[str] = None) -> Tuple[bool, str]:
        """Sync one series/anime notification (and any batched with it), through the pipeline."""
        ids = [notification_id] + [n for n in (batched_notification_ids or []) if n != notification_id]
        result = self._engine().sync_notifications(ids)
        return bool(result.get('ok')), result.get('message') or ''
    
    def update_webhook_transfer_status(self, transfer_id: str, status: str, transfer_model):
        """
        Update webhook notification status based on transfer state changes
        
        TRANSFER STATE -> WEBHOOK STATE MAPPING:
        - transfer 'pending'   -> webhook stays in current state (preparing)
        - transfer 'running'   -> webhook 'SYNCING' 
        - transfer 'queued'    -> webhook 'QUEUED_PATH' or 'QUEUED_SLOT' (determined by context)
        - transfer 'completed' -> webhook 'COMPLETED'
        - transfer 'failed'    -> webhook 'FAILED'
        - transfer 'cancelled' -> webhook 'CANCELLED'
        """
        try:
            # Get the transfer record to determine media_type
            transfer = transfer_model.get(transfer_id)
            if not transfer:
                print(f"⚠️  Transfer {transfer_id} not found, skipping webhook status update")
                return
            
            media_type = transfer.get('media_type', '')
            webhook_notification = None
            
            # Lookup webhook notification by transfer_id (efficient indexed query)
            if media_type == 'movies':
                # Direct lookup using indexed transfer_id column
                webhook_notification = self.webhook_model.get_by_transfer_id(transfer_id)
            elif media_type in ['anime', 'tvshows', 'series']:
                # Direct lookup using indexed transfer_id column
                webhook_notification = self.series_webhook_model.get_by_transfer_id(transfer_id)
            else:
                print(f"⚠️  Unknown media_type '{media_type}' for transfer {transfer_id}, skipping webhook status update")
                return
            
            if webhook_notification:
                update_data = {}
                
                # Map transfer status to webhook status
                if status == 'running':
                    update_data = {
                        'status': 'syncing',  # Transfer running -> Webhook SYNCING
                        'completed_at': datetime.now().isoformat()
                    }
                elif status == 'completed':
                    update_data = {
                        'status': 'completed',
                        'completed_at': datetime.now().isoformat()
                    }
                elif status == 'failed':
                    update_data = {
                        'status': 'failed',
                        'error_message': 'Transfer failed'
                    }
                elif status == 'cancelled':
                    update_data = {
                        'status': 'cancelled'
                    }
                elif status == 'queued':
                    # Transfer queued - webhook should be QUEUED_SLOT or QUEUED_PATH
                    # The specific queue type should have been set by the coordinator
                    # Don't override here, just log
                    print(f"📋 Transfer {transfer_id} is queued, webhook should already be in QUEUED_SLOT or QUEUED_PATH")
                    return
                
                if update_data:
                    # Update the appropriate model based on media_type
                    if media_type == 'movies':
                        self.webhook_model.update(webhook_notification['notification_id'], update_data)
                        print(f"📋 Updated movie webhook notification status to {update_data['status']} for {webhook_notification['title']}")
                    elif media_type in ['anime', 'tvshows', 'series']:
                        # For series/anime, update ALL notifications linked to this transfer
                        # This ensures batched episodes stay in sync
                        updated_count = self.series_webhook_model.update_notifications_by_transfer_id(
                            transfer_id,
                            update_data
                        )
                        title = webhook_notification.get('series_title', webhook_notification.get('title', 'Unknown'))
                        print(f"📋 Updated {updated_count} {media_type} notification(s) for transfer {transfer_id} to {update_data['status']}")
                        
                        # After successful series/anime transfer, mark all SYNCING notifications linked to this transfer as COMPLETED
                        # Uses transfer_id linkage for accurate completion marking
                        if status == 'completed':
                            self._mark_notifications_completed_by_transfer(transfer_id)
            else:
                print(f"⚠️  No webhook notification found for transfer {transfer_id} (media_type: {media_type})")
                
                # For manual syncs, try to use transfer_id if available
                # Fallback to series/season matching only if needed
                if status == 'completed' and media_type in ['anime', 'tvshows', 'series']:
                    # Try to find notifications by transfer pattern (manual transfers may not have direct linkage)
                    self._mark_pending_season_notifications_completed_from_transfer(transfer)
                    
        except Exception as e:
            print(f"❌ Error updating webhook transfer status: {e}")
    
    def _mark_notifications_completed_by_transfer(self, transfer_id: str):
        """
        Mark all SYNCING notifications linked to a transfer as completed
        
        Uses transfer_id linkage instead of series/season matching for accurate
        completion marking. Only notifications actually in the completed transfer
        will be marked.
        """
        try:
            if not transfer_id:
                print(f"⚠️ No transfer_id provided for completion marking")
                return
            
            print(f"🔄 Marking all notifications linked to transfer {transfer_id} as COMPLETED")
            updated_count = self.series_webhook_model.mark_notifications_completed_by_transfer(transfer_id)
            
            if updated_count > 0:
                print(f"✅ Marked {updated_count} notification(s) as COMPLETED for transfer {transfer_id}")
        except Exception as e:
            print(f"❌ Error marking notifications completed by transfer: {e}")
            import traceback
            traceback.print_exc()
    
    def _mark_pending_season_notifications_completed_from_transfer(self, transfer: Dict):
        """
        Mark SYNCING notifications based on manual sync transfer details
        
        IMPORTANT: Only marks SYNCING notifications (those actively being transferred).
        Does NOT mark PENDING notifications (episodes that arrived during sync - they need next cycle).
        """
        try:
            # Extract series details from transfer
            media_type = transfer.get('media_type')
            folder_name = transfer.get('folder_name')  # e.g., "Series Name (2023)"
            season_name = transfer.get('season_name')  # e.g., "Season 01"

            #TODO: improve this function to match only SEASON PATH instead of parsing season number and series title
            
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
            
            print(f"🔄 Checking for SYNCING notifications for manual sync: {series_title} Season {season_number}")
            updated_count = self.series_webhook_model.mark_pending_by_series_season_completed(
                series_title=series_title,
                season_number=season_number,
                media_type=media_type
            )
            
            if updated_count > 0:
                print(f"✅ Marked {updated_count} SYNCING notification(s) as COMPLETED for manual sync")
        except Exception as e:
            print(f"❌ Error marking SYNCING notifications from manual sync: {e}")
            import traceback
            traceback.print_exc()

