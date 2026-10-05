import type { ComponentType, ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { StageDef, StageStatus } from "@/lib/sync-types";
import { RUN_STATE, TONE_BADGE, stageStatusInfo, type PipelineTone } from "@/lib/pipeline";
import {
  IconArchive,
  IconCircleDashed,
  IconCompass,
  IconFlask,
  IconHandClick,
  IconRadar,
  IconRefresh,
  IconWebhook,
} from "@tabler/icons-react";

/**
 * Presentation pieces for the pipeline, in the app's four-note status
 * vocabulary: brand is in progress, amber waits or needs a person, rose
 * failed, emerald finished. A skipped stage is neither good nor bad, so it is
 * drawn quiet and dashed rather than given a colour that would read as a
 * verdict.
 */

type Icon = ComponentType<{ className?: string }>;

// -- stages -----------------------------------------------------------------

/** The round marker for a stage: its outcome as an icon, in its tone. */
export function StageNode({
  status,
  className,
  iconClassName,
}: {
  status: StageStatus | string;
  className?: string;
  iconClassName?: string;
}) {
  const info = stageStatusInfo(status);
  const Glyph = info.icon;
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full border",
        status === "skipped" || status === "pending" ? "border-dashed" : "",
        TONE_BADGE[info.tone],
        className
      )}
    >
      <Glyph className={cn(iconClassName, status === "running" && "animate-spin")} />
    </span>
  );
}

export function StageStatusBadge({
  status,
  className,
}: {
  status: StageStatus | string;
  className?: string;
}) {
  const info = stageStatusInfo(status);
  const Glyph = info.icon;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase",
        status === "skipped" && "border-dashed",
        TONE_BADGE[info.tone],
        className
      )}
    >
      <Glyph className={cn("size-3", status === "running" && "animate-spin")} />
      {info.label}
    </span>
  );
}

const STRIP_FILL: Record<StageStatus, string> = {
  passed: "bg-emerald-500/70",
  skipped: "bg-transparent border border-dashed border-muted-foreground/35",
  running: "bg-brand-gradient-x animate-pulse",
  waiting: "bg-amber-500/80",
  failed: "bg-rose-500/80",
  refused: "bg-amber-500/80",
  pending: "bg-white/8",
};

/**
 * Nine segments, one per stage — how far a sync got, readable at a glance in a
 * list. Each segment names its stage and outcome on hover and to a screen
 * reader, so the colour is never the only carrier.
 */
export function StageStrip({
  stages,
  defs,
  className,
}: {
  stages: { id: string; status: StageStatus }[];
  defs?: StageDef[];
  className?: string;
}) {
  const labels = new Map(defs?.map((def) => [def.id, def.label]) ?? []);
  const described = stages
    .map(
      (stage, index) =>
        `${index + 1} ${labels.get(stage.id) ?? stage.id}: ${stageStatusInfo(stage.status).label}`
    )
    .join(", ");
  return (
    <span
      role="img"
      aria-label={described}
      className={cn("flex items-center gap-[3px]", className)}
    >
      {stages.map((stage, index) => (
        <span
          key={stage.id}
          title={`${index + 1} ${labels.get(stage.id) ?? stage.id} — ${stageStatusInfo(stage.status).label}`}
          className={cn(
            "h-1.5 min-w-0 flex-1 rounded-full",
            STRIP_FILL[stage.status] ?? STRIP_FILL.pending
          )}
        />
      ))}
    </span>
  );
}

// -- runs -------------------------------------------------------------------

export function RunStateBadge({
  state,
  label,
  className,
}: {
  state: string;
  /** The engine's own words for the state: "Waiting for the download". */
  label: string;
  className?: string;
}) {
  const info = RUN_STATE[state] ?? { tone: "muted" as PipelineTone, icon: IconCircleDashed };
  const Glyph = info.icon;
  const spinning = state === "checking" || state === "transferring" || state === "finishing";
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase",
        TONE_BADGE[info.tone],
        className
      )}
    >
      <Glyph className={cn("size-3", spinning && "animate-spin")} />
      {label}
    </span>
  );
}

const KIND_ICON: Record<string, Icon> = {
  sonarr_webhook: IconWebhook,
  radarr_webhook: IconWebhook,
  auto_scanner: IconRadar,
  manual: IconHandClick,
  explore: IconCompass,
  restart: IconRefresh,
  restore: IconArchive,
  simulation: IconFlask,
};

/** What started a sync, as a quiet chip — the state badge is the loud one. */
export function KindBadge({
  kind,
  label,
  className,
}: {
  kind: string;
  label: string;
  className?: string;
}) {
  const Glyph = KIND_ICON[kind] ?? IconWebhook;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[5px] border border-border bg-black/30 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase",
        kind === "simulation" && "border-amber-500/30 text-amber-300/90",
        className
      )}
    >
      <Glyph className="size-[11px]" />
      {label}
    </span>
  );
}

/** A row of facts separated by quiet dots; a wrapped line never opens with one. */
export function FactLine({ facts, className }: { facts: ReactNode[]; className?: string }) {
  const kept = facts.filter((fact) => fact !== null && fact !== undefined && fact !== "");
  return (
    <span
      className={cn(
        "flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[11px] text-muted-foreground",
        className
      )}
    >
      {kept.map((fact, index) => (
        <span key={index} className="flex items-center gap-1.5">
          {fact}
          {index < kept.length - 1 && <span className="opacity-50">·</span>}
        </span>
      ))}
    </span>
  );
}
