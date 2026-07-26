import { PageHeader } from "@/components/layout/page-header";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  useDeleteRenameNotification,
  useDeleteWebhookNotification,
  useMarkWebhookComplete,
  useRenameNotificationDetails,
  useRenameNotifications,
  useTriggerWebhookSync,
  useVerifyRenameNotification,
  useWebhookDryRun,
  useWebhookNotificationJson,
  useWebhookNotifications,
  type RenameNotification,
  type RenameVerificationResult,
  type WebhookNotification,
} from "@/hooks/useWebhooks";
import {
  onRenameCompleted,
  onRenameWebhookReceived,
  onWebhookCaptured,
  onWebhookReceived,
} from "@/services/socket";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  IconCheck,
  IconCode,
  IconEye,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
  IconUser,
  IconWebhook,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import {
  formatSize,
  groupNotifications,
  groupStatus,
  isSyncable,
  distinctEpisodeCount,
  itemDetail,
  seasonBytes,
  timeAgo,
  type WebhookItem,
} from "@/lib/webhook-grouping";
import { EpisodeDetailPanel, EpisodeList } from "@/components/webhooks/episode-details";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { MediaBadge, StatusBadge, WebhookPoster } from "@/components/webhooks/webhook-bits";

// Status / media chips and relative time come from the shared webhook helpers so
// the page, its dialogs and the dashboard rail all present notifications alike.
function getStatusBadge(status: string) {
  return <StatusBadge status={status} />;
}

function formatAgo(value?: string) {
  return timeAgo(value) || "Unknown";
}

function mapMediaType(mediaType: string) {
  if (mediaType === "series") return "tvshows";
  return mediaType;
}

function getApiErrorMessage(error: unknown) {
  if (typeof error !== "object" || error === null) return undefined;

  const maybeError = error as {
    response?: { data?: { result?: { message?: string }; message?: string } };
    result?: { message?: string };
    message?: string;
  };

  return (
    maybeError.response?.data?.result?.message ??
    maybeError.response?.data?.message ??
    maybeError.result?.message ??
    maybeError.message
  );
}

const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "pending", label: "Pending" },
  { value: "syncing", label: "Syncing" },
  { value: "MANUAL_SYNC_REQUIRED", label: "Manual" },
  { value: "failed", label: "Failed" },
] as const;

interface NotificationRowProps {
  item: WebhookItem;
  onSync: (notification: WebhookNotification) => void;
  onSyncAll: (item: WebhookItem) => void;
  onComplete: (notification: WebhookNotification) => void;
  onDryRun: (notification: WebhookNotification) => void;
  onJson: (notification: WebhookNotification) => void;
  onDelete: (notification: WebhookNotification) => void;
}

/**
 * One row per item, expanding in place: a season lists its episodes (each of
 * which opens its own detail), a movie opens its detail directly. Expanding is
 * the only way in — there are no detail dialogs to get lost between.
 */
function NotificationRow({
  item,
  onSync,
  onSyncAll,
  onComplete,
  onDryRun,
  onJson,
  onDelete,
}: NotificationRowProps) {
  const status = groupStatus(item.notifications);
  const single = item.notifications[0];
  const episodeCount = distinctEpisodeCount(item.notifications);
  const canSync = item.notifications.some(isSyncable) && status !== "syncing";
  const actions = { onSync, onComplete, onDryRun, onJson, onDelete };

  const meta = [item.requestedBy, itemDetail(item), formatSize(seasonBytes(item.notifications))]
    .filter(Boolean)
    .join(" · ");

  return (
    <AccordionItem value={item.key} className="border-b border-border last:border-b-0">
      <div className="flex items-stretch">
        <AccordionTrigger className="min-w-0 flex-1 items-center gap-3 px-4 py-3 no-underline hover:bg-muted/40 hover:no-underline">
          <span className="flex min-w-0 flex-1 items-center gap-4">
            <WebhookPoster item={item} className="h-[62px] w-[44px]" iconClassName="size-4" />
            <span className="flex min-w-0 flex-1 flex-col gap-1.5">
              <span className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm font-semibold text-foreground">
                  {item.title}
                  {item.year ? (
                    <span className="font-normal text-muted-foreground"> ({item.year})</span>
                  ) : null}
                </span>
                <MediaBadge mediaType={item.mediaType} />
              </span>
              <span className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
                <IconUser className="size-3 shrink-0 opacity-80" />
                <span className="truncate">{meta}</span>
                <span className="shrink-0 opacity-50">·</span>
                <span className="shrink-0">{timeAgo(item.createdAt)}</span>
              </span>
            </span>
            <StatusBadge status={status} />
          </span>
        </AccordionTrigger>

        {canSync && (
          <div className="flex items-center pr-4">
            <Button
              size="sm"
              className="border-0 bg-brand-gradient-x text-white"
              onClick={() => (item.isGroup ? onSyncAll(item) : onSync(single))}
            >
              <IconPlayerPlay className="mr-1.5 size-3.5" />
              {item.isGroup ? "Sync all" : single.status === "failed" ? "Retry" : "Sync"}
            </Button>
          </div>
        )}
      </div>

      <AccordionContent className="bg-black/20 px-4 pt-1 pb-4">
        {item.isGroup ? (
          <>
            <div className="mb-2 font-mono text-[10.5px] text-muted-foreground">
              {episodeCount} episode{episodeCount === 1 ? "" : "s"} · {item.notifications.length}{" "}
              webhook{item.notifications.length === 1 ? "" : "s"} ·{" "}
              {formatSize(seasonBytes(item.notifications))} on disk
            </div>
            <EpisodeList item={item} actions={actions} />
          </>
        ) : (
          <EpisodeDetailPanel notification={single} actions={actions} />
        )}
      </AccordionContent>
    </AccordionItem>
  );
}

export function WebhooksPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [activeTab, setActiveTab] = useState("notifications");

  const [jsonId, setJsonId] = useState<string | null>(null);
  const [dryRunPayload, setDryRunPayload] = useState<unknown>(null);

  const [renameDetailsId, setRenameDetailsId] = useState<string | null>(null);
  const [renameVerifyPayload, setRenameVerifyPayload] = useState<RenameVerificationResult | null>(
    null
  );
  const [verifyingRenameId, setVerifyingRenameId] = useState<string | null>(null);

  const notificationsQuery = useWebhookNotifications(
    statusFilter === "all" ? undefined : statusFilter,
    100
  );
  const renameQuery = useRenameNotifications(100);

  const jsonQuery = useWebhookNotificationJson(jsonId ?? "");
  const renameDetailsQuery = useRenameNotificationDetails(renameDetailsId ?? "");

  const syncMutation = useTriggerWebhookSync();
  const completeMutation = useMarkWebhookComplete();
  const deleteMutation = useDeleteWebhookNotification();
  const dryRunMutation = useWebhookDryRun();
  const deleteRenameMutation = useDeleteRenameNotification();
  const verifyRenameMutation = useVerifyRenameNotification();

  useEffect(() => {
    const offWebhookCaptured = onWebhookCaptured(() => {
      notificationsQuery.refetch();
    });
    const offRenameReceived = onRenameWebhookReceived(() => {
      renameQuery.refetch();
    });
    const offRenameCompleted = onRenameCompleted(() => {
      renameQuery.refetch();
    });
    const offTestWebhook = onWebhookReceived((payload) => {
      if (payload?.message) {
        notificationsQuery.refetch();
      }
    });

    return () => {
      offWebhookCaptured();
      offRenameReceived();
      offRenameCompleted();
      offTestWebhook();
    };
  }, [notificationsQuery, renameQuery]);

  const notifications = useMemo(
    () => notificationsQuery.data?.notifications ?? [],
    [notificationsQuery.data?.notifications]
  );
  const items = useMemo(() => groupNotifications(notifications), [notifications]);

  // Counted per grouped item so the stats agree with the rows on screen.
  const groupCounts = useMemo(() => {
    let completed = 0;
    let inProgress = 0;
    let failed = 0;
    for (const item of items) {
      const status = groupStatus(item.notifications);
      if (status === "completed") completed += 1;
      else if (status === "failed") failed += 1;
      else inProgress += 1;
    }
    return { completed, inProgress, failed };
  }, [items]);

  const runSync = async (notification: WebhookNotification) => {
    try {
      await syncMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      toast.success("Sync triggered");
      notificationsQuery.refetch();
    } catch {
      toast.error("Failed to trigger sync");
    }
  };

  const runComplete = async (notification: WebhookNotification) => {
    try {
      await completeMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      toast.success("Marked complete");
      notificationsQuery.refetch();
    } catch {
      toast.error("Failed to mark complete");
    }
  };

  const runDelete = async (notification: WebhookNotification) => {
    if (!window.confirm("Delete this notification?")) return;
    try {
      await deleteMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      toast.success("Notification deleted");
      notificationsQuery.refetch();
    } catch {
      toast.error("Failed to delete notification");
    }
  };

  const runDryRun = async (notification: WebhookNotification) => {
    try {
      const result = await dryRunMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      setDryRunPayload(result.dry_run_result);
      toast.info("Dry-run completed");
    } catch {
      toast.error("Dry-run failed");
    }
  };

  const syncAllInGroup = async (group: WebhookItem) => {
    const candidates = group.notifications.filter(
      (notification) =>
        notification.status === "pending" ||
        notification.status === "failed" ||
        notification.status === "MANUAL_SYNC_REQUIRED" ||
        notification.status === "manual_sync_required"
    );

    if (!candidates.length) {
      toast.info("No syncable notifications in this group");
      return;
    }

    const results = await Promise.allSettled(
      candidates.map((notification) => runSync(notification))
    );
    const failures = results.filter((result) => result.status === "rejected").length;
    if (failures === 0) {
      toast.success(`Sync started for ${candidates.length} item(s)`);
    } else {
      toast.error(`Failed to sync ${failures} item(s)`);
    }
  };

  const deleteRenameNotification = async (notification: RenameNotification) => {
    if (!window.confirm("Delete this rename notification?")) return;

    try {
      await deleteRenameMutation.mutateAsync(notification.notification_id);
      toast.success("Rename notification deleted");
      renameQuery.refetch();
      if (renameDetailsId === notification.notification_id) {
        setRenameDetailsId(null);
      }
    } catch {
      toast.error("Failed to delete rename notification");
    }
  };

  const runVerifyRename = async (notification: RenameNotification) => {
    setVerifyingRenameId(notification.notification_id);
    try {
      const response = await verifyRenameMutation.mutateAsync(notification.notification_id);
      setRenameVerifyPayload(response.result);

      if (response.result.status === "verified") {
        toast.success(response.result.message);
      } else if (response.result.status === "partial") {
        toast.warning(response.result.message);
      } else {
        toast.error(response.result.message);
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error) || "Failed to verify rename");
    } finally {
      setVerifyingRenameId(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Webhooks" description="Incoming media notifications and rename history">
        <Button
          variant="outline"
          onClick={() => {
            notificationsQuery.refetch();
            renameQuery.refetch();
          }}
          disabled={notificationsQuery.isFetching || renameQuery.isFetching}
        >
          <IconRefresh
            className={`mr-2 h-4 w-4 ${notificationsQuery.isFetching || renameQuery.isFetching ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </PageHeader>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="notifications">Notifications ({notifications.length})</TabsTrigger>
          <TabsTrigger value="rename">Rename History ({renameQuery.data?.total ?? 0})</TabsTrigger>
        </TabsList>

        <TabsContent value="notifications" className="mt-4 flex flex-col gap-3.5">
          {/* Stats — counted over grouped items, matching what the list shows */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              {
                label: "Notifications",
                value: notifications.length,
                unit: `in ${items.length} group${items.length === 1 ? "" : "s"}`,
                tone: "text-foreground",
              },
              {
                label: "Completed",
                value: groupCounts.completed,
                unit: "synced",
                tone: "text-emerald-400",
              },
              {
                label: "In progress",
                value: groupCounts.inProgress,
                unit: "pending",
                tone: "text-amber-400",
              },
              {
                label: "Failed",
                value: groupCounts.failed,
                unit: "needs retry",
                tone: "text-rose-400",
              },
            ].map((stat) => (
              <div key={stat.label} className="rounded-xl border border-border bg-card px-4 py-3">
                <div className="mb-1.5 font-mono text-[10px] tracking-[0.06em] text-muted-foreground uppercase">
                  {stat.label}
                </div>
                <div className="flex items-baseline gap-1.5">
                  <span className={cn("font-display text-2xl font-semibold", stat.tone)}>
                    {stat.value}
                  </span>
                  <span className="text-[11px] text-muted-foreground">{stat.unit}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-border bg-card px-3 py-2.5">
            {STATUS_FILTERS.map((filter) => (
              <button
                key={filter.value}
                type="button"
                onClick={() => setStatusFilter(filter.value)}
                className={cn(
                  "rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors",
                  statusFilter === filter.value
                    ? "border-brand/35 bg-brand/15 text-brand-foreground"
                    : "border-transparent text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                )}
              >
                {filter.label}
              </button>
            ))}
            <span className="ml-auto font-mono text-[11px] text-muted-foreground">
              series &amp; anime grouped by season
            </span>
          </div>

          {/* Grouped list */}
          <div className="overflow-hidden rounded-xl border border-border bg-card">
            {notificationsQuery.isLoading ? (
              <div className="flex flex-col gap-3 p-4">
                {[1, 2, 3, 4].map((idx) => (
                  <Skeleton key={idx} className="h-20 w-full rounded-lg" />
                ))}
              </div>
            ) : items.length ? (
              <Accordion>
                {items.map((item) => (
                  <NotificationRow
                    key={item.key}
                    item={item}
                    onSync={runSync}
                    onSyncAll={syncAllInGroup}
                    onComplete={runComplete}
                    onDryRun={runDryRun}
                    onJson={(notification) => setJsonId(notification.notification_id)}
                    onDelete={runDelete}
                  />
                ))}
              </Accordion>
            ) : (
              <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
                <IconWebhook className="size-9" />
                <span className="text-sm">No webhook notifications found</span>
              </div>
            )}
          </div>
        </TabsContent>

        <TabsContent value="rename" className="mt-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Rename History</CardTitle>
              <CardDescription className="text-neutral-400">
                Live updates from rename webhook events
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[560px] pr-3">
                {renameQuery.isLoading ? (
                  <div className="space-y-3">
                    {[1, 2, 3].map((idx) => (
                      <Skeleton key={idx} className="h-24 w-full" />
                    ))}
                  </div>
                ) : (renameQuery.data?.notifications.length ?? 0) > 0 ? (
                  <div className="space-y-3">
                    {(renameQuery.data?.notifications ?? []).map((notification) => (
                      <div
                        key={notification.notification_id}
                        className="rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <p className="text-sm font-medium text-white">
                              {notification.series_title}
                            </p>
                            <p className="mt-1 text-xs text-neutral-400">
                              {notification.success_count}/{notification.total_files} renamed -{" "}
                              {notification.media_type}
                            </p>
                            <p className="mt-1 text-xs text-neutral-500">
                              {formatAgo(notification.created_at)}
                            </p>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            {getStatusBadge(notification.status)}
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setRenameDetailsId(notification.notification_id)}
                            >
                              <IconEye className="mr-1.5 h-4 w-4" />
                              Details
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => runVerifyRename(notification)}
                              disabled={verifyingRenameId === notification.notification_id}
                            >
                              <IconCheck className="mr-1.5 h-4 w-4" />
                              {verifyingRenameId === notification.notification_id
                                ? "Verifying..."
                                : "Verify Rename"}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                window.open(
                                  `/api/webhook/rename/notifications/${notification.notification_id}/json`,
                                  "_blank"
                                )
                              }
                            >
                              <IconCode className="mr-1.5 h-4 w-4" />
                              JSON
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => deleteRenameNotification(notification)}
                            >
                              <IconTrash className="mr-1.5 h-4 w-4" />
                              Delete
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-14 text-center text-neutral-500">No rename operations yet</div>
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={Boolean(jsonId)} onOpenChange={(open) => !open && setJsonId(null)}>
        <DialogContent className="border-neutral-800 bg-neutral-900 sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="text-white">Webhook JSON</DialogTitle>
            <DialogDescription className="text-neutral-400">Raw JSON payload</DialogDescription>
          </DialogHeader>
          <Textarea
            readOnly
            className="min-h-[60vh] border-neutral-800 bg-neutral-950 font-mono text-xs"
            value={jsonQuery.data ? JSON.stringify(jsonQuery.data, null, 2) : "Loading..."}
          />
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(dryRunPayload)}
        onOpenChange={(open) => !open && setDryRunPayload(null)}
      >
        <DialogContent className="border-neutral-800 bg-neutral-900 sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="text-white">Dry-Run Result</DialogTitle>
            <DialogDescription className="text-neutral-400">
              Validation output for selected notification
            </DialogDescription>
          </DialogHeader>
          <Textarea
            readOnly
            className="min-h-[60vh] border-neutral-800 bg-neutral-950 font-mono text-xs"
            value={dryRunPayload ? JSON.stringify(dryRunPayload, null, 2) : "No dry-run output"}
          />
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(renameDetailsId)}
        onOpenChange={(open) => !open && setRenameDetailsId(null)}
      >
        <DialogContent className="border-neutral-800 bg-neutral-900 sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="text-white">Rename Details</DialogTitle>
            <DialogDescription className="text-neutral-400">
              Per-file rename results
            </DialogDescription>
          </DialogHeader>
          {renameDetailsQuery.data?.notification ? (
            <div className="space-y-4">
              <div className="grid gap-3 text-sm md:grid-cols-4">
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Series</div>
                  <div className="mt-1 text-neutral-200">
                    {renameDetailsQuery.data.notification.series_title}
                  </div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Status</div>
                  <div className="mt-1">
                    {getStatusBadge(renameDetailsQuery.data.notification.status)}
                  </div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Result</div>
                  <div className="mt-1 text-neutral-200">
                    {renameDetailsQuery.data.notification.success_count}/
                    {renameDetailsQuery.data.notification.total_files} successful
                  </div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Completed</div>
                  <div className="mt-1 text-neutral-200">
                    {renameDetailsQuery.data.notification.completed_at
                      ? new Date(renameDetailsQuery.data.notification.completed_at).toLocaleString()
                      : "Not completed"}
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => runVerifyRename(renameDetailsQuery.data.notification)}
                  disabled={
                    verifyingRenameId === renameDetailsQuery.data.notification.notification_id
                  }
                >
                  <IconCheck className="mr-1.5 h-4 w-4" />
                  {verifyingRenameId === renameDetailsQuery.data.notification.notification_id
                    ? "Verifying..."
                    : "Verify Rename"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    window.open(
                      `/api/webhook/rename/notifications/${renameDetailsQuery.data.notification.notification_id}/json`,
                      "_blank"
                    )
                  }
                >
                  <IconCode className="mr-1.5 h-4 w-4" />
                  JSON
                </Button>
              </div>

              <ScrollArea className="h-[50vh] pr-3">
                <div className="space-y-2">
                  {(renameDetailsQuery.data.notification.renamed_files ?? []).map((file, index) => (
                    <div
                      key={`${index}-${file.previous_name}`}
                      className="rounded border border-neutral-800 bg-neutral-950 p-3 text-xs"
                    >
                      <div className="text-neutral-500">Before</div>
                      <div className="break-all text-neutral-200">{file.previous_name || "-"}</div>
                      <div className="mt-2 text-neutral-500">After</div>
                      <div className="break-all text-neutral-200">
                        {file.new_name || file.message || file.error || "-"}
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          ) : (
            <div className="text-neutral-500">Loading...</div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(renameVerifyPayload)}
        onOpenChange={(open) => !open && setRenameVerifyPayload(null)}
      >
        <DialogContent className="border-neutral-800 bg-neutral-900 sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="text-white">Rename Verification</DialogTitle>
            <DialogDescription className="text-neutral-400">
              On-disk check against the expected TO filenames from the stored Sonarr webhook
            </DialogDescription>
          </DialogHeader>
          <Textarea
            readOnly
            className="min-h-[60vh] border-neutral-800 bg-neutral-950 font-mono text-xs"
            value={
              renameVerifyPayload
                ? JSON.stringify(renameVerifyPayload, null, 2)
                : "No verification output"
            }
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
