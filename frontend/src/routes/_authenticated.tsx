import { createFileRoute, redirect, Outlet } from '@tanstack/react-router';
import { useAuthStore } from '@/stores/auth';
import { useEffect } from 'react';
import { connectSocket, disconnectSocket } from '@/services/socket';
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
  const { isAuthenticated } = useAuthStore();
  useRuntimeConnection();

  useEffect(() => {
    if (isAuthenticated) {
      connectSocket();
    }

    return () => {
      disconnectSocket();
    };
  }, [isAuthenticated]);

  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  );
}
