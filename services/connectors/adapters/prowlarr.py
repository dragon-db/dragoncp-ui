#!/usr/bin/env python3
"""
Prowlarr.

Search every indexer, a chosen few, or only torrent or only usenet ones, and
see which indexers are healthy. Prowlarr runs on another machine, reached
over HTTPS at the saved address, so every call here crosses the network: the
page reads Prowlarr's own state through a short cache, and a search asks it
a bounded number of questions at a time. What reaches the indexers is
Prowlarr asking them, and that only happens when the operator presses Search,
tests one indexer, or sends a release to a download client.

Nothing here searches on its own, retries a search, or tests every indexer at
once: private trackers count API hits, and a retry is a second hit.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode, urlparse

from services.connectors import transport
from services.connectors.base import CAP_QUERY, CheckResult, ConfigField, Connector
from services.connectors.registry import register

#: Reads of Prowlarr's own state (indexers, health, stats) answer from its
#: database; the time is mostly the trip to the other machine.
READ_TIMEOUT = 15.0
#: One indexer's search. Prowlarr waits on the indexer before answering, and a
#: slow tracker can take most of a minute.
SEARCH_TIMEOUT = 75.0
#: Testing an indexer or grabbing a release waits on the indexer too.
WRITE_TIMEOUT = 45.0
#: The largest .torrent or .nzb handed back. A season pack's .nzb can be a few
#: megabytes; nothing legitimate comes near this.
MAX_FILE_BYTES = 10 * 1024 * 1024


def _truthy(value: Any) -> bool:
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class Answer:
    """One answer from Prowlarr: what it said, or what went wrong, in plain words."""

    ok: bool
    data: Any = None
    error: str = ''
    status: Optional[int] = None
    duration_ms: int = 0


@register
class ProwlarrConnector(Connector):
    id = 'prowlarr'
    display_name = 'Prowlarr'
    description = 'Indexer manager. Search every indexer from DragonCP and see which are healthy.'
    capabilities = frozenset({CAP_QUERY})
    views = ('search', 'indexers')

    config_fields = (
        ConfigField(
            'base_url', 'Address',
            'Where Prowlarr is reachable from the DragonCP host.',
            kind='url', required=True, placeholder='http://localhost:9696',
            group='connection',
        ),
        ConfigField(
            'api_key', 'API key',
            'Settings → General → Security → API Key in Prowlarr.',
            kind='password', secret=True, required=True, group='connection',
        ),
        ConfigField(
            'allow_grabs', 'Allow sending releases from this instance',
            'Only matters on a test instance (TEST_MODE on). There, "Send to '
            'download client" is refused until this is on, because it starts a '
            'real download. Searching is always allowed. A normal instance '
            'always allows it.',
            kind='boolean', group='changes',
        ),
    )

    config_groups = (
        ('connection', 'Address and key', 'Where DragonCP reaches it.'),
        ('changes', 'Changes', 'What this instance may start.'),
    )

    settings_description = 'How DragonCP reaches it, and what it may start.'

    # -- settings ------------------------------------------------------------

    def allows_grabs(self) -> bool:
        return _truthy(self.setting('allow_grabs'))

    # -- talking to Prowlarr -------------------------------------------------

    def _base(self) -> str:
        base = self.setting('base_url').rstrip('/')
        # Accept the address with or without the API prefix pasted on.
        if base.endswith('/api/v1'):
            base = base[:-len('/api/v1')]
        return base

    def _headers(self) -> Dict[str, str]:
        return {'X-Api-Key': self.secret('api_key'), 'Accept': 'application/json'}

    def _call(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
              body: Any = None, timeout: float = READ_TIMEOUT,
              missing: str = 'Prowlarr has no such item') -> Answer:
        if not self._base():
            return Answer(False, error='No address set')
        url = f"{self._base()}/api/v1{path}"
        if params:
            clean = {k: v for k, v in params.items() if v not in (None, '', [], ())}
            if clean:
                # doseq: Prowlarr takes lists as repeated keys,
                # `indexerIds=1&indexerIds=4`.
                url = f"{url}?{urlencode(clean, doseq=True)}"
        # Never retried: a second search is a second hit on every tracker, and
        # a second grab is a second download.
        result = transport.send(method, url, json=body, headers=self._headers(),
                                timeout=timeout, max_retries=0)
        if result.ok:
            return Answer(True, data=result.json, status=result.status_code,
                          duration_ms=result.duration_ms)
        status = result.status_code
        if status in (401, 403):
            return Answer(False, error='Prowlarr rejected the API key', status=status,
                          duration_ms=result.duration_ms)
        if status == 404:
            return Answer(False, error=missing, status=status, duration_ms=result.duration_ms)
        said = _said(result.json)
        if status and said:
            return Answer(False, error=f"Prowlarr said: {said[:300]}", status=status,
                          duration_ms=result.duration_ms)
        return Answer(False, error=result.error or 'Could not reach Prowlarr', status=status,
                      duration_ms=result.duration_ms)

    def check(self) -> CheckResult:
        if not self._base():
            return CheckResult(False, 'No address set')
        status = self._call('GET', '/system/status')
        if not status.ok:
            return CheckResult(False, status.error)
        data = status.data if isinstance(status.data, dict) else {}
        version = data.get('version')
        if not version or str(data.get('appName') or 'Prowlarr').lower() != 'prowlarr':
            return CheckResult(False, 'Something answered, but it was not Prowlarr. Check the address.')
        return CheckResult(True, f"Connected to Prowlarr {version}", detail={'version': version})

    # -- Prowlarr's own state ------------------------------------------------

    def status(self) -> Answer:
        return self._call('GET', '/system/status')

    def indexers(self) -> Answer:
        return self._call('GET', '/indexer')

    def indexer(self, indexer_id: int) -> Answer:
        return self._call('GET', f'/indexer/{int(indexer_id)}',
                          missing='Prowlarr has no such indexer any more')

    def indexer_status(self) -> Answer:
        """Indexers Prowlarr has switched off for a while after failures."""
        return self._call('GET', '/indexerstatus')

    def indexer_stats(self, start: Optional[str] = None) -> Answer:
        return self._call('GET', '/indexerstats', params={'startDate': start})

    def health(self) -> Answer:
        return self._call('GET', '/health')

    def download_clients(self) -> Answer:
        return self._call('GET', '/downloadclient')

    # -- the parts that reach indexers ---------------------------------------

    def search(self, query: str, *, search_type: str = 'search',
               indexer_ids: Iterable[int] = (), categories: Iterable[int] = (),
               limit: int = 100, offset: int = 0) -> Answer:
        """One search. Pass one indexer id to hear from that indexer alone."""
        return self._call('GET', '/search', params={
            'query': query, 'type': search_type,
            'indexerIds': [int(i) for i in indexer_ids],
            'categories': [int(c) for c in categories],
            'limit': int(limit), 'offset': int(offset),
        }, timeout=SEARCH_TIMEOUT)

    def grab(self, guid: str, indexer_id: int,
             download_client_id: Optional[int] = None) -> Answer:
        """Hand a release from a recent search to Prowlarr's download client."""
        body: Dict[str, Any] = {'guid': guid, 'indexerId': int(indexer_id)}
        if download_client_id:
            body['downloadClientId'] = int(download_client_id)
        return self._call('POST', '/search', body=body, timeout=WRITE_TIMEOUT,
                          missing='Prowlarr no longer has this release. Search again.')

    def test_indexer(self, indexer_id: int) -> Answer:
        """Ask Prowlarr to test one indexer, the way its own Test button does."""
        current = self.indexer(indexer_id)
        if not current.ok or not isinstance(current.data, dict):
            return current if not current.ok else Answer(False, error='Prowlarr did not answer')
        return self._call('POST', '/indexer/test', body=current.data, timeout=WRITE_TIMEOUT,
                          missing='Prowlarr has no such indexer any more')

    def download(self, url: str) -> transport.DownloadResult:
        """A release's .torrent or .nzb, or its magnet link, through Prowlarr.

        `url` is the download address from Prowlarr's own search answer, which
        carries Prowlarr's API key; it never leaves the server.
        """
        target = self.download_url(url)
        if not target:
            return transport.DownloadResult(False, error='That download is not from Prowlarr')
        return transport.fetch_download(target, headers=self._headers(),
                                        timeout=WRITE_TIMEOUT, max_bytes=MAX_FILE_BYTES)

    def download_url(self, url: str) -> str:
        """`url` re-pointed at the saved address, or '' when it is not Prowlarr's.

        Prowlarr writes its download links with the address it believes it has,
        which behind a proxy can be `http://` or another host name than the one
        saved here. Only the path and query are kept, so a download can only
        ever go to the Prowlarr this connector is set up for.
        """
        base = self._base()
        try:
            parsed = urlparse(url or '')
        except ValueError:
            return ''
        if not base or parsed.scheme not in ('http', 'https') or not parsed.path:
            return ''
        prefix = urlparse(base).path.rstrip('/')
        path = parsed.path
        if prefix and not path.startswith(prefix + '/'):
            path = prefix + path
        root = base[:len(base) - len(prefix)] if prefix else base
        return f"{root}{path}" + (f"?{parsed.query}" if parsed.query else '')


def _said(payload: Any) -> str:
    """What Prowlarr said in an error answer: a message, or validation failures."""
    if isinstance(payload, dict):
        return str(payload.get('message') or payload.get('error')
                   or payload.get('description') or '').strip()
    if isinstance(payload, list):
        parts = [str(item.get('errorMessage') or '').strip()
                 for item in payload if isinstance(item, dict)]
        return '; '.join(p for p in parts if p)
    return ''
