import { IconAlertTriangle, IconFileFilled, IconRestore } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/lib/explore-format";
import { FullPath, PathSwap } from "@/components/backups/full-path";
import type { RestorePlan } from "@/lib/backup-types";

/**
 * The restore confirmation.
 *
 * Every row answers the two questions worth asking before a restore: exactly
 * which file is being written, and exactly which file it writes over. Both come
 * from the plan the server built — the same one it will execute — so nothing
 * here is re-derived between the preview and the run.
 *
 * The paths are shown in full and as a single statement rather than two
 * basenames. A restore replaces one file with another inside the same folder,
 * and two truncated names ending in `.mkv` are not enough to tell which copy
 * you are about to lose.
 */

function OperationRow({
  target,
  replaces,
  replacesSize,
  size,
  isMedia,
}: {
  target: string;
  replaces: string | null;
  replacesSize: number;
  size: number;
  isMedia: boolean;
}) {
  return (
    <div className="border-b border-border/60 px-5 py-3.5 last:border-b-0">
      <div className="mb-2 flex items-center gap-2">
        <IconFileFilled
          className={cn("size-3 flex-none", isMedia ? "text-brand/70" : "text-muted-foreground/50")}
        />
        <span className="font-mono text-[9.5px] tracking-[0.14em] text-muted-foreground uppercase">
          {isMedia ? "Media file" : "Sidecar"}
        </span>
      </div>
      <PathSwap
        incoming={target}
        incomingMeta={formatBytes(size)}
        outgoing={replaces}
        outgoingMeta={replaces ? formatBytes(replacesSize) : undefined}
      />
    </div>
  );
}

export function RestoreDialog({
  open,
  onOpenChange,
  plan,
  loading,
  submitting,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: RestorePlan | null;
  loading: boolean;
  submitting: boolean;
  onConfirm: () => void;
}) {
  const blocked = plan?.blocked ?? null;
  const operations = plan?.operations ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="px-5 pt-5 pb-3">
          <DialogTitle className="text-base">
            Restore {plan?.slot_display || "this version"}
          </DialogTitle>
          <DialogDescription className="text-[12.5px]">
            {blocked
              ? "This restore cannot run."
              : `${operations.length} file(s), ${plan?.replaces_count ?? 0} of them writing over a file already in the library`}
          </DialogDescription>
        </DialogHeader>

        {plan?.target_dir && !blocked && (
          <div className="border-y border-border/70 bg-muted/20 px-5 py-2.5">
            <FullPath label="Restoring into" value={plan.target_dir} />
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2].map((row) => (
                <Skeleton key={row} className="h-20 w-full" />
              ))}
            </div>
          ) : blocked ? (
            <div className="flex items-start gap-3 px-5 py-8">
              <IconAlertTriangle className="size-5 flex-none text-amber-400" />
              <p className="text-[13px] text-pretty">{blocked}</p>
            </div>
          ) : (
            <>
              {operations.map((operation) => (
                <OperationRow
                  key={operation.relative_path}
                  target={operation.target}
                  replaces={operation.replaces}
                  replacesSize={operation.replaces_size}
                  size={operation.file_size}
                  isMedia={operation.is_media}
                />
              ))}
              {(plan?.warnings.length ?? 0) > 0 && (
                <div className="space-y-1 border-t border-border/70 bg-amber-500/[0.06] px-5 py-3">
                  {plan!.warnings.map((warning) => (
                    <div
                      key={warning}
                      className="flex items-start gap-2 text-[12px] text-amber-400"
                    >
                      <IconAlertTriangle className="mt-px size-3.5 flex-none" />
                      <span className="text-pretty">{warning}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {!blocked && (
          <div className="border-t border-border/70 px-5 py-2.5 text-[11.5px] text-muted-foreground">
            Each file this writes over is kept first, so this restore can itself be undone.
          </div>
        )}

        {/*
          `mx-0 mb-0` cancels the footer's own `-mx-4 -mb-4`, which is there to
          undo DialogContent's default `p-4`. This dialog sets `p-0`, so there
          is no padding to undo and those negative margins pull the footer
          sixteen pixels outside the panel on three sides.
        */}
        <DialogFooter className="mx-0 mb-0 gap-2 border-t border-border/70 px-5 py-3.5">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={Boolean(blocked) || loading || submitting || !operations.length}
          >
            <IconRestore className="size-4" />
            {submitting ? "Starting…" : "Restore"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
