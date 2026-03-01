import { IconPlugConnectedX, IconRefresh } from '@tabler/icons-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface BackendUnavailableOverlayProps {
  isVisible: boolean;
  isRetrying?: boolean;
  errorMessage?: string | null;
  onRetry: () => void;
}

export function BackendUnavailableOverlay({
  isVisible,
  isRetrying = false,
  errorMessage,
  onRetry,
}: BackendUnavailableOverlayProps) {
  if (!isVisible) return null;

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-background/78 p-6 backdrop-blur-md">
      <section className="relative w-full max-w-2xl overflow-hidden rounded-3xl border border-border/70 bg-card/95 shadow-[0_30px_80px_-52px_rgba(0,0,0,0.95)] ring-1 ring-black/20">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-primary/14 via-primary/6 to-transparent" />
        <div className="space-y-7 px-6 py-8 text-center sm:px-10 sm:py-10">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/35 bg-primary/12 text-primary">
            <IconPlugConnectedX className="h-6 w-6" />
          </div>

          <div className="space-y-2.5">
            <h2 className="text-2xl font-semibold text-foreground sm:text-[1.75rem]">Backend Connection Unavailable</h2>
            <p className="mx-auto max-w-xl text-sm leading-relaxed text-muted-foreground sm:text-[0.95rem]">
              Dragon-CP requires a live backend connection. All UI operations are disabled until connectivity is restored.
            </p>
          </div>

          {errorMessage && (
            <div className="mx-auto w-full max-w-xl rounded-xl border border-border/70 bg-background/55 px-4 py-3 text-left">
              <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground/90">
                Last Connection Error
              </p>
              <p className="mt-1.5 break-all font-mono text-xs text-foreground/90">{errorMessage}</p>
            </div>
          )}

          <div className="flex items-center justify-center">
            <Button
              size="lg"
              onClick={onRetry}
              disabled={isRetrying}
              className="min-w-44 rounded-xl px-6 shadow-[0_14px_28px_-20px_rgba(217,70,239,0.95)]"
              autoFocus
            >
              <IconRefresh className={cn('h-4 w-4', isRetrying && 'animate-spin')} />
              Retry Connection
            </Button>
          </div>

          <p className="text-xs text-muted-foreground/90">
            This screen will close automatically once backend connectivity is restored.
          </p>
        </div>
      </section>
    </div>
  );
}
