#!/usr/bin/env python3
"""
The safety net under the webhook: notice what was never synced, and sync it.

A webhook is the only thing that starts an automatic sync, which makes a lost
one a silent, total failure — nothing is scheduled, nothing is recorded, and the
episode sits on the media host until somebody happens to look. The causes are
ordinary: this application restarting, a network blip, the notification erroring
inside Sonarr. One deployment had it down for 26 minutes with auto-sync on, and
there is no way, from inside this application, to know what was sent in that
window.

The repair does not need to know *why* a notification was lost. It asks a
different question, which the service can always answer and which covers every
cause at once:

    what does the service hold files for, that this disk does not have?

That is the same comparison the library view makes, so the sweep reuses it
rather than growing a second opinion about what "synced" means. Two findings
matter, and they are the two an operator would name:

    missing      the service holds files and the folder is not here at all
    incomplete   the folder is here, and a season the service holds is not

Both end in the same action: fetch what is absent, through the ordinary transfer
path, with the ordinary safety checks.

What test mode does and does not change
---------------------------------------
Nothing here is gated on test mode. Reading a service, comparing with the disk
and deciding what to do are exactly the things worth exercising while
rehearsing, and a sweep that refused to run in test mode could never be trusted
in production. The transfer it starts inherits `--dry-run` from `TEST_MODE` like
every other transfer, so the decision is real and the write is not.
"""

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from activity_log import record, record_failure
from actor import AUTO_LIBRARY_SWEEP, acting_as
from models.media_item import SOURCE_RADARR, SOURCE_SONARR

#: Where the last completed sweep is remembered.
#:
#: Written straight to `app_settings` rather than through the settings service,
#: which correctly refuses keys the registry does not declare. This is internal
#: bookkeeping, not something an operator sets.
LAST_RUN_KEY = 'AUTOSYNC_SWEEP_LAST_RUN'

#: The most **transfers** one pass may start.
#:
#: Counted in transfers rather than in titles, which is not the same thing: one
#: incomplete series can be missing sixteen seasons, and sixteen is what would
#: actually enter a queue that runs three at a time. A first sweep of a library
#: that has never been reconciled finds a great many gaps at once, and a safety
#: net that starts all of them is a stampede. The rest are found again on the
#: next pass, and the log says how many were held back.
MAX_TRANSFERS_PER_RUN = 5

#: How long an unresolved finding stays quiet before it is mentioned again.
#:
#: A finding is announced when it first appears, and then at most once a day
#: while it persists. Announcing every run meant a Discord message every
#: fifteen minutes about the same two titles all night, which is the reliable
#: way to teach somebody to ignore the channel.
RENOTIFY_AFTER_HOURS = 24

#: Cleared for the record: the 170 transfers this produced overnight before the
#: memory existed were a development instance in test mode, so every one was an
#: `rsync --dry-run` and nothing moved. The cost was the noise, not the data.

#: How many times the sweep will try to close the same gap on its own.
#:
#: A gap that survives two attempts is not going to be fixed by a third: the
#: source is unreachable, the path is wrong, or something is refusing. It stays
#: on the list, stops being retried, and waits for a person — which is the
#: honest outcome and costs nothing while it waits.
MAX_SYNC_ATTEMPTS = 2

#: How long after start-up the first sweep runs. Long enough for the rest of the
#: application to finish coming up; short enough that a restart — the very event
#: most likely to have lost a notification — is checked promptly.
FIRST_RUN_DELAY_SECONDS = 45


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_stamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace('Z', '+00:00')
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _is_stale(stamp: Optional[str], hours: float) -> bool:
    """Whether a timestamp is absent, or older than `hours`."""
    moment = _parse_stamp(stamp)
    return moment is None or (_now() - moment) >= timedelta(hours=hours)


def _season_of(season_name: Optional[str]) -> Optional[int]:
    """The number out of "Season 07", or None for a whole-title transfer."""
    if not season_name:
        return None
    digits = ''.join(ch for ch in season_name if ch.isdigit())
    return int(digits) if digits else None


class SweepDecision:
    """One title the sweep looked at, and what it decided.

    Kept as an object rather than a tuple because every one of these is written
    to a log a person reads, and a field named `why` is the difference between
    an audit trail and a wall of identifiers.
    """

    def __init__(self, source: str, title: str, finding: str, why: str,
                 media_type: str = '', folder: str = '',
                 remote_folder: str = '', external_id: str = '',
                 seasons: Optional[List[int]] = None):
        self.source = source
        self.external_id = str(external_id or '')
        #: What the sweep already knows about each season of this gap, keyed by
        #: season number (None for a film). Filled in before anything is
        #: decided, so "is this new" is looked up rather than assumed.
        self.known: Dict[Optional[int], Dict[str, Any]] = {}
        self.actionable = False
        self.worth_announcing = False
        self.title = title
        self.finding = finding          # missing | incomplete
        self.why = why
        self.media_type = media_type
        #: What the folder is called here. May be empty for a title never synced.
        self.folder = folder
        #: What it is called on the machine the files come from. Taken from the
        #: service rather than derived, because the two names differ.
        self.remote_folder = remote_folder
        self.seasons = seasons or []
        self.action = 'reported'        # reported | queued | skipped | failed
        self.detail = ''
        self.transfer_ids: List[str] = []

    def as_dict(self) -> Dict[str, Any]:
        return {
            'source': self.source, 'title': self.title, 'finding': self.finding,
            'external_id': self.external_id,
            'why': self.why, 'media_type': self.media_type, 'folder': self.folder,
            'remote_folder': self.remote_folder,
            'worth_announcing': self.worth_announcing,
            'seasons': list(self.seasons), 'action': self.action,
            'detail': self.detail, 'transfer_ids': list(self.transfer_ids),
        }

    def _season_keys(self) -> List[Optional[int]]:
        return list(self.seasons) if self.seasons else [None]

    def classify(self, may_act: bool) -> None:
        """Decide what to do about this gap given what has happened before.

        Three questions, and they are separate on purpose:

          is it new?         nothing has ever been said about it
          is it overdue?     said once, and a day has gone by
          is it untried?     no sync has been attempted, or the attempts are
                             under the limit

        A gap can be worth mentioning and not worth retrying, or the reverse.
        Collapsing them is how a channel ends up with a message every fifteen
        minutes about a title somebody has already decided to leave alone.
        """
        from services.autosync_sweep import (MAX_SYNC_ATTEMPTS,
                                             RENOTIFY_AFTER_HOURS, _is_stale)

        new, overdue, untried = [], [], []
        for season in self._season_keys():
            known = self.known.get(season) or {}
            notified = known.get('notified_at')
            attempts = known.get('sync_attempts') or 0
            if not notified:
                new.append(season)
            elif _is_stale(notified, RENOTIFY_AFTER_HOURS):
                overdue.append(season)
            if attempts < MAX_SYNC_ATTEMPTS and not known.get('sync_started_at'):
                untried.append(season)

        self.worth_announcing = bool(new or overdue)

        if not may_act:
            self.action = 'reported'
            self.actionable = False
            return
        if not untried:
            self.action = 'skipped'
            self.detail = 'already attempted; waiting for a person'
            self.actionable = False
            return

        # Fetch only the seasons that have not been tried, not the whole gap.
        if self.seasons:
            self.seasons = [n for n in untried if n is not None]
        self.actionable = True

    def line(self) -> str:
        """One readable line for the log."""
        what = self.why
        if self.action == 'queued':
            what += f" → {len(self.transfer_ids)} sync(s) started"
            if self.detail:
                what += f", {self.detail}"
        elif self.action == 'skipped':
            what += f" → not started: {self.detail}"
        elif self.action == 'failed':
            what += f" → could not start: {self.detail}"
        else:
            what += " → reported only"
        return f"{self.title} — {what}"


class AutoSyncSweep:
    """Compares each service with the disk, and closes the gap it finds."""

    def __init__(self, db_manager, settings_service, media_index,
                 coordinator=None, config=None):
        self.db = db_manager
        self.settings = settings_service
        self.index = media_index
        self.coordinator = coordinator
        self.config = config
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last: Dict[str, Any] = {}

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Begin sweeping in the background.

        Safe to call when every connector has it switched off: the loop reads
        the settings each time round, so turning it on takes effect without a
        restart, and turning it off stops the work rather than the thread.
        """
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name='library-sweep')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(FIRST_RUN_DELAY_SECONDS)
        while not self._stop.is_set():
            wait_minutes = 15
            try:
                due = self._due_sources()
                if due:
                    self.run_once(sources=due)
                wait_minutes = self._shortest_interval()
            except Exception as exc:  # noqa: BLE001 - a sweep must never die
                print(f"⚠️  Library sweep failed: {exc}")
            self._stop.wait(max(60, wait_minutes * 60))

    def _configured(self, source: str):
        """The adapter for a source, when it is usable and sweeping is on."""
        adapter = self.index._adapter(source)
        if adapter is None or not getattr(adapter, 'sweep_enabled', None):
            return None
        return adapter if adapter.sweep_enabled() else None

    def _due_sources(self) -> List[str]:
        return [s for s in (SOURCE_SONARR, SOURCE_RADARR) if self._configured(s)]

    def _shortest_interval(self) -> int:
        intervals = [a.sweep_interval_minutes()
                     for a in (self._configured(s) for s in (SOURCE_SONARR, SOURCE_RADARR))
                     if a is not None]
        return min(intervals) if intervals else 15

    # -- one pass ------------------------------------------------------------

    def run_once(self, sources: Optional[List[str]] = None) -> Dict[str, Any]:
        """Look at each service, decide, act, and say what happened.

        Never raises. A sweep that could take the application down with it would
        be a worse problem than the one it exists to solve.
        """
        started = _now()
        with acting_as(AUTO_LIBRARY_SWEEP):
            runs = []
            for source in (sources or self._due_sources()):
                try:
                    runs.append(self._sweep_source(source))
                except Exception as exc:  # noqa: BLE001
                    print(f"⚠️  Library sweep of {source} failed: {exc}")
                    runs.append({'source': source, 'ok': False, 'error': str(exc),
                                 'decisions': []})

        summary = {
            'at': started.isoformat(),
            'sources': runs,
            'found': sum(len(r.get('decisions', [])) for r in runs),
            'started_syncs': sum(
                1 for r in runs for d in r.get('decisions', [])
                if d['action'] == 'queued'),
        }
        self._last = summary
        self._set_last_run(started)
        return summary

    # -- what has already been seen -----------------------------------------

    def _finding_keys(self, decision: 'SweepDecision') -> List[Optional[int]]:
        """The rows one decision occupies: one per season, or one for a film."""
        return list(decision.seasons) if decision.seasons else [None]

    def _open_findings(self, source: str) -> Dict[Tuple[str, Optional[int]], Dict[str, Any]]:
        try:
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    'SELECT * FROM sweep_finding WHERE source = ? AND resolved_at IS NULL',
                    (source,)).fetchall()
            return {(str(r['external_id']), r['season_number']): dict(r) for r in rows}
        except Exception:
            return {}

    def _remember(self, source: str, external_id: str, season: Optional[int],
                  decision: 'SweepDecision') -> Dict[str, Any]:
        """Record that this gap exists, and hand back what is known about it.

        A row that had been resolved and is seen again is reopened rather than
        left alone: the season came back, which is a new thing to say.
        """
        now = _now().isoformat()
        try:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    'SELECT * FROM sweep_finding WHERE source = ? AND external_id = ? '
                    'AND season_number IS ?',
                    (source, str(external_id), season)).fetchone()
                if row is None:
                    conn.execute(
                        'INSERT INTO sweep_finding (source, external_id, season_number, '
                        'title, finding, detail, first_seen_at, last_seen_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (source, str(external_id), season, decision.title,
                         decision.finding, decision.why, now, now))
                    conn.commit()
                    return {'notified_at': None, 'sync_started_at': None,
                            'sync_attempts': 0, 'reopened': False}

                existing = dict(row)
                reopened = existing.get('resolved_at') is not None
                conn.execute(
                    'UPDATE sweep_finding SET last_seen_at = ?, resolved_at = NULL, '
                    'title = ?, finding = ?, detail = ?, '
                    'notified_at = CASE WHEN ? THEN NULL ELSE notified_at END, '
                    'sync_attempts = CASE WHEN ? THEN 0 ELSE sync_attempts END, '
                    'sync_started_at = CASE WHEN ? THEN NULL ELSE sync_started_at END '
                    'WHERE id = ?',
                    (now, decision.title, decision.finding, decision.why,
                     reopened, reopened, reopened, existing['id']))
                conn.commit()
                if reopened:
                    return {'notified_at': None, 'sync_started_at': None,
                            'sync_attempts': 0, 'reopened': True}
                existing['reopened'] = False
                return existing
        except Exception:
            # Unable to remember: behave as though this is new. Repeating a
            # message is a smaller failure than losing one.
            return {'notified_at': None, 'sync_started_at': None,
                    'sync_attempts': 0, 'reopened': False}

    def _resolve_absent(self, source: str, still_open: set) -> int:
        """Close every finding this run did not see again."""
        try:
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    'SELECT id, external_id, season_number FROM sweep_finding '
                    'WHERE source = ? AND resolved_at IS NULL', (source,)).fetchall()
                closing = [r['id'] for r in rows
                           if (str(r['external_id']), r['season_number']) not in still_open]
                for finding_id in closing:
                    conn.execute('UPDATE sweep_finding SET resolved_at = ? WHERE id = ?',
                                 (_now().isoformat(), finding_id))
                conn.commit()
                return len(closing)
        except Exception:
            return 0

    def _stamp(self, source: str, external_id: str, season: Optional[int],
               **fields) -> None:
        if not fields:
            return
        try:
            with self.db.get_connection() as conn:
                sets = ', '.join(f'{k} = ?' for k in fields)
                conn.execute(
                    f'UPDATE sweep_finding SET {sets} WHERE source = ? '
                    f'AND external_id = ? AND season_number IS ?',
                    (*fields.values(), source, str(external_id), season))
                conn.commit()
        except Exception:
            pass

    def _sweep_source(self, source: str) -> Dict[str, Any]:
        adapter = self._configured(source)
        if adapter is None:
            return {'source': source, 'ok': False,
                    'error': 'not configured for sweeping', 'decisions': []}

        view = self.index.library_view(source, refresh=True)
        if not view.get('live'):
            print(f"🔍 Sweep · {source} · the service did not answer, nothing compared")
            record_failure('sweep.run', f"Could not reach {source.title()} to check for "
                                        f"missed imports",
                           target_type='connector', target_id=source)
            return {'source': source, 'ok': False,
                    'error': 'the service did not answer', 'decisions': []}

        counts = view.get('counts', {})
        with_files = sum(1 for i in view['items'] if i.get('service_has_files'))

        decisions = [d for d in (self._decide(source, item) for item in view['items'])
                     if d is not None]

        # Remember every gap before deciding anything, so "is this new" is a
        # fact rather than a guess, and close the ones that have gone away.
        seen = set()
        for decision in decisions:
            for season in self._finding_keys(decision):
                key = (str(decision.external_id), season)
                seen.add(key)
                known = self._remember(source, decision.external_id, season, decision)
                decision.known[season] = known
        resolved = self._resolve_absent(source, seen)

        may_act = adapter.sweep_auto_sync()
        started, held_back = 0, 0
        for decision in decisions:
            decision.classify(may_act)
            if not decision.actionable:
                continue
            budget = MAX_TRANSFERS_PER_RUN - started
            if budget <= 0:
                decision.action = 'skipped'
                decision.detail = 'held back until the next sweep'
                held_back += 1
                continue
            started += self._start_sync(decision, budget)
            if decision.action == 'skipped' and 'held back' in decision.detail:
                held_back += 1

        fresh = [d for d in decisions if d.worth_announcing]
        for decision in fresh:
            for season in self._finding_keys(decision):
                self._stamp(source, decision.external_id, season,
                            notified_at=_now().isoformat())

        self._log_run(source, view, with_files, counts, decisions, may_act,
                      started, held_back, resolved, fresh)
        return {'source': source, 'ok': True, 'total': view.get('total', 0),
                'with_files': with_files, 'counts': counts,
                'auto_sync': may_act, 'started': started,
                'decisions': [d.as_dict() for d in decisions]}

    # -- the judgement -------------------------------------------------------

    def _decide(self, source: str, item: Dict[str, Any]) -> Optional[SweepDecision]:
        """Whether one title needs fetching, and why.

        Only two states are acted on, and both come straight from the library
        view so this cannot drift from what the screen shows:

          `never`   the service holds files and nothing is on the disk
          `partial` the folder is here and a season with files there is not

        Everything else is either already correct, has nothing to fetch, or is a
        title the service no longer lists — which is not something to repair by
        downloading it again.
        """
        state = item.get('sync_state')
        if state not in ('never', 'partial'):
            return None
        if not item.get('service_has_files'):
            return None

        title = item.get('title') or 'Untitled'
        service_path = item.get('service_path') or ''
        remote_folder = os.path.basename(service_path.rstrip('/')) if service_path else ''

        # A title never synced has no local folder to learn a library from, so
        # the library is read off the service's own path instead — it sits under
        # whichever configured root it belongs to.
        media_type = item.get('media_type') or self._library_of(service_path) or (
            'movies' if source == SOURCE_RADARR else '')

        if state == 'never':
            return SweepDecision(
                source, title, 'missing',
                f"{item.get('service_episode_file_count') or 1} file(s) there, "
                f"nothing here",
                media_type=media_type,
                folder=item.get('local_folder') or remote_folder,
                remote_folder=remote_folder,
                external_id=item.get('external_id') or '')

        outstanding = [s['season_number'] for s in item.get('seasons') or []
                       if s.get('counts_towards_state') and not s.get('synced_here')]
        if not outstanding:
            return None
        return SweepDecision(
            source, title, 'incomplete',
            f"season(s) {', '.join(str(n) for n in outstanding)} there, not here",
            media_type=media_type,
            folder=item.get('local_folder') or remote_folder,
            remote_folder=remote_folder,
            external_id=item.get('external_id') or '',
            seasons=outstanding)

    # -- acting on it --------------------------------------------------------

    def _library_of(self, service_path: str) -> str:
        """Which configured library a path from the service belongs to.

        Also the boundary check. A path is only usable if it sits under a root
        this installation was configured with — an address the service supplied
        is not a reason to read somewhere nobody asked for.
        """
        if not service_path or self.config is None:
            return ''
        for media_type in ('movies', 'tvshows', 'anime'):
            remote_root, _ = self._roots(media_type)
            if remote_root and service_path.rstrip('/').startswith(remote_root + '/'):
                return media_type
        return ''

    def _roots(self, media_type: str) -> Tuple[str, str]:
        """The remote and local roots for a library, or ('', '')."""
        pairs = {
            'movies': ('MOVIE_PATH', 'MOVIE_DEST_PATH'),
            'tvshows': ('TVSHOW_PATH', 'TVSHOW_DEST_PATH'),
            'anime': ('ANIME_PATH', 'ANIME_DEST_PATH'),
        }
        keys = pairs.get(media_type)
        if not keys or self.config is None:
            return '', ''
        try:
            return ((self.config.get(keys[0]) or '').rstrip('/'),
                    (self.config.get(keys[1]) or '').rstrip('/'))
        except Exception:
            return '', ''

    def plan_paths(self, decision: SweepDecision) -> Tuple[List[Tuple[str, str, Optional[str]]], str]:
        """The transfers a decision amounts to: (source, dest, season label).

        One planner, used by the sweep and by the Sync button on the Library
        tab, so a click fetches exactly what an automatic run would have — the
        paths cannot drift apart depending on who asked.
        """
        remote_root, local_root = self._roots(decision.media_type)
        if not remote_root or not local_root:
            return [], f"no paths configured for {decision.media_type or 'this library'}"

        folder = decision.folder
        remote_folder = decision.remote_folder or folder
        if not folder or not remote_folder:
            return [], 'the folder name is not known on one side or the other'

        targets = []
        seasons = decision.seasons or [None]
        for number in seasons:
            season_name = f"Season {number:02d}" if number is not None else None
            source_path = f"{remote_root}/{remote_folder}"
            dest_path = f"{local_root}/{folder}"
            if season_name:
                source_path = f"{source_path}/{season_name}"
                dest_path = f"{dest_path}/{season_name}"
            targets.append((source_path, dest_path, season_name))
        return targets, ''

    def decide_for(self, source: str, external_id: str):
        """One title's decision, freshly derived — or (None, why not).

        Used by the Sync button. Derived on the server from a fresh look at the
        service rather than trusted from the page, because a browser tab can be
        hours old and "sync what is missing" has to mean missing *now*.
        """
        view = self.index.library_view(source, refresh=False)
        if not view.get('live'):
            return None, f"{source.title()} did not answer"
        item = next((i for i in view.get('items', [])
                     if str(i.get('external_id')) == str(external_id)), None)
        if item is None:
            return None, 'No such title is recorded'
        decision = self._decide(source, item)
        if decision is None:
            state = item.get('sync_state')
            if state == 'synced':
                return None, 'Everything the service holds is already here'
            if state == 'no_files':
                return None, 'The service holds no files for it yet'
            return None, f"Nothing to fetch (state: {state})"
        return decision, ''

    def sync_one(self, source: str, external_id: str) -> Dict[str, Any]:
        """Fetch one title's gap, on somebody's explicit say-so.

        No budget and no sweep actor: a person named this title, so every
        outstanding season is fetched and the activity entry carries whoever
        clicked rather than `library-sweep`. The caller's request context
        provides the actor, exactly as it does for any other manual sync.
        """
        decision, why_not = self.decide_for(source, external_id)
        if decision is None:
            return {'success': False, 'error': why_not}
        started = self._start_sync(decision, budget=len(decision.seasons) or 1,
                                   action='transfer.start',
                                   summary=(f"Started a sync of {decision.title} — "
                                            f"{decision.why}"))
        return {'success': started > 0,
                'error': decision.detail if started == 0 else '',
                'decision': decision.as_dict(),
                'transfers_started': started}

    def _start_sync(self, decision: SweepDecision, budget: int,
                    action: str = 'sweep.sync_started',
                    summary: str = '') -> int:
        """Fetch what is missing, through the ordinary transfer path.

        Deliberately the same entry point the media browser uses, with paths
        built from the roots already in the configuration. Nothing here invents
        a notification: a row in the Webhooks list is a record that a service
        told us something, and manufacturing one for a sync we decided on our
        own would make that list a liar.
        """
        if self.coordinator is None:
            decision.action = 'skipped'
            decision.detail = 'no transfer coordinator available'
            return 0

        targets, problem = self.plan_paths(decision)
        if problem:
            decision.action = 'skipped'
            decision.detail = problem
            return 0

        # A series missing sixteen seasons is sixteen transfers, not one. Take
        # only what the run has budget for and say so; the rest are found again
        # next time, which is the whole point of a sweep that repeats.
        deferred = max(0, len(targets) - budget)
        targets = targets[:budget]

        started_here = 0
        for source_path, dest_path, season_name in targets:
            transfer_id = f"sweep_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            try:
                started, state = self.coordinator.start_transfer(
                    transfer_id, source_path, dest_path,
                    'folder', decision.media_type, decision.folder, season_name)
            except Exception as exc:  # noqa: BLE001
                decision.action = 'failed'
                decision.detail = str(exc)
                record_failure('sweep.sync_failed',
                               f"Could not start a sync of {decision.title}",
                               target_type='media_item', target_label=decision.title,
                               detail={'error': str(exc), 'source': decision.source})
                return started_here

            if started:
                started_here += 1
                decision.transfer_ids.append(transfer_id)
                # Recorded per season, so a retry limit means "this season has
                # been tried twice", not "this title has".
                self._stamp(decision.source, decision.external_id,
                            _season_of(season_name),
                            sync_started_at=_now().isoformat(),
                            sync_attempts=((decision.known.get(_season_of(season_name))
                                            or {}).get('sync_attempts') or 0) + 1,
                            last_transfer_id=transfer_id)
            else:
                decision.detail = str(state)

        if started_here:
            decision.action = 'queued'
            if deferred:
                decision.detail = f"{deferred} more season(s) held back until the next sweep"
        else:
            decision.action = 'skipped'
        if started_here:
            record(action,
                   summary or (f"Synced {decision.title} after finding it "
                               f"{decision.finding} during a "
                               f"{decision.source.title()} check"),
                   target_type='media_item', target_label=decision.title,
                   detail={'why': decision.why, 'finding': decision.finding,
                           'seasons': decision.seasons,
                           'transfers': decision.transfer_ids,
                           'source': decision.source})
        return started_here

    # -- saying what happened ------------------------------------------------

    def _log_run(self, source: str, view: Dict[str, Any], with_files: int,
                 counts: Dict[str, int], decisions: List[SweepDecision],
                 may_act: bool, started: int, held_back: int,
                 resolved: int = 0,
                 fresh: Optional[List['SweepDecision']] = None) -> None:
        """One readable block per sweep.

        Written as a block rather than scattered lines because the question an
        operator asks is "what happened at 3am", and the answer has to be
        findable in one place and legible without knowing the code.
        """
        name = source.title()
        lines = [
            f"🔍 Library sweep · {name} · {_now().strftime('%Y-%m-%d %H:%M UTC')}",
            f"   asked {name}: {view.get('total', 0)} titles, {with_files} with files",
            f"   compared with the disk: "
            f"{counts.get('synced', 0)} already here, "
            f"{counts.get('partial', 0)} incomplete, "
            f"{counts.get('never', 0)} missing",
        ]
        if resolved:
            lines.append(f"   {resolved} earlier finding(s) no longer apply")
        if not decisions:
            lines.append("   nothing to fetch")
        else:
            lines.append(f"   decisions ({'syncing' if may_act else 'reporting only'}):")
            lines.extend(f"     • {d.line()}" for d in decisions)
            if held_back:
                lines.append(f"   {held_back} title(s) held back until the next sweep "
                             f"(at most {MAX_TRANSFERS_PER_RUN} transfers per run)")
            lines.append(f"   {started} sync(s) started")
            quiet = len(decisions) - len(fresh or [])
            if quiet:
                lines.append(f"   {quiet} already reported before — not announced again")
        print('\n'.join(lines))

        summary = (f"Checked {name}: {len(decisions)} title(s) missing or incomplete, "
                   f"{started} sync(s) started"
                   if decisions else
                   f"Checked {name}: everything it holds files for is already here")
        record('sweep.run', summary,
               target_type='connector', target_id=source,
               detail={'total': view.get('total', 0), 'with_files': with_files,
                       'counts': counts, 'auto_sync': may_act,
                       'started': started, 'held_back': held_back,
                       'findings': [d.as_dict() for d in decisions]})

        # Only what is new, or what has gone a day without being mentioned.
        # Everything else is on the Library tab where it has been all along.
        if fresh:
            self._announce(source, fresh, may_act, started)

    def _announce(self, source: str, decisions: List['SweepDecision'],
                  may_act: bool, started: int) -> None:
        """Say something once, not once per sweep."""
        from services.connectors.events import Event, Field
        body = '\n'.join(d.line() for d in decisions[:10])
        if len(decisions) > 10:
            body += f"\n...and {len(decisions) - 10} more"
        try:
            from services.connectors import notify
            if may_act:
                notify(Event(
                    key='autosync.blocked', severity='info',
                    title=f"{started} sync(s) started after checking {source.title()}",
                    fields=(Field('What was found', body, monospace=True),),
                ))
            else:
                # Report-only is the default, and its message has one job:
                # say that something is waiting on a person, and where the
                # one-click answer lives.
                notify(Event(
                    key='autosync.blocked', severity='warning',
                    title=f"{len(decisions)} title(s) out of sync — needs a manual look",
                    fields=(
                        Field('What was found', body, monospace=True),
                        Field('To sync one',
                              f"Integrations → {source.title()} → Library, "
                              f"press Sync on the title. Nothing is fetched "
                              f"until you do."),
                    ),
                ))
        except Exception:
            pass

    # -- state ---------------------------------------------------------------

    def last_run(self) -> Dict[str, Any]:
        return dict(self._last)

    def _set_last_run(self, moment: datetime) -> None:
        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    'INSERT INTO app_settings (key, value) VALUES (?, ?) '
                    'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                    (LAST_RUN_KEY, moment.isoformat()))
                conn.commit()
        except Exception:
            pass
