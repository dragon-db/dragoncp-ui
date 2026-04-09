import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import type { RenameNotification, RenameVerificationResult, WebhookNotification } from '@/lib/api-types';
export type { RenameNotification, RenameVerificationResult, WebhookNotification } from '@/lib/api-types';

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

export function useWebhookNotifications(status?: string, limit = 50) {
  return useQuery({
    queryKey: ['webhooks', 'notifications', status, limit],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (status) params.append('status', status);
      params.append('limit', limit.toString());
      
      const response = await api.get<{
        status: string;
        notifications: WebhookNotification[];
        total: number;
      }>(`/webhook/notifications?${params}`);
      return response.data;
    },
    refetchInterval: 10000, // Poll every 10 seconds
  });
}

export function useRenameNotifications(limit = 50, status?: string, mediaType?: 'tvshows' | 'anime') {
  return useQuery({
    queryKey: ['webhooks', 'rename', limit, status, mediaType],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.append('limit', String(limit));
      if (status) params.append('status', status);
      if (mediaType) params.append('media_type', mediaType);
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
    queryKey: ['webhooks', 'rename', notificationId],
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
      queryClient.invalidateQueries({ queryKey: ['webhooks', 'rename'] });
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
    queryKey: ['webhooks', 'notification', notificationId],
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
    queryKey: ['webhooks', 'notification', notificationId, 'json'],
    queryFn: async () => {
      const response = await api.get(`/webhook/notifications/${notificationId}/json`);
      return response.data;
    },
    enabled: !!notificationId,
  });
}

export function useTriggerWebhookSync() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async ({ notificationId, mediaType }: { notificationId: string; mediaType: string }) => {
      let endpoint = `/webhook/notifications/${notificationId}/sync`;
      if (mediaType === 'tvshows') {
        endpoint = `/webhook/series/notifications/${notificationId}/sync`;
      } else if (mediaType === 'anime') {
        endpoint = `/webhook/anime/notifications/${notificationId}/sync`;
      }
      const response = await api.post(endpoint);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
    },
  });
}

export function useMarkWebhookComplete() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async ({ notificationId, mediaType }: { notificationId: string; mediaType: string }) => {
      let endpoint = `/webhook/notifications/${notificationId}/complete`;
      if (mediaType === 'tvshows') {
        endpoint = `/webhook/series/notifications/${notificationId}/complete`;
      } else if (mediaType === 'anime') {
        endpoint = `/webhook/anime/notifications/${notificationId}/complete`;
      }
      const response = await api.post(endpoint);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
    },
  });
}

export function useDeleteWebhookNotification() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async ({ notificationId, mediaType }: { notificationId: string; mediaType: string }) => {
      let endpoint = `/webhook/notifications/${notificationId}/delete`;
      if (mediaType === 'tvshows') {
        endpoint = `/webhook/series/notifications/${notificationId}/delete`;
      } else if (mediaType === 'anime') {
        endpoint = `/webhook/anime/notifications/${notificationId}/delete`;
      }
      const response = await api.post(endpoint);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
    },
  });
}

export function useWebhookDryRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ notificationId, mediaType }: { notificationId: string; mediaType: string }) => {
      let endpoint = `/webhook/notifications/${notificationId}/dry-run`;
      if (mediaType === 'tvshows' || mediaType === 'series') {
        endpoint = `/webhook/series/notifications/${notificationId}/dry-run`;
      } else if (mediaType === 'anime') {
        endpoint = `/webhook/anime/notifications/${notificationId}/dry-run`;
      }
      const response = await api.post(endpoint);
      return response.data as { status: string; dry_run_result: unknown };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
    },
  });
}

export function useWebhookSettings() {
  return useQuery({
    queryKey: ['webhooks', 'settings'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        settings: WebhookSettings;
      }>('/webhook/settings');
      return response.data;
    },
  });
}

export function useUpdateWebhookSettings() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (settings: Partial<WebhookSettings>) => {
      const response = await api.post('/webhook/settings', settings);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks', 'settings'] });
    },
  });
}

export function useDiscordSettings() {
  return useQuery({
    queryKey: ['discord', 'settings'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        settings: DiscordSettings;
      }>('/discord/settings');
      return response.data;
    },
  });
}

export function useUpdateDiscordSettings() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (settings: Partial<DiscordSettings>) => {
      const response = await api.post('/discord/settings', settings);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['discord', 'settings'] });
    },
  });
}

export function useTestDiscord() {
  return useMutation({
    mutationFn: async () => {
      const response = await api.post('/discord/test');
      return response.data;
    },
  });
}
