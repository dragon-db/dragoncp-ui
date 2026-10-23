/**
 * Shapes returned by the rename endpoints (`/explore/rename`, `/explore/titles`,
 * `/explore/tmdb`). An episode still named TBA is "ready" when a real title is
 * waiting for it, "waiting" when nobody has one yet, and "skipped" when it
 * cannot be renamed safely; `reason` says why in words.
 */

export type RenameState = "ready" | "waiting" | "skipped";
export type TitleSource = "sonarr" | "tmdb";

export interface RenameSidecar {
  old: string;
  new: string;
  status?: string;
}

export interface RenameItem {
  /** Inside the series folder: `Season 01/<file>`. Quoted back to apply it. */
  path: string;
  season_folder: string;
  season: number | null;
  code: string;
  old_name: string;
  new_name: string | null;
  title: string | null;
  source: TitleSource | null;
  state: RenameState;
  reason: string;
  /** Subtitles, `.nfo` and artwork that take the new name with it. */
  sidecars: RenameSidecar[];
  sonarr_file_id: number | null;
  /** Sonarr still holds this file and is asked to rename its copy too. */
  sonarr_rename: boolean;
  /** Named from TMDB earlier; this replaces it with Sonarr's own title. */
  retitle: boolean;
  size: number;
}

export interface RenameSonarr {
  state: "found" | "missing" | "unavailable" | "off";
  series_id: number | null;
  title: string | null;
  message: string;
}

export interface RenameTmdb {
  state: "linked" | "unlinked" | "unavailable" | "off";
  tmdb_id: number | null;
  name: string;
  link_source: "manual" | "sonarr" | null;
}

export interface RenamePlan {
  media_type: string;
  folder: string;
  season: string | null;
  scope: string;
  items: RenameItem[];
  counts: {
    ready: number;
    waiting: number;
    skipped: number;
    sonarr_files: number;
    sidecars: number;
    from_tmdb: number;
  };
  sonarr: RenameSonarr;
  tmdb: RenameTmdb;
  /** Why a rename cannot run right now, or null. */
  blocker: string | null;
  /** True on a test instance: Rename rehearses, nothing changes. */
  test_mode: boolean;
}

export interface RenamedFile {
  previous_name: string;
  new_name: string;
  code: string;
  source: TitleSource | null;
  status: "success" | "failed";
  message: string;
  sidecars: RenameSidecar[];
  dry_run: boolean;
}

export interface RenameResult {
  notification_id: string;
  series_title: string;
  folder: string;
  /** How the run went; `status` on the reply is the request's own. */
  run_status: "completed" | "partial" | "failed";
  total_files: number;
  success_count: number;
  failed_count: number;
  renamed_files: RenamedFile[];
  sidecar_count: number;
  sonarr: { asked: boolean; ok: boolean | null; files: number; message: string };
  dry_run: boolean;
  message: string;
}

/** The last title check of one series: what Explore shows without asking Sonarr. */
export interface TitleStatus {
  state: "ready" | "waiting" | "not_in_sonarr" | "unknown" | "clear";
  ready: number;
  waiting: number;
  skipped: number;
  placeholders: number;
  checked_at: string | null;
  message: string;
  seasons: Record<string, { ready: number; waiting: number; skipped: number }>;
  tmdb: Partial<RenameTmdb>;
  sonarr: Partial<RenameSonarr>;
}

/** What the last check proposed for one file. */
export interface TitleProposal {
  code: string;
  season_folder: string;
  old_name: string;
  new_name: string | null;
  state: RenameState;
  reason: string;
  source: TitleSource | null;
  retitle: boolean;
}

export interface RenameAllPlan {
  media_type: string;
  series: Array<{ folder: string; checked_at: string | null; items: TitleProposal[] }>;
  files: number;
  running: boolean;
  test_mode: boolean;
}

export interface TmdbShow {
  tmdb_id: number;
  name: string;
  year: number | null;
  first_air_date: string | null;
  overview: string;
  poster_path: string | null;
}

export interface TmdbLink {
  tmdb_id: number;
  tmdb_name: string;
  tmdb_year: number | null;
  source: "manual" | "sonarr";
}

export interface TmdbSearch {
  query: string;
  results: TmdbShow[];
  linked: TmdbLink | null;
}

/** `rename_progress` while Rename all works through a library. */
export interface RenameProgress {
  media_type: string;
  done: number;
  total: number;
  last: { folder: string; ok: boolean; renamed?: number; failed?: number; message?: string };
}

/** `rename_library_finished`: Rename all is done. */
export interface RenameLibraryFinished {
  media_type: string;
  renamed: number;
  series: number;
  failed: Array<{ folder: string; message?: string; failed?: number }>;
  dry_run: boolean;
}

/**
 * How many files a tag should count, for a series or one of its seasons.
 *
 * Two sources: the last walk of the library (free, but only as fresh as that
 * walk) and the last title check (updated by every rename and Undo). Whichever
 * is newer answers, so a tag goes the moment a rename finishes and comes back
 * when a sync brings in another TBA episode.
 */
export function titleCounts(
  fromWalk: number | undefined,
  status: TitleStatus | undefined,
  walkedAt: string | null | undefined,
  season?: string
): { count: number; ready: number } {
  const walk = fromWalk ?? 0;
  if (!status) return { count: walk, ready: 0 };
  const checked = status.checked_at ? Date.parse(status.checked_at) : NaN;
  const walked = walkedAt ? Date.parse(walkedAt) : NaN;
  const part = season ? status.seasons[season] : undefined;
  const fromCheck = season
    ? part
      ? part.ready + part.waiting + part.skipped
      : 0
    : status.placeholders;
  const ready = season ? (part?.ready ?? 0) : status.ready;
  if (!Number.isNaN(walked) && !Number.isNaN(checked) && walked > checked) {
    return { count: walk, ready: walk > 0 ? ready : 0 };
  }
  return { count: fromCheck, ready };
}
