/** Seerr, as DragonCP's server hands it over (`/api/seerr/*`). */

export type Tone = "ok" | "warn" | "crit" | "brand" | "info" | "muted";

export interface SeerrPerson {
  id: number;
  name: string;
}

export interface SeerrTitle {
  tmdb_id: number | null;
  tvdb_id: number | null;
  type: "movie" | "tv";
  name: string;
  year: number | null;
  poster: string;
}

export type StageKey =
  | "waiting"
  | "declined"
  | "failed"
  | "removed"
  | "in_jellyfin"
  | "held"
  | "syncing"
  | "downloading"
  | "arrived"
  | "sync_failed"
  | "partly"
  | "synced"
  | "searching";

export interface RequestStage {
  key: StageKey;
  label: string;
  tone: Tone;
  detail: string;
  percent?: number | null;
  stuck?: boolean;
}

export type StepKey = "approved" | "download" | "sync" | "jellyfin";
export type StepState = "done" | "active" | "waiting" | "problem" | "todo";

export interface RequestStep {
  key: StepKey;
  state: StepState;
}

export interface RequestSeason {
  number: number;
  /** available | partial | processing | pending | deleted | waiting */
  state: string;
  episodes_total: number | null;
  episodes_here: number | null;
  downloading: boolean;
  syncing: boolean;
}

export interface SeerrRequest {
  id: number;
  status: "pending" | "approved" | "declined" | "failed" | "completed" | "unknown";
  type: "movie" | "tv";
  is4k: boolean;
  title: SeerrTitle;
  jellyfin_id: string | null;
  seasons: RequestSeason[];
  requested_by: SeerrPerson | null;
  requested_at: string | null;
  decided_by: SeerrPerson | null;
  updated_at: string | null;
  profile: string | null;
  stage: RequestStage;
  steps: RequestStep[];
  actions: ("approve" | "decline" | "retry")[];
}

export interface SeerrListState {
  state: "ok" | "off" | "unreachable";
  message: string;
  total: number;
  can_change: boolean;
  why_not: string;
}

export interface RequestsPage extends SeerrListState {
  requests: SeerrRequest[];
}

export interface SeerrComment {
  id: number;
  by: SeerrPerson | null;
  message: string;
  at: string | null;
}

export type IssueType = "video" | "audio" | "subtitles" | "other";

export interface SeerrIssue {
  id: number;
  type: IssueType;
  status: "open" | "resolved";
  title: SeerrTitle;
  jellyfin_id: string | null;
  season: number | null;
  episode: number | null;
  reported_by: SeerrPerson | null;
  reported_at: string | null;
  updated_at: string | null;
  modified_by: SeerrPerson | null;
  message: string;
  replies: number;
  comments: SeerrComment[];
}

export interface IssuesPage extends SeerrListState {
  issues: SeerrIssue[];
}

export interface SeerrSummary {
  state: "ok" | "off" | "unreachable";
  message: string;
  requests: {
    pending: number;
    processing: number;
    approved: number;
    declined: number;
    completed: number;
    available: number;
    total: number;
    movie: number;
    tv: number;
  } | null;
  issues: {
    open: number;
    closed: number;
    total: number;
    video: number;
    audio: number;
    subtitles: number;
    others: number;
  } | null;
  can_change: boolean;
  why_not: string;
  test_mode: boolean;
  polling: boolean;
  webhook: {
    password_set: boolean;
    last_at: string | null;
    last_type: string | null;
    path: string;
  };
}

export interface RequestOptions {
  service: "sonarr" | "radarr";
  servers: { id: number; name: string; is_default: boolean }[];
  server_id: number | null;
  profiles: { id: number; name: string }[];
  root_folders: { path: string; free_bytes: number | null }[];
  current: { profile_id: number | null; root_folder: string | null };
  seasons: { number: number; episodes: number | null; requested: boolean; available: boolean }[];
}

export interface RequestChanges {
  server_id?: number;
  profile_id?: number;
  root_folder?: string;
  seasons?: number[];
}
