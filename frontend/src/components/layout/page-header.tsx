import type { ComponentType, ReactNode } from "react";
import { IconDots } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface PageHeaderProps {
  title: string;
  description?: string;
  /** Controls, on the title's row at every width — on a phone too. */
  children?: ReactNode;
}

/**
 * A page's title with its controls beside it, and the description under both.
 *
 * On a phone the controls used to drop onto their own line, so "Sonarr" sat
 * above its On/Off switch and every page lost a row before its content
 * (operator, 2026-10-20). They now stay on the title's row; a page keeps them
 * narrow there by showing icons only below `sm`, or by moving the rarely used
 * ones into a `PageHeaderMenu`.
 */
export function PageHeader({ title, description, children }: PageHeaderProps) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-3">
        <h1 className="min-w-0 truncate text-2xl font-bold text-foreground sm:text-3xl">{title}</h1>
        {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
      </div>
      {description && <p className="text-muted-foreground">{description}</p>}
    </div>
  );
}

export interface PageMenuItem {
  label: string;
  icon: ComponentType<{ className?: string }>;
  onSelect: () => void;
  disabled?: boolean;
}

/**
 * A phone's "⋯" for a header's less frequent actions, written out in words.
 * An icon alone means nothing on a touch screen, where there is no tooltip to
 * hover for. Hidden from `sm` up, where the page shows them as buttons.
 */
export function PageHeaderMenu({ items }: { items: PageMenuItem[] }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="outline" size="icon" />} className="sm:hidden">
        <IconDots className="size-4" />
        <span className="sr-only">More actions</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {items.map((item) => (
          <DropdownMenuItem key={item.label} onClick={item.onSelect} disabled={item.disabled}>
            <item.icon className="size-4" />
            {item.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
