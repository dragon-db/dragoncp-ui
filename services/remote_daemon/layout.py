#!/usr/bin/env python3
"""
Every name and path the remote transfer server uses, in one place.

Nothing else in the application should build one of these strings. When the
installer, the status check and the uninstaller disagree about where a file
lives, the uninstaller is the one that quietly stops working — and an installer
that can leave things behind on a machine we do not have root on is the failure
mode worth designing against.

Everything we put on that machine is under ONE directory plus ONE service file,
both listed here, so `uninstall` is a complete statement rather than a guess.
"""

import posixpath
from typing import Dict, List, Optional, Tuple

#: Everything this application installs lives under the remote user's home.
REMOTE_DIR = '.dragoncp'
UNIT_DIR = '.config/systemd/user'
UNIT_NAME = 'dragoncp-rsyncd.service'

CONF_FILE = 'rsyncd.conf'
SECRETS_FILE = 'rsyncd.secrets'
LOG_FILE = 'rsyncd.log'
PID_FILE = 'rsyncd.pid'
LOCK_FILE = 'rsyncd.lock'

#: The account name used for the transfer server's own password. It has nothing
#: to do with the SSH account — it exists only inside the rsync daemon and is
#: never a login anywhere.
DAEMON_USER = 'dragoncp'

#: Published library -> the setting holding its directory on the remote host.
#: The published names are deliberately not the directory names: a module name
#: appears in the transfer command and in rsync's log, and there is no reason
#: for either to carry the layout of someone's disk.
MODULES: Tuple[Tuple[str, str], ...] = (
    ('movies', 'MOVIE_PATH'),
    ('tvshows', 'TVSHOW_PATH'),
    ('anime', 'ANIME_PATH'),
)

#: The media type the rest of the application uses -> the published library.
#: These already agree today; the mapping is written down so a future rename of
#: either one is a single edit rather than a hunt.
MEDIA_TYPE_TO_MODULE: Dict[str, str] = {
    'movies': 'movies',
    'tvshows': 'tvshows',
    'anime': 'anime',
}


def remote_dir(home: str) -> str:
    return posixpath.join(home, REMOTE_DIR)


def conf_path(home: str) -> str:
    return posixpath.join(remote_dir(home), CONF_FILE)


def secrets_path(home: str) -> str:
    return posixpath.join(remote_dir(home), SECRETS_FILE)


def log_path(home: str) -> str:
    return posixpath.join(remote_dir(home), LOG_FILE)


def pid_path(home: str) -> str:
    return posixpath.join(remote_dir(home), PID_FILE)


def lock_path(home: str) -> str:
    return posixpath.join(remote_dir(home), LOCK_FILE)


def unit_dir(home: str) -> str:
    return posixpath.join(home, UNIT_DIR)


def unit_path(home: str) -> str:
    return posixpath.join(unit_dir(home), UNIT_NAME)


def installed_paths(home: str) -> List[str]:
    """
    Everything this application puts on the remote host.

    `uninstall` removes exactly this list and nothing else, which is why it is
    stated here rather than assembled at the call site.
    """
    return [remote_dir(home), unit_path(home)]


def module_roots(settings) -> List[Tuple[str, str]]:
    """
    The libraries to publish, as (published name, remote directory).

    A library with no directory configured is skipped rather than published as
    an empty path — rsync would happily serve the whole filesystem from one.
    """
    roots = []
    for name, key in MODULES:
        root = (settings.get(key) or '').strip()
        if root:
            roots.append((name, root.rstrip('/')))
    return roots


def _within(root: str, path: str) -> Optional[str]:
    """
    The part of `path` below `root`, or None if it is not below it.

    Compared segment by segment rather than with a prefix test, so a library at
    `/media/tv` does not appear to contain `/media/tv-archive/...`.
    """
    root_parts = [p for p in root.strip('/').split('/') if p]
    path_parts = [p for p in path.strip('/').split('/') if p]
    if path_parts[:len(root_parts)] != root_parts:
        return None
    return '/'.join(path_parts[len(root_parts):])


def source_for(settings, absolute_path: str) -> Optional[Tuple[str, str]]:
    """
    Map an absolute path on the remote host to (published library, path within it).

    Returns None when the path is not inside any configured library, which is
    the signal to use SSH instead. Failing closed matters here: a path we cannot
    place is a path we should not be publishing a route to.
    """
    if not absolute_path:
        return None
    for name, root in module_roots(settings):
        relative = _within(root, absolute_path)
        if relative is not None:
            return name, relative
    return None


def daemon_source(host: str, module: str, relative: str = '') -> str:
    """
    The address rsync is given for a daemon transfer.

    Deliberately the `host::module/path` form rather than `rsync://host:port/...`.
    Both reach the same daemon, but the URL form invites the question of whether
    the path is URL-encoded — and media filenames are full of the characters
    that would make the answer matter. This form has no such layer: the path is
    sent as typed. The port travels separately, as `--port`.
    """
    base = f"{DAEMON_USER}@{host}::{module}"
    return f"{base}/{relative}" if relative else f"{base}/"
