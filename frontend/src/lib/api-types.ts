export type SyncStatusType = 'SYNCED' | 'OUT_OF_SYNC' | 'NO_INFO' | 'LOADING' | 'PARTIAL_SYNC'
export type TransferStatus = 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type WebhookStatus =
  | 'pending'
  | 'READY_FOR_TRANSFER'
  | 'QUEUED_SLOT'
  | 'QUEUED_PATH'
  | 'syncing'
  | 'completed'
  | 'failed'
  | 'MANUAL_SYNC_REQUIRED'

export interface MediaType {
  id: 'movies' | 'tvshows' | 'anime' | string
  name: string
  path: string
}

export interface FolderMetadata {
  name: string
  modification_time: number
}

export interface FolderSyncStatus {
  status: SyncStatusType
  type: 'movie' | 'series' | 'season' | 'unknown'
  modification_time?: number
  seasons?: Array<{
    name: string
    status: SyncStatusType | string
    modification_time: number
  }>
  most_recent_season?: {
    name: string
    status: SyncStatusType | string
  } | null
}

export interface DryRunResult {
  safe_to_sync: boolean
  reason?: string
  deleted_count?: number
  incoming_count?: number
  server_file_count?: number
  local_file_count?: number
  deleted_files?: string[]
  incoming_files?: string[]
  raw_output?: string
}

export interface Transfer {
  id: string
  status: TransferStatus | string
  progress: string
  media_type: string
  folder_name: string
  season_name?: string
  parsed_title?: string
  parsed_season?: string
  operation_type: 'folder' | 'file' | string
  source_path: string
  dest_path: string
  start_time?: string
  end_time?: string
  created_at?: string
  log_count: number
  logs?: string[]
  rsync_process_id?: number
}

export interface QueueStatus {
  running_count: number
  queued_count: number
  max_concurrent: number
  available_slots?: number
  running_transfer_ids?: string[]
  queued_transfer_ids?: string[]
  active_destinations?: string[]
}

export interface WebhookNotification {
  id?: number | string
  notification_id: string
  media_type: 'movie' | 'tvshows' | 'anime' | 'series' | string
  display_title: string
  status: WebhookStatus | string
  created_at: string
  completed_at?: string
  poster_url?: string
  title?: string
  year?: number
  folder_path?: string
  file_path?: string
  quality?: string
  release_size?: number
  release_title?: string
  requested_by?: string
  series_title?: string
  series_title_slug?: string
  season_number?: number
  episode_count?: number
  dry_run_result?: unknown
  dry_run_performed_at?: string
}

export interface RenameNotification {
  notification_id: string
  media_type: 'tvshows' | 'anime' | string
  series_title: string
  status: 'pending' | 'completed' | 'partial' | 'failed' | string
  total_files: number
  success_count: number
  failed_count: number
  created_at?: string
  processed_at?: string
  renamed_files?: Array<{
    previous_name?: string
    new_name?: string
    status?: string
    message?: string
    error?: string
  }>
}

export interface AppConfig {
  REMOTE_IP?: string
  REMOTE_USER?: string
  REMOTE_PASSWORD?: string
  SSH_KEY_PATH?: string
  MOVIE_PATH?: string
  TVSHOW_PATH?: string
  ANIME_PATH?: string
  BACKUP_PATH?: string
  MOVIE_DEST_PATH?: string
  TVSHOW_DEST_PATH?: string
  ANIME_DEST_PATH?: string
  DISK_PATH_1?: string
  DISK_PATH_2?: string
  DISK_PATH_3?: string
  DISK_API_ENDPOINT?: string
  DISK_API_TOKEN?: string
  WEBSOCKET_TIMEOUT_MINUTES?: string | number
  [key: string]: string | number | undefined
}

export interface SSHConfig {
  host: string
  username: string
  password: string
  key_path: string
}

export interface DiskUsage {
  path: string
  filesystem?: string
  total_size?: string
  used_size?: string
  available_size?: string
  usage_percent?: number
  mount_point?: string
  available: boolean
  error?: string
}

export interface RemoteStorageInfo {
  free_storage_bytes: number
  free_storage_gb: number
  total_storage_value: number
  total_storage_unit: string
  used_storage_value: number
  used_storage_unit: string
  usage_percent: number
  total_display: string
  used_display: string
  free_display: string
  available: boolean
}
