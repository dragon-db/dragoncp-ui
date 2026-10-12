import { useState } from "react";
import type { RunDetail } from "@/lib/sync-types";
import { isLiveState } from "@/hooks/useSync";
import { StageFlow } from "@/components/pipeline/stage-flow";
import { StagePanel } from "@/components/pipeline/stage-detail";

/** The stage worth opening without being asked: the one working, waiting, or where it went wrong. */
function stageNeedingEyes(run: RunDetail): string | null {
  const found = run.stage_detail.find((stage) =>
    ["failed", "refused", "waiting", "running"].includes(stage.status)
  );
  return found?.id ?? null;
}

/**
 * One sync at a glance: the nine stages as a flow, and below it the details
 * of the one stage picked — what it decided, the facts and its log.
 *
 * Used inside a transfer's row and in the side panel for a sync. Nothing is
 * open for a sync that went through cleanly; one that is working, waiting,
 * stopped or failed opens that stage by itself, until someone picks another.
 */
export function RunStages({
  run,
  showTransferFacts = true,
}: {
  run: RunDetail;
  /** Off inside a transfer's row, which already shows the copy's progress and output. */
  showTransferFacts?: boolean;
}) {
  // `undefined` until someone picks: the run's own choice applies, and moves
  // with it. `null` is a choice too — everything closed.
  const [chosen, setChosen] = useState<string | null | undefined>(undefined);
  const selected = chosen === undefined ? stageNeedingEyes(run) : chosen;
  const index = run.stage_detail.findIndex((stage) => stage.id === selected);
  const stage = index >= 0 ? run.stage_detail[index] : null;

  return (
    <div className="flex flex-col gap-3">
      <StageFlow
        runId={run.run_id}
        stages={run.stage_detail}
        currentStage={run.current_stage}
        live={isLiveState(run.state)}
        selected={selected}
        onPick={(stageId) => setChosen(stageId === selected ? null : stageId)}
      />
      {stage ? (
        <StagePanel
          run={run}
          stage={stage}
          index={index}
          showTransferFacts={showTransferFacts}
          onClose={() => setChosen(null)}
        />
      ) : (
        <p className="text-[11.5px] text-muted-foreground">
          Pick a stage to see what it decided and its log.
        </p>
      )}
    </div>
  );
}
