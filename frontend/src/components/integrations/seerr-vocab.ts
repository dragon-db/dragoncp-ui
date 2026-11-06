import type { ComponentType } from "react";
import { IconBadgeCc, IconHelpCircle, IconMovie, IconVolume } from "@tabler/icons-react";
import type { IssueType, SeerrTitle, StepKey } from "@/lib/seerr-types";

/** The four steps an approved request goes through, as a person says them. */
export const STEP_LABELS: Record<StepKey, string> = {
  approved: "Approved",
  download: "On the remote server",
  sync: "Synced here",
  jellyfin: "In Jellyfin",
};

export const ISSUE_TYPES: Record<
  IssueType,
  { label: string; icon: ComponentType<{ className?: string }> }
> = {
  video: { label: "Video", icon: IconMovie },
  audio: { label: "Audio", icon: IconVolume },
  subtitles: { label: "Subtitles", icon: IconBadgeCc },
  other: { label: "Other", icon: IconHelpCircle },
};

/** What Seerr's webhook last said, in words. */
export const WEBHOOK_EVENTS: Record<string, string> = {
  MEDIA_PENDING: "a new request",
  MEDIA_APPROVED: "a request approved",
  MEDIA_AUTO_APPROVED: "a request approved automatically",
  MEDIA_AUTO_REQUESTED: "an automatic request",
  MEDIA_AVAILABLE: "a request now available",
  MEDIA_FAILED: "a request that failed",
  MEDIA_DECLINED: "a request declined",
  ISSUE_CREATED: "a new issue",
  ISSUE_COMMENT: "a comment on an issue",
  ISSUE_RESOLVED: "an issue resolved",
  ISSUE_REOPENED: "an issue reopened",
  TEST_NOTIFICATION: "the test",
};

/** A title's name, or what it is when Seerr could not name it. */
export function titleName(title: SeerrTitle): string {
  if (title.name) return title.name;
  return title.type === "movie"
    ? `A film (TMDB ${title.tmdb_id ?? "?"})`
    : `A series (TMDB ${title.tmdb_id ?? "?"})`;
}

/** "Season 2", "Seasons 1–3, 5". */
export function seasonList(numbers: number[]): string {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b);
  if (!sorted.length) return "";
  const runs: string[] = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (const n of [...sorted.slice(1), Number.NaN]) {
    if (n === prev + 1) {
      prev = n;
      continue;
    }
    runs.push(start === prev ? `${start}` : `${start}–${prev}`);
    start = n;
    prev = n;
  }
  return `${sorted.length === 1 ? "Season" : "Seasons"} ${runs.join(", ")}`;
}

/** Bytes as a person reads free space: "1.8 TB free". */
export function freeSpace(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]} free`;
}
