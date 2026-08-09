#!/usr/bin/env python3
"""
Repairing files the old single-episode download stranded.

That download built its destination path with the filename already appended and
then created it as a *directory*, so the episode landed at
`Season 01/episode.mkv/episode.mkv`. The file is intact and the right size — it
is simply one level too deep, which is enough for every media server to miss it.

The comparison already finds these (`FileEntry.misplaced`, set whenever a media
file does not sit at `EXPECTED_DEPTH`). This module is the other half: work out
where each one should have gone, and move it there.

Two rules shape everything below.

**Nothing is overwritten.** A repair that displaced a file would need the whole
backup machinery behind it to be safe, and a stranded copy is never worth that.
If something already occupies the destination the file stays where it is and is
reported as a conflict for a person to look at.

**A file is only moved when the destination is derivable.** Too *deep* is
repairable — the series and season folders are right there in the path above it.
Too *shallow* is not: an episode sitting loose in the series folder does not say
which season it belongs to, and guessing that from the filename would be a
rename dressed up as a repair. Those are reported, never touched.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from security import PathTraversalError, assert_path_within_bounds

from .inventory import EXPECTED_DEPTH, FileEntry


@dataclass
class RepairAction:
    """One stranded file and where it should be."""
    relative_path: str
    destination: str
    name: str
    season_folder: Optional[str]
    size: int
    # The directory the file is buried in, which becomes empty once it moves.
    wrapper: str

    def as_dict(self) -> Dict:
        return {
            'relative_path': self.relative_path,
            'destination': self.destination,
            'name': self.name,
            'season_folder': self.season_folder,
            'size': self.size,
            'wrapper': self.wrapper,
        }


@dataclass
class RepairBlocker:
    """A stranded file that will not be moved, and why not in plain words."""
    relative_path: str
    reason: str
    size: int = 0

    def as_dict(self) -> Dict:
        return {'relative_path': self.relative_path, 'reason': self.reason, 'size': self.size}


@dataclass
class RepairPlan:
    media_type: str
    scope: str
    actions: List[RepairAction] = field(default_factory=list)
    blocked: List[RepairBlocker] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(action.size for action in self.actions)

    def as_dict(self) -> Dict:
        return {
            'media_type': self.media_type,
            'scope': self.scope,
            'actions': [a.as_dict() for a in self.actions],
            'blocked': [b.as_dict() for b in self.blocked],
            'action_count': len(self.actions),
            'blocked_count': len(self.blocked),
            'total_size': self.total_size,
        }


def _destination_for(media_type: str, entry: FileEntry) -> Optional[str]:
    """
    Where this file should sit, or None when that cannot be worked out.

    Built from the folders the file is already under rather than from its name,
    so the repair moves a file and never renames one.
    """
    expected = EXPECTED_DEPTH.get(media_type, 3)
    if entry.depth <= expected:
        return None
    if not entry.series:
        return None
    if media_type == 'movies':
        return f"{entry.series}/{entry.name}"
    if not entry.season_folder:
        return None
    return f"{entry.series}/{entry.season_folder}/{entry.name}"


def plan_repair(media_type: str, local_root: str, entries: List[FileEntry],
                scope: str) -> RepairPlan:
    """
    Work out what repairing this series or season would do.

    Read-only. `entries` is the local side of a comparison that has already run,
    so this never re-reads the disk — except to ask whether each destination is
    free, which is the one thing the comparison cannot answer for a path that
    does not exist in it.
    """
    plan = RepairPlan(media_type=media_type, scope=scope)
    claimed: Dict[str, str] = {}

    for entry in sorted((e for e in entries if e.misplaced), key=lambda e: e.relative_path):
        expected = EXPECTED_DEPTH.get(media_type, 3)
        destination = _destination_for(media_type, entry)

        if destination is None:
            reason = (
                'sits above its season folder, so there is nothing to say which '
                'season it belongs to'
                if entry.depth < expected
                else 'is not inside a recognisable title folder'
            )
            plan.blocked.append(RepairBlocker(entry.relative_path, reason, entry.size))
            continue

        # Two stranded copies of the same episode both want the same place. The
        # first one claims it; the second is a decision about which copy to keep,
        # which is not a repair.
        if destination in claimed:
            plan.blocked.append(RepairBlocker(
                entry.relative_path,
                f"would land on the same path as {claimed[destination]}",
                entry.size,
            ))
            continue

        # In the shape this exists to fix, the destination path is the wrapper
        # directory the file is sitting inside — `Season 01/ep.mkv/ep.mkv` wants
        # to become `Season 01/ep.mkv`, which is the directory above it. That is
        # the expected case, not a collision; anything else occupying the
        # destination is a real file and is left alone.
        wraps_the_source = entry.relative_path.startswith(destination + '/')
        absolute = os.path.join(local_root, destination)
        if os.path.lexists(absolute) and not wraps_the_source:
            plan.blocked.append(RepairBlocker(
                entry.relative_path,
                'a file is already there — nothing is overwritten',
                entry.size,
            ))
            continue

        # The wrapper has to come down for the file to take its name, so it must
        # hold nothing but that file. Caught here rather than at the rename so
        # the preview says why, instead of the run reporting a failure.
        if wraps_the_source and not _holds_only(absolute, os.path.join(local_root,
                                                                      entry.relative_path)):
            plan.blocked.append(RepairBlocker(
                entry.relative_path,
                'the folder around it holds other files, which would have to go '
                'somewhere first',
                entry.size,
            ))
            continue

        wrapper = entry.relative_path.rsplit('/', 1)[0] if '/' in entry.relative_path else ''
        claimed[destination] = entry.relative_path
        plan.actions.append(RepairAction(
            relative_path=entry.relative_path,
            destination=destination,
            name=entry.name,
            season_folder=entry.season_folder,
            size=entry.size,
            wrapper=wrapper,
        ))

    return plan


def _holds_only(directory: str, path: str) -> bool:
    """Whether `directory` contains `path` and nothing else at all."""
    try:
        for root, _, names in os.walk(directory):
            for name in names:
                if os.path.join(root, name) != path:
                    return False
    except OSError:
        return False
    return True


def _staging_name(destination: str) -> str:
    """
    A free name beside the destination to hold the file while its own folder is
    taken down. Leading dot so a media server ignores it if anything goes wrong
    mid-run; numbered rather than random so a leftover is recognisable.
    """
    base = os.path.join(os.path.dirname(destination),
                        '.dragoncp-repair-' + os.path.basename(destination))
    candidate = base
    counter = 1
    while os.path.lexists(candidate):
        candidate = f"{base}.{counter}"
        counter += 1
    return candidate


def _prune_empty(directory: str, stop_at: str) -> int:
    """
    Remove `directory` and its now-empty parents, stopping before `stop_at`.

    Walking upward from the directory that was just emptied, not from the one
    above it: the wrapper the file came out of is itself the first thing that
    should go. Stops at the first directory that still holds something.
    """
    removed = 0
    stop = os.path.realpath(stop_at)
    current = os.path.realpath(directory)
    while current != stop and current.startswith(stop + os.sep):
        try:
            if os.listdir(current):
                break
            os.rmdir(current)
        except OSError:
            break
        removed += 1
        current = os.path.dirname(current)
    return removed


def apply_repair(local_root: str, plan: RepairPlan, allowed_paths: List[str]) -> Dict:
    """
    Carry out a plan, one file at a time.

    Every source and destination is bounds-checked against the configured media
    directories before anything moves, and the destination is re-checked for an
    occupant immediately before the rename — the plan may have been sitting on
    someone's screen while a transfer ran.

    A file that fails is reported and the rest still run. There is no partial
    state to unpick: each move is one rename that either happened or did not.
    """
    moved: List[Dict] = []
    failed: List[Dict] = []
    directories_removed = 0

    for action in plan.actions:
        source = os.path.join(local_root, action.relative_path)
        destination = os.path.join(local_root, action.destination)
        try:
            source = assert_path_within_bounds(source, allowed_paths)
            destination = assert_path_within_bounds(destination, allowed_paths)
        except PathTraversalError as error:
            failed.append({'relative_path': action.relative_path, 'error': str(error)})
            continue

        if not os.path.isfile(source):
            failed.append({
                'relative_path': action.relative_path,
                'error': 'the file is no longer there',
            })
            continue

        # The wrapper case has to go via a staging name inside the season
        # folder: the destination is a directory that still contains the file,
        # so it cannot be emptied until the file leaves and cannot be written
        # until it is emptied. Staging is a rename within one directory, so
        # nothing is copied and there is no window where the file does not exist.
        wraps = source.startswith(destination + os.sep)
        if not wraps and os.path.lexists(destination):
            failed.append({
                'relative_path': action.relative_path,
                'error': 'something now occupies the destination',
            })
            continue

        wrapper = os.path.dirname(source)
        removed_here = 0
        try:
            if wraps:
                staged = _staging_name(destination)
                os.rename(source, staged)
                removed_here = _prune_empty(wrapper, local_root)
                if os.path.lexists(destination):
                    # The wrapper would not empty — put the file back rather
                    # than leaving it under a name nothing else recognises.
                    os.rename(staged, source)
                    failed.append({
                        'relative_path': action.relative_path,
                        'error': 'the folder holding it could not be cleared',
                    })
                    continue
                os.rename(staged, destination)
            else:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                os.rename(source, destination)
                if action.wrapper:
                    removed_here = _prune_empty(wrapper, local_root)
        except OSError as error:
            failed.append({'relative_path': action.relative_path, 'error': str(error)})
            continue

        directories_removed += removed_here
        moved.append({
            'relative_path': action.relative_path,
            'destination': action.destination,
            'size': action.size,
        })

    return {
        'moved': moved,
        'failed': failed,
        'moved_count': len(moved),
        'failed_count': len(failed),
        'directories_removed': directories_removed,
        'moved_size': sum(entry['size'] for entry in moved),
    }
