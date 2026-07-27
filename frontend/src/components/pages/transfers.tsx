import { PageHeader } from "@/components/layout/page-header";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import {
  useActiveTransfers,
  useAllTransfers,
  useCancelTransfer,
  useCleanupTransfers,
  useDeleteTransfer,
  usePauseTransfer,
  useRestartTransfer,
  useResumeTransfer,
  type Transfer,
} from "@/hooks/useTransfers";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import {
  formatSizePair,
  formatSpeed,
  formatEta,
  transferPercent,
} from "@/lib/transfer-progress";
import {
  onTransferComplete,
  onTransferPromoted,
  onTransferQueued,
  onTransferUpdate,
} from "@/services/socket";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTransferPosters } from "@/hooks/useTransferPosters";
import { WebhookPoster } from "@/components/webhooks/webhook-bits";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  IconArrowsMaximize,
  IconInfoCircle,
  IconList,
  IconCircleX,
  IconPlayerPause,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
  IconArrowBackUp,
  IconEye,
  IconTerminal2,
} from "@tabler/icons-react";

interface LogTab {
  transferId: string;
  title: string;
  status: string;
  logs: string[];
  autoScroll: boolean;
}

function getStatusBadge(status: string) {
  switch (status) {
    case "running":
      return <Badge className="border-blue-500/50 bg-blue-500/20 text-blue-400">RUNNING</Badge>;
    case "completed":
      return (
        <Badge className="border-green-500/50 bg-green-500/20 text-green-400">COMPLETED</Badge>
      );
    case "failed":
      return <Badge className="border-red-500/50 bg-red-500/20 text-red-400">FAILED</Badge>;
    case "queued":
      return <Badge className="border-amber-500/50 bg-amber-500/20 text-amber-400">QUEUED</Badge>;
    case "paused":
      return <Badge className="border-amber-500/50 bg-amber-500/20 text-amber-400">PAUSED</Badge>;
    case "cancelled":
      return (
        <Badge className="border-neutral-500/50 bg-neutral-500/20 text-neutral-400">
          CANCELLED
        </Badge>
      );
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

/**
 * Speed / ETA / size line for a transfer, from the stats the backend parses out
 * of rsync's progress output.
 */
function TransferStats({ transfer }: { transfer: Transfer }) {
  const size = formatSizePair(transfer.bytes_transferred, transfer.total_bytes);
  const eta = transfer.status === "running" ? formatEta(transfer.eta_seconds) : null;

  if (!size && transfer.status !== "running") return null;

  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-neutral-400">
      {transfer.status === "running" && (
        <span className="text-brand-foreground">{formatSpeed(transfer.speed_bps)}</span>
      )}
      {eta && <span>ETA {eta}</span>}
      {size && (
        <span>
          {size.value} {size.unit}
        </span>
      )}
    </div>
  );
}

function classifyLogLine(line: string) {
  const lower = line.toLowerCase();
  if (lower.includes("error") || lower.includes("failed")) return "text-red-300";
  if (lower.includes("warning")) return "text-yellow-300";
  if (lower.includes("completed") || lower.includes("success")) return "text-green-300";
  return "text-neutral-300";
}

function formatAgo(time?: string) {
  if (!time) return "Unknown";
  const date = new Date(time);
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function TransfersPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [detailsTransfer, setDetailsTransfer] = useState<Transfer | null>(null);
  const [fullscreenLogs, setFullscreenLogs] = useState(false);
  const [activeLogTab, setActiveLogTab] = useState<string | null>(null);
  const [logTabs, setLogTabs] = useState<Record<string, LogTab>>({});

  const activeQuery = useActiveTransfers();
  const allQuery = useAllTransfers(200);
  const posters = useTransferPosters();

  const cancelMutation = useCancelTransfer();
  const restartMutation = useRestartTransfer();
  const deleteMutation = useDeleteTransfer();
  const cleanupMutation = useCleanupTransfers();
  const pauseMutation = usePauseTransfer();
  const resumeMutation = useResumeTransfer();

  // Destructive actions are confirmed through a dialog rather than
  // window.confirm, so the prompt can name the transfer and explain the effect.
  const [stopTarget, setStopTarget] = useState<Transfer | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Transfer | null>(null);
  const [confirmCleanup, setConfirmCleanup] = useState(false);

  const allTransfers = useMemo(() => {
    const list = allQuery.data?.transfers ?? [];
    if (statusFilter === "all") return list;
    return list.filter((x) => x.status === statusFilter);
  }, [allQuery.data?.transfers, statusFilter]);

  useEffect(() => {
    const unbindProgress = onTransferUpdate((payload) => {
      const nextLogs = payload.logs ?? (payload.log ? [payload.log] : undefined);
      setLogTabs((prev) => {
        const existing = prev[payload.transfer_id];
        if (!existing) return prev;
        return {
          ...prev,
          [payload.transfer_id]: {
            ...existing,
            status: payload.status || existing.status,
            logs: nextLogs ?? existing.logs,
          },
        };
      });
      activeQuery.refetch();
    });
    const unbindComplete = onTransferComplete((payload) => {
      const nextLogs = payload.logs ?? (payload.log ? [payload.log] : undefined);
      setLogTabs((prev) => {
        const existing = prev[payload.transfer_id];
        if (!existing) return prev;
        return {
          ...prev,
          [payload.transfer_id]: {
            ...existing,
            status: payload.status || existing.status,
            logs: nextLogs ?? existing.logs,
          },
        };
      });
      activeQuery.refetch();
      allQuery.refetch();
    });
    const unbindQueued = onTransferQueued(() => {
      activeQuery.refetch();
      allQuery.refetch();
    });
    const unbindPromoted = onTransferPromoted(() => {
      activeQuery.refetch();
      allQuery.refetch();
    });
    return () => {
      unbindProgress();
      unbindComplete();
      unbindQueued();
      unbindPromoted();
    };
  }, [activeQuery, allQuery]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "l") {
        event.preventDefault();
        if (!activeLogTab) return;
        setLogTabs((prev) => {
          const tab = prev[activeLogTab];
          if (!tab) return prev;
          toast.info(`Auto-scroll ${tab.autoScroll ? "disabled" : "enabled"} for current tab`);
          return {
            ...prev,
            [activeLogTab]: { ...tab, autoScroll: !tab.autoScroll },
          };
        });
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (!activeLogTab) return;
        setLogTabs((prev) => {
          const tab = prev[activeLogTab];
          if (!tab) return prev;
          return {
            ...prev,
            [activeLogTab]: { ...tab, logs: [] },
          };
        });
      }
      if (event.key === "Escape") {
        setFullscreenLogs(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeLogTab]);

  const loadLogs = async (transferId: string, fallbackTitle: string) => {
    try {
      const response = await api.get<{
        status: string;
        logs: string[];
        log_count: number;
        transfer_status: string;
      }>(`/transfer/${transferId}/logs`);

      if (response.data.status !== "success") {
        toast.error("Failed to load logs");
        return;
      }

      setLogTabs((prev) => ({
        ...prev,
        [transferId]: {
          transferId,
          title: fallbackTitle,
          status: response.data.transfer_status,
          logs: response.data.logs,
          autoScroll: prev[transferId]?.autoScroll ?? true,
        },
      }));
      setActiveLogTab(transferId);
    } catch {
      toast.error("Failed to load logs");
    }
  };

  const loadDetails = async (transferId: string) => {
    try {
      const response = await api.get<{ status: string; transfer: Transfer }>(
        `/transfer/${transferId}/status`
      );
      if (response.data.status !== "success") {
        toast.error("Failed to load transfer details");
        return;
      }
      setDetailsTransfer(response.data.transfer);
    } catch {
      toast.error("Failed to load transfer details");
    }
  };

  const runCancel = async (transferId: string) => {
    try {
      await cancelMutation.mutateAsync(transferId);
      toast.success("Transfer stopped");
      activeQuery.refetch();
      allQuery.refetch();
    } catch {
      toast.error("Failed to stop transfer");
    }
  };

  const runPause = async (transferId: string) => {
    try {
      await pauseMutation.mutateAsync(transferId);
      toast.success("Transfer paused");
      activeQuery.refetch();
    } catch {
      toast.error("Failed to pause transfer");
    }
  };

  const runResume = async (transferId: string) => {
    try {
      const result = await resumeMutation.mutateAsync(transferId);
      toast.success(result?.message ?? "Transfer resumed");
      activeQuery.refetch();
      allQuery.refetch();
    } catch {
      toast.error("Failed to resume transfer");
    }
  };

  const runRestart = async (transferId: string) => {
    try {
      await restartMutation.mutateAsync(transferId);
      toast.success("Transfer restarted");
      activeQuery.refetch();
      allQuery.refetch();
    } catch {
      toast.error("Failed to restart transfer");
    }
  };

  const runDelete = async (transferId: string) => {
    try {
      await deleteMutation.mutateAsync(transferId);
      toast.success("Transfer deleted");
      setDetailsTransfer(null);
      allQuery.refetch();
      activeQuery.refetch();
      setLogTabs((prev) => {
        const next = { ...prev };
        delete next[transferId];
        return next;
      });
      if (activeLogTab === transferId) setActiveLogTab(null);
    } catch {
      toast.error("Failed to delete transfer");
    }
  };

  const runCleanup = async () => {
    try {
      const result = await cleanupMutation.mutateAsync();
      toast.success(`Cleaned ${result?.cleaned_count ?? 0} duplicate transfer(s)`);
      allQuery.refetch();
      activeQuery.refetch();
    } catch {
      toast.error("Cleanup failed");
    }
  };

  const activeTransfers = activeQuery.data?.transfers ?? [];
  const currentTab = activeLogTab ? logTabs[activeLogTab] : null;

  return (
    <div className="space-y-6">
      <PageHeader title="Transfers" description="Track running, queued, and completed transfers">
        <Button variant="outline" onClick={() => activeQuery.refetch()}>
          <IconRefresh className="mr-2 h-4 w-4" />
          Refresh
        </Button>
        <Button
          variant="outline"
          onClick={() => setConfirmCleanup(true)}
          disabled={cleanupMutation.isPending}
        >
          <IconTrash className="mr-2 h-4 w-4" />
          Cleanup
        </Button>
      </PageHeader>

      <Card className="border-neutral-800 bg-neutral-900/50">
        <CardHeader>
          <CardTitle className="text-white">Queue Status</CardTitle>
          <CardDescription className="text-neutral-400">
            {activeQuery.data?.queue_status.running_count ?? 0}/
            {activeQuery.data?.queue_status.max_concurrent ?? 3} running,{" "}
            {activeQuery.data?.queue_status.queued_count ?? 0} queued
          </CardDescription>
        </CardHeader>
      </Card>

      <Tabs defaultValue="active">
        <TabsList>
          <TabsTrigger value="active">Active ({activeTransfers.length})</TabsTrigger>
          <TabsTrigger value="all">All Transfers ({allQuery.data?.total ?? 0})</TabsTrigger>
          <TabsTrigger value="logs">Logs ({Object.keys(logTabs).length})</TabsTrigger>
        </TabsList>

        <TabsContent value="active" className="mt-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardContent className="pt-6">
              <ScrollArea className="h-[500px] pr-3">
                {activeQuery.isLoading ? (
                  <div className="space-y-3">
                    {[1, 2, 3].map((i) => (
                      <Skeleton key={i} className="h-24 w-full" />
                    ))}
                  </div>
                ) : activeTransfers.length ? (
                  <div className="space-y-3">
                    {activeTransfers.map((transfer) => (
                      <div
                        key={transfer.id}
                        className="rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4"
                      >
                        <div className="flex items-center justify-between gap-4">
                          <WebhookPoster
                            item={{
                              posterUrl: posters.get(transfer.id),
                              mediaType: transfer.media_type,
                              title: transfer.parsed_title || transfer.folder_name,
                            }}
                            className="h-[62px] w-11"
                            iconClassName="size-4"
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="truncate text-sm font-medium text-white">
                                {transfer.parsed_title || transfer.folder_name}
                              </p>
                              {getStatusBadge(transfer.status)}
                            </div>
                            <p className="mt-1 text-xs text-neutral-400">
                              {transfer.media_type}
                              {transfer.season_name ? ` - ${transfer.season_name}` : ""}
                              {" - "}
                              {transfer.progress}
                            </p>
                            <p className="mt-1 text-xs text-neutral-500">
                              Started {formatAgo(transfer.start_time)}
                            </p>
                            <TransferStats transfer={transfer} />
                            {(transfer.status === "running" || transfer.status === "paused") && (
                              <div className="mt-2">
                                <Progress value={transferPercent(transfer)} className="h-1.5" />
                              </div>
                            )}
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => loadDetails(transfer.id)}
                            >
                              <IconEye className="mr-1.5 h-4 w-4" />
                              Details
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                loadLogs(transfer.id, transfer.parsed_title || transfer.folder_name)
                              }
                            >
                              <IconTerminal2 className="mr-1.5 h-4 w-4" />
                              Logs ({transfer.log_count})
                            </Button>
                            {transfer.status === "running" && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => runPause(transfer.id)}
                                disabled={pauseMutation.isPending}
                              >
                                <IconPlayerPause className="mr-1.5 h-4 w-4" />
                                Pause
                              </Button>
                            )}
                            {transfer.status === "paused" && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => runResume(transfer.id)}
                                disabled={resumeMutation.isPending}
                              >
                                <IconPlayerPlay className="mr-1.5 h-4 w-4" />
                                Resume
                              </Button>
                            )}
                            {(transfer.status === "running" || transfer.status === "paused") && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setStopTarget(transfer)}
                                disabled={cancelMutation.isPending}
                              >
                                <IconCircleX className="mr-1.5 h-4 w-4" />
                                Stop
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-16 text-center text-neutral-500">
                    <IconInfoCircle className="mx-auto mb-2 h-10 w-10" />
                    No active transfers
                  </div>
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="all" className="mt-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-white">Transfer History</CardTitle>
                  <CardDescription className="text-neutral-400">
                    Filter and inspect completed, queued, failed, and cancelled transfers
                  </CardDescription>
                </div>
                <Select
                  value={statusFilter}
                  onValueChange={(value) => setStatusFilter(value ?? "all")}
                  items={{
                    all: "All statuses",
                    running: "Running",
                    queued: "Queued",
                    paused: "Paused",
                    completed: "Completed",
                    failed: "Failed",
                    cancelled: "Cancelled",
                  }}
                >
                  <SelectTrigger className="w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All statuses</SelectItem>
                    <SelectItem value="running">Running</SelectItem>
                    <SelectItem value="queued">Queued</SelectItem>
                    <SelectItem value="paused">Paused</SelectItem>
                    <SelectItem value="completed">Completed</SelectItem>
                    <SelectItem value="failed">Failed</SelectItem>
                    <SelectItem value="cancelled">Cancelled</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[500px] pr-3">
                {allQuery.isLoading ? (
                  <div className="space-y-3">
                    {[1, 2, 3, 4].map((i) => (
                      <Skeleton key={i} className="h-24 w-full" />
                    ))}
                  </div>
                ) : allTransfers.length ? (
                  <div className="space-y-3">
                    {allTransfers.map((transfer) => (
                      <div
                        key={transfer.id}
                        className="rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4"
                      >
                        <div className="flex items-center justify-between gap-4">
                          <WebhookPoster
                            item={{
                              posterUrl: posters.get(transfer.id),
                              mediaType: transfer.media_type,
                              title: transfer.parsed_title || transfer.folder_name,
                            }}
                            className="h-[62px] w-11"
                            iconClassName="size-4"
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="truncate text-sm font-medium text-white">
                                {transfer.parsed_title || transfer.folder_name}
                              </p>
                              {getStatusBadge(transfer.status)}
                            </div>
                            <p className="mt-1 text-xs text-neutral-400">
                              {transfer.media_type}
                              {transfer.season_name ? ` - ${transfer.season_name}` : ""}
                              {" - "}
                              {transfer.progress}
                            </p>
                            <p className="mt-1 text-xs text-neutral-500">
                              Started {formatAgo(transfer.start_time)}
                            </p>
                            <TransferStats transfer={transfer} />
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => loadDetails(transfer.id)}
                            >
                              <IconEye className="mr-1.5 h-4 w-4" />
                              Details
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                loadLogs(transfer.id, transfer.parsed_title || transfer.folder_name)
                              }
                            >
                              <IconTerminal2 className="mr-1.5 h-4 w-4" />
                              Logs
                            </Button>
                            {(transfer.status === "failed" || transfer.status === "cancelled") && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => runRestart(transfer.id)}
                                disabled={restartMutation.isPending}
                              >
                                <IconArrowBackUp className="mr-1.5 h-4 w-4" />
                                Restart
                              </Button>
                            )}
                            {transfer.status !== "running" && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setDeleteTarget(transfer)}
                                disabled={deleteMutation.isPending}
                              >
                                <IconTrash className="mr-1.5 h-4 w-4" />
                                Delete
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-16 text-center text-neutral-500">
                    <IconList className="mx-auto mb-2 h-10 w-10" />
                    No transfers found
                  </div>
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="logs" className="mt-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-white">Transfer Logs</CardTitle>
                  <CardDescription className="text-neutral-400">
                    Ctrl/Cmd+L toggles auto-scroll, Ctrl/Cmd+K clears current log tab
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      if (!activeLogTab) return;
                      setLogTabs((prev) => {
                        const tab = prev[activeLogTab];
                        if (!tab) return prev;
                        return {
                          ...prev,
                          [activeLogTab]: { ...tab, autoScroll: !tab.autoScroll },
                        };
                      });
                    }}
                    disabled={!activeLogTab}
                  >
                    Auto-scroll
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      if (!activeLogTab) return;
                      setLogTabs((prev) => {
                        const tab = prev[activeLogTab];
                        if (!tab) return prev;
                        return {
                          ...prev,
                          [activeLogTab]: { ...tab, logs: [] },
                        };
                      });
                    }}
                    disabled={!activeLogTab}
                  >
                    Clear
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setFullscreenLogs(true)}
                    disabled={!currentTab}
                  >
                    <IconArrowsMaximize className="mr-1.5 h-4 w-4" />
                    Fullscreen
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {Object.keys(logTabs).length ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 overflow-x-auto pb-1">
                    {Object.values(logTabs).map((tab) => (
                      <button
                        key={tab.transferId}
                        type="button"
                        onClick={() => setActiveLogTab(tab.transferId)}
                        className={`rounded-md border px-3 py-1.5 text-xs whitespace-nowrap ${
                          activeLogTab === tab.transferId
                            ? "border-brand bg-brand/10 text-brand-foreground"
                            : "border-neutral-700 text-neutral-300 hover:border-neutral-500"
                        }`}
                      >
                        {tab.title} [{tab.status}]
                      </button>
                    ))}
                  </div>
                  <ScrollArea className="h-[460px] rounded-md border border-neutral-800 bg-neutral-950 p-3 font-mono text-xs">
                    {currentTab?.logs.length ? (
                      <div className="space-y-1">
                        {currentTab.logs.map((line, idx) => (
                          <div
                            key={`${idx}-${line.slice(0, 20)}`}
                            className={classifyLogLine(line)}
                          >
                            {line}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-neutral-500">No logs yet for this transfer.</div>
                    )}
                  </ScrollArea>
                </div>
              ) : (
                <div className="py-16 text-center text-neutral-500">
                  <IconTerminal2 className="mx-auto mb-2 h-10 w-10" />
                  Open a transfer log from Active/All tabs
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog
        open={Boolean(detailsTransfer)}
        onOpenChange={(open) => !open && setDetailsTransfer(null)}
      >
        <DialogContent className="border-neutral-800 bg-neutral-900 sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="text-white">Transfer Details</DialogTitle>
            <DialogDescription className="text-neutral-400">
              {detailsTransfer?.parsed_title || detailsTransfer?.folder_name}
            </DialogDescription>
          </DialogHeader>
          {detailsTransfer && (
            <div className="space-y-4 text-sm">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Status</div>
                  <div className="mt-1">{getStatusBadge(detailsTransfer.status)}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Progress</div>
                  <div className="mt-1 text-neutral-200">{detailsTransfer.progress}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Source</div>
                  <div className="mt-1 break-all text-neutral-300">
                    {detailsTransfer.source_path}
                  </div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Destination</div>
                  <div className="mt-1 break-all text-neutral-300">{detailsTransfer.dest_path}</div>
                </div>
              </div>
              <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                <div className="mb-2 text-neutral-500">Actions</div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      loadLogs(
                        detailsTransfer.id,
                        detailsTransfer.parsed_title || detailsTransfer.folder_name
                      )
                    }
                  >
                    <IconTerminal2 className="mr-1.5 h-4 w-4" />
                    View Logs
                  </Button>
                  {detailsTransfer.status === "running" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => runPause(detailsTransfer.id)}
                    >
                      <IconPlayerPause className="mr-1.5 h-4 w-4" />
                      Pause
                    </Button>
                  )}
                  {detailsTransfer.status === "paused" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => runResume(detailsTransfer.id)}
                    >
                      <IconPlayerPlay className="mr-1.5 h-4 w-4" />
                      Resume
                    </Button>
                  )}
                  {(detailsTransfer.status === "running" ||
                    detailsTransfer.status === "paused") && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setStopTarget(detailsTransfer)}
                    >
                      <IconCircleX className="mr-1.5 h-4 w-4" />
                      Stop
                    </Button>
                  )}
                  {(detailsTransfer.status === "failed" ||
                    detailsTransfer.status === "cancelled") && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => runRestart(detailsTransfer.id)}
                    >
                      <IconArrowBackUp className="mr-1.5 h-4 w-4" />
                      Restart
                    </Button>
                  )}
                  {detailsTransfer.status !== "running" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setDeleteTarget(detailsTransfer)}
                    >
                      <IconTrash className="mr-1.5 h-4 w-4" />
                      Delete
                    </Button>
                  )}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

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
        pending={cancelMutation.isPending}
        onConfirm={() => {
          if (stopTarget) runCancel(stopTarget.id);
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
            and its logs are removed from the history. Transferred files are not touched.
            {deleteTarget?.status === "paused" &&
              " This transfer is paused, so deleting it also means it can no longer be resumed."}
          </>
        }
        confirmLabel="Delete record"
        pending={deleteMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) runDelete(deleteTarget.id);
          setDeleteTarget(null);
        }}
      />

      <ConfirmDialog
        open={confirmCleanup}
        onOpenChange={setConfirmCleanup}
        icon={<IconTrash />}
        title="Remove duplicate transfers?"
        description="Where several completed transfers share a destination path, only the most recent one is kept. Transferred files are not touched."
        confirmLabel="Remove duplicates"
        pending={cleanupMutation.isPending}
        onConfirm={runCleanup}
      />

      <Dialog open={fullscreenLogs} onOpenChange={setFullscreenLogs}>
        <DialogContent className="border-neutral-800 bg-neutral-900 sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle className="text-white">Fullscreen Logs</DialogTitle>
            <DialogDescription className="text-neutral-400">
              {currentTab?.title || "No tab selected"}
            </DialogDescription>
          </DialogHeader>
          <ScrollArea className="h-[70vh] rounded-md border border-neutral-800 bg-neutral-950 p-3 font-mono text-xs">
            {currentTab?.logs.length ? (
              <div className="space-y-1">
                {currentTab.logs.map((line, idx) => (
                  <div key={`${idx}-${line.slice(0, 20)}`} className={classifyLogLine(line)}>
                    {line}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-neutral-500">No logs available.</div>
            )}
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  );
}
