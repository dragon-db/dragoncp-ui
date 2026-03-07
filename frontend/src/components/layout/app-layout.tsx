import { useState, type ComponentType, type ReactNode } from 'react';
import { Link, useLocation } from '@tanstack/react-router';
import { useAuthStore } from '@/stores/auth';
import { useLogout } from '@/hooks/useAuth';
import { useSSHStatus } from '@/hooks/useConfig';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { useRuntimeStore } from '@/stores/runtime';
import { connectSocket } from '@/services/socket';
import { BackendUnavailableOverlay } from '@/components/layout/backend-unavailable-overlay';
import {
  IconLayoutDashboard,
  IconMovie,
  IconDeviceTv,
  IconBrandNetflix,
  IconTransfer,
  IconWebhook,
  IconArchive,
  IconSettings,
  IconLogout,
  IconMenu2,
  IconChevronDown,
  IconChevronRight,
  IconX,
} from '@tabler/icons-react';

interface AppLayoutProps {
  children: ReactNode;
}

// App version - can be made configurable from env or API later
const APP_VERSION = 'v2.0.8';

// Dragon-CP Logo URL
const LOGO_URL = 'https://blog.infinitysystems.in/dragondbserver/DragonDB_Trans.png';

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  isActive?: (pathname: string) => boolean;
}

const primaryNavItems: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: IconLayoutDashboard },
  { to: '/transfers', label: 'Transfers', icon: IconTransfer },
  { to: '/webhooks', label: 'Webhooks', icon: IconWebhook },
];

const mediaNavItems: NavItem[] = [
  { to: '/media/movies', label: 'Movies', icon: IconMovie, isActive: (pathname) => pathname.startsWith('/media/movies') },
  { to: '/media/tvshows', label: 'TV Shows', icon: IconDeviceTv, isActive: (pathname) => pathname.startsWith('/media/tvshows') },
  { to: '/media/anime', label: 'Anime', icon: IconBrandNetflix, isActive: (pathname) => pathname.startsWith('/media/anime') },
];

const utilityNavItems: NavItem[] = [
  { to: '/backups', label: 'Backups', icon: IconArchive },
  { to: '/settings', label: 'Settings', icon: IconSettings },
];

export function AppLayout({ children }: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [retryingBackend, setRetryingBackend] = useState(false);
  const location = useLocation();
  const [mediaExpandedManual, setMediaExpandedManual] = useState(true);
  const { user } = useAuthStore();
  const socketError = useRuntimeStore((state) => state.socketError);
  const sshStatusQuery = useSSHStatus();
  const logoutMutation = useLogout();
  const mediaExpanded = location.pathname.startsWith('/media/') || mediaExpandedManual;
  const backendUnavailable = sshStatusQuery.isError;
  const backendErrorMessage =
    (sshStatusQuery.error instanceof Error ? sshStatusQuery.error.message : null) ??
    socketError;

  const handleLogout = () => {
    logoutMutation.mutate();
  };

  const retryBackendConnection = async () => {
    try {
      setRetryingBackend(true);
      connectSocket();
      await sshStatusQuery.refetch();
    } finally {
      setRetryingBackend(false);
    }
  };

  const getItemActiveState = (item: NavItem) => {
    if (item.isActive) {
      return item.isActive(location.pathname);
    }
    return location.pathname === item.to;
  };

  const renderNavItem = (item: NavItem, nested = false) => {
    const isActive = getItemActiveState(item);

    return (
      <Link
        key={item.to}
        to={item.to}
        className={cn(
          'group relative flex items-center gap-3 rounded-xl border text-sm font-medium transition-all duration-200',
          nested ? 'px-3 py-2 text-[0.82rem]' : 'px-3 py-2.5',
          isActive
            ? 'border-fuchsia-400/35 bg-fuchsia-500/15 text-fuchsia-100 shadow-[0_10px_28px_-18px_rgba(217,70,239,0.9)]'
            : 'border-transparent text-sidebar-foreground/70 hover:border-sidebar-border hover:bg-sidebar-accent/70 hover:text-sidebar-foreground'
        )}
        onClick={() => setSidebarOpen(false)}
      >
        <item.icon className={cn('shrink-0', nested ? 'h-4 w-4' : 'h-5 w-5')} />
        <span className="truncate">{item.label}</span>
      </Link>
    );
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-background via-background to-muted/20">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={cn(
        "fixed inset-y-0 left-0 z-50 w-72 border-r border-sidebar-border/70 bg-sidebar/95 backdrop-blur-xl transform transition-transform duration-200 ease-in-out lg:translate-x-0 lg:static",
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      )}>
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(217,70,239,0.2),transparent_52%)]" />
        <div className="relative flex flex-col h-full">
          {/* Logo Section */}
          <div className="p-3 border-b border-sidebar-border/70">
            <div className="flex items-center justify-between gap-2">
              <Link
                to="/dashboard"
                className="flex min-w-0 items-center gap-3 rounded-xl px-2 py-2 transition-colors hover:bg-sidebar-accent/45"
              >
                <img
                  src={LOGO_URL}
                  alt="DragonCP Logo"
                  className="h-10 w-10 object-contain shrink-0"
                />
                <span className="truncate text-lg font-bold tracking-[0.16em] text-transparent bg-clip-text bg-gradient-to-r from-[#6a00fd] via-[#b200ff] to-[#fe00fc]">
                  DRAGON-CP
                </span>
              </Link>
              <Button
                variant="ghost"
                size="icon-sm"
                className="lg:hidden text-sidebar-foreground/60 hover:text-sidebar-foreground"
                onClick={() => setSidebarOpen(false)}
              >
                <IconX className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* Navigation */}
          <ScrollArea className="flex-1 py-4">
            <nav className="space-y-5 px-3">
              <div>
                <p className="px-2 pb-2 text-[0.68rem] font-semibold uppercase tracking-[0.22em] text-sidebar-foreground/35">
                  Workspace
                </p>
                <div className="space-y-1">
                  {primaryNavItems.map((item) => renderNavItem(item))}
                </div>
              </div>

              <div>
                <p className="px-2 pb-2 text-[0.68rem] font-semibold uppercase tracking-[0.22em] text-sidebar-foreground/35">
                  Library
                </p>
                <button
                  type="button"
                  className={cn(
                    'w-full flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-sm font-medium transition-all duration-200',
                    location.pathname.startsWith('/media/')
                      ? 'border-fuchsia-400/35 bg-fuchsia-500/15 text-fuchsia-100'
                      : 'border-transparent text-sidebar-foreground/70 hover:border-sidebar-border hover:bg-sidebar-accent/70 hover:text-sidebar-foreground'
                  )}
                  onClick={() => setMediaExpandedManual((value) => !value)}
                >
                  <IconMovie className="h-5 w-5 shrink-0" />
                  <span className="flex-1 truncate">Browse Media</span>
                  {mediaExpanded ? <IconChevronDown className="h-4 w-4" /> : <IconChevronRight className="h-4 w-4" />}
                </button>
                {mediaExpanded && (
                  <div className="mt-2 ml-4 border-l border-sidebar-border/70 pl-3 space-y-1">
                    {mediaNavItems.map((item) => renderNavItem(item, true))}
                  </div>
                )}
              </div>

              <div>
                <p className="px-2 pb-2 text-[0.68rem] font-semibold uppercase tracking-[0.22em] text-sidebar-foreground/35">
                  System
                </p>
                <div className="space-y-1">
                  {utilityNavItems.map((item) => renderNavItem(item))}
                </div>
              </div>
            </nav>
          </ScrollArea>

          {/* User section */}
          <div className="p-3 border-t border-sidebar-border/70">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="h-8 w-8 rounded-full bg-fuchsia-500/20 border border-fuchsia-500/35 flex items-center justify-center">
                  <span className="text-sm font-medium text-fuchsia-100">
                    {user?.charAt(0).toUpperCase() || 'U'}
                  </span>
                </div>
                <div className="min-w-0">
                  <span className="block text-sm font-medium text-sidebar-foreground truncate">{user || 'User'}</span>
                  <span className="block text-[0.7rem] uppercase tracking-[0.18em] text-sidebar-foreground/45">Session</span>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="text-sidebar-foreground/60 hover:text-red-400"
                onClick={handleLogout}
                title="Logout"
              >
                <IconLogout className="h-5 w-5" />
              </Button>
            </div>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* Top Header Bar - Desktop */}
        <header className="hidden lg:flex h-14 border-b border-sidebar-border/60 bg-background/80 backdrop-blur items-center justify-between px-6">
          <div className="flex items-center gap-3">
            {/* Breadcrumb or page title can go here */}
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="outline" className="text-xs text-muted-foreground border-border/70">
              {APP_VERSION}
            </Badge>
            <Link to="/settings">
              <Button
                variant="outline"
                size="icon"
                className="h-8 w-8 border-border/80 text-muted-foreground hover:text-foreground hover:bg-muted/60"
                title="Settings"
              >
                <IconSettings className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </header>

        {/* Mobile header */}
        <header className="h-16 border-b border-sidebar-border/70 bg-sidebar/95 flex items-center justify-between px-4 lg:hidden">
          <div className="flex items-center">
            <Button
              variant="ghost"
              size="icon"
              className="text-sidebar-foreground/60 hover:text-sidebar-foreground"
              onClick={() => setSidebarOpen(true)}
            >
              <IconMenu2 className="h-5 w-5" />
            </Button>
            <div className="ml-3 flex items-center gap-2">
              <img
                src={LOGO_URL}
                alt="DragonCP Logo"
                className="h-7 w-7 object-contain"
              />
              <span className="text-lg font-bold tracking-tight">
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#6a00fd] to-[#fe00fc]">
                  DRAGON-CP
                </span>
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs text-sidebar-foreground/60 border-sidebar-border/70">
              {APP_VERSION}
            </Badge>
            <Link to="/settings">
              <Button
                variant="ghost"
                size="icon-sm"
                className="text-sidebar-foreground/60 hover:text-sidebar-foreground"
                title="Settings"
              >
                <IconSettings className="h-5 w-5" />
              </Button>
            </Link>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <div className="container mx-auto p-6">
            {children}
          </div>
        </main>
      </div>

      <BackendUnavailableOverlay
        isVisible={backendUnavailable}
        errorMessage={backendErrorMessage}
        isRetrying={retryingBackend || sshStatusQuery.isFetching}
        onRetry={retryBackendConnection}
      />
    </div>
  );
}
