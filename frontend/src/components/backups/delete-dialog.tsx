import { IconAlertTriangle, IconPinFilled, IconTrash } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes, formatWhen } from "@/lib/explore-format";
import type { DeletePreview } from "@/lib/backup-types";

/**
 * The confirmation for reclaiming space.
 *
 * Deleting a backup is the one action here with no undo — those files are the
 * last copy of that version — so it always leads with the count and the size,
 * and never guesses at a pinned version.
 */
export function DeleteDialog({
  open,
  onOpenChange,
  preview,
  loading,
  submitting,
  scope,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preview: DeletePreview | null;
  loading: boolean;
  submitting: boolean;
  /** What was selected, in words: "3 versions", "everything in 2 items". */
  scope: string;
  onConfirm: () => void;
}) {
  const nothingToDo = !loading && preview?.count === 0;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="sm:max-w-lg">
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {scope}?</AlertDialogTitle>
          <AlertDialogDescription className="text-[12.5px]">
            {loading
              ? "Working out what this would remove…"
              : nothingToDo
                ? "Nothing would be removed."
                : `This permanently removes ${preview?.count ?? 0} stored version(s) from the backup disk, freeing ${formatBytes(preview?.total_size)}. The library is not touched, and this cannot be undone.`}
          </AlertDialogDescription>
        </AlertDialogHeader>

        {loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-8 w-full" />
            ))}
          </div>
        ) : (
          <>
            {(preview?.skipped_pinned ?? 0) > 0 && (
              <div className="flex items-start gap-2 rounded-lg border border-brand/35 bg-brand/[0.08] px-3 py-2 text-[12px] text-brand-foreground">
                <IconPinFilled className="mt-px size-3.5 flex-none" />
                <span>
                  {preview!.skipped_pinned} pinned version(s) will be left alone. Unpin them first
                  if you want them gone.
                </span>
              </div>
            )}

            {(preview?.captures.length ?? 0) > 0 && (
              <ul className="max-h-56 divide-y divide-border/50 overflow-y-auto rounded-lg border border-border">
                {preview!.captures.slice(0, 100).map((candidate) => (
                  <li
                    key={candidate.capture_id}
                    className="flex items-center gap-2 px-3 py-1.5 text-[12px]"
                  >
                    <span className="min-w-0 flex-1 truncate">{candidate.display}</span>
                    <span className="flex-none text-[10.5px] text-muted-foreground">
                      {formatWhen(candidate.captured_at).split(",")[0]}
                    </span>
                    <span className="w-16 flex-none text-right font-mono text-[10.5px] text-muted-foreground tabular-nums">
                      {formatBytes(candidate.total_size)}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {(preview?.count ?? 0) > 100 && (
              <p className="text-[11px] text-muted-foreground">
                …and {preview!.count - 100} more, all included in the total above.
              </p>
            )}
          </>
        )}

        <AlertDialogFooter className="gap-2">
          <AlertDialogCancel disabled={submitting}>Cancel</AlertDialogCancel>
          <Button
            variant="destructive"
            disabled={loading || submitting || nothingToDo}
            onClick={onConfirm}
          >
            <IconTrash className="size-4" />
            {submitting ? "Deleting…" : `Delete ${formatBytes(preview?.total_size)}`}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** The strip that appears once anything is ticked. */
export function SelectionBar({
  count,
  onDelete,
  onClear,
}: {
  count: number;
  onDelete: () => void;
  onClear: () => void;
}) {
  if (count === 0) return null;
  return (
    <div className="sticky bottom-0 z-20 flex flex-wrap items-center gap-2 border-t border-border bg-card/95 px-4 py-2.5 backdrop-blur-md">
      <span className="text-[12.5px] font-medium">{count} selected</span>
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onClear}>
          Clear
        </Button>
        <Button variant="destructive" size="sm" onClick={onDelete}>
          <IconTrash className="size-4" />
          Delete selected
        </Button>
      </div>
    </div>
  );
}

/** Shown on the unidentified section — the least painful thing to lose. */
export function ClearUnsortedButton({
  count,
  size,
  onClick,
  busy,
}: {
  count: number;
  size: number;
  onClick: () => void;
  busy: boolean;
}) {
  return (
    <Button variant="outline" size="sm" onClick={onClick} disabled={busy}>
      <IconAlertTriangle className="size-4" />
      {busy ? "Removing…" : `Delete all ${count} (${formatBytes(size)})`}
    </Button>
  );
}
