import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import api from '@/lib/api';
import type { AppConfig, DiskUsage, RemoteStorageInfo, SSHConfig, SSHConfigResponse } from '@/lib/api-types';
export type { AppConfig, DiskUsage, RemoteStorageInfo, SSHConfig, SSHConfigResponse } from '@/lib/api-types';

const RUNTIME_STATUS_REFETCH_MS = 5000;
const LEGACY_DEBUG_REFETCH_MS = 30000;

let runtimeStatusEndpointUnsupported = false;

export interface RuntimeStatusResponse {
  status: string;
  runtime_status: {
    backend_reachable: boolean;
    ssh_connected: boolean;
    websocket: {
      active_connections: number;
      cleanup_thread_running: boolean;
      runtime: Record<string, unknown>;
    };
    timestamp: string;
  };
}

interface LegacyDebugResponse {
  status: string;
  debug_info: {
    ssh_connected: boolean;
    websocket_info?: {
      active_connections?: number;
      cleanup_thread_running?: boolean;
      runtime?: Record<string, unknown>;
    };
    timestamp?: string;
  };
}

function normalizeLegacyRuntimeStatus(data: LegacyDebugResponse): RuntimeStatusResponse {
  return {
    status: data.status,
    runtime_status: {
      backend_reachable: true,
      ssh_connected: Boolean(data.debug_info?.ssh_connected),
      websocket: {
        active_connections: data.debug_info?.websocket_info?.active_connections ?? 0,
        cleanup_thread_running: Boolean(data.debug_info?.websocket_info?.cleanup_thread_running),
        runtime: data.debug_info?.websocket_info?.runtime ?? {},
      },
      timestamp: data.debug_info?.timestamp ?? new Date().toISOString(),
    },
  };
}

function runtimeStatusQueryOptions() {
  return {
    queryKey: ['runtime', 'status'],
    queryFn: async () => {
      if (runtimeStatusEndpointUnsupported) {
        const fallback = await api.get<LegacyDebugResponse>('/debug');
        return normalizeLegacyRuntimeStatus(fallback.data);
      }

      try {
        const response = await api.get<RuntimeStatusResponse>('/runtime/status');
        return response.data;
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 404) {
          runtimeStatusEndpointUnsupported = true;
          const fallback = await api.get<LegacyDebugResponse>('/debug');
          return normalizeLegacyRuntimeStatus(fallback.data);
        }
        throw error;
      }
    },
    refetchInterval: () => (runtimeStatusEndpointUnsupported ? LEGACY_DEBUG_REFETCH_MS : RUNTIME_STATUS_REFETCH_MS),
  };
}

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
      queryClient.invalidateQueries({ queryKey: ['runtime', 'status'] });
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
      queryClient.invalidateQueries({ queryKey: ['runtime', 'status'] });
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
    ...runtimeStatusQueryOptions(),
    select: (data) => data.runtime_status.ssh_connected,
  });
}

export function useRuntimeStatus() {
  return useQuery(runtimeStatusQueryOptions());
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
      queryClient.invalidateQueries({ queryKey: ['runtime', 'status'] });
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
      queryClient.invalidateQueries({ queryKey: ['runtime', 'status'] });
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
      queryClient.invalidateQueries({ queryKey: ['runtime', 'status'] });
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
