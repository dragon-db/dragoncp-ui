import { useMemo, useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FilenameDiff } from "@/components/webhooks/filename-diff";
import { episodeTagOf } from "@/lib/rename-diff";
import { timeAgo } from "@/lib/webhook-grouping";
import type { RenameVerificationResult } from "@/lib/api-types";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconCircleX,
  IconCopy,
  IconFileCheck,
  IconHistory,
  IconQuestionMark,
  IconShieldCheck,
  IconShieldX,
} from "@tabler/icons-react";

/**
 * Verification asks one question per file: is the renamed file on this machine
 * under its new name? The answer has three useful shapes — it is (verified), the
 * old name is still there (the rename never reached this machine), or neither
 * name is on disk. Grouping by that, rather than by pass/fail, is what tells you
 * whether to re-sync or go looking.
 */

type Outcome = "verified" | "stale" | "missing" | "blocked";

interface VerifiedFile {
  outcome: Outcome;
  previousName?: string;
  expectedName?: string;
  actualName?: string | null;
  actualPath?: string | null;
  expectedPath?: string | null;
  message?: string;
}

const OUTCOME: Record<
  Outcome,
  { label: string; badge: string; icon: typeof IconCircleCheck; hint: string }
> = {
  verified: {
    label: "Verified",
    badge: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
    icon: IconCircleCheck,
    hint: "on disk under the new name",
  },
  stale: {
    label: "Old name",
    badge: "border-amber-500/40 bg-amber-500/15 text-amber-400",
    icon: IconHistory,
    hint: "still the previous filename — re-sync this season",
  },
  missing: {
    label: "Missing",
    badge: "border-rose-500/40 bg-rose-500/15 text-rose-400",
    icon: IconQuestionMark,
    hint: "neither name found on this machine",
  },
  blocked: {
    label: "Blocked",
    badge: "border-rose-500/40 bg-rose-500/15 text-rose-400",
    icon: IconShieldX,
    hint: "path rejected before it was checked",
  },
};

function classify(file: RenameVerificationResult["files"][number]): Outcome {
  if (file.status === "verified") return "verified";
  if (file.message?.toLowerCase().includes("traversal")) return "blocked";
  if (file.actual_path) return "stale";
  return "missing";
}

type Filter = "all" | Outcome;

export function RenameVerifyReport({ result }: { result: RenameVerificationResult }) {
  const [filter, setFilter] = useState<Filter>("all");

  const files: VerifiedFile[] = useMemo(
    () =>
      (result.files ?? []).map((file) => ({
        outcome: classify(file),
        previousName: file.previous_name,
        expectedName: file.expected_name,
        actualName: file.actual_name,
        actualPath: file.actual_path,
        expectedPath: file.local_expected_path,
        message: file.message,
      })),
    [result.files]
  );

  const counts = useMemo(() => {
    const tally: Record<Outcome, number> = { verified: 0, stale: 0, missing: 0, blocked: 0 };
    for (const file of files) tally[file.outcome] += 1;
    return tally;
  }, [files]);

  const tone =
    result.status === "verified"
      ? {
          wrap: "border-emerald-500/35 bg-emerald-500/10",
          text: "text-emerald-300",
          icon: IconShieldCheck,
          title: "Every file verified",
        }
      : result.status === "partial"
        ? {
            wrap: "border-amber-500/35 bg-amber-500/10",
            text: "text-amber-400",
            icon: IconAlertTriangle,
            title: "Some files not verified",
          }
        : {
            wrap: "border-rose-500/35 bg-rose-500/10",
            text: "text-rose-400",
            icon: IconCircleX,
            title: result.status === "not_found" ? "Nothing to verify" : "No files verified",
          };
  const ToneIcon = tone.icon;

  const filters: Array<{ value: Filter; label: string; count: number }> = [
    { value: "all", label: "All", count: files.length },
    { value: "verified", label: "Verified", count: counts.verified },
    { value: "stale", label: "Old name", count: counts.stale },
    { value: "missing", label: "Missing", count: counts.missing + counts.blocked },
  ];

  const visible = files.filter((file) =>
    filter === "all"
      ? true
      : filter === "missing"
        ? file.outcome === "missing" || file.outcome === "blocked"
        : file.outcome === filter
  );

  const total = files.length || result.total_files || 0;
  const segments = [
    { key: "verified" as Outcome, count: counts.verified, className: "bg-emerald-400" },
    { key: "stale" as Outcome, count: counts.stale, className: "bg-amber-400" },
    {
      key: "missing" as Outcome,
      count: counts.missing + counts.blocked,
      className: "bg-rose-400",
    },
  ].filter((segment) => segment.count > 0);

  const copyJson = () => {
    navigator.clipboard
      .writeText(JSON.stringify(result, null, 2))
      .then(() => toast.success("JSON copied"))
      .catch(() => toast.error("Copy failed"));
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Verdict */}
      <div className={cn("flex gap-3 rounded-lg border px-3.5 py-3", tone.wrap)}>
        <ToneIcon className={cn("mt-0.5 size-5 shrink-0", tone.text)} />
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("text-sm font-semibold", tone.text)}>{tone.title}</span>
            {result.verified_at && (
              <span className="text-[11px] text-muted-foreground">
                checked {timeAgo(result.verified_at) || "just now"}
              </span>
            )}
          </div>
          <p className="text-[13px] text-foreground">{result.message}</p>
        </div>
      </div>

      {/* Numbers */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Files checked" value={total} icon={IconFileCheck} />
        <Stat label="Verified" value={counts.verified} tone="good" icon={IconCircleCheck} />
        <Stat
          label="Old name"
          value={counts.stale}
          tone={counts.stale ? "warn" : "default"}
          icon={IconHistory}
        />
        <Stat
          label="Missing"
          value={counts.missing + counts.blocked}
          tone={counts.missing + counts.blocked ? "bad" : "default"}
          icon={IconQuestionMark}
        />
      </div>

      {segments.length > 0 && (
        <div className="flex h-2 overflow-hidden rounded-full border border-border bg-black/30">
          {segments.map((segment) => (
            <div
              key={segment.key}
              className={cn("h-full", segment.className)}
              style={{ width: `${(segment.count / total) * 100}%` }}
              title={`${OUTCOME[segment.key].label}: ${segment.count}`}
            />
          ))}
        </div>
      )}

      {/* Files */}
      {files.length > 0 ? (
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-1.5">
            {filters.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setFilter(option.value)}
                className={cn(
                  "rounded-md border px-2 py-1 text-[11px] font-medium transition-colors",
                  filter === option.value
                    ? "border-brand/50 bg-brand/15 text-brand-foreground"
                    : "border-border bg-card/40 text-muted-foreground hover:text-foreground"
                )}
              >
                {option.label}
                <span className="ml-1 font-mono text-[10px] opacity-70">{option.count}</span>
              </button>
            ))}
          </div>

          <div className="flex max-h-[46vh] flex-col gap-2 overflow-y-auto pr-1">
            {visible.map((file, index) => {
              const meta = OUTCOME[file.outcome];
              const OutcomeIcon = meta.icon;
              const episode = episodeTagOf(file.expectedName || file.previousName);
              return (
                <div
                  key={`${index}-${file.expectedName ?? file.previousName}`}
                  className="flex flex-col gap-2 rounded-lg border border-border bg-card/50 p-2.5"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-bold tracking-wide uppercase",
                        meta.badge
                      )}
                    >
                      <OutcomeIcon className="size-2.5" />
                      {meta.label}
                    </span>
                    {episode && (
                      <span className="font-mono text-[11px] font-semibold text-brand-hover">
                        {episode}
                      </span>
                    )}
                    <span className="text-[11px] text-muted-foreground">{meta.hint}</span>
                  </div>

                  <FilenameDiff before={file.previousName} after={file.expectedName} />

                  {file.outcome !== "verified" && (
                    <p className="font-mono text-[10.5px] break-all text-muted-foreground">
                      {file.actualPath
                        ? `on disk: ${file.actualPath}`
                        : file.expectedPath
                          ? `looked for: ${file.expectedPath}`
                          : file.message}
                    </p>
                  )}
                </div>
              );
            })}
            {!visible.length && (
              <p className="px-1 py-4 text-center text-xs text-muted-foreground">
                No files in this group.
              </p>
            )}
          </div>
        </div>
      ) : (
        <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
          This run recorded no files to verify.
        </p>
      )}

      <Accordion className="flex flex-col gap-1.5">
        <AccordionItem
          value="json"
          className="overflow-hidden rounded-lg border border-border bg-card/50"
        >
          <AccordionTrigger className="px-3 py-2 text-[12px] no-underline hover:bg-muted/40 hover:no-underline">
            JSON payload
          </AccordionTrigger>
          <AccordionContent className="border-t border-border bg-black/20 px-3 py-3">
            <div className="flex flex-col gap-2">
              <Button variant="outline" size="sm" className="self-start" onClick={copyJson}>
                <IconCopy className="mr-1.5 size-3.5" />
                Copy JSON
              </Button>
              <pre className="max-h-[320px] overflow-auto rounded-md border border-border bg-background/60 p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted-foreground">
                {JSON.stringify(result, null, 2)}
              </pre>
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "default",
  icon: Icon,
}: {
  label: string;
  value: number;
  tone?: "default" | "good" | "warn" | "bad";
  icon: typeof IconCircleCheck;
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-300"
      : tone === "warn"
        ? "text-amber-400"
        : tone === "bad"
          ? "text-rose-400"
          : "text-foreground";
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card/60 px-3 py-2.5">
      <span className="flex items-center gap-1.5 text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        <Icon className="size-3" />
        {label}
      </span>
      <span className={cn("font-mono text-lg leading-none font-semibold", toneClass)}>{value}</span>
    </div>
  );
}

/** Dialog wrapper, matching the dry-run report's shell. */
export function RenameVerifyDialog({
  result,
  open,
  onOpenChange,
}: {
  result: RenameVerificationResult | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[88vh] flex-col overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Rename verification</DialogTitle>
          <DialogDescription>
            {result?.series_title
              ? `${result.series_title} — expected names checked against this machine`
              : "Expected names checked against this machine"}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {result ? (
            <RenameVerifyReport result={result} />
          ) : (
            <p className="py-6 text-center text-xs text-muted-foreground">
              No verification output.
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
