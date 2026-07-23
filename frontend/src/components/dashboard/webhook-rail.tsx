import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { useWebhookNotifications, type WebhookNotification } from "@/hooks/useWebhooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  IconWebhook,
  IconRefresh,
  IconInfoCircle,
  IconMovie,
  IconDeviceTv,
  IconBrandNetflix,
  IconUser,
  IconCheck,
  IconAlertTriangle,
  IconClock,
} from "@tabler/icons-react";

const POSTER_FALLBACK_BG = {
  background:
    "repeating-linear-gradient(135deg, var(--surface-3) 0 5px, var(--surface-2) 5px 10px)",
} as const;

function mediaIcon(mediaType: string, className: string) {
  switch (mediaType) {
    case "tvshows":
    case "series":
      return <IconDeviceTv className={className} />;
    case "anime":
      return <IconBrandNetflix className={className} />;
    default:
      return <IconMovie className={className} />;
  }
}

function mediaLabel(mediaType: string): string {
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

function statusMeta(status: string): { label: string; cls: string; icon: React.ReactNode } {
  const check = <IconCheck className="size-2.5" />;
  const alert = <IconAlertTriangle className="size-2.5" />;
  const clock = <IconClock className="size-2.5" />;
  switch (status) {
    case "completed":
      return {
        label: "Completed",
        cls: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
        icon: check,
      };
    case "failed":
      return {
        label: "Failed",
        cls: "border-rose-500/40 bg-rose-500/15 text-rose-400",
        icon: alert,
      };
    case "syncing":
      return {
        label: "Syncing",
        cls: "border-brand/40 bg-brand/15 text-brand-foreground",
        icon: clock,
      };
    case "READY_FOR_TRANSFER":
      return {
        label: "Ready",
        cls: "border-brand/40 bg-brand/15 text-brand-foreground",
        icon: clock,
      };
    case "QUEUED_SLOT":
    case "QUEUED_PATH":
      return {
        label: "Queued",
        cls: "border-amber-500/40 bg-amber-500/15 text-amber-400",
        icon: clock,
      };
    case "MANUAL_SYNC_REQUIRED":
      return {
        label: "Manual",
        cls: "border-amber-500/40 bg-amber-500/15 text-amber-400",
        icon: alert,
      };
    default:
      return {
        label: "Pending",
        cls: "border-amber-500/40 bg-amber-500/15 text-amber-400",
        icon: clock,
      };
  }
}

function cleanTitle(item: WebhookNotification): string {
  if (item.season_number != null) {
    return (
      item.series_title ||
      item.display_title.replace(/\s*Season\s+\d+\s*$/i, "").trim() ||
      item.display_title
    );
  }
  return item.title || item.display_title;
}

function detailLine(item: WebhookNotification): string {
  if (item.season_number != null) {
    const eps = item.episode_count ?? 0;
    return `Season ${item.season_number} · ${eps} ep${eps === 1 ? "" : "s"}`;
  }
  return item.quality || (item.year ? String(item.year) : "");
}

function formatSize(bytes?: number): string {
  if (!bytes) return "";
  const gb = bytes / 1073741824;
  if (gb >= 1) return `${gb.toFixed(gb < 10 ? 1 : 0)} GB`;
  return `${Math.round(bytes / 1048576)} MB`;
}

function timeAgo(dateString?: string): string {
  if (!dateString) return "";
  const diff = Date.now() - new Date(dateString.replace(" ", "T")).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function WebhookRow({ item }: { item: WebhookNotification }) {
  const status = statusMeta(item.status);
  const detail = detailLine(item);
  const meta = [item.requested_by, formatSize(item.release_size), timeAgo(item.created_at)]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="flex gap-3 border-b border-border px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/40">
      {/* Poster */}
      <div
        className="relative h-[62px] w-11 shrink-0 overflow-hidden rounded-md border border-border text-muted-foreground"
        style={POSTER_FALLBACK_BG}
      >
        <span className="absolute inset-0 grid place-items-center">
          {mediaIcon(item.media_type, "size-4")}
        </span>
        {item.poster_url && (
          <img
            src={item.poster_url}
            alt=""
            loading="lazy"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
            className="absolute inset-0 size-full object-cover"
          />
        )}
      </div>

      {/* Body */}
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex items-start gap-2">
          <span className="line-clamp-2 text-[13px] leading-tight font-semibold text-foreground">
            {cleanTitle(item)}
            {item.year ? (
              <span className="font-normal text-muted-foreground"> ({item.year})</span>
            ) : null}
          </span>
          <span
            className={cn(
              "ml-auto inline-flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9.5px] font-bold tracking-wide uppercase",
              status.cls
            )}
          >
            {status.icon}
            {status.label}
          </span>
        </div>

        <div className="flex min-w-0 items-center gap-2">
          <span className="inline-flex shrink-0 items-center gap-1 rounded-[5px] border border-border bg-black/20 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
            {mediaIcon(item.media_type, "size-[11px] text-brand-hover")}
            {mediaLabel(item.media_type)}
          </span>
          {detail && <span className="truncate text-[11px] text-muted-foreground">{detail}</span>}
        </div>

        <div className="flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
          <IconUser className="size-[11px] opacity-80" />
          <span className="truncate">{meta}</span>
        </div>
      </div>
    </div>
  );
}

export function WebhookRail() {
  const { data, isLoading, refetch } = useWebhookNotifications(undefined, 10);
  const notifications = data?.notifications ?? [];
  const items = notifications.slice(0, 6);

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <IconWebhook className="size-4 text-muted-foreground" />
        <span className="font-display text-sm font-semibold text-foreground">Webhooks</span>
        {data?.total != null && (
          <Badge variant="outline" className="gap-1.5 text-muted-foreground">
            <span className="size-1.5 rounded-full bg-emerald-400" />
            {data.total}
          </Badge>
        )}
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => refetch()}
          title="Refresh"
        >
          <IconRefresh className="size-4" />
        </Button>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-3 p-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : items.length ? (
        <>
          <div className="flex-1 overflow-auto">
            {items.map((item) => (
              <WebhookRow key={item.notification_id} item={item} />
            ))}
          </div>
          <div className="flex justify-center border-t border-border px-4 py-2">
            <Link to="/webhooks">
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-foreground"
              >
                View all webhooks →
              </Button>
            </Link>
          </div>
        </>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
          <IconInfoCircle className="size-5" />
          <span className="text-sm">No webhook activity</span>
        </div>
      )}
    </section>
  );
}
