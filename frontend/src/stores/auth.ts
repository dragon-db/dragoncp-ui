import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface SessionIdentity {
  token: string;
  refreshToken: string;
  user: string;
  expiresAt: string;
  accountId?: number | null;
  role?: string;
  mustChangePassword?: boolean;
  isFallbackAccount?: boolean;
}

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: string | null;
  isAuthenticated: boolean;
  expiresAt: string | null;
  /**
   * The account's stable id. Usernames can be renamed, so anything that needs
   * to refer to a person across a rename refers to this instead.
   */
  accountId: number | null;
  role: string | null;
  /**
   * Set when the password was chosen by whoever created the account rather than
   * by the person using it. The app holds them at the change-password screen
   * until they pick their own.
   */
  mustChangePassword: boolean;
  /**
   * Signed in with the credentials from the server's environment file, because
   * no real account exists yet. Such a session cannot change its own password.
   */
  isFallbackAccount: boolean;
  login: (identity: SessionIdentity) => void;
  logout: () => void;
  updateToken: (token: string, expiresAt: string) => void;
  updateSession: (identity: SessionIdentity) => void;
  setMustChangePassword: (value: boolean) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      expiresAt: null,
      accountId: null,
      role: null,
      mustChangePassword: false,
      isFallbackAccount: false,

      login: (identity) =>
        set({
          token: identity.token,
          refreshToken: identity.refreshToken,
          user: identity.user,
          isAuthenticated: true,
          expiresAt: identity.expiresAt,
          accountId: identity.accountId ?? null,
          role: identity.role ?? null,
          mustChangePassword: identity.mustChangePassword ?? false,
          isFallbackAccount: identity.isFallbackAccount ?? false,
        }),

      logout: () =>
        set({
          token: null,
          refreshToken: null,
          user: null,
          isAuthenticated: false,
          expiresAt: null,
          accountId: null,
          role: null,
          mustChangePassword: false,
          isFallbackAccount: false,
        }),

      updateToken: (token, expiresAt) =>
        set({
          token,
          expiresAt,
        }),

      // Changing a password retires every token the account had, including the
      // one in this browser, so the server hands back a fresh pair to adopt.
      updateSession: (identity) =>
        set({
          token: identity.token,
          refreshToken: identity.refreshToken,
          user: identity.user,
          isAuthenticated: true,
          expiresAt: identity.expiresAt,
          accountId: identity.accountId ?? null,
          role: identity.role ?? null,
          mustChangePassword: identity.mustChangePassword ?? false,
          isFallbackAccount: identity.isFallbackAccount ?? false,
        }),

      setMustChangePassword: (value) => set({ mustChangePassword: value }),
    }),
    {
      name: "dragoncp-auth",
      partialize: (state) => ({
        token: state.token,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        expiresAt: state.expiresAt,
        accountId: state.accountId,
        role: state.role,
        mustChangePassword: state.mustChangePassword,
        isFallbackAccount: state.isFallbackAccount,
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
