import { useState } from "react";
import {
  IconAlertTriangle,
  IconHistory,
  IconPlugConnectedX,
  IconRefresh,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { FilterChips, ListPagination } from "@/components/layout/list-controls";
import { type HistoryRecord, useLibraryHistory } from "@/hooks/useMediaLibrary";
import { Notice, ToneChip } from "@/components/integrations/library-bits";
import {
  HISTORY_EVENT,
  HISTORY_FILTERS,
  TONE_CHIP,
  TONE_TEXT,
  formatSize,
  libraryError,
  sinceText,
  stampText,
} from "@/components/integrations/library-vocab";

/**
 * What the service itself has been doing, read straight from it a page at a
 * time — the history of a busy library runs to tens of thousands of rows.
 *
 * Each row reads the way Sonarr's own History does: the series, "1x08", the
 * episode's title, the quality and custom formats, when. A row opens its
 * title's episode-by-episode panel. "Unknown here" marks an import for a title
 * DragonCP has never heard of — the shape a lost webhook leaves behind.
 */
export function HistoryPanel({
  source,
  displayName,
  onOpenTitle,
}: {
  source: string;
  displayName: string;
  /** Show a row's title in place of the list. */
  onOpenTitle: (externalId: string) => void;
}) {
  const [event, setEvent] = useState("all");
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(25);
  const page = Math.floor(offset / limit) + 1;
  const { data, isLoading, isFetching, isError, error, refetch } = useLibraryHistory(
    source,
    page,
    limit,
    event
  );

  const records = data?.records ?? [];
  const total = data?.total ?? 0;
  const label = HISTORY_FILTERS.find((entry) => entry.value === event)?.label ?? "All";

  const chooseEvent = (value: string) => {
    setEvent(value);
    setOffset(0);
  };

  return (
    <div className="space-y-3">
      <SectionCard
        label={`${displayName} history`}
        description={
          data?.live
            ? `${total.toLocaleString()} ${event === "all" ? "" : `${label.toLowerCase()} `}event${
                total === 1 ? "" : "s"
              }, newest first. A row opens its title.`
            : undefined
        }
        actions={
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            <IconRefresh className={cn("size-3.5", isFetching && "animate-spin")} />
            Refresh
          </Button>
        }
        toolbar={
          <div className="flex w-full flex-wrap gap-1">
            <FilterChips choices={HISTORY_FILTERS} value={event} onChange={chooseEvent} />
          </div>
        }
      >
        {isLoading ? (
          <RowsSkeleton />
        ) : isError ? (
          <div className="p-3">
            <Notice tone="crit" icon={IconAlertTriangle}>
              {libraryError(error, "Could not load the history.")}
            </Notice>
          </div>
        ) : data && !data.live ? (
          <div className="p-3">
            <Notice tone="warn" icon={IconPlugConnectedX}>
              {data.message ?? `${displayName} did not answer.`}
            </Notice>
          </div>
        ) : records.length === 0 ? (
          <SectionEmpty
            icon={IconHistory}
            title={
              event === "all" ? "Nothing in the history yet" : `No ${label.toLowerCase()} events`
            }
            hint={
              event === "all"
                ? `Grabs, imports and deletions show up here as ${displayName} makes them.`
                : `${displayName} has recorded none of these.`
            }
            action={
              event !== "all" ? (
                <Button size="sm" variant="outline" onClick={() => chooseEvent("all")}>
                  Show all
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <ul
              className={cn(
                "divide-y divide-border/70 transition-opacity",
                isFetching && "opacity-60"
              )}
            >
              {records.map((record) => (
                <HistoryRow
                  key={record.id}
                  record={record}
                  movie={source === "radarr"}
                  onOpen={
                    record.external_id ? () => onOpenTitle(String(record.external_id)) : undefined
                  }
                />
              ))}
            </ul>
            <ListPagination
              offset={offset}
              limit={limit}
              total={total}
              count={records.length}
              onOffsetChange={setOffset}
              onLimitChange={(next) => {
                setLimit(next);
                setOffset(0);
              }}
              noun="events"
            />
          </>
        )}
      </SectionCard>
    </div>
  );
}

function HistoryRow({
  record,
  movie,
  onOpen,
}: {
  record: HistoryRecord;
  movie: boolean;
  onOpen?: () => void;
}) {
  const info = HISTORY_EVENT[record.event] ?? HISTORY_EVENT.other;
  const Glyph = info.icon;
  const score = record.custom_format_score;
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        disabled={!onOpen}
        className="flex w-full items-start gap-3 px-3.5 py-2.5 text-left transition-colors outline-none hover:bg-elevated/50 focus-visible:bg-elevated/60 disabled:cursor-default disabled:hover:bg-transparent"
      >
        <span
          className={cn(
            "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border",
            TONE_CHIP[info.tone]
          )}
          aria-hidden
        >
          <Glyph className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start justify-between gap-3">
            <p className="min-w-0 text-[13.5px] leading-snug break-words">
              <span className="font-semibold text-foreground">
                {record.title ?? record.source_title ?? "Unknown title"}
              </span>
              {movie && record.year ? (
                <span className="text-muted-foreground"> ({record.year})</span>
              ) : null}
              {record.episode_label && (
                <span className="ml-1.5 font-mono text-[12px] text-foreground-2">
                  {record.episode_label}
                </span>
              )}
              {record.episode_title && (
                <span className="ml-1.5 text-foreground-2">{record.episode_title}</span>
              )}
            </p>
            <time
              dateTime={record.date}
              title={stampText(record.date)}
              className="shrink-0 pt-0.5 font-mono text-[11px] whitespace-nowrap text-muted-foreground"
            >
              {sinceText(record.date)}
            </time>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted-foreground">
            <span
              className={cn("text-[10px] font-bold tracking-wide uppercase", TONE_TEXT[info.tone])}
            >
              {record.event_label || info.label}
            </span>
            {record.quality && (
              <span className="rounded-md border border-border bg-black/25 px-1.5 py-px font-mono text-[10.5px] text-foreground-2">
                {record.quality}
              </span>
            )}
            {record.custom_formats.map((format) => (
              <span
                key={format}
                className="rounded-md border border-border bg-black/25 px-1.5 py-px text-[10.5px] text-foreground-2"
              >
                {format}
              </span>
            ))}
            {score != null && score !== 0 && (
              <span className="font-mono text-[10.5px] tabular-nums" title="Custom format score">
                {score > 0 ? `+${score}` : score}
              </span>
            )}
            {record.size ? (
              <span className="font-mono text-[10.5px] tabular-nums">
                {formatSize(record.size)}
              </span>
            ) : null}
            {record.download_client && <span>via {record.download_client}</span>}
            {record.indexer && <span>from {record.indexer}</span>}
            {!record.known_here && (
              <ToneChip
                tone="warn"
                icon={IconAlertTriangle}
                label="Unknown here"
                size="sm"
                title="DragonCP has no record of this title, which is what a lost webhook leaves behind"
              />
            )}
          </div>
          {record.reason && <p className="text-[12px] text-foreground-2">{record.reason}</p>}
          {record.source_title && record.source_title !== record.title && (
            <p
              className="truncate font-mono text-[10.5px] text-foreground-3"
              title={record.source_title}
            >
              {record.source_title}
            </p>
          )}
        </div>
      </button>
    </li>
  );
}

function RowsSkeleton() {
  return (
    <div className="divide-y divide-border/70">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex gap-3 px-3.5 py-3">
          <Skeleton className="size-7 shrink-0 rounded-full" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-3/5" />
            <Skeleton className="h-3 w-2/5" />
          </div>
        </div>
      ))}
    </div>
  );
}
