import { useMemo, useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import {
  IconAlertTriangle,
  IconCheck,
  IconChevronDown,
  IconCircleCheck,
  IconCircleX,
  IconCopy,
  IconDownload,
  IconFolder,
  IconLink,
  IconRefresh,
  IconSearch,
  IconServer,
  IconShieldCheck,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import {
  formatBytes,
  formatDuration,
  formatNumber,
  parseDryRun,
  type ChangeKind,
  type DryRunEntry,
  type DryRunReport,
} from "@/lib/dry-run";
import { timeAgo } from "@/lib/webhook-grouping";

/**
 * Presentation for a parsed rsync dry-run. The raw payload is JSON wrapped
 * around a few thousand characters of rsync stdout; everything here exists to
 * answer three questions without reading that text: is it safe, what exactly
 * changes, and what did rsync actually see.
 */

const CHANGE_META: Record<
  ChangeKind,
  { label: string; badge: string; dot: string; icon: typeof IconCheck }
> = {
  new: {
    label: "New",
    badge: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
    dot: "bg-emerald-400",
    icon: IconDownload,
  },
  update: {
    label: "Update",
    badge: "border-sky-500/40 bg-sky-500/15 text-sky-300",
    dot: "bg-sky-400",
    icon: IconRefresh,
  },
  unchanged: {
    label: "In sync",
    badge: "border-border bg-black/25 text-muted-foreground",
    dot: "bg-muted-foreground/60",
    icon: IconCheck,
  },
  delete: {
    label: "Delete",
    badge: "border-rose-500/40 bg-rose-500/15 text-rose-400",
    dot: "bg-rose-400",
    icon: IconTrash,
  },
};

type FileFilter = "all" | "incoming" | "unchanged" | "delete";

const FILE_FILTERS: Array<{
  value: FileFilter;
  label: string;
  match: (kind: ChangeKind) => boolean;
}> = [
  { value: "all", label: "All", match: () => true },
  { value: "incoming", label: "Incoming", match: (kind) => kind === "new" || kind === "update" },
  { value: "unchanged", label: "In sync", match: (kind) => kind === "unchanged" },
  { value: "delete", label: "Deleting", match: (kind) => kind === "delete" },
];

const PAGE_SIZE = 60;

function copyToClipboard(text: string, label: string) {
  // Absent over plain http on a LAN address, which is how this app is often reached.
  if (!navigator.clipboard) {
    toast.error("Copy failed");
    return;
  }
  navigator.clipboard
    .writeText(text)
    .then(() => toast.success(`${label} copied`))
    .catch(() => toast.error("Copy failed"));
}

function Stat({
  label,
  value,
  hint,
  tone = "default",
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "good" | "bad" | "brand";
  icon?: typeof IconCheck;
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-300"
      : tone === "bad"
        ? "text-rose-400"
        : tone === "brand"
          ? "text-brand-hover"
          : "text-foreground";
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card/60 px-3 py-2.5">
      <span className="flex items-center gap-1.5 text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        {Icon && <Icon className="size-3" />}
        {label}
      </span>
      <span className={cn("font-mono text-lg leading-none font-semibold", toneClass)}>{value}</span>
      {hint && <span className="text-[10.5px] text-muted-foreground">{hint}</span>}
    </div>
  );
}

/** Proportional bar of what the sync does to the folder, with a legend. */
function CompositionBar({ report }: { report: DryRunReport }) {
  const { incoming, deleted, unchanged } = report.counts;
  const total = incoming + deleted + unchanged;
  if (total === 0) return null;

  const segments = [
    { kind: "unchanged" as ChangeKind, count: unchanged },
    { kind: "new" as ChangeKind, count: incoming },
    { kind: "delete" as ChangeKind, count: deleted },
  ].filter((segment) => segment.count > 0);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-2 overflow-hidden rounded-full border border-border bg-black/30">
        {segments.map((segment) => (
          <div
            key={segment.kind}
            className={cn("h-full", CHANGE_META[segment.kind].dot)}
            style={{ width: `${(segment.count / total) * 100}%` }}
            title={`${CHANGE_META[segment.kind].label}: ${segment.count}`}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        {segments.map((segment) => (
          <span key={segment.kind} className="inline-flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", CHANGE_META[segment.kind].dot)} />
            {segment.count} {CHANGE_META[segment.kind].label.toLowerCase()}
          </span>
        ))}
      </div>
    </div>
  );
}

function EntryRow({ entry }: { entry: DryRunEntry }) {
  const meta = CHANGE_META[entry.change];
  const Icon = entry.kind === "dir" ? IconFolder : entry.kind === "link" ? IconLink : meta.icon;

  return (
    // Narrow screens put the release tags on their own line rather than hiding
    // them: everything rsync reported stays readable.
    <div
      className="flex flex-col gap-1 rounded-md border border-border/60 bg-card/40 px-2.5 py-1.5 sm:flex-row sm:items-center sm:gap-2.5"
      title={entry.path}
    >
      <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-bold tracking-wide uppercase",
            meta.badge
          )}
        >
          <Icon className="size-2.5" />
          {meta.label}
        </span>
        {entry.episode && (
          <span className="shrink-0 font-mono text-[11px] font-semibold text-brand-hover">
            {entry.episode}
          </span>
        )}
        <span className="min-w-0 text-[13px] break-words text-foreground sm:truncate">
          {entry.dir && <span className="text-muted-foreground">{entry.dir}/</span>}
          {entry.label}
        </span>
      </span>
      <span className="flex shrink-0 flex-wrap items-center gap-1.5">
        {entry.tags.slice(0, 2).map((tag) => (
          <span
            key={tag}
            className="rounded border border-border bg-black/25 px-1.5 py-px font-mono text-[10px] text-muted-foreground"
          >
            {tag}
          </span>
        ))}
        {entry.extension && (
          <span className="font-mono text-[10px] text-muted-foreground/70">.{entry.extension}</span>
        )}
      </span>
    </div>
  );
}

function FileBrowser({ report }: { report: DryRunReport }) {
  const [filter, setFilter] = useState<FileFilter>("all");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);

  const counts = useMemo(() => {
    const tally: Record<FileFilter, number> = { all: 0, incoming: 0, unchanged: 0, delete: 0 };
    for (const entry of report.entries) {
      for (const option of FILE_FILTERS) {
        if (option.match(entry.change)) tally[option.value] += 1;
      }
    }
    return tally;
  }, [report.entries]);

  const filtered = useMemo(() => {
    const option = FILE_FILTERS.find((item) => item.value === filter) ?? FILE_FILTERS[0];
    const needle = query.trim().toLowerCase();
    return report.entries.filter(
      (entry) =>
        option.match(entry.change) && (!needle || entry.path.toLowerCase().includes(needle))
    );
  }, [report.entries, filter, query]);

  if (!report.entries.length) {
    return (
      <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
        rsync listed no files for this path.
      </p>
    );
  }

  const visible = filtered.slice(0, limit);

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {FILE_FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                setFilter(option.value);
                setLimit(PAGE_SIZE);
              }}
              className={cn(
                "rounded-md border px-2 py-1 text-[11px] font-medium transition-colors",
                filter === option.value
                  ? "border-brand/50 bg-brand/15 text-brand-foreground"
                  : "border-border bg-card/40 text-muted-foreground hover:text-foreground"
              )}
            >
              {option.label}
              <span className="ml-1 font-mono text-[10px] opacity-70">{counts[option.value]}</span>
            </button>
          ))}
        </div>
        <div className="relative ml-auto w-full sm:w-56">
          <IconSearch className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setLimit(PAGE_SIZE);
            }}
            placeholder="Filter files"
            className="h-8 pl-7 text-xs"
          />
        </div>
      </div>

      <div className="flex max-h-[300px] flex-col gap-1 overflow-y-auto pr-1">
        {visible.map((entry) => (
          <EntryRow key={`${entry.change}:${entry.path}`} entry={entry} />
        ))}
        {!visible.length && (
          <p className="px-1 py-4 text-center text-xs text-muted-foreground">
            No files match “{query}”.
          </p>
        )}
      </div>

      {filtered.length > visible.length && (
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => setLimit((current) => current + PAGE_SIZE * 4)}
        >
          <IconChevronDown className="mr-1.5 size-3.5" />
          Show {filtered.length - visible.length} more
        </Button>
      )}
    </div>
  );
}

function StatsGrid({ report }: { report: DryRunReport }) {
  const { stats, connection } = report;

  const rows: Array<[string, string]> = [];
  const push = (label: string, value: string, when: unknown = true) => {
    if (when !== undefined && when !== null && when !== false) rows.push([label, value]);
  };

  push("Files in list", formatNumber(stats.totalFiles), stats.totalFiles);
  push(
    "Regular / directories",
    `${formatNumber(stats.regularFiles)} / ${formatNumber(stats.directories)}`,
    stats.regularFiles ?? stats.directories
  );
  push("Would create", formatNumber(stats.createdFiles), stats.createdFiles);
  push("Would delete", formatNumber(stats.deletedFiles), stats.deletedFiles);
  push("Files transferred", formatNumber(stats.transferredFiles), stats.transferredFiles);
  push("Total size on server", formatBytes(stats.totalSize), stats.totalSize);
  push("Data to transfer", formatBytes(stats.transferredSize), stats.transferredSize);
  push(
    "Literal / matched data",
    `${formatBytes(stats.literalData)} / ${formatBytes(stats.matchedData)}`,
    stats.literalData ?? stats.matchedData
  );
  push("File list size", formatBytes(stats.fileListSize), stats.fileListSize);
  push("File list generation", formatDuration(stats.fileListGenTime), stats.fileListGenTime);
  push(
    "Bytes sent / received",
    `${formatBytes(stats.bytesSent)} / ${formatBytes(stats.bytesReceived)}`,
    stats.bytesSent ?? stats.bytesReceived
  );
  push(
    "Speedup",
    stats.speedup ? `${formatNumber(Math.round(stats.speedup))}×` : "—",
    stats.speedup
  );

  if (!rows.length && !connection.remotePath) return null;

  return (
    <div className="flex flex-col gap-3">
      {(connection.remotePath || connection.host) && (
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
            Source
          </span>
          <div className="rounded-md border border-border bg-background/60 px-2.5 py-1.5 font-mono text-[11px] break-all text-foreground/80">
            {connection.user && connection.host ? `${connection.user}@${connection.host}:` : ""}
            {connection.remotePath ?? ""}
          </div>
        </div>
      )}
      {rows.length > 0 && (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {rows.map(([label, value]) => (
            <div
              key={label}
              className="flex items-baseline justify-between gap-3 border-b border-border/50 pb-1.5"
            >
              <dt className="text-[11.5px] text-muted-foreground">{label}</dt>
              <dd className="font-mono text-[12px] text-foreground">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
      {children}
    </span>
  );
}

/** The full report: verdict, numbers, per-file plan, rsync stats, raw output. */
export function DryRunReportView({
  payload,
  performedAt,
  className,
}: {
  payload: unknown;
  performedAt?: string;
  className?: string;
}) {
  const report = useMemo(() => parseDryRun(payload), [payload]);

  if (!report.ok) {
    return (
      <div className={cn("rounded-lg border border-border bg-card/60 px-3 py-6", className)}>
        <p className="text-center text-xs text-muted-foreground">
          No dry-run output available for this item.
        </p>
      </div>
    );
  }

  const tone = !report.completed
    ? {
        wrap: "border-rose-500/35 bg-rose-500/10",
        text: "text-rose-400",
        icon: IconCircleX,
        title: "Validation failed",
      }
    : report.safeToSync
      ? {
          wrap: "border-emerald-500/35 bg-emerald-500/10",
          text: "text-emerald-300",
          icon: IconShieldCheck,
          title: "Safe to sync",
        }
      : {
          wrap: "border-amber-500/35 bg-amber-500/10",
          text: "text-amber-400",
          icon: IconAlertTriangle,
          title: "Manual review required",
        };
  const ToneIcon = tone.icon;
  const hasErrors = report.messages.some((message) => message.level === "error");

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      {/* Verdict */}
      <div className={cn("flex gap-3 rounded-lg border px-3.5 py-3", tone.wrap)}>
        <ToneIcon className={cn("mt-0.5 size-5 shrink-0", tone.text)} />
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("text-sm font-semibold", tone.text)}>{tone.title}</span>
            {performedAt && (
              <span className="text-[11px] text-muted-foreground">
                validated {timeAgo(performedAt) || "just now"}
              </span>
            )}
          </div>
          {report.completed ? (
            <>
              <p className="text-[13px] text-foreground">{report.headline}.</p>
              <p className="text-[11.5px] text-muted-foreground">{report.reason}</p>
            </>
          ) : (
            <>
              <p className="text-[13px] text-foreground">{report.reason}.</p>
              <p className="text-[11.5px] text-muted-foreground">
                rsync never reported on this folder, so there are no file counts to show. Run the
                dry-run again once the server is reachable.
              </p>
            </>
          )}
        </div>
      </div>

      {report.completed && (
        <>
          {/* Numbers — the fifth tile fills the row on phones so the grid keeps a flush edge */}
          <div className="grid grid-cols-2 gap-2 *:last:col-span-2 sm:grid-cols-3 sm:*:last:col-span-1 md:grid-cols-5">
            <Stat
              label="Incoming"
              value={formatNumber(report.counts.incoming)}
              hint={
                report.stats.transferredSize
                  ? formatBytes(report.stats.transferredSize)
                  : "nothing to pull"
              }
              tone={report.counts.incoming > 0 ? "good" : "default"}
              icon={IconDownload}
            />
            <Stat
              label="Deleting"
              value={formatNumber(report.counts.deleted)}
              hint={report.counts.deleted > 0 ? "local files removed" : "nothing removed"}
              tone={report.counts.deleted > 0 ? "bad" : "default"}
              icon={IconTrash}
            />
            <Stat
              label="Already in sync"
              value={formatNumber(report.counts.unchanged)}
              hint="matching files"
              icon={IconCheck}
            />
            <Stat
              label="Server files"
              value={formatNumber(report.counts.server)}
              hint={report.stats.totalSize ? formatBytes(report.stats.totalSize) : undefined}
              icon={IconServer}
            />
            <Stat
              label="Local files"
              value={formatNumber(report.counts.local)}
              hint="on this machine"
              icon={IconFolder}
            />
          </div>

          <CompositionBar report={report} />

          {/* Safety checks */}
          <div className="flex flex-col gap-1.5">
            <SectionLabel>Safety checks</SectionLabel>
            {report.checks.map((check) => (
              <div key={check.label} className="flex items-start gap-2 text-[12px]">
                {check.passed ? (
                  <IconCircleCheck className="mt-0.5 size-3.5 shrink-0 text-emerald-400" />
                ) : (
                  <IconCircleX className="mt-0.5 size-3.5 shrink-0 text-amber-400" />
                )}
                {/* Phones put the outcome under the check instead of in a ragged second column */}
                <span className="flex min-w-0 flex-col gap-0.5 sm:flex-row sm:gap-1.5">
                  <span className="text-foreground">{check.label}</span>
                  <span className="text-muted-foreground">
                    <span className="hidden sm:inline">— </span>
                    {check.detail}
                  </span>
                </span>
              </div>
            ))}
          </div>

          {/* rsync complaints */}
          {report.messages.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <SectionLabel>{hasErrors ? "rsync errors" : "rsync warnings"}</SectionLabel>
              {report.messages.slice(0, 8).map((message) => (
                <div
                  key={message.text}
                  className={cn(
                    "flex items-start gap-2 rounded-md border px-2.5 py-1.5 font-mono text-[11px] break-all",
                    message.level === "error"
                      ? "border-rose-500/35 bg-rose-500/10 text-rose-300"
                      : "border-amber-500/35 bg-amber-500/10 text-amber-300"
                  )}
                >
                  {message.level === "error" ? (
                    <IconX className="mt-px size-3 shrink-0" />
                  ) : (
                    <IconAlertTriangle className="mt-px size-3 shrink-0" />
                  )}
                  {message.text}
                </div>
              ))}
            </div>
          )}

          {/* Files */}
          <div className="flex flex-col gap-2">
            <SectionLabel>Files ({report.entries.length})</SectionLabel>
            <FileBrowser report={report} />
          </div>
        </>
      )}

      {/* Detail */}
      <Accordion className="flex flex-col gap-1.5">
        {report.completed && (
          <AccordionItem
            value="stats"
            className="overflow-hidden rounded-lg border border-border bg-card/50"
          >
            <AccordionTrigger className="px-3 py-2 text-[12px] no-underline hover:bg-muted/40 hover:no-underline">
              Transfer statistics
            </AccordionTrigger>
            <AccordionContent className="border-t border-border bg-black/20 px-3 py-3">
              <StatsGrid report={report} />
            </AccordionContent>
          </AccordionItem>
        )}

        {report.raw && (
          <AccordionItem
            value="raw"
            className="overflow-hidden rounded-lg border border-border bg-card/50"
          >
            <AccordionTrigger className="px-3 py-2 text-[12px] no-underline hover:bg-muted/40 hover:no-underline">
              Raw rsync output
            </AccordionTrigger>
            <AccordionContent className="border-t border-border bg-black/20 px-3 py-3">
              <div className="flex flex-col gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={() => copyToClipboard(report.raw, "rsync output")}
                >
                  <IconCopy className="mr-1.5 size-3.5" />
                  Copy output
                </Button>
                <pre className="max-h-[320px] overflow-auto rounded-md border border-border bg-background/60 p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted-foreground">
                  {report.raw}
                </pre>
              </div>
            </AccordionContent>
          </AccordionItem>
        )}

        <AccordionItem
          value="json"
          className="overflow-hidden rounded-lg border border-border bg-card/50"
        >
          <AccordionTrigger className="px-3 py-2 text-[12px] no-underline hover:bg-muted/40 hover:no-underline">
            JSON payload
          </AccordionTrigger>
          <AccordionContent className="border-t border-border bg-black/20 px-3 py-3">
            <div className="flex flex-col gap-2">
              <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => copyToClipboard(JSON.stringify(report.json, null, 2), "JSON")}
              >
                <IconCopy className="mr-1.5 size-3.5" />
                Copy JSON
              </Button>
              <pre className="max-h-[320px] overflow-auto rounded-md border border-border bg-background/60 p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted-foreground">
                {JSON.stringify(report.json, null, 2)}
              </pre>
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

/**
 * One-line verdict plus the four numbers that matter — for embedding beside a
 * notification that already carries a stored dry-run result.
 */
export function DryRunSummary({
  payload,
  performedAt,
  onOpen,
}: {
  payload: unknown;
  performedAt?: string;
  onOpen?: () => void;
}) {
  const report = useMemo(() => parseDryRun(payload), [payload]);
  if (!report.ok) return null;

  const tone = !report.completed
    ? { text: "text-rose-400", icon: IconCircleX, label: "Validation failed" }
    : report.safeToSync
      ? { text: "text-emerald-300", icon: IconShieldCheck, label: "Safe to sync" }
      : { text: "text-amber-400", icon: IconAlertTriangle, label: "Manual review" };
  const ToneIcon = tone.icon;

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-card/50 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <ToneIcon className={cn("size-4 shrink-0", tone.text)} />
        <span className={cn("text-xs font-semibold", tone.text)}>{tone.label}</span>
        <span className="text-[11px] text-muted-foreground">
          {report.completed ? report.headline : report.reason}
        </span>
        {performedAt && (
          <span className="text-[10.5px] text-muted-foreground/80">
            · {timeAgo(performedAt) || "just now"}
          </span>
        )}
        {onOpen && (
          <Button variant="ghost" size="sm" className="ml-auto h-6 text-[11px]" onClick={onOpen}>
            Details
          </Button>
        )}
      </div>
      <div
        className={cn(
          "flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-muted-foreground",
          !report.completed && "hidden"
        )}
      >
        <span>server {report.counts.server}</span>
        <span>local {report.counts.local}</span>
        <span className={report.counts.incoming > 0 ? "text-emerald-300" : undefined}>
          +{report.counts.incoming}
        </span>
        <span className={report.counts.deleted > 0 ? "text-rose-400" : undefined}>
          −{report.counts.deleted}
        </span>
        {report.stats.totalSize ? <span>{formatBytes(report.stats.totalSize)}</span> : null}
      </div>
    </div>
  );
}

/** Dialog wrapper shared by the media browser and the webhooks page. */
export function DryRunDialog({
  payload,
  performedAt,
  open,
  onOpenChange,
  subtitle,
}: {
  payload: unknown;
  performedAt?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  subtitle?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[88vh] flex-col overflow-hidden sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Dry-run validation</DialogTitle>
          <DialogDescription>
            {subtitle ?? "What this sync would do, straight from rsync's dry run"}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <DryRunReportView payload={payload} performedAt={performedAt} className="pb-1" />
        </div>
      </DialogContent>
    </Dialog>
  );
}
