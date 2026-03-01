import { Link } from '@tanstack/react-router';
import { toast } from 'sonner';
import { useRuntimeConnection } from '@/hooks/useRuntime';
import { useSSHAutoConnect, useSSHDisconnect, useWebSocketStatus } from '@/hooks/useConfig';
import { useActiveTransfers, useCancelTransfer, useCleanupTransfers, type Transfer } from '@/hooks/useTransfers';
import { useWebhookNotifications, type WebhookNotification, useRenameNotifications } from '@/hooks/useWebhooks';
import { ConnectionStatusBar } from '@/components/dashboard/connection-status-bar';
import { DiskUsageMonitor } from '@/components/dashboard/disk-usage-monitor';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  IconArchive,
  IconBrandNetflix,
  IconDeviceTv,
  IconFlare,
  IconInfoCircle,
  IconList,
  IconMovie,
  IconPlayerStop,
  IconRefresh,
  IconTransfer,
} from '@tabler/icons-react';

function getStatusBadge(status: string) {
  switch (status) {
    case 'completed':
      return <Badge className="bg-green-500/20 text-green-400 border-green-500/50">COMPLETED</Badge>;
    case 'running':
    case 'syncing':
      return <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/50">RUNNING</Badge>;
    case 'queued':
    case 'QUEUED_SLOT':
    case 'QUEUED_PATH':
      return <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/50">QUEUED</Badge>;
    case 'failed':
      return <Badge className="bg-red-500/20 text-red-400 border-red-500/50">FAILED</Badge>;
    case 'MANUAL_SYNC_REQUIRED':
      return <Badge className="bg-orange-500/20 text-orange-400 border-orange-500/50">MANUAL</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function getMediaIcon(mediaType: string) {
  switch (mediaType) {
    case 'movie':
    case 'movies':
      return <IconMovie className="h-4 w-4 text-fuchsia-400" />;
    case 'tvshows':
    case 'series':
      return <IconDeviceTv className="h-4 w-4 text-blue-400" />;
    case 'anime':
      return <IconBrandNetflix className="h-4 w-4 text-green-400" />;
    default:
      return <IconMovie className="h-4 w-4 text-neutral-400" />;
  }
}

function formatTimeAgo(dateString?: string) {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins} min ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

const dashboardPanelClass =
  'overflow-hidden rounded-xl border border-border/70 bg-card/95 ring-1 ring-black/15';

const dashboardPanelHeaderClass =
  'flex items-center justify-between border-b border-border/70 bg-muted/35 px-4 py-3';

export function DashboardPage() {
  const runtime = useRuntimeConnection();
  const wsStatus = useWebSocketStatus();

  const autoConnect = useSSHAutoConnect();
  const disconnect = useSSHDisconnect();
  const cleanupTransfers = useCleanupTransfers();
  const cancelTransfer = useCancelTransfer();

  const { data: activeTransfers, isLoading: transfersLoading, refetch: refetchTransfers } = useActiveTransfers();
  const { data: webhooks, isLoading: webhooksLoading, refetch: refetchWebhooks } = useWebhookNotifications(undefined, 10);
  const { data: renames, refetch: refetchRenames } = useRenameNotifications(10);

  const handleReconnect = async () => {
    try {
      await autoConnect.mutateAsync();
      runtime.reconnectSocket();
      toast.success('Connected to server');
    } catch {
      toast.error('Connection failed');
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnect.mutateAsync();
      toast.success('Disconnected from server');
    } catch {
      toast.error('Failed to disconnect');
    }
  };

  const handleCleanup = async () => {
    try {
      const result = await cleanupTransfers.mutateAsync();
      const cleanedCount = typeof result?.cleaned_count === 'number' ? result.cleaned_count : 0;
      toast.success(`Cleaned ${cleanedCount} duplicate transfer(s)`);
      refetchTransfers();
    } catch {
      toast.error('Cleanup failed');
    }
  };

  const handleCancelTransfer = async (transferId: string) => {
    try {
      await cancelTransfer.mutateAsync(transferId);
      toast.success('Transfer cancelled');
    } catch {
      toast.error('Failed to cancel transfer');
    }
  };

  const statusMessage = (() => {
    if (runtime.connectionState === 'config-changed') return 'Configuration updated - reconnection required';
    if (runtime.connectionState === 'auto-disconnected') return 'Connected to server - background monitoring active';
    if (runtime.connectionState === 'connected') return `Connected to server - session ${runtime.minutesRemaining} min remaining`;
    if (runtime.sshConnected && !runtime.socketConnected) return 'Connected to server - realtime updates unavailable';
    return runtime.socketError ? `WebSocket error: ${runtime.socketError}` : 'Disconnected from server';
  })();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white">Dashboard</h1>
        <p className="text-neutral-400 mt-1">Operational overview and quick actions</p>
      </div>

      <ConnectionStatusBar
        connectionState={runtime.connectionState}
        statusMessage={statusMessage}
        timeRemainingMinutes={runtime.minutesRemaining}
        activeSocketConnections={wsStatus.data?.websocket_status.active_connections}
        onReconnect={handleReconnect}
        onDisconnect={handleDisconnect}
        onExtendSession={runtime.extendSession}
        onRefreshWsStatus={() => {
          wsStatus.refetch();
          refetchTransfers();
          refetchWebhooks();
          refetchRenames();
        }}
        isReconnecting={autoConnect.isPending}
      />

      <DiskUsageMonitor />

      <div className={dashboardPanelClass}>
        <div className={dashboardPanelHeaderClass}>
          <div className="flex items-center gap-3">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-primary/30 bg-primary/15">
              <IconTransfer className="h-4 w-4 text-primary" />
            </span>
            <span className="font-semibold text-foreground">Active Transfers</span>
            <Badge variant="outline" className="text-xs border-border/80 text-muted-foreground">
              {activeTransfers?.queue_status.running_count ?? 0}/{activeTransfers?.queue_status.max_concurrent ?? 3} running
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-foreground" onClick={() => refetchTransfers()}>
              <IconRefresh className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" className="text-xs border-border/80 bg-card hover:bg-muted/60" onClick={handleCleanup} disabled={cleanupTransfers.isPending}>
              Cleanup
            </Button>
            <Link to="/transfers">
              <Button variant="outline" size="sm" className="text-xs border-border/80 bg-card hover:bg-muted/60">
                <IconList className="h-3.5 w-3.5 mr-1" />
                All
              </Button>
            </Link>
            <Link to="/backups">
              <Button variant="outline" size="sm" className="text-xs border-border/80 bg-card hover:bg-muted/60">
                <IconArchive className="h-3.5 w-3.5 mr-1" />
                Backups
              </Button>
            </Link>
          </div>
        </div>
        <div className="p-4">
          {transfersLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))}
            </div>
          ) : activeTransfers?.transfers.length ? (
            <div className="space-y-2">
              {activeTransfers.transfers.slice(0, 5).map((transfer: Transfer) => (
                <div key={transfer.id} className="flex items-center justify-between rounded-lg border border-border/70 bg-background/45 p-3 transition-colors hover:bg-muted/35">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    {getMediaIcon(transfer.media_type)}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium text-foreground truncate">{transfer.parsed_title || transfer.folder_name}</p>
                        {getStatusBadge(transfer.status)}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {transfer.season_name ? `${transfer.season_name} - ` : ''}
                        {transfer.progress || 'Initializing...'}
                        {transfer.start_time ? ` - ${formatTimeAgo(transfer.start_time)}` : ''}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground hover:text-red-400"
                    onClick={() => handleCancelTransfer(transfer.id)}
                    disabled={transfer.status !== 'running' || cancelTransfer.isPending}
                    title="Cancel transfer"
                  >
                    <IconPlayerStop className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground">
              <IconInfoCircle className="h-5 w-5" />
              <span>No active transfers found</span>
            </div>
          )}
        </div>
      </div>

      <div className={dashboardPanelClass}>
        <div className={dashboardPanelHeaderClass}>
          <div className="flex items-center gap-3">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-primary/30 bg-primary/15">
              <IconFlare className="h-4 w-4 text-primary" />
            </span>
            <span className="font-semibold text-foreground">Webhook + Rename Activity</span>
            <Badge variant="outline" className="text-xs border-border/80 text-muted-foreground">
              {(webhooks?.total ?? 0) + (renames?.total ?? 0)} total
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => {
                refetchWebhooks();
                refetchRenames();
              }}
              className="text-muted-foreground hover:text-foreground"
            >
              <IconRefresh className="h-4 w-4" />
            </Button>
            <Link to="/webhooks">
              <Button variant="outline" size="sm" className="text-xs border-border/80 bg-card hover:bg-muted/60">Open</Button>
            </Link>
          </div>
        </div>
        <div className="p-4">
          {webhooksLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 w-full rounded-lg" />
              ))}
            </div>
          ) : webhooks?.notifications.length ? (
            <div className="space-y-2">
              {webhooks.notifications.slice(0, 5).map((item: WebhookNotification) => (
                <div key={item.notification_id} className="flex items-center justify-between rounded-lg border border-border/70 bg-background/45 p-3 transition-colors hover:bg-muted/35">
                  <div className="flex items-center gap-3 min-w-0">
                    {getMediaIcon(item.media_type)}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{item.display_title}</p>
                      <p className="text-xs text-muted-foreground">{formatTimeAgo(item.created_at)}</p>
                    </div>
                  </div>
                  {getStatusBadge(item.status)}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground">
              <IconInfoCircle className="h-5 w-5" />
              <span>No webhook notifications found</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
