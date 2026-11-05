#!/usr/bin/env python3
"""
Jellyfin.

Read only, for now: what is playing, and from 2.3.4 a record of every play.
Jellyfin keeps neither the play method nor the transcode reasons of a finished
play, so DragonCP watches the live sessions and writes its own history
(`services/jellyfin/`). Library and metadata editing come later; the plan is
`planning/jellyfin-seerr.md`.

Jellyfin runs on the media server itself, so every call here is a local one.
Nothing in this adapter reaches the remote server.
"""

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from services.connectors import transport
from services.connectors.base import CAP_QUERY, CheckResult, ConfigField, Connector
from services.connectors.registry import register

#: How long a session read may take. Jellyfin is on this machine and answers
#: in milliseconds; anything slower is Jellyfin in trouble, and the poller
#: should give up rather than queue behind it.
SESSIONS_TIMEOUT = 6.0


def _truthy(value: Any) -> bool:
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


@register
class JellyfinConnector(Connector):
    id = 'jellyfin'
    display_name = 'Jellyfin'
    description = 'Media server. Shows what is playing and keeps a record of every play.'
    capabilities = frozenset({CAP_QUERY})
    views = ('now_playing', 'plays')

    config_fields = (
        ConfigField(
            'base_url', 'Address',
            'Where Jellyfin is reachable from the DragonCP host.',
            kind='url', required=True, placeholder='http://localhost:8096',
            group='connection',
        ),
        ConfigField(
            'api_key', 'API key',
            'Dashboard → API Keys in Jellyfin itself. Jellyfin keys have '
            'administrator rights; DragonCP only reads with it.',
            kind='password', secret=True, required=True, group='connection',
        ),
        ConfigField(
            'record_plays', 'Record plays',
            'Keep every play in DragonCP: who watched what, on which device, '
            'and why Jellyfin transcoded it. Jellyfin keeps none of this itself. '
            'Checks every 10 seconds while something plays and every 30 when '
            'nothing does. Off by default.',
            kind='boolean', group='plays',
        ),
    )

    config_groups = (
        ('connection', 'Address and key', 'Where DragonCP reaches it.'),
        ('plays', 'Plays', 'What DragonCP keeps by itself.'),
    )

    settings_description = 'How DragonCP reaches it, and what it keeps.'

    # -- settings ------------------------------------------------------------

    def record_plays(self) -> bool:
        return _truthy(self.setting('record_plays'))

    # -- talking to Jellyfin -------------------------------------------------

    def _base(self) -> str:
        return self.setting('base_url').rstrip('/')

    def _headers(self) -> Dict[str, str]:
        # The scheme Jellyfin 10.11 documents. `X-Emby-Token` also works today,
        # but only because the server's "legacy authorization" setting is on.
        return {
            'Authorization': f'MediaBrowser Token="{self.secret("api_key")}"',
            'Accept': 'application/json',
        }

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None,
             timeout: float = 10.0) -> transport.TransportResult:
        url = f"{self._base()}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        return transport.send('GET', url, headers=self._headers(), timeout=timeout,
                              max_retries=0)

    def check(self) -> CheckResult:
        if not self._base():
            return CheckResult(False, 'No address set')

        result = self._get('/System/Info', timeout=8)
        if not result.ok:
            if result.status_code in (401, 403):
                return CheckResult(False, 'The API key was rejected')
            return CheckResult(False, result.error or 'Could not reach Jellyfin')

        payload = result.json or {}
        version = payload.get('Version') if isinstance(payload, dict) else None
        server = (payload.get('ServerName') if isinstance(payload, dict) else None) or 'Jellyfin'
        if version:
            return CheckResult(
                True, f"Connected to {server} {version}",
                detail={'version': version, 'server_name': server},
            )
        return CheckResult(
            False,
            'Something answered, but it was not Jellyfin. Check the address.',
        )

    def sessions(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        """Every session Jellyfin knows, raw: (ok, sessions, what went wrong).

        Includes the ones playing nothing; telling them apart is the caller's
        job, because "signed in, playing nothing" is still a device in use.
        """
        result = self._get('/Sessions', {'activeWithinSeconds': 960},
                           timeout=SESSIONS_TIMEOUT)
        if not result.ok:
            if result.status_code in (401, 403):
                return False, [], 'Jellyfin rejected the API key'
            return False, [], result.error or 'Could not reach Jellyfin'
        payload = result.json
        if not isinstance(payload, list):
            return False, [], 'Jellyfin answered, but not with a list of sessions'
        return True, [s for s in payload if isinstance(s, dict)], ''

    def episode_counts(self, series_id: str) -> Optional[Dict[int, int]]:
        """How many episodes of each season Jellyfin has files for, or None.

        `isMissing=false` leaves out the placeholder episodes Jellyfin lists
        for ones it knows of but has no file for.
        """
        result = self._get(f'/Shows/{quote(series_id)}/Episodes', {
            'isMissing': 'false', 'enableImages': 'false', 'enableUserData': 'false',
        }, timeout=SESSIONS_TIMEOUT)
        payload = result.json if result.ok else None
        items = payload.get('Items') if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return None
        counts: Dict[int, int] = {}
        for item in items:
            if not isinstance(item, dict) or item.get('LocationType') == 'Virtual':
                continue
            season = item.get('ParentIndexNumber')
            if isinstance(season, int):
                counts[season] = counts.get(season, 0) + 1
        return counts

    def image(self, item_id: str, kind: str = 'Primary',
              width: int = 240) -> transport.BytesResult:
        """One of an item's images, scaled down by Jellyfin before it is sent."""
        query = urlencode({'fillWidth': width, 'quality': 85})
        url = f"{self._base()}/Items/{quote(item_id)}/Images/{quote(kind)}?{query}"
        return transport.fetch_bytes(url, headers=self._headers(), timeout=8.0,
                                     max_bytes=4 * 1024 * 1024)
