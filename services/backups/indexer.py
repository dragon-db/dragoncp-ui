#!/usr/bin/env python3
"""
Rebuild the index by walking the tree.

The tree is the source of truth, so this needs no transfer record, no prior
index and no luck. That is the whole point: the previous recovery action
reconstructed a transfer id from a folder name and imported the backup with an
empty destination when that failed, which is why webhook-created backups could
be listed and never restored.

Three things are NOT derivable from a path and are therefore carried over from
the existing index rather than regenerated: whether a capture is pinned, why it
was displaced, and which transfer produced it. Losing a pin to a routine
rebuild would quietly re-expose the one copy someone marked as worth keeping.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from services.explore.identity import parse_episode_keys

from .identity import (
    SlotIdentity,
    is_media,
    parse_movie_identity,
)
from .layout import BackupLayout, CaptureLocation


@dataclass
class RebuildResult:
    indexed: int = 0
    files: int = 0
    total_size: int = 0
    unsorted: int = 0
    removed: int = 0
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            'indexed': self.indexed,
            'files': self.files,
            'total_size': self.total_size,
            'unsorted': self.unsorted,
            'removed': self.removed,
            'errors': self.errors,
        }


class BackupIndexer:
    """Keeps the index in step with the tree."""

    def __init__(self, layout: BackupLayout, capture_model):
        self.layout = layout
        self.captures = capture_model

    # ---- one capture ------------------------------------------------------

    def index_location(self, location: CaptureLocation,
                       carried: Optional[Dict] = None) -> Optional[Dict]:
        """Index one capture folder. Returns the record written, or None."""
        files = self._read_files(location)
        if not files:
            return None

        carried = carried or {}
        record = {
            'capture_id': location.capture_id,
            'library': location.library or None,
            'title': location.title or None,
            'season_number': location.season,
            'episode_number': location.episode,
            'release_year': None,
            'slot_key': None,
            'capture_path': location.relative_path,
            'captured_at': location.captured_at.isoformat().replace('+00:00', 'Z'),
            'source_transfer_id': carried.get('source_transfer_id'),
            'source_ref': location.source_ref,
            'reason': carried.get('reason') or 'sync_replace',
            'kind': location.kind,
            'file_count': len(files),
            'total_size': sum(f['file_size'] for f in files),
            'pinned': carried.get('pinned', 0),
            'status': 'present',
        }

        slot_keys: List[str] = []
        if location.kind == 'slot':
            identity = self._identity_for(location, files)
            record['slot_key'] = identity.slot_key
            record['release_year'] = identity.year
            slot_keys = list(identity.all_slot_keys)

        self.captures.upsert(record, files, slot_keys)
        return record

    def _identity_for(self, location: CaptureLocation, files: List[Dict]) -> SlotIdentity:
        """
        Rebuild the slot identity, including any extra episodes.

        The path gives one episode. A double-episode file gives two, and the
        second is only visible in the filename — so the names inside the
        capture are parsed as well, and the capture ends up reachable from both
        slots rather than only the one it is filed under.
        """
        if location.library == 'movies':
            title, year = parse_movie_identity(location.title)
            return SlotIdentity(library='movies', title=location.title, year=year)

        keys = []
        for entry in files:
            if not entry['is_media']:
                continue
            filename = os.path.basename(entry['relative_path'])
            keys.extend(parse_episode_keys(filename, location.season))

        # Deduplicate while keeping the path's own episode first, so the
        # capture's primary slot always matches the folder it lives in.
        ordered = []
        for key in keys:
            if key not in ordered:
                ordered.append(key)
        ordered.sort(key=lambda k: (k.season != location.season, k.episode != location.episode))

        return SlotIdentity(
            library=location.library,
            title=location.title,
            season=location.season,
            episode=location.episode,
            keys=tuple(ordered),
        )

    def _read_files(self, location: CaptureLocation) -> List[Dict]:
        files: List[Dict] = []
        for root, _dirs, filenames in os.walk(location.path):
            for filename in filenames:
                full = os.path.join(root, filename)
                if os.path.islink(full):
                    continue
                try:
                    stat = os.stat(full)
                    size, mtime = stat.st_size, int(stat.st_mtime)
                except OSError:
                    size, mtime = 0, 0
                relative = os.path.relpath(full, location.path).replace(os.sep, '/')
                files.append({
                    'relative_path': relative,
                    # The library path this copy came from is not recorded in
                    # the tree. It is re-derived at restore time from the slot
                    # and the live library, which is more reliable than a path
                    # stored months ago and never revisited.
                    'original_path': '',
                    'file_size': size,
                    'modified_time': mtime,
                    'is_media': is_media(filename),
                })
        return files

    # ---- the whole tree ---------------------------------------------------

    def rebuild(self) -> RebuildResult:
        """
        Regenerate the entire index from disk.

        Safe to run at any time and idempotent — running it twice leaves the
        same index. It writes nothing to the tree and deletes no media.
        """
        result = RebuildResult()

        carried = self._carry_forward()
        seen = set()

        for location in self.layout.scan():
            try:
                record = self.index_location(location, carried.get(location.capture_id))
            except Exception as error:  # noqa: BLE001 - one bad folder must not stop the scan
                result.errors.append(f"{location.relative_path}: {error}")
                continue
            if not record:
                continue
            seen.add(location.capture_id)
            result.indexed += 1
            result.files += record['file_count']
            result.total_size += record['total_size']
            if location.kind == 'unsorted':
                result.unsorted += 1

        # Anything indexed but no longer on disk is gone; the index must say so
        # rather than offering a restore that would fail at the first read.
        for capture_id in set(carried) - seen:
            if self.captures.delete(capture_id):
                result.removed += 1

        return result

    def _carry_forward(self) -> Dict[str, Dict]:
        """Facts the path cannot hold, keyed by capture id."""
        carried: Dict[str, Dict] = {}
        for row in self.captures.recent(limit=1_000_000):
            carried[row['capture_id']] = {
                'pinned': row.get('pinned', 0),
                'reason': row.get('reason'),
                'source_transfer_id': row.get('source_transfer_id'),
            }
        return carried

    def reindex_capture(self, capture_id: str) -> Optional[Dict]:
        """Re-read one capture from disk. Used after files change underneath it."""
        for location in self.layout.scan():
            if location.capture_id == capture_id:
                existing = self.captures.get(capture_id) or {}
                return self.index_location(location, {
                    'pinned': existing.get('pinned', 0),
                    'reason': existing.get('reason'),
                    'source_transfer_id': existing.get('source_transfer_id'),
                })
        return None
