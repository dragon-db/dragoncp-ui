import { useEffect, useMemo, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import { toast } from 'sonner';
import { useAppConfig, useRuntimeStatus } from '@/hooks/useConfig';
import {
  connectSocket,
  disconnectSocket,
  getSocket,
  onRenameCompleted,
  onRenameWebhookReceived,
  onTransferComplete,
  onTransferPromoted,
  onTransferQueued,
  onTransferUpdate,
  onWebhookCaptured,
  onWebhookReceived,
  sendActivityPing,
  type TransferUpdate,
  type WebhookCapturedEvent,
} from '@/services/socket';
import { useRuntimeStore } from '@/stores/runtime';

const ACTIVITY_EVENTS: Array<keyof DocumentEventMap> = ['click', 'keydown', 'submit', 'touchstart'];

function buildRealtimeStatusMessage(payload: TransferUpdate): string {
  if (payload.message) return payload.message;
  if (payload.progress) return payload.progress;
  return `Transfer update for ${payload.transfer_id}`;
}

function buildWebhookToastMessage(payload: WebhookCapturedEvent): string {
  if (payload.message) return payload.message;
  if (payload.title) return `Webhook captured for ${payload.title}`;
  return 'Webhook captured';
}

export function useRuntimeController() {
  const {
    backendReachable,
    backendError,
    sshConnected,
    realtimeRequested,
    socketConnected,
    socketError,
    connectionState,
    lastActivityAt,
    timeoutMinutes,
    wasAutoDisconnected,
    configChanged,
    liveActivityMessage,
    liveActivityType,
    liveActivityAt,
    setAutoDisconnected,
    setConfigChanged,
    setRealtimeRequested,
    setSocketConnected,
    setSocketError,
    markActivity,
    clearLiveActivity,
  } = useRuntimeStore();

  const minutesRemaining = useMemo(() => {
    if (!socketConnected) return 0;
    const elapsedMs = Date.now() - lastActivityAt;
    const remainingMs = timeoutMinutes * 60 * 1000 - elapsedMs;
    return Math.max(0, Math.floor(remainingMs / 60000));
  }, [lastActivityAt, socketConnected, timeoutMinutes]);

  const enableRealtime = () => {
    if (socketConnected) return;
    setAutoDisconnected(false);
    setConfigChanged(false);
    setSocketError(null);
    setRealtimeRequested(true);
    connectSocket();
    toast.success('Realtime updates enabled.');
  };

  const disableRealtime = () => {
    setAutoDisconnected(false);
    setConfigChanged(false);
    setSocketError(null);
    setRealtimeRequested(false);
    setSocketConnected(false);
    disconnectSocket();
    clearLiveActivity();
    toast.info('Realtime updates disabled.');
  };

  const reconnectRealtime = () => {
    setAutoDisconnected(false);
    setConfigChanged(false);
    setSocketError(null);
    setRealtimeRequested(true);
    connectSocket();
  };

  const extendSession = () => {
    if (!socketConnected) return;
    markActivity();
    sendActivityPing();
    toast.success('Realtime session extended.');
  };

  return {
    backendReachable,
    backendError,
    sshConnected,
    realtimeRequested,
    socketConnected,
    socketError,
    connectionState,
    timeoutMinutes,
    minutesRemaining,
    wasAutoDisconnected,
    configChanged,
    liveActivityMessage,
    liveActivityType,
    liveActivityAt,
    enableRealtime,
    disableRealtime,
    reconnectRealtime,
    extendSession,
  };
}

export function useRuntimeConnection() {
  const queryClient = useQueryClient();
  const { data: runtimeStatus, error: runtimeStatusError, isError: runtimeStatusIsError } = useRuntimeStatus();
  const { data: config } = useAppConfig();
  const {
    realtimeRequested,
    socketConnected,
    lastActivityAt,
    timeoutMinutes,
    setBackendReachable,
    setSshConnected,
    setSocketConnected,
    setSocketError,
    markActivity,
    setTimeoutMinutes,
    setAutoDisconnected,
    setConfigChanged,
    setLiveActivity,
  } = useRuntimeStore();
  const warningShownRef = useRef(false);
  const hasCheckedTransferRef = useRef(false);
  const lastTransferActivityRef = useRef(0);

  useEffect(() => {
    if (runtimeStatus?.runtime_status) {
      setBackendReachable(true, null);
      setSshConnected(runtimeStatus.runtime_status.ssh_connected);
    }
  }, [runtimeStatus, setBackendReachable, setSshConnected]);

  useEffect(() => {
    if (!runtimeStatusIsError) return;
    const message = runtimeStatusError instanceof Error ? runtimeStatusError.message : 'Backend unavailable';
    setBackendReachable(false, message);
  }, [runtimeStatusError, runtimeStatusIsError, setBackendReachable]);

  useEffect(() => {
    const timeoutValue = Number(config?.WEBSOCKET_TIMEOUT_MINUTES ?? 30);
    if (!Number.isNaN(timeoutValue)) {
      setTimeoutMinutes(timeoutValue);
    }
  }, [config?.WEBSOCKET_TIMEOUT_MINUTES, setTimeoutMinutes]);

  useEffect(() => {
    if (!realtimeRequested) {
      return;
    }

    const socket = connectSocket();
    if (!socket) {
      setSocketError('No auth token available for realtime session');
      return;
    }

    const onConnect = () => {
      setSocketConnected(true);
      setSocketError(null);
      setConfigChanged(false);
      warningShownRef.current = false;
      hasCheckedTransferRef.current = false;
      markActivity();
    };

    const onDisconnect = (reason: string) => {
      setSocketConnected(false);
      if (reason !== 'io client disconnect' && realtimeRequested) {
        setSocketError(reason);
      }
    };

    const onConnectError = (error: Error) => {
      setSocketError(error.message);
    };

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('connect_error', onConnectError);

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('connect_error', onConnectError);
    };
  }, [markActivity, realtimeRequested, setConfigChanged, setSocketConnected, setSocketError]);

  useEffect(() => {
    if (!socketConnected) return;

    let throttled = false;
    const onActivity = () => {
      if (throttled) return;
      throttled = true;
      markActivity();
      sendActivityPing();
      window.setTimeout(() => {
        throttled = false;
      }, 1500);
    };

    ACTIVITY_EVENTS.forEach((eventName) => {
      document.addEventListener(eventName, onActivity);
    });

    return () => {
      ACTIVITY_EVENTS.forEach((eventName) => {
        document.removeEventListener(eventName, onActivity);
      });
    };
  }, [markActivity, socketConnected]);

  useEffect(() => {
    if (!realtimeRequested) return;

    const socket = getSocket() ?? connectSocket();
    if (!socket) return;

    const unbindWebhookCaptured = onWebhookCaptured((payload) => {
      const message = buildWebhookToastMessage(payload);
      setLiveActivity('webhook', message);
      toast.info(message);
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
    });

    const unbindTestWebhook = onWebhookReceived((payload) => {
      const message = payload?.message || 'Webhook connectivity verified';
      setLiveActivity('webhook', message);
      toast.info(message);
    });

    const unbindRenameReceived = onRenameWebhookReceived((payload) => {
      const message = payload.series_title
        ? `Rename webhook captured for ${payload.series_title}`
        : 'Rename webhook captured';
      setLiveActivity('rename', message);
      toast.info(message);
      queryClient.invalidateQueries({ queryKey: ['webhooks', 'rename'] });
    });

    const unbindRenameCompleted = onRenameCompleted((payload) => {
      const message = payload.message || 'Rename flow completed';
      setLiveActivity('rename', message);
      toast.success(message);
      queryClient.invalidateQueries({ queryKey: ['webhooks', 'rename'] });
    });

    const unbindTransferUpdate = onTransferUpdate((payload) => {
      const now = Date.now();
      if (now - lastTransferActivityRef.current < 2000) return;
      lastTransferActivityRef.current = now;
      setLiveActivity('transfer', buildRealtimeStatusMessage(payload));
    });

    const unbindTransferQueued = onTransferQueued((payload) => {
      const message = buildRealtimeStatusMessage(payload);
      setLiveActivity('transfer', message);
      toast.info(message);
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
    });

    const unbindTransferPromoted = onTransferPromoted((payload) => {
      const message = buildRealtimeStatusMessage(payload);
      setLiveActivity('transfer', message);
      toast.success(message);
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
    });

    const unbindTransferComplete = onTransferComplete((payload) => {
      const message = buildRealtimeStatusMessage(payload);
      setLiveActivity('transfer', message);
      if (payload.status === 'failed') {
        toast.error(message);
      } else {
        toast.success(message);
      }
      queryClient.invalidateQueries({ queryKey: ['transfers'] });
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
    });

    return () => {
      unbindWebhookCaptured();
      unbindTestWebhook();
      unbindRenameReceived();
      unbindRenameCompleted();
      unbindTransferUpdate();
      unbindTransferQueued();
      unbindTransferPromoted();
      unbindTransferComplete();
    };
  }, [queryClient, realtimeRequested, setLiveActivity]);

  useEffect(() => {
    const interval = window.setInterval(async () => {
      if (!socketConnected) return;

      const elapsedMs = Date.now() - lastActivityAt;
      const timeoutMs = timeoutMinutes * 60 * 1000;
      const remainingMs = timeoutMs - elapsedMs;

      if (remainingMs <= 2 * 60 * 1000 && remainingMs > 60 * 1000 && !warningShownRef.current) {
        warningShownRef.current = true;
        toast.warning(`Realtime connection will disconnect in ${Math.ceil(remainingMs / 60000)} minute(s) due to inactivity.`);
      }

      if (remainingMs <= 0) {
        try {
          const response = await api.get<{
            status: string;
            transfers: unknown[];
          }>('/transfers/active');
          const hasActiveTransfers = Array.isArray(response.data.transfers) && response.data.transfers.length > 0;
          if (hasActiveTransfers) {
            if (!hasCheckedTransferRef.current) {
              toast.info('Realtime session timeout prevented because active transfers are running.');
              hasCheckedTransferRef.current = true;
            }
            markActivity();
            return;
          }
        } catch {
          // Keep default behavior and disconnect realtime.
        }

        disconnectSocket();
        setAutoDisconnected(true);
        toast.info('Realtime connection disconnected due to inactivity. Dashboard polling remains active.');
      }
    }, 15000);

    return () => window.clearInterval(interval);
  }, [lastActivityAt, markActivity, setAutoDisconnected, socketConnected, timeoutMinutes]);
}
