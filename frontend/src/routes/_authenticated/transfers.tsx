import { createFileRoute } from '@tanstack/react-router';
import { TransfersPage } from '@/components/pages/transfers';

export const Route = createFileRoute('/_authenticated/transfers')({
  component: TransfersPage,
});
