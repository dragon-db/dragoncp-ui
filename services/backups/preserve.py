#!/usr/bin/env python3
"""
Putting a file into the backup tree without reading it, when that is safe.

A hardlink is a second name for the same bytes: instant to create whatever the
file's size, and costing no additional space. It only works within one
filesystem, which is why this became available at all — the backup area moved
onto the same disk as the media.

THE RULE, AND WHY IT IS NOT "ALWAYS LINK"
-----------------------------------------
Two names for one file means writing through either name changes both. There is
no second copy to fall back on. So a hardlinked backup is only a backup for as
long as nothing writes to the library file **in place**.

Nothing in this application does — rsync writes a temporary file and renames it,
the rename service only changes names, and a restore replaces atomically. But
the library is not only touched by this application, and a tool that rewrites a
video container's tags or strips an audio track in place would rewrite the
"backup" too. Silently: it would still be listed, still look restorable, and no
longer be what was backed up.

So the rule is about how long the two names coexist, not about how much disk is
saved:

    keep_before_destroying()   the original is about to be replaced or deleted.
                               The two names share bytes for SECONDS. Link.

    a restored file            goes back to being an ordinary library file and
                               stays one for months, exposed to anything that
                               ever touches the library. COPY — see
                               `restore.py::_restore_one`, which deliberately
                               does not use this module.

The saving is in the first case anyway. It happens on every transfer that
replaces or deletes anything; a restore is rare and started by a person.
"""

import os
import shutil
from typing import Tuple

LINKED = 'link'
COPIED = 'copy'


def same_filesystem(one: str, other: str) -> bool:
    """
    Whether two paths sit on the same filesystem, and so can share bytes.

    Compared on the containing directory, because the target normally does not
    exist yet — it is what we are about to create.
    """
    try:
        first = os.stat(one if os.path.exists(one) else os.path.dirname(one) or '.')
        second = os.stat(other if os.path.exists(other) else os.path.dirname(other) or '.')
    except OSError:
        return False
    return first.st_dev == second.st_dev


def keep_before_destroying(source: str, target: str) -> Tuple[str, int]:
    """
    Put `source` at `target`, for a caller that is about to destroy `source`.

    Returns (how, size) where `how` is LINKED or COPIED, so the caller can say
    what happened. Raises OSError if neither worked — and a caller that gets an
    exception here must NOT go on to destroy anything.

    Falls back to copying whenever a link is not possible: a different
    filesystem, or one that will not take another name for a file. That fallback
    is what keeps this correct if the backup area is ever moved back off the
    media disk — the behaviour degrades to what it was before, rather than
    failing.
    """
    size = os.path.getsize(source)

    if same_filesystem(source, target):
        try:
            os.link(source, target)
            # Cheap sanity check on the result. A link cannot be short — it is
            # the same bytes — so this is really asking "did we link the file we
            # meant to", which a wrong target would fail.
            if os.path.getsize(target) != size:
                raise OSError('linked file does not match the original')
            return LINKED, size
        except OSError:
            # Cross-device, a filesystem without hardlinks, a hit link limit, or
            # a target that already exists. Copying still works for all of them.
            if os.path.exists(target):
                try:
                    os.remove(target)
                except OSError:
                    pass

    shutil.copy2(source, target)
    # A short copy would otherwise only be discovered once the original was gone.
    if os.path.getsize(target) != size:
        raise OSError('short copy')
    return COPIED, size
