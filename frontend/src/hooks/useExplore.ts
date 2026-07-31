import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type {
  ExploreBackupRun,
  ExploreDryRun,
  ExploreHistoryRun,
  ExplorePlan,
  ExploreSeason,
  ExploreTree,
} from "@/lib/explore-types";

/**
 * Explore reads a cached comparison so the page paints instantly and can say
 * when it last checked. `refresh` forces a fresh pass over the remote library —
 * that is the only call that costs the media server anything, which is why it
 * is an explicit action rather than something that happens on focus.
 */
export function useExploreTree(mediaType: string, enabled = true) {
  return useQuery({
    queryKey: ["explore", "tree", mediaType],
    queryFn: async () => {
      const response = await api.get<ExploreTree>(`/explore/tree/${mediaType}`);
      return response.data;
    },
    enabled: enabled && !!mediaType,
    staleTime: 60_000,
  });
}

export function useExploreRefresh(mediaType: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const response = await api.get<ExploreTree>(`/explore/tree/${mediaType}?refresh=1`);
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["explore", "tree", mediaType], data);
      queryClient.invalidateQueries({ queryKey: ["explore", "series", mediaType] });
      queryClient.invalidateQueries({ queryKey: ["explore", "season", mediaType] });
    },
  });
}

// There is no hook for GET /explore/series: the tree already carries every
// series' seasons, which is what lets several stay expanded at once. The
// endpoint stays as the middle step of the API and is covered by its tests.

export function useExploreSeason(mediaType: string, folder: string | null, season: string | null) {
  return useQuery({
    queryKey: ["explore", "season", mediaType, folder, season],
    queryFn: async () => {
      const response = await api.get<{ season: ExploreSeason }>(
        `/explore/season/${mediaType}/${encodeURIComponent(folder!)}/${encodeURIComponent(season!)}`
      );
      return response.data.season;
    },
    enabled: !!mediaType && !!folder && !!season,
  });
}

export function useExploreHistory(
  mediaType: string,
  folder: string | null,
  season?: string | null
) {
  return useQuery({
    queryKey: ["explore", "history", mediaType, folder, season ?? null],
    queryFn: async () => {
      const response = await api.get<{ runs: ExploreHistoryRun[] }>(
        `/explore/history/${mediaType}/${encodeURIComponent(folder!)}`,
        { params: season ? { season } : undefined }
      );
      return response.data.runs;
    },
    enabled: !!mediaType && !!folder,
  });
}

/**
 * Copies moved aside by an earlier sync for this series, or one of its seasons.
 *
 * Read-only here. Restoring lives on the Backups page, which owns matching the
 * saved copy back to a destination file and confirming the replacement.
 */
export function useExploreBackups(
  mediaType: string,
  folder: string | null,
  season?: string | null
) {
  return useQuery({
    queryKey: ["explore", "backups", mediaType, folder, season ?? null],
    queryFn: async () => {
      const response = await api.get<{ backups: ExploreBackupRun[] }>(
        `/explore/backups/${mediaType}/${encodeURIComponent(folder!)}`,
        { params: season ? { season } : undefined }
      );
      return response.data.backups;
    },
    enabled: !!mediaType && !!folder,
  });
}

export interface PlanRequest {
  media_type: string;
  operation: "sync_series" | "sync_season" | "sync_seasons" | "download" | "replace";
  folder: string;
  season?: string | null;
  /** Several ticked seasons, reconciled as one plan and one transfer. */
  seasons?: string[];
  codes?: string[];
  include_removals?: boolean;
}

/**
 * Ask the server what an operation would do. The server computes and stores the
 * plan and hands back its id; the client never describes the work itself.
 */
export function useExplorePlan() {
  return useMutation({
    mutationFn: async (request: PlanRequest) => {
      const response = await api.post<{ plan: ExplorePlan }>("/explore/plan", request);
      return response.data.plan;
    },
  });
}

/**
 * Rehearse a plan: rsync is asked what it would do, with `--dry-run`, and its
 * answer is reported back. Nothing is moved and the plan stays runnable, so
 * this can be done as many times as you like before deciding.
 */
export function useExploreDryRun() {
  return useMutation({
    mutationFn: async (planId: string) => {
      const response = await api.post<ExploreDryRun>("/explore/dry-run", { plan_id: planId });
      return response.data;
    },
  });
}

/** Execute a plan by id. Anything that failed its checks needs the typed name. */
export function useExploreExecute(mediaType: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { plan_id: string; override?: boolean; confirm_text?: string }) => {
      const response = await api.post<{ message: string; transfer_id: string | null }>(
        "/explore/transfer",
        body
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
      queryClient.invalidateQueries({ queryKey: ["explore", "history"] });
      // A run that replaces or removes anything creates a backup, so the
      // panel listing them is stale the moment one starts.
      queryClient.invalidateQueries({ queryKey: ["explore", "backups"] });
      queryClient.invalidateQueries({ queryKey: ["explore", "tree", mediaType] });
    },
  });
}

export interface ExploreLibrary {
  id: string;
  label: string;
  remote_path: string;
  local_path: string;
  configured: boolean;
  local_exists: boolean;
  checked_at: string | null;
}

/** The configured libraries — used by the switcher and the remote path readout. */
export function useExploreLibraries() {
  return useQuery({
    queryKey: ["explore", "libraries"],
    queryFn: async () => {
      const response = await api.get<{ libraries: ExploreLibrary[] }>("/explore/libraries");
      return response.data.libraries;
    },
    staleTime: 5 * 60_000,
  });
}
