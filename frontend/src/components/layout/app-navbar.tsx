import { Link, useLocation } from "@tanstack/react-router";
import { useActiveTransfers } from "@/hooks/useTransfers";
import { useWebhookNotifications } from "@/hooks/useWebhooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RealtimeStatus } from "@/components/layout/realtime-status";
import { IconHome, IconChevronRight, IconBell, IconSettings } from "@tabler/icons-react";

const APP_VERSION = "v2.1.4";

interface Crumb {
  section: string;
  label: string;
}

// pathname prefix → breadcrumb. Longest match wins.
const CRUMBS: Array<[string, Crumb]> = [
  ["/dashboard", { section: "Workspace", label: "Dashboard" }],
  ["/transfers", { section: "Workspace", label: "Transfers" }],
  ["/webhooks", { section: "Workspace", label: "Webhooks" }],
  ["/media/movies", { section: "Library", label: "Movies" }],
  ["/media/tvshows", { section: "Library", label: "TV Shows" }],
  ["/media/anime", { section: "Library", label: "Anime" }],
  ["/backups", { section: "System", label: "Backups" }],
  ["/settings", { section: "System", label: "Settings" }],
];

function resolveCrumb(pathname: string): Crumb {
  const match = CRUMBS.find(([prefix]) => pathname === prefix || pathname.startsWith(prefix + "/"));
  return match?.[1] ?? { section: "Workspace", label: "Dashboard" };
}

export function AppNavbar() {
  const location = useLocation();
  const crumb = resolveCrumb(location.pathname);

  const activeQuery = useActiveTransfers();
  const running = activeQuery.data?.queue_status.running_count ?? 0;
  const queued = activeQuery.data?.queue_status.queued_count ?? 0;

  const notificationsQuery = useWebhookNotifications();
  const pendingCount = (notificationsQuery.data?.notifications ?? []).filter(
    (n) => n.status === "pending"
  ).length;

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4 md:px-6">
      {/* Breadcrumb — context, left. Below md the bottom nav owns the sidebar
          toggle, so the header keeps no trigger of its own. */}
      <nav className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
        <IconHome className="hidden size-4 shrink-0 sm:block" />
        <span className="hidden sm:inline">{crumb.section}</span>
        <IconChevronRight className="hidden size-3.5 shrink-0 opacity-50 sm:block" />
        <span className="truncate font-display text-[15px] font-semibold tracking-tight text-foreground">
          {crumb.label}
        </span>
      </nav>

      <div className="flex-1" />

      {/* Live metrics pill — right. Realtime segment opens the connection popover. */}
      <div className="hidden items-stretch overflow-hidden rounded-full border border-border bg-black/20 font-mono text-xs lg:flex">
        <RealtimeStatus />
        <div className="flex items-center gap-2 self-stretch border-l border-border px-3 py-1.5">
          <span className="text-muted-foreground">Active</span>
          <span className="font-medium text-brand-hover">{running}</span>
        </div>
        <div className="flex items-center gap-2 self-stretch border-l border-border px-3 py-1.5">
          <span className="text-muted-foreground">Queued</span>
          <span className="font-medium text-foreground">{queued}</span>
        </div>
      </div>

      {/* Notifications */}
      <Link to="/webhooks">
        <Button
          variant="ghost"
          size="icon"
          className="relative size-8 text-muted-foreground hover:text-foreground"
          title={pendingCount > 0 ? `${pendingCount} pending webhook(s)` : "Webhooks"}
        >
          <IconBell className="size-[18px]" />
          {pendingCount > 0 && (
            <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-brand-accent ring-2 ring-background" />
          )}
        </Button>
      </Link>

      {/* Settings */}
      <Link to="/settings">
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-foreground"
          title="Settings"
        >
          <IconSettings className="size-[18px]" />
        </Button>
      </Link>

      <Badge
        variant="outline"
        className="hidden font-mono text-xs text-muted-foreground sm:inline-flex"
      >
        {APP_VERSION}
      </Badge>
    </header>
  );
}
