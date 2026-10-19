#!/usr/bin/env python3
"""
What the application announces, in terms no outside service owns.

A caller describes *what happened*. The adapter decides how its service shows
it. Before this existed, four call sites each built a Discord embed by hand —
so the colour for "this failed", the 1024-character field cap and the
timestamp format were written out four times and drifted independently.

Adding a new announcement is one row in CATALOGUE. Adding a service that
announces things touches none of this.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

# --- severity ---------------------------------------------------------------
#
# How bad it is, not how it looks. Adapters map these onto their own palette.

INFO = 'info'
SUCCESS = 'success'
WARNING = 'warning'
FAILURE = 'failure'

SEVERITIES = (INFO, SUCCESS, WARNING, FAILURE)

# --- accents ----------------------------------------------------------------
#
# An event that wants to be visually distinct from others of the same severity.
# A finished rename and a finished sync are both successes, and the operator
# asked for them to be told apart at a glance. Adapters may ignore these.

ACCENT_RENAME = 'rename'
ACCENT_BLOCKED = 'blocked'

ACCENTS = (ACCENT_RENAME, ACCENT_BLOCKED)

# --- headlines --------------------------------------------------------------
#
# The line above every message's title says what kind of message it is, in one
# scheme: "TOPIC - DETAIL", upper case. A sync names how it started and where
# from ("MANUAL SYNC - EXPLORE"); a failure says so in the topic ("AUTO SYNC
# FAILED - SONARR"). Before 2.3.2 each sender wrote its own: "Automated Sync",
# "Explore", "Manual Sync - FAILED ❌", "Manual Sync Alert ⚠️".

def headline(topic: str, detail: str = '') -> str:
    """A message's top line: "TOPIC - DETAIL", upper case."""
    topic = ' '.join((topic or '').split()).upper()
    detail = ' '.join((detail or '').split()).upper()
    return f"{topic} - {detail}" if detail else topic


#: How a sync started, for its headline.
SYNC_AUTO = 'AUTO'
SYNC_MANUAL = 'MANUAL'


def sync_headline(mode: str, source: str = '', failed: bool = False) -> str:
    """AUTO SYNC - SONARR, MANUAL SYNC - EXPLORE, AUTO SYNC FAILED - SCANNER."""
    return headline(f"{mode} SYNC{' FAILED' if failed else ''}", source)


# --- pings ------------------------------------------------------------------
#
# When a notification may ping someone (a Discord role, a user, @here). Who is
# pinged is the route's or the webhook's choice; this is only *when*.

PING_NEVER = 'never'
#: Only a message that needs a person: a warning or a failure. "Sync finished"
#: never pings under this rule; "Sync failed" always does.
PING_ATTENTION = 'attention'
PING_ALWAYS = 'always'

PING_CHOICES = (PING_NEVER, PING_ATTENTION, PING_ALWAYS)


def should_ping(when: str, severity: str) -> bool:
    """Whether a message of `severity` pings under the rule `when`."""
    if when == PING_ALWAYS:
        return True
    if when == PING_ATTENTION:
        return severity in (WARNING, FAILURE)
    return False


@dataclass(frozen=True)
class Field:
    """One labelled piece of an announcement."""

    name: str
    value: str
    inline: bool = False
    #: Rendered as a code block where the service supports one. Used for paths,
    #: statistics and error text — anything where alignment carries meaning.
    monospace: bool = False


@dataclass(frozen=True)
class Event:
    """One thing that happened, described so any service could render it."""

    key: str
    severity: str
    title: str
    #: A sentence under the title. Optional; most events do not need one.
    summary: str = ''
    fields: Tuple[Field, ...] = ()
    #: The small line above the title: what this is, as "TOPIC - DETAIL" in
    #: upper case — "AUTO SYNC - SONARR", "SAFETY CHECK - AUTO SYNC STOPPED".
    #: Build it with `headline()`; every message uses the one scheme.
    author: str = ''
    thumbnail_url: Optional[str] = None
    #: Where to send someone who clicks the announcement. Usually this app.
    link_url: Optional[str] = None
    accent: Optional[str] = None
    #: Free-form, never rendered — carried into the delivery log for tracing.
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # A typo'd key would route nowhere and be silently dropped, which is
        # the one failure mode this whole design exists to remove. Every caller
        # is in this repository, so failing loudly here is right: it surfaces
        # in tests rather than as a notification nobody notices is missing.
        if self.key not in VALID_KEYS:
            raise ValueError(
                f"Unknown event key {self.key!r}. "
                f"Add it to services/connectors/events.py CATALOGUE."
            )
        if self.severity not in SEVERITIES:
            raise ValueError(f"Unknown severity {self.severity!r}")
        if self.accent is not None and self.accent not in ACCENTS:
            raise ValueError(f"Unknown accent {self.accent!r}")


@dataclass(frozen=True)
class EventType:
    """One row of the catalogue — what the routing table renders."""

    key: str
    label: str
    #: Written for an operator deciding where this should go. Shown next to the
    #: destination dropdown, so it says when this fires, not what code runs.
    description: str
    default_severity: str = INFO
    #: When this pings until the operator says otherwise. Things that need a
    #: person ping on a warning or a failure; reports of something done never.
    default_ping: str = PING_ATTENTION

    def as_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'label': self.label,
            'description': self.description,
            'default_severity': self.default_severity,
            'default_ping': self.default_ping,
        }


CATALOGUE: Tuple[EventType, ...] = (
    EventType(
        'transfer.completed', 'Sync finished',
        'A transfer finished successfully, with what moved and how fast.',
        SUCCESS,
        default_ping=PING_NEVER,
    ),
    EventType(
        'transfer.failed', 'Sync failed',
        'A transfer stopped without finishing, with the errors rsync reported.',
        FAILURE,
    ),
    EventType(
        'rename.finished', 'Rename finished',
        'A rename run finished — whole, partial, or failed — with the new names.',
        SUCCESS,
        default_ping=PING_NEVER,
    ),
    EventType(
        'backup.retention_deleted', 'Old backups deleted',
        'The retention rule deleted stored versions. This cannot be undone, '
        'which is why it comes and finds you.',
        WARNING,
        default_ping=PING_NEVER,
    ),
    EventType(
        'autosync.blocked', 'Automatic sync refused',
        'An automatic sync looked unsafe and stopped, waiting for a person.',
        WARNING,
    ),
    EventType(
        'sync.held', 'Waiting for a manual sync',
        'Automatic sync is off for this library, so a batch is waiting for '
        'someone to press Sync. Sent once per batch.',
        WARNING,
    ),
    EventType(
        'sync.interrupted', 'Sync may have been skipped',
        'DragonCP restarted while a sync was waiting or copying. The alert in '
        'Notifications says what to check.',
        WARNING,
    ),
    EventType(
        'sync.stuck', 'Synced without a stuck download',
        'A season synced while something for it was stuck in Sonarr, or after '
        'waiting the full 30 minutes for a slow download.',
        WARNING,
        default_ping=PING_NEVER,
    ),
    EventType(
        'scanner.found', 'Auto-scanner found something',
        'The scheduled auto-scanner found something the service has and this disk '
        'does not, and started syncing it — or could not close a gap.',
        INFO,
    ),
    EventType(
        'integration.down', 'Sonarr or Radarr not answering',
        'A connected service stopped answering, so automatic sync fell back to '
        'the fixed timer. Sent once until it answers again.',
        WARNING,
    ),
    EventType(
        'scheduler.failing', 'Background job failing',
        'A scheduled background job failed several times in a row.',
        WARNING,
    ),
    EventType(
        'fast_route.failed', 'Fast transfers failed',
        'A copy failed on the fast transfer server and ran again over SSH. Sent '
        'once while the alert stays open.',
        WARNING,
    ),
)

#: What the routing table shows and what a caller may announce.
EVENT_KEYS: Tuple[str, ...] = tuple(e.key for e in CATALOGUE)
BY_KEY: Dict[str, EventType] = {e.key: e for e in CATALOGUE}

#: A test message. Deliberately outside the catalogue: it is not something the
#: application announces, it is never routed, and listing it would offer the
#: operator a destination choice for a message that ignores destinations by
#: design. It is still a real key so the delivery log does not claim a test
#: send was a finished transfer.
TEST_EVENT_KEY = 'connector.test'

#: Every key that may be constructed, routable or not.
VALID_KEYS: Tuple[str, ...] = EVENT_KEYS + (TEST_EVENT_KEY,)


def get(key: str) -> Optional[EventType]:
    return BY_KEY.get(key)


def catalogue() -> Tuple[Dict[str, Any], ...]:
    return tuple(e.as_dict() for e in CATALOGUE)
