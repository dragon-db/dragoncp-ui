import { createFileRoute } from "@tanstack/react-router";
import { ExplorePage } from "@/components/pages/explore";

/**
 * `series` and `season` open Explore on one folder. A Sonarr or Radarr title's
 * panel links here to fetch only what is missing, when syncing the whole season
 * folder would also remove the episodes kept only here.
 */
interface ExploreSearch {
  series?: string;
  season?: string;
}

/**
 * What Explore calls a film's own list of files — a folder with no seasons
 * (`display_name` in `services/explore/compare.py`). A link that names a film
 * opens straight on it, as clicking the film in the tree does.
 */
const MOVIE_FILES = "Files";

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

export const Route = createFileRoute("/_authenticated/media/$type")({
  validateSearch: (search: Record<string, unknown>): ExploreSearch => ({
    series: text(search.series),
    season: text(search.season),
  }),
  component: ExploreComponent,
});

function ExploreComponent() {
  const { type } = Route.useParams();
  const { series, season } = Route.useSearch();
  const initialSeason = season ?? (type === "movies" && series ? MOVIE_FILES : undefined);
  // Keying on the library throws away the open series, season, expanded rows
  // and ticked files when you switch. A TV series has no meaning inside Anime,
  // and carrying it over left the file list empty with no way back. A link to
  // another folder starts afresh the same way.
  return (
    <ExplorePage
      key={`${type}|${series ?? ""}|${initialSeason ?? ""}`}
      mediaType={type}
      initialSeries={series}
      initialSeason={series ? initialSeason : undefined}
    />
  );
}
