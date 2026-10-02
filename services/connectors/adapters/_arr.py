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
    eta_seconds: Optional[int] = None
    detail: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def clear(self) -> bool:
        """A definite "nothing is coming, go now"."""
        return self.known and self.blocking == 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            'known': self.known, 'blocking': self.blocking, 'total': self.total,
            'stalled': self.stalled, 'reason': self.reason,
            'eta_seconds': self.eta_seconds, 'detail': list(self.detail),
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
        # -- the safety net under the webhook ------------------------------
        # These live on the connector rather than in app settings because they
        # describe this link: two services can be swept on different schedules,
        # and one can be trusted to sync on its own while the other is watched
        # first. A single global pair could express neither.
        ConfigField(
            'sweep_enabled', 'Check for missed imports',
            'Periodically ask this service what it imported, and compare it with '
            'what is on the disk here. This is what catches an import whose '
            'notification never arrived.',
            kind='boolean',
        ),
        ConfigField(
            'sweep_interval_minutes', 'How often to check (minutes)',
            'Between 5 and 360. One request per check, so a short interval costs '
            'the service almost nothing.',
            kind='number', placeholder='15',
        ),
        ConfigField(
            'sweep_auto_sync', 'Sync what it finds automatically',
            'Off (the default): findings are reported — a Discord warning, and a '
            'Sync button on each affected title in the Library tab — and nothing '
            'is fetched until you press it. That is the setting for a library '
            'where some titles are deliberately not kept here. On: gaps are '
            'synced without asking, through the same safety checks as any other '
            'sync.',
            kind='boolean',
        ),
    )

    # -- reading those back ------------------------------------------------

    def sweep_enabled(self) -> bool:
        return _truthy(self.setting('sweep_enabled'))

    def sweep_auto_sync(self) -> bool:
        """Whether a finding may act on its own.

        Deliberately separate from `sweep_enabled`: watching and acting are
        different amounts of trust, and an operator should be able to see what
        the sweep *would* do for a while before letting it.
        """
        return _truthy(self.setting('sweep_auto_sync'))

    def sweep_interval_minutes(self) -> int:
        try:
            value = int(str(self.setting('sweep_interval_minutes') or 15).strip())
        except (TypeError, ValueError):
            return 15
        return max(5, min(360, value))

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

        if state == 'importblocked':
            return {'verdict': 'blocked', 'holds': True,
                    'why': (_first_status_message(row)
                            or 'Import is blocked and needs a person')}
        if state == 'failedpending':
            return {'verdict': 'failed', 'holds': True,
                    'why': 'Failed, waiting on a retry decision'}

        return {'verdict': state, 'holds': True, 'why': f'Still {state}'}

    def _assess(self, rows: List[Dict[str, Any]], label: str) -> InFlight:
        """Turn queue rows into a hold-or-go answer."""
        blocking, stalled, detail, etas = 0, 0, [], []
        for row in rows:
            title = row.get('title') or 'an item'
            verdict = self.classify_row(row)

            if verdict['verdict'] == 'stalled':
                stalled += 1
            if not verdict['holds']:
                if verdict['verdict'] not in ('imported',):
                    detail.append(f"{title}: {verdict['why']}")
                continue

            blocking += 1
            detail.append(f"{title}: {verdict['why']}")
            eta = row.get('timeleft')
            if eta:
                etas.append(str(eta))

        if blocking:
            reason = f"{blocking} still arriving for {label}"
            if stalled:
                reason += f" ({stalled} stalled, not counted)"
        elif stalled:
            reason = f"nothing moving for {label} — {stalled} stalled"
        else:
            reason = f"nothing in flight for {label}"

        return InFlight(
            known=True, blocking=blocking, total=len(rows), stalled=stalled,
            reason=reason, detail=tuple(detail[:8]),
        )

    def imports_since(self, since_iso: str) -> Tuple[bool, List[Dict[str, Any]]]:
        """What this service says it imported since a moment.

        The catch-up sweep's source. A webhook that never arrived leaves no
        trace anywhere in this application, so the only way to notice is to ask
        the service what it did rather than to re-read our own record of being
        told.
        """
        ok, rows = self._get('/api/v3/history/since',
                             {'date': since_iso, 'eventType': 3}, timeout=25.0)
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
