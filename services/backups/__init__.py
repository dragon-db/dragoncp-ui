#!/usr/bin/env python3
"""
Backups — every movie and episode is a slot with a version history.

The library holds a slot's current occupant. This package holds the previous
ones, newest first. One primitive runs through all of it: *displace whatever
occupies the slot, then put something else there.* A sync does it, a restore
does it, an Explore removal does it — which is why undoing a restore needs no
code of its own. It is restoring the capture the restore itself created.

Module map:

    identity.py   what a displaced file IS — the slot it belongs to
    layout.py     where that slot lives on disk, and how to read it back
    sorter.py     rsync's flat staging output -> the identity tree
    indexer.py    rebuild the database index by walking the tree
    restore.py    plan and run a restore, capture-before-destroy
    retention.py  keep N captures per slot
    migrate.py    adopt the old per-transfer folders
    service.py    the facade routes and the coordinator talk to

The tree is the source of truth. Every fact needed to rebuild the index is in
the path, so the index can always be regenerated from disk and cannot drift
from it for long.
"""

from .identity import (
    CaptureId,
    SlotIdentity,
    library_for_media_type,
    media_type_for_library,
    new_capture_id,
    parse_movie_identity,
    season_folder_name,
    slot_folder_name,
)
from .layout import BackupLayout, BackupPathNotConfigured
from .service import BackupsService

__all__ = [
    'BackupLayout',
    'BackupPathNotConfigured',
    'BackupsService',
    'CaptureId',
    'SlotIdentity',
    'library_for_media_type',
    'media_type_for_library',
    'new_capture_id',
    'parse_movie_identity',
    'season_folder_name',
    'slot_folder_name',
]
