import { createFileRoute } from '@tanstack/react-router';
import { WebhooksPage } from '@/components/pages/webhooks';

export const Route = createFileRoute('/_authenticated/webhooks')({
  component: WebhooksPage,
});
