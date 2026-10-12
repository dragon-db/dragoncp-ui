#!/usr/bin/env python3
"""
Radarr.

Phase 1: stores an address and an API key, and proves they work. Nothing uses
it yet.

Phase 2 (TASK-020) is the same question Sonarr answers, and simpler — one
movie, one file — so a movie sync can wait for the download to finish rather
than starting on the notification.
"""

from typing import Any, Dict, List, Tuple

from services.connectors.adapters._arr import UNKNOWN, ArrConnector, InFlight
from services.connectors.registry import register


@register
class RadarrConnector(ArrConnector):
    id = 'radarr'
    display_name = 'Radarr'
    description = (
        'Film library manager. Already sends notifications here; connecting '
        'it lets DragonCP ask questions back.'
    )

    #: **Singular.** `movieIds` is accepted, ignored, and answers 200 with the
    #: whole queue — verified against Radarr v6, where filtering on a film
    #: with one queued download returned every row in the queue. Using the
    #: plural would have held every film sync whenever anything was downloading,
    #: and looked like it was working.
    queue_filter_param = 'movieId'
    library_path = '/api/v3/movie'
    external_id_field = 'tmdbId'

    #: With this, a history or queue row carries the film's title and year
    #: even when DragonCP has never heard of it.
    history_include = {'includeMovie': 'true'}
    queue_include = {'includeMovie': 'true'}

    #: Radarr's `MovieHistoryEventType` — the same as Sonarr's up to "failed",
    #: then numbered differently (5 and 7 are unused here).
    history_event_types = {
        'grabbed': 1,
        'imported': 3,
        'failed': 4,
        'deleted': 6,
        'renamed': 8,
        'ignored': 9,
    }

    def _row_id(self, row) -> Any:
        return row.get('movieId')

    def title_history(self, movie_id: Any) -> Tuple[bool, List[Dict[str, Any]]]:
        """Everything Radarr recorded for one film. One call, when someone opens it."""
        if movie_id in (None, ''):
            return False, []
        ok, rows = self._get('/api/v3/history/movie', {'movieId': movie_id}, timeout=20.0)
        if not ok or not isinstance(rows, list):
            return False, []
        return True, [r for r in rows if isinstance(r, dict)]

    def in_flight(self, movie_id: Any) -> InFlight:
        """Is anything still arriving for this film."""
        ok, rows = self.queue_rows(movie_id)
        if not ok:
            return UNKNOWN

        # Two reasons a row is dropped here, both seen live:
        #   * it names no film at all — Radarr could not attribute the download,
        #     so it cannot speak for this one;
        #   * it names a different film — which means the filter did not apply,
        #     and obeying the response would block on somebody else's download.
        rows = [r for r in rows if self._row_id(r) == movie_id]

        return self._assess(rows, 'this film')

    def has_file(self, movie_id: Any):
        """Whether the film now has a file. None when unanswerable."""
        ok, movie = self._get(f'/api/v3/movie/{movie_id}')
        if not ok or not isinstance(movie, dict):
            return None
        return bool(movie.get('hasFile'))
