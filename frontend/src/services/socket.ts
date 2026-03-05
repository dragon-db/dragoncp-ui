import { io, Socket } from 'socket.io-client';
import { useAuthStore } from '@/stores/auth';

let socket: Socket | null = null;

export interface TransferUpdate {
  transfer_id: string;
  status: string;
  progress: string;
  media_type: string;
  folder_name: string;
  season_name?: string;
  log?: string;
  logs?: string[];
  log_count?: number;
  message?: string;
  queue_type?: 'path' | 'slot' | string;
  existing_transfer_id?: string;
  dest_path?: string;
}

export interface WebhookNotification {
  message: string;
  timestamp: string;
}

export interface RenameWebhookEvent {
  series_title?: string;
  total_files?: number;
  message?: string;
  status?: string;
}

export function connectSocket(): Socket | null {
  const token = useAuthStore.getState().token;
  
  if (!token) {
    console.warn('Cannot connect socket: no auth token');
    return null;
  }
  
  if (socket?.connected) {
    return socket;
  }
  
  const wsUrl =
    import.meta.env.VITE_WS_URL ||
    (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:5000');
  
  socket = io(wsUrl, {
    auth: { token },
    autoConnect: true,
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
  });
  
  socket.on('connect', () => {
    console.log('🔌 Socket connected');
  });
  
  socket.on('disconnect', (reason) => {
    console.log('🔌 Socket disconnected:', reason);
  });
  
  socket.on('connect_error', (error) => {
    console.error('🔌 Socket connection error:', error.message);
  });
  
  return socket;
}

export function disconnectSocket(): void {
  if (socket) {
    socket.disconnect();
    socket = null;
  }
}

export function getSocket(): Socket | null {
  return socket;
}

export function reAuthenticateSocket(): void {
  const token = useAuthStore.getState().token;
  
  if (socket && token) {
    socket.emit('authenticate', { token }, (response: { success: boolean; message?: string }) => {
      if (response.success) {
        console.log('🔄 Socket re-authenticated');
      } else {
        console.error('🔒 Socket re-authentication failed:', response.message);
      }
    });
  }
}

// Typed event listeners
export function onTransferUpdate(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on('transfer_progress', callback);
  return () => socket?.off('transfer_progress', callback);
}

export function onTransferComplete(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};
  
  socket.on('transfer_complete', callback);
  return () => socket?.off('transfer_complete', callback);
}

export function onTransferError(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on('transfer_failed', callback);
  return () => socket?.off('transfer_failed', callback);
}

export function onTransferQueued(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on('transfer_queued', callback);
  return () => socket?.off('transfer_queued', callback);
}

export function onTransferPromoted(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on('transfer_promoted', callback);
  return () => socket?.off('transfer_promoted', callback);
}

export function onWebhookReceived(callback: (data: WebhookNotification) => void): () => void {
  if (!socket) return () => {};
  
  socket.on('test_webhook_received', callback);
  return () => socket?.off('test_webhook_received', callback);
}

export function onRenameWebhookReceived(callback: (data: RenameWebhookEvent) => void): () => void {
  if (!socket) return () => {};

  socket.on('rename_webhook_received', callback);
  return () => socket?.off('rename_webhook_received', callback);
}

export function onRenameCompleted(callback: (data: RenameWebhookEvent) => void): () => void {
  if (!socket) return () => {};

  socket.on('rename_completed', callback);
  return () => socket?.off('rename_completed', callback);
}

export function sendActivityPing(): void {
  if (socket?.connected) {
    socket.emit('activity');
  }
}

export function isSocketConnected(): boolean {
  return Boolean(socket?.connected);
}
