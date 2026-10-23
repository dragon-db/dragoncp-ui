import { useState } from "react";
import { IconChevronRight, IconTestPipe } from "@tabler/icons-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import type { RenameAllPlan } from "@/lib/rename-types";

/**
 * Every ready episode in a library, one series per row.
 *
 * The names come from the last title check, so opening this asks Sonarr
 * nothing. Each series is confirmed with Sonarr again as it is renamed, which
 * is why a name can still change slightly: Sonarr's own name wins for a file it
 * holds, so both ends match.
 */
export function RenameAllDialog({
  open,
  onOpenChange,
  plan,
  loading,
  error,
  submitting,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: RenameAllPlan | null;
  loading: boolean;
  error: string | null;
  submitting: boolean;
  onConfirm: (folders: string[]) => void;
}) {
  const series = plan?.series ?? [];
  const [unpicked, setUnpicked] = useState<Set<string>>(new Set());
  const [openRows, setOpenRows] = useState<Set<string>>(new Set());
  const [planSeen, setPlanSeen] = useState<RenameAllPlan | null>(null);
  if (plan !== planSeen) {
    setPlanSeen(plan);
    setUnpicked(new Set());
    setOpenRows(new Set());
  }

  const picked = series.filter((s) => !unpicked.has(s.folder));
  const files = picked.reduce((sum, s) => sum + s.items.length, 0);
  const flip = (setter: typeof setUnpicked, key: string) =>
    setter((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="text-[15px]">Rename every ready episode</DialogTitle>
          <DialogDescription className="text-[12.5px]">
            One series at a time, in the background. Sonarr renames its own copy where it still
            holds one. Each series is its own run in Webhooks → Renames, with its own Undo.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[58vh] overflow-y-auto px-5 py-4">
          {loading ? (
            <p className="text-[12.5px] text-muted-foreground">Reading the last title check…</p>
          ) : error ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/8 p-2.5 text-[12.5px] text-rose-100">
              {error}
            </p>
          ) : series.length === 0 ? (
            <p className="text-[12.5px] text-muted-foreground">
              Nothing is ready to rename. Check titles finds out whether any have arrived.
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              {plan?.test_mode && (
                <p className="flex items-center gap-2 rounded-md border border-sky-500/40 bg-sky-500/8 p-2.5 text-[12.5px] text-sky-100">
                  <IconTestPipe className="size-4 flex-none" />
                  Test mode: this is a rehearsal. Nothing is renamed here or in Sonarr.
                </p>
              )}
              <ul className="flex flex-col gap-1.5">
                {series.map((entry) => {
                  const isPicked = !unpicked.has(entry.folder);
                  const isOpen = openRows.has(entry.folder);
                  return (
                    <li
                      key={entry.folder}
                      className={cn(
                        "rounded-md border border-border/70",
                        !isPicked && "opacity-55"
                      )}
                    >
                      <div className="flex items-center gap-2.5 px-2.5 py-2">
                        <Checkbox
                          checked={isPicked}
                          onCheckedChange={() => flip(setUnpicked, entry.folder)}
                          aria-label={`Rename ${entry.folder}`}
                        />
                        <button
                          type="button"
                          onClick={() => flip(setOpenRows, entry.folder)}
                          className="flex min-w-0 flex-1 items-center gap-2 text-left"
                        >
                          <IconChevronRight
                            className={cn(
                              "size-3.5 flex-none text-muted-foreground transition-transform",
                              isOpen && "rotate-90"
                            )}
                          />
                          <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">
                            {entry.folder}
                          </span>
                          <span className="flex-none font-mono text-[11px] text-foreground-3">
                            {entry.items.length} file{entry.items.length === 1 ? "" : "s"}
                          </span>
                        </button>
                      </div>
                      {isOpen && (
                        <ul className="flex flex-col gap-1 border-t border-border/70 px-3 py-2">
                          {entry.items.map((item) => (
                            <li
                              key={item.old_name}
                              className="font-mono text-[11px] break-all text-emerald-200/90"
                            >
                              <span className="text-brand-hover">{item.code}</span> →{" "}
                              {item.new_name}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>

        <DialogFooter className="mx-0 mb-0 items-center gap-2 border-t border-border px-5 py-3 sm:justify-between">
          <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
            {picked.length > 0 &&
              `${files} file${files === 1 ? "" : "s"} in ${picked.length} series`}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={loading || submitting || picked.length === 0 || Boolean(plan?.running)}
              onClick={() => onConfirm(picked.map((s) => s.folder))}
            >
              {plan?.running
                ? "Already running"
                : submitting
                  ? "Starting…"
                  : `${plan?.test_mode ? "Rehearse" : "Rename"} ${files || ""}`.trim()}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
