import { cn } from "@/lib/utils";
import {
  IconCheck,
  IconAlertTriangle,
  IconClock,
  IconPlayerPause,
  IconCircleX,
  IconArrowsTransferDown,
  IconRocket,
  IconKey,
} from "@tabler/icons-react";
import type { ReactNode } from "react";

/**
 * Presentation pieces for transfer rows, matching the webhook equivalents so a
 * status chip reads the same whichever page you are on. Transfers have their
 * own status vocabulary (running / paused / cancelled), which is why this does
 * not reuse the webhook status map.
 */

export type TransferTone = "ok" | "warn" | "crit" | "brand" | "muted";

const TONE_BADGE: Record<TransferTone, string> = {
  ok: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/15 text-amber-400",
  crit: "border-rose-500/40 bg-rose-500/15 text-rose-400",
  brand: "border-brand/40 bg-brand/15 text-brand-foreground",
  muted: "border-border bg-muted/40 text-muted-foreground",
};

function transferStatusInfo(status: string): { label: string; tone: TransferTone } {
  switch (status) {
    case "running":
      return { label: "Running", tone: "brand" };
    case "completed":
      return { label: "Completed", tone: "ok" };
    case "failed":
      return { label: "Failed", tone: "crit" };
    case "paused":
      return { label: "Paused", tone: "warn" };
    case "queued":
      return { label: "Queued", tone: "warn" };
    case "cancelled":
      return { label: "Stopped", tone: "muted" };
    case "pending":
      return { label: "Starting", tone: "brand" };
    default:
      return { label: status || "Unknown", tone: "muted" };
  }
}

function StatusIcon({ status, className }: { status: string; className?: string }) {
  switch (status) {
    case "completed":
      return <IconCheck className={className} />;
    case "failed":
      return <IconAlertTriangle className={className} />;
    case "paused":
      return <IconPlayerPause className={className} />;
    case "cancelled":
      return <IconCircleX className={className} />;
    case "running":
    case "pending":
      return <IconArrowsTransferDown className={className} />;
    default:
      return <IconClock className={className} />;
  }
}

export function TransferStatusBadge({
  status,
  size = "default",
  className,
}: {
  status: string;
  size?: "default" | "sm";
  className?: string;
}) {
  const { label, tone } = transferStatusInfo(status);
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

/**
 * The progress bar used in rows and in the detail panel. Queued transfers show
 * an empty track rather than a zero-width bar, so "not started" and "just
 * started" don't look identical.
 */
export function ProgressMeter({
  percent,
  status,
  className,
}: {
  percent: number;
  status: string;
  className?: string;
}) {
  const queued = status === "queued" || status === "pending";
  return (
    <div className={cn("h-1 overflow-hidden rounded-full bg-white/8", className)}>
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-500 ease-out",
          status === "running" && "bg-brand-gradient-x",
          status === "paused" && "bg-amber-500/70",
          status === "completed" && "bg-emerald-500/70",
          status === "failed" && "bg-rose-500/70",
          status === "cancelled" && "bg-muted-foreground/40",
          queued && "bg-muted-foreground/40"
        )}
        style={{ width: `${queued ? 0 : percent}%` }}
      />
    </div>
  );
}

/**
 * Which route a transfer took to the media host, on every row that lists one.
 *
 * All three routes are badged. A fast-route-only badge left the commonest case
 * unlabelled, and "no badge" could mean SSH, not started yet, or a run from
 * before routes were recorded — the operator asked to see the route at a
 * glance (2026-10-14). Nothing is shown until rsync starts, because the route
 * is chosen at that moment, and nothing for old runs that never recorded one.
 */
const ROUTE_BADGES: Record<
  string,
  { label: string; title: string; icon: typeof IconRocket; className: string }
> = {
  daemon: {
    label: "Fast",
    title: "Copied over the fast transfer server",
    icon: IconRocket,
    className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  },
  ssh: {
    label: "SSH",
    title: "Copied over SSH",
    icon: IconKey,
    className: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  },
  ssh_fallback: {
    label: "SSH fallback",
    title: "The fast transfer server failed, so this copy ran again over SSH",
    icon: IconAlertTriangle,
    className: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  },
};

export function TransportBadge({
  transport,
  className,
}: {
  transport?: string | null;
  className?: string;
}) {
  const route = transport ? ROUTE_BADGES[transport] : undefined;
  if (!route) return null;
  const Icon = route.icon;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[5px] border px-1.5 py-0.5 text-[10px] font-semibold tracking-wide whitespace-nowrap uppercase",
        route.className,
        className
      )}
      title={route.title}
    >
      <Icon className="size-[11px]" />
      {route.label}
    </span>
  );
}

export function Chip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-border bg-black/25 px-2 py-0.5 font-mono text-[11px] text-muted-foreground",
        className
      )}
    >
      {children}
    </span>
  );
}

export function Fact({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value?: ReactNode;
  mono?: boolean;
  tone?: TransferTone;
}) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </span>
      <span
        className={cn(
          "text-xs break-words text-foreground",
          mono && "font-mono",
          tone === "ok" && "text-emerald-400",
          tone === "warn" && "text-amber-400",
          tone === "crit" && "text-rose-400",
          tone === "brand" && "text-brand-foreground"
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function PathBlock({
  label,
  value,
  className,
}: {
  label: string;
  value?: string;
  className?: string;
}) {
  if (!value) return null;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </span>
      <div className="rounded-md border border-border bg-background/60 px-2.5 py-1.5 font-mono text-[11px] break-all text-foreground/80">
        {value}
      </div>
    </div>
  );
}
