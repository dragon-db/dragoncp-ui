/**
 * Formatting shared across the Explore screens.
 *
 * Kept out of the component files so fast refresh keeps working — a module that
 * exports both components and plain functions loses it.
 */

export function formatBytes(bytes?: number | null): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 100 || unit < 2 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

export function formatAge(unixSeconds?: number | null): string {
  if (!unixSeconds) return "—";
  const days = Math.floor((Date.now() / 1000 - unixSeconds) / 86400);
  if (days <= 0) return "today";
  if (days < 7) return `${days}d`;
  if (days < 30) return `${Math.floor(days / 7)}w`;
  if (days < 365) return `${Math.floor(days / 30)}mo`;
  return `${Math.floor(days / 365)}y`;
}

export function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}
