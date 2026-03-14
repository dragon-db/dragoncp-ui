import { create } from 'zustand';

export type ConnectionState = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'auto-disconnected' | 'config-changed';
export type LiveActivityType = 'transfer' | 'webhook' | 'rename' | 'info' | null;

interface RuntimeState {
  backendReachable: boolean;
  backendError: string | null;
  sshConnected: boolean;
  realtimeRequested: boolean;
  socketConnected: boolean;
  socketError: string | null;
  connectionState: ConnectionState;
  lastActivityAt: number;
  timeoutMinutes: number;
  wasAutoDisconnected: boolean;
  configChanged: boolean;
  liveActivityMessage: string | null;
  liveActivityType: LiveActivityType;
  liveActivityAt: number | null;
  setBackendReachable: (value: boolean, error?: string | null) => void;
  setSshConnected: (value: boolean) => void;
  setRealtimeRequested: (value: boolean) => void;
  setSocketConnected: (value: boolean) => void;
  setSocketError: (error: string | null) => void;
  markActivity: () => void;
  setTimeoutMinutes: (minutes: number) => void;
  setAutoDisconnected: (value: boolean) => void;
  setConfigChanged: (value: boolean) => void;
  setLiveActivity: (type: Exclude<LiveActivityType, null>, message: string) => void;
  clearLiveActivity: () => void;
  resetRuntime: () => void;
}

function deriveState(
  state: Pick<RuntimeState, 'realtimeRequested' | 'socketConnected' | 'wasAutoDisconnected' | 'configChanged' | 'socketError'>,
): ConnectionState {
  if (state.socketConnected && state.configChanged) return 'config-changed';
  if (state.socketConnected) return 'connected';
  if (state.wasAutoDisconnected) return 'auto-disconnected';
  if (!state.realtimeRequested) return 'idle';
  if (state.configChanged) return 'config-changed';
  if (state.socketError) return 'disconnected';
  return 'connecting';
}

export const useRuntimeStore = create<RuntimeState>((set, get) => ({
  backendReachable: true,
  backendError: null,
  sshConnected: false,
  realtimeRequested: false,
  socketConnected: false,
  socketError: null,
  connectionState: 'idle',
  lastActivityAt: Date.now(),
  timeoutMinutes: 30,
  wasAutoDisconnected: false,
  configChanged: false,
  liveActivityMessage: null,
  liveActivityType: null,
  liveActivityAt: null,
  setBackendReachable: (value, error = null) =>
    set({
      backendReachable: value,
      backendError: value ? null : error,
    }),
  setSshConnected: (value) => set({ sshConnected: value }),
  setRealtimeRequested: (value) =>
    set((prev) => ({
      realtimeRequested: value,
      wasAutoDisconnected: value ? false : prev.wasAutoDisconnected,
      connectionState: deriveState({
        ...prev,
        realtimeRequested: value,
        wasAutoDisconnected: value ? false : prev.wasAutoDisconnected,
      }),
    })),
  setSocketConnected: (value) =>
    set((prev) => ({
      socketConnected: value,
      wasAutoDisconnected: value ? false : prev.wasAutoDisconnected,
      socketError: value ? null : prev.socketError,
      connectionState: deriveState({
        ...prev,
        socketConnected: value,
        wasAutoDisconnected: value ? false : prev.wasAutoDisconnected,
      }),
    })),
  setSocketError: (error) =>
    set((prev) => ({
      socketError: error,
      connectionState: deriveState({ ...prev, socketError: error }),
    })),
  markActivity: () => set({ lastActivityAt: Date.now() }),
  setTimeoutMinutes: (minutes) => set({ timeoutMinutes: Math.max(5, Math.min(60, minutes)) }),
  setAutoDisconnected: (value) =>
    set((prev) => ({
      wasAutoDisconnected: value,
      realtimeRequested: value ? false : prev.realtimeRequested,
      socketConnected: value ? false : prev.socketConnected,
      connectionState: deriveState({
        ...prev,
        wasAutoDisconnected: value,
        realtimeRequested: value ? false : prev.realtimeRequested,
        socketConnected: value ? false : prev.socketConnected,
      }),
    })),
  setConfigChanged: (value) =>
    set((prev) => ({
      configChanged: value,
      connectionState: deriveState({ ...prev, configChanged: value }),
    })),
  setLiveActivity: (type, message) =>
    set({
      liveActivityType: type,
      liveActivityMessage: message,
      liveActivityAt: Date.now(),
    }),
  clearLiveActivity: () =>
    set({
      liveActivityType: null,
      liveActivityMessage: null,
      liveActivityAt: null,
    }),
  resetRuntime: () =>
    set({
      backendReachable: true,
      backendError: null,
      sshConnected: false,
      realtimeRequested: false,
      socketConnected: false,
      socketError: null,
      connectionState: 'idle',
      lastActivityAt: Date.now(),
      timeoutMinutes: get().timeoutMinutes,
      wasAutoDisconnected: false,
      configChanged: false,
      liveActivityType: null,
      liveActivityMessage: null,
      liveActivityAt: null,
    }),
}));
