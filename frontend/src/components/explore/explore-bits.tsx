import { IconAlertTriangle, IconCheck, IconClock, IconStack2 } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import type { ExploreCounts, ExploreLabel, ExploreStatus } from "@/lib/explore-types";

/**
 * The shared vocabulary. Every badge and count on the Explore page comes from
 * a comparison label, so they are defined once here rather than per component.
 */

const STATUS_META: Record<ExploreStatus, { label: string; tone: string; Icon: typeof IconCheck }> =
  {
    SYNCED: {
      label: "Synced",
      tone: "border-emerald-500/35 bg-emerald-500/12 text-emerald-300",
      Icon: IconCheck,
    },
    OUT_OF_SYNC: {
      label: "Out of sync",
      tone: "border-amber-500/38 bg-amber-500/12 text-amber-400",
      Icon: IconAlertTriangle,
    },
    PARTIAL_SYNC: {
      label: "Partial",
      tone: "border-brand/38 bg-brand/15 text-brand-foreground",
      Icon: IconStack2,
    },
    NO_INFO: {
      label: "Not checked",
      tone: "border-transparent bg-transparent text-muted-foreground",
      Icon: IconClock,
    },
  };

export function StatusBadge({ status, className }: { status: ExploreStatus; className?: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.NO_INFO;
  const { Icon } = meta;
  return (
    <span
      className={cn(
        "inline-flex flex-none items-center gap-[5px] rounded-full border px-2 py-[2.5px]",
        "text-[10px] font-bold tracking-[0.05em] whitespace-nowrap uppercase",
        meta.tone,
        status === "NO_INFO" && "pl-0",
        className
      )}
    >
      <Icon className="size-2.5" />
      {meta.label}
    </span>
  );
}

const LABEL_META: Record<ExploreLabel, { label: string; tone: string }> = {
  IN_SYNC: { label: "In sync", tone: "text-muted-foreground bg-muted/60" },
  MISSING: { label: "Download", tone: "text-amber-400 bg-amber-500/14" },
  UPGRADED: { label: "Replace", tone: "text-brand-foreground bg-brand/20" },
  LOCAL_ONLY: { label: "Local only", tone: "text-rose-300 bg-rose-500/14" },
};

export function EpisodeLabel({ label }: { label: ExploreLabel }) {
  const meta = LABEL_META[label];
  return (
    <span
      className={cn(
        "flex-none rounded px-1.5 py-px font-mono text-[9.5px] font-semibold tracking-[0.06em]",
        meta.tone
      )}
    >
      {meta.label}
    </span>
  );
}

/**
 * The counts that matter, in the order you scan them. Zero values are dropped —
 * a season with nothing missing should not display "0 missing".
 */
export function CountChips({ counts, className }: { counts: ExploreCounts; className?: string }) {
  const chips: Array<{ n: number; label: string; tone: string }> = [
    { n: counts.missing, label: "missing", tone: "text-amber-400" },
    { n: counts.upgraded, label: "upgraded", tone: "text-brand-foreground" },
    { n: counts.local_only, label: "extra", tone: "text-rose-300" },
    { n: counts.in_sync, label: "in sync", tone: "text-muted-foreground" },
  ].filter((chip) => chip.n > 0);

  if (!chips.length) return null;

  return (
    <span className={cn("flex items-center gap-2 font-mono text-[10px]", className)}>
      {chips.map((chip) => (
        <span key={chip.label} className={chip.tone}>
          {chip.n} {chip.label}
        </span>
      ))}
    </span>
  );
}
