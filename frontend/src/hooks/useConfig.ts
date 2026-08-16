import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import api from "@/lib/api";
import { isOutdated } from "@/lib/version";
import type {
  SettingsResponse,
  DiskUsage,
  RemoteStorageInfo,
  SSHConfig,
  SSHConfigResponse,
} from "@/lib/api-types";
export type {
  SettingsResponse,
  SettingDescriptor,
  SettingGroup,
  SettingStore,
  DiskUsage,
  RemoteStorageInfo,
  SSHConfig,
  SSHConfigResponse,
} from "@/lib/api-types";

const RUNTIME_STATUS_REFETCH_MS = 5000;
const LEGACY_DEBUG_REFETCH_MS = 30000;

let runtimeStatusEndpointUnsupported = false;

export interface RuntimeStatusResponse {
  status: string;
  runtime_status: {
    backend_reachable: boolean;
    /**
     * What the server is running. Optional because a backend that has not been
     * restarted since this was added answers without it — the caller falls back
     * to the version this bundle was built from.
     */
    version?: string;
    /**
     * Whether the server is running with every write turned into a rehearsal.
     * Optional because a backend that has not been restarted since this was
     * added answers without it — absent is read as "not in test mode", which is
     * the safe way round: it never claims a real server is a test one.
     */
    test_mode?: boolean;
    ssh_connected: boolean;
    websocket: {
      active_connections: number;
      cleanup_thread_running: boolean;
      runtime: Record<string, unknown>;
    };
    timestamp: string;
  };
}

export type BackendLogLevel = "ERROR" | "WARNING" | "INFO" | "DEBUG" | "ALL";
export type BackendLogEntryLevel = "CRITICAL" | Exclude<BackendLogLevel, "ALL">;

export interface BackendLogResponse {
  status: string;
  log_file: string;
  level: BackendLogLevel;
  limit: number;
  line_count: number;
  size_bytes?: number;
  last_modified?: string;
  message?: string;
  lines: Array<{ level: BackendLogEntryLevel; text: string }>;
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
    queryKey: ["runtime", "status"],
    queryFn: async () => {
      if (runtimeStatusEndpointUnsupported) {
        const fallback = await api.get<LegacyDebugResponse>("/debug");
        return normalizeLegacyRuntimeStatus(fallback.data);
      }

      try {
        const response = await api.get<RuntimeStatusResponse>("/runtime/status");
        return response.data;
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 404) {
          runtimeStatusEndpointUnsupported = true;
          const fallback = await api.get<LegacyDebugResponse>("/debug");
          return normalizeLegacyRuntimeStatus(fallback.data);
        }
        throw error;
      }
    },
    refetchInterval: () =>
      runtimeStatusEndpointUnsupported ? LEGACY_DEBUG_REFETCH_MS : RUNTIME_STATUS_REFETCH_MS,
  };
}

/** Every setting, grouped, each saying which store it came from. */
export function useSettings() {
  return useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const response = await api.get<SettingsResponse>("/config");
      return response.data;
    },
  });
}

/**
 * Save the editable half.
 *
 * Environment-backed keys are refused by name rather than ignored, so a save
 * that only partly applied says which settings it did not touch instead of
 * reporting a flat success.
 */
export function useUpdateSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (values: Record<string, string | number | boolean>) => {
      const response = await api.post<SettingsResponse>("/config", values);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["runtime", "status"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });
}

export function useSSHConfig() {
  return useQuery({
    queryKey: ["ssh", "config"],
    queryFn: async () => {
      const response = await api.get<SSHConfigResponse>("/ssh-config");
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

/**
 * The version to show: the running server's, or this bundle's if it has not
 * answered yet.
 *
 * Preferring the server means the number on screen is the one actually serving
 * requests. A cached bundle can outlive a deploy, and a version baked into it
 * would then confidently report a release that is no longer running.
 */
export function useAppVersion(): string {
  const { data } = useQuery({
    ...runtimeStatusQueryOptions(),
    select: (response) => response.runtime_status.version,
  });
  return data || __APP_VERSION__;
}

/**
 * Whether this tab is running code the server has moved on from.
 *
 * Nothing about caching causes this and nothing about caching fixes it. Asset
 * files are content-hashed and the shell is `no-cache`, so *a reload* always
 * lands on the new build — the gap is the session that never reloads. A tab
 * left open across a deploy keeps executing yesterday's JavaScript against
 * today's API for as long as it stays open.
 *
 * The comparison is deliberately narrow. Both sides must be known and real:
 * a backend too old to report its version says nothing, and `unknown` means the
 * VERSION file could not be read at build or at startup. Guessing from either
 * would nag on every poll about an update that may not exist.
 */
export function useUpdateAvailable(): { stale: boolean; running: string; available: string } {
  const { data } = useQuery({
    ...runtimeStatusQueryOptions(),
    select: (response) => response.runtime_status.version,
  });

  const running = __APP_VERSION__;
  const available = data ?? "";

  return { stale: isOutdated(running, available), running, available };
}

/**
 * Whether this server writes anything to disk.
 *
 * Reads the runtime status every page already polls, so it costs no extra
 * request. Absent means no — a backend too old to report it is far more likely
 * to be a real one than a test one, and claiming a live server is a rehearsal
 * would be the more dangerous mistake.
 */
export function useTestMode(): boolean {
  const { data } = useQuery({
    ...runtimeStatusQueryOptions(),
    select: (response) => response.runtime_status.test_mode ?? false,
  });
  return data ?? false;
}

export function useSSHConnect() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (config: SSHConfig) => {
      const response = await api.post("/connect", config);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ssh"] });
      queryClient.invalidateQueries({ queryKey: ["media"] });
      queryClient.invalidateQueries({ queryKey: ["runtime", "status"] });
    },
  });
}

export function useSSHAutoConnect() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const response = await api.get("/auto-connect");
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ssh"] });
      queryClient.invalidateQueries({ queryKey: ["media"] });
      queryClient.invalidateQueries({ queryKey: ["runtime", "status"] });
    },
  });
}

export function useSSHDisconnect() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const response = await api.post("/disconnect");
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ssh"] });
      queryClient.invalidateQueries({ queryKey: ["media"] });
      queryClient.invalidateQueries({ queryKey: ["runtime", "status"] });
    },
  });
}

export function useLocalDiskUsage() {
  return useQuery({
    queryKey: ["disk", "local"],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        disk_info: DiskUsage[];
      }>("/disk-usage/local");
      return response.data;
    },
    refetchInterval: 60000, // Refresh every minute
  });
}

export function useRemoteDiskUsage() {
  return useQuery({
    queryKey: ["disk", "remote"],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        storage_info: RemoteStorageInfo;
      }>("/disk-usage/remote");
      return response.data;
    },
    refetchInterval: 60000, // Refresh every minute
  });
}

export function useDebugInfo() {
  return useQuery({
    queryKey: ["debug"],
    queryFn: async () => {
      const response = await api.get("/debug");
      return response.data;
    },
  });
}

export function useWebSocketStatus() {
  return useQuery({
    queryKey: ["websocket", "status"],
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
      }>("/websocket/status");
      return response.data;
    },
    refetchInterval: 5000,
  });
}

export function useBackendLogs({
  level,
  search,
  autoRefresh,
}: {
  level: BackendLogLevel;
  search: string;
  autoRefresh: boolean;
}) {
  return useQuery({
    queryKey: ["backend-logs", level, search],
    queryFn: async () => {
      const response = await api.get<BackendLogResponse>("/logs", {
        params: { level, search: search || undefined, limit: 300 },
      });
      return response.data;
    },
    refetchInterval: autoRefresh ? 5000 : false,
  });
}

export function useDownloadBackendLogs() {
  return useMutation({
    mutationFn: async () => {
      const response = await api.get<Blob>("/logs/download", { responseType: "blob" });
      const disposition = String(response.headers["content-disposition"] ?? "");
      const match = disposition.match(
        /filename\*?=(?:UTF-8'')?["']?([^"';]+)|filename=["']?([^"';]+)/i
      );
      const filename = decodeURIComponent(match?.[1] ?? match?.[2] ?? "dragoncp.log");
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      return filename;
    },
  });
}
