#!/usr/bin/env python3
"""
Seerr.

The admin side only: requests waiting for approval, where approved ones have
got to, and the issues users reported. No discover, no making requests, no
Seerr users or settings; those stay in Seerr.

Seerr runs on the media server, so every call here is a local one. Two of
Seerr's own answers do reach the remote server, and both are bounded:

  * listing requests makes Seerr look up Sonarr's and Radarr's quality
    profiles, through Seerr's own rolling one-hour cache, so at most about
    one call an hour;
  * the "change before approving" choices (`service_detail`) ask Sonarr or
    Radarr live, and are only fetched when the operator opens that section.

Approving a request is what starts a download on the remote server; that is
the point of the button, and it goes through Seerr exactly as Seerr's own
button does.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from services.connectors import transport
from services.connectors.base import CAP_QUERY, CheckResult, ConfigField, Connector
from services.connectors.registry import register

#: Seerr is on this machine and answers reads in well under a second. A list
#: of requests waits on its database, so it gets a little more.
READ_TIMEOUT = 8.0
#: An approve hands the request to Sonarr or Radarr before Seerr answers.
WRITE_TIMEOUT = 20.0


def _truthy(value: Any) -> bool:
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class Answer:
    """One answer from Seerr: what it said, or what went wrong, in plain words."""

    ok: bool
    data: Any = None
    error: str = ''
    status: Optional[int] = None


@register
class SeerrConnector(Connector):
    id = 'seerr'
    display_name = 'Seerr'
    description = 'Requests and issues. Approve requests, follow them to Jellyfin, answer issues.'
    capabilities = frozenset({CAP_QUERY})
    views = ('requests', 'issues')

    config_fields = (
        ConfigField(
            'base_url', 'Address',
            'Where Seerr is reachable from the DragonCP host.',
            kind='url', required=True, placeholder='http://localhost:5055',
            group='connection',
        ),
        ConfigField(
            'api_key', 'API key',
            'Settings → General → API Key in Seerr. It acts as Seerr\'s owner '
            'account, so replies from DragonCP show under that name.',
            kind='password', secret=True, required=True, group='connection',
        ),
        ConfigField(
            'webhook_secret', 'Webhook password',
            'Any long random text. Paste the same text into Seerr: Settings → '
            'Notifications → Webhook → Authorization Header. Until this is set, '
            'DragonCP refuses anything sent to its Seerr webhook address.',
            kind='password', secret=True, group='updates',
        ),
        ConfigField(
            'poll', 'Check every 5 minutes',
            'Ask Seerr for the number of waiting requests and open issues every '
            '5 minutes, in case a webhook went missing. Off by default.',
            kind='boolean', group='updates',
        ),
        ConfigField(
            'allow_changes', 'Allow changes from this instance',
            'Only matters on a test instance (TEST_MODE on). There, Approve, '
            'Decline, Retry, Reply and Resolve are refused until this is on, '
            'because approving starts a real download on the remote server. A '
            'normal instance always allows them.',
            kind='boolean', group='updates',
        ),
    )

    config_groups = (
        ('connection', 'Address and key', 'Where DragonCP reaches it.'),
        ('updates', 'Updates and changes',
         'How DragonCP hears that something changed, and what it may change.'),
    )

    settings_description = 'How DragonCP reaches it, and how it stays up to date.'

    # -- settings ------------------------------------------------------------

    def polls(self) -> bool:
        return _truthy(self.setting('poll'))

    def allows_changes(self) -> bool:
        return _truthy(self.setting('allow_changes'))

    def webhook_secret(self) -> str:
        return self.secret('webhook_secret')

    # -- talking to Seerr ----------------------------------------------------

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
              missing: str = 'Seerr has no such item') -> Answer:
        if not self._base():
            return Answer(False, error='No address set')
        url = f"{self._base()}/api/v1{path}"
        if params:
            clean = {k: v for k, v in params.items() if v not in (None, '')}
            if clean:
                url = f"{url}?{urlencode(clean)}"
        # Never retried: a comment sent twice is two comments.
        result = transport.send(method, url, json=body, headers=self._headers(),
                                timeout=timeout, max_retries=0)
        if result.ok:
            return Answer(True, data=result.json, status=result.status_code)
        status = result.status_code
        if status in (401, 403):
            return Answer(False, error='Seerr rejected the API key', status=status)
        if status == 404:
            return Answer(False, error=missing, status=status)
        said = ''
        payload = result.json
        if isinstance(payload, dict):
            said = str(payload.get('message') or payload.get('error') or '').strip()
        if status and said:
            return Answer(False, error=f"Seerr said: {said[:200]}", status=status)
        return Answer(False, error=result.error or 'Could not reach Seerr', status=status)

    def check(self) -> CheckResult:
        if not self._base():
            return CheckResult(False, 'No address set')
        status = self._call('GET', '/status')
        if not status.ok:
            return CheckResult(False, status.error)
        version = status.data.get('version') if isinstance(status.data, dict) else None
        if not version:
            return CheckResult(False, 'Something answered, but it was not Seerr. Check the address.')
        # /status answers without a key; /auth/me is what proves the key works.
        me = self._call('GET', '/auth/me')
        if not me.ok:
            return CheckResult(False, me.error)
        return CheckResult(True, f"Connected to Seerr {version}", detail={'version': version})

    # -- requests ------------------------------------------------------------

    def requests(self, *, filter: str = 'all', take: int = 20, skip: int = 0,
                 sort: str = 'added', media_type: str = 'all',
                 requested_by: Optional[int] = None) -> Answer:
        return self._call('GET', '/request', params={
            'filter': filter, 'take': take, 'skip': skip, 'sort': sort,
            'mediaType': media_type, 'requestedBy': requested_by,
        })

    def request_counts(self) -> Answer:
        return self._call('GET', '/request/count')

    def request_one(self, request_id: int) -> Answer:
        return self._call('GET', f'/request/{int(request_id)}',
                          missing='Seerr has no such request any more')

    def set_request_status(self, request_id: int, status: str) -> Answer:
        if status not in ('approve', 'decline'):
            return Answer(False, error=f"Unknown request action: {status}")
        return self._call('POST', f'/request/{int(request_id)}/{status}', body={},
                          timeout=WRITE_TIMEOUT, missing='Seerr has no such request any more')

    def retry_request(self, request_id: int) -> Answer:
        return self._call('POST', f'/request/{int(request_id)}/retry', body={},
                          timeout=WRITE_TIMEOUT, missing='Seerr has no such request any more')

    def update_request(self, request_id: int, body: Dict[str, Any]) -> Answer:
        answer = self._call('PUT', f'/request/{int(request_id)}', body=body,
                            timeout=WRITE_TIMEOUT, missing='Seerr has no such request any more')
        # Seerr answers 202 when every season asked for is already requested
        # elsewhere: nothing was changed.
        if answer.ok and answer.status == 202:
            said = answer.data.get('message') if isinstance(answer.data, dict) else ''
            return Answer(False, error=f"Seerr said: {said or 'nothing to change'}", status=202)
        return answer

    def services(self, kind: str) -> Answer:
        if kind not in ('sonarr', 'radarr'):
            return Answer(False, error=f"Unknown service: {kind}")
        return self._call('GET', f'/service/{kind}')

    def service_detail(self, kind: str, server_id: int) -> Answer:
        if kind not in ('sonarr', 'radarr'):
            return Answer(False, error=f"Unknown service: {kind}")
        return self._call('GET', f'/service/{kind}/{int(server_id)}', timeout=15.0,
                          missing=f"Seerr has no such {kind.capitalize()} server")

    # -- issues --------------------------------------------------------------

    def issues(self, *, filter: str = 'open', take: int = 20, skip: int = 0,
               sort: str = 'added', created_by: Optional[int] = None) -> Answer:
        return self._call('GET', '/issue', params={
            'filter': filter, 'take': take, 'skip': skip, 'sort': sort,
            'createdBy': created_by,
        })

    def issue_counts(self) -> Answer:
        return self._call('GET', '/issue/count')

    def issue_one(self, issue_id: int) -> Answer:
        return self._call('GET', f'/issue/{int(issue_id)}',
                          missing='Seerr has no such issue any more')

    def comment(self, issue_id: int, message: str) -> Answer:
        return self._call('POST', f'/issue/{int(issue_id)}/comment', body={'message': message},
                          timeout=WRITE_TIMEOUT, missing='Seerr has no such issue any more')

    def set_issue_status(self, issue_id: int, status: str) -> Answer:
        if status not in ('resolved', 'open'):
            return Answer(False, error=f"Unknown issue action: {status}")
        return self._call('POST', f'/issue/{int(issue_id)}/{status}', body={},
                          timeout=WRITE_TIMEOUT, missing='Seerr has no such issue any more')

    # -- titles and people ---------------------------------------------------

    def title(self, media_type: str, tmdb_id: int) -> Answer:
        """A film's or series' name, year, poster and seasons, from Seerr."""
        path = '/movie' if media_type == 'movie' else '/tv'
        return self._call('GET', f'{path}/{int(tmdb_id)}', params={'language': 'en'},
                          missing='Seerr does not know this title')

    def users(self, take: int = 200) -> Answer:
        return self._call('GET', '/user', params={'take': take, 'skip': 0, 'sort': 'displayname'})
