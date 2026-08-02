#!/usr/bin/env python3
"""
Adopt the old per-transfer folders into the identity tree.

The previous shape was `<BACKUP_PATH>/<safe folder name>_<transfer id>/`, with
files inside at their destination-relative path. On the live disk that produced
864 folders of which 687 held nothing at all, 330 files across the rest, and an
index that knew about 19 of them.

Migration runs as a preview first. Nothing moves until the mapping has been
seen, because identity is being inferred for files that in some cases have no
transfer record left to check the inference against.

Rules:

  * every file is identified the same way a new backup is, using the legacy
    record's media type and destination when one exists, and falling back to
    the folder name when it does not,
  * anything unidentified goes to `_unsorted/` keeping its original relative
    path — nothing is deleted for being unrecognised,
  * empty folders are removed only after the files have been dealt with,
  * moves are renames within the backup disk, so nothing is copied.

Order within a slot can only be as good as the evidence: captures adopted here
are timestamped from the folder's own mtime, so two legacy captures of one slot
recorded in the same second cannot be ordered against each other. That is
reported rather than invented.
"""

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from security import PathTraversalError

from .identity import (
    SlotIdentity,
    identify,
    is_media,
    library_for_media_type,
    new_capture_id,
    title_of,
)
from .layout import BackupLayout

_PARTIAL_DIR = '.rsync-partial'

# How recently a legacy folder must have been touched to be treated as "in use".
#
# The backup disk can be shared by more than one instance — a development
# checkout and the live one, each with its own database. The "no transfers
# running" guard only sees its OWN database, so it cannot know the other
# instance is mid-transfer writing into one of these folders. A folder whose
# contents changed in the last few minutes is left alone regardless of what any
# database says.
ACTIVE_FOLDER_GRACE_SECONDS = 15 * 60

# Legacy folders are "<safe title>_<transfer id>", and a transfer id carries its
# own underscores ("transfer_1732000000", "webhook_12_1732000000"). Splitting at
# the last underscore therefore leaves the title holding a trailing "_transfer",
# which is why the old reindex had to reconstruct the id from a bare timestamp
# and gave up whenever that guess did not resolve. Anchoring on the id's kind
# instead recovers both halves exactly.
_ID_KINDS = ('transfer', 'explore', 'webhook', 'restore', 'simulation', 'sim')
_LEGACY_NAME_RE = re.compile(
    r'^(?P<folder>.*?)_(?P<id>(?:' + '|'.join(_ID_KINDS) + r')_.+)$'
)

# Fallback for a name with no recognisable id kind.
_LEGACY_SUFFIX_RE = re.compile(r'^(?P<folder>.+)_(?P<suffix>[^_]+)$')


def _split_legacy_name(folder_name: str) -> Tuple[str, Optional[str]]:
    """(safe title, transfer id) for a legacy backup folder."""
    match = _LEGACY_NAME_RE.match(folder_name or '')
    if match and match.group('folder'):
        return match.group('folder'), match.group('id')

    fallback = _LEGACY_SUFFIX_RE.match(folder_name or '')
    if fallback:
        suffix = fallback.group('suffix')
        return fallback.group('folder'), (
            suffix if suffix.startswith('transfer_') else f"transfer_{suffix}"
        )
    return folder_name or '', None


def _recently_touched(folder: str, within: int = ACTIVE_FOLDER_GRACE_SECONDS) -> bool:
    """
    Whether anything in this folder changed very recently.

    Cheap insurance for a shared backup disk: if another instance is running a
    transfer, rsync is writing into its backup folder right now, and moving
    those files out from under it would strand them.
    """
    cutoff = time.time() - within
    try:
        if os.path.getmtime(folder) > cutoff:
            return True
    except OSError:
        return False
    for root, _dirs, files in os.walk(folder):
        try:
            if os.path.getmtime(root) > cutoff:
                return True
        except OSError:
            continue
        for name in files:
            try:
                if os.path.getmtime(os.path.join(root, name)) > cutoff:
                    return True
            except OSError:
                continue
    return False


def _flatten(name: str) -> str:
    """
    Collapse a name the way the legacy folder namer did, so a library folder
    and the folder derived from it compare equal.
    """
    return re.sub(r'[^A-Za-z0-9]+', '_', name or '').strip('_').lower()


@dataclass
class PlannedMove:
    source: str
    library: str
    title: str
    slot: Optional[str]
    display: str
    target_relative: str
    size: int
    identified: bool

    def as_dict(self) -> Dict:
        return {
            'source': self.source,
            'library': self.library,
            'title': self.title,
            'slot': self.slot,
            'display': self.display,
            'target': self.target_relative,
            'size': self.size,
            'identified': self.identified,
        }


@dataclass
class MigrationReport:
    folders_seen: int = 0
    empty_folders: List[str] = field(default_factory=list)
    #: Left alone because something wrote to them very recently — most likely
    #: another instance sharing this disk.
    active_folders: List[str] = field(default_factory=list)
    moves: List[PlannedMove] = field(default_factory=list)
    unidentified: List[PlannedMove] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    applied: bool = False
    moved_count: int = 0
    removed_folders: int = 0

    @property
    def total_size(self) -> int:
        return sum(m.size for m in self.moves) + sum(m.size for m in self.unidentified)

    def as_dict(self) -> Dict:
        return {
            'applied': self.applied,
            'folders_seen': self.folders_seen,
            'empty_folder_count': len(self.empty_folders),
            'empty_folders': self.empty_folders[:200],
            'active_folder_count': len(self.active_folders),
            'active_folders': self.active_folders[:50],
            'move_count': len(self.moves),
            'moves': [m.as_dict() for m in self.moves[:500]],
            'unidentified_count': len(self.unidentified),
            'unidentified': [m.as_dict() for m in self.unidentified[:200]],
            'total_size': self.total_size,
            'moved_count': self.moved_count,
            'removed_folders': self.removed_folders,
            'warnings': self.warnings,
            'errors': self.errors,
        }


class LegacyMigration:
    """Walks the old folders and files their contents into the tree."""

    def __init__(self, config, layout: BackupLayout, backup_model, transfer_model,
                 indexer):
        self.config = config
        self.layout = layout
        self.backup_model = backup_model
        self.transfer_model = transfer_model
        self.indexer = indexer
        self._catalogue_cache: Optional[List[Tuple[str, str, str]]] = None

    # ---- planning ---------------------------------------------------------

    def plan(self) -> MigrationReport:
        """What migration would do. Moves nothing."""
        return self._walk(apply=False)

    def apply(self) -> MigrationReport:
        """Do it, then rebuild the index over the result."""
        report = self._walk(apply=True)
        if report.moved_count:
            try:
                self.indexer.rebuild()
            except Exception as error:  # noqa: BLE001 - the files are already placed
                report.errors.append(f"Index rebuild after migration failed: {error}")
        return report

    # ---- the walk ---------------------------------------------------------

    def _walk(self, apply: bool) -> MigrationReport:
        report = MigrationReport(applied=apply)
        base = self.layout.base_or_none(for_writing=apply)
        if not base:
            report.errors.append('BACKUP_PATH is not configured')
            return report

        for folder in self.layout.legacy_folders():
            report.folders_seen += 1
            name = os.path.basename(folder)

            if _recently_touched(folder):
                report.active_folders.append(name)
                report.warnings.append(
                    f"{name}: written to in the last "
                    f"{ACTIVE_FOLDER_GRACE_SECONDS // 60} minutes, so it was left alone. "
                    'Another instance may be using this disk.'
                )
                continue

            if self.layout.is_empty_tree(folder):
                report.empty_folders.append(name)
                if apply:
                    try:
                        shutil.rmtree(folder)
                        report.removed_folders += 1
                    except OSError as error:
                        report.errors.append(f"{name}: {error}")
                continue

            try:
                self._migrate_folder(folder, name, report, apply)
            except Exception as error:  # noqa: BLE001 - one folder must not stop the rest
                report.errors.append(f"{name}: {error}")

        return report

    def _migrate_folder(self, folder: str, name: str,
                        report: MigrationReport, apply: bool) -> None:
        context = self._context_for(name)
        library = context['library']
        dest_relative = context['dest_relative']
        dest_path = context['dest_path']

        if not library:
            report.warnings.append(
                f"{name}: media type unknown, everything from it goes to the unsorted bucket"
            )

        capture_id = str(new_capture_id(
            context['transfer_id'] or name, context['captured_at'],
        ))

        groups: Dict[SlotIdentity, List[Dict]] = {}
        extras: Dict[str, List[Dict]] = {}
        unknown: List[Dict] = []

        for root, dirs, filenames in os.walk(folder):
            dirs[:] = [d for d in dirs if d != _PARTIAL_DIR]
            for filename in filenames:
                full = os.path.join(root, filename)
                if os.path.islink(full):
                    continue
                relative = os.path.relpath(full, folder).replace(os.sep, '/')
                try:
                    size = os.path.getsize(full)
                    mtime = int(os.path.getmtime(full))
                except OSError:
                    size, mtime = 0, 0

                entry = {
                    'source': full,
                    'relative': relative,
                    'filename': filename,
                    'size': size,
                    'mtime': mtime,
                    'original_path': (
                        os.path.join(dest_path, relative).replace(os.sep, '/')
                        if dest_path else ''
                    ),
                    'is_media': is_media(filename),
                }

                library_relative = (
                    f"{dest_relative}/{relative}" if dest_relative else relative
                )
                identity = identify(library, library_relative) if library else None
                if identity is not None:
                    groups.setdefault(identity, []).append(entry)
                    continue

                # Artwork and season-level metadata belong to the title but to
                # no episode. Keeping them beside the title rather than in the
                # unsorted bucket is both truer and easier to find later.
                extra_title = title_of(library, library_relative) if library else None
                if extra_title:
                    extras.setdefault(extra_title, []).append(entry)
                    continue

                unknown.append(entry)

        for identity, entries in groups.items():
            self._record_group(identity, entries, capture_id, report, apply)

        for extra_title, entries in extras.items():
            self._record_extras(
                library or '', extra_title, entries, capture_id, report, apply,
            )

        if unknown:
            self._record_unknown(unknown, capture_id, library, report, apply)

        if apply and self.layout.is_empty_tree(folder):
            try:
                shutil.rmtree(folder)
                report.removed_folders += 1
            except OSError as error:
                report.errors.append(f"{name}: could not remove after migrating: {error}")

    # ---- context ----------------------------------------------------------

    def _context_for(self, folder_name: str) -> Dict:
        """
        What a legacy folder name and any surviving records can tell us.

        The legacy record is consulted first because it holds the media type
        and the real destination. Where none exists, the folder name is all
        there is, and the result is deliberately weaker: unidentified files
        land in the unsorted bucket rather than being placed on a guess.
        """
        _safe_title, transfer_id = _split_legacy_name(folder_name)

        record = None
        for candidate in filter(None, [folder_name, transfer_id]):
            try:
                record = self.backup_model.get(candidate)
            except Exception:  # noqa: BLE001
                record = None
            if record:
                break

        transfer = None
        for candidate in filter(None, [record.get('transfer_id') if record else None, transfer_id]):
            try:
                transfer = self.transfer_model.get(candidate)
            except Exception:  # noqa: BLE001
                transfer = None
            if transfer:
                break

        media_type = (record or {}).get('media_type') or (transfer or {}).get('media_type')
        dest_path = (record or {}).get('dest_path') or (transfer or {}).get('dest_path') or ''
        library = library_for_media_type(media_type)
        dest_relative = self._dest_relative(library, dest_path)

        if not dest_relative:
            # Either no record survived — the common case on the live disk — or
            # one did but its destination no longer resolves. Either way the
            # library still holds the title folder, so ask it. An absent or
            # ambiguous answer stays unknown, and those files go to the
            # unsorted bucket rather than being placed on a guess.
            inferred_library, title = self._infer_from_the_library(folder_name, media_type)
            if inferred_library:
                library = inferred_library
                dest_relative = title

        return {
            'transfer_id': (transfer or {}).get('transfer_id') or transfer_id,
            'library': library,
            'dest_path': dest_path,
            'dest_relative': dest_relative,
            'captured_at': self._folder_time(folder_name),
        }

    def _catalogue(self) -> List[Tuple[str, str, str]]:
        """
        Every title folder in every library, flattened for comparison.

        Built once and reused. Flattening matches what the legacy folder namer
        did to the title, which is what lets "Alpha - Bravo, Charlie of the
        Delta (2016)" be recognised from "Alpha_Bravo_Charlie_of_the_Delta_2016".
        """
        if self._catalogue_cache is not None:
            return self._catalogue_cache

        entries: List[Tuple[str, str, str]] = []
        for library, key in (
            ('movies', 'MOVIE_DEST_PATH'),
            ('shows', 'TVSHOW_DEST_PATH'),
            ('anime', 'ANIME_DEST_PATH'),
        ):
            root = self.config.get(key)
            if not root or not os.path.isdir(root):
                continue
            try:
                names = os.listdir(root)
            except OSError:
                continue
            for name in names:
                if os.path.isdir(os.path.join(root, name)):
                    entries.append((library, name, _flatten(name)))

        # Longest first, so the most specific title wins a prefix match.
        entries.sort(key=lambda e: len(e[2]), reverse=True)
        self._catalogue_cache = entries
        return entries

    def _infer_from_the_library(self, folder_name: str,
                                media_type_hint: Optional[str] = None
                                ) -> Tuple[Optional[str], str]:
        """
        Recover the library and the exact title from a legacy folder name.

        The name is `<flattened title>_<transfer id>`, and a transfer id has no
        fixed shape — the live disk holds ids like `series_webhook_tvshows_301
        _s1_ef92`. Splitting the name is therefore guesswork, so this does not
        split it: it asks the library which of its titles the name starts with,
        and takes the longest match. That gives the library and the folder's
        real spelling in one step, and it is checked against something that
        exists rather than inferred from a pattern.

        Returns (library, title), or (None, '') when nothing matches or the
        match is ambiguous between two libraries.
        """
        flattened = _flatten(folder_name)
        if not flattened:
            return None, ''

        matches: List[Tuple[str, str]] = []
        best_length = 0
        for library, title, key in self._catalogue():
            if not key or len(key) < best_length:
                break
            if flattened == key or flattened.startswith(key + '_'):
                if len(key) > best_length:
                    matches = [(library, title)]
                    best_length = len(key)
                elif (library, title) not in matches:
                    matches.append((library, title))

        if not matches:
            return None, ''
        if len(matches) == 1:
            return matches[0]

        # The same title exists in more than one library. A media type from a
        # surviving record settles it; without one, refuse to guess.
        wanted = library_for_media_type(media_type_hint)
        narrowed = [m for m in matches if m[0] == wanted]
        return narrowed[0] if len(narrowed) == 1 else (None, '')

    def _dest_relative(self, library: Optional[str], dest_path: str) -> str:
        if not library or not dest_path:
            return ''
        key = {
            'movies': 'MOVIE_DEST_PATH',
            'shows': 'TVSHOW_DEST_PATH',
            'anime': 'ANIME_DEST_PATH',
        }[library]
        base = self.config.get(key)
        if not base:
            return ''
        try:
            relative = os.path.relpath(os.path.realpath(dest_path), os.path.realpath(base))
        except ValueError:
            return ''
        if relative.startswith('..') or relative == '.':
            return ''
        return relative.replace(os.sep, '/')

    def _folder_time(self, folder_name: str) -> datetime:
        base = self.layout.base_or_none()
        path = os.path.join(base, folder_name) if base else ''
        try:
            return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        except OSError:
            return datetime.now(timezone.utc)

    # ---- placement --------------------------------------------------------

    def _record_group(self, identity: SlotIdentity, entries: List[Dict],
                      capture_id: str, report: MigrationReport, apply: bool) -> None:
        try:
            slot_dir = self.layout.slot_dir(identity)
        except (ValueError, PathTraversalError) as error:
            report.warnings.append(f"{identity.display}: {error}; sent to the unsorted bucket")
            self._record_unknown(entries, capture_id, identity.library, report, apply)
            return

        if apply:
            os.makedirs(slot_dir, exist_ok=True)
        capture_path, _actual = self.layout.unique_capture_dir(slot_dir, capture_id)

        for entry in entries:
            target = os.path.join(capture_path, entry['filename'])
            report.moves.append(PlannedMove(
                source=entry['source'],
                library=identity.library,
                title=identity.title,
                slot=identity.slot_folder,
                display=identity.display,
                target_relative=self._safe_relative(target),
                size=entry['size'],
                identified=True,
            ))
            if apply and self._move(entry['source'], target, report):
                report.moved_count += 1

    def _record_extras(self, library: str, title: str, entries: List[Dict],
                       capture_id: str, report: MigrationReport, apply: bool) -> None:
        try:
            root = os.path.dirname(self.layout.extras_dir(library, title, capture_id))
        except (ValueError, PathTraversalError) as error:
            report.warnings.append(f"{title}: {error}; sent to the unsorted bucket")
            self._record_unknown(entries, capture_id, library, report, apply)
            return

        if apply:
            os.makedirs(root, exist_ok=True)
        capture_path, _actual = self.layout.unique_capture_dir(root, capture_id)

        for entry in entries:
            target = os.path.join(capture_path, entry['relative'])
            report.moves.append(PlannedMove(
                source=entry['source'], library=library, title=title, slot=None,
                display=f"{title} — extras", target_relative=self._safe_relative(target),
                size=entry['size'], identified=True,
            ))
            if apply and self._move(entry['source'], target, report):
                report.moved_count += 1

    def _record_unknown(self, entries: List[Dict], capture_id: str,
                        library: Optional[str], report: MigrationReport,
                        apply: bool) -> None:
        try:
            root = self.layout.unsorted_root()
        except Exception as error:  # noqa: BLE001
            report.errors.append(f"Unsorted bucket unavailable: {error}")
            return

        if apply:
            os.makedirs(root, exist_ok=True)
        capture_path, _actual = self.layout.unique_capture_dir(root, capture_id)

        for entry in entries:
            target = os.path.join(capture_path, entry['relative'])
            report.unidentified.append(PlannedMove(
                source=entry['source'],
                library=library or '',
                title='',
                slot=None,
                display=entry['filename'],
                target_relative=self._safe_relative(target),
                size=entry['size'],
                identified=False,
            ))
            if apply and self._move(entry['source'], target, report):
                report.moved_count += 1

    def _move(self, source: str, target: str, report: MigrationReport) -> bool:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                stem, extension = os.path.splitext(target)
                counter = 2
                while os.path.exists(f"{stem} ({counter}){extension}"):
                    counter += 1
                target = f"{stem} ({counter}){extension}"
            shutil.move(source, target)
            return True
        except OSError as error:
            report.errors.append(f"{os.path.basename(source)}: {error}")
            return False

    def _safe_relative(self, path: str) -> str:
        try:
            return self.layout.relative(path)
        except Exception:  # noqa: BLE001
            return path
