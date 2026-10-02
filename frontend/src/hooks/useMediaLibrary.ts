import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

/**
 * The library and history views — read-only, in both directions.
 *
 * Everything here reaches Sonarr or Radarr through adapters that refuse any
 * verb but GET, so no screen built on these hooks can change anything on the
 * other side. The one mutation below writes to DragonCP's own index; the call
 * it makes outward is still a read.
 */

/** One season, as the service holds it and as we hold it. */
export interface LibrarySeason {
  season_number: number;
  /** Season 0. Left out of the sync judgement — most libraries skip specials. */
  specials: boolean;
  monitored: boolean;
  episode_count: number;
  episode_file_count: number;
  /** Media files found in this season's folder on our disk. */
  files_here: number;
  synced_here: boolean;
  counts_towards_state: boolean;
}

/**
 * `sync_state` is the whole point of this view:
 *
 *   synced    the service holds files, and so do we
 *   partial   it holds files for seasons we do not have
 *   never     it holds files and we have none of them
 *   no_files  it lists the title but holds no files — nothing to sync
 *   orphan    we hold files for a title it no longer lists
 *   unknown   the disk could not be read, so no honest answer is possible
 *
 * `no_files` matters more than it looks. Of 129 series in one real Sonarr, 99
 * had no files at all — shows added before they air. Judging those as "never
 * synced" turned two genuine gaps into a list of 101 warnings.
 *
 * Presence is read from the disk, never from the transfer log: files put there
 * by hand, restored from a backup, or synced by another instance sharing the
 * disk are present either way.
 */
export type SyncState = "synced" | "partial" | "never" | "no_files" | "orphan" | "unknown";

export interface LibraryItem {
  external_id: string;
  service_item_id: number | null;
  title: string | null;
  year: number | null;
  media_type: string | null;
  monitored: boolean;
  service_status: string | null;
  poster: string;
  present_in_service: boolean;
  /** Whether the service holds any files for it. Titles without are not judged. */
  service_has_files: boolean;
  sync_state: SyncState;
  local_folder: string | null;
  /** Read from the filesystem, not from the transfer log. */
  present_locally: boolean;
  local_file_count: number;
  transfers: number;
  last_synced_at: string | null;
  service_episode_count: number;
  service_episode_file_count: number;
  service_size_on_disk: number;
  seasons: LibrarySeason[];
  seasons_synced_here: number[];
}

export interface LibraryView {
  success: boolean;
  source: string;
  /** Whether the service answered, or this is the stored index alone. */
  live: boolean;
  read_only: boolean;
  test_mode: boolean;
  total: number;
  counts: Partial<Record<SyncState, number>>;
  items: LibraryItem[];
}

export interface HistoryRecord {
  id: number;
  event_type: string;
  date: string;
  source_title: string | null;
  quality: string | null;
  service_item_id: number | null;
  title: string | null;
  external_id: string | null;
  /** Whether DragonCP knows this title at all. */
  known_here: boolean;
}

export interface HistoryView {
  success: boolean;
  source: string;
  live: boolean;
  read_only: boolean;
  records: HistoryRecord[];
  page: number;
  page_size: number;
  total: number;
  message?: string;
}

export function useLibrary(source: string, enabled = true) {
  return useQuery({
    queryKey: ["library", source],
    queryFn: async () => {
      const response = await api.get<LibraryView>(`/library/${source}`);
      return response.data;
    },
    enabled,
    // The catalogue changes when someone adds a show, not by the second.
    staleTime: 60_000,
  });
}

export function useLibraryHistory(source: string, page: number, pageSize = 50, enabled = true) {
  return useQuery({
    queryKey: ["library", source, "history", page, pageSize],
    queryFn: async () => {
      const response = await api.get<HistoryView>(
        `/library/${source}/history?page=${page}&page_size=${pageSize}`
      );
      return response.data;
    },
    enabled,
    // Keeps the table on screen while the next page loads, instead of
    // collapsing to a spinner and losing the reader's place.
    placeholderData: (previous) => previous,
  });
}

/**
 * Pull the service's whole catalogue into the index.
 *
 * This is how titles that have never been synced appear at all: nothing else
 * in DragonCP ever hears about a series until a notification arrives for it,
 * so without this the view can only ever show what already went wrong once.
 */
export function useRefreshLibrary(source: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const response = await api.post<{ success: boolean; titles_seen: number }>(
        `/library/${source}/refresh`
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library", source] });
    },
  });
}

/**
 * One row waiting on the service.
 *
 * `verdict` is decided server-side by the same classifier the sync gate uses,
 * so what this screen says and what the scheduler does cannot drift apart.
 */
export interface QueueRow {
  id: number;
  title: string;
  release: string | null;
  service_item_id: number | null;
  external_id: string | null;
  known_here: boolean;
  /** The service cannot say which title this download is for. */
  unattributed: boolean;
  season_number: number | null;
  state: string | null;
  status: string | null;
  /** downloading | importing | blocked | stalled | stale | imported | failed | unrecognised */
  verdict: string;
  /** Whether this row is currently holding an automatic sync back. */
  holds_sync: boolean;
  /** The service's own sentence about it, where it left one. */
  why: string;
  progress: number;
  size: number;
  size_left: number;
  time_left: string | null;
  estimated_completion: string | null;
  download_client: string | null;
  indexer: string | null;
  protocol: string | null;
  error_message: string;
  added: string | null;
  age_hours: number | null;
  needs_attention: boolean;
}

export interface QueueView {
  success: boolean;
  source: string;
  live: boolean;
  read_only: boolean;
  rows: QueueRow[];
  counts: Record<string, number>;
  total: number;
  needing_attention: number;
  holding_a_sync: number;
  message?: string;
}

export function useLibraryQueue(source: string, enabled = true) {
  return useQuery({
    queryKey: ["library", source, "queue"],
    queryFn: async () => {
      const response = await api.get<QueueView>(`/library/${source}/queue`);
      return response.data;
    },
    enabled,
    // A queue moves. Short enough to feel live, long enough not to hammer a
    // service that is already having a bad time.
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

/**
 * Fetch one title's gap, because you pressed Sync on it.
 *
 * What to fetch is decided on the server from a fresh look at the service —
 * this page may have been open for hours, and "sync what is missing" has to
 * mean missing now. A 409 comes back when there is nothing to fetch any more,
 * which is a result, not an error.
 */
export function useSyncLibraryItem(source: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (externalId: string) => {
      const response = await api.post<{
        success: boolean;
        error?: string;
        transfers_started?: number;
      }>(`/library/${source}/sync`, { external_id: externalId });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library", source] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}
