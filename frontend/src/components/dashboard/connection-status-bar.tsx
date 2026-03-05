import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
    IconRefresh,
    IconChevronUp,
    IconPlugConnectedX,
    IconClock,
    IconBolt,
} from '@tabler/icons-react';
import type { ConnectionState } from '@/stores/runtime';

interface ConnectionStatusBarProps {
    connectionState: ConnectionState;
    statusMessage: string;
    timeRemainingMinutes?: number;
    activeSocketConnections?: number;
    onReconnect: () => void;
    onDisconnect?: () => void;
    onExtendSession?: () => void;
    onRefreshWsStatus?: () => void;
    isReconnecting?: boolean;
    onCollapseAll?: () => void;
}

export function ConnectionStatusBar({
    connectionState,
    statusMessage,
    timeRemainingMinutes = 0,
    activeSocketConnections,
    onReconnect,
    onDisconnect,
    onExtendSession,
    onRefreshWsStatus,
    isReconnecting = false,
    onCollapseAll,
}: ConnectionStatusBarProps) {
    const connected = connectionState === 'connected';
    const connecting = connectionState === 'connecting';
    const autoDisconnected = connectionState === 'auto-disconnected';
    const configChanged = connectionState === 'config-changed';

    return (
        <div className="rounded-xl border border-fuchsia-500/20 bg-gradient-to-r from-neutral-900 via-neutral-900 to-neutral-900/70 p-4 shadow-[0_14px_35px_-30px_rgba(217,70,239,0.85)] flex items-center justify-between">
            {/* Connection Status */}
            <div className="flex items-center gap-3">
                <span
                    className={cn(
                        "w-2.5 h-2.5 rounded-full",
                        connected && "bg-green-500 animate-pulse",
                        connecting && "bg-blue-500 animate-pulse",
                        autoDisconnected && "bg-amber-500",
                        configChanged && "bg-yellow-500",
                        !connected && !connecting && !autoDisconnected && !configChanged && "bg-red-500"
                    )}
                />
                <div className="text-sm text-neutral-300 space-y-0.5">
                    <div>{statusMessage}</div>
                    <div className="text-xs text-neutral-500 flex items-center gap-3">
                        <span className="inline-flex items-center gap-1">
                            <IconClock className="h-3.5 w-3.5" />
                            {connected ? `${timeRemainingMinutes} min left` : 'Realtime offline'}
                        </span>
                        {typeof activeSocketConnections === 'number' && (
                            <button
                                type="button"
                                onClick={onRefreshWsStatus}
                                className="text-neutral-400 hover:text-neutral-200"
                            >
                                WebSocket: {activeSocketConnections}
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2">
                {onCollapseAll && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="h-8 border-neutral-700 text-neutral-400 hover:text-white hover:bg-neutral-800 gap-1.5"
                        onClick={onCollapseAll}
                    >
                        <IconChevronUp className="h-4 w-4" />
                        Collapse All
                    </Button>
                )}
                {connected && onExtendSession && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="h-8 border-neutral-700 text-neutral-300 hover:text-white hover:bg-neutral-800 gap-1.5"
                        onClick={onExtendSession}
                    >
                        <IconBolt className="h-4 w-4" />
                        Extend
                    </Button>
                )}
                <Button
                    variant="default"
                    size="sm"
                    className="h-8 gap-1.5 shadow-sm shadow-fuchsia-950/40"
                    onClick={onReconnect}
                    disabled={isReconnecting}
                >
                    <IconRefresh className={cn("h-4 w-4", isReconnecting && "animate-spin")} />
                    {configChanged ? 'Apply Settings' : 'Reconnect'}
                </Button>
                {onDisconnect && connected && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="h-8 border-neutral-700 text-neutral-300 hover:text-red-300 hover:bg-neutral-800 gap-1.5"
                        onClick={onDisconnect}
                    >
                        <IconPlugConnectedX className="h-4 w-4" />
                        Disconnect
                    </Button>
                )}
            </div>
        </div>
    );
}
