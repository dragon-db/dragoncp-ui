#!/usr/bin/env python3
"""
The pipeline, written down once.

Every sync DragonCP performs passes the same nine stages. A kind of sync may
run a stage differently or skip it, and when it skips one it says why in a
sentence a person can read — that sentence is what the interface shows under
the stage, so it is written here, next to the decision, rather than invented
by whoever renders it.

This module is data. The engine reads it to decide what to do; the API serves
it so the interface draws the same pipeline the engine runs.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

RECEIVE = 'receive'
IDENTIFY = 'identify'
BATCH = 'batch'
READY = 'ready'
SAFETY = 'safety'
QUEUE = 'queue'
TRANSFER = 'transfer'
FINISH = 'finish'
TELL = 'tell'


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    #: The short line shown under the label.
    tagline: str
    #: What the stage does, for anyone wondering.
    description: str

    def as_dict(self) -> Dict[str, str]:
        return {'id': self.id, 'label': self.label, 'tagline': self.tagline,
                'description': self.description}


STAGES: Tuple[Stage, ...] = (
    Stage(RECEIVE, 'Receive', 'Who or what asked',
          'Records the request and who or what made it — a webhook, the '
          'auto-scanner or a person — before anything else happens.'),
    Stage(IDENTIFY, 'Identify', 'What, and which folders',
          'Works out what is being synced (a season, a whole series or a movie) '
          'and the source and destination folders. A path outside the library '
          'folders is refused.'),
    Stage(BATCH, 'Batch', 'Group requests for one folder',
          'Looks for a batch already open for the same folder. Waiting or queued: '
          'join it. Copying: join the one follow-up behind it. None: open one.'),
    Stage(READY, 'Ready check', 'Still downloading?',
          'Asks Sonarr whether anything for the season is still downloading, '
          'and waits as long as Sonarr says it needs — at most 30 minutes. When '
          'Sonarr cannot answer, the fallback wait decides instead.'),
    Stage(SAFETY, 'Safety check', 'Dry run first',
          'A dry run before anything is written. The sync stops when it would '
          'delete more files than it brings in, or when the media server holds '
          'fewer files than this disk.'),
    Stage(QUEUE, 'Queue', 'Wait for a turn',
          'Waits while anything writes to the same season or the series it '
          'belongs to, and for a free slot — three transfers at once.'),
    Stage(TRANSFER, 'Transfer', 'Copy the files',
          'rsync copies the folder. Files it replaces go to the backup area '
          'first.'),
    Stage(FINISH, 'Finish', 'Close out its webhooks',
          'Marks every webhook in the batch synced, or failed with the reason, '
          'and releases a follow-up waiting behind it.'),
    Stage(TELL, 'Tell', 'Discord + Notifications',
          'Announces the outcome on Discord. Anything that needs a person also '
          'opens an alert in the Notifications tab.'),
)

STAGE_IDS: Tuple[str, ...] = tuple(s.id for s in STAGES)
BY_ID: Dict[str, Stage] = {s.id: s for s in STAGES}


def stage_index(stage_id: str) -> int:
    return STAGE_IDS.index(stage_id)


# ---------------------------------------------------------------------------
# Stage outcomes
# ---------------------------------------------------------------------------

PENDING = 'pending'      # not reached yet
RUNNING = 'running'      # working right now
WAITING = 'waiting'      # paused on purpose: a timer, Sonarr, the queue, a person
PASSED = 'passed'
SKIPPED = 'skipped'
FAILED = 'failed'
REFUSED = 'refused'      # stopped on purpose, for a person to decide

STAGE_STATUSES = (PENDING, RUNNING, WAITING, PASSED, SKIPPED, FAILED, REFUSED)
STAGE_DONE = (PASSED, SKIPPED, FAILED, REFUSED)

# ---------------------------------------------------------------------------
# Run states
# ---------------------------------------------------------------------------

#: Open: the batch has not started copying, so a new webhook may join it.
HELD = 'held'                # waiting for a person (automatic sync is off)
WAITING_STATE = 'waiting'    # in the ready check
CHECKING = 'checking'        # the safety dry run is running
QUEUED = 'queued'            # handed to the queue, not copying yet
#: Active: copying, or about to resume copying. A webhook arriving now goes
#: to the follow-up batch behind it.
TRANSFERRING = 'transferring'
PAUSED = 'paused'
FINISHING = 'finishing'
#: Done.
COMPLETED = 'completed'
FAILED_STATE = 'failed'
CANCELLED = 'cancelled'
REFUSED_STATE = 'refused'
INTERRUPTED = 'interrupted'

OPEN_STATES = (HELD, WAITING_STATE, CHECKING, QUEUED)
ACTIVE_STATES = (TRANSFERRING, PAUSED, FINISHING)
LIVE_STATES = OPEN_STATES + ACTIVE_STATES
TERMINAL_STATES = (COMPLETED, FAILED_STATE, CANCELLED, REFUSED_STATE, INTERRUPTED)

STATE_LABELS = {
    HELD: 'Waiting for a person',
    WAITING_STATE: 'Waiting for the download',
    CHECKING: 'Checking safety',
    QUEUED: 'In the queue',
    TRANSFERRING: 'Copying',
    PAUSED: 'Paused',
    FINISHING: 'Finishing',
    COMPLETED: 'Synced',
    FAILED_STATE: 'Failed',
    CANCELLED: 'Cancelled',
    REFUSED_STATE: 'Stopped for a person',
    INTERRUPTED: 'Interrupted by a restart',
}

# ---------------------------------------------------------------------------
# Kinds of sync
# ---------------------------------------------------------------------------

SONARR_WEBHOOK = 'sonarr_webhook'
RADARR_WEBHOOK = 'radarr_webhook'
AUTO_SCANNER = 'auto_scanner'
MANUAL = 'manual'
EXPLORE = 'explore'
RESTART = 'restart'
RESTORE = 'restore'
SIMULATION = 'simulation'

#: How a stage runs for a kind.
RUN = 'run'
DIFFERENT = 'diff'
SKIP = 'skip'


@dataclass(frozen=True)
class KindPolicy:
    id: str
    label: str
    description: str
    #: stage id -> (mode, sentence). A stage not listed runs as standard.
    stages: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    #: Whether runs of this kind take in other requests for the same folder.
    mergeable: bool = True

    def mode(self, stage_id: str) -> str:
        return self.stages.get(stage_id, (RUN, ''))[0]

    def note(self, stage_id: str) -> str:
        return self.stages.get(stage_id, (RUN, ''))[1]

    def as_dict(self) -> Dict:
        return {
            'id': self.id,
            'label': self.label,
            'description': self.description,
            'mergeable': self.mergeable,
            'stages': {
                stage.id: {'mode': self.mode(stage.id), 'note': self.note(stage.id)}
                for stage in STAGES
            },
        }


KINDS: Dict[str, KindPolicy] = {
    SONARR_WEBHOOK: KindPolicy(
        SONARR_WEBHOOK, 'Sonarr webhook',
        'One webhook per imported episode, for series and anime. The full '
        'pipeline, including the ready check.',
    ),
    RADARR_WEBHOOK: KindPolicy(
        RADARR_WEBHOOK, 'Radarr webhook',
        'One webhook per imported or upgraded movie. Never waits.',
        stages={
            READY: (SKIP, 'A Radarr webhook means one finished movie, so there is '
                          'nothing to wait for — whether Radarr’s API is up or not.'),
        },
    ),
    AUTO_SCANNER: KindPolicy(
        AUTO_SCANNER, 'Auto-scanner',
        'The scheduled auto-scanner found something the service has and this '
        'disk does not — usually because a webhook never arrived.',
        stages={
            RECEIVE: (DIFFERENT, 'The auto-scanner records what it found and why.'),
            READY: (DIFFERENT, 'Sonarr finds get the full ready check; Radarr finds '
                               'are one finished movie and skip it.'),
            TELL: (DIFFERENT, 'The scanner reports what it started, then the usual '
                              'finished or failed message follows.'),
        },
    ),
    MANUAL: KindPolicy(
        MANUAL, 'Manual sync',
        'An admin pressed Sync — on the Webhooks page, a Library tab, or an alert.',
        stages={
            BATCH: (DIFFERENT, 'A batch already waiting for this folder is told to go '
                               'now instead of a second transfer being started.'),
            READY: (SKIP, 'Skipped: an admin asked for this sync now.'),
            SAFETY: (DIFFERENT, 'The same dry run, but an admin may choose to go ahead '
                                'when it fails. Automatic syncs never can.'),
        },
    ),
    EXPLORE: KindPolicy(
        EXPLORE, 'Explore',
        'An admin pressed Sync, Download or Replace in Explore and confirmed its '
        'review.',
        stages={
            IDENTIFY: (DIFFERENT, 'Copies exactly the files listed in Explore’s review, '
                                  'not the whole folder.'),
            BATCH: (SKIP, 'Skipped: it copies a fixed list of files, so webhooks never '
                          'join it. The queue still holds it behind anything writing '
                          'to the same folder.'),
            READY: (SKIP, 'Skipped: Explore compared both sides just before it started.'),
            SAFETY: (DIFFERENT, 'Explore’s review checked these exact files before it '
                                'started.'),
        },
        mergeable=False,
    ),
    RESTART: KindPolicy(
        RESTART, 'Restart',
        'An admin restarted a failed or stopped transfer.',
        stages={
            IDENTIFY: (DIFFERENT, 'The same folders as the attempt being retried.'),
            BATCH: (DIFFERENT, 'If a batch for the same folder is already waiting, '
                               'the restart joins it instead of copying twice.'),
            READY: (SKIP, 'Skipped: this retries something that was already ready.'),
            TRANSFER: (DIFFERENT, 'rsync picks up its partial files where the last '
                                  'attempt stopped.'),
        },
    ),
    RESTORE: KindPolicy(
        RESTORE, 'Restore',
        'An admin put an older version from the backup area back into the library.',
        stages={
            IDENTIFY: (DIFFERENT, 'What changes is the one episode or movie being '
                                  'swapped.'),
            BATCH: (SKIP, 'Skipped: one restore swaps one slot; there is nothing to '
                          'merge it with.'),
            READY: (SKIP, 'Skipped: nothing is downloading — the files come from the '
                          'backup area.'),
            SAFETY: (DIFFERENT, 'The restore preview named the exact file it replaces '
                                'before it ran.'),
            QUEUE: (DIFFERENT, 'A restore refuses rather than waits when its folder '
                               'is busy: someone is watching it, and parking it '
                               'silently behind a sync is worse than saying so.'),
            TRANSFER: (DIFFERENT, 'A local copy from the backup area, not rsync from '
                                  'the media server.'),
            FINISH: (DIFFERENT, 'The file it replaced is kept as a new backup version, '
                                'so a restore can be undone.'),
        },
        mergeable=False,
    ),
    SIMULATION: KindPolicy(
        SIMULATION, 'Simulation',
        'A rehearsal: the real pipeline against throwaway files in a sandbox.',
        stages={
            RECEIVE: (DIFFERENT, 'Marked as a simulation everywhere it is recorded.'),
            IDENTIFY: (DIFFERENT, 'Throwaway files in a sandbox folder.'),
            BATCH: (SKIP, 'Each rehearsal transfer stands alone, so what it exercises is '
                          'the queue’s own rules — slots and folder locks.'),
            READY: (SKIP, 'Skipped: nothing is downloading in a rehearsal.'),
            SAFETY: (SKIP, 'Skipped: the dry run checks the media server, and a '
                           'simulation copies sandbox files that live on this '
                           'machine.'),
            TRANSFER: (DIFFERENT, 'Real rsync on throwaway files, held to a set speed.'),
            TELL: (DIFFERENT, 'Rehearsals are not announced on Discord.'),
        },
        mergeable=False,
    ),
}


def policy(kind: str) -> KindPolicy:
    found = KINDS.get(kind)
    if found is None:
        raise ValueError(f"Unknown sync kind {kind!r}")
    return found


def kind_label(kind: str) -> str:
    found = KINDS.get(kind)
    return found.label if found else kind


def catalogue() -> Dict:
    """Everything the interface needs to draw the pipeline the engine runs."""
    return {
        'stages': [s.as_dict() for s in STAGES],
        'kinds': [k.as_dict() for k in KINDS.values()],
        'stage_statuses': list(STAGE_STATUSES),
        'states': {
            'open': list(OPEN_STATES),
            'active': list(ACTIVE_STATES),
            'terminal': list(TERMINAL_STATES),
            'labels': dict(STATE_LABELS),
        },
    }


def describe_state(state: Optional[str]) -> str:
    return STATE_LABELS.get(state or '', state or '')
