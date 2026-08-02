#!/usr/bin/env python3
"""
Restore — promote an old version of a slot back to current.

The sequence is chosen so nothing is destroyed before its replacement is safely
written:

    1. capture the file currently occupying the slot into a NEW capture
    2. write the restored file to the target path under a temporary name,
       then rename it into place
    3. remove the previous occupant, only if its path differs from the target
    4. index the new capture

Step 1 completing before step 3 is the whole safety argument. The previous
implementation deleted first and copied after, logged delete failures and
carried on, and compared by size only — so a same-size file at the destination
was silently left alone while the log reported it as copied.

The library and the backup area are separate devices, so the copies here move
real bytes. That is why a restore is a queued transfer with progress rather
than something that blocks a web request, and why the rename in step 2 is done
within the library disk where it is atomic.
"""

import os
import shutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from env_flags import test_mode_enabled
from security import PathTraversalError, assert_path_within_bounds, validate_relative_path

from .identity import SlotIdentity, media_type_for_library, new_capture_id
from .layout import BackupLayout, utc_now


@dataclass
class RestoreOperation:
    """One file's worth of restore, fully resolved before anything runs."""
    relative_path: str            # inside the capture
    source: str                   # absolute, in the backup tree
    target: str                   # absolute, in the library
    replaces: Optional[str]       # the current occupant, if there is one
    replaces_size: int
    file_size: int
    is_media: bool
    display: str

    def as_dict(self) -> Dict:
        return {
            'relative_path': self.relative_path,
            'target': self.target,
            'replaces': self.replaces,
            'replaces_size': self.replaces_size,
            'file_size': self.file_size,
            'is_media': self.is_media,
            'display': self.display,
        }


@dataclass
class RestorePlan:
    capture_id: str
    slot_display: str
    library: str
    target_dir: str
    operations: List[RestoreOperation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    blocked: Optional[str] = None

    @property
    def total_size(self) -> int:
        return sum(op.file_size for op in self.operations)

    @property
    def replaces_count(self) -> int:
        return sum(1 for op in self.operations if op.replaces)

    def as_dict(self) -> Dict:
        return {
            'capture_id': self.capture_id,
            'slot_display': self.slot_display,
            'library': self.library,
            'target_dir': self.target_dir,
            'operations': [op.as_dict() for op in self.operations],
            'warnings': self.warnings,
            'blocked': self.blocked,
            'total_size': self.total_size,
            'replaces_count': self.replaces_count,
        }


class RestorePlanner:
    """
    Works out exactly what a restore would do, without doing any of it.

    The same function backs the preview and the run, so what is approved is
    what happens.
    """

    def __init__(self, config, layout: BackupLayout, capture_model,
                 locator: Optional[Callable] = None):
        self.config = config
        self.layout = layout
        self.captures = capture_model
        # Injected so tests can supply a library without a disk. Defaults to
        # the real lookup below.
        self._locate = locator or self._locate_in_library

    # ---- destination ------------------------------------------------------

    def library_root(self, library: str) -> Optional[str]:
        media_type = media_type_for_library(library)
        key = {
            'movies': 'MOVIE_DEST_PATH',
            'tvshows': 'TVSHOW_DEST_PATH',
            'anime': 'ANIME_DEST_PATH',
        }.get(media_type or '')
        if not key:
            return None
        return (self.config.get(key) or '').strip() or None

    def target_directory(self, capture: Dict) -> Optional[str]:
        """
        Where a capture's files belong in the library.

        Derived from the slot, not from a destination recorded months ago. A
        reindexed capture therefore restores correctly even though no transfer
        record exists for it — the case the old implementation failed outright.
        """
        root = self.library_root(capture.get('library') or '')
        if not root or not capture.get('title'):
            return None

        if capture['library'] == 'movies':
            return os.path.join(root, capture['title'])

        season = capture.get('season_number')
        if season is None:
            return os.path.join(root, capture['title'])
        folder = 'Specials' if season == 0 else f"Season {season:02d}"
        return os.path.join(root, capture['title'], folder)

    # ---- the plan ---------------------------------------------------------

    def plan(self, capture_id: str, files: Optional[List[str]] = None) -> RestorePlan:
        capture = self.captures.get(capture_id)
        if not capture:
            return RestorePlan(
                capture_id=capture_id, slot_display='', library='', target_dir='',
                blocked='This backup is no longer in the index',
            )

        display = self._display(capture)
        library = capture.get('library') or ''
        plan = RestorePlan(
            capture_id=capture_id, slot_display=display,
            library=library, target_dir='',
        )

        if capture.get('kind') != 'slot':
            plan.blocked = (
                'This file was never identified, so there is nowhere to put it back. '
                'Recover it by hand from the backup folder.'
            )
            return plan

        if capture.get('status') != 'present':
            plan.blocked = 'The files for this backup have been removed from disk'
            return plan

        target_dir = self.target_directory(capture)
        if not target_dir:
            plan.blocked = (
                'No library folder is configured for this media type, '
                'so there is nowhere to restore to'
            )
            return plan
        plan.target_dir = target_dir

        try:
            capture_path = self.layout.absolute(capture['capture_path'])
        except Exception:  # noqa: BLE001 - traversal, or no backup path configured
            plan.blocked = 'The backup folder is outside the configured backup path'
            return plan

        if not os.path.isdir(capture_path):
            plan.blocked = 'The backup folder is missing from disk'
            return plan

        selected = self._selection(files)
        occupants = self._locate(capture, target_dir)

        for row in self.captures.files(capture_id):
            relative = row['relative_path']
            if selected is not None and relative not in selected:
                continue

            source = os.path.join(capture_path, relative)
            if not os.path.isfile(source):
                plan.warnings.append(f"Missing from the backup folder: {relative}")
                continue

            filename = os.path.basename(relative)
            target = os.path.join(target_dir, filename)
            replaces, replaces_size = self._match_occupant(
                occupants, filename, bool(row['is_media']), target,
            )

            plan.operations.append(RestoreOperation(
                relative_path=relative,
                source=source,
                target=target,
                replaces=replaces,
                replaces_size=replaces_size,
                file_size=row['file_size'],
                is_media=bool(row['is_media']),
                display=display,
            ))

        if not plan.operations and not plan.blocked:
            plan.blocked = 'Nothing to restore for the selected files'
        return plan

    @staticmethod
    def _selection(files: Optional[List[str]]) -> Optional[set]:
        if files is None:
            return None
        cleaned = set()
        for entry in files:
            if not isinstance(entry, str) or not validate_relative_path(entry):
                continue
            cleaned.add(entry.strip().lstrip('/').replace('\\', '/'))
        return cleaned

    @staticmethod
    def _display(capture: Dict) -> str:
        identity = SlotIdentity(
            library=capture.get('library') or '',
            title=capture.get('title') or '',
            season=capture.get('season_number'),
            episode=capture.get('episode_number'),
            year=capture.get('release_year'),
        )
        return identity.display

    def _match_occupant(self, occupants: List[Dict], filename: str,
                        wants_media: bool, target: str) -> Tuple[Optional[str], int]:
        """
        Which library file this one would displace.

        A media file only ever replaces a media file and a sidecar only ever
        replaces a sidecar, so restoring a subtitle can never delete an episode.
        An exact filename match wins; otherwise the single occupant of the
        matching kind is used, which is what catches an upgrade that renamed
        the file.
        """
        same_kind = [o for o in occupants if o['is_media'] == wants_media]

        for occupant in same_kind:
            if occupant['path'] == target:
                return occupant['path'], occupant['size']

        for occupant in same_kind:
            if os.path.basename(occupant['path']) == filename:
                return occupant['path'], occupant['size']

        if wants_media and len(same_kind) == 1:
            return same_kind[0]['path'], same_kind[0]['size']

        return None, 0

    def _locate_in_library(self, capture: Dict, target_dir: str) -> List[Dict]:
        """
        The files currently occupying this slot.

        Scoped to the slot's own folder and filtered by episode identity, so it
        reads one directory rather than walking the whole library once per file
        the way the previous implementation did. For a movie the whole folder
        is the slot.
        """
        if not os.path.isdir(target_dir):
            return []

        library = capture.get('library')
        season = capture.get('season_number')
        episode = capture.get('episode_number')

        from services.explore.identity import parse_episode_keys
        from .identity import is_media as _is_media, is_sidecar as _is_sidecar

        occupants: List[Dict] = []
        try:
            entries = sorted(os.listdir(target_dir))
        except OSError:
            return []

        for name in entries:
            path = os.path.join(target_dir, name)
            if not os.path.isfile(path):
                continue

            media = _is_media(name)
            if not media and not _is_sidecar(name):
                continue

            if library != 'movies':
                keys = parse_episode_keys(name, season)
                if not keys:
                    continue
                if not any(k.season == season and k.episode == episode for k in keys):
                    continue

            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            occupants.append({'path': path, 'size': size, 'is_media': media})

        return occupants


class RestoreRunner:
    """Carries out an approved plan."""

    def __init__(self, config, layout: BackupLayout, capture_model, indexer,
                 log: Optional[Callable[[str], None]] = None):
        self.config = config
        self.layout = layout
        self.captures = capture_model
        self.indexer = indexer
        self.log = log or (lambda message: None)

    def run(self, plan: RestorePlan, capture: Dict,
            progress: Optional[Callable[[int, int, str], None]] = None
            ) -> Tuple[bool, str, Dict]:
        """
        Execute the plan. Returns (ok, message, summary).

        Every file is handled independently: one failure is reported and the
        rest continue, because a half-restore that says so is better than an
        abort that leaves the caller guessing which files moved.
        """
        summary = {
            'restored': 0, 'replaced': 0, 'failed': 0,
            'captured': None, 'bytes': 0, 'failures': [],
        }

        allowed = self.config.get_destination_paths()
        if not allowed:
            return False, 'No library folders are configured; refusing to restore', summary

        try:
            assert_path_within_bounds(plan.target_dir, allowed)
        except PathTraversalError:
            return False, 'The restore target is outside the configured library', summary

        dry_run = test_mode_enabled()
        if dry_run:
            self.log('🧪 TEST_MODE: nothing below is actually written')

        # ---- 1. capture what is there now ---------------------------------
        displaced = [op for op in plan.operations if op.replaces]
        new_capture_path = None
        new_capture_id_value = None

        if displaced:
            ok, message, new_capture_path, new_capture_id_value = self._capture_current(
                capture, displaced, dry_run,
            )
            if not ok:
                return False, message, summary
            summary['captured'] = new_capture_id_value

        if not dry_run:
            os.makedirs(plan.target_dir, exist_ok=True)

        # ---- 2 & 3. write the restored file, then remove the old one ------
        total = len(plan.operations)
        for index, operation in enumerate(plan.operations, start=1):
            if progress:
                progress(index, total, os.path.basename(operation.target))
            ok, error = self._restore_one(operation, dry_run)
            if not ok:
                summary['failed'] += 1
                summary['failures'].append({'file': operation.relative_path, 'error': error})
                continue
            summary['restored'] += 1
            summary['bytes'] += operation.file_size
            if operation.replaces:
                summary['replaced'] += 1

        # ---- 4. index the capture the restore itself created --------------
        if new_capture_path and not dry_run:
            try:
                self.indexer.reindex_capture(new_capture_id_value)
            except Exception as error:  # noqa: BLE001 - files are already safe
                self.log(f"⚠️  Could not index the swapped-out copy: {error}")

        if summary['failed'] and not summary['restored']:
            return False, f"Restore failed: {summary['failed']} file(s) could not be written", summary
        if summary['failed']:
            return True, (
                f"Restored {summary['restored']} file(s); "
                f"{summary['failed']} failed"
            ), summary
        return True, f"Restored {summary['restored']} file(s)", summary

    # ---- step 1 -----------------------------------------------------------

    def _capture_current(self, capture: Dict, operations: List[RestoreOperation],
                         dry_run: bool) -> Tuple[bool, str, Optional[str], Optional[str]]:
        """
        Copy the current occupants into a new capture in the same slot.

        This is what makes a restore reversible without any reverse code path:
        the file being replaced becomes the newest version of the slot, and
        undoing the restore is restoring it.
        """
        identity = SlotIdentity(
            library=capture.get('library') or '',
            title=capture.get('title') or '',
            season=capture.get('season_number'),
            episode=capture.get('episode_number'),
            year=capture.get('release_year'),
        )

        capture_id = str(new_capture_id('restore', utc_now()))
        try:
            slot_dir = self.layout.slot_dir(identity)
        except (ValueError, PathTraversalError) as error:
            return False, f"Cannot store the file being replaced: {error}", None, None

        if dry_run:
            self.log(f"🧪 TEST_MODE: would store {len(operations)} replaced file(s) as {capture_id}")
            return True, 'dry run', None, capture_id

        try:
            os.makedirs(slot_dir, exist_ok=True)
            capture_path, actual_id = self.layout.unique_capture_dir(slot_dir, capture_id)
            os.makedirs(capture_path, exist_ok=True)
        except OSError as error:
            return False, (
                f"Could not create somewhere to keep the file being replaced: {error}. "
                'Nothing was changed.'
            ), None, None

        stored = 0
        for operation in operations:
            source = operation.replaces
            if not source or not os.path.isfile(source):
                continue
            target = os.path.join(capture_path, os.path.basename(source))
            try:
                shutil.copy2(source, target)
                # Verify before anything is destroyed. A short copy here would
                # otherwise be discovered only after the original was gone.
                if os.path.getsize(target) != os.path.getsize(source):
                    raise OSError('short copy')
                stored += 1
                self.log(f"Kept the current copy: {os.path.basename(source)}")
            except OSError as error:
                shutil.rmtree(capture_path, ignore_errors=True)
                return False, (
                    f"Could not preserve the file being replaced ({os.path.basename(source)}): "
                    f"{error}. Nothing was changed."
                ), None, None

        if not stored:
            # Every occupant vanished between planning and running. Nothing to
            # keep, so do not leave an empty capture folder behind.
            shutil.rmtree(capture_path, ignore_errors=True)
            self.layout.prune_empty_dirs(os.path.dirname(capture_path))
            return True, 'nothing to preserve', None, None

        return True, 'preserved', capture_path, actual_id

    # ---- steps 2 and 3 ----------------------------------------------------

    def _restore_one(self, operation: RestoreOperation, dry_run: bool) -> Tuple[bool, str]:
        if dry_run:
            self.log(f"🧪 TEST_MODE: would write {operation.target}")
            if operation.replaces and operation.replaces != operation.target:
                self.log(f"🧪 TEST_MODE: would remove {operation.replaces}")
            return True, ''

        temporary = f"{operation.target}.dragoncp-restore"
        try:
            shutil.copy2(operation.source, temporary)
            if os.path.getsize(temporary) != os.path.getsize(operation.source):
                raise OSError('short copy')
            # Same filesystem as the target, so this replaces it atomically.
            os.replace(temporary, operation.target)
        except OSError as error:
            if os.path.exists(temporary):
                try:
                    os.remove(temporary)
                except OSError:
                    pass
            return False, str(error)

        self.log(f"Restored: {os.path.basename(operation.target)}")

        # The old occupant only needs removing when the upgrade renamed it;
        # otherwise os.replace above has already overwritten it in place.
        if operation.replaces and operation.replaces != operation.target:
            try:
                os.remove(operation.replaces)
                self.log(f"Removed the replaced file: {os.path.basename(operation.replaces)}")
            except OSError as error:
                # The restored file is already in place and the old copy is
                # safely stored, so this is reported rather than fatal.
                return True, f"could not remove {operation.replaces}: {error}"

        return True, ''
