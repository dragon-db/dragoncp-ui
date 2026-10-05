import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type {
  Alert,
  AlertList,
  AlertSummary,
  RunActionResult,
  RunDetail,
  RunList,
  SchedulerJob,
  SyncCatalogue,
} from "@/lib/sync-types";

/**
 * The sync engine, the Notifications tab and the scheduler.
 *
 * Realtime is opt-in, so every query here polls on its own; socket events
 * (`sync_run_updated`, `sync_run_event`, `alerts_changed`) only make the
 * same queries refresh sooner when realtime is on. No fact arrives by socket
 * alone.
 */

/** States a run can still move out of. A list or a run in one of these polls. */
const LIVE_STATES = new Set([
  "held",
  "waiting",
  "checking",
  "queued",
  "transferring",
  "paused",
  "finishing",
]);

export function isLiveState(state: string | null | undefined): boolean {
  return LIVE_STATES.has(state ?? "");
}

/** The nine stages and every kind of sync — the same data the engine runs on. */
export function useSyncCatalogue() {
  return useQuery({
    queryKey: ["sync", "catalogue"],
    queryFn: async () => {
      const response = await api.get<SyncCatalogue & { status: string }>("/sync/catalogue");
      return response.data;
    },
    // Changes only with a new backend build.
    staleTime: Infinity,
  });
}

export interface RunListOptions {
  /** A state group (`live`, `open`, `active`, `finished`, `all`) or states, comma separated. */
  state?: string;
  kinds?: string[];
  search?: string;
  limit?: number;
  offset?: number;
  /** Include rehearsals. On by default, as on the server. */
  simulations?: boolean;
}

export function useSyncRuns(options: RunListOptions = {}) {
  const { state = "all", kinds, search, limit = 50, offset = 0, simulations = true } = options;
  return useQuery({
    queryKey: ["sync", "runs", { state, kinds, search, limit, offset, simulations }],
    queryFn: async () => {
      const params = new URLSearchParams({
        state,
        limit: String(limit),
        offset: String(offset),
        simulations: simulations ? "1" : "0",
      });
      if (kinds?.length) params.set("kind", kinds.join(","));
      if (search) params.set("search", search);
      const response = await api.get<RunList & { status: string }>(`/sync/runs?${params}`);
      return response.data;
    },
    placeholderData: (previous) => previous,
    // Quick while something on the page can still change, slow otherwise.
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => isLiveState(run.state)) ? 4000 : 15000,
  });
}

export function useSyncRun(runId: string | undefined) {
  return useQuery({
    queryKey: ["sync", "run", runId],
    enabled: Boolean(runId),
    queryFn: async () => {
      const response = await api.get<{ status: string; run: RunDetail }>(`/sync/runs/${runId}`);
      return response.data.run;
    },
    // A finished run does not change; a live one is worth watching.
    refetchInterval: (query) => (isLiveState(query.state.data?.state) ? 2500 : false),
  });
}

export type RunAction = "go-now" | "cancel" | "sync-anyway";

export function useSyncRunAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ runId, action }: { runId: string; action: RunAction }) => {
      const response = await api.post<RunActionResult>(`/sync/runs/${runId}/${action}`);
      return response.data;
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["sync"] });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
}

// -- Notifications ----------------------------------------------------------

/** `open`, or every closed alert at once. */
export type AlertView = "open" | "closed";

const CLOSED_STATES = "done,wrong,dismissed";

export function useAlerts(view: AlertView, page: { limit?: number; offset?: number } = {}) {
  const { limit = 50, offset = 0 } = page;
  return useQuery({
    queryKey: ["alerts", "list", { view, limit, offset }],
    queryFn: async () => {
      const params = new URLSearchParams({
        state: view === "open" ? "open" : CLOSED_STATES,
        limit: String(limit),
        offset: String(offset),
      });
      const response = await api.get<AlertList & { status: string }>(`/alerts?${params}`);
      return response.data;
    },
    placeholderData: (previous) => previous,
    refetchInterval: 30000,
  });
}

/** How many alerts are open — the badge on the bell and the sidebar. */
export function useAlertSummary() {
  return useQuery({
    queryKey: ["alerts", "summary"],
    queryFn: async () => {
      const response = await api.get<AlertSummary & { status: string }>("/alerts/summary");
      return response.data;
    },
    refetchInterval: 30000,
  });
}

export function useAlertAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ alertId, action }: { alertId: string; action: string }) => {
      const response = await api.post<{ status: string; message: string; alert: Alert | null }>(
        `/alerts/${alertId}/action`,
        { action }
      );
      return response.data;
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: ["sync"] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });
}

// -- Scheduler --------------------------------------------------------------

export function useSchedulerJobs() {
  return useQuery({
    queryKey: ["scheduler", "jobs"],
    queryFn: async () => {
      const response = await api.get<{ status: string; jobs: SchedulerJob[] }>("/scheduler/jobs");
      return response.data.jobs;
    },
    // A running job finishes in seconds; an idle one changes every few minutes.
    refetchInterval: (query) => (query.state.data?.some((job) => job.running) ? 3000 : 30000),
  });
}

export function useRunJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const response = await api.post<{ status: string; message: string; job: SchedulerJob }>(
        `/scheduler/jobs/${name}/run`
      );
      return response.data;
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduler"] });
      queryClient.invalidateQueries({ queryKey: ["sync"] });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}
