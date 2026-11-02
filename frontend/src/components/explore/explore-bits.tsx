import {
  IconAlertTriangle,
  IconCheck,
  IconCircleArrowUp,
  IconCloudOff,
  IconFolderExclamation,
  IconStack2,
  IconTool,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import type { ExploreCounts, ExploreLabel, ExploreStatus } from "@/lib/explore-types";

/**
 * The shared vocabulary. Every badge and count on the Explore page comes from
 * a comparison label, so they are defined once here rather than per component.
 *
 * `NO_INFO` reads "Not on remote", not "Not checked". The comparison did run —
 * it found the remote holds no episodes for this title, either because the
 * folder is not there or because it is there and empty. "Not checked" said the
 * opposite of what happened and sent people looking for a button to press.
 */

const STATUS_META: Record<ExploreStatus, { label: string; tone: string; Icon: typeof IconCheck }> =
  {
    SYNCED: {
      label: "Synced",
      tone: "border-emerald-500/35 bg-emerald-500/12 text-emerald-300",
      Icon: IconCheck,
    },
    NEEDS_REPAIR: {
      label: "Needs repair",
      tone: "border-amber-500/38 bg-amber-500/12 text-amber-400",
      Icon: IconTool,
    },
    OUT_OF_SYNC: {
      label: "Out of sync",
      tone: "border-amber-500/38 bg-amber-500/12 text-amber-400",
      Icon: IconAlertTriangle,
    },
    PARTIAL_SYNC: {
      label: "Partial",
      tone: "border-brand/38 bg-brand/15 text-brand-foreground",
      Icon: IconStack2,
    },
    NO_INFO: {
      label: "Not on remote",
      tone: "border-transparent bg-transparent text-muted-foreground",
      Icon: IconCloudOff,
    },
  };

/** One shape for every tag on a row, so a status and the tags beside it line up. */
const TAG_SHAPE = cn(
  "inline-flex flex-none items-center gap-[5px] rounded-full border px-2 py-[2.5px]",
  "text-[10px] font-bold tracking-[0.05em] whitespace-nowrap uppercase"
);

export function StatusBadge({ status, className }: { status: ExploreStatus; className?: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.NO_INFO;
  const { Icon } = meta;
  return (
    <span className={cn(TAG_SHAPE, meta.tone, status === "NO_INFO" && "pl-0", className)}>
      <Icon className="size-2.5" />
      {meta.label}
    </span>
  );
}

/**
 * An upgrade waiting: the same episode on both sides, a different file on the
 * remote. Sky, the colour the dry run already gives a file it would update,
 * so "Upgrade" reads the same in the tree, on an episode and in the dry run.
 * The Replace button keeps its name — it says what it does.
 */
const UPGRADE_TONE = "border-sky-500/40 bg-sky-500/15 text-sky-300";

/**
 * A file inside an extra folder (`Season 04/ep.mkv/ep.mkv`), where the media
 * server cannot see it. Amber: it needs a person, and Repair is the fix.
 */
const NESTED_TONE = "border-amber-500/40 bg-amber-500/15 text-amber-300";
const NESTED_LABEL_TONE = "text-amber-300 bg-amber-500/15 ring-1 ring-inset ring-amber-500/40";

const LABEL_META: Record<ExploreLabel, { label: string; tone: string }> = {
  IN_SYNC: { label: "In sync", tone: "text-muted-foreground bg-muted/60" },
  NESTED: { label: "Nested", tone: NESTED_LABEL_TONE },
  MISSING: { label: "Download", tone: "text-amber-400 bg-amber-500/14" },
  UPGRADED: { label: "Upgrade", tone: "text-sky-300 bg-sky-500/15" },
  LOCAL_ONLY: { label: "Local only", tone: "text-rose-300 bg-rose-500/14" },
};

/**
 * Beside a title's status: at least one of its files has a newer version on
 * the remote. Its own tag rather than a fifth status, because a series can be
 * missing one episode and have an upgrade for another — "Partial" alone could
 * not say which.
 */
export function UpgradeTag({ count, className }: { count: number; className?: string }) {
  if (count <= 0) return null;
  return (
    <span
      title={`${count} file${count === 1 ? " has" : "s have"} a different, usually newer, version on the remote server`}
      className={cn(TAG_SHAPE, UPGRADE_TONE, className)}
    >
      <IconCircleArrowUp className="size-3" />
      Upgrade
    </span>
  );
}

/**
 * Beside a title's or season's status: some of its local files sit in a
 * nested folder. Hidden when the status already says "Needs repair", so the
 * row does not say the same thing twice.
 */
export function NestedTag({
  count,
  status,
  className,
}: {
  count?: number;
  status?: ExploreStatus;
  className?: string;
}) {
  if (!count || status === "NEEDS_REPAIR") return null;
  return (
    <span
      title={`${count} file${count === 1 ? " is" : "s are"} inside a nested folder, where the media server cannot see ${count === 1 ? "it" : "them"}. Repair moves ${count === 1 ? "it" : "them"} into place.`}
      className={cn(TAG_SHAPE, NESTED_TONE, className)}
    >
      <IconFolderExclamation className="size-3" />
      Nested
    </span>
  );
}

/**
 * Episodes still named TBA: Sonarr named them before their title was known.
 *
 * The same pill as the status beside it, with no icon and a three-letter
 * label so it stays the shortest tag on the row: it is not a sync problem.
 * Violet, a colour nothing else on the page uses. Outlined while every title
 * is still unknown; filled, with the count of titles ready to rename, once
 * some have arrived. The tooltip says what both numbers mean.
 */
export function TitlesTag({
  count,
  ready = 0,
  className,
}: {
  count: number;
  ready?: number;
  className?: string;
}) {
  if (count <= 0 && ready <= 0) return null;
  const files = Math.max(count, ready);
  const still = `${files} episode${files === 1 ? " is" : "s are"} still named TBA`;
  return (
    <span
      title={
        ready > 0
          ? `${still}. ${ready} can get ${ready === 1 ? "its" : "their"} real title now.`
          : still
      }
      className={cn(
        TAG_SHAPE,
        ready > 0
          ? "border-violet-500/40 bg-violet-500/14 pr-[3px] text-violet-200"
          : "border-violet-500/30 text-violet-300/75",
        className
      )}
    >
      TBA
      {ready > 0 && (
        <span className="grid h-3.5 min-w-3.5 place-items-center rounded-full bg-violet-400 px-1 text-[9px] tracking-normal text-violet-950 tabular-nums">
          {ready}
        </span>
      )}
    </span>
  );
}

export function EpisodeLabel({ label, title }: { label: ExploreLabel; title?: string }) {
  const meta = LABEL_META[label] ?? LABEL_META.IN_SYNC;
  return (
    <span
      title={title}
      className={cn(
        "flex-none rounded px-1.5 py-px font-mono text-[9.5px] font-semibold tracking-[0.06em]",
        meta.tone
      )}
    >
      {meta.label}
    </span>
  );
}

/**
 * The counts that matter, in the order you scan them. Zero values are dropped —
 * a season with nothing missing should not display "0 missing".
 */
export function CountChips({ counts, className }: { counts: ExploreCounts; className?: string }) {
  const chips: Array<{ n: number; label: string; tone: string }> = [
    { n: counts.missing, label: "missing", tone: "text-amber-400" },
    { n: counts.upgraded, label: "upgraded", tone: "text-sky-300" },
    { n: counts.nested_files ?? 0, label: "nested", tone: "text-amber-300" },
    { n: counts.local_only, label: "extra", tone: "text-rose-300" },
    { n: counts.in_sync, label: "in sync", tone: "text-muted-foreground" },
  ].filter((chip) => chip.n > 0);

  if (!chips.length) return null;

  return (
    <span className={cn("flex items-center gap-2 font-mono text-[10px]", className)}>
      {chips.map((chip) => (
        <span key={chip.label} className={chip.tone}>
          {chip.n} {chip.label}
        </span>
      ))}
    </span>
  );
}
