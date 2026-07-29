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
  useBulkDeleteNotifications,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  IconCheck,
  IconCode,
  IconEye,
  IconPencil,
  IconPlayerPlay,
  IconRefresh,
  IconTransfer,
  IconTrash,
  IconUser,
  IconWebhook,
} from "@tabler/icons-react";
import {
  formatSize,
  groupNotifications,
  groupStatus,
  isSyncable,
  distinctEpisodeCount,
  itemDetail,
  mediaLabel,
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
import { AutoSyncControl } from "@/components/webhooks/auto-sync-panel";
import { FilenameDiff } from "@/components/webhooks/filename-diff";
import { RenameVerifyDialog } from "@/components/webhooks/rename-verify-report";
import { episodeTagOf } from "@/lib/rename-diff";
import { DryRunDialog } from "@/components/dry-run/dry-run-report";
import { PageTabsList } from "@/components/layout/page-tabs";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
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

/** Title for dialogs: the series and season, or the movie and its year. */
function notificationLabel(notification: WebhookNotification) {
  const title = notification.series_title || notification.title || "Selected item";
  if (notification.season_number !== undefined && notification.season_number !== null) {
    return `${title} · Season ${String(notification.season_number).padStart(2, "0")}`;
  }
  return notification.year ? `${title} (${notification.year})` : title;
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
  onViewDryRun: (notification: WebhookNotification) => void;
  onJson: (notification: WebhookNotification) => void;
  onDelete: (notification: WebhookNotification) => void;
  /** Selection state, present only where rows can be picked for a bulk action. */
  selection?: {
    selected: boolean;
    onSelectedChange: (selected: boolean) => void;
  };
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
  onViewDryRun,
  onJson,
  onDelete,
  selection,
}: NotificationRowProps) {
  const status = groupStatus(item.notifications);
  const single = item.notifications[0];
  const episodeCount = distinctEpisodeCount(item.notifications);
  const canSync = item.notifications.some(isSyncable) && status !== "syncing";
  const actions = { onSync, onComplete, onDryRun, onViewDryRun, onJson, onDelete };

  // Each fact stays its own element so narrow screens wrap them instead of
  // cutting the line off mid-word.
  const facts = [
    item.requestedBy,
    itemDetail(item),
    formatSize(seasonBytes(item.notifications)),
    timeAgo(item.createdAt),
  ].filter(Boolean) as string[];

  return (
    <AccordionItem value={item.key} className="border-b border-border last:border-b-0">
      <div className="flex flex-col items-stretch sm:flex-row">
        {/* The tick stays beside the row at every width. On phones the outer
            stack turns vertical, which would otherwise strand it on a line of
            its own above the title. */}
        <div className="flex min-w-0 flex-1 items-center">
          {selection && (
            <RowCheckbox
              checked={selection.selected}
              onCheckedChange={selection.onSelectedChange}
              label={`Select ${item.title}`}
            />
          )}
          <AccordionTrigger className="min-w-0 flex-1 items-start gap-3 px-4 py-3 no-underline hover:bg-muted/40 hover:no-underline sm:items-center">
            <span className="flex min-w-0 flex-1 items-start gap-3 sm:items-center sm:gap-4">
              <WebhookPoster
                item={item}
                className="h-[62px] w-[44px] shrink-0"
                iconClassName="size-4"
              />
              <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-semibold break-words text-foreground">
                    {item.title}
                    {item.year ? (
                      <span className="font-normal text-muted-foreground"> ({item.year})</span>
                    ) : null}
                  </span>
                  <MediaBadge mediaType={item.mediaType} />
                  {/* On phones the status reads with the title; on desktop it keeps
                    its column at the end of the row. */}
                  <StatusBadge status={status} className="sm:hidden" />
                </span>
                <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[11px] text-muted-foreground">
                  <IconUser className="size-3 shrink-0 opacity-80" />
                  {facts.map((fact, index) => (
                    // Separator trails its fact so a wrapped line never opens with a dot.
                    <span key={fact} className="flex items-center gap-1.5">
                      {fact}
                      {index < facts.length - 1 && <span className="opacity-50">·</span>}
                    </span>
                  ))}
                </span>
              </span>
              <StatusBadge status={status} className="hidden sm:inline-flex" />
            </span>
          </AccordionTrigger>
        </div>

        {canSync && (
          <div className="flex items-center px-4 pb-3 sm:p-0 sm:pr-4">
            <Button
              size="sm"
              className="w-full border-0 bg-brand-gradient-x text-white sm:w-auto"
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

const NOTIFICATION_PAGE_SIZE = 50;

export function WebhooksPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [notificationSearch, setNotificationSearch] = useState("");
  const [notificationOffset, setNotificationOffset] = useState(0);
  const [notificationLimit, setNotificationLimit] = useState(NOTIFICATION_PAGE_SIZE);
  const [activeTab, setActiveTab] = useState("media-sync");

  // Rows picked for deletion, held by group key. `selectAllMatching` means
  // every arrival the filter finds, which the server re-evaluates at delete
  // time rather than the browser enumerating thousands of ids.
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => new Set());
  const [selectAllMatching, setSelectAllMatching] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);

  const debouncedSearch = useDebouncedValue(notificationSearch, 300);

  const [jsonId, setJsonId] = useState<string | null>(null);
  const [dryRunView, setDryRunView] = useState<{
    payload: unknown;
    label: string;
    performedAt?: string;
  } | null>(null);

  const [renameDetailsId, setRenameDetailsId] = useState<string | null>(null);
  const [renameVerifyPayload, setRenameVerifyPayload] = useState<RenameVerificationResult | null>(
    null
  );
  const [verifyingRenameId, setVerifyingRenameId] = useState<string | null>(null);

  const notificationsQuery = useWebhookNotifications({
    limit: notificationLimit,
    offset: notificationOffset,
    status: statusFilter === "all" ? undefined : statusFilter,
    search: debouncedSearch || undefined,
  });
  const renameQuery = useRenameNotifications(100);

  const jsonQuery = useWebhookNotificationJson(jsonId ?? "");
  const renameDetailsQuery = useRenameNotificationDetails(renameDetailsId ?? "");

  const syncMutation = useTriggerWebhookSync();
  const completeMutation = useMarkWebhookComplete();
  const deleteMutation = useDeleteWebhookNotification();
  const dryRunMutation = useWebhookDryRun();
  const deleteRenameMutation = useDeleteRenameNotification();
  const bulkDeleteMutation = useBulkDeleteNotifications();
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
  // Arrivals are grouped by season for display. A season whose episodes fall
  // either side of a page boundary shows as a group on each page - the page is
  // a window on the arrivals, and grouping is what happens inside it.
  const items = useMemo(() => groupNotifications(notifications), [notifications]);

  const notificationTotal = notificationsQuery.data?.total ?? 0;
  // Memoised so the derived counts are not rebuilt on every render.
  const notificationStatusCounts = useMemo(
    () => notificationsQuery.data?.status_counts ?? {},
    [notificationsQuery.data?.status_counts]
  );

  // Return to the first page whenever the question changes - page 4 of the old
  // results is not page 4 of the new ones.
  useEffect(() => {
    setNotificationOffset(0);
    setSelectedKeys(new Set());
    setSelectAllMatching(false);
  }, [statusFilter, debouncedSearch, notificationLimit]);

  // Manual is not a stored status - it is the `requires_manual_sync` flag on an
  // arrival that is still pending - so it carries its own count rather than one
  // read out of status_counts, where it would never have appeared.
  const manualSyncCount = notificationsQuery.data?.manual_sync_count ?? 0;

  const statusChoices = useMemo(
    () =>
      STATUS_FILTERS.map((filter) => ({
        ...filter,
        count:
          filter.value === "all"
            ? Object.values(notificationStatusCounts).reduce((sum, n) => sum + n, 0)
            : filter.value === "MANUAL_SYNC_REQUIRED"
              ? manualSyncCount
              : (notificationStatusCounts[filter.value] ?? 0),
      })),
    [notificationStatusCounts, manualSyncCount]
  );

  const pageKeys = items.map((item) => item.key);
  const allPageSelected = pageKeys.length > 0 && pageKeys.every((key) => selectedKeys.has(key));

  const toggleSelected = (key: string, selected: boolean) => {
    // Picking rows by hand contradicts "everything matching".
    setSelectAllMatching(false);
    setSelectedKeys((current) => {
      const next = new Set(current);
      if (selected) next.add(key);
      else next.delete(key);
      return next;
    });
  };

  const togglePageSelection = () => {
    setSelectAllMatching(false);
    setSelectedKeys((current) => {
      const next = new Set(current);
      if (allPageSelected) pageKeys.forEach((key) => next.delete(key));
      else pageKeys.forEach((key) => next.add(key));
      return next;
    });
  };

  const clearSelection = () => {
    setSelectedKeys(new Set());
    setSelectAllMatching(false);
  };

  // A picked row is a season, which may stand for several arrivals; deleting it
  // means deleting all of them.
  const selectedNotificationIds = useMemo(
    () =>
      items
        .filter((item) => selectedKeys.has(item.key))
        .flatMap((item) => item.notifications.map((n) => n.notification_id)),
    [items, selectedKeys]
  );

  const selectedCount = selectAllMatching ? notificationTotal : selectedNotificationIds.length;

  const runBulkDelete = async () => {
    try {
      const result = await bulkDeleteMutation.mutateAsync(
        selectAllMatching
          ? {
              all_matching: true,
              status: statusFilter === "all" ? undefined : statusFilter,
              search: debouncedSearch || undefined,
            }
          : { ids: selectedNotificationIds }
      );
      toast.success(result.message);
      clearSelection();
      setNotificationOffset(0);
    } catch (error) {
      toast.error(getApiErrorMessage(error) ?? "Could not delete arrivals");
    } finally {
      setConfirmBulkDelete(false);
    }
  };

  // Counted across everything on record by the server, so the tiles and the
  // filter chips agree - they used to disagree, because the tiles counted
  // groups on the current page while the filters counted arrivals in the table.
  const arrivalTotals = useMemo(() => {
    const completed = notificationStatusCounts.completed ?? 0;
    const failed = notificationStatusCounts.failed ?? 0;
    const inProgress = Object.entries(notificationStatusCounts)
      .filter(([status]) => status !== "completed" && status !== "failed")
      .reduce((sum, [, n]) => sum + n, 0);
    return { completed, inProgress, failed };
  }, [notificationStatusCounts]);

  // Rename runs summarised the same way: files, not webhooks, are what people
  // count when they ask "did the rename land?".
  const renameTotals = useMemo(() => {
    const runs = renameQuery.data?.notifications ?? [];
    let renamed = 0;
    let failed = 0;
    for (const run of runs) {
      renamed += run.success_count ?? 0;
      failed += run.failed_count ?? 0;
    }
    return {
      runs: renameQuery.data?.total ?? runs.length,
      renamed,
      failed,
      lastRun: runs.length ? timeAgo(runs[0].created_at).replace(" ago", "") || "—" : "—",
    };
  }, [renameQuery.data]);

  /**
   * Returns whether the sync started, so a bulk run can count what failed.
   * `silent` suppresses the per-item toast when the caller reports the batch.
   */
  const runSync = async (notification: WebhookNotification, options?: { silent?: boolean }) => {
    try {
      await syncMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      if (!options?.silent) {
        toast.success("Sync started");
        notificationsQuery.refetch();
      }
      return true;
    } catch {
      if (!options?.silent) toast.error("Could not start the sync");
      return false;
    }
  };

  const runComplete = async (notification: WebhookNotification) => {
    try {
      await completeMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      toast.success("Marked as complete");
      notificationsQuery.refetch();
    } catch {
      toast.error("Could not mark it complete");
    }
  };

  const runDelete = async (notification: WebhookNotification) => {
    if (!window.confirm("Delete this sync record?")) return;
    try {
      await deleteMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      toast.success("Sync record deleted");
      notificationsQuery.refetch();
    } catch {
      toast.error("Could not delete the sync record");
    }
  };

  const runDryRun = async (notification: WebhookNotification) => {
    try {
      const result = await dryRunMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      setDryRunView({
        payload: result.dry_run_result,
        label: notificationLabel(notification),
      });
      toast.info("Dry-run finished");
    } catch {
      toast.error("Dry-run could not run");
    }
  };

  const showStoredDryRun = (notification: WebhookNotification) => {
    if (!notification.dry_run_result) return;
    setDryRunView({
      payload: notification.dry_run_result,
      label: notificationLabel(notification),
      performedAt: notification.dry_run_performed_at,
    });
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
      toast.info("Nothing in this group needs a sync");
      return;
    }

    // One message for the batch instead of one per episode.
    const results = await Promise.all(
      candidates.map((notification) => runSync(notification, { silent: true }))
    );
    notificationsQuery.refetch();

    const failures = results.filter((started) => !started).length;
    if (failures === 0) {
      toast.success(`Sync started for ${candidates.length} item(s)`);
    } else if (failures === candidates.length) {
      toast.error(`Could not start any of the ${candidates.length} syncs`);
    } else {
      toast.warning(`Started ${candidates.length - failures}, failed ${failures}`);
    }
  };

  const deleteRenameNotification = async (notification: RenameNotification) => {
    if (!window.confirm("Delete this rename run?")) return;

    try {
      await deleteRenameMutation.mutateAsync(notification.notification_id);
      toast.success("Rename run deleted");
      renameQuery.refetch();
      if (renameDetailsId === notification.notification_id) {
        setRenameDetailsId(null);
      }
    } catch {
      toast.error("Could not delete the rename run");
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
      <PageHeader title="Webhooks" description="Media syncs and renames">
        <AutoSyncControl />
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
        <PageTabsList
          items={[
            {
              value: "media-sync",
              label: "Media sync",
              icon: IconTransfer,
              // Everything on record, not just the page in view.
              count: notificationsQuery.data?.unfiltered_total ?? 0,
            },
            {
              value: "renames",
              label: "Renames",
              icon: IconPencil,
              count: renameQuery.data?.total ?? 0,
            },
          ]}
        />

        <TabsContent value="media-sync" className="mt-4 flex flex-col gap-3.5">
          {/* Counted over grouped items, matching what the list below shows */}
          <StatTiles
            items={[
              {
                label: "Media syncs",
                value: notificationTotal,
                unit: `${items.length} group${items.length === 1 ? "" : "s"} on this page`,
              },
              { label: "Completed", value: arrivalTotals.completed, unit: "synced", tone: "ok" },
              {
                label: "In progress",
                value: arrivalTotals.inProgress,
                unit: "pending",
                tone: "warn",
              },
              {
                label: "Failed",
                value: arrivalTotals.failed,
                unit: "needs retry",
                tone: arrivalTotals.failed ? "crit" : "default",
              },
            ]}
          />

          <SectionCard
            label="Arrivals"
            description="Grouped by season"
            toolbar={
              <>
                <FilterChips
                  choices={statusChoices}
                  value={statusFilter}
                  onChange={setStatusFilter}
                />
                <ListSearch
                  value={notificationSearch}
                  onChange={setNotificationSearch}
                  placeholder="Search title, path or requester"
                  className="ml-auto"
                />
              </>
            }
          >
            {items.length > 0 && (
              <SelectionBar
                selectedCount={selectedCount}
                // Counted in arrivals, not groups, so it can be compared with
                // the total - a group may stand for several arrivals.
                pageCount={notifications.length}
                total={notificationTotal}
                allPageSelected={allPageSelected}
                allMatchingSelected={selectAllMatching}
                onTogglePage={togglePageSelection}
                onSelectAllMatching={() => setSelectAllMatching(true)}
                onClear={clearSelection}
                onDelete={() => setConfirmBulkDelete(true)}
                busy={bulkDeleteMutation.isPending}
                noun="arrivals"
                filterLabel={
                  statusFilter === "all"
                    ? undefined
                    : STATUS_FILTERS.find((f) => f.value === statusFilter)?.label.toLowerCase()
                }
              />
            )}

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
                    onViewDryRun={showStoredDryRun}
                    onJson={(notification) => setJsonId(notification.notification_id)}
                    onDelete={runDelete}
                    selection={{
                      selected: selectAllMatching || selectedKeys.has(item.key),
                      onSelectedChange: (selected) => toggleSelected(item.key, selected),
                    }}
                  />
                ))}
              </Accordion>
            ) : (
              <SectionEmpty
                icon={IconWebhook}
                title={
                  notificationSearch
                    ? `Nothing matches "${notificationSearch}"`
                    : statusFilter === "all"
                      ? "No arrivals yet"
                      : "Nothing matches this filter"
                }
                hint={
                  statusFilter === "all" && !notificationSearch
                    ? "Imports show up here once Radarr or Sonarr points at this app."
                    : undefined
                }
                action={
                  statusFilter !== "all" || notificationSearch ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setStatusFilter("all");
                        setNotificationSearch("");
                      }}
                    >
                      Show all
                    </Button>
                  ) : undefined
                }
              />
            )}

            <ListPagination
              offset={notificationOffset}
              limit={notificationLimit}
              total={notificationTotal}
              count={notifications.length}
              onOffsetChange={setNotificationOffset}
              onLimitChange={setNotificationLimit}
              noun="arrivals"
            />
          </SectionCard>
        </TabsContent>

        <TabsContent value="renames" className="mt-4 flex flex-col gap-3.5">
          <StatTiles
            items={[
              { label: "Renames", value: renameTotals.runs, unit: "webhook runs" },
              {
                label: "Files renamed",
                value: renameTotals.renamed,
                unit: "on this machine",
                tone: "ok",
              },
              {
                label: "Failed files",
                value: renameTotals.failed,
                unit: "not renamed",
                tone: renameTotals.failed > 0 ? "crit" : "default",
              },
              {
                label: "Last run",
                value: renameTotals.lastRun,
                unit: renameTotals.lastRun === "—" ? "" : "ago",
              },
            ]}
          />

          <SectionCard
            label="Rename history"
            description="Replays Sonarr's renames on this machine"
            contentClassName="p-3"
          >
            {renameQuery.isLoading ? (
              <div className="flex flex-col gap-3">
                {[1, 2, 3].map((idx) => (
                  <Skeleton key={idx} className="h-24 w-full rounded-lg" />
                ))}
              </div>
            ) : (renameQuery.data?.notifications.length ?? 0) > 0 ? (
              <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto pr-1">
                {(renameQuery.data?.notifications ?? []).map((notification) => (
                  <div
                    key={notification.notification_id}
                    className="flex flex-col gap-3 rounded-lg border border-border bg-card/60 p-3.5"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex min-w-0 flex-col gap-1">
                        <p className="text-sm font-semibold break-words text-foreground">
                          {notification.series_title}
                        </p>
                        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[11px] text-muted-foreground">
                          <span>
                            {notification.success_count}/{notification.total_files} renamed
                          </span>
                          <span className="opacity-50">·</span>
                          <span>{mediaLabel(notification.media_type)}</span>
                          <span className="opacity-50">·</span>
                          <span>{formatAgo(notification.created_at)}</span>
                        </p>
                      </div>
                      {getStatusBadge(notification.status)}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setRenameDetailsId(notification.notification_id)}
                      >
                        <IconEye className="mr-1.5 size-3.5" />
                        Details
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => runVerifyRename(notification)}
                        disabled={verifyingRenameId === notification.notification_id}
                      >
                        <IconCheck className="mr-1.5 size-3.5" />
                        {verifyingRenameId === notification.notification_id
                          ? "Verifying…"
                          : "Verify rename"}
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
                        <IconCode className="mr-1.5 size-3.5" />
                        View JSON
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="text-muted-foreground hover:text-rose-400"
                        onClick={() => deleteRenameNotification(notification)}
                      >
                        <IconTrash className="mr-1.5 size-3.5" />
                        Delete
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <SectionEmpty
                icon={IconPencil}
                title="No renames yet"
                hint="When Sonarr renames files, the run lands here so you can replay it on this machine."
              />
            )}
          </SectionCard>
        </TabsContent>
      </Tabs>

      <Dialog open={Boolean(jsonId)} onOpenChange={(open) => !open && setJsonId(null)}>
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>Webhook JSON</DialogTitle>
            <DialogDescription>Raw JSON payload</DialogDescription>
          </DialogHeader>
          <Textarea
            readOnly
            className="min-h-[50vh] font-mono text-xs sm:min-h-[60vh]"
            value={jsonQuery.data ? JSON.stringify(jsonQuery.data, null, 2) : "Loading…"}
          />
        </DialogContent>
      </Dialog>

      <DryRunDialog
        payload={dryRunView?.payload}
        performedAt={dryRunView?.performedAt}
        open={Boolean(dryRunView)}
        onOpenChange={(open) => !open && setDryRunView(null)}
        subtitle={dryRunView ? `${dryRunView.label} — what this sync would do` : undefined}
      />

      <Dialog
        open={Boolean(renameDetailsId)}
        onOpenChange={(open) => !open && setRenameDetailsId(null)}
      >
        <DialogContent className="flex max-h-[88vh] flex-col overflow-hidden sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>Rename details</DialogTitle>
            <DialogDescription>Per-file rename results</DialogDescription>
          </DialogHeader>
          {renameDetailsQuery.data?.notification ? (
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
              <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border border-border bg-card/60 px-3 py-2.5">
                  <div className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
                    Series
                  </div>
                  <div className="mt-1 break-words text-foreground">
                    {renameDetailsQuery.data.notification.series_title}
                  </div>
                </div>
                <div className="rounded-lg border border-border bg-card/60 px-3 py-2.5">
                  <div className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
                    Status
                  </div>
                  <div className="mt-1">
                    {getStatusBadge(renameDetailsQuery.data.notification.status)}
                  </div>
                </div>
                <div className="rounded-lg border border-border bg-card/60 px-3 py-2.5">
                  <div className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
                    Result
                  </div>
                  <div className="mt-1 text-foreground">
                    {renameDetailsQuery.data.notification.success_count}/
                    {renameDetailsQuery.data.notification.total_files} successful
                  </div>
                </div>
                <div className="rounded-lg border border-border bg-card/60 px-3 py-2.5">
                  <div className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
                    Completed
                  </div>
                  <div className="mt-1 text-foreground">
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
                  <IconCheck className="mr-1.5 size-3.5" />
                  {verifyingRenameId === renameDetailsQuery.data.notification.notification_id
                    ? "Verifying…"
                    : "Verify rename"}
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
                  <IconCode className="mr-1.5 size-3.5" />
                  View JSON
                </Button>
              </div>

              <div className="flex flex-col gap-2">
                {(renameDetailsQuery.data.notification.renamed_files ?? []).map((file, index) => {
                  const episode = episodeTagOf(file.new_name || file.previous_name);
                  const failed = !file.new_name;
                  return (
                    <div
                      key={`${index}-${file.previous_name}`}
                      className="flex flex-col gap-2 rounded-lg border border-border bg-card/60 p-2.5"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        {episode && (
                          <span className="font-mono text-[11px] font-semibold text-brand-hover">
                            {episode}
                          </span>
                        )}
                        {failed ? (
                          <span className="text-[11px] text-rose-400">
                            {file.message || file.error || "Not renamed"}
                          </span>
                        ) : (
                          <span className="text-[11px] text-muted-foreground">
                            renamed by Sonarr
                          </span>
                        )}
                      </div>
                      <FilenameDiff before={file.previous_name} after={file.new_name} />
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="text-muted-foreground">Loading…</div>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmBulkDelete}
        onOpenChange={setConfirmBulkDelete}
        icon={<IconTrash />}
        title={selectedCount === 1 ? "Delete this arrival?" : `Delete ${selectedCount} arrivals?`}
        description={
          <>
            {selectAllMatching
              ? `Every arrival this filter finds — all ${notificationTotal} of them — is removed, including any on pages you have not opened. `
              : `The selected arrivals are removed from this list. `}
            Media already copied is not touched, and neither are the transfers that copied it.
            Deleting a pending arrival means it can no longer be synced from here.
          </>
        }
        confirmLabel={selectedCount === 1 ? "Delete arrival" : `Delete ${selectedCount} arrivals`}
        pending={bulkDeleteMutation.isPending}
        onConfirm={runBulkDelete}
      />

      <RenameVerifyDialog
        result={renameVerifyPayload}
        open={Boolean(renameVerifyPayload)}
        onOpenChange={(open) => !open && setRenameVerifyPayload(null)}
      />
    </div>
  );
}
