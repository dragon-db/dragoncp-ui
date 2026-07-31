#!/usr/bin/env python3
"""
Episode identity — the anchor the whole comparison hangs off.

Two files are "the same episode" when they carry the same season and episode
number, regardless of what the rest of the filename says. That is what lets us
notice an upgrade:

    local   Show - S01E23 - Title [WEBDL-1080p][OLD-Dragon DB].mkv
    remote  Show - S01E23 - Title [Bluray-2160p][NEW-Dragon DB].mkv

Same episode, different file, different name. Matching on filename would call
that "a file we don't have" and download it alongside the old one, leaving two
copies of S01E23 in the folder. Matching on identity calls it a replacement.

The rules here were derived from the real library, not from a spec. Four things
in that library would break a naive parser:

  * the series title sometimes carries the year and sometimes does not
      A.B.C. - S02E03 - An Episode Title [WEBDL-1080p][DUS-Dragon DB].mkv
      Another Series (2024) - S01E03 - A Third Episode [WEBDL-1080p][HONE].mkv
    -> never parse the title; anchor on the SxxExx code.

  * anime adds an absolute number after the code
      Example Anime (2018) - S01E24 - 024 - Another Episode Title [...].mkv
    -> the code still leads, the absolute number is extra.

  * season folders are not consistently padded ("Season 01" vs "Season 1"),
    and "Specials" exists
    -> compare season *numbers*, never folder strings.

  * some files predate the current naming
      Example Show - S01E15 - 1080p x265.mkv
    -> the code anchor still works, which is why we anchor on it.
"""

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

# Files that count as media. Every safety threshold and every episode count is
# based on these alone — the library holds roughly twice as many .nfo/.jpg
# files as episodes, so mixing them in would make the numbers meaningless.
MEDIA_EXTENSIONS = frozenset({
    '.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.flv', '.webm', '.ts', '.m2ts',
})

# Files that travel with the media but never drive a decision.
ANCILLARY_EXTENSIONS = frozenset({
    '.nfo', '.jpg', '.jpeg', '.png', '.srt', '.ass', '.sub', '.idx', '.txt', '.vtt',
})

# S01E23, s01e23, S1E23 — the primary anchor.
_CODE_RE = re.compile(r'[Ss](\d{1,4})[\s._-]?[Ee](\d{1,4})')

# Continuation of a multi-episode file, matched at a fixed offset immediately
# after the first code: S01E01E02, S01E01-E02, S01E01-02.
_MULTI_RE = re.compile(r'[\s._-]*(?:[Ee])?(\d{1,4})')

# Absolute-numbered anime that never went through Sonarr's rename, e.g.
# "[SubsPlease] Maou no Musume wa Yasashi Sugiru!! - 07 (1080p) [5F530970].mkv"
_ABSOLUTE_RE = re.compile(r'[\s._-]-[\s._-](\d{1,4})(?:v\d)?[\s._-]*[\(\[]')

# "Season 01", "Season 1", "season 2"
_SEASON_FOLDER_RE = re.compile(r'^season[\s._-]*(\d{1,4})$', re.IGNORECASE)


@dataclass(frozen=True, order=True)
class EpisodeKey:
    """A season/episode pair. Season 0 is Specials."""
    season: int
    episode: int

    def __str__(self) -> str:
        return f"S{self.season:02d}E{self.episode:02d}"


def is_media_file(name: str) -> bool:
    """True when the filename is a media file we make decisions about."""
    return os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS


def is_ancillary_file(name: str) -> bool:
    """True for artwork/metadata/subtitles — carried along, never counted."""
    return os.path.splitext(name)[1].lower() in ANCILLARY_EXTENSIONS


def season_number_from_folder(folder_name: Optional[str]) -> Optional[int]:
    """
    Season number from a season folder name.

    "Season 01" and "Season 1" both give 1 — the library contains both spellings
    and matching the strings would leave those seasons permanently unpaired.
    "Specials" is season 0, which is how Sonarr models it.
    """
    if not folder_name:
        return None

    name = folder_name.strip()
    if name.lower() == 'specials':
        return 0

    match = _SEASON_FOLDER_RE.match(name)
    if match:
        return int(match.group(1))
    return None


def parse_episode_keys(filename: str, season_hint: Optional[int] = None) -> Tuple[EpisodeKey, ...]:
    """
    Episode identities carried by a filename.

    Returns a tuple because one file can hold several episodes (S01E01E02); a
    double episode is "the same episode" as either of its halves, so both keys
    have to match. Returns an empty tuple when nothing can be parsed — the
    caller decides what to do with an unidentifiable file rather than this
    guessing.

    season_hint is the season number of the containing folder, used only by the
    absolute-numbering fallback.
    """
    if not filename:
        return ()

    stem = os.path.splitext(filename)[0]

    match = _CODE_RE.search(stem)
    if match:
        season = int(match.group(1))
        episodes = [int(match.group(2))]

        # Walk any immediately-following episode numbers so S01E01E02 and
        # S01E01-E02 both yield two keys. Anything separated by more than a
        # delimiter (the anime absolute number, " - 024 - ") is not a
        # continuation and must not be swallowed here.
        position = match.end()
        while True:
            more = _MULTI_RE.match(stem, position)
            if not more:
                break
            separator = stem[position:more.start(1)]
            # A bare "-024-" style separator with no 'E' is only a continuation
            # when it directly abuts the code; the anime absolute number is
            # padded and surrounded by spaces, which this rejects.
            if 'e' not in separator.lower() and separator.strip() not in ('-', ''):
                break
            if 'e' not in separator.lower() and len(more.group(1)) > 2:
                break
            episodes.append(int(more.group(1)))
            position = more.end()

        return tuple(EpisodeKey(season, ep) for ep in dict.fromkeys(episodes))

    # No SxxExx: fall back to absolute numbering for un-renamed anime. Only
    # usable when we know which season folder the file sits in.
    if season_hint is not None:
        absolute = _ABSOLUTE_RE.search(stem)
        if absolute:
            return (EpisodeKey(season_hint, int(absolute.group(1))),)

    return ()


def parse_absolute_number(filename: str) -> Optional[int]:
    """
    The anime absolute number, when the file carries one.

    Informational only — displayed in the UI, never used for matching, because
    absolute numbering is not present on TV files and is not always consistent
    across seasons.
    """
    stem = os.path.splitext(filename)[0]
    match = _CODE_RE.search(stem)
    if not match:
        return None
    tail = stem[match.end():]
    absolute = re.match(r'[\s._-]+(\d{1,4})[\s._-]', tail)
    return int(absolute.group(1)) if absolute else None


def split_library_path(relative_path: str) -> Tuple[str, Optional[str], str]:
    """
    Split a library-relative path into (series folder, season folder, filename).

    "Show (2024)/Season 01/ep.mkv" -> ("Show (2024)", "Season 01", "ep.mkv")
    "Movie (2024)/movie.mkv"       -> ("Movie (2024)", None, "movie.mkv")

    Anything deeper than series/season/file keeps its intermediate directories
    in the season slot so the path still round-trips.
    """
    parts = [p for p in relative_path.replace('\\', '/').split('/') if p]
    if not parts:
        return '', None, ''
    if len(parts) == 1:
        return '', None, parts[0]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    return parts[0], '/'.join(parts[1:-1]), parts[-1]
