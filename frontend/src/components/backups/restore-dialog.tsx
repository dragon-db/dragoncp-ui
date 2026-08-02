import {
  IconAlertTriangle,
  IconArrowNarrowRight,
  IconFileFilled,
  IconRestore,
} from "@tabler/icons-react";
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
import type { RestorePlan } from "@/lib/backup-types";

/**
 * The confirmation.
 *
 * Every row answers the two questions worth asking before a restore: what is
 * being put back, and what it will replace. Both come from the plan the server
 * built — the same one it will execute — so nothing here is re-derived between
 * the preview and the run.
 */

function basename(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

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
    <div className="border-b border-border/60 px-4 py-3 last:border-b-0">
      <div className="mb-1.5 flex min-w-0 items-center gap-2">
        <IconFileFilled
          className={cn("size-3 flex-none", isMedia ? "text-brand/70" : "text-muted-foreground/50")}
        />
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium" title={target}>
          {basename(target)}
        </span>
        <span className="flex-none font-mono text-[10.5px] text-muted-foreground tabular-nums">
          {formatBytes(size)}
        </span>
      </div>

      {replaces ? (
        <div className="flex min-w-0 items-center gap-1.5 pl-5 text-[11.5px] text-amber-400">
          <IconArrowNarrowRight className="size-3.5 flex-none" />
          <span className="flex-none font-mono text-[10px] tracking-[0.06em] uppercase">
            Replaces
          </span>
          <span className="min-w-0 truncate" title={replaces}>
            {basename(replaces)}
          </span>
          <span className="flex-none font-mono text-[10.5px] tabular-nums opacity-70">
            {formatBytes(replacesSize)}
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 pl-5 text-[11.5px] text-muted-foreground">
          <IconArrowNarrowRight className="size-3.5 flex-none" />
          <span>Nothing to replace — this will be re-added</span>
        </div>
      )}
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
              : `${operations.length} file(s) · ${plan?.replaces_count ?? 0} replacing a file already in the library`}
          </DialogDescription>
        </DialogHeader>

        {plan?.target_dir && !blocked && (
          <div className="border-y border-border/70 bg-muted/25 px-5 py-2">
            <div className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
              Restoring into
            </div>
            <div className="truncate font-mono text-[11.5px]" title={plan.target_dir}>
              {plan.target_dir}
            </div>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2].map((row) => (
                <Skeleton key={row} className="h-12 w-full" />
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
                <div className="border-t border-border/70 bg-amber-500/[0.06] px-5 py-3">
                  {plan!.warnings.map((warning) => (
                    <div
                      key={warning}
                      className="flex items-start gap-2 text-[12px] text-amber-400"
                    >
                      <IconAlertTriangle className="mt-px size-3.5 flex-none" />
                      <span>{warning}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {!blocked && (
          <div className="border-t border-border/70 px-5 py-2.5 text-[11.5px] text-muted-foreground">
            The file each of these replaces is kept first, so this restore can itself be undone.
          </div>
        )}

        <DialogFooter className="gap-2 border-t border-border/70 px-5 py-3.5">
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
