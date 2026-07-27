import type { WebhookEpisode, WebhookEpisodeFile, WebhookNotification } from "@/lib/api-types";

/**
 * Grouping + presentation helpers for webhook notifications.
 *
 * Behaviour mirrors the original UI (static/modules/webhook-manager.js):
 * series/anime notifications collapse into one row per show + season, movies
 * stay standalone, and a group takes the most urgent status of its episodes.
 * Shared by the Webhooks page and the dashboard rail so both read the same.
 */

export interface WebhookItem {
  /** Stable key: `${slug}_S${season}` for groups, notification id for singles. */
  key: string;
  isGroup: boolean;
  title: string;
  mediaType: string;
  seasonNumber: number | null;
  year?: number;
  quality?: string;
  posterUrl?: string;
  requestedBy?: string;
  /** Most recent notification timestamp in the item. */
  createdAt?: string;
  notifications: WebhookNotification[];
}

const SERIES_TYPES = new Set(["series", "tvshows", "anime"]);

export function isSeries(mediaType?: string): boolean {
  return SERIES_TYPES.has(mediaType || "movie");
}

/** Show title without the "Season N" suffix the API appends to display_title. */
export function itemTitle(notification: WebhookNotification): string {
  if (isSeries(notification.media_type)) {
    return (
      notification.series_title ||
      notification.display_title?.replace(/\s*Season\s+\d+\s*$/i, "").trim() ||
      notification.display_title
    );
  }
  return notification.title || notification.display_title;
}

export function groupNotifications(list: WebhookNotification[]): WebhookItem[] {
  const groups = new Map<string, WebhookItem>();
  const singles: WebhookItem[] = [];

  for (const notification of list) {
    const mediaType = notification.media_type || "movie";

    if (!isSeries(mediaType)) {
      singles.push({
        key: notification.notification_id,
        isGroup: false,
        title: itemTitle(notification),
        mediaType,
        seasonNumber: null,
        year: notification.year,
        quality: notification.quality,
        posterUrl: notification.poster_url,
        requestedBy: notification.requested_by,
        createdAt: notification.created_at,
        notifications: [notification],
      });
      continue;
    }

    const slug =
      notification.series_title_slug || notification.series_title || notification.display_title;
    const season = notification.season_number ?? 0;
    const key = `${slug}_S${season}`;

    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        isGroup: true,
        title: itemTitle(notification),
        mediaType,
        seasonNumber: season,
        year: notification.year,
        posterUrl: notification.poster_url,
        requestedBy: notification.requested_by,
        createdAt: notification.created_at,
        notifications: [],
      };
      groups.set(key, group);
    }

    group.notifications.push(notification);
    // Keep the newest timestamp, and backfill a poster from any episode that has one.
    if ((notification.created_at ?? "") > (group.createdAt ?? "")) {
      group.createdAt = notification.created_at;
    }
    if (!group.posterUrl && notification.poster_url) {
      group.posterUrl = notification.poster_url;
    }
  }

  return [...groups.values(), ...singles].sort(
    (a, b) => new Date(b.createdAt ?? 0).getTime() - new Date(a.createdAt ?? 0).getTime()
  );
}

/** Most urgent status wins — same precedence as the original UI. */
const STATUS_PRIORITY = [
  "syncing",
  "failed",
  "QUEUED_PATH",
  "QUEUED_SLOT",
  "READY_FOR_TRANSFER",
  "pending",
  "MANUAL_SYNC_REQUIRED",
  "manual_sync_required",
] as const;

export function groupStatus(notifications: WebhookNotification[]): string {
  const present = new Set(notifications.map((n) => n.status));
  return STATUS_PRIORITY.find((status) => present.has(status)) ?? "completed";
}

export type StatusTone = "ok" | "warn" | "crit" | "brand";

export function statusInfo(status: string): { label: string; tone: StatusTone } {
  switch (status) {
    case "completed":
      return { label: "Completed", tone: "ok" };
    case "failed":
      return { label: "Failed", tone: "crit" };
    case "syncing":
      return { label: "Syncing", tone: "brand" };
    case "READY_FOR_TRANSFER":
      return { label: "Ready", tone: "brand" };
    case "QUEUED_SLOT":
    case "QUEUED_PATH":
      return { label: "Queued", tone: "warn" };
    case "MANUAL_SYNC_REQUIRED":
    case "manual_sync_required":
      return { label: "Manual", tone: "warn" };
    // Rename runs report "partial" when some files landed and some did not.
    case "partial":
      return { label: "Partial", tone: "warn" };
    default:
      return { label: "Pending", tone: "warn" };
  }
}

/** Notifications a user can act on (sync / retry). */
export function isSyncable(notification: WebhookNotification): boolean {
  return (
    notification.status === "pending" ||
    notification.status === "failed" ||
    notification.status === "MANUAL_SYNC_REQUIRED" ||
    notification.status === "manual_sync_required"
  );
}

export function mediaLabel(mediaType: string): string {
  switch (mediaType) {
    case "tvshows":
    case "series":
      return "TV";
    case "anime":
      return "Anime";
    default:
      return "Movie";
  }
}

/**
 * Identity of the download a notification came from. Notifications sharing a
 * release_title are the same physical grab (a season pack fans out into one
 * webhook per episode), so this is what we de-duplicate on.
 */
function releaseKey(notification: WebhookNotification): string {
  return notification.release_title || notification.notification_id;
}

/**
 * The imported media file this webhook is about (Sonarr's `episodeFile`).
 * The API serves `episode_files` pre-parsed, but tolerate raw JSON text so a
 * serialization change can never silently fall back to the wrong size.
 */
export function episodeFileOf(notification: WebhookNotification): WebhookEpisodeFile | undefined {
  const files = notification.episode_files;
  if (Array.isArray(files)) return files[0];
  if (typeof files === "string") {
    try {
      const parsed = JSON.parse(files) as WebhookEpisodeFile[];
      return Array.isArray(parsed) ? parsed[0] : undefined;
    } catch {
      return undefined;
    }
  }
  return undefined;
}

/**
 * Bytes of the actual imported file.
 *
 * `release_size` is the size of the whole grab — for a season pack that is the
 * entire pack repeated on every episode's webhook, so it must never be summed.
 * `episodeFile.size` is this episode's real file and is what we bill against.
 */
export function fileBytes(notification: WebhookNotification): number {
  return episodeFileOf(notification)?.size ?? notification.release_size ?? 0;
}

export type ReleaseType = "seasonPack" | "singleEpisode" | "unknown";

/** Sonarr's own classification, read from the stored payload. */
export function releaseTypeOf(notification: WebhookNotification): ReleaseType {
  const raw = notification.raw_webhook_data;
  if (typeof raw === "string" && raw) {
    try {
      const type = (JSON.parse(raw) as { release?: { releaseType?: string } }).release?.releaseType;
      if (type === "seasonPack" || type === "singleEpisode") return type;
    } catch {
      // fall through to the heuristic below
    }
  }
  // Fallback: a pack fans out into several webhooks that share one release title.
  return "unknown";
}

/**
 * Total bytes actually on disk for a set of notifications.
 *
 * An episode can be delivered more than once (grabbed individually, then
 * upgraded by a season pack), so the newest file per episode number wins.
 */
export function seasonBytes(notifications: WebhookNotification[]): number {
  const latestPerEpisode = new Map<number, { at: string; size: number }>();
  let unattributed = 0;

  for (const notification of notifications) {
    const size = fileBytes(notification);
    const numbers = episodeNumbers(notification);
    if (!numbers.length) {
      // No episode mapping (movies, or older rows) — count it as-is.
      unattributed += size;
      continue;
    }
    const at = notification.created_at ?? "";
    for (const number of numbers) {
      const current = latestPerEpisode.get(number);
      if (!current || at >= current.at) latestPerEpisode.set(number, { at, size });
    }
  }

  return [...latestPerEpisode.values()].reduce((sum, entry) => sum + entry.size, 0) + unattributed;
}

export function episodeNumbers(notification: WebhookNotification): number[] {
  return (notification.episodes ?? [])
    .map((episode) => episode.episodeNumber)
    .filter((n): n is number => typeof n === "number");
}

/**
 * Distinct episodes covered. A pack grabbed alongside individual episode grabs
 * must not be counted twice, so we count episode numbers, not notifications.
 */
export function distinctEpisodeCount(notifications: WebhookNotification[]): number {
  const episodes = new Set<number>();
  for (const notification of notifications) {
    for (const number of episodeNumbers(notification)) episodes.add(number);
  }
  // Older rows may not carry `episodes` — fall back to the notification count.
  return episodes.size || notifications.length;
}

/**
 * Bytes actually downloaded: each distinct release counted once. Summing every
 * notification would multiply a season pack's size by its episode count.
 */
export function effectiveSize(notifications: WebhookNotification[]): number {
  const perRelease = new Map<string, number>();
  for (const notification of notifications) {
    perRelease.set(releaseKey(notification), notification.release_size ?? 0);
  }
  return [...perRelease.values()].reduce((sum, size) => sum + size, 0);
}

export interface ReleaseGroup {
  key: string;
  releaseTitle: string;
  /** Size of the grab as advertised by the indexer (whole pack for packs). */
  size: number;
  /** Bytes of the files this release actually imported. */
  fileBytes: number;
  /** Episode numbers this release delivered, ascending. */
  episodes: number[];
  /** True when the release covers more than one episode (season/multi pack). */
  isPack: boolean;
  releaseType: ReleaseType;
  indexer?: string;
  quality?: string;
  status: string;
  createdAt?: string;
  notifications: WebhookNotification[];
}

/**
 * Collapse a season's notifications into the releases that produced them, so
 * a pack shows as one row ("E01–E10, 26.2 GB") instead of one row per episode.
 */
export function releaseGroups(notifications: WebhookNotification[]): ReleaseGroup[] {
  const releases = new Map<string, ReleaseGroup>();

  for (const notification of notifications) {
    const key = releaseKey(notification);
    let release = releases.get(key);
    if (!release) {
      release = {
        key,
        releaseTitle: notification.release_title || notification.display_title,
        size: notification.release_size ?? 0,
        fileBytes: 0,
        episodes: [],
        isPack: false,
        releaseType: releaseTypeOf(notification),
        indexer: notification.release_indexer,
        quality: episodeFileOf(notification)?.quality,
        status: notification.status,
        createdAt: notification.created_at,
        notifications: [],
      };
      releases.set(key, release);
    }
    release.notifications.push(notification);
    release.episodes.push(...episodeNumbers(notification));
    if ((notification.created_at ?? "") > (release.createdAt ?? "")) {
      release.createdAt = notification.created_at;
    }
  }

  for (const release of releases.values()) {
    release.episodes = [...new Set(release.episodes)].sort((a, b) => a - b);
    release.status = groupStatus(release.notifications);
    release.fileBytes = seasonBytes(release.notifications);
    // Trust Sonarr's classification; otherwise a release spanning several
    // episodes (one webhook each) is a pack.
    release.isPack =
      release.releaseType === "seasonPack" ||
      (release.releaseType === "unknown" && release.episodes.length > 1);
  }

  return [...releases.values()].sort(
    (a, b) => new Date(b.createdAt ?? 0).getTime() - new Date(a.createdAt ?? 0).getTime()
  );
}

export interface EpisodeEntry {
  episodeNumber: number;
  label: string;
  title?: string;
  airDate?: string;
  /** Newest webhook for this episode — the file currently on disk. */
  current: WebhookNotification;
  /** Earlier grabs of the same episode (upgrades), newest first. */
  history: WebhookNotification[];
}

/**
 * One entry per episode, newest grab first, so an episode upgraded by a later
 * pack shows once with its previous grabs kept as history.
 */
export function episodeEntries(
  notifications: WebhookNotification[],
  seasonNumber?: number | null
): EpisodeEntry[] {
  const byEpisode = new Map<number, { meta?: WebhookEpisode; rows: WebhookNotification[] }>();

  for (const notification of notifications) {
    for (const episode of notification.episodes ?? []) {
      const number = episode.episodeNumber;
      if (typeof number !== "number") continue;
      let bucket = byEpisode.get(number);
      if (!bucket) {
        bucket = { meta: episode, rows: [] };
        byEpisode.set(number, bucket);
      }
      // Prefer metadata that actually carries a title.
      if (!bucket.meta?.title && episode.title) bucket.meta = episode;
      bucket.rows.push(notification);
    }
  }

  return [...byEpisode.entries()]
    .map(([episodeNumber, bucket]) => {
      const rows = [...bucket.rows].sort((a, b) =>
        (b.created_at ?? "").localeCompare(a.created_at ?? "")
      );
      const season = bucket.meta?.seasonNumber ?? seasonNumber ?? 0;
      return {
        episodeNumber,
        label: `S${String(season).padStart(2, "0")}E${String(episodeNumber).padStart(2, "0")}`,
        title: bucket.meta?.title,
        airDate: bucket.meta?.airDate,
        current: rows[0],
        history: rows.slice(1),
      };
    })
    .sort((a, b) => a.episodeNumber - b.episodeNumber);
}

/** "E01–E10" when contiguous, "E05" for one, else a short list. */
export function formatEpisodeRange(numbers: number[]): string {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b);
  if (!sorted.length) return "";
  const label = (n: number) => `E${String(n).padStart(2, "0")}`;
  if (sorted.length === 1) return label(sorted[0]);
  const contiguous = sorted.every((n, i) => i === 0 || n === sorted[i - 1] + 1);
  if (contiguous) return `${label(sorted[0])}–${label(sorted[sorted.length - 1])}`;
  if (sorted.length <= 4) return sorted.map(label).join(", ");
  return `${sorted.slice(0, 3).map(label).join(", ")} +${sorted.length - 3}`;
}

export function formatSize(bytes?: number): string {
  if (!bytes) return "";
  const gb = bytes / 1073741824;
  if (gb >= 1) return `${gb.toFixed(gb < 10 ? 1 : 0)} GB`;
  return `${Math.round(bytes / 1048576)} MB`;
}

export function timeAgo(dateString?: string): string {
  if (!dateString) return "";
  const diff = Date.now() - new Date(dateString.replace(" ", "T")).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** "Season 2 · 3 episodes" for groups, quality/year for movies. */
export function itemDetail(item: WebhookItem): string {
  if (item.isGroup) {
    const count = distinctEpisodeCount(item.notifications);
    return `Season ${item.seasonNumber ?? 0} · ${count} episode${count === 1 ? "" : "s"}`;
  }
  return item.quality || (item.year ? String(item.year) : "");
}
