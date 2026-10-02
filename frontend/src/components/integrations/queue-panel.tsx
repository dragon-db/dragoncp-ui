import { IconAlertTriangle, IconCircleCheck, IconRefresh } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { type QueueRow, useLibraryQueue } from "@/hooks/useMediaLibrary";
import { cn } from "@/lib/utils";

/**
 * What is waiting on the service, and why each row is waiting.
 *
 * The rows worth a screen are not the ones downloading — those look after
 * themselves. They are the ones that will never finish on their own: a download
 * whose progress has not moved, an import blocked on something only a person can
 * settle, a row the service cannot attribute to any title, or anything that has
 * simply been sitting there for days.
 *
 * Every row says whether it is holding an automatic sync back, decided by the
 * same classifier the gate uses.
 */

const VERDICTS: Record<string, { label: string; chip: string }> = {
  downloading: { label: "Downloading", chip: "border-sky-500/30 bg-sky-500/10 text-sky-300" },
  importing: { label: "Importing", chip: "border-sky-500/30 bg-sky-500/10 text-sky-300" },
  importpending: {
    label: "Waiting to import",
    chip: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  },
  stalled: { label: "Stalled", chip: "border-rose-500/30 bg-rose-500/10 text-rose-300" },
  blocked: { label: "Import blocked", chip: "border-rose-500/30 bg-rose-500/10 text-rose-300" },
  failed: { label: "Failed", chip: "border-rose-500/30 bg-rose-500/10 text-rose-300" },
  stale: { label: "Stale", chip: "border-amber-500/30 bg-amber-500/10 text-amber-300" },
  unrecognised: {
    label: "Unrecognised",
    chip: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  },
  imported: { label: "Filed", chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
};

function verdictStyle(verdict: string) {
  return (
    VERDICTS[verdict] ?? {
      label: verdict || "Waiting",
      chip: "border-border bg-muted/40 text-muted-foreground",
    }
  );
}

function age(hours: number | null) {
  if (hours === null) return "";
  if (hours < 1) return "just now";
  if (hours < 48) return `${Math.round(hours)}h old`;
  return `${Math.round(hours / 24)} days old`;
}

function bytes(value: number) {
  if (!value) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function Row({ row }: { row: QueueRow }) {
  const style = verdictStyle(row.verdict);
  return (
    <li
      className={cn(
        "rounded-xl border bg-card/60 px-3.5 py-3",
        row.needs_attention ? "border-amber-500/25" : "border-border/70"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">
            {row.title}
            {row.season_number !== null && row.season_number !== undefined && (
              <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                S{String(row.season_number).padStart(2, "0")}
              </span>
            )}
          </p>
          {row.release && row.release !== row.title && (
            <p className="truncate font-mono text-[11px] text-muted-foreground">{row.release}</p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {row.holds_sync && (
            <Badge
              variant="outline"
              className="border-primary/40 bg-primary/10 text-[11px] text-primary-foreground"
              title="An automatic sync for this title is waiting on this row"
            >
              Holding a sync
            </Badge>
          )}
          {row.unattributed && (
            <Badge
              variant="outline"
              className="border-amber-500/30 bg-amber-500/10 text-[11px] text-amber-300"
              title="The service cannot say which title this download is for"
            >
              No title
            </Badge>
          )}
          <Badge variant="outline" className={cn("text-[11px]", style.chip)}>
            {style.label}
          </Badge>
        </div>
      </div>

      {/* The service's own sentence. "Movie title mismatch, manual import
          required" tells you what to do; "importBlocked" does not. */}
      {row.why && <p className="mt-1.5 text-xs text-muted-foreground">{row.why}</p>}

      {row.verdict !== "blocked" && row.verdict !== "stale" && row.size > 0 && (
        <Progress value={row.progress} className="mt-2 h-1" />
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {row.size > 0 && (
          <span className="tabular-nums">
            {row.progress}% of {bytes(row.size)}
          </span>
        )}
        {row.time_left && row.verdict === "downloading" && <span>{row.time_left} left</span>}
        {row.download_client && <span>via {row.download_client}</span>}
        {row.indexer && <span>from {row.indexer}</span>}
        {row.age_hours !== null && <span>{age(row.age_hours)}</span>}
      </div>
    </li>
  );
}

export function QueuePanel({ source, displayName }: { source: string; displayName: string }) {
  const { data, isLoading, isFetching, refetch } = useLibraryQueue(source);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (data && !data.live) {
    return (
      <div className="rounded-xl border border-amber-500/25 bg-amber-500/8 px-4 py-3 text-sm text-amber-200/90">
        {data.message ?? `${displayName} did not answer.`}
      </div>
    );
  }

  const rows = data?.rows ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {rows.length === 0 ? (
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <IconCircleCheck className="h-4 w-4 text-emerald-400" />
            The {displayName} queue is empty
          </span>
        ) : (
          <>
            <span className="text-muted-foreground">
              {rows.length} row{rows.length === 1 ? "" : "s"}
            </span>
            {(data?.needing_attention ?? 0) > 0 && (
              <Badge
                variant="outline"
                className="gap-1 border-amber-500/30 bg-amber-500/10 text-[11px] text-amber-300"
              >
                <IconAlertTriangle className="h-3 w-3" />
                {data?.needing_attention} needing attention
              </Badge>
            )}
            {(data?.holding_a_sync ?? 0) > 0 && (
              <Badge
                variant="outline"
                className="border-primary/40 bg-primary/10 text-[11px] text-primary-foreground"
              >
                {data?.holding_a_sync} holding a sync
              </Badge>
            )}
          </>
        )}
        <Button
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <IconRefresh className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
          <span className="hidden sm:inline">Refresh</span>
        </Button>
      </div>

      {rows.length > 0 && (
        <ul className="space-y-2">
          {rows.map((row) => (
            <Row key={row.id} row={row} />
          ))}
        </ul>
      )}
    </div>
  );
}
