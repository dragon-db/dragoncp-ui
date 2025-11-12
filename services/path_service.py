#!/usr/bin/env python3
"""
DragonCP Path Service
Centralized service for constructing destination paths from source paths.
Ensures consistency between dry-run validation and actual sync operations.
"""

import os
from typing import Optional, Tuple


class PathService:
    """
    Centralized service for path construction and manipulation.
    
    Core principle: Destination folder structure should mirror source structure,
    with only the base path replaced. This ensures that:
    1. Folder names are identical (already sanitized by Radarr/Sonarr)
    2. Dry-run and actual sync use the same paths
    3. No issues with special characters in titles
    """
    
    def __init__(self, config):
        """Initialize with config for accessing destination base paths"""
        self.config = config
    
    def get_destination_path(self, source_path: str, media_type: str) -> str:
        """
        Convert a remote source path to local destination path.
        
        This is the main function that should be used everywhere for consistency.
        
        Algorithm:
        1. Extract the folder structure from source path
        2. Get the appropriate destination base path for media type
        3. Combine them to create destination path
        
        Args:
            source_path: Remote source path (e.g., "/remote/Movies/Title (2021)")
            media_type: Type of media ("movies", "tvshows", "anime")
        
        Returns:
            Local destination path (e.g., "/local/movies/Title (2021)")
        
        Examples:
            >>> get_destination_path("/remote/Movies/New Gods Nezha Reborn (2021)", "movies")
            "/local/movies/New Gods Nezha Reborn (2021)"
            
            >>> get_destination_path("/remote/TVShows/Breaking Bad (2008)/Season 01", "tvshows")
            "/local/tvshows/Breaking Bad (2008)/Season 01"
        """
        if not source_path:
            raise ValueError("source_path cannot be empty")
        
        # Get destination base path
        dest_base = self.get_base_destination(media_type)
        if not dest_base:
            raise ValueError(f"Destination path not configured for media type: {media_type}")
        
        # Extract relative folder structure
        relative_structure = self.extract_relative_structure(source_path, media_type)
        
        # Combine to create destination path
        dest_path = os.path.join(dest_base, relative_structure)
        
        return dest_path
    
    def extract_relative_structure(self, source_path: str, media_type: str) -> str:
        """
        Extract the folder structure that should be preserved in destination.
        
        For movies: Just the movie folder name
        For series/anime: Series folder + Season folder (if season path provided)
        
        Args:
            source_path: Remote source path
            media_type: Type of media
        
        Returns:
            Relative folder structure to preserve
        
        Examples:
            >>> extract_relative_structure("/remote/Movies/Title (2021)", "movies")
            "Title (2021)"
            
            >>> extract_relative_structure("/remote/TVShows/Show (2020)/Season 01", "tvshows")
            "Show (2020)/Season 01"
            
            >>> extract_relative_structure("/remote/TVShows/Show (2020)", "tvshows")
            "Show (2020)"
        """
        # Normalize path (remove trailing slashes)
        source_path = source_path.rstrip('/')
        
        if media_type == 'movies':
            # For movies, just extract the movie folder name
            folder_name = os.path.basename(source_path)
            return folder_name
        
        elif media_type in ['tvshows', 'anime', 'series']:
            # For series/anime, we need to determine if this is a season path or series path
            folder_name = os.path.basename(source_path)
            
            # Check if this looks like a season folder
            if folder_name.lower().startswith('season '):
                # This is a season path, need to include both series and season
                series_path = os.path.dirname(source_path)
                series_folder = os.path.basename(series_path)
                return f"{series_folder}/{folder_name}"
            else:
                # This is just a series folder path
                return folder_name
        
        else:
            raise ValueError(f"Unknown media type: {media_type}")
    
    def get_base_destination(self, media_type: str) -> Optional[str]:
        """
        Get the configured destination base path for a media type.
        
        Args:
            media_type: Type of media ("movies", "tvshows", "anime")
        
        Returns:
            Base destination path from config, or None if not configured
        """
        dest_map = {
            "movies": self.config.get("MOVIE_DEST_PATH"),
            "tvshows": self.config.get("TVSHOW_DEST_PATH"),
            "anime": self.config.get("ANIME_DEST_PATH"),
            "series": self.config.get("TVSHOW_DEST_PATH")  # Alias for tvshows
        }
        
        return dest_map.get(media_type)
    
    def extract_folder_components(self, source_path: str, media_type: str) -> Tuple[str, Optional[str]]:
        """
        Extract folder components for more detailed path manipulation.
        
        Args:
            source_path: Remote source path
            media_type: Type of media
        
        Returns:
            Tuple of (folder_name, season_name) where season_name is None for movies
        
        Examples:
            >>> extract_folder_components("/remote/Movies/Title (2021)", "movies")
            ("Title (2021)", None)
            
            >>> extract_folder_components("/remote/TVShows/Show/Season 01", "tvshows")
            ("Show", "Season 01")
        """
        source_path = source_path.rstrip('/')
        
        if media_type == 'movies':
            folder_name = os.path.basename(source_path)
            return (folder_name, None)
        
        elif media_type in ['tvshows', 'anime', 'series']:
            current_folder = os.path.basename(source_path)
            
            # Check if this is a season path
            if current_folder.lower().startswith('season '):
                # Extract season and series folders
                season_name = current_folder
                series_path = os.path.dirname(source_path)
                folder_name = os.path.basename(series_path)
                return (folder_name, season_name)
            else:
                # Just a series folder
                return (current_folder, None)
        
        else:
            raise ValueError(f"Unknown media type: {media_type}")
    
    def construct_destination_from_components(
        self, 
        media_type: str, 
        folder_name: str, 
        season_name: Optional[str] = None
    ) -> str:
        """
        Construct destination path from individual components.
        
        This is useful when you have folder/season names from other sources
        (like manual input from UI).
        
        Args:
            media_type: Type of media
            folder_name: Main folder name (movie or series folder)
            season_name: Season folder name (optional, for series/anime)
        
        Returns:
            Complete destination path
        """
        dest_base = self.get_base_destination(media_type)
        if not dest_base:
            raise ValueError(f"Destination path not configured for media type: {media_type}")
        
        if season_name:
            # Series/anime with season
            dest_path = os.path.join(dest_base, folder_name, season_name)
        else:
            # Movie or series folder
            dest_path = os.path.join(dest_base, folder_name)
        
        return dest_path
    
    def validate_destination_path(self, dest_path: str) -> bool:
        """
        Validate that a destination path is valid.
        
        Args:
            dest_path: Destination path to validate
        
        Returns:
            True if valid, False otherwise
        """
        if not dest_path:
            return False
        
        # Check for invalid characters (though os.path.join should handle most)
        # On Linux, most characters are valid except null byte
        if '\0' in dest_path:
            return False
        
        return True
    
    def get_source_path_from_notification(
        self, 
        notification: dict, 
        media_type: str
    ) -> str:
        """
        Extract the appropriate source path from a webhook notification.
        
        This handles the differences between movie and series/anime notifications.
        
        Args:
            notification: Webhook notification dictionary
            media_type: Type of media
        
        Returns:
            Source path to use for transfer
        
        Raises:
            ValueError: If required fields are missing
        """
        if media_type == 'movies':
            # For movies, use folder_path directly
            source_path = notification.get('folder_path')
            if not source_path:
                raise ValueError("Movie notification missing 'folder_path'")
            return source_path
        
        elif media_type in ['tvshows', 'anime', 'series']:
            # For series/anime, we need to construct season path
            series_path = notification.get('series_path')
            season_number = notification.get('season_number')
            
            if not series_path:
                raise ValueError("Series notification missing 'series_path'")
            
            if season_number is not None:
                # Construct season path
                season_folder = f"Season {season_number:02d}"
                source_path = f"{series_path.rstrip('/')}/{season_folder}"
                return source_path
            else:
                # Just use series path (whole series sync)
                return series_path
        
        else:
            raise ValueError(f"Unknown media type: {media_type}")

