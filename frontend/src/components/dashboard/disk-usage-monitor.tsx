import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useLocalDiskUsage, useRemoteDiskUsage } from '@/hooks/useConfig';
import type { DiskUsage, RemoteStorageInfo } from '@/hooks/useConfig';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { DiskWidget } from './disk-widget';
import type { DiskInfo } from './disk-widget';
import {
    IconRefresh,
    IconChevronDown,
    IconChevronUp,
    IconServer,
} from '@tabler/icons-react';

function formatDiskInfo(disk: DiskUsage, index: number): DiskInfo {
    const paths: DiskInfo['paths'] = [];

    if (disk.path) {
        paths.push({ type: 'folder', label: disk.path });
    }
    if (disk.filesystem) {
        paths.push({ type: 'device', label: disk.filesystem });
    }
    if (disk.mount_point && disk.mount_point !== disk.path) {
        paths.push({ type: 'folder', label: disk.mount_point });
    }

    return {
        name: `Local Disk ${index + 1}`,
        usagePercent: disk.usage_percent || 0,
        paths,
        usedSize: disk.used_size || '0 GB',
        freeSize: disk.available_size || '0 GB',
        totalSize: disk.total_size || '0 GB',
    };
}

function formatRemoteInfo(storage: RemoteStorageInfo): DiskInfo {
    return {
        name: 'Remote Storage',
        usagePercent: Math.round(storage.usage_percent || 0),
        paths: [],
        usedSize: storage.used_display || '0 GB',
        freeSize: storage.free_display || '0 GB',
        totalSize: storage.total_display || '0 GB',
    };
}

export function DiskUsageMonitor() {
    const [isCollapsed, setIsCollapsed] = useState(false);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const queryClient = useQueryClient();

    const { data: localDisk, isLoading: localLoading } = useLocalDiskUsage();
    const { data: remoteDisk, isLoading: remoteLoading } = useRemoteDiskUsage();

    const lastUpdated = new Date().toLocaleString('en-IN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
    });

    const handleRefresh = async () => {
        setIsRefreshing(true);
        await Promise.all([
            queryClient.invalidateQueries({ queryKey: ['disk', 'local'] }),
            queryClient.invalidateQueries({ queryKey: ['disk', 'remote'] }),
        ]);
        // Small delay for visual feedback
        setTimeout(() => setIsRefreshing(false), 500);
    };

    const localDisks: DiskInfo[] = localDisk?.disk_info
        ?.filter(d => d.available)
        .map((disk, idx) => formatDiskInfo(disk, idx)) || [];

    const remoteStorage: DiskInfo | null = remoteDisk?.storage_info?.available
        ? formatRemoteInfo(remoteDisk.storage_info)
        : null;

    const isLoading = localLoading || remoteLoading;

    return (
        <div className="space-y-4">
            {/* Header */}
            <div className="bg-gradient-to-r from-purple-600/90 to-fuchsia-600/90 rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3">
                    <button
                        onClick={() => setIsCollapsed(!isCollapsed)}
                        className="flex items-center gap-2 text-white hover:text-white/90 transition-colors"
                    >
                        <IconServer className="h-5 w-5" />
                        <span className="font-semibold">Disk Usage Monitor</span>
                        {isCollapsed ? (
                            <IconChevronDown className="h-4 w-4" />
                        ) : (
                            <IconChevronUp className="h-4 w-4" />
                        )}
                    </button>
                    <Button
                        variant="ghost"
                        size="icon"
                        className="text-white/80 hover:text-white hover:bg-white/10"
                        onClick={handleRefresh}
                        disabled={isRefreshing}
                    >
                        <IconRefresh className={cn("h-5 w-5", isRefreshing && "animate-spin")} />
                    </Button>
                </div>
            </div>

            {/* Content */}
            {!isCollapsed && (
                <div className="space-y-4">
                    {/* Disk Widgets Grid */}
                    {isLoading ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                            {[1, 2, 3, 4].map((i) => (
                                <Skeleton key={i} className="h-48 rounded-xl" />
                            ))}
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                            {/* Local Disks */}
                            {localDisks.map((disk, idx) => (
                                <DiskWidget key={idx} disk={disk} variant="local" />
                            ))}

                            {/* Remote Storage */}
                            {remoteStorage && (
                                <DiskWidget disk={remoteStorage} variant="remote" />
                            )}

                            {/* Empty state */}
                            {localDisks.length === 0 && !remoteStorage && (
                                <div className="col-span-full text-center py-8 text-neutral-500">
                                    No disk information available
                                </div>
                            )}
                        </div>
                    )}

                    {/* Last Updated */}
                    <div className="text-center text-xs text-neutral-500 flex items-center justify-center gap-2">
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-neutral-600" />
                        Last updated: {lastUpdated}
                    </div>
                </div>
            )}
        </div>
    );
}
