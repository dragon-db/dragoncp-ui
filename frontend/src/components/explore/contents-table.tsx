import { IconEye, IconPlayerPlay, IconStack2, IconVideo } from "@tabler/icons-react";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { EpisodeLabel, StatusBadge } from "./explore-bits";
import { formatBytes } from "@/lib/explore-format";
import { EPISODE_CODE, containerOf, parseFilename } from "@/lib/media-filename";
import type { ExploreEpisode, ExploreSeason } from "@/lib/explore-types";

/**
 * What is inside the selected node: seasons when a series is selected, episodes
 * when a season is.
 *
 * The Items column hides itself when the rows are files — a file has no child
 * items, and the width is better spent on the name. Rows keep their episode
 * order; sorting by title would put S02E11 before S02E01.
 */

/**
 * What a row is telling you.
 *
 * This replaced a comfortable/compact switch, which only changed row height —
 * the least useful axis on a screen whose whole job is comparing two copies of
 * a library. Each of these answers a different question instead:
 *
 *   list     what is in here            (one line per file, most rows on screen)
 *   compare  what is actually different (local and remote side by side)
 *   quality  what a sync would change   (resolution, source and size, both sides)
 *
 * The data for all three has always been sent; the table collapsed it with
 * `remote ?? local` and showed one value, which hid the difference the page
 * exists to reveal. Quality goes one further and reads the file names, because
 * "Upgraded" says the remote is different without saying whether that is 2160p
 * replacing 1080p or the same 1080p at twice the size.
 */
export type ViewMode = "list" | "compare" | "quality";

/**
 * The leading gutter that holds the tick box.
 *
 * On a phone the full-width version wastes about a fifth of the row on empty
 * space before the file name, so it narrows below `sm`. `overflow-visible`
 * lets the tick box's oversized touch area spill out of the cell instead of
 * being clipped back to sixteen pixels.
 */
const SELECT_COL = "w-8 overflow-visible pl-2 sm:w-9 sm:pl-3";
/** The name sits flush against that gutter on a phone, indented on a desktop. */
const NAME_COL = "pl-0 sm:pl-3";
/**
 * The file-name cell, which is the one place a row is allowed to grow.
 *
 * Every other cell is a fixed-height single line. This one carries names that
 * run past a hundred characters — and, in the richer views, the two sides of
 * the comparison — so it drops the table's `whitespace-nowrap` and its fixed
 * height and lets the row take the space it needs.
 */
const NAME_CELL = "h-auto min-h-[38px] overflow-visible py-2 whitespace-normal";

/**
 * Base UI puts the tick box's hidden `input` beside it rather than inside it,
 * and forwards the click there. That click reaches the row and undoes the tick,
 * so the guard has to wrap both elements — putting it on the tick box alone
 * looks right and does nothing.
 */
function TickCell({
  checked,
  indeterminate,
  label,
  onToggle,
}: {
  checked: boolean;
  indeterminate?: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <Td className={SELECT_COL}>
      <div className="flex items-center py-2.5 pr-2" onClick={(event) => event.stopPropagation()}>
        <Checkbox
          checked={checked}
          indeterminate={indeterminate}
          aria-label={label}
          onCheckedChange={onToggle}
        />
      </div>
    </Td>
  );
}

/**
 * One side of a comparison: what this copy of the file is.
 *
 * Absence is stated rather than left blank. A row with an empty Local column
 * and a row whose local file happens to be unnamed look identical when the
 * cell is empty, and only one of them means "you do not have this".
 */
function SideRow({
  side,
  name,
  size,
  mtime,
  differs,
}: {
  side: "Local" | "Remote";
  name: string | null;
  size: number | null;
  mtime: number | null;
  /** Highlighted because the two sides disagree on it. */
  differs: { name: boolean; size: boolean };
}) {
  const missing = !name;
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span
        className={cn(
          "w-[46px] flex-none font-mono text-[9px] tracking-[0.12em] uppercase",
          side === "Local" ? "text-brand-hover/80" : "text-foreground-3"
        )}
      >
        {side}
      </span>
      {missing ? (
        <span className="text-[11.5px] text-muted-foreground/70 italic">not on this side</span>
      ) : (
        <>
          <span
            className={cn(
              "min-w-0 flex-1 font-mono text-[11.5px] leading-[1.45] break-all",
              differs.name ? "text-amber-300" : "text-foreground-2"
            )}
          >
            {name}
          </span>
          <span
            className={cn(
              "flex-none font-mono text-[10.5px] tabular-nums",
              differs.size ? "font-semibold text-amber-300" : "text-foreground-3"
            )}
          >
            {formatBytes(size ?? 0)}
          </span>
          <span className="hidden flex-none text-[10.5px] text-foreground-3 sm:inline">
            {relativeDate(mtime)}
          </span>
        </>
      )}
    </div>
  );
}

/** Both sides of one file, with whatever disagrees picked out. */
function CompareBlock({ episode }: { episode: ExploreEpisode }) {
  const bothPresent = Boolean(episode.remote_name) && Boolean(episode.local_name);
  const differs = {
    name: bothPresent && episode.remote_name !== episode.local_name,
    size: bothPresent && episode.remote_size !== episode.local_size,
  };
  return (
    <div className="mt-1.5 space-y-1 border-l border-border/70 pl-2.5">
      <SideRow
        side="Local"
        name={episode.local_name}
        size={episode.local_size}
        mtime={episode.local_mtime}
        differs={differs}
      />
      <SideRow
        side="Remote"
        name={episode.remote_name}
        size={episode.remote_size}
        mtime={episode.remote_mtime}
        differs={differs}
      />
    </div>
  );
}

/** Where a resolution sits relative to the others. Unknown sorts lowest. */
const RESOLUTION_RANK: Record<string, number> = {
  "480p": 1,
  "576p": 2,
  "720p": 3,
  "1080p": 4,
  "1440p": 5,
  "2160p": 6,
};

/**
 * How good the source is, roughly.
 *
 * "Roughly" is the honest word: a good web release beats a bad disc rip, and no
 * ordering of these tags is true in every case. It is used only to say which
 * way a swap goes, never to recommend one.
 */
const SOURCE_RANK: Record<string, number> = {
  hdtv: 1,
  webrip: 2,
  webdl: 3,
  "web-dl": 3,
  bluray: 4,
  blurayremux: 5,
  remux: 5,
};

interface Grade {
  resolution: string | null;
  source: string | null;
  codec: string | null;
  group: string | null;
}

/** What a filename says about the file's quality. Nulls where it says nothing. */
function grade(name: string | null, isMovie: boolean): Grade | null {
  if (!name) return null;
  const parsed = parseFilename(name, isMovie);
  const quality = parsed.quality ?? "";
  const resolution = quality.match(/\d{3,4}p/i)?.[0]?.toLowerCase() ?? null;
  // The word joined to the resolution: `WEBDL-1080p` -> `webdl`. Deliberately
  // not anchored to the start — a quality tag can carry other words in front of
  // it (`Dual-Audio WEBDL-1080p`), and anchoring dropped the source on every
  // one of those. A bare `1080p` states no source at all.
  //
  // Hyphens are allowed inside the token so `WEB-DL-1080p` yields `web-dl`,
  // which SOURCE_RANK knows about — without them that entry was unreachable.
  // Greedy matching backtracks to the last hyphen before the resolution, so
  // `Dual-Audio WEBDL-1080p` still gives `webdl` rather than the whole phrase.
  const sourceRaw = quality.match(/([A-Za-z][A-Za-z-]*)-\d{3,4}p/)?.[1] ?? null;
  return {
    resolution,
    source: sourceRaw ? sourceRaw.toLowerCase().replace(/\s/g, "") : null,
    codec: parsed.codec,
    group: parsed.group,
  };
}

function rankOf(table: Record<string, number>, key: string | null): number | null {
  if (!key) return null;
  return table[key] ?? null;
}

/**
 * What the two copies are, and which way a sync would move the quality.
 *
 * This answers the question the Sync column raises and never explains. A row
 * labelled "Upgraded" says the remote is different, not whether it is 2160p
 * replacing 1080p or the same 1080p from another group at twice the size — and
 * those are opposite decisions.
 *
 * Everything here is read out of the filename, so where the name says nothing
 * this says nothing rather than guessing.
 */
function QualityBlock({ episode }: { episode: ExploreEpisode }) {
  const isMovie = episode.episode === null;
  const local = grade(episode.local_name, isMovie);
  const remote = grade(episode.remote_name, isMovie);

  const resDelta = compareRank(RESOLUTION_RANK, local?.resolution, remote?.resolution);
  const srcDelta = compareRank(SOURCE_RANK, local?.source, remote?.source);
  const sizeDelta =
    local && remote && episode.local_size !== null && episode.remote_size !== null
      ? episode.remote_size - episode.local_size
      : null;

  return (
    <div className="mt-1.5 space-y-1 border-l border-border/70 pl-2.5">
      <GradeRow side="Local" grade={local} size={episode.local_size} />
      <GradeRow side="Remote" grade={remote} size={episode.remote_size} />
      <Verdict
        local={local}
        remote={remote}
        resDelta={resDelta}
        srcDelta={srcDelta}
        sizeDelta={sizeDelta}
      />
    </div>
  );
}

/** -1 worse, 0 same, 1 better, null when either side cannot be read. */
function compareRank(
  table: Record<string, number>,
  localKey: string | null | undefined,
  remoteKey: string | null | undefined
): number | null {
  const a = rankOf(table, localKey ?? null);
  const b = rankOf(table, remoteKey ?? null);
  if (a === null || b === null) return null;
  return Math.sign(b - a);
}

function GradeRow({
  side,
  grade: value,
  size,
}: {
  side: "Local" | "Remote";
  grade: Grade | null;
  size: number | null;
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
      <span
        className={cn(
          "w-[46px] flex-none font-mono text-[9px] tracking-[0.12em] uppercase",
          side === "Local" ? "text-brand-hover/80" : "text-foreground-3"
        )}
      >
        {side}
      </span>
      {!value ? (
        <span className="text-[11.5px] text-muted-foreground/70 italic">not on this side</span>
      ) : (
        <>
          <Chip value={value.resolution?.toUpperCase()} strong />
          <Chip value={value.source?.toUpperCase()} />
          <Chip value={value.codec?.toUpperCase()} />
          {value.group && (
            <span className="font-mono text-[10px] text-foreground-3">{value.group}</span>
          )}
          {!value.resolution && !value.source && !value.codec && (
            <span className="text-[11.5px] text-muted-foreground/70 italic">
              the filename does not say
            </span>
          )}
          <span className="ml-auto flex-none font-mono text-[10.5px] text-foreground-3 tabular-nums">
            {formatBytes(size ?? 0)}
          </span>
        </>
      )}
    </div>
  );
}

function Chip({ value, strong }: { value?: string | null; strong?: boolean }) {
  if (!value) return null;
  return (
    <span
      className={cn(
        "flex-none rounded border px-1 py-px font-mono text-[9.5px] leading-[13px]",
        strong
          ? "border-brand/40 bg-brand/10 text-brand-foreground"
          : "border-border/70 text-foreground-3"
      )}
    >
      {value}
    </span>
  );
}

/** One sentence on what a sync would actually change here. */
function Verdict({
  local,
  remote,
  resDelta,
  srcDelta,
  sizeDelta,
}: {
  local: Grade | null;
  remote: Grade | null;
  resDelta: number | null;
  srcDelta: number | null;
  sizeDelta: number | null;
}) {
  if (!local || !remote) return null;

  let text: string;
  let tone = "text-muted-foreground";

  if (resDelta === null && srcDelta === null) {
    text = "The filenames do not say enough to compare quality.";
  } else if (resDelta && resDelta > 0) {
    text = `Higher resolution: ${remote.resolution?.toUpperCase()} replaces ${local.resolution?.toUpperCase()}.`;
    tone = "text-emerald-300";
  } else if (resDelta && resDelta < 0) {
    text = `Lower resolution: ${remote.resolution?.toUpperCase()} replaces ${local.resolution?.toUpperCase()}.`;
    tone = "text-amber-300";
  } else if (srcDelta && srcDelta > 0) {
    text = `Better source: ${remote.source?.toUpperCase()} replaces ${local.source?.toUpperCase()}.`;
    tone = "text-emerald-300";
  } else if (srcDelta && srcDelta < 0) {
    text = `Weaker source: ${remote.source?.toUpperCase()} replaces ${local.source?.toUpperCase()}.`;
    tone = "text-amber-300";
  } else if (local.group && remote.group && local.group !== remote.group) {
    text = `Same resolution and source, a different release (${remote.group}).`;
  } else {
    text = "Same quality on both sides.";
  }

  const size =
    sizeDelta === null || sizeDelta === 0
      ? null
      : `${sizeDelta > 0 ? "+" : "−"}${formatBytes(Math.abs(sizeDelta))} on disk`;

  return (
    <p className={cn("pt-0.5 text-[11px]", tone)}>
      {text}
      {size && <span className="ml-1.5 font-mono text-foreground-3">{size}</span>}
    </p>
  );
}

/**
 * A season's two sides: how many files each holds and how much they weigh.
 *
 * Counts rather than names, because a season is a container — the question at
 * this level is "how far apart are these two folders", and the file-by-file
 * answer is one click down.
 */
function SeasonCompareBlock({ season }: { season: ExploreSeason }) {
  // There is no local total on the wire, so it is the labels that describe a
  // local file: matching, present-but-outdated, and here-only. `missing` is
  // deliberately absent — those are the ones you do not have.
  const localCount = season.counts.in_sync + season.counts.upgraded + season.counts.local_only;
  const remoteCount = season.counts.remote_total ?? 0;
  const differs = localCount !== remoteCount || season.local_bytes !== season.remote_bytes;

  return (
    <div className="mt-1.5 space-y-1 border-l border-border/70 pl-2.5">
      <SeasonSide
        side="Local"
        count={localCount}
        bytes={season.local_bytes}
        folder={season.local_folder}
        differs={differs}
      />
      <SeasonSide
        side="Remote"
        count={remoteCount}
        bytes={season.remote_bytes}
        folder={season.remote_folder}
        differs={differs}
      />
    </div>
  );
}

function SeasonSide({
  side,
  count,
  bytes,
  folder,
  differs,
}: {
  side: "Local" | "Remote";
  count: number;
  bytes: number;
  folder: string | null;
  differs: boolean;
}) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span
        className={cn(
          "w-[46px] flex-none font-mono text-[9px] tracking-[0.12em] uppercase",
          side === "Local" ? "text-brand-hover/80" : "text-foreground-3"
        )}
      >
        {side}
      </span>
      {folder === null ? (
        <span className="text-[11.5px] text-muted-foreground/70 italic">
          no folder on this side
        </span>
      ) : (
        <>
          <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-foreground-2">
            {folder}
          </span>
          <span
            className={cn(
              "flex-none font-mono text-[10.5px] tabular-nums",
              differs ? "text-amber-300" : "text-foreground-3"
            )}
          >
            {count} file{count === 1 ? "" : "s"} · {formatBytes(bytes)}
          </span>
        </>
      )}
    </div>
  );
}

function relativeDate(unixSeconds: number | null): string {
  if (!unixSeconds) return "—";
  const days = Math.floor((Date.now() / 1000 - unixSeconds) / 86400);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) {
    const weeks = Math.floor(days / 7);
    return weeks === 1 ? "1 week ago" : `${weeks} weeks ago`;
  }
  if (days < 365) {
    const months = Math.floor(days / 30);
    return months === 1 ? "1 month ago" : `${months} months ago`;
  }
  const years = Math.floor(days / 365);
  return years === 1 ? "1 year ago" : `${years} years ago`;
}

interface SeasonRowsProps {
  seasons: ExploreSeason[];
  selected: Set<string>;
  view: ViewMode;
  cursor: number;
  focused: boolean;
  onOpen: (season: string) => void;
  onSync: (season: string) => void;
  onToggle: (season: string) => void;
  onToggleAll: () => void;
}

export function SeasonRows({
  seasons,
  selected,
  view,
  cursor,
  focused,
  onOpen,
  onSync,
  onToggle,
  onToggleAll,
}: SeasonRowsProps) {
  const allSelected = seasons.length > 0 && seasons.every((s) => selected.has(s.name));
  const someSelected = !allSelected && seasons.some((s) => selected.has(s.name));

  return (
    <table className="w-full table-fixed border-collapse">
      <thead>
        <tr>
          <Th className={SELECT_COL}>
            <Checkbox
              checked={allSelected}
              indeterminate={someSelected}
              onCheckedChange={onToggleAll}
              aria-label="Select every season"
            />
          </Th>
          <Th className={NAME_COL}>Name</Th>
          <Th className="w-[60px] text-right">Items</Th>
          <Th className="hidden w-[72px] text-right sm:table-cell">Size</Th>
          <Th className="hidden w-[96px] md:table-cell">Modified</Th>
          <Th className="w-[124px]">Sync</Th>
          <Th className="hidden w-[54px] sm:table-cell" />
        </tr>
      </thead>
      <tbody>
        {seasons.map((season, index) => {
          const isSelected = selected.has(season.name);
          return (
            <Row
              key={season.name}
              cursor={focused && index === cursor}
              selected={isSelected}
              view={view}
              onClick={() => onOpen(season.name)}
            >
              <TickCell
                checked={isSelected}
                label={`Select ${season.name}`}
                onToggle={() => onToggle(season.name)}
              />
              <Td className={cn(NAME_COL, view === "compare" && NAME_CELL)}>
                <div className="flex min-w-0 items-center gap-2">
                  <IconStack2
                    className={cn(
                      "size-4 flex-none",
                      isSelected ? "text-brand-hover" : "text-muted-foreground"
                    )}
                  />
                  <span className="min-w-0 truncate font-medium text-foreground">
                    {season.name}
                  </span>
                </div>
                {/* No Quality block here: a season is a folder, and quality is
                    read out of file names. The switch disables that option
                    while this list is showing rather than offering one that
                    renders nothing. */}
                {view === "compare" && <SeasonCompareBlock season={season} />}
              </Td>
              <Td className="text-right font-mono text-[11px] text-foreground-3">
                {season.counts.remote_total || season.counts.local_only || 0}
              </Td>
              <Td className="hidden text-right font-mono text-[11px] text-foreground-3 sm:table-cell">
                {formatBytes(
                  season.counts.remote_total > 0 ? season.remote_bytes : season.local_bytes
                )}
              </Td>
              <Td className="hidden text-[11px] text-foreground-3 md:table-cell">
                {relativeDate(season.remote_mtime)}
              </Td>
              <Td>
                <StatusBadge status={season.status} />
              </Td>
              <Td className="hidden sm:table-cell">
                <RowActions
                  onSync={(event) => {
                    event.stopPropagation();
                    onSync(season.name);
                  }}
                />
              </Td>
            </Row>
          );
        })}
      </tbody>
    </table>
  );
}

interface EpisodeRowsProps {
  episodes: ExploreEpisode[];
  selected: Set<string>;
  view: ViewMode;
  cursor: number;
  focused: boolean;
  onToggle: (code: string, index: number, shiftKey: boolean) => void;
  onToggleAll: () => void;
}

export function EpisodeRows({
  episodes,
  selected,
  view,
  cursor,
  focused,
  onToggle,
  onToggleAll,
}: EpisodeRowsProps) {
  // Every file can be ticked, whether or not it is already in sync. A matching
  // file is still something you may want to rehearse, or fetch again because
  // your copy is damaged — the row saying "In sync" is the answer to that
  // question, not a reason to take the control away.
  const allSelected = episodes.length > 0 && episodes.every((e) => selected.has(e.code));
  const someSelected = !allSelected && episodes.some((e) => selected.has(e.code));

  return (
    <table className="w-full table-fixed border-collapse">
      <thead>
        <tr>
          <Th className={SELECT_COL}>
            {/* partial selection renders as a dash, never as a tick */}
            <Checkbox
              checked={allSelected}
              indeterminate={someSelected}
              onCheckedChange={onToggleAll}
              aria-label="Select every file"
            />
          </Th>
          <Th className={NAME_COL}>Name</Th>
          <Th className="hidden w-[72px] text-right sm:table-cell">Size</Th>
          <Th className="hidden w-[96px] md:table-cell">Modified</Th>
          <Th className="w-[124px]">Sync</Th>
        </tr>
      </thead>
      <tbody>
        {episodes.map((episode, index) => {
          const isSelected = selected.has(episode.code);
          const actionable = episode.label !== "IN_SYNC";
          return (
            <Row
              key={`${episode.code}-${index}`}
              cursor={focused && index === cursor}
              selected={isSelected}
              view={view}
              muted={!actionable && !isSelected}
              onClick={(event) =>
                onToggle(episode.code, index, (event as React.MouseEvent).shiftKey)
              }
            >
              <TickCell
                checked={isSelected}
                label={`Select ${episode.code}`}
                onToggle={() => onToggle(episode.code, index, false)}
              />
              <Td className={cn(NAME_COL, NAME_CELL)}>
                {/* Centred, not top-aligned: the tick box in the gutter sits in
                    the middle of the row, so an icon pinned to the first line of
                    a wrapped name left the two visibly out of step. */}
                <div className="flex min-w-0 items-center gap-2">
                  <IconVideo
                    className={cn(
                      "size-4 flex-none",
                      isSelected ? "text-brand-hover" : "text-muted-foreground"
                    )}
                  />
                  <FileName episode={episode} view={view} />
                  {episode.renamed && (
                    <span className="flex-none font-mono text-[9.5px] text-muted-foreground">
                      renamed
                    </span>
                  )}
                </div>
                {view === "compare" && <CompareBlock episode={episode} />}
                {view === "quality" && <QualityBlock episode={episode} />}
              </Td>
              <Td className="hidden text-right font-mono text-[11px] text-foreground-3 sm:table-cell">
                {formatBytes(episode.remote_size ?? episode.local_size)}
              </Td>
              <Td className="hidden text-[11px] text-foreground-3 md:table-cell">
                {relativeDate(episode.remote_mtime ?? episode.local_mtime)}
              </Td>
              <Td>
                <EpisodeLabel label={episode.label} />
              </Td>
            </Row>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * A file's name and what it is.
 *
 * The whole filename is shown, with the episode code picked out inside it — the
 * name is the thing being looked at, and abbreviating it hid which of two
 * copies of an episode a row referred to.
 *
 * The format is pulled out into chips beside it. A Sonarr filename carries the
 * container, quality, languages and group at its very end, which is precisely
 * what a truncating cell cuts off, so the facts most needed to tell two files
 * apart were the ones guaranteed to disappear.
 */
function FileName({ episode, view }: { episode: ExploreEpisode; view: ViewMode }) {
  const name = episode.remote_name ?? episode.local_name ?? "";
  const parsed = parseFilename(name, episode.episode === null);
  const container = containerOf(name);
  const chips = container ? [container, ...parsed.format] : parsed.format;

  return (
    <>
      {/* These names run to a hundred characters and past two hundred at the
          extreme, and the pane holding them is under three hundred pixels
          wide, so the name wraps and is shown whole however many lines it
          takes. Three lines is the ceiling: on a wide window a name fits on
          one and rows stay at their normal height, and the cap stops a single
          long name turning a row into a paragraph.

          In the richer views this line is a heading for the two sides below
          it, which carry the names in full and unclamped, so the clamp costs
          nothing there. */}
      <span className="line-clamp-3 min-w-0 flex-1 break-words text-foreground" title={name}>
        <CodeInName name={name} />
      </span>
      {view !== "list" && <span className="sr-only">, shown in detail below</span>}
      {chips.length > 0 && (
        <span className="hidden flex-none items-center gap-1 md:inline-flex">
          {chips.map((part) => (
            <span
              key={part}
              className="rounded border border-border/70 px-1 py-px font-mono text-[9.5px] leading-[13px] text-foreground-3"
            >
              {part}
            </span>
          ))}
        </span>
      )}
    </>
  );
}

/** The filename, with `S01E02` in the accent colour so it can be found fast. */
function CodeInName({ name }: { name: string }) {
  const match = name.match(EPISODE_CODE);
  if (!match || match.index === undefined) return <>{name}</>;
  return (
    <>
      {name.slice(0, match.index)}
      <span className="font-semibold text-brand-hover">{match[0]}</span>
      {name.slice(match.index + match[0].length)}
    </>
  );
}

export function TableShell({
  loading,
  empty,
  children,
}: {
  loading: boolean;
  empty: string | null;
  children: React.ReactNode;
}) {
  return (
    <ScrollArea className="min-h-0 flex-1">
      {loading ? (
        <div className="flex flex-col gap-1.5 p-3">
          {[1, 2, 3, 4, 5, 6, 7].map((n) => (
            <Skeleton key={n} className="h-9 w-full" />
          ))}
        </div>
      ) : empty ? (
        <p className="px-4 py-14 text-center text-sm text-muted-foreground">{empty}</p>
      ) : (
        children
      )}
    </ScrollArea>
  );
}

function Row({
  children,
  onClick,
  cursor,
  selected,
  muted,
  view,
}: {
  children: React.ReactNode;
  onClick?: (event: React.MouseEvent) => void;
  cursor?: boolean;
  selected?: boolean;
  muted?: boolean;
  view: ViewMode;
}) {
  return (
    <tr
      onClick={onClick}
      data-view={view}
      className={cn(
        "group/row border-b border-border/60",
        // A file that is already in sync reads as quieter, but it still answers
        // a tap — it opens what can be done with it rather than doing nothing.
        muted && "opacity-70",
        onClick && "cursor-pointer hover:bg-elevated",
        selected && "bg-brand/10 hover:bg-brand/15",
        cursor && "shadow-[inset_0_0_0_1px_var(--brand)]"
      )}
    >
      {children}
    </tr>
  );
}

function RowActions({ onSync }: { onSync: (event: React.MouseEvent) => void }) {
  return (
    <div className="flex justify-end gap-0.5 opacity-0 transition-opacity group-hover/row:opacity-100">
      <button
        type="button"
        title="Review and sync"
        onClick={onSync}
        className="grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <IconPlayerPlay className="size-3.5" />
      </button>
      <button
        type="button"
        title="Open"
        className="grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <IconEye className="size-3.5" />
      </button>
    </div>
  );
}

function Th({ className, children }: { className?: string; children?: React.ReactNode }) {
  return (
    <th
      className={cn(
        "sticky top-0 z-2 h-[30px] border-b border-border bg-background pr-[11px] pl-3 text-left",
        "font-mono text-[9.5px] font-semibold tracking-[0.1em] whitespace-nowrap text-foreground-3 uppercase",
        className
      )}
    >
      {children}
    </th>
  );
}

function Td({ className, children }: { className?: string; children?: React.ReactNode }) {
  return (
    <td
      className={cn(
        "overflow-hidden pr-[11px] pl-3 text-[12.5px] whitespace-nowrap text-foreground-2",
        // Fixed height in List, where every row is one line and a uniform rhythm
        // is the point. The richer views carry two sides in the name cell, so
        // the row is sized by its content and the other cells align to the top
        // rather than floating in the middle of a tall row.
        "h-[38px] group-data-[view=compare]/row:h-auto group-data-[view=quality]/row:h-auto",
        "group-data-[view=compare]/row:align-top group-data-[view=quality]/row:align-top",
        className
      )}
    >
      {children}
    </td>
  );
}
