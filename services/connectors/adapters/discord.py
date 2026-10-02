#!/usr/bin/env python3
"""
Discord.

Everything Discord-shaped lives here and nowhere else: the colours, the field
length cap, the timestamp format, the URL check, and the fact that a webhook
answers 204 rather than 200. Four call sites used to each hold their own copy
of all of that, and they had already drifted — two fence styles for code
blocks, two timestamp formats, four different truncation limits.

Callers describe what happened. This decides how Discord shows it.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from services.connectors import transport
from services.connectors.base import (
    CheckResult,
    ConfigField,
    DeliveryResult,
    NotifyingConnector,
    Target,
)
from services.connectors.events import (
    ACCENT_BLOCKED,
    ACCENT_RENAME,
    FAILURE,
    INFO,
    SUCCESS,
    WARNING,
    Event,
)
from services.connectors.registry import register

# --- the palette ------------------------------------------------------------
#
# The exact integers the four hand-written senders used, so nothing an operator
# recognises changes colour.

_SEVERITY_COLOURS = {
    INFO: 11164867,       # purple, the app's own
    SUCCESS: 11164867,    # purple
    WARNING: 15105570,    # amber
    FAILURE: 15158332,    # red
}

#: An event that wants to be distinct from others of its severity. A finished
#: rename and a finished sync are both successes and were deliberately given
#: different colours so they can be told apart at a glance.
_ACCENT_COLOURS = {
    ACCENT_RENAME: 1752220,    # teal
    ACCENT_BLOCKED: 15844367,  # gold
}

# --- Discord's own limits ---------------------------------------------------
#
# Exceeding any of these means Discord rejects the *whole message*, so an
# unusually long title or path costs the operator the entire notification
# rather than one field. None of these were enforced before.

MAX_FIELD_VALUE = 1024
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_AUTHOR_NAME = 256
MAX_FOOTER = 2048
MAX_FIELDS = 25

#: ```\n … \n``` — the fence form that can never be mistaken for a language
#: hint, unlike ```text on one line.
_FENCE_OVERHEAD = 8

#: A webhook posted to by this server has exactly one legitimate shape. Anything
#: else is either a mistake or an attempt to point the server somewhere else.
_WEBHOOK_HOSTS = frozenset({
    'discord.com', 'discordapp.com',
    'ptb.discord.com', 'canary.discord.com',
    'ptb.discordapp.com', 'canary.discordapp.com',
})

#: The app's own URL, used as the embed link. Deliberately permissive: this is
#: a private deployment and the value is routinely a Tailscale IP or localhost.
_APP_URL_PATTERN = re.compile(
    r'^https?://(?:(?:[a-zA-Z0-9-]+\.)*[a-zA-Z0-9-]+|localhost|'
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d{1,5})?(?:/.*)?$'
)


def is_valid_app_url(url: str) -> bool:
    """Whether a URL is one Discord will accept as an embed link."""
    try:
        return bool(_APP_URL_PATTERN.match(url or ''))
    except Exception:
        return False


@register
class DiscordConnector(NotifyingConnector):
    id = 'discord'
    display_name = 'Discord'
    description = 'Post announcements to Discord channels through webhooks.'
    target_noun = 'webhook'

    # Not "Connection". Nothing here reaches Discord — a webhook URL carries
    # its own credential, so connecting happens on the webhooks list. These
    # three decide how a message *looks* once it arrives, and they are set
    # once and then left alone.
    settings_label = 'Appearance'
    settings_description = 'How a message looks when it arrives in Discord.'
    supports_check = False

    config_fields = (
        ConfigField(
            'app_url', 'App URL',
            'Where a message links back to. Usually this app’s own address.',
            kind='url', placeholder='http://localhost:5000',
        ),
        ConfigField(
            'icon_url', 'Notification icon',
            'The small image shown beside the message author.',
            kind='url',
        ),
        ConfigField(
            'manual_sync_thumbnail_url', 'Default thumbnail',
            'Used for transfers started by hand, which have no poster.',
            kind='url',
        ),
    )

    # ---- configuration -----------------------------------------------------

    def is_configured(self) -> bool:
        """Discord needs no connector-level credential — a webhook carries it.

        Which means "configured" is "has somewhere to send", and that question
        is answered by the destinations, not by this form. The service checks
        for a usable destination separately, so this is always true.
        """
        return True

    def check(self) -> CheckResult:
        """There is no Discord endpoint to ping that is not a webhook.

        Reported as a failure rather than a success: this used to answer `ok`
        with a note telling the reader to test a webhook instead, which left a
        green "last checked" badge on something nothing had checked. The UI
        does not offer the button at all — `supports_check` is False — so this
        is only reachable by calling the API directly.
        """
        return CheckResult(
            False,
            'Discord has nothing to test at this level. Use Test beside a '
            'webhook to check that webhook.',
        )

    def validate_target(self, credential: str) -> Optional[str]:
        """Reject anything that is not a Discord webhook URL.

        The server posts to whatever is stored here, so this is the one place
        that decides where it may be pointed.
        """
        url = (credential or '').strip()
        if not url:
            return 'Paste the webhook URL from Discord'
        try:
            parsed = urlparse(url)
        except Exception:
            return 'That does not look like a URL'
        if parsed.scheme != 'https':
            return 'A Discord webhook URL starts with https://'
        if (parsed.hostname or '').lower() not in _WEBHOOK_HOSTS:
            return 'That is not a Discord address. Copy the URL from the channel’s Integrations settings.'
        if '/api/webhooks/' not in (parsed.path or ''):
            return 'That is a Discord link, but not a webhook URL'
        return None

    # ---- rendering ---------------------------------------------------------

    def render(self, event: Event) -> Dict[str, Any]:
        """One event as a Discord message payload."""
        embed: Dict[str, Any] = {
            'title': _clip(event.title, MAX_TITLE),
            'color': self._colour(event),
            # The exact shape the hand-written senders produced, minus the
            # deprecated `utcnow()` they used to get there.
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        }

        if event.summary:
            embed['description'] = _clip(event.summary, MAX_DESCRIPTION)

        fields = self._render_fields(event)
        if fields:
            embed['fields'] = fields

        if event.author:
            author: Dict[str, Any] = {'name': _clip(event.author, MAX_AUTHOR_NAME)}
            icon_url = self.setting('icon_url')
            if icon_url:
                author['icon_url'] = icon_url
            embed['author'] = author

        if event.footer:
            embed['footer'] = {'text': _clip(event.footer, MAX_FOOTER)}

        thumbnail = event.thumbnail_url or self.setting('manual_sync_thumbnail_url')
        if thumbnail:
            embed['thumbnail'] = {'url': thumbnail}

        link = event.link_url or self.setting('app_url')
        # Discord validates embed URLs strictly and rejects the whole message
        # for a malformed one, so a bad app URL must cost the link and nothing
        # else.
        if link and is_valid_app_url(link):
            embed['url'] = link

        return {'embeds': [embed]}

    def _render_fields(self, event: Event) -> List[Dict[str, Any]]:
        fields = []
        for item in event.fields[:MAX_FIELDS]:
            value = item.value if item.value not in (None, '') else 'N/A'
            if item.monospace:
                value = _fenced(str(value))
            else:
                value = _clip(str(value), MAX_FIELD_VALUE)
            fields.append({
                'name': _clip(item.name, MAX_TITLE),
                'value': value,
                'inline': bool(item.inline),
            })
        return fields

    def _colour(self, event: Event) -> int:
        if event.accent and event.accent in _ACCENT_COLOURS:
            return _ACCENT_COLOURS[event.accent]
        return _SEVERITY_COLOURS.get(event.severity, _SEVERITY_COLOURS[INFO])

    # ---- delivery ----------------------------------------------------------

    def deliver(self, event: Event, target: Target, credential: str) -> DeliveryResult:
        payload = self.render(event)
        result = transport.send(
            'POST', credential,
            json=payload,
            headers={'Content-Type': 'application/json'},
            # A Discord webhook answers 204 and nothing else on success. A 200
            # would mean the URL is not the endpoint it claims to be.
            expect=(204,),
        )
        return DeliveryResult(
            ok=result.ok,
            status_code=result.status_code,
            error=None if result.ok else result.error,
            duration_ms=result.duration_ms,
            retry_after=result.retry_after,
        )


def _clip(text: str, limit: int) -> str:
    text = '' if text is None else str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + '…'


def _fenced(text: str) -> str:
    """Text in a code block, clipped so the fenced result still fits.

    The fences are part of the budget. Truncating to the limit and *then*
    wrapping is how a message gets rejected for being 1030 characters long.
    """
    budget = MAX_FIELD_VALUE - _FENCE_OVERHEAD
    body = text if len(text) <= budget else text[: budget - 1] + '…'
    return f"```\n{body}\n```"
