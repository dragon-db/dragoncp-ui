import { create } from "zustand";

/**
 * What this browser's live connection has been doing since the page loaded.
 *
 * Kept in memory only, for the WebSocket diagnostics card: which transport is
 * in use right now, how many times it had to reconnect, and the last few
 * things that happened to it. The console already logs the same events, but
 * nobody has the console open when a connection starts dropping.
 */

export type SocketEventKind = "connected" | "upgraded" | "dropped" | "error" | "retrying";

export interface SocketEvent {
  at: number;
  kind: SocketEventKind;
  text: string;
}

/** Enough to see a pattern, few enough to read at a glance. */
const KEEP = 12;

interface SocketDiagnostics {
  /** "websocket" or "polling" while connected, otherwise null. */
  transport: string | null;
  socketId: string | null;
  connectedAt: number | null;
  /** Times it came back on its own after a drop. */
  reconnects: number;
  /** Newest first. */
  events: SocketEvent[];
  record: (
    kind: SocketEventKind,
    text: string,
    patch?: Partial<Pick<SocketDiagnostics, "transport" | "socketId" | "connectedAt">>
  ) => void;
  countReconnect: () => void;
}

export const useSocketDiagnostics = create<SocketDiagnostics>((set) => ({
  transport: null,
  socketId: null,
  connectedAt: null,
  reconnects: 0,
  events: [],
  record: (kind, text, patch = {}) =>
    set((prev) => ({
      ...patch,
      events: [{ at: Date.now(), kind, text }, ...prev.events].slice(0, KEEP),
    })),
  countReconnect: () => set((prev) => ({ reconnects: prev.reconnects + 1 })),
}));
