import type { ComponentType } from "react";
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
}

export function PageTabsList({ items, className }: { items: PageTabItem[]; className?: string }) {
  return (
    // Pill inside pill: the track is `rounded-full` and so is each segment, so
    // the two curves stay concentric at any height without radius arithmetic.
    // `group-data-horizontal/tabs:h-auto` is needed as well as `h-auto` — the
    // base TabsList pins a 32px height with that same variant, which a plain
    // `h-auto` does not override, and the taller segments then spill out of it.
    <TabsList
      className={cn(
        "w-full gap-1 rounded-full border border-border bg-card p-1 group-data-horizontal/tabs:h-auto sm:w-fit",
        className
      )}
    >
      {items.map((item) => (
        <TabsTrigger
          key={item.value}
          value={item.value}
          className={cn(
            "h-9 flex-1 gap-2 rounded-full px-4 text-[13px] font-medium sm:flex-none",
            "data-active:bg-brand/15 data-active:font-semibold data-active:text-brand-foreground",
            "data-active:ring-1 data-active:ring-brand/35 data-active:ring-inset",
            "dark:data-active:border-transparent dark:data-active:bg-brand/15",
            "[&_svg]:text-current data-active:[&_svg]:text-brand-hover"
          )}
        >
          {item.icon && <item.icon className="size-4" />}
          {item.label}
          {item.count !== undefined && (
            <span className="rounded-full bg-black/25 px-1.5 py-px font-mono text-[10px] text-current tabular-nums">
              {item.count}
            </span>
          )}
        </TabsTrigger>
      ))}
    </TabsList>
  );
}
