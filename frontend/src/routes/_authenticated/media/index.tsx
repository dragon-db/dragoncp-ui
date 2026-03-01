import { createFileRoute, redirect } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/media/')({
  beforeLoad: () => {
    // Redirect to movies by default
    throw redirect({ to: '/media/$type', params: { type: 'movies' } });
  },
});
