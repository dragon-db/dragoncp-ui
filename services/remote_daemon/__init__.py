"""
The transfer server that runs on the remote host.

Transfers over SSH are held to about 11 MB/s on this link — not by the ISP, but
by a limit inside SSH itself interacting with a 154 ms round trip. The same
files over rsync's own daemon, on a plain port, move at 27 MB/s. This package
owns that daemon: generating it, installing it, controlling it and reporting on
it, all from here.

See `docs/plans/fast-transport.md` for the measurements and the reasoning.
"""

from .service import RemoteDaemonError, RemoteDaemonService

__all__ = ['RemoteDaemonService', 'RemoteDaemonError']
