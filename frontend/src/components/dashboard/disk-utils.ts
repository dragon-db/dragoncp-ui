import { useLocalDiskUsage, useRemoteDiskUsage } from "@/hooks/useConfig";

export interface DiskItem {
  name: string;
  pct: number;
  used: string;
  free: string;
  total: string;
  /** Mount point / watched path, e.g. /mnt/media. */
  path: string;
  /** Backing device / filesystem, e.g. /dev/sdc1. */
  device: string;
  type: "local" | "remote";
}

/** Normalized local + remote disks, deduped via react-query. */
export function useDisks(): { disks: DiskItem[]; isLoading: boolean } {
  const local = useLocalDiskUsage();
  const remote = useRemoteDiskUsage();

  const disks: DiskItem[] = [];

  local.data?.disk_info
    ?.filter((d) => d.available)
    .forEach((d, idx) => {
      disks.push({
        name: `Local Disk ${idx + 1}`,
        pct: Math.round(d.usage_percent ?? 0),
        used: d.used_size ?? "—",
        free: d.available_size ?? "—",
        total: d.total_size ?? "—",
        path: d.mount_point || d.path || "",
        device: d.filesystem ?? "",
        type: "local",
      });
    });

  const storage = remote.data?.storage_info;
  if (storage?.available) {
    disks.push({
      name: "Remote Storage",
      pct: Math.round(storage.usage_percent ?? 0),
      used: storage.used_display,
      free: storage.free_display,
      total: storage.total_display,
      path: "",
      device: "remote",
      type: "remote",
    });
  }

  return { disks, isLoading: local.isLoading || remote.isLoading };
}

export type Severity = "ok" | "warn" | "crit";

/** On-brand severity: brand until a disk nears full, then amber, then rose. */
export function diskSeverity(pct: number): Severity {
  if (pct >= 92) return "crit";
  if (pct >= 78) return "warn";
  return "ok";
}

// Tailwind class maps — brand gradient for the calm case, warm only when filling.
export const sevBarFill: Record<Severity, string> = {
  ok: "bg-brand-gradient-x",
  warn: "bg-amber-400",
  crit: "bg-rose-400",
};

export const sevText: Record<Severity, string> = {
  ok: "text-brand-hover",
  warn: "text-amber-400",
  crit: "text-rose-400",
};

export const sevDot: Record<Severity, string> = {
  ok: "bg-brand-hover",
  warn: "bg-amber-400",
  crit: "bg-rose-400",
};
