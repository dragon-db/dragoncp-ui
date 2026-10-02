import { useState } from "react";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLibraryHistory } from "@/hooks/useMediaLibrary";
import { cn } from "@/lib/utils";

/**
 * What the service itself has been doing.
 *
 * Read straight from Sonarr or Radarr, one page at a time — the history of a
 * busy library runs to tens of thousands of rows, and unlike the queue there is
 * no filter that makes a single page enough.
 *
 * The column that earns its place is "known here". An import the service made
 * for a title DragonCP has never heard of is the shape a lost notification
 * leaves behind.
 */

const PAGE_SIZE = 25;

/** Plain words for the service's own event names. */
const EVENT_LABELS: Record<string, { label: string; className: string }> = {
  downloadFolderImported: {
    label: "Imported",
    className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  },
  grabbed: { label: "Grabbed", className: "border-sky-500/30 bg-sky-500/10 text-sky-300" },
  episodeFileDeleted: {
    label: "File deleted",
    className: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  },
  movieFileDeleted: {
    label: "File deleted",
    className: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  },
  downloadFailed: {
    label: "Download failed",
    className: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  },
  episodeFileRenamed: {
    label: "Renamed",
    className: "border-border bg-muted/40 text-muted-foreground",
  },
  movieFileRenamed: {
    label: "Renamed",
    className: "border-border bg-muted/40 text-muted-foreground",
  },
};

function eventStyle(eventType: string) {
  return (
    EVENT_LABELS[eventType] ?? {
      label: eventType || "Event",
      className: "border-border bg-muted/40 text-muted-foreground",
    }
  );
}

function when(iso: string) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function HistoryPanel({ source, displayName }: { source: string; displayName: string }) {
  const [page, setPage] = useState(1);
  const { data, isLoading, isFetching } = useLibraryHistory(source, page, PAGE_SIZE);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
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

  const records = data?.records ?? [];
  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>
          {total.toLocaleString()} event{total === 1 ? "" : "s"} in {displayName}
        </span>
        <span className="ml-auto flex items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || isFetching}
          >
            <IconChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <span className="tabular-nums">
            {page} / {lastPage}
          </span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2"
            onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
            disabled={page >= lastPage || isFetching}
          >
            <IconChevronRight className="h-3.5 w-3.5" />
          </Button>
        </span>
      </div>

      <ul className={cn("space-y-1.5 transition-opacity", isFetching && "opacity-60")}>
        {records.map((record) => {
          const style = eventStyle(record.event_type);
          return (
            <li
              key={record.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border/70 bg-card/60 px-3 py-2"
            >
              <Badge variant="outline" className={cn("shrink-0 text-[11px]", style.className)}>
                {style.label}
              </Badge>
              <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                {record.title ?? record.source_title ?? "—"}
              </span>
              {record.quality && (
                <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                  {record.quality}
                </span>
              )}
              {!record.known_here && (
                <Badge
                  variant="outline"
                  className="shrink-0 border-amber-500/30 bg-amber-500/10 text-[11px] text-amber-300"
                  title="DragonCP has no record of this title at all"
                >
                  Unknown here
                </Badge>
              )}
              <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">
                {when(record.date)}
              </span>
            </li>
          );
        })}
      </ul>

      {records.length === 0 && (
        <p className="rounded-xl border border-border/70 bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
          Nothing on this page.
        </p>
      )}
    </div>
  );
}
