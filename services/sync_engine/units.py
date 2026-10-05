#!/usr/bin/env python3
"""
Identify: what a sync is about, and where it copies from and to.

One answer for every way a sync starts, so a webhook, a manual press and a
restart of the same season land on the same folder — and therefore in the
same batch and behind the same lock. The destination is what identifies a
unit: it is what the queue locks on, and two requests that would write the
same folder are the same piece of work.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence


class IdentifyError(ValueError):
    """The request does not name something this installation can sync."""


@dataclass
class Unit:
    """One thing to sync: a season folder, a whole series, or a movie folder."""

    media_type: str
    source_path: str
    dest_path: str
    folder_name: str
    season_name: Optional[str] = None
    season_number: Optional[int] = None
    title: str = ''
    operation_type: str = 'folder'
    #: Identifiers the services know this title by (tvdb_id, tmdb_id, series_id).
    ids: Dict[str, Any] = field(default_factory=dict)

    @property
    def unit_key(self) -> str:
        return unit_key(self.dest_path)

    @property
    def label(self) -> str:
        """How a person would name it: "Example Show — Season 01"."""
        name = self.title or self.folder_name or os.path.basename(self.dest_path.rstrip('/'))
        if self.season_name:
            return f"{name} — {self.season_name}"
        return name

    def as_dict(self) -> Dict[str, Any]:
        return {
            'media_type': self.media_type, 'source_path': self.source_path,
            'dest_path': self.dest_path, 'folder_name': self.folder_name,
            'season_name': self.season_name, 'season_number': self.season_number,
            'title': self.title, 'operation_type': self.operation_type,
            'unit_key': self.unit_key,
        }


def unit_key(path: str) -> str:
    """A destination path in the one form two requests can be compared in.

    The same normalisation the queue applies to its locks, so "same batch" and
    "same lock" can never disagree about whether two paths are the same folder.
    """
    if not path:
        return ''
    cleaned = str(path).rstrip('/\\')
    if not os.path.isabs(cleaned):
        cleaned = os.path.abspath(cleaned)
    cleaned = os.path.normpath(cleaned)
    if os.name == 'nt':
        cleaned = cleaned.lower()
    return cleaned


def overlaps(path_a: str, path_b: str) -> bool:
    """Whether two destinations touch: the same folder, or one inside the other.

    A whole-series copy writes every season folder, so it collides with a copy
    of any one of them; two different seasons of the same show do not.
    """
    a, b = unit_key(path_a), unit_key(path_b)
    if not a or not b:
        return False
    if a == b:
        return True
    return a.startswith(b + os.sep) or b.startswith(a + os.sep)


def series_source_path(notification: Dict[str, Any]) -> str:
    """Where a series webhook's files live on the media server.

    The season path taken from the episode file's own location is the truth;
    rebuilding "Season NN" under the series path is the fallback, and the whole
    series path the last resort — the same order the old trigger used.
    """
    season_path = notification.get('season_path')
    series_path = notification.get('series_path')
    season_number = notification.get('season_number')
    if season_path:
        return season_path
    if series_path and season_number is not None:
        try:
            return f"{series_path.rstrip('/')}/Season {int(season_number):02d}"
        except (TypeError, ValueError):
            return series_path
    if series_path:
        return series_path
    raise IdentifyError('The webhook names neither a season folder nor a series folder')


def from_series_notification(notification: Dict[str, Any], path_service) -> Unit:
    """The season a Sonarr webhook is about."""
    media_type = notification.get('media_type') or 'tvshows'
    if media_type == 'series':
        media_type = 'tvshows'
    source = series_source_path(notification)
    try:
        dest = path_service.get_destination_path(source, media_type)
    except ValueError as error:
        raise IdentifyError(str(error)) from error
    folder_name, season_name = path_service.extract_folder_components(source, media_type)
    season_number = notification.get('season_number')
    try:
        season_number = int(season_number) if season_number is not None else None
    except (TypeError, ValueError):
        season_number = None
    ids = {k: notification.get(k) for k in ('tvdb_id', 'series_id', 'tmdb_id', 'imdb_id')
           if notification.get(k) not in (None, '')}
    return Unit(
        media_type=media_type, source_path=source, dest_path=dest,
        folder_name=folder_name, season_name=season_name,
        season_number=season_number,
        title=notification.get('series_title') or folder_name, ids=ids,
    )


def from_movie_notification(notification: Dict[str, Any], path_service) -> Unit:
    """The movie folder a Radarr webhook is about."""
    source = notification.get('folder_path') or ''
    if not source:
        raise IdentifyError('The webhook does not say which folder the movie is in')
    try:
        dest = path_service.get_destination_path(source, 'movies')
    except ValueError as error:
        raise IdentifyError(str(error)) from error
    folder_name = os.path.basename(source.rstrip('/'))
    title = notification.get('title') or folder_name
    year = notification.get('year')
    if year and str(year) not in title:
        title = f"{title} ({year})"
    ids = {k: notification.get(k) for k in ('tmdb_id', 'imdb_id')
           if notification.get(k) not in (None, '')}
    return Unit(media_type='movies', source_path=source, dest_path=dest,
                folder_name=folder_name, title=title, ids=ids)


def from_paths(media_type: str, source_path: str, dest_path: str, folder_name: str = '',
               season_name: Optional[str] = None, title: str = '',
               operation_type: str = 'folder', season_number: Optional[int] = None,
               allowed_roots: Optional[Sequence[str]] = None,
               ids: Optional[Dict[str, Any]] = None) -> Unit:
    """A unit named directly — a manual sync, Explore, a restart, a simulation.

    `allowed_roots`, when given, is the destination boundary: a path outside it
    is refused here rather than discovered by rsync.
    """
    if not source_path or not dest_path:
        raise IdentifyError('Both a source and a destination folder are needed')
    if allowed_roots:
        from security import PathTraversalError, assert_path_within_bounds
        try:
            assert_path_within_bounds(dest_path, list(allowed_roots))
        except PathTraversalError as error:
            raise IdentifyError('The destination is outside the configured library '
                                'folders') from error
    if season_number is None and season_name:
        digits = ''.join(ch for ch in season_name if ch.isdigit())
        season_number = int(digits) if digits else None
    folder = folder_name or os.path.basename(dest_path.rstrip('/'))
    if season_name and not folder_name:
        folder = os.path.basename(os.path.dirname(dest_path.rstrip('/')))
    return Unit(media_type=media_type or '', source_path=source_path, dest_path=dest_path,
                folder_name=folder, season_name=season_name,
                season_number=season_number, title=title or folder,
                operation_type=operation_type or 'folder', ids=dict(ids or {}))
