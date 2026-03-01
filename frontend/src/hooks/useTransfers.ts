import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import type { QueueStatus, Transfer } from '@/lib/api-types';
export type { QueueStatus, Transfer } from '@/lib/api-types';

export interface TransferRequest {
  type: 'folder' | 'file';
  media_type: 'movies' | 'tvshows' | 'anime';
  folder_name: string;
  season_name?: string;
  episode_name?: string;
}

export function useActiveTransfers() {
  return useQuery({
    queryKey: ['transfers', 'active'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        transfers: Transfer[];
        total: number;
        queue_status: QueueStatus;
      }>('/transfers/active');
      return response.data;
    },
    refetchInterval: 5000, // Poll every 5 seconds
  });
}

export function useAllTransfers(limit = 50) {
  return useQuery({
    queryKey: ['transfers', 'all', limit],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        transfers: Transfer[];
        total: number;
      }>(`/transfers/all?limit=${limit}`);
      return response.data;
    },
  });
}

export function useTransferStatus(transferId: string) {
  return useQuery({
    queryKey: ['transfers', transferId],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        transfer: Transfer;
      }>(`/transfer/${transferId}/status`);
      return response.data;
    },
    enabled: !!transferId,
    refetchInterval: 2000, // Poll every 2 seconds for active transfer
  });
}

export function useTransferLogs(transferId: string) {
  return useQuery({
    queryKey: ['transfers', transferId, 'logs'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        logs: string[];
        log_count: number;
        transfer_status: string;
      }>(`/transfer/${transferId}/logs`);
      return response.data;
    },
    enabled: !!transferId,
  });
}

export function useQueueStatus() {
  return useQuery({
    queryKey: ['transfers', 'queue'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        queue: QueueStatus;
      }>('/transfers/queue/status');
      return response.data;
    },
    refetchInterval: 5000,
  });
}

export function useStartTransfer() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (data: TransferRequest) => {
      const response = await api.post<{
        status: string;
        transfer_id: string;
        message: string;
        source: string;
        destination: string;
      }>('/transfer', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
    },
  });
}

export function useCancelTransfer() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (transferId: string) => {
      const response = await api.post(`/transfer/${transferId}/cancel`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
    },
  });
}

export function useRestartTransfer() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (transferId: string) => {
      const response = await api.post(`/transfer/${transferId}/restart`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
    },
  });
}

export function useDeleteTransfer() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (transferId: string) => {
      const response = await api.post(`/transfer/${transferId}/delete`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
    },
  });
}

export function useCleanupTransfers() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      const response = await api.post('/transfers/cleanup');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
    },
  });
}
