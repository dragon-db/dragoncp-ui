import { useMemo, useState } from "react";
import {
  IconAlertTriangle,
  IconCheck,
  IconCloudDownload,
  IconFolderX,
  IconLayoutGrid,
  IconList,
  IconLoader2,
  IconPhotoOff,
  IconRefresh,
  IconSearch,
} from "@tabler/icons-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type LibraryItem,
  type SyncState,
  useLibrary,
  useRefreshLibrary,
  useSyncLibraryItem,
} from "@/hooks/useMediaLibrary";
import { errorText } from "@/lib/api-error";
import { cn } from "@/lib/utils";

/**
 * What the service holds, and what is actually on our disk.
 *
 * Two things this screen learned the hard way, both visible in what it counts:
 *
 * Presence is read from the filesystem, never from the transfer log. The log
 * says what this installation fetched; the question is what is *there*.
 *
 * Titles the service holds no files for are counted apart and not judged. In
 * one real library that is 99 of 129 series — shows added before they air.
 * Calling those "never synced" buried two genuine gaps under a hundred
 * non-problems.
 */

interface StateStyle {
  key: SyncState;
  label: string;
  hint: string;
  chip: string;
  dot: string;
  /** Whether this state is a judgement about syncing at all. */
  judged: boolean;
}

const STATES: StateStyle[] = [
  {
    key: "synced",
    label: "Synced",
    hint: "The service holds files, and so do we",
    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    dot: "bg-emerald-400",
    judged: true,
  },
  {
    key: "partial",
    label: "Partial",
    hint: "It holds files for seasons we do not have",
    chip: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    dot: "bg-amber-400",
    judged: true,
  },
  {
    key: "never",
    label: "Missing",
    hint: "It holds files and we have none of them",
    chip: "border-sky-500/30 bg-sky-500/10 text-sky-300",
    dot: "bg-sky-400",
    judged: true,
  },
  {
    key: "orphan",
    label: "Orphaned",
    hint: "We hold files for a title it no longer lists",
    chip: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    dot: "bg-rose-400",
    judged: true,
  },
  {
    key: "no_files",
    label: "Nothing to sync",
    hint: "Listed there, but it holds no files yet",
    chip: "border-border bg-muted/40 text-muted-foreground",
    dot: "bg-muted-foreground/60",
    judged: false,
  },
  {
    key: "unknown",
    label: "Unknown",
    hint: "The library folders could not be read",
    chip: "border-border bg-muted/40 text-muted-foreground",
    dot: "bg-muted-foreground/60",
    judged: false,
  },
];

function styleFor(state: SyncState): StateStyle {
  return STATES.find((s) => s.key === state) ?? STATES[STATES.length - 1];
}

function Poster({ item }: { item: LibraryItem }) {
  const [failed, setFailed] = useState(false);
  if (!item.poster || failed) {
    return (
      <div className="flex aspect-[2/3] w-full items-center justify-center rounded-lg bg-muted/40">
        <IconPhotoOff className="h-6 w-6 text-muted-foreground/60" />
      </div>
    );
  }
  return (
    <img
      src={item.poster}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="aspect-[2/3] w-full rounded-lg object-cover"
    />
  );
}

/** One pip per season: green where we have files, amber where only they do. */
function SeasonPips({ item, compact = false }: { item: LibraryItem; compact?: boolean }) {
  const seasons = item.seasons.filter((s) => !s.specials || s.episode_file_count > 0);
  if (seasons.length === 0) return null;
  return (
    <div className={cn("flex flex-wrap gap-1", compact ? "mt-1.5" : "mt-2")}>
      {seasons.map((season) => {
        const theyHave = season.episode_file_count > 0;
        const weHave = season.files_here > 0;
        return (
          <span
            key={season.season_number}
            title={
              season.specials
                ? `Specials — ${season.episode_file_count} there, ${season.files_here} here. Not counted towards the state.`
                : `Season ${season.season_number} — ${season.episode_file_count} there, ${season.files_here} here`
            }
            className={cn(
              "rounded px-1.5 py-0.5 font-mono text-[10px] leading-none",
              season.specials
                ? "bg-muted/50 text-muted-foreground"
                : weHave
                  ? "bg-emerald-500/15 text-emerald-300"
                  : theyHave
                    ? "bg-amber-500/15 text-amber-300"
                    : "bg-muted/40 text-muted-foreground"
            )}
          >
            {season.specials ? "SP" : `S${String(season.season_number).padStart(2, "0")}`}
          </span>
        );
      })}
    </div>
  );
}

/**
 * The one-click answer to a pending row.
 *
 * Only rendered on `partial` and `never` — the two states with something to
 * fetch — and it says how many transfers the click amounts to, because "Sync"
 * on a series missing sixteen seasons is sixteen queue entries, and that is
 * worth knowing before pressing rather than after.
 */
function SyncButton({
  item,
  source,
  compact = false,
}: {
  item: LibraryItem;
  source: string;
  compact?: boolean;
}) {
  const sync = useSyncLibraryItem(source);
  if (item.sync_state !== "partial" && item.sync_state !== "never") return null;

  const outstanding = item.seasons.filter((s) => s.counts_towards_state && !s.synced_here).length;
  const count = item.sync_state === "partial" && outstanding > 0 ? outstanding : 1;
  const label = item.sync_state === "partial" ? `Sync missing (${count})` : "Sync";

  const onClick = async (event: React.MouseEvent) => {
    event.stopPropagation();
    try {
      const result = await sync.mutateAsync(item.external_id);
      if (result.success) {
        toast.success(
          `${result.transfers_started ?? 1} sync(s) on their way for ${item.title ?? "this title"} — safety check first, then the queue`
        );
      } else {
        toast.info(result.error ?? "Nothing to fetch any more");
      }
    } catch (error) {
      toast.error(errorText(error, "Could not start the sync"));
    }
  };

  return (
    <Button
      size="sm"
      variant="outline"
      className={cn(
        "border-primary/40 bg-primary/10 hover:bg-primary/20",
        compact ? "h-6 px-2 text-[11px]" : "h-7 px-2.5 text-xs"
      )}
      onClick={onClick}
      disabled={sync.isPending}
      title={
        item.sync_state === "partial"
          ? `Fetch the ${count} season(s) the service holds and this disk does not`
          : "Fetch this title"
      }
    >
      {sync.isPending ? (
        <IconLoader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <IconCloudDownload className="h-3.5 w-3.5" />
      )}
      {label}
    </Button>
  );
}

function GridCard({ item, source }: { item: LibraryItem; source: string }) {
  const style = styleFor(item.sync_state);
  return (
    <li className="group relative">
      <div className="relative overflow-hidden rounded-lg border border-border/70">
        <Poster item={item} />
        <span
          title={style.hint}
          className={cn(
            "absolute top-1.5 left-1.5 flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium backdrop-blur-sm",
            style.chip
          )}
        >
          <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
          {style.label}
        </span>
      </div>
      <p className="mt-1.5 line-clamp-2 text-xs leading-tight font-medium text-foreground">
        {item.title ?? "Untitled"}
      </p>
      <p className="text-[11px] text-muted-foreground">
        {item.year ?? ""}
        {item.service_has_files
          ? ` · ${item.local_file_count}/${item.service_episode_file_count || item.local_file_count} files`
          : " · no files there"}
      </p>
      <div className="mt-1.5">
        <SyncButton item={item} source={source} compact />
      </div>
    </li>
  );
}

function ListRow({ item, source }: { item: LibraryItem; source: string }) {
  const style = styleFor(item.sync_state);
  return (
    <li className="flex gap-3 rounded-xl border border-border/70 bg-card/60 p-2.5">
      <div className="w-12 shrink-0 sm:w-14">
        <Poster item={item} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <p className="min-w-0 truncate text-sm font-medium text-foreground">
            {item.title ?? "Untitled"}
            {item.year ? <span className="ml-1.5 text-muted-foreground">({item.year})</span> : null}
          </p>
          <span className="flex items-center gap-1.5">
            <SyncButton item={item} source={source} compact />
            <Badge
              variant="outline"
              className={cn("gap-1 text-[11px]", style.chip)}
              title={style.hint}
            >
              {item.sync_state === "synced" && <IconCheck className="h-3 w-3" />}
              {item.sync_state === "orphan" && <IconFolderX className="h-3 w-3" />}
              {style.label}
            </Badge>
          </span>
        </div>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {item.service_has_files
            ? `${item.service_episode_file_count} file(s) there · ${item.local_file_count} here`
            : "No files there yet"}
          {item.local_folder ? ` · ${item.local_folder}` : " · not on this disk"}
        </p>
        <SeasonPips item={item} compact />
      </div>
    </li>
  );
}

export function LibraryPanel({ source, displayName }: { source: string; displayName: string }) {
  const { data, isLoading, isError, error } = useLibrary(source);
  const refresh = useRefreshLibrary(source);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<SyncState | "all" | "attention">("attention");
  const [layout, setLayout] = useState<"grid" | "list">("grid");

  const items = useMemo(() => {
    const all = data?.items ?? [];
    const needle = query.trim().toLowerCase();
    return all
      .filter((item) => {
        if (filter === "all") return true;
        // The default view. Everything the service actually holds files for —
        // which is the only part of the list a sync decision applies to.
        if (filter === "attention") return item.service_has_files;
        return item.sync_state === filter;
      })
      .filter((item) => (needle ? (item.title ?? "").toLowerCase().includes(needle) : true))
      .sort((a, b) => (a.title ?? "").localeCompare(b.title ?? ""));
  }, [data, query, filter]);

  const doRefresh = async () => {
    try {
      const result = await refresh.mutateAsync();
      toast.success(`Read ${result.titles_seen} title(s) from ${displayName}`);
    } catch (err) {
      toast.error(errorText(err, `Could not read from ${displayName}`));
    }
  };

  if (isLoading) {
    return (
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-6">
        {Array.from({ length: 12 }).map((_, i) => (
          <Skeleton key={i} className="aspect-[2/3] w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-xl border border-rose-500/25 bg-rose-500/8 px-4 py-3 text-sm text-rose-200/90">
        {errorText(error, "Could not load the library")}
      </div>
    );
  }

  const counts = data?.counts ?? {};
  const withFiles = (data?.items ?? []).filter((i) => i.service_has_files).length;

  return (
    <div className="space-y-4">
      {data && !data.live && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/8 px-4 py-3 text-sm text-amber-200/90">
          <IconAlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {displayName} did not answer. Showing what DragonCP already had recorded, which may be
            out of date.
          </span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          title={`The ${withFiles} title(s) ${displayName} actually holds files for`}
          onClick={() => setFilter("attention")}
          className={cn(
            "rounded-lg border px-2.5 py-1 text-xs font-medium transition",
            filter === "attention"
              ? "border-primary/50 bg-primary/15 text-foreground"
              : "border-border/70 bg-card/60 text-muted-foreground hover:text-foreground"
          )}
        >
          Has files {withFiles}
        </button>
        {STATES.filter((s) => counts[s.key]).map((state) => (
          <button
            key={state.key}
            type="button"
            title={state.hint}
            onClick={() => setFilter(filter === state.key ? "attention" : state.key)}
            className={cn(
              "rounded-lg border px-2.5 py-1 text-xs font-medium transition",
              filter === state.key
                ? state.chip
                : "border-border/70 bg-card/60 text-muted-foreground hover:text-foreground"
            )}
          >
            {state.label} {counts[state.key]}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setFilter("all")}
          className={cn(
            "rounded-lg border px-2.5 py-1 text-xs font-medium transition",
            filter === "all"
              ? "border-primary/50 bg-primary/15 text-foreground"
              : "border-border/70 bg-card/60 text-muted-foreground hover:text-foreground"
          )}
        >
          All {data?.total ?? 0}
        </button>

        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <IconSearch className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a title"
              className="h-8 w-36 pl-8 text-sm sm:w-44"
            />
          </div>
          <div className="flex items-center rounded-lg border border-border/70 bg-card/60 p-0.5">
            <button
              type="button"
              aria-label="Grid"
              onClick={() => setLayout("grid")}
              className={cn(
                "rounded-md p-1.5",
                layout === "grid" ? "bg-primary/20 text-foreground" : "text-muted-foreground"
              )}
            >
              <IconLayoutGrid className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              aria-label="List"
              onClick={() => setLayout("list")}
              className={cn(
                "rounded-md p-1.5",
                layout === "list" ? "bg-primary/20 text-foreground" : "text-muted-foreground"
              )}
            >
              <IconList className="h-3.5 w-3.5" />
            </button>
          </div>
          <Button size="sm" variant="outline" onClick={doRefresh} disabled={refresh.isPending}>
            <IconRefresh className={cn("h-3.5 w-3.5", refresh.isPending && "animate-spin")} />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="rounded-xl border border-border/70 bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
          {data?.total === 0
            ? `Nothing recorded yet. Press Refresh to read ${displayName}'s catalogue.`
            : "No title matches that."}
        </p>
      ) : layout === "grid" ? (
        <ul className="grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-6">
          {items.map((item) => (
            <GridCard key={item.external_id} item={item} source={source} />
          ))}
        </ul>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <ListRow key={item.external_id} item={item} source={source} />
          ))}
        </ul>
      )}
    </div>
  );
}
