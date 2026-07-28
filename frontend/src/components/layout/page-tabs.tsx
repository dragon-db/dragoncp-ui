import { Fragment, type ComponentType } from "react";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

/**
 * The top-level section switcher for a page — one segmented control, one
 * active section. Styled to match the sidebar and bottom nav: quiet inactive
 * segments, a brand wash and ring on the active one, so "where am I" reads the
 * same everywhere in the app.
 *
 * Render it inside a `<Tabs>` root alongside the `<TabsContent>` panels.
 */

export interface PageTabItem {
  value: string;
  label: string;
  icon?: ComponentType<{ className?: string }>;
  /** Shown as a chip after the label. Omit when there is nothing to count. */
  count?: number;
  /**
   * Draws a rule before this segment, marking it as a different kind of thing
   * from the ones before it — a tool sitting after a set of views, rather than
   * another view. Without it a countless segment among counted ones just reads
   * as one that forgot its chip.
   */
  separated?: boolean;
}

export function PageTabsList({ items, className }: { items: PageTabItem[]; className?: string }) {
  return (
    // Pill inside pill: the track is `rounded-full` and so is each segment, so
    // the two curves stay concentric at any height without radius arithmetic.
    // `group-data-horizontal/tabs:h-auto` is needed as well as `h-auto` — the
    // base TabsList pins a 32px height with that same variant, which a plain
    // `h-auto` does not override, and the taller segments then spill out of it.
    // `overflow-hidden` is the guarantee, not the fix: whatever the segments do,
    // an active pill can never paint outside the track's rounded edge. The
    // shrinking below is what stops it needing to.
    <TabsList
      className={cn(
        "w-full gap-1 overflow-hidden rounded-full border border-border bg-card p-1 group-data-horizontal/tabs:h-auto sm:w-fit",
        className
      )}
    >
      {items.map((item) => (
        <Fragment key={item.value}>
          {item.separated && (
            <span
              aria-hidden
              className="my-2 w-px shrink-0 self-stretch bg-border"
            />
          )}
          <TabsTrigger
            value={item.value}
            className={cn(
              // Segments size to their own content and give up room in
              // proportion when there is not enough - equal thirds would
              // squeeze "Activity 0" to fit "Simulate", which needs less.
              // `min-w-0` is what allows any of it: flex items default to
              // `min-width: auto` and would otherwise push out of the track.
              // `flex-initial` (0 1 auto) overrides the base trigger's `flex-1`,
              // whose 0% basis gives every segment the same width whatever it
              // contains - which is what squeezed "Activity 0" to fit
              // "Simulate". Sizing to content and shrinking only when short of
              // room keeps the labels whole. `flex-none` above sm stops them
              // shrinking at all, since the track is `w-fit` there and grows.
              "h-9 min-w-0 flex-initial gap-1.5 rounded-full px-2 text-[13px] font-medium",
              "sm:flex-none sm:gap-2 sm:px-4",
              "data-active:bg-brand/15 data-active:font-semibold data-active:text-brand-foreground",
              "data-active:ring-1 data-active:ring-brand/35 data-active:ring-inset",
              "dark:data-active:border-transparent dark:data-active:bg-brand/15",
              "[&_svg]:text-current data-active:[&_svg]:text-brand-hover"
            )}
          >
            {item.icon && <item.icon className="size-4 shrink-0" />}
            {/* The label is the only part that may give up room; the icon and
                the count stay legible at any width. */}
            <span className="min-w-0 truncate">{item.label}</span>
            {/* Dropped on phones, where the room buys a readable label and the
                stat tiles directly below already carry the same numbers. */}
            {item.count !== undefined && (
              <span className="hidden shrink-0 rounded-full bg-black/25 px-1.5 py-px font-mono text-[10px] text-current tabular-nums sm:inline">
                {item.count}
              </span>
            )}
          </TabsTrigger>
        </Fragment>
      ))}
    </TabsList>
  );
}
