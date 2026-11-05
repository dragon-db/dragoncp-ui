import { useState } from "react";
import {
  IconAlertTriangle,
  IconDeviceTv,
  IconHistory,
  IconPlayerPlay,
  IconRefresh,
  IconTransform,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { FilterChips, ListPagination, ListSearch } from "@/components/layout/list-controls";
import { Notice, TitlePoster, ToneChip } from "@/components/integrations/library-bits";
import { libraryError } from "@/components/integrations/library-vocab";
import {
  duration,
  episodeCode,
  methodInfo,
  byCost,
  reasonInfo,
  since,
} from "@/components/integrations/jellyfin-vocab";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { usePlays } from "@/hooks/useJellyfin";
import type { Play } from "@/lib/jellyfin-types";

const METHODS = [
  { value: "all", label: "All" },
  { value: "converted", label: "Converted" },
  { value: "direct", label: "Not converted" },
] as const;

const EVERYONE = "__everyone__";

/**
 * Every play DragonCP has recorded, newest first: who, what, on which device,
 * how much of it, and — for a converted one — why.
 */
export function PlaysPanel({ onOpenSettings }: { onOpenSettings: () => void }) {
  const [method, setMethod] = useState<string>("all");
  const [user, setUser] = useState<string>("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(50);
  const q = useDebouncedValue(search.trim(), 300);

  const { data, isLoading, isFetching, isError, error, refetch } = usePlays({
    limit,
    offset,
    user,
    converted: method,
    q,
  });
  const plays = data?.plays ?? [];
  const total = data?.total ?? 0;
  const users = data?.users ?? [];
  const filtered = method !== "all" || Boolean(user) || Boolean(q);
  const userItems = [
    { value: EVERYONE, label: "Everyone" },
    ...users.map((name) => ({ value: name, label: name })),
  ];

  const resetTo = (apply: () => void) => {
    apply();
    setOffset(0);
  };

  return (
    <div className="space-y-3">
      {data && !data.recording && (
        <Notice tone="muted" icon={IconHistory}>
          <span>
            New plays are not being recorded. Switch on <strong>Record plays</strong> and every play
            from then on is kept here.{" "}
          </span>
          <button
            type="button"
            onClick={onOpenSettings}
            className="font-medium text-foreground underline-offset-2 hover:underline"
          >
            Open Connection
          </button>
        </Notice>
      )}
      <SectionCard
        label="Plays"
        description={
          data
            ? `${total.toLocaleString()} play${total === 1 ? "" : "s"}${filtered ? " match" : " recorded"}, newest first.`
            : undefined
        }
        actions={
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            <IconRefresh className={cn("size-3.5", isFetching && "animate-spin")} />
            Refresh
          </Button>
        }
        toolbar={
          <div className="flex w-full flex-wrap items-center gap-2">
            <div className="flex flex-wrap gap-1">
              <FilterChips
                choices={METHODS}
                value={method}
                onChange={(value) => resetTo(() => setMethod(value))}
              />
            </div>
            {users.length > 0 && (
              <Select
                items={userItems}
                value={user || EVERYONE}
                onValueChange={(value) =>
                  resetTo(() => setUser(!value || value === EVERYONE ? "" : String(value)))
                }
              >
                <SelectTrigger size="sm" className="h-8 min-w-[150px]" aria-label="Who">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {userItems.map((entry) => (
                    <SelectItem key={entry.value} value={entry.value}>
                      {entry.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <ListSearch
              value={search}
              onChange={(value) => resetTo(() => setSearch(value))}
              placeholder="Title, device or app"
              className="sm:ml-auto"
            />
          </div>
        }
      >
        {isLoading ? (
          <RowsSkeleton />
        ) : isError ? (
          <div className="p-3">
            <Notice tone="crit" icon={IconAlertTriangle}>
              {libraryError(error, "Could not load the plays.")}
            </Notice>
          </div>
        ) : plays.length === 0 ? (
          <SectionEmpty
            icon={IconHistory}
            title={filtered ? "No plays match" : "No plays recorded yet"}
            hint={
              filtered
                ? "Try another filter, or clear the search."
                : "Each play shows up here once it starts, and stays when it ends."
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
              {plays.map((play) => (
                <PlayRow key={play.id} play={play} />
              ))}
            </ul>
            <ListPagination
              offset={offset}
              limit={limit}
              total={total}
              count={plays.length}
              onOffsetChange={setOffset}
              onLimitChange={(next) => {
                setLimit(next);
                setOffset(0);
              }}
              noun="plays"
            />
          </>
        )}
      </SectionCard>
    </div>
  );
}

function PlayRow({ play }: { play: Play }) {
  const { item } = play;
  const method = methodInfo(
    play.play_method,
    play.play_method === "Transcode" ? play.video_converted : null
  );
  const code = episodeCode(item.season, item.episode);
  const live = !play.ended_at;
  const watched =
    play.source === "live"
      ? `watched ${duration(play.watched_seconds)}${play.finished ? ", to the end" : ""}`
      : "";
  return (
    <li className="flex gap-3 px-3.5 py-3">
      <TitlePoster src={item.poster} movie={item.type === "Movie"} className="w-10 self-start" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-start justify-between gap-3">
          <p className="min-w-0 text-[13.5px] leading-snug break-words">
            <span className="font-semibold text-foreground">{item.series || item.title}</span>
            {!item.series && item.year ? (
              <span className="text-muted-foreground"> ({item.year})</span>
            ) : null}
            {code && <span className="ml-1.5 font-mono text-[12px] text-foreground-2">{code}</span>}
            {item.series && item.title && (
              <span className="ml-1.5 text-foreground-2">{item.title}</span>
            )}
          </p>
          <div className="flex shrink-0 items-center gap-1.5">
            {live && <ToneChip tone="brand" icon={IconPlayerPlay} label="Playing" size="sm" />}
            {play.play_method && (
              <ToneChip
                tone={method.tone}
                icon={play.play_method === "Transcode" ? IconTransform : IconPlayerPlay}
                label={method.label}
                title={method.hint}
                size="sm"
              />
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
          <span className="font-medium text-foreground-2">{play.user || "Someone"}</span>
          <span className="flex items-center gap-1">
            <IconDeviceTv className="size-3.5" />
            {play.device || "Unknown device"}
          </span>
          {play.client && <span>{play.client}</span>}
          <span title={new Date(play.started_at).toLocaleString()}>{since(play.started_at)}</span>
          {watched && <span>{watched}</span>}
        </div>
        {play.reasons.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {byCost(play.reasons).map((code) => {
              const info = reasonInfo(code);
              return (
                <ToneChip
                  key={code}
                  tone="warn"
                  icon={IconAlertTriangle}
                  label={info.label}
                  title={`${info.meaning} ${info.fix}`.trim()}
                  size="sm"
                />
              );
            })}
          </div>
        )}
      </div>
    </li>
  );
}

function RowsSkeleton() {
  return (
    <div className="divide-y divide-border/70">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex gap-3 px-3.5 py-3">
          <Skeleton className="aspect-[2/3] w-10 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/2" />
            <Skeleton className="h-3 w-2/5" />
          </div>
        </div>
      ))}
    </div>
  );
}
