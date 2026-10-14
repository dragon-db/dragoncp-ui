import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { errorText } from "@/lib/api-error";
import { clockText, formatSpan, sinceText } from "@/lib/pipeline";
import { useRunJob, useSchedulerJobs } from "@/hooks/useSync";
import { SectionCard } from "@/components/layout/section-card";
import { Button } from "@/components/ui/button";
import { IconAlertTriangle, IconCheck, IconLoader2, IconRadar } from "@tabler/icons-react";

interface ScanDecision {
  action: string;
  run_id: string | null;
  detail?: string;
  find: { label?: string; reasons?: string[] };
}

const ACTION_LABEL: Record<string, string> = {
  started: "Started a sync",
  already_on_its_way: "Already on its way",
  held_back: "Held back for the next scan",
  needs_a_person: "Waiting for a person",
  failed: "Could not start",
};

/**
 * The scheduled auto-scanner for one service: whether it is on, when it last
 * looked and what it found, and when it looks next. The switch itself is the
 * form above, because it is one of the connector's settings; this is what the
 * switch is doing.
 */
export function ScannerStatus({
  source,
  displayName,
  connectorEnabled,
}: {
  source: string;
  displayName: string;
  connectorEnabled: boolean;
}) {
  const jobs = useSchedulerJobs();
  const runJob = useRunJob();
  const job = jobs.data?.find((item) => item.name === `${source}_auto_scanner`);
  if (!job) return null;

  const result = job.last_result ?? {};
  const decisions = (Array.isArray(result.decisions) ? result.decisions : []) as ScanDecision[];

  const scanNow = async () => {
    try {
      const answer = await runJob.mutateAsync(job.name);
      toast.success(
        answer.message === "Started." ? `Scanning ${displayName} now.` : answer.message
      );
    } catch (error) {
      toast.error(errorText(error, "Could not start the scan."));
    }
  };

  return (
    <SectionCard
      label="Auto-scanner"
      description={job.description}
      actions={
        job.enabled ? (
          <Button
            size="sm"
            variant="outline"
            disabled={job.running || runJob.isPending}
            onClick={scanNow}
          >
            {job.running ? (
              <IconLoader2 className="mr-1.5 size-3.5 animate-spin" />
            ) : (
              <IconRadar className="mr-1.5 size-3.5" />
            )}
            {job.running ? "Scanning…" : "Scan now"}
          </Button>
        ) : undefined
      }
      contentClassName="flex flex-col gap-3 px-4 py-3"
    >
      {!job.enabled ? (
        <p className="text-sm text-muted-foreground">
          {connectorEnabled ? (
            <>
              Switched off. Turn on <span className="text-foreground">Scheduled auto-scanner</span>{" "}
              above and save to have {displayName} checked for anything a webhook never delivered.
            </>
          ) : (
            <>
              {displayName} is turned off, so the auto-scanner cannot ask it anything. Turn{" "}
              {displayName} on at the top of this page, then switch the scanner on above.
            </>
          )}
        </p>
      ) : (
        <p className="text-sm text-foreground/85">
          Every {formatSpan(job.interval_seconds ?? 0)}
          {job.next_run_at && <> · next scan at {clockText(job.next_run_at)}</>}
        </p>
      )}

      {job.last_run_at && (
        <div
          className={cn(
            "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
            job.last_ok === false
              ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
              : "border-border bg-background/50 text-muted-foreground"
          )}
        >
          {job.last_ok === false ? (
            <IconAlertTriangle className="mt-px size-3.5 shrink-0" />
          ) : (
            <IconCheck className="mt-px size-3.5 shrink-0 text-emerald-400" />
          )}
          <span>
            <span className="font-semibold text-foreground/90">
              Last scan {sinceText(job.last_run_at)}:
            </span>{" "}
            {String(result.summary ?? (job.last_ok ? "Finished." : "Failed."))}
            {job.consecutive_failures > 1 && ` Failed ${job.consecutive_failures} times in a row.`}
          </span>
        </div>
      )}

      {decisions.length > 0 && (
        <ul className="flex flex-col divide-y divide-border/70 rounded-lg border border-border">
          {decisions.slice(0, 8).map((decision, index) => (
            <li key={index} className="flex flex-col gap-0.5 px-3 py-2">
              <span className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-semibold text-foreground">
                  {decision.find.label ?? "A title"}
                </span>
                {decision.run_id && decision.action === "started" ? (
                  <Link
                    to="/transfers"
                    search={{ sync: decision.run_id }}
                    className="text-[11px] font-medium text-brand-hover hover:underline"
                  >
                    {ACTION_LABEL[decision.action]} →
                  </Link>
                ) : (
                  <span className="text-[11px] text-muted-foreground">
                    {ACTION_LABEL[decision.action] ?? decision.action}
                  </span>
                )}
              </span>
              {decision.find.reasons?.[0] && (
                <span className="text-[11.5px] text-muted-foreground">
                  {decision.find.reasons[0]}
                </span>
              )}
            </li>
          ))}
          {decisions.length > 8 && (
            <li className="px-3 py-2 text-[11px] text-muted-foreground">
              and {decisions.length - 8} more in the activity trail
            </li>
          )}
        </ul>
      )}
    </SectionCard>
  );
}
