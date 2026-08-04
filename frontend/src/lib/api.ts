import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import { useAuthStore, shouldRefreshToken } from "@/stores/auth";
import { destroySocket, reAuthenticateSocket } from "@/services/socket";

// Create axios instance
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api",
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor to add auth token
api.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const { token, refreshToken } = useAuthStore.getState();

    // Check if we need to refresh the token
    if (token && refreshToken && shouldRefreshToken()) {
      try {
        const response = await axios.post(
          `${import.meta.env.VITE_API_URL || "/api"}/auth/refresh`,
          { refresh_token: refreshToken }
        );

        if (response.data.token) {
          useAuthStore.getState().updateToken(response.data.token, response.data.expires_at);
          reAuthenticateSocket();
        }
      } catch (error) {
        // If refresh fails, continue with current token
        console.warn("Token refresh failed:", error);
      }
    }

    // Get the (possibly updated) token
    const currentToken = useAuthStore.getState().token;
    if (currentToken) {
      config.headers.Authorization = `Bearer ${currentToken}`;
    }

    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle 401 errors
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ code?: string }>) => {
    if (error.response?.status === 401) {
      // Token is invalid or expired, logout user
      destroySocket();
      useAuthStore.getState().logout();

      // Redirect to login page if not already there
      if (typeof window !== "undefined" && !window.location.pathname.includes("/login")) {
        window.location.href = "/login";
      }
    }

    // The server refuses ordinary work while an account still owes its first
    // password change. Normally the gate is already up and no such request is
    // made; this catches a stale tab whose stored state predates the rule.
    if (
      error.response?.status === 403 &&
      error.response.data?.code === "PASSWORD_CHANGE_REQUIRED"
    ) {
      destroySocket();
      useAuthStore.getState().setMustChangePassword(true);
    }

    return Promise.reject(error);
  }
);

// API response types
export interface ApiResponse<T = unknown> {
  status: "success" | "error";
  message?: string;
  data?: T;
}

export interface LoginResponse {
  status: "success" | "error";
  message?: string;
  token?: string;
  refresh_token?: string;
  expires_at?: string;
  refresh_expires_at?: string;
  user?: string;
  code?: string;
  account_id?: number | null;
  role?: string;
  must_change_password?: boolean;
  is_fallback_account?: boolean;
  /** Seconds to wait after too many failed sign-in attempts. */
  retry_after?: number;
}

export interface VerifyResponse {
  status: "success" | "error";
  valid: boolean;
  user?: string;
  account_id?: number | null;
  role?: string;
  must_change_password?: boolean;
  is_fallback_account?: boolean;
  remaining_seconds?: number;
  code?: string;
  message?: string;
}

export interface MeResponse {
  status: "success" | "error";
  user?: string;
  account_id?: number | null;
  role?: string;
  must_change_password?: boolean;
  is_fallback_account?: boolean;
  can_change_password?: boolean;
}

/**
 * Pull the server's own explanation out of a failed request.
 *
 * The sign-in and password endpoints answer with a specific reason — the
 * account is disabled, the attempt was throttled, the new password is too short
 * — and showing "Request failed with status code 429" instead of that reason
 * leaves people with no idea what to do next.
 */
export function errorMessageFrom(error: unknown, fallback: string): string {
  const axiosError = error as AxiosError<{ message?: string; retry_after?: number }>;
  const data = axiosError?.response?.data;

  if (data?.message) {
    if (data.retry_after) {
      const minutes = Math.ceil(data.retry_after / 60);
      return `${data.message} (about ${minutes} minute${minutes === 1 ? "" : "s"})`;
    }
    return data.message;
  }

  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

// Auth API functions
export const authApi = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const response = await api.post<LoginResponse>("/auth/login", { username, password });
    return response.data;
  },

  logout: async (): Promise<ApiResponse> => {
    const response = await api.post<ApiResponse>("/auth/logout");
    return response.data;
  },

  verify: async (): Promise<VerifyResponse> => {
    const response = await api.get<VerifyResponse>("/auth/verify");
    return response.data;
  },

  refresh: async (refreshToken: string): Promise<LoginResponse> => {
    const response = await api.post<LoginResponse>("/auth/refresh", {
      refresh_token: refreshToken,
    });
    return response.data;
  },

  status: async (): Promise<{
    auth_configured: boolean;
    account_count?: number;
    using_fallback_account?: boolean;
  }> => {
    const response = await api.get("/auth/status");
    return response.data;
  },

  me: async (): Promise<MeResponse> => {
    const response = await api.get<MeResponse>("/auth/me");
    return response.data;
  },

  /**
   * Change your own password. Nobody can change anyone else's from the browser
   * — that is what the server-side account script is for.
   *
   * Succeeding signs out every other session for this account, so the response
   * carries a replacement token pair for this one.
   */
  changePassword: async (
    currentPassword: string,
    newPassword: string
  ): Promise<LoginResponse> => {
    const response = await api.post<LoginResponse>("/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    });
    return response.data;
  },
};

// ===== Activity =====

export interface ActivityEntry {
  id: number;
  occurred_at: string;
  actor_kind: "admin" | "automated" | "system";
  actor_name: string;
  actor_account_id: number | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_label: string | null;
  summary: string;
  detail: Record<string, unknown> | null;
  outcome: "ok" | "failed" | "refused";
  request_ip: string | null;
}

export interface ActivityPage {
  status: string;
  entries: ActivityEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface ActivityFilters {
  status: string;
  actors: {
    actor_kind: string;
    actor_name: string;
    actor_account_id: number | null;
    entries: number;
    last_seen: string;
  }[];
  actions: { action: string; label: string; group: string }[];
  total: number;
}

export interface ActivityQuery {
  actor?: string;
  actor_kind?: string;
  action?: string;
  group?: string;
  target_type?: string;
  target_id?: string;
  outcome?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

/**
 * How an actor is shown. Automation is always badged so it can never be
 * mistaken for a colleague — the server forbids usernames that would blur that
 * line, and this is the other half of the same rule.
 */
export function actorLabel(entry: {
  actor_kind: string;
  actor_name: string;
}): string {
  return entry.actor_kind === "admin" ? entry.actor_name : `AUTO / ${entry.actor_name}`;
}

export const activityApi = {
  list: async (query: ActivityQuery = {}): Promise<ActivityPage> => {
    const params = Object.fromEntries(
      Object.entries(query).filter(([, v]) => v !== undefined && v !== "" && v !== null)
    );
    const response = await api.get<ActivityPage>("/activity", { params });
    return response.data;
  },

  filters: async (): Promise<ActivityFilters> => {
    const response = await api.get<ActivityFilters>("/activity/filters");
    return response.data;
  },

  forTarget: async (
    targetType: string,
    targetId: string
  ): Promise<{ status: string; entries: ActivityEntry[] }> => {
    const response = await api.get(`/activity/for/${targetType}/${encodeURIComponent(targetId)}`);
    return response.data;
  },
};

export default api;
