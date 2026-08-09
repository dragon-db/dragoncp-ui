import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  IconAlertTriangle,
  IconArchive,
  IconArrowLeft,
  IconArrowsSort,
  IconChevronRight,
  IconDeviceTv,
  IconDots,
  IconDownload,
  IconExchange,
  IconEye,
  IconHistory,
  IconLayoutList,
  IconList,
  IconMenu2,
  IconMovie,
  IconPlayerPlay,
  IconPlugConnected,
  IconRefresh,
  IconRestore,
  IconSearch,
  IconSettings,
  IconTestPipe,
  IconTool,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { useMediaQuery } from "@/hooks/use-media-query";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import {
  useExploreBackups,
  useExploreDryRun,
  useExploreExecute,
  useExploreHistory,
  useExploreLibraries,
  useExplorePlan,
  useExploreRefresh,
  useExploreRepair,
  useExploreRepairPlan,
  useExploreSeason,
  useExploreTree,
  type PlanRequest,
} from "@/hooks/useExplore";
import { useSSHStatus } from "@/hooks/useConfig";
import { LibraryTree } from "@/components/explore/library-tree";
import {
  EpisodeRows,
  SeasonRows,
  TableShell,
  type Density,
} from "@/components/explore/contents-table";
import { PlanDialog } from "@/components/explore/plan-dialog";
import { RepairDialog } from "@/components/explore/repair-dialog";
import { RestoreDialog } from "@/components/backups/restore-dialog";
import { usePlanRestore, useRestoreCapture } from "@/hooks/useBackups";
import type { RestorePlan } from "@/lib/backup-types";
import { CountChips, StatusBadge } from "@/components/explore/explore-bits";
import { formatBytes, formatWhen } from "@/lib/explore-format";
import type {
  ExploreBackupRun,
  ExploreCounts,
  ExploreDryRunReport,
  ExplorePlan,
  ExploreSeason,
  ExploreSeriesSummary,
  ExploreStatus,
  RepairDecision,
} from "@/lib/explore-types";

const LIBRARIES = [
  { id: "movies", label: "Movies", Icon: IconMovie },
  { id: "tvshows", label: "TV Shows", Icon: IconDeviceTv },
  { id: "anime", label: "Anime", Icon: IconLayoutList },
] as const;

const STATUS_FILTERS: Array<{ id: "all" | ExploreStatus; label: string }> = [
  { id: "all", label: "All" },
  { id: "OUT_OF_SYNC", label: "Out of sync" },
  { id: "PARTIAL_SYNC", label: "Partial" },
  { id: "SYNCED", label: "Synced" },
  { id: "NO_INFO", label: "Not on remote" },
];

type Pane = "tree" | "table";

/**
 * Scrolls sideways when the text is longer than the strip it sits in, without
 * a scrollbar taking a slice out of a thirty-pixel bar.
 */
const SCROLL_X =
  "overflow-x-auto overscroll-x-contain whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden";

/**
 * Whether the focused element answers Space or Enter itself.
 *
 * Covers native controls, anything given a button/link/checkbox role — Base UI
 * renders its tick box as a `span` with `role="checkbox"` — and anything inside
 * a dialog or sheet, whose contents are never the page's to drive.
 */
function isInteractive(element: HTMLElement | null): boolean {
  if (!element) return false;
  if (element.closest("[role=dialog]")) return true;
  return Boolean(
    element.closest(
      'button, a[href], select, [contenteditable=""], [contenteditable="true"], ' +
        '[role="button"], [role="link"], [role="checkbox"], [role="switch"], ' +
        '[role="tab"], [role="menuitem"], [role="option"]'
    )
  );
}

export function ExplorePage({ mediaType }: { mediaType: string }) {
  const navigate = useNavigate();
  // A movie folder holds files, not seasons — the season layer is skipped
  // entirely rather than shown as one nameless row.
  const isMovies = mediaType === "movies";

  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | ExploreStatus>("all");
  const [sort, setSort] = useState<"recent" | "name">("recent");
  const [density, setDensity] = useState<Density>("comfortable");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedSeries, setSelectedSeries] = useState<string | null>(null);
  const [selectedSeason, setSelectedSeason] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [lastIndex, setLastIndex] = useState<number | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showBackups, setShowBackups] = useState(false);
  const [pane, setPane] = useState<Pane>("tree");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  // The row cursor belongs to whichever node is open, so changing selection
  // resets it without an effect writing state on every navigation.
  const [cursorAt, setCursorAt] = useState<{ node: string; index: number }>({
    node: "",
    index: 0,
  });

  const [pickedSeasons, setPickedSeasons] = useState<Set<string>>(new Set());

  const [planOpen, setPlanOpen] = useState(false);
  const [plan, setPlan] = useState<ExplorePlan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<ExploreDryRunReport | null>(null);
  const [dryRunError, setDryRunError] = useState<string | null>(null);

  // The version being put back, and what the planner says that would do. Held
  // separately because the plan arrives after the dialog opens — the dialog
  // shows its own loading state rather than delaying the click.
  const [restoreTarget, setRestoreTarget] = useState<ExploreBackupRun | null>(null);
  const [restorePlan, setRestorePlan] = useState<RestorePlan | null>(null);

  // The scope a repair was asked for: null means "not asked", a string or the
  // whole series otherwise. Held rather than derived from the selection so the
  // dialog keeps describing what it opened on if the selection moves behind it.
  const [repairScope, setRepairScope] = useState<{ folder: string; season: string | null } | null>(
    null
  );
  // Which copy to keep, for the files whose place is already taken. Keyed by
  // the stranded file's path and cleared with the dialog, so a choice made in
  // one scope cannot leak into the next one.
  const [repairChoices, setRepairChoices] = useState<Record<string, RepairDecision>>({});

  const isMobile = useIsMobile();
  // The actions panel is pinned open on a wide screen; below that it is a
  // sheet, so anything that wants to show actions has to open it first.
  const inspectorPinned = useMediaQuery("(min-width: 1280px)");
  const sshStatus = useSSHStatus();
  const connected = Boolean(sshStatus.data);

  const libraries = useExploreLibraries();
  const tree = useExploreTree(mediaType, connected);
  const refresh = useExploreRefresh(mediaType);
  const seasonQuery = useExploreSeason(mediaType, selectedSeries, selectedSeason);
  const historyQuery = useExploreHistory(
    mediaType,
    showHistory ? selectedSeries : null,
    selectedSeason
  );
  const backupsQuery = useExploreBackups(
    mediaType,
    showBackups ? selectedSeries : null,
    selectedSeason
  );
  const planMutation = useExplorePlan();
  const dryRunMutation = useExploreDryRun();
  const execute = useExploreExecute(mediaType);
  const planRestore = usePlanRestore();
  const restore = useRestoreCapture();
  const repairPlan = useExploreRepairPlan(
    mediaType,
    repairScope?.folder ?? null,
    repairScope?.season
  );
  const repair = useExploreRepair(mediaType);

  const series = useMemo(() => tree.data?.series ?? [], [tree.data]);
  const library = libraries.data?.find((entry) => entry.id === mediaType);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let list = series;
    if (needle) list = list.filter((s) => s.name.toLowerCase().includes(needle));
    if (statusFilter !== "all") list = list.filter((s) => s.status === statusFilter);
    return [...list].sort((a, b) =>
      sort === "name" ? a.name.localeCompare(b.name) : b.remote_mtime - a.remote_mtime
    );
  }, [series, query, statusFilter, sort]);

  const counts = useMemo(() => {
    const base: Record<string, number> = { all: series.length };
    for (const filter of STATUS_FILTERS.slice(1)) {
      base[filter.id] = series.filter((s) => s.status === filter.id).length;
    }
    return base;
  }, [series]);

  const activeSeries = useMemo(
    () => series.find((entry) => entry.name === selectedSeries),
    [series, selectedSeries]
  );
  const activeSeason = seasonQuery.data;
  const episodes = useMemo(() => activeSeason?.episodes ?? [], [activeSeason]);
  const seasons = useMemo(() => activeSeries?.seasons ?? [], [activeSeries]);
  const rowCount = selectedSeason ? episodes.length : seasons.length;
  const nodeKey = `${selectedSeries ?? ""}|${selectedSeason ?? ""}`;
  const cursor = cursorAt.node === nodeKey ? cursorAt.index : 0;
  const setCursor = useCallback(
    (next: number | ((current: number) => number)) =>
      setCursorAt((current) => {
        const base = current.node === nodeKey ? current.index : 0;
        return { node: nodeKey, index: typeof next === "function" ? next(base) : next };
      }),
    [nodeKey]
  );
  const pickedEpisodes = useMemo(
    () => episodes.filter((e) => picked.has(e.code)),
    [episodes, picked]
  );

  // --- selection ----------------------------------------------------------

  const selectSeries = useCallback(
    (name: string) => {
      setSelectedSeries(name);
      setPicked(new Set());
      setPickedSeasons(new Set());
      setShowHistory(false);
      if (isMovies) {
        // straight to the movie's files; there is nothing to expand
        const movie = series.find((entry) => entry.name === name);
        setSelectedSeason(movie?.seasons?.[0]?.name ?? null);
        setPane("table");
        return;
      }
      setSelectedSeason(null);
      setPane("tree");
      setExpanded((current) => {
        const next = new Set(current);
        if (next.has(name)) next.delete(name);
        else next.add(name);
        return next;
      });
    },
    [isMovies, series]
  );

  const selectSeason = useCallback((seriesName: string, seasonName: string) => {
    setSelectedSeries(seriesName);
    setSelectedSeason(seasonName);
    setPicked(new Set());
    setShowHistory(false);
    setPane("table");
    setExpanded((current) => new Set(current).add(seriesName));
  }, []);

  const toggleExpand = useCallback((name: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const togglePick = useCallback(
    (code: string, index: number, shiftKey: boolean) => {
      setPane("table");
      setCursor(index);
      setPicked((current) => {
        const next = new Set(current);
        if (shiftKey && lastIndex !== null) {
          const [from, to] = [lastIndex, index].sort((a, b) => a - b);
          episodes.slice(from, to + 1).forEach((episode) => next.add(episode.code));
          return next;
        }
        if (next.has(code)) next.delete(code);
        else {
          next.add(code);
          // A movie folder holds one file, so picking it is the whole decision.
          // Show what can be done with it rather than making them find the way.
          if (isMovies && !inspectorPinned) setInspectorOpen(true);
        }
        return next;
      });
      setLastIndex(index);
    },
    [episodes, inspectorPinned, isMovies, lastIndex, setCursor]
  );

  /** Bring the actions into view — they are already there on a wide screen. */
  const openActions = useCallback(() => {
    setPane("table");
    if (!inspectorPinned) setInspectorOpen(true);
  }, [inspectorPinned]);

  const toggleAll = useCallback(() => {
    setPicked((current) => {
      const all = episodes.length > 0 && episodes.every((episode) => current.has(episode.code));
      return all ? new Set() : new Set(episodes.map((episode) => episode.code));
    });
  }, [episodes]);

  const toggleSeasonPick = useCallback((name: string) => {
    setPickedSeasons((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const toggleAllSeasons = useCallback(() => {
    setPickedSeasons((current) => {
      const all = seasons.length > 0 && seasons.every((season) => current.has(season.name));
      return all ? new Set() : new Set(seasons.map((season) => season.name));
    });
  }, [seasons]);

  // --- plan + run ---------------------------------------------------------

  const runDryRun = useCallback(
    async (planId: string) => {
      setDryRun(null);
      setDryRunError(null);
      try {
        const result = await dryRunMutation.mutateAsync(planId);
        setDryRun(result.report);
      } catch (error) {
        setDryRunError(messageFrom(error, "Could not ask rsync what this would do."));
      }
    },
    [dryRunMutation]
  );

  /**
   * Open the review for an operation. `rehearse` runs the dry run straight
   * away — the plan is still there to approve afterwards, because rehearsing
   * something must not be what stops you doing it.
   */
  const openPlan = useCallback(
    async (request: PlanRequest, rehearse = false) => {
      setPlan(null);
      setPlanError(null);
      setDryRun(null);
      setDryRunError(null);
      setPlanOpen(true);
      try {
        const created = await planMutation.mutateAsync(request);
        setPlan(created);
        if (rehearse && !created.is_empty) await runDryRun(created.plan_id);
      } catch (error) {
        setPlanError(messageFrom(error, "Could not work out what this would do."));
      }
    },
    [planMutation, runDryRun]
  );

  const confirmPlan = useCallback(
    async (override: boolean, confirmText: string) => {
      if (!plan) return;
      try {
        const result = await execute.mutateAsync({
          plan_id: plan.plan_id,
          override,
          confirm_text: confirmText,
        });
        toast.success(result.message);
        setPlanOpen(false);
        setPicked(new Set());
      } catch (error) {
        setPlanError(messageFrom(error, "Could not start the transfer."));
      }
    },
    [execute, plan]
  );

  /**
   * Putting a stored version back, from the season you are looking at.
   *
   * The planner is the same one the Backups page uses, so the preview names the
   * exact library file this replaces before anything moves. A run that is
   * narrowed to a season here still restores the whole capture — the capture is
   * what was saved, and restoring half of it would leave the slot in a state
   * nothing else on either page can describe.
   */
  const openRestore = useCallback(
    (run: ExploreBackupRun) => {
      setRestoreTarget(run);
      setRestorePlan(null);
      planRestore.mutate(
        { captureId: run.backup_id },
        {
          onSuccess: setRestorePlan,
          onError: (error: unknown) => {
            toast.error(messageFrom(error, "Could not work out what this restore would do."));
            setRestoreTarget(null);
          },
        }
      );
    },
    [planRestore]
  );

  const confirmRestore = useCallback(() => {
    if (!restoreTarget) return;
    restore.mutate(
      { captureId: restoreTarget.backup_id },
      {
        onSuccess: (result) => {
          toast.success(result.message);
          setRestoreTarget(null);
          setRestorePlan(null);
        },
        onError: (error: unknown) => {
          toast.error(messageFrom(error, "Restore could not be started."));
        },
      }
    );
  }, [restore, restoreTarget]);

  const confirmRepair = useCallback(() => {
    if (!repairScope) return;
    repair.mutate(
      { folder: repairScope.folder, season: repairScope.season, decisions: repairChoices },
      {
        onSuccess: (result) => {
          const parts = [];
          if (result.moved_count) parts.push(`moved ${result.moved_count} back into place`);
          if (result.deleted_count)
            parts.push(
              `removed ${result.deleted_count} redundant (${formatBytes(result.freed_size)} freed)`
            );
          if (result.replaced_count) parts.push(`replaced ${result.replaced_count}`);
          toast.success(
            (parts.join(", ") || "Nothing needed doing") +
              (result.failed_count ? ` — ${result.failed_count} could not be done` : "")
          );
          if (result.failed_count) {
            for (const failure of result.failed) {
              toast.error(`${failure.relative_path.split("/").pop()} — ${failure.error}`);
            }
          }
          setRepairScope(null);
          setRepairChoices({});
        },
        onError: (error: unknown) => {
          toast.error(messageFrom(error, "The repair could not be run."));
        },
      }
    );
  }, [repair, repairScope, repairChoices]);

  const primaryAction = useCallback(() => {
    if (!selectedSeries) return;
    if (pickedEpisodes.length && selectedSeason) {
      openPlan({
        media_type: mediaType,
        operation: "download",
        folder: selectedSeries,
        season: selectedSeason,
        codes: pickedEpisodes.map((e) => e.code),
      });
      return;
    }
    if (!selectedSeason && pickedSeasons.size) {
      openPlan({
        media_type: mediaType,
        operation: "sync_seasons",
        folder: selectedSeries,
        seasons: [...pickedSeasons],
      });
      return;
    }
    openPlan({
      media_type: mediaType,
      operation: selectedSeason ? "sync_season" : "sync_series",
      folder: selectedSeries,
      season: selectedSeason,
    });
  }, [mediaType, openPlan, pickedEpisodes, pickedSeasons, selectedSeason, selectedSeries]);

  // --- keyboard: the point of a three-pane console -------------------------

  const treeOrder = useMemo(() => {
    const order: Array<[string, string | null]> = [];
    for (const entry of visible) {
      order.push([entry.name, null]);
      if (expanded.has(entry.name) && entry.name === selectedSeries) {
        for (const season of seasons) order.push([entry.name, season.name]);
      }
    }
    return order;
  }, [visible, expanded, seasons, selectedSeries]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
      // Space and Enter belong to whatever is focused. Swallowing them here
      // meant tabbing to a button and pressing Enter moved the page's cursor
      // instead of pressing the button.
      if ((event.key === " " || event.key === "Enter") && isInteractive(target)) return;
      // The actions sheet covers the console below xl; the shortcuts underneath
      // it are not what the keyboard is aimed at while it is open.
      if (planOpen || inspectorOpen || isMobile) return;
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " ", "Enter"].includes(event.key))
        return;
      event.preventDefault();

      const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;

      if (step && pane === "tree") {
        const at = treeOrder.findIndex(
          ([s, se]) => s === selectedSeries && (se ?? null) === selectedSeason
        );
        const next = treeOrder[Math.max(0, Math.min(treeOrder.length - 1, at + step))];
        if (next) {
          if (next[1]) selectSeason(next[0], next[1]);
          else {
            setSelectedSeries(next[0]);
            setSelectedSeason(null);
            setPicked(new Set());
          }
        }
        return;
      }
      if (step && pane === "table") {
        setCursor((c) => Math.max(0, Math.min(rowCount - 1, c + step)));
        return;
      }
      if (event.key === "ArrowRight") return setPane("table");
      if (event.key === "ArrowLeft") return setPane("tree");
      if (event.key === " " && pane === "table" && selectedSeason) {
        const row = episodes[cursor];
        if (row && row.label !== "IN_SYNC") togglePick(row.code, cursor, false);
        return;
      }
      if (event.key === "Enter") primaryAction();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    cursor,
    episodes,
    pane,
    planOpen,
    primaryAction,
    rowCount,
    selectSeason,
    selectedSeason,
    selectedSeries,
    setCursor,
    togglePick,
    treeOrder,
    isMobile,
    inspectorOpen,
  ]);

  // --- the live remote path ------------------------------------------------

  const remotePath = useMemo(() => {
    const root = library?.remote_path ?? "";
    if (!root || !selectedSeries) return root;
    const parts = [root, selectedSeries];
    if (activeSeason?.remote_folder) parts.push(activeSeason.remote_folder);
    if (selectedSeason && pane === "table") {
      const row = episodes[cursor];
      if (row?.remote_name) parts.push(row.remote_name);
    }
    return parts.join("/");
  }, [library, selectedSeries, activeSeason, selectedSeason, pane, episodes, cursor]);

  if (!connected && !sshStatus.isLoading) return <NoSession />;

  const treeError = tree.isError ? messageFrom(tree.error, "Could not read the library.") : null;
  const tally = selectedSeason
    ? `${episodes.length} items · ${formatBytes(activeSeason?.remote_bytes)}`
    : activeSeries
      ? `${seasons.length} seasons · ${formatBytes(activeSeries.remote_bytes)}`
      : "";

  // A file the remote no longer has still has a size worth showing — its own.
  const pickedBytes = pickedEpisodes.reduce(
    (sum, e) => sum + (e.remote_size ?? e.local_size ?? 0),
    0
  );

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      {/* ---- toolbar ---- */}
      <div className="flex flex-none items-center gap-2.5 overflow-x-auto border-b border-border px-4 py-[11px] [scrollbar-width:none] lg:overflow-hidden [&::-webkit-scrollbar]:hidden">
        <div className="inline-flex flex-none gap-0.5 rounded-[10px] border border-border bg-well p-[3px]">
          {LIBRARIES.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => navigate({ to: "/media/$type", params: { type: id } })}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-[7px] px-[11px] py-[5px] text-[12.5px] font-semibold",
                id === mediaType
                  ? "bg-brand/15 text-brand-foreground shadow-[inset_0_0_0_1px_var(--brand)]"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div className="flex w-[250px] min-w-[120px] shrink items-center gap-2 rounded-[10px] border border-border bg-well px-[11px] py-1.5">
          <IconSearch className="size-3.5 flex-none text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter series"
            className="w-full min-w-0 bg-transparent text-[12.5px] outline-none placeholder:text-muted-foreground"
          />
        </div>

        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.id}
            type="button"
            onClick={() => setStatusFilter(filter.id)}
            className={cn(
              "inline-flex flex-none items-center gap-1.5 rounded-full border px-2.5 py-[5px] text-[11.5px] font-semibold",
              statusFilter === filter.id
                ? "border-brand bg-brand/15 text-brand-foreground"
                : "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground"
            )}
          >
            {filter.label}
            <span className="font-mono text-[10px] opacity-75">{counts[filter.id] ?? 0}</span>
          </button>
        ))}

        <div className="ml-auto flex flex-none items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSort(sort === "recent" ? "name" : "recent")}
          >
            <IconArrowsSort className="mr-2 size-4" />
            {sort === "recent" ? "Recent" : "A–Z"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={refresh.isPending}
            title={
              tree.data?.checked_at
                ? `Last checked ${formatWhen(tree.data.checked_at)}`
                : "Never checked"
            }
            onClick={() =>
              refresh
                .mutateAsync()
                .then(() => toast.success("Library re-checked"))
                .catch((error) => toast.error(messageFrom(error, "Re-check failed")))
            }
          >
            <IconRefresh className={cn("mr-2 size-4", refresh.isPending && "animate-spin")} />
            Re-check sync
          </Button>
        </div>
      </div>

      {/* ---- panes: three side by side, one at a time on a narrow screen ---- */}
      <div className="flex min-h-0 flex-1">
        <LibraryTree
          flat={isMovies}
          className={cn(selectedSeries && "hidden lg:flex")}
          series={visible}
          total={series.length}
          loading={tree.isLoading || refresh.isPending}
          focused={pane === "tree"}
          expanded={expanded}
          selectedSeries={selectedSeries}
          selectedSeason={selectedSeason}
          onToggle={toggleExpand}
          onSelectSeries={selectSeries}
          onSelectSeason={selectSeason}
          onCollapseAll={() =>
            setExpanded((current) =>
              current.size ? new Set() : new Set(visible.map((s) => s.name))
            )
          }
          emptyMessage={
            treeError ?? (query ? `No series match “${query}”.` : "This library is empty.")
          }
        />

        <div
          className={cn(
            "flex min-h-0 min-w-0 flex-1 flex-col",
            !selectedSeries && "hidden lg:flex"
          )}
        >
          {/* Back, path, tally, actions and density all on one 34px strip is
              fine at desktop widths and unreadable on a phone, so below `sm`
              the path gets the strip to itself and the rest sits under it. */}
          <div className="flex flex-none flex-col border-b border-border bg-well sm:h-[34px] sm:flex-row sm:items-center sm:gap-2.5 sm:px-3">
            <div className="flex h-[34px] flex-none items-center gap-2.5 px-3 sm:h-auto sm:min-w-0 sm:flex-1 sm:px-0">
              {selectedSeries && (
                <button
                  type="button"
                  aria-label="Back to the library"
                  onClick={() => {
                    setSelectedSeason(null);
                    setSelectedSeries(null);
                  }}
                  className="grid size-6 flex-none place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground lg:hidden"
                >
                  <IconArrowLeft className="size-4" />
                </button>
              )}
              {/* A long series name used to end in an ellipsis with no way to
                read the rest, so the crumb scrolls sideways instead. */}
              <nav
                className={cn(
                  "flex min-w-0 items-center gap-[5px] text-[11.5px] text-foreground-3",
                  SCROLL_X
                )}
              >
                {selectedSeries ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setSelectedSeason(null)}
                      className={cn(
                        "flex-none hover:text-foreground hover:underline",
                        !selectedSeason && "font-semibold text-foreground"
                      )}
                    >
                      {selectedSeries}
                    </button>
                    {selectedSeason && !isMovies && (
                      <>
                        <IconChevronRight className="size-3 flex-none opacity-50" />
                        <span className="flex-none font-semibold text-foreground">
                          {selectedSeason}
                        </span>
                      </>
                    )}
                  </>
                ) : (
                  <span>Select a series</span>
                )}
              </nav>
            </div>

            <div className="flex h-[30px] flex-none items-center gap-2.5 border-t border-border px-3 sm:h-auto sm:gap-2.5 sm:border-0 sm:px-0">
              <span className="flex-none font-mono text-[10.5px] text-foreground-3 sm:ml-auto">
                {tally}
              </span>
              {selectedSeries && (
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto h-6 flex-none px-2 text-[11px] sm:ml-0 xl:hidden"
                  onClick={() => setInspectorOpen(true)}
                >
                  Actions
                </Button>
              )}
              <div className="hidden gap-0.5 rounded-md border border-border bg-elevated p-0.5 sm:inline-flex">
                {(
                  [
                    ["comfortable", IconList, "Comfortable rows"],
                    ["compact", IconMenu2, "Compact rows"],
                  ] as const
                ).map(([value, Icon, title]) => (
                  <button
                    key={value}
                    type="button"
                    title={title}
                    onClick={() => setDensity(value)}
                    className={cn(
                      "grid h-5 w-6 place-items-center rounded",
                      density === value
                        ? "bg-brand/15 text-brand-foreground"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    <Icon className="size-3.5" />
                  </button>
                ))}
              </div>
            </div>
          </div>

          <TableShell
            loading={seasonQuery.isLoading}
            empty={
              !selectedSeries
                ? `Pick a ${isMovies ? "movie" : "series"} on the left to see what it holds.`
                : selectedSeason && episodes.length === 0
                  ? `This ${isMovies ? "movie folder" : "season"} is empty on both sides.`
                  : !selectedSeason && seasons.length === 0
                    ? "No seasons found."
                    : null
            }
          >
            {selectedSeason ? (
              <EpisodeRows
                episodes={episodes}
                selected={picked}
                density={density}
                cursor={cursor}
                focused={pane === "table"}
                onToggle={togglePick}
                onToggleAll={toggleAll}
              />
            ) : activeSeries && !isMovies ? (
              <SeasonRows
                seasons={seasons}
                selected={pickedSeasons}
                density={density}
                cursor={cursor}
                focused={pane === "table"}
                onOpen={(season) => selectSeason(activeSeries.name, season)}
                onToggle={toggleSeasonPick}
                onToggleAll={toggleAllSeasons}
                onSync={(season) =>
                  openPlan({
                    media_type: mediaType,
                    operation: "sync_season",
                    folder: activeSeries.name,
                    season,
                  })
                }
              />
            ) : null}
          </TableShell>
        </div>

        <aside className="hidden w-[336px] flex-none flex-col border-l border-border bg-sidebar xl:flex">
          <Inspector
            isMovies={isMovies}
            mediaType={mediaType}
            series={activeSeries}
            season={activeSeason}
            picked={pickedEpisodes}
            pickedSeasons={selectedSeason ? [] : [...pickedSeasons]}
            onClearSeasons={() => setPickedSeasons(new Set())}
            totalEpisodes={episodes.length}
            showHistory={showHistory}
            onToggleHistory={() => setShowHistory((value) => !value)}
            history={historyQuery.data}
            showBackups={showBackups}
            onToggleBackups={() => setShowBackups((value) => !value)}
            backups={backupsQuery.data}
            onRestore={openRestore}
            restoringId={restore.isPending ? (restoreTarget?.backup_id ?? null) : null}
            onRepair={(folder, season) => setRepairScope({ folder, season })}
            onClearPick={() => setPicked(new Set())}
            onFocusTable={() => setPane("table")}
            onPlan={openPlan}
          />
        </aside>
      </div>

      {/* ---- what you picked, and what you can do with it ----
           The actions panel is off screen below xl, so the picks would
           otherwise have nowhere to go. This rides above the status bar. */}
      {(pickedEpisodes.length > 0 || (!selectedSeason && pickedSeasons.size > 0)) && (
        <div className="pointer-events-none absolute inset-x-0 bottom-11 z-20 flex justify-center px-3 xl:hidden">
          <div className="pointer-events-auto flex max-w-full items-center gap-2 rounded-full border border-border bg-elevated/95 py-1.5 pr-1.5 pl-3.5 shadow-[0_18px_40px_-16px_rgba(0,0,0,0.85)] backdrop-blur">
            <span className="min-w-0 truncate text-[12px] font-medium text-foreground">
              {pickedEpisodes.length ? (
                <>
                  {pickedEpisodes.length} picked
                  <span className="ml-1.5 font-mono text-[10.5px] text-foreground-3">
                    {formatBytes(pickedBytes)}
                  </span>
                </>
              ) : (
                `${pickedSeasons.size} season${pickedSeasons.size === 1 ? "" : "s"}`
              )}
            </span>
            <Button size="sm" className="h-7 flex-none rounded-full px-3" onClick={primaryAction}>
              {pickedEpisodes.length ? (
                <>
                  <IconDownload className="mr-1.5 size-3.5" />
                  Download
                </>
              ) : (
                <>
                  <IconPlayerPlay className="mr-1.5 size-3.5" />
                  Sync
                </>
              )}
            </Button>
            <button
              type="button"
              aria-label="More actions"
              onClick={openActions}
              className="grid size-7 flex-none place-items-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <IconDots className="size-4" />
            </button>
            <button
              type="button"
              aria-label="Clear selection"
              onClick={() => {
                setPicked(new Set());
                setPickedSeasons(new Set());
              }}
              className="grid size-7 flex-none place-items-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <IconX className="size-4" />
            </button>
          </div>
        </div>
      )}

      {/* ---- status bar ----
          `md:rounded-b-xl` matches the inset shell, which is only rounded from
          md up. The navbar at the top needs no equivalent: it is transparent,
          so the shell's own background shows through its corners, while this
          bar is filled and would otherwise paint square over them. */}
      <div className="flex h-8 flex-none items-center gap-3 border-t border-border bg-well px-3.5 font-mono text-[11px] text-foreground-3 md:rounded-b-xl">
        {/* the whole path is readable by dragging it, not just its tail */}
        <span className={cn("min-w-0 flex-1", SCROLL_X)}>
          {remotePath ? <RemotePath path={remotePath} /> : "No library selected"}
        </span>
        <span className="hidden flex-none items-center gap-2.5 lg:flex">
          <Hint keys={["↑", "↓"]} label="move" />
          <Hint keys={["←", "→"]} label="pane" />
          <Hint keys={["space"]} label="pick" />
          <Hint keys={["⏎"]} label="transfer" />
        </span>
      </div>

      <Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
        <SheetContent side="right" className="flex w-[92vw] max-w-[380px] flex-col p-0">
          <SheetTitle className="sr-only">Transfer actions</SheetTitle>
          <Inspector
            isMovies={isMovies}
            mediaType={mediaType}
            series={activeSeries}
            season={activeSeason}
            picked={pickedEpisodes}
            pickedSeasons={selectedSeason ? [] : [...pickedSeasons]}
            onClearSeasons={() => setPickedSeasons(new Set())}
            totalEpisodes={episodes.length}
            showHistory={showHistory}
            onToggleHistory={() => setShowHistory((value) => !value)}
            history={historyQuery.data}
            showBackups={showBackups}
            onToggleBackups={() => setShowBackups((value) => !value)}
            backups={backupsQuery.data}
            onRestore={openRestore}
            restoringId={restore.isPending ? (restoreTarget?.backup_id ?? null) : null}
            onRepair={(folder, season) => setRepairScope({ folder, season })}
            onClearPick={() => setPicked(new Set())}
            onFocusTable={() => {
              setPane("table");
              setInspectorOpen(false);
            }}
            onPlan={(request, rehearse) => {
              setInspectorOpen(false);
              openPlan(request, rehearse);
            }}
          />
        </SheetContent>
      </Sheet>

      <PlanDialog
        open={planOpen}
        plan={plan}
        loading={planMutation.isPending && !plan}
        error={planError}
        submitting={execute.isPending}
        dryRun={dryRun}
        dryRunLoading={dryRunMutation.isPending}
        dryRunError={dryRunError}
        onDryRun={() => plan && runDryRun(plan.plan_id)}
        onOpenChange={setPlanOpen}
        onConfirm={confirmPlan}
      />

      <RestoreDialog
        open={Boolean(restoreTarget)}
        plan={restorePlan}
        loading={planRestore.isPending && !restorePlan}
        submitting={restore.isPending}
        onOpenChange={(open) => {
          if (open) return;
          setRestoreTarget(null);
          setRestorePlan(null);
        }}
        onConfirm={confirmRestore}
      />

      <RepairDialog
        open={Boolean(repairScope)}
        plan={repairPlan.data ?? null}
        loading={repairPlan.isPending}
        submitting={repair.isPending}
        decisions={repairChoices}
        onDecide={(path, choice) =>
          setRepairChoices((current) => {
            const next = { ...current };
            if (choice) next[path] = choice;
            else delete next[path];
            return next;
          })
        }
        onOpenChange={(open) => {
          if (open) return;
          setRepairScope(null);
          setRepairChoices({});
        }}
        onConfirm={confirmRepair}
      />
    </div>
  );
}

function RemotePath({ path }: { path: string }) {
  const index = path.lastIndexOf("/");
  if (index < 0) return <>{path}</>;
  return (
    <>
      {path.slice(0, index + 1)}
      <span className="text-foreground/80">{path.slice(index + 1)}</span>
    </>
  );
}

function Hint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="flex items-center gap-1">
      {keys.map((key) => (
        <kbd
          key={key}
          className="rounded border border-border bg-card px-[5px] py-px text-[10px] leading-[13px] text-foreground-2"
        >
          {key}
        </kbd>
      ))}
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------

interface InspectorProps {
  isMovies: boolean;
  mediaType: string;
  series?: ExploreSeriesSummary;
  season?: ExploreSeason;
  picked: Array<{ code: string; label: string; remote_size: number | null }>;
  /** Seasons ticked in the list, when the season list is what is showing. */
  pickedSeasons: string[];
  totalEpisodes: number;
  showHistory: boolean;
  history?: ReturnType<typeof useExploreHistory>["data"];
  onToggleHistory: () => void;
  showBackups: boolean;
  onRestore: (run: ExploreBackupRun) => void;
  restoringId: string | null;
  onRepair: (folder: string, season: string | null) => void;
  backups?: ExploreBackupRun[];
  onToggleBackups: () => void;
  onClearPick: () => void;
  onClearSeasons: () => void;
  onFocusTable: () => void;
  onPlan: (request: PlanRequest, rehearse?: boolean) => void;
}

function Inspector({
  isMovies,
  mediaType,
  series,
  season,
  picked,
  pickedSeasons,
  totalEpisodes,
  showHistory,
  history,
  onToggleHistory,
  showBackups,
  onRestore,
  restoringId,
  onRepair,
  backups,
  onToggleBackups,
  onClearPick,
  onClearSeasons,
  onFocusTable,
  onPlan,
}: InspectorProps) {
  if (!series) {
    return (
      <p className="p-5 text-[12.5px] text-muted-foreground">
        Nothing selected. Pick a series to see how it compares with the remote.
      </p>
    );
  }

  const scope = season ?? series;
  const pickedBytes = picked.reduce((sum, e) => sum + (e.remote_size ?? 0), 0);
  const hasUpgrade = picked.some((e) => e.label === "UPGRADED");
  const seasonsPicked = pickedSeasons.length;
  const kind = picked.length
    ? "Selection"
    : seasonsPicked
      ? "Seasons"
      : isMovies
        ? "Movie"
        : season
          ? "Season"
          : "Series";
  const unit = isMovies ? "file" : "episode";
  const title = picked.length
    ? `${picked.length} ${unit}${picked.length === 1 ? "" : "s"} picked`
    : seasonsPicked
      ? `${seasonsPicked} season${seasonsPicked === 1 ? "" : "s"} picked`
      : season && !isMovies
        ? `${series.name} · ${season.name}`
        : series.name;

  // The same request, built once, so a dry run rehearses exactly the operation
  // the button beside it would run.
  const selectionRequest = (operation: "download" | "replace"): PlanRequest => ({
    media_type: mediaType,
    operation,
    folder: series.name,
    season: season?.name ?? null,
    codes: picked.map((e) => e.code),
  });
  const seasonsRequest = (): PlanRequest => ({
    media_type: mediaType,
    operation: "sync_seasons",
    folder: series.name,
    seasons: pickedSeasons,
  });
  const seasonRequest = (): PlanRequest => ({
    media_type: mediaType,
    operation: "sync_season",
    folder: series.name,
    season: season?.name ?? null,
  });
  const seriesRequest = (): PlanRequest => ({
    media_type: mediaType,
    operation: "sync_series",
    folder: series.name,
  });

  return (
    <>
      <div className="flex-none border-b border-border px-4.5 py-4">
        <p className="font-mono text-[10px] tracking-[0.14em] text-foreground-3 uppercase">
          {kind}
        </p>
        <h2 className="mt-1.5 font-display text-[17px] leading-tight font-semibold text-foreground">
          {title}
        </h2>
        <div className="mt-2.5">
          {picked.length || seasonsPicked ? (
            <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10.5px] text-foreground-3">
              {series.name}
              {picked.length && season ? ` · ${season.name}` : ""}
            </span>
          ) : (
            <StatusBadge status={scope.status} />
          )}
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-4 px-4.5 py-3.5 pb-5">
          {picked.length ? (
            <Facts
              items={[
                ["To copy", formatBytes(pickedBytes)],
                ["Files", `${picked.length}`, `of ${totalEpisodes}`],
              ]}
            />
          ) : seasonsPicked ? (
            <Facts
              items={[
                ["Picked", `${seasonsPicked}`, `of ${series.season_count}`],
                ["Episodes", `${scope.counts.remote_total}`],
              ]}
            />
          ) : (
            <>
              {/* With nothing on the remote every one of these reads zero,
                  which says "empty" about a series you hold in full. Report
                  your own copy instead — that is the only side there is. */}
              {scope.status === "NO_INFO" ? (
                <Facts
                  items={[
                    [isMovies ? "Your files" : "Your episodes", `${scope.counts.local_only}`],
                    ["Size", formatBytes(scope.local_bytes)],
                  ]}
                />
              ) : (
                <Facts
                  items={[
                    [isMovies ? "Files" : "Episodes", `${scope.counts.remote_total}`],
                    ["Size", formatBytes(scope.remote_bytes)],
                    ["Missing", `${scope.counts.missing}`],
                    ["Upgraded", `${scope.counts.upgraded}`],
                  ]}
                />
              )}
              <CountChips counts={scope.counts} className="flex-wrap" />
            </>
          )}

          {season && season.misplaced.length > 0 && (
            <MisplacedWarning
              count={season.misplaced.length}
              onRepair={() => onRepair(series.name, season.name)}
            />
          )}
          {!season && series.misplaced_count > 0 && (
            <MisplacedWarning
              count={series.misplaced_count}
              onRepair={() => onRepair(series.name, null)}
            />
          )}

          <NamingWarning
            folders={season ? season.odd_folders : series.odd_folders}
            expected={season?.standard_name ?? null}
          />

          {scope.status === "NO_INFO" && <NotOnRemoteNote counts={scope.counts} />}

          <section className="flex flex-col gap-2">
            <p className="font-mono text-[10px] tracking-[0.14em] text-foreground-3 uppercase">
              Transfer
            </p>

            {picked.length > 0 && season ? (
              <>
                <Action
                  primary
                  Icon={IconDownload}
                  title={`Download ${picked.length} file${picked.length === 1 ? "" : "s"}`}
                  detail="Adds only what is missing. Never overwrites."
                  onClick={() => onPlan(selectionRequest("download"))}
                />
                <Action
                  Icon={IconExchange}
                  title={`Replace ${picked.length} file${picked.length === 1 ? "" : "s"}`}
                  detail={
                    hasUpgrade
                      ? "Backs up the local copy, then brings the new one."
                      : "Backs up what is there and fetches the remote copy."
                  }
                  onClick={() => onPlan(selectionRequest("replace"))}
                />
                <Action
                  Icon={IconTestPipe}
                  title="Dry run"
                  detail="Ask rsync what this would do, without doing it."
                  onClick={() => onPlan(selectionRequest("replace"), true)}
                />
                <Action
                  Icon={IconX}
                  title="Clear selection"
                  detail={isMovies ? "Back to the whole movie" : "Back to the whole season"}
                  onClick={onClearPick}
                />
              </>
            ) : seasonsPicked ? (
              <>
                <Action
                  primary
                  Icon={IconPlayerPlay}
                  title={`Sync ${seasonsPicked} season${seasonsPicked === 1 ? "" : "s"}`}
                  detail="One plan and one transfer, however many are picked."
                  onClick={() => onPlan(seasonsRequest())}
                />
                <Action
                  Icon={IconEye}
                  title="Download & replace only"
                  detail="Leaves local files the remote no longer has."
                  onClick={() => onPlan({ ...seasonsRequest(), include_removals: false })}
                />
                <Action
                  Icon={IconTestPipe}
                  title="Dry run"
                  detail="Ask rsync what this would do, without doing it."
                  onClick={() => onPlan(seasonsRequest(), true)}
                />
                <Action
                  Icon={IconX}
                  title="Clear selection"
                  detail="Back to the whole series"
                  onClick={onClearSeasons}
                />
              </>
            ) : season ? (
              <>
                <Action
                  primary
                  Icon={IconPlayerPlay}
                  title={isMovies ? "Sync this movie" : "Sync this season"}
                  detail="Download what is missing, replace what changed."
                  onClick={() => onPlan(seasonRequest())}
                />
                <Action
                  Icon={IconEye}
                  title="Download & replace only"
                  detail="Leaves local files the remote no longer has."
                  onClick={() => onPlan({ ...seasonRequest(), include_removals: false })}
                />
                <Action
                  Icon={IconTestPipe}
                  title="Dry run"
                  detail="Ask rsync what this would do, without doing it."
                  onClick={() => onPlan(seasonRequest(), true)}
                />
                <Action
                  Icon={IconList}
                  title={isMovies ? "Pick files" : "Pick episodes"}
                  detail="Choose individual files instead."
                  onClick={onFocusTable}
                />
              </>
            ) : (
              <>
                <Action
                  primary
                  Icon={IconPlayerPlay}
                  title="Sync the whole series"
                  detail="One plan, grouped by season, reviewed before it runs."
                  onClick={() => onPlan(seriesRequest())}
                />
                <Action
                  Icon={IconEye}
                  title="Download & replace only"
                  detail="Leaves local files the remote no longer has."
                  onClick={() => onPlan({ ...seriesRequest(), include_removals: false })}
                />
                <Action
                  Icon={IconTestPipe}
                  title="Dry run"
                  detail="Ask rsync what this would do, without doing it."
                  onClick={() => onPlan(seriesRequest(), true)}
                />
              </>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <button
              type="button"
              onClick={onToggleHistory}
              className="flex items-center gap-2 font-mono text-[10px] tracking-[0.14em] text-foreground-3 uppercase hover:text-foreground"
            >
              <IconHistory className="size-3.5" />
              History
              <IconChevronRight
                className={cn("size-3 transition-transform", showHistory && "rotate-90")}
              />
            </button>
            {showHistory && (
              <div className="flex flex-col gap-2">
                {!history?.length ? (
                  <p className="text-[12px] text-muted-foreground">Nothing has run here yet.</p>
                ) : (
                  history.map((run) => (
                    <div key={run.transfer_id} className="rounded-md border border-border p-2.5">
                      <p className="flex items-center gap-2 text-[12px] text-foreground">
                        <span className="font-medium capitalize">
                          {(run.explore_mode ?? run.operation_type).replace("explore_", "")}
                        </span>
                        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                          {run.status}
                        </span>
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                        {formatWhen(run.end_time ?? run.start_time)} · {run.files.length} file
                        {run.files.length === 1 ? "" : "s"}
                      </p>
                    </div>
                  ))
                )}
              </div>
            )}
          </section>

          <BackupSection
            open={showBackups}
            onToggle={onToggleBackups}
            onRestore={onRestore}
            restoringId={restoringId}
            runs={backups}
            scope={season && !isMovies ? season.name : series.name}
          />
        </div>
      </ScrollArea>
    </>
  );
}

/**
 * What an earlier sync moved aside here, and whether it is still recoverable.
 *
 * This answers the question you actually have while looking at a season — "I
 * replaced that episode, can I get the old one back?" — and now answers it in
 * place. The confirmation is the Backups page's own restore dialog, driven by
 * the same planner, so the file being replaced is named here exactly as it is
 * named there. Anything larger than one version — pinning, retention, deleting
 * — still belongs on the Backups page, which is why the link stays.
 */
function BackupSection({
  open,
  onToggle,
  runs,
  scope,
  onRestore,
  restoringId,
}: {
  open: boolean;
  onToggle: () => void;
  runs?: ExploreBackupRun[];
  scope: string;
  onRestore: (run: ExploreBackupRun) => void;
  restoringId: string | null;
}) {
  const total = runs?.reduce((sum, run) => sum + run.shown_count, 0) ?? 0;

  return (
    <section className="flex flex-col gap-2">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-2 font-mono text-[10px] tracking-[0.14em] text-foreground-3 uppercase hover:text-foreground"
      >
        <IconArchive className="size-3.5" />
        Backups
        {total > 0 && (
          <span className="rounded-full bg-brand/15 px-1.5 text-[9.5px] text-brand-foreground">
            {total}
          </span>
        )}
        <IconChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} />
      </button>

      {open && (
        <div className="flex flex-col gap-2">
          {!runs?.length ? (
            <p className="text-[12px] text-muted-foreground">
              Nothing has been replaced or removed in {scope}, so there is nothing to put back.
            </p>
          ) : (
            <>
              {runs.map((run) => (
                <div key={run.backup_id} className="rounded-md border border-border p-2.5">
                  <p className="flex items-center gap-2 text-[12px]">
                    <span className="font-medium text-foreground">
                      {run.shown_count} file{run.shown_count === 1 ? "" : "s"}
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {formatBytes(run.shown_size)}
                    </span>
                    <span
                      className={cn(
                        "ml-auto rounded-full px-1.5 py-px font-mono text-[9.5px]",
                        run.status === "restored"
                          ? "bg-emerald-500/15 text-emerald-300"
                          : run.status === "files_removed"
                            ? "bg-rose-500/15 text-rose-300"
                            : "bg-elevated text-foreground-3"
                      )}
                    >
                      {run.status === "files_removed" ? "files gone" : run.status}
                    </span>
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                    {formatWhen(run.created_at)}
                    {run.shown_count < run.file_count && ` · ${run.file_count} in the whole run`}
                  </p>

                  <ul className="mt-1.5 flex flex-col gap-0.5">
                    {run.files.slice(0, 6).map((file) => (
                      <li
                        key={file.relative_path}
                        className="flex items-center gap-2 text-[11.5px]"
                      >
                        {file.code && (
                          <span className="flex-none font-mono text-[10px] font-semibold text-brand-hover">
                            {file.code}
                          </span>
                        )}
                        <span className="min-w-0 flex-1 truncate text-foreground-2">
                          {baseName(file.relative_path)}
                        </span>
                        <span className="flex-none font-mono text-[10px] text-muted-foreground">
                          {formatBytes(file.file_size)}
                        </span>
                      </li>
                    ))}
                    {run.files.length > 6 && (
                      <li className="text-[11px] text-muted-foreground">
                        and {run.files.length - 6} more
                      </li>
                    )}
                  </ul>

                  {run.status === "files_removed" ? (
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      The saved copies were deleted — only the record is left.
                    </p>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={Boolean(restoringId)}
                      onClick={() => onRestore(run)}
                      className="mt-2 h-6 w-full px-2 text-[11px]"
                    >
                      <IconRestore className="mr-1.5 size-3.5" />
                      {restoringId === run.backup_id ? "Restoring…" : "Restore this version"}
                    </Button>
                  )}
                </div>
              ))}
              <p className="text-[11px] text-muted-foreground">
                Restoring shows you the exact library file it replaces first, and saves that file
                before overwriting it. Pinning, retention and deleting live on the{" "}
                <Link to="/backups" className="underline underline-offset-2 hover:text-foreground">
                  Backups page
                </Link>
                .
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}

function baseName(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function Facts({ items }: { items: Array<[string, string, string?]> }) {
  return (
    <div className="grid grid-cols-2 gap-x-2.5 gap-y-3">
      {items.map(([key, value, sub]) => (
        <div key={key}>
          <p className="font-mono text-[9.5px] tracking-[0.1em] text-foreground-3 uppercase">
            {key}
          </p>
          <p className="mt-0.5 font-display text-[15px] font-semibold text-foreground">
            {value}
            {sub && (
              <span className="ml-1 text-[11px] font-normal text-muted-foreground">{sub}</span>
            )}
          </p>
        </div>
      ))}
    </div>
  );
}

function MisplacedWarning({ count, onRepair }: { count: number; onRepair: () => void }) {
  return (
    <div className="rounded-md border border-amber-500/40 bg-amber-500/8 p-2.5">
      <p className="flex items-center gap-2 text-[12px] font-medium text-amber-100">
        <IconAlertTriangle className="size-3.5 flex-none" />
        {count} file{count === 1 ? " is" : "s are"} in the wrong place
      </p>
      <p className="mt-1 text-[11px] text-amber-50/75">
        Nested one level too deep, inside a folder named after the file, so your media server cannot
        see {count === 1 ? "it" : "them"}.
      </p>
      <Button
        variant="outline"
        size="sm"
        onClick={onRepair}
        className="mt-2 h-6 w-full border-amber-500/40 px-2 text-[11px] text-amber-100 hover:bg-amber-500/12"
      >
        <IconTool className="mr-1.5 size-3.5" />
        Repair {count === 1 ? "it" : "them"}
      </Button>
    </div>
  );
}

/**
 * Why a title shows "Not on remote".
 *
 * The badge is easy to misread as "we have not looked yet", and the natural
 * next move is to hunt for a button that re-checks it. There is nothing to
 * re-check: the comparison ran and the remote had no episodes. Saying so here
 * is the difference between a dead end and an answer.
 */
function NotOnRemoteNote({ counts }: { counts: ExploreCounts }) {
  return (
    <div className="rounded-md border border-border bg-muted/30 p-2.5">
      <p className="text-[12px] font-medium text-foreground">Nothing to compare</p>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {counts.local_only > 0 ? (
          <>
            The remote holds no episodes here, so there is nothing to measure your copy against. The{" "}
            {counts.local_only} file{counts.local_only === 1 ? "" : "s"} below are yours alone —
            either the remote never had them, or it has since dropped them. Re-checking will report
            the same thing.
          </>
        ) : (
          <>Neither side holds any episodes here. The folder exists but is empty of media.</>
        )}
      </p>
    </div>
  );
}

/**
 * A season folder that is not named the way Sonarr names them.
 *
 * Nothing is broken: seasons pair by number, so "Season 1" lines up with
 * "Season 01" and syncs into whichever spelling is already on disk. It is shown
 * because the drift is worth knowing about before it spreads, not because it
 * blocks anything.
 */
function NamingWarning({ folders, expected }: { folders?: string[]; expected: string | null }) {
  if (!folders?.length) return null;
  return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/6 p-2.5">
      <p className="flex items-center gap-2 text-[12px] font-medium text-amber-100">
        <IconAlertTriangle className="size-3.5 flex-none" />
        {folders.length === 1 ? "Season folder is" : "Season folders are"} named differently
      </p>
      <p className="mt-1 text-[11px] text-amber-50/75">
        <span className="font-mono">{folders.join(", ")}</span>
        {expected ? (
          <>
            {" "}
            — Sonarr writes <span className="font-mono">{expected}</span>.
          </>
        ) : null}{" "}
        Syncing works either way; new files go into the folder you already have.
      </p>
    </div>
  );
}

function Action({
  Icon,
  title,
  detail,
  onClick,
  primary,
}: {
  Icon: typeof IconDownload;
  title: string;
  detail: string;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left",
        primary
          ? "bg-brand-gradient-x text-white shadow-[0_10px_24px_-14px_var(--brand)]"
          : "border border-border hover:bg-accent"
      )}
    >
      <Icon className={cn("size-4 flex-none", primary ? "text-white" : "text-muted-foreground")} />
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-semibold">{title}</span>
        {detail && (
          <span
            className={cn(
              "mt-px block text-[11px] leading-[15px]",
              primary ? "text-white/70" : "text-muted-foreground"
            )}
          >
            {detail}
          </span>
        )}
      </span>
    </button>
  );
}

function NoSession() {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="max-w-md rounded-xl border border-amber-500/30 bg-amber-500/8 p-5">
        <p className="flex items-center gap-2 text-sm font-medium text-amber-100">
          <IconPlugConnected className="size-4" />
          Remote browse session required
        </p>
        <p className="mt-2 text-sm text-amber-50/80">
          Explore compares your local library against the remote one, so it needs the SSH browse
          connection. Connect it in Settings and come back.
        </p>
        <Link to="/settings" className="mt-4 inline-block">
          <Button variant="outline" size="sm">
            <IconSettings className="mr-2 size-4" />
            Open Settings
          </Button>
        </Link>
      </div>
    </div>
  );
}

function messageFrom(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { message?: string } } })?.response;
  return response?.data?.message ?? fallback;
}
