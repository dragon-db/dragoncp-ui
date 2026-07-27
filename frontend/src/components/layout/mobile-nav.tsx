import type { ComponentType } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { useActiveTransfers } from "@/hooks/useTransfers";
import { useWebhookNotifications } from "@/hooks/useWebhooks";
import { Badge } from "@/components/ui/badge";
import { useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { IconHome, IconTransfer, IconWebhook, IconMenu2 } from "@tabler/icons-react";

/**
 * Bottom navigation for phones. The sidebar collapses into a sheet below `md`,
 * which leaves one small trigger in the header as the only way around the app —
 * this puts the three places you actually move between, plus that sheet, under
 * your thumb. Hidden from `md` up, where the sidebar is always on screen.
 *
 * It is a flex sibling of the scrolling <main>, not a fixed overlay, so page
 * content is never hidden underneath it.
 */

interface Destination {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  /** Prefix match, for routes with children. */
  match?: (pathname: string) => boolean;
}

const DESTINATIONS: Destination[] = [
  { to: "/dashboard", label: "Home", icon: IconHome },
  { to: "/transfers", label: "Transfers", icon: IconTransfer },
  { to: "/webhooks", label: "Webhooks", icon: IconWebhook },
];

const tabBase =
  "relative flex flex-1 flex-col items-center justify-center gap-1 py-2 text-[10px] font-semibold tracking-wide transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-inset";

/** Brand rail across the top edge marks the tab you are on. */
function ActiveRail({ active }: { active: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "absolute inset-x-4 top-0 h-[3px] rounded-b-full bg-brand-gradient-x transition-opacity",
        active ? "opacity-100" : "opacity-0"
      )}
    />
  );
}

/** Unread-style count, only rendered when there is something to report. */
function TabBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <Badge className="absolute -top-1.5 -right-2.5 h-4 min-w-4 border-0 bg-brand px-1 font-mono text-[9px] leading-none text-white ring-2 ring-background">
      {count > 99 ? "99+" : count}
    </Badge>
  );
}

export function MobileNav() {
  const location = useLocation();
  const { openMobile, setOpenMobile } = useSidebar();

  const activeQuery = useActiveTransfers();
  const transferCount =
    (activeQuery.data?.queue_status.running_count ?? 0) +
    (activeQuery.data?.queue_status.queued_count ?? 0);

  const notificationsQuery = useWebhookNotifications();
  const pendingCount = (notificationsQuery.data?.notifications ?? []).filter(
    (notification) => notification.status === "pending"
  ).length;

  const counts: Record<string, number> = {
    "/transfers": transferCount,
    "/webhooks": pendingCount,
  };

  const isActive = (destination: Destination) =>
    destination.match
      ? destination.match(location.pathname)
      : location.pathname === destination.to || location.pathname.startsWith(`${destination.to}/`);

  return (
    <nav
      aria-label="Primary"
      className="sticky bottom-0 z-30 flex shrink-0 border-t border-border bg-background/85 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
    >
      {DESTINATIONS.map((destination) => {
        const active = isActive(destination);
        return (
          <Link
            key={destination.to}
            to={destination.to}
            aria-current={active ? "page" : undefined}
            className={cn(
              tabBase,
              active ? "text-brand-foreground" : "text-muted-foreground active:bg-muted/40"
            )}
          >
            <ActiveRail active={active} />
            <span className="relative">
              <destination.icon
                className={cn("size-[22px]", active ? "text-brand-hover" : "text-current")}
              />
              <TabBadge count={counts[destination.to] ?? 0} />
            </span>
            {destination.label}
          </Link>
        );
      })}

      <button
        type="button"
        aria-label="Open menu"
        aria-expanded={openMobile}
        onClick={() => setOpenMobile(true)}
        className={cn(
          tabBase,
          openMobile ? "text-brand-foreground" : "text-muted-foreground active:bg-muted/40"
        )}
      >
        <ActiveRail active={openMobile} />
        <IconMenu2 className={cn("size-[22px]", openMobile && "text-brand-hover")} />
        Menu
      </button>
    </nav>
  );
}
