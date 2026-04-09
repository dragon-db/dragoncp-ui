import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useDeleteRenameNotification,
  useDeleteWebhookNotification,
  useMarkWebhookComplete,
  useRenameNotificationDetails,
  useRenameNotifications,
  useTriggerWebhookSync,
  useVerifyRenameNotification,
  useWebhookDryRun,
  useWebhookNotificationDetails,
  useWebhookNotificationJson,
  useWebhookNotifications,
  type RenameNotification,
  type RenameVerificationResult,
  type WebhookNotification,
} from '@/hooks/useWebhooks';
import { onRenameCompleted, onRenameWebhookReceived, onWebhookCaptured, onWebhookReceived } from '@/services/socket';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  IconCheck,
  IconCode,
  IconEye,
  IconList,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
  IconWebhook,
} from '@tabler/icons-react';

interface GroupedNotification {
  key: string;
  mediaType: string;
  title: string;
  seasonNumber?: number;
  createdAt?: string;
  requestedBy?: string;
  year?: number;
  notifications: WebhookNotification[];
}

type NotificationItem =
  | { type: 'group'; value: GroupedNotification }
  | { type: 'single'; value: WebhookNotification };

const statusOrder: Record<string, number> = {
  syncing: 0,
  failed: 1,
  QUEUED_PATH: 2,
  QUEUED_SLOT: 3,
  READY_FOR_TRANSFER: 4,
  pending: 5,
  MANUAL_SYNC_REQUIRED: 6,
  manual_sync_required: 6,
  completed: 7,
};

function getStatusBadge(status: string) {
  switch (status) {
    case 'pending':
      return <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/50">Pending</Badge>;
    case 'READY_FOR_TRANSFER':
      return <Badge className="bg-blue-500/20 text-blue-300 border-blue-500/50">Ready</Badge>;
    case 'QUEUED_SLOT':
      return <Badge className="bg-yellow-500/20 text-yellow-300 border-yellow-500/50">Queued Slot</Badge>;
    case 'QUEUED_PATH':
      return <Badge className="bg-yellow-500/20 text-yellow-300 border-yellow-500/50">Queued Path</Badge>;
    case 'syncing':
      return <Badge className="bg-cyan-500/20 text-cyan-300 border-cyan-500/50">Syncing</Badge>;
    case 'completed':
      return <Badge className="bg-green-500/20 text-green-300 border-green-500/50">Completed</Badge>;
    case 'failed':
      return <Badge className="bg-red-500/20 text-red-300 border-red-500/50">Failed</Badge>;
    case 'MANUAL_SYNC_REQUIRED':
    case 'manual_sync_required':
      return <Badge className="bg-orange-500/20 text-orange-300 border-orange-500/50">Manual Required</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function getMediaBadge(mediaType: string) {
  switch (mediaType) {
    case 'movie':
      return <Badge className="bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/50">Movie</Badge>;
    case 'tvshows':
    case 'series':
      return <Badge className="bg-blue-500/20 text-blue-300 border-blue-500/50">TV</Badge>;
    case 'anime':
      return <Badge className="bg-green-500/20 text-green-300 border-green-500/50">Anime</Badge>;
    default:
      return <Badge variant="outline">{mediaType}</Badge>;
  }
}

function formatAgo(value?: string) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function toGroupStatus(notifications: WebhookNotification[]) {
  return (
    notifications
      .map((notification) => notification.status)
      .sort((a, b) => (statusOrder[a] ?? 100) - (statusOrder[b] ?? 100))[0] ?? 'pending'
  );
}

function buildItems(notifications: WebhookNotification[]): NotificationItem[] {
  const grouped = new Map<string, GroupedNotification>();
  const singles: NotificationItem[] = [];

  for (const notification of notifications) {
    const mediaType = notification.media_type || 'movie';
    const isSeries = mediaType === 'tvshows' || mediaType === 'series' || mediaType === 'anime';
    if (!isSeries) {
      singles.push({ type: 'single', value: notification });
      continue;
    }

    const slug = notification.series_title_slug || notification.series_title || notification.display_title;
    const season = notification.season_number ?? 0;
    const key = `${slug}_S${season}`;

    if (!grouped.has(key)) {
      grouped.set(key, {
        key,
        mediaType,
        title: notification.series_title || notification.display_title,
        seasonNumber: season,
        createdAt: notification.created_at,
        requestedBy: notification.requested_by,
        year: notification.year,
        notifications: [],
      });
    }

    const group = grouped.get(key)!;
    group.notifications.push(notification);
    if ((notification.created_at ?? '') > (group.createdAt ?? '')) {
      group.createdAt = notification.created_at;
    }
  }

  const groupedItems: NotificationItem[] = Array.from(grouped.values()).map((value) => ({ type: 'group', value }));
  const result = [...groupedItems, ...singles];
  result.sort((a, b) => {
    const aDate = a.type === 'group' ? a.value.createdAt : a.value.created_at;
    const bDate = b.type === 'group' ? b.value.createdAt : b.value.created_at;
    return new Date(bDate ?? 0).getTime() - new Date(aDate ?? 0).getTime();
  });

  return result;
}

function mapMediaType(mediaType: string) {
  if (mediaType === 'series') return 'tvshows';
  return mediaType;
}

function getApiErrorMessage(error: unknown) {
  if (typeof error !== 'object' || error === null) return undefined;

  const maybeError = error as {
    response?: {
      data?: {
        result?: { message?: string }
        message?: string
      }
    }
    result?: { message?: string }
    message?: string
  };

  return (
    maybeError.response?.data?.result?.message ??
    maybeError.response?.data?.message ??
    maybeError.result?.message ??
    maybeError.message
  );
}

export function WebhooksPage() {
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [activeTab, setActiveTab] = useState('notifications');

  const [detailsId, setDetailsId] = useState<string | null>(null);
  const [jsonId, setJsonId] = useState<string | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<GroupedNotification | null>(null);
  const [dryRunPayload, setDryRunPayload] = useState<unknown>(null);

  const [renameDetailsId, setRenameDetailsId] = useState<string | null>(null);
  const [renameVerifyPayload, setRenameVerifyPayload] = useState<RenameVerificationResult | null>(null);
  const [verifyingRenameId, setVerifyingRenameId] = useState<string | null>(null);

  const notificationsQuery = useWebhookNotifications(statusFilter === 'all' ? undefined : statusFilter, 100);
  const renameQuery = useRenameNotifications(100);

  const detailsQuery = useWebhookNotificationDetails(detailsId ?? '');
  const jsonQuery = useWebhookNotificationJson(jsonId ?? '');
  const renameDetailsQuery = useRenameNotificationDetails(renameDetailsId ?? '');

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

  const notifications = notificationsQuery.data?.notifications ?? [];
  const items = useMemo(() => buildItems(notifications), [notifications]);

  const pendingCount = notifications.filter((notification) => notification.status === 'pending').length;
  const syncingCount = notifications.filter((notification) => notification.status === 'syncing').length;
  const queuedCount = notifications.filter(
    (notification) => notification.status === 'QUEUED_SLOT' || notification.status === 'QUEUED_PATH',
  ).length;

  const runSync = async (notification: WebhookNotification) => {
    try {
      await syncMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      toast.success('Sync triggered');
      notificationsQuery.refetch();
    } catch {
      toast.error('Failed to trigger sync');
    }
  };

  const runComplete = async (notification: WebhookNotification) => {
    try {
      await completeMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      toast.success('Marked complete');
      notificationsQuery.refetch();
    } catch {
      toast.error('Failed to mark complete');
    }
  };

  const runDelete = async (notification: WebhookNotification) => {
    if (!window.confirm('Delete this notification?')) return;
    try {
      await deleteMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      toast.success('Notification deleted');
      notificationsQuery.refetch();
    } catch {
      toast.error('Failed to delete notification');
    }
  };

  const runDryRun = async (notification: WebhookNotification) => {
    try {
      const result = await dryRunMutation.mutateAsync({
        notificationId: notification.notification_id,
        mediaType: mapMediaType(notification.media_type),
      });
      setDryRunPayload(result.dry_run_result);
      toast.info('Dry-run completed');
    } catch {
      toast.error('Dry-run failed');
    }
  };

  const syncAllInGroup = async (group: GroupedNotification) => {
    const candidates = group.notifications.filter(
      (notification) =>
        notification.status === 'pending' ||
        notification.status === 'failed' ||
        notification.status === 'MANUAL_SYNC_REQUIRED' ||
        notification.status === 'manual_sync_required',
    );

    if (!candidates.length) {
      toast.info('No syncable notifications in this group');
      return;
    }

    const results = await Promise.allSettled(candidates.map((notification) => runSync(notification)));
    const failures = results.filter((result) => result.status === 'rejected').length;
    if (failures === 0) {
      toast.success(`Sync started for ${candidates.length} item(s)`);
    } else {
      toast.error(`Failed to sync ${failures} item(s)`);
    }
  };

  const deleteRenameNotification = async (notification: RenameNotification) => {
    if (!window.confirm('Delete this rename notification?')) return;

    try {
      await deleteRenameMutation.mutateAsync(notification.notification_id);
      toast.success('Rename notification deleted');
      renameQuery.refetch();
      if (renameDetailsId === notification.notification_id) {
        setRenameDetailsId(null);
      }
    } catch {
      toast.error('Failed to delete rename notification');
    }
  };

  const runVerifyRename = async (notification: RenameNotification) => {
    setVerifyingRenameId(notification.notification_id);
    try {
      const response = await verifyRenameMutation.mutateAsync(notification.notification_id);
      setRenameVerifyPayload(response.result);

      if (response.result.status === 'verified') {
        toast.success(response.result.message);
      } else if (response.result.status === 'partial') {
        toast.warning(response.result.message);
      } else {
        toast.error(response.result.message);
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error) || 'Failed to verify rename');
    } finally {
      setVerifyingRenameId(null);
    }
  };

  const selectedNotification =
    detailsQuery.data?.notification ?? notifications.find((item) => item.notification_id === detailsId) ?? null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-3xl font-bold text-white">Webhooks</h1>
          <p className="text-neutral-400 mt-1">Grouped notifications, queue states, dry-run, details, and rename history</p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            notificationsQuery.refetch();
            renameQuery.refetch();
          }}
          disabled={notificationsQuery.isFetching || renameQuery.isFetching}
        >
          <IconRefresh className={`h-4 w-4 mr-2 ${(notificationsQuery.isFetching || renameQuery.isFetching) ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="bg-neutral-800 border-neutral-700">
          <TabsTrigger value="notifications">Notifications ({notifications.length})</TabsTrigger>
          <TabsTrigger value="rename">Rename History ({renameQuery.data?.total ?? 0})</TabsTrigger>
        </TabsList>

        <TabsContent value="notifications" className="mt-4 space-y-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardContent className="pt-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm text-neutral-300">
                  <span className="mr-4">{pendingCount} pending</span>
                  <span className="mr-4">{syncingCount} syncing</span>
                  <span>{queuedCount} queued</span>
                </div>
                <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value ?? 'all')}>
                  <SelectTrigger className="w-56 bg-neutral-800 border-neutral-700">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-neutral-900 border-neutral-700">
                    <SelectItem value="all">All statuses</SelectItem>
                    <SelectItem value="pending">Pending</SelectItem>
                    <SelectItem value="READY_FOR_TRANSFER">Ready for Transfer</SelectItem>
                    <SelectItem value="QUEUED_SLOT">Queued Slot</SelectItem>
                    <SelectItem value="QUEUED_PATH">Queued Path</SelectItem>
                    <SelectItem value="syncing">Syncing</SelectItem>
                    <SelectItem value="MANUAL_SYNC_REQUIRED">Manual Sync Required</SelectItem>
                    <SelectItem value="completed">Completed</SelectItem>
                    <SelectItem value="failed">Failed</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Webhook Notifications</CardTitle>
              <CardDescription className="text-neutral-400">Series/anime grouped by slug + season for parity with static UI</CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[560px] pr-3">
                {notificationsQuery.isLoading ? (
                  <div className="space-y-3">
                    {[1, 2, 3, 4].map((idx) => (
                      <Skeleton key={idx} className="h-28 w-full" />
                    ))}
                  </div>
                ) : items.length ? (
                  <div className="space-y-3">
                    {items.map((item) => {
                      if (item.type === 'single') {
                        const notification = item.value;
                        return (
                          <div key={notification.notification_id} className="rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4">
                            <div className="flex items-start justify-between gap-4">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2 mb-1">
                                  <p className="text-sm font-medium text-white truncate">{notification.display_title}</p>
                                  {getMediaBadge(notification.media_type)}
                                  {getStatusBadge(notification.status)}
                                </div>
                                <p className="text-xs text-neutral-400">
                                  Requested by {notification.requested_by || 'Unknown'} - {formatAgo(notification.created_at)}
                                </p>
                              </div>
                              <div className="flex flex-wrap items-center gap-2 shrink-0">
                                {(notification.status === 'pending' || notification.status === 'failed') && (
                                  <Button size="sm" variant="outline" onClick={() => runSync(notification)}>
                                    <IconPlayerPlay className="h-4 w-4 mr-1.5" />
                                    {notification.status === 'failed' ? 'Retry' : 'Sync'}
                                  </Button>
                                )}
                                <Button size="sm" variant="outline" onClick={() => setDetailsId(notification.notification_id)}>
                                  <IconEye className="h-4 w-4 mr-1.5" />
                                  Details
                                </Button>
                                {notification.status !== 'syncing' && (
                                  <Button size="sm" variant="outline" onClick={() => runDelete(notification)}>
                                    <IconTrash className="h-4 w-4 mr-1.5" />
                                    Delete
                                  </Button>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      }

                      const group = item.value;
                      const groupStatus = toGroupStatus(group.notifications);
                      const totalSize = group.notifications.reduce((sum, current) => sum + (current.release_size ?? 0), 0);

                      return (
                        <div key={group.key} className="rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4">
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2 mb-1">
                                <p className="text-sm font-medium text-white truncate">{group.title}</p>
                                {getMediaBadge(group.mediaType)}
                                {getStatusBadge(groupStatus)}
                              </div>
                              <p className="text-xs text-neutral-400">
                                Season {group.seasonNumber ?? 0} - {group.notifications.length} episode(s) - {(totalSize / 1024 / 1024 / 1024).toFixed(2)} GB
                              </p>
                              <p className="text-xs text-neutral-500 mt-1">
                                Requested by {group.requestedBy || 'Unknown'} - {formatAgo(group.createdAt)}
                              </p>
                            </div>
                            <div className="flex flex-wrap items-center gap-2 shrink-0">
                              {group.notifications.some((notification) => notification.status === 'pending' || notification.status === 'failed') && (
                                <Button size="sm" variant="outline" onClick={() => syncAllInGroup(group)}>
                                  <IconPlayerPlay className="h-4 w-4 mr-1.5" />
                                  Sync All
                                </Button>
                              )}
                              <Button size="sm" variant="outline" onClick={() => setSelectedGroup(group)}>
                                <IconList className="h-4 w-4 mr-1.5" />
                                Details ({group.notifications.length})
                              </Button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center py-14 text-neutral-500">
                    <IconWebhook className="h-10 w-10 mx-auto mb-2" />
                    No webhook notifications found
                  </div>
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="rename" className="mt-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Rename History</CardTitle>
              <CardDescription className="text-neutral-400">Live updates from rename webhook events</CardDescription>
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
                      <div key={notification.notification_id} className="rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4">
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <p className="text-sm font-medium text-white">{notification.series_title}</p>
                            <p className="text-xs text-neutral-400 mt-1">
                              {notification.success_count}/{notification.total_files} renamed - {notification.media_type}
                            </p>
                            <p className="text-xs text-neutral-500 mt-1">{formatAgo(notification.created_at)}</p>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            {getStatusBadge(notification.status)}
                            <Button size="sm" variant="outline" onClick={() => setRenameDetailsId(notification.notification_id)}>
                              <IconEye className="h-4 w-4 mr-1.5" />
                              Details
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => runVerifyRename(notification)}
                              disabled={verifyingRenameId === notification.notification_id}
                            >
                              <IconCheck className="h-4 w-4 mr-1.5" />
                              {verifyingRenameId === notification.notification_id ? 'Verifying...' : 'Verify Rename'}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => window.open(`/api/webhook/rename/notifications/${notification.notification_id}/json`, '_blank')}
                            >
                              <IconCode className="h-4 w-4 mr-1.5" />
                              JSON
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => deleteRenameNotification(notification)}>
                              <IconTrash className="h-4 w-4 mr-1.5" />
                              Delete
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-14 text-neutral-500">No rename operations yet</div>
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={Boolean(detailsId)} onOpenChange={(open) => !open && setDetailsId(null)}>
        <DialogContent className="max-w-3xl bg-neutral-900 border-neutral-800">
          <DialogHeader>
            <DialogTitle className="text-white">Webhook Details</DialogTitle>
            <DialogDescription className="text-neutral-400">Detailed notification payload and actions</DialogDescription>
          </DialogHeader>
          {selectedNotification ? (
            <div className="space-y-4 text-sm">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Title</div>
                  <div className="text-neutral-200 mt-1">{selectedNotification.display_title}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Status</div>
                  <div className="mt-1">{getStatusBadge(selectedNotification.status)}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Media Type</div>
                  <div className="mt-1">{getMediaBadge(selectedNotification.media_type)}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Created</div>
                  <div className="text-neutral-200 mt-1">{new Date(selectedNotification.created_at).toLocaleString()}</div>
                </div>
              </div>

              <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                <div className="text-neutral-500 mb-2">Actions</div>
                <div className="flex flex-wrap gap-2">
                  {(selectedNotification.status === 'pending' || selectedNotification.status === 'failed') && (
                    <Button size="sm" variant="outline" onClick={() => runSync(selectedNotification)}>
                      <IconPlayerPlay className="h-4 w-4 mr-1.5" />
                      {selectedNotification.status === 'failed' ? 'Retry' : 'Sync'}
                    </Button>
                  )}
                  {selectedNotification.status !== 'completed' && (
                    <Button size="sm" variant="outline" onClick={() => runComplete(selectedNotification)}>
                      <IconCheck className="h-4 w-4 mr-1.5" />
                      Mark Complete
                    </Button>
                  )}
                  <Button size="sm" variant="outline" onClick={() => runDryRun(selectedNotification)}>
                    <IconRefresh className="h-4 w-4 mr-1.5" />
                    Dry-Run
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setJsonId(selectedNotification.notification_id)}>
                    <IconCode className="h-4 w-4 mr-1.5" />
                    JSON
                  </Button>
                  {selectedNotification.status !== 'syncing' && (
                    <Button size="sm" variant="outline" onClick={() => runDelete(selectedNotification)}>
                      <IconTrash className="h-4 w-4 mr-1.5" />
                      Delete
                    </Button>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="text-neutral-500">Loading...</div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(selectedGroup)} onOpenChange={(open) => !open && setSelectedGroup(null)}>
        <DialogContent className="max-w-5xl bg-neutral-900 border-neutral-800">
          <DialogHeader>
            <DialogTitle className="text-white">Grouped Notification Details</DialogTitle>
            <DialogDescription className="text-neutral-400">Series/anime grouped by season</DialogDescription>
          </DialogHeader>
          {selectedGroup && (
            <div className="space-y-4">
              <div className="text-sm text-neutral-300">
                {selectedGroup.title} - Season {selectedGroup.seasonNumber ?? 0} - {selectedGroup.notifications.length} notification(s)
              </div>
              <ScrollArea className="h-[60vh] pr-3">
                <div className="space-y-3">
                  {selectedGroup.notifications.map((notification) => (
                    <div key={notification.notification_id} className="rounded border border-neutral-800 bg-neutral-950 p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm text-neutral-100 truncate">{notification.display_title}</span>
                            {getStatusBadge(notification.status)}
                          </div>
                          <div className="text-xs text-neutral-500 mt-1">{new Date(notification.created_at).toLocaleString()}</div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {(notification.status === 'pending' || notification.status === 'failed') && (
                            <Button size="sm" variant="outline" onClick={() => runSync(notification)}>
                              <IconPlayerPlay className="h-4 w-4 mr-1.5" />
                              {notification.status === 'failed' ? 'Retry' : 'Sync'}
                            </Button>
                          )}
                          <Button size="sm" variant="outline" onClick={() => runDryRun(notification)}>
                            <IconRefresh className="h-4 w-4 mr-1.5" />
                            Dry-Run
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => setJsonId(notification.notification_id)}>
                            <IconCode className="h-4 w-4 mr-1.5" />
                            JSON
                          </Button>
                          {notification.status !== 'completed' && (
                            <Button size="sm" variant="outline" onClick={() => runComplete(notification)}>
                              <IconCheck className="h-4 w-4 mr-1.5" />
                              Complete
                            </Button>
                          )}
                          {notification.status !== 'syncing' && (
                            <Button size="sm" variant="outline" onClick={() => runDelete(notification)}>
                              <IconTrash className="h-4 w-4 mr-1.5" />
                              Delete
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(jsonId)} onOpenChange={(open) => !open && setJsonId(null)}>
        <DialogContent className="max-w-4xl bg-neutral-900 border-neutral-800">
          <DialogHeader>
            <DialogTitle className="text-white">Webhook JSON</DialogTitle>
            <DialogDescription className="text-neutral-400">Raw JSON payload</DialogDescription>
          </DialogHeader>
          <Textarea
            readOnly
            className="min-h-[60vh] bg-neutral-950 border-neutral-800 font-mono text-xs"
            value={jsonQuery.data ? JSON.stringify(jsonQuery.data, null, 2) : 'Loading...'}
          />
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(dryRunPayload)} onOpenChange={(open) => !open && setDryRunPayload(null)}>
        <DialogContent className="max-w-4xl bg-neutral-900 border-neutral-800">
          <DialogHeader>
            <DialogTitle className="text-white">Dry-Run Result</DialogTitle>
            <DialogDescription className="text-neutral-400">Validation output for selected notification</DialogDescription>
          </DialogHeader>
          <Textarea
            readOnly
            className="min-h-[60vh] bg-neutral-950 border-neutral-800 font-mono text-xs"
            value={dryRunPayload ? JSON.stringify(dryRunPayload, null, 2) : 'No dry-run output'}
          />
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(renameDetailsId)} onOpenChange={(open) => !open && setRenameDetailsId(null)}>
        <DialogContent className="max-w-4xl bg-neutral-900 border-neutral-800">
          <DialogHeader>
            <DialogTitle className="text-white">Rename Details</DialogTitle>
            <DialogDescription className="text-neutral-400">Per-file rename results</DialogDescription>
          </DialogHeader>
          {renameDetailsQuery.data?.notification ? (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-4 text-sm">
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Series</div>
                  <div className="text-neutral-200 mt-1">{renameDetailsQuery.data.notification.series_title}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Status</div>
                  <div className="mt-1">{getStatusBadge(renameDetailsQuery.data.notification.status)}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Result</div>
                  <div className="text-neutral-200 mt-1">
                    {renameDetailsQuery.data.notification.success_count}/{renameDetailsQuery.data.notification.total_files} successful
                  </div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Completed</div>
                  <div className="text-neutral-200 mt-1">
                    {renameDetailsQuery.data.notification.completed_at
                      ? new Date(renameDetailsQuery.data.notification.completed_at).toLocaleString()
                      : 'Not completed'}
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => runVerifyRename(renameDetailsQuery.data.notification)}
                  disabled={verifyingRenameId === renameDetailsQuery.data.notification.notification_id}
                >
                  <IconCheck className="h-4 w-4 mr-1.5" />
                  {verifyingRenameId === renameDetailsQuery.data.notification.notification_id ? 'Verifying...' : 'Verify Rename'}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => window.open(`/api/webhook/rename/notifications/${renameDetailsQuery.data.notification.notification_id}/json`, '_blank')}
                >
                  <IconCode className="h-4 w-4 mr-1.5" />
                  JSON
                </Button>
              </div>

              <ScrollArea className="h-[50vh] pr-3">
                <div className="space-y-2">
                  {(renameDetailsQuery.data.notification.renamed_files ?? []).map((file, index) => (
                    <div key={`${index}-${file.previous_name}`} className="rounded border border-neutral-800 bg-neutral-950 p-3 text-xs">
                      <div className="text-neutral-500">Before</div>
                      <div className="text-neutral-200 break-all">{file.previous_name || '-'}</div>
                      <div className="text-neutral-500 mt-2">After</div>
                      <div className="text-neutral-200 break-all">{file.new_name || file.message || file.error || '-'}</div>
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

      <Dialog open={Boolean(renameVerifyPayload)} onOpenChange={(open) => !open && setRenameVerifyPayload(null)}>
        <DialogContent className="max-w-4xl bg-neutral-900 border-neutral-800">
          <DialogHeader>
            <DialogTitle className="text-white">Rename Verification</DialogTitle>
            <DialogDescription className="text-neutral-400">
              On-disk check against the expected TO filenames from the stored Sonarr webhook
            </DialogDescription>
          </DialogHeader>
          <Textarea
            readOnly
            className="min-h-[60vh] bg-neutral-950 border-neutral-800 font-mono text-xs"
            value={renameVerifyPayload ? JSON.stringify(renameVerifyPayload, null, 2) : 'No verification output'}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
