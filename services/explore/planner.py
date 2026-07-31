#!/usr/bin/env python3
"""
Planning — turn a comparison into an explicit list of actions plus a verdict.

Nothing here touches the disk. A plan says exactly which files will be fetched,
which local files will be moved to backup, and why — which is what makes the
preview honest and what the executor is then held to.

Why an explicit plan instead of `rsync --delete`:

  * `--delete` removes anything the transfer set does not contain, including
    artwork and subtitles, and it cannot be shown to you beforehand in terms of
    episodes.
  * an upgrade whose filename changed needs the OLD local file moved out of the
    way, or you end up holding both copies. rsync will never do that for you.
  * the preview you approve and the work that runs have to be the same list.

Every action's `rel` is relative to the plan's source/destination roots, so the
executor can hand rsync a --files-from list and nothing has to be re-derived.

New files land in the LOCAL season folder when one already exists, even if it is
spelled differently from the remote ("Season 1" vs "Season 01"). Creating the
remote spelling alongside it would split the season in two.
"""

import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .compare import (
    IN_SYNC, LOCAL_ONLY, MISSING, UPGRADED,
    EpisodeDiff, SeasonDiff, SeriesDiff,
)

# Operations
SYNC_SERIES = 'sync_series'
SYNC_SEASON = 'sync_season'
SYNC_SEASONS = 'sync_seasons'   # several seasons ticked in the list, one plan
DOWNLOAD = 'download'
REPLACE = 'replace'

# Actions
FETCH = 'fetch'      # copy a file that is not there
SUPERSEDE = 'supersede'  # back up the local file, then copy the new one
REMOVE = 'remove'    # move a local file to backup, nothing replaces it

# A sync that would clear out more than this share of a season's local media
# files is stopped for review even if the raw counts look acceptable.
DEFAULT_REMOVAL_SHARE = 0.20


@dataclass
class PlanAction:
    action: str
    rel: str                      # path relative to the plan roots
    size: int
    code: str = ''
    season: Optional[int] = None
    season_label: str = ''
    local_rel: Optional[str] = None   # the file being backed up, when there is one
    local_size: int = 0
    reason: str = ''

    def to_dict(self) -> Dict:
        return {
            'action': self.action,
            'rel': self.rel,
            'size': self.size,
            'code': self.code,
            'season': self.season,
            'season_label': self.season_label,
            'local_rel': self.local_rel,
            'local_size': self.local_size,
            'reason': self.reason,
        }


@dataclass
class SafetyCheck:
    id: str
    label: str
    passed: bool
    detail: str

    def to_dict(self) -> Dict:
        return {'id': self.id, 'label': self.label, 'passed': self.passed, 'detail': self.detail}


@dataclass
class PlanUnit:
    """
    One transfer's worth of work: a single season folder, both sides.

    A transfer in this application is scoped to a season folder — that is what
    the queue locks on, what a webhook produces, and what the backup and history
    records are keyed by. A plan that spans seasons is therefore a plan for
    SEVERAL transfers, one per season, and this is one of them.

    Each unit carries its own pair of roots, which is why a season spelled
    "Season 01" remotely and "Season 1" locally needs no special handling: the
    run reads from one and writes into the other, and the file list is bare
    filenames that cannot recreate a folder.
    """
    season_label: str
    season_name: Optional[str]
    source_root: str
    dest_root: str
    actions: List[PlanAction] = field(default_factory=list)

    @property
    def transfer_rels(self) -> List[str]:
        return [a.rel for a in self.actions if a.action in (FETCH, SUPERSEDE)]


@dataclass
class Plan:
    media_type: str
    operation: str
    series: str
    source_root: str
    dest_root: str
    season_label: Optional[str] = None
    actions: List[PlanAction] = field(default_factory=list)
    checks: List[SafetyCheck] = field(default_factory=list)
    include_removals: bool = True
    warnings: List[str] = field(default_factory=list)
    # One per season. A season-scoped plan has exactly one; a series plan has
    # one for every season it touches, and each becomes its own transfer.
    units: List[PlanUnit] = field(default_factory=list)

    # ---- derived ----------------------------------------------------------

    @property
    def fetches(self) -> List[PlanAction]:
        return [a for a in self.actions if a.action == FETCH]

    @property
    def supersedes(self) -> List[PlanAction]:
        return [a for a in self.actions if a.action == SUPERSEDE]

    @property
    def removals(self) -> List[PlanAction]:
        return [a for a in self.actions if a.action == REMOVE]

    @property
    def incoming_bytes(self) -> int:
        return sum(a.size for a in self.actions if a.action in (FETCH, SUPERSEDE))

    @property
    def backup_bytes(self) -> int:
        return sum(a.local_size for a in self.actions if a.action in (SUPERSEDE, REMOVE))

    @property
    def transfer_rels(self) -> List[str]:
        """The file list handed to rsync — fetches and replacements."""
        return [a.rel for a in self.actions if a.action in (FETCH, SUPERSEDE)]

    @property
    def backup_rels(self) -> List[str]:
        """Local files that move to backup before anything is written."""
        return [a.local_rel for a in self.actions
                if a.action in (SUPERSEDE, REMOVE) and a.local_rel]

    @property
    def is_destructive(self) -> bool:
        return bool(self.supersedes or self.removals)

    @property
    def safe(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def is_empty(self) -> bool:
        return not self.actions

    def grouped(self) -> List[Dict]:
        """Actions grouped by season — how a series-level plan is reviewed."""
        groups: Dict[str, Dict] = {}
        for action in self.actions:
            label = action.season_label or self.season_label or ''
            group = groups.setdefault(label, {
                'season_label': label,
                'season': action.season,
                'fetch': 0, 'supersede': 0, 'remove': 0,
                'incoming_bytes': 0, 'backup_bytes': 0,
                'actions': [],
            })
            group[action.action] += 1
            if action.action in (FETCH, SUPERSEDE):
                group['incoming_bytes'] += action.size
            if action.action in (SUPERSEDE, REMOVE):
                group['backup_bytes'] += action.local_size
            group['actions'].append(action.to_dict())

        # Removals first: a season that loses files is what you need to see.
        return sorted(groups.values(), key=lambda g: (-g['remove'], g['season_label']))

    def verdict(self) -> str:
        """One sentence, in the terms you care about."""
        if self.is_empty:
            return 'Nothing to do — the local copy already matches the remote.'
        parts = []
        if self.fetches:
            parts.append(f"downloads {len(self.fetches)}")
        if self.supersedes:
            parts.append(f"replaces {len(self.supersedes)}")
        if self.removals:
            parts.append(f"removes {len(self.removals)}")
        else:
            parts.append('removes nothing')
        return f"This {_scope_word(self.operation)} {', '.join(parts)}."

    def to_dict(self) -> Dict:
        return {
            'media_type': self.media_type,
            'operation': self.operation,
            'series': self.series,
            'season_label': self.season_label,
            'source_root': self.source_root,
            'dest_root': self.dest_root,
            'include_removals': self.include_removals,
            'safe': self.safe,
            'is_destructive': self.is_destructive,
            'is_empty': self.is_empty,
            'verdict': self.verdict(),
            'counts': {
                'fetch': len(self.fetches),
                'supersede': len(self.supersedes),
                'remove': len(self.removals),
                'incoming_bytes': self.incoming_bytes,
                'backup_bytes': self.backup_bytes,
            },
            'checks': [c.to_dict() for c in self.checks],
            'warnings': self.warnings,
            'groups': self.grouped(),
        }


def _scope_word(operation: str) -> str:
    return {
        SYNC_SERIES: 'series sync',
        SYNC_SEASON: 'season sync',
        SYNC_SEASONS: 'sync',
        DOWNLOAD: 'download',
        REPLACE: 'replacement',
    }.get(operation, 'operation')


def _season_dest_folder(season: SeasonDiff) -> str:
    """
    Where new files go. An existing local folder wins over the remote spelling —
    "Season 1" locally stays "Season 1" rather than gaining a sibling
    "Season 01" holding half the episodes.
    """
    return season.local_folder or season.remote_folder or ''


def _episode_actions(season: SeasonDiff, prefix: str,
                     include_removals: bool,
                     only_codes: Optional[Sequence[str]] = None,
                     labels: Sequence[str] = (MISSING, UPGRADED)) -> List[PlanAction]:
    """Turn one season's episode diffs into plan actions."""
    actions: List[PlanAction] = []
    dest_folder = _season_dest_folder(season)
    label_name = season.display_name

    for episode in season.episodes:
        if only_codes is not None and episode.code not in only_codes:
            continue

        if episode.label == MISSING and MISSING in labels:
            actions.append(PlanAction(
                action=FETCH,
                rel=_join(prefix, episode.remote.name),
                size=episode.remote.size,
                code=episode.code,
                season=season.season,
                season_label=label_name,
                reason='Not in the local library',
            ))
        elif episode.label == UPGRADED and UPGRADED in labels:
            actions.append(PlanAction(
                action=SUPERSEDE,
                rel=_join(prefix, episode.remote.name),
                size=episode.remote.size,
                code=episode.code,
                season=season.season,
                season_label=label_name,
                local_rel=_local_rel(prefix, dest_folder, episode.local),
                local_size=episode.local.size,
                reason='A different file for this episode is on the remote',
            ))
        elif episode.label == IN_SYNC and IN_SYNC in labels and episode.remote:
            # Only reachable by ticking a file that already matches and asking
            # for a replacement — "my copy is damaged, fetch it again". Never
            # produced by a sync, which has nothing to do with a matching file.
            actions.append(PlanAction(
                action=SUPERSEDE,
                rel=_join(prefix, episode.remote.name),
                size=episode.remote.size,
                code=episode.code,
                season=season.season,
                season_label=label_name,
                local_rel=(_local_rel(prefix, dest_folder, episode.local)
                           if episode.local else None),
                local_size=episode.local.size if episode.local else 0,
                reason='Asked for again, though the local copy already matches',
            ))
        # Removal is gated on include_removals alone. `labels` narrows which
        # *arrivals* a selection-based operation may produce; download and
        # replace pass include_removals=False, so they can never remove.
        elif episode.label == LOCAL_ONLY and include_removals:
            actions.append(PlanAction(
                action=REMOVE,
                rel='',
                size=0,
                code=episode.code,
                season=season.season,
                season_label=label_name,
                local_rel=_local_rel(prefix, dest_folder, episode.local),
                local_size=episode.local.size,
                reason='Not on the remote any more',
            ))

    return actions


def _join(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


def _local_rel(prefix: str, dest_folder: str, entry) -> str:
    """
    The local file's path relative to the plan's destination root.

    Derived from the entry's own relative path so a misplaced file (one nested a
    level too deep) still resolves to the file that is really there.
    """
    parts = [p for p in entry.relative_path.split('/') if p]
    # relative_path is series/[season...]/name — drop the series segment.
    without_series = '/'.join(parts[1:]) if len(parts) > 1 else parts[-1]
    if prefix:
        return without_series
    # Season-scoped plan: the destination root already is the season folder.
    season_parts = [p for p in without_series.split('/')]
    if season_parts and dest_folder and season_parts[0] == dest_folder.split('/')[0]:
        return '/'.join(season_parts[1:]) or season_parts[-1]
    return without_series


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------

def _build_unit(series: str, season: SeasonDiff, remote_root: str, local_root: str,
                include_removals: bool,
                only_codes: Optional[Sequence[str]] = None,
                labels: Sequence[str] = (MISSING, UPGRADED)) -> PlanUnit:
    """
    One season, both sides, as a single transfer's worth of work.

    The roots are the two season folders, so the file list is bare filenames.
    That is what lets the remote and local spellings differ — rsync reads from
    one folder and writes into the other, and no path in the list can recreate
    a folder on the way.
    """
    remote_folder = season.remote_folder or season.local_folder or ''
    dest_folder = _season_dest_folder(season)

    return PlanUnit(
        season_label=season.display_name,
        season_name=dest_folder or None,
        source_root=os.path.join(remote_root, series, remote_folder) if remote_folder
        else os.path.join(remote_root, series),
        dest_root=os.path.join(local_root, series, dest_folder) if dest_folder
        else os.path.join(local_root, series),
        actions=_episode_actions(season, '', include_removals,
                                 only_codes=only_codes, labels=labels),
    )


def _single_unit_plan(operation: str, media_type: str, series_diff: SeriesDiff,
                      unit: PlanUnit, include_removals: bool,
                      season_label: Optional[str]) -> Plan:
    plan = Plan(
        media_type=media_type,
        operation=operation,
        series=series_diff.series,
        season_label=season_label,
        source_root=unit.source_root,
        dest_root=unit.dest_root,
        include_removals=include_removals,
        units=[unit],
    )
    plan.actions = unit.actions
    return plan


def plan_season_sync(media_type: str, series_diff: SeriesDiff, season: SeasonDiff,
                     remote_root: str, local_root: str,
                     include_removals: bool = True) -> Plan:
    """Reconcile one season: download what is missing, replace what changed."""
    unit = _build_unit(series_diff.series, season, remote_root, local_root, include_removals)
    return _single_unit_plan(SYNC_SEASON, media_type, series_diff, unit,
                             include_removals, season.display_name)


def plan_series_sync(media_type: str, series_diff: SeriesDiff,
                     remote_root: str, local_root: str,
                     include_removals: bool = True) -> Plan:
    """
    Reconcile every season of a series as ONE plan, grouped by season.

    A series with one season needing downloads and another needing removals is a
    single decision — the review screen groups it and puts the removals first.
    """
    return _multi_season_plan(SYNC_SERIES, media_type, series_diff,
                              series_diff.seasons, remote_root, local_root,
                              include_removals)


def plan_seasons_sync(media_type: str, series_diff: SeriesDiff,
                      seasons: Sequence[SeasonDiff],
                      remote_root: str, local_root: str,
                      include_removals: bool = True) -> Plan:
    """
    Reconcile the seasons that were ticked, as ONE plan.

    Identical in shape to a series sync — the only difference is which seasons
    are in it. One plan means one transfer and one review, however many seasons
    were picked.
    """
    return _multi_season_plan(SYNC_SEASONS, media_type, series_diff, seasons,
                              remote_root, local_root, include_removals)


def _multi_season_plan(operation: str, media_type: str, series_diff: SeriesDiff,
                       seasons: Sequence[SeasonDiff],
                       remote_root: str, local_root: str,
                       include_removals: bool) -> Plan:
    """
    One review covering several seasons, carried out as one transfer EACH.

    A transfer is scoped to a season folder everywhere else in the application —
    it is what the queue locks on and what a webhook produces — so a series sync
    is not one big transfer but several ordinary ones. They land on distinct
    destinations, so the queue runs them in parallel up to its slot cap instead
    of serialising a single run through every season.

    The plan itself stays whole: one verdict, one set of safety checks, one
    review grouped by season with the removals at the top.
    """
    plan = Plan(
        media_type=media_type,
        operation=operation,
        series=series_diff.series,
        # The series roots describe the plan's scope for display. The work is
        # carried out against each unit's own pair of season folders.
        source_root=os.path.join(remote_root, series_diff.series),
        dest_root=os.path.join(local_root, series_diff.series),
        include_removals=include_removals,
    )

    for season in seasons:
        unit = _build_unit(series_diff.series, season, remote_root, local_root,
                           include_removals)
        if not unit.actions:
            continue
        plan.units.append(unit)
        plan.actions.extend(unit.actions)

    return plan


def plan_movie_sync(media_type: str, series_diff: SeriesDiff,
                    remote_root: str, local_root: str,
                    include_removals: bool = True) -> Plan:
    """A movie folder has no season layer; otherwise identical to a season."""
    unit = PlanUnit(
        season_label='Files',
        season_name=None,
        source_root=os.path.join(remote_root, series_diff.series),
        dest_root=os.path.join(local_root, series_diff.series),
    )
    for season in series_diff.seasons:
        unit.actions.extend(_episode_actions(season, '', include_removals))
    return _single_unit_plan(SYNC_SEASON, media_type, series_diff, unit,
                             include_removals, None)


def plan_download(media_type: str, series_diff: SeriesDiff, season: SeasonDiff,
                  remote_root: str, local_root: str,
                  codes: Sequence[str]) -> Plan:
    """
    Copy the selected episodes and nothing else. Never replaces, never removes —
    an episode already present is simply skipped.
    """
    # Only MISSING episodes are fetchable here: an UPGRADED one would need its
    # local counterpart moved aside first, which is the replace operation.
    unit = _build_unit(series_diff.series, season, remote_root, local_root, False,
                       only_codes=codes, labels=(MISSING,))
    return _single_unit_plan(DOWNLOAD, media_type, series_diff, unit,
                             False, season.display_name)


def plan_replace(media_type: str, series_diff: SeriesDiff, season: SeasonDiff,
                 remote_root: str, local_root: str,
                 codes: Sequence[str]) -> Plan:
    """
    Swap the selected episodes: back up the local file, bring the remote one.
    Nothing else in the season is touched.
    """
    unit = _build_unit(series_diff.series, season, remote_root, local_root, False,
                       only_codes=codes, labels=(MISSING, UPGRADED, IN_SYNC))
    return _single_unit_plan(REPLACE, media_type, series_diff, unit,
                             False, season.display_name)


# --------------------------------------------------------------------------
# safety
# --------------------------------------------------------------------------

def evaluate(plan: Plan, season_or_series, local_media_total: int,
             removal_share: float = DEFAULT_REMOVAL_SHARE,
             duplicate_codes: Optional[Sequence[str]] = None) -> Plan:
    """
    Run the safety checks over a built plan.

    All counts are media files. Artwork, subtitles and metadata travel with the
    media and never trip a threshold — the library holds roughly twice as many
    of them as episodes, so including them would make every number meaningless.
    """
    checks: List[SafetyCheck] = []

    arrivals = len(plan.fetches) + len(plan.supersedes)
    removals = len(plan.removals)

    checks.append(SafetyCheck(
        id='removals_vs_arrivals',
        label='Removals do not outnumber arrivals',
        passed=removals <= arrivals,
        detail=(f"{removals} would be removed, {arrivals} would arrive"
                if removals else 'Nothing would be removed'),
    ))

    if local_media_total > 0 and removals:
        share = removals / local_media_total
        checks.append(SafetyCheck(
            id='removal_share',
            label='Removals stay under the safety threshold',
            passed=share <= removal_share,
            detail=f"{removals} of {local_media_total} local episodes ({share:.0%})",
        ))

    remote_total = getattr(season_or_series, 'counts', None)
    if remote_total is not None:
        counts = season_or_series.counts
        local_total = counts.in_sync + counts.upgraded + counts.local_only
        checks.append(SafetyCheck(
            id='remote_shrunk',
            label='The remote is not smaller than the local copy',
            passed=counts.remote_total >= local_total or not plan.removals,
            detail=(f"remote holds {counts.remote_total} episodes, "
                    f"local holds {local_total}"),
        ))

    if duplicate_codes:
        checks.append(SafetyCheck(
            id='duplicate_identity',
            label='No episode matches more than one local file',
            passed=False,
            detail='Ambiguous: ' + ', '.join(sorted(duplicate_codes)[:8]),
        ))

    free = _free_bytes(plan.dest_root)
    if free is not None:
        checks.append(SafetyCheck(
            id='free_space',
            label='The destination has room',
            passed=free >= plan.incoming_bytes,
            detail=f"{_gb(plan.incoming_bytes)} incoming, {_gb(free)} free",
        ))

    plan.checks = checks
    return plan


def _free_bytes(path: str) -> Optional[int]:
    """Free space at the nearest existing ancestor of a destination path."""
    probe = path
    for _ in range(8):
        if os.path.isdir(probe):
            try:
                return shutil.disk_usage(probe).free
            except OSError:
                return None
        parent = os.path.dirname(probe)
        if not parent or parent == probe:
            return None
        probe = parent
    return None


def _gb(value: int) -> str:
    return f"{value / (1024 ** 3):.1f} GB"
