#!/usr/bin/env python3
"""
Asking the transfer server whether it will actually serve us.

This asks with **rsync itself**, not with a hand-written conversation over a
socket. Two reasons, both learned the hard way against the real server:

1. A hand-rolled check cannot authenticate without reimplementing rsync's
   challenge-response, so it opened a connection, named a library and hung up —
   which the daemon recorded as `auth failed` in its log. Once per health check,
   before every transfer. The log we want to read to spot someone probing the
   port would have been buried under our own noise.

2. A check that is not the thing doing the work can be wrong about it. Using the
   same client, the same password file and the same address form as the transfer
   means "the check passed" and "a transfer would work" cannot come apart.

It costs one process and about two seconds on a long link, which is nothing
against a transfer measured in minutes, and the answer is cached anyway.

WHAT THE ANSWERS MEAN

    ready         authenticated; a transfer would run
    blocked       the daemon is up and will not show us this library
    auth_failed   it is up, we reached it, and our password is wrong
    unreachable   nothing answered
    error         something else, reported verbatim

`blocked` deserves a note. rsync answers "unknown module" both when a library
is not published AND when the asking address is not allowed to see it — it
deliberately does not confirm that a hidden library exists. That is a good
property and not something to work around, so this layer does not guess between
the two. The service does, using facts it holds on this side: whether we
published that library, and whether our address still matches the one allowed.
"""

import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from .layout import DAEMON_USER

READY = 'ready'
BLOCKED = 'blocked'
AUTH_FAILED = 'auth_failed'
UNREACHABLE = 'unreachable'
ERROR = 'error'

#: Short on purpose. This runs before a transfer starts, and a server that is
#: not answering promptly is one to skip rather than wait for.
DEFAULT_TIMEOUT = 8


@dataclass
class ProbeResult:
    state: str
    detail: str = ''

    @property
    def ok(self) -> bool:
        return self.state == READY

    @property
    def running(self) -> bool:
        """Something answered and spoke rsync, whether or not it will serve us."""
        return self.state in (READY, BLOCKED, AUTH_FAILED)

    def to_dict(self) -> dict:
        return {
            'state': self.state,
            'detail': self.detail,
            'ok': self.ok,
            'running': self.running,
        }


def build_command(host: str, port: int, module: str, password_file: str,
                  timeout: int = DEFAULT_TIMEOUT) -> List[str]:
    """
    The cheapest question that still proves a transfer would work.

    `--exclude=*` leaves nothing to list, so this connects, authenticates and
    stops. Without it the answer would carry every entry at the top of a media
    library, for no gain.
    """
    return [
        'rsync', '--list-only', '--no-motd',
        f'--port={int(port)}',
        f'--contimeout={int(timeout)}',
        f'--timeout={int(timeout)}',
        '--exclude=*',
        '--password-file', password_file,
        f'{DAEMON_USER}@{host}::{module}',
    ]


def probe(host: str, port: int, module: str, password_file: str,
          timeout: int = DEFAULT_TIMEOUT) -> ProbeResult:
    if not host or not port or not module:
        return ProbeResult(UNREACHABLE, 'The transfer server is not configured')
    if not password_file or not os.path.exists(password_file):
        return ProbeResult(
            ERROR, 'No password has been generated for the transfer server yet')

    command = build_command(host, port, module, password_file, timeout)
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            # Bounds the whole thing including looking the host name up, which
            # rsync's own timeouts do not cover.
            timeout=timeout + 5,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(UNREACHABLE, 'The transfer server did not answer in time')
    except OSError as error:
        return ProbeResult(ERROR, f"Could not run rsync: {error}")

    return classify(result.returncode, result.stdout or '')


def classify(exit_code: int, output: str) -> ProbeResult:
    """
    Turn rsync's exit code and output into one of the five answers.

    Separate from running it so the mapping can be tested without a server, and
    so an unfamiliar failure is reported in rsync's own words rather than being
    flattened into something reassuring.
    """
    if exit_code == 0:
        return ProbeResult(READY, 'Ready')

    lowered = output.lower()

    if 'auth failed' in lowered:
        return ProbeResult(
            AUTH_FAILED,
            'The transfer server did not accept our password. Reinstall it to '
            'push the current one.')
    if 'unknown module' in lowered:
        return ProbeResult(
            BLOCKED, 'The transfer server would not serve this library')
    if 'connection refused' in lowered:
        return ProbeResult(UNREACHABLE, 'Nothing is listening on that port')
    if 'no route to host' in lowered or 'network is unreachable' in lowered:
        return ProbeResult(UNREACHABLE, 'The remote host could not be reached')
    if 'unknown host' in lowered or 'name or service not known' in lowered:
        return ProbeResult(UNREACHABLE, 'The remote host name could not be looked up')
    if 'timed out' in lowered or 'timeout' in lowered:
        return ProbeResult(UNREACHABLE, 'The transfer server did not answer in time')
    if exit_code == 10:
        return ProbeResult(UNREACHABLE, 'Could not connect to the transfer server')

    return ProbeResult(ERROR, _first_error(output) or f"rsync exited with code {exit_code}")


def _first_error(output: str) -> Optional[str]:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith('@ERROR'):
            return line[len('@ERROR'):].lstrip(': ').strip()
        if line.startswith('rsync:') or line.startswith('rsync error:'):
            return line
    return None
