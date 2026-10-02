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
"""

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

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
        """One title folder: its seasons, and how many media files each holds."""
        seasons: Dict[int, int] = {}
        loose_files = 0
        try:
            for child in os.scandir(entry.path):
                if child.is_dir():
                    number = season_number(child.name)
                    if number is None:
                        continue
                    seasons[number] = self._count_media(child.path)
                elif _is_media(child.name):
                    loose_files += 1
        except OSError:
            pass

        return {
            'folder': entry.name,
            'path': entry.path,
            'media_type': media_type,
            'year': year_of(entry.name),
            'seasons': seasons,
            'loose_files': loose_files,
            'file_count': loose_files + sum(seasons.values()),
        }

    @staticmethod
    def _count_media(path: str) -> int:
        total = 0
        try:
            for child in os.scandir(path):
                if child.is_file() and _is_media(child.name):
                    total += 1
        except OSError:
            pass
        return total

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
