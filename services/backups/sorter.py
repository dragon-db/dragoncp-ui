#!/usr/bin/env python3
"""
rsync's flat staging output -> the identity tree.

rsync writes displaced files at their destination-relative path into one
staging folder per transfer. That is the shape rsync gives us and it is not
worth fighting; this runs afterwards and files each one under the slot it
belongs to.

Three properties make this safe enough to run unattended after every transfer:

  * it only ever touches files that are ALREADY out of the library, so a
    failure here cannot damage media,
  * it is a rename within one filesystem — instant regardless of file size,
    because the backup area and the library are separate devices but the
    staging folder and the tree are not,
  * it is idempotent. If it dies part-way the staging folder still holds
    whatever is left, and the next run finishes the job.

Anything it cannot identify goes to `_unsorted/` with its original relative
path rather than being dropped or guessed at.
"""

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from security import PathTraversalError

from .identity import (
    SlotIdentity,
    identify,
    is_media,
    library_for_media_type,
    new_capture_id,
    parse_capture_id,
    title_of,
)
from .layout import BackupLayout, BackupPathNotConfigured, utc_now

# Files rsync leaves behind that are not displaced media.
_PARTIAL_DIR = '.rsync-partial'


@dataclass
class SortedCapture:
    """One capture the sorter produced, ready to be indexed."""
    capture_id: str
    identity: Optional[SlotIdentity]
    kind: str                       # 'slot' | 'extras' | 'unsorted'
    library: str
    title: str
    path: str
    captured_at: datetime
    source_transfer_id: str
    reason: str
    files: List[Dict] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(f.get('file_size', 0) for f in self.files)


@dataclass
class SortResult:
    captures: List[SortedCapture] = field(default_factory=list)
    unsorted_count: int = 0
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(len(c.files) for c in self.captures)

    @property
    def total_size(self) -> int:
        return sum(c.total_size for c in self.captures)


class BackupSorter:
    """Turns one transfer's staging folder into captures in the tree."""

    def __init__(self, config, layout: Optional[BackupLayout] = None):
        self.config = config
        self.layout = layout or BackupLayout(config)

    # ---- entry point ------------------------------------------------------

    def sort_transfer(self, transfer: Dict, reason: str = 'sync_replace',
                      moment: Optional[datetime] = None) -> SortResult:
        """
        Sort everything a transfer displaced.

        `transfer` needs `transfer_id`, `media_type` and `dest_path`. The
        destination is what turns a staging-relative path back into a
        library-relative one, which is what identity is derived from.
        """
        result = SortResult()
        transfer_id = transfer.get('transfer_id') or ''
        if not transfer_id:
            result.errors.append('Transfer has no id; nothing sorted')
            return result

        try:
            staging = self.layout.staging_dir(transfer_id)
        except BackupPathNotConfigured as error:
            result.errors.append(str(error))
            return result

        if not os.path.isdir(staging):
            return result

        library = library_for_media_type(transfer.get('media_type'))
        dest_path = transfer.get('dest_path') or ''
        dest_relative = self._destination_relative(library, dest_path)

        capture_id = str(new_capture_id(transfer_id, moment))
        groups, extras, unknown = self._group(staging, library, dest_relative, dest_path)

        for identity, entries in groups.items():
            capture = self._write_group(
                identity, entries, capture_id, transfer_id, reason, staging,
            )
            if capture:
                result.captures.append(capture)

        for title, entries in extras.items():
            capture = self._write_extras(
                library or '', title, entries, capture_id, transfer_id, reason,
            )
            if capture:
                result.captures.append(capture)

        if unknown:
            capture = self._write_unsorted(
                unknown, capture_id, transfer_id, reason, library,
            )
            if capture:
                result.captures.append(capture)
                result.unsorted_count = len(capture.files)

        self._cleanup_staging(staging, result)
        return result

    # ---- grouping ---------------------------------------------------------

    def _destination_relative(self, library: Optional[str], dest_path: str) -> str:
        """
        Where the transfer's destination sits inside its library root.

        A season transfer lands on "<base>/Example Show/Season 01" and a series
        transfer on "<base>/Example Show". Prefixing this onto each staging
        path reconstructs the library-relative path the file used to have,
        which is what identity needs. Without it a season transfer's files look
        like bare filenames with no series attached.
        """
        if not library or not dest_path:
            return ''
        media_type = {'movies': 'movies', 'shows': 'tvshows', 'anime': 'anime'}[library]
        base = self.config.get({
            'movies': 'MOVIE_DEST_PATH',
            'tvshows': 'TVSHOW_DEST_PATH',
            'anime': 'ANIME_DEST_PATH',
        }[media_type])
        if not base:
            return ''
        try:
            relative = os.path.relpath(os.path.realpath(dest_path), os.path.realpath(base))
        except ValueError:
            return ''
        if relative.startswith('..') or relative == '.':
            return ''
        return relative.replace(os.sep, '/')

    def _group(self, staging: str, library: Optional[str], dest_relative: str,
               dest_path: str) -> Tuple[Dict[SlotIdentity, List[Dict]],
                                        Dict[str, List[Dict]], List[Dict]]:
        """
        Walk the staging folder and bucket every file by the slot it belongs to.

        Sidecars are identified the same way media files are — a subtitle named
        "Example Show - S01E01 - Title.srt" carries the same episode code as the
        video, so it lands in the same capture without any pairing heuristics.

        Three buckets come out: slots, title-level extras (a season poster
        belongs to a series but to no episode), and files with no identity at
        all, which go to `_unsorted` rather than being guessed at.
        """
        groups: Dict[SlotIdentity, List[Dict]] = {}
        extras: Dict[str, List[Dict]] = {}
        unknown: List[Dict] = []

        for root, dirs, filenames in os.walk(staging):
            # rsync's partial directory holds in-flight fragments of files that
            # are still arriving, not displaced copies. Indexing them as
            # backups was listing half-downloads as recoverable media.
            dirs[:] = [d for d in dirs if d != _PARTIAL_DIR]

            for filename in filenames:
                full = os.path.join(root, filename)
                if os.path.islink(full):
                    continue
                staging_relative = os.path.relpath(full, staging).replace(os.sep, '/')
                entry = self._describe(full, staging_relative, dest_path)

                library_relative = (
                    f"{dest_relative}/{staging_relative}" if dest_relative else staging_relative
                )
                identity = identify(library, library_relative) if library else None
                if identity is not None:
                    groups.setdefault(identity, []).append(entry)
                    continue

                title = title_of(library, library_relative) if library else None
                if title:
                    extras.setdefault(title, []).append(entry)
                    continue

                unknown.append(entry)

        return groups, extras, unknown

    @staticmethod
    def _describe(full_path: str, staging_relative: str, dest_path: str) -> Dict:
        try:
            stat = os.stat(full_path)
            size, mtime = stat.st_size, int(stat.st_mtime)
        except OSError:
            size, mtime = 0, 0
        return {
            'source': full_path,
            'staging_relative': staging_relative,
            'filename': os.path.basename(staging_relative),
            'original_path': (
                os.path.join(dest_path, staging_relative).replace(os.sep, '/')
                if dest_path else ''
            ),
            'file_size': size,
            'modified_time': mtime,
            'is_media': is_media(os.path.basename(staging_relative)),
        }

    # ---- writing ----------------------------------------------------------

    def _write_group(self, identity: SlotIdentity, entries: List[Dict],
                     capture_id: str, transfer_id: str, reason: str,
                     staging: str) -> Optional[SortedCapture]:
        del staging  # kept for call-site symmetry with the unsorted path
        try:
            parent = self.layout.slot_dir(identity)
        except (ValueError, OSError, PathTraversalError) as error:
            # Cannot place it — treat as unsorted rather than losing it.
            print(f"⚠️  Backup sorter could not place {identity.display}: {error}")
            return self._write_unsorted(
                entries, capture_id, transfer_id, reason, identity.library,
            )

        os.makedirs(parent, exist_ok=True)
        capture_path, actual_id = self.layout.unique_capture_dir(parent, capture_id)
        moved = self._move_all(entries, capture_path, flatten=True)
        if not moved:
            return None

        return SortedCapture(
            capture_id=actual_id,
            identity=identity,
            kind='slot',
            library=identity.library,
            title=identity.title,
            path=capture_path,
            captured_at=self._captured_at(actual_id),
            source_transfer_id=transfer_id,
            reason=reason,
            files=moved,
        )

    def _write_extras(self, library: str, title: str, entries: List[Dict],
                      capture_id: str, transfer_id: str, reason: str
                      ) -> Optional[SortedCapture]:
        try:
            parent = os.path.dirname(self.layout.extras_dir(library, title, capture_id))
        except (OSError, ValueError, PathTraversalError) as error:
            print(f"⚠️  Backup sorter could not place extras for {title}: {error}")
            return self._write_unsorted(entries, capture_id, transfer_id, reason, library)

        os.makedirs(parent, exist_ok=True)
        capture_path, actual_id = self.layout.unique_capture_dir(parent, capture_id)
        moved = self._move_all(entries, capture_path, flatten=False)
        if not moved:
            return None

        return SortedCapture(
            capture_id=actual_id,
            identity=None,
            kind='extras',
            library=library,
            title=title,
            path=capture_path,
            captured_at=self._captured_at(actual_id),
            source_transfer_id=transfer_id,
            reason=reason,
            files=moved,
        )

    def _write_unsorted(self, entries: List[Dict], capture_id: str, transfer_id: str,
                        reason: str, library: Optional[str]) -> Optional[SortedCapture]:
        try:
            parent = self.layout.unsorted_root()
        except (OSError, ValueError, PathTraversalError) as error:
            print(f"⚠️  Backup sorter could not write the unsorted bucket: {error}")
            return None

        os.makedirs(parent, exist_ok=True)
        capture_path, actual_id = self.layout.unique_capture_dir(parent, capture_id)
        # Unsorted files keep their original relative path, so they are
        # recoverable by hand and can be re-sorted once the parser improves.
        moved = self._move_all(entries, capture_path, flatten=False)
        if not moved:
            return None

        return SortedCapture(
            capture_id=actual_id,
            identity=None,
            kind='unsorted',
            library=library or '',
            title='',
            path=capture_path,
            captured_at=self._captured_at(actual_id),
            source_transfer_id=transfer_id,
            reason=reason,
            files=moved,
        )

    def _move_all(self, entries: List[Dict], capture_path: str,
                  flatten: bool) -> List[Dict]:
        """
        Move files into a capture folder.

        `flatten` puts every file directly in the capture (a slot's files all
        belong to one episode, so their directory nesting carries no
        information). The unsorted bucket keeps nesting, because there the path
        is the only clue left about what the file was.
        """
        moved: List[Dict] = []
        for entry in entries:
            relative = (
                entry['filename'] if flatten else entry['staging_relative']
            )
            target = os.path.join(capture_path, relative)
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                if os.path.exists(target):
                    target = self._deduplicate(target)
                    relative = os.path.relpath(target, capture_path).replace(os.sep, '/')
                # Same filesystem as the staging folder, so this is a rename.
                shutil.move(entry['source'], target)
            except OSError as error:
                print(f"⚠️  Backup sorter could not move {entry['source']}: {error}")
                continue
            moved.append({
                'relative_path': relative.replace(os.sep, '/'),
                'original_path': entry['original_path'],
                'file_size': entry['file_size'],
                'modified_time': entry['modified_time'],
                'is_media': entry['is_media'],
            })
        if not moved and os.path.isdir(capture_path):
            try:
                os.rmdir(capture_path)
            except OSError:
                pass
        return moved

    @staticmethod
    def _deduplicate(target: str) -> str:
        """Two files with one name inside one capture — keep both."""
        stem, extension = os.path.splitext(target)
        counter = 2
        while os.path.exists(f"{stem} ({counter}){extension}"):
            counter += 1
        return f"{stem} ({counter}){extension}"

    @staticmethod
    def _captured_at(capture_id: str) -> datetime:
        parsed = parse_capture_id(capture_id)
        return parsed[0] if parsed else utc_now()

    def _cleanup_staging(self, staging: str, result: SortResult) -> None:
        """
        Remove the staging folder once it holds nothing worth keeping.

        Anything still in `.rsync-partial` is an in-flight fragment, so its
        presence must not keep the folder alive forever — but a file left
        directly in staging means the sort did not finish, and that folder is
        deliberately preserved for the next run to pick up.
        """
        if not os.path.isdir(staging):
            return

        leftovers = []
        for root, dirs, files in os.walk(staging):
            if os.path.basename(root) == _PARTIAL_DIR:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d != _PARTIAL_DIR]
            leftovers.extend(os.path.join(root, f) for f in files)

        if leftovers:
            result.skipped.extend(
                os.path.relpath(p, staging) for p in leftovers
            )
            return

        try:
            shutil.rmtree(staging)
        except OSError as error:
            result.errors.append(f"Could not remove staging folder: {error}")
