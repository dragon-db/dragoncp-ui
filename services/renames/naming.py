#!/usr/bin/env python3
"""
Where an episode's title sits in a file name, and how Sonarr writes one.

Only the title is ever swapped. Quality, release group and audio languages stay
exactly as they are: a file Sonarr no longer holds cannot be asked about them,
and a title arriving does not change them.

    Example Show - S01E05 - TBA [WEBDL-1080p][GRP].mkv
    Example Show - S01E05 - The Real Title [WEBDL-1080p][GRP].mkv

    Example Anime (2024) - S01E05 - 005 - TBA [CF WEBDL-1080p][JA][GRP].mkv
    Example Anime (2024) - S01E05 - 005 - The Real Title [CF WEBDL-1080p][JA][GRP].mkv

The cleaning rules are Sonarr's `{Episode CleanTitle}` followed by its file
name rules. They were checked against every file Sonarr held on 2026-10-23,
the names it has and the names its rename preview would give: all 891 agreed.
"""

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services.explore.identity import is_media_file

#: What Sonarr writes when an episode has no title yet. It writes TBA; TBD is
#: what people type, and is treated the same.
PLACEHOLDER_TITLES = frozenset({'tba', 'tbd'})

#: A file name longer than this cannot be written on the media server's disk.
MAX_NAME_BYTES = 255

# The code and, for anime, the absolute number after it, then the title, then
# everything from the first " [" on. CleanTitle removes brackets from a title,
# so the first " [" is always where the title ends.
_SPLIT = re.compile(
    r'^(?P<head>.*?[Ss]\d{1,4}[Ee]\d{1,4}(?:-?[Ee]\d{1,4})*)'
    r'(?P<absolute> - \d{2,4}(?:-\d{2,4})?)?'
    r' - (?P<title>.+?)(?P<tail> \[.*)?$'
)

# Sonarr's CleanTitle, character for character: a separator standing alone
# between spaces, a quote, colon, question mark or comma that ends a word or a
# contraction, and every bracket.
_CLEAN_REMOVE = re.compile(
    r"(?<=\s)(,|<|>|\/|\\|;|:|'|\"|\||`|’|~|!|\?|@|\$|%|\^|\*|-|_|=){1}(?=\s)"
    r"|('|`|’|:|\?|,)(?=(?:(?:s|m|t|ve|ll|d|re)\s)|\s|$)"
    r"|(\(|\)|\[|\]|\{|\})",
    re.IGNORECASE,
)

# Sonarr collapses a run of the same separator to one: two spaces left by a
# removed dash become one, and "..." becomes ".".
_REPEATED_SEPARATOR = re.compile(r'([- ._])(\1)+')

# TMDB's name for an episode it has no title for.
_GENERIC_TITLE = re.compile(r'^(?:episode|ep\.?|chapter)\s*#?\d+$', re.IGNORECASE)

_ILLEGAL = ('\\', '/', '<', '>', '?', '*', '|', '"')
_ILLEGAL_REPLACED = ('+', '+', '', '', '!', '-', '', '')

#: Sonarr's ColonReplacementFormat, by number and by name.
_COLON_FORMATS = {
    0: 'delete', 1: 'dash', 2: 'spaceDash', 3: 'spaceDashSpace', 4: 'smart', 5: 'custom',
}


@dataclass(frozen=True)
class NamingRules:
    """The parts of Sonarr's naming settings that touch a title.

    The defaults are what this library is named with, so a series Sonarr does
    not have is named the way the rest of the library is.
    """

    replace_illegal: bool = True
    colon: str = 'smart'
    custom_colon: str = ''

    @classmethod
    def from_sonarr(cls, config: Optional[Dict[str, Any]]) -> 'NamingRules':
        if not isinstance(config, dict):
            return cls()
        colon = config.get('colonReplacementFormat', 'smart')
        if isinstance(colon, int) or str(colon).isdigit():
            colon = _COLON_FORMATS.get(int(colon), 'smart')
        return cls(
            replace_illegal=bool(config.get('replaceIllegalCharacters', True)),
            colon=str(colon or 'smart'),
            custom_colon=str(config.get('customColonReplacementFormat') or ''),
        )


@dataclass(frozen=True)
class NameParts:
    """A file name cut at its title."""

    head: str       # "Example Show - S01E05", or "... - S01E05 - 005" for anime
    title: str      # "TBA"
    tail: str       # " [WEBDL-1080p][GRP]", or "" when nothing follows the title
    extension: str  # ".mkv"

    def with_title(self, title: str) -> str:
        return f"{self.head} - {title}{self.tail}{self.extension}"


def split_name(name: str) -> Optional[NameParts]:
    """The parts of a media file name, or None when it does not follow the format."""
    if not name:
        return None
    stem, extension = os.path.splitext(name)
    match = _SPLIT.match(stem)
    if not match:
        return None
    title = match.group('title').strip()
    if not title:
        return None
    return NameParts(
        head=match.group('head') + (match.group('absolute') or ''),
        title=title,
        tail=match.group('tail') or '',
        extension=extension,
    )


def is_placeholder_title(title: Optional[str]) -> bool:
    return (title or '').strip().lower() in PLACEHOLDER_TITLES


def is_placeholder(name: str) -> bool:
    """Whether a media file still carries a placeholder where its title goes."""
    if not is_media_file(name):
        return False
    parts = split_name(name)
    return parts is not None and is_placeholder_title(parts.title)


def is_real_title(title: Optional[str]) -> bool:
    """A title worth renaming to: not empty, not TBA, not TMDB's "Episode 5"."""
    text = (title or '').strip()
    if not text or is_placeholder_title(text):
        return False
    return not _GENERIC_TITLE.match(text)


def clean_title(title: str) -> str:
    """Sonarr's `{Episode CleanTitle}` for one episode."""
    text = (title or '').rstrip(' .?')
    text = text.replace('&', 'and').replace('/', ' ')
    return _CLEAN_REMOVE.sub('', text)


def clean_file_name(text: str, rules: NamingRules = NamingRules()) -> str:
    """Sonarr's file name rules: colons and the characters a disk cannot hold."""
    result = text
    if rules.replace_illegal:
        if rules.colon == 'smart':
            result = result.replace(': ', ' - ').replace(':', '-')
        else:
            replacement = {
                'delete': '', 'dash': '-', 'spaceDash': ' -',
                'spaceDashSpace': ' - ', 'custom': rules.custom_colon,
            }.get(rules.colon, '')
            result = result.replace(':', replacement)
    else:
        result = result.replace(':', '')
    for bad, good in zip(_ILLEGAL, _ILLEGAL_REPLACED):
        result = result.replace(bad, good if rules.replace_illegal else '')
    return result


def episode_title(title: str, rules: NamingRules = NamingRules()) -> str:
    """A title as Sonarr would write it into a file name."""
    cleaned = clean_file_name(clean_title(title), rules)
    cleaned = _REPEATED_SEPARATOR.sub(lambda m: m.group(0)[0], cleaned)
    return cleaned.strip(' ').lstrip('.')


def retitle(name: str, title: str,
            rules: NamingRules = NamingRules()) -> Tuple[Optional[str], str]:
    """The name with its title swapped, or None and the reason in plain words."""
    parts = split_name(name)
    if parts is None:
        return None, "Its name doesn't follow the naming format, so it can't be renamed safely"
    written = episode_title(title, rules)
    if not written:
        return None, 'The title is empty once the characters a file name cannot hold are removed'
    new_name = parts.with_title(written)
    if len(new_name.encode('utf-8')) > MAX_NAME_BYTES:
        return None, 'The new name would be too long for the disk'
    return new_name, ''


def same_apart_from_title(first: str, second: str) -> bool:
    """Two names that differ in nothing but the title: the same file, named twice."""
    one, two = split_name(first), split_name(second)
    return bool(one and two and one.head == two.head and one.tail == two.tail
                and one.extension.lower() == two.extension.lower())


def title_of(name: str) -> Optional[str]:
    parts = split_name(name)
    return parts.title if parts else None


def sidecars(video_name: str, new_video_name: str,
             siblings: Iterable[str]) -> List[Tuple[str, str]]:
    """The files that travel with a video: subtitles, `.nfo`, artwork.

    Every other file in the folder whose name starts with the video's base name
    followed by "." or "-" — `.nfo`, `.en.srt`, `-thumb.jpg` — gets the new base
    name. Another video is never one of them, whatever it is called.
    """
    old_stem = os.path.splitext(video_name)[0]
    new_stem = os.path.splitext(new_video_name)[0]
    out = []
    for sibling in sorted(siblings):
        if sibling == video_name or is_media_file(sibling):
            continue
        if len(sibling) > len(old_stem) and sibling.startswith(old_stem) \
                and sibling[len(old_stem)] in '.-':
            out.append((sibling, new_stem + sibling[len(old_stem):]))
    return out


def normalise_unicode(name: str) -> str:
    """NFC, so the same name typed two ways compares equal."""
    return unicodedata.normalize('NFC', name or '')
