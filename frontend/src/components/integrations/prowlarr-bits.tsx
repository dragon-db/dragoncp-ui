import type { ComponentType, ReactNode } from "react";
import { IconCheck } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import {
  CATEGORIES,
  INDEXER_STATE,
  type QualityToken,
} from "@/components/integrations/prowlarr-vocab";
import type { Protocol, ProwlarrIndexer } from "@/lib/prowlarr-types";

/** Pieces shared by Prowlarr's Search and Indexers tabs. */

const TOKEN_STYLE: Record<QualityToken["kind"], string> = {
  res: "border-brand/35 text-brand-foreground",
  src: "border-sky-500/30 text-sky-300",
  hdr: "border-amber-500/30 text-amber-300",
  codec: "border-border text-foreground-2",
  audio: "border-border text-muted-foreground",
};

/** 2160p · WEB-DL · DV · x265 · DDP5.1, pulled out of a release name. */
export function QualityChips({ tokens }: { tokens: QualityToken[] }) {
  if (!tokens.length) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {tokens.map((token) => (
        <span
          key={token.kind}
          className={cn(
            "rounded-md border px-1.5 py-px font-mono text-[10.5px] leading-4",
            TOKEN_STYLE[token.kind]
          )}
        >
          {token.text}
        </span>
      ))}
    </span>
  );
}

/** "T" for torrent, "N" for usenet (NZB), in a small square. */
export function ProtocolMark({ protocol, className }: { protocol: Protocol; className?: string }) {
  const torrent = protocol === "torrent";
  return (
    <span
      title={torrent ? "Torrent" : protocol === "usenet" ? "Usenet" : "Unknown"}
      className={cn(
        "inline-flex size-4 shrink-0 items-center justify-center rounded-[4px] font-mono text-[9.5px] font-bold",
        torrent ? "bg-brand/20 text-brand-foreground" : "bg-sky-500/20 text-sky-300",
        className
      )}
    >
      {torrent ? "T" : protocol === "usenet" ? "N" : "?"}
      <span className="sr-only">{torrent ? " torrent" : " usenet"}</span>
    </span>
  );
}

export function HealthDot({
  state,
  className,
}: {
  state: ProwlarrIndexer["state"];
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-2 shrink-0 rounded-full",
        INDEXER_STATE[state].dot,
        className
      )}
    />
  );
}

/** A row of toggles where several can be on at once (categories, indexers). */
export function ToggleChips<T extends string | number>({
  items,
  selected,
  onToggle,
  label,
}: {
  items: readonly { value: T; label: string; count?: number }[];
  selected: readonly T[];
  onToggle: (value: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {items.map((item) => {
        const on = selected.includes(item.value);
        return (
          <button
            key={String(item.value)}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(item.value)}
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold transition-colors",
              on
                ? "border-brand/40 bg-brand/15 text-brand-foreground"
                : "border-border/70 text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            )}
          >
            {item.label}
            {item.count != null && (
              <span className="font-mono text-[10.5px] text-muted-foreground/70 tabular-nums">
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * One line of the search options: a short name, then its control. The name
 * stays beside the control even on a phone, in a narrow column, so the whole
 * panel is a few rows tall and every control starts at the same edge.
 */
export function OptionRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[4.25rem_minmax(0,1fr)] items-center gap-2 px-3 py-2 sm:grid-cols-[6.5rem_minmax(0,1fr)] sm:gap-3">
      <span className="text-[10.5px] font-semibold tracking-wide text-muted-foreground uppercase sm:text-[11px]">
        {label}
      </span>
      <div className="flex min-w-0 items-center gap-3">{children}</div>
    </div>
  );
}

/**
 * Pick one of a few. Equal-width segments that fill the row on a phone (so
 * each is a full-size target, words only) and shrink to their content, with
 * icons, on wider screens.
 */
export function Segmented<T extends string>({
  items,
  value,
  onChange,
  onReselect,
  label,
}: {
  items: readonly {
    value: T;
    label: string;
    icon?: ComponentType<{ className?: string }>;
    count?: number;
  }[];
  value: T;
  onChange: (value: T) => void;
  /** Tapping the segment already chosen, e.g. to open the indexer picker again. */
  onReselect?: (value: T) => void;
  label: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="grid w-full auto-cols-fr grid-flow-col gap-0.5 rounded-lg border border-border/70 bg-background/40 p-0.5 sm:inline-grid sm:w-auto"
    >
      {items.map((item) => {
        const on = item.value === value;
        const Glyph = item.icon;
        return (
          <button
            key={item.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => (on ? onReselect?.(item.value) : onChange(item.value))}
            className={cn(
              "flex h-9 min-w-0 items-center justify-center gap-1.5 rounded-md border px-1.5 text-[13px] font-semibold whitespace-nowrap transition-colors sm:h-8 sm:px-3 sm:text-xs",
              on
                ? "border-brand/35 bg-brand/20 text-brand-foreground"
                : "border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            )}
          >
            {Glyph && <Glyph className="hidden size-3.5 shrink-0 sm:block" />}
            <span className="truncate">{item.label}</span>
            {item.count != null && (
              <span className="rounded-full bg-brand/30 px-1.5 font-mono text-[10.5px] leading-4 tabular-nums">
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Categories as pills: "All" when none is chosen, a tick on each chosen one.
 * One row that scrolls sideways on a phone, fading at the edge so it is clear
 * there is more; wrapped from `sm` up.
 */
export function CategoryPills({
  selected,
  onToggle,
  onAll,
}: {
  selected: readonly number[];
  onToggle: (id: number) => void;
  onAll: () => void;
}) {
  const pill = (on: boolean) =>
    cn(
      "flex h-8 shrink-0 items-center gap-1 rounded-full border px-3 text-[12.5px] font-semibold transition-colors",
      on
        ? "border-brand/40 bg-brand/15 text-brand-foreground"
        : "border-border/70 text-muted-foreground hover:border-border hover:text-foreground"
    );
  return (
    <div
      role="group"
      aria-label="Categories"
      className="-mx-3 flex min-w-0 flex-1 gap-1.5 overflow-x-auto [mask-image:linear-gradient(to_right,black_calc(100%-28px),transparent)] px-3 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:[mask-image:none] sm:px-0"
    >
      <button
        type="button"
        aria-pressed={selected.length === 0}
        onClick={onAll}
        className={pill(selected.length === 0)}
      >
        All
      </button>
      {CATEGORIES.map((category) => {
        const on = selected.includes(category.id);
        return (
          <button
            key={category.id}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(category.id)}
            className={pill(on)}
          >
            {on && <IconCheck className="size-3.5" />}
            {category.label}
          </button>
        );
      })}
      {/* Room after the last pill, so the fade does not cover it when scrolled to the end. */}
      <span aria-hidden className="w-3 shrink-0 sm:hidden" />
    </div>
  );
}
