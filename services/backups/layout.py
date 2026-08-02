#!/usr/bin/env python3
"""
Where a slot lives on disk, and how to read it back.

    <BACKUP_PATH>/
      movies/
        Example Film (2024)/
          20260730T142205Z__t1a2b3/
            Example Film (2024) [Bluray-1080p].mkv
            Example Film (2024).nfo
      shows/
        Example Show/
          Season 01/
            S01E01/
              20260730T142205Z__t1a2b3/
                Example Show - S01E01 - An Episode [WEBDL-1080p].mkv
              20260804T091033Z__t9f8e7/
                Example Show - S01E01 - An Episode [HDTV-720p].mkv
      anime/
        ...
      _unsorted/
        20260730T142205Z__t1a2b3/
          <original path within the transfer's destination>
      .staging/
        <transfer id>/          <- rsync's --backup-dir writes here

Everything needed to rebuild the index is in the path: library, title, season,
episode, capture time and provenance. That is deliberate. The database is an
index over this tree, not the other way round, so it can always be regenerated
and cannot drift for long.

A capture is a FOLDER rather than a file so an episode's subtitles and metadata
stay welded to the copy they belong to.

SECURITY: every path built here is asserted to resolve inside BACKUP_PATH
before it is returned. Title, season and slot segments are validated as single
path components first, so a crafted library folder name cannot walk out of the
tree. See security.py.
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, List, Optional, Tuple

from security import (
    PathTraversalError,
    assert_path_within_bounds,
    validate_path_component,
)

from .identity import (
    LIBRARIES,
    SlotIdentity,
    parse_capture_id,
    season_folder_name,
)

# Top-level names inside BACKUP_PATH that are not libraries.
STAGING_DIR = '.staging'
UNSORTED_DIR = '_unsorted'
EXTRAS_DIR = '_extras'

# Directories the tree scan must never descend into or treat as content.
RESERVED_TOP_LEVEL = frozenset({STAGING_DIR, UNSORTED_DIR})

# Legacy plumbing that lived directly under BACKUP_PATH before this rework.
LEGACY_INTERNAL = frozenset({'.explore-plans', '.explore-dryrun'})

_SLOT_FOLDER_RE = re.compile(r'^S(\d{2,4})E(\d{2,4})$')


class BackupPathNotConfigured(RuntimeError):
    """
    Raised when BACKUP_PATH is unset and something wants to write a backup.

    This is the fix for a defect that made backups look like they worked and be
    unrecoverable: writing used to fall back to a temporary directory the OS
    may clear, while restore refused outright to read from anywhere but a
    configured BACKUP_PATH. The two halves now agree, and they agree on
    refusing rather than on a fallback nobody can restore from.
    """


@dataclass(frozen=True)
class CaptureLocation:
    """A capture found in the tree, described entirely by its path."""
    capture_id: str
    captured_at: datetime
    source_ref: str
    library: str
    title: str
    season: Optional[int]
    episode: Optional[int]
    path: str                 # absolute
    relative_path: str        # relative to BACKUP_PATH
    kind: str                 # 'slot' | 'extras' | 'unsorted'

    @property
    def slot_key(self) -> Optional[str]:
        if self.kind != 'slot':
            return None
        identity = SlotIdentity(
            library=self.library,
            title=self.title,
            season=self.season,
            episode=self.episode,
        )
        return identity.slot_key


class BackupLayout:
    """Builds and reads paths inside the backup tree."""

    def __init__(self, config):
        self.config = config

    # ---- the base ---------------------------------------------------------

    def base(self, for_writing: bool = True) -> str:
        """
        The configured BACKUP_PATH.

        Fails closed when unset. There is deliberately no fallback: the old
        `/tmp/backup` default meant every sync quietly wrote displaced media
        somewhere the OS may clear and restore would not read.
        """
        value = (self.config.get('BACKUP_PATH') or '').strip()
        if not value:
            raise BackupPathNotConfigured(
                'BACKUP_PATH is not configured. Set it before running a transfer '
                'that can displace files — writing backups somewhere restore '
                'cannot read them is worse than not backing up at all.'
            )
        if for_writing:
            os.makedirs(value, exist_ok=True)
        return value

    def base_or_none(self, for_writing: bool = False) -> Optional[str]:
        """The base, or None when it is unset. For read paths that may skip."""
        try:
            return self.base(for_writing=for_writing)
        except BackupPathNotConfigured:
            return None

    def is_configured(self) -> bool:
        return bool((self.config.get('BACKUP_PATH') or '').strip())

    def _within(self, path: str) -> str:
        """Assert a constructed path stays inside BACKUP_PATH."""
        return assert_path_within_bounds(path, [self.base(for_writing=False)])

    # ---- staging ----------------------------------------------------------

    def staging_dir(self, transfer_id: str) -> str:
        """
        Where rsync's --backup-dir points for one transfer.

        Kept under a dot-prefixed directory so it never appears as content in
        the tree, and keyed on the transfer id alone so a resumed or restarted
        run keeps writing into the folder its first attempt used.
        """
        if not validate_path_component(transfer_id):
            raise PathTraversalError(f"Unsafe transfer id for staging: {transfer_id!r}")
        path = os.path.join(self.base(), STAGING_DIR, transfer_id)
        return self._within(path)

    def staging_root(self) -> str:
        return self._within(os.path.join(self.base(), STAGING_DIR))

    # ---- slots and captures ----------------------------------------------

    def slot_dir(self, identity: SlotIdentity) -> str:
        """The folder holding every capture of one movie or episode."""
        segments: List[str] = [identity.library, identity.title]

        if not identity.is_movie:
            season = identity.season_folder
            slot = identity.slot_folder
            if not season or not slot:
                raise ValueError(
                    f"Cannot place {identity.display!r}: it carries no season/episode"
                )
            segments.extend([season, slot])

        for segment in segments:
            if not validate_path_component(segment):
                raise PathTraversalError(f"Unsafe path segment for a slot: {segment!r}")

        return self._within(os.path.join(self.base(), *segments))

    def capture_dir(self, identity: SlotIdentity, capture_id: str) -> str:
        """One capture inside a slot."""
        if not validate_path_component(capture_id):
            raise PathTraversalError(f"Unsafe capture id: {capture_id!r}")
        return self._within(os.path.join(self.slot_dir(identity), capture_id))

    def extras_dir(self, library: str, title: str, capture_id: str) -> str:
        """
        Files that belong to a title but to no single episode — series artwork,
        season posters. Kept beside the seasons rather than in `_unsorted`, so
        they stay findable, but never treated as a slot occupant.
        """
        for segment in (library, title, capture_id):
            if not validate_path_component(segment):
                raise PathTraversalError(f"Unsafe path segment for extras: {segment!r}")
        path = os.path.join(self.base(), library, title, EXTRAS_DIR, capture_id)
        return self._within(path)

    def unsorted_root(self) -> str:
        return self._within(os.path.join(self.base(), UNSORTED_DIR))

    def unsorted_dir(self, capture_id: str) -> str:
        """
        Anything the parser could not identify.

        Nothing is ever discarded for being unrecognised. The file keeps the
        relative path it had, so it is recoverable by hand today and can be
        re-sorted later when the parser improves.
        """
        if not validate_path_component(capture_id):
            raise PathTraversalError(f"Unsafe capture id: {capture_id!r}")
        return self._within(os.path.join(self.base(), UNSORTED_DIR, capture_id))

    def relative(self, path: str) -> str:
        """A path inside the tree, expressed relative to BACKUP_PATH."""
        return os.path.relpath(path, self.base(for_writing=False)).replace(os.sep, '/')

    def absolute(self, relative_path: str) -> str:
        """The inverse of `relative`, bounds-checked."""
        path = os.path.join(self.base(for_writing=False), relative_path)
        return self._within(path)

    def unique_capture_dir(self, parent: str, capture_id: str) -> Tuple[str, str]:
        """
        A capture folder that does not already exist.

        Two captures of one slot in the same second, from the same source, would
        otherwise collide and merge into each other. Returns (path, capture_id).
        """
        candidate = capture_id
        suffix = 1
        while os.path.exists(os.path.join(parent, candidate)):
            suffix += 1
            candidate = f"{capture_id}__{suffix}"
        return os.path.join(parent, candidate), candidate

    # ---- reading the tree back -------------------------------------------

    def scan(self) -> Iterator[CaptureLocation]:
        """
        Every capture in the tree, found by walking it.

        This is what makes the index rebuildable: nothing here consults the
        database, and nothing needs a matching transfer record. The previous
        recovery action reconstructed a transfer id out of a folder name and
        gave up when it did not resolve, which is why webhook-created backups
        could be imported but never restored.
        """
        base = self.base_or_none()
        if not base or not os.path.isdir(base):
            return

        for library in LIBRARIES:
            library_root = os.path.join(base, library)
            if not os.path.isdir(library_root):
                continue
            yield from self._scan_library(base, library, library_root)

        unsorted_root = os.path.join(base, UNSORTED_DIR)
        if os.path.isdir(unsorted_root):
            for name in sorted(os.listdir(unsorted_root)):
                path = os.path.join(unsorted_root, name)
                parsed = parse_capture_id(name)
                if not os.path.isdir(path) or not parsed:
                    continue
                captured_at, source_ref = parsed
                yield CaptureLocation(
                    capture_id=name, captured_at=captured_at, source_ref=source_ref,
                    library='', title='', season=None, episode=None,
                    path=path, relative_path=self.relative(path), kind='unsorted',
                )

    def _scan_library(self, base: str, library: str, library_root: str) -> Iterator[CaptureLocation]:
        for title in sorted(os.listdir(library_root)):
            title_path = os.path.join(library_root, title)
            if not os.path.isdir(title_path):
                continue

            if library == 'movies':
                # movies/<Title>/<capture>/
                yield from self._captures_in(
                    title_path, library, title, None, None, 'slot',
                )
                continue

            for child in sorted(os.listdir(title_path)):
                child_path = os.path.join(title_path, child)
                if not os.path.isdir(child_path):
                    continue

                if child == EXTRAS_DIR:
                    yield from self._captures_in(
                        child_path, library, title, None, None, 'extras',
                    )
                    continue

                # The season folder is navigation only. Season and episode are
                # read from the slot code, which is padded and canonical — the
                # folder name is not, and trusting it is what splits one
                # episode's history across "Season 1" and "Season 01".
                for slot in sorted(os.listdir(child_path)):
                    slot_path = os.path.join(child_path, slot)
                    if not os.path.isdir(slot_path):
                        continue
                    match = _SLOT_FOLDER_RE.match(slot)
                    if not match:
                        continue
                    yield from self._captures_in(
                        slot_path, library, title,
                        int(match.group(1)), int(match.group(2)), 'slot',
                    )

    def _captures_in(self, parent: str, library: str, title: str,
                     season: Optional[int], episode: Optional[int],
                     kind: str) -> Iterator[CaptureLocation]:
        for name in sorted(os.listdir(parent)):
            path = os.path.join(parent, name)
            if not os.path.isdir(path):
                continue
            parsed = parse_capture_id(name)
            if not parsed:
                continue
            captured_at, source_ref = parsed
            yield CaptureLocation(
                capture_id=name, captured_at=captured_at, source_ref=source_ref,
                library=library, title=title, season=season, episode=episode,
                path=path, relative_path=self.relative(path), kind=kind,
            )

    # ---- housekeeping -----------------------------------------------------

    def legacy_folders(self) -> List[str]:
        """
        Top-level folders that are neither libraries nor internal — the old
        per-transfer shape, which migration adopts and then removes.
        """
        base = self.base_or_none()
        if not base or not os.path.isdir(base):
            return []
        found = []
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if not os.path.isdir(path):
                continue
            if name in LIBRARIES or name in RESERVED_TOP_LEVEL or name in LEGACY_INTERNAL:
                continue
            # Anything dot-prefixed is rsync's or ours, never a backup folder.
            # The live disk has a stray `.rsync-partial` at the top level, and
            # treating that as media to migrate would have moved fragments of
            # half-finished downloads into the tree as if they were backups.
            if name.startswith('.'):
                continue
            found.append(path)
        return found

    @staticmethod
    def is_empty_tree(path: str) -> bool:
        """True when a directory holds no files at any depth."""
        for _root, _dirs, files in os.walk(path):
            if files:
                return False
        return True

    def prune_empty_dirs(self, start: str) -> None:
        """
        Remove now-childless directories above a path, stopping at the base.

        Called after a capture is deleted so an emptied slot, season and title
        do not linger as a tree of empty folders.

        `start` is normally the capture folder that was just removed, so it does
        not exist any more. Walking up to the first directory that DOES exist
        before pruning is the whole point — starting at a missing path and
        giving up on the first error is what left the empty tree behind.
        """
        try:
            base = os.path.realpath(self.base(for_writing=False))
        except BackupPathNotConfigured:
            return

        current = os.path.abspath(start)
        while current.startswith(base + os.sep) and not os.path.isdir(current):
            current = os.path.dirname(current)

        while current.startswith(base + os.sep) and current != base:
            try:
                if os.listdir(current):
                    return
                os.rmdir(current)
            except OSError:
                return
            current = os.path.dirname(current)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
