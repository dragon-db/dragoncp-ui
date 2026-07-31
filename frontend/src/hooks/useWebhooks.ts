import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type {
  RenameNotification,
  RenameVerificationResult,
  WebhookNotification,
} from "@/lib/api-types";
export type {
  RenameNotification,
  RenameVerificationResult,
  WebhookNotification,
} from "@/lib/api-types";

export interface WebhookSettings {
  auto_sync_movies: boolean;
  auto_sync_series: boolean;
  auto_sync_anime: boolean;
  series_anime_sync_wait_time: number;
}

export interface DiscordSettings {
  webhook_url: string;
  app_url: string;
  manual_sync_thumbnail_url: string;
  icon_url: string;
  enabled: boolean;
}

/** What a paged listing returns, alongside the rows themselves. */
export interface ListPage {
  /** Records matching the filter, across both webhook tables. */
  total: number;
  /** Records on this page. */
  count: number;
  limit: number;
  offset: number;
  /** Matching records per status, so filters can show their own counts. */
  status_counts: Record<string, number>;
  /** Records on file ignoring the current filter and search. */
  unfiltered_total: number;
  /**
   * Arrivals flagged for manual sync. Reported separately from `status_counts`
   * because a flagged arrival keeps its real status too - counting it as a
   * status would double it in any total built from those counts.
   */
  manual_sync_count: number;
}

export interface NotificationListOptions {
  limit?: number;
  offset?: number;
  status?: string;
  mediaType?: string;
  search?: string;
}

/**
 * A page of movie and series arrivals, newest first.
 *
 * Ordering and paging run across both sources on the server. The page used to
 * request the same number from each and merge them here, which meant the newer
 * source crowded the other one off the list.
 */
export function useWebhookNotifications(options: NotificationListOptions = {}) {
  const { limit = 50, offset = 0, status, mediaType, search } = options;

  return useQuery({
    queryKey: ["webhooks", "notifications", { limit, offset, status, mediaType, search }],
    queryFn: async () => {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      if (status) params.set("status", status);
      if (mediaType) params.set("media_type", mediaType);
      if (search) params.set("search", search);

      const response = await api.get<
        { status: string; notifications: WebhookNotification[] } & ListPage
      >(`/webhook/notifications?${params}`);
      return response.data;
    },
    refetchInterval: 10000, // Poll every 10 seconds
    // Keeps the current page on screen while the next one loads.
    placeholderData: (previous) => previous,
  });
}

export interface BulkDeleteNotifications {
  /** Specific notifications to delete. Ignored when `all_matching` is set. */
  ids?: string[];
  /** Delete every notification matching the filter below. */
  all_matching?: boolean;
  status?: string;
  media_type?: string;
  search?: string;
}

/** Delete several webhook notifications at once. */
export function useBulkDeleteNotifications() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: BulkDeleteNotifications) => {
      const response = await api.post<{
        status: string;
        deleted_count: number;
        message: string;
      }>("/webhook/notifications/bulk-delete", payload);
      if (response.data?.status === "error") {
        throw new Error(response.data.message || "Request failed");
      }
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
}

export function useRenameNotifications(
  limit = 50,
  status?: string,
  mediaType?: "tvshows" | "anime"
) {
  return useQuery({
    queryKey: ["webhooks", "rename", limit, status, mediaType],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.append("limit", String(limit));
      if (status) params.append("status", status);
      if (mediaType) params.append("media_type", mediaType);
      const response = await api.get<{
        status: string;
        notifications: RenameNotification[];
        total: number;
      }>(`/webhook/rename/notifications?${params.toString()}`);
      return response.data;
    },
    refetchInterval: 10000,
  });
}

export function useRenameNotificationDetails(notificationId: string) {
  return useQuery({
    queryKey: ["webhooks", "rename", notificationId],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        notification: RenameNotification;
      }>(`/webhook/rename/notifications/${notificationId}`);
      return response.data;
    },
    enabled: !!notificationId,
  });
}

export function useDeleteRenameNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (notificationId: string) => {
      const response = await api.post(`/webhook/rename/notifications/${notificationId}/delete`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks", "rename"] });
    },
  });
}

export function useVerifyRenameNotification() {
  return useMutation({
    mutationFn: async (notificationId: string) => {
      const response = await api.post<{
        status: string;
        result: RenameVerificationResult;
      }>(`/webhook/rename/notifications/${notificationId}/verify`);
      return response.data;
    },
  });
}

export function useWebhookNotificationDetails(notificationId: string) {
  return useQuery({
    queryKey: ["webhooks", "notification", notificationId],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        notification: WebhookNotification;
      }>(`/webhook/notifications/${notificationId}`);
      return response.data;
    },
    enabled: !!notificationId,
  });
}

export function useWebhookNotificationJson(notificationId: string) {
  return useQuery({
    queryKey: ["webhooks", "notification", notificationId, "json"],
    queryFn: async () => {
      const response = await api.get(`/webhook/notifications/${notificationId}/json`);
      return response.data;
    },
    enabled: !!notificationId,
  });
}

/**
 * Sync a whole group in one request.
 *
 * A series transfer is scoped to the season folder, so a season's episode
 * notifications need exactly one transfer between them. Posting them
 * individually created one transfer per episode, all aimed at the same
 * destination; the queue then serialised them and all but the first moved
 * nothing. The server re-derives the grouping, so this only nominates which
 * notifications to consider.
 */
export function useTriggerWebhookGroupSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (notificationIds: string[]) => {
      const response = await api.post<{
        status: string;
        message: string;
        transfer_ids: string[];
      }>("/webhook/series/notifications/sync-batch", {
        notification_ids: notificationIds,
      });
      return response.data;
    },
    // Same refresh as a single sync: the group's rows and the transfer list
    // both change the moment this returns.
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}

export function useTriggerWebhookSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      notificationId,
      mediaType,
    }: {
      notificationId: string;
      mediaType: string;
    }) => {
      let endpoint = `/webhook/notifications/${notificationId}/sync`;
      if (mediaType === "tvshows") {
        endpoint = `/webhook/series/notifications/${notificationId}/sync`;
      } else if (mediaType === "anime") {
        endpoint = `/webhook/anime/notifications/${notificationId}/sync`;
      }
      const response = await api.post(endpoint);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}

export function useMarkWebhookComplete() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      notificationId,
      mediaType,
    }: {
      notificationId: string;
      mediaType: string;
    }) => {
      let endpoint = `/webhook/notifications/${notificationId}/complete`;
      if (mediaType === "tvshows") {
        endpoint = `/webhook/series/notifications/${notificationId}/complete`;
      } else if (mediaType === "anime") {
        endpoint = `/webhook/anime/notifications/${notificationId}/complete`;
      }
      const response = await api.post(endpoint);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
}

export function useDeleteWebhookNotification() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      notificationId,
      mediaType,
    }: {
      notificationId: string;
      mediaType: string;
    }) => {
      let endpoint = `/webhook/notifications/${notificationId}/delete`;
      if (mediaType === "tvshows") {
        endpoint = `/webhook/series/notifications/${notificationId}/delete`;
      } else if (mediaType === "anime") {
        endpoint = `/webhook/anime/notifications/${notificationId}/delete`;
      }
      const response = await api.post(endpoint);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
}

export function useWebhookDryRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      notificationId,
      mediaType,
    }: {
      notificationId: string;
      mediaType: string;
    }) => {
      let endpoint = `/webhook/notifications/${notificationId}/dry-run`;
      if (mediaType === "tvshows" || mediaType === "series") {
        endpoint = `/webhook/series/notifications/${notificationId}/dry-run`;
      } else if (mediaType === "anime") {
        endpoint = `/webhook/anime/notifications/${notificationId}/dry-run`;
      }
      const response = await api.post(endpoint);
      return response.data as { status: string; dry_run_result: unknown };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
}

export function useWebhookSettings() {
  return useQuery({
    queryKey: ["webhooks", "settings"],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        settings: WebhookSettings;
      }>("/webhook/settings");
      return response.data;
    },
  });
}

export function useUpdateWebhookSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (settings: Partial<WebhookSettings>) => {
      const response = await api.post("/webhook/settings", settings);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks", "settings"] });
    },
  });
}

export function useDiscordSettings() {
  return useQuery({
    queryKey: ["discord", "settings"],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        settings: DiscordSettings;
      }>("/discord/settings");
      return response.data;
    },
  });
}

export function useUpdateDiscordSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (settings: Partial<DiscordSettings>) => {
      const response = await api.post("/discord/settings", settings);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["discord", "settings"] });
    },
  });
}

export function useTestDiscord() {
  return useMutation({
    mutationFn: async () => {
      const response = await api.post("/discord/test");
      return response.data;
    },
  });
}
