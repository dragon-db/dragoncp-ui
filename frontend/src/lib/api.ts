import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { useAuthStore, shouldRefreshToken } from '@/stores/auth';
import { destroySocket, reAuthenticateSocket } from '@/services/socket';

// Create axios instance
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
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
          `${import.meta.env.VITE_API_URL || '/api'}/auth/refresh`,
          { refresh_token: refreshToken }
        );
        
        if (response.data.token) {
          useAuthStore.getState().updateToken(
            response.data.token,
            response.data.expires_at
          );
          reAuthenticateSocket();
        }
      } catch (error) {
        // If refresh fails, continue with current token
        console.warn('Token refresh failed:', error);
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
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Token is invalid or expired, logout user
      destroySocket();
      useAuthStore.getState().logout();
      
      // Redirect to login page if not already there
      if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// API response types
export interface ApiResponse<T = unknown> {
  status: 'success' | 'error';
  message?: string;
  data?: T;
}

export interface LoginResponse {
  status: 'success' | 'error';
  message?: string;
  token?: string;
  refresh_token?: string;
  expires_at?: string;
  refresh_expires_at?: string;
  user?: string;
  code?: string;
}

export interface VerifyResponse {
  status: 'success' | 'error';
  valid: boolean;
  user?: string;
  remaining_seconds?: number;
  message?: string;
}

// Auth API functions
export const authApi = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const response = await api.post<LoginResponse>('/auth/login', { username, password });
    return response.data;
  },
  
  logout: async (): Promise<ApiResponse> => {
    const response = await api.post<ApiResponse>('/auth/logout');
    return response.data;
  },
  
  verify: async (): Promise<VerifyResponse> => {
    const response = await api.get<VerifyResponse>('/auth/verify');
    return response.data;
  },
  
  refresh: async (refreshToken: string): Promise<LoginResponse> => {
    const response = await api.post<LoginResponse>('/auth/refresh', { refresh_token: refreshToken });
    return response.data;
  },
  
  status: async (): Promise<{ auth_configured: boolean }> => {
    const response = await api.get('/auth/status');
    return response.data;
  },
};

export default api;
