import { useState } from "react";
import { toast } from "sonner";
import {
  IconAlertTriangle,
  IconArrowsShuffle,
  IconDatabaseCog,
  IconDeviceFloppy,
  IconFolderQuestion,
  IconTrash,
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/lib/explore-format";
import {
  useMigrationApply,
  useMigrationPlan,
  useRetentionApply,
  useRetentionPreview,
  useSaveRetention,
} from "@/hooks/useBackups";
import type { DiskUsage, MigrationReport, RetentionRule } from "@/lib/backup-types";

/**
 * Disk pressure, the retention rule, and the one-off migration.
 *
 * Disk usage is shown and never acted on: pruning keyed to free space fires at
 * unpredictable moments, which for a recovery tool is exactly the wrong
 * property. The number goes in front of the operator and the decision stays
 * theirs.
 */

export function DiskBar({ disk }: { disk: DiskUsage | null }) {
  if (!disk) return null;
  const tone =
    disk.percent_used >= 90 ? "bg-rose-500" : disk.percent_used >= 75 ? "bg-amber-500" : "bg-brand";

  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="font-mono text-[10px] tracking-[0.06em] text-muted-foreground uppercase">
          Backup disk
        </span>
        <span className="font-mono text-[11px] tabular-nums">
          {formatBytes(disk.free)} free of {formatBytes(disk.total)}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", tone)}
          style={{ width: `${disk.percent_used}%` }}
        />
      </div>
      <div className="mt-1.5 text-[11px] text-muted-foreground">
        {disk.percent_used}% used
        {disk.percent_used >= 75 && " — old versions are worth pruning"}
      </div>
    </div>
  );
}

export function RetentionDialog({
  open,
  onOpenChange,
  rule,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rule: RetentionRule;
}) {
  const [keep, setKeep] = useState(String(rule.keep));
  const [grace, setGrace] = useState(String(rule.grace_hours));
  const preview = useRetentionPreview();
  const apply = useRetentionApply();
  const save = useSaveRetention();

  const values = { keep: Number(keep) || rule.keep, grace_hours: Number(grace) || 0 };
  const changed = values.keep !== rule.keep || values.grace_hours !== rule.grace_hours;

  // The backend reports whether it has a writable store. Without one the rule
  // lives in the env file and a restart, so offering a Save that can only
  // return an error is worse than saying so. Preview and a one-off clean-up
  // still work — they do not persist anything.
  const savable = rule.editable !== false;

  /**
   * Which rule the shown preview belongs to.
   *
   * Removing versions has no undo, so the button may only ever delete the set
   * that is on screen. Editing the numbers after previewing used to leave the
   * old list visible while the button applied the NEW rule — preview "keep 10",
   * type 1, and it would delete the far larger keep-1 set unseen.
   */
  const [previewedFor, setPreviewedFor] = useState<string | null>(null);
  const signature = `${values.keep}:${values.grace_hours}`;
  const previewIsCurrent = Boolean(preview.data) && previewedFor === signature;

  function editRule(setter: (next: string) => void, next: string) {
    setter(next);
    setPreviewedFor(null);
    preview.reset();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Retention</DialogTitle>
          <DialogDescription className="text-[12.5px]">
            How many old versions of each movie or episode to keep. Pinned versions are never
            removed, and neither is anything newer than the grace period. Saved settings live in the
            database, so they take effect without a restart.
          </DialogDescription>
        </DialogHeader>

        {!savable && (
          <div className="rounded-lg border border-amber-500/35 bg-amber-500/[0.08] px-3 py-2.5 text-[12.5px] text-amber-400">
            No settings store is available, so this rule can only be changed in
            <code className="mx-1 font-mono text-[11.5px]">dragoncp_env.env</code>
            on the server. You can still preview and run a one-off clean-up below.
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="retention-keep">Versions to keep</Label>
            <Input
              id="retention-keep"
              type="number"
              min={1}
              max={50}
              value={keep}
              disabled={!savable}
              onChange={(event) => editRule(setKeep, event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="retention-grace">Grace period (hours)</Label>
            <Input
              id="retention-grace"
              type="number"
              min={0}
              value={grace}
              disabled={!savable}
              onChange={(event) => editRule(setGrace, event.target.value)}
            />
          </div>
        </div>

        {preview.data && previewIsCurrent && (
          <div className="rounded-lg border border-border bg-muted/25 px-3 py-2.5 text-[12.5px]">
            {preview.data.candidate_count === 0 ? (
              <span className="text-muted-foreground">
                Nothing would be removed under this rule.
              </span>
            ) : (
              <>
                <div className="mb-1.5">
                  <strong>{preview.data.candidate_count}</strong> version(s) would be removed,
                  reclaiming <strong>{formatBytes(preview.data.candidate_size)}</strong>.
                </div>
                <ul className="max-h-40 space-y-0.5 overflow-y-auto">
                  {preview.data.candidates.slice(0, 20).map((candidate) => (
                    <li key={candidate.capture_id} className="truncate text-muted-foreground">
                      {candidate.display}
                    </li>
                  ))}
                </ul>
                {preview.data.candidate_count > 20 && (
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    …and {preview.data.candidate_count - 20} more
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {!previewIsCurrent && (
          <p className="text-[12px] text-muted-foreground">
            Preview to see exactly which versions this rule would remove. Nothing can be removed
            until you have, and editing the numbers means previewing again.
          </p>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          <Button
            variant="secondary"
            disabled={save.isPending || !changed || !savable}
            onClick={() =>
              save.mutate(values, {
                onSuccess: () => toast.success("Retention saved"),
                onError: () => toast.error("Could not save retention"),
              })
            }
          >
            <IconDeviceFloppy className="size-4" />
            {save.isPending ? "Saving…" : "Save rule"}
          </Button>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() =>
                preview.mutate(values, { onSuccess: () => setPreviewedFor(signature) })
              }
              disabled={preview.isPending}
            >
              {preview.isPending ? "Checking…" : "Preview"}
            </Button>
            <Button
              variant="destructive"
              disabled={apply.isPending || !previewIsCurrent || !preview.data?.candidate_count}
              onClick={() =>
                apply.mutate(values, {
                  onSuccess: (result) => {
                    toast.success(result.message);
                    preview.reset();
                    setPreviewedFor(null);
                    onOpenChange(false);
                  },
                  onError: () => toast.error("Could not apply retention"),
                })
              }
            >
              <IconTrash className="size-4" />
              {apply.isPending ? "Removing…" : "Remove them now"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MigrationDialog({
  open,
  onOpenChange,
  legacyFolders,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  legacyFolders: number;
}) {
  const [report, setReport] = useState<MigrationReport | null>(null);
  const plan = useMigrationPlan();
  const apply = useMigrationApply();

  const blocked = report?.blocked ?? null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Adopt the old backup folders</DialogTitle>
          <DialogDescription className="text-[12.5px]">
            {legacyFolders} folder(s) from the previous per-transfer layout are still on the disk.
            This identifies what is in them and files each one under the movie or episode it belongs
            to. Preview first — nothing moves until you say so. Moving re-reads the disk, so a
            folder that appeared or changed since the preview is handled as it is then; nothing is
            deleted either way.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
          {blocked && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/35 bg-amber-500/[0.08] px-3 py-2.5 text-[12.5px] text-amber-400">
              <IconAlertTriangle className="mt-px size-4 flex-none" />
              <span>{blocked}</span>
            </div>
          )}

          {report && !blocked && (
            <>
              {report.active_folder_count > 0 && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-500/35 bg-amber-500/[0.08] px-3 py-2.5 text-[12.5px] text-amber-400">
                  <IconAlertTriangle className="mt-px size-4 flex-none" />
                  <span>
                    {report.active_folder_count} folder(s) were written to in the last few minutes
                    and were left alone. If another instance shares this backup disk, wait until it
                    is idle and preview again.
                  </span>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "Folders", value: report.folders_seen },
                  { label: "Empty", value: report.empty_folder_count },
                  { label: "Identified", value: report.move_count },
                  { label: "Unidentified", value: report.unidentified_count },
                ].map((tile) => (
                  <div key={tile.label} className="rounded-lg border border-border px-3 py-2">
                    <div className="font-mono text-[9.5px] tracking-[0.06em] text-muted-foreground uppercase">
                      {tile.label}
                    </div>
                    <div className="font-display text-lg font-semibold tabular-nums">
                      {tile.value}
                    </div>
                  </div>
                ))}
              </div>

              <p className="text-[12.5px] text-muted-foreground">
                {formatBytes(report.total_size)} in total. Anything unidentified is kept and listed
                separately — nothing is deleted for not being recognised.
              </p>

              {report.moves.length > 0 && (
                <div className="rounded-lg border border-border">
                  <div className="border-b border-border/70 px-3 py-1.5 font-mono text-[10px] tracking-[0.1em] text-muted-foreground uppercase">
                    Where they would go
                  </div>
                  <ul className="max-h-52 divide-y divide-border/50 overflow-y-auto">
                    {report.moves.slice(0, 100).map((move) => (
                      <li key={move.source} className="px-3 py-1.5 text-[12px]">
                        <div className="truncate font-medium">{move.display}</div>
                        <div className="truncate font-mono text-[10.5px] text-muted-foreground">
                          {move.target}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {report.errors.length > 0 && (
                <div className="rounded-lg border border-rose-500/35 bg-rose-500/[0.07] px-3 py-2 text-[12px] text-rose-300">
                  {report.errors.slice(0, 5).map((error) => (
                    <div key={error}>{error}</div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            disabled={plan.isPending}
            onClick={() =>
              plan.mutate(undefined, {
                onSuccess: setReport,
                onError: () => toast.error("Could not read the old folders"),
              })
            }
          >
            {plan.isPending ? "Reading…" : "Preview"}
          </Button>
          <Button
            disabled={!report || Boolean(blocked) || apply.isPending || report.applied}
            onClick={() =>
              apply.mutate(undefined, {
                onSuccess: (result) => {
                  setReport(result);
                  toast.success(result.message);
                },
                onError: (error: unknown) => {
                  // A refusal comes back 409 with the reason — a transfer is
                  // running, or the disk could not be checked. Say which.
                  const body = (
                    error as { response?: { data?: { message?: string } & MigrationReport } }
                  )?.response?.data;
                  if (body) setReport(body as MigrationReport);
                  toast.error(body?.message ?? "Migration failed");
                },
              })
            }
          >
            <IconArrowsShuffle className="size-4" />
            {apply.isPending ? "Moving…" : "Move them"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function HousekeepingBar({
  legacyFolders,
  unsortedCount,
  onOpenRetention,
  onOpenMigration,
  onRebuild,
  rebuilding,
}: {
  legacyFolders: number;
  unsortedCount: number;
  onOpenRetention: () => void;
  onOpenMigration: () => void;
  onRebuild: () => void;
  rebuilding: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {legacyFolders > 0 && (
        <Button variant="outline" size="sm" onClick={onOpenMigration}>
          <IconArrowsShuffle className="size-4" />
          Adopt {legacyFolders} old folder{legacyFolders === 1 ? "" : "s"}
        </Button>
      )}
      {unsortedCount > 0 && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/35 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-400">
          <IconFolderQuestion className="size-3.5" />
          {unsortedCount} unidentified
        </span>
      )}
      <Button variant="outline" size="sm" onClick={onOpenRetention}>
        <IconTrash className="size-4" />
        Retention
      </Button>
      <Button variant="outline" size="sm" onClick={onRebuild} disabled={rebuilding}>
        <IconDatabaseCog className="size-4" />
        {rebuilding ? "Rebuilding…" : "Rebuild index"}
      </Button>
    </div>
  );
}
