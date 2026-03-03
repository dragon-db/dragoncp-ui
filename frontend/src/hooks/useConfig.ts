import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import type { AppConfig, DiskUsage, RemoteStorageInfo, SSHConfig, SSHConfigResponse } from '@/lib/api-types';
export type { AppConfig, DiskUsage, RemoteStorageInfo, SSHConfig, SSHConfigResponse } from '@/lib/api-types';

export function useAppConfig() {
  return useQuery({
    queryKey: ['config'],
    queryFn: async () => {
      const response = await api.get<AppConfig>('/config');
      return response.data;
    },
  });
}

export function useUpdateConfig() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (config: Partial<AppConfig>) => {
      const response = await api.post('/config', config);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      queryClient.invalidateQueries({ queryKey: ['ssh', 'status'] });
    },
  });
}

export function useResetConfig() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      const response = await api.post('/config/reset');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      queryClient.invalidateQueries({ queryKey: ['ssh', 'status'] });
    },
  });
}

export function useEnvOnlyConfig() {
  return useQuery({
    queryKey: ['config', 'env-only'],
    queryFn: async () => {
      const response = await api.get<AppConfig>('/config/env-only');
      return response.data;
    },
  });
}

export function useSSHConfig() {
  return useQuery({
    queryKey: ['ssh', 'config'],
    queryFn: async () => {
      const response = await api.get<SSHConfigResponse>('/ssh-config');
      return response.data;
    },
  });
}

export function useSSHStatus() {
  return useQuery({
    queryKey: ['ssh', 'status'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        debug_info: {
          ssh_connected: boolean;
        };
      }>('/debug');
      return response.data.debug_info.ssh_connected;
    },
    refetchInterval: 5000,
  });
}

export function useSSHConnect() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (config: SSHConfig) => {
      const response = await api.post('/connect', config);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ssh'] });
      queryClient.invalidateQueries({ queryKey: ['media'] });
    },
  });
}

export function useSSHAutoConnect() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      const response = await api.get('/auto-connect');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ssh'] });
      queryClient.invalidateQueries({ queryKey: ['media'] });
      queryClient.invalidateQueries({ queryKey: ['ssh', 'status'] });
    },
  });
}

export function useSSHDisconnect() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      const response = await api.post('/disconnect');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ssh'] });
      queryClient.invalidateQueries({ queryKey: ['media'] });
      queryClient.invalidateQueries({ queryKey: ['ssh', 'status'] });
    },
  });
}

export function useLocalDiskUsage() {
  return useQuery({
    queryKey: ['disk', 'local'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        disk_info: DiskUsage[];
      }>('/disk-usage/local');
      return response.data;
    },
    refetchInterval: 60000, // Refresh every minute
  });
}

export function useRemoteDiskUsage() {
  return useQuery({
    queryKey: ['disk', 'remote'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        storage_info: RemoteStorageInfo;
      }>('/disk-usage/remote');
      return response.data;
    },
    refetchInterval: 60000, // Refresh every minute
  });
}

export function useDebugInfo() {
  return useQuery({
    queryKey: ['debug'],
    queryFn: async () => {
      const response = await api.get('/debug');
      return response.data;
    },
  });
}

export function useWebSocketStatus() {
  return useQuery({
    queryKey: ['websocket', 'status'],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        websocket_status: {
          active_connections: number;
          default_timeout_minutes: number;
          max_timeout_minutes: number;
          connection_details: Array<{
            session_id: string;
            connected_minutes_ago: number;
            last_activity_minutes_ago: number;
            timeout_minutes: number;
          }>;
        };
      }>('/websocket/status');
      return response.data;
    },
    refetchInterval: 5000,
  });
}
