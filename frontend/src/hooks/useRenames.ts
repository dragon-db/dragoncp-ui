import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "@/lib/api";
import { getSocket } from "@/services/socket";
import type {
  RenameAllPlan,
  RenameLibraryFinished,
  RenamePlan,
  RenameProgress,
  RenameResult,
  TitleProposal,
  TitleStatus,
  TmdbSearch,
} from "@/lib/rename-types";

/** Films have no episode titles, so nothing here runs for them. */
export function hasTitles(mediaType: string): boolean {
  return mediaType === "tvshows" || mediaType === "anime";
}

/**
 * The last title check of every series in a library. A database read: Sonarr
 * is asked only by Check titles, Refresh titles, and the scheduled check when
 * someone has switched it on.
 */
export function useTitleStatus(mediaType: string) {
  return useQuery({
    queryKey: ["explore", "titles", mediaType],
    queryFn: async () => {
      const response = await api.get<{ titles: Record<string, TitleStatus> }>(
        `/explore/titles/${mediaType}`
      );
      return response.data.titles;
    },
    enabled: hasTitles(mediaType),
    staleTime: 60_000,
  });
}

/** What the last check proposed for each file of one season, by its name here. */
export function useSeasonTitles(
  mediaType: string,
  folder: string | null,
  season: string | null,
  enabled: boolean
) {
  return useQuery({
    queryKey: ["explore", "titles", mediaType, folder, season],
    queryFn: async () => {
      const response = await api.get<{ files: Record<string, TitleProposal> }>(
        `/explore/titles/${mediaType}/${encodeURIComponent(folder!)}`,
        { params: season ? { season } : undefined }
      );
      return response.data.files;
    },
    enabled: enabled && hasTitles(mediaType) && !!folder,
    staleTime: 60_000,
  });
}

/**
 * What renaming one series or season would do. Reads Sonarr for that one
 * series, so it is only asked for when the review dialog opens.
 */
export function useRenamePlan(
  mediaType: string,
  folder: string | null,
  season: string | null,
  enabled: boolean
) {
  return useQuery({
    queryKey: ["explore", "rename", mediaType, folder, season],
    queryFn: async () => {
      const response = await api.get<{ plan: RenamePlan }>(
        `/explore/rename/${mediaType}/${encodeURIComponent(folder!)}`,
        { params: season ? { season } : undefined }
      );
      return response.data.plan;
    },
    enabled: enabled && hasTitles(mediaType) && !!folder,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
}

/**
 * Rename what the preview showed. The body quotes each file's path and the new
 * name it was shown; the server rebuilds the plan and renames only those.
 */
export function useRename(mediaType: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      folder: string;
      season?: string | null;
      picks: Array<{ path: string; new_name: string }>;
    }) => {
      const response = await api.post<{ status: string } & RenameResult>(
        `/explore/rename/${mediaType}/${encodeURIComponent(body.folder)}`,
        { season: body.season ?? null, picks: body.picks }
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["explore"] });
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
}

/** Ask Sonarr to fetch fresh titles for one series; it checks again when done. */
export function useRefreshTitles(mediaType: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (folder: string) => {
      const response = await api.post<{ asked_sonarr: boolean; message: string }>(
        `/explore/titles/refresh/${mediaType}/${encodeURIComponent(folder)}`
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["explore", "titles", mediaType] });
    },
  });
}

/** Check one series now, or (no folder) every library in the background. */
export function useCheckTitles(mediaType: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (folder?: string) => {
      const response = await api.post<{ started?: boolean }>("/explore/titles/check", {
        media_type: mediaType,
        ...(folder ? { folder } : {}),
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["explore", "titles", mediaType] });
    },
  });
}

/** What Rename all ready would do, from the last check. Asks Sonarr nothing. */
export function useRenameAllPlan(mediaType: string, enabled: boolean) {
  return useQuery({
    queryKey: ["explore", "rename-all", mediaType],
    queryFn: async () => {
      const response = await api.get<{ plan: RenameAllPlan }>(`/explore/rename-all/${mediaType}`);
      return response.data.plan;
    },
    enabled: enabled && hasTitles(mediaType),
    staleTime: 0,
  });
}

export function useRenameAll(mediaType: string) {
  return useMutation({
    mutationFn: async (folders: string[]) => {
      const response = await api.post<{ started: boolean; total: number }>(
        `/explore/rename-all/${mediaType}`,
        { folders }
      );
      return response.data;
    },
  });
}

export function useTmdbSearch(
  mediaType: string,
  folder: string | null,
  query: string,
  enabled: boolean
) {
  return useQuery({
    queryKey: ["explore", "tmdb", mediaType, folder, query],
    queryFn: async () => {
      const response = await api.get<TmdbSearch>(
        `/explore/tmdb/search/${mediaType}/${encodeURIComponent(folder!)}`,
        { params: query ? { q: query } : undefined }
      );
      return response.data;
    },
    enabled: enabled && !!folder,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useTmdbLink(mediaType: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ folder, tmdbId }: { folder: string; tmdbId: number | null }) => {
      const url = `/explore/tmdb/link/${mediaType}/${encodeURIComponent(folder)}`;
      const response =
        tmdbId === null ? await api.delete(url) : await api.post(url, { tmdb_id: tmdbId });
      return response.data as { status: string };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["explore", "titles", mediaType] });
      queryClient.invalidateQueries({ queryKey: ["explore", "tmdb", mediaType] });
    },
  });
}

/**
 * Keeps the page current while the server works: a title check finishing,
 * a rename done here or by Sonarr's webhook, and Rename all's progress, which
 * ends in one message for the whole run.
 */
export function useTitleEvents(mediaType: string) {
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState<RenameProgress | null>(null);

  useEffect(() => {
    const socket = getSocket();
    if (!socket || !hasTitles(mediaType)) return;
    const refresh = () => {
      queryClient.invalidateQueries({ queryKey: ["explore", "titles", mediaType] });
      queryClient.invalidateQueries({ queryKey: ["explore", "season", mediaType] });
    };
    const onProgress = (data: RenameProgress) => {
      if (data.media_type === mediaType) setProgress(data);
    };
    const onFinished = (data: RenameLibraryFinished) => {
      if (data.media_type !== mediaType) return;
      setProgress(null);
      refresh();
      queryClient.invalidateQueries({ queryKey: ["webhooks", "rename"] });
      const text = data.dry_run
        ? `Test mode: nothing was renamed. Would have renamed ${data.renamed} file(s) in ${data.series} series`
        : `Renamed ${data.renamed} file(s) in ${data.series} series`;
      if (data.failed.length) {
        toast.warning(
          `${text}. ${data.failed.length} series had a problem — see Webhooks → Renames.`
        );
      } else if (data.dry_run) {
        toast.warning(text);
      } else {
        toast.success(text);
      }
    };
    socket.on("titles_checked", refresh);
    socket.on("rename_completed", refresh);
    socket.on("rename_progress", onProgress);
    socket.on("rename_library_finished", onFinished);
    return () => {
      socket.off("titles_checked", refresh);
      socket.off("rename_completed", refresh);
      socket.off("rename_progress", onProgress);
      socket.off("rename_library_finished", onFinished);
    };
  }, [mediaType, queryClient]);

  return { progress };
}
