import { Link } from "@tanstack/react-router";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  useActiveTransfers,
  useCancelTransfer,
  usePauseTransfer,
  useResumeTransfer,
  type Transfer,
} from "@/hooks/useTransfers";
import { useTransferPosters } from "@/hooks/useTransferPosters";
import { WebhookPoster } from "@/components/webhooks/webhook-bits";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { formatSizePair, formatSpeed, formatEta, transferPercent } from "@/lib/transfer-progress";
import {
  IconTransfer,
  IconPlus,
  IconRefresh,
  IconArrowNarrowRight,
  IconPlayerPause,
  IconPlayerPlay,
  IconCircleX,
  IconDots,
  IconTerminal2,
  IconInfoCircle,
} from "@tabler/icons-react";

/** Fixed column widths, shared by the header labels and every row. */
const COL_PERCENT = "w-10 shrink-0 text-right";
const COL_SPEED = "hidden w-24 shrink-0 text-right sm:block";
const COL_SIZE = "hidden w-20 shrink-0 text-right sm:block";

function TransferRow({
  transfer,
  posterUrl,
  onPause,
  onResume,
  onRequestStop,
  busy,
}: {
  transfer: Transfer;
  posterUrl?: string;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onRequestStop: (transfer: Transfer) => void;
  busy: boolean;
}) {
  const queued = transfer.status === "queued";
  const paused = transfer.status === "paused";
  const running = transfer.status === "running";
  const pct = transferPercent(transfer);
  const size = formatSizePair(transfer.bytes_transferred, transfer.total_bytes);
  const eta = running ? formatEta(transfer.eta_seconds) : null;

  return (
    <div className="flex items-center gap-3.5 border-b border-border px-4 py-3 last:border-b-0">
      <WebhookPoster
        item={{
          posterUrl,
          mediaType: transfer.media_type,
          title: transfer.parsed_title || transfer.folder_name,
        }}
        className="h-[54px] w-9"
        iconClassName="size-4"
      />

      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-2">
          <span className="truncate text-sm font-semibold text-foreground">
            {transfer.parsed_title || transfer.folder_name}
          </span>
          {transfer.season_name && (
            <span className="truncate text-xs text-muted-foreground">{transfer.season_name}</span>
          )}
          {paused && (
            <Badge variant="outline" className="shrink-0 border-amber-500/40 text-amber-400">
              Paused
            </Badge>
          )}
        </div>
        <div className="mb-1.5 h-1 overflow-hidden rounded-full bg-white/8">
          <div
            className={cn(
              "h-full rounded-full",
              queued && "bg-muted-foreground",
              paused && "bg-amber-500/70",
              running && "bg-brand-gradient-x"
            )}
            style={{ width: `${queued ? 0 : pct}%` }}
          />
        </div>
        <div className="flex items-center gap-1.5 truncate font-mono text-[10px] text-muted-foreground">
          <span className="truncate">{transfer.source_path}</span>
          <IconArrowNarrowRight className="size-3 shrink-0" />
          <span className="truncate">{transfer.dest_path}</span>
        </div>
      </div>

      <span className={cn(COL_PERCENT, "font-mono text-[11px] text-foreground")}>
        {queued ? "—" : `${pct}%`}
      </span>

      <div className={COL_SPEED}>
        {queued ? (
          <Badge variant="outline" className="text-muted-foreground">
            Queued
          </Badge>
        ) : paused ? (
          <span className="font-mono text-[11px] text-amber-400">Paused</span>
        ) : (
          <>
            <div className="font-mono text-xs font-semibold text-brand-foreground">
              {formatSpeed(transfer.speed_bps)}
            </div>
            {eta && <div className="font-mono text-[10px] text-muted-foreground">ETA {eta}</div>}
          </>
        )}
      </div>

      <div className={COL_SIZE}>
        {size ? (
          <>
            <div className="font-mono text-xs text-foreground">{size.value}</div>
            <div className="font-mono text-[10px] text-muted-foreground">{size.unit}</div>
          </>
        ) : (
          <span className="font-mono text-xs text-muted-foreground">—</span>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-0.5">
        {running && (
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => onPause(transfer.id)}
            disabled={busy}
            title="Pause transfer"
          >
            <IconPlayerPause className="size-4" />
            <span className="sr-only">Pause transfer</span>
          </Button>
        )}
        {paused && (
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => onResume(transfer.id)}
            disabled={busy}
            title="Resume transfer"
          >
            <IconPlayerPlay className="size-4" />
            <span className="sr-only">Resume transfer</span>
          </Button>
        )}

        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button variant="ghost" size="icon-sm" />}
            className="text-muted-foreground hover:text-foreground"
          >
            <IconDots className="size-4" />
            <span className="sr-only">More actions</span>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem render={<Link to="/transfers" />}>
              <IconTerminal2 />
              View logs
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={() => onRequestStop(transfer)}>
              <IconCircleX />
              Stop transfer
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="border-b border-border bg-muted/20 px-4 py-1.5 font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
      {children}
    </div>
  );
}

export function TransfersPanel() {
  const { data, isLoading, refetch } = useActiveTransfers();
  const cancelTransfer = useCancelTransfer();
  const pauseTransfer = usePauseTransfer();
  const resumeTransfer = useResumeTransfer();
  const posters = useTransferPosters();

  const [stopTarget, setStopTarget] = useState<Transfer | null>(null);

  const running = data?.queue_status.running_count ?? 0;
  const queuedCount = data?.queue_status.queued_count ?? 0;
  const transfers = useMemo(() => data?.transfers ?? [], [data?.transfers]);

  // Queued transfers are grouped under their own heading, matching how the
  // queue actually behaves: they are waiting, not progressing.
  const { activeRows, queuedRows } = useMemo(() => {
    const visible = transfers.slice(0, 8);
    return {
      activeRows: visible.filter((t) => t.status !== "queued"),
      queuedRows: visible.filter((t) => t.status === "queued"),
    };
  }, [transfers]);

  const anyPausable = activeRows.some((t) => t.status === "running");
  const busy = pauseTransfer.isPending || resumeTransfer.isPending || cancelTransfer.isPending;

  const handlePause = async (id: string) => {
    try {
      await pauseTransfer.mutateAsync(id);
      toast.success("Transfer paused");
    } catch {
      toast.error("Failed to pause transfer");
    }
  };

  const handleResume = async (id: string) => {
    try {
      const result = await resumeTransfer.mutateAsync(id);
      toast.success(result?.message ?? "Transfer resumed");
    } catch {
      toast.error("Failed to resume transfer");
    }
  };

  const handlePauseAll = async () => {
    const targets = activeRows.filter((t) => t.status === "running");
    const results = await Promise.allSettled(targets.map((t) => pauseTransfer.mutateAsync(t.id)));
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed) {
      toast.error(`Paused ${targets.length - failed} of ${targets.length} transfers`);
    } else {
      toast.success(`Paused ${targets.length} transfer${targets.length === 1 ? "" : "s"}`);
    }
  };

  const handleStop = async (id: string) => {
    try {
      await cancelTransfer.mutateAsync(id);
      toast.success("Transfer stopped");
    } catch {
      toast.error("Failed to stop transfer");
    }
  };

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card">
      {/* Actions wrap to their own line rather than squeezing the title on phones */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2 border-b border-border px-4 py-3">
        <IconTransfer className="size-4 shrink-0 text-muted-foreground" />
        <span className="font-display text-sm font-semibold whitespace-nowrap text-foreground">
          Active Transfers
        </span>
        {running > 0 && (
          <Badge className="gap-1.5 border-brand/40 bg-brand/15 text-brand-foreground">
            <span className="size-1.5 rounded-full bg-brand-hover" />
            {running} running
          </Badge>
        )}
        {queuedCount > 0 && (
          <Badge variant="outline" className="text-muted-foreground">
            {queuedCount} queued
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-2">
          {anyPausable && (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-foreground"
              onClick={handlePauseAll}
              disabled={busy}
            >
              Pause all
            </Button>
          )}
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
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-2 p-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : transfers.length ? (
        <div className="flex-1">
          {/* Column headings so the speed/size figures are self-explanatory */}
          <div className="flex items-center gap-3.5 border-b border-border px-4 py-1.5 font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
            <span className="w-9 shrink-0" />
            <span className="min-w-0 flex-1">Transfer</span>
            <span className={COL_PERCENT} />
            <span className={COL_SPEED}>Speed</span>
            <span className={COL_SIZE}>Size</span>
            <span className="w-[3.75rem] shrink-0" />
          </div>

          {activeRows.map((transfer) => (
            <TransferRow
              key={transfer.id}
              transfer={transfer}
              posterUrl={posters.get(transfer.id)}
              onPause={handlePause}
              onResume={handleResume}
              onRequestStop={setStopTarget}
              busy={busy}
            />
          ))}

          {queuedRows.length > 0 && (
            <>
              <SectionLabel>Queued · {queuedRows.length}</SectionLabel>
              {queuedRows.map((transfer) => (
                <TransferRow
                  key={transfer.id}
                  transfer={transfer}
                  posterUrl={posters.get(transfer.id)}
                  onPause={handlePause}
                  onResume={handleResume}
                  onRequestStop={setStopTarget}
                  busy={busy}
                />
              ))}
            </>
          )}
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

      <ConfirmDialog
        open={Boolean(stopTarget)}
        onOpenChange={(open) => !open && setStopTarget(null)}
        icon={<IconCircleX />}
        title="Stop this transfer?"
        description={
          <>
            <span className="font-medium text-foreground">
              {stopTarget?.parsed_title || stopTarget?.folder_name}
            </span>{" "}
            will stop mid-transfer and be marked cancelled. Files already copied stay in place, but
            the remaining files are not transferred. Use Pause instead if you intend to continue
            later.
          </>
        }
        confirmLabel="Stop transfer"
        cancelLabel="Keep running"
        pending={cancelTransfer.isPending}
        onConfirm={() => {
          if (stopTarget) handleStop(stopTarget.id);
          setStopTarget(null);
        }}
      />
    </section>
  );
}
