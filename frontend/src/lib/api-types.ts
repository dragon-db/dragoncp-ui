export type SyncStatusType = "SYNCED" | "OUT_OF_SYNC" | "NO_INFO" | "LOADING" | "PARTIAL_SYNC";
export type TransferStatus =
  "pending" | "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type WebhookStatus =
  | "pending"
  | "READY_FOR_TRANSFER"
  | "QUEUED_SLOT"
  | "QUEUED_PATH"
  | "syncing"
  | "completed"
  | "failed"
  | "MANUAL_SYNC_REQUIRED";

export interface MediaType {
  id: "movies" | "tvshows" | "anime" | string;
  name: string;
  path: string;
}

export interface FolderMetadata {
  name: string;
  modification_time: number;
}

export interface FolderSyncStatus {
  status: SyncStatusType;
  type: "movie" | "series" | "season" | "unknown";
  modification_time?: number;
  seasons?: Array<{
    name: string;
    status: SyncStatusType | string;
    modification_time: number;
  }>;
  most_recent_season?: {
    name: string;
    status: SyncStatusType | string;
  } | null;
}

export interface DryRunResult {
  safe_to_sync: boolean;
  reason?: string;
  deleted_count?: number;
  incoming_count?: number;
  server_file_count?: number;
  local_file_count?: number;
  deleted_files?: string[];
  incoming_files?: string[];
  raw_output?: string;
}

export interface Transfer {
  id: string;
  status: TransferStatus | string;
  progress: string;
  media_type: string;
  folder_name: string;
  season_name?: string;
  parsed_title?: string;
  parsed_season?: string;
  operation_type: "folder" | "file" | string;
  source_path: string;
  dest_path: string;
  start_time?: string;
  end_time?: string;
  paused_at?: string | null;
  created_at?: string;
  /** Why a queued transfer is waiting: a free slot, or the destination path. */
  queue_reason?: "slot" | "path" | string | null;
  /** True for transfers created by the simulation tool. */
  is_simulation?: boolean;
  log_count: number;
  logs?: string[];
  rsync_process_id?: number;
  /**
   * Who started this run. `started_by_kind` separates a person from automation;
   * `started_by_account_id` is the stable identity that survives a rename, while
   * `started_by_name` is the name as it read at the time.
   *
   * All three are absent on runs that predate attribution — those show as
   * "unrecorded" rather than being guessed at.
   */
  started_by_kind?: "admin" | "automated" | "system" | null;
  started_by_name?: string | null;
  started_by_account_id?: number | null;
  /** Structured rsync progress, parsed server-side from --info=progress2 output. */
  progress_percent?: number | null;
  bytes_transferred?: number | null;
  total_bytes?: number | null;
  speed_bps?: number | null;
  eta_seconds?: number | null;
}

export interface QueueStatus {
  running_count: number;
  queued_count: number;
  max_concurrent: number;
  available_slots?: number;
  running_transfer_ids?: string[];
  queued_transfer_ids?: string[];
  active_destinations?: string[];
}

/** Episode entry inside a Sonarr webhook payload (`episodes` JSON column). */
export interface WebhookEpisode {
  id?: number;
  episodeNumber?: number;
  seasonNumber?: number;
  title?: string;
  airDate?: string;
  overview?: string;
}

/**
 * The imported media file (`episode_files` JSON column). Its `size` is the real
 * per-episode size — unlike `release_size`, which is the size of the whole grab.
 */
export interface WebhookEpisodeFile {
  id?: number;
  relativePath?: string;
  path?: string;
  quality?: string;
  releaseGroup?: string;
  sceneName?: string;
  size?: number;
  dateAdded?: string;
  languages?: Array<{ id?: number; name?: string }>;
  mediaInfo?: {
    videoCodec?: string;
    audioCodec?: string;
    audioChannels?: number;
    audioLanguages?: string[];
    subtitles?: string[];
    width?: number;
    height?: number;
    videoDynamicRangeType?: string;
  };
}

export interface WebhookNotification {
  id?: number | string;
  notification_id: string;
  /**
   * Episodes this webhook covers. Sonarr fires one webhook per episode, so a
   * season-pack grab produces several notifications that share a release_title
   * and repeat the pack's release_size.
   */
  episodes?: WebhookEpisode[];
  /** Imported file(s) for this webhook — the source of true per-episode size. */
  episode_files?: WebhookEpisodeFile[];
  /** Original Sonarr/Radarr payload as JSON text (holds release.releaseType). */
  raw_webhook_data?: string;
  release_indexer?: string;
  season_path?: string;
  series_path?: string;
  series_id?: number;
  media_type: "movie" | "tvshows" | "anime" | "series" | string;
  display_title: string;
  status: WebhookStatus | string;
  created_at: string;
  completed_at?: string;
  /** Transfer this notification was synced under — the join to `Transfer.id`. */
  transfer_id?: string;
  poster_url?: string;
  title?: string;
  year?: number;
  folder_path?: string;
  file_path?: string;
  quality?: string;
  release_size?: number;
  release_title?: string;
  requested_by?: string;
  series_title?: string;
  series_title_slug?: string;
  season_number?: number;
  episode_count?: number;
  dry_run_result?: unknown;
  dry_run_performed_at?: string;
}

export interface RenameNotification {
  notification_id: string;
  media_type: "tvshows" | "anime" | string;
  series_title: string;
  status: "pending" | "completed" | "partial" | "failed" | string;
  total_files: number;
  success_count: number;
  failed_count: number;
  created_at?: string;
  completed_at?: string;
  renamed_files?: Array<{
    previous_name?: string;
    new_name?: string;
    previous_relative_path?: string;
    new_relative_path?: string;
    status?: string;
    message?: string;
    error?: string;
    local_previous_path?: string | null;
    local_new_path?: string | null;
  }>;
}

export interface RenameVerificationResult {
  notification_id: string;
  series_title: string;
  media_type?: string;
  status: "verified" | "partial" | "failed" | "not_found" | string;
  total_files: number;
  verified_count: number;
  failed_count: number;
  verified_at?: string;
  message: string;
  files: Array<{
    previous_name?: string;
    expected_name?: string;
    local_previous_path?: string | null;
    local_expected_path?: string | null;
    actual_name?: string | null;
    actual_path?: string | null;
    status?: "verified" | "failed" | string;
    message?: string;
  }>;
}

/**
 * Settings live in one of two stores, and the server says which on every row.
 *
 * `env` — set once when the installation was built: where the media lives, how
 * to reach the remote, and everything that is a security boundary. Shown
 * read-only; changing it means editing the file on the server.
 * `db` — changed while running. Saved immediately, shared by every operator and
 * every background job.
 *
 * There used to be a third store, a per-browser session, and it was a trap:
 * background threads never read it, so sixteen settings looked editable and
 * were ignored by the machinery that used them. It is gone.
 */
export type SettingStore = "env" | "db";

export type SettingKind = "text" | "password" | "number" | "boolean" | "path";

export interface SettingDescriptor {
  key: string;
  store: SettingStore;
  group: string;
  label: string;
  description: string;
  kind: SettingKind;
  editable: boolean;
  sensitive: boolean;
  value: string | number | boolean;
  minimum?: number;
  maximum?: number;
  /** DB settings only: nothing saved yet, so the built-in default applies. */
  is_default?: boolean;
}

export interface SettingGroup {
  id: string;
  label: string;
  settings: SettingDescriptor[];
}

export interface SettingsResponse {
  status: string;
  groups: SettingGroup[];
  stores: Record<SettingStore, { label: string; description: string }>;
  /** Present on a save: what was written, and what was refused as env-backed. */
  saved?: string[];
  refused?: string[];
  message?: string;
}

/**
 * The flat key -> value map.
 *
 * Still returned by `/api/config` alongside the grouped payload as a deprecated
 * cutover compatibility shape. New code should use `SettingsResponse` — the
 * flat shape cannot say which store a value came from or whether it can be
 * written.
 */
export interface AppConfig {
  [key: string]: string | number | undefined;
}

export interface SSHConfig {
  host: string;
  username: string;
  password: string;
  key_path: string;
}

export interface SSHConfigResponse {
  host: string;
  username: string;
  key_path: string;
  has_password: boolean;
}

export interface DiskUsage {
  path: string;
  filesystem?: string;
  total_size?: string;
  used_size?: string;
  available_size?: string;
  usage_percent?: number;
  mount_point?: string;
  available: boolean;
  error?: string;
}

export interface RemoteStorageInfo {
  free_storage_bytes: number;
  free_storage_gb: number;
  total_storage_value: number;
  total_storage_unit: string;
  used_storage_value: number;
  used_storage_unit: string;
  usage_percent: number;
  total_display: string;
  used_display: string;
  free_display: string;
  available: boolean;
}
