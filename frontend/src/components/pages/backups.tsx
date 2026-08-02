import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  IconAlertTriangle,
  IconArchive,
  IconArrowLeft,
  IconChevronRight,
  IconClockHour4,
  IconDeviceTv,
  IconFolder,
  IconLayoutList,
  IconMovie,
  IconPinFilled,
  IconSearch,
  IconSortDescending2,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { StatTiles } from "@/components/layout/stat-tiles";
import { useMediaQuery } from "@/hooks/use-media-query";
import { cn } from "@/lib/utils";
import { formatBytes, formatWhen } from "@/lib/explore-format";
import {
  useBackupSlot,
  useBackupSlots,
  useBackupTitles,
  useBackupsOverview,
  useDeleteBackups,
  useDeletePreview,
  usePinCapture,
  usePlanRestore,
  useRebuildIndex,
  useRestoreCapture,
  useUnsortedBackups,
  type DeleteSelection,
} from "@/hooks/useBackups";
import {
  LIBRARY_LABELS,
  seasonLabel,
  type BackupLibrary,
  type Capture,
  type DeletePreview,
  type RestorePlan,
  type SlotSort,
  type SlotSummary,
} from "@/lib/backup-types";
import { VersionList } from "@/components/backups/version-list";
import { RestoreDialog } from "@/components/backups/restore-dialog";
import {
  ClearUnsortedButton,
  DeleteDialog,
  SelectionBar,
} from "@/components/backups/delete-dialog";
import {
  DiskBar,
  HousekeepingBar,
  MigrationDialog,
  RetentionDialog,
} from "@/components/backups/housekeeping";

/**
 * Backups.
 *
 * Shaped like Explore on purpose — titles on the left, contents on the right,
 * details in an inspector — because they are two views of the same library, and
 * reading them the same way is most of what makes them one system.
 *
 * The unit here is a slot: one movie, or one episode. Versions stack inside it,
 * newest first, and the library holds the current one.
 */

const LIBRARIES = [
  { id: "movies", label: "Movies", Icon: IconMovie },
  { id: "shows", label: "TV Shows", Icon: IconDeviceTv },
  { id: "anime", label: "Anime", Icon: IconLayoutList },
] as const;

type Pane = "titles" | "slots";

export function BackupsPage() {
  const [library, setLibrary] = useState<BackupLibrary>("shows");
  const [title, setTitle] = useState<string | null>(null);
  const [slotKey, setSlotKey] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [pane, setPane] = useState<Pane>("titles");
  const [showRetention, setShowRetention] = useState(false);
  const [showMigration, setShowMigration] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<Capture | null>(null);
  const [restorePlan, setRestorePlan] = useState<RestorePlan | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [sort, setSort] = useState<SlotSort>("recent");

  // Two selections, kept apart on purpose: ticking items in the list means
  // "every version of these", while ticking rows in the inspector means "these
  // specific versions". Merging them would make one checkbox mean two things.
  const [pickedSlots, setPickedSlots] = useState<Set<string>>(new Set());
  const [pickedVersions, setPickedVersions] = useState<Set<string>>(new Set());

  const [pendingDelete, setPendingDelete] = useState<DeleteSelection | null>(null);
  const [deleteScope, setDeleteScope] = useState("");
  const [deletePreview, setDeletePreview] = useState<DeletePreview | null>(null);

  // Two panes side by side from lg up, one at a time below it — which is what
  // makes this usable on a phone without a second layout to keep in step.
  const isWide = useMediaQuery("(min-width: 1024px)");

  const overview = useBackupsOverview();
  const titles = useBackupTitles(library);
  const slots = useBackupSlots({ library, title, search: search.trim() || undefined, sort });
  const slot = useBackupSlot(slotKey);
  const unsorted = useUnsortedBackups((overview.data?.totals.unsorted_count ?? 0) > 0);

  const planRestore = usePlanRestore();
  const restore = useRestoreCapture();
  const pin = usePinCapture();
  const previewDelete = useDeletePreview();
  const removeMany = useDeleteBackups();
  const rebuild = useRebuildIndex();

  /**
   * A title selected under one library means nothing under another, so
   * switching clears both selections. Done here rather than in an effect
   * watching `library` — the reset is part of the click, not a reaction to it.
   */
  function selectLibrary(next: BackupLibrary) {
    if (next === library) return;
    setLibrary(next);
    setTitle(null);
    setSlotKey(null);
    setPane("titles");
    clearSelection();
  }

  function clearSelection() {
    setPickedSlots(new Set());
    setPickedVersions(new Set());
  }

  function toggleSlot(slotKeyToToggle: string) {
    setPickedSlots((current) => {
      const next = new Set(current);
      if (!next.delete(slotKeyToToggle)) next.add(slotKeyToToggle);
      return next;
    });
  }

  function toggleVersion(capture: Capture) {
    setPickedVersions((current) => {
      const next = new Set(current);
      if (!next.delete(capture.capture_id)) next.add(capture.capture_id);
      return next;
    });
  }

  const totals = overview.data?.totals;
  const tiles = useMemo(
    () => [
      { label: "Items", value: totals?.slot_count ?? 0, unit: "with versions" },
      { label: "Versions", value: totals?.capture_count ?? 0, unit: "stored" },
      { label: "Size", value: formatBytes(totals?.total_size), unit: "held" },
      {
        label: "Pinned",
        value: totals?.pinned_count ?? 0,
        unit: "kept always",
        tone: (totals?.pinned_count ?? 0) > 0 ? ("ok" as const) : ("default" as const),
      },
    ],
    [totals]
  );

  function openRestore(capture: Capture) {
    setRestoreTarget(capture);
    setRestorePlan(null);
    planRestore.mutate(
      { captureId: capture.capture_id },
      {
        onSuccess: setRestorePlan,
        onError: () => {
          toast.error("Could not work out what this restore would do");
          setRestoreTarget(null);
        },
      }
    );
  }

  function confirmRestore() {
    if (!restoreTarget) return;
    setBusyId(restoreTarget.capture_id);
    restore.mutate(
      { captureId: restoreTarget.capture_id },
      {
        onSuccess: (result) => {
          toast.success(result.message);
          setRestoreTarget(null);
          setRestorePlan(null);
        },
        onError: (error: unknown) => {
          const message =
            (error as { response?: { data?: { message?: string } } })?.response?.data?.message ??
            "Restore could not be started";
          toast.error(message);
        },
        onSettled: () => setBusyId(null),
      }
    );
  }

  function togglePin(capture: Capture) {
    setBusyId(capture.capture_id);
    pin.mutate(
      { captureId: capture.capture_id, pinned: !capture.pinned },
      {
        onSuccess: (result) => toast.success(result.message),
        onError: () => toast.error("Could not update the pin"),
        onSettled: () => setBusyId(null),
      }
    );
  }

  /**
   * Every delete goes through one path: preview, then confirm.
   *
   * Removing a stored version is the only action on this page with no undo —
   * those files are the last copy of it — so the count and the size are always
   * shown before anything happens, whether one version was picked or fifty.
   */
  function openDelete(selection: DeleteSelection, scope: string) {
    setPendingDelete(selection);
    setDeleteScope(scope);
    setDeletePreview(null);
    previewDelete.mutate(selection, {
      onSuccess: setDeletePreview,
      onError: () => {
        toast.error("Could not work out what this would remove");
        setPendingDelete(null);
      },
    });
  }

  function confirmDelete() {
    if (!pendingDelete) return;
    removeMany.mutate(pendingDelete, {
      onSuccess: (result) => {
        toast.success(result.message);
        setPendingDelete(null);
        setDeletePreview(null);
        clearSelection();
        // The inspector is showing a slot that may no longer have versions.
        if (slot.data && result.deleted_count >= slot.data.captures.length) setSlotKey(null);
      },
      onError: () => toast.error("Could not delete"),
    });
  }

  const selectionCount = pickedSlots.size + pickedVersions.size;

  function deleteSelection() {
    const parts: string[] = [];
    if (pickedSlots.size) parts.push(`${pickedSlots.size} item(s)`);
    if (pickedVersions.size) parts.push(`${pickedVersions.size} version(s)`);
    openDelete(
      {
        slot_keys: pickedSlots.size ? [...pickedSlots] : undefined,
        capture_ids: pickedVersions.size ? [...pickedVersions] : undefined,
      },
      parts.join(" and ")
    );
  }

  const notConfigured = overview.data && !overview.data.configured;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-semibold">Backups</h1>
          <p className="text-[12.5px] text-muted-foreground">
            Every movie and episode a sync has replaced, newest first. Restoring puts one back and
            keeps what it replaced.
          </p>
        </div>
        <HousekeepingBar
          legacyFolders={overview.data?.legacy_folders ?? 0}
          unsortedCount={overview.data?.totals.unsorted_count ?? 0}
          onOpenRetention={() => setShowRetention(true)}
          onOpenMigration={() => setShowMigration(true)}
          rebuilding={rebuild.isPending}
          onRebuild={() =>
            rebuild.mutate(undefined, {
              onSuccess: (result) => toast.success(result.message),
              onError: () => toast.error("Could not rebuild the index"),
            })
          }
        />
      </header>

      {notConfigured && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-500/35 bg-amber-500/[0.08] px-4 py-3">
          <IconAlertTriangle className="mt-0.5 size-5 flex-none text-amber-400" />
          <div className="text-[13px]">
            <div className="font-medium text-amber-400">No backup location is set</div>
            <p className="text-muted-foreground">
              Syncs will refuse to run until one is configured. Nothing is written anywhere else — a
              backup that cannot be restored is worse than none at all.
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-[1fr_18rem]">
        <StatTiles items={tiles} />
        <DiskBar disk={overview.data?.disk ?? null} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-border p-0.5">
          {LIBRARIES.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => selectLibrary(entry.id)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors",
                library === entry.id
                  ? "bg-brand/15 text-brand-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <entry.Icon className="size-4" />
              <span className="hidden sm:inline">{entry.label}</span>
            </button>
          ))}
        </div>

        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <IconSearch className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search titles"
            className="pl-8"
          />
        </div>

        <div className="flex rounded-lg border border-border p-0.5">
          {(
            [
              { id: "recent", label: "Newest", Icon: IconClockHour4 },
              { id: "size", label: "Largest", Icon: IconSortDescending2 },
            ] as const
          ).map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setSort(option.id)}
              title={
                option.id === "size"
                  ? "Biggest first — what to delete when you need space back"
                  : "Most recently replaced first"
              }
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors",
                sort === option.id
                  ? "bg-brand/15 text-brand-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <option.Icon className="size-3.5" />
              <span className="hidden sm:inline">{option.label}</span>
            </button>
          ))}
        </div>

        {!isWide && pane === "slots" && (
          <Button variant="outline" size="sm" onClick={() => setPane("titles")}>
            <IconArrowLeft className="size-4" />
            Titles
          </Button>
        )}
      </div>

      <div className={cn("grid min-h-0 flex-1 gap-4", isWide && "lg:grid-cols-[290px_1fr]")}>
        {(isWide || pane === "titles") && (
          <SectionCard
            label="Titles"
            className="flex min-h-0 flex-col"
            contentClassName="min-h-0 flex-1"
          >
            <ScrollArea className="h-full max-h-[60vh] lg:max-h-[70vh]">
              {titles.isLoading ? (
                <div className="space-y-2 p-3">
                  {[0, 1, 2, 3].map((row) => (
                    <Skeleton key={row} className="h-9 w-full" />
                  ))}
                </div>
              ) : !titles.data?.length ? (
                <SectionEmpty
                  icon={IconFolder}
                  title="Nothing backed up here"
                  hint={`No ${LIBRARY_LABELS[library]} have been replaced yet.`}
                />
              ) : (
                <ul className="p-1.5">
                  <li>
                    <button
                      type="button"
                      onClick={() => setTitle(null)}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors",
                        title === null ? "bg-brand/12 text-brand-foreground" : "hover:bg-muted/60"
                      )}
                    >
                      <IconArchive className="size-3.5 flex-none opacity-70" />
                      <span className="flex-1">Everything</span>
                    </button>
                  </li>
                  {titles.data.map((entry) => (
                    <li key={entry.title}>
                      <button
                        type="button"
                        onClick={() => {
                          setTitle(entry.title);
                          setSlotKey(null);
                          if (!isWide) setPane("slots");
                        }}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors",
                          title === entry.title
                            ? "bg-brand/12 text-brand-foreground"
                            : "hover:bg-muted/60"
                        )}
                      >
                        <span className="min-w-0 flex-1 truncate" title={entry.title}>
                          {entry.title}
                        </span>
                        <span className="flex-none font-mono text-[10px] text-muted-foreground tabular-nums">
                          {entry.capture_count}
                        </span>
                        <span className="w-14 flex-none text-right font-mono text-[10px] text-muted-foreground tabular-nums">
                          {formatBytes(entry.total_size)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </ScrollArea>
          </SectionCard>
        )}

        {(isWide || pane === "slots") && (
          <SectionCard
            label={title ? `Versions in ${title}` : "All versions"}
            description={
              slots.data ? `${slots.data.total} item(s) with stored versions` : undefined
            }
            className="flex min-h-0 flex-col"
            contentClassName="min-h-0 flex-1"
          >
            <ScrollArea className="h-full max-h-[70vh]">
              {slots.isLoading ? (
                <div className="space-y-2 p-3">
                  {[0, 1, 2, 3, 4].map((row) => (
                    <Skeleton key={row} className="h-11 w-full" />
                  ))}
                </div>
              ) : !slots.data?.slots.length ? (
                <SectionEmpty
                  icon={IconArchive}
                  title="Nothing stored here"
                  hint="A version appears once a sync replaces or removes a file."
                />
              ) : (
                <ul className="divide-y divide-border/50">
                  {slots.data.slots.map((entry) => (
                    <SlotRow
                      key={entry.slot_key}
                      slot={entry}
                      active={slotKey === entry.slot_key}
                      picked={pickedSlots.has(entry.slot_key)}
                      onPick={() => toggleSlot(entry.slot_key)}
                      onSelect={() => setSlotKey(entry.slot_key)}
                    />
                  ))}
                </ul>
              )}
            </ScrollArea>
            <SelectionBar
              count={selectionCount}
              onDelete={deleteSelection}
              onClear={clearSelection}
            />
          </SectionCard>
        )}
      </div>

      {(overview.data?.totals.unsorted_count ?? 0) > 0 && unsorted.data && (
        <SectionCard
          label="Unidentified"
          description="Kept but not recognised. Recoverable by hand today, and re-sortable once the parser improves."
          actions={
            <ClearUnsortedButton
              count={unsorted.data.length}
              size={unsorted.data.reduce((total, capture) => total + capture.total_size, 0)}
              busy={previewDelete.isPending || removeMany.isPending}
              onClick={() =>
                openDelete(
                  { capture_ids: unsorted.data!.map((capture) => capture.capture_id) },
                  `all ${unsorted.data!.length} unidentified item(s)`
                )
              }
            />
          }
        >
          <ul className="divide-y divide-border/50">
            {unsorted.data.slice(0, 20).map((capture) => (
              <li key={capture.capture_id} className="flex items-center gap-2 px-4 py-2.5">
                <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-muted-foreground">
                  {capture.capture_path}
                </span>
                <span className="flex-none font-mono text-[10.5px] text-muted-foreground tabular-nums">
                  {capture.file_count} file(s) · {formatBytes(capture.total_size)}
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      <Sheet open={Boolean(slotKey)} onOpenChange={(open) => !open && setSlotKey(null)}>
        <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-xl">
          <SheetTitle className="border-b border-border px-4 py-3 text-[13.5px]">
            {slot.data?.display || "Versions"}
          </SheetTitle>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <VersionList
              captures={slot.data?.captures ?? []}
              current={slot.data?.current ?? null}
              loading={slot.isLoading}
              busyId={busyId}
              selected={pickedVersions}
              onToggle={toggleVersion}
              onRestore={openRestore}
              onPin={togglePin}
              onDelete={(capture) =>
                openDelete({ capture_ids: [capture.capture_id] }, "this version")
              }
            />
          </div>
        </SheetContent>
      </Sheet>

      <RestoreDialog
        open={Boolean(restoreTarget)}
        onOpenChange={(open) => {
          if (!open) {
            setRestoreTarget(null);
            setRestorePlan(null);
          }
        }}
        plan={restorePlan}
        loading={planRestore.isPending}
        submitting={restore.isPending}
        onConfirm={confirmRestore}
      />

      <DeleteDialog
        open={Boolean(pendingDelete)}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
            setDeletePreview(null);
          }
        }}
        preview={deletePreview}
        loading={previewDelete.isPending}
        submitting={removeMany.isPending}
        scope={deleteScope}
        onConfirm={confirmDelete}
      />

      {overview.data && (
        <RetentionDialog
          open={showRetention}
          onOpenChange={setShowRetention}
          rule={overview.data.retention}
        />
      )}
      <MigrationDialog
        open={showMigration}
        onOpenChange={setShowMigration}
        legacyFolders={overview.data?.legacy_folders ?? 0}
      />
    </div>
  );
}

function SlotRow({
  slot,
  active,
  picked,
  onPick,
  onSelect,
}: {
  slot: SlotSummary;
  /** Currently open in the inspector. */
  active: boolean;
  /** Ticked for deletion. */
  picked: boolean;
  onPick: () => void;
  onSelect: () => void;
}) {
  const season = seasonLabel(slot.season_number);
  return (
    <li className={cn("flex items-center", active ? "bg-brand/10" : "hover:bg-muted/40")}>
      {/*
        Base UI's checkbox forwards its click to a hidden input rendered as a
        SIBLING of the box, so a checkbox nested inside the row's button would
        toggle the row straight back. Keeping it outside the button — its own
        interactive element, not inside another — is what makes both work.
      */}
      <div className="flex items-center py-2.5 pr-1 pl-4">
        <Checkbox
          checked={picked}
          onCheckedChange={onPick}
          aria-label={`Select every version of ${slot.display}`}
        />
      </div>

      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-center gap-3 py-2.5 pr-4 pl-2 text-left"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="min-w-0 truncate text-[13px] font-medium">{slot.display}</span>
            {slot.has_pinned === 1 && (
              <IconPinFilled
                className="size-3 flex-none text-brand"
                aria-label="Has a pinned version"
              />
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
            {season && <span>{season}</span>}
            <span>
              {slot.version_count} version{slot.version_count === 1 ? "" : "s"}
            </span>
            <span>·</span>
            <span>{formatBytes(slot.total_size)}</span>
          </div>
        </div>
        <span className="hidden flex-none font-mono text-[10.5px] text-muted-foreground tabular-nums sm:inline">
          {formatWhen(slot.latest_captured_at).split(",")[0]}
        </span>
        <IconChevronRight className="size-4 flex-none text-muted-foreground/60" />
      </button>
    </li>
  );
}

export default BackupsPage;
