import { useState, type ComponentType } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { useAuthStore } from "@/stores/auth";
import { useLogout } from "@/hooks/useAuth";
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
  IconLibraryPhoto,
  IconMovie,
  IconDeviceTv,
  IconBrandNetflix,
  IconArchive,
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
                  <IconLibraryPhoto />
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
