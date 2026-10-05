import { cn } from "@/lib/utils";
import { stageStatusInfo, TONE_TEXT } from "@/lib/pipeline";
import type { StageDetail } from "@/lib/sync-types";
import { StageNode } from "@/components/pipeline/pipeline-bits";

/**
 * The nine stages side by side — the pipeline as a flow you can read left to
 * right, the same shape the plan page drew. Each card says what happened at
 * that stage in one word; picking one opens it in the list below.
 *
 * Three across on a phone, nine across from `lg`: nine cards in a row would be
 * too narrow to read below that, and a sideways scroll would hide the end of
 * the run, which is usually the part that matters.
 */
export function StageFlow({
  stages,
  currentStage,
  live,
  onPick,
}: {
  stages: StageDetail[];
  currentStage: string | null;
  /** Whether the run can still move: the stage it is on gets the live mark. */
  live: boolean;
  onPick: (stageId: string) => void;
}) {
  return (
    <ol className="grid grid-cols-3 gap-2 lg:grid-cols-9">
      {stages.map((stage, index) => {
        const info = stageStatusInfo(stage.status);
        const here = live && stage.id === currentStage;
        const quiet = stage.status === "skipped" || stage.status === "pending";
        return (
          <li key={stage.id} className="min-w-0">
            <button
              type="button"
              onClick={() => onPick(stage.id)}
              aria-label={`Stage ${index + 1}, ${stage.label}: ${info.label}. Show its details.`}
              className={cn(
                "flex h-full w-full min-w-0 flex-col gap-2 rounded-xl border bg-card px-2.5 py-2.5 text-left transition-colors",
                "hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none",
                quiet ? "border-dashed border-border" : "border-border",
                here && "border-brand/45 bg-brand/10 ring-1 ring-brand/30 ring-inset"
              )}
            >
              <span className="flex items-center justify-between gap-1.5">
                <StageNode status={stage.status} className="size-6" iconClassName="size-3.5" />
                <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
                  {index + 1}
                </span>
              </span>
              <span
                className={cn(
                  "truncate text-[12.5px] leading-tight font-semibold",
                  quiet ? "text-muted-foreground" : "text-foreground"
                )}
              >
                {stage.label}
              </span>
              <span
                className={cn(
                  "truncate text-[10px] font-bold tracking-wide uppercase",
                  TONE_TEXT[info.tone]
                )}
              >
                {here && stage.status !== "passed" ? (
                  <span className="inline-flex items-center gap-1">
                    <span className="size-1.5 animate-pulse rounded-full bg-current" />
                    {info.label}
                  </span>
                ) : (
                  info.label
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
