import { useQuery, useMutation } from '@tanstack/react-query';
import api from '@/lib/api';
import type { DryRunResult, FolderMetadata, FolderSyncStatus, MediaType } from '@/lib/api-types';

export function useMediaTypes() {
  return useQuery({
    queryKey: ['media', 'types'],
    queryFn: async () => {
      const response = await api.get<MediaType[]>('/media-types');
      return response.data;
    },
  });
}

export function useFolders(mediaType: string) {
  return useQuery({
    queryKey: ['media', 'folders', mediaType],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        folders: FolderMetadata[];
      }>(`/folders/${mediaType}`);
      return response.data;
    },
    enabled: !!mediaType,
  });
}

export function useSeasons(mediaType: string, folderName: string) {
  return useQuery({
    queryKey: ['media', 'seasons', mediaType, folderName],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        seasons: FolderMetadata[];
      }>(`/seasons/${mediaType}/${encodeURIComponent(folderName)}`);
      return response.data;
    },
    enabled: !!mediaType && !!folderName,
  });
}

export function useEpisodes(mediaType: string, folderName: string, seasonName: string) {
  return useQuery({
    queryKey: ['media', 'episodes', mediaType, folderName, seasonName],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        episodes: string[];
      }>(`/episodes/${mediaType}/${encodeURIComponent(folderName)}/${encodeURIComponent(seasonName)}`);
      return response.data;
    },
    enabled: !!mediaType && !!folderName && !!seasonName,
  });
}

export function useSyncStatus(mediaType: string) {
  return useQuery({
    queryKey: ['media', 'sync-status', mediaType],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        sync_statuses: Record<string, FolderSyncStatus>;
      }>(`/sync-status/${mediaType}`);
      return response.data;
    },
    enabled: !!mediaType,
  });
}

export function useFolderSyncStatus(mediaType: string, folderName: string) {
  return useQuery({
    queryKey: ['media', 'sync-status', mediaType, folderName],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        folder_name: string;
        sync_status: FolderSyncStatus;
        seasons_sync_status?: Record<string, FolderSyncStatus>;
      }>(`/sync-status/${mediaType}/${encodeURIComponent(folderName)}`);
      return response.data;
    },
    enabled: !!mediaType && !!folderName,
  });
}

export function useMediaDryRun() {
  return useMutation({
    mutationFn: async (data: {
      media_type: string;
      folder_name: string;
      season_name?: string;
    }) => {
      const response = await api.post<{
        status: string;
        dry_run_result: DryRunResult;
      }>('/media/dry-run', data);
      return response.data;
    },
  });
}
