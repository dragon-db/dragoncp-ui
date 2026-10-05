#!/usr/bin/env python3
"""
What Sonarr and Radarr have in common.

Both are the same application with a different noun, down to the API shape:
`/api/v3/system/status` behind an `X-Api-Key` header. Writing the connection
handling twice would be the exact duplication this whole layer exists to
remove, so it is written once here and each adapter says only what differs.

Phase 1 stops at "these credentials work". Phase 2 (TASK-020) adds the queries
that let a season sync wait for the season to actually be complete instead of
for a timer.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from env_flags import test_mode_enabled
from services.connectors import transport
from services.connectors.base import (
    CAP_QUERY,
    CheckResult,
    ConfigField,
    Connector,
)

#: Queue states that mean something is genuinely still on its way.
#:
#: `imported` is deliberately absent, and it is the load-bearing omission. A
#: torrent client keeps seeding long after the file has been filed, and the
#: queue row stays for the whole of it — so "the queue is empty" would make
#: every season sync wait out a seed ratio.
BLOCKING_STATES = frozenset({
    'downloading', 'importpending', 'importing', 'importblocked', 'failedpending',
})

#: A state this version has never heard of does **not** hold a sync.
#:
#: The two failure modes are not symmetrical. Blocking on an unrecognised state
#: stalls syncs indefinitely with no symptom; not blocking starts a sync early,
#: which is exactly what the fixed timer does today and which the catch-up
#: sweep repairs. Degrading to current behaviour beats degrading to silence.
UNKNOWN_STATE_BLOCKS = False


@dataclass(frozen=True)
class InFlight:
    """Whether anything is still on its way for one title.

    `known` is the field that matters. False means no usable answer was had —
    unconfigured, unreachable, rejected, nonsense response — and every caller
    must then behave exactly as it did before this feature existed. A sync must
    never fail, or stall, because a status check failed.
    """

    known: bool
    blocking: int = 0
    total: int = 0
    stalled: int = 0
    #: Operator-facing, already plain English.
    reason: str = ''
    #: How long the slowest download still holding the sync expects to take,
    #: from the service's own "time left". None when it gave no estimate.
    eta_seconds: Optional[int] = None
    detail: Tuple[str, ...] = field(default_factory=tuple)
    #: Downloads that will not finish on their own — stalled, failed, or
    #: blocked from importing. Counted so the sync can say it went without
    #: them; they never hold a season (decided 2026-10-02).
    stuck: int = 0
    stuck_detail: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def clear(self) -> bool:
        """A definite "nothing is coming, go now"."""
        return self.known and self.blocking == 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            'known': self.known, 'blocking': self.blocking, 'total': self.total,
            'stalled': self.stalled, 'reason': self.reason,
            'eta_seconds': self.eta_seconds, 'detail': list(self.detail),
            'stuck': self.stuck, 'stuck_detail': list(self.stuck_detail),
        }


UNKNOWN = InFlight(known=False, reason='No usable answer from the service')

#: The only verbs this connector is ever allowed to use.
#:
#: Sonarr and Radarr are read *from*, never written to. DragonCP has no reason
#: to add a series, trigger a search or delete a file on the other side — it
#: syncs what has already been imported. Holding an API key that could do those
#: things and simply never calling them is a property of today's code; this is
#: the same property written down where it cannot be lost in a later edit.
READ_ONLY_METHODS = frozenset({'GET', 'HEAD'})


class ArrConnector(Connector):
    """Shared base for Sonarr and Radarr."""

    capabilities = frozenset({CAP_QUERY})

    config_fields = (
        ConfigField(
            'base_url', 'Address',
            'Where this service is reachable from the DragonCP host.',
            kind='url', required=True, placeholder='http://localhost:8989',
        ),
        ConfigField(
            'api_key', 'API key',
            'Settings → General → Security → API Key in the service itself.',
            kind='password', secret=True, required=True,
        ),
        # -- the scheduled auto-scanner --------------------------------------
        # These live on the connector rather than in app settings because they
        # describe this link: two services can be scanned on different
        # schedules, and one can be switched on while the other is not.
        ConfigField(
            'auto_scanner_enabled', 'Scheduled auto-scanner',
            'Every few minutes, ask this service what it imported — new episodes, '
            'new titles, upgrades — and sync anything this disk does not have yet, '
            'through the same pipeline and safety checks as a webhook. Also fills '
            'in missing episodes of seasons this disk already keeps. This is what '
            'catches a webhook that never arrived. Off by default.',
            kind='boolean',
        ),
        ConfigField(
            'auto_scanner_interval_minutes', 'Scan every (minutes)',
            'Between 5 and 360. Each scan is a few read-only requests to the service.',
            kind='number', placeholder='15',
        ),
    )

    # -- reading those back ------------------------------------------------

    def auto_scanner_enabled(self) -> bool:
        """Whether the scheduled auto-scanner runs for this service.

        One switch: on means scan and sync, and off until someone turns it on
        (decided 2026-10-02). The earlier missed-import check's two switches
        never shipped in a release, so nothing is read from them: a scanner
        that ran while its switch showed off would be worse than one that
        waits to be turned on.
        """
        return _truthy(self.setting('auto_scanner_enabled'))

    def auto_scanner_interval_minutes(self) -> int:
        raw = self.setting('auto_scanner_interval_minutes') or 15
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return 15
        return max(5, min(360, value))

    def season_folder(self, series_id: Any, season_number: int) -> Optional[str]:
        """What this season's folder is actually called on the media server.

        Read from a file the service holds for the season ("Season 01/…"), so a
        library whose folders are named "Season 1" or "Specials" is copied from
        the folder that exists rather than one rebuilt by convention. None when
        the service holds no file for the season or cannot be asked.
        """
        ok, files = self._get('/api/v3/episodefile', {'seriesId': series_id}, timeout=20.0)
        if not ok or not isinstance(files, list):
            return None
        for item in files:
            if not isinstance(item, dict) or item.get('seasonNumber') != season_number:
                continue
            relative = str(item.get('relativePath') or '').replace('\\', '/')
            if '/' in relative:
                return relative.split('/', 1)[0]
        return None

    #: Overridden per service only if the path ever diverges.
    status_path = '/api/v3/system/status'

    #: The queue parameter that names one title. Radarr's is **singular**;
    #: the plural form is accepted, silently ignored, and answers 200 with the
    #: entire queue — which would have blocked every film whenever anything at
    #: all was downloading. Verified against the live services, not the docs.
    queue_filter_param = ''

    def base_url(self) -> str:
        return self.setting('base_url').rstrip('/')

    def api_key(self) -> str:
        return self.secret('api_key')

    def check(self) -> CheckResult:
        base = self.base_url()
        if not base:
            return CheckResult(False, 'No address set')

        result = transport.send(
            'GET', f"{base}{self.status_path}",
            headers={'X-Api-Key': self.api_key()},
            timeout=8,
        )

        if not result.ok:
            if result.status_code in (401, 403):
                return CheckResult(False, 'The API key was rejected')
            return CheckResult(False, result.error or 'Could not reach the service')

        payload = result.json or {}
        version = payload.get('version')
        name = payload.get('appName') or self.display_name
        if version:
            return CheckResult(
                True, f"Connected to {name} {version}",
                detail={'version': version, 'app_name': name},
            )
        # A 200 with a body that is not the status document usually means a
        # reverse proxy or a login page answered instead of the service.
        return CheckResult(
            False,
            'Something answered, but it was not this service. Check the address.',
        )

    def request(self, path: str, *, params: Optional[dict] = None,
                timeout: float = 15.0):
        """One authenticated call. The phase 2 clients build on this."""
        base = self.base_url()
        if not base:
            return transport.TransportResult(False, error='No address set')
        url = f"{base}{path}"
        if params:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"
        return transport.send(
            'GET', url, headers={'X-Api-Key': self.api_key()}, timeout=timeout,
        )


    # -- asking questions ----------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None,
             timeout: float = 12.0) -> Tuple[bool, Any]:
        """One read. Returns (usable, parsed). Never raises, never blocks long."""
        return self._request('GET', path, params, timeout)

    def _request(self, method: str, path: str,
                 params: Optional[Dict[str, Any]] = None,
                 timeout: float = 12.0) -> Tuple[bool, Any]:
        """One call to the service, refused unless it only reads.

        Two separate refusals, and they mean different things:

          * a verb outside `READ_ONLY_METHODS` is refused **always**. Nothing in
            this application has a reason to change anything in Sonarr or
            Radarr, so a write is a mistake rather than a mode.
          * in test mode the refusal is stated in the log, because test mode is
            precisely when someone is exercising paths they are not sure about,
            with a real API key that would really work.

        Refusal returns the same `(False, None)` an unreachable service returns,
        so a caller cannot accidentally treat it as an answer.
        """
        verb = (method or '').upper()
        if verb not in READ_ONLY_METHODS:
            if test_mode_enabled():
                print(f"🧪 TEST_MODE: refused {verb} {path} to {self.display_name} "
                      f"— these connectors are read-only")
            else:
                print(f"⛔ Refused {verb} {path} to {self.display_name} "
                      f"— these connectors are read-only")
            return False, None

        base = self.base_url()
        if not base or not self.api_key():
            return False, None
        query = ''
        if params:
            from urllib.parse import urlencode
            query = '?' + urlencode({k: v for k, v in params.items()
                                     if v not in (None, '')})
        result = transport.send(
            verb, f"{base}{path}{query}",
            headers={'X-Api-Key': self.api_key()}, timeout=timeout,
        )
        if not result.ok:
            return False, None
        parsed = result.json
        # A 200 carrying something that is not JSON is a reverse proxy or a
        # login page answering in the service's place. Not an answer.
        if parsed is None:
            return False, None
        return True, parsed

    def queue_rows(self, item_id: Any) -> Tuple[bool, List[Dict[str, Any]]]:
        """The queue rows this service attributes to one title."""
        if not self.queue_filter_param or item_id in (None, ''):
            return False, []
        ok, rows = self._get('/api/v3/queue/details',
                             {self.queue_filter_param: item_id})
        if not ok or not isinstance(rows, list):
            return False, []
        return True, [r for r in rows if isinstance(r, dict)]

    def _row_id(self, row: Dict[str, Any]) -> Any:
        """The title id a queue row belongs to, or None if it names none."""
        raise NotImplementedError

    @staticmethod
    def _is_stalled(row: Dict[str, Any]) -> bool:
        """A row that reads as active but is not moving.

        Seen live: a film sitting at 0% with "The download is stalled with no
        connections". Holding a sync for that burns the whole window for
        nothing, and the catch-up sweep collects the file if it ever lands.
        """
        message = (row.get('errorMessage') or '').lower()
        if 'stalled' in message or 'no connections' in message:
            return True
        size, left = row.get('size') or 0, row.get('sizeleft') or 0
        state = (row.get('trackedDownloadState') or '').lower()
        return bool(state == 'downloading' and size and left >= size)

    @staticmethod
    def _already_filed(row: Dict[str, Any]) -> bool:
        """The queue still lists it, but the library already has the file.

        Seen live: a row six days old, still `importPending`, whose episode
        reported `episodeHasFile` true. Trusting the queue alone would have
        held that season for ever.
        """
        return bool(row.get('episodeHasFile'))

    def classify_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """What one queue row means, and whether it holds a sync.

        The single place that judgement is made. The gate and the queue view
        both call it, so the screen an operator reads and the decision the
        scheduler takes can never disagree — which they would, silently, if each
        grew its own copy of these rules.
        """
        state = (row.get('trackedDownloadState') or '').lower()

        if state not in BLOCKING_STATES:
            if state == 'imported':
                return {'verdict': 'imported', 'holds': False,
                        'why': 'Filed. The row stays while the client seeds'}
            if not state:
                return {'verdict': 'unknown', 'holds': False,
                        'why': 'No state reported'}
            return {'verdict': 'unrecognised', 'holds': UNKNOWN_STATE_BLOCKS,
                    'why': f"State '{state}' is not one this version knows"}

        if self._already_filed(row):
            return {'verdict': 'stale', 'holds': False,
                    'why': 'The library already has the file; this row is stale'}

        if self._is_stalled(row):
            return {'verdict': 'stalled', 'holds': False,
                    'why': (row.get('errorMessage')
                            or 'Downloading, but nothing is moving')}

        # Stuck does not block (decided 2026-10-02). A download blocked from
        # importing, or failed and waiting on a retry decision, will not finish
        # on its own — holding the whole season for it means the season never
        # syncs. The sync goes without it and says so; the episode arrives later
        # through its own webhook or the auto-scanner.
        if state == 'importblocked':
            return {'verdict': 'blocked', 'holds': False,
                    'why': (_first_status_message(row)
                            or 'Import is blocked and needs a person')}
        if state == 'failedpending':
            return {'verdict': 'failed', 'holds': False,
                    'why': 'Failed, waiting on a retry decision'}

        return {'verdict': state, 'holds': True, 'why': f'Still {state}'}

    #: Verdicts that mean "this will not finish by itself".
    STUCK_VERDICTS = frozenset({'stalled', 'blocked', 'failed'})

    def _assess(self, rows: List[Dict[str, Any]], label: str) -> InFlight:
        """Turn queue rows into a hold-or-go answer."""
        blocking, stalled, detail, etas = 0, 0, [], []
        stuck, stuck_detail = 0, []
        for row in rows:
            title = row.get('title') or 'an item'
            verdict = self.classify_row(row)

            if verdict['verdict'] == 'stalled':
                stalled += 1
            if verdict['verdict'] in self.STUCK_VERDICTS:
                stuck += 1
                stuck_detail.append(f"{title}: {verdict['why']}")
            if not verdict['holds']:
                if verdict['verdict'] not in ('imported',) + tuple(self.STUCK_VERDICTS):
                    detail.append(f"{title}: {verdict['why']}")
                continue

            blocking += 1
            eta = _seconds_left(row)
            if eta is not None:
                etas.append(eta)
            left = _describe_progress(row)
            detail.append(f"{title}: {verdict['why']}{left}")

        if blocking:
            reason = f"{blocking} still arriving for {label}"
            if stuck:
                reason += f" ({stuck} stuck, not waited for)"
        elif stuck:
            reason = f"nothing moving for {label} — {stuck} stuck"
        else:
            reason = f"nothing in flight for {label}"

        return InFlight(
            known=True, blocking=blocking, total=len(rows), stalled=stalled,
            reason=reason, detail=tuple(detail[:8]),
            eta_seconds=max(etas) if etas else None,
            stuck=stuck, stuck_detail=tuple(stuck_detail[:8]),
        )

    def imports_since(self, since_iso: str) -> Tuple[bool, List[Dict[str, Any]]]:
        """What this service says it imported since a moment.

        The auto-scanner's main source. A webhook that never arrived leaves no
        trace anywhere in this application, so the only way to notice is to ask
        the service what it did rather than to re-read our own record of being
        told. Event type 3 is "imported from the download folder" in both
        Sonarr and Radarr — new files and upgrades alike. Sonarr is asked to
        include each episode, which is what carries its season number.
        """
        ok, rows = self._get('/api/v3/history/since',
                             {'date': since_iso, 'eventType': 3,
                              'includeEpisode': 'true'}, timeout=25.0)
        if not ok or not isinstance(rows, list):
            return False, []
        return True, [r for r in rows if isinstance(r, dict)]

    def library(self) -> Tuple[bool, List[Dict[str, Any]]]:
        """Everything the service holds. Used to refresh the title index."""
        ok, rows = self._get(self.library_path, timeout=30.0)
        if not ok or not isinstance(rows, list):
            return False, []
        return True, [r for r in rows if isinstance(r, dict)]

    #: Where the full catalogue lives, and which external id anchors a row.
    library_path = ''
    external_id_field = ''

    def history(self, page: int = 1, page_size: int = 50,
                event_type: Optional[int] = None) -> Tuple[bool, Dict[str, Any]]:
        """A page of what the service has done.

        Paged on the service's side — the history of a busy library is far too
        long to pull whole, and unlike the queue there is no filter that makes
        one page enough.
        """
        params: Dict[str, Any] = {
            'page': max(1, int(page or 1)),
            'pageSize': max(1, min(200, int(page_size or 50))),
            'sortKey': 'date',
            'sortDirection': 'descending',
        }
        if event_type is not None:
            params['eventType'] = event_type
        ok, payload = self._get('/api/v3/history', params, timeout=20.0)
        if not ok or not isinstance(payload, dict):
            return False, {}
        return True, payload

    def queue_all(self) -> Tuple[bool, List[Dict[str, Any]]]:
        """Every row in the service's queue, unfiltered.

        The view wants the whole thing — including the rows the service cannot
        attribute to any title, which are invisible in its own interface until
        you go looking and are exactly the kind that sit there for weeks.
        """
        ok, rows = self._get('/api/v3/queue/details', timeout=20.0)
        if not ok or not isinstance(rows, list):
            return False, []
        return True, [r for r in rows if isinstance(r, dict)]


def _truthy(value: Any) -> bool:
    """Connector settings are stored as text; booleans have to be read back."""
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _parse_timeleft(value: Any) -> Optional[int]:
    """Seconds from the service's "time left": "00:12:34" or "1.02:03:04"."""
    if value in (None, ''):
        return None
    text = str(value).strip()
    days = 0
    if '.' in text.split(':')[0]:
        day_part, text = text.split('.', 1)
        try:
            days = int(day_part)
        except ValueError:
            return None
    parts = text.split(':')
    if len(parts) != 3:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = int(float(parts[2]))
    except ValueError:
        return None
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _seconds_left(row: Dict[str, Any]) -> Optional[int]:
    """How long one download expects to take, or None if it does not say.

    "Time left" first, because it is the download client's own figure; the
    estimated completion time second, because it is the same figure dated.
    """
    left = _parse_timeleft(row.get('timeleft'))
    if left is not None:
        return max(0, left)
    eta = row.get('estimatedCompletionTime')
    if eta:
        from datetime import datetime, timezone
        try:
            moment = datetime.fromisoformat(str(eta).replace('Z', '+00:00'))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return max(0, int((moment - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            return None
    return None


def _describe_progress(row: Dict[str, Any]) -> str:
    """ " — 42%, about 3 min left" for one download, or nothing."""
    size, left = row.get('size') or 0, row.get('sizeleft') or 0
    bits = []
    if size:
        bits.append(f"{round(100 * (1 - left / size))}%")
    seconds = _seconds_left(row)
    if seconds is not None:
        if seconds < 90:
            bits.append(f"about {seconds} s left")
        else:
            bits.append(f"about {round(seconds / 60)} min left")
    return f" — {', '.join(bits)}" if bits else ''


def _first_status_message(row: Dict[str, Any]) -> str:
    """The service's own explanation, when it left one.

    `statusMessages` is where the useful sentence lives — "Movie title mismatch,
    automatic import is not possible" says what to do; `importBlocked` does not.
    """
    for entry in row.get('statusMessages') or []:
        if not isinstance(entry, dict):
            continue
        for message in entry.get('messages') or []:
            if message:
                return str(message)
    return ''
