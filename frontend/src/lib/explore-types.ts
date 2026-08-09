/**
 * Shapes returned by the Explore endpoints.
 *
 * The four labels are the whole vocabulary: every badge, count and action on
 * the page is derived from them.
 */

export type ExploreLabel = "IN_SYNC" | "MISSING" | "UPGRADED" | "LOCAL_ONLY";
export type ExploreStatus = "SYNCED" | "PARTIAL_SYNC" | "OUT_OF_SYNC" | "NO_INFO";

export interface ExploreCounts {
  in_sync: number;
  missing: number;
  upgraded: number;
  local_only: number;
  remote_total: number;
  incoming_bytes: number;
  removable_bytes: number;
}

export interface ExploreSeriesSummary {
  name: string;
  media_type: string;
  status: ExploreStatus;
  counts: ExploreCounts;
  season_count: number;
  exists_locally: boolean;
  remote_bytes: number;
  local_bytes: number;
  remote_mtime: number;
  misplaced_count: number;
  /** Season folders Sonarr would have named differently, e.g. "Season 1". */
  odd_folders: string[];
  /** Every season, sent with the tree so several series can stay expanded. */
  seasons?: ExploreSeason[];
}

export interface ExploreSeason {
  series: string;
  season: number | null;
  name: string;
  remote_folder: string | null;
  local_folder: string | null;
  status: ExploreStatus;
  counts: ExploreCounts;
  ancillary_missing: number;
  ancillary_local_only: number;
  /** What Sonarr would call this folder, e.g. "Season 04". Null for movies. */
  standard_name: string | null;
  /** The folders on either side that differ from it. Empty when both match. */
  odd_folders: string[];
  misplaced: string[];
  remote_bytes: number;
  local_bytes: number;
  remote_mtime: number;
  episodes?: ExploreEpisode[];
}

export interface ExploreEpisode {
  label: ExploreLabel;
  code: string;
  season: number | null;
  episode: number | null;
  renamed: boolean;
  remote_name: string | null;
  remote_size: number | null;
  remote_mtime: number | null;
  remote_path: string | null;
  local_name: string | null;
  local_size: number | null;
  local_mtime: number | null;
  local_path: string | null;
  absolute_number: number | null;
}

export interface ExploreSeries extends ExploreSeriesSummary {
  seasons: ExploreSeason[];
}

export interface ExploreTree {
  media_type: string;
  series: ExploreSeriesSummary[];
  checked_at: string | null;
  stale: boolean;
}

export interface ExplorePlanAction {
  action: "fetch" | "supersede" | "remove";
  rel: string;
  size: number;
  code: string;
  season: number | null;
  season_label: string;
  local_rel: string | null;
  local_size: number;
  reason: string;
}

export interface ExplorePlanGroup {
  season_label: string;
  season: number | null;
  fetch: number;
  supersede: number;
  remove: number;
  incoming_bytes: number;
  backup_bytes: number;
  actions: ExplorePlanAction[];
}

export interface ExploreSafetyCheck {
  id: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface ExplorePlan {
  plan_id: string;
  media_type: string;
  operation: string;
  series: string;
  season_label: string | null;
  source_root: string;
  dest_root: string;
  include_removals: boolean;
  safe: boolean;
  is_destructive: boolean;
  is_empty: boolean;
  requires_override: boolean;
  verdict: string;
  counts: {
    fetch: number;
    supersede: number;
    remove: number;
    incoming_bytes: number;
    backup_bytes: number;
  };
  checks: ExploreSafetyCheck[];
  warnings: string[];
  groups: ExplorePlanGroup[];
}

/** What rsync says it would do, asked with --dry-run before anything moves. */
export type DryRunChange = "new" | "replaced" | "unchanged" | "deleted" | "directory";

export interface ExploreDryRunFile {
  change: DryRunChange;
  rel: string;
  size: number;
  itemize: string;
  is_media: boolean;
}

export interface ExploreDryRunReport {
  ok: boolean;
  /** False when the plan only removes files — there was nothing to ask rsync. */
  ran: boolean;
  exit_code: number;
  error: string | null;
  duration_ms: number;
  verdict: string;
  summary: {
    new: number;
    replaced: number;
    unchanged: number;
    directories: number;
    deleted: number;
    backed_up: number;
    removed: number;
    incoming_bytes: number;
    backup_bytes: number;
    removed_bytes: number;
    media_new: number;
    media_replaced: number;
  };
  files: ExploreDryRunFile[];
  backups: Array<{ rel?: string; local_rel: string; local_size: number; code?: string | null }>;
  removals: Array<{ rel?: string; local_rel: string; local_size: number; code?: string | null }>;
  warnings: string[];
  raw_tail: string;
}

export interface ExploreDryRun {
  plan_id: string;
  operation: string;
  series: string;
  season_label: string | null;
  source_root: string;
  dest_root: string;
  report: ExploreDryRunReport;
}

/** A copy that was moved aside before a sync overwrote or removed it. */
export interface ExploreBackupFile {
  relative_path: string;
  original_path: string;
  file_size: number;
  modified_time: number;
  season: number | null;
  episode: number | null;
  /** `S04E03`, or null for artwork and metadata that carry no episode. */
  code: string | null;
  context_display: string | null;
}

export interface ExploreBackupRun {
  backup_id: string;
  transfer_id: string;
  media_type: string;
  folder_name: string;
  season_name: string | null;
  backup_path: string;
  dest_path: string;
  status: string;
  created_at: string;
  restored_at: string | null;
  /** Totals for the whole run, which may span more than the season shown. */
  file_count: number;
  total_size: number;
  /** Totals for what is shown here, after narrowing to this season. */
  shown_count: number;
  shown_size: number;
  files: ExploreBackupFile[];
}

/** A copy of the same episode or film already sitting where it belongs. */
export interface ExploreRepairRival {
  relative_path: string;
  name: string;
  size: number;
  /** True when it is literally the same filename — the plain wrapper case. */
  same_name: boolean;
}

/** What to do with a stranded file whose place is already taken. */
export type RepairDecision = "keep_existing" | "replace";

/** One stranded file and where the repair would put it. */
export interface ExploreRepairAction {
  relative_path: string;
  destination: string;
  name: string;
  season_folder: string | null;
  size: number;
  /** The folder it is buried in, which comes down once it moves. */
  wrapper: string;
  /** What already holds this episode or film, if anything. */
  rival: ExploreRepairRival | null;
  /** True when `rival` is set: one of the two copies has to go. */
  needs_decision: boolean;
}

/** A stranded file the repair will not touch, and why not in plain words. */
export interface ExploreRepairBlocker {
  relative_path: string;
  reason: string;
  size: number;
}

export interface ExploreRepairPlan {
  media_type: string;
  scope: string;
  actions: ExploreRepairAction[];
  blocked: ExploreRepairBlocker[];
  /** Files that can simply be moved — excludes the contested ones. */
  action_count: number;
  /** Files whose place is already held by another copy of the same thing. */
  contested_count: number;
  blocked_count: number;
  total_size: number;
  /** What deleting every contested stranded copy would free. */
  reclaimable: number;
  /** Why the repair cannot run right now, or null. */
  blocker: string | null;
}

export interface ExploreRepairResult {
  scope: string;
  moved: Array<{ relative_path: string; destination: string; size: number }>;
  deleted: Array<{ relative_path: string; kept_instead: string; size: number }>;
  replaced: Array<{ relative_path: string; replaced_by: string; size: number }>;
  failed: Array<{ relative_path: string; error: string }>;
  blocked: ExploreRepairBlocker[];
  moved_count: number;
  deleted_count: number;
  replaced_count: number;
  failed_count: number;
  directories_removed: number;
  moved_size: number;
  freed_size: number;
}

export interface ExploreHistoryFile {
  action: string;
  rel_path: string;
  size: number;
  code: string | null;
  season_label: string | null;
}

export interface ExploreHistoryRun {
  transfer_id: string;
  media_type: string;
  folder_name: string;
  season_name: string | null;
  operation_type: string;
  status: string;
  progress: string;
  start_time: string | null;
  end_time: string | null;
  total_bytes: number | null;
  bytes_transferred: number | null;
  explore_mode: string | null;
  files: ExploreHistoryFile[];
}
