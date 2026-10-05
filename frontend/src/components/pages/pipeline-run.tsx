import { useMemo, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { errorText } from "@/lib/api-error";
import { clockText, runStateTone, sinceText, TONE_BADGE } from "@/lib/pipeline";
import type { RunDetail } from "@/lib/sync-types";
import { isLiveState, useSyncRun, useSyncRunAction, type RunAction } from "@/hooks/useSync";
import { useRestartTransfer } from "@/hooks/useTransfers";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard } from "@/components/layout/section-card";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import { TransferStatusBadge } from "@/components/transfers/transfer-bits";
import { StatusBadge } from "@/components/webhooks/webhook-bits";
import { ActorBadge } from "@/components/activity/actor-badge";
import { AlertCard } from "@/components/pipeline/alert-card";
import { FactLine, KindBadge, RunStateBadge } from "@/components/pipeline/pipeline-bits";
import { StageFlow } from "@/components/pipeline/stage-flow";
import { StageList } from "@/components/pipeline/stage-list";
import {
  IconArrowBackUp,
  IconArrowLeft,
  IconPlayerPlay,
  IconPlayerStop,
  IconShieldCheck,
} from "@tabler/icons-react";

/** Stages worth having open without being asked: where the run is, and where it went wrong. */
function defaultOpen(run: RunDetail): string[] {
  const open = new Set<string>();
  if (run.current_stage) open.add(run.current_stage);
  for (const stage of run.stage_detail) {
    if (["failed", "refused", "waiting", "running"].includes(stage.status)) open.add(stage.id);
  }
  return [...open];
}

const RELATION_LABEL: Record<string, string> = {
  follow_up: "Follow-up",
  retry: "Retry",
  follow_up_of: "Follows",
  retry_of: "Retries",
};

/**
 * One sync, stage by stage.
 *
 * The flow across the top answers "how far did it get"; the list under it
 * answers "what did each stage decide, and why" with the stage's own log
 * lines. The side column is what rode on the sync — its webhooks, its
 * transfer, the syncs before and after it, and any alert it raised.
 */
export function PipelineRunPage({ runId }: { runId: string }) {
  const runQuery = useSyncRun(runId);
  const run = runQuery.data;
  const act = useSyncRunAction();
  const restart = useRestartTransfer();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [confirm, setConfirm] = useState<"cancel" | "sync-anyway" | null>(null);

  // Until someone opens or closes a stage, follow the run: as it moves on, the
  // stage it moves to opens by itself.
  const open = useMemo(() => chosen ?? (run ? defaultOpen(run) : []), [chosen, run]);

  if (runQuery.isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (!run) {
    // Only a 404 means the sync is gone; anything else is a failed request,
    // and saying "no such sync" then would send someone looking for the wrong
    // problem.
    const status = (runQuery.error as { response?: { status?: number } } | null)?.response?.status;
    const missing = status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <h1 className="text-2xl font-bold text-foreground">
          {missing ? "No such sync" : "Could not load this sync"}
        </h1>
        <p className="text-muted-foreground">
          {missing
            ? "It may have been a rehearsal that was cleaned up. The list has every sync on record."
            : errorText(runQuery.error, "The server did not answer.")}
        </p>
        {!missing && (
          <Button variant="outline" onClick={() => runQuery.refetch()}>
            Try again
          </Button>
        )}
      </div>
    );
  }

  const live = isLiveState(run.state);

  const perform = async (action: RunAction) => {
    try {
      const result = await act.mutateAsync({ runId: run.run_id, action });
      toast.success(result.message || "Done.");
    } catch (error) {
      toast.error(errorText(error, "That did not work."));
    }
  };

  const retry = async () => {
    if (!run.transfer_id) return;
    try {
      const result = (await restart.mutateAsync(run.transfer_id)) as {
        message?: string;
        run_id?: string;
      };
      toast.success(result.message || "Restart requested.");
      queryClient.invalidateQueries({ queryKey: ["sync"] });
      // The retry is a sync of its own; follow it there rather than leave this
      // finished one on screen offering Retry again.
      if (result.run_id && result.run_id !== run.run_id) {
        navigate({ to: "/pipeline/$runId", params: { runId: result.run_id } });
      }
    } catch (error) {
      toast.error(
        error instanceof Error && error.message ? error.message : "Could not restart it."
      );
    }
  };

  const pick = (stageId: string) => {
    setChosen((current) => {
      const base = current ?? defaultOpen(run);
      return base.includes(stageId) ? base : [...base, stageId];
    });
    // After the accordion has opened it.
    window.setTimeout(() => {
      document
        .getElementById(`stage-${stageId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  };

  const busy = act.isPending || restart.isPending;

  return (
    <div className="space-y-5">
      <BackLink />

      <header className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="text-2xl font-bold break-words text-foreground sm:text-3xl">
            {run.label}
          </h1>
          <div className="flex flex-wrap items-center gap-2">
            <RunStateBadge state={run.state} label={run.state_label} />
            <KindBadge kind={run.kind} label={run.kind_label} />
            {run.is_simulation && run.kind !== "simulation" && (
              <KindBadge kind="simulation" label="Rehearsal" />
            )}
            <ActorBadge kind={run.requested_by.kind} name={run.requested_by.name} size="sm" />
          </div>
          <FactLine
            facts={[
              `Started ${sinceText(run.created_at)}`,
              run.finished_at ? `ended ${clockText(run.finished_at)}` : null,
              <span key="id" className="select-all">
                {run.run_id}
              </span>,
            ]}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {run.actions.includes("go_now") && (
            <Button
              className="border-0 bg-brand-gradient-x text-white"
              disabled={busy}
              onClick={() => perform("go-now")}
            >
              <IconPlayerPlay className="mr-1.5 size-4" />
              {run.state === "held" ? "Sync now" : "Go now"}
            </Button>
          )}
          {run.actions.includes("sync_anyway") && (
            <Button
              variant="outline"
              className="border-amber-500/40 text-amber-300 hover:bg-amber-500/10"
              disabled={busy}
              onClick={() => setConfirm("sync-anyway")}
            >
              <IconShieldCheck className="mr-1.5 size-4" />
              Sync anyway
            </Button>
          )}
          {run.actions.includes("restart") && (
            <Button
              className="border-0 bg-brand-gradient-x text-white"
              disabled={busy}
              onClick={retry}
            >
              <IconArrowBackUp className="mr-1.5 size-4" />
              Retry
            </Button>
          )}
          {run.actions.includes("cancel") && (
            <Button
              variant="ghost"
              className="text-muted-foreground hover:bg-destructive/12 hover:text-destructive"
              disabled={busy}
              onClick={() => setConfirm("cancel")}
            >
              <IconPlayerStop className="mr-1.5 size-4" />
              Cancel
            </Button>
          )}
        </div>
      </header>

      <StateCallout run={run} />

      <StageFlow
        stages={run.stage_detail}
        currentStage={run.current_stage}
        live={live}
        onPick={pick}
      />

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_330px]">
        <StageList run={run} open={open} onOpenChange={setChosen} />

        <aside className="flex flex-col gap-4">
          {run.alerts.length > 0 && (
            <div className="flex flex-col gap-2">
              {run.alerts.map((alert) => (
                <AlertCard key={alert.alert_id} alert={alert} showRunLink={false} />
              ))}
            </div>
          )}

          <SectionCard label={`Webhooks · ${run.webhooks.length}`}>
            {run.webhooks.length ? (
              <ul className="divide-y divide-border/70">
                {run.webhooks.map((hook) => (
                  <li key={hook.notification_id} className="flex items-center gap-2 px-4 py-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground">
                      {hook.label || hook.notification_id}
                    </span>
                    <StatusBadge
                      status={
                        hook.requires_manual_sync && hook.status === "pending"
                          ? "MANUAL_SYNC_REQUIRED"
                          : hook.status
                      }
                    />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-4 py-3 text-xs text-muted-foreground">
                No webhook rode on this sync — it was started{" "}
                {run.kind === "auto_scanner" ? "by the auto-scanner" : "by hand"}.
              </p>
            )}
          </SectionCard>

          {run.transfer && (
            <SectionCard label="Transfer" contentClassName="flex flex-col gap-2 px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
                  {run.transfer.transfer_id}
                </span>
                <TransferStatusBadge status={run.transfer.status} size="sm" />
              </div>
              {run.transfer.progress && (
                <p className="text-xs break-words text-muted-foreground">{run.transfer.progress}</p>
              )}
              <Link
                to="/transfers"
                className="text-xs font-medium text-brand-hover hover:underline"
              >
                Open Transfers
              </Link>
            </SectionCard>
          )}

          {run.related.length > 0 && (
            <SectionCard label="Related syncs">
              <ul className="divide-y divide-border/70">
                {run.related.map((other) => (
                  <li key={other.run_id}>
                    <Link
                      to="/pipeline/$runId"
                      params={{ runId: other.run_id }}
                      className="flex flex-col gap-1 px-4 py-2.5 hover:bg-muted/40"
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-foreground">
                          {RELATION_LABEL[other.relation] ?? other.relation}
                        </span>
                        <RunStateBadge state={other.state} label={other.state_label} />
                      </span>
                      <span className="font-mono text-[10.5px] text-muted-foreground">
                        {other.run_id} · {sinceText(other.created_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </SectionCard>
          )}
        </aside>
      </div>

      <ConfirmDialog
        open={confirm === "cancel"}
        onOpenChange={(value) => !value && setConfirm(null)}
        title="Cancel this sync?"
        description="A copy in progress stops where it is; files it already finished stay, and partial ones are kept for a later retry. Its webhooks are marked cancelled."
        confirmLabel="Cancel the sync"
        cancelLabel="Keep it"
        pending={act.isPending}
        onConfirm={() => perform("cancel")}
      />
      <ConfirmDialog
        open={confirm === "sync-anyway"}
        onOpenChange={(value) => !value && setConfirm(null)}
        title="Sync despite the safety check?"
        description="The dry run said this sync could lose files. Going ahead copies it anyway; anything rsync replaces or removes is kept in the backup area."
        confirmLabel="Sync anyway"
        pending={act.isPending}
        onConfirm={() => perform("sync-anyway")}
      />
    </div>
  );
}

function BackLink() {
  return (
    <Link
      to="/pipeline"
      className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
    >
      <IconArrowLeft className="size-3.5" />
      Pipeline
    </Link>
  );
}

/** One sentence on where the sync stands, in the state's colour. */
function StateCallout({ run }: { run: RunDetail }) {
  const tone = runStateTone(run.state);
  const sentence = isLiveState(run.state)
    ? run.current_summary
    : run.outcome_message || run.current_summary;
  if (!sentence) return null;
  const next =
    run.state === "waiting" && run.next_check_at
      ? `Next step at ${clockText(run.next_check_at)}.`
      : "";
  return (
    <div className={cn("rounded-xl border px-4 py-3 text-sm text-pretty", TONE_BADGE[tone])}>
      <span className="font-semibold">{run.state_label}.</span> {sentence}
      {next && <span className="ml-1 opacity-80">{next}</span>}
    </div>
  );
}
