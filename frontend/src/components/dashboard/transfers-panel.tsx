import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useActiveTransfers, useCancelTransfer, type Transfer } from "@/hooks/useTransfers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  IconTransfer,
  IconMovie,
  IconDeviceTv,
  IconBrandNetflix,
  IconPlus,
  IconRefresh,
  IconArrowNarrowRight,
  IconPlayerStop,
  IconInfoCircle,
} from "@tabler/icons-react";

function mediaIcon(mediaType: string) {
  switch (mediaType) {
    case "tvshows":
    case "series":
      return <IconDeviceTv className="size-4" />;
    case "anime":
      return <IconBrandNetflix className="size-4" />;
    default:
      return <IconMovie className="size-4" />;
  }
}

function parseProgress(progress?: string): number {
  if (!progress) return 0;
  const match = progress.match(/(\d{1,3})%/);
  return match ? Math.max(0, Math.min(100, Number(match[1]))) : 0;
}

function TransferRow({
  transfer,
  onCancel,
  cancelling,
}: {
  transfer: Transfer;
  onCancel: (id: string) => void;
  cancelling: boolean;
}) {
  const icon = mediaIcon(transfer.media_type);
  const queued = transfer.status === "queued";
  const pct = parseProgress(transfer.progress);

  return (
    <div className="flex items-center gap-3.5 border-b border-border px-4 py-3 last:border-b-0">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-md border border-border bg-black/20 text-muted-foreground">
        {icon}
      </span>

      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-2">
          <span className="truncate text-sm font-semibold text-foreground">
            {transfer.parsed_title || transfer.folder_name}
          </span>
          {transfer.season_name && (
            <span className="truncate text-xs text-muted-foreground">{transfer.season_name}</span>
          )}
        </div>
        <div className="mb-1.5 flex items-center gap-2">
          <div className="h-0.5 flex-1 overflow-hidden rounded-full bg-black/25">
            <div
              className={cn(
                "h-full rounded-full",
                queued ? "bg-muted-foreground" : "bg-brand-gradient-x"
              )}
              style={{ width: `${queued ? 0 : pct}%` }}
            />
          </div>
          <span className="min-w-9 text-right font-mono text-[10px] text-foreground">
            {queued ? "—" : `${pct}%`}
          </span>
        </div>
        <div className="flex items-center gap-1.5 truncate font-mono text-[10px] text-muted-foreground">
          <span className="truncate">{transfer.source_path}</span>
          <IconArrowNarrowRight className="size-3 shrink-0" />
          <span className="truncate">{transfer.dest_path}</span>
        </div>
      </div>

      {queued ? (
        <Badge variant="outline" className="shrink-0 text-muted-foreground">
          Queued
        </Badge>
      ) : (
        <Button
          variant="ghost"
          size="icon-sm"
          className="shrink-0 text-muted-foreground hover:text-rose-400"
          onClick={() => onCancel(transfer.id)}
          disabled={transfer.status !== "running" || cancelling}
          title="Cancel transfer"
        >
          <IconPlayerStop className="size-4" />
        </Button>
      )}
    </div>
  );
}

export function TransfersPanel() {
  const { data, isLoading, refetch } = useActiveTransfers();
  const cancelTransfer = useCancelTransfer();

  const running = data?.queue_status.running_count ?? 0;
  const queued = data?.queue_status.queued_count ?? 0;
  const transfers = data?.transfers ?? [];

  const handleCancel = async (id: string) => {
    try {
      await cancelTransfer.mutateAsync(id);
      toast.success("Transfer cancelled");
    } catch {
      toast.error("Failed to cancel transfer");
    }
  };

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <IconTransfer className="size-4 text-muted-foreground" />
        <span className="font-display text-sm font-semibold text-foreground">Active Transfers</span>
        {running > 0 && (
          <Badge className="gap-1.5 border-brand/40 bg-brand/15 text-brand-foreground">
            <span className="size-1.5 rounded-full bg-brand-hover" />
            {running} running
          </Badge>
        )}
        {queued > 0 && (
          <Badge variant="outline" className="text-muted-foreground">
            {queued} queued
          </Badge>
        )}
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => refetch()}
          title="Refresh"
        >
          <IconRefresh className="size-4" />
        </Button>
        <Link to="/media/$type" params={{ type: "movies" }}>
          <Button size="sm" className="gap-1.5 border-0 bg-brand-gradient-x text-white">
            <IconPlus className="size-4" />
            New transfer
          </Button>
        </Link>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-2 p-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : transfers.length ? (
        <div className="flex-1">
          {transfers.slice(0, 6).map((transfer) => (
            <TransferRow
              key={transfer.id}
              transfer={transfer}
              onCancel={handleCancel}
              cancelling={cancelTransfer.isPending}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
          <IconInfoCircle className="size-5" />
          <span className="text-sm">No active transfers</span>
          <Link to="/media/$type" params={{ type: "movies" }}>
            <Button variant="outline" size="sm" className="mt-1">
              Browse media to start one
            </Button>
          </Link>
        </div>
      )}
    </section>
  );
}
