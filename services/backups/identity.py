#!/usr/bin/env python3
"""
What a displaced file is — the slot it belongs to.

A slot is one movie, or one episode of one series. It is the unit everything
else hangs off: files group into it, versions stack inside it, retention counts
per it, and a restore targets it.

Episode parsing is NOT reimplemented here. `services/explore/identity.py`
already derives its rules from the real library and handles the four things
that break naive parsers — titles that sometimes carry a year, anime absolute
numbers, "Season 01" versus "Season 1", Specials, and multi-episode files. A
second parser would be a second set of bugs, and the previous backup code was
exactly that: it split filenames at the first " - " to get a series title,
which mis-parses any title containing one.

What IS added here is the movie half, which the episode-shaped parser has no
notion of, and the naming rules for the tree.
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

from services.explore.identity import (
    EpisodeKey,
    is_ancillary_file,
    is_media_file,
    parse_episode_keys,
    season_number_from_folder,
    split_library_path,
)

# The three libraries, and how the rest of the application spells them.
# `media_type` is the application's word; `library` is the folder in the tree.
_MEDIA_TYPE_TO_LIBRARY = {
    'movies': 'movies',
    'tvshows': 'shows',
    'series': 'shows',
    'anime': 'anime',
}

_LIBRARY_TO_MEDIA_TYPE = {
    'movies': 'movies',
    'shows': 'tvshows',
    'anime': 'anime',
}

LIBRARIES = ('movies', 'shows', 'anime')

# "Title (2024)" at the start of a name. The year is what makes a movie
# identity precise — two films share a title often enough that dropping it
# would let a restore target the wrong one.
_MOVIE_RE = re.compile(r'^(.+?)\s*\((\d{4})\)')

# Any four-digit year in brackets, used when the name does not lead with one.
_ANY_YEAR_RE = re.compile(r'\((\d{4})\)')


def library_for_media_type(media_type: Optional[str]) -> Optional[str]:
    """'tvshows' -> 'shows'. None when the media type is unknown."""
    return _MEDIA_TYPE_TO_LIBRARY.get((media_type or '').strip().lower())


def media_type_for_library(library: Optional[str]) -> Optional[str]:
    """'shows' -> 'tvshows'. The inverse, for talking to the rest of the app."""
    return _LIBRARY_TO_MEDIA_TYPE.get((library or '').strip().lower())


def parse_movie_identity(folder_name: str, filename: str = '') -> Tuple[str, Optional[str]]:
    """
    Title and release year for a movie.

    The library folder is the better source and is tried first: Radarr names it
    "Title (2024)" and it stays stable while the file inside may carry quality
    tags, edition markers or a scene name. The filename is only consulted when
    the folder yields nothing.

    Returns (title, year). Year is None when no four-digit year is present
    anywhere — the slot is still usable, just less precise.
    """
    for candidate in (folder_name or '', os.path.splitext(filename or '')[0]):
        candidate = candidate.strip()
        if not candidate:
            continue
        match = _MOVIE_RE.match(candidate)
        if match:
            return match.group(1).strip(), match.group(2)

    # No "Title (Year)" shape. Fall back to the folder as the title and any
    # year found anywhere in either string.
    title = (folder_name or '').strip() or os.path.splitext(filename or '')[0].strip()
    year_match = _ANY_YEAR_RE.search(folder_name or '') or _ANY_YEAR_RE.search(filename or '')
    return title, (year_match.group(1) if year_match else None)


def normalise_key_part(value: Optional[str]) -> str:
    """Lowercase, alphanumeric-and-underscore. Used only for match keys."""
    if not value:
        return ''
    return re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_')


def season_folder_name(season: Optional[int]) -> Optional[str]:
    """
    Canonical season folder for the tree.

    Always padded, and always "Specials" for season 0. The library itself
    contains both "Season 01" and "Season 1"; inheriting that inconsistency
    would mean one episode's history could end up split across two folders.
    """
    if season is None:
        return None
    if season == 0:
        return 'Specials'
    return f"Season {season:02d}"


def slot_folder_name(season: Optional[int], episode: Optional[int]) -> Optional[str]:
    """'S01E01'. None when the file carries no episode identity."""
    if season is None or episode is None:
        return None
    return f"S{season:02d}E{episode:02d}"


@dataclass(frozen=True)
class SlotIdentity:
    """
    One movie, or one episode of one series.

    `keys` holds every episode a file claims. It normally has one entry; a
    double episode (S01E01E02) has two, and the capture is then reachable from
    both slots without being stored twice. `keys` is empty for movies.
    """
    library: str                      # movies | shows | anime
    title: str                        # library folder name, as on disk
    season: Optional[int] = None
    episode: Optional[int] = None
    year: Optional[str] = None        # movies only
    keys: Tuple[EpisodeKey, ...] = ()

    @property
    def is_movie(self) -> bool:
        return self.library == 'movies'

    @property
    def season_folder(self) -> Optional[str]:
        return season_folder_name(self.season)

    @property
    def slot_folder(self) -> Optional[str]:
        return slot_folder_name(self.season, self.episode)

    @property
    def slot_key(self) -> str:
        """
        Stable match key. Two files describing the same episode produce the
        same key regardless of how they are named.

            shows|example_show|S01E01
            movies|example_film|Y2024
        """
        title = normalise_key_part(self.title)
        if self.is_movie:
            return f"movies|{title}|Y{self.year or ''}"
        code = self.slot_folder or 'UNKNOWN'
        return f"{self.library}|{title}|{code}"

    def key_for(self, key: EpisodeKey) -> str:
        """The slot key for one of a multi-episode file's episodes."""
        return f"{self.library}|{normalise_key_part(self.title)}|{key}"

    @property
    def all_slot_keys(self) -> Tuple[str, ...]:
        """Every slot this identity belongs to. One entry unless multi-episode."""
        if self.is_movie or not self.keys:
            return (self.slot_key,)
        return tuple(dict.fromkeys(self.key_for(key) for key in self.keys))

    @property
    def display(self) -> str:
        """Human label. 'Example Show — S01E01', 'Example Film (2024)'."""
        if self.is_movie:
            return f"{self.title} ({self.year})" if self.year else self.title
        code = self.slot_folder
        return f"{self.title} — {code}" if code else self.title


@dataclass(frozen=True)
class CaptureId:
    """
    Identifies one capture, and names its folder.

    `<UTC timestamp>__<short ref>`. The timestamp orders versions inside a slot;
    the short ref ties the capture back to whatever produced it and keeps two
    captures in the same second apart.
    """
    value: str

    def __str__(self) -> str:
        return self.value


_CAPTURE_RE = re.compile(r'^(\d{8}T\d{6}\.\d{3}Z)__([A-Za-z0-9]{1,16})(?:__(\d+))?$')

_STAMP_FORMAT = '%Y%m%dT%H%M%S.%fZ'


def new_capture_id(source_ref: Optional[str] = None,
                   moment: Optional[datetime] = None) -> CaptureId:
    """
    Build a capture id.

    Milliseconds are part of the stamp, not decoration. Versions inside a slot
    are ordered by it, and a sync followed immediately by a restore of the same
    episode would otherwise produce two captures that cannot be told apart —
    which is exactly the pair whose order matters most.

    `source_ref` is normally a transfer id; only its trailing alphanumerics are
    kept, because the full id is long and the folder name has to stay readable.
    """
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    stamp = f"{moment.strftime('%Y%m%dT%H%M%S')}.{moment.microsecond // 1000:03d}Z"

    ref = re.sub(r'[^A-Za-z0-9]', '', source_ref or '')[-8:] or 'manual'
    return CaptureId(f"{stamp}__{ref}")


def parse_capture_id(name: str) -> Optional[Tuple[datetime, str]]:
    """
    Read a capture folder name back.

    Returns (captured_at, source_ref), or None when the name is not a capture
    folder — which is how the rebuild scan tells captures from anything else
    that has found its way into the tree.
    """
    match = _CAPTURE_RE.match(name or '')
    if not match:
        return None
    try:
        moment = datetime.strptime(match.group(1), _STAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return moment, match.group(2)


def identify(library: str, library_relative_path: str) -> Optional[SlotIdentity]:
    """
    Work out which slot a file belongs to from its path within the library.

    `library_relative_path` is the path the file had (or would have had) under
    the media root: "Example Show/Season 01/Example Show - S01E01 - Title.mkv".

    Returns None when the file carries no usable identity — an episode file
    with no parseable code, or artwork that belongs to no single episode. The
    caller decides what to do with it rather than this guessing; the sorter
    files it under `_unsorted/` where it stays recoverable and can be re-sorted
    later once the parser improves.
    """
    if not library_relative_path:
        return None

    series, season_path, filename = split_library_path(library_relative_path)
    if not filename:
        return None

    if library == 'movies':
        # A movie folder is itself the slot. Every file inside it — the video,
        # the .nfo, the artwork — belongs to that one movie, so nothing here
        # needs to parse the filename to be placed.
        title = series or os.path.splitext(filename)[0]
        movie_title, year = parse_movie_identity(series, filename)
        return SlotIdentity(
            library='movies',
            title=title,
            year=year,
        ) if movie_title else None

    if not series:
        return None

    season_folder = season_path.split('/')[0] if season_path else None
    season_hint = season_number_from_folder(season_folder)

    keys = parse_episode_keys(filename, season_hint)
    if not keys:
        return None

    first = keys[0]
    return SlotIdentity(
        library=library,
        title=series,
        season=first.season,
        episode=first.episode,
        keys=keys,
    )


def title_of(library: str, library_relative_path: str) -> Optional[str]:
    """
    The title folder a file sits under, when it has one.

    Used for files that belong to a title but to no single episode — season
    artwork, a series-level `.nfo`. They are worth keeping beside the title
    rather than in the unsorted bucket, but they are never a slot's occupant.
    """
    if not library_relative_path or library == 'movies':
        return None
    series, _season_path, filename = split_library_path(library_relative_path)
    return series if series and filename else None


def is_media(filename: str) -> bool:
    """Video files — what a slot's occupant actually is."""
    return is_media_file(filename)


def is_sidecar(filename: str) -> bool:
    """Subtitles, metadata and artwork — carried along, never the occupant."""
    return is_ancillary_file(filename)
