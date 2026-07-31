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

export type Density = "comfortable" | "compact";

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
 * run past a hundred characters, so it drops the table's `whitespace-nowrap`
 * and its fixed height and lets the row take the space it needs. Compact rows
 * put both back — see `FileName`.
 */
const NAME_CELL =
  "h-auto min-h-[38px] overflow-visible py-2 whitespace-normal " +
  "group-data-[density=compact]/row:h-[27px] group-data-[density=compact]/row:py-0 " +
  "group-data-[density=compact]/row:whitespace-nowrap";

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
  density: Density;
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
  density,
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
          <Th className="w-[104px]">Sync</Th>
          <Th className="hidden w-[54px] sm:table-cell" />
        </tr>
      </thead>
      <tbody className={density === "compact" ? "compact" : undefined}>
        {seasons.map((season, index) => {
          const isSelected = selected.has(season.name);
          return (
            <Row
              key={season.name}
              cursor={focused && index === cursor}
              selected={isSelected}
              density={density}
              onClick={() => onOpen(season.name)}
            >
              <TickCell
                checked={isSelected}
                label={`Select ${season.name}`}
                onToggle={() => onToggle(season.name)}
              />
              <Td className={NAME_COL}>
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
              </Td>
              <Td className="text-right font-mono text-[11px] text-foreground-3">
                {season.counts.remote_total}
              </Td>
              <Td className="hidden text-right font-mono text-[11px] text-foreground-3 sm:table-cell">
                {formatBytes(season.remote_bytes)}
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
  density: Density;
  cursor: number;
  focused: boolean;
  onToggle: (code: string, index: number, shiftKey: boolean) => void;
  onToggleAll: () => void;
}

export function EpisodeRows({
  episodes,
  selected,
  density,
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
          <Th className="w-[104px]">Sync</Th>
        </tr>
      </thead>
      <tbody className={density === "compact" ? "compact" : undefined}>
        {episodes.map((episode, index) => {
          const isSelected = selected.has(episode.code);
          const actionable = episode.label !== "IN_SYNC";
          return (
            <Row
              key={`${episode.code}-${index}`}
              cursor={focused && index === cursor}
              selected={isSelected}
              density={density}
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
                <div className="flex min-w-0 items-start gap-2">
                  <IconVideo
                    className={cn(
                      "mt-px size-4 flex-none",
                      isSelected ? "text-brand-hover" : "text-muted-foreground"
                    )}
                  />
                  <FileName episode={episode} density={density} />
                  {episode.renamed && (
                    <span className="flex-none font-mono text-[9.5px] text-muted-foreground">
                      renamed
                    </span>
                  )}
                </div>
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
function FileName({ episode, density }: { episode: ExploreEpisode; density: Density }) {
  const name = episode.remote_name ?? episode.local_name ?? "";
  const parsed = parseFilename(name, episode.episode === null);
  const container = containerOf(name);
  const chips = container ? [container, ...parsed.format] : parsed.format;

  return (
    <>
      {/* These names run to a hundred characters and past two hundred at the
          extreme, and the pane holding them is under three hundred pixels
          wide. On one line the episode code itself was being cut off, so
          comfortable rows wrap and show the name whole, however many lines it
          takes. Compact keeps it to one line for when the point is to fit more
          rows on screen — that is what the density switch is for.

          Three lines is the ceiling. On a wide window a name fits on one and
          rows stay at their normal height; the wrap only appears when the pane
          is genuinely too narrow, and the cap stops one long name turning a
          row into a paragraph. The whole name is on the element either way. */}
      <span
        className={cn(
          "min-w-0 flex-1 text-foreground",
          density === "compact" ? "truncate" : "line-clamp-3 break-words"
        )}
        title={name}
      >
        <CodeInName name={name} />
      </span>
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
  density,
}: {
  children: React.ReactNode;
  onClick?: (event: React.MouseEvent) => void;
  cursor?: boolean;
  selected?: boolean;
  muted?: boolean;
  density: Density;
}) {
  return (
    <tr
      onClick={onClick}
      data-density={density}
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
        "h-[38px] group-data-[density=compact]/row:h-[27px]",
        className
      )}
    >
      {children}
    </td>
  );
}
