#!/usr/bin/env python3
"""
The one place this application makes an outbound HTTP call.

Before this, six calls across five files each chose their own timeout, their
own retry policy (none), and their own way of reporting a failure — including
printing the response body next to the URL, which for a Discord webhook means
printing the credential.

Two rules hold here and nowhere else needs to know them:

  Nothing raises.  Every path — timeout, DNS failure, refused connection,
                   malformed response — returns a TransportResult. Callers are
                   background threads that must survive a service being down.

  Nothing leaks.   A URL is redacted before it reaches any string a caller
                   might log, store or render. A Discord webhook URL *is* the
                   credential; there is no separate token to hide.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

#: Statuses worth trying again. 429 is rate limiting; the 5xx set is the
#: service having a bad moment. A 4xx that is not 429 means the request was
#: wrong, and repeating it will not make it right.
DEFAULT_RETRY_ON: Tuple[int, ...] = (429, 500, 502, 503, 504)

#: One retry. Enough to survive a blip, few enough that a dead service does not
#: hold a dispatch worker for a minute.
DEFAULT_MAX_RETRIES = 1

DEFAULT_TIMEOUT = 10.0

#: However long the service asks us to wait, we wait at most this. Discord can
#: return a Retry-After of several minutes on a hard rate limit, and blocking a
#: shared worker that long would stall every other notification behind it.
MAX_RETRY_AFTER = 10.0

#: Response bodies are for diagnosis, not storage — `body` is capped so a
#: stored error or a log line stays a sentence rather than a document.
#:
#: The cap applies to the text kept for a human. It must NOT apply to the text
#: handed to a parser: a status document from Sonarr is 836 bytes, so capping
#: before parsing truncated it mid-object and every read came back as "not this
#: service". Parsing happens on the full response, in `_parse_json` below.
MAX_BODY_CHARS = 500


@dataclass(frozen=True)
class TransportResult:
    ok: bool
    status_code: Optional[int] = None
    body: str = ''
    #: Operator-facing, and already redacted.
    error: Optional[str] = None
    duration_ms: int = 0
    attempts: int = 1
    retry_after: Optional[float] = None
    #: The response parsed as JSON, from the *full* text rather than from the
    #: truncated `body`. None when there was nothing to parse or it was not
    #: JSON — the two cases callers already have to handle identically.
    parsed: Any = None

    @property
    def json(self) -> Any:
        """The response parsed as JSON, or None. Never raises.

        Prefers what was parsed from the whole response. Falls back to `body`
        so a result built by hand — in a test, or by a caller that only had the
        text — still behaves.
        """
        if self.parsed is not None:
            return self.parsed
        return _parse_json(self.body)


def _parse_json(text: str) -> Any:
    """`text` as JSON, or None. Never raises, and never truncates first."""
    if not text:
        return None
    try:
        import json as _json
        return _json.loads(text)
    except Exception:  # noqa: BLE001 - a non-JSON body is an ordinary outcome
        return None


def redact_url(url: str) -> str:
    """A URL as it may appear in a log, a stored error, or the UI.

    Scheme, host and the first two path segments survive — enough to say
    *which* service and *which* endpoint failed. Everything after that, and the
    whole query string, is replaced.

    `https://discord.com/api/webhooks/123456/lB9-secret` becomes
    `https://discord.com/api/webhooks/…`, which names the service without
    handing over the credential.
    """
    if not url:
        return ''
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return '<invalid url>'
        segments = [s for s in (parsed.path or '').split('/') if s]
        kept = '/'.join(segments[:2])
        base = f"{parsed.scheme}://{parsed.netloc}"
        if not segments:
            return base
        suffix = '/…' if len(segments) > 2 or parsed.query else ''
        return f"{base}/{kept}{suffix}"
    except Exception:
        return '<invalid url>'


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Seconds from a Retry-After header, when it is the seconds form.

    The HTTP-date form is legal and unused by every service here; treating it
    as absent falls back to sending again immediately, which the retry cap
    already bounds.
    """
    if not value:
        return None
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


def send(method: str, url: str, *,
         json: Optional[Any] = None,
         data: Optional[Any] = None,
         headers: Optional[Dict[str, str]] = None,
         timeout: float = DEFAULT_TIMEOUT,
         retry_on: Tuple[int, ...] = DEFAULT_RETRY_ON,
         max_retries: int = DEFAULT_MAX_RETRIES,
         expect: Tuple[int, ...] = ()) -> TransportResult:
    """Make one outbound request and say what happened.

    Args:
        expect: Statuses that count as success. Empty means "any 2xx", which is
            what most services mean. Discord's webhook endpoint answers 204 and
            nothing else, so its adapter passes it explicitly.
    """
    safe_url = redact_url(url)
    started = time.monotonic()
    total_attempts = max(1, max_retries + 1)
    last = TransportResult(
        ok=False, error=f"Request to {safe_url} was never attempted",
    )

    for attempts in range(1, total_attempts + 1):
        retryable = True
        try:
            response = requests.request(
                method.upper(), url,
                json=json, data=data, headers=headers, timeout=timeout,
            )
        except requests.Timeout:
            last = TransportResult(
                ok=False,
                error=f"{safe_url} did not answer within {timeout:.0f}s",
                duration_ms=_elapsed_ms(started), attempts=attempts,
            )
        except requests.ConnectionError:
            last = TransportResult(
                ok=False,
                error=f"Could not reach {safe_url}",
                duration_ms=_elapsed_ms(started), attempts=attempts,
            )
        except Exception as exc:  # noqa: BLE001 - the whole point is not raising
            # Deliberately does not interpolate the exception's own repr, which
            # for a requests exception embeds the full URL.
            last = TransportResult(
                ok=False,
                error=f"Request to {safe_url} failed: {type(exc).__name__}",
                duration_ms=_elapsed_ms(started), attempts=attempts,
            )
        else:
            status = response.status_code
            text = response.text or ''
            # Parsed before the cap, kept after it. An error document is worth
            # parsing too — a service that explains itself in JSON should not
            # be readable only when its answer is short.
            parsed = _parse_json(text)
            body = text[:MAX_BODY_CHARS]
            ok = (status in expect) if expect else (200 <= status < 300)
            retry_after = _parse_retry_after(response.headers.get('Retry-After'))

            if ok:
                return TransportResult(
                    ok=True, status_code=status, body=body, parsed=parsed,
                    duration_ms=_elapsed_ms(started), attempts=attempts,
                )

            last = TransportResult(
                ok=False, status_code=status, body=body, parsed=parsed,
                error=_describe_status(safe_url, status, retry_after),
                duration_ms=_elapsed_ms(started), attempts=attempts,
                retry_after=retry_after,
            )
            retryable = status in retry_on

        if not retryable or attempts == total_attempts:
            break

        # Only the status path sets a wait; a refused connection is retried
        # straight away, since there is nobody to have asked us to wait.
        if last.retry_after:
            time.sleep(min(last.retry_after, MAX_RETRY_AFTER))

    logger.warning("Outbound %s %s failed: %s", method.upper(), safe_url, last.error)
    return last


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _describe_status(safe_url: str, status: int, retry_after: Optional[float]) -> str:
    """A failed status in words an operator can act on."""
    if status == 429:
        if retry_after:
            return f"{safe_url} is rate-limiting; try again in {retry_after:.0f}s"
        return f"{safe_url} is rate-limiting"
    if status in (401, 403):
        return f"{safe_url} rejected the credentials ({status})"
    if status == 404:
        return f"{safe_url} does not exist (404) — it may have been deleted"
    if 500 <= status < 600:
        return f"{safe_url} returned a server error ({status})"
    return f"{safe_url} returned {status}"
