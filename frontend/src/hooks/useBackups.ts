import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api, { activityApi } from "@/lib/api";
import { HISTORY_LENS_ACTIONS } from "@/lib/backup-types";
import type {
  BackupLibrary,
  BackupsOverview,
  Capture,
  DeletePreview,
  DeleteResult,
  HistoryDetail,
  HistoryLens,
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
      // A restore swaps a file in the library, which is exactly what Explore
      // compares against the remote. Invalidated here rather than at the call
      // site so a restore started from either page tells the same story.
      queryClient.invalidateQueries({ queryKey: ["explore"] });
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

// Deleting a single version has no hook of its own either. Every deletion on
// the page — one version, fifty, or the whole unidentified bucket — goes
// through `useDeletePreview` then `useDeleteBackups`, so the count and the size
// are always shown first. `POST /backups/captures/<id>/delete` still exists for
// API callers; it removes the files and the index entry together.

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

// Clearing the unidentified bucket deliberately has no hook of its own. It is
// a permanent deletion like any other, so the page runs it through the same
// preview-then-confirm path (`useDeletePreview` + `useDeleteBackups`) rather
// than firing a one-click endpoint that erased the whole bucket on a misclick.

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

/**
 * Preview the migration. Moves nothing.
 *
 * The plan is NOT a token that `useMigrationApply` then redeems. Apply re-walks
 * the disk and re-derives its own plan, so the preview is a description of what
 * the migration would do to the disk as it was a moment ago, not a reservation
 * of those exact moves.
 *
 * That is deliberate rather than an oversight, and it is safe here in a way it
 * would not be for a deletion: migration only ever moves legacy folders into the
 * tree and removes ones it has emptied. It deletes no media, so a plan that has
 * drifted since it was shown costs an operator accuracy, not files. Anything it
 * cannot identify goes to `_unsorted` rather than being placed on a guess.
 */
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

/** Re-derives the plan against the disk as it is now — see `useMigrationPlan`. */
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

/* ===== History ===== */

/**
 * What the Backups feature has done, read from the activity trail.
 *
 * Read from the trail rather than from a table of its own because the trail is
 * already the record of who did what, and a second store would immediately
 * disagree with it. The lens filters are sent to the server as a list of
 * actions so the total and the paging describe the filtered set — filtering in
 * the browser would page over rows it then threw away.
 */
export function useBackupHistory(lens: HistoryLens, limit = 25, offset = 0) {
  const actions = HISTORY_LENS_ACTIONS[lens];
  return useQuery({
    queryKey: [KEY, "history", lens, limit, offset],
    queryFn: () =>
      activityApi.list({
        ...(actions.length ? { action: actions.join(",") } : { group: "backup" }),
        limit,
        offset,
      }),
    placeholderData: keepPreviousData,
    staleTime: 1000 * 15,
  });
}

/**
 * Deletions the automatic cleanup made that this browser has not acknowledged.
 *
 * The marker is the in-app half of the promise that an unattended deletion
 * announces itself; Discord is the other half. Acknowledgement is stored per
 * browser rather than on the server on purpose — it is "have *I* seen this",
 * and one admin dismissing it should not hide it from another.
 */
const SEEN_KEY = "dragoncp.backups.retention-seen";

function lastSeen(): string | null {
  try {
    return window.localStorage.getItem(SEEN_KEY);
  } catch {
    // Private browsing, or storage disabled. Showing the marker every time is
    // the safe failure: over-reporting a deletion is recoverable, missing one
    // is the thing this exists to prevent.
    return null;
  }
}

export function markRetentionSeen() {
  try {
    window.localStorage.setItem(SEEN_KEY, new Date().toISOString());
  } catch {
    /* nothing to do — the marker simply stays up */
  }
}

/**
 * Asks for the endpoint's whole page rather than a token few.
 *
 * The banner states how many versions were deleted, so a short page would
 * understate a number about lost data — the one place rounding down is worse
 * than saying nothing. 200 is the server's cap, which is far more sweeps than
 * accumulate between two visits in practice; `truncated` covers the case where
 * it is not, so the figure reads "200+" rather than as an exact count that
 * happens to be wrong.
 */
const UNSEEN_PAGE = 200;

export function useUnseenRetention() {
  const seen = lastSeen();
  return useQuery({
    queryKey: [KEY, "retention-unseen", seen],
    queryFn: async () => {
      const page = await activityApi.list({
        action: "backup.retention_apply",
        limit: UNSEEN_PAGE,
      });
      const fresh = seen ? page.entries.filter((entry) => entry.occurred_at > seen) : page.entries;
      const versions = fresh.reduce((total, entry) => {
        const detail = (entry.detail ?? {}) as HistoryDetail;
        return total + (detail.deleted_count ?? 0);
      }, 0);
      return {
        sweeps: fresh.length,
        versions,
        // Every entry on a full page was unseen, so there are very likely more
        // behind it that this figure does not include.
        truncated: fresh.length >= UNSEEN_PAGE,
        latest: fresh[0] ?? null,
      };
    },
    staleTime: 1000 * 30,
  });
}
