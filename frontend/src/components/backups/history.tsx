import { useState } from "react";
import {
  IconArchive,
  IconChevronDown,
  IconChevronRight,
  IconHistory,
  IconRobot,
  IconTrash,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { ActorBadge } from "@/components/activity/actor-badge";
import { FullName, FullPath } from "@/components/backups/full-path";
import { cn } from "@/lib/utils";
import { formatBytes, formatWhen } from "@/lib/explore-format";
import { useBackupHistory } from "@/hooks/useBackups";
import type { ActivityEntry } from "@/lib/api";
import {
  HISTORY_ACTION_LABELS,
  HISTORY_DESTRUCTIVE,
  REASON_LABELS,
  type HistoryDetail,
  type HistoryItem,
  type HistoryLens,
} from "@/lib/backup-types";

/**
 * What the Backups feature has done, and to what.
 *
 * The list on the Library tab shows what still exists. This one exists for the
 * opposite question — "there was a version here and now there is not" — which
 * nothing else on the page can answer, because the version and its index row
 * are both gone by the time anybody asks.
 *
 * The server writes the answer before it deletes anything, so every entry here
 * names the title, the version and the full paths on both sides: where the file
 * lived in the library, and where the kept copy sat on the backup disk.
 */

const LENSES: { id: HistoryLens; label: string; hint: string }[] = [
  { id: "all", label: "Everything", hint: "Every backup action, newest first" },
  { id: "removed", label: "Deleted", hint: "What was removed, by anyone or by the cleanup" },
  { id: "kept", label: "Kept", hint: "Versions created when a sync or repair replaced a file" },
  { id: "restored", label: "Restored", hint: "Versions put back into the library" },
];

const PAGE_SIZE = 25;

export function BackupHistory() {
  const [lens, setLens] = useState<HistoryLens>("all");
  const [page, setPage] = useState(0);

  const history = useBackupHistory(lens, PAGE_SIZE, page * PAGE_SIZE);
  const entries = history.data?.entries ?? [];
  const total = history.data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  function pick(next: HistoryLens) {
    setLens(next);
    setPage(0);
  }

  return (
    <SectionCard
      label="History"
      description="Every version this system created, restored or deleted — including the ones the automatic cleanup took while nobody was watching."
      toolbar={
        <div className="flex flex-wrap items-center gap-1">
          {LENSES.map((entry) => (
            <button
              key={entry.id}
              type="button"
              title={entry.hint}
              onClick={() => pick(entry.id)}
              className={cn(
                "rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors",
                lens === entry.id
                  ? "bg-brand/15 text-brand-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {entry.label}
            </button>
          ))}
          {total > 0 && (
            <span className="ml-auto font-mono text-[10.5px] text-muted-foreground tabular-nums">
              {total} entr{total === 1 ? "y" : "ies"}
            </span>
          )}
        </div>
      }
    >
      {history.isLoading ? (
        <div className="space-y-2 p-4">
          {[0, 1, 2, 3].map((row) => (
            <Skeleton key={row} className="h-14 w-full" />
          ))}
        </div>
      ) : history.isError ? (
        <SectionEmpty
          icon={IconHistory}
          title="The history could not be read"
          hint="The activity trail did not answer. Everything on the Library tab is unaffected."
        />
      ) : !entries.length ? (
        <SectionEmpty
          icon={IconHistory}
          title={lens === "all" ? "Nothing recorded yet" : "Nothing matches this filter"}
          hint={
            lens === "all"
              ? "Entries appear as soon as a sync replaces a file, or anything is restored or deleted."
              : "Try Everything to see the whole trail."
          }
        />
      ) : (
        <>
          <ul className="divide-y divide-border/50">
            {entries.map((entry) => (
              <HistoryRow key={entry.id} entry={entry} />
            ))}
          </ul>
          {lastPage > 0 && (
            <div className="flex items-center justify-between gap-2 border-t border-border/70 px-4 py-2.5">
              <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">
                Page {page + 1} of {lastPage + 1}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((current) => Math.max(0, current - 1))}
                >
                  Newer
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= lastPage}
                  onClick={() => setPage((current) => Math.min(lastPage, current + 1))}
                >
                  Older
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}

function HistoryRow({ entry }: { entry: ActivityEntry }) {
  const [open, setOpen] = useState(false);
  const detail = (entry.detail ?? {}) as HistoryDetail;
  const items = detail.items ?? [];
  const destructive = HISTORY_DESTRUCTIVE.has(entry.action);
  const automatic = Boolean(detail.automatic) && entry.actor_kind !== "admin";
  const label = HISTORY_ACTION_LABELS[entry.action] ?? entry.action.replace("backup.", "");

  const size =
    detail.reclaimed_bytes !== undefined
      ? detail.reclaimed_bytes
      : detail.kept_bytes !== undefined
        ? detail.kept_bytes
        : undefined;
  const count = detail.deleted_count ?? detail.created_count ?? items.length;

  return (
    <li className={cn(destructive && "bg-rose-500/[0.03]")}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        disabled={!items.length}
        className={cn(
          "flex w-full items-start gap-2.5 px-4 py-3 text-left",
          items.length ? "hover:bg-muted/30" : "cursor-default"
        )}
      >
        <span className="mt-0.5 flex-none">
          {items.length ? (
            open ? (
              <IconChevronDown className="size-4 text-muted-foreground" />
            ) : (
              <IconChevronRight className="size-4 text-muted-foreground" />
            )
          ) : (
            <span className="block size-4" />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span
              className={cn(
                "rounded px-1.5 py-px font-mono text-[9.5px] font-bold tracking-[0.05em] uppercase",
                destructive
                  ? "bg-rose-500/15 text-rose-300"
                  : entry.action === "backup.restore"
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-muted/70 text-muted-foreground"
              )}
            >
              {label}
            </span>
            {/*
              An unattended deletion is the one thing on this page nobody chose.
              Badged separately from the actor so it reads as "this happened to
              you" rather than "somebody named retention did this".
            */}
            {automatic && destructive && (
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/12 px-2 py-px text-[9.5px] font-bold tracking-[0.05em] text-amber-300 uppercase">
                <IconRobot className="size-2.5" />
                Nobody asked for this
              </span>
            )}
            <ActorBadge kind={entry.actor_kind} name={entry.actor_name} size="sm" />
            <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">
              {formatWhen(entry.occurred_at)}
            </span>
            {entry.outcome !== "ok" && (
              <span className="rounded bg-rose-500/15 px-1.5 py-px text-[9.5px] font-bold text-rose-300 uppercase">
                {entry.outcome}
              </span>
            )}
          </div>

          <p className="mt-1 text-[12.5px] text-pretty">{entry.summary}</p>

          {(count > 0 || size !== undefined) && (
            <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-muted-foreground">
              {count > 0 && (
                <span>
                  {count} version{count === 1 ? "" : "s"}
                </span>
              )}
              {size !== undefined && size > 0 && <span>· {formatBytes(size)}</span>}
              {detail.skipped_pinned ? <span>· {detail.skipped_pinned} pinned kept</span> : null}
              {detail.keep !== undefined && <span>· rule: keep {detail.keep}</span>}
              {items.length > 0 && !open && (
                <span className="text-brand-foreground/80">· show what it touched</span>
              )}
            </div>
          )}
        </div>
      </button>

      {open && items.length > 0 && (
        <div className="space-y-2 border-t border-border/40 bg-background/40 px-4 py-3">
          {items.map((item) => (
            <HistoryItemCard key={item.capture_id} item={item} destructive={destructive} />
          ))}
          {(detail.omitted ?? 0) > 0 && (
            <p className="text-[11px] text-muted-foreground">
              …and {detail.omitted} more, not itemised. The counts and sizes above cover all of
              them.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * One version, with both of the paths that matter.
 *
 * `original_path` is where the file lived in the library — the answer to "what
 * did I actually lose". `backup_path` is where the kept copy sat, which is what
 * to go looking for on disk when the index no longer knows about it. Older
 * versions recovered by an index rebuild never knew their library path, so that
 * line is simply absent rather than faked.
 */
function HistoryItemCard({ item, destructive }: { item: HistoryItem; destructive: boolean }) {
  const reason = item.reason ? (REASON_LABELS[item.reason] ?? item.reason) : null;

  return (
    <div className="rounded-lg border border-border/70 bg-card/60 px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        {destructive ? (
          <IconTrash className="size-3.5 flex-none translate-y-0.5 text-rose-400/80" />
        ) : (
          <IconArchive className="size-3.5 flex-none translate-y-0.5 text-brand/70" />
        )}
        <FullName value={item.display} />
        <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">
          {formatBytes(item.total_size)}
        </span>
        {item.captured_at && (
          <span className="text-[10.5px] text-muted-foreground">
            kept {formatWhen(item.captured_at)}
          </span>
        )}
        {reason && <span className="text-[10.5px] text-muted-foreground/80">· {reason}</span>}
        {item.pinned && (
          <span className="rounded-full border border-brand/40 bg-brand/12 px-1.5 text-[9.5px] font-bold text-brand-foreground uppercase">
            Pinned
          </span>
        )}
      </div>

      {/* The paths carry the filename themselves now, so it is not repeated
          above them — one line per location rather than a name and two echoes. */}
      <div className="mt-2 space-y-2">
        {item.files.map((file) => (
          <div key={file.relative_path} className="space-y-1.5">
            <FullPath
              label="In the library"
              value={file.original_path}
              meta={formatBytes(file.file_size)}
            />
            <FullPath label="Backup copy" value={file.backup_path} />
          </div>
        ))}
        {item.files.length === 0 && item.capture_dir && (
          <FullPath label="Backup folder" value={item.capture_dir} />
        )}
        {item.files_omitted > 0 && (
          <p className="text-[11px] text-muted-foreground">
            …and {item.files_omitted} more file{item.files_omitted === 1 ? "" : "s"} in this
            version.
          </p>
        )}
      </div>
    </div>
  );
}
