import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { errorText } from "@/lib/api-error";
import { sinceText, TONE_BADGE, type PipelineTone } from "@/lib/pipeline";
import type { Alert } from "@/lib/sync-types";
import { useAlertAction } from "@/hooks/useSync";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import {
  IconAlertTriangle,
  IconArrowRight,
  IconBellRinging,
  IconCircleCheck,
  IconShieldExclamation,
} from "@tabler/icons-react";

const SEVERITY_TONE: Record<string, PipelineTone> = {
  failure: "crit",
  warning: "warn",
  info: "brand",
};

/** Actions that settle the matter rather than just closing the alert. */
const DOING_ACTIONS = new Set(["sync_now", "retry", "sync_anyway", "run_now"]);

const CLOSED_AS: Record<string, string> = {
  done: "Closed as done",
  wrong: "Marked as wrong",
  dismissed: "Dismissed",
};

/**
 * One thing that needs a person, with the actions that fit it.
 *
 * The buttons come from the alert itself, so an "After a restart" alert offers
 * Sync now / Mark as done / Mark as wrong / Dismiss and a failed transfer
 * offers Retry — the screen does not decide what can be done about what.
 */
export function AlertCard({ alert, showRunLink = true }: { alert: Alert; showRunLink?: boolean }) {
  const act = useAlertAction();
  const [confirmAnyway, setConfirmAnyway] = useState(false);
  const tone = SEVERITY_TONE[alert.severity] ?? "warn";
  const open = alert.state === "open";
  const Glyph =
    alert.kind === "sync_refused"
      ? IconShieldExclamation
      : tone === "brand"
        ? IconBellRinging
        : IconAlertTriangle;

  const run = async (action: string) => {
    try {
      const result = await act.mutateAsync({ alertId: alert.alert_id, action });
      toast.success(result.message || "Done.");
    } catch (error) {
      toast.error(errorText(error, "That did not work."));
    }
  };

  return (
    <article
      className={cn(
        "flex gap-3 rounded-xl border bg-card px-4 py-3.5",
        open ? "border-border" : "border-border/60 opacity-80"
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border",
          open ? TONE_BADGE[tone] : TONE_BADGE.muted
        )}
      >
        {open ? <Glyph className="size-4" /> : <IconCircleCheck className="size-4" />}
      </span>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <h3 className="min-w-0 text-sm font-semibold break-words text-foreground">
            {alert.title}
          </h3>
          <span className="flex shrink-0 items-center gap-1.5">
            {alert.occurrences > 1 && (
              <span
                className="rounded-full border border-border bg-black/30 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                title={`Raised ${alert.occurrences} times`}
              >
                ×{alert.occurrences}
              </span>
            )}
            <span className="rounded-[5px] border border-border bg-black/30 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
              {alert.kind_label}
            </span>
          </span>
        </div>

        {alert.message && (
          <p className="text-[13px] text-pretty whitespace-pre-line text-muted-foreground">
            {alert.message}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {open &&
            alert.action_buttons.map((button) => {
              const doing = DOING_ACTIONS.has(button.id);
              return (
                <Button
                  key={button.id}
                  size="sm"
                  variant={doing ? "default" : button.id === "dismiss" ? "ghost" : "outline"}
                  className={cn(doing && "border-0 bg-brand-gradient-x text-white")}
                  disabled={act.isPending}
                  onClick={() =>
                    button.id === "sync_anyway" ? setConfirmAnyway(true) : run(button.id)
                  }
                >
                  {button.label}
                </Button>
              );
            })}

          {showRunLink && alert.run_id && (
            <Link
              to="/transfers"
              search={{ sync: alert.run_id }}
              className="inline-flex items-center gap-1 text-xs font-medium text-brand-hover hover:underline"
            >
              Open the sync
              <IconArrowRight className="size-3.5" />
            </Link>
          )}

          <span className="ml-auto font-mono text-[10.5px] text-muted-foreground">
            {open
              ? sinceText(alert.updated_at)
              : `${CLOSED_AS[alert.state] ?? "Closed"}${
                  alert.resolved_by_name && alert.resolved_by_name !== "system"
                    ? ` by ${alert.resolved_by_name}`
                    : ""
                } · ${sinceText(alert.resolved_at)}`}
          </span>
        </div>
      </div>

      <ConfirmDialog
        open={confirmAnyway}
        onOpenChange={setConfirmAnyway}
        title="Sync despite the safety check?"
        description="The dry run said this sync could lose files. Going ahead copies it anyway, and anything rsync replaces is kept in the backup area."
        confirmLabel="Sync anyway"
        pending={act.isPending}
        onConfirm={() => run("sync_anyway")}
      />
    </article>
  );
}
