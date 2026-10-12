#!/usr/bin/env python3
"""
Sonarr.

Phase 1: stores an address and an API key, and proves they work. Nothing in
the application uses it yet, and the connector's page says so rather than
implying a feature that is not there.

Phase 2 (TASK-020) is where this earns its place: asking whether a season is
still downloading, so an automatic sync starts when the season is actually
complete instead of when `SERIES_ANIME_SYNC_WAIT_TIME` runs out.
"""

from typing import Any, Dict, List, Optional, Tuple

from services.connectors.adapters._arr import UNKNOWN, ArrConnector, InFlight
from services.connectors.registry import register


@register
class SonarrConnector(ArrConnector):
    id = 'sonarr'
    display_name = 'Sonarr'
    description = (
        'TV and anime library manager. Already sends notifications here; '
        'connecting it lets DragonCP ask questions back.'
    )

    #: Sonarr filters the queue by series on its side, and every row carries
    #: the season it belongs to — so one call answers a season question with no
    #: per-episode fan-out. The unfiltered endpoint pages at 10 and cannot
    #: filter at all, which is why it is not the one used.
    queue_filter_param = 'seriesId'
    library_path = '/api/v3/series'
    external_id_field = 'tvdbId'

    #: With these, a history or queue row carries its series and its episode —
    #: the "1x08 Episode Title" an operator reads in Sonarr's own screens.
    history_include = {'includeSeries': 'true', 'includeEpisode': 'true'}
    queue_include = {'includeSeries': 'true', 'includeEpisode': 'true'}

    #: Sonarr's `EpisodeHistoryEventType`. "Imported" is an import from a
    #: download (3), the same event the auto-scanner reads; one number per
    #: filter, because older versions read only one.
    history_event_types = {
        'grabbed': 1,
        'imported': 3,
        'failed': 4,
        'deleted': 5,
        'renamed': 6,
        'ignored': 7,
    }

    def _row_id(self, row) -> Any:
        return row.get('seriesId')

    def episodes(self, series_id: Any) -> Tuple[bool, List[Dict[str, Any]]]:
        """Every episode Sonarr knows for a series: numbers, titles, air dates, files.

        One call per series, made only when a person opens that title. The
        library list never makes it — a call per title would be hundreds of
        requests for one page.
        """
        if series_id in (None, ''):
            return False, []
        ok, rows = self._get('/api/v3/episode', {'seriesId': series_id}, timeout=20.0)
        if not ok or not isinstance(rows, list):
            return False, []
        return True, [r for r in rows if isinstance(r, dict)]

    def title_history(self, series_id: Any) -> Tuple[bool, List[Dict[str, Any]]]:
        """Everything Sonarr recorded for one series, with each episode folded in.

        One call, made when a person opens the series' History. Sonarr answers
        with the whole list rather than a page; the caller keeps the newest.
        """
        if series_id in (None, ''):
            return False, []
        ok, rows = self._get('/api/v3/history/series',
                             {'seriesId': series_id, 'includeEpisode': 'true'}, timeout=20.0)
        if not ok or not isinstance(rows, list):
            return False, []
        return True, [r for r in rows if isinstance(r, dict)]

    def episode_files(self, series_id: Any) -> Tuple[bool, List[Dict[str, Any]]]:
        """Every file Sonarr holds for a series: where it sits, its size, its quality."""
        if series_id in (None, ''):
            return False, []
        ok, rows = self._get('/api/v3/episodefile', {'seriesId': series_id}, timeout=20.0)
        if not ok or not isinstance(rows, list):
            return False, []
        return True, [r for r in rows if isinstance(r, dict)]

    def in_flight(self, series_id: Any,
                  season_number: Optional[int] = None) -> InFlight:
        """Is anything still arriving for this series, or this one season.

        Never raises. Returns an answer whose `known` flag says whether it can
        be trusted; the caller falls back to the fixed wait when it cannot.
        """
        ok, rows = self.queue_rows(series_id)
        if not ok:
            return UNKNOWN

        label = 'this series'
        if season_number is not None:
            rows = [r for r in rows if r.get('seasonNumber') == season_number]
            label = f'season {season_number}'

        # A row Sonarr cannot attribute to this series cannot hold it. The
        # filter is server-side, but a mismatched row would mean the filter was
        # ignored — the exact failure Radarr's plural parameter produces.
        rows = [r for r in rows
                if self._row_id(r) in (None, series_id)]

        return self._assess(rows, label)

    def season_files(self, series_id: Any, season_number: int):
        """How much of one season the service already holds a file for."""
        ok, episodes = self._get('/api/v3/episode',
                                 {'seriesId': series_id,
                                  'seasonNumber': season_number})
        if not ok or not isinstance(episodes, list):
            return None
        episodes = [e for e in episodes if isinstance(e, dict)]
        return {
            'episodes_total': len(episodes),
            'episodes_with_file': sum(1 for e in episodes if e.get('hasFile')),
            'episodes_monitored': sum(1 for e in episodes if e.get('monitored')),
        }
