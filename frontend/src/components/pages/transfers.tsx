import { PageHeader } from "@/components/layout/page-header";
import { PageTabsList } from "@/components/layout/page-tabs";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import {
  FilterChips,
  ListPagination,
  ListSearch,
  RowCheckbox,
  SelectionBar,
} from "@/components/layout/list-controls";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { StatTiles } from "@/components/layout/stat-tiles";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import {
  useActiveTransfers,
  useAllTransfers,
  useBulkDeleteTransfers,
  useCancelTransfer,
  useCleanupTransfers,
  useDeleteTransfer,
  usePauseTransfer,
  useRestartTransfer,
  useResumeTransfer,
  useTransferLogs,
  type Transfer,
} from "@/hooks/useTransfers";
import {
  onTransferComplete,
  onTransferLogs,
  onTransferPromoted,
  onTransferQueued,
  onTransferUpdate,
  subscribeTransferLogs,
  unsubscribeTransferLogs,
} from "@/services/socket";
import { useTransferPosters } from "@/hooks/useTransferPosters";
import { useSimulationStatus } from "@/hooks/useSimulation";
import { WebhookPoster, MediaBadge } from "@/components/webhooks/webhook-bits";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import { ProgressMeter, TransferStatusBadge } from "@/components/transfers/transfer-bits";
import { TransferDetailPanel, type TransferActions } from "@/components/transfers/transfer-detail";
import { SimulationBadge, SimulationPanel } from "@/components/transfers/simulation-panel";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  formatBytes,
  formatEta,
  formatSizePair,
  formatSpeed,
  transferPercent,
} from "@/lib/transfer-progress";
// Relative times come from the shared webhook helper so "2h ago" reads the same
// on both pages.
import { timeAgo } from "@/lib/webhook-grouping";
import {
  IconActivity,
  IconArrowBackUp,
  IconCircleX,
  IconFlask,
  IconHistory,
  IconPlayerPause,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
} from "@tabler/icons-react";

const ACTIVE_STATUSES = new Set(["running", "pending", "queued", "paused"]);

// What History covers: everything that has finished, one way or another. Asked
// for by name so the server can leave live transfers out of the page rather
// than the browser dropping them after the fact.
const HISTORY_STATUSES = ["completed", "failed", "cancelled"] as const;

const HISTORY_FILTERS = [
  { value: "all", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Stopped" },
] as const;

const HISTORY_PAGE_SIZE = 25;

interface TransferRowProps {
  transfer: Transfer;
  posterUrl?: string;
  now: number;
  expanded: boolean;
  actions: TransferActions;
  busy: boolean;
  /** Selection state, present only where rows can be picked for a bulk action. */
  selection?: {
    selected: boolean;
    onSelectedChange: (selected: boolean) => void;
  };
}

/**
 * One row per transfer, expanding in place to its full detail and live output —
 * the same way a webhook arrival opens, so the two pages are navigated alike.
 */
function TransferRow({
  transfer,
  posterUrl,
  now,
  expanded,
  actions,
  busy,
  selection,
}: TransferRowProps) {
  const status = transfer.status;
  const running = status === "running";
  const paused = status === "paused";
  const queued = status === "queued" || status === "pending";
  const percent = transferPercent(transfer);
  const size = formatSizePair(transfer.bytes_transferred, transfer.total_bytes);
  const eta = running ? formatEta(transfer.eta_seconds) : null;

  // Output is only fetched once the row is open, and only kept fresh while the
  // transfer is still producing any.
  const logsQuery = useTransferLogs(transfer.id, { enabled: expanded, live: running });

  // Each fact is its own element so narrow screens wrap them rather than
  // truncating the line.
  const facts = [
    transfer.season_name || undefined,
    running ? formatSpeed(transfer.speed_bps) : undefined,
    eta ? `ETA ${eta}` : undefined,
    size ? `${size.value} ${size.unit}` : undefined,
    timeAgo(transfer.start_time || transfer.created_at),
  ].filter(Boolean) as string[];

  return (
    <AccordionItem value={transfer.id} className="border-b border-border last:border-b-0">
      <div className="flex flex-col items-stretch sm:flex-row">
        {/* The tick stays beside the row at every width. On phones the outer
            stack turns vertical, which would otherwise strand it on a line of
            its own above the title. */}
        <div className="flex min-w-0 flex-1 items-center">
          {selection && (
            <RowCheckbox
              checked={selection.selected}
              onCheckedChange={selection.onSelectedChange}
              label={`Select ${transfer.parsed_title || transfer.folder_name}`}
            />
          )}
          <AccordionTrigger className="min-w-0 flex-1 items-start gap-3 px-4 py-3 no-underline hover:bg-muted/40 hover:no-underline sm:items-center">
            <span className="flex min-w-0 flex-1 items-start gap-3 sm:items-center sm:gap-4">
              <WebhookPoster
                item={{
                  posterUrl,
                  mediaType: transfer.media_type,
                  title: transfer.parsed_title || transfer.folder_name,
                }}
                className="h-[62px] w-[44px] shrink-0"
                iconClassName="size-4"
              />
              <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-semibold break-words text-foreground">
                    {transfer.parsed_title || transfer.folder_name}
                  </span>
                  <MediaBadge mediaType={transfer.media_type} />
                  {transfer.is_simulation && <SimulationBadge />}
                  {/* On phones the status reads with the title; from sm up it
                    keeps its column at the end of the row. */}
                  <TransferStatusBadge status={status} className="sm:hidden" />
                </span>

                {(running || paused || queued) && (
                  <span className="flex items-center gap-2.5">
                    <ProgressMeter percent={percent} status={status} className="flex-1" />
                    <span className="w-9 shrink-0 text-right font-mono text-[10.5px] text-foreground tabular-nums">
                      {queued ? "—" : `${percent}%`}
                    </span>
                  </span>
                )}

                <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[11px] text-muted-foreground">
                  {facts.map((fact, index) => (
                    // Separator trails its fact so a wrapped line never opens with a dot.
                    <span key={`${fact}-${index}`} className="flex items-center gap-1.5">
                      {fact}
                      {index < facts.length - 1 && <span className="opacity-50">·</span>}
                    </span>
                  ))}
                </span>
              </span>
              <TransferStatusBadge status={status} className="hidden sm:inline-flex" />
            </span>
          </AccordionTrigger>
        </div>

        {/* The one action worth reaching without opening the row */}
        {(running || paused || status === "failed") && (
          <div className="flex items-center px-4 pb-3 sm:p-0 sm:pr-4">
            {running && (
              <Button
                size="sm"
                variant="outline"
                className="w-full sm:w-auto"
                disabled={busy}
                onClick={() => actions.onPause(transfer)}
              >
                <IconPlayerPause className="mr-1.5 size-3.5" />
                Pause
              </Button>
            )}
            {paused && (
              <Button
                size="sm"
                className="w-full border-0 bg-brand-gradient-x text-white sm:w-auto"
                disabled={busy}
                onClick={() => actions.onResume(transfer)}
              >
                <IconPlayerPlay className="mr-1.5 size-3.5" />
                Resume
              </Button>
            )}
            {status === "failed" && (
              <Button
                size="sm"
                className="w-full border-0 bg-brand-gradient-x text-white sm:w-auto"
                disabled={busy}
                onClick={() => actions.onRestart(transfer)}
              >
                <IconArrowBackUp className="mr-1.5 size-3.5" />
                Retry
              </Button>
            )}
          </div>
        )}
      </div>

      <AccordionContent className="bg-black/20 px-4 pt-1 pb-4">
        <TransferDetailPanel
          transfer={transfer}
          logs={logsQuery.data?.logs ?? []}
          logsLoading={logsQuery.isLoading}
          now={now}
          actions={actions}
          busy={busy}
        />
      </AccordionContent>
    </AccordionItem>
  );
}

function TransferList({
  transfers,
  loading,
  ...rowProps
}: {
  transfers: Transfer[];
  loading: boolean;
  posters: Map<string, string>;
  now: number;
  actions: TransferActions;
  busy: boolean;
  expanded: string[];
  onExpandedChange: (value: string[]) => void;
  empty: React.ReactNode;
  /** Ids currently picked; omit entirely to hide the checkboxes. */
  selectedIds?: Set<string>;
  onSelectedChange?: (id: string, selected: boolean) => void;
}) {
  const {
    posters,
    now,
    actions,
    busy,
    expanded,
    onExpandedChange,
    empty,
    selectedIds,
    onSelectedChange,
  } = rowProps;

  if (loading) {
    return (
      <div className="flex flex-col gap-3 p-4">
        {[1, 2, 3].map((index) => (
          <Skeleton key={index} className="h-20 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (!transfers.length) return <>{empty}</>;

  return (
    <Accordion value={expanded} onValueChange={(value) => onExpandedChange(value as string[])}>
      {transfers.map((transfer) => (
        <TransferRow
          key={transfer.id}
          transfer={transfer}
          posterUrl={posters.get(transfer.id)}
          now={now}
          expanded={expanded.includes(transfer.id)}
          actions={actions}
          busy={busy}
          selection={
            selectedIds && onSelectedChange
              ? {
                  selected: selectedIds.has(transfer.id),
                  onSelectedChange: (selected) => onSelectedChange(transfer.id, selected),
                }
              : undefined
          }
        />
      ))}
    </Accordion>
  );
}

export function TransfersPage() {
  const [activeTab, setActiveTab] = useState("activity");
  const [historyFilter, setHistoryFilter] = useState<string>("all");
  const [historySearch, setHistorySearch] = useState("");
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyLimit, setHistoryLimit] = useState(HISTORY_PAGE_SIZE);
  const [expanded, setExpanded] = useState<string[]>([]);

  // Rows picked for deletion. `selectAllMatching` is deliberately not a list of
  // ids: it means every record the filter finds, which the server re-evaluates
  // at delete time rather than the browser enumerating thousands of ids.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [selectAllMatching, setSelectAllMatching] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);

  const historyQuery_search = useDebouncedValue(historySearch, 300);

  // Ticks once a second so elapsed times and pause durations stay honest
  // without re-fetching anything.
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const queryClient = useQueryClient();
  const activeQuery = useActiveTransfers();
  const allQuery = useAllTransfers({
    limit: historyLimit,
    offset: historyOffset,
    status: historyFilter === "all" ? undefined : historyFilter,
    search: historyQuery_search || undefined,
    statuses: historyFilter === "all" ? [...HISTORY_STATUSES] : undefined,
  });
  // The Simulate badge counts every simulated row on the board, which History's
  // page cannot see past its own window.
  const simulationStatus = useSimulationStatus(false);
  const posters = useTransferPosters();

  const cancelMutation = useCancelTransfer();
  const restartMutation = useRestartTransfer();
  const deleteMutation = useDeleteTransfer();
  const cleanupMutation = useCleanupTransfers();
  const bulkDeleteMutation = useBulkDeleteTransfers();
  const pauseMutation = usePauseTransfer();
  const resumeMutation = useResumeTransfer();

  const [stopTarget, setStopTarget] = useState<Transfer | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Transfer | null>(null);
  const [confirmCleanup, setConfirmCleanup] = useState(false);

  const busy =
    pauseMutation.isPending ||
    resumeMutation.isPending ||
    cancelMutation.isPending ||
    restartMutation.isPending;

  const activeTransfers = useMemo(
    () => activeQuery.data?.transfers ?? [],
    [activeQuery.data?.transfers]
  );

  // Already filtered, searched and paged by the server; the guard only covers a
  // transfer that started between the query and the render.
  const historyTransfers = useMemo(
    () => (allQuery.data?.transfers ?? []).filter((t) => !ACTIVE_STATUSES.has(t.status)),
    [allQuery.data?.transfers]
  );

  // Memoised so the derived counts are not rebuilt on every render.
  const historyStatusCounts = useMemo(
    () => allQuery.data?.status_counts ?? {},
    [allQuery.data?.status_counts]
  );
  const historyTotal = allQuery.data?.total ?? 0;

  // Reset to the first page whenever the question changes - page 4 of the old
  // results is not page 4 of the new ones.
  useEffect(() => {
    setHistoryOffset(0);
    setSelectedIds(new Set());
    setSelectAllMatching(false);
  }, [historyFilter, historyQuery_search, historyLimit]);

  const historyFilterChoices = useMemo(
    () =>
      HISTORY_FILTERS.map((filter) => ({
        ...filter,
        count:
          filter.value === "all"
            ? Object.values(historyStatusCounts).reduce((sum, n) => sum + n, 0)
            : (historyStatusCounts[filter.value] ?? 0),
      })),
    [historyStatusCounts]
  );

  const toggleSelected = (id: string, selected: boolean) => {
    // Picking rows by hand contradicts "everything matching", so the broader
    // claim is dropped the moment one row is touched.
    setSelectAllMatching(false);
    setSelectedIds((current) => {
      const next = new Set(current);
      if (selected) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const pageIds = historyTransfers.map((transfer) => transfer.id);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));

  const togglePageSelection = () => {
    setSelectAllMatching(false);
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allPageSelected) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
    setSelectAllMatching(false);
  };

  const selectedCount = selectAllMatching ? historyTotal : selectedIds.size;

  // Completed records are what Browse Media reads to mark something synced, so
  // the confirmation has to say when they are in the set being deleted.
  const includesCompleted = selectAllMatching
    ? historyFilter === "all" || historyFilter === "completed"
    : historyTransfers.some((t) => selectedIds.has(t.id) && t.status === "completed");

  const runBulkDelete = async () => {
    try {
      const result = await bulkDeleteMutation.mutateAsync(
        selectAllMatching
          ? {
              all_matching: true,
              status: historyFilter === "all" ? undefined : historyFilter,
              search: historyQuery_search || undefined,
              statuses: historyFilter === "all" ? [...HISTORY_STATUSES] : undefined,
            }
          : { ids: [...selectedIds] }
      );
      toast.success(result.message);
      clearSelection();
      setHistoryOffset(0);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete transfers");
    } finally {
      setConfirmBulkDelete(false);
    }
  };

  /** Combined speed and remaining bytes across everything currently copying. */
  const liveTotals = useMemo(() => {
    let speed = 0;
    let remaining = 0;
    let running = 0;
    for (const transfer of activeTransfers) {
      if (transfer.status !== "running") continue;
      running += 1;
      speed += transfer.speed_bps ?? 0;
      if (transfer.total_bytes != null && transfer.bytes_transferred != null) {
        remaining += Math.max(0, transfer.total_bytes - transfer.bytes_transferred);
      }
    }
    return { speed, remaining, running };
  }, [activeTransfers]);

  // Counted across the whole table by the server, so the tiles describe the
  // record rather than whichever page happens to be open.
  const historyTotals = useMemo(() => {
    const completed = historyStatusCounts.completed ?? 0;
    const failed = historyStatusCounts.failed ?? 0;
    const cancelled = historyStatusCounts.cancelled ?? 0;
    const decided = completed + failed;
    return {
      total: completed + failed + cancelled,
      completed,
      failed,
      cancelled,
      successRate: decided ? Math.round((completed / decided) * 100) : null,
    };
  }, [historyStatusCounts]);

  const pausedCount = activeTransfers.filter((t) => t.status === "paused").length;

  // Simulated rows left on the board, running or finished. Surfaced on the tab
  // so an abandoned simulation is visible without opening it.
  const simulationCount = simulationStatus.data?.total ?? 0;
  const queuedCount = activeQuery.data?.queue_status.queued_count ?? 0;
  const maxConcurrent = activeQuery.data?.queue_status.max_concurrent ?? 3;

  // Ask the server for output only while a row is open, and stop when it
  // closes. Without a subscription the server does not even build the payload.
  useEffect(() => {
    expanded.forEach(subscribeTransferLogs);
    return () => expanded.forEach(unsubscribeTransferLogs);
  }, [expanded]);

  useEffect(() => {
    // Progress arrives many times a second per transfer. Writing it straight
    // into the cache keeps the numbers live without a refetch per tick, which
    // is what made the old page hammer the API while anything was running.
    const offProgress = onTransferUpdate((payload) => {
      const stats = payload.stats;
      queryClient.setQueryData(
        ["transfers", "active"],
        (previous: { transfers: Transfer[] } | undefined) => {
          if (!previous?.transfers) return previous;
          return {
            ...previous,
            transfers: previous.transfers.map((transfer) =>
              transfer.id === payload.transfer_id
                ? {
                    ...transfer,
                    status: payload.status || transfer.status,
                    progress: payload.progress ?? transfer.progress,
                    log_count: payload.log_count ?? transfer.log_count,
                    ...(stats ?? {}),
                  }
                : transfer
            ),
          };
        }
      );
    });

    // Output arrives on its own event, only for transfers this client asked
    // for. Everyone used to receive every transfer's log tail several times a
    // second whether or not they had a row open.
    const offLogs = onTransferLogs((payload) => {
      queryClient.setQueryData(
        ["transfers", payload.transfer_id, "logs"],
        (previous: { logs: string[] } | undefined) =>
          previous ? { ...previous, logs: payload.logs } : previous
      );
    });

    const offComplete = onTransferComplete(() => {
      activeQuery.refetch();
      allQuery.refetch();
    });
    const offQueued = onTransferQueued(() => {
      activeQuery.refetch();
    });
    const offPromoted = onTransferPromoted(() => {
      activeQuery.refetch();
    });

    return () => {
      offProgress();
      offLogs();
      offComplete();
      offQueued();
      offPromoted();
    };
  }, [activeQuery, allQuery, queryClient]);

  const refreshAll = () => {
    activeQuery.refetch();
    allQuery.refetch();
  };

  const actions: TransferActions = {
    onPause: async (transfer) => {
      try {
        await pauseMutation.mutateAsync(transfer.id);
        toast.success("Transfer paused");
        activeQuery.refetch();
      } catch {
        toast.error("Could not pause the transfer");
      }
    },
    onResume: async (transfer) => {
      try {
        const result = await resumeMutation.mutateAsync(transfer.id);
        toast.success(result?.message ?? "Transfer resumed");
        refreshAll();
      } catch {
        toast.error("Could not resume the transfer");
      }
    },
    onStop: (transfer) => setStopTarget(transfer),
    onRestart: async (transfer) => {
      try {
        await restartMutation.mutateAsync(transfer.id);
        toast.success("Transfer restarted");
        refreshAll();
      } catch {
        toast.error("Could not restart the transfer");
      }
    },
    onDelete: (transfer) => setDeleteTarget(transfer),
  };

  const runStop = async (transfer: Transfer) => {
    try {
      await cancelMutation.mutateAsync(transfer.id);
      toast.success("Transfer stopped");
      refreshAll();
    } catch {
      toast.error("Could not stop the transfer");
    }
  };

  const runDelete = async (transfer: Transfer) => {
    try {
      await deleteMutation.mutateAsync(transfer.id);
      toast.success("Transfer deleted");
      refreshAll();
      queryClient.removeQueries({ queryKey: ["transfers", transfer.id, "logs"] });
      setExpanded((prev) => prev.filter((id) => id !== transfer.id));
    } catch {
      toast.error("Could not delete the transfer");
    }
  };

  const runCleanup = async () => {
    try {
      const result = await cleanupMutation.mutateAsync();
      toast.success(`Removed ${result?.cleaned_count ?? 0} duplicate transfer(s)`);
      refreshAll();
    } catch {
      toast.error("Could not remove duplicates");
    }
  };

  const rowProps = {
    posters,
    now,
    actions,
    busy,
    expanded,
    onExpandedChange: setExpanded,
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Transfers" description="Copies running now and everything that has run">
        <Button
          variant="outline"
          onClick={refreshAll}
          disabled={activeQuery.isFetching || allQuery.isFetching}
        >
          <IconRefresh
            className={cn(
              "mr-2 h-4 w-4",
              (activeQuery.isFetching || allQuery.isFetching) && "animate-spin"
            )}
          />
          Refresh
        </Button>
        <Button
          variant="outline"
          onClick={() => setConfirmCleanup(true)}
          disabled={cleanupMutation.isPending}
        >
          <IconTrash className="mr-2 h-4 w-4" />
          Remove duplicates
        </Button>
      </PageHeader>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <PageTabsList
          items={[
            {
              value: "activity",
              label: "Activity",
              icon: IconActivity,
              count: activeTransfers.length,
            },
            {
              value: "history",
              label: "History",
              icon: IconHistory,
              // Everything on record, not just the page in view - and not
              // affected by a search in progress.
              count: allQuery.data?.unfiltered_total ?? 0,
            },
            {
              value: "simulate",
              label: "Simulate",
              icon: IconFlask,
              // Only counts when something is actually on the board
              count: simulationCount || undefined,
              // A tool, not another view of the transfer list
              atEnd: true,
            },
          ]}
        />

        <TabsContent value="activity" className="mt-4 flex flex-col gap-3.5">
          <StatTiles
            items={[
              {
                label: "Copying now",
                value: liveTotals.running,
                unit: `of ${maxConcurrent} slots`,
                tone: liveTotals.running ? "ok" : "default",
              },
              {
                label: "Waiting",
                value: queuedCount,
                unit: queuedCount === 1 ? "in queue" : "in queue",
                tone: queuedCount ? "warn" : "default",
              },
              {
                label: "Paused",
                value: pausedCount,
                unit: "resumable",
                tone: pausedCount ? "warn" : "default",
              },
              {
                label: "Throughput",
                value: liveTotals.speed ? formatSpeed(liveTotals.speed) : "—",
                unit: liveTotals.remaining ? `${formatBytes(liveTotals.remaining)} left` : "",
                tone: liveTotals.speed ? "ok" : "default",
              },
            ]}
          />

          <SectionCard
            label="In flight"
            description="Running, queued and paused copies"
            toolbar={
              <>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {activeQuery.data?.queue_status.running_count ?? 0}/{maxConcurrent} running
                  {queuedCount ? ` · ${queuedCount} queued` : ""}
                </span>
                <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                  {activeTransfers.length} shown
                </span>
              </>
            }
          >
            <TransferList
              transfers={activeTransfers}
              loading={activeQuery.isLoading}
              {...rowProps}
              empty={
                <SectionEmpty
                  icon={IconActivity}
                  title="Nothing is copying"
                  hint="Transfers started from Browse Media, or by a Radarr or Sonarr import, appear here while they run."
                />
              }
            />
          </SectionCard>
        </TabsContent>

        <TabsContent value="history" className="mt-4 flex flex-col gap-3.5">
          <StatTiles
            items={[
              { label: "Transfers", value: historyTotals.total, unit: "on record" },
              {
                label: "Completed",
                value: historyTotals.completed,
                unit: "finished",
                tone: "ok",
              },
              {
                label: "Failed",
                value: historyTotals.failed,
                unit: "needs a retry",
                tone: historyTotals.failed ? "crit" : "default",
              },
              {
                label: "Success rate",
                value: historyTotals.successRate == null ? "—" : `${historyTotals.successRate}%`,
                unit: historyTotals.successRate == null ? "" : "of finished runs",
                tone:
                  historyTotals.successRate == null
                    ? "default"
                    : historyTotals.successRate >= 90
                      ? "ok"
                      : historyTotals.successRate >= 70
                        ? "warn"
                        : "crit",
              },
            ]}
          />

          <SectionCard
            label="Past runs"
            description="Newest first"
            toolbar={
              <>
                <FilterChips
                  choices={historyFilterChoices}
                  value={historyFilter}
                  onChange={setHistoryFilter}
                />
                <ListSearch
                  value={historySearch}
                  onChange={setHistorySearch}
                  placeholder="Search title, season or path"
                  className="ml-auto"
                />
              </>
            }
          >
            {historyTransfers.length > 0 && (
              <SelectionBar
                selectedCount={selectedCount}
                pageCount={historyTransfers.length}
                total={historyTotal}
                allPageSelected={allPageSelected}
                allMatchingSelected={selectAllMatching}
                onTogglePage={togglePageSelection}
                onSelectAllMatching={() => setSelectAllMatching(true)}
                onClear={clearSelection}
                onDelete={() => setConfirmBulkDelete(true)}
                busy={bulkDeleteMutation.isPending}
                noun="transfers"
                filterLabel={
                  historyFilter === "all"
                    ? undefined
                    : HISTORY_FILTERS.find((f) => f.value === historyFilter)?.label.toLowerCase()
                }
              />
            )}

            <TransferList
              transfers={historyTransfers}
              loading={allQuery.isLoading}
              {...rowProps}
              selectedIds={selectAllMatching ? new Set(pageIds) : selectedIds}
              onSelectedChange={toggleSelected}
              empty={
                <SectionEmpty
                  icon={IconHistory}
                  title={
                    historySearch
                      ? `Nothing matches "${historySearch}"`
                      : historyFilter === "all"
                        ? "No transfers yet"
                        : "Nothing matches this filter"
                  }
                  hint={
                    historyFilter === "all" && !historySearch
                      ? "Finished copies are kept here with their full output."
                      : undefined
                  }
                  action={
                    historyFilter !== "all" || historySearch ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setHistoryFilter("all");
                          setHistorySearch("");
                        }}
                      >
                        Show all
                      </Button>
                    ) : undefined
                  }
                />
              }
            />

            <ListPagination
              offset={historyOffset}
              limit={historyLimit}
              total={historyTotal}
              count={historyTransfers.length}
              onOffsetChange={setHistoryOffset}
              onLimitChange={setHistoryLimit}
              noun="transfers"
            />
          </SectionCard>
        </TabsContent>
        <TabsContent value="simulate" className="mt-4">
          <SimulationPanel onStarted={() => setActiveTab("activity")} />
        </TabsContent>
      </Tabs>

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
            stops where it is and is marked stopped. Files already copied stay in place, but the
            rest are not transferred. Pause instead if you mean to continue later.
          </>
        }
        confirmLabel="Stop transfer"
        cancelLabel="Keep running"
        pending={cancelMutation.isPending}
        onConfirm={() => {
          if (stopTarget) runStop(stopTarget);
          setStopTarget(null);
        }}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        icon={<IconTrash />}
        title="Delete this transfer record?"
        description={
          <>
            The record for{" "}
            <span className="font-medium text-foreground">
              {deleteTarget?.parsed_title || deleteTarget?.folder_name}
            </span>{" "}
            and its output are removed from the history. Copied files are not touched.
            {deleteTarget?.status === "paused" &&
              " This transfer is paused, so deleting it also means it can no longer be resumed."}
          </>
        }
        confirmLabel="Delete record"
        pending={deleteMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) runDelete(deleteTarget);
          setDeleteTarget(null);
        }}
      />

      <ConfirmDialog
        open={confirmCleanup}
        onOpenChange={setConfirmCleanup}
        icon={<IconTrash />}
        title="Remove duplicate transfers?"
        description="Where several completed transfers share a destination, only the most recent is kept. Copied files are not touched."
        confirmLabel="Remove duplicates"
        pending={cleanupMutation.isPending}
        onConfirm={runCleanup}
      />

      <ConfirmDialog
        open={confirmBulkDelete}
        onOpenChange={setConfirmBulkDelete}
        icon={<IconTrash />}
        title={
          selectedCount === 1
            ? "Delete this transfer record?"
            : `Delete ${selectedCount} transfer records?`
        }
        description={
          <>
            {selectAllMatching
              ? `Every transfer this filter finds — all ${historyTotal} of them — is removed from the history, including any on pages you have not opened. `
              : `The selected records and their output are removed from the history. `}
            Copied files are not touched.
            {includesCompleted && (
              <>
                {" "}
                Deleting completed records also clears their sync history, so the media they covered
                will show as not yet synced in Browse Media.
              </>
            )}{" "}
            Transfers still running are left alone.
          </>
        }
        confirmLabel={selectedCount === 1 ? "Delete record" : `Delete ${selectedCount} records`}
        pending={bulkDeleteMutation.isPending}
        onConfirm={runBulkDelete}
      />
    </div>
  );
}
