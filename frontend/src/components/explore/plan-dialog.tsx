import { useState } from "react";
import {
  IconAlertTriangle,
  IconArrowDown,
  IconCheck,
  IconRefresh,
  IconTestPipe,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/lib/explore-format";
import type { ExploreDryRunReport, ExplorePlan, ExplorePlanGroup } from "@/lib/explore-types";

/**
 * The review step. Nothing that can remove or overwrite a local file runs
 * without passing through here, and the confirmation is bound to the plan the
 * server computed — not to whatever the page happened to be showing.
 *
 * A series plan is one decision, grouped by season, with the seasons that lose
 * files at the top.
 */

interface PlanDialogProps {
  open: boolean;
  plan: ExplorePlan | null;
  loading: boolean;
  error: string | null;
  submitting: boolean;
  dryRun: ExploreDryRunReport | null;
  dryRunLoading: boolean;
  dryRunError: string | null;
  onDryRun: () => void;
  onOpenChange: (open: boolean) => void;
  onConfirm: (override: boolean, confirmText: string) => void;
}

export function PlanDialog({
  open,
  plan,
  loading,
  error,
  submitting,
  dryRun,
  dryRunLoading,
  dryRunError,
  onDryRun,
  onOpenChange,
  onConfirm,
}: PlanDialogProps) {
  // Tied to the plan it was typed for, so a new plan starts empty without an
  // effect resetting state on every open.
  const [typed, setTyped] = useState<{ planId: string | null; text: string }>({
    planId: null,
    text: "",
  });
  const confirmText = typed.planId === plan?.plan_id ? typed.text : "";
  const setConfirmText = (text: string) => setTyped({ planId: plan?.plan_id ?? null, text });

  const needsOverride = Boolean(plan && !plan.safe);
  const expected = plan?.season_label || plan?.series || "";
  const canConfirm =
    Boolean(plan) && !plan!.is_empty && (!needsOverride || confirmText.trim() === expected);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Review before it runs</DialogTitle>
          <DialogDescription>
            {plan
              ? `${plan.series}${plan.season_label ? ` · ${plan.season_label}` : ""}`
              : "Working out what this would do…"}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex flex-col gap-3 py-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : error ? (
          <p className="rounded-md border border-rose-500/35 bg-rose-500/10 p-3 text-sm text-rose-200">
            {error}
          </p>
        ) : plan ? (
          <>
            <div
              className={cn(
                "flex items-start gap-3 rounded-lg border p-3",
                plan.is_empty
                  ? "border-border bg-muted/40"
                  : plan.safe
                    ? "border-emerald-500/30 bg-emerald-500/8"
                    : "border-amber-500/40 bg-amber-500/10"
              )}
            >
              {plan.safe ? (
                <IconCheck className="mt-0.5 size-5 flex-none text-emerald-400" />
              ) : (
                <IconAlertTriangle className="mt-0.5 size-5 flex-none text-amber-400" />
              )}
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">{plan.verdict}</p>
                <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                  {formatBytes(plan.counts.incoming_bytes)} to download
                  {plan.counts.backup_bytes > 0 &&
                    ` · ${formatBytes(plan.counts.backup_bytes)} moved to backup`}
                </p>
              </div>
            </div>

            {plan.warnings.map((warning) => (
              <p key={warning} className="text-[12px] text-muted-foreground">
                {warning}
              </p>
            ))}

            {/* A plain overflow container, not ScrollArea: the dialog is sized
                by max-height alone, so ScrollArea's `height: 100%` viewport has
                nothing definite to resolve against and grows to its content —
                the list then runs behind the footer instead of scrolling. */}
            <div className="min-h-0 flex-1 overflow-y-auto pr-3">
              <div className="flex flex-col gap-3">
                <DryRunCard
                  report={dryRun}
                  loading={dryRunLoading}
                  error={dryRunError}
                  disabled={plan.is_empty}
                  onRun={onDryRun}
                />

                {plan.groups.map((group) => (
                  <PlanGroupCard key={group.season_label || "all"} group={group} />
                ))}

                <div className="rounded-lg border border-border">
                  <p className="border-b border-border px-3 py-2 font-mono text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                    Safety checks
                  </p>
                  <ul className="divide-y divide-border/60">
                    {plan.checks.map((check) => (
                      <li key={check.id} className="flex items-start gap-2.5 px-3 py-2">
                        {check.passed ? (
                          <IconCheck className="mt-0.5 size-3.5 flex-none text-emerald-400" />
                        ) : (
                          <IconX className="mt-0.5 size-3.5 flex-none text-rose-400" />
                        )}
                        <span className="min-w-0">
                          <span className="block text-[12.5px] text-foreground">{check.label}</span>
                          <span className="block font-mono text-[10.5px] text-muted-foreground">
                            {check.detail}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            {needsOverride && !plan.is_empty && (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/8 p-3">
                <p className="text-[12.5px] text-amber-100">
                  This did not pass its checks. To run it anyway, type{" "}
                  <span className="font-mono font-semibold">{expected}</span> below. Everything
                  removed is moved to backup and can be restored.
                </p>
                <Input
                  value={confirmText}
                  onChange={(event) => setConfirmText(event.target.value)}
                  placeholder={expected}
                  className="mt-2 h-8"
                />
              </div>
            )}
          </>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!canConfirm || submitting}
            onClick={() => onConfirm(needsOverride, confirmText.trim())}
          >
            {submitting ? (
              <>
                <IconRefresh className="mr-2 size-4 animate-spin" />
                Starting…
              </>
            ) : plan?.is_empty ? (
              "Nothing to do"
            ) : (
              "Start transfer"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The rehearsal.
 *
 * The plan above is worked out by comparing two file listings. This asks rsync
 * itself, with `--dry-run`, and shows what it says — so a plan built on a stale
 * or wrong reading of the remote is caught here rather than mid-transfer.
 */
function DryRunCard({
  report,
  loading,
  error,
  disabled,
  onRun,
}: {
  report: ExploreDryRunReport | null;
  loading: boolean;
  error: string | null;
  disabled: boolean;
  onRun: () => void;
}) {
  const disagreements = report?.warnings ?? [];
  const failed = report ? !report.ok : false;

  return (
    <div
      className={cn(
        "rounded-lg border",
        failed
          ? "border-rose-500/40 bg-rose-500/8"
          : disagreements.length
            ? "border-amber-500/40 bg-amber-500/6"
            : "border-border"
      )}
    >
      <div className="flex items-center gap-3 border-b border-border px-3 py-2">
        <IconTestPipe className="size-3.5 flex-none text-muted-foreground" />
        <span className="text-[13px] font-semibold text-foreground">Dry run</span>
        <Button
          size="sm"
          variant="outline"
          className="ml-auto h-6 px-2 text-[11px]"
          disabled={loading || disabled}
          onClick={onRun}
        >
          {loading ? (
            <>
              <IconRefresh className="mr-1.5 size-3 animate-spin" />
              Asking rsync…
            </>
          ) : report ? (
            "Run again"
          ) : (
            "Check with rsync"
          )}
        </Button>
      </div>

      <div className="px-3 py-2.5">
        {error ? (
          <p className="text-[12px] text-rose-200">{error}</p>
        ) : loading ? (
          <Skeleton className="h-10 w-full" />
        ) : !report ? (
          <p className="text-[12px] text-muted-foreground">
            {disabled
              ? "There is nothing to rehearse — this plan does nothing."
              : "Runs rsync against the remote without copying anything, and reports back what it would do. Nothing is moved and this plan stays runnable."}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            <p className="text-[12.5px] text-foreground">{report.verdict}</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10.5px] text-muted-foreground">
              <Stat label="download" value={report.summary.new} />
              <Stat label="replace" value={report.summary.replaced} />
              <Stat label="remove" value={report.summary.removed} />
              <Stat label="untouched" value={report.summary.unchanged} />
              <span>{formatBytes(report.summary.incoming_bytes)} in</span>
              {report.summary.backup_bytes + report.summary.removed_bytes > 0 && (
                <span>
                  {formatBytes(report.summary.backup_bytes + report.summary.removed_bytes)} to
                  backup
                </span>
              )}
            </div>

            {disagreements.map((warning) => (
              <p key={warning} className="flex items-start gap-1.5 text-[11.5px] text-amber-100/90">
                <IconAlertTriangle className="mt-0.5 size-3 flex-none text-amber-400" />
                {warning}
              </p>
            ))}

            {report.files.length > 0 && (
              <ul className="max-h-40 divide-y divide-border/50 overflow-y-auto rounded-md border border-border">
                {report.files.map((file, index) => (
                  <li
                    key={`${file.rel}-${index}`}
                    className="flex items-center gap-2 px-2.5 py-1 text-[11.5px]"
                  >
                    <span
                      className={cn(
                        "w-[68px] flex-none font-mono text-[9.5px] tracking-[0.08em] uppercase",
                        file.change === "new" && "text-amber-400",
                        file.change === "replaced" && "text-brand-hover",
                        file.change === "deleted" && "text-rose-300",
                        (file.change === "unchanged" || file.change === "directory") &&
                          "text-muted-foreground"
                      )}
                    >
                      {file.change}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-foreground">
                      {shortName(file.rel)}
                    </span>
                    <span className="flex-none font-mono text-[10px] text-muted-foreground">
                      {formatBytes(file.size)}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {report.raw_tail && (
              <details className="text-[11px]">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                  What rsync printed
                </summary>
                <pre className="mt-1.5 max-h-40 overflow-auto rounded-md border border-border bg-well p-2 font-mono text-[10px] leading-[15px] whitespace-pre-wrap text-foreground-3">
                  {report.raw_tail}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  if (!value) return null;
  return (
    <span>
      <span className="text-foreground">{value}</span> {label}
    </span>
  );
}

function PlanGroupCard({ group }: { group: ExplorePlanGroup }) {
  const dangerous = group.remove > 0;
  return (
    <div
      className={cn(
        "rounded-lg border",
        dangerous ? "border-amber-500/40 bg-amber-500/6" : "border-border"
      )}
    >
      <div className="flex items-center gap-3 border-b border-border px-3 py-2">
        <span className="text-[13px] font-semibold text-foreground">
          {group.season_label || "This folder"}
        </span>
        <span className="ml-auto flex items-center gap-3 font-mono text-[10.5px]">
          {group.fetch > 0 && <span className="text-amber-400">{group.fetch} download</span>}
          {group.supersede > 0 && (
            <span className="text-brand-foreground">{group.supersede} replace</span>
          )}
          {group.remove > 0 && <span className="text-rose-300">{group.remove} remove</span>}
        </span>
      </div>
      <ul className="max-h-56 divide-y divide-border/50 overflow-y-auto">
        {group.actions.map((action, index) => (
          <li
            key={`${action.rel || action.local_rel}-${index}`}
            className="flex items-start gap-2.5 px-3 py-1.5"
          >
            {action.action === "fetch" && (
              <IconArrowDown className="mt-0.5 size-3.5 flex-none text-amber-400" />
            )}
            {action.action === "supersede" && (
              <IconRefresh className="mt-0.5 size-3.5 flex-none text-brand-hover" />
            )}
            {action.action === "remove" && (
              <IconTrash className="mt-0.5 size-3.5 flex-none text-rose-400" />
            )}
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                {/* A movie has no episode number, so its "code" is the filename.
                    Printing that as a code chip repeats the name beside it. */}
                {isEpisodeCode(action.code) && (
                  <span className="flex-none font-mono text-[10.5px] font-semibold text-brand-hover">
                    {action.code}
                  </span>
                )}
                <span className="min-w-0 truncate text-[12px] text-foreground">
                  {action.rel ? shortName(action.rel) : shortName(action.local_rel ?? "")}
                </span>
              </span>
              {action.action === "supersede" && action.local_rel && (
                <span className="block truncate font-mono text-[10px] text-muted-foreground">
                  replaces {shortName(action.local_rel)} → backup
                </span>
              )}
              {action.action === "remove" && (
                <span className="block font-mono text-[10px] text-muted-foreground">
                  {action.reason} → backup
                </span>
              )}
            </span>
            <span className="flex-none font-mono text-[10.5px] text-muted-foreground">
              {formatBytes(action.size || action.local_size)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function shortName(rel: string): string {
  const parts = rel.split("/");
  return parts[parts.length - 1] || rel;
}

/** `S02E07`, `S00E13` — anything else is a filename standing in for one. */
function isEpisodeCode(code: string): boolean {
  return /^S\d+E\d+$/i.test(code);
}
