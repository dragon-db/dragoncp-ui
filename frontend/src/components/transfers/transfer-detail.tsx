import { cn } from "@/lib/utils";
import { ActorBadge } from "@/components/activity/actor-badge";
import { Button } from "@/components/ui/button";
import { Chip, Fact, PathBlock, ProgressMeter } from "@/components/transfers/transfer-bits";
import { TransferLogConsole } from "@/components/transfers/transfer-logs";
import type { Transfer } from "@/lib/api-types";
import {
  formatBytes,
  formatDuration,
  formatEta,
  formatSizePair,
  formatSpeed,
  parseTimestamp,
  transferElapsed,
  transferPercent,
} from "@/lib/transfer-progress";
import {
  IconArrowBackUp,
  IconCircleX,
  IconPlayerPause,
  IconPlayerPlay,
  IconTrash,
} from "@tabler/icons-react";

export interface TransferActions {
  onPause: (transfer: Transfer) => void;
  onResume: (transfer: Transfer) => void;
  onStop: (transfer: Transfer) => void;
  onRestart: (transfer: Transfer) => void;
  onDelete: (transfer: Transfer) => void;
}

/**
 * The transfer's own history: how long it waited, how long it has run, and
 * whether a pause interrupted it. A queue that holds work for forty minutes
 * looks identical to a slow copy in a status column — here it doesn't.
 */
function Timeline({ transfer, now }: { transfer: Transfer; now: number }) {
  const created = parseTimestamp(transfer.created_at);
  const started = parseTimestamp(transfer.start_time);
  const paused = parseTimestamp(transfer.paused_at);
  const ended = parseTimestamp(transfer.end_time);

  const stages: Array<{ label: string; at: number | null; span: string | null; tone?: string }> =
    [];

  if (created != null) {
    stages.push({
      label: "Queued",
      at: created,
      span: started != null ? formatDuration(started - created) : null,
    });
  }
  if (started != null) {
    stages.push({
      label: transfer.status === "queued" ? "Waiting" : "Started",
      at: started,
      span: formatDuration((ended ?? now) - started),
      tone: "brand",
    });
  }
  if (paused != null) {
    stages.push({
      label: "Paused",
      at: paused,
      span: formatDuration(now - paused),
      tone: "warn",
    });
  }
  if (ended != null) {
    stages.push({
      label:
        transfer.status === "completed"
          ? "Completed"
          : transfer.status === "cancelled"
            ? "Stopped"
            : "Ended",
      at: ended,
      span: null,
      tone: transfer.status === "completed" ? "ok" : "muted",
    });
  }

  if (!stages.length) return null;

  return (
    <section className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        Timeline
      </span>
      <ol className="flex flex-col">
        {stages.map((stage, index) => (
          <li key={stage.label} className="flex items-start gap-2.5">
            <div className="flex flex-col items-center self-stretch">
              <span
                className={cn(
                  "mt-1 size-1.5 shrink-0 rounded-full",
                  stage.tone === "brand" && "bg-brand-hover",
                  stage.tone === "ok" && "bg-emerald-400",
                  stage.tone === "warn" && "bg-amber-400",
                  (!stage.tone || stage.tone === "muted") && "bg-muted-foreground/60"
                )}
              />
              {index < stages.length - 1 && <span className="w-px flex-1 bg-border" />}
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5 pb-2">
              <span className="text-xs font-medium text-foreground">{stage.label}</span>
              <span className="font-mono text-[10.5px] text-muted-foreground">
                {stage.at != null ? new Date(stage.at).toLocaleTimeString() : ""}
              </span>
              {stage.span && (
                <span className="font-mono text-[10.5px] text-muted-foreground/80">
                  · {stage.span}
                </span>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * Everything known about one transfer: what it is moving right now, where it is
 * going, how it got here, and the live rsync output — expanded in place rather
 * than in a dialog, matching how a webhook arrival opens.
 */
export function TransferDetailPanel({
  transfer,
  logs,
  logsLoading,
  now,
  actions,
  busy,
}: {
  transfer: Transfer;
  logs: string[];
  logsLoading?: boolean;
  now: number;
  actions: TransferActions;
  busy?: boolean;
}) {
  const status = transfer.status;
  const running = status === "running";
  const paused = status === "paused";
  const queued = status === "queued" || status === "pending";
  const active = running || paused || queued;

  const percent = transferPercent(transfer);
  const size = formatSizePair(transfer.bytes_transferred, transfer.total_bytes);
  const eta = running ? formatEta(transfer.eta_seconds) : null;
  const elapsed = transferElapsed(transfer, now);

  const remaining =
    transfer.total_bytes != null && transfer.bytes_transferred != null
      ? Math.max(0, transfer.total_bytes - transfer.bytes_transferred)
      : null;

  const title = transfer.parsed_title || transfer.folder_name;

  return (
    <div className="flex flex-col gap-4">
      {/* Progress — only while there is progress to report */}
      {active && (
        <section className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Progress
            </span>
            {running && <Chip>{formatSpeed(transfer.speed_bps)}</Chip>}
            {eta && <Chip>ETA {eta}</Chip>}
            {size && (
              <Chip>
                {size.value} {size.unit}
              </Chip>
            )}
            {remaining != null && running && <Chip>{formatBytes(remaining)} left</Chip>}
            {/* Why it is waiting decides what to do about it: a busy queue
                clears itself, a path conflict needs the other copy to finish. */}
            {queued && (
              <Chip>
                {transfer.queue_reason === "path"
                  ? "waiting for the destination to be free"
                  : "waiting for a free slot"}
              </Chip>
            )}
          </div>
          <div className="flex items-center gap-3">
            <ProgressMeter percent={percent} status={status} className="h-1.5 flex-1" />
            <span className="w-10 shrink-0 text-right font-mono text-xs text-foreground tabular-nums">
              {queued ? "—" : `${percent}%`}
            </span>
          </div>
        </section>
      )}

      {/* Who is answerable for this run. First, because when something has gone
          wrong in the library this is the question being asked. */}
      <section className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
          Started by
        </span>
        {transfer.started_by_name ? (
          <ActorBadge kind={transfer.started_by_kind} name={transfer.started_by_name} size="sm" />
        ) : (
          <span
            className="text-xs text-muted-foreground"
            title="This run predates activity recording, so nobody was captured. It is unknown rather than nobody."
          >
            not recorded
          </span>
        )}
      </section>

      {/* Facts */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact label="Media" value={transfer.media_type} mono />
        <Fact label="Season" value={transfer.season_name || transfer.parsed_season} mono />
        <Fact
          label="Scope"
          value={transfer.operation_type === "file" ? "single file" : "folder"}
          mono
        />
        <Fact
          label={transfer.end_time ? "Ran for" : "Running for"}
          value={formatDuration(elapsed)}
          mono
        />
        {/* Named in full here rather than badged, because the detail view is
            where someone asks why a transfer took as long as it did. */}
        <Fact
          label="Route"
          value={
            transfer.transport === "daemon"
              ? "transfer server"
              : transfer.transport === "ssh"
                ? "SSH"
                : undefined
          }
          mono
        />
        <Fact
          label="Transferred"
          value={
            transfer.bytes_transferred != null ? formatBytes(transfer.bytes_transferred) : undefined
          }
          mono
        />
        <Fact
          label="Total size"
          value={transfer.total_bytes != null ? formatBytes(transfer.total_bytes) : undefined}
          mono
        />
        <Fact label="Log lines" value={transfer.log_count} mono />
        <Fact label="Transfer ID" value={transfer.id} mono />
      </section>

      {/* Paths */}
      <section className="grid gap-2 sm:grid-cols-2">
        <PathBlock label="From (remote)" value={transfer.source_path} />
        <PathBlock label="To (local)" value={transfer.dest_path} />
      </section>

      <Timeline transfer={transfer} now={now} />

      {/* The last thing rsync said, when it is not just another progress tick */}
      {transfer.progress && !active && (
        <section className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
            Result
          </span>
          <p
            className={cn(
              "text-xs break-words",
              status === "failed" ? "text-rose-300" : "text-foreground/80"
            )}
          >
            {transfer.progress}
          </p>
        </section>
      )}

      <TransferLogConsole logs={logs} title={title} live={running} loading={logsLoading} />

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {running && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => actions.onPause(transfer)}
          >
            <IconPlayerPause className="mr-1.5 size-3.5" />
            Pause
          </Button>
        )}
        {paused && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => actions.onResume(transfer)}
          >
            <IconPlayerPlay className="mr-1.5 size-3.5" />
            Resume
          </Button>
        )}
        {(status === "failed" || status === "cancelled" || status === "completed") && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => actions.onRestart(transfer)}
          >
            <IconArrowBackUp className="mr-1.5 size-3.5" />
            {status === "completed" ? "Run again" : "Retry"}
          </Button>
        )}
        {(running || paused || queued) && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => actions.onStop(transfer)}
          >
            <IconCircleX className="mr-1.5 size-3.5" />
            Stop
          </Button>
        )}
        <span className="flex-1" />
        {status !== "running" && (
          <Button
            size="sm"
            variant="outline"
            className="text-muted-foreground hover:text-rose-400"
            disabled={busy}
            onClick={() => actions.onDelete(transfer)}
          >
            <IconTrash className="mr-1.5 size-3.5" />
            Delete
          </Button>
        )}
      </div>
    </div>
  );
}
