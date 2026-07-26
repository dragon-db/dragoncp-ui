import type { WebhookNotification } from "@/lib/api-types";

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

export function totalSize(notifications: WebhookNotification[]): number {
  return notifications.reduce((sum, n) => sum + (n.release_size ?? 0), 0);
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
    const count = item.notifications.length;
    return `Season ${item.seasonNumber ?? 0} · ${count} episode${count === 1 ? "" : "s"}`;
  }
  return item.quality || (item.year ? String(item.year) : "");
}
