import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { clockText, formatSpan } from "@/lib/pipeline";
import type { RunDetail, RunEvent, StageDetail } from "@/lib/sync-types";
import { useTransferLogs } from "@/hooks/useTransfers";
import { formatBytes, formatEta, formatSpeed } from "@/lib/transfer-progress";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { StageNode, StageStatusBadge } from "@/components/pipeline/pipeline-bits";
import {
  Fact,
  PathBlock,
  ProgressMeter,
  TransportBadge,
} from "@/components/transfers/transfer-bits";
import { TransferLogConsole } from "@/components/transfers/transfer-logs";
import { IconInfoCircle } from "@tabler/icons-react";

/**
 * Every stage of one run, top to bottom, each opening to what it decided, the
 * facts it decided on, and the log lines it wrote — so "what happened to this
 * webhook" is answered stage by stage rather than by reading the server log.
 *
 * A skipped stage still opens: why it was skipped is the point of showing it.
 */
export function StageList({
  run,
  open,
  onOpenChange,
}: {
  run: RunDetail;
  open: string[];
  onOpenChange: (open: string[]) => void;
}) {
  return (
    <Accordion
      multiple
      value={open}
      onValueChange={(value) => onOpenChange(value as string[])}
      className="overflow-hidden rounded-xl border border-border bg-card"
    >
      {run.stage_detail.map((stage, index) => (
        <StageItem
          key={stage.id}
          run={run}
          stage={stage}
          index={index}
          expanded={open.includes(stage.id)}
        />
      ))}
    </Accordion>
  );
}

function StageItem({
  run,
  stage,
  index,
  expanded,
}: {
  run: RunDetail;
  stage: StageDetail;
  index: number;
  expanded: boolean;
}) {
  const quiet = stage.status === "pending" || stage.status === "skipped";
  const took = durationText(stage.started_at, stage.finished_at);
  // A skipped stage's reason is usually the kind's own note; say it once.
  const showPolicy =
    stage.mode !== "run" && stage.policy_note && stage.policy_note !== stage.summary;

  return (
    <AccordionItem
      value={stage.id}
      id={`stage-${stage.id}`}
      className="scroll-mt-20 border-b border-border last:border-b-0"
    >
      <AccordionTrigger className="items-start gap-3 px-4 py-3 no-underline hover:bg-muted/40 hover:no-underline">
        <span className="flex min-w-0 flex-1 items-start gap-3">
          <StageNode status={stage.status} className="mt-0.5 size-7" iconClassName="size-3.5" />
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                {index + 1}
              </span>
              <span
                className={cn(
                  "text-sm font-semibold",
                  quiet ? "text-muted-foreground" : "text-foreground"
                )}
              >
                {stage.label}
              </span>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {stage.tagline}
              </span>
              {stage.mode === "diff" && (
                <span className="rounded-[5px] border border-amber-500/30 px-1 py-px text-[9px] font-semibold tracking-wide text-amber-300/90 uppercase">
                  Different here
                </span>
              )}
            </span>
            <span
              className={cn(
                "text-[13px] text-pretty",
                quiet ? "text-muted-foreground" : "text-foreground/85",
                !expanded && "line-clamp-2"
              )}
            >
              {stage.summary || (stage.status === "pending" ? "Not reached yet." : "")}
            </span>
          </span>
          <span className="flex shrink-0 flex-col items-end gap-1">
            <StageStatusBadge status={stage.status} />
            {(stage.started_at || took) && (
              <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">
                {clockText(stage.started_at)}
                {took && ` · ${took}`}
              </span>
            )}
          </span>
        </span>
      </AccordionTrigger>

      <AccordionContent className="bg-black/20 px-4 pt-1 pb-4">
        <div className="flex flex-col gap-4 pl-10">
          {showPolicy && (
            <p className="flex items-start gap-2 rounded-lg border border-border bg-background/50 px-3 py-2 text-xs text-muted-foreground">
              <IconInfoCircle className="mt-px size-3.5 shrink-0" />
              <span>
                <span className="font-semibold text-foreground/90">
                  {stage.mode === "skip" ? "Skipped" : "Runs differently"} for {run.kind_label}:
                </span>{" "}
                {stage.policy_note}
              </span>
            </p>
          )}

          <StageFacts run={run} stage={stage} expanded={expanded} />

          <EventLog events={stage.events} />
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}

/** The facts a stage decided on, drawn for the stages that have any. */
function StageFacts({
  run,
  stage,
  expanded,
}: {
  run: RunDetail;
  stage: StageDetail;
  expanded: boolean;
}) {
  const detail = (stage.detail ?? {}) as Record<string, unknown>;

  if (stage.id === "identify" && stage.status !== "pending") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <PathBlock label="From (media server)" value={run.source_path ?? undefined} />
        <PathBlock label="To (this disk)" value={run.dest_path ?? undefined} />
      </div>
    );
  }

  if (stage.id === "ready") {
    return <ReadyFacts run={run} detail={detail} />;
  }

  if (stage.id === "safety" && "incoming_count" in detail) {
    return <SafetyFacts detail={detail} />;
  }

  if (stage.id === "transfer" && run.transfer) {
    return <TransferFacts run={run} stage={stage} expanded={expanded} />;
  }

  return null;
}

function ReadyFacts({ run, detail }: { run: RunDetail; detail: Record<string, unknown> }) {
  const downloading = asList(detail.detail);
  const stuck = asList(detail.stuck_detail);
  const eta = typeof detail.eta_seconds === "number" ? formatSpan(detail.eta_seconds) : "";
  if (!run.ready_mode && !downloading.length && !stuck.length) return null;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact
          label="Decided by"
          value={
            run.ready_mode === "ask"
              ? "Asking Sonarr"
              : run.ready_mode === "timer"
                ? "The fixed timer"
                : undefined
          }
        />
        <Fact
          label="Times asked"
          value={run.checks_made ? String(run.checks_made) : undefined}
          mono
        />
        <Fact label="Still downloading" value={numberText(detail.blocking)} mono tone="warn" />
        <Fact label="Time left (Sonarr)" value={eta || undefined} mono />
        <Fact
          label="Timer ends"
          value={run.ready_mode === "timer" ? clockText(run.timer_due_at) : undefined}
          mono
        />
        <Fact label="Gives up waiting" value={clockText(run.ready_deadline_at)} mono />
      </div>
      <FileList label="Downloading" items={downloading} />
      <FileList label="Stuck in Sonarr — not waited for" items={stuck} tone="warn" />
    </div>
  );
}

function SafetyFacts({ detail }: { detail: Record<string, unknown> }) {
  const deleting = Number(detail.deleted_count ?? 0);
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact label="Would copy" value={numberText(detail.incoming_count) ?? "0"} mono />
        <Fact
          label="Would delete"
          value={numberText(detail.deleted_count) ?? "0"}
          mono
          tone={deleting > 0 ? "warn" : undefined}
        />
        <Fact
          label="On the media server"
          value={numberText(detail.server_file_count) ?? "0"}
          mono
        />
        <Fact label="On this disk" value={numberText(detail.local_file_count) ?? "0"} mono />
      </div>
      <FileList label="Files it would copy" items={asList(detail.incoming_files)} />
      <FileList label="Files it would delete" items={asList(detail.deleted_files)} tone="warn" />
    </div>
  );
}

function TransferFacts({
  run,
  stage,
  expanded,
}: {
  run: RunDetail;
  stage: StageDetail;
  expanded: boolean;
}) {
  const transfer = run.transfer!;
  const running = transfer.status === "running";
  const stats = (stage.detail ?? {}) as Record<string, unknown>;
  // The rsync output is the Transfer stage's own log; fetched only while the
  // stage is open, and kept fresh only while rsync is still writing it.
  const logsQuery = useTransferLogs(transfer.transfer_id, { enabled: expanded, live: running });
  const percent = Math.round(transfer.progress_percent ?? 0);
  const size =
    transfer.total_bytes != null
      ? `${formatBytes(transfer.bytes_transferred ?? 0)} of ${formatBytes(transfer.total_bytes)}`
      : undefined;

  return (
    <div className="flex flex-col gap-3">
      {(running || transfer.status === "paused") && (
        <div className="flex items-center gap-2.5">
          <ProgressMeter percent={percent} status={transfer.status} className="flex-1" />
          <span className="w-10 shrink-0 text-right font-mono text-[11px] text-foreground tabular-nums">
            {percent}%
          </span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact
          label="Route"
          value={
            transfer.transport === "daemon" ? (
              <TransportBadge transport="daemon" />
            ) : transfer.transport === "ssh" ? (
              "SSH"
            ) : run.is_simulation ? (
              "Local (rehearsal)"
            ) : undefined
          }
        />
        <Fact label="Moved" value={size} mono />
        <Fact label="Speed" value={running ? formatSpeed(transfer.speed_bps) : undefined} mono />
        <Fact
          label="Time left"
          value={running ? formatEta(transfer.eta_seconds) : undefined}
          mono
        />
        <Fact label="Files copied" value={numberText(stats.regular_files_transferred)} mono />
        <Fact label="Files deleted" value={numberText(stats.deleted_files)} mono />
        <Fact label="Size moved" value={stringText(stats.total_transferred_size)} mono />
        <Fact label="Average speed" value={stringText(stats.avg_speed)} mono />
      </div>
      <TransferLogConsole
        title={run.label}
        logs={logsQuery.data?.logs ?? []}
        live={running}
        loading={logsQuery.isLoading}
      />
    </div>
  );
}

const LEVEL_TONE: Record<string, string> = {
  error: "text-rose-400",
  warning: "text-amber-400",
  success: "text-emerald-400",
};

/** The stage's own log lines, oldest first. */
function EventLog({ events }: { events: RunEvent[] }) {
  const lines = useMemo(() => events.slice(-200), [events]);
  if (!lines.length) {
    return <p className="text-xs text-muted-foreground">Nothing was logged at this stage.</p>;
  }
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        Log · {events.length} line{events.length === 1 ? "" : "s"}
        {events.length > lines.length && ` · last ${lines.length}`}
      </span>
      <ol className="flex max-h-72 flex-col gap-1 overflow-y-auto rounded-md border border-border bg-background/60 px-2.5 py-2 font-mono text-[11.5px] leading-relaxed">
        {lines.map((event) => (
          <li key={event.id} className="flex gap-2.5">
            <span className="shrink-0 text-muted-foreground/70 tabular-nums">
              {clockText(event.created_at)}
            </span>
            <span
              className={cn("min-w-0 break-words", LEVEL_TONE[event.level] ?? "text-foreground/85")}
            >
              {event.message}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function FileList({ label, items, tone }: { label: string; items: string[]; tone?: "warn" }) {
  if (!items.length) return null;
  const shown = items.slice(0, 12);
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </span>
      <ul
        className={cn(
          "flex flex-col gap-0.5 rounded-md border border-border bg-background/60 px-2.5 py-1.5 font-mono text-[11px] break-all",
          tone === "warn" ? "text-amber-300/90" : "text-foreground/80"
        )}
      >
        {shown.map((item) => (
          <li key={item}>{item}</li>
        ))}
        {items.length > shown.length && (
          <li className="text-muted-foreground">and {items.length - shown.length} more</li>
        )}
      </ul>
    </div>
  );
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function numberText(value: unknown): string | undefined {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : undefined;
}

function stringText(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function durationText(started: string | null, finished: string | null): string {
  if (!started || !finished) return "";
  const seconds = (new Date(finished).getTime() - new Date(started).getTime()) / 1000;
  return seconds >= 1 ? formatSpan(seconds) : "";
}
