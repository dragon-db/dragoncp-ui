import { cn } from "@/lib/utils";

/**
 * The four-numbers-at-a-glance row every workspace page opens with. Tone is
 * carried by the number alone — labels and units stay quiet so a screen full of
 * tiles doesn't turn into a traffic light.
 */

export type StatTone = "default" | "ok" | "warn" | "crit";

export interface StatTile {
  label: string;
  value: number | string;
  /** Short qualifier after the number: "synced", "in 6 groups". */
  unit?: string;
  tone?: StatTone;
}

const TONE: Record<StatTone, string> = {
  default: "text-foreground",
  ok: "text-emerald-400",
  warn: "text-amber-400",
  crit: "text-rose-400",
};

export function StatTiles({ items, className }: { items: StatTile[]; className?: string }) {
  return (
    <div className={cn("grid grid-cols-2 gap-3 lg:grid-cols-4", className)}>
      {items.map((item) => (
        <div key={item.label} className="rounded-xl border border-border bg-card px-4 py-3">
          <div className="mb-1.5 font-mono text-[10px] tracking-[0.06em] text-muted-foreground uppercase">
            {item.label}
          </div>
          <div className="flex items-baseline gap-1.5">
            <span
              className={cn(
                "font-display text-2xl font-semibold tabular-nums",
                TONE[item.tone ?? "default"]
              )}
            >
              {item.value}
            </span>
            {item.unit && <span className="text-[11px] text-muted-foreground">{item.unit}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
