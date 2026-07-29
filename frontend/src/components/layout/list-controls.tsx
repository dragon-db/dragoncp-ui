import {
  IconChevronLeft,
  IconChevronRight,
  IconSearch,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group";
import { cn } from "@/lib/utils";

/**
 * The controls a long list needs: search, status filters, paging, and picking
 * rows out to act on. Transfers and Media sync both grew past the point where a
 * single scrolling page works, and they share these so the two lists are
 * driven the same way.
 */

export function ListSearch({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
}) {
  return (
    <InputGroup className={cn("h-8 w-full min-w-0 sm:w-64", className)}>
      <InputGroupAddon>
        <IconSearch />
      </InputGroupAddon>
      <InputGroupInput
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="text-[13px]"
      />
      {value && (
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            variant="ghost"
            size="icon-xs"
            aria-label="Clear search"
            onClick={() => onChange("")}
          >
            <IconX />
          </InputGroupButton>
        </InputGroupAddon>
      )}
    </InputGroup>
  );
}

export interface FilterChoice {
  value: string;
  label: string;
  /** How many records sit behind this filter, counted server-side. */
  count?: number;
}

/**
 * Status filters, each showing how many records it holds.
 *
 * The counts come from the whole table, not the page on screen, so "Failed 15"
 * means fifteen failed records exist — the number is the reason to click.
 */
export function FilterChips({
  choices,
  value,
  onChange,
}: {
  choices: readonly FilterChoice[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <>
      {choices.map((choice) => {
        const selected = value === choice.value;
        return (
          <button
            key={choice.value}
            type="button"
            onClick={() => onChange(choice.value)}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors",
              selected
                ? "border-brand/35 bg-brand/15 text-brand-foreground"
                : "border-transparent text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            )}
          >
            {choice.label}
            {choice.count != null && (
              <span
                className={cn(
                  "font-mono text-[10.5px] tabular-nums",
                  selected ? "text-brand-foreground/70" : "text-muted-foreground/60"
                )}
              >
                {choice.count}
              </span>
            )}
          </button>
        );
      })}
    </>
  );
}

const PAGE_SIZES = [25, 50, 100] as const;

/**
 * Page position and movement, stated in records rather than page numbers —
 * "51–100 of 519" answers "how much is there" and "where am I" at once.
 */
export function ListPagination({
  offset,
  limit,
  total,
  count,
  onOffsetChange,
  onLimitChange,
  noun,
}: {
  offset: number;
  limit: number;
  total: number;
  /** How many rows this page actually returned. */
  count: number;
  onOffsetChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
  noun: string;
}) {
  if (!total) return null;

  const first = total ? offset + 1 : 0;
  const last = offset + count;
  const atStart = offset === 0;
  const atEnd = last >= total;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border/70 px-3 py-2.5">
      <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
        {first}–{last} of {total} {noun}
      </span>

      <div className="ml-auto flex items-center gap-1">
        <span className="mr-1 hidden font-mono text-[10px] tracking-[0.1em] text-muted-foreground/70 uppercase sm:inline">
          Per page
        </span>
        {PAGE_SIZES.map((size) => (
          <button
            key={size}
            type="button"
            onClick={() => onLimitChange(size)}
            className={cn(
              "rounded-md px-2 py-1 font-mono text-[11px] tabular-nums transition-colors",
              limit === size
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            )}
          >
            {size}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={atStart}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
        >
          <IconChevronLeft className="size-3.5" />
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={atEnd}
          onClick={() => onOffsetChange(offset + limit)}
        >
          Next
          <IconChevronRight className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

/**
 * Appears once rows are picked, and says exactly what is about to be deleted.
 *
 * Selecting every row on a page is not the same as selecting every match, and
 * the difference matters when there are thousands of matches and fifty rows on
 * screen — so both are offered, separately and by name.
 */
export function SelectionBar({
  selectedCount,
  pageCount,
  total,
  allPageSelected,
  allMatchingSelected,
  onTogglePage,
  onSelectAllMatching,
  onClear,
  onDelete,
  busy,
  noun,
  filterLabel,
}: {
  selectedCount: number;
  pageCount: number;
  total: number;
  allPageSelected: boolean;
  allMatchingSelected: boolean;
  onTogglePage: () => void;
  onSelectAllMatching: () => void;
  onClear: () => void;
  onDelete: () => void;
  busy: boolean;
  noun: string;
  /** What the current filter is showing, e.g. "failed" — used in the prompt. */
  filterLabel?: string;
}) {
  const moreBeyondPage = total > pageCount;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border/70 bg-muted/25 px-3 py-2.5">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-foreground">
        <Checkbox
          checked={allPageSelected}
          indeterminate={selectedCount > 0 && !allPageSelected && !allMatchingSelected}
          onCheckedChange={onTogglePage}
          aria-label={`Select the ${pageCount} ${noun} on this page`}
        />
        {selectedCount
          ? allMatchingSelected
            ? `All ${total} ${noun} selected`
            : `${selectedCount} selected`
          : `Select page`}
      </label>

      {selectedCount > 0 && !allMatchingSelected && moreBeyondPage && (
        <Button variant="ghost" size="sm" onClick={onSelectAllMatching}>
          Select all {total}
          {filterLabel ? ` ${filterLabel}` : ""}
        </Button>
      )}

      {selectedCount > 0 && (
        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onClear} disabled={busy}>
            Clear
          </Button>
          <Button variant="destructive" size="sm" onClick={onDelete} disabled={busy}>
            <IconTrash className="size-3.5" />
            Delete {allMatchingSelected ? `all ${total}` : selectedCount > 1 ? selectedCount : ""}
          </Button>
        </div>
      )}
    </div>
  );
}

/** Checkbox that sits at the head of a row without triggering the row itself. */
export function RowCheckbox({
  checked,
  onCheckedChange,
  label,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <span
      // The row underneath expands on click; a tick should not also open it.
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
      className="flex items-center pl-4"
    >
      <Checkbox
        checked={checked}
        onCheckedChange={(value) => onCheckedChange(Boolean(value))}
        aria-label={label}
      />
    </span>
  );
}
