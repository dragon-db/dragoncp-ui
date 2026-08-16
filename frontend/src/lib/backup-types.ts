/**
 * The Backups vocabulary.
 *
 * A **slot** is one movie or one episode. A **capture** is one previous
 * occupant of that slot: the file plus the sidecars that travelled with it,
 * taken at one moment. The library holds the current occupant; the backup area
 * holds the rest, newest first.
 *
 * Restoring promotes a capture to current, which pushes the file it replaced
 * into the same slot's history — so undoing a restore is restoring the capture
 * the restore itself created, not a separate operation.
 */

export type BackupLibrary = "movies" | "shows" | "anime";

export type CaptureKind = "slot" | "extras" | "unsorted";

export type CaptureReason = "sync_replace" | "sync_delete" | "restore_swap" | "explore_prune";

export interface CaptureFile {
  relative_path: string;
  original_path: string;
  file_size: number;
  modified_time: number;
  is_media: 0 | 1;
}

export interface Capture {
  capture_id: string;
  library: BackupLibrary | null;
  title: string | null;
  season_number: number | null;
  episode_number: number | null;
  release_year: string | null;
  slot_key: string | null;
  capture_path: string;
  captured_at: string;
  source_transfer_id: string | null;
  source_ref: string | null;
  reason: CaptureReason | string | null;
  kind: CaptureKind;
  file_count: number;
  total_size: number;
  pinned: 0 | 1;
  /** Whether the files are still on the backup disk, and nothing else. */
  status: "present" | "files_removed";
  /** When this version was last put back into the library, if it ever was. */
  restored_at: string | null;
  /** Who put it back. Absent for a restore that predates attribution. */
  restored_by_kind?: "admin" | "automated" | "system" | null;
  restored_by_name?: string | null;
  restored_by_account_id?: number | null;
  /** Present on the detail endpoints only. */
  files?: CaptureFile[];
  slot_keys?: string[];
  display?: string;
}

/** One row of the slot list: an episode or movie with versions stored. */
export interface SlotSummary {
  slot_key: string;
  library: BackupLibrary;
  title: string;
  season_number: number | null;
  episode_number: number | null;
  release_year: string | null;
  version_count: number;
  total_size: number;
  latest_captured_at: string;
  has_pinned: 0 | 1;
  display: string;
}

/** What the library currently holds for a slot, if anything. */
export interface CurrentOccupant {
  path: string;
  name: string;
  size: number;
  directory: string;
}

export interface SlotDetail {
  slot_key: string;
  display: string;
  captures: Capture[];
  current: CurrentOccupant | null;
}

export interface TitleSummary {
  library: BackupLibrary;
  title: string;
  capture_count: number;
  total_size: number;
  latest_captured_at: string;
}

export interface SeasonSummary {
  season_number: number | null;
  slot_count: number;
  capture_count: number;
  total_size: number;
}

/** One file's worth of restore, resolved before anything runs. */
export interface RestoreOperation {
  relative_path: string;
  target: string;
  /** The library file this would displace, or null when the slot is empty. */
  replaces: string | null;
  replaces_size: number;
  file_size: number;
  is_media: boolean;
  display: string;
}

export interface RestorePlan {
  capture_id: string;
  slot_display: string;
  library: string;
  target_dir: string;
  operations: RestoreOperation[];
  warnings: string[];
  /** Set when the restore cannot proceed at all, and says why. */
  blocked: string | null;
  total_size: number;
  replaces_count: number;
  transfer_id?: string;
  /**
   * True when the server is in test mode and the restore only rehearsed. The
   * result message says so too; this is what stops the interface dressing a
   * rehearsal up as a success.
   */
  dry_run?: boolean;
}

export interface RetentionRule {
  enabled: boolean;
  keep: number;
  grace_hours: number;
  /** False when there is no database store, so the rule is env-file only. */
  editable?: boolean;
}

/** One version a deletion would remove. */
export interface DeleteCandidate {
  capture_id: string;
  display: string;
  captured_at: string;
  total_size: number;
  file_count: number;
  pinned: boolean;
  /** Relative to the backup base — what the index stores. */
  capture_path: string;
  /** The absolute folder on the backup disk, when the server could resolve it. */
  capture_dir: string | null;
  /**
   * The files this version holds. Populated for the versions the dialog
   * actually lists; beyond that the server sends an empty list rather than
   * reading file rows nobody will see. `DeletePreview.detailed` says how many.
   *
   * Optional because the field is newer than the endpoint: a server that has
   * not been restarted answers without it, and a confirmation dialog for a
   * deletion with no undo must degrade to fewer facts rather than to a crash.
   */
  files?: HistoryFile[];
}

export interface DeletePreview {
  captures: DeleteCandidate[];
  count: number;
  total_size: number;
  /** Held back because they are pinned. Reported, never silently absorbed. */
  skipped_pinned: number;
  /** How many candidates carry their file paths. */
  detailed?: number;
}

export interface DeleteResult {
  deleted: string[];
  deleted_count: number;
  reclaimed: number;
  skipped_pinned: number;
  errors: string[];
  message: string;
}

export type SlotSort = "recent" | "size";

export interface DiskUsage {
  total: number;
  used: number;
  free: number;
  percent_used: number;
}

export interface BackupTotals {
  capture_count: number;
  total_size: number;
  file_count: number;
  pinned_count: number;
  unsorted_count: number;
  slot_count: number;
}

export interface BackupsOverview {
  configured: boolean;
  backup_path_set: boolean;
  totals: BackupTotals;
  disk: DiskUsage | null;
  retention: RetentionRule;
  libraries: Array<{
    library: BackupLibrary;
    title_count: number;
    capture_count: number;
    total_size: number;
  }>;
  /** Old per-transfer folders still awaiting migration. */
  legacy_folders: number;
}

export interface PruneCandidate {
  capture_id: string;
  slot_key: string;
  display: string;
  captured_at: string;
  total_size: number;
  capture_path: string;
}

export interface RetentionResult {
  keep: number;
  grace_hours: number;
  applied: boolean;
  candidates: PruneCandidate[];
  candidate_count: number;
  candidate_size: number;
  deleted: string[];
  deleted_count: number;
  reclaimed: number;
  errors: string[];
}

export interface MigrationMove {
  source: string;
  library: string;
  title: string;
  slot: string | null;
  display: string;
  target: string;
  size: number;
  identified: boolean;
}

export interface MigrationReport {
  applied: boolean;
  folders_seen: number;
  empty_folder_count: number;
  empty_folders: string[];
  /** Skipped because something wrote to them recently — likely another instance. */
  active_folder_count: number;
  active_folders: string[];
  move_count: number;
  moves: MigrationMove[];
  unidentified_count: number;
  unidentified: MigrationMove[];
  total_size: number;
  moved_count: number;
  removed_folders: number;
  warnings: string[];
  errors: string[];
  /** Set when migration must wait — a transfer is still writing to the disk. */
  blocked?: string | null;
}

export interface RebuildResult {
  indexed: number;
  files: number;
  total_size: number;
  unsorted: number;
  removed: number;
  /** Capture folders renamed because another folder already had that id. */
  repaired: number;
  errors: string[];
  message: string;
}

/* ===== History =====
 *
 * What the Backups feature did, read back from the activity trail. The server
 * describes every version it removes BEFORE removing it, because afterwards
 * there is nothing left to read — so these entries are the only record of a
 * file that no longer exists anywhere.
 */

/** One file inside a version an entry describes. */
export interface HistoryFile {
  name: string;
  relative_path: string;
  /** Where it lived in the media library. Absent for index-rebuilt versions. */
  original_path: string | null;
  /** Where the kept copy sat on the backup disk. */
  backup_path: string | null;
  file_size: number;
  is_media: boolean;
}

/** One stored version an entry created or removed. */
export interface HistoryItem {
  capture_id: string;
  display: string;
  library: BackupLibrary | null;
  title: string | null;
  season_number: number | null;
  episode_number: number | null;
  release_year: string | null;
  slot_key: string | null;
  kind: CaptureKind | null;
  reason: CaptureReason | string | null;
  captured_at: string | null;
  pinned: boolean;
  total_size: number;
  file_count: number;
  capture_path: string;
  /** The absolute folder on the backup disk, when the server could resolve it. */
  capture_dir: string | null;
  /**
   * Absent on entries recorded before deletions described what they removed.
   * These come out of a database that holds every shape the trail has ever
   * had, so nothing here may be assumed present.
   */
  files?: HistoryFile[];
  files_omitted?: number;
}

export interface HistoryDetail {
  /** True when nothing and nobody asked for it — the retention sweep. */
  automatic?: boolean;
  items?: HistoryItem[];
  /** Items beyond the recorded cap. Counted, never dropped silently. */
  omitted?: number;
  titles?: string[];
  deleted_count?: number;
  reclaimed_bytes?: number;
  created_count?: number;
  kept_bytes?: number;
  keep?: number;
  grace_hours?: number;
  skipped_pinned?: number;
  by_slot?: boolean;
  legacy_endpoint?: boolean;
}

/** The filter chips above the history list. */
export type HistoryLens = "all" | "removed" | "kept" | "restored";

/** Which actions each lens covers. Empty means every backup action. */
export const HISTORY_LENS_ACTIONS: Record<HistoryLens, string[]> = {
  all: [],
  removed: [
    "backup.retention_apply",
    "backup.delete",
    "backup.bulk_delete",
    "backup.clear_unsorted",
  ],
  kept: ["backup.capture"],
  restored: ["backup.restore"],
};

export const HISTORY_ACTION_LABELS: Record<string, string> = {
  "backup.capture": "Kept",
  "backup.restore": "Restored",
  "backup.delete": "Deleted",
  "backup.bulk_delete": "Deleted",
  "backup.clear_unsorted": "Cleared",
  "backup.retention_apply": "Auto-deleted",
  "backup.retention_save": "Rule changed",
  "backup.pin": "Pinned",
  "backup.unpin": "Unpinned",
  "backup.rebuild_index": "Reindexed",
  "backup.migrate": "Migrated",
};

/** Actions that destroyed something. Coloured and worded as such. */
export const HISTORY_DESTRUCTIVE = new Set([
  "backup.delete",
  "backup.bulk_delete",
  "backup.clear_unsorted",
  "backup.retention_apply",
]);

export const LIBRARY_LABELS: Record<BackupLibrary, string> = {
  movies: "Movies",
  shows: "TV Shows",
  anime: "Anime",
};

/**
 * Why a stored version exists.
 *
 * `restore_swap` is the one that matters most: it is the copy a restore
 * displaced, so it is what you restore to undo that restore. It was previously
 * never produced — every capture came back as `sync_replace` — which left the
 * version somebody is most likely to want described as an ordinary sync backup.
 *
 * `sync_delete` is listed but is not produced yet. A file removed by a sync and
 * one replaced by a sync both arrive the same way, and telling them apart after
 * the fact would mislabel an upgrade that renamed its file as a deletion. Better
 * to say "replaced" than to guess wrongly.
 */
export const REASON_LABELS: Record<string, string> = {
  sync_replace: "Replaced by a sync",
  sync_delete: "Removed by a sync",
  restore_swap: "Replaced by a restore",
  explore_prune: "Removed from Explore",
  explore_repair: "Set aside by a repair",
};

/** "Season 01", "Specials", or nothing for a movie. */
export function seasonLabel(season: number | null | undefined): string | null {
  if (season === null || season === undefined) return null;
  return season === 0 ? "Specials" : `Season ${String(season).padStart(2, "0")}`;
}
