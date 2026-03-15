import { createFileRoute, redirect, Outlet } from '@tanstack/react-router';
import { useAuthStore } from '@/stores/auth';
import { AppLayout } from '@/components/layout/app-layout';
import { useRuntimeConnection } from '@/hooks/useRuntime';

export const Route = createFileRoute('/_authenticated')({
  beforeLoad: () => {
    const { isAuthenticated, token } = useAuthStore.getState();
    if (!isAuthenticated || !token) {
      throw redirect({ to: '/login' });
    }
  },
  component: AuthenticatedLayout,
});

function AuthenticatedLayout() {
  useRuntimeConnection();

  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  );
}
