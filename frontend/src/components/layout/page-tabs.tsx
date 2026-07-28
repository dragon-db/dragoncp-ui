import type { ComponentType } from "react";
import { Badge } from "@/components/ui/badge";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

/**
 * The top-level section switcher for a page.
 *
 * Underlined rather than a pill: the mobile bottom nav already marks "where am
 * I" with a brand rail, so a page does the same and the app has one idiom for
 * it instead of two. It is shadcn's built-in `line` variant re-tinted to the
 * brand, not a bespoke control.
 *
 * The rail also drops the enclosing track a pill needs, which is what used to
 * make this fragile — a fixed-width container that segments could overflow or
 * float inside. Here the segments simply sit on a hairline, so any number of
 * them work at any width, and the row scrolls if it ever runs out of room.
 *
 * Render inside a `<Tabs>` root alongside the `<TabsContent>` panels.
 */

export interface PageTabItem {
  value: string;
  label: string;
  icon?: ComponentType<{ className?: string }>;
  /** Shown as a badge after the label. Omit when there is nothing to count. */
  count?: number;
  /**
   * Pushes this segment to the far end, separating a tool from the views
   * before it. Position carries the distinction, so a countless segment among
   * counted ones reads as deliberate rather than unfinished.
   */
  atEnd?: boolean;
}

export function PageTabsList({ items, className }: { items: PageTabItem[]; className?: string }) {
  return (
    <TabsList
      variant="line"
      className={cn(
        // `h-auto` twice: the base list pins a height under the horizontal
        // variant, which a plain `h-auto` does not beat.
        "h-auto w-full flex-wrap justify-start gap-x-1 gap-y-0 rounded-none border-b border-border p-0",
        "group-data-horizontal/tabs:h-auto",
        className
      )}
    >
      {items.map((item) => (
        <TabsTrigger
          key={item.value}
          value={item.value}
          className={cn(
            // `flex-none` beats the base trigger's `flex-1`, whose 0% basis
            // would stretch three segments across the whole row.
            "h-auto flex-none gap-2 px-3 pb-2.5 text-[13px]",
            // The base variant hangs its rule 5px below the segment, for a list
            // that has padding under it. This one sits directly on the
            // hairline, so the offset has to go — and the base sets it through
            // a group variant, which a plain utility would lose to.
            "after:bottom-0!",
            "data-active:text-brand-foreground data-active:after:bg-brand-gradient-x",
            "data-active:[&_svg]:text-brand-hover",
            item.atEnd && "ml-auto"
          )}
        >
          {item.icon && <item.icon />}
          {item.label}
          {item.count !== undefined && (
            <Badge variant="secondary" className="px-1.5 font-mono tabular-nums">
              {item.count}
            </Badge>
          )}
        </TabsTrigger>
      ))}
    </TabsList>
  );
}
