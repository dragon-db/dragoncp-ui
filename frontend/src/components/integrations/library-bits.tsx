import { useState, type ComponentType, type ReactNode } from "react";
import { IconDeviceTv, IconListDetails, IconMovie } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import type { EpisodeState } from "@/hooks/useMediaLibrary";
import {
  EPISODE_STATE,
  TONE_CHIP,
  TONE_TEXT,
  titleState,
  type Tone,
} from "@/components/integrations/library-vocab";

/**
 * Presentation pieces shared by the Library, Queue and History tabs and the
 * series view. Badges keep the app's shape (rounded, hairline, a 15% fill of
 * the tone, an icon and a bold uppercase word) so a state reads the same here
 * as on every other page.
 */

type Icon = ComponentType<{ className?: string }>;

export function ToneChip({
  tone,
  icon: Glyph,
  label,
  size = "default",
  title,
  className,
}: {
  tone: Tone;
  icon: Icon;
  label: string;
  size?: "default" | "sm";
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full shrink-0 items-center gap-1 rounded-full border font-bold tracking-wide whitespace-nowrap uppercase",
        size === "sm" ? "px-1.5 py-px text-[9px]" : "px-2 py-0.5 text-[10px]",
        TONE_CHIP[tone],
        className
      )}
    >
      <Glyph className={cn("shrink-0", size === "sm" ? "size-2.5" : "size-3")} />
      <span className="truncate">{label}</span>
    </span>
  );
}

/** A title's one state, as a badge. */
export function TitleStateChip({
  state,
  size,
  title,
  className,
}: {
  state: string | undefined;
  size?: "default" | "sm";
  title?: string;
  className?: string;
}) {
  const info = titleState(state);
  return (
    <ToneChip
      tone={info.tone}
      icon={info.icon}
      label={info.label}
      size={size}
      title={title}
      className={className}
    />
  );
}

/** An episode's state as an icon and a word — the right-hand column of a row. */
export function EpisodeMark({ state, className }: { state: EpisodeState; className?: string }) {
  const info = EPISODE_STATE[state];
  const Glyph = info.icon;
  return (
    <span
      title={info.hint}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 text-[12px] whitespace-nowrap",
        info.tone === "warn" ? "font-semibold" : "font-medium",
        TONE_TEXT[info.tone],
        className
      )}
    >
      <Glyph className="size-3.5" />
      {info.label}
    </span>
  );
}

/**
 * A poster, or the title's kind of media on a recessed tile when there is none
 * or it will not load. Posters come from the service's image host; a broken
 * one must not leave a hole in the grid.
 */
export function TitlePoster({
  src,
  movie,
  interactive = false,
  className,
}: {
  src: string | null | undefined;
  movie?: boolean;
  /**
   * Inside a card that opens something (`group/card`): on hover or keyboard
   * focus the picture eases in a little within its frame, a brand ring draws
   * round it and a veil names what opens. The card itself stays put — a grid
   * whose tiles jump as the pointer crosses them reads as unsteady.
   */
  interactive?: boolean;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const Fallback = movie ? IconMovie : IconDeviceTv;
  return (
    <div
      className={cn(
        "relative aspect-[2/3] shrink-0 overflow-hidden rounded-md border border-border bg-well",
        interactive &&
          "transition-shadow duration-300 group-hover/card:ring-2 group-hover/card:ring-brand/45 group-focus-visible/card:ring-2 group-focus-visible/card:ring-brand/60",
        className
      )}
    >
      <span className="absolute inset-0 grid place-items-center text-muted-foreground/60">
        <Fallback className="size-5" />
      </span>
      {src && !failed && (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
          className={cn(
            "absolute inset-0 size-full object-cover",
            interactive &&
              "transition-[transform,filter] duration-500 ease-out group-hover/card:scale-[1.04] group-hover/card:brightness-75 group-focus-visible/card:brightness-75 motion-reduce:transition-none motion-reduce:group-hover/card:scale-100"
          )}
        />
      )}
      {interactive && (
        <span className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-center gap-1 bg-gradient-to-t from-black/85 via-black/45 to-transparent pt-8 pb-2 text-[11px] font-medium text-white opacity-0 transition-opacity duration-300 group-hover/card:opacity-100 group-focus-visible/card:opacity-100">
          <IconListDetails className="size-3.5" />
          {movie ? "Details" : "Episodes"}
        </span>
      )}
    </div>
  );
}

/** A one-line banner: the service did not answer, a rule could not be applied. */
export function Notice({
  tone,
  icon: Glyph,
  children,
  className,
}: {
  tone: "warn" | "crit" | "muted";
  icon: Icon;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "muted" ? undefined : "status"}
      className={cn(
        "flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-[13px]",
        tone === "warn" && "border-amber-500/25 bg-amber-500/8 text-amber-200/90",
        tone === "crit" && "border-rose-500/25 bg-rose-500/8 text-rose-200/90",
        tone === "muted" && "border-border bg-card text-muted-foreground",
        className
      )}
    >
      <Glyph className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
