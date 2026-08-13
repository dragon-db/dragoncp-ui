#!/usr/bin/env python3
"""
DragonCP Actor Resolution
Who is responsible for an action — a signed-in administrator, or automation.

Most of what this application does is not started by a person. Download-manager
webhooks queue syncs, the scheduler batches seasons, retention prunes old
restore points, and simulation runs create their own traffic. If those actions
are recorded with an empty owner they read as anonymous, and anyone looking at
the history later assumes a human was behind them.

So every action has an actor, and an actor is always one of three kinds:

    admin      a person who signed in, carrying their stable account id
    automated  a named background process, shown as "AUTO / <name>"
    system     the application itself, outside any request or job

The actor is resolved for every request and every declared background job, and
written onto the activity trail by `activity_log.record()`.
"""

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Optional


#: Declared actor for the current thread, for work that runs outside a request:
#: the auto-sync scheduler, retention, and anything else on a background thread.
#: A request sets `g.current_actor` instead and takes precedence over this.
_local = threading.local()


ACTOR_ADMIN = 'admin'
ACTOR_AUTOMATED = 'automated'
ACTOR_SYSTEM = 'system'

#: Rendered in front of every automated actor's name. Human usernames are
#: forbidden from starting with this (see models/admin_account.py), so the two
#: can never be confused in a log line or an activity entry.
AUTOMATED_LABEL_PREFIX = 'AUTO'


@dataclass(frozen=True)
class Actor:
    """One responsible party for one action."""

    kind: str
    name: str
    account_id: Optional[int] = None

    @property
    def is_human(self) -> bool:
        return self.kind == ACTOR_ADMIN

    @property
    def label(self) -> str:
        """
        How this actor should be shown to a person.

        Administrators appear under their own name. Everything else is badged,
        so a reader never has to wonder whether 'retention' was a colleague.
        """
        if self.kind == ACTOR_ADMIN:
            return self.name
        if self.kind == ACTOR_AUTOMATED:
            return f'{AUTOMATED_LABEL_PREFIX} / {self.name}'
        return f'{AUTOMATED_LABEL_PREFIX} / {ACTOR_SYSTEM}'

    def to_dict(self) -> Dict:
        """The shape the activity trail stores."""
        return {
            'actor_kind': self.kind,
            'actor_name': self.name,
            'actor_account_id': self.account_id,
            'actor_label': self.label,
        }


def admin_actor(username: str, account_id: Optional[int] = None) -> Actor:
    """An actor for a signed-in person."""
    return Actor(kind=ACTOR_ADMIN, name=username, account_id=account_id)


def automated_actor(name: str) -> Actor:
    """
    An actor for a named background process.

    Prefer one of the constants below so the names stay a closed set and the
    activity trail can be filtered by them.
    """
    return Actor(kind=ACTOR_AUTOMATED, name=name)


# ----- the named automation ------------------------------------------------
# Every background entry point in the application should identify as one of
# these rather than inventing a name at the call site.

AUTO_SYNC_SCHEDULER = automated_actor('auto-sync')
AUTO_WEBHOOK_MOVIES = automated_actor('webhook-movies')
AUTO_WEBHOOK_SERIES = automated_actor('webhook-series')
AUTO_WEBHOOK_ANIME = automated_actor('webhook-anime')
AUTO_WEBHOOK_RENAME = automated_actor('webhook-rename')
AUTO_RETENTION = automated_actor('retention')
#: Files kept out of the way of a sync. Named separately from the person who
#: started the sync, and from retention, so the History tab can tell "this
#: version was created for you" apart from "this version was taken away".
AUTO_BACKUP = automated_actor('backup')

# There is deliberately no actor for simulation or for queue promotion.
#
# A simulation is started by a person clicking a button, so the person is the
# honest answer; the rows it creates are already flagged as simulated for
# telling them apart. Queue promotion does not begin anything — the run it
# releases already carries whoever asked for it, and re-attributing it to the
# queue would lose that.
#
# A name in this set that nothing can produce is worse than no name: it offers a
# filter that always comes back empty and implies a path that was wired.

SYSTEM_ACTOR = Actor(kind=ACTOR_SYSTEM, name=ACTOR_SYSTEM)

#: Lookup for turning a stored name back into an actor.
NAMED_AUTOMATION = {
    actor.name: actor
    for actor in (
        AUTO_SYNC_SCHEDULER,
        AUTO_WEBHOOK_MOVIES,
        AUTO_WEBHOOK_SERIES,
        AUTO_WEBHOOK_ANIME,
        AUTO_WEBHOOK_RENAME,
        AUTO_RETENTION,
    )
}


def webhook_actor(media_type: str) -> Actor:
    """The automated actor for a download-manager webhook of the given kind."""
    return {
        'movies': AUTO_WEBHOOK_MOVIES,
        'series': AUTO_WEBHOOK_SERIES,
        'anime': AUTO_WEBHOOK_ANIME,
        'rename': AUTO_WEBHOOK_RENAME,
    }.get(media_type, automated_actor(f'webhook-{media_type}'))


@contextmanager
def acting_as(actor: Actor):
    """
    Declare who is responsible for work on this thread.

    Background work has no request to read an identity from, so the entry point
    says who it is once and everything underneath is attributed to it without
    having to pass an actor down through every call:

        with acting_as(AUTO_SYNC_SCHEDULER):
            coordinator.start_transfer(...)

    Nests correctly, and restores the previous actor on the way out.
    """
    previous = getattr(_local, 'actor', None)
    _local.actor = actor
    try:
        yield actor
    finally:
        _local.actor = previous


def declared_actor() -> Optional[Actor]:
    """Whatever `acting_as` last declared on this thread, if anything."""
    return getattr(_local, 'actor', None)


def current_actor() -> Actor:
    """
    The actor for whatever is happening right now.

    Resolved in order of how specific the answer is:

      1. the signed-in administrator on this request, put on `g` by require_auth
      2. an actor declared for this thread with `acting_as`
      3. the application itself

    Falling through to `system` is not an error, but on any path that changes
    something it means nobody said who was responsible — and the whole point of
    the activity trail is that this should not happen silently.
    """
    try:
        from flask import g, has_request_context

        if has_request_context():
            actor = getattr(g, 'current_actor', None)
            if isinstance(actor, Actor):
                return actor

            username = getattr(g, 'current_user', None)
            if username:
                return admin_actor(username, getattr(g, 'current_account_id', None))
    except Exception:
        # Actor resolution must never be the reason an action fails.
        pass

    declared = declared_actor()
    if isinstance(declared, Actor):
        return declared

    return SYSTEM_ACTOR
