import { cn } from "@/lib/utils";
import { stageAnchor, stageStatusInfo, TONE_TEXT } from "@/lib/pipeline";
import type { StageDetail } from "@/lib/sync-types";
import { StageNode } from "@/components/pipeline/pipeline-bits";

/**
 * The nine stages side by side — the pipeline as a flow you can read left to
 * right. Each card says how its stage ended in one word; picking one opens
 * that stage's details below it, and picking it again closes them.
 *
 * Sized by the space it is given rather than by the screen: it sits inside a
 * transfer's row and inside the side panel, which are different widths on the
 * same monitor. Three across when narrow, five, then all nine once each card
 * can hold its label — a sideways scroll would hide the end of the run, which
 * is usually the part that matters. In the single row a short rule joins each
 * card to the next, green once the stage before it has passed, so the row
 * reads as one pipeline rather than nine tiles.
 */
export function StageFlow({
  runId,
  stages,
  currentStage,
  live,
  selected,
  onPick,
}: {
  runId: string;
  stages: StageDetail[];
  currentStage: string | null;
  /** Whether the run can still move: the stage it is on gets the live mark. */
  live: boolean;
  /** The stage whose details are open below, if any. */
  selected: string | null;
  onPick: (stageId: string) => void;
}) {
  return (
    <div className="@container">
      <ol className="grid grid-cols-3 gap-2 @lg:grid-cols-5 @4xl:grid-cols-9 @4xl:gap-3">
        {stages.map((stage, index) => {
          const info = stageStatusInfo(stage.status);
          const here = live && stage.id === currentStage;
          const picked = stage.id === selected;
          const quiet = stage.status === "skipped" || stage.status === "pending";
          const last = index === stages.length - 1;
          return (
            <li key={stage.id} className="relative min-w-0">
              <button
                type="button"
                onClick={() => onPick(stage.id)}
                aria-expanded={picked}
                aria-controls={picked ? stageAnchor(runId, stage.id) : undefined}
                aria-label={`Stage ${index + 1}, ${stage.label}: ${info.label}. ${
                  picked ? "Hide" : "Show"
                } its details.`}
                title={stage.summary ?? undefined}
                className={cn(
                  "flex h-full w-full min-w-0 flex-col gap-2 rounded-xl border bg-card px-2.5 py-2.5 text-left transition-[background-color,border-color,box-shadow] duration-200",
                  "hover:border-brand/40 hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none",
                  quiet ? "border-dashed border-border" : "border-border",
                  here && "border-brand/45 bg-brand/10",
                  picked && "border-solid border-brand/70 bg-brand/[0.12] ring-2 ring-brand/30"
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
                    quiet && !picked ? "text-muted-foreground" : "text-foreground"
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
                      <span className="size-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none" />
                      {info.label}
                    </span>
                  ) : (
                    info.label
                  )}
                </span>
              </button>
              {!last && (
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-1/2 -right-3 hidden h-px w-3 @4xl:block",
                    stage.status === "passed" ? "bg-emerald-500/50" : "bg-border"
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
