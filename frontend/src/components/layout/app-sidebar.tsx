import { useState, type ComponentType } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { useAuthStore } from "@/stores/auth";
import { useLogout } from "@/hooks/useAuth";
import { useConnectors } from "@/hooks/useConnectors";
import { useAlertSummary } from "@/hooks/useSync";
import { ConnectorIcon } from "@/components/integrations/connector-icon";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  IconLayoutDashboard,
  IconTransfer,
  IconWebhook,
  IconBell,
  IconCategory2,
  IconMovie,
  IconDeviceTv,
  IconBrandNetflix,
  IconArchive,
  IconHistory,
  IconSettings,
  IconLogout,
  IconChevronRight,
} from "@tabler/icons-react";

const LOGO_URL = "/dragoncp-logo.png";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  match?: (pathname: string) => boolean;
}

const workspaceItems: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: IconLayoutDashboard },
  { to: "/transfers", label: "Transfers", icon: IconTransfer },
  { to: "/webhooks", label: "Webhooks", icon: IconWebhook },
  { to: "/notifications", label: "Notifications", icon: IconBell },
];

const mediaItems: NavItem[] = [
  {
    to: "/media/movies",
    label: "Movies",
    icon: IconMovie,
    match: (p) => p.startsWith("/media/movies"),
  },
  {
    to: "/media/tvshows",
    label: "TV Shows",
    icon: IconDeviceTv,
    match: (p) => p.startsWith("/media/tvshows"),
  },
  {
    to: "/media/anime",
    label: "Anime",
    icon: IconBrandNetflix,
    match: (p) => p.startsWith("/media/anime"),
  },
];

const systemItems: NavItem[] = [
  { to: "/backups", label: "Backups", icon: IconArchive },
  { to: "/activity", label: "Activity", icon: IconHistory },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

// Brand active/hover treatment for the Inset Cockpit look. Semantic + brand
// tokens only — the inactive state is quiet, the active state lights up.
const navButton = cn(
  "text-sidebar-foreground/80 transition-colors [&_svg]:text-sidebar-foreground/55",
  "data-active:bg-brand/15 data-active:font-medium data-active:text-brand-foreground",
  "data-active:ring-1 data-active:ring-brand/35 data-active:ring-inset",
  "data-active:[&_svg]:text-brand-hover"
);

const eyebrow =
  "font-display text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground";

export function AppSidebar() {
  const location = useLocation();
  const { user } = useAuthStore();
  const logoutMutation = useLogout();
  const { setOpenMobile } = useSidebar();

  const mediaSectionActive = location.pathname.startsWith("/media/");
  const [mediaOpen, setMediaOpen] = useState(true);
  const mediaExpanded = mediaSectionActive || mediaOpen;

  // The connector list comes from the server, not from a list kept here. A
  // connector added on the backend appears in this menu on the next load
  // without the frontend knowing it exists — which is the whole point of the
  // adapters registering themselves.
  const connectorsQuery = useConnectors();
  const connectors = connectorsQuery.data ?? [];

  // Open alerts, on the item that lists them: the one count in this menu that
  // means someone has to do something.
  const openAlerts = useAlertSummary().data?.open ?? 0;
  const counts: Record<string, number> = { "/notifications": openAlerts };

  const closeMobile = () => setOpenMobile(false);
  const isActive = (item: NavItem) =>
    item.match ? item.match(location.pathname) : location.pathname === item.to;

  return (
    <Sidebar
      variant="inset"
      className="[&_[data-slot=sidebar-inner]]:bg-transparent [&_[data-slot=sidebar-inner]]:ring-0"
    >
      <SidebarHeader>
        <Link
          to="/dashboard"
          onClick={closeMobile}
          className="flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-sidebar-accent/50"
        >
          <img
            src={LOGO_URL}
            alt="DragonCP"
            className="size-8 shrink-0 object-contain drop-shadow-[0_3px_12px_rgba(166,14,239,0.4)]"
          />
          <span className="font-display text-[1.2rem] font-bold tracking-wide text-foreground">
            Dragon<span className="text-brand-gradient">CP</span>
          </span>
        </Link>
      </SidebarHeader>

      <SidebarContent className="gap-1 px-1">
        <SidebarGroup>
          <SidebarGroupLabel className={eyebrow}>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {workspaceItems.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton
                    render={<Link to={item.to} />}
                    isActive={isActive(item)}
                    onClick={closeMobile}
                    className={navButton}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                    {(counts[item.to] ?? 0) > 0 && (
                      <span
                        className="ml-auto min-w-5 rounded-full border border-amber-500/40 bg-amber-500/15 px-1.5 text-center font-mono text-[10px] leading-4 text-amber-300"
                        title={`${counts[item.to]} open`}
                      >
                        {counts[item.to] > 99 ? "99+" : counts[item.to]}
                      </span>
                    )}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel className={eyebrow}>Library</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={mediaSectionActive}
                  onClick={() => setMediaOpen((v) => !v)}
                  aria-expanded={mediaExpanded}
                  className={navButton}
                >
                  {/* Four squares, because this item opens into exactly that:
                      the three libraries. The photo-album glyph it replaced
                      read as pictures rather than a media library, and its
                      frame-and-stack detail turned to mush at 16px. */}
                  <IconCategory2 />
                  <span>Browse Media</span>
                  <IconChevronRight
                    className={cn("ml-auto transition-transform", mediaExpanded && "rotate-90")}
                  />
                </SidebarMenuButton>
                {mediaExpanded && (
                  <SidebarMenuSub>
                    {mediaItems.map((item) => (
                      <SidebarMenuSubItem key={item.to}>
                        <SidebarMenuSubButton
                          render={<Link to={item.to} />}
                          isActive={isActive(item)}
                          onClick={closeMobile}
                          className={navButton}
                        >
                          <item.icon />
                          <span>{item.label}</span>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                    ))}
                  </SidebarMenuSub>
                )}
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/*
          Flat, unlike Browse Media. That one collapses because its three
          entries are one thing seen three ways; these are separate
          applications that happen to be reached from the same place, and a
          "Connectors" parent above them was a level that existed only to be
          expanded before Discord could be clicked.

          Hidden entirely until the list arrives. A labelled section with
          nothing under it reads as "there are no connectors" when what it
          actually means is "the request has not come back" — and if the
          backend is older than this build it never will.
        */}
        {connectors.length > 0 && (
          <SidebarGroup>
            <SidebarGroupLabel className={eyebrow}>Integrations</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {connectors.map((connector) => (
                  <SidebarMenuItem key={connector.id}>
                    <SidebarMenuButton
                      render={
                        <Link to="/integrations/$connector" params={{ connector: connector.id }} />
                      }
                      isActive={location.pathname === `/integrations/${connector.id}`}
                      onClick={closeMobile}
                      className={navButton}
                    >
                      <ConnectorIcon connectorId={connector.id} />
                      <span>{connector.display_name}</span>
                      {connector.enabled && (
                        <span
                          className="ml-auto size-1.5 rounded-full bg-brand"
                          title="Turned on"
                        />
                      )}
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}

        <SidebarGroup>
          <SidebarGroupLabel className={eyebrow}>System</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {systemItems.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton
                    render={<Link to={item.to} />}
                    isActive={isActive(item)}
                    onClick={closeMobile}
                    className={navButton}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="flex items-center gap-2.5 px-1 py-1">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-[11px] bg-brand-gradient font-display text-sm font-semibold text-white shadow-[0_4px_14px_-6px_rgba(166,14,239,0.6)]">
            {user?.charAt(0).toUpperCase() || "U"}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-sidebar-foreground">
              {user || "User"}
            </div>
            <div className="text-[10px] font-medium tracking-[0.16em] text-muted-foreground uppercase">
              Session
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground hover:bg-destructive/12 hover:text-destructive"
            onClick={() => logoutMutation.mutate()}
            title="Log out"
          >
            <IconLogout className="size-5" />
          </Button>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
