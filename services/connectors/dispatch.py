#!/usr/bin/env python3
"""
Delivering without making the caller wait.

Before this, a rename notification was posted to Discord synchronously inside
the HTTP request Sonarr made — `RenameService.process_rename_webhook` called
straight from the webhook route. Sonarr waited up to ten seconds for Discord to
answer, and adding retries would have made that worse. Announcements are now
handed to this worker and the caller returns immediately.

One daemon thread, one bounded queue. Bounded matters: a Discord outage with an
unbounded queue is a slow memory leak that looks like nothing at all until it
does not. When it fills, the oldest waiting announcement is dropped and the
drop is logged — losing one notification is better than losing the process.
"""

import logging
import queue
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 500
#: How long `stop()` waits for the worker to finish what it is holding.
SHUTDOWN_GRACE_SECONDS = 5.0

_SENTINEL = object()


class Dispatcher:
    """A single background worker running one function over queued items."""

    def __init__(self, handler: Callable[[Any], None], *,
                 maxsize: int = DEFAULT_QUEUE_SIZE,
                 synchronous: bool = False,
                 name: str = 'connector-dispatch'):
        self._handler = handler
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=maxsize)
        self._thread: Optional[threading.Thread] = None
        self._name = name
        self._lock = threading.Lock()
        #: Tests and the CLI want deliveries to happen inline so the assertion
        #: after the call can see them. Nothing about the behaviour changes,
        #: only when it happens.
        self.synchronous = synchronous
        self.dropped = 0

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self.synchronous:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name=self._name, daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = SHUTDOWN_GRACE_SECONDS) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is None:
            return
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            # Full queue and shutting down: the worker is stuck on something
            # slow. It is a daemon thread, so leaving it is safe.
            pass
        thread.join(timeout=timeout)

    # ---- work --------------------------------------------------------------

    def submit(self, item: Any) -> bool:
        """Queue one item. Returns False when it was dropped.

        Never raises and never blocks — every caller is on a path that must not
        be held up by a notification.
        """
        if self.synchronous:
            self._handle(item)
            return True

        self.start()
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            # Drop the oldest rather than the newest: what just happened is
            # more useful than what happened while the service was down.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self._queue.put_nowait(item)
                self.dropped += 1
                logger.warning(
                    "Connector dispatch queue full; dropped the oldest pending "
                    "notification (%d dropped so far)", self.dropped
                )
                return True
            except queue.Empty:
                return False
            except queue.Full:
                self.dropped += 1
                return False

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait until everything queued has been handled. Tests only."""
        if self.synchronous:
            return
        self._queue.join()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    # ---- internals ---------------------------------------------------------

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                self._queue.task_done()
                return
            try:
                self._handle(item)
            finally:
                self._queue.task_done()

    def _handle(self, item: Any) -> None:
        try:
            self._handler(item)
        except Exception:
            # The worker outlives any single failure. A handler that raises is
            # a bug, but it must not take the thread with it and silently stop
            # every later notification.
            logger.exception("Connector dispatch handler failed")
