import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { authApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { connectSocket, disconnectSocket } from '@/services/socket';

export function useLogin() {
  const login = useAuthStore((state) => state.login);
  const navigate = useNavigate();
  
  return useMutation({
    mutationFn: async ({ username, password }: { username: string; password: string }) => {
      const response = await authApi.login(username, password);
      if (response.status === 'error') {
        throw new Error(response.message || 'Login failed');
      }
      return response;
    },
    onSuccess: (data) => {
      if (data.token && data.refresh_token && data.user && data.expires_at) {
        login(data.token, data.refresh_token, data.user, data.expires_at);
        // Connect WebSocket after login
        connectSocket();
        navigate({ to: '/dashboard' });
      }
    },
  });
}

export function useLogout() {
  const logout = useAuthStore((state) => state.logout);
  const navigate = useNavigate();
  
  return useMutation({
    mutationFn: async () => {
      try {
        await authApi.logout();
      } catch (error) {
        // Even if logout fails on server, we still logout locally
        console.warn('Server logout failed:', error);
      }
    },
    onSettled: () => {
      disconnectSocket();
      logout();
      navigate({ to: '/login' });
    },
  });
}

export function useVerifyAuth() {
  const { token, isAuthenticated } = useAuthStore();
  
  return useQuery({
    queryKey: ['auth', 'verify'],
    queryFn: async () => {
      const response = await authApi.verify();
      return response;
    },
    enabled: !!token && isAuthenticated,
    staleTime: 1000 * 60 * 5, // 5 minutes
    refetchInterval: 1000 * 60 * 5, // Check every 5 minutes
  });
}

export function useAuthStatus() {
  return useQuery({
    queryKey: ['auth', 'status'],
    queryFn: async () => {
      const response = await authApi.status();
      return response;
    },
    staleTime: 1000 * 60 * 60, // 1 hour
  });
}
