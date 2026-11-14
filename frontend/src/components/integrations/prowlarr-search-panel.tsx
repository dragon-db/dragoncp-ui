import { useDeferredValue, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  IconAdjustmentsHorizontal,
  IconAlertTriangle,
  IconChevronDown,
  IconChevronUp,
  IconClock,
  IconDeviceTv,
  IconLoader2,
  IconRefresh,
  IconMovie,
  IconPlus,
  IconSearch,
  IconWorldSearch,
  IconX,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Notice } from "@/components/integrations/library-bits";
import { formatSize, libraryError, sinceText } from "@/components/integrations/library-vocab";
import {
  CATEGORIES,
  EMPTY_FILTER,
  RESOLUTIONS,
  SORTS,
  activeFilters,
  ageText,
  filterReleases,
  isFree,
  qualityTokens,
  sortReleases,
  toggle,
  type ResultFilter,
  type SortKey,
} from "@/components/integrations/prowlarr-vocab";
import {
  CategoryPills,
  HealthDot,
  OptionRow,
  ProtocolMark,
  QualityChips,
  Segmented,
  ToggleChips,
} from "@/components/integrations/prowlarr-bits";
import { ReleaseSheet } from "@/components/integrations/prowlarr-release-sheet";
import { useProwlarrOverview } from "@/hooks/useProwlarr";
import { useProwlarrSearch, useRecentSearches } from "@/stores/prowlarr-search";
import type {
  ProwlarrIndexer,
  ProwlarrRelease,
  Scope,
  SearchRequest,
  SearchType,
} from "@/lib/prowlarr-types";

/** Rows drawn at first, and added by each "Show more". A thousand cards at once
 *  is what makes a phone stutter; nobody reads past the first screens anyway. */
const PAGE = 60;

const SCOPES: { value: Scope; label: string }[] = [
  { value: "all", label: "All indexers" },
  { value: "torrent", label: "Torrent" },
  { value: "usenet", label: "Usenet" },
  { value: "picked", label: "Pick…" },
];

/**
 * Prowlarr's search, built for a phone: one box, what to search, where, and
 * the results as each indexer answers. Sorting and filtering the results
 * happen here on the device, so they are instant and ask Prowlarr nothing.
 */
export function ProwlarrSearchPanel({ onOpenSettings }: { onOpenSettings: () => void }) {
  const overview = useProwlarrOverview();
  const search = useProwlarrSearch();
  const recent = useRecentSearches();
  const last = search.request;

  const [query, setQuery] = useState(last?.query ?? "");
  const [mode, setMode] = useState<SearchType>(last?.type ?? "search");
  const [scope, setScope] = useState<Scope>(last?.scope ?? "all");
  const [picked, setPicked] = useState<number[]>(last?.indexer_ids ?? []);
  const [categories, setCategories] = useState<number[]>(last?.categories ?? []);
  const [season, setSeason] = useState(last?.season ?? "");
  const [episode, setEpisode] = useState(last?.episode ?? "");
  const [imdb, setImdb] = useState(last?.imdb_id ?? "");
  const [extraId, setExtraId] = useState(last?.tvdb_id ?? last?.tmdb_id ?? "");
  const [pickerOpen, setPickerOpen] = useState(false);
  // Ids are rarely needed, so their boxes stay folded until asked for.
  const [showIds, setShowIds] = useState(Boolean(last?.imdb_id || last?.tvdb_id || last?.tmdb_id));
  // What, where and which categories fold into one line once there are
  // results, so the first ones are on screen on a phone without scrolling.
  const [optionsOpen, setOptionsOpen] = useState(!last);

  const [sort, setSort] = useState<SortKey>("seeders");
  const [filter, setFilter] = useState<ResultFilter>(EMPTY_FILTER);
  const [filterOpen, setFilterOpen] = useState(false);
  const [shown, setShown] = useState(PAGE);
  const [openId, setOpenId] = useState<number | null>(null);

  const indexers = useMemo(
    () => (overview.data?.indexers ?? []).filter((i) => i.enabled),
    [overview.data?.indexers]
  );

  const build = (fresh = false): SearchRequest => ({
    query: query.trim(),
    type: mode,
    scope,
    indexer_ids: scope === "picked" ? picked : undefined,
    categories: categories.length ? categories : undefined,
    season: mode === "tvsearch" && season ? season : undefined,
    episode: mode === "tvsearch" && episode ? episode : undefined,
    imdb_id: mode !== "search" && imdb ? imdb : undefined,
    tvdb_id: mode === "tvsearch" && extraId ? extraId : undefined,
    tmdb_id: mode === "movie" && extraId ? extraId : undefined,
    fresh: fresh || undefined,
  });

  const run = (request: SearchRequest) => {
    setShown(PAGE);
    setOpenId(null);
    setOptionsOpen(false);
    void search.start(request);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    // Drop the keyboard so the first results are visible on a phone.
    (document.activeElement as HTMLElement | null)?.blur?.();
    run(build());
  };

  const reuse = (request: SearchRequest) => {
    setQuery(request.query);
    setMode(request.type);
    setScope(request.scope);
    setPicked(request.indexer_ids ?? []);
    setCategories(request.categories ?? []);
    setSeason(request.season ?? "");
    setEpisode(request.episode ?? "");
    setImdb(request.imdb_id ?? "");
    setExtraId(request.tvdb_id ?? request.tmdb_id ?? "");
    run(request);
  };

  // Typing in the result filter stays smooth with thousands of rows: the list
  // follows the text a beat behind instead of on every key.
  const deferredFilter = useDeferredValue(filter);
  const visible = useMemo(
    () => sortReleases(filterReleases(search.releases, deferredFilter), sort),
    [search.releases, deferredFilter, sort]
  );
  const open = openId != null ? (search.releases.find((r) => r.id === openId) ?? null) : null;
  const filtersOn = activeFilters(filter);

  if (overview.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (overview.isError || (overview.data && overview.data.state !== "ok")) {
    return (
      <Notice tone="crit" icon={IconAlertTriangle}>
        <span>
          {overview.data?.message || libraryError(overview.error, "Could not reach Prowlarr.")}{" "}
        </span>
        <button
          type="button"
          onClick={onOpenSettings}
          className="font-medium text-foreground underline-offset-2 hover:underline"
        >
          Open Connection
        </button>
      </Notice>
    );
  }

  const searching = search.starting || search.running;

  return (
    <div className="space-y-3">
      <form onSubmit={submit} className="space-y-2.5" role="search">
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1">
            <IconSearch className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              inputMode="search"
              enterKeyHint="search"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={
                mode === "tvsearch"
                  ? "Series name"
                  : mode === "movie"
                    ? "Film name"
                    : "Search every indexer"
              }
              aria-label="Search for"
              className="h-11 pl-9 text-base sm:text-sm"
            />
          </div>
          <Button type="submit" className="h-11 px-4" disabled={search.starting}>
            {searching ? (
              <IconLoader2 className="size-4 animate-spin" />
            ) : (
              <IconSearch className="size-4" />
            )}
            <span className="hidden sm:inline">Search</span>
          </Button>
        </div>

        {optionsOpen ? (
          <div className="divide-y divide-border/60 rounded-xl border border-border/70 bg-card/40">
            <OptionRow label="Type">
              <Segmented
                label="Search for"
                value={mode}
                onChange={setMode}
                items={[
                  { value: "search", label: "Anything", icon: IconWorldSearch },
                  { value: "tvsearch", label: "TV show", icon: IconDeviceTv },
                  { value: "movie", label: "Film", icon: IconMovie },
                ]}
              />
            </OptionRow>

            {mode === "tvsearch" && (
              <OptionRow label="Episode">
                <div className="flex items-center gap-3">
                  <SmallNumber label="Season" value={season} onChange={setSeason} />
                  <SmallNumber label="Episode" value={episode} onChange={setEpisode} />
                </div>
              </OptionRow>
            )}

            {mode !== "search" && (
              <OptionRow label="Id">
                {showIds ? (
                  <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto">
                    <Input
                      value={imdb}
                      onChange={(event) => setImdb(event.target.value.trim())}
                      placeholder="IMDb tt0000000"
                      aria-label="IMDb id"
                      autoCapitalize="off"
                      className="h-9 font-mono text-base sm:h-8 sm:w-40 sm:text-xs"
                    />
                    <Input
                      value={extraId}
                      onChange={(event) => setExtraId(event.target.value.replace(/\D/g, ""))}
                      inputMode="numeric"
                      placeholder={mode === "tvsearch" ? "TVDB id" : "TMDB id"}
                      aria-label={mode === "tvsearch" ? "TVDB id" : "TMDB id"}
                      className="h-9 font-mono text-base sm:h-8 sm:w-32 sm:text-xs"
                    />
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowIds(true)}
                    className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-dashed border-border px-3 text-[12.5px] font-medium text-muted-foreground hover:text-foreground sm:h-8 sm:text-xs"
                  >
                    <IconPlus className="size-3.5" />
                    Add an IMDb or {mode === "tvsearch" ? "TVDB" : "TMDB"} id
                  </button>
                )}
              </OptionRow>
            )}

            <OptionRow label="Indexers">
              <Segmented
                label="Which indexers"
                value={scope}
                onChange={(next) => {
                  setScope(next);
                  if (next === "picked") setPickerOpen(true);
                }}
                onReselect={(value) => value === "picked" && setPickerOpen(true)}
                items={[
                  { value: "all", label: "All" },
                  { value: "torrent", label: "Torrent" },
                  { value: "usenet", label: "Usenet" },
                  {
                    value: "picked",
                    label: "Pick",
                    count: scope === "picked" && picked.length ? picked.length : undefined,
                  },
                ]}
              />
            </OptionRow>

            <OptionRow label="Category">
              <CategoryPills
                selected={categories}
                onToggle={(id) => setCategories((list) => toggle(list, id))}
                onAll={() => setCategories([])}
              />
            </OptionRow>

            {search.request && (
              <div className="flex justify-end px-3 py-1.5">
                <button
                  type="button"
                  onClick={() => setOptionsOpen(false)}
                  className="inline-flex h-8 items-center gap-1 text-[12px] font-medium text-muted-foreground hover:text-foreground"
                >
                  Hide options
                  <IconChevronUp className="size-3.5" />
                </button>
              </div>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setOptionsOpen(true)}
            aria-expanded={false}
            className="flex w-full items-center gap-2 rounded-lg border border-border/70 px-3 py-2 text-left text-[12.5px] text-muted-foreground hover:text-foreground"
          >
            <span className="min-w-0 flex-1 truncate">
              {[requestWhere(build()), episodeText(build())].filter(Boolean).join(" · ")}
            </span>
            <span className="shrink-0 font-medium text-foreground-2">Change</span>
            <IconChevronDown className="size-3.5 shrink-0" />
          </button>
        )}
      </form>

      {!search.request && recent.recent.length > 0 && (
        <RecentSearches
          items={recent.recent}
          onPick={reuse}
          onForget={(index) => recent.forget(index)}
        />
      )}

      {search.error && (
        <Notice tone="crit" icon={IconAlertTriangle}>
          {search.error}
        </Notice>
      )}

      {search.request && !search.error && (
        <>
          <Progress
            indexers={search.indexers}
            starting={search.starting}
            running={search.running}
            reused={search.reused}
            serverStarted={search.serverStarted}
            startedAt={search.startedAt}
            finishedAt={search.finishedAt}
            onAgain={() => run({ ...search.request!, fresh: true })}
          />

          {search.releases.length > 0 && (
            <div className="sticky -top-4 z-10 -mx-4 flex items-center gap-2 border-b border-border/60 bg-background/95 px-4 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/85 sm:-top-6 sm:-mx-6 sm:px-6 xl:-top-7 xl:-mx-8 xl:px-8">
              {/* Pinned flush under the top bar. The page scrolls inside a
                  padded box, and `top-0` stopped the bar one padding below its
                  edge with results showing through above it; the negative top
                  and side margins match that padding (p-4, sm:p-6, xl:px-8 py-7). */}
              <div className="relative min-w-0 flex-1">
                <Input
                  value={filter.text}
                  onChange={(event) => setFilter((f) => ({ ...f, text: event.target.value }))}
                  placeholder="Filter words"
                  aria-label="Filter results by words"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  className="h-9 pr-8 text-base sm:text-sm"
                />
                {filter.text && (
                  <button
                    type="button"
                    aria-label="Clear the word filter"
                    onClick={() => setFilter((f) => ({ ...f, text: "" }))}
                    className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <IconX className="size-4" />
                  </button>
                )}
              </div>
              <Select
                items={SORTS.map((s) => ({ value: s.value, label: s.label }))}
                value={sort}
                onValueChange={(next) => next && setSort(next as SortKey)}
              >
                <SelectTrigger className="h-9 w-[8.5rem] shrink-0" aria-label="Order">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SORTS.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="outline"
                className="relative h-9 shrink-0 px-2.5"
                onClick={() => setFilterOpen(true)}
                aria-label={filtersOn ? `Filters, ${filtersOn} on` : "Filters"}
              >
                <IconAdjustmentsHorizontal className="size-4" />
                {filtersOn > 0 && (
                  <span className="absolute -top-1.5 -right-1.5 flex size-4 items-center justify-center rounded-full bg-brand text-[10px] font-bold text-white">
                    {filtersOn}
                  </span>
                )}
              </Button>
            </div>
          )}

          {search.releases.length > 0 && (
            <p className="text-[12px] text-muted-foreground">
              {visible.length === search.releases.length
                ? `${search.releases.length.toLocaleString()} results`
                : `${visible.length.toLocaleString()} of ${search.releases.length.toLocaleString()} results`}
              {(filtersOn > 0 || filter.text) && (
                <button
                  type="button"
                  onClick={() => setFilter(EMPTY_FILTER)}
                  className="ml-2 font-medium text-foreground underline-offset-2 hover:underline"
                >
                  Clear filters
                </button>
              )}
            </p>
          )}

          {visible.length > 0 ? (
            <>
              <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/70 bg-card/60">
                {visible.slice(0, shown).map((release) => (
                  <ReleaseRow
                    key={release.id}
                    release={release}
                    onOpen={() => setOpenId(release.id)}
                  />
                ))}
              </ul>
              {visible.length > shown && (
                <Button
                  variant="outline"
                  className="h-10 w-full"
                  onClick={() => setShown((n) => n + PAGE)}
                >
                  Show {Math.min(PAGE, visible.length - shown)} more of{" "}
                  {(visible.length - shown).toLocaleString()}
                </Button>
              )}
            </>
          ) : (
            !searching &&
            search.searchId && (
              <p className="rounded-xl border border-border/70 bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
                {search.releases.length
                  ? "Nothing matches these filters."
                  : "No indexer found anything. Try fewer words, another category, or All indexers."}
              </p>
            )
          )}
        </>
      )}

      <IndexerPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        indexers={indexers}
        picked={picked}
        onChange={setPicked}
        onDone={() => {
          setPickerOpen(false);
          if (!picked.length) setScope("all");
        }}
      />
      <FilterSheet
        open={filterOpen}
        onOpenChange={setFilterOpen}
        filter={filter}
        onChange={setFilter}
        releases={search.releases}
      />
      <ReleaseSheet
        release={open}
        searchId={search.searchId}
        clients={overview.data?.download_clients ?? []}
        canGrab={overview.data?.can_grab ?? false}
        whyNot={overview.data?.why_not ?? ""}
        onClose={() => setOpenId(null)}
      />
    </div>
  );
}

function SmallNumber({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
      {label}
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value.replace(/\D/g, "").slice(0, 4))}
        inputMode="numeric"
        pattern="[0-9]*"
        placeholder="–"
        className="h-9 w-16 text-center font-mono text-base sm:h-8 sm:w-14 sm:text-xs"
      />
    </label>
  );
}

function RecentSearches({
  items,
  onPick,
  onForget,
}: {
  items: SearchRequest[];
  onPick: (request: SearchRequest) => void;
  onForget: (index: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        <IconClock className="size-3.5" />
        Recent
      </p>
      <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/70 bg-card/60">
        {items.map((item, index) => (
          <li key={index} className="flex items-center">
            <button
              type="button"
              onClick={() => onPick(item)}
              className="min-w-0 flex-1 px-3.5 py-2.5 text-left hover:bg-muted/40"
            >
              <span className="block truncate text-[13.5px] text-foreground">
                {describeRequest(item)}
              </span>
              <span className="block truncate text-[11.5px] text-muted-foreground">
                {requestWhere(item)}
              </span>
            </button>
            <button
              type="button"
              aria-label="Forget this search"
              onClick={() => onForget(index)}
              className="flex size-11 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
            >
              <IconX className="size-4" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function describeRequest(request: SearchRequest) {
  return [request.query || "(by id)", episodeText(request)].filter(Boolean).join(" ");
}

/** "S01E02", "S01", or "". */
function episodeText(request: SearchRequest) {
  if (!request.season) return "";
  const season = `S${request.season.padStart(2, "0")}`;
  return request.episode ? `${season}E${request.episode.padStart(2, "0")}` : season;
}

function requestWhere(request: SearchRequest) {
  const mode =
    request.type === "tvsearch"
      ? "TV search"
      : request.type === "movie"
        ? "Film search"
        : "Any search";
  const where =
    request.scope === "picked"
      ? `${request.indexer_ids?.length ?? 0} indexers`
      : (SCOPES.find((s) => s.value === request.scope)?.label ?? "All indexers");
  const cats = (request.categories ?? [])
    .map((id) => CATEGORIES.find((c) => c.id === id)?.label)
    .filter(Boolean)
    .join(", ");
  return [mode, where, cats].filter(Boolean).join(" · ");
}

/**
 * How the search is going, one indexer at a time: a bar while it runs, then
 * a line saying who answered. Tapping it lists every indexer with what it
 * found, how long it took, or why it failed.
 */
function Progress({
  indexers,
  starting,
  running,
  reused,
  serverStarted,
  startedAt,
  finishedAt,
  onAgain,
}: {
  indexers: {
    id: number;
    name: string;
    state: string;
    count: number;
    ms: number | null;
    error: string | null;
  }[];
  starting: boolean;
  running: boolean;
  reused: boolean;
  serverStarted: string | null;
  startedAt: number | null;
  finishedAt: number | null;
  onAgain: () => void;
}) {
  const [open, setOpen] = useState(false);
  const asked = indexers.filter((i) => i.state !== "skipped");
  const answered = asked.filter((i) => i.state === "done" || i.state === "failed").length;
  const failed = asked.filter((i) => i.state === "failed").length;
  const skipped = indexers.length - asked.length;
  const percent = asked.length ? Math.round((answered / asked.length) * 100) : 0;
  const seconds =
    startedAt && finishedAt ? Math.max(0.1, (finishedAt - startedAt) / 1000).toFixed(1) : null;

  if (starting) {
    return (
      <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
        <IconLoader2 className="size-3.5 animate-spin" />
        Asking Prowlarr…
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border/70 bg-card/60">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 text-left text-[12.5px]"
        >
          {running ? (
            <IconLoader2 className="size-3.5 shrink-0 animate-spin text-brand-hover" />
          ) : failed ? (
            <IconAlertTriangle className="size-3.5 shrink-0 text-amber-400" />
          ) : (
            <span aria-hidden className="size-2 shrink-0 rounded-full bg-emerald-400" />
          )}
          <span className="min-w-0 truncate text-foreground-2">
            {running
              ? `${answered} of ${asked.length} indexers answered`
              : `${answered - failed} of ${asked.length} answered${
                  reused && serverStarted
                    ? ` · from ${sinceText(serverStarted)}`
                    : seconds
                      ? ` in ${seconds}s`
                      : ""
                }`}
            {failed > 0 && <span className="text-amber-400"> · {failed} failed</span>}
            {skipped > 0 && <span className="text-muted-foreground"> · {skipped} skipped</span>}
          </span>
          <IconChevronDown
            className={cn(
              "ml-auto size-3.5 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-180"
            )}
          />
        </button>
        {!running && (
          <Button size="sm" variant="ghost" onClick={onAgain} className="shrink-0">
            <IconRefresh className="size-3.5" />
            Again
          </Button>
        )}
      </div>
      {running && (
        <div className="mx-3 mb-2 h-1 overflow-hidden rounded-full bg-white/8">
          <div
            className="h-full rounded-full bg-brand-gradient-x transition-[width] duration-300"
            style={{ width: `${Math.max(4, percent)}%` }}
          />
        </div>
      )}
      {open && (
        <ul className="divide-y divide-border/50 border-t border-border/60 text-[12.5px]">
          {indexers.map((row) => (
            <li key={row.id} className="flex items-start gap-2 px-3 py-2">
              <span
                aria-hidden
                className={cn(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  row.state === "done"
                    ? "bg-emerald-400"
                    : row.state === "failed"
                      ? "bg-rose-400"
                      : row.state === "skipped"
                        ? "bg-muted-foreground/50"
                        : "animate-pulse bg-brand-hover"
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-medium text-foreground-2">{row.name}</span>
                  <span className="shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums">
                    {row.state === "done"
                      ? `${row.count} · ${row.ms != null ? (row.ms / 1000).toFixed(1) + "s" : ""}`
                      : row.state === "waiting"
                        ? "waiting"
                        : row.state}
                  </span>
                </div>
                {row.error && (
                  <p
                    className={cn(
                      "text-[11.5px] [overflow-wrap:anywhere]",
                      row.state === "failed" ? "text-rose-300" : "text-muted-foreground"
                    )}
                  >
                    {row.error}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** One result: its name, what quality the name says, and the numbers that decide. */
function ReleaseRow({ release, onOpen }: { release: ProwlarrRelease; onOpen: () => void }) {
  const tokens = qualityTokens(release.title);
  const dead = release.protocol === "torrent" && (release.seeders ?? 0) === 0;
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="block w-full space-y-1.5 px-3.5 py-3 text-left transition-colors hover:bg-muted/40 active:bg-muted/60"
      >
        <p className="text-[13.5px] leading-snug [overflow-wrap:anywhere] text-foreground">
          {release.title}
        </p>
        <div className="flex flex-wrap items-center gap-1">
          <QualityChips tokens={tokens} />
          {isFree(release) && (
            <span className="rounded-md border border-emerald-500/30 px-1.5 py-px text-[10.5px] leading-4 font-semibold text-emerald-300">
              FL
            </span>
          )}
          {release.grabbed && (
            <span className="rounded-md bg-emerald-500/15 px-1.5 py-px text-[10.5px] leading-4 font-semibold text-emerald-300">
              Sent
            </span>
          )}
        </div>
        <div className="flex items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground tabular-nums">
          <ProtocolMark protocol={release.protocol} />
          <span className="font-medium text-foreground-2">{formatSize(release.size)}</span>
          {release.published && <span>{ageText(release.published)}</span>}
          {release.protocol === "torrent" ? (
            <span className={cn(dead && "text-rose-400")}>
              <span className={cn(!dead && "text-emerald-400")}>▲{release.seeders ?? "?"}</span> ▼
              {release.leechers ?? "?"}
            </span>
          ) : release.grabs != null ? (
            <span>{release.grabs.toLocaleString()} grabs</span>
          ) : null}
          <span className="ml-auto min-w-0 truncate text-right">{release.indexer}</span>
        </div>
      </button>
    </li>
  );
}

function IndexerPicker({
  open,
  onOpenChange,
  indexers,
  picked,
  onChange,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  indexers: ProwlarrIndexer[];
  picked: number[];
  onChange: (ids: number[]) => void;
  onDone: () => void;
}) {
  const groups: { label: string; items: ProwlarrIndexer[] }[] = [
    { label: "Torrent", items: indexers.filter((i) => i.protocol === "torrent") },
    { label: "Usenet", items: indexers.filter((i) => i.protocol === "usenet") },
  ].filter((g) => g.items.length);
  return (
    <Sheet open={open} onOpenChange={(next) => (next ? onOpenChange(true) : onDone())}>
      <SheetContent
        side="bottom"
        className="max-h-[85dvh] gap-0 rounded-t-2xl sm:mx-auto sm:max-w-lg sm:rounded-2xl sm:border data-[side=bottom]:sm:bottom-4"
      >
        <SheetHeader className="px-4 pt-4 pb-2">
          <SheetTitle>Pick indexers</SheetTitle>
          <SheetDescription>Only these are asked. Paused ones are skipped.</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-3">
          {groups.map((group) => {
            const ids = group.items.map((i) => i.id);
            const all = ids.every((id) => picked.includes(id));
            return (
              <div key={group.label} className="space-y-1">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                    {group.label}
                  </p>
                  <button
                    type="button"
                    onClick={() =>
                      onChange(
                        all
                          ? picked.filter((id) => !ids.includes(id))
                          : [...new Set([...picked, ...ids])]
                      )
                    }
                    className="text-xs font-medium text-brand-hover"
                  >
                    {all ? "None" : "All"}
                  </button>
                </div>
                <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/70">
                  {group.items.map((indexer) => {
                    const on = picked.includes(indexer.id);
                    return (
                      <li key={indexer.id}>
                        <button
                          type="button"
                          role="checkbox"
                          aria-checked={on}
                          onClick={() => onChange(toggle(picked, indexer.id))}
                          className="flex h-11 w-full items-center gap-2.5 px-3 text-left text-[13.5px] hover:bg-muted/40"
                        >
                          <span
                            className={cn(
                              "flex size-4.5 shrink-0 items-center justify-center rounded border text-[11px]",
                              on ? "border-brand bg-brand text-white" : "border-input bg-input/30"
                            )}
                          >
                            {on ? "✓" : ""}
                          </span>
                          <HealthDot state={indexer.state} />
                          <span className="min-w-0 flex-1 truncate">{indexer.name}</span>
                          <span className="text-[11px] text-muted-foreground capitalize">
                            {indexer.privacy === "semiprivate" ? "semi-private" : indexer.privacy}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
        <SheetFooter className="border-t border-border/70 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <Button className="h-11 w-full" onClick={onDone}>
            {picked.length ? `Use ${picked.length} indexers` : "Done"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

const AGES = [
  { value: 1, label: "1 day" },
  { value: 7, label: "1 week" },
  { value: 30, label: "1 month" },
  { value: 365, label: "1 year" },
];
const SEEDERS = [1, 5, 20, 50];

/** Everything that narrows the results without asking again. */
function FilterSheet({
  open,
  onOpenChange,
  filter,
  onChange,
  releases,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filter: ResultFilter;
  onChange: (filter: ResultFilter) => void;
  releases: ProwlarrRelease[];
}) {
  const set = (patch: Partial<ResultFilter>) => onChange({ ...filter, ...patch });
  // Only indexers that found something are worth offering.
  const byIndexer = new Map<number, { name: string; count: number }>();
  for (const release of releases) {
    if (release.indexer_id == null) continue;
    const entry = byIndexer.get(release.indexer_id) ?? { name: release.indexer, count: 0 };
    entry.count += 1;
    byIndexer.set(release.indexer_id, entry);
  }
  const indexers = [...byIndexer.entries()].sort((a, b) => b[1].count - a[1].count);
  const protocols = [...new Set(releases.map((r) => r.protocol))];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className="max-h-[85dvh] gap-0 rounded-t-2xl sm:mx-auto sm:max-w-lg sm:rounded-2xl sm:border data-[side=bottom]:sm:bottom-4"
      >
        <SheetHeader className="px-4 pt-4 pb-2">
          <SheetTitle>Filter results</SheetTitle>
          <SheetDescription>Narrows what was found. Prowlarr is not asked again.</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-3">
          {protocols.length > 1 && (
            <Field label="Kind">
              <ToggleChips
                label="Kind"
                items={protocols.map((p) => ({
                  value: p,
                  label: p === "torrent" ? "Torrent" : p === "usenet" ? "Usenet" : "Other",
                }))}
                selected={filter.protocols}
                onToggle={(p) => set({ protocols: toggle(filter.protocols, p) })}
              />
            </Field>
          )}
          <Field label="Quality">
            <ToggleChips
              label="Quality"
              items={RESOLUTIONS.map((r) => ({ value: r, label: r }))}
              selected={filter.resolutions}
              onToggle={(r) => set({ resolutions: toggle(filter.resolutions, r) })}
            />
          </Field>
          <Field label="At least this many seeders">
            <ToggleChips
              label="Seeders"
              items={SEEDERS.map((n) => ({ value: n, label: `${n}+` }))}
              selected={filter.minSeeders ? [filter.minSeeders] : []}
              onToggle={(n) => set({ minSeeders: filter.minSeeders === n ? 0 : n })}
            />
          </Field>
          <Field label="No older than">
            <ToggleChips
              label="Age"
              items={AGES}
              selected={filter.maxAgeDays != null ? [filter.maxAgeDays] : []}
              onToggle={(n) => set({ maxAgeDays: filter.maxAgeDays === n ? null : n })}
            />
          </Field>
          <Field label="Size in GB">
            <div className="flex items-center gap-2">
              <GbInput
                label="Smallest size in GB"
                placeholder="min"
                value={filter.minGb}
                onChange={(minGb) => set({ minGb })}
              />
              <span className="text-muted-foreground">to</span>
              <GbInput
                label="Largest size in GB"
                placeholder="max"
                value={filter.maxGb}
                onChange={(maxGb) => set({ maxGb })}
              />
            </div>
          </Field>
          <Field label="Freeleech">
            <ToggleChips
              label="Freeleech"
              items={[{ value: "free", label: "Freeleech only" }]}
              selected={filter.freeOnly ? ["free"] : []}
              onToggle={() => set({ freeOnly: !filter.freeOnly })}
            />
          </Field>
          {indexers.length > 1 && (
            <Field label="Indexer">
              <ToggleChips
                label="Indexer"
                items={indexers.map(([id, entry]) => ({
                  value: id,
                  label: entry.name,
                  count: entry.count,
                }))}
                selected={filter.indexers}
                onToggle={(id) => set({ indexers: toggle(filter.indexers, id) })}
              />
            </Field>
          )}
        </div>
        <SheetFooter className="flex-row gap-2 border-t border-border/70 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <Button
            variant="outline"
            className="h-11 flex-1"
            onClick={() => onChange({ ...EMPTY_FILTER, text: filter.text })}
          >
            Reset
          </Button>
          <Button className="h-11 flex-1" onClick={() => onOpenChange(false)}>
            Show {filterReleases(releases, filter).length.toLocaleString()}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        {label}
      </p>
      {children}
    </div>
  );
}

function GbInput({
  label,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: number | null;
  onChange: (value: number | null) => void;
}) {
  // The box keeps what was typed ("1." on the way to "1.5"); the filter gets the number.
  const [text, setText] = useState(value != null ? String(value) : "");
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    // Changed from outside (Reset): show the new value instead of what was typed.
    setSeen(value);
    if (value == null || Number.parseFloat(text) !== value)
      setText(value == null ? "" : String(value));
  }
  return (
    <Input
      aria-label={label}
      placeholder={placeholder}
      inputMode="decimal"
      value={text}
      onChange={(event) => {
        const next = event.target.value.replace(",", ".").replace(/[^\d.]/g, "");
        setText(next);
        const number = Number.parseFloat(next);
        onChange(next === "" || !Number.isFinite(number) ? null : number);
      }}
      className="h-9 w-24 text-center font-mono text-base sm:text-sm"
    />
  );
}
