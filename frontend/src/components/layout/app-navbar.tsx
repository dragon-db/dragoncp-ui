import { Link, useLocation } from "@tanstack/react-router";
import { useActiveTransfers } from "@/hooks/useTransfers";
import { useAlertSummary } from "@/hooks/useSync";
import { useAppVersion, useTestMode } from "@/hooks/useConfig";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { RealtimeStatus } from "@/components/layout/realtime-status";
import { IconHome, IconChevronRight, IconBell, IconFlask, IconSettings } from "@tabler/icons-react";

interface Crumb {
  section: string;
  label: string;
}

// pathname prefix → breadcrumb. Longest match wins.
const CRUMBS: Array<[string, Crumb]> = [
  ["/dashboard", { section: "Workspace", label: "Dashboard" }],
  ["/transfers", { section: "Workspace", label: "Transfers" }],
  ["/webhooks", { section: "Workspace", label: "Webhooks" }],
  ["/notifications", { section: "Workspace", label: "Notifications" }],
  ["/media/movies", { section: "Library", label: "Movies" }],
  ["/media/tvshows", { section: "Library", label: "TV Shows" }],
  ["/media/anime", { section: "Library", label: "Anime" }],
  ["/backups", { section: "System", label: "Backups" }],
  ["/activity", { section: "System", label: "Activity" }],
  ["/settings", { section: "System", label: "Settings" }],
];

function resolveCrumb(pathname: string): Crumb {
  // Integrations are one page per connector and the list comes from the server,
  // so there is nothing static to match against. The id in the path is the
  // name — "discord" is Discord — which holds for any connector added later
  // without this table needing to hear about it.
  if (pathname.startsWith("/integrations/")) {
    const id = pathname.split("/")[2] ?? "";
    return {
      section: "Integrations",
      label: id ? id.charAt(0).toUpperCase() + id.slice(1) : "Integrations",
    };
  }

  const match = CRUMBS.find(([prefix]) => pathname === prefix || pathname.startsWith(prefix + "/"));
  return match?.[1] ?? { section: "Workspace", label: "Dashboard" };
}

export function AppNavbar() {
  const location = useLocation();
  const crumb = resolveCrumb(location.pathname);
  const version = useAppVersion();
  const testMode = useTestMode();

  const activeQuery = useActiveTransfers();
  const running = activeQuery.data?.queue_status.running_count ?? 0;
  const queued = activeQuery.data?.queue_status.queued_count ?? 0;

  // The bell is for what needs a person — open alerts — not for every webhook
  // still waiting its turn, which is the pipeline doing its job.
  const openAlerts = useAlertSummary().data?.open ?? 0;

  return (
    <header className="flex h-[58px] shrink-0 items-center gap-3 border-b border-border px-4 md:px-6">
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

      {/*
        Test mode.

        Deliberately NOT hidden on small screens, unlike the version badge
        beside it. This is the one thing in the header that changes what every
        result in the application means — with it on, a transfer reports
        "completed" and a restore reports "restored" while nothing is written to
        disk — and a phone is exactly where somebody checks whether a sync
        worked. A badge that disappeared at the width it is most needed would be
        worse than none.

        Kept to a chip rather than a banner because this only ever runs on the
        development instance. If it ever appears on the production one, that is
        itself the emergency it is reporting.
      */}
      {testMode && (
        <span
          role="status"
          title="Test mode: nothing is written to disk. Transfers and restores report success without moving any files."
          className="inline-flex flex-none items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold tracking-[0.06em] text-amber-300 uppercase"
        >
          <IconFlask aria-hidden="true" className="size-3" />
          Test
        </span>
      )}

      {/* Notifications — the link carries the button styling itself; a <button>
          nested inside the <a> would be an interactive element inside another. */}
      <Link
        to="/notifications"
        className={cn(
          buttonVariants({ variant: "ghost", size: "icon" }),
          "relative size-8 text-muted-foreground hover:text-foreground"
        )}
        title={
          openAlerts > 0
            ? `${openAlerts} notification${openAlerts === 1 ? "" : "s"} need you`
            : "Notifications"
        }
      >
        <IconBell className="size-[18px]" />
        {openAlerts > 0 && (
          <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-brand-accent ring-2 ring-background" />
        )}
      </Link>

      {/* Settings */}
      <Link
        to="/settings"
        className={cn(
          buttonVariants({ variant: "ghost", size: "icon" }),
          "size-8 text-muted-foreground hover:text-foreground"
        )}
        title="Settings"
      >
        <IconSettings className="size-[18px]" />
      </Link>

      <Badge
        variant="outline"
        className="hidden font-mono text-xs text-muted-foreground sm:inline-flex"
      >
        v{version}
      </Badge>
    </header>
  );
}
