import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { IconArrowsMaximize, IconArrowDown, IconEraser, IconTerminal2 } from "@tabler/icons-react";

/**
 * rsync writes one progress line per tick, so a log is mostly repetition of the
 * same shape. Colouring only the lines that break that rhythm — errors,
 * warnings, the completion notice — keeps the exceptions findable in a wall of
 * identical-looking text.
 */
function lineTone(line: string): string {
  const lower = line.toLowerCase();
  if (lower.includes("error") || lower.includes("failed") || lower.startsWith("rsync:")) {
    return "text-rose-300";
  }
  if (lower.includes("warning") || lower.includes("skipping")) return "text-amber-300";
  if (lower.includes("completed") || lower.includes("speedup is")) return "text-emerald-300";
  // Progress ticks are the background noise of the log; dim them so file names
  // and the summary block stand out.
  if (/^\s*[\d,.]+[KMGTP]?\s+\d{1,3}%/.test(line)) return "text-muted-foreground";
  return "text-foreground/80";
}

function LogLines({
  logs,
  emptyText = "No output yet.",
  /** Position of logs[0] in the full output, so a tail still numbers truthfully. */
  startIndex = 0,
  className,
}: {
  logs: string[];
  emptyText?: string;
  startIndex?: number;
  className?: string;
}) {
  if (!logs.length) {
    return (
      <p className={cn("px-3 py-6 text-center text-xs text-muted-foreground", className)}>
        {emptyText}
      </p>
    );
  }
  return (
    <div className={cn("flex flex-col", className)}>
      {logs.map((line, index) => (
        <div
          key={`${index}-${line.slice(0, 24)}`}
          className={cn(
            "flex gap-3 px-3 py-[3px] font-mono text-[11px] leading-relaxed break-all",
            lineTone(line)
          )}
        >
          <span className="w-9 shrink-0 text-right text-muted-foreground/40 tabular-nums select-none">
            {startIndex + index + 1}
          </span>
          <span className="min-w-0 flex-1">{line}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Live rsync output for one transfer, with the controls the old Logs tab put
 * behind keyboard shortcuts — follow, clear, fullscreen — attached to the log
 * they act on.
 *
 * A long transfer stores tens of thousands of progress lines, so the inline
 * console renders only the tail; the full log stays one click away rather than
 * putting every line in the DOM on a two-second refresh. Clearing hides what is
 * on screen rather than deleting anything, and the label says so.
 */
const INLINE_TAIL = 400;

export function TransferLogConsole({
  logs,
  title,
  live,
  loading,
  className,
}: {
  logs: string[];
  title: string;
  live: boolean;
  loading?: boolean;
  className?: string;
}) {
  const [follow, setFollow] = useState(true);
  const [hiddenBefore, setHiddenBefore] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const kept = useMemo(() => logs.slice(hiddenBefore), [logs, hiddenBefore]);
  const visible = useMemo(
    () => (kept.length > INLINE_TAIL ? kept.slice(-INLINE_TAIL) : kept),
    [kept]
  );
  const truncated = kept.length - visible.length;

  // Following means pinning to the newest line as output arrives. Turning it
  // off lets you read back through the log while the transfer keeps writing.
  useEffect(() => {
    if (!follow) return;
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [visible, follow]);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
          Output
        </span>
        {live && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-brand/40 bg-brand/15 px-2 py-0.5 text-[10px] font-bold tracking-wide text-brand-foreground uppercase">
            <span className="size-1.5 animate-pulse rounded-full bg-brand-hover" />
            Live
          </span>
        )}
        <span className="font-mono text-[10.5px] text-muted-foreground">
          {kept.length} line{kept.length === 1 ? "" : "s"}
          {truncated > 0 && <span className="opacity-70"> · showing last {INLINE_TAIL}</span>}
        </span>

        <div className="ml-auto flex items-center gap-1">
          <Button
            size="xs"
            variant={follow ? "secondary" : "ghost"}
            className={cn(!follow && "text-muted-foreground")}
            onClick={() => setFollow((value) => !value)}
            title={follow ? "Stop following new output" : "Follow new output"}
          >
            <IconArrowDown className="mr-1 size-3" />
            Follow
          </Button>
          <Button
            size="xs"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => setHiddenBefore(logs.length)}
            disabled={!kept.length}
            title="Hide the output currently on screen"
          >
            <IconEraser className="mr-1 size-3" />
            Clear
          </Button>
          <Button
            size="xs"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => setExpanded(true)}
            disabled={!kept.length}
            title="Open the full log"
          >
            <IconArrowsMaximize className="mr-1 size-3" />
            Expand
          </Button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="max-h-72 overflow-y-auto rounded-md border border-border bg-background/80 py-1.5"
      >
        {loading ? (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">Loading output…</p>
        ) : (
          <LogLines
            logs={visible}
            startIndex={hiddenBefore + truncated}
            emptyText={live ? "Waiting for output…" : "No output was recorded for this transfer."}
          />
        )}
      </div>

      {hiddenBefore > 0 && (
        <button
          type="button"
          onClick={() => setHiddenBefore(0)}
          className="self-start font-mono text-[10.5px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          {hiddenBefore} earlier line{hiddenBefore === 1 ? "" : "s"} hidden — show them
        </button>
      )}

      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="flex max-h-[88vh] flex-col overflow-hidden sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <IconTerminal2 className="size-4 text-brand-hover" />
              Transfer output
            </DialogTitle>
            <DialogDescription>{title}</DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-border bg-background/80 py-1.5">
            <LogLines
              logs={kept}
              startIndex={hiddenBefore}
              emptyText={live ? "Waiting for output…" : "No output was recorded for this transfer."}
            />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
