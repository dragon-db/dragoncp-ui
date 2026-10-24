import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import {
  IconAlertTriangle,
  IconCloudUpload,
  IconPaperclip,
  IconSearch,
  IconTestPipe,
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
import { Checkbox } from "@/components/ui/checkbox";
import { FilenameDiff } from "@/components/webhooks/filename-diff";
import { cn } from "@/lib/utils";
import type { RenameItem, RenamePlan } from "@/lib/rename-types";

/**
 * The review in front of a rename.
 *
 * Every file is named old over new, with only the title tinted, because "rename
 * 12 files" is not something to approve without seeing the names. What waits,
 * and why, is in the same dialog: a rename that quietly covers 12 of 30 reads
 * as finished.
 */
export function RenameDialog({
  open,
  onOpenChange,
  plan,
  loading,
  error,
  submitting,
  onConfirm,
  onFindOnTmdb,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: RenamePlan | null;
  loading: boolean;
  error: string | null;
  submitting: boolean;
  onConfirm: (picks: Array<{ path: string; new_name: string }>) => void;
  /** Opens the TMDB search for a series Sonarr does not have. */
  onFindOnTmdb: () => void;
}) {
  const ready = useMemo(() => plan?.items.filter((i) => i.state === "ready") ?? [], [plan]);
  const waiting = plan?.items.filter((i) => i.state !== "ready") ?? [];
  // Files left out by a person, so a fresh plan starts with everything ticked.
  const [unpicked, setUnpicked] = useState<Set<string>>(new Set());
  const [planSeen, setPlanSeen] = useState<RenamePlan | null>(null);
  if (plan !== planSeen) {
    setPlanSeen(plan);
    setUnpicked(new Set());
  }

  const picked = ready.filter((i) => !unpicked.has(i.path));
  const toSonarr = picked.filter((i) => i.sonarr_rename).length;
  const sidecars = picked.reduce((sum, i) => sum + i.sidecars.length, 0);
  const blocker = plan?.blocker ?? null;
  const rehearsal = Boolean(plan?.test_mode);
  const needsLink = plan?.sonarr.state === "missing" && plan?.tmdb.state === "unlinked";
  const needsKey = plan?.sonarr.state === "missing" && plan?.tmdb.state === "off";

  const toggle = (path: string) =>
    setUnpicked((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="text-[15px]">Give these episodes their real titles</DialogTitle>
          <DialogDescription className="text-[12.5px]">
            Only the title part of each name changes. Subtitles, .nfo and artwork take the new name
            with their episode. Nothing is overwritten, and Undo is in Webhooks → Renames.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[58vh] overflow-y-auto px-5 py-4">
          {loading ? (
            <p className="text-[12.5px] text-muted-foreground">
              Asking Sonarr for this series’ titles…
            </p>
          ) : error ? (
            <Notice tone="rose">{error}</Notice>
          ) : plan ? (
            <div className="flex flex-col gap-3">
              {rehearsal && (
                <Notice tone="sky" icon={IconTestPipe}>
                  Test mode: this is a rehearsal. Nothing is renamed here or in Sonarr.
                </Notice>
              )}
              {blocker && <Notice tone="amber">{blocker}</Notice>}
              <SourceLine plan={plan} />

              {needsLink && (
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-violet-500/35 bg-violet-500/8 p-2.5 text-[12px] text-violet-100">
                  <span className="min-w-0 flex-1">
                    This series is not in Sonarr. Find it on TMDB once, and its episodes get titles
                    from there.
                  </span>
                  <Button size="sm" variant="outline" onClick={onFindOnTmdb}>
                    <IconSearch className="mr-1.5 size-3.5" />
                    Find titles on TMDB
                  </Button>
                </div>
              )}
              {needsKey && (
                <Notice tone="violet">
                  This series is not in Sonarr. Add a TMDB key on{" "}
                  <Link
                    to="/integrations/$connector"
                    params={{ connector: "sonarr" }}
                    className="underline underline-offset-2"
                  >
                    Sonarr’s Connection tab
                  </Link>{" "}
                  to find titles for it.
                </Notice>
              )}

              {ready.length > 0 && (
                <ul className="flex flex-col gap-2">
                  {ready.map((item) => (
                    <ReadyRow
                      key={item.path}
                      item={item}
                      picked={!unpicked.has(item.path)}
                      onToggle={() => toggle(item.path)}
                    />
                  ))}
                </ul>
              )}

              {waiting.length > 0 && (
                <div className="rounded-md border border-border p-3">
                  <p className="text-[12px] font-medium text-foreground-2">
                    {waiting.length} not renamed yet
                  </p>
                  <ul className="mt-1.5 flex flex-col gap-1">
                    {waiting.map((item) => (
                      <li key={item.path} className="text-[11.5px] text-muted-foreground">
                        <span className="font-mono text-foreground-2">{item.code}</span> —{" "}
                        <span className={cn(item.state === "skipped" && "text-amber-200/90")}>
                          {item.reason}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {plan.items.length === 0 && (
                <p className="text-[12.5px] text-muted-foreground">
                  Nothing here is named TBA any more.
                </p>
              )}
            </div>
          ) : null}
        </div>

        {/* `mx-0 mb-0` cancels the footer's `-mx-4 -mb-4`; see restore-dialog. */}
        <DialogFooter className="mx-0 mb-0 items-center gap-2 border-t border-border px-5 py-3 sm:justify-between">
          <span className="min-w-0 font-mono text-[11px] text-muted-foreground tabular-nums">
            {[
              picked.length ? `${picked.length} here` : "",
              toSonarr ? `${toSonarr} in Sonarr` : "",
              sidecars ? `${sidecars} sidecar${sidecars === 1 ? "" : "s"}` : "",
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
                loading || submitting || Boolean(error) || Boolean(blocker) || picked.length === 0
              }
              onClick={() =>
                onConfirm(picked.map((i) => ({ path: i.path, new_name: i.new_name ?? "" })))
              }
            >
              {submitting
                ? "Renaming…"
                : `${rehearsal ? "Rehearse" : "Rename"} ${picked.length || ""}`.trim()}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReadyRow({
  item,
  picked,
  onToggle,
}: {
  item: RenameItem;
  picked: boolean;
  onToggle: () => void;
}) {
  return (
    <li
      className={cn(
        "flex gap-2.5 rounded-md border border-border/70 p-2.5",
        !picked && "opacity-55"
      )}
    >
      <Checkbox
        checked={picked}
        onCheckedChange={onToggle}
        aria-label={`Rename ${item.code}`}
        className="mt-1"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <span className="font-mono font-semibold text-brand-hover">{item.code}</span>
          <Chip>{item.source === "tmdb" ? "Title from TMDB" : "Title from Sonarr"}</Chip>
          {item.sonarr_rename && (
            <Chip tone="emerald">
              <IconCloudUpload className="size-3" />
              Sonarr renames its copy too
            </Chip>
          )}
          {item.retitle && <Chip tone="violet">Replaces the TMDB title</Chip>}
        </div>
        <FilenameDiff before={item.old_name} after={item.new_name ?? ""} />
        {item.sidecars.length > 0 && (
          <p
            className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
            title={item.sidecars.map((s) => s.new).join("\n")}
          >
            <IconPaperclip className="size-3 flex-none opacity-70" />
            {item.sidecars.length} file{item.sidecars.length === 1 ? "" : "s"} move with it:{" "}
            {item.sidecars.map((s) => sidecarKind(s.old, item.old_name)).join(", ")}
          </p>
        )}
      </div>
    </li>
  );
}

/** Where the titles come from, in one line. */
function SourceLine({ plan }: { plan: RenamePlan }) {
  const parts: string[] = [plan.sonarr.message];
  if (plan.tmdb.state === "linked" && plan.tmdb.name) {
    parts.push(`TMDB: ${plan.tmdb.name}`);
  } else if (plan.tmdb.state === "off") {
    parts.push("No TMDB key");
  }
  return (
    <p className="font-mono text-[10.5px] tracking-[0.04em] text-foreground-3 uppercase">
      {parts.filter(Boolean).join(" · ")}
    </p>
  );
}

/** `.nfo`, `.en.srt`, `-thumb.jpg`: what follows the video's own name. */
function sidecarKind(sidecar: string, video: string): string {
  const stem = video.replace(/\.[^.]+$/, "");
  return sidecar.startsWith(stem) ? sidecar.slice(stem.length) : sidecar;
}

function Chip({ children, tone }: { children: React.ReactNode; tone?: "emerald" | "violet" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-px font-mono text-[9.5px] tracking-[0.04em] uppercase",
        tone === "emerald"
          ? "border-emerald-500/40 text-emerald-300"
          : tone === "violet"
            ? "border-violet-500/40 text-violet-300"
            : "border-border/70 text-foreground-3"
      )}
    >
      {children}
    </span>
  );
}

const NOTICE_TONES = {
  rose: "border-rose-500/40 bg-rose-500/8 text-rose-100",
  amber: "border-amber-500/40 bg-amber-500/8 text-amber-100",
  sky: "border-sky-500/40 bg-sky-500/8 text-sky-100",
  violet: "border-violet-500/35 bg-violet-500/8 text-violet-100",
};

function Notice({
  tone,
  icon: Icon = IconAlertTriangle,
  children,
}: {
  tone: keyof typeof NOTICE_TONES;
  icon?: typeof IconAlertTriangle;
  children: React.ReactNode;
}) {
  return (
    <p
      className={cn(
        "flex items-start gap-2 rounded-md border p-2.5 text-[12.5px]",
        NOTICE_TONES[tone]
      )}
    >
      <Icon className="mt-px size-4 flex-none" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}
