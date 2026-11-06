#!/usr/bin/env python3
"""
What is playing on Jellyfin, and the record of it.

One question is asked of Jellyfin — the session list — and two things are
answered from it: the Now playing tab, and the play recorder. Both go through
`poll()`, so a page open on Now playing also keeps the record precise, and a
scheduler run and a page load arriving together ask Jellyfin once.

The scheduler asks every 10 seconds while something plays and every 30 when
nothing does, and backs off to five minutes while Jellyfin is not answering.
Jellyfin is on this machine; none of this reaches the remote server.
"""

import hashlib
import hmac
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from services.jellyfin.recorder import PlayRecorder, iso
from services.jellyfin.sessions import streams_from_sessions

log = logging.getLogger('dragoncp.jellyfin')

ACTIVE_INTERVAL = 10.0
IDLE_INTERVAL = 30.0
#: While Jellyfin is not answering: 60 s, 120 s, then every 5 minutes.
BACKOFF = (60.0, 120.0, 300.0)
#: Two answers this close together are the same answer.
FRESH_SECONDS = 2.0


def _default_connectors():
    from services.connectors import get_service
    return get_service()


class JellyfinService:
    def __init__(self, db_manager, *, secret: str = '',
                 connectors: Callable[[], Any] = _default_connectors,
                 clock: Callable[[], float] = time.time):
        self.recorder = PlayRecorder(db_manager, clock=clock)
        self._connectors = connectors
        self._secret = (secret or '').encode('utf-8')
        self.clock = clock
        self._lock = threading.Lock()
        self._snapshot: Optional[Dict[str, Any]] = None
        self._snapshot_at = 0.0
        self._failures = 0

    # ------------------------------------------------------------- adapter

    def adapter(self):
        """Jellyfin's adapter while it is switched on and configured, else None."""
        try:
            service = self._connectors()
            if service is None:
                return None
            row = service.store.get_connector('jellyfin')
            if not row or not row.get('enabled'):
                return None
            adapter = service.adapter('jellyfin')
            return adapter if adapter is not None and adapter.is_configured() else None
        except Exception:  # noqa: BLE001 - "cannot tell" reads as "not connected"
            return None

    def recording(self) -> bool:
        adapter = self.adapter()
        return bool(adapter is not None and adapter.record_plays())

    # ---------------------------------------------------------------- poll

    def poll(self) -> Dict[str, Any]:
        """Ask Jellyfin what is playing; record it when recording is on."""
        with self._lock:
            now = self.clock()
            if self._snapshot is not None and now - self._snapshot_at < FRESH_SECONDS:
                return self._snapshot
            adapter = self.adapter()
            if adapter is None:
                self.recorder.close_open()
                snapshot = {'ok': False, 'state': 'off', 'streams': [],
                            'message': 'Jellyfin is off or not set up yet.'}
            else:
                ok, sessions, error = adapter.sessions()
                if ok:
                    self._failures = 0
                    streams = streams_from_sessions(sessions)
                    recording = adapter.record_plays()
                    if recording:
                        self.recorder.observe(streams, now=now)
                    else:
                        self.recorder.close_open()
                    for stream in streams:
                        stream['item']['poster'] = self.poster_url(stream['item']['poster_id'])
                    snapshot = {'ok': True, 'state': 'ok', 'streams': streams,
                                'recording': recording,
                                'signed_in': sum(1 for s in sessions if s.get('UserId')),
                                'message': ''}
                else:
                    self._failures += 1
                    snapshot = {'ok': False, 'state': 'unreachable', 'streams': [],
                                'message': error}
            snapshot['checked_at'] = iso(now)
            self._snapshot, self._snapshot_at = snapshot, now
            return snapshot

    # ----------------------------------------------------------- scheduler

    def interval(self) -> Optional[float]:
        if not self.recording():
            return None
        if self._failures:
            return BACKOFF[min(self._failures, len(BACKOFF)) - 1]
        return ACTIVE_INTERVAL if self.recorder.open_count() else IDLE_INTERVAL

    def run_job(self) -> Dict[str, Any]:
        snapshot = self.poll()
        if not snapshot['ok']:
            return {'ok': False, 'summary': snapshot['message'] or 'Jellyfin did not answer'}
        count = len(snapshot['streams'])
        return {'ok': True, 'summary': (f"{count} playing" if count else 'Nothing playing'),
                'playing': count}

    def scheduler_job(self):
        from services.scheduler import Job
        return Job(
            name='jellyfin_plays', label='Jellyfin plays',
            description=('Asks Jellyfin what is playing and keeps a record of every play: who, '
                         'what, on which device, and why it was converted. Jellyfin is on this '
                         'machine; nothing reaches the remote server.'),
            interval=self.interval,
            run=self.run_job,
            first_run_delay=15.0,
        )

    # --------------------------------------------------------------- plays

    def plays(self, **filters) -> Dict[str, Any]:
        """Recorded plays, each with its poster address."""
        if not self.recording():
            # Switched off mid-play: close what was open at its last sighting,
            # or it would read as "Playing" until recording came back on.
            self.recorder.close_open()
        page = self.recorder.plays(**filters)
        for play in page['plays']:
            item = play['item']
            item['poster'] = self.poster_url(item.get('series_id') or item.get('id') or '')
        return page

    # -------------------------------------------------------------- images

    def _signature(self, item_id: str) -> str:
        return hmac.new(self._secret, f"jellyfin-image:{item_id}".encode('utf-8'),
                        hashlib.sha256).hexdigest()[:20]

    def poster_url(self, item_id: str) -> str:
        """Where the browser fetches an item's poster through DragonCP.

        An `<img>` cannot carry the sign-in token, so the address is signed
        instead: only item ids this app handed out to a signed-in page load.
        """
        if not item_id:
            return ''
        return f"/api/jellyfin/image/{item_id}?s={self._signature(item_id)}"

    def signature_ok(self, item_id: str, signature: str) -> bool:
        return bool(item_id) and hmac.compare_digest(self._signature(item_id), signature or '')

    def image(self, item_id: str, width: int):
        adapter = self.adapter()
        if adapter is None:
            return None
        return adapter.image(item_id, 'Primary', width)
