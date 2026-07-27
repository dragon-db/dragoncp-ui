import type { ComponentType, ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * The page spine: every section of a page is a bordered card introduced by a
 * mono uppercase label — the same eyebrow the sidebar groups and the dashboard
 * strips already use. Pages become a readable stack of these instead of a set
 * of one-off panels.
 *
 * `actions` sits at the end of the label row; `toolbar` is a full-width strip
 * under it for filters and controls that belong to the section's content.
 */
export function SectionCard({
  label,
  description,
  actions,
  toolbar,
  children,
  className,
  contentClassName,
}: {
  label: string;
  description?: string;
  actions?: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  return (
    <section className={cn("overflow-hidden rounded-xl border border-border bg-card", className)}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3.5 pb-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="font-mono text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            {label}
          </h2>
          {description && (
            <p className="text-[12.5px] text-pretty text-muted-foreground/90">{description}</p>
          )}
        </div>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </header>

      {toolbar && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-2 border-t border-border/70 px-3 py-2.5">
          {toolbar}
        </div>
      )}

      <div className={cn("border-t border-border/70", contentClassName)}>{children}</div>
    </section>
  );
}

/** Empty state for a section's content area — an invitation, not a shrug. */
export function SectionEmpty({
  icon: Icon,
  title,
  hint,
  action,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
      <Icon className="size-7 text-muted-foreground/70" />
      <span className="text-sm font-medium text-foreground">{title}</span>
      {hint && <span className="max-w-sm text-xs text-muted-foreground">{hint}</span>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
