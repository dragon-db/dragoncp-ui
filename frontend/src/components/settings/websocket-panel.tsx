import { useState, type ReactNode } from "react";
import {
  IconBolt,
  IconChevronRight,
  IconPlugConnected,
  IconPlugConnectedX,
  IconRefresh,
  IconWifiOff,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/layout/section-card";
import { StatTiles } from "@/components/layout/stat-tiles";
import { useWebSocketStatus, type LiveConnection } from "@/hooks/useConfig";
import { useRuntimeController } from "@/hooks/useRuntime";
import { useSocketDiagnostics, type SocketEventKind } from "@/stores/socket-diagnostics";
import type { ConnectionState } from "@/stores/runtime";
import { cn } from "@/lib/utils";
import { NumberSetting, SettingList, SettingRow, ToneIcon } from "./settings-bits";
import {
  TAP_SM,
  TONE_CHIP,
  TONE_TEXT,
  useSaveSetting,
  useSettingMap,
  type Tone,
} from "./settings-model";

/**
 * WebSocket diagnostics: who is getting live updates, over what, and for how
 * much longer.
 *
 * The tiles answer "how many are alive" without reading anything. The card
 * below lists every session the server holds, this browser's first: its row
 * carries the controls and the drops and retries only the browser sees, so
 * nothing about this browser is shown twice.
 *
 * Everything here reads one query that the header's live pill already polls,
 * so the card adds no requests of its own.
 */

function span(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

function ago(seconds: number): string {
  return seconds < 10 ? "just now" : `${span(seconds)} ago`;
}

/** Seconds from a row, falling back to the minutes an older backend sends. */
function seconds(row: LiveConnection) {
  const timeout = row.idle_limit_seconds ?? row.timeout_seconds ?? row.timeout_minutes * 60;
  const idle = row.idle_seconds ?? row.last_activity_minutes_ago * 60;
  return {
    connected: row.connected_seconds ?? row.connected_minutes_ago * 60,
    idle,
    timeout,
    left: Math.max(0, timeout - idle),
  };
}

function transportName(transport?: string | null): string {
  if (transport === "websocket") return "WebSocket";
  if (transport === "polling") return "Long-polling";
  return "Unknown";
}

/** The first eight characters, which is all the server hands out. */
function shortId(id?: string | null) {
  return (id ?? "").replace(/\.+$/, "").slice(0, 8);
}

function clock(at: number) {
  return new Date(at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function Chip({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-1.5 py-px text-[11px] font-medium",
        TONE_CHIP[tone]
      )}
    >
      {children}
    </span>
  );
}

function TransportChip({ transport }: { transport?: string | null }) {
  if (!transport || transport === "unknown") return null;
  return <Chip tone={transport === "polling" ? "warn" : "muted"}>{transportName(transport)}</Chip>;
}

/** This browser's row while it has no live session: what happened, and what to press. */
function offlineState(state: ConnectionState, error: string | null) {
  switch (state) {
    case "connecting":
      return {
        icon: IconPlugConnected,
        tone: "muted" as const,
        title: "Connecting",
        detail: "Opening a live connection.",
      };
    case "auto-disconnected":
      return {
        icon: IconPlugConnectedX,
        tone: "warn" as const,
        title: "Paused after going unused",
        detail: "Pages refresh by polling until you reconnect.",
      };
    case "disconnected":
      return {
        icon: IconWifiOff,
        tone: "crit" as const,
        title: "Live connection lost",
        detail: error ? `Error: ${error}` : "Pages refresh by polling until you reconnect.",
      };
    default:
      return {
        icon: IconBolt,
        tone: "muted" as const,
        title: "Live updates are off",
        detail: "Pages refresh by polling instead.",
      };
  }
}

export function LiveConnectionTiles() {
  const status = useWebSocketStatus().data?.websocket_status;
  const reconnects = useSocketDiagnostics((state) => state.reconnects);
  const rows = status?.connection_details ?? [];
  const total = status?.active_connections ?? rows.length;
  const onWebSocket = rows.filter((row) => row.transport === "websocket").length;

  return (
    <StatTiles
      // Three tiles: on a phone the third takes the whole second row.
      className="lg:grid-cols-3 max-lg:[&>:last-child]:col-span-2"
      items={[
        {
          label: "Live sessions",
          value: status ? total : "…",
          unit: total === 1 ? "browser" : "browsers",
          tone: total > 0 ? "ok" : "default",
        },
        {
          label: "On WebSocket",
          value: status ? onWebSocket : "…",
          unit: total ? `of ${total}` : "no sessions",
          tone: total > 0 && onWebSocket < total ? "warn" : "default",
        },
        {
          label: "Reconnects here",
          value: reconnects,
          unit: "since this page loaded",
        },
      ]}
    />
  );
}

/** How long a session has before it is closed for going unused, as a shrinking bar. */
function IdleMeter({ left, timeout }: { left: number; timeout: number }) {
  const share = timeout > 0 ? left / timeout : 0;
  const fill = share > 0.5 ? "bg-emerald-400" : share > 0.15 ? "bg-amber-400" : "bg-rose-400";
  const text = left > 0 ? `Closes in ${span(left)}` : "Closing";
  return (
    <div className="w-full shrink-0 sm:w-40">
      <div className="mb-1 text-[12px] text-muted-foreground tabular-nums sm:text-right">
        {text}
      </div>
      <div
        role="meter"
        aria-label="Time left before it closes for going unused"
        aria-valuemin={0}
        aria-valuemax={timeout}
        aria-valuenow={left}
        aria-valuetext={text}
        className="h-1.5 overflow-hidden rounded-full bg-white/8"
      >
        <div
          className={cn("h-full rounded-full", fill)}
          style={{ width: `${Math.round(share * 100)}%` }}
        />
      </div>
    </div>
  );
}

/** One line of the list: icon, who it is, and whatever sits on the right. */
function Row({
  icon,
  heading,
  detail,
  aside,
  children,
}: {
  icon: ReactNode;
  heading: ReactNode;
  detail: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="px-4 py-3">
      <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:gap-6">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          {icon}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">{heading}</div>
            <p className="mt-0.5 text-[12.5px] text-muted-foreground">{detail}</p>
          </div>
        </div>
        {aside}
      </div>
      {children}
    </div>
  );
}

function usage(row: LiveConnection) {
  const time = seconds(row);
  return `${row.username ? `${row.username} · ` : ""}connected ${span(time.connected)} · used ${ago(time.idle)}`;
}

function SessionRow({ row }: { row: LiveConnection }) {
  const time = seconds(row);
  return (
    <Row
      icon={<ToneIcon icon={IconPlugConnected} tone="ok" />}
      heading={
        <>
          <span className="font-mono text-[13px] text-foreground">{shortId(row.session_id)}</span>
          <TransportChip transport={row.transport} />
        </>
      }
      detail={usage(row)}
      aside={<IdleMeter left={time.left} timeout={time.timeout} />}
    />
  );
}

const EVENT_DOT: Record<SocketEventKind, string> = {
  connected: "bg-emerald-400",
  upgraded: "bg-emerald-400",
  dropped: "bg-amber-400",
  error: "bg-rose-400",
  retrying: "bg-muted-foreground",
};

/**
 * Drops, retries and upgrades this browser went through. The server never sees
 * them, so they live here, folded to the latest one until asked for.
 */
function ConnectionLog() {
  const events = useSocketDiagnostics((state) => state.events);
  const [open, setOpen] = useState(false);
  if (events.length === 0) return null;
  const latest = events[0];

  return (
    <div className="mt-2 sm:pl-11">
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={open}
        aria-controls="connection-log"
        onClick={() => setOpen((value) => !value)}
        className={cn("-ml-2.5 max-w-full justify-start font-normal text-muted-foreground", TAP_SM)}
      >
        <IconChevronRight className={cn("transition-transform", open && "rotate-90")} />
        <span className="shrink-0">Since this page loaded</span>
        {!open && (
          <span className="min-w-0 truncate">
            · {clock(latest.at)} {latest.text}
          </span>
        )}
      </Button>
      {open && (
        <ol id="connection-log" className="mt-1.5 space-y-1.5">
          {events.map((event, index) => (
            <li key={`${event.at}-${index}`} className="flex items-baseline gap-2.5 text-[12.5px]">
              <span className="font-mono text-[11.5px] text-muted-foreground tabular-nums">
                {clock(event.at)}
              </span>
              <span
                className={cn(
                  "size-1.5 shrink-0 translate-y-[-1px] rounded-full",
                  EVENT_DOT[event.kind]
                )}
              />
              <span className="min-w-0 text-foreground/90">{event.text}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/**
 * This browser, always first. Live: its own session row (from the server once
 * it lists it) with Keep open and Turn off. Otherwise: why it has no session,
 * and Turn on or Reconnect.
 */
function ThisBrowserRow({ row }: { row?: LiveConnection }) {
  const runtime = useRuntimeController();
  const { transport, socketId, connectedAt } = useSocketDiagnostics();
  const chip = <Chip tone="brand">This browser</Chip>;

  if (runtime.socketConnected) {
    const time = row ? seconds(row) : null;
    return (
      <Row
        icon={<ToneIcon icon={IconPlugConnected} tone="brand" />}
        heading={
          <>
            <span className="font-mono text-[13px] text-foreground">{shortId(socketId)}</span>
            {chip}
            <TransportChip transport={transport ?? row?.transport} />
          </>
        }
        detail={row ? usage(row) : connectedAt ? `Connected at ${clock(connectedAt)}` : "Connected"}
        aside={
          <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:gap-4">
            {time && <IdleMeter left={time.left} timeout={time.timeout} />}
            <div className="flex shrink-0 gap-2">
              <Button
                size="sm"
                variant="outline"
                className={TAP_SM}
                onClick={runtime.extendSession}
              >
                <IconRefresh className="size-4" />
                Keep open
              </Button>
              <Button
                size="sm"
                variant="outline"
                className={TAP_SM}
                onClick={runtime.disableRealtime}
              >
                <IconPlugConnectedX className="size-4" />
                Turn off
              </Button>
            </div>
          </div>
        }
      >
        <ConnectionLog />
      </Row>
    );
  }

  const state = offlineState(runtime.connectionState, runtime.socketError);
  return (
    <Row
      icon={<ToneIcon icon={state.icon} tone={state.tone} />}
      heading={
        <>
          <span className="text-[13px] font-medium text-foreground">{state.title}</span>
          {chip}
        </>
      }
      detail={state.detail}
      aside={
        runtime.realtimeRequested ? (
          <Button size="sm" className={TAP_SM} onClick={runtime.reconnectRealtime}>
            <IconRefresh className="size-4" />
            Reconnect
          </Button>
        ) : (
          <Button size="sm" className={TAP_SM} onClick={runtime.enableRealtime}>
            <IconBolt className="size-4" />
            Turn on
          </Button>
        )
      }
    >
      <ConnectionLog />
    </Row>
  );
}

/** A server fact in one line: name on the left, answer on the right. */
function ServerFact({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-2">
      <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "text-right text-[12.5px] font-medium",
          tone ? TONE_TEXT[tone] : "text-foreground/90"
        )}
      >
        {value}
      </dd>
    </div>
  );
}

export function SessionsCard() {
  const query = useWebSocketStatus();
  const status = query.data?.websocket_status;
  const rows = status?.connection_details ?? [];
  const runtime = useRuntimeController();
  const socketId = useSocketDiagnostics((state) => state.socketId);
  const { map } = useSettingMap();
  const { save, saving } = useSaveSetting();
  const timeout = map.get("WEBSOCKET_TIMEOUT_MINUTES");
  const server = status?.runtime;
  const ready = server?.websocket_transport_ready;

  const mine =
    runtime.socketConnected && socketId
      ? rows.find((row) => shortId(row.session_id) === shortId(socketId))
      : undefined;
  const others = rows.filter((row) => row !== mine);

  return (
    <SectionCard
      label="WebSocket sessions"
      description="Every browser getting live updates, this one first. Refreshes every 5 seconds."
    >
      {ready === false && (
        <p className="mx-4 mt-3 rounded-lg border border-amber-500/30 bg-amber-500/8 p-3 text-[12.5px] text-amber-100">
          WebSocket support is missing on this server, so every session uses long-polling. Install{" "}
          <span className="font-mono">simple-websocket</span> in the virtual environment and restart
          DragonCP.
        </p>
      )}

      <SettingList>
        <ThisBrowserRow row={mine} />
        {query.isError ? (
          <p className="px-4 py-4 text-[13px] text-rose-300">
            Could not read the other sessions. Reload once the backend answers.
          </p>
        ) : query.isLoading ? (
          <p className="px-4 py-4 text-[13px] text-muted-foreground">Reading live sessions…</p>
        ) : (
          others.map((row) => <SessionRow key={row.session_id} row={row} />)
        )}
      </SettingList>

      <div className="border-t border-border/70">
        <SettingList>
          <SettingRow
            label="Close unused sessions after"
            htmlFor="realtime-timeout"
            description="A session counts as used when someone clicks or types on a page. Applies to sessions opened from now on."
          >
            <NumberSetting
              id="realtime-timeout"
              value={timeout?.value as number | undefined}
              unit="minutes"
              min={timeout?.minimum}
              max={timeout?.maximum}
              disabled={!timeout || saving}
              onSave={(next) =>
                save(
                  "WEBSOCKET_TIMEOUT_MINUTES",
                  next,
                  `Unused sessions close after ${next} minutes`
                )
              }
            />
          </SettingRow>
        </SettingList>
      </div>

      {server && (
        <dl className="grid border-t border-border/70 py-1.5 sm:grid-cols-2">
          <ServerFact
            label="WebSocket support"
            value={ready === false ? "Missing, polling only" : "Installed"}
            tone={ready === false ? "warn" : "ok"}
          />
          <ServerFact
            label="Idle check"
            value={
              status?.cleanup_thread_running === false ? "Stopped, nothing gets closed" : "Running"
            }
            tone={status?.cleanup_thread_running === false ? "crit" : undefined}
          />
          {server.ping_interval_seconds !== undefined && (
            <ServerFact
              label="Heartbeat"
              value={`Every ${server.ping_interval_seconds} s, dropped after ${server.ping_timeout_seconds ?? "?"} s silent`}
            />
          )}
          {server.verbose_logging !== undefined && (
            <ServerFact
              label="Socket logging"
              value={server.verbose_logging ? "Detailed, every heartbeat" : "Normal"}
            />
          )}
        </dl>
      )}
    </SectionCard>
  );
}
