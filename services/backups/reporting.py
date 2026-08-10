#!/usr/bin/env python3
"""
What a backup operation removed, in enough detail to answer for it later.

Every path that deletes a stored version reports through here — the automatic
retention sweep, a manual delete, and clearing the unidentified bucket — so the
activity trail, the Discord message and the History tab all describe a deletion
the same way rather than each inventing its own shape.

Two rules make this worth having:

  * **Read before the delete.** Once the files and the index row are gone this
    record is the only thing that says what was there. An id on its own tells
    nobody what they lost, and the file rows cannot be read back afterwards.
  * **Name the path.** "Removed 3 old versions" is not an answer to "what
    happened to my episode". Every item carries where it lived in the library
    and where the copy sat on the backup disk, spelled out in full.

The detail is capped: a sweep can take hundreds of versions and an unbounded
JSON blob on every entry would make the trail unreadable and the table large.
The counts and the totals always describe everything; the itemised list says
how many it left out.
"""

from typing import Dict, Iterable, List, Optional

#: Items spelled out per activity entry. The rest are counted, never dropped
#: silently — `omitted` says how many, and the totals still cover them all.
MAX_DETAIL_ITEMS = 50

#: Files listed per item. A season pack capture is one media file and a handful
#: of sidecars; anything beyond this is a folder nobody reads file by file.
MAX_DETAIL_FILES = 12


def describe_files(files: Optional[Iterable[Dict]], capture_dir: Optional[str] = None) -> List[Dict]:
    """
    One capture's files, each with both of the paths that matter.

    `original_path` is where the file lived in the media library — the answer to
    "what did I actually lose". `backup_path` is where the kept copy sat, which
    is what an operator needs when they go looking on disk for something the
    index no longer knows about.
    """
    described: List[Dict] = []
    for entry in list(files or [])[:MAX_DETAIL_FILES]:
        relative = entry.get('relative_path') or ''
        described.append({
            'name': relative.rsplit('/', 1)[-1] or relative,
            'relative_path': relative,
            'original_path': entry.get('original_path') or None,
            'backup_path': f"{capture_dir}/{relative}" if capture_dir and relative else None,
            'file_size': entry.get('file_size') or 0,
            'is_media': bool(entry.get('is_media')),
        })
    return described


def describe_capture(capture: Dict, files: Optional[Iterable[Dict]] = None,
                     display: Optional[str] = None,
                     capture_dir: Optional[str] = None) -> Dict:
    """
    One stored version, described so it can be identified after it is gone.

    `capture_dir` is the absolute folder on the backup disk when the caller
    could resolve it. It is optional because resolving it needs a configured
    backup path, and a description that fails when the path is unset would take
    the deletion's whole record down with it.
    """
    file_list = list(files or [])
    return {
        'capture_id': capture.get('capture_id'),
        'display': display or capture.get('display') or capture.get('capture_path') or '',
        'library': capture.get('library'),
        'title': capture.get('title'),
        'season_number': capture.get('season_number'),
        'episode_number': capture.get('episode_number'),
        'release_year': capture.get('release_year'),
        'slot_key': capture.get('slot_key'),
        'kind': capture.get('kind'),
        'reason': capture.get('reason'),
        'captured_at': capture.get('captured_at'),
        'pinned': bool(capture.get('pinned')),
        'total_size': capture.get('total_size') or 0,
        'file_count': capture.get('file_count') or len(file_list),
        # Relative to the backup base, which is what the index stores, plus the
        # absolute form when it could be resolved.
        'capture_path': capture.get('capture_path') or '',
        'capture_dir': capture_dir,
        'files': describe_files(file_list, capture_dir),
        'files_omitted': max(0, len(file_list) - MAX_DETAIL_FILES),
    }


def _itemised(items: List[Dict], automatic: bool) -> Dict:
    """The part of the detail that is the same whichever way it happened."""
    return {
        'automatic': automatic,
        'items': items[:MAX_DETAIL_ITEMS],
        'omitted': max(0, len(items) - MAX_DETAIL_ITEMS),
        # Enough to name the titles even when the itemised list was capped.
        'titles': sorted({item.get('title') for item in items if item.get('title')})[:MAX_DETAIL_ITEMS],
    }


def summarise(items: List[Dict], *, automatic: bool = False,
              reclaimed: Optional[int] = None,
              extra: Optional[Dict] = None) -> Dict:
    """
    The activity-trail detail for a set of removals.

    `reclaimed` is passed in rather than summed here when the caller knows what
    the filesystem actually freed — a capture whose files were already missing
    is deleted from the index and frees nothing, and the sum of the recorded
    sizes would overstate it.
    """
    total = sum(item.get('total_size') or 0 for item in items)
    detail = {
        **_itemised(items, automatic),
        'deleted_count': len(items),
        'reclaimed_bytes': total if reclaimed is None else reclaimed,
    }
    if extra:
        detail.update(extra)
    return detail


def summarise_created(items: List[Dict], *, automatic: bool = True,
                      extra: Optional[Dict] = None) -> Dict:
    """
    The same detail for versions that came into existence.

    Deliberately a different shape from `summarise`: reusing the deletion keys
    would put `deleted_count` and `reclaimed_bytes` on an entry about files
    being kept, and a reader skimming the trail would take it for a deletion.
    """
    detail = {
        **_itemised(items, automatic),
        'created_count': len(items),
        'kept_bytes': sum(item.get('total_size') or 0 for item in items),
    }
    if extra:
        detail.update(extra)
    return detail


def summary_line(items: List[Dict], limit: int = 3) -> str:
    """
    The removed versions as a phrase, for a log line or a toast.

    Named rather than counted, because "removed 3 old versions" and "removed
    the only copy of the thing you were looking for" read identically when the
    names are left out.
    """
    if not items:
        return 'nothing'
    names = [str(item.get('display') or item.get('capture_id') or '?') for item in items]
    shown = names[:limit]
    if len(names) > limit:
        shown.append(f"and {len(names) - limit} more")
    return ', '.join(shown)
