import { useState, type CSSProperties, type ReactNode } from "react";
import { useRuntimeStatus } from "@/hooks/useConfig";
import { useRuntimeStore } from "@/stores/runtime";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { AppNavbar } from "@/components/layout/app-navbar";
import { BackendUnavailableOverlay } from "@/components/layout/backend-unavailable-overlay";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

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

  return (
    <SidebarProvider
      className="app-ambient"
      style={{ "--sidebar-width": "15rem" } as CSSProperties}
    >
      <AppSidebar />

      <SidebarInset className="border border-border shadow-[0_24px_60px_-30px_rgba(0,0,0,0.85)]">
        <AppNavbar />
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
