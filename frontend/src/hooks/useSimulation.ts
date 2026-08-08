import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

export interface SimulationScenario {
  key: string;
  name: string;
  description: string;
  transfers: number;
  size_mb: number;
  bwlimit_kbps: number;
  same_destination: boolean;
  with_webhooks: boolean;
  fail: boolean;
}

export interface SimulationStatus {
  scenarios: SimulationScenario[];
  total: number;
  by_status: Record<string, number>;
  finished: boolean;
  disk_bytes: number;
  real_transfers_running: number;
  max_concurrent: number;
}

/** A real transfer that a simulation would queue behind. */
export interface BusyTransfer {
  id: string;
  title: string;
  status: string;
}

export function useSimulationStatus(pollWhileActive: boolean) {
  return useQuery({
    queryKey: ["simulation", "status"],
    queryFn: async () => {
      const response = await api.get<{ status: string } & SimulationStatus>("/simulation/status");
      return response.data;
    },
    refetchInterval: pollWhileActive ? 3000 : false,
  });
}

export function useStartSimulation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ scenario, confirmBusy }: { scenario: string; confirmBusy?: boolean }) => {
      const response = await api.post<{ status: string; message: string; run_id?: string }>(
        "/simulation/start",
        { scenario, confirm_busy: confirmBusy }
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["simulation"] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}

export function useStopSimulation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const response = await api.post("/simulation/stop");
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["simulation"] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}

export function useCleanupSimulation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const response = await api.post<{
        status: string;
        message: string;
        transfers_removed: number;
        notifications_removed: number;
      }>("/simulation/cleanup");
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["simulation"] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}

/** The 409 body the start endpoint returns when real transfers are running. */
export function busyConflictFrom(error: unknown): BusyTransfer[] | null {
  const response = (error as { response?: { status?: number; data?: Record<string, unknown> } })
    ?.response;
  if (response?.status !== 409) return null;
  if (response.data?.code !== "real_transfers_running") return null;
  return (response.data.running as BusyTransfer[]) ?? [];
}
