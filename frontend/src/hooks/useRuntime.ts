import { useEffect, useMemo, useRef } from 'react';
import api from '@/lib/api';
import { toast } from 'sonner';
import { useAppConfig, useSSHStatus } from '@/hooks/useConfig';
import { connectSocket, disconnectSocket, getSocket, sendActivityPing } from '@/services/socket';
import { useRuntimeStore } from '@/stores/runtime';

const ACTIVITY_EVENTS: Array<keyof DocumentEventMap> = ['click', 'keydown', 'submit', 'touchstart'];

export function useRuntimeConnection() {
  const {
    connectionState,
    sshConnected,
    socketConnected,
    socketError,
    lastActivityAt,
    timeoutMinutes,
    wasAutoDisconnected,
    setSshConnected,
    setSocketConnected,
    setSocketError,
    markActivity,
    setTimeoutMinutes,
    setAutoDisconnected,
    setConfigChanged,
  } = useRuntimeStore();

  const { data: sshStatus } = useSSHStatus();
  const { data: config } = useAppConfig();
  const warningShownRef = useRef(false);
  const hasCheckedTransferRef = useRef(false);

  useEffect(() => {
    if (typeof sshStatus === 'boolean') {
      setSshConnected(sshStatus);
    }
  }, [setSshConnected, sshStatus]);

  useEffect(() => {
    const timeoutValue = Number(config?.WEBSOCKET_TIMEOUT_MINUTES ?? 30);
    if (!Number.isNaN(timeoutValue)) {
      setTimeoutMinutes(timeoutValue);
    }
  }, [config?.WEBSOCKET_TIMEOUT_MINUTES, setTimeoutMinutes]);

  useEffect(() => {
    const socket = connectSocket();
    if (!socket) return;

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
      if (reason !== 'io client disconnect') {
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
  }, [markActivity, setConfigChanged, setSocketConnected, setSocketError]);

  useEffect(() => {
    if (!socketConnected) return;

    let throttled = false;
    const onActivity = () => {
      if (throttled) return;
      throttled = true;
      markActivity();
      sendActivityPing();
      setTimeout(() => {
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
    const interval = window.setInterval(async () => {
      if (!socketConnected) return;

      const elapsedMs = Date.now() - lastActivityAt;
      const timeoutMs = timeoutMinutes * 60 * 1000;
      const remainingMs = timeoutMs - elapsedMs;

      if (remainingMs <= 2 * 60 * 1000 && remainingMs > 60 * 1000 && !warningShownRef.current) {
        warningShownRef.current = true;
        toast.warning(`Real-time connection will disconnect in ${Math.ceil(remainingMs / 60000)} minute(s) due to inactivity.`);
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
              toast.info('Session timeout prevented because active transfers are running.');
              hasCheckedTransferRef.current = true;
            }
            markActivity();
            return;
          }
        } catch {
          // Fallback: keep default behavior and disconnect socket.
        }

        disconnectSocket();
        setAutoDisconnected(true);
        toast.info('Real-time connection disconnected due to inactivity. Background monitoring remains available.');
      }
    }, 15000);

    return () => window.clearInterval(interval);
  }, [lastActivityAt, markActivity, setAutoDisconnected, socketConnected, timeoutMinutes]);

  const minutesRemaining = useMemo(() => {
    if (!socketConnected) return 0;
    const elapsedMs = Date.now() - lastActivityAt;
    const remainingMs = timeoutMinutes * 60 * 1000 - elapsedMs;
    return Math.max(0, Math.floor(remainingMs / 60000));
  }, [lastActivityAt, socketConnected, timeoutMinutes]);

  const extendSession = () => {
    if (!socketConnected) return;
    warningShownRef.current = false;
    hasCheckedTransferRef.current = false;
    markActivity();
    sendActivityPing();
    toast.success('Session extended successfully.');
  };

  const reconnectSocket = () => {
    const existing = getSocket();
    if (existing?.connected) return;
    setAutoDisconnected(false);
    setConfigChanged(false);
    connectSocket();
  };

  return {
    connectionState,
    sshConnected,
    socketConnected,
    socketError,
    timeoutMinutes,
    minutesRemaining,
    wasAutoDisconnected,
    extendSession,
    reconnectSocket,
  };
}
