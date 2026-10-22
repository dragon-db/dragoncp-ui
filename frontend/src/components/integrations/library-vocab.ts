/**
 * The words, tones and icons of the Sonarr and Radarr Library, Queue and
 * History tabs — kept out of the component files so they export components
 * only, which fast refresh needs.
 *
 * Status follows the app's four notes and nothing else: emerald for in sync or
 * finished, brand for something moving, amber for something a person may need
 * to look at, rose for a failure; muted for a fact that is no verdict at all.
 * One addition: sky for an upgrade waiting, the colour the dry run and Explore
 * give a file with a newer version on the other side.
 * Every state carries an icon and a word beside its colour.
 */

import type { ComponentType } from "react";
import {
  IconAlertTriangle,
  IconArchive,
  IconCircleArrowUp,
  IconCircleCheck,
  IconCircleDashed,
  IconCircleX,
  IconCloudDownload,
  IconDownload,
  IconEyeOff,
  IconFolderExclamation,
  IconFolderOff,
  IconFolderQuestion,
  IconHelpCircle,
  IconPencil,
  IconTool,
  IconTrash,
} from "@tabler/icons-react";
import type {
  EpisodeState,
  HistoryEvent,
  LibraryAttention,
  LibraryItem,
  LibraryState,
} from "@/hooks/useMediaLibrary";

type Icon = ComponentType<{ className?: string }>;

export type Tone = "ok" | "warn" | "crit" | "brand" | "info" | "muted";

export const TONE_CHIP: Record<Tone, string> = {
  ok: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/15 text-amber-400",
  crit: "border-rose-500/40 bg-rose-500/15 text-rose-400",
  brand: "border-brand/40 bg-brand/15 text-brand-foreground",
  info: "border-sky-500/40 bg-sky-500/15 text-sky-300",
  muted: "border-border bg-muted/40 text-muted-foreground",
};

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-emerald-400",
  warn: "text-amber-400",
  crit: "text-rose-400",
  brand: "text-brand-hover",
  info: "text-sky-300",
  muted: "text-muted-foreground",
};

/** A progress bar's fill. In progress is brand, never blue or green. */
export const TONE_BAR: Record<Tone, string> = {
  ok: "bg-emerald-500/70",
  warn: "bg-amber-500/75",
  crit: "bg-rose-500/75",
  brand: "bg-brand-gradient-x",
  info: "bg-sky-500/70",
  muted: "bg-muted-foreground/40",
};

// -- a title ---------------------------------------------------------------------

export interface StateInfo {
  label: string;
  tone: Tone;
  icon: Icon;
  /** What the word means, for a tooltip, where the word alone could puzzle. */
  hint?: string;
}

export const TITLE_STATE: Record<LibraryState, StateInfo> = {
  out_of_sync: { label: "Out of sync", tone: "warn", icon: IconAlertTriangle },
  // Explore's word for the same thing: everything is here, but a file sits in
  // a nested folder the media server cannot see.
  needs_repair: {
    label: "Needs repair",
    tone: "warn",
    icon: IconTool,
    hint: "Everything is here, but a file sits inside a nested folder your media server cannot see. Repair it in Explore.",
  },
  in_sync: { label: "In sync", tone: "ok", icon: IconCircleCheck },
  // Kept-here is the media server having cleaned up after a sync: in sync, on
  // purpose, with only a quiet note that more is kept here.
  kept_here: { label: "In sync", tone: "ok", icon: IconCircleCheck },
  never: { label: "Not here", tone: "muted", icon: IconFolderOff },
  no_files: { label: "No files yet", tone: "muted", icon: IconCircleDashed },
  orphan: { label: "Unlisted", tone: "muted", icon: IconFolderQuestion },
  unknown: { label: "Unknown", tone: "muted", icon: IconHelpCircle },
};

export function titleState(state: string | undefined): StateInfo {
  return TITLE_STATE[(state ?? "unknown") as LibraryState] ?? TITLE_STATE.unknown;
}

/** The order "needs attention first" sorts by. */
export const STATE_RANK: Record<LibraryState, number> = {
  out_of_sync: 0,
  needs_repair: 0,
  in_sync: 1,
  kept_here: 1,
  never: 2,
  orphan: 3,
  unknown: 4,
  no_files: 5,
};

/**
 * The reasons that mean an upgrade is waiting: a newer file imported since the
 * last sync, or the service's file differing from the one here.
 */
const UPGRADE_KINDS = new Set(["new_file", "different"]);

/** Whether this title has an upgrade waiting to be synced. */
export function hasUpgrade(item: LibraryItem): boolean {
  return (
    item.sync_state === "out_of_sync" &&
    (item.attention ?? []).some((entry) => UPGRADE_KINDS.has(entry.kind))
  );
}

/** Whether some of this title's files sit in a nested folder, whatever its state. */
export function hasNested(item: LibraryItem): boolean {
  return (item.attention ?? []).some((entry) => entry.kind === "nested");
}

/** The Library's filter chips, out of sync first. */
export const LIBRARY_FILTERS: Array<{ value: string; label: string; states: LibraryState[] }> = [
  { value: "out_of_sync", label: "Out of sync", states: ["out_of_sync"] },
  { value: "in_sync", label: "In sync", states: ["in_sync", "kept_here"] },
  { value: "never", label: "Not here", states: ["never"] },
  { value: "orphan", label: "Unlisted", states: ["orphan"] },
  { value: "no_files", label: "No files yet", states: ["no_files"] },
  { value: "unknown", label: "Unknown", states: ["unknown"] },
];

// -- an episode --------------------------------------------------------------------

/**
 * An episode's state on the series view: an icon and a word. Only what needs
 * doing is coloured (amber); a settled episode, one kept only here and one
 * nobody has downloaded read quiet, so the eye lands on the rows to act on.
 */
export const EPISODE_STATE: Record<EpisodeState, StateInfo> = {
  missing_here: {
    label: "Not here",
    tone: "warn",
    icon: IconCloudDownload,
    hint: "The service has this file and this disk does not.",
  },
  different: {
    label: "Upgrade",
    tone: "info",
    icon: IconCircleArrowUp,
    hint: "Both have this episode, but the service holds a different file — usually an upgrade.",
  },
  nested: {
    label: "Nested",
    tone: "warn",
    icon: IconFolderExclamation,
    hint: "Here, but inside a nested folder your media server cannot see. Repair it in Explore; copying it again would not help.",
  },
  in_sync: {
    label: "Here",
    tone: "muted",
    icon: IconCircleCheck,
    hint: "The same file is on the service and on this disk.",
  },
  only_here: {
    label: "Only here",
    tone: "muted",
    icon: IconArchive,
    hint: "The service no longer has this file, which is normal once it is removed there after syncing. The copy here is kept.",
  },
  not_downloaded: {
    label: "Not downloaded",
    tone: "muted",
    icon: IconCircleDashed,
    hint: "Neither the service nor this disk has a file for it.",
  },
};

// -- history ------------------------------------------------------------------------

export const HISTORY_EVENT: Record<HistoryEvent, StateInfo> = {
  imported: { label: "Imported", tone: "ok", icon: IconDownload },
  grabbed: { label: "Grabbed", tone: "brand", icon: IconCloudDownload },
  deleted: { label: "Deleted", tone: "muted", icon: IconTrash },
  failed: { label: "Failed", tone: "crit", icon: IconCircleX },
  renamed: { label: "Renamed", tone: "muted", icon: IconPencil },
  ignored: { label: "Ignored", tone: "muted", icon: IconEyeOff },
  other: { label: "Other", tone: "muted", icon: IconHelpCircle },
};

export const HISTORY_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "All" },
  { value: "imported", label: "Imported" },
  { value: "grabbed", label: "Grabbed" },
  { value: "deleted", label: "Deleted" },
  { value: "failed", label: "Failed" },
  { value: "renamed", label: "Renamed" },
];

// -- words for numbers and time ------------------------------------------------------

/** "1.4 GB", "820 MB", "size unknown" when there is no size to show. */
export function formatSize(bytes?: number | null): string {
  if (!bytes) return "size unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 100 || unit < 2 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** "just now", "5 min ago", "3 h ago", "2 days ago". */
export function sinceText(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const seconds = (now - then) / 1000;
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  const days = Math.round(seconds / 86400);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** Date and time in the reader's own locale, for a tooltip beside `sinceText`. */
export function stampText(iso: string | null | undefined): string {
  if (!iso) return "";
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return "";
  return moment.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** An air date: "Oct 4, 2026", or "airs Oct 12" when it is still to come. */
export function airText(date: string | null | undefined): string {
  if (!date) return "";
  const moment = new Date(`${date}T12:00:00`);
  if (Number.isNaN(moment.getTime())) return date;
  const words = moment.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return moment.getTime() > Date.now() ? `airs ${words}` : words;
}

/** "12 s", "4 min", "2 h 10 min" — a download's time left. */
export function spanText(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours >= 48) return `${Math.round(hours / 24)} days`;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

function plural(count: number, word: string, many?: string) {
  return `${count} ${count === 1 ? word : (many ?? `${word}s`)}`;
}

function codes(list: string[] | undefined, limit = 3) {
  if (!list?.length) return "";
  if (list.length <= limit) return list.join(", ");
  return `${list.slice(0, limit).join(", ")} and ${list.length - limit} more`;
}

/** One reason a title is out of sync, in a sentence. */
export function attentionText(entry: LibraryAttention, service: string): string {
  const when = sinceText(entry.imported_at);
  const seasonWord = entry.season_number ? `season ${entry.season_number}` : "";
  switch (entry.kind) {
    case "new_import":
      return `${plural(entry.count, "new episode")} on ${service}${
        entry.episodes?.length ? ` (${codes(entry.episodes)})` : ""
      }${when ? `, imported ${when}` : ""}`;
    case "new_file":
      return `${entry.count === 1 ? "A newer file" : `${entry.count} newer files`} on ${service}${
        entry.episodes?.length ? ` for ${codes(entry.episodes)}` : ""
      }${when ? `, imported ${when}` : ""}`;
    case "short":
      return `${service} has ${entry.theirs} episode files for ${seasonWord}, ${entry.ours} here`;
    case "season_not_here":
      return `${seasonWord.charAt(0).toUpperCase()}${seasonWord.slice(1)} is not here; ${service} has ${entry.theirs}`;
    // Found by size: the service's files for the season are not among the
    // files here. Which episode it is shows once the title is opened.
    case "not_matching":
      return entry.theirs === 1
        ? `${service} has a file for ${seasonWord} that is not here`
        : `Not all of ${service}'s ${entry.theirs} files for ${seasonWord} are here`;
    case "missing":
      return `${plural(entry.count, "episode")} on ${service} not here yet: ${codes(entry.episodes)}`;
    case "nested":
      if (entry.episodes?.length === 1 && entry.count === 1) {
        return `${entry.episodes[0]} is here, but inside a nested folder`;
      }
      return entry.season_number === null
        ? "The film is here, but inside a nested folder"
        : `${plural(entry.count, "file")} in ${seasonWord} ${entry.count === 1 ? "is" : "are"} inside a nested folder`;
    case "different":
      return entry.episodes?.length
        ? `${entry.count === 1 ? "An upgrade" : `${entry.count} upgrades`} on ${service}: ${codes(entry.episodes)}`
        : `An upgrade on ${service}: a different file${
            entry.quality ? ` (${entry.quality}, ${formatSize(entry.size)})` : ""
          }`;
    default:
      return "";
  }
}

/** The card's tooltip and the panel's fallback: why a title reads as it does. */
export function itemSentence(item: LibraryItem, service: string): string {
  if (
    (item.sync_state === "out_of_sync" || item.sync_state === "needs_repair") &&
    item.attention?.length
  ) {
    const first = attentionText(item.attention[0], service);
    const more = item.attention.length - 1;
    return more > 0 ? `${first}, and ${more} more` : first;
  }
  if (item.sync_state === "kept_here" && item.kept_here_count > 0) {
    return `Everything ${service} holds is here. ${plural(item.kept_here_count, "more episode")} ${
      item.kept_here_count === 1 ? "is" : "are"
    } kept only here, which is normal once the media server removes its copies after a sync.`;
  }
  return item.state_reason;
}

/**
 * A failed request's own explanation. The library endpoints answer
 * `{success, error}`; most of the app answers `{status, message}`.
 */
export function libraryError(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: string; message?: string } } })?.response
    ?.data;
  return data?.error || data?.message || fallback;
}
