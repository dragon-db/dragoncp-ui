/**
 * Pipeline vocabulary that is not a component: tones, and the words for time.
 *
 * Kept out of `components/pipeline/pipeline-bits.tsx` so that module exports
 * components only, which is what fast refresh needs.
 */

import type { ComponentType } from "react";
import type { StageStatus } from "@/lib/sync-types";
import {
  IconAlertTriangle,
  IconCheck,
  IconCircleDashed,
  IconClockHour4,
  IconHandStop,
  IconLoader2,
  IconPlayerPause,
  IconPlayerSkipForward,
  IconShieldExclamation,
  IconX,
} from "@tabler/icons-react";

type Icon = ComponentType<{ className?: string }>;

export type PipelineTone = "ok" | "warn" | "crit" | "brand" | "muted";

export const TONE_BADGE: Record<PipelineTone, string> = {
  ok: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/15 text-amber-400",
  crit: "border-rose-500/40 bg-rose-500/15 text-rose-400",
  brand: "border-brand/40 bg-brand/15 text-brand-foreground",
  muted: "border-border bg-muted/40 text-muted-foreground",
};

export const TONE_TEXT: Record<PipelineTone, string> = {
  ok: "text-emerald-400",
  warn: "text-amber-400",
  crit: "text-rose-400",
  brand: "text-brand-hover",
  muted: "text-muted-foreground",
};

// -- time -------------------------------------------------------------------

/** "12 s", "4 min", "2 h 10 min". */
export function formatSpan(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** How long ago, in words a person uses: "just now", "5 min ago", "3 days ago". */
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

/** Wall-clock time; the date too when it was not today. */
export function clockText(iso: string | null | undefined): string {
  if (!iso) return "";
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return "";
  const today = new Date();
  const sameDay = moment.toDateString() === today.toDateString();
  return sameDay
    ? moment.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : moment.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

export const STAGE_STATUS: Record<StageStatus, { label: string; tone: PipelineTone; icon: Icon }> =
  {
    passed: { label: "Done", tone: "ok", icon: IconCheck },
    skipped: { label: "Skipped", tone: "muted", icon: IconPlayerSkipForward },
    running: { label: "Working", tone: "brand", icon: IconLoader2 },
    waiting: { label: "Waiting", tone: "warn", icon: IconClockHour4 },
    failed: { label: "Failed", tone: "crit", icon: IconX },
    refused: { label: "Stopped", tone: "warn", icon: IconShieldExclamation },
    pending: { label: "Not reached", tone: "muted", icon: IconCircleDashed },
  };

export function stageStatusInfo(status: StageStatus | string) {
  return STAGE_STATUS[status as StageStatus] ?? STAGE_STATUS.pending;
}

export const RUN_STATE: Record<string, { tone: PipelineTone; icon: Icon }> = {
  held: { tone: "warn", icon: IconHandStop },
  waiting: { tone: "brand", icon: IconClockHour4 },
  checking: { tone: "brand", icon: IconLoader2 },
  queued: { tone: "warn", icon: IconClockHour4 },
  transferring: { tone: "brand", icon: IconLoader2 },
  paused: { tone: "warn", icon: IconPlayerPause },
  finishing: { tone: "brand", icon: IconLoader2 },
  completed: { tone: "ok", icon: IconCheck },
  failed: { tone: "crit", icon: IconAlertTriangle },
  cancelled: { tone: "muted", icon: IconX },
  refused: { tone: "warn", icon: IconShieldExclamation },
  interrupted: { tone: "warn", icon: IconAlertTriangle },
};

export function runStateTone(state: string): PipelineTone {
  return RUN_STATE[state]?.tone ?? "muted";
}
