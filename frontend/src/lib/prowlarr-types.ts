/** Prowlarr, as DragonCP's server describes it. No download address, magnet
 *  address or guid ever reaches the page; a release is named by its search
 *  and its place in it. */

export type Protocol = "torrent" | "usenet" | "unknown";
export type SearchType = "search" | "tvsearch" | "movie" | "music" | "book";
export type Scope = "all" | "torrent" | "usenet" | "picked";

export interface ProwlarrIndexer {
  id: number;
  name: string;
  definition: string;
  protocol: Protocol;
  privacy: "public" | "private" | "semiprivate" | "unknown";
  enabled: boolean;
  priority: number | null;
  state: "ok" | "failing" | "paused" | "off";
  paused_until: string | null;
  failing_since: string | null;
  last_failure: string | null;
  site: string | null;
  categories: { id: number; name: string }[];
  search_types: SearchType[];
  stats: {
    queries: number;
    grabs: number;
    failed_queries: number;
    failed_grabs: number;
    avg_ms: number | null;
    failure_rate: number | null;
  } | null;
}

export interface ProwlarrHealth {
  source: string;
  level: "ok" | "notice" | "warning" | "error";
  message: string;
  wiki_url: string | null;
}

export interface ProwlarrClient {
  id: number;
  name: string;
  protocol: Protocol;
  enabled: boolean;
  priority: number | null;
  kind: string;
  /** Prowlarr's own category for this client, used when no mapping fits. */
  category: string;
  /** Release categories (Newznab ids) → the client category they go in. */
  mappings: { category: string; ids: number[] }[];
}

export type ArrApp = "sonarr" | "radarr";

/** An app that imports what lands in a category on a download client. */
export interface ArrWatcher {
  app: ArrApp;
  label: string;
  client: string;
  /** Completed-download handling is on in that app. */
  imports: boolean;
  /** Its client has no category, so it watches everything there. */
  everything: boolean;
  /** Its client is at the same address as Prowlarr's. False: only the same
   *  kind of client, so it may be another server. */
  verified: boolean;
}

export interface RouteClient {
  id: number;
  name: string;
  category: string;
  how: "mapped" | "default" | "none";
  watchers: ArrWatcher[];
}

/** What Sonarr or Radarr make of a release name. */
export interface ArrReading {
  app: ArrApp;
  label: string;
  state: "matched" | "unmatched" | "unreadable" | "error" | "off";
  title?: string;
  year?: number | null;
  read_as?: string;
  season?: number | null;
  episodes?: number[];
  absolute?: number[];
  full_season?: boolean;
  multi_season?: boolean;
  anime?: boolean;
  other_title?: boolean;
  /** Sonarr: episodes it found for the name; Radarr: absent. */
  found?: number;
  /** How many of those (or the film) are already in the library. */
  have?: number;
}

/** Where a sent release is in Sonarr or Radarr. */
export interface ArrTracking {
  app: ArrApp;
  label: string;
  state: "imported" | "queued" | "not_seen" | "error" | "off";
  verdict?: string;
  why?: string;
  known?: boolean;
  stuck?: boolean;
  progress?: number | null;
  message?: string;
}

export interface ReleaseRoute {
  connected: ArrApp[];
  family: ArrApp | null;
  clients: RouteClient[];
  readings: ArrReading[];
  sent: { client_id: number | null; at: string } | null;
  tracking: ArrTracking[];
}

export interface ProwlarrOverview {
  state: "ok" | "off" | "error";
  message?: string;
  version?: string | null;
  indexers?: ProwlarrIndexer[];
  health?: ProwlarrHealth[];
  download_clients?: ProwlarrClient[];
  stats_days?: number;
  stats_available?: boolean;
  read_at?: string;
  can_grab?: boolean;
  why_not?: string;
}

export interface SearchIndexerRow {
  id: number;
  name: string;
  protocol: Protocol;
  state: "waiting" | "done" | "failed" | "skipped";
  count: number;
  ms: number | null;
  error: string | null;
}

export interface ProwlarrRelease {
  id: number;
  title: string;
  size: number | null;
  published: string | null;
  grabs: number | null;
  files: number | null;
  seeders: number | null;
  leechers: number | null;
  protocol: Protocol;
  indexer_id: number | null;
  indexer: string;
  categories: string[];
  category_ids: number[];
  flags: string[];
  info_url: string | null;
  info_hash: string | null;
  imdb_id: number | null;
  tmdb_id: number | null;
  tvdb_id: number | null;
  can_download: boolean;
  can_magnet: boolean;
  grabbed: boolean;
}

export interface SearchPoll {
  id: string;
  query: string;
  type: SearchType;
  categories: number[];
  running: boolean;
  started: string;
  finished: string | null;
  indexers: SearchIndexerRow[];
  total: number;
  cursor: number;
  releases: ProwlarrRelease[];
  grabbed: number[];
}

export interface SearchRequest {
  query: string;
  type: SearchType;
  scope: Scope;
  indexer_ids?: number[];
  categories?: number[];
  season?: string;
  episode?: string;
  imdb_id?: string;
  tvdb_id?: string;
  tmdb_id?: string;
  fresh?: boolean;
}
