import { createFileRoute } from '@tanstack/react-router';
import { MediaBrowserPage } from '@/components/pages/media-browser';

export const Route = createFileRoute('/_authenticated/media/$type')({
  component: MediaBrowserComponent,
});

function MediaBrowserComponent() {
  const { type } = Route.useParams();
  return <MediaBrowserPage mediaType={type} />;
}
