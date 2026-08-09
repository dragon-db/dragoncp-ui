import { IconAlertTriangle, IconArrowNarrowRight, IconFolderOff } from "@tabler/icons-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/explore-format";
import type { ExploreRepairPlan } from "@/lib/explore-types";

function basename(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

/**
 * The confirmation in front of a repair.
 *
 * Every file it will touch is named, with the folder that comes down under it,
 * because "move 22 files" is not something anyone should approve without seeing
 * the list. What it refuses to touch is shown in the same dialog rather than
 * left out — a repair that silently covers 20 of 22 files reads as complete.
 */
export function RepairDialog({
  open,
  onOpenChange,
  plan,
  loading,
  submitting,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: ExploreRepairPlan | null;
  loading: boolean;
  submitting: boolean;
  onConfirm: () => void;
}) {
  const actions = plan?.actions ?? [];
  const blocked = plan?.blocked ?? [];
  const blocker = plan?.blocker ?? null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="text-[15px]">Put these files back where they belong</DialogTitle>
          <DialogDescription className="text-[12.5px]">
            Each one is nested a level too deep, inside a folder named after itself, which is why
            your media server cannot see it. Nothing is renamed and nothing is overwritten — the
            file moves up and the empty folder is removed.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[52vh] overflow-y-auto px-5 py-4">
          {loading ? (
            <p className="text-[12.5px] text-muted-foreground">Checking what is out of place…</p>
          ) : blocker ? (
            <p className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/8 p-3 text-[12.5px] text-amber-100">
              <IconAlertTriangle className="mt-px size-4 flex-none" />
              {blocker}
            </p>
          ) : (
            <div className="flex flex-col gap-4">
              {actions.length > 0 && (
                <ul className="flex flex-col gap-2">
                  {actions.map((action) => (
                    <li key={action.relative_path} className="flex flex-col gap-1">
                      <div className="flex min-w-0 items-center gap-2 text-[12.5px]">
                        <span
                          className="min-w-0 flex-1 truncate text-foreground"
                          title={action.name}
                        >
                          {action.name}
                        </span>
                        <span className="flex-none font-mono text-[10.5px] text-muted-foreground tabular-nums">
                          {formatBytes(action.size)}
                        </span>
                      </div>
                      <div className="flex min-w-0 items-center gap-1.5 pl-1 text-[11.5px] text-emerald-300">
                        <IconArrowNarrowRight className="size-3.5 flex-none" />
                        <span className="min-w-0 truncate" title={action.destination}>
                          {action.season_folder ?? basename(action.destination)}
                        </span>
                        <IconFolderOff className="size-3 flex-none opacity-60" />
                        <span className="flex-none font-mono text-[10px] tracking-[0.06em] uppercase opacity-70">
                          folder removed
                        </span>
                      </div>
                    </li>
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
          <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
            {actions.length > 0
              ? `${actions.length} file${actions.length === 1 ? "" : "s"} · ${formatBytes(plan?.total_size ?? 0)}`
              : ""}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={loading || submitting || Boolean(blocker) || actions.length === 0}
              onClick={onConfirm}
            >
              {submitting ? "Moving…" : `Move ${actions.length || ""}`.trim()}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
