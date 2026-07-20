import { useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useRuntimeStatus } from "@/hooks/useConfig";
import { useRuntimeStore } from "@/stores/runtime";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { BackendUnavailableOverlay } from "@/components/layout/backend-unavailable-overlay";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { IconBolt, IconPlugConnected, IconSettings } from "@tabler/icons-react";

interface AppLayoutProps {
  children: ReactNode;
}

// App version - can be made configurable from env or API later
const APP_VERSION = "v2.1.4";

export function AppLayout({ children }: AppLayoutProps) {
  const [retryingBackend, setRetryingBackend] = useState(false);
  const backendReachable = useRuntimeStore((state) => state.backendReachable);
  const backendError = useRuntimeStore((state) => state.backendError);
  const realtimeRequested = useRuntimeStore((state) => state.realtimeRequested);
  const socketConnected = useRuntimeStore((state) => state.socketConnected);
  const liveActivityMessage = useRuntimeStore((state) => state.liveActivityMessage);
  const liveActivityType = useRuntimeStore((state) => state.liveActivityType);
  const liveActivityAt = useRuntimeStore((state) => state.liveActivityAt);
  const runtimeStatusQuery = useRuntimeStatus();

  const backendUnavailable = runtimeStatusQuery.isError || !backendReachable;
  const backendErrorMessage =
    (runtimeStatusQuery.error instanceof Error ? runtimeStatusQuery.error.message : null) ??
    backendError;

  const realtimeTitle = (() => {
    if (socketConnected) {
      return liveActivityMessage
        ? `Realtime active: ${liveActivityMessage}`
        : "Realtime active across all pages";
    }
    if (realtimeRequested) return "Realtime is connecting";
    return "Realtime is off. Enable it from the dashboard.";
  })();

  const liveActivityAgeLabel = liveActivityAt
    ? new Date(liveActivityAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;

  const retryBackendConnection = async () => {
    try {
      setRetryingBackend(true);
      await runtimeStatusQuery.refetch();
    } finally {
      setRetryingBackend(false);
    }
  };

  return (
    <SidebarProvider
      className="app-ambient"
      style={{ "--sidebar-width": "15rem" } as CSSProperties}
    >
      <AppSidebar />

      <SidebarInset className="border border-border shadow-[0_24px_60px_-30px_rgba(0,0,0,0.85)]">
        {/* Top bar */}
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4 md:px-6">
          <SidebarTrigger className="text-muted-foreground md:hidden" />

          <div className="ml-auto flex items-center gap-2.5">
            <div
              title={realtimeTitle}
              className={cn(
                "flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs transition-colors",
                socketConnected
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                  : realtimeRequested
                    ? "border-blue-500/35 bg-blue-500/10 text-blue-200"
                    : "border-border bg-card text-muted-foreground"
              )}
            >
              {socketConnected ? (
                <IconPlugConnected className="size-3.5" />
              ) : (
                <IconBolt className="size-3.5" />
              )}
              <span>
                {socketConnected
                  ? "Realtime On"
                  : realtimeRequested
                    ? "Realtime Starting"
                    : "Polling Mode"}
              </span>
              {socketConnected && liveActivityMessage && (
                <span className="max-w-56 truncate text-[11px] text-emerald-100/80">
                  {liveActivityType ? `${liveActivityType}: ` : ""}
                  {liveActivityMessage}
                  {liveActivityAgeLabel ? ` - ${liveActivityAgeLabel}` : ""}
                </span>
              )}
            </div>

            <Badge variant="outline" className="font-mono text-xs text-muted-foreground">
              {APP_VERSION}
            </Badge>

            <Link to="/settings">
              <Button
                variant="outline"
                size="icon"
                className="size-8 text-muted-foreground hover:text-foreground"
                title="Settings"
              >
                <IconSettings className="size-4" />
              </Button>
            </Link>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <div className="container mx-auto p-6">{children}</div>
        </main>
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
