import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

/**
 * The library and history views — read-only, in both directions.
 *
 * Everything here reaches Sonarr or Radarr through adapters that refuse any
 * verb but GET, so no screen built on these hooks can change anything on the
 * other side. The mutations below write to DragonCP's own index, or start a
 * sync on this side; the calls they make outward are still reads.
 */

/** One season, as the service holds it and as we hold it. */
export interface LibrarySeason {
  season_number: number;
  /** Season 0. Left out of the sync judgement — most libraries skip specials. */
  specials: boolean;
  monitored: boolean;
  episode_count: number;
  /** Episodes the service holds a file for (a double episode counts twice). */
  episode_file_count: number;
  /** Media files found in this season's folder on our disk. */
  files_here: number;
  /** Distinct episodes here, read from the file names. */
  episodes_here: number;
  folder_here: string | null;
  synced_here: boolean;
  counts_towards_state: boolean;
}

/**
 * What the list calls a title.
 *
 *   out_of_sync  something the service holds is not here, or differs
 *   in_sync      everything the service holds is here
 *   kept_here    in sync, and more is kept here than the service still holds —
 *                the media server cleaned up after a sync; shown as in sync
 *   never        the service holds files and none are here
 *   no_files     the service lists it but holds no files — nothing to sync
 *   orphan       we hold files for a title it no longer lists
 *   unknown      the disk could not be read, so no honest answer is possible
 *
 * The list is worked out from three cheap reads and no call per title; a title
 * opened in the detail view within ten minutes shows that exact answer instead
 * (`state_exact`).
 */
export type LibraryState =
  | "out_of_sync"
  | "needs_repair"
  | "in_sync"
  | "kept_here"
  | "never"
  | "no_files"
  | "orphan"
  | "unknown";

/** Why a title is out of sync — the list words its sentence from these. */
export interface LibraryAttention {
  kind:
    | "new_import"
    | "new_file"
    | "short"
    | "season_not_here"
    | "not_matching"
    | "missing"
    | "different"
    | "nested";
  season_number: number | null;
  count: number;
  theirs?: number;
  ours?: number;
  episodes?: string[];
  imported_at?: string | null;
  quality?: string | null;
  size?: number | null;
  /** For "nested": where each stranded file sits now. */
  paths?: string[];
}

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
  sync_state: LibraryState;
  /** One plain sentence; the UI prefers its own wording from `attention`. */
  state_reason: string;
  /** True when the state came from a file-by-file comparison. */
  state_exact: boolean;
  attention: LibraryAttention[];
  /** Episodes kept here beyond what the service still holds. */
  kept_here_count: number;
  /** The service's latest import for it in the last two weeks. */
  last_import_at: string | null;
  local_folder: string | null;
  /** Read from the filesystem, not from the transfer log. */
  present_locally: boolean;
  local_file_count: number;
  transfers: number;
  last_synced_at: string | null;
  service_episode_count: number;
  service_episode_file_count: number;
  service_size_on_disk: number;
  /** The card's counts line: the service's episodes with a file, Specials left out. */
  service_files_counted: number;
  /** Distinct episodes here (films: media files here), Specials left out. */
  episodes_here: number;
  /** Films only. */
  service_file_size?: number;
  local_file_size?: number;
  quality?: string | null;
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
  /** Whether the service's recent imports could be read for the verdicts. */
  history_checked?: boolean;
  total: number;
  counts: Partial<Record<LibraryState, number>>;
  items: LibraryItem[];
}

// -- one title, episode by episode --------------------------------------------

/**
 * One episode's state against the service:
 *
 *   in_sync         the service has a file and the same file (same size) is here
 *   different       both have it, sizes differ — an upgrade there, or another release
 *   missing_here    the service has a file, nothing here: needs syncing
 *   only_here       here, the service has no file — normal after its cleanup
 *   not_downloaded  neither has it, aired or not
 */
export type EpisodeState =
  "missing_here" | "different" | "nested" | "in_sync" | "only_here" | "not_downloaded";

export type EpisodeCounts = Record<EpisodeState, number>;

export interface ServiceFile {
  name: string;
  relative_path: string;
  size: number;
  quality: string | null;
  custom_formats: string[];
  custom_format_score: number | null;
  release_group: string | null;
  date_added: string | null;
}

export interface LocalFile {
  name: string;
  relative_path: string;
  size: number;
  /** For a file holding several episodes: every code it covers. */
  covers: string[];
  /** In a folder below the season (or film) folder: here, but not visible to a media server. */
  nested?: boolean;
}

export interface TitleEpisode {
  code: string;
  season_number: number;
  episode_number: number | null;
  absolute_episode_number: number | null;
  title: string | null;
  air_date: string | null;
  air_date_utc: string | null;
  monitored: boolean;
  state: EpisodeState;
  service_file: ServiceFile | null;
  local_file: LocalFile | null;
  /** Further files here holding the same episode. */
  local_duplicates: number;
}

export interface TitleSeason {
  season_number: number;
  specials: boolean;
  counts_towards_state: boolean;
  monitored: boolean;
  folder_here: string | null;
  /** The season's folder on the media server, read from where its files sit. */
  service_folder: string | null;
  /** What Explore calls this season, for a link straight to it. */
  explore_season: string;
  counts: EpisodeCounts;
  state: string;
  service_file_count: number;
  files_here: number;
  episodes_here: number;
  /** Files here a whole-folder sync of this season would remove. */
  local_only_files: number;
  /** Every media file of the season in a nested folder, by path. */
  nested_here?: string[];
  episodes: TitleEpisode[];
  unidentified_here: LocalFile[];
  last_synced_at: string | null;
}

export interface TitleMovie {
  state: EpisodeState;
  service_file: ServiceFile | null;
  local_file: LocalFile | null;
  other_files_here: LocalFile[];
}

export interface TitleHeader {
  external_id: string;
  service_item_id: number | null;
  title: string | null;
  year: number | null;
  poster: string;
  status: string | null;
  network: string | null;
  monitored: boolean;
  service_path: string;
  local_folder: string | null;
  media_type: string | null;
}

export interface TitleDetail {
  success: boolean;
  source: string;
  external_id: string;
  /** False when the service could not be asked; `message` says why. */
  live: boolean;
  found: boolean;
  message?: string;
  title?: TitleHeader;
  state?: LibraryState;
  summary?: string;
  counts?: EpisodeCounts;
  seasons?: TitleSeason[];
  movie?: TitleMovie | null;
  attention?: LibraryAttention[];
  kept_here_count?: number;
  /** Media files here in a nested folder (counted seasons, or the film). */
  nested_files?: number;
  /** Episode files here still named TBA, which Explore's Rename can give a title. */
  placeholder_count?: number;
  last_synced_at?: string | null;
  actions?: {
    /** The title's Sync, offered only where a whole-folder sync removes nothing. */
    sync: { offered: boolean; seasons: number[]; reason: string };
    /** Where Explore opens to fetch only what is missing. */
    explore: {
      media_type: string;
      series: string | null;
      season: string | null;
      /** The first season with a nested file: where "Repair in Explore" opens. */
      nested_season?: string | null;
    } | null;
  };
  computed_at?: string;
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

/**
 * One title, compared episode by episode.
 *
 * Reading it also brings that title's card up to date in the list already on
 * screen: the server keeps this exact answer for the list for ten minutes, and
 * the card should not go on saying something the panel beside it contradicts.
 */
export function useLibraryTitle(source: string, externalId: string | null) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["library", source, "title", externalId],
    queryFn: async () => {
      const response = await api.get<TitleDetail>(`/library/${source}/${externalId}`);
      const detail = response.data;
      if (detail.live && detail.state) {
        queryClient.setQueryData<LibraryView>(["library", source], (view) =>
          view
            ? {
                ...view,
                items: view.items.map((item) =>
                  item.external_id === externalId
                    ? {
                        ...item,
                        sync_state: detail.state ?? item.sync_state,
                        state_reason: detail.summary ?? item.state_reason,
                        state_exact: true,
                        attention: detail.attention ?? item.attention,
                        kept_here_count: detail.kept_here_count ?? item.kept_here_count,
                      }
                    : item
                ),
              }
            : view
        );
      }
      return detail;
    },
    enabled: Boolean(externalId),
    staleTime: 30_000,
  });
}

/**
 * One entry in a title's history: something the service did, or something
 * DragonCP did about it. `status` is whether it got done; an import's own
 * status is decided on screen from the episode comparison.
 */
export type TitleHistoryStatus = "done" | "not_done" | "failed" | "in_progress" | "info";

export interface TitleHistoryEntry {
  at: string | null;
  /** Who did it: the service (Sonarr, Radarr) or DragonCP. */
  side: "service" | "dragoncp";
  /** imported, grabbed, deleted, failed, renamed, ignored, other; sync or transfer for DragonCP. */
  kind: string;
  title: string;
  detail: string;
  status: TitleHistoryStatus;
  episodes: string[];
  run_id?: string | null;
  transfer_id?: string | null;
  state?: string;
  /** For DragonCP's entries: the season folder synced, or null for the whole title. */
  season?: string | null;
}

export interface TitleHistory {
  success: boolean;
  source: string;
  external_id: string;
  /** False when the service could not be asked: only DragonCP's side is listed. */
  live: boolean;
  message?: string;
  /** Every entry found; `entries` holds the newest of them. */
  total: number;
  entries: TitleHistoryEntry[];
}

/** What happened to one title, on both sides, read when its History tab opens. */
export function useLibraryTitleHistory(source: string, externalId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["library", source, "title", externalId, "history"],
    queryFn: async () => {
      const response = await api.get<TitleHistory>(`/library/${source}/${externalId}/history`);
      return response.data;
    },
    enabled: Boolean(externalId) && enabled,
    staleTime: 30_000,
  });
}

/** Where a history row came from, in the words the History tab filters by. */
export type HistoryEvent =
  "imported" | "grabbed" | "deleted" | "failed" | "renamed" | "ignored" | "other";

export interface HistoryRecord {
  id: number;
  /** The service's own event name. */
  event_type: string;
  event: HistoryEvent;
  event_label: string;
  date: string;
  /** The release name. */
  source_title: string | null;
  quality: string | null;
  custom_formats: string[];
  custom_format_score: number | null;
  service_item_id: number | null;
  title: string | null;
  year: number | null;
  /** Opens the title's detail view; set even for titles DragonCP has not recorded. */
  external_id: string | null;
  /** Whether DragonCP knows this title at all. */
  known_here: boolean;
  season_number: number | null;
  episode_number: number | null;
  /** "S01E08". */
  episode_code: string | null;
  /** "1x08", as Sonarr prints it. */
  episode_label: string | null;
  episode_title: string | null;
  absolute_episode_number: number | null;
  download_client: string | null;
  indexer: string | null;
  release_group: string | null;
  size: number | null;
  /** Why it was deleted, why it failed, or what it was renamed from. */
  reason: string | null;
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
  event: string;
  message?: string;
}

export function useLibraryHistory(
  source: string,
  page: number,
  pageSize = 50,
  event = "all",
  enabled = true
) {
  return useQuery({
    queryKey: ["library", source, "history", page, pageSize, event],
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (event !== "all") params.set("event", event);
      const response = await api.get<HistoryView>(`/library/${source}/history?${params}`);
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
 * `status_label` / `status_detail` / `tone` are that verdict in plain words.
 */
export interface QueueRow {
  id: number;
  title: string;
  year: number | null;
  release: string | null;
  service_item_id: number | null;
  external_id: string | null;
  known_here: boolean;
  /** The service cannot say which title this download is for. */
  unattributed: boolean;
  season_number: number | null;
  episode_number: number | null;
  episode_code: string | null;
  episode_title: string | null;
  quality: string | null;
  custom_formats: string[];
  custom_format_score: number | null;
  state: string | null;
  status: string | null;
  client_status: string | null;
  /** downloading | importing | blocked | stalled | stale | imported | failed | unrecognised */
  verdict: string;
  /** Whether this row is currently holding an automatic sync back. */
  holds_sync: boolean;
  /** The service's own sentence about it, where it left one. */
  why: string;
  status_label: string;
  status_detail: string;
  status_text: string;
  tone: "ok" | "warn" | "crit" | "brand" | "muted";
  progress: number;
  size: number;
  size_left: number;
  time_left: string | null;
  seconds_left: number | null;
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

export interface LibrarySyncResult {
  success: boolean;
  error?: string;
  transfers_started?: number;
  runs?: Array<{ ok: boolean; run_id: string | null; action: string; message: string }>;
}

/**
 * Fetch one title's gap, because you pressed Sync on it.
 *
 * What to fetch is decided on the server from a fresh look at the service —
 * this page may have been open for hours, and "sync what is missing" has to
 * mean missing now. A 409 comes back when there is nothing to fetch any more,
 * which is a result, not an error, so it resolves with the server's own
 * sentence instead of throwing it away.
 */
export function useSyncLibraryItem(source: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (externalId: string) => {
      const response = await api.post<LibrarySyncResult>(
        `/library/${source}/sync`,
        { external_id: externalId },
        { validateStatus: (status) => status === 200 || status === 409 }
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library", source] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
      queryClient.invalidateQueries({ queryKey: ["sync"] });
    },
  });
}
