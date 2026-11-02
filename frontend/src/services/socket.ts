import { io, Socket } from "socket.io-client";
import { useAuthStore } from "@/stores/auth";
import { useSocketDiagnostics } from "@/stores/socket-diagnostics";

let socket: Socket | null = null;

const SOCKET_OPTIONS = {
  autoConnect: false,
  reconnection: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 15000,
  randomizationFactor: 0.5,
  timeout: 20000,
  transports: ["polling", "websocket"] as string[],
  upgrade: true,
  rememberUpgrade: false,
};

export interface TransferUpdate {
  /** The only field every transfer event carries. */
  transfer_id: string;
  // Optional because `transfer_queued` sends just an id and a message, and
  // `transfer_promoted` little more. Marking these required described the
  // progress events and quietly mis-described the rest, so any code that
  // trusted the type would read undefined at runtime.
  status?: string;
  progress?: string;
  media_type?: string;
  folder_name?: string;
  season_name?: string;
  log?: string;
  /**
   * No longer sent on `transfer_progress` or `transfer_complete` - subscribe
   * with `subscribeTransferLogs` and listen for `transfer_logs` instead.
   */
  logs?: string[];
  log_count?: number;
  message?: string;
  queue_type?: "path" | "slot" | string;
  existing_transfer_id?: string;
  dest_path?: string;
  /** Parsed rsync progress, so the UI can update live without a refetch. */
  stats?: {
    progress_percent?: number | null;
    bytes_transferred?: number | null;
    total_bytes?: number | null;
    speed_bps?: number | null;
    eta_seconds?: number | null;
  };
}

/** Payload of `transfer_logs`, sent only to subscribers of that transfer. */
export interface TransferLogsUpdate {
  transfer_id: string;
  logs: string[];
  log_count: number;
  status: string;
}

export interface WebhookNotification {
  message: string;
  timestamp: string;
}

export interface WebhookCapturedEvent {
  notification_id?: string;
  title?: string;
  media_type?: string;
  auto_sync?: boolean;
  message?: string;
  timestamp?: string;
}

export interface RenameWebhookEvent {
  series_title?: string;
  total_files?: number;
  message?: string;
  status?: string;
  /** 'webhook' for Sonarr's, 'manual' for a rename pressed in Explore. */
  trigger_kind?: string;
  /** Test mode: rehearsed, nothing renamed. */
  dry_run?: boolean;
}

function getSocketUrl(): string {
  return (
    import.meta.env.VITE_WS_URL ||
    (typeof window !== "undefined" ? window.location.origin : "http://localhost:5000")
  );
}

/** A transport name as people read it. */
function transportLabel(name: string | undefined): string {
  if (name === "websocket") return "WebSocket";
  if (name === "polling") return "long-polling";
  return name ?? "an unknown transport";
}

const diagnostics = () => useSocketDiagnostics.getState();

function bindTransportListeners(target: Socket): void {
  const engine = target.io.engine as
    (typeof target.io.engine & { __dragoncpTransportBound?: boolean }) | undefined;
  if (!engine || engine.__dragoncpTransportBound) {
    return;
  }

  engine.__dragoncpTransportBound = true;
  console.log(`🔌 Socket transport active: ${engine.transport?.name ?? "unknown"}`);

  engine.on("upgrade", (transport) => {
    console.log(`🔌 Socket transport upgraded to ${transport?.name ?? "unknown"}`);
    diagnostics().record("upgraded", `Moved to ${transportLabel(transport?.name)}`, {
      transport: transport?.name ?? null,
    });
  });

  engine.on("upgradeError", (error) => {
    console.warn("🔌 Socket transport upgrade failed, continuing with fallback transport:", error);
    diagnostics().record("error", "Could not move to WebSocket, staying on long-polling");
  });
}

/** Socket.IO's disconnect reasons, said plainly. */
function dropReason(reason: string): string {
  switch (reason) {
    case "io client disconnect":
      return "Closed from this browser";
    case "io server disconnect":
      return "Closed by the server";
    case "ping timeout":
      return "Dropped: the server stopped answering heartbeats";
    case "transport close":
      return "Dropped: the connection closed";
    case "transport error":
      return "Dropped: the connection failed";
    case "parse error":
      return "Dropped: the server sent something unreadable";
    default:
      return `Dropped: ${reason}`;
  }
}

function ensureSocket(): Socket {
  if (socket) {
    return socket;
  }

  socket = io(getSocketUrl(), {
    ...SOCKET_OPTIONS,
    auth: { token: useAuthStore.getState().token },
  });

  socket.on("connect", () => {
    bindTransportListeners(socket as Socket);
    const transport = socket?.io.engine?.transport?.name ?? "unknown";
    console.log(`🔌 Socket connected via ${transport}`);
    diagnostics().record("connected", `Connected over ${transportLabel(transport)}`, {
      transport,
      socketId: socket?.id ?? null,
      connectedAt: Date.now(),
    });
    // Rooms live on the server connection, so a reconnect starts with none.
    // Replaying what the UI still wants keeps an open log panel live across a
    // drop without the page having to know a drop happened.
    for (const transferId of watchedTransfers) {
      socket?.emit("transfer_logs_subscribe", { transfer_id: transferId });
    }
  });

  socket.on("disconnect", (reason) => {
    console.log("🔌 Socket disconnected:", reason);
    diagnostics().record("dropped", dropReason(reason), {
      transport: null,
      socketId: null,
      connectedAt: null,
    });
    if (reason === "io server disconnect") {
      socket?.connect();
    }
  });

  socket.on("connect_error", (error) => {
    console.error("🔌 Socket connection error:", error.message);
    diagnostics().record("error", `Could not connect: ${error.message}`);
  });

  socket.io.on("reconnect_attempt", (attempt) => {
    console.log(`🔌 Socket reconnect attempt ${attempt}`);
    diagnostics().record("retrying", `Trying again, attempt ${attempt}`);
  });

  socket.io.on("reconnect", (attempt) => {
    console.log(`🔌 Socket reconnected after ${attempt} attempt(s)`);
    diagnostics().countReconnect();
  });

  socket.io.on("reconnect_failed", () => {
    console.error("🔌 Socket reconnection failed");
  });

  return socket;
}

export function connectSocket(): Socket | null {
  const token = useAuthStore.getState().token;

  if (!token) {
    console.warn("Cannot connect socket: no auth token");
    return null;
  }

  if (socket?.connected) {
    return socket;
  }

  const activeSocket = ensureSocket();
  activeSocket.auth = { token };

  if (!activeSocket.connected && !activeSocket.active) {
    activeSocket.connect();
  }

  return activeSocket;
}

export function disconnectSocket(): void {
  if (socket) {
    socket.disconnect();
  }
}

export function destroySocket(): void {
  if (socket) {
    socket.disconnect();
    socket = null;
  }
}

/**
 * Transfers whose log output this client wants.
 *
 * Held here rather than in the page so it survives a reconnect: the server
 * forgets room membership when a socket drops, and this is what tells it again.
 */
const watchedTransfers = new Set<string>();

/**
 * Start receiving one transfer's rsync output.
 *
 * Log lines are the largest thing the backend pushes and only matter to
 * whoever has that transfer open, so they are not broadcast - a client has to
 * ask. Safe to call when the socket is off; the intent is remembered and sent
 * if realtime is enabled later.
 */
export function subscribeTransferLogs(transferId: string): void {
  if (!transferId || watchedTransfers.has(transferId)) return;
  watchedTransfers.add(transferId);
  socket?.emit("transfer_logs_subscribe", { transfer_id: transferId });
}

/** Stop receiving a transfer's output. */
export function unsubscribeTransferLogs(transferId: string): void {
  if (!transferId || !watchedTransfers.delete(transferId)) return;
  socket?.emit("transfer_logs_unsubscribe", { transfer_id: transferId });
}

/** Log output for a transfer this client subscribed to. */
export function onTransferLogs(callback: (data: TransferLogsUpdate) => void): () => void {
  if (!socket) return () => {};
  socket.on("transfer_logs", callback);
  return () => socket?.off("transfer_logs", callback);
}

export function getSocket(): Socket | null {
  return socket;
}

export function reAuthenticateSocket(): void {
  const token = useAuthStore.getState().token;

  if (socket && token) {
    socket.auth = { token };
    socket.emit("authenticate", { token }, (response?: { success: boolean; message?: string }) => {
      if (response?.success) {
        console.log("🔄 Socket re-authenticated");
      } else {
        const message = response?.message ?? "No response from server";
        console.error("🔒 Socket re-authentication failed:", message);
        socket?.disconnect();
        connectSocket();
      }
    });
  } else if (token) {
    connectSocket();
  }
}

// Typed event listeners
export function onTransferUpdate(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on("transfer_progress", callback);
  return () => socket?.off("transfer_progress", callback);
}

export function onTransferComplete(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on("transfer_complete", callback);
  return () => socket?.off("transfer_complete", callback);
}

// There is no `onTransferError`. The backend emits no `transfer_failed` event:
// a failure arrives as `transfer_complete` carrying `status: "failed"`, which is
// what the pages already listen for. A helper for an event nobody sends reads
// like coverage that does not exist.

export function onTransferQueued(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on("transfer_queued", callback);
  return () => socket?.off("transfer_queued", callback);
}

export function onTransferPromoted(callback: (data: TransferUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on("transfer_promoted", callback);
  return () => socket?.off("transfer_promoted", callback);
}

export function onWebhookReceived(callback: (data: WebhookNotification) => void): () => void {
  if (!socket) return () => {};

  socket.on("test_webhook_received", callback);
  return () => socket?.off("test_webhook_received", callback);
}

export function onWebhookCaptured(callback: (data: WebhookCapturedEvent) => void): () => void {
  if (!socket) return () => {};

  socket.on("webhook_received", callback);
  return () => socket?.off("webhook_received", callback);
}

export function onRenameWebhookReceived(callback: (data: RenameWebhookEvent) => void): () => void {
  if (!socket) return () => {};

  socket.on("rename_webhook_received", callback);
  return () => socket?.off("rename_webhook_received", callback);
}

export function onRenameCompleted(callback: (data: RenameWebhookEvent) => void): () => void {
  if (!socket) return () => {};

  socket.on("rename_completed", callback);
  return () => socket?.off("rename_completed", callback);
}

/** `sync_run_updated`: a run's list row, sent whenever the run changes. */
export interface SyncRunUpdate {
  run_id: string;
  state: string;
  label?: string;
  current_stage?: string | null;
}

/** `sync_run_event`: one new log line on a run. */
export interface SyncRunEventUpdate {
  run_id: string;
  event: { id: number; stage: string; level: string; message: string; created_at: string };
}

/** `alerts_changed`: the open counts behind the Notifications badge. */
export interface AlertsChangedUpdate {
  open: number;
  by_severity: Record<string, number>;
}

export function onSyncRunUpdated(callback: (data: SyncRunUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on("sync_run_updated", callback);
  return () => socket?.off("sync_run_updated", callback);
}

export function onSyncRunEvent(callback: (data: SyncRunEventUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on("sync_run_event", callback);
  return () => socket?.off("sync_run_event", callback);
}

export function onAlertsChanged(callback: (data: AlertsChangedUpdate) => void): () => void {
  if (!socket) return () => {};

  socket.on("alerts_changed", callback);
  return () => socket?.off("alerts_changed", callback);
}

export function sendActivityPing(): void {
  if (socket?.connected) {
    socket.emit("activity");
  }
}

export function isSocketConnected(): boolean {
  return Boolean(socket?.connected);
}
