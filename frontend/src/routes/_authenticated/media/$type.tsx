import { createFileRoute } from "@tanstack/react-router";
import { ExplorePage } from "@/components/pages/explore";

export const Route = createFileRoute("/_authenticated/media/$type")({
  component: ExploreComponent,
});

function ExploreComponent() {
  const { type } = Route.useParams();
  // Keying on the library throws away the open series, season, expanded rows
  // and ticked files when you switch. A TV series has no meaning inside Anime,
  // and carrying it over left the file list empty with no way back.
  return <ExplorePage key={type} mediaType={type} />;
}
