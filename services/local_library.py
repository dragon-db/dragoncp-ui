#!/usr/bin/env python3
"""
What is actually on the disk, which is the only honest answer to "do we have it".

The library view first derived its answer from the `transfers` table, and that
was wrong in a way that made the whole screen untrustworthy: a transfer log says
what *this installation fetched*, not what is present. Files put there before
this application existed, fetched by hand, restored from a backup, or synced by
a different instance sharing the same disk all read as "never synced" while
sitting in the library the whole time.

On the machine this was written for that gap is not marginal. The library holds
381 folders; the development database records 12 transfers.

So presence is read from the filesystem, and the transfer log is demoted to what
it is actually good for — saying *when* and *how* something arrived.

Matching a service title to a folder
------------------------------------
The folder name is the title with the characters a filesystem cannot hold taken
out, and the sanitising is not even self-consistent — one colon became " - ",
another was dropped entirely:

    Example Show: The Sequel   ->   Example Show - The Sequel (2024)
    Another: Story             ->   Another Story (2021)

Reconstructing one from the other is therefore hopeless. Both sides are instead
reduced to letters and digits alone, which survives every sanitising rule seen
here, and the answer is written to `media_item.local_folder` so the match is
made once rather than guessed at every read.

Counting episodes, not files
----------------------------
Sonarr's per-season `episodeFileCount` counts *episodes* that have a file, so a
double episode in one file counts twice. Comparing that with a count of files
here made a season of double episodes look half missing. The scan therefore
also reads the SxxEyy code out of every file name and counts distinct episodes,
the same way Explore does, and remembers which file holds which episode so a
single title can be checked without walking the disk again.
"""

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from services.explore.identity import parse_episode_keys

#: What counts as media. Artwork, subtitles and `.nfo` files sit beside the
#: video and must not make an empty season folder look full.
VIDEO_EXTENSIONS = frozenset({
    '.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.ts', '.m2ts', '.mpg', '.mpeg',
})

#: Rescanned at most this often. A library walk is a few hundred `scandir` calls
#: — cheap, but not worth doing on every row of a rendering page.
CACHE_SECONDS = 60

_YEAR_SUFFIX = re.compile(r'\s*\((\d{4})\)\s*$')
_SEASON = re.compile(r'^(?:season|series)\s*(\d+)$|^s(\d+)$', re.IGNORECASE)


def normalise(title: str) -> str:
    """A title reduced to what survives being written to a disk.

    Letters and digits only, folded to lower case. Punctuation goes because the
    sanitising rules disagree about it; spacing goes with it, since removing a
    colon sometimes leaves two spaces and sometimes one.
    """
    if not title:
        return ''
    without_year = _YEAR_SUFFIX.sub('', str(title))
    return ''.join(ch for ch in without_year.lower() if ch.isalnum())


def year_of(folder_name: str) -> Optional[int]:
    """The year a folder name ends with, when it has one."""
    match = _YEAR_SUFFIX.search(folder_name or '')
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def season_number(folder_name: str) -> Optional[int]:
    """The season a subfolder names, or None if it names none."""
    match = _SEASON.match((folder_name or '').strip())
    if not match:
        return None
    digits = match.group(1) or match.group(2)
    try:
        return int(digits)
    except (TypeError, ValueError):
        return None


def season_of_folder(folder_name: str) -> Optional[int]:
    """Like `season_number`, and "Specials" is season 0, as Sonarr models it.

    Kept apart from `season_number` because the per-season file counts the
    auto-scanner reads have never included Specials, and changing what an
    existing field counts would change what the scanner does.
    """
    number = season_number(folder_name)
    if number is None and (folder_name or '').strip().lower() == 'specials':
        return 0
    return number


def episode_keys(file_name: str, folder_season: Optional[int]) -> Tuple[Tuple[int, int], ...]:
    """The (season, episode) pairs a media file holds, read from its name.

    A double episode ("S01E01E02") holds two. A name with no SxxEyy code falls
    back to an absolute number inside its season folder, which is how
    un-renamed anime is named; anything else holds none and is counted as one
    file of unknown episode by the caller.
    """
    return tuple((key.season, key.episode)
                 for key in parse_episode_keys(file_name, season_hint=folder_season))


def has_episode_code(file_name: str) -> bool:
    """Whether a name carries an SxxEyy code rather than only an absolute number."""
    return bool(parse_episode_keys(file_name))


class LocalLibrary:
    """The destination folders, walked and cached."""

    def __init__(self, config):
        self.config = config
        self._cache: Optional[Dict[str, Any]] = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def roots(self) -> List[Dict[str, str]]:
        """Where each library lives, skipping any that is unset or missing."""
        wanted = (
            ('movies', 'MOVIE_DEST_PATH'),
            ('tvshows', 'TVSHOW_DEST_PATH'),
            ('anime', 'ANIME_DEST_PATH'),
        )
        found = []
        for media_type, key in wanted:
            path = ''
            try:
                path = (self.config.get(key) or '').strip()
            except Exception:
                path = ''
            if path and os.path.isdir(path):
                found.append({'media_type': media_type, 'path': path})
        return found

    def scan(self, force: bool = False) -> Dict[str, Any]:
        """Every title folder, keyed by its normalised name.

        Returns a mapping rather than a list because every caller is asking the
        same question — "is this particular title here" — and doing that by
        scanning a list once per title turns a page render into a quadratic walk.
        """
        with self._lock:
            fresh = self._cache is not None and (time.time() - self._cached_at) < CACHE_SECONDS
            if fresh and not force:
                return self._cache

            index: Dict[str, Any] = {}
            for root in self.roots():
                try:
                    entries = list(os.scandir(root['path']))
                except OSError:
                    continue
                for entry in entries:
                    if not entry.is_dir() or entry.name.startswith('.'):
                        continue
                    record = self._read_title(entry, root['media_type'])
                    key = normalise(entry.name)
                    if not key:
                        continue
                    # A title present in two libraries — a show filed under both
                    # anime and tv_shows — keeps whichever holds files, because
                    # that is the one the question is about.
                    existing = index.get(key)
                    if existing is None or record['file_count'] > existing['file_count']:
                        index[key] = record

            self._cache = index
            self._cached_at = time.time()
            return index

    def _read_title(self, entry, media_type: str) -> Dict[str, Any]:
        """One title folder: its seasons, and how many media files and episodes each holds.

        `seasons` and `file_count` keep the meaning they have always had —
        media files per season folder, Specials not included — because the
        auto-scanner decides what to fetch from them. Everything added for the
        episode comparison sits in fields of its own.
        """
        seasons: Dict[int, int] = {}
        season_folders: Dict[int, str] = {}
        folder_files: Dict[int, int] = {}
        episodes: Dict[int, set] = {}
        unidentified: Dict[int, int] = {}
        episode_files: Dict[Tuple[int, int], List[str]] = {}
        loose_files = 0
        loose_media: List[Dict[str, Any]] = []
        try:
            for child in os.scandir(entry.path):
                if child.is_dir():
                    number = season_of_folder(child.name)
                    if number is None:
                        continue
                    names = self._media_names(child.path)
                    if season_number(child.name) is not None:
                        seasons[number] = len(names)
                    # Two folders for one season ("Season 1" beside "Season 01")
                    # are both read; the fuller one names the season.
                    if len(names) > folder_files.get(number, -1):
                        season_folders[number] = child.name
                        folder_files[number] = len(names)
                    for name in names:
                        keys = episode_keys(name, number)
                        if not keys:
                            unidentified[number] = unidentified.get(number, 0) + 1
                            continue
                        for key in keys:
                            episodes.setdefault(key[0], set()).add(key[1])
                            episode_files.setdefault(key, []).append(f"{child.name}/{name}")
                elif _is_media(child.name):
                    loose_files += 1
                    # Sizes only for files sitting in the title folder itself —
                    # a film. Statting every episode of every series on each
                    # rescan would cost more than the whole rest of the walk.
                    loose_media.append({'name': child.name, 'size': _size_of(child)})
        except OSError:
            pass

        # A file whose name carries no episode still holds one: counted as one
        # rather than none, so an oddly named season does not read as empty.
        episodes_here = {number: len(found) for number, found in episodes.items()}
        for number, count in unidentified.items():
            episodes_here[number] = episodes_here.get(number, 0) + count

        return {
            'folder': entry.name,
            'path': entry.path,
            'media_type': media_type,
            'year': year_of(entry.name),
            'seasons': seasons,
            'loose_files': loose_files,
            'file_count': loose_files + sum(seasons.values()),
            'season_folders': season_folders,
            'episodes_here': episodes_here,
            'episode_files': episode_files,
            'loose_media': loose_media,
        }

    @staticmethod
    def _media_names(path: str) -> List[str]:
        names: List[str] = []
        try:
            for child in os.scandir(path):
                if child.is_file() and _is_media(child.name):
                    names.append(child.name)
        except OSError:
            pass
        return names

    @staticmethod
    def _count_media(path: str) -> int:
        return len(LocalLibrary._media_names(path))

    def files_of(self, record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Every media file of one title folder, read fresh, with sizes.

        What the per-episode comparison is built from. Not cached: it is one
        folder, read when a person opens that title, and a cached answer could
        miss the episode that landed a minute ago — the very thing they opened
        it to check.
        """
        if not record or not record.get('path'):
            return None
        try:
            children = list(os.scandir(record['path']))
        except OSError:
            return None

        files: List[Dict[str, Any]] = []
        loose: List[Dict[str, Any]] = []
        season_folders: Dict[int, List[str]] = {}
        for child in sorted(children, key=lambda c: c.name):
            try:
                if child.is_dir():
                    number = season_of_folder(child.name)
                    if number is None:
                        continue
                    season_folders.setdefault(number, []).append(child.name)
                    for item in sorted(os.scandir(child.path), key=lambda c: c.name):
                        if not item.is_file() or not _is_media(item.name):
                            continue
                        files.append({
                            'name': item.name,
                            'relative_path': f"{child.name}/{item.name}",
                            'folder': child.name,
                            'folder_season': number,
                            'size': _size_of(item),
                            'keys': list(episode_keys(item.name, number)),
                            'coded': has_episode_code(item.name),
                        })
                elif child.is_file() and _is_media(child.name):
                    loose.append({'name': child.name, 'relative_path': child.name,
                                  'size': _size_of(child)})
            except OSError:
                continue

        return {
            'path': record['path'],
            'folder': record.get('folder'),
            'media_type': record.get('media_type'),
            'season_folders': season_folders,
            'files': files,
            'loose': loose,
        }

    def find(self, title: str, year: Optional[int] = None,
             folder: str = '') -> Optional[Dict[str, Any]]:
        """The folder holding a title, by stored name first and title second.

        A folder already recorded on the title wins outright: it was learned
        from a transfer that actually used it, which is stronger evidence than
        any name comparison.
        """
        index = self.scan()
        if folder:
            record = index.get(normalise(folder))
            if record:
                return record
        record = index.get(normalise(title))
        if record is None:
            return None
        # The year is a tie-breaker, not a requirement: plenty of folders carry
        # no year, and refusing those would report a present title as missing.
        if year and record.get('year') and int(record['year']) != int(year):
            return None
        return record


def _is_media(name: str) -> bool:
    return os.path.splitext(name or '')[1].lower() in VIDEO_EXTENSIONS


def _size_of(entry) -> int:
    try:
        return int(entry.stat().st_size)
    except OSError:
        return 0


#: Season folder -> (its modification time, its media files' sizes).
_SIZES: Dict[str, Tuple[int, List[int]]] = {}
_SIZES_LIMIT = 4096


def media_sizes_in(path: str) -> Optional[List[int]]:
    """The size of every media file directly inside one folder, or None.

    For the Library list's check of a season against the service's own size
    for it. Kept by the folder's modification time — adding, removing or
    renaming a file changes it, and rsync always renames a finished file into
    place (no `--inplace`) — so a list redrawn every few seconds costs one stat
    per season rather than one per episode.
    """
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return None
    cached = _SIZES.get(path)
    if cached is not None and cached[0] == stamp:
        return list(cached[1])
    sizes: List[int] = []
    try:
        for child in os.scandir(path):
            if child.is_file() and _is_media(child.name):
                sizes.append(int(child.stat().st_size))
    except OSError:
        return None
    if len(_SIZES) >= _SIZES_LIMIT:
        _SIZES.clear()
    _SIZES[path] = (stamp, sizes)
    return list(sizes)


def size_of_path(path: str) -> Optional[int]:
    """One file's size, or None when it cannot be read."""
    try:
        return int(os.stat(path).st_size)
    except OSError:
        return None
