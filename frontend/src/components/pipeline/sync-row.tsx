import { cn } from "@/lib/utils";
import { sinceText } from "@/lib/pipeline";
import type { RunSummary } from "@/lib/sync-types";
import { isLiveState, useSyncCatalogue } from "@/hooks/useSync";
import { Button } from "@/components/ui/button";
import {
  FactLine,
  KindBadge,
  RunStateBadge,
  StageStrip,
} from "@/components/pipeline/pipeline-bits";
import { IconChevronRight, IconPlayerPlay } from "@tabler/icons-react";

/**
 * One sync that has no transfer row of its own — still waiting to start, or
 * stopped before it copied anything — as a row in the Transfers lists.
 *
 * Shaped like a transfer's row so the two lists read alike: what it is, how far
 * it got as a nine-segment strip, and in the engine's own words what it is
 * doing now or why it ended. Opening it shows every stage in the side panel.
 */
export function SyncRow({
  run,
  onOpen,
  onGoNow,
  busy,
}: {
  run: RunSummary;
  onOpen: (runId: string) => void;
  /** Start a held or waiting sync now — the one action worth having on the row. */
  onGoNow?: (run: RunSummary) => void;
  busy?: boolean;
}) {
  const catalogue = useSyncCatalogue();
  const stageLabel = catalogue.data?.stages.find((stage) => stage.id === run.current_stage)?.label;
  const webhooks = run.webhook_count ?? 0;
  // A live sync is described by what it is doing; a finished one by how it
  // ended — the safety check's reason, the error — rather than by the
  // bookkeeping its last stage did.
  const sentence = isLiveState(run.state)
    ? run.current_summary || run.outcome_message
    : run.outcome_message || run.current_summary;
  const canGo = Boolean(onGoNow) && (run.state === "held" || run.state === "waiting");

  return (
    <li className="flex flex-col items-stretch border-b border-border last:border-b-0 sm:flex-row">
      <button
        type="button"
        onClick={() => onOpen(run.run_id)}
        className="flex min-w-0 flex-1 items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40 sm:items-center"
      >
        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-sm font-semibold break-words text-foreground">{run.label}</span>
            <KindBadge kind={run.kind} label={run.kind_label} />
            {run.is_simulation && run.kind !== "simulation" && (
              <KindBadge kind="simulation" label="Rehearsal" />
            )}
            <RunStateBadge state={run.state} label={run.state_label} className="sm:hidden" />
          </span>

          <span className="flex min-w-0 items-center gap-2.5">
            <StageStrip
              stages={run.stages}
              defs={catalogue.data?.stages}
              className="w-[160px] shrink-0 sm:w-[200px]"
            />
            {stageLabel && (
              <span className="truncate font-mono text-[10.5px] text-muted-foreground">
                {stageLabel}
              </span>
            )}
          </span>

          {sentence && (
            <span
              className={cn(
                "line-clamp-2 text-[12.5px] text-pretty",
                run.state === "failed" ? "text-rose-300/90" : "text-foreground/75"
              )}
            >
              {sentence}
            </span>
          )}

          <FactLine
            facts={[
              run.requested_by.label ? `by ${run.requested_by.label}` : null,
              sinceText(run.created_at),
              webhooks ? `${webhooks} webhook${webhooks === 1 ? "" : "s"}` : null,
            ]}
          />
        </span>

        <span className="hidden shrink-0 items-center gap-2 sm:flex">
          <RunStateBadge state={run.state} label={run.state_label} />
          <IconChevronRight className="size-4 text-muted-foreground" />
        </span>
      </button>

      {canGo && (
        <div className="flex items-center px-4 pb-3 sm:p-0 sm:pr-4">
          <Button
            size="sm"
            className="w-full border-0 bg-brand-gradient-x text-white sm:w-auto"
            disabled={busy}
            onClick={() => onGoNow?.(run)}
          >
            <IconPlayerPlay className="mr-1.5 size-3.5" />
            {run.state === "held" ? "Sync now" : "Go now"}
          </Button>
        </div>
      )}
    </li>
  );
}
