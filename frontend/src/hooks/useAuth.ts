import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { authApi, errorMessageFrom, type LoginResponse } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";
import { destroySocket, reAuthenticateSocket } from "@/services/socket";

/** Turn a successful sign-in or password change into the stored session. */
function identityFrom(data: LoginResponse) {
  return {
    token: data.token!,
    refreshToken: data.refresh_token!,
    user: data.user!,
    expiresAt: data.expires_at!,
    accountId: data.account_id ?? null,
    role: data.role,
    mustChangePassword: data.must_change_password ?? false,
    isFallbackAccount: data.is_fallback_account ?? false,
  };
}

export function useLogin() {
  const login = useAuthStore((state) => state.login);
  const navigate = useNavigate();

  return useMutation({
    mutationFn: async ({ username, password }: { username: string; password: string }) => {
      try {
        const response = await authApi.login(username, password);
        if (response.status === "error") {
          throw new Error(response.message || "Login failed");
        }
        return response;
      } catch (error) {
        // A wrong password, a disabled account and a throttled attempt all
        // arrive as failed requests. The server explains which; pass that on.
        throw new Error(errorMessageFrom(error, "Login failed"));
      }
    },
    onSuccess: (data) => {
      if (data.token && data.refresh_token && data.user && data.expires_at) {
        login(identityFrom(data));
        navigate({ to: "/dashboard" });
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
        console.warn("Server logout failed:", error);
      }
    },
    onSettled: () => {
      destroySocket();
      logout();
      navigate({ to: "/login" });
    },
  });
}

/**
 * Change your own password.
 *
 * The server retires every token this account held, so it returns a fresh pair
 * for this browser to adopt. Without swapping them in, succeeding would bounce
 * the person straight back to the sign-in screen.
 */
export function useChangePassword() {
  const updateSession = useAuthStore((state) => state.updateSession);

  return useMutation({
    mutationFn: async ({
      currentPassword,
      newPassword,
    }: {
      currentPassword: string;
      newPassword: string;
    }) => {
      try {
        const response = await authApi.changePassword(currentPassword, newPassword);
        if (response.status === "error") {
          throw new Error(response.message || "Could not change the password");
        }
        return response;
      } catch (error) {
        throw new Error(errorMessageFrom(error, "Could not change the password"));
      }
    },
    onSuccess: (data) => {
      if (data.token && data.refresh_token && data.user && data.expires_at) {
        updateSession(identityFrom(data));
        reAuthenticateSocket();
      }
    },
  });
}

export function useVerifyAuth() {
  const { token, isAuthenticated } = useAuthStore();
  const setMustChangePassword = useAuthStore((state) => state.setMustChangePassword);

  return useQuery({
    queryKey: ["auth", "verify"],
    queryFn: async () => {
      const response = await authApi.verify();
      if (response.valid) {
        setMustChangePassword(response.must_change_password ?? false);
      }
      return response;
    },
    enabled: !!token && isAuthenticated,
    staleTime: 1000 * 60 * 5, // 5 minutes
    refetchInterval: 1000 * 60 * 5, // Check every 5 minutes
  });
}

export function useAuthStatus() {
  return useQuery({
    queryKey: ["auth", "status"],
    queryFn: async () => {
      const response = await authApi.status();
      return response;
    },
    staleTime: 1000 * 60 * 60, // 1 hour
  });
}
