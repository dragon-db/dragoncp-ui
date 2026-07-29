import type { Transfer } from "@/lib/api-types";

/**
 * Formatting helpers for the structured rsync progress the backend now stores
 * (percent, byte counts, speed, ETA).
 *
 * rsync reports human-readable sizes in powers of 1000, so these match that
 * rather than using 1024 - otherwise the numbers would disagree with the raw
 * log lines shown right next to them.
 */
const UNITS = ["B", "KB", "MB", "GB", "TB", "PB"] as const;

function scale(bytes: number): { value: number; unit: string } {
  let value = Math.max(0, bytes);
  let index = 0;
  while (value >= 1000 && index < UNITS.length - 1) {
    value /= 1000;
    index += 1;
  }
  return { value, unit: UNITS[index] };
}

function trim(value: number): string {
  if (value >= 100) return value.toFixed(0);
  if (value >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

export function formatBytes(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "—";
  const { value, unit } = scale(bytes);
  return `${trim(value)} ${unit}`;
}

export function formatSpeed(bytesPerSecond?: number | null): string {
  if (!bytesPerSecond || !Number.isFinite(bytesPerSecond)) return "—";
  const { value, unit } = scale(bytesPerSecond);
  return `${trim(value)} ${unit}/s`;
}

export function formatEta(seconds?: number | null): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/**
 * "2.7 / 4.2" plus a shared unit, so transferred and total read as one figure
 * instead of two independently scaled numbers.
 */
export function formatSizePair(
  done?: number | null,
  total?: number | null
): { value: string; unit: string } | null {
  if (done == null || !Number.isFinite(done)) return null;
  if (total == null || !Number.isFinite(total) || total <= 0) {
    const { value, unit } = scale(done);
    return { value: trim(value), unit };
  }
  const { unit } = scale(total);
  const divisor = 1000 ** UNITS.indexOf(unit as (typeof UNITS)[number]);
  return {
    value: `${trim(done / divisor)} / ${trim(total / divisor)}`,
    unit,
  };
}

/** Coarse duration for spans that can run from seconds to days. */
export function formatDuration(ms?: number | null): string | null {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

/** Parses the backend's naive-local ISO timestamps ("2026-07-27T22:14:48"). */
export function parseTimestamp(value?: string | null): number | null {
  if (!value) return null;
  const ms = new Date(value.replace(" ", "T")).getTime();
  return Number.isFinite(ms) ? ms : null;
}

/**
 * How long a transfer ran: to its end time if it finished, otherwise to now.
 * Returns null when there is no start time to measure from.
 */
export function transferElapsed(transfer: Transfer, now: number): number | null {
  const start = parseTimestamp(transfer.start_time);
  if (start == null) return null;
  const end = parseTimestamp(transfer.end_time) ?? now;
  return Math.max(0, end - start);
}

/** Legacy fallback: pull a percentage out of a raw rsync log line. */
export function parseProgressText(progress?: string): number {
  if (!progress) return 0;
  const match = progress.match(/(\d{1,3})%/);
  return match ? Math.max(0, Math.min(100, Number(match[1]))) : 0;
}

/**
 * Percent complete for a transfer, preferring the parsed column and falling
 * back to the progress text for records written before that column existed.
 */
export function transferPercent(transfer: Transfer): number {
  if (transfer.progress_percent != null && Number.isFinite(transfer.progress_percent)) {
    return Math.max(0, Math.min(100, transfer.progress_percent));
  }
  return parseProgressText(transfer.progress);
}

export function isActiveStatus(status: string): boolean {
  return status === "running" || status === "pending";
}
