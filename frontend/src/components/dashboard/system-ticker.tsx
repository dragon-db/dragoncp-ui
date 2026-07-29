import { cn } from "@/lib/utils";
import { useActiveTransfers } from "@/hooks/useTransfers";
import { useWebhookNotifications } from "@/hooks/useWebhooks";
import { useDisks, diskSeverity, sevText } from "@/components/dashboard/disk-utils";

function Cell({
  label,
  value,
  tone = "text-foreground",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-center gap-2 font-mono">
      <span className="text-[10px] tracking-[0.08em] text-muted-foreground uppercase">{label}</span>
      <span className={cn("text-xs font-medium", tone)}>{value}</span>
    </div>
  );
}

export function SystemTicker() {
  const { disks } = useDisks();
  const activeQuery = useActiveTransfers();
  const webhooksQuery = useWebhookNotifications({ limit: 10 });

  const peak = disks.reduce((m, d) => Math.max(m, d.pct), 0);
  const nearFull = disks.filter((d) => d.pct >= 78).length;
  const peakSev = diskSeverity(peak);

  const running = activeQuery.data?.queue_status.running_count ?? 0;
  const maxConcurrent = activeQuery.data?.queue_status.max_concurrent ?? 3;
  const queued = activeQuery.data?.queue_status.queued_count ?? 0;
  const hooks = webhooksQuery.data?.total ?? 0;

  const attention = nearFull > 0;
  const now = new Date();
  const stamp = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2.5">
        <span className="relative flex size-2">
          <span
            className={cn(
              "absolute inline-flex size-full animate-ping rounded-full opacity-60",
              attention ? "bg-amber-400" : "bg-emerald-400"
            )}
          />
          <span
            className={cn(
              "relative inline-flex size-2 rounded-full",
              attention ? "bg-amber-400" : "bg-emerald-400"
            )}
          />
        </span>
        <span className="font-display text-sm font-semibold text-foreground">
          {attention ? "Attention" : "Operational"}
        </span>
        <span className="text-xs text-muted-foreground">
          {attention
            ? `${nearFull} disk${nearFull > 1 ? "s" : ""} near full`
            : "All systems nominal"}
        </span>
      </div>

      <span className="hidden h-4 w-px bg-border sm:block" />

      <Cell label="Peak disk" value={disks.length ? `${peak}%` : "—"} tone={sevText[peakSev]} />
      <Cell label="Queue" value={`${running}/${maxConcurrent}`} tone="text-brand-hover" />
      <Cell label="Queued" value={String(queued)} />
      <Cell label="Webhooks" value={String(hooks)} />

      <span className="flex-1" />
      <span className="font-mono text-[11px] text-muted-foreground">updated {stamp}</span>
    </div>
  );
}
