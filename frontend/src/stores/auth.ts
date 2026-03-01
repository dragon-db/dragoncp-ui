import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: string | null;
  isAuthenticated: boolean;
  expiresAt: string | null;
  login: (token: string, refreshToken: string, user: string, expiresAt: string) => void;
  logout: () => void;
  updateToken: (token: string, expiresAt: string) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      expiresAt: null,
      
      login: (token, refreshToken, user, expiresAt) => set({
        token,
        refreshToken,
        user,
        isAuthenticated: true,
        expiresAt,
      }),
      
      logout: () => set({
        token: null,
        refreshToken: null,
        user: null,
        isAuthenticated: false,
        expiresAt: null,
      }),
      
      updateToken: (token, expiresAt) => set({
        token,
        expiresAt,
      }),
    }),
    {
      name: 'dragoncp-auth',
      partialize: (state) => ({
        token: state.token,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        expiresAt: state.expiresAt,
      }),
    }
  )
);

// Utility function to check if token is expired
export function isTokenExpired(): boolean {
  const { expiresAt } = useAuthStore.getState();
  if (!expiresAt) return true;
  
  const expiry = new Date(expiresAt);
  const now = new Date();
  // Consider expired if less than 5 minutes remaining
  return expiry.getTime() - now.getTime() < 5 * 60 * 1000;
}

// Utility function to check if token needs refresh
export function shouldRefreshToken(): boolean {
  const { expiresAt } = useAuthStore.getState();
  if (!expiresAt) return false;
  
  const expiry = new Date(expiresAt);
  const now = new Date();
  // Refresh if less than 30 minutes remaining
  return expiry.getTime() - now.getTime() < 30 * 60 * 1000;
}
