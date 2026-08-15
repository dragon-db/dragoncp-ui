import { useState, type CSSProperties, type ReactNode } from "react";
import { useRuntimeStatus } from "@/hooks/useConfig";
import { useRuntimeStore } from "@/stores/runtime";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { UpdateBanner } from "@/components/layout/update-banner";
import { TestModeBanner } from "@/components/layout/test-mode-banner";
import { AppNavbar } from "@/components/layout/app-navbar";
import { MobileNav } from "@/components/layout/mobile-nav";
import { BackendUnavailableOverlay } from "@/components/layout/backend-unavailable-overlay";
import { useLocation } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

interface AppLayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const [retryingBackend, setRetryingBackend] = useState(false);
  const backendReachable = useRuntimeStore((state) => state.backendReachable);
  const backendError = useRuntimeStore((state) => state.backendError);
  const runtimeStatusQuery = useRuntimeStatus();

  const backendUnavailable = runtimeStatusQuery.isError || !backendReachable;
  const backendErrorMessage =
    (runtimeStatusQuery.error instanceof Error ? runtimeStatusQuery.error.message : null) ??
    backendError;

  const retryBackendConnection = async () => {
    try {
      setRetryingBackend(true);
      await runtimeStatusQuery.refetch();
    } finally {
      setRetryingBackend(false);
    }
  };

  const location = useLocation();

  // Explore is a three-pane console with its own status bar: it fills the inset
  // card edge to edge instead of sitting in the usual page padding.
  const fullBleed = location.pathname.startsWith("/media/");

  return (
    <SidebarProvider
      className="h-svh overflow-hidden app-ambient"
      style={{ "--sidebar-width": "14.125rem" } as CSSProperties}
    >
      <AppSidebar />

      <SidebarInset className="min-w-0 border border-border shadow-[0_24px_60px_-30px_rgba(0,0,0,0.85)]">
        <AppNavbar />
        {/* Above the content, not floating over it: a tab running an older
            release is a standing condition until reloaded, not a passing
            notification that can be missed. */}
        <UpdateBanner />
        {/* Above everything and never dismissible: with test mode on, every
            success message in the interface is a rehearsal, so this has to be
            on screen at the moment somebody reads one. */}
        <TestModeBanner />
        {/* The scroll container is the padded wrapper rather than <main>, and it
            is a flex column — so a page that wants to fill the viewport (Explore
            pins a status bar to the bottom) can do it with flex-1, while normal
            pages stack and scroll exactly as before. */}
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div
            className={cn(
              "flex min-h-0 w-full flex-1 flex-col",
              fullBleed
                ? "overflow-hidden"
                : "mx-auto max-w-[1920px] overflow-auto p-4 sm:p-6 xl:px-8 xl:py-7"
            )}
          >
            {children}
          </div>
        </main>
        <MobileNav />
      </SidebarInset>

      <BackendUnavailableOverlay
        isVisible={backendUnavailable}
        errorMessage={backendErrorMessage}
        isRetrying={retryingBackend || runtimeStatusQuery.isFetching}
        onRetry={retryBackendConnection}
      />
    </SidebarProvider>
  );
}
