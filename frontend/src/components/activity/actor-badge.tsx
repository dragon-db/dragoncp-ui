import { cn } from "@/lib/utils";
import { IconRobot, IconUser } from "@tabler/icons-react";

interface ActorBadgeProps {
  kind: string | null | undefined;
  name: string | null | undefined;
  className?: string;
  /** Compact form for table rows, where vertical space is scarce. */
  size?: "sm" | "md";
}

/**
 * Who was responsible, shown so a person and a background job can never be
 * confused for one another.
 *
 * The server refuses usernames beginning with the automation prefixes, and this
 * is the other half of that rule: automation always carries the AUTO mark and a
 * different colour, so nobody reads "retention deleted your backup" as a
 * colleague having done it.
 */
export function ActorBadge({ kind, name, className, size = "md" }: ActorBadgeProps) {
  if (!name) {
    return <span className={cn("text-xs text-muted-foreground", className)}>—</span>;
  }

  const isPerson = kind === "admin";
  const Icon = isPerson ? IconUser : IconRobot;

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-full border font-medium",
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs",
        isPerson
          ? "border-brand/30 bg-brand/10 text-brand-accent"
          : "border-neutral-700 bg-neutral-800/60 text-neutral-300",
        className
      )}
      title={isPerson ? `Signed in as ${name}` : `Automated: ${name}`}
    >
      <Icon className={size === "sm" ? "size-3" : "size-3.5"} />
      <span className="truncate">
        {isPerson ? name : <><span className="opacity-60">AUTO</span> {name}</>}
      </span>
    </span>
  );
}
