import { cn } from "@/lib/utils";
import { useRuntimeController } from "@/hooks/useRuntime";
import { useWebSocketStatus } from "@/hooks/useConfig";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { IconBolt, IconRefresh, IconPlugConnectedX } from "@tabler/icons-react";
import type { ConnectionState } from "@/stores/runtime";

interface Display {
  label: string;
  dot: string;
  text: string;
  title: string;
}

function display(state: ConnectionState, requested: boolean, minutes: number): Display {
  if (state === "connected")
    return {
      label: "Realtime",
      dot: "bg-emerald-400 shadow-[0_0_8px_1px] shadow-emerald-400/60",
      text: "text-emerald-300",
      title: "Realtime active",
    };
  if (state === "connecting")
    return {
      label: "Starting",
      dot: "bg-blue-400 animate-pulse",
      text: "text-blue-300",
      title: "Connecting…",
    };
  if (state === "config-changed")
    return {
      label: "Update",
      dot: "bg-yellow-400",
      text: "text-yellow-300",
      title: "Settings changed",
    };
  if (state === "auto-disconnected")
    return {
      label: "Paused",
      dot: "bg-amber-400",
      text: "text-amber-300",
      title: "Realtime paused",
    };
  if (state === "disconnected")
    return {
      label: "Offline",
      dot: "bg-red-400",
      text: "text-red-300",
      title: "Realtime disconnected",
    };
  // idle / not requested → polling
  void requested;
  void minutes;
  return {
    label: "Polling",
    dot: "bg-muted-foreground",
    text: "text-muted-foreground",
    title: "Polling mode",
  };
}

function subtitle(state: ConnectionState, minutes: number, socketError?: string | null): string {
  switch (state) {
    case "connected":
      return `Session · ${minutes} min remaining`;
    case "connecting":
      return "Establishing a live session…";
    case "config-changed":
      return "Apply changes to refresh the live session.";
    case "auto-disconnected":
      return "The session idled out. Reconnect to resume.";
    case "disconnected":
      return socketError ? `Error: ${socketError}` : "Connection lost. Reconnect to resume.";
    default:
      return "Live updates are off. Enable realtime to stream changes across every page.";
  }
}

export function RealtimeStatus() {
  const runtime = useRuntimeController();
  const wsStatus = useWebSocketStatus();

  const d = display(runtime.connectionState, runtime.realtimeRequested, runtime.minutesRemaining);
  const activeConnections = wsStatus.data?.websocket_status.active_connections ?? 0;
  const connected = runtime.connectionState === "connected";
  const configChanged = runtime.connectionState === "config-changed";

  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={120}
        closeDelay={180}
        className={cn(
          "flex items-center gap-2 self-stretch rounded-l-full px-3 py-1.5 transition-colors outline-none",
          "hover:bg-white/[0.05] focus-visible:bg-white/[0.05] data-[popup-open]:bg-white/[0.05]"
        )}
      >
        <span className={cn("size-1.5 rounded-full", d.dot)} />
        <span className={d.text}>{d.label}</span>
      </PopoverTrigger>

      <PopoverContent align="start" sideOffset={10} className="w-80 gap-0 p-0 font-sans">
        {/* Header */}
        <div className="flex items-start gap-3 p-4">
          <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", d.dot)} />
          <div className="min-w-0">
            <div className="font-display text-sm font-semibold text-foreground">{d.title}</div>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              {subtitle(runtime.connectionState, runtime.minutesRemaining, runtime.socketError)}
            </p>
          </div>
        </div>

        <Separator />

        {/* Details */}
        <div className="grid grid-cols-2 gap-px bg-border">
          <div className="bg-popover px-4 py-2.5">
            <div className="text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
              Session
            </div>
            <div className="mt-0.5 font-mono text-sm text-foreground">
              {connected ? `${runtime.minutesRemaining} min` : "—"}
            </div>
          </div>
          <div className="bg-popover px-4 py-2.5">
            <div className="text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
              WebSocket
            </div>
            <div className="mt-0.5 font-mono text-sm text-foreground">{activeConnections}</div>
          </div>
        </div>

        <Separator />

        {/* Actions */}
        <div className="flex flex-col gap-2 p-3">
          {!runtime.realtimeRequested ? (
            <Button size="sm" className="w-full gap-1.5" onClick={runtime.enableRealtime}>
              <IconBolt className="size-4" />
              Enable realtime
            </Button>
          ) : connected ? (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                className="flex-1 gap-1.5"
                onClick={runtime.extendSession}
              >
                <IconBolt className="size-4" />
                Extend
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="flex-1 gap-1.5 text-muted-foreground hover:text-destructive"
                onClick={runtime.disableRealtime}
              >
                <IconPlugConnectedX className="size-4" />
                Disable
              </Button>
            </div>
          ) : (
            <Button size="sm" className="w-full gap-1.5" onClick={runtime.reconnectRealtime}>
              <IconRefresh className="size-4" />
              {configChanged ? "Apply settings" : "Reconnect"}
            </Button>
          )}
          <p className="px-0.5 text-[11px] text-muted-foreground/70">
            Realtime applies across every page.
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
