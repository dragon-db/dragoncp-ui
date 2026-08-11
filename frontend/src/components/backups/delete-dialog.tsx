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
import { FullPath } from "@/components/layout/full-path";
import type { DeleteCandidate, DeletePreview } from "@/lib/backup-types";

/**
 * The confirmation for reclaiming space.
 *
 * Deleting a version is the one action on this page with no undo — those files
 * are the last copy of it — so it leads with the count and the size, and never
 * quietly takes a pinned version.
 *
 * It also names the files. This dialog used to show a friendly label and a
 * number, which asked an operator to authorise a permanent deletion without
 * ever being shown what leaves the disk: "Show · Season 1 · Episode 2" matches
 * every copy of that episode, and the one being deleted is a specific file in a
 * specific folder.
 */

const LISTED = 100;

function CandidateRow({ candidate }: { candidate: DeleteCandidate }) {
  // Never assumed present. A server that has not been restarted since the file
  // detail was added answers without it, and this dialog guards a deletion with
  // no undo — falling back to the capture folder tells the operator less, but
  // crashing tells them nothing and strands the action entirely.
  const files = candidate.files ?? [];
  const media = files.filter((file) => file.is_media);
  const sidecars = files.length - media.length;

  return (
    <li className="border-b border-border/50 px-3.5 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="min-w-0 text-[12.5px] font-medium break-all">{candidate.display}</span>
        {candidate.pinned && (
          <span className="inline-flex items-center gap-1 rounded-full border border-brand/40 bg-brand/15 px-1.5 text-[9px] font-bold text-brand-foreground uppercase">
            <IconPinFilled className="size-2.5" />
            Pinned
          </span>
        )}
        <span className="ml-auto flex-none font-mono text-[10.5px] text-muted-foreground tabular-nums">
          {formatBytes(candidate.total_size)}
        </span>
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">
        kept {formatWhen(candidate.captured_at)}
      </div>

      <div className="mt-2 space-y-2">
        {media.map((file) => (
          <FullPath
            key={file.relative_path}
            label="Deleting from the backup disk"
            value={
              file.backup_path ??
              `${candidate.capture_dir ?? candidate.capture_path}/${file.relative_path}`
            }
            meta={formatBytes(file.file_size)}
            tone="danger"
          />
        ))}
        {/* Where it came from. The library keeps its current file either way —
            this says which episode the deleted copy was a copy OF. */}
        {media.map(
          (file) =>
            file.original_path && (
              <FullPath
                key={`${file.relative_path}-origin`}
                label="Was taken from"
                value={file.original_path}
              />
            )
        )}
        {/* Keyed on the media files, not on the file list: a version holding
            only sidecars has files but nothing above would draw a path, and the
            confirmation would name no location at all. */}
        {!media.length && (
          <FullPath
            label="Deleting from the backup disk"
            value={candidate.capture_dir ?? candidate.capture_path}
            tone="danger"
          />
        )}
        {sidecars > 0 && (
          <p className="text-[11px] text-muted-foreground">
            and {sidecars} sidecar file{sidecars === 1 ? "" : "s"} in the same folder
          </p>
        )}
      </div>
    </li>
  );
}

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
  // No preview counts as nothing to do, not as something to do. The optional
  // chain made a failed or absent preview leave the button enabled, so a
  // permanent deletion could be confirmed against numbers that never arrived.
  const nothingToDo = !loading && !preview?.count;
  const shown = (preview?.captures ?? []).slice(0, LISTED);
  const beyondListed = (preview?.count ?? 0) - shown.length;
  const beyondDetailed = shown.length - (preview?.detailed ?? shown.length);

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {/*
        The width classes carry the same `data-[size=…]` prefix the base uses.
        Without it a plain `sm:max-w-2xl` never applies: the base sets
        `data-[size=default]:sm:max-w-sm`, which is the more specific selector
        AND a different key to tailwind-merge, so the caller's width is dropped.
        This dialog was already losing that argument — it asked for `sm:max-w-lg`
        and rendered at `sm:max-w-sm`, which is why a list of paths had nowhere
        to go.
      */}
      <AlertDialogContent className="flex max-h-[85vh] flex-col data-[size=default]:max-w-[calc(100vw-2rem)] data-[size=default]:sm:max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {scope}?</AlertDialogTitle>
          <AlertDialogDescription className="text-[12.5px]">
            {loading
              ? "Working out what this would remove…"
              : nothingToDo
                ? "Nothing would be removed."
                : `This permanently removes ${preview?.count ?? 0} stored version(s) from the backup disk, freeing ${formatBytes(preview?.total_size)}. Your media library is not touched, and this cannot be undone.`}
          </AlertDialogDescription>
        </AlertDialogHeader>

        {loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-16 w-full" />
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

            {shown.length > 0 && (
              <ul className="min-h-0 flex-1 divide-y divide-border/50 overflow-y-auto rounded-lg border border-border">
                {shown.map((candidate) => (
                  <CandidateRow key={candidate.capture_id} candidate={candidate} />
                ))}
              </ul>
            )}

            {/* Both limits are stated. A list that silently stops reads as the
                whole set, and the total above would then look wrong. */}
            {beyondListed > 0 && (
              <p className="text-[11px] text-muted-foreground">
                …and {beyondListed} more version(s) not listed here, all included in the total
                above.
              </p>
            )}
            {beyondDetailed > 0 && (
              <p className="text-[11px] text-muted-foreground">
                File paths are shown for the first {preview?.detailed} version(s).
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

/**
 * The strip that appears once anything is ticked.
 *
 * Says what it will delete, not just how many things are ticked. The page has
 * two selections that mean different things — whole items in the list, and
 * specific versions in the inspector — and a bar reading "5 selected" over a
 * permanent deletion does not say which.
 */
export function SelectionBar({
  count,
  noun,
  onDelete,
  onClear,
  docked = true,
}: {
  count: number;
  /** What one of them is: "item", "version". */
  noun: string;
  onDelete: () => void;
  onClear: () => void;
  /**
   * Fixed above the mobile navigation. False inside a sheet, which scrolls in
   * its own right and where a viewport-docked bar would float over the page
   * behind it.
   */
  docked?: boolean;
}) {
  if (count === 0) return null;
  return (
    /*
     * Docked to the viewport on a phone, sticky within its card from `lg` up.
     *
     * `sticky bottom-0` only pins against a scrolling ancestor. On mobile the
     * card flows with the page instead of being height-constrained, so the bar
     * sat at the very bottom of a long list — you could tick five items and the
     * action to do anything with them was a screen and a half away.
     */
    <div
      className={
        docked
          ? "fixed inset-x-0 bottom-[calc(3.75rem+env(safe-area-inset-bottom))] z-40 flex flex-wrap items-center gap-2 border-y border-border bg-card/95 px-4 py-2.5 backdrop-blur-md lg:sticky lg:inset-x-auto lg:bottom-0 lg:z-20 lg:border-y-0 lg:border-t"
          : "sticky bottom-0 z-20 flex flex-wrap items-center gap-2 border-t border-border bg-card/95 px-4 py-2.5 backdrop-blur-md"
      }
    >
      <span className="text-[12.5px] font-medium">
        {count} {noun}
        {count === 1 ? "" : "s"} selected
      </span>
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onClear}>
          Clear
        </Button>
        <Button variant="destructive" size="sm" onClick={onDelete}>
          <IconTrash className="size-4" />
          Delete {count} {noun}
          {count === 1 ? "" : "s"}
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
