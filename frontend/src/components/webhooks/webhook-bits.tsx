import { cn } from "@/lib/utils";
import {
  IconMovie,
  IconDeviceTv,
  IconBrandNetflix,
  IconCheck,
  IconAlertTriangle,
  IconClock,
  IconRefresh,
} from "@tabler/icons-react";
import { mediaLabel, statusInfo, type StatusTone, type WebhookItem } from "@/lib/webhook-grouping";

/** Shared presentation pieces for webhook rows (page + dashboard rail). */

export function MediaIcon({ mediaType, className }: { mediaType: string; className?: string }) {
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

const POSTER_FALLBACK = {
  background:
    "repeating-linear-gradient(135deg, var(--surface-3) 0 5px, var(--surface-2) 5px 10px)",
} as const;

/** Poster art with a media-icon fallback when missing or broken. */
export function WebhookPoster({
  item,
  className,
  iconClassName = "size-4",
}: {
  item: Pick<WebhookItem, "posterUrl" | "mediaType" | "title">;
  className?: string;
  iconClassName?: string;
}) {
  return (
    <div
      className={cn(
        "relative shrink-0 overflow-hidden rounded-md border border-border text-muted-foreground",
        className
      )}
      style={POSTER_FALLBACK}
    >
      <span className="absolute inset-0 grid place-items-center">
        <MediaIcon mediaType={item.mediaType} className={iconClassName} />
      </span>
      {item.posterUrl && (
        <img
          src={item.posterUrl}
          alt=""
          loading="lazy"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
          className="absolute inset-0 size-full object-cover"
        />
      )}
    </div>
  );
}

const TONE_BADGE: Record<StatusTone, string> = {
  ok: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/15 text-amber-400",
  crit: "border-rose-500/40 bg-rose-500/15 text-rose-400",
  brand: "border-brand/40 bg-brand/15 text-brand-foreground",
};

const TONE_DOT: Record<StatusTone, string> = {
  ok: "bg-emerald-400",
  warn: "bg-amber-400",
  crit: "bg-rose-400",
  brand: "bg-brand-hover",
};

/** Small status dot, for dense rows where a full badge is too heavy. */
export function StatusDot({ status, className }: { status: string; className?: string }) {
  return (
    <span
      className={cn("size-1.5 shrink-0 rounded-full", TONE_DOT[statusInfo(status).tone], className)}
    />
  );
}

function StatusIcon({ status, className }: { status: string; className?: string }) {
  if (status === "completed") return <IconCheck className={className} />;
  if (status === "failed" || status.toLowerCase().includes("manual"))
    return <IconAlertTriangle className={className} />;
  if (status === "syncing") return <IconRefresh className={className} />;
  return <IconClock className={className} />;
}

export function StatusBadge({
  status,
  size = "default",
  className,
}: {
  status: string;
  size?: "default" | "sm";
  className?: string;
}) {
  const { label, tone } = statusInfo(status);
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border font-bold tracking-wide uppercase",
        size === "sm" ? "px-1.5 py-0.5 text-[9px]" : "px-2 py-0.5 text-[10px]",
        TONE_BADGE[tone],
        className
      )}
    >
      <StatusIcon status={status} className={size === "sm" ? "size-2.5" : "size-3"} />
      {label}
    </span>
  );
}

export function MediaBadge({ mediaType }: { mediaType: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-[5px] border border-border bg-black/20 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
      <MediaIcon mediaType={mediaType} className="size-[11px] text-brand-hover" />
      {mediaLabel(mediaType)}
    </span>
  );
}
