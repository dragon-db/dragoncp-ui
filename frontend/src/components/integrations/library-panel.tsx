import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  IconCircleArrowUp,
  IconInbox,
  IconInfoCircle,
  IconPlugConnectedX,
  IconRefresh,
  IconSearch,
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
import { FilterChips, ListSearch } from "@/components/layout/list-controls";
import { type LibraryItem, useLibrary, useRefreshLibrary } from "@/hooks/useMediaLibrary";
import {
  Notice,
  TitlePoster,
  TitleStateChip,
  ToneChip,
} from "@/components/integrations/library-bits";
import {
  LIBRARY_FILTERS,
  STATE_RANK,
  formatSize,
  hasUpgrade,
  itemSentence,
  libraryError,
} from "@/components/integrations/library-vocab";

/**
 * What the service holds, against what is actually on this disk.
 *
 * A grid of small posters, out of sync first, each with one state and one
 * quiet counts line ("Sonarr 1 · here 7"). The state is worked out without a
 * call per title — the service's counts, its imports of the last two weeks
 * against the last sync of each folder, and the disk — and opening a card
 * compares that title episode by episode, which then stands in for the
 * estimate for ten minutes.
 *
 * Presence is read from the filesystem, never from the transfer log, and
 * titles the service holds no files for are counted apart, not judged: in one
 * real library that is 99 of 129 series, shows added before they air.
 */

type SortKey = "attention" | "recent" | "title";

const UPGRADE_FILTER = "upgrade";

const SORTS: Array<{ value: SortKey; label: string }> = [
  { value: "attention", label: "Needs attention first" },
  { value: "recent", label: "Recently imported" },
  { value: "title", label: "Title" },
];

function byTitle(a: LibraryItem, b: LibraryItem) {
  return (a.title ?? "").localeCompare(b.title ?? "");
}

function byImport(a: LibraryItem, b: LibraryItem) {
  const left = a.last_import_at ? Date.parse(a.last_import_at) : 0;
  const right = b.last_import_at ? Date.parse(b.last_import_at) : 0;
  return right - left;
}

export function LibraryPanel({
  source,
  displayName,
  onOpenTitle,
}: {
  source: string;
  displayName: string;
  /** Show one title in place of the grid. */
  onOpenTitle: (externalId: string) => void;
}) {
  const { data, isLoading, isError, error } = useLibrary(source);
  const refresh = useRefreshLibrary(source);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<SortKey>("attention");
  const movie = source === "radarr";

  const items = useMemo(() => data?.items ?? [], [data]);

  const choices = useMemo(() => {
    const present = LIBRARY_FILTERS.map((entry) => ({
      value: entry.value,
      label: entry.label,
      count: items.filter((item) => entry.states.includes(item.sync_state)).length,
    })).filter((entry) => entry.count > 0 || entry.value === "out_of_sync");
    // Upgrades are a kind of out of sync, picked out on their own. Always
    // offered, like Out of sync, so "none waiting" is an answer too.
    const upgrade = {
      value: UPGRADE_FILTER,
      label: "Upgrade",
      count: items.filter(hasUpgrade).length,
    };
    return [
      present[0],
      upgrade,
      ...present.slice(1),
      { value: "all", label: "All", count: items.length },
    ];
  }, [items]);

  const visible = useMemo(() => {
    const wanted = LIBRARY_FILTERS.find((entry) => entry.value === filter)?.states;
    const needle = query.trim().toLowerCase();
    const list = items
      .filter((item) => (filter === UPGRADE_FILTER ? hasUpgrade(item) : true))
      .filter((item) => !wanted || wanted.includes(item.sync_state))
      .filter((item) => !needle || (item.title ?? "").toLowerCase().includes(needle));
    return [...list].sort((a, b) => {
      if (sort === "title") return byTitle(a, b);
      if (sort === "recent") return byImport(a, b) || byTitle(a, b);
      return (
        (STATE_RANK[a.sync_state] ?? 9) - (STATE_RANK[b.sync_state] ?? 9) ||
        byImport(a, b) ||
        byTitle(a, b)
      );
    });
  }, [items, filter, query, sort]);

  const doRefresh = async () => {
    try {
      const result = await refresh.mutateAsync();
      toast.success(`Read ${result.titles_seen} title(s) from ${displayName}.`);
    } catch (err) {
      toast.error(libraryError(err, `Could not read from ${displayName}.`));
    }
  };

  const refreshButton = (
    <Button size="sm" variant="outline" onClick={doRefresh} disabled={refresh.isPending}>
      <IconRefresh className={cn("size-3.5", refresh.isPending && "animate-spin")} />
      Refresh
    </Button>
  );

  if (isError) {
    return (
      <Notice tone="crit" icon={IconPlugConnectedX}>
        {libraryError(error, "Could not load the library.")}
      </Notice>
    );
  }

  const outOfSync = items.filter((item) => item.sync_state === "out_of_sync").length;

  return (
    <div className="space-y-3">
      {data && !data.live && (
        <Notice tone="warn" icon={IconPlugConnectedX}>
          {displayName} did not answer. Showing what DragonCP already had recorded, which may be out
          of date.
        </Notice>
      )}

      <SectionCard
        label={`${displayName} library`}
        description={
          isLoading
            ? `Reading ${displayName} and this disk…`
            : outOfSync
              ? `${outOfSync} ${outOfSync === 1 ? "title is" : "titles are"} out of sync. Open one to see which episodes.`
              : `Everything ${displayName} holds is here, as far as its counts and recent imports say.`
        }
        actions={refreshButton}
        toolbar={
          <>
            <div className="flex w-full flex-wrap gap-1">
              <FilterChips choices={choices} value={filter} onChange={setFilter} />
            </div>
            <div className="flex w-full flex-wrap items-center gap-2">
              <ListSearch
                value={query}
                onChange={setQuery}
                placeholder="Find a title"
                className="sm:w-60"
              />
              <Select
                items={SORTS}
                value={sort}
                onValueChange={(value) => setSort((value as SortKey) ?? "attention")}
              >
                <SelectTrigger size="sm" className="h-8 min-w-[170px]" aria-label="Sort by">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SORTS.map((entry) => (
                    <SelectItem key={entry.value} value={entry.value}>
                      {entry.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {data?.live && data.history_checked === false && (
                <span className="flex items-center gap-1 text-[11.5px] text-muted-foreground">
                  <IconInfoCircle className="size-3.5" />
                  Recent imports could not be read; only the counts were compared.
                </span>
              )}
            </div>
          </>
        }
      >
        {isLoading ? (
          <GridSkeleton />
        ) : items.length === 0 ? (
          <SectionEmpty
            icon={IconInbox}
            title="Nothing recorded yet"
            hint={`Refresh reads ${displayName}'s catalogue into DragonCP; until then only titles a webhook has named are known.`}
            action={refreshButton}
          />
        ) : visible.length === 0 ? (
          <SectionEmpty
            icon={IconSearch}
            title="No title matches"
            hint={
              query ? `Nothing here is called “${query}”.` : "No title is in that state right now."
            }
            action={
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setFilter("all");
                  setQuery("");
                }}
              >
                Show all
              </Button>
            }
          />
        ) : (
          <ul className="grid grid-cols-3 gap-x-3 gap-y-4 p-3 sm:grid-cols-[repeat(auto-fill,minmax(96px,1fr))] sm:p-4">
            {visible.map((item) => (
              <TitleCard
                key={item.external_id}
                item={item}
                movie={movie}
                displayName={displayName}
                onOpen={() => onOpenTitle(String(item.external_id))}
              />
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

function TitleCard({
  item,
  movie,
  displayName,
  onOpen,
}: {
  item: LibraryItem;
  movie: boolean;
  displayName: string;
  onOpen: () => void;
}) {
  const sentence = itemSentence(item, displayName);
  const outOfSync = item.sync_state === "out_of_sync";
  const upgrade = hasUpgrade(item);
  return (
    <li className="min-w-0">
      <button
        type="button"
        onClick={onOpen}
        title={sentence}
        // The focus ring is drawn on the poster (see `TitlePoster`), not round
        // the whole card, so keyboard and pointer land on the same picture.
        className="group/card flex w-full flex-col gap-1.5 rounded-lg text-left outline-none"
      >
        <TitlePoster
          src={item.poster}
          movie={movie}
          interactive
          className={cn(
            "w-full",
            // A second cue beside the chip, so a problem stands out in a
            // screen of posters; the chip still carries the word.
            outOfSync && "border-amber-500/60"
          )}
        />
        <span className="line-clamp-2 text-[12px] leading-tight font-medium text-foreground transition-colors duration-200 group-hover/card:text-brand-foreground">
          {item.title ?? "Untitled"}
          {item.year ? (
            <span className="font-normal text-muted-foreground"> ({item.year})</span>
          ) : null}
        </span>
        <span className="flex flex-wrap items-center gap-1">
          <TitleStateChip state={item.sync_state} size="sm" />
          {upgrade && <ToneChip tone="info" icon={IconCircleArrowUp} label="Upgrade" size="sm" />}
        </span>
        <CountsLine item={item} movie={movie} displayName={displayName} />
      </button>
    </li>
  );
}

/** "Sonarr 1 · here 7" — Specials left out on both sides, as from the verdict. */
function CountsLine({
  item,
  movie,
  displayName,
}: {
  item: LibraryItem;
  movie: boolean;
  displayName: string;
}) {
  const theirs = movie
    ? item.service_has_files
      ? formatSize(item.service_file_size)
      : "none"
    : String(item.service_files_counted ?? 0);
  const ours = movie
    ? item.present_locally
      ? formatSize(item.local_file_size)
      : "none"
    : String(item.episodes_here ?? 0);
  // The quiet note for kept-here: in sync, and the extra episodes here are
  // the media server having cleaned up after a sync — said on hover, not
  // with a second badge.
  const kept = item.sync_state === "kept_here" && item.kept_here_count > 0;
  return (
    <span className="flex flex-wrap gap-x-1 text-[10.5px] leading-tight text-muted-foreground">
      <span className="whitespace-nowrap">
        {displayName} <span className="font-mono text-foreground-2 tabular-nums">{theirs}</span>
      </span>
      <span aria-hidden>·</span>
      <span
        className={cn(
          "whitespace-nowrap",
          kept && "underline decoration-muted-foreground/50 decoration-dotted underline-offset-2"
        )}
        title={
          kept
            ? `${item.kept_here_count} kept only here, which is normal once the media server removes its copies after a sync`
            : undefined
        }
      >
        here <span className="font-mono text-foreground-2 tabular-nums">{ours}</span>
      </span>
    </span>
  );
}

function GridSkeleton() {
  return (
    <ul className="grid grid-cols-3 gap-x-3 gap-y-4 p-3 sm:grid-cols-[repeat(auto-fill,minmax(96px,1fr))] sm:p-4">
      {Array.from({ length: 18 }).map((_, i) => (
        <li key={i} className="space-y-1.5">
          <Skeleton className="aspect-[2/3] w-full rounded-md" />
          <Skeleton className="h-3 w-4/5" />
          <Skeleton className="h-3 w-1/2" />
        </li>
      ))}
    </ul>
  );
}
