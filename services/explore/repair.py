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

Three rules shape everything below.

**A file is only moved when the destination is derivable.** Too *deep* is
repairable — the series and season folders are right there in the path above it.
Too *shallow* is not: an episode sitting loose in the series folder does not say
which season it belongs to, and guessing that from the filename would be a
rename dressed up as a repair. Those are reported, never touched.

**A copy already in place is found by identity, not by name.** A competing copy
of the same episode is almost never named the same — it is a different quality
or release group. Comparing paths would report no conflict, move the file up,
and leave the episode in the folder twice for the media server to choose
between, which is the duplication this is supposed to prevent. For a film the
folder is the slot, so any media file in it is another copy of that film.

**Nothing is destroyed, only displaced.** When both copies exist, which to keep
is a judgement about quality that this code cannot make, so the run refuses
until a person says. Whichever copy loses is captured into the backup area
first and shows up on the Backups page — so "keep what I already have" and
"the stranded one is better" are both reversible by an ordinary restore.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from security import PathTraversalError, assert_path_within_bounds

from .identity import is_media_file, parse_episode_keys
from .inventory import EXPECTED_DEPTH, FileEntry


@dataclass
class Rival:
    """A copy of the same episode or film already sitting where it belongs."""
    relative_path: str
    name: str
    size: int
    #: True when it is literally the same filename, which is the plain wrapper
    #: case rather than a competing release.
    same_name: bool

    def as_dict(self) -> Dict:
        return {
            'relative_path': self.relative_path,
            'name': self.name,
            'size': self.size,
            'same_name': self.same_name,
        }


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
    #: What already holds this episode or film, if anything. When set, the file
    #: cannot simply be moved — one of the two copies has to go, and which one
    #: is a judgement about quality that only a person can make.
    rival: Optional[Rival] = None

    @property
    def needs_decision(self) -> bool:
        return self.rival is not None

    def as_dict(self) -> Dict:
        return {
            'relative_path': self.relative_path,
            'destination': self.destination,
            'name': self.name,
            'season_folder': self.season_folder,
            'size': self.size,
            'wrapper': self.wrapper,
            'rival': self.rival.as_dict() if self.rival else None,
            'needs_decision': self.needs_decision,
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
    def clean(self) -> List[RepairAction]:
        """Files that can just be moved. Nothing else holds their place."""
        return [a for a in self.actions if not a.needs_decision]

    @property
    def contested(self) -> List[RepairAction]:
        """Files whose destination already holds the same episode or film."""
        return [a for a in self.actions if a.needs_decision]

    @property
    def total_size(self) -> int:
        return sum(action.size for action in self.clean)

    #: What deleting every contested stranded copy would free. Shown so the
    #: "keep what I already have" choice has a number attached to it.
    @property
    def reclaimable(self) -> int:
        return sum(action.size for action in self.contested)

    def find(self, relative_path: str) -> Optional[RepairAction]:
        for action in self.actions:
            if action.relative_path == relative_path:
                return action
        return None

    def as_dict(self) -> Dict:
        return {
            'media_type': self.media_type,
            'scope': self.scope,
            'actions': [a.as_dict() for a in self.actions],
            'blocked': [b.as_dict() for b in self.blocked],
            'action_count': len(self.clean),
            'contested_count': len(self.contested),
            'blocked_count': len(self.blocked),
            'total_size': self.total_size,
            'reclaimable': self.reclaimable,
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
        # the expected case, not a collision.
        wraps_the_source = entry.relative_path.startswith(destination + '/')
        absolute = os.path.join(local_root, destination)

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

        rival = _find_rival(media_type, local_root, entry, destination)

        wrapper = entry.relative_path.rsplit('/', 1)[0] if '/' in entry.relative_path else ''
        claimed[destination] = entry.relative_path
        plan.actions.append(RepairAction(
            relative_path=entry.relative_path,
            destination=destination,
            name=entry.name,
            season_folder=entry.season_folder,
            size=entry.size,
            wrapper=wrapper,
            rival=rival,
        ))

    return plan


def _find_rival(media_type: str, local_root: str, entry: FileEntry,
                destination: str) -> Optional[Rival]:
    """
    A copy of this same episode or film already in the right place.

    Matched on **identity**, not filename. A competing copy is almost never
    named the same — it is a different quality or release group — so comparing
    paths would say "no conflict", move the file up, and leave the episode in
    the folder twice under two names for the media server to choose between.

    For a film the folder is the slot, so any media file already sitting in it
    is another copy of that film regardless of what it is called.
    """
    parent = os.path.dirname(os.path.join(local_root, destination))
    if not os.path.isdir(parent):
        return None

    wanted = {str(key) for key in entry.keys}
    source = os.path.join(local_root, entry.relative_path)

    try:
        names = sorted(os.listdir(parent))
    except OSError:
        return None

    for name in names:
        path = os.path.join(parent, name)
        if not os.path.isfile(path) or path == source:
            continue
        if not is_media_file(name):
            continue

        if media_type == 'movies':
            match = True
        else:
            # The season is taken from the folder being looked in, so a file
            # named without one still lines up with the episode it sits beside.
            keys = {str(key) for key in parse_episode_keys(name, entry.season)}
            match = bool(wanted and keys & wanted)

        if match:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            return Rival(
                relative_path=os.path.relpath(path, local_root).replace('\\', '/'),
                name=name,
                size=size,
                same_name=(name == entry.name),
            )
    return None


def _holds_only(directory: str, path: str) -> bool:
    """
    Whether `directory` contains `path` and nothing else at all.

    Empty directories count. They hold no files, so ignoring them looks
    harmless — but the wrapper has to be *removed* for the file to take its
    name, and `os.rmdir` will not remove a directory that still has one. The
    plan would promise a move that the run could only fail, which is the one
    thing the preview exists to prevent.

    Directories on the way down to the file itself are expected and do not
    count against it.
    """
    on_the_way = set()
    current = os.path.dirname(path)
    while current.startswith(directory):
        on_the_way.add(current)
        if current == directory:
            break
        current = os.path.dirname(current)

    try:
        for root, dirs, names in os.walk(directory):
            for name in names:
                if os.path.join(root, name) != path:
                    return False
            for name in dirs:
                if os.path.join(root, name) not in on_the_way:
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


#: What a person can decide about a stranded file whose place is already taken.
KEEP_EXISTING = 'keep_existing'   # the copy in place wins; delete the stranded one
REPLACE = 'replace'               # the stranded copy wins; displace the one in place
DECISIONS = (KEEP_EXISTING, REPLACE)


def apply_repair(local_root: str, plan: RepairPlan, allowed_paths: List[str],
                 decisions: Optional[Dict[str, str]] = None,
                 keep_a_copy=None) -> Dict:
    """
    Carry out a plan, one file at a time.

    Every source and destination is bounds-checked against the configured media
    directories before anything moves, and the destination is re-checked for an
    occupant immediately before the rename — the plan may have been sitting on
    someone's screen while a transfer ran.

    A file whose place is already taken is only touched if `decisions` names it,
    because which of two copies to keep is a judgement about quality that this
    code cannot make. Either way a media file is about to stop existing in the
    library, so `keep_a_copy(library_relative_path, absolute_path)` is called
    first and must return (ok, message); a false answer aborts that file and
    leaves both copies alone.

    A file that fails is reported and the rest still run.
    """
    moved: List[Dict] = []
    failed: List[Dict] = []
    deleted: List[Dict] = []
    replaced: List[Dict] = []
    directories_removed = 0
    decisions = decisions or {}

    def preserve(relative_path: str, absolute_path: str) -> Tuple[bool, str]:
        if keep_a_copy is None:
            return True, 'not requested'
        try:
            return keep_a_copy(relative_path, absolute_path)
        except Exception as error:  # noqa: BLE001 - a failure here must not delete
            return False, str(error)

    for action in plan.actions:
        decision = decisions.get(action.relative_path)

        if action.needs_decision and decision not in DECISIONS:
            failed.append({
                'relative_path': action.relative_path,
                'error': 'another copy of this is already in place and no choice was made',
            })
            continue

        source_rel = action.relative_path
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

        # "Keep what I already have." The stranded copy is redundant, so it is
        # captured into the backup area and then removed — never deleted
        # outright, because the judgement that the other copy is better is one
        # a person can regret.
        if action.needs_decision and decision == KEEP_EXISTING:
            ok, message = preserve(source_rel, source)
            if not ok:
                failed.append({
                    'relative_path': action.relative_path,
                    'error': f"could not keep a copy before deleting it: {message}",
                })
                continue
            try:
                os.remove(source)
            except OSError as error:
                failed.append({'relative_path': action.relative_path, 'error': str(error)})
                continue
            directories_removed += _prune_empty(os.path.dirname(source), local_root)
            deleted.append({
                'relative_path': action.relative_path,
                'kept_instead': action.rival.relative_path if action.rival else '',
                'size': action.size,
            })
            continue

        # "The stranded one is the better copy." The file in place is captured
        # and removed first, which frees the destination for the ordinary move
        # below — so this needs no separate move path of its own.
        if action.needs_decision and decision == REPLACE and action.rival:
            rival_abs = os.path.join(local_root, action.rival.relative_path)
            try:
                rival_abs = assert_path_within_bounds(rival_abs, allowed_paths)
            except PathTraversalError as error:
                failed.append({'relative_path': action.relative_path, 'error': str(error)})
                continue

            ok, message = preserve(action.rival.relative_path, rival_abs)
            if not ok:
                failed.append({
                    'relative_path': action.relative_path,
                    'error': f"could not keep the copy being replaced: {message}",
                })
                continue
            try:
                os.remove(rival_abs)
            except OSError as error:
                failed.append({'relative_path': action.relative_path, 'error': str(error)})
                continue
            replaced.append({
                'relative_path': action.rival.relative_path,
                'replaced_by': action.relative_path,
                'size': action.rival.size,
            })

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
        'deleted': deleted,
        'replaced': replaced,
        'failed': failed,
        'moved_count': len(moved),
        'deleted_count': len(deleted),
        'replaced_count': len(replaced),
        'failed_count': len(failed),
        'directories_removed': directories_removed,
        'moved_size': sum(entry['size'] for entry in moved),
        'freed_size': sum(entry['size'] for entry in deleted),
    }
