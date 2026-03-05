import { create } from 'zustand';

export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'auto-disconnected' | 'config-changed';

interface RuntimeState {
  sshConnected: boolean;
  socketConnected: boolean;
  socketError: string | null;
  connectionState: ConnectionState;
  lastActivityAt: number;
  timeoutMinutes: number;
  wasAutoDisconnected: boolean;
  configChanged: boolean;
  setSshConnected: (value: boolean) => void;
  setSocketConnected: (value: boolean) => void;
  setSocketError: (error: string | null) => void;
  markActivity: () => void;
  setTimeoutMinutes: (minutes: number) => void;
  setAutoDisconnected: (value: boolean) => void;
  setConfigChanged: (value: boolean) => void;
  resetRuntime: () => void;
}

function deriveState(state: Pick<RuntimeState, 'sshConnected' | 'socketConnected' | 'wasAutoDisconnected' | 'configChanged'>): ConnectionState {
  if (state.configChanged) return 'config-changed';
  if (state.socketConnected && state.sshConnected) return 'connected';
  if (!state.socketConnected && state.sshConnected && state.wasAutoDisconnected) return 'auto-disconnected';
  if (!state.socketConnected && state.sshConnected) return 'disconnected';
  if (state.socketConnected) return 'connecting';
  return 'disconnected';
}

export const useRuntimeStore = create<RuntimeState>((set, get) => ({
  sshConnected: false,
  socketConnected: false,
  socketError: null,
  connectionState: 'connecting',
  lastActivityAt: Date.now(),
  timeoutMinutes: 30,
  wasAutoDisconnected: false,
  configChanged: false,
  setSshConnected: (value) =>
    set((prev) => ({
      sshConnected: value,
      connectionState: deriveState({ ...prev, sshConnected: value }),
    })),
  setSocketConnected: (value) =>
    set((prev) => ({
      socketConnected: value,
      wasAutoDisconnected: value ? false : prev.wasAutoDisconnected,
      socketError: value ? null : prev.socketError,
      connectionState: deriveState({ ...prev, socketConnected: value, wasAutoDisconnected: value ? false : prev.wasAutoDisconnected }),
    })),
  setSocketError: (error) =>
    set((prev) => ({
      socketError: error,
      connectionState: deriveState(prev),
    })),
  markActivity: () => set({ lastActivityAt: Date.now() }),
  setTimeoutMinutes: (minutes) => set({ timeoutMinutes: Math.max(5, Math.min(60, minutes)) }),
  setAutoDisconnected: (value) =>
    set((prev) => ({
      wasAutoDisconnected: value,
      socketConnected: value ? false : prev.socketConnected,
      connectionState: deriveState({ ...prev, wasAutoDisconnected: value, socketConnected: value ? false : prev.socketConnected }),
    })),
  setConfigChanged: (value) =>
    set((prev) => ({
      configChanged: value,
      connectionState: deriveState({ ...prev, configChanged: value }),
    })),
  resetRuntime: () =>
    set({
      sshConnected: false,
      socketConnected: false,
      socketError: null,
      connectionState: 'disconnected',
      lastActivityAt: Date.now(),
      timeoutMinutes: get().timeoutMinutes,
      wasAutoDisconnected: false,
      configChanged: false,
    }),
}));
