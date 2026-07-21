import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { IconDatabase, IconCloud } from "@tabler/icons-react";
import {
  useDisks,
  diskSeverity,
  sevBarFill,
  sevText,
  type DiskItem,
} from "@/components/dashboard/disk-utils";

function DiskCell({ disk }: { disk: DiskItem }) {
  const sev = diskSeverity(disk.pct);
  const Icon = disk.type === "remote" ? IconCloud : IconDatabase;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="truncate text-xs font-semibold text-foreground">{disk.name}</span>
            <span className="flex-1" />
            <span className={cn("font-mono text-xs font-medium", sevText[sev])}>{disk.pct}%</span>
          </div>
          <div
            className="truncate font-mono text-[10px] text-muted-foreground"
            title={disk.device ? `${disk.path || disk.device} · ${disk.device}` : disk.path}
          >
            {disk.path || (disk.type === "remote" ? "remote endpoint" : disk.device)}
          </div>
        </div>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-black/25">
        <div
          className={cn("h-full rounded-full", sevBarFill[sev])}
          style={{ width: `${Math.min(100, Math.max(0, disk.pct))}%` }}
        />
      </div>
      <div className="flex justify-between font-mono text-[10px] text-muted-foreground">
        <span>{disk.used} used</span>
        <span className={cn(sev === "crit" && sevText.crit)}>{disk.free} free</span>
      </div>
    </div>
  );
}

export function StorageStrip() {
  const { disks, isLoading } = useDisks();
  const localCount = disks.filter((d) => d.type === "local").length;
  const remoteCount = disks.filter((d) => d.type === "remote").length;

  return (
    <section className="rounded-xl border border-border bg-card px-4 py-3.5">
      <div className="mb-3 flex items-baseline gap-2">
        <span className="font-display text-xs font-semibold tracking-[0.12em] text-foreground/80 uppercase">
          Storage
        </span>
        {!isLoading && disks.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {localCount} local{remoteCount ? ` · ${remoteCount} remote` : ""}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : disks.length ? (
        <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
          {disks.map((disk, i) => (
            <DiskCell key={i} disk={disk} />
          ))}
        </div>
      ) : (
        <div className="py-4 text-center text-sm text-muted-foreground">
          No disk information available
        </div>
      )}
    </section>
  );
}
