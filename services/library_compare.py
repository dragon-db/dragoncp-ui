#!/usr/bin/env python3
"""
One title, episode by episode: what the service holds against what is here.

The library list used to call a series "Synced" when every season the service
had files for had *some* file here. That answered the wrong question. A Sonarr
whose media server deletes what has been synced holds one file for a season —
the newest episode, E08 — while this disk holds E01 to E07: "some file here"
was true, and E08 was not here. Explore said so, because it compares file by
file. This module is that comparison for one title, built from what the service
says it holds rather than from a remote folder listing:

    in_sync         the service has a file, and the same file (same size) is here
    different       both have the episode and the sizes differ — an upgrade over
                    there, or a different release
    missing_here    the service has a file and nothing is here: needs syncing
    nested          here, but only in a folder below the season folder
                    (`Season 01/ep.mkv/ep.mkv`), where a media server cannot
                    see it. Not missing — copying it again would not make it
                    visible — and not in sync: Explore's Repair moves it.
    only_here       here, and the service has no file — normal once the media
                    server has cleaned up after a sync; not a problem
    not_downloaded  neither side has it, aired or not — not a problem either

A title is out of sync exactly when one of its episodes is `missing_here` or
`different`. One with nothing else wrong but a file in a nested folder needs
repair — Explore's word for the same thing. Specials (season 0) are compared and shown, never counted: most
libraries leave them out on purpose, and a warning nobody can clear is one
everybody learns to ignore.

Everything here is pure — lists in, dicts out — so it is tested without a
service, a disk or a database.
"""

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

# -- one episode -------------------------------------------------------------

IN_SYNC = 'in_sync'
DIFFERENT = 'different'
MISSING_HERE = 'missing_here'
NESTED = 'nested'
ONLY_HERE = 'only_here'
NOT_DOWNLOADED = 'not_downloaded'

#: In the order a person wants to read them: what needs doing first.
EPISODE_STATES = (MISSING_HERE, DIFFERENT, NESTED, IN_SYNC, ONLY_HERE, NOT_DOWNLOADED)
NEEDS_SYNC = frozenset({MISSING_HERE, DIFFERENT})

# -- one title, in the list's words -------------------------------------------

OUT_OF_SYNC = 'out_of_sync'
NEEDS_REPAIR = 'needs_repair'
TITLE_IN_SYNC = 'in_sync'
KEPT_HERE = 'kept_here'
NEVER = 'never'
NO_FILES = 'no_files'
ORPHAN = 'orphan'
UNKNOWN = 'unknown'

#: How a film's single comparison reads as a title state.
MOVIE_TITLE_STATE = {
    IN_SYNC: TITLE_IN_SYNC,
    DIFFERENT: OUT_OF_SYNC,
    MISSING_HERE: NEVER,
    NESTED: NEEDS_REPAIR,
    ONLY_HERE: KEPT_HERE,
    NOT_DOWNLOADED: NO_FILES,
}


def episode_code(season: Optional[int], episode: Optional[int]) -> str:
    """"S01E08" — the form Explore, the file names and this screen all share."""
    if season is None:
        return ''
    if episode is None:
        return f"S{int(season):02d}"
    return f"S{int(season):02d}E{int(episode):02d}"


def empty_counts() -> Dict[str, int]:
    return {state: 0 for state in EPISODE_STATES}


def plural(count: int, word: str, many: Optional[str] = None) -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"


def custom_format_names(record: Dict[str, Any]) -> List[str]:
    """`customFormats[].name`, which is how Sonarr shows "WEB Tier 01"."""
    names = []
    for entry in (record or {}).get('customFormats') or []:
        if isinstance(entry, dict) and entry.get('name'):
            names.append(str(entry['name']))
    return names


def quality_name(record: Dict[str, Any]) -> Optional[str]:
    return (((record or {}).get('quality') or {}).get('quality') or {}).get('name')


def service_file(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The parts of a Sonarr or Radarr file record a person reads."""
    if not isinstance(record, dict):
        return None
    relative = str(record.get('relativePath') or '').replace('\\', '/')
    return {
        'name': relative.rsplit('/', 1)[-1] if relative else '',
        'relative_path': relative,
        'size': _int(record.get('size')),
        'quality': quality_name(record),
        'custom_formats': custom_format_names(record),
        'custom_format_score': record.get('customFormatScore'),
        'release_group': record.get('releaseGroup') or None,
        'date_added': record.get('dateAdded'),
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


#: The most of the service's episodes a season's size is matched for. A media
#: server that deletes what has synced leaves Sonarr holding only the newest
#: one to three; a season it holds more of is left to the other rules.
SIZE_MATCH_LIMIT = 3


def holds_files_of_size(sizes: List[int], count: int, total: int) -> Optional[bool]:
    """Whether the files here include ones adding up to exactly `total` bytes.

    The Library list's check that a season holds the files the service holds,
    without asking the service which ones they are: Sonarr gives each season's
    count of episodes with a file and the files' combined size, and a copied
    file keeps its size to the byte. A season where the service holds one new
    episode and this disk holds seven older ones has no file of that size here,
    so the new one is missing — whatever the transfer log says.

    `count` is episodes, not files — one file can hold two — so any one to
    `count` of the files here may make up the total. True or False when it can
    tell; None when it cannot do so cheaply (no sizes, or more than
    `SIZE_MATCH_LIMIT` episodes to account for).
    """
    if not total or count <= 0 or not sizes or count > SIZE_MATCH_LIMIT:
        return None
    return any(_sums_to(sizes, pick, total) for pick in range(1, min(count, len(sizes)) + 1))


def _sums_to(sizes: List[int], pick: int, target: int) -> bool:
    """Whether `pick` of `sizes` (each used once) add up to `target`."""
    if pick == 1:
        return target in set(sizes)
    if pick == 2:
        remaining = Counter(sizes)
        for size in sizes:
            other = target - size
            if remaining[other] - (1 if other == size else 0) > 0:
                return True
        return False
    # Three: for each first file, a two-sum over the files after it.
    ordered = sorted(sizes)
    for index, first in enumerate(ordered[:-2]):
        low, high = index + 1, len(ordered) - 1
        while low < high:
            found = first + ordered[low] + ordered[high]
            if found == target:
                return True
            if found < target:
                low += 1
            else:
                high -= 1
    return False


def _local_view(entry: Optional[Dict[str, Any]], keys: Iterable[Tuple[int, int]] = ()) \
        -> Optional[Dict[str, Any]]:
    if not entry:
        return None
    covers = [episode_code(s, e) for s, e in keys]
    return {
        'name': entry.get('name') or '',
        'relative_path': entry.get('relative_path') or entry.get('name') or '',
        'size': _int(entry.get('size')),
        'nested': bool(entry.get('nested')),
        # A double episode is one file holding two; saying so explains why the
        # same size appears on two rows.
        'covers': covers if len(covers) > 1 else [],
    }


def same_file(theirs: Dict[str, Any], ours: Dict[str, Any]) -> bool:
    """Whether the file here is the one the service holds.

    Size, because Sonarr renames files without changing their contents and an
    upgrade almost never lands on the byte. The name only decides when a size
    is missing on one side.
    """
    their_size, our_size = _int(theirs.get('size')), _int(ours.get('size'))
    if their_size and our_size:
        return their_size == our_size
    their_name = (theirs.get('name') or '').lower()
    our_name = (ours.get('name') or '').lower()
    if their_name and our_name:
        return their_name == our_name
    return True


def _pick(candidates: List[Dict[str, Any]], theirs: Optional[Dict[str, Any]]) \
        -> Optional[Dict[str, Any]]:
    """Which of several files here stands for the episode.

    The one matching the service's file if any does; otherwise the largest —
    a leftover sample or an old release is the smaller file far more often.
    """
    if not candidates:
        return None
    if theirs:
        size = _int(theirs.get('size'))
        if size:
            for entry in candidates:
                if _int(entry.get('size')) == size:
                    return entry
        name = (theirs.get('name') or '').lower()
        if name:
            for entry in candidates:
                if (entry.get('name') or '').lower() == name:
                    return entry
    return max(candidates, key=lambda entry: _int(entry.get('size')))


# =============================================================================
# A series
# =============================================================================

def compare_series(episodes: List[Dict[str, Any]],
                   episode_files: List[Dict[str, Any]],
                   local: Optional[Dict[str, Any]],
                   season_meta: Optional[List[Dict[str, Any]]] = None,
                   service: str = 'Sonarr') -> Dict[str, Any]:
    """Every episode of one series, with one state each.

    `episodes` and `episode_files` are Sonarr's own rows for the series;
    `local` is `LocalLibrary.files_of()` for its folder here, or None when
    there is no folder here at all.
    """
    files_by_id: Dict[Any, Dict[str, Any]] = {}
    for record in episode_files or []:
        if isinstance(record, dict) and record.get('id') is not None:
            files_by_id[record['id']] = record

    # The season folder on the media server, read from where Sonarr's files
    # sit. Explore names a season by it, so a link into Explore uses it too.
    service_folders: Dict[int, str] = {}
    for record in files_by_id.values():
        relative = str(record.get('relativePath') or '').replace('\\', '/')
        if '/' in relative and record.get('seasonNumber') is not None:
            service_folders.setdefault(int(record['seasonNumber']), relative.split('/', 1)[0])

    # Anime that never went through Sonarr's rename is numbered absolutely
    # ("- 25 -"), and season 2 does not start at 25. Sonarr knows the mapping.
    absolute: Dict[int, Tuple[int, int]] = {}
    for episode in episodes or []:
        number = episode.get('absoluteEpisodeNumber')
        if number is None or episode.get('seasonNumber') is None \
                or episode.get('episodeNumber') is None:
            continue
        absolute.setdefault(int(number), (int(episode['seasonNumber']),
                                          int(episode['episodeNumber'])))

    local_files = [dict(entry) for entry in ((local or {}).get('files') or [])]
    by_key: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for entry in local_files:
        keys = [tuple(key) for key in entry.get('keys') or []]
        if keys and not entry.get('coded') and absolute:
            mapped = [absolute.get(key[1]) for key in keys]
            keys = [key for key in mapped if key] or keys
        entry['_keys'] = keys
        for key in keys:
            by_key.setdefault(key, []).append(entry)
        by_name.setdefault((entry.get('name') or '').lower(), []).append(entry)

    rows: Dict[int, List[Dict[str, Any]]] = {}
    known: set = set()
    claimed: set = set()      # files here standing for an episode Sonarr knows
    served: set = set()       # of those, the ones that are the service's own file
    duplicates: Dict[Tuple[int, int], int] = {}

    ordered = sorted(
        (e for e in episodes or [] if isinstance(e, dict)
         and e.get('seasonNumber') is not None and e.get('episodeNumber') is not None),
        key=lambda e: (int(e['seasonNumber']), int(e['episodeNumber'])))

    for episode in ordered:
        season, number = int(episode['seasonNumber']), int(episode['episodeNumber'])
        key = (season, number)
        if key in known:
            continue
        known.add(key)

        theirs = None
        if episode.get('hasFile') or episode.get('episodeFileId'):
            theirs = service_file(files_by_id.get(episode.get('episodeFileId')))
            if theirs is None and episode.get('hasFile'):
                # Sonarr says a file exists but its record was not in the list
                # — an import landing between the two reads. A file with no
                # size still counts as the service having it.
                theirs = service_file({})

        named = by_name.get(theirs['name'].lower(), []) if theirs and theirs['name'] else []
        keyed = by_key.get(key, [])
        # A copy where it belongs stands for the episode; one stranded in a
        # nested folder only when there is no other.
        placed = ([c for c in named if not c.get('nested')]
                  or [c for c in keyed if not c.get('nested')])
        ours = _pick(placed, theirs)
        if ours is None:
            ours = _pick([c for c in named if c.get('nested')]
                         or [c for c in keyed if c.get('nested')], theirs)

        if ours is not None and ours.get('nested'):
            state = NESTED
        elif theirs and ours:
            state = IN_SYNC if same_file(theirs, ours) else DIFFERENT
        elif theirs:
            state = MISSING_HERE
        elif ours:
            state = ONLY_HERE
        else:
            state = NOT_DOWNLOADED

        others = [entry for entry in by_key.get(key, []) if entry is not ours]
        if ours is not None:
            claimed.add(id(ours))
            if theirs:
                served.add(id(ours))
        for entry in others:
            claimed.add(id(entry))
        if others:
            duplicates[key] = len(others)

        rows.setdefault(season, []).append({
            'code': episode_code(season, number),
            'season_number': season,
            'episode_number': number,
            'absolute_episode_number': episode.get('absoluteEpisodeNumber'),
            'title': episode.get('title') or None,
            'air_date': episode.get('airDate') or None,
            'air_date_utc': episode.get('airDateUtc') or None,
            'monitored': bool(episode.get('monitored')),
            'state': state,
            'service_file': theirs,
            'local_file': _local_view(ours, (ours or {}).get('_keys') or ()),
            'local_duplicates': len(others),
        })

    # Files here that stand for no episode Sonarr lists: an episode it has
    # since dropped, or a season it does not know. Here, and not there.
    extra: Dict[Tuple[int, int], Dict[str, Any]] = {}
    unidentified: Dict[int, List[Dict[str, Any]]] = {}
    for entry in local_files:
        if id(entry) in claimed:
            continue
        keys = entry['_keys']
        if not keys:
            unidentified.setdefault(entry.get('folder_season', -1), []).append(
                _local_view(entry))
            continue
        for key in keys:
            if key in known:
                continue
            if key in extra:
                extra[key]['local_duplicates'] += 1
                continue
            row = {
                'code': episode_code(*key), 'season_number': key[0], 'episode_number': key[1],
                'absolute_episode_number': None, 'title': None, 'air_date': None,
                'air_date_utc': None, 'monitored': False, 'state': ONLY_HERE,
                'service_file': None, 'local_file': _local_view(entry, keys),
                'local_duplicates': 0,
            }
            extra[key] = row
            rows.setdefault(key[0], []).append(row)

    # -- seasons -------------------------------------------------------------
    folders_here = (local or {}).get('season_folders') or {}
    monitored = {}
    for meta in season_meta or []:
        if isinstance(meta, dict) and meta.get('seasonNumber') is not None:
            monitored[int(meta['seasonNumber'])] = bool(meta.get('monitored'))

    numbers = sorted(set(rows) | {n for n in unidentified if n is not None and n >= 0})
    seasons = []
    for number in numbers:
        season_rows = sorted(rows.get(number, []),
                             key=lambda r: (r['episode_number'] is None, r['episode_number'] or 0))
        counts = empty_counts()
        for row in season_rows:
            counts[row['state']] += 1
        in_folder = [entry for entry in local_files if entry.get('folder_season') == number]
        # What a whole-folder sync of this season would remove: every file here
        # that is not the service's own copy of an episode. Kept-only-here
        # episodes, second copies and files nothing can identify alike.
        removable = sum(1 for entry in in_folder if id(entry) not in served)
        nested_here = [entry for entry in in_folder if entry.get('nested')]
        names = folders_here.get(number) or []
        seasons.append({
            'season_number': number,
            'specials': number == 0,
            'counts_towards_state': number > 0,
            'monitored': monitored.get(number, False),
            'folder_here': names[0] if names else None,
            'service_folder': service_folders.get(number),
            'counts': counts,
            'state': _season_state(counts, bool(in_folder), bool(nested_here)),
            # Every media file of the season in a nested folder, whatever it
            # stands for — a second copy of an episode included.
            'nested_here': [entry.get('relative_path') or '' for entry in nested_here],
            'service_file_count': sum(1 for row in season_rows if row['service_file']),
            'files_here': len(in_folder),
            'episodes_here': len({key for entry in in_folder if not entry.get('nested')
                                  for key in entry['_keys']})
            + sum(1 for entry in in_folder if not entry['_keys'] and not entry.get('nested')),
            'local_only_files': removable,
            'episodes': season_rows,
            'unidentified_here': unidentified.get(number, []),
        })

    counted = [s for s in seasons if s['counts_towards_state']]
    counts = empty_counts()
    for season in counted:
        for state, value in season['counts'].items():
            counts[state] += value

    present = bool((local or {}).get('loose')) or any(
        (entry.get('folder_season') or 0) > 0 for entry in local_files)
    service_has_files = any(s['service_file_count'] for s in seasons)
    unidentified_count = sum(len(s['unidentified_here']) for s in counted)
    nested_files = sum(len(s['nested_here']) for s in counted)

    if local is None or not present:
        state = NEVER if service_has_files else NO_FILES
    elif counts[MISSING_HERE] or counts[DIFFERENT]:
        state = OUT_OF_SYNC
    elif nested_files:
        state = NEEDS_REPAIR
    elif not service_has_files:
        state = KEPT_HERE
    elif counts[ONLY_HERE] or unidentified_count:
        state = KEPT_HERE
    else:
        state = TITLE_IN_SYNC

    return {
        'state': state,
        'summary': series_summary(state, counted, counts, service),
        'counts': counts,
        'nested_files': nested_files,
        'service_has_files': service_has_files,
        'present_locally': present,
        'seasons': seasons,
        'sync': series_sync_advice(state, seasons, service),
        'duplicates': {episode_code(*key): count for key, count in duplicates.items()},
    }


def _season_state(counts: Dict[str, int], anything_here: bool, nested: bool = False) -> str:
    if counts[MISSING_HERE] or counts[DIFFERENT]:
        return OUT_OF_SYNC
    if nested:
        return NEEDS_REPAIR
    if counts[ONLY_HERE]:
        return KEPT_HERE
    if counts[IN_SYNC]:
        return TITLE_IN_SYNC
    return KEPT_HERE if anything_here else NOT_DOWNLOADED


def _named(rows: List[Dict[str, Any]], limit: int = 3) -> str:
    """'S01E08 “Title”' for one, 'S01E06, S01E07 and S01E08' for a few."""
    if len(rows) == 1:
        row = rows[0]
        return f"{row['code']} “{row['title']}”" if row.get('title') else row['code']
    codes = [row['code'] for row in rows]
    if len(codes) <= limit:
        return ', '.join(codes[:-1]) + f" and {codes[-1]}"
    return ', '.join(codes[:limit]) + f" and {len(codes) - limit} more"


def series_summary(state: str, counted: List[Dict[str, Any]], counts: Dict[str, int],
                   service: str = 'Sonarr') -> str:
    """One sentence a person can act on, for the top of the detail view."""
    rows = [row for season in counted for row in season['episodes']]
    missing = [row for row in rows if row['state'] == MISSING_HERE]
    different = [row for row in rows if row['state'] == DIFFERENT]
    stranded = [row for row in rows if row['state'] == NESTED]
    nested_files = sum(len(season.get('nested_here') or []) for season in counted)
    kept = counts[ONLY_HERE]
    held = sum(1 for row in rows if row['service_file'])

    if state == NEVER:
        return (f"Nothing of this series is here yet. {service} has "
                f"{plural(held, 'episode')} with a file.")
    if state == NO_FILES:
        return f"{service} holds no files for this series yet, and nothing is here."
    if state == KEPT_HERE and not held:
        return (f"{service} holds no files for this series any more; "
                f"what is here is kept.")
    if state == KEPT_HERE:
        return (f"Everything {service} holds is here. {plural(kept, 'more episode')} "
                f"{'is' if kept == 1 else 'are'} kept only here — normal once the media "
                f"server has cleaned up after a sync.")
    if state == TITLE_IN_SYNC:
        return f"Everything {service} holds is here."

    nested_part = _nested_sentence(stranded, nested_files) if nested_files else ''
    if state == NEEDS_REPAIR:
        return nested_part + '. Repair it in Explore.'

    parts = []
    if missing:
        if len(missing) == 1:
            parts.append(f"1 episode on {service} is not here yet: {_named(missing)}")
        else:
            parts.append(f"{len(missing)} episodes on {service} are not here yet: "
                         f"{_named(missing)}")
    if different:
        if len(different) == 1:
            parts.append(f"{_named(different)} is a different file on {service} "
                         f"(an upgrade or another release)")
        else:
            parts.append(f"{len(different)} episodes are a different file on {service}: "
                         f"{_named(different)}")
    if nested_files:
        parts.append(nested_part)
    return '; '.join(parts) + '.'


def _nested_sentence(stranded: List[Dict[str, Any]], nested_files: int) -> str:
    """'S01E38 is here, but inside a nested folder …', without the full stop."""
    where = 'inside a nested folder your media server cannot see'
    if len(stranded) == 1 and nested_files <= 1:
        return f"{_named(stranded)} is here, but {where}"
    if stranded and len(stranded) == nested_files:
        return f"{len(stranded)} episodes are here, but {where}: {_named(stranded)}"
    return f"{plural(nested_files, 'file')} here {'is' if nested_files == 1 else 'are'} {where}"


def series_sync_advice(state: str, seasons: List[Dict[str, Any]],
                       service: str = 'Sonarr') -> Dict[str, Any]:
    """Whether the title's Sync button is safe to offer, and why not when it is not.

    That button syncs whole season folders — every season holding fewer files
    here than the service has episodes with files, the rule
    `AutoScanner.sync_one` applies — and a whole-folder sync makes the folder
    here match the folder there. Episodes kept only here would be removed, so
    the safety check stops such a sync; offering the button would only lead
    there. Explore fetches just the missing files instead.
    """
    fetch = [s for s in seasons if s['counts_towards_state'] and s['service_file_count']
             and s['files_here'] < s['service_file_count']]
    needs = [s for s in seasons if s['counts_towards_state']
             and (s['counts'][MISSING_HERE] or s['counts'][DIFFERENT])]

    if state == NEVER:
        return {'offered': bool(fetch), 'seasons': [s['season_number'] for s in fetch],
                'reason': '' if fetch else f"{service} holds nothing to fetch."}
    if state != OUT_OF_SYNC:
        return {'offered': False, 'seasons': [], 'reason': ''}

    # A season that needs something and keeps files only here is exactly the
    # case a folder sync gets wrong — the real one being E08 there and E01–E07
    # here. Said first, because it is the reason the button is not the answer.
    wanted = {s['season_number'] for s in needs}
    order = needs + [s for s in fetch if s['season_number'] not in wanted]
    stranded = [s for s in order if s.get('nested_here')]
    if stranded:
        first = stranded[0]
        label = 'Specials' if first['specials'] else f"Season {first['season_number']}"
        return {
            'offered': False, 'seasons': [],
            'reason': (f"{label} has a file inside a nested folder. Syncing the whole season "
                       f"folder would remove it and copy it again; repair it in Explore "
                       f"instead."),
        }
    risky = [s for s in order if s['local_only_files']]
    if risky:
        first = risky[0]
        label = 'Specials' if first['specials'] else f"Season {first['season_number']}"
        kept = first['local_only_files']
        return {
            'offered': False, 'seasons': [],
            'reason': (f"{label} also holds {plural(kept, 'file')} kept only here. Syncing "
                       f"the whole season folder would remove {'it' if kept == 1 else 'them'}, "
                       f"so the safety check would stop it. Fetch only what is missing "
                       f"in Explore."),
        }
    if not any(s['season_number'] in wanted for s in fetch):
        return {
            'offered': False, 'seasons': [],
            'reason': (f"Sync on a title only fetches seasons holding fewer files here than "
                       f"{service} has; replace a different file from Explore."),
        }
    return {'offered': True, 'seasons': [s['season_number'] for s in fetch], 'reason': ''}


# =============================================================================
# A film
# =============================================================================

def compare_movie(movie: Dict[str, Any], local: Optional[Dict[str, Any]],
                  service: str = 'Radarr') -> Dict[str, Any]:
    """One film: the service's file against the media file(s) in its folder here.

    `local` is `LocalLibrary.files_of()` for the film's folder (its `loose`
    files), or None when there is no folder here.
    """
    movie = movie or {}
    has_file = bool(movie.get('hasFile'))
    theirs = None
    if has_file:
        theirs = service_file(movie.get('movieFile') if isinstance(movie.get('movieFile'), dict)
                              else None)
        if theirs is None:
            theirs = service_file({'size': movie.get('sizeOnDisk')})

    here = list((local or {}).get('loose') or [])
    stranded = [dict(entry, nested=True) for entry in (local or {}).get('nested_loose') or []]
    ours = _pick(here, theirs)
    if ours is None and stranded:
        ours = _pick(stranded, theirs)
    if ours is not None and ours.get('nested'):
        state = NESTED
    elif theirs and ours:
        state = IN_SYNC if same_file(theirs, ours) else DIFFERENT
    elif theirs:
        state = MISSING_HERE
    elif ours:
        state = ONLY_HERE
    else:
        state = NOT_DOWNLOADED

    title_state = MOVIE_TITLE_STATE[state]
    if title_state != OUT_OF_SYNC and stranded and ours is not None and not ours.get('nested'):
        # The film plays from its own folder; a second copy below it is still
        # stranded there.
        title_state = NEEDS_REPAIR
    counts = empty_counts()
    counts[state] = 1
    others = [_local_view(entry) for entry in here + stranded if entry is not ours]
    summary = movie_summary(state, theirs, ours, service)
    if title_state == NEEDS_REPAIR and state != NESTED:
        summary += (" A second copy is inside a nested folder your media server cannot see; "
                    "repair it in Explore.")
    return {
        'state': title_state,
        'summary': summary,
        'counts': counts,
        'nested_files': len(stranded),
        'service_has_files': has_file,
        'present_locally': bool(here or stranded),
        'movie': {
            'state': state,
            'service_file': theirs,
            'local_file': _local_view(ours),
            'other_files_here': others,
        },
        'sync': {
            'offered': title_state == NEVER,
            'seasons': [],
            'reason': (f"Sync on a film fetches it only when it is not here; replace a "
                       f"different file from Explore." if title_state == OUT_OF_SYNC else ''),
        },
    }


def size_words(size: int) -> str:
    """"1.6 GB", "820 MB": a file size the way the screens print it."""
    value = float(size or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return f"{value:.1f} {unit}" if unit in ('GB', 'TB') else f"{value:.0f} {unit}"
        value /= 1024
    return f"{size} B"


def movie_summary(state: str, theirs: Optional[Dict[str, Any]],
                  ours: Optional[Dict[str, Any]], service: str = 'Radarr') -> str:
    if state == NESTED:
        return ("The film is here, but inside a nested folder your media server cannot "
                "see. Repair it in Explore.")
    if state == IN_SYNC:
        return f"The film here is the file {service} holds."
    if state == DIFFERENT:
        quality = f"{theirs.get('quality')}, " if theirs and theirs.get('quality') else ''
        return (f"{service} holds a different file ({quality}{size_words(theirs['size'])}); "
                f"the one here is {size_words(_int((ours or {}).get('size')))}.")
    if state == MISSING_HERE:
        return f"{service} holds this film; it is not here yet."
    if state == ONLY_HERE:
        return f"{service} holds no file for it any more; the copy here is kept."
    return f"Neither {service} nor this disk has a file for it yet."
