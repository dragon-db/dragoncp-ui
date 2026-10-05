/**
 * What the sync engine, the Notifications tab and the scheduler send.
 *
 * Mirrors `routes/sync_engine.py` and the engine's `summarise` / `describe_run`.
 * The stage and kind vocabulary is not repeated here: it comes from
 * `GET /api/sync/catalogue`, which is the same data the engine runs on, so the
 * screen cannot describe a different pipeline from the one that ran.
 */

/** How a stage ended, or what it is doing now. */
export type StageStatus =
  "pending" | "running" | "waiting" | "passed" | "skipped" | "failed" | "refused";

/** How a kind of sync treats a stage: as standard, differently, or not at all. */
export type StageMode = "run" | "diff" | "skip";

export interface StageDef {
  id: string;
  label: string;
  tagline: string;
  description: string;
}

export interface KindDef {
  id: string;
  label: string;
  description: string;
  mergeable: boolean;
  stages: Record<string, { mode: StageMode; note: string }>;
}

export interface SyncCatalogue {
  stages: StageDef[];
  kinds: KindDef[];
  stage_statuses: StageStatus[];
  states: {
    open: string[];
    active: string[];
    terminal: string[];
    labels: Record<string, string>;
  };
  state_groups: Record<string, string[]>;
  alert_actions: Record<string, string>;
  alert_kinds: Record<string, string>;
}

/** A run as a list row: what, how far, and the stage strip. */
export interface RunSummary {
  run_id: string;
  kind: string;
  kind_label: string;
  label: string;
  title: string | null;
  season_name: string | null;
  media_type: string | null;
  source: string | null;
  state: string;
  state_label: string;
  current_stage: string | null;
  /** What the stage it is on last said: what the run is doing now. */
  current_summary: string | null;
  outcome: string | null;
  outcome_message: string | null;
  transfer_id: string | null;
  parent_run_id: string | null;
  parent_relation: string | null;
  is_simulation: boolean;
  requested_by: { kind: string | null; name: string | null; label: string };
  stages: { id: string; status: StageStatus }[];
  webhook_count: number | null;
  next_check_at: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunList {
  runs: RunSummary[];
  total: number;
  state_counts: Record<string, number>;
  limit: number;
  offset: number;
}

/** One log line, tagged with the stage that wrote it. */
export interface RunEvent {
  id: number;
  run_id: string;
  stage: string;
  level: "info" | "success" | "warning" | "error" | string;
  message: string;
  data: Record<string, unknown> | null;
  created_at: string;
}

export interface StageDetail extends StageDef {
  mode: StageMode;
  /** Why this kind of sync runs the stage differently, or skips it. */
  policy_note: string;
  status: StageStatus;
  summary: string | null;
  detail: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  events: RunEvent[];
}

export interface RunWebhook {
  notification_id: string;
  table: "sonarr_webhook" | "radarr_webhook" | string;
  label: string | null;
  status: string;
  title?: string | null;
  year?: number | null;
  season_number?: number | null;
  created_at: string;
  sync_attached_at: string | null;
  transfer_id: string | null;
  requires_manual_sync?: number | null;
  manual_sync_reason?: string | null;
}

export interface RunTransfer {
  transfer_id: string;
  status: string;
  progress: string | null;
  transport: string | null;
  progress_percent: number | null;
  bytes_transferred: number | null;
  total_bytes: number | null;
  speed_bps: number | null;
  eta_seconds: number | null;
  start_time: string | null;
  end_time: string | null;
  log_count: number;
  queue_reason: string | null;
}

export interface RelatedRun extends RunSummary {
  /** `follow_up`, `retry`, or `<relation>_of` when this run is the parent. */
  relation: string;
}

/** Everything about one run, stage by stage, for the pipeline view. */
export interface RunDetail extends RunSummary {
  source_path: string | null;
  dest_path: string | null;
  operation_type: string | null;
  ready_mode: "ask" | "timer" | null;
  checks_made: number | null;
  timer_due_at: string | null;
  ready_deadline_at: string | null;
  force_safety: boolean;
  stage_detail: StageDetail[];
  webhooks: RunWebhook[];
  transfer: RunTransfer | null;
  related: RelatedRun[];
  alerts: Alert[];
  /** What can be done to it now: go_now, cancel, sync_anyway, restart. */
  actions: string[];
}

/** What an action on a run answers. */
export interface RunActionResult {
  status: string;
  ok: boolean;
  run_id: string | null;
  action: string;
  state: string;
  message: string;
  transfer_id: string | null;
  queue_state: string | null;
}

export type AlertState = "open" | "done" | "wrong" | "dismissed";
export type AlertSeverity = "info" | "warning" | "failure";

export interface Alert {
  alert_id: string;
  kind: string;
  kind_label: string;
  severity: AlertSeverity | string;
  title: string;
  message: string | null;
  state: AlertState | string;
  run_id: string | null;
  transfer_id: string | null;
  unit_key: string | null;
  link: string | null;
  actions: string[];
  action_buttons: { id: string; label: string }[];
  data: Record<string, unknown>;
  occurrences: number;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  resolved_action: string | null;
  resolved_by_kind: string | null;
  resolved_by_name: string | null;
}

export interface AlertSummary {
  open: number;
  by_severity: Record<string, number>;
}

export interface AlertList extends AlertSummary {
  alerts: Alert[];
  total: number;
  limit: number;
  offset: number;
}

export interface SchedulerJob {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  interval_seconds: number | null;
  running: boolean;
  last_run_at: string | null;
  last_finished_at: string | null;
  last_ok: boolean | null;
  last_result: { ok?: boolean; summary?: string; [key: string]: unknown };
  consecutive_failures: number;
  next_run_at: string | null;
}
