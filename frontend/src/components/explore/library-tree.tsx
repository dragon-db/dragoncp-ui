import { IconChevronRight, IconFolder, IconMovie, IconStack2 } from "@tabler/icons-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { StatusBadge } from "./explore-bits";
import { formatAge, formatBytes } from "@/lib/explore-format";
import type { ExploreSeriesSummary } from "@/lib/explore-types";

/**
 * The library tree.
 *
 * Two right-hand columns do the alignment work: the sync badge sits at the
 * panel's right edge and the size sits directly under it, at every depth, so
 * status reads as one scannable column instead of landing wherever each title
 * happens to end.
 *
 * Seasons hang off their series on a thread line (see `.explore-*` in
 * index.css). Clicking a series selects it and toggles its seasons; clicking
 * the thread collapses the branch; the chevron toggles without moving the
 * selection.
 */

interface LibraryTreeProps {
  className?: string;
  /** Movies have no season layer, so their rows are leaves. */
  flat?: boolean;
  series: ExploreSeriesSummary[];
  total: number;
  loading: boolean;
  focused: boolean;
  expanded: Set<string>;
  selectedSeries: string | null;
  selectedSeason: string | null;
  onToggle: (name: string) => void;
  onSelectSeries: (name: string) => void;
  onSelectSeason: (series: string, season: string) => void;
  onCollapseAll: () => void;
  emptyMessage: string;
}

export function LibraryTree({
  className,
  flat = false,
  series,
  total,
  loading,
  focused,
  expanded,
  selectedSeries,
  selectedSeason,
  onToggle,
  onSelectSeries,
  onSelectSeason,
  onCollapseAll,
  emptyMessage,
}: LibraryTreeProps) {
  return (
    <aside
      className={cn(
        "flex min-w-0 flex-col border-r border-border bg-sidebar explore-thread",
        "w-full lg:w-[404px] lg:flex-none",
        className
      )}
    >
      <div className="flex h-[34px] flex-none items-center gap-2 border-b border-border bg-well px-[13px]">
        <span
          className={cn(
            "font-display text-[11px] font-semibold tracking-[0.14em] uppercase",
            focused ? "text-brand-hover" : "text-foreground-3"
          )}
        >
          Library
        </span>
        <span className="ml-auto font-mono text-[10.5px] text-foreground-3">
          {series.length === total ? total : `${series.length} / ${total}`}
        </span>
        <button
          type="button"
          onClick={onCollapseAll}
          title={expanded.size ? "Collapse all" : "Expand all"}
          className="grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <IconChevronRight
            className={cn("size-3.5 transition-transform", expanded.size && "rotate-90")}
          />
        </button>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="p-1.5">
          {loading ? (
            <div className="flex flex-col gap-1.5 p-1">
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <Skeleton key={n} className="h-11 w-full" />
              ))}
            </div>
          ) : series.length === 0 ? (
            <p className="px-3 py-8 text-center text-xs text-muted-foreground">{emptyMessage}</p>
          ) : (
            series.map((entry) => {
              const isOpen = !flat && expanded.has(entry.name);
              const inBranch = selectedSeries === entry.name;
              const seriesSelected = inBranch && !selectedSeason;
              const seasons = entry.seasons ?? [];

              return (
                <div
                  key={entry.name}
                  className="explore-group"
                  data-open={isOpen}
                  data-active={inBranch}
                >
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelectSeries(entry.name)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectSeries(entry.name);
                      }
                    }}
                    className={cn(
                      "explore-row relative flex cursor-pointer items-start gap-[9px] rounded-[7px] py-1.5 pr-2.5 pl-1.5",
                      "hover:bg-accent",
                      seriesSelected && "bg-brand/20 shadow-[inset_0_0_0_1px_var(--brand)]",
                      inBranch && !seriesSelected && "bg-brand/7"
                    )}
                  >
                    {flat ? (
                      // A movie has nothing to expand, so the chevron's slot
                      // would sit empty down the whole list. Mark the kind of
                      // thing it is instead of leaving a column of nothing.
                      <IconMovie
                        aria-hidden
                        className={cn(
                          "mt-[3px] size-3.5 flex-none",
                          inBranch ? "text-brand-hover" : "text-foreground-3"
                        )}
                      />
                    ) : (
                      <button
                        type="button"
                        aria-label={isOpen ? `Collapse ${entry.name}` : `Expand ${entry.name}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          onToggle(entry.name);
                        }}
                        className="mt-[3px] flex-none text-muted-foreground"
                      >
                        <IconChevronRight
                          className={cn("size-3.5 transition-transform", isOpen && "rotate-90")}
                        />
                      </button>
                    )}
                    <IconFolder
                      className={cn(
                        "mt-0.5 size-4 flex-none",
                        inBranch ? "text-brand-hover" : "text-muted-foreground"
                      )}
                    />
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <span
                          className={cn(
                            "min-w-0 flex-1 truncate text-[13px]",
                            seriesSelected ? "font-semibold text-foreground" : "text-foreground-2"
                          )}
                        >
                          {entry.name}
                        </span>
                        <StatusBadge status={entry.status} />
                      </div>
                      <div className="flex items-baseline gap-2.5 font-mono text-[10px] text-foreground-3">
                        <span className="min-w-0 flex-1 truncate">
                          {flat ? (
                            `${entry.counts.remote_total} file${entry.counts.remote_total === 1 ? "" : "s"}`
                          ) : (
                            <>
                              {entry.season_count} season{entry.season_count === 1 ? "" : "s"}
                              <span className="px-1 opacity-40">·</span>
                              {entry.counts.remote_total} eps
                            </>
                          )}
                          <span className="px-1 opacity-40">·</span>
                          {formatAge(entry.remote_mtime)}
                        </span>
                        <span className="flex-none text-foreground-2">
                          {formatBytes(entry.remote_bytes)}
                        </span>
                      </div>
                    </div>
                  </div>

                  {isOpen && (
                    <div className="relative ml-[30px] pl-[21px]">
                      <button
                        type="button"
                        aria-label={`Collapse ${entry.name}`}
                        onClick={() => onToggle(entry.name)}
                        className="explore-thread-hit absolute top-0 bottom-0 left-0 w-4 cursor-pointer"
                      />
                      {seasons.length === 0 ? (
                        <p className="py-2 text-[11px] text-muted-foreground">No seasons</p>
                      ) : (
                        seasons.map((season) => {
                          const selected = inBranch && selectedSeason === season.name;
                          return (
                            <div key={season.name} className="explore-kid">
                              <div
                                role="button"
                                tabIndex={0}
                                onClick={() => onSelectSeason(entry.name, season.name)}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    onSelectSeason(entry.name, season.name);
                                  }
                                }}
                                className={cn(
                                  "explore-row relative flex cursor-pointer items-start gap-[9px] rounded-[7px] py-1.5 pr-2.5 pl-1.5",
                                  "hover:bg-accent",
                                  selected && "bg-brand/20 shadow-[inset_0_0_0_1px_var(--brand)]"
                                )}
                              >
                                <IconStack2
                                  className={cn(
                                    "mt-0.5 size-4 flex-none",
                                    inBranch ? "text-brand-hover" : "text-muted-foreground"
                                  )}
                                />
                                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                                  <div className="flex min-w-0 items-center gap-2.5">
                                    <span
                                      className={cn(
                                        "min-w-0 flex-1 truncate text-[13px]",
                                        selected
                                          ? "font-semibold text-foreground"
                                          : "text-foreground-2"
                                      )}
                                    >
                                      {season.name}
                                    </span>
                                    <StatusBadge status={season.status} />
                                  </div>
                                  <div className="flex items-baseline gap-2.5 font-mono text-[10px] text-foreground-3">
                                    <span className="min-w-0 flex-1 truncate">
                                      {season.counts.remote_total} eps
                                      <span className="px-1 opacity-40">·</span>
                                      {formatAge(season.remote_mtime)}
                                    </span>
                                    <span className="flex-none text-foreground-2">
                                      {formatBytes(season.remote_bytes)}
                                    </span>
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>
    </aside>
  );
}
