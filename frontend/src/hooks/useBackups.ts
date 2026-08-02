import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type {
  BackupLibrary,
  BackupsOverview,
  Capture,
  DeletePreview,
  DeleteResult,
  MigrationReport,
  RebuildResult,
  RestorePlan,
  RetentionResult,
  RetentionRule,
  SeasonSummary,
  SlotDetail,
  SlotSort,
  SlotSummary,
  TitleSummary,
} from "@/lib/backup-types";

/**
 * Data for the Backups page.
 *
 * Everything is keyed under `["backups", ...]` so one invalidation after a
 * restore, a prune or a rebuild refreshes the whole screen — these views are
 * all projections of the same tree, and letting them drift apart is how a page
 * ends up showing a version that is no longer on disk.
 */

const KEY = "backups";

export function useBackupsOverview() {
  return useQuery({
    queryKey: [KEY, "overview"],
    queryFn: async () => {
      const response = await api.get<{ status: string } & BackupsOverview>("/backups/overview");
      return response.data;
    },
  });
}

export function useBackupTitles(library?: BackupLibrary) {
  return useQuery({
    queryKey: [KEY, "titles", library ?? "all"],
    queryFn: async () => {
      const params = library ? `?library=${encodeURIComponent(library)}` : "";
      const response = await api.get<{ status: string; titles: TitleSummary[] }>(
        `/backups/titles${params}`
      );
      return response.data.titles;
    },
  });
}

export function useBackupSeasons(library?: BackupLibrary, title?: string | null) {
  return useQuery({
    queryKey: [KEY, "seasons", library, title],
    queryFn: async () => {
      const params = new URLSearchParams({ library: library!, title: title! });
      const response = await api.get<{ status: string; seasons: SeasonSummary[] }>(
        `/backups/seasons?${params}`
      );
      return response.data.seasons;
    },
    enabled: Boolean(library && title),
  });
}

export function useBackupSlots(filters: {
  library?: BackupLibrary;
  title?: string | null;
  season?: number | null;
  search?: string;
  limit?: number;
  offset?: number;
  sort?: SlotSort;
}) {
  const { library, title, season, search, limit = 200, offset = 0, sort = "recent" } = filters;
  return useQuery({
    queryKey: [KEY, "slots", library, title, season, search, limit, offset, sort],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (library) params.set("library", library);
      if (title) params.set("title", title);
      if (season !== null && season !== undefined) params.set("season", String(season));
      if (search) params.set("search", search);
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      params.set("sort", sort);

      const response = await api.get<{
        status: string;
        slots: SlotSummary[];
        total: number;
        limit: number;
        offset: number;
      }>(`/backups/slots?${params}`);
      return response.data;
    },
  });
}

export function useBackupSlot(slotKey: string | null) {
  return useQuery({
    queryKey: [KEY, "slot", slotKey],
    queryFn: async () => {
      const params = new URLSearchParams({ slot_key: slotKey! });
      const response = await api.get<{ status: string } & SlotDetail>(`/backups/slot?${params}`);
      return response.data;
    },
    enabled: Boolean(slotKey),
  });
}

export function useUnsortedBackups(enabled = false) {
  return useQuery({
    queryKey: [KEY, "unsorted"],
    queryFn: async () => {
      const response = await api.get<{ status: string; captures: Capture[] }>("/backups/unsorted");
      return response.data.captures;
    },
    enabled,
  });
}

/** Preview only. Never writes — the same planner backs the restore itself. */
export function usePlanRestore() {
  return useMutation({
    mutationFn: async ({ captureId, files }: { captureId: string; files?: string[] }) => {
      const response = await api.post<{ status: string; plan: RestorePlan }>(
        `/backups/captures/${captureId}/plan`,
        files ? { files } : {}
      );
      return response.data.plan;
    },
  });
}

export function useRestoreCapture() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ captureId, files }: { captureId: string; files?: string[] }) => {
      const response = await api.post<{ status: string; message: string } & RestorePlan>(
        `/backups/captures/${captureId}/restore`,
        files ? { files } : {}
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [KEY] });
      // The restore runs as a transfer, so the Transfers views want it too.
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}

export function usePinCapture() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ captureId, pinned }: { captureId: string; pinned: boolean }) => {
      const response = await api.post<{ status: string; message: string }>(
        `/backups/captures/${captureId}/pin`,
        { pinned }
      );
      return response.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useDeleteCapture() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      captureId,
      deleteFiles = true,
    }: {
      captureId: string;
      deleteFiles?: boolean;
    }) => {
      const response = await api.post<{ status: string; message: string }>(
        `/backups/captures/${captureId}/delete`,
        { delete_files: deleteFiles }
      );
      return response.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

/** Selection for a bulk delete: explicit versions, or whole items. */
export interface DeleteSelection {
  capture_ids?: string[];
  slot_keys?: string[];
  /** Leave the most recent N of each selected item. */
  keep_newest?: number;
  include_pinned?: boolean;
}

/** Reads only. Deleting a backup has no undo, so the numbers come first. */
export function useDeletePreview() {
  return useMutation({
    mutationFn: async (selection: DeleteSelection) => {
      const response = await api.post<{ status: string } & DeletePreview>(
        "/backups/delete/preview",
        selection
      );
      return response.data;
    },
  });
}

export function useDeleteBackups() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (selection: DeleteSelection) => {
      const response = await api.post<{ status: string } & DeleteResult>(
        "/backups/delete",
        selection
      );
      return response.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useClearUnsorted() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const response = await api.post<{ status: string } & DeleteResult>(
        "/backups/unsorted/delete",
        { confirm: true }
      );
      return response.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

/** Persists to the database, so it survives a restart and background threads see it. */
export function useSaveRetention() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { keep?: number; grace_hours?: number; enabled?: boolean }) => {
      const response = await api.post<{
        status: string;
        message: string;
        retention: RetentionRule;
      }>("/backups/retention", input);
      return response.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useRebuildIndex() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const response = await api.post<{ status: string } & RebuildResult>("/backups/rebuild");
      return response.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useRetentionPreview() {
  return useMutation({
    mutationFn: async (input: { keep?: number; grace_hours?: number }) => {
      const response = await api.post<{ status: string } & RetentionResult>(
        "/backups/retention/preview",
        input
      );
      return response.data;
    },
  });
}

export function useRetentionApply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { keep?: number; grace_hours?: number }) => {
      const response = await api.post<{ status: string; message: string } & RetentionResult>(
        "/backups/retention/apply",
        input
      );
      return response.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useMigrationPlan() {
  return useMutation({
    mutationFn: async () => {
      const response = await api.post<{ status: string } & MigrationReport>(
        "/backups/migration/plan"
      );
      return response.data;
    },
  });
}

export function useMigrationApply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const response = await api.post<{ status: string; message: string } & MigrationReport>(
        "/backups/migration/apply",
        { confirm: true }
      );
      return response.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}
