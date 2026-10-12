import { useState } from "react";
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
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { SectionCard } from "@/components/layout/section-card";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import { TransferStatusBadge } from "@/components/transfers/transfer-bits";
import { StatusBadge } from "@/components/webhooks/webhook-bits";
import { ActorBadge } from "@/components/activity/actor-badge";
import { AlertCard } from "@/components/pipeline/alert-card";
import { FactLine, KindBadge, RunStateBadge } from "@/components/pipeline/pipeline-bits";
import { RunStages } from "@/components/pipeline/run-stages";
import {
  IconArrowBackUp,
  IconChevronRight,
  IconPlayerPlay,
  IconPlayerStop,
  IconShieldCheck,
} from "@tabler/icons-react";

const RELATION_LABEL: Record<string, string> = {
  follow_up: "Follow-up",
  retry: "Retry",
  follow_up_of: "Follows",
  retry_of: "Retries",
};

/**
 * One sync in a side panel over the Transfers page.
 *
 * This is where everything that points at a sync lands — an alert, a webhook,
 * the auto-scanner's card, a sync still waiting to start — whether or not it
 * ever became a copy. Beside the stages it carries what a transfer's row does
 * not: the webhooks linked to the sync, its alerts, and the syncs before and
 * after it.
 */
export function SyncSheet({
  runId,
  onClose,
  onOpenRun,
}: {
  runId: string | null;
  onClose: () => void;
  /** Show another sync in the panel: a related one, or the retry just started. */
  onOpenRun: (runId: string) => void;
}) {
  return (
    <Sheet open={Boolean(runId)} onOpenChange={(open) => !open && onClose()}>
      {/*
        The width carries the `data-[side=right]:` prefix the sheet's own
        defaults use; without it tailwind-merge keeps the base `w-3/4` and drops
        this one (see the Backups inspector for the long version).
      */}
      <SheetContent
        side="right"
        className="gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-2xl"
      >
        {runId && <SyncSheetBody key={runId} runId={runId} onOpenRun={onOpenRun} />}
      </SheetContent>
    </Sheet>
  );
}

function SyncSheetBody({
  runId,
  onOpenRun,
}: {
  runId: string;
  onOpenRun: (runId: string) => void;
}) {
  const runQuery = useSyncRun(runId);
  const run = runQuery.data;

  if (runQuery.isLoading) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <SheetTitle className="sr-only">Loading the sync</SheetTitle>
        <Skeleton className="h-7 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-72 w-full" />
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
      <div className="flex flex-col gap-3 p-4 pr-12">
        <SheetTitle>{missing ? "No such sync" : "Could not load this sync"}</SheetTitle>
        <p className="text-sm text-muted-foreground">
          {missing
            ? "It may have been a rehearsal that was cleaned up."
            : errorText(runQuery.error, "The server did not answer.")}
        </p>
        {!missing && (
          <Button variant="outline" className="self-start" onClick={() => runQuery.refetch()}>
            Try again
          </Button>
        )}
      </div>
    );
  }

  return <SyncDetail run={run} onOpenRun={onOpenRun} />;
}

function SyncDetail({ run, onOpenRun }: { run: RunDetail; onOpenRun: (runId: string) => void }) {
  const act = useSyncRunAction();
  const restart = useRestartTransfer();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState<"cancel" | "sync-anyway" | null>(null);

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
      // The retry is a sync of its own; follow it rather than leave this
      // finished one on screen offering Retry again.
      if (result.run_id && result.run_id !== run.run_id) onOpenRun(result.run_id);
    } catch (error) {
      toast.error(
        error instanceof Error && error.message ? error.message : "Could not restart it."
      );
    }
  };

  const busy = act.isPending || restart.isPending;
  const hasActions = ["go_now", "sync_anyway", "restart", "cancel"].some((action) =>
    run.actions.includes(action)
  );

  return (
    <>
      <SheetHeader className="gap-2 border-b border-border px-4 py-3 pr-12">
        <SheetTitle className="text-base break-words">{run.label}</SheetTitle>
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
        {hasActions && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {run.actions.includes("go_now") && (
              <Button
                size="sm"
                className="border-0 bg-brand-gradient-x text-white"
                disabled={busy}
                onClick={() => perform("go-now")}
              >
                <IconPlayerPlay className="mr-1.5 size-3.5" />
                {run.state === "held" ? "Sync now" : "Go now"}
              </Button>
            )}
            {run.actions.includes("sync_anyway") && (
              <Button
                size="sm"
                variant="outline"
                className="border-amber-500/40 text-amber-300 hover:bg-amber-500/10"
                disabled={busy}
                onClick={() => setConfirm("sync-anyway")}
              >
                <IconShieldCheck className="mr-1.5 size-3.5" />
                Sync anyway
              </Button>
            )}
            {run.actions.includes("restart") && (
              <Button
                size="sm"
                className="border-0 bg-brand-gradient-x text-white"
                disabled={busy}
                onClick={retry}
              >
                <IconArrowBackUp className="mr-1.5 size-3.5" />
                Retry
              </Button>
            )}
            {run.actions.includes("cancel") && (
              <Button
                size="sm"
                variant="ghost"
                className="text-muted-foreground hover:bg-destructive/12 hover:text-destructive"
                disabled={busy}
                onClick={() => setConfirm("cancel")}
              >
                <IconPlayerStop className="mr-1.5 size-3.5" />
                Cancel
              </Button>
            )}
          </div>
        )}
      </SheetHeader>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <StateCallout run={run} />

        {run.alerts.length > 0 && (
          <div className="flex flex-col gap-2">
            {run.alerts.map((alert) => (
              <AlertCard key={alert.alert_id} alert={alert} showRunLink={false} />
            ))}
          </div>
        )}

        <RunStages run={run} />

        <SectionCard label={`Webhooks linked · ${run.webhooks.length}`}>
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
              No webhook is linked to this sync — it was started{" "}
              {run.kind === "auto_scanner" ? "by the auto-scanner" : "by hand"}.
            </p>
          )}
        </SectionCard>

        {run.transfer && (
          <SectionCard label="Its transfer" contentClassName="flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
                {run.transfer.transfer_id}
              </span>
              <TransferStatusBadge status={run.transfer.status} size="sm" />
            </div>
            {run.transfer.progress && (
              <p className="text-xs break-words text-muted-foreground">{run.transfer.progress}</p>
            )}
          </SectionCard>
        )}

        {run.related.length > 0 && (
          <SectionCard label="Related syncs">
            <ul className="divide-y divide-border/70">
              {run.related.map((other) => (
                <li key={other.run_id}>
                  <button
                    type="button"
                    onClick={() => onOpenRun(other.run_id)}
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-muted/40"
                  >
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-foreground">
                          {RELATION_LABEL[other.relation] ?? other.relation}
                        </span>
                        <RunStateBadge state={other.state} label={other.state_label} />
                      </span>
                      <span className="font-mono text-[10.5px] text-muted-foreground">
                        {other.run_id} · {sinceText(other.created_at)}
                      </span>
                    </span>
                    <IconChevronRight className="size-4 shrink-0 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          </SectionCard>
        )}
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
    </>
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
