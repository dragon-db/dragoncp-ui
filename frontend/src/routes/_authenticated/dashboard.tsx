import { createFileRoute } from '@tanstack/react-router';
import { DashboardPage } from '@/components/pages/dashboard';

export const Route = createFileRoute('/_authenticated/dashboard')({
  component: DashboardPage,
});
