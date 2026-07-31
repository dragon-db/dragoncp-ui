#!/usr/bin/env python3
"""
Comparison — line the two libraries up and label every episode.

Four labels, and every decision in Explore is built from them:

    IN_SYNC     same episode both sides, same size
    MISSING     on the remote, not local            -> download
    UPGRADED    both sides, different file          -> replace (back up the old one)
    LOCAL_ONLY  local, not on the remote            -> removal candidate, never silent

Two rules that are easy to get wrong and matter a lot:

*   Seasons are paired by NUMBER, not by folder name. The library contains both
    "Season 01" and "Season 1", and "Specials" is season 0. Pairing on the
    string leaves those seasons permanently unmatched, which would read as
    "everything is missing".

*   A local file whose episode matches but whose NAME differs is only an upgrade
    when the size differs too. Sonarr renames files without changing content; if
    we called a rename an upgrade we would re-download the whole library, and if
    we called it "missing" we would download a second copy alongside it.

Status roll-up:

    SYNCED        nothing missing, nothing upgraded
    PARTIAL_SYNC  you have some of it, but not all or not current
    OUT_OF_SYNC   you have none of what the remote holds
    NO_INFO       the remote side holds nothing to compare against

LOCAL_ONLY files deliberately do NOT push a season out of SYNCED. "In sync with
the remote" means you hold everything the remote holds; files the remote has
since dropped are a separate fact, surfaced as their own count and warned about
loudly at sync time (that is the scenario where a mirror would delete them).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .identity import EpisodeKey
from .inventory import FileEntry, Inventory

IN_SYNC = 'IN_SYNC'
MISSING = 'MISSING'
UPGRADED = 'UPGRADED'
LOCAL_ONLY = 'LOCAL_ONLY'

SYNCED = 'SYNCED'
PARTIAL_SYNC = 'PARTIAL_SYNC'
OUT_OF_SYNC = 'OUT_OF_SYNC'
NO_INFO = 'NO_INFO'


@dataclass
class EpisodeDiff:
    """What should happen to one episode (or one un-numbered media file)."""
    label: str
    key: Optional[EpisodeKey] = None
    remote: Optional[FileEntry] = None
    local: Optional[FileEntry] = None
    renamed: bool = False  # same content, different filename — left alone

    @property
    def code(self) -> str:
        if self.key:
            return str(self.key)
        entry = self.remote or self.local
        return entry.name if entry else ''

    @property
    def size(self) -> int:
        entry = self.remote or self.local
        return entry.size if entry else 0

    def to_dict(self) -> Dict:
        return {
            'label': self.label,
            'code': self.code,
            'season': self.key.season if self.key else None,
            'episode': self.key.episode if self.key else None,
            'renamed': self.renamed,
            'remote_name': self.remote.name if self.remote else None,
            'remote_size': self.remote.size if self.remote else None,
            'remote_mtime': self.remote.mtime if self.remote else None,
            'remote_path': self.remote.relative_path if self.remote else None,
            'local_name': self.local.name if self.local else None,
            'local_size': self.local.size if self.local else None,
            'local_mtime': self.local.mtime if self.local else None,
            'local_path': self.local.relative_path if self.local else None,
            'absolute_number': (self.remote or self.local).absolute_number if (self.remote or self.local) else None,
        }


@dataclass
class Counts:
    in_sync: int = 0
    missing: int = 0
    upgraded: int = 0
    local_only: int = 0

    # bytes that would move if this scope were synced
    incoming_bytes: int = 0
    # bytes that would be moved to backup if local extras were removed
    removable_bytes: int = 0

    def add(self, other: 'Counts') -> 'Counts':
        return Counts(
            in_sync=self.in_sync + other.in_sync,
            missing=self.missing + other.missing,
            upgraded=self.upgraded + other.upgraded,
            local_only=self.local_only + other.local_only,
            incoming_bytes=self.incoming_bytes + other.incoming_bytes,
            removable_bytes=self.removable_bytes + other.removable_bytes,
        )

    @property
    def remote_total(self) -> int:
        return self.in_sync + self.missing + self.upgraded

    def status(self) -> str:
        if self.remote_total == 0:
            return NO_INFO
        if self.missing == 0 and self.upgraded == 0:
            return SYNCED
        if self.in_sync > 0:
            return PARTIAL_SYNC
        return OUT_OF_SYNC

    def to_dict(self) -> Dict:
        return {
            'in_sync': self.in_sync,
            'missing': self.missing,
            'upgraded': self.upgraded,
            'local_only': self.local_only,
            'remote_total': self.remote_total,
            'incoming_bytes': self.incoming_bytes,
            'removable_bytes': self.removable_bytes,
        }


@dataclass
class SeasonDiff:
    series: str
    season: Optional[int]
    remote_folder: Optional[str]
    local_folder: Optional[str]
    counts: Counts = field(default_factory=Counts)
    episodes: List[EpisodeDiff] = field(default_factory=list)
    ancillary_missing: int = 0
    ancillary_local_only: int = 0
    misplaced: List[str] = field(default_factory=list)
    remote_bytes: int = 0
    local_bytes: int = 0
    remote_mtime: int = 0

    @property
    def status(self) -> str:
        return self.counts.status()

    @property
    def display_name(self) -> str:
        if self.remote_folder or self.local_folder:
            return self.remote_folder or self.local_folder
        if self.season == 0:
            return 'Specials'
        if self.season is not None:
            return f"Season {self.season:02d}"
        return 'Files'

    @property
    def standard_name(self) -> Optional[str]:
        """What Sonarr would call this folder: `Season {season:00}`."""
        if self.season is None:
            return None
        return 'Specials' if self.season == 0 else f"Season {self.season:02d}"

    @property
    def odd_folders(self) -> List[str]:
        """
        Folder names on either side that are not what Sonarr would write.

        Nothing here is broken — seasons pair by NUMBER, so "Season 1" lines up
        with "Season 01" and syncs correctly into whichever spelling is already
        there. It is reported so the drift is visible and can be tidied up,
        rather than being discovered later.
        """
        expected = self.standard_name
        if expected is None:
            return []
        return sorted({folder for folder in (self.remote_folder, self.local_folder)
                       if folder and folder != expected})

    def to_dict(self, include_episodes: bool = False) -> Dict:
        data = {
            'standard_name': self.standard_name,
            'odd_folders': self.odd_folders,
            'series': self.series,
            'season': self.season,
            'name': self.display_name,
            'remote_folder': self.remote_folder,
            'local_folder': self.local_folder,
            'status': self.status,
            'counts': self.counts.to_dict(),
            'ancillary_missing': self.ancillary_missing,
            'ancillary_local_only': self.ancillary_local_only,
            'misplaced': self.misplaced,
            'remote_bytes': self.remote_bytes,
            'local_bytes': self.local_bytes,
            'remote_mtime': self.remote_mtime,
        }
        if include_episodes:
            data['episodes'] = [e.to_dict() for e in self.episodes]
        return data


@dataclass
class SeriesDiff:
    series: str
    media_type: str
    seasons: List[SeasonDiff] = field(default_factory=list)
    exists_locally: bool = False
    remote_bytes: int = 0
    local_bytes: int = 0
    remote_mtime: int = 0

    @property
    def counts(self) -> Counts:
        total = Counts()
        for season in self.seasons:
            total = total.add(season.counts)
        return total

    @property
    def status(self) -> str:
        return self.counts.status()

    @property
    def misplaced(self) -> List[str]:
        out: List[str] = []
        for season in self.seasons:
            out.extend(season.misplaced)
        return out

    @property
    def odd_folders(self) -> List[str]:
        """Season folders on either side that Sonarr would have named differently."""
        out: List[str] = []
        for season in self.seasons:
            out.extend(season.odd_folders)
        return sorted(set(out))

    def to_dict(self, include_seasons: bool = False) -> Dict:
        data = {
            'name': self.series,
            'media_type': self.media_type,
            'status': self.status,
            'counts': self.counts.to_dict(),
            'season_count': len(self.seasons),
            'exists_locally': self.exists_locally,
            'remote_bytes': self.remote_bytes,
            'local_bytes': self.local_bytes,
            'remote_mtime': self.remote_mtime,
            'misplaced_count': len(self.misplaced),
            'odd_folders': self.odd_folders,
        }
        if include_seasons:
            data['seasons'] = [s.to_dict() for s in self.seasons]
        return data


@dataclass
class LibraryDiff:
    media_type: str
    series: List[SeriesDiff] = field(default_factory=list)
    remote_ok: bool = True
    local_ok: bool = True
    remote_error: Optional[str] = None
    local_error: Optional[str] = None

    def find(self, series_name: str) -> Optional[SeriesDiff]:
        for entry in self.series:
            if entry.series == series_name:
                return entry
        return None

    def to_dict(self) -> Dict:
        return {
            'media_type': self.media_type,
            'remote_ok': self.remote_ok,
            'local_ok': self.local_ok,
            'remote_error': self.remote_error,
            'local_error': self.local_error,
            'series': [s.to_dict() for s in self.series],
        }


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

def _by_key(entries: List[FileEntry]) -> Dict[EpisodeKey, List[FileEntry]]:
    mapping: Dict[EpisodeKey, List[FileEntry]] = {}
    for entry in entries:
        for key in entry.keys:
            mapping.setdefault(key, []).append(entry)
    return mapping


def _unkeyed(entries: List[FileEntry]) -> List[FileEntry]:
    return [e for e in entries if e.is_media and not e.keys]


def _pick_match(remote: FileEntry, candidates: List[FileEntry]) -> Tuple[FileEntry, bool]:
    """
    Choose the local file that corresponds to a remote episode.

    A same-size candidate means the content is already there — possibly under a
    different name after a rename, which is not something to re-download.
    Otherwise the newest candidate is the one being superseded.
    """
    for candidate in candidates:
        if candidate.size == remote.size:
            return candidate, True
    return max(candidates, key=lambda c: c.mtime), False


def compare_season(media_type: str, series: str, season: Optional[int],
                   remote_entries: List[FileEntry], local_entries: List[FileEntry],
                   remote_folder: Optional[str],
                   local_folder: Optional[str]) -> SeasonDiff:
    """Compare one season (or, for movies, one movie folder)."""
    diff = SeasonDiff(
        series=series, season=season,
        remote_folder=remote_folder, local_folder=local_folder,
    )

    remote_media = [e for e in remote_entries if e.is_media]
    local_media = [e for e in local_entries if e.is_media]

    diff.remote_bytes = sum(e.size for e in remote_media)
    diff.local_bytes = sum(e.size for e in local_media)
    diff.remote_mtime = max((e.mtime for e in remote_entries), default=0)
    diff.misplaced = sorted(e.relative_path for e in local_media if e.misplaced)

    remote_keys = _by_key(remote_media)
    local_keys = _by_key(local_media)
    matched_local: set = set()

    for key in sorted(remote_keys):
        remote_file = remote_keys[key][0]
        candidates = local_keys.get(key, [])
        if candidates:
            local_file, same_size = _pick_match(remote_file, candidates)
            matched_local.add(local_file.relative_path)
            if same_size:
                diff.episodes.append(EpisodeDiff(
                    label=IN_SYNC, key=key, remote=remote_file, local=local_file,
                    renamed=local_file.name != remote_file.name,
                ))
                diff.counts.in_sync += 1
            else:
                diff.episodes.append(EpisodeDiff(
                    label=UPGRADED, key=key, remote=remote_file, local=local_file,
                ))
                diff.counts.upgraded += 1
                diff.counts.incoming_bytes += remote_file.size
        else:
            diff.episodes.append(EpisodeDiff(label=MISSING, key=key, remote=remote_file))
            diff.counts.missing += 1
            diff.counts.incoming_bytes += remote_file.size

    # Local episodes the remote does not have.
    for key in sorted(local_keys):
        if key in remote_keys:
            continue
        for entry in local_keys[key]:
            if entry.relative_path in matched_local:
                continue
            matched_local.add(entry.relative_path)
            diff.episodes.append(EpisodeDiff(label=LOCAL_ONLY, key=key, local=entry))
            diff.counts.local_only += 1
            diff.counts.removable_bytes += entry.size

    # Media files carrying no episode number (movies, extras). Matched by name;
    # for movies the "main file" rule turns a name change into an upgrade rather
    # than a download-plus-leftover.
    remote_plain = {e.name: e for e in _unkeyed(remote_media)}
    local_plain = {e.name: e for e in _unkeyed(local_media)
                   if e.relative_path not in matched_local}

    remote_only_names = [n for n in remote_plain if n not in local_plain]
    local_only_names = [n for n in local_plain if n not in remote_plain]

    treated_as_upgrade = False
    if media_type == 'movies' and len(remote_only_names) == 1 and len(local_only_names) == 1:
        remote_file = remote_plain[remote_only_names[0]]
        local_file = local_plain[local_only_names[0]]
        # Only when both are the folder's main (largest) media file.
        if (remote_file.size == max(e.size for e in remote_media)
                and local_file.size == max(e.size for e in local_media)):
            diff.episodes.append(EpisodeDiff(
                label=UPGRADED, remote=remote_file, local=local_file))
            diff.counts.upgraded += 1
            diff.counts.incoming_bytes += remote_file.size
            treated_as_upgrade = True

    if not treated_as_upgrade:
        for name in remote_only_names:
            remote_file = remote_plain[name]
            diff.episodes.append(EpisodeDiff(label=MISSING, remote=remote_file))
            diff.counts.missing += 1
            diff.counts.incoming_bytes += remote_file.size
        for name in local_only_names:
            local_file = local_plain[name]
            diff.episodes.append(EpisodeDiff(label=LOCAL_ONLY, local=local_file))
            diff.counts.local_only += 1
            diff.counts.removable_bytes += local_file.size

    for name, remote_file in remote_plain.items():
        if name not in local_plain:
            continue
        local_file = local_plain[name]
        if local_file.size == remote_file.size:
            diff.episodes.append(EpisodeDiff(
                label=IN_SYNC, remote=remote_file, local=local_file))
            diff.counts.in_sync += 1
        else:
            diff.episodes.append(EpisodeDiff(
                label=UPGRADED, remote=remote_file, local=local_file))
            diff.counts.upgraded += 1
            diff.counts.incoming_bytes += remote_file.size

    # Artwork, subtitles and metadata: counted, never decisive.
    remote_extra = {e.name for e in remote_entries if e.is_ancillary}
    local_extra = {e.name for e in local_entries if e.is_ancillary}
    diff.ancillary_missing = len(remote_extra - local_extra)
    diff.ancillary_local_only = len(local_extra - remote_extra)

    return diff


def _season_pairs(media_type: str, remote: Inventory, local: Inventory,
                  series: str) -> List[Tuple[Optional[int], Optional[str], Optional[str]]]:
    """
    Pair remote and local season folders by season NUMBER.

    "Season 01" on one side and "Season 1" on the other are the same season; so
    are "Specials" and "Season 00". Folders whose name yields no number are
    paired by their literal name so nothing silently disappears.
    """
    if media_type == 'movies':
        return [(None, None, None)]

    remote_folders = remote.season_folders(series)
    local_folders = local.season_folders(series)

    from .identity import season_number_from_folder

    remote_by_number: Dict[int, str] = {}
    remote_unnumbered: List[str] = []
    for folder in remote_folders:
        number = season_number_from_folder(folder)
        if number is None:
            remote_unnumbered.append(folder)
        else:
            remote_by_number.setdefault(number, folder)

    local_by_number: Dict[int, str] = {}
    local_unnumbered: List[str] = []
    for folder in local_folders:
        number = season_number_from_folder(folder)
        if number is None:
            local_unnumbered.append(folder)
        else:
            local_by_number.setdefault(number, folder)

    pairs: List[Tuple[Optional[int], Optional[str], Optional[str]]] = []
    for number in sorted(set(remote_by_number) | set(local_by_number)):
        pairs.append((number, remote_by_number.get(number), local_by_number.get(number)))

    for folder in sorted(set(remote_unnumbered) | set(local_unnumbered)):
        pairs.append((
            None,
            folder if folder in remote_unnumbered else None,
            folder if folder in local_unnumbered else None,
        ))

    return pairs


def compare_series(media_type: str, remote: Inventory, local: Inventory,
                   series: str) -> SeriesDiff:
    """Compare one series (or one movie folder) across all its seasons."""
    result = SeriesDiff(series=series, media_type=media_type)
    result.exists_locally = series in set(local.series_names())

    for season, remote_folder, local_folder in _season_pairs(media_type, remote, local, series):
        remote_entries = remote.in_season(series, remote_folder) if remote_folder is not None or media_type == 'movies' else []
        local_entries = local.in_season(series, local_folder) if local_folder is not None or media_type == 'movies' else []

        # For movies the season slot is None; in_season(None) returns files
        # sitting directly in the movie folder, which is what we want.
        season_diff = compare_season(
            media_type, series, season,
            remote_entries, local_entries,
            remote_folder, local_folder,
        )
        # Skip season folders that hold nothing at all on either side.
        if season_diff.counts.remote_total or season_diff.counts.local_only or season_diff.misplaced:
            result.seasons.append(season_diff)

    result.remote_bytes = sum(s.remote_bytes for s in result.seasons)
    result.local_bytes = sum(s.local_bytes for s in result.seasons)
    result.remote_mtime = max((s.remote_mtime for s in result.seasons), default=0)
    return result


def compare_library(media_type: str, remote: Inventory, local: Inventory) -> LibraryDiff:
    """Compare a whole library."""
    diff = LibraryDiff(
        media_type=media_type,
        remote_ok=remote.exists, local_ok=local.exists,
        remote_error=remote.error, local_error=local.error,
    )

    names = sorted(set(remote.series_names()) | set(local.series_names()))
    for name in names:
        diff.series.append(compare_series(media_type, remote, local, name))
    return diff
