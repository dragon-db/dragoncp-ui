import type { ComponentType } from "react";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconCircleX,
  IconClockHour4,
  IconCloudDownload,
  IconHourglassHigh,
  IconLoader2,
  IconPlayerPause,
  IconPlugConnectedX,
  IconRefresh,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { type QueueRow, useLibraryQueue } from "@/hooks/useMediaLibrary";
import { Notice, ToneChip } from "@/components/integrations/library-bits";
import {
  TONE_BAR,
  TONE_TEXT,
  formatSize,
  libraryError,
  spanText,
} from "@/components/integrations/library-vocab";

/**
 * What is waiting on the service, and what each row is doing, in plain words.
 *
 * The rows worth a look are not the ones downloading — those look after
 * themselves. They are the ones that will not finish on their own: a download
 * that has not moved, an import blocked on something only a person can settle,
 * a row the service cannot attribute to any title, anything sitting there for
 * days. Those come first.
 *
 * Every row says whether it is holding an automatic sync back, decided by the
 * same classifier Sonarr's Ready check uses. A row opens its title's panel.
 */

type Icon = ComponentType<{ className?: string }>;

const STATUS_ICON: Record<string, Icon> = {
  Downloading: IconCloudDownload,
  Queued: IconClockHour4,
  Delayed: IconClockHour4,
  Paused: IconPlayerPause,
  "Waiting to import": IconClockHour4,
  Importing: IconLoader2,
  Imported: IconCircleCheck,
  Stuck: IconAlertTriangle,
  Stale: IconAlertTriangle,
  Unrecognised: IconAlertTriangle,
  Failed: IconCircleX,
};

function age(hours: number | null) {
  if (hours === null) return "";
  if (hours < 1) return "added just now";
  if (hours < 48) return `${Math.round(hours)} h in the queue`;
  return `${Math.round(hours / 24)} days in the queue`;
}

export function QueuePanel({
  source,
  displayName,
  onOpenTitle,
}: {
  source: string;
  displayName: string;
  /** Show a row's title in place of the list. */
  onOpenTitle: (externalId: string) => void;
}) {
  const { data, isLoading, isFetching, isError, error, refetch } = useLibraryQueue(source);
  const rows = data?.rows ?? [];
  const moving = rows.filter((row) => row.tone === "brand").length;

  const summary = [
    rows.length ? `${rows.length} in the queue` : null,
    moving ? `${moving} on the move` : null,
    data?.needing_attention ? `${data.needing_attention} needing a look` : null,
    data?.holding_a_sync ? `${data.holding_a_sync} holding a sync back` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="space-y-3">
      <SectionCard
        label={`${displayName} queue`}
        description={
          data?.live && rows.length ? `${summary}. Checked every 30 seconds.` : undefined
        }
        actions={
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            <IconRefresh className={cn("size-3.5", isFetching && "animate-spin")} />
            Refresh
          </Button>
        }
      >
        {isLoading ? (
          <RowsSkeleton />
        ) : isError ? (
          <div className="p-3">
            <Notice tone="crit" icon={IconAlertTriangle}>
              {libraryError(error, "Could not load the queue.")}
            </Notice>
          </div>
        ) : data && !data.live ? (
          <div className="p-3">
            <Notice tone="warn" icon={IconPlugConnectedX}>
              {data.message ?? `${displayName} did not answer.`}
            </Notice>
          </div>
        ) : rows.length === 0 ? (
          <SectionEmpty
            icon={IconCircleCheck}
            title={`The ${displayName} queue is empty`}
            hint={`Downloads show up here while ${displayName} fetches them, with anything stuck at the top.`}
          />
        ) : (
          <ul className="divide-y divide-border/70">
            {rows.map((row) => (
              <QueueItem
                key={row.id}
                row={row}
                movie={source === "radarr"}
                onOpen={row.external_id ? () => onOpenTitle(String(row.external_id)) : undefined}
              />
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

function QueueItem({ row, movie, onOpen }: { row: QueueRow; movie: boolean; onOpen?: () => void }) {
  const Glyph = STATUS_ICON[row.status_label] ?? IconHourglassHigh;
  const showBar = row.size > 0 && row.verdict !== "stale";
  const left = row.tone === "brand" ? spanText(row.seconds_left) : "";
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        disabled={!onOpen}
        className={cn(
          "w-full space-y-1.5 px-3.5 py-3 text-left transition-colors outline-none hover:bg-elevated/50 focus-visible:bg-elevated/60 disabled:cursor-default disabled:hover:bg-transparent",
          row.needs_attention && "bg-amber-500/[0.03]"
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <p className="min-w-0 text-[13.5px] leading-snug break-words">
            <span className="font-semibold text-foreground">{row.title}</span>
            {movie && row.year ? (
              <span className="text-muted-foreground"> ({row.year})</span>
            ) : null}
            {row.episode_code && (
              <span className="ml-1.5 font-mono text-[12px] text-foreground-2">
                {row.episode_code}
              </span>
            )}
            {row.episode_title && (
              <span className="ml-1.5 text-foreground-2">{row.episode_title}</span>
            )}
          </p>
          <ToneChip
            tone={row.tone}
            icon={Glyph}
            label={row.status_label}
            className={cn(row.status_label === "Importing" && "[&_svg]:animate-spin")}
          />
        </div>

        {/* The service's own sentence: "Title mismatch, manual import required"
            says what to do; "importBlocked" does not. */}
        {row.status_detail && (
          <p
            className={cn(
              "text-[12px] leading-snug",
              row.tone === "brand" || row.tone === "ok"
                ? "text-muted-foreground"
                : TONE_TEXT[row.tone]
            )}
          >
            {row.status_detail}
          </p>
        )}

        {showBar && (
          <div
            className="h-1 overflow-hidden rounded-full bg-white/8"
            role="progressbar"
            aria-valuenow={row.progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`${row.progress}% downloaded`}
          >
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-500",
                TONE_BAR[row.tone]
              )}
              style={{ width: `${Math.max(0, Math.min(100, row.progress))}%` }}
            />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted-foreground">
          {row.size > 0 && (
            <span>
              <span className="font-mono text-foreground-2 tabular-nums">{row.progress}%</span> of{" "}
              <span className="font-mono tabular-nums">{formatSize(row.size)}</span>
            </span>
          )}
          {left && <span className="font-mono tabular-nums">{left} left</span>}
          {row.quality && <span className="font-mono text-[10.5px]">{row.quality}</span>}
          {row.custom_formats.length > 0 && <span>{row.custom_formats.join(", ")}</span>}
          {row.download_client && <span>via {row.download_client}</span>}
          {row.age_hours !== null && row.age_hours > 24 && (
            <span className={cn(row.age_hours > 48 && "text-amber-300/90")}>
              {age(row.age_hours)}
            </span>
          )}
          {row.holds_sync && (
            <ToneChip
              tone="brand"
              icon={IconHourglassHigh}
              label="Holding a sync"
              size="sm"
              title="An automatic sync of this season is waiting for this download"
            />
          )}
          {row.unattributed && (
            <ToneChip
              tone="warn"
              icon={IconAlertTriangle}
              label="No title"
              size="sm"
              title="The service cannot say which title this download is for"
            />
          )}
        </div>

        {row.release && row.release !== row.title && (
          <p className="truncate font-mono text-[10.5px] text-foreground-3" title={row.release}>
            {row.release}
          </p>
        )}
      </button>
    </li>
  );
}

function RowsSkeleton() {
  return (
    <div className="divide-y divide-border/70">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="space-y-2 px-3.5 py-3">
          <div className="flex justify-between gap-3">
            <Skeleton className="h-3.5 w-1/2" />
            <Skeleton className="h-4 w-24 rounded-full" />
          </div>
          <Skeleton className="h-1 w-full" />
          <Skeleton className="h-3 w-2/5" />
        </div>
      ))}
    </div>
  );
}
