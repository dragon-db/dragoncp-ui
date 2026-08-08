import { createFileRoute, redirect, Outlet } from "@tanstack/react-router";
import { useAuthStore } from "@/stores/auth";
import { AppLayout } from "@/components/layout/app-layout";
import { PasswordChangeGate } from "@/components/auth/password-change-gate";
import { useRuntimeConnection } from "@/hooks/useRuntime";

export const Route = createFileRoute("/_authenticated")({
  beforeLoad: () => {
    const { isAuthenticated, token } = useAuthStore.getState();
    if (!isAuthenticated || !token) {
      throw redirect({ to: "/login" });
    }
  },
  component: AuthenticatedLayout,
});

function AuthenticatedLayout() {
  const mustChangePassword = useAuthStore((state) => state.mustChangePassword);

  // Checked here rather than at sign-in so it survives a page reload and cannot
  // be stepped around by navigating straight to a page. The live connection is
  // deliberately not opened until the password has been replaced.
  if (mustChangePassword) {
    return <PasswordChangeGate />;
  }

  return <AuthenticatedApp />;
}

function AuthenticatedApp() {
  useRuntimeConnection();

  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  );
}
