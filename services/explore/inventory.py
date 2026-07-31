#!/usr/bin/env python3
"""
Library inventory — both sides of the comparison as a flat list of files.

The remote side is read in ONE ssh round trip for an entire library. The old
browse code ran a listing for the library and then one more listing per show,
which is why status refresh had to be a separate button; a single `find` with
`-printf` returns every path, size and mtime in one go.

SECURITY: the remote command interpolates the library root, so it goes through
SSHManager._quote_remote_path via the ssh manager's own helpers. Record fields
are ordered so the *path comes last* and the record separator is NUL — a
filename containing a tab or a newline therefore cannot forge extra records or
shift fields. See the note on _RECORD_FORMAT.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .identity import (
    EpisodeKey,
    is_ancillary_file,
    is_media_file,
    parse_absolute_number,
    parse_episode_keys,
    season_number_from_folder,
    split_library_path,
)

# How deep a media file is expected to sit below the library root.
#   movies       Movie (2024)/movie.mkv                 -> 2
#   tv / anime   Show (2024)/Season 01/episode.mkv       -> 3
# Anything deeper is misplaced. This is not theoretical: the old single-episode
# download built its destination path with the filename included and then
# created it as a directory, stranding episodes at
# "Season 01/episode.mkv/episode.mkv" where no media server can see them.
EXPECTED_DEPTH = {'movies': 2, 'tvshows': 3, 'anime': 3}

# Fields are (kind, size, mtime, relative path) and records are NUL-separated.
# The path is last and split is bounded, so tabs inside a filename land in the
# path where they belong instead of shifting size/mtime.
_FILE_FORMAT = r'F\t%s\t%T@\t%P\0'
_DIR_FORMAT = r'D\t0\t0\t%P\0'


@dataclass
class FileEntry:
    """One file on one side of the library."""
    relative_path: str
    series: str
    season_folder: Optional[str]
    season: Optional[int]
    name: str
    size: int
    mtime: int
    is_media: bool
    is_ancillary: bool
    keys: Tuple[EpisodeKey, ...]
    absolute_number: Optional[int]
    misplaced: bool

    @property
    def depth(self) -> int:
        return len([p for p in self.relative_path.split('/') if p])


@dataclass
class Inventory:
    """Every file and directory under one library root, on one side."""
    media_type: str
    root: str
    side: str  # 'remote' | 'local'
    files: List[FileEntry] = field(default_factory=list)
    directories: List[str] = field(default_factory=list)
    exists: bool = True
    error: Optional[str] = None

    # ---- lookups the comparison needs -------------------------------------

    def series_names(self) -> List[str]:
        """Every series/movie folder, including ones holding no files yet."""
        names = {entry.series for entry in self.files if entry.series}
        for directory in self.directories:
            parts = [p for p in directory.split('/') if p]
            if len(parts) == 1:
                names.add(parts[0])
        return sorted(names)

    def season_folders(self, series: str) -> List[str]:
        """Season folder names inside a series, including empty ones."""
        names = set()
        for entry in self.files:
            if entry.series == series and entry.season_folder:
                names.add(entry.season_folder)
        prefix = f"{series}/"
        for directory in self.directories:
            if directory.startswith(prefix):
                remainder = directory[len(prefix):]
                if remainder and '/' not in remainder:
                    names.add(remainder)
        return sorted(names)

    def in_series(self, series: str) -> List[FileEntry]:
        return [e for e in self.files if e.series == series]

    def in_season(self, series: str, season_folder: Optional[str]) -> List[FileEntry]:
        return [
            e for e in self.files
            if e.series == series and e.season_folder == season_folder
        ]

    def media_count(self) -> int:
        return sum(1 for e in self.files if e.is_media)

    def total_bytes(self) -> int:
        return sum(e.size for e in self.files if e.is_media)


def build_entry(media_type: str, relative_path: str, size: int, mtime: int) -> FileEntry:
    """Turn one raw listing row into a FileEntry, parsing identity as we go."""
    relative_path = relative_path.replace('\\', '/').strip('/')
    series, season_path, name = split_library_path(relative_path)

    # A file sitting deeper than expected still belongs to the season it is
    # buried under: "Season 01/ep.mkv/ep.mkv" is Season 01's problem, and
    # grouping it anywhere else would hide it. Group on the FIRST segment and
    # let `misplaced` carry the fact that it is too deep. Movies have no season
    # layer at all, so everything under the movie folder is that movie's.
    if media_type == 'movies':
        season_folder = None
        season = None
    else:
        season_folder = season_path.split('/')[0] if season_path else None
        season = season_number_from_folder(season_folder)

    media = is_media_file(name)
    depth = len([p for p in relative_path.split('/') if p])
    expected = EXPECTED_DEPTH.get(media_type, 3)

    return FileEntry(
        relative_path=relative_path,
        series=series,
        season_folder=season_folder,
        season=season,
        name=name,
        size=size,
        mtime=mtime,
        is_media=media,
        is_ancillary=is_ancillary_file(name),
        keys=parse_episode_keys(name, season) if media else (),
        absolute_number=parse_absolute_number(name) if media else None,
        misplaced=media and depth != expected,
    )


def _parse_records(payload: str, media_type: str) -> Tuple[List[FileEntry], List[str]]:
    """Parse the NUL-separated find output into files and directories."""
    files: List[FileEntry] = []
    directories: List[str] = []

    for record in payload.split('\0'):
        if not record:
            continue
        parts = record.split('\t', 3)
        if len(parts) != 4:
            continue
        kind, raw_size, raw_mtime, relative_path = parts
        if not relative_path:
            continue
        if kind == 'D':
            directories.append(relative_path.replace('\\', '/').strip('/'))
            continue
        if kind != 'F':
            continue
        try:
            size = int(raw_size)
        except ValueError:
            size = 0
        try:
            # %T@ is a float ("1699999999.1234567890")
            mtime = int(float(raw_mtime))
        except ValueError:
            mtime = 0
        files.append(build_entry(media_type, relative_path, size, mtime))

    return files, directories


class RemoteInventory:
    """Reads a whole remote library in a single ssh command."""

    def __init__(self, ssh_manager):
        self.ssh = ssh_manager

    def read(self, media_type: str, root: str) -> Inventory:
        if not self.ssh or not getattr(self.ssh, 'connected', False):
            return Inventory(
                media_type=media_type, root=root, side='remote',
                exists=False, error='No remote browse session',
            )

        # SECURITY: the root is shell-quoted by the ssh manager's helper.
        quoted = self.ssh._quote_remote_path(root)
        command = (
            f"find {quoted} -mindepth 1 "
            rf"\( -type d -printf '{_DIR_FORMAT}' -o -type f -printf '{_FILE_FORMAT}' \)"
        )

        exit_code, output, error = self.ssh.execute_command(command)
        if exit_code != 0:
            return Inventory(
                media_type=media_type, root=root, side='remote',
                exists=False,
                error=error or f"Remote listing failed (exit {exit_code})",
            )

        files, directories = _parse_records(output, media_type)
        return Inventory(
            media_type=media_type, root=root, side='remote',
            files=files, directories=directories,
        )


class LocalInventory:
    """Reads a whole local library from disk."""

    def read(self, media_type: str, root: str) -> Inventory:
        if not root:
            return Inventory(
                media_type=media_type, root=root or '', side='local',
                exists=False, error='Local library path is not configured',
            )
        if not os.path.isdir(root):
            return Inventory(
                media_type=media_type, root=root, side='local',
                exists=False, error='Local library path does not exist',
            )

        files: List[FileEntry] = []
        directories: List[str] = []

        for dirpath, dirnames, filenames in os.walk(root):
            relative_dir = os.path.relpath(dirpath, root)
            if relative_dir != '.':
                directories.append(relative_dir.replace(os.sep, '/'))
            for filename in filenames:
                relative_path = (
                    filename if relative_dir == '.'
                    else os.path.join(relative_dir, filename)
                )
                try:
                    stat = os.stat(os.path.join(dirpath, filename))
                    size, mtime = stat.st_size, int(stat.st_mtime)
                except OSError:
                    size, mtime = 0, 0
                files.append(
                    build_entry(media_type, relative_path.replace(os.sep, '/'), size, mtime)
                )

        return Inventory(
            media_type=media_type, root=root, side='local',
            files=files, directories=directories,
        )


class StaticInventory:
    """
    Inventory source backed by a literal list — used by the tests so the
    comparison and planner can be exercised without ssh or a real disk.

    Rows are (relative_path, size, mtime); directories are optional.
    """

    def __init__(self, rows: Iterable[Tuple[str, int, int]],
                 directories: Optional[Iterable[str]] = None,
                 side: str = 'remote', exists: bool = True,
                 error: Optional[str] = None):
        self.rows = list(rows)
        self.directories = list(directories or [])
        self.side = side
        self.exists = exists
        self.error = error

    def read(self, media_type: str, root: str) -> Inventory:
        return Inventory(
            media_type=media_type, root=root, side=self.side,
            files=[build_entry(media_type, p, s, m) for p, s, m in self.rows],
            directories=self.directories,
            exists=self.exists, error=self.error,
        )
