import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import type { Transfer } from '@/lib/api-types';

export interface Backup {
  id: number;
  backup_id: string;
  transfer_id: string;
  media_type?: string;
  folder_name?: string;
  season_name?: string;
  source_path: string;
  dest_path: string;
  backup_path: string;
  file_count: number;
  total_size: number;
  status: 'ready' | 'restored' | 'deleted';
  created_at: string;
  restored_at?: string;
}

export interface BackupFile {
  id: number;
  backup_id: string;
  relative_path: string;
  original_path: string;
  file_size?: number;
  modified_time?: number;
  context_media_type?: string;
  context_title?: string;
  context_display?: string;
}

export interface RestorePlan {
  backup?: Backup;
  files?: BackupFile[];
  operations?: Array<{
    backup_relative: string;
    context_display?: string;
    target_delete?: string;
    copy_to: string;
  }>;
  restore_targets: Array<{
    source: string;
    destination: string;
  }>;
  transfer?: Transfer;
}

export function useBackups(limit = 100, includeDeleted = false) {
  return useQuery({
    queryKey: ['backups', 'list', limit, includeDeleted],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.append('limit', limit.toString());
      if (includeDeleted) params.append('include_deleted', '1');
      
      const response = await api.get<{
        status: string;
        backups: Backup[];
        total: number;
      }>(`/backups?${params}`);
      return response.data;
    },
  });
}

export function useBackupDetails(backupId: string) {
  return useQuery({
    queryKey: ['backups', backupId],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        backup: Backup;
      }>(`/backups/${backupId}`);
      return response.data;
    },
    enabled: !!backupId,
  });
}

export function useBackupFiles(backupId: string, limit?: number) {
  return useQuery({
    queryKey: ['backups', backupId, 'files', limit],
    queryFn: async () => {
      const params = limit ? `?limit=${limit}` : '';
      const response = await api.get<{
        status: string;
        files: BackupFile[];
        total: number;
      }>(`/backups/${backupId}/files${params}`);
      return response.data;
    },
    enabled: !!backupId,
  });
}

export function useRestoreBackup() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async ({ backupId, files }: { backupId: string; files?: string[] }) => {
      const response = await api.post(`/backups/${backupId}/restore`, { files });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backups'] });
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
    },
  });
}

export function useDeleteBackup() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async ({ 
      backupId, 
      deleteRecord = true, 
      deleteFiles = false 
    }: { 
      backupId: string; 
      deleteRecord?: boolean; 
      deleteFiles?: boolean;
    }) => {
      const response = await api.post(`/backups/${backupId}/delete`, {
        delete_record: deleteRecord,
        delete_files: deleteFiles,
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backups'] });
    },
  });
}

export function usePlanRestoreBackup() {
  return useMutation({
    mutationFn: async ({ backupId, files }: { backupId: string; files?: string[] }) => {
      const response = await api.post<{
        status: string;
        plan: RestorePlan;
      }>(`/backups/${backupId}/plan`, { files });
      return response.data;
    },
  });
}

export function useReindexBackups() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      const response = await api.post<{
        status: string;
        message: string;
        imported: number;
        skipped: number;
      }>('/backups/reindex');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backups'] });
    },
  });
}
