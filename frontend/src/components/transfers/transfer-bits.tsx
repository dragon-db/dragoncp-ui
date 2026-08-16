import { cn } from "@/lib/utils";
import {
  IconCheck,
  IconAlertTriangle,
  IconClock,
  IconPlayerPause,
  IconCircleX,
  IconArrowsTransferDown,
  IconRocket,
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
 * Which route a transfer took to the media host.
 *
 * Only shown for the fast route. A transfer over SSH is the normal case and
 * badging every one of them would be noise — but a transfer that ran three
 * times faster is worth being able to see, and its absence is what tells you a
 * transfer fell back.
 */
export function TransportBadge({
  transport,
  className,
}: {
  transport?: string | null;
  className?: string;
}) {
  if (transport !== "daemon") return null;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[5px] border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-emerald-300 uppercase",
        className
      )}
      title="Pulled over the fast transfer server rather than SSH"
    >
      <IconRocket className="size-[11px]" />
      Fast
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
