#!/usr/bin/env python3
"""
Jellyfin.

Phase 1: stores an address and an API key, and proves they work.

What this is eventually *for* is deliberately undecided. "Refresh the library
after a sync lands" is the obvious candidate and would make it a command
connector rather than a query one, but nobody has asked for it, and a connector
built on a guess is a connector built wrong.
"""

from services.connectors import transport
from services.connectors.base import CAP_QUERY, CheckResult, ConfigField, Connector
from services.connectors.registry import register


@register
class JellyfinConnector(Connector):
    id = 'jellyfin'
    display_name = 'Jellyfin'
    description = 'Media server. Connected but unused — nothing reads it yet.'
    capabilities = frozenset({CAP_QUERY})

    config_fields = (
        ConfigField(
            'base_url', 'Address',
            'Where Jellyfin is reachable from the DragonCP host.',
            kind='url', required=True, placeholder='http://localhost:8096',
        ),
        ConfigField(
            'api_key', 'API key',
            'Dashboard → Advanced → API Keys in Jellyfin itself.',
            kind='password', secret=True, required=True,
        ),
    )

    def check(self) -> CheckResult:
        base = self.setting('base_url').rstrip('/')
        if not base:
            return CheckResult(False, 'No address set')

        # `X-Emby-Token` is the header Jellyfin 10.x accepts for an API key.
        # Verify against the installed version before relying on it for
        # anything beyond this check.
        result = transport.send(
            'GET', f"{base}/System/Info",
            headers={'X-Emby-Token': self.secret('api_key')},
            timeout=8,
        )

        if not result.ok:
            if result.status_code in (401, 403):
                return CheckResult(False, 'The API key was rejected')
            return CheckResult(False, result.error or 'Could not reach Jellyfin')

        payload = result.json or {}
        version = payload.get('Version')
        server = payload.get('ServerName') or 'Jellyfin'
        if version:
            return CheckResult(
                True, f"Connected to {server} {version}",
                detail={'version': version, 'server_name': server},
            )
        return CheckResult(
            False,
            'Something answered, but it was not Jellyfin. Check the address.',
        )
