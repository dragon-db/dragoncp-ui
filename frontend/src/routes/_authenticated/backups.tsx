import { createFileRoute } from '@tanstack/react-router';
import { BackupsPage } from '@/components/pages/backups';

export const Route = createFileRoute('/_authenticated/backups')({
  component: BackupsPage,
});
