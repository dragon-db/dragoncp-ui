import {
  IconAlertTriangle,
  IconArrowNarrowRight,
  IconFolderOff,
  IconTrash,
} from "@tabler/icons-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/lib/explore-format";
import { FullPath } from "@/components/layout/full-path";
import type {
  ExploreRepairAction,
  ExploreRepairPlan,
  RepairChoice,
  RepairDecision,
} from "@/lib/explore-types";

function basename(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

/**
 * A file that can simply be moved: nothing else holds its place.
 *
 * Both ends of the move are spelled out. This used to show the filename
 * truncated and only the destination's season folder, so the one thing it did
 * not say was where the file actually is — which is the whole subject of a
 * repair, since the file being in the wrong place is the problem.
 */
function CleanRow({ action }: { action: ExploreRepairAction }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-md border border-border/70 p-2.5">
      <FullPath label="Now at" value={action.relative_path} meta={formatBytes(action.size)} />
      <div className="flex min-w-0 items-start gap-1.5">
        <IconArrowNarrowRight className="mt-3 size-3.5 flex-none text-emerald-300" />
        <FullPath label="Moves to" value={action.destination} tone="ok" className="flex-1" />
      </div>
      <p className="flex items-center gap-1.5 pl-1 font-mono text-[10px] tracking-[0.06em] text-muted-foreground uppercase">
        <IconFolderOff className="size-3 flex-none opacity-60" />
        the folder it was buried in comes down
      </p>
    </li>
  );
}

/**
 * A file whose place is already held by another copy of the same thing.
 *
 * Both copies are named with their sizes, because that is usually the whole
 * basis for the decision — a 9 GB Bluray beside a 3 GB web copy answers itself.
 * Neither is pre-selected: there is no default here that is right often enough
 * to be worth the times it would be wrong.
 */
function ContestedRow({
  action,
  decision,
  onDecide,
}: {
  action: ExploreRepairAction;
  decision: RepairDecision | undefined;
  onDecide: (choice: RepairChoice | undefined) => void;
}) {
  const rival = action.rival!;
  const strandedWins = decision?.choice === "replace";
  const existingWins = decision?.choice === "keep_existing";

  return (
    <li className="rounded-md border border-amber-500/35 bg-amber-500/[0.05] p-2.5">
      <p className="flex items-center gap-1.5 text-[11px] font-medium text-amber-100">
        <IconAlertTriangle className="size-3.5 flex-none" />
        This is already in your library — keep one
      </p>

      <div className="mt-2 flex flex-col gap-1.5">
        <button
          type="button"
          aria-pressed={existingWins}
          onClick={() => onDecide(existingWins ? undefined : "keep_existing")}
          className={cn(
            "flex min-w-0 items-center gap-2 rounded border px-2 py-1.5 text-left text-[12px] transition-colors",
            existingWins
              ? "border-emerald-500/50 bg-emerald-500/10"
              : "border-border hover:bg-accent/40"
          )}
        >
          <span className="min-w-0 flex-1 font-mono text-[11.5px] leading-[1.45] break-all">
            {rival.relative_path}
          </span>
          <span className="flex-none font-mono text-[10px] tabular-nums opacity-70">
            {formatBytes(rival.size)}
          </span>
          <span className="flex-none font-mono text-[9.5px] tracking-[0.08em] uppercase opacity-60">
            in place
          </span>
        </button>

        <button
          type="button"
          aria-pressed={strandedWins}
          onClick={() => onDecide(strandedWins ? undefined : "replace")}
          className={cn(
            "flex min-w-0 items-center gap-2 rounded border px-2 py-1.5 text-left text-[12px] transition-colors",
            strandedWins
              ? "border-emerald-500/50 bg-emerald-500/10"
              : "border-border hover:bg-accent/40"
          )}
        >
          <span className="min-w-0 flex-1 font-mono text-[11.5px] leading-[1.45] break-all">
            {action.relative_path}
          </span>
          <span className="flex-none font-mono text-[10px] tabular-nums opacity-70">
            {formatBytes(action.size)}
          </span>
          <span className="flex-none font-mono text-[9.5px] tracking-[0.08em] uppercase opacity-60">
            stranded
          </span>
        </button>
      </div>

      <p className="mt-1.5 text-[11px] text-muted-foreground">
        {existingWins ? (
          <>
            Keeping the one in place. The stranded copy is removed — {formatBytes(action.size)}{" "}
            back.
          </>
        ) : strandedWins ? (
          <>Using the stranded copy. The one in place is removed.</>
        ) : (
          <>Nothing happens to either until you pick one.</>
        )}
        {decision ? " The other is kept in Backups, so this can be undone." : ""}
      </p>
    </li>
  );
}

/**
 * The confirmation in front of a repair.
 *
 * Every file it will touch is named, because "move 22 files" is not something
 * anyone should approve without seeing the list. What it refuses to touch is
 * shown in the same dialog rather than left out — a repair that silently covers
 * 20 of 22 files reads as complete.
 */
export function RepairDialog({
  open,
  onOpenChange,
  plan,
  loading,
  error,
  submitting,
  decisions,
  onDecide,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: ExploreRepairPlan | null;
  loading: boolean;
  /** Why the plan could not be read. Distinct from a plan that found nothing. */
  error: string | null;
  submitting: boolean;
  decisions: Record<string, RepairDecision>;
  onDecide: (relativePath: string, choice: RepairChoice | undefined) => void;
  onConfirm: () => void;
}) {
  const actions = plan?.actions ?? [];
  const blocked = plan?.blocked ?? [];
  const blocker = plan?.blocker ?? null;

  const clean = actions.filter((a) => !a.needs_decision);
  const contested = actions.filter((a) => a.needs_decision);
  const decided = contested.filter((a) => decisions[a.relative_path]);
  const undecided = contested.length - decided.length;

  const willMove =
    clean.length + decided.filter((a) => decisions[a.relative_path]?.choice === "replace").length;
  const willDelete = decided.filter(
    (a) => decisions[a.relative_path]?.choice === "keep_existing"
  ).length;
  const nothingToDo = willMove === 0 && willDelete === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="text-[15px]">Put these files back where they belong</DialogTitle>
          <DialogDescription className="text-[12.5px]">
            Each one is nested a level too deep, inside a folder named after itself, which is why
            your media server cannot see it. Nothing is renamed, and anything removed is kept in
            Backups first.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[52vh] overflow-y-auto px-5 py-4">
          {loading ? (
            <p className="text-[12.5px] text-muted-foreground">Checking what is out of place…</p>
          ) : error ? (
            <p className="flex items-start gap-2 rounded-md border border-rose-500/40 bg-rose-500/8 p-3 text-[12.5px] text-rose-100">
              <IconAlertTriangle className="mt-px size-4 flex-none" />
              {error}
            </p>
          ) : blocker ? (
            <p className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/8 p-3 text-[12.5px] text-amber-100">
              <IconAlertTriangle className="mt-px size-4 flex-none" />
              {blocker}
            </p>
          ) : (
            <div className="flex flex-col gap-4">
              {contested.length > 0 && (
                <ul className="flex flex-col gap-2">
                  {contested.map((action) => (
                    <ContestedRow
                      key={action.relative_path}
                      action={action}
                      decision={decisions[action.relative_path]}
                      onDecide={(choice) => onDecide(action.relative_path, choice)}
                    />
                  ))}
                </ul>
              )}

              {clean.length > 0 && (
                <ul className="flex flex-col gap-2">
                  {clean.map((action) => (
                    <CleanRow key={action.relative_path} action={action} />
                  ))}
                </ul>
              )}

              {blocked.length > 0 && (
                <div className="rounded-md border border-amber-500/35 bg-amber-500/8 p-3">
                  <p className="flex items-center gap-2 text-[12px] font-medium text-amber-100">
                    <IconAlertTriangle className="size-3.5 flex-none" />
                    {blocked.length} left alone
                  </p>
                  <ul className="mt-1.5 flex flex-col gap-1">
                    {blocked.map((entry) => (
                      <li key={entry.relative_path} className="text-[11.5px] text-amber-50/80">
                        <span className="text-amber-50">{basename(entry.relative_path)}</span> —{" "}
                        {entry.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {actions.length === 0 && blocked.length === 0 && (
                <p className="text-[12.5px] text-muted-foreground">
                  Nothing is out of place here any more.
                </p>
              )}
            </div>
          )}
        </div>

        {/* `mx-0 mb-0` cancels the footer's `-mx-4 -mb-4`; see restore-dialog. */}
        <DialogFooter className="mx-0 mb-0 items-center gap-2 border-t border-border px-5 py-3 sm:justify-between">
          <span className="min-w-0 font-mono text-[11px] text-muted-foreground tabular-nums">
            {undecided > 0
              ? `${undecided} still need a choice`
              : [
                  willMove > 0 ? `move ${willMove}` : "",
                  willDelete > 0 ? `delete ${willDelete}` : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={
                loading ||
                submitting ||
                Boolean(error) ||
                Boolean(blocker) ||
                nothingToDo ||
                undecided > 0
              }
              onClick={onConfirm}
            >
              {willDelete > 0 && willMove === 0 && <IconTrash className="mr-1.5 size-3.5" />}
              {submitting ? "Working…" : "Apply"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
