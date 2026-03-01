import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import {
    IconFolder,
    IconDeviceSdCard,
    IconCloud,
} from '@tabler/icons-react';

export interface DiskInfo {
    name: string;
    usagePercent: number;
    paths: { type: 'folder' | 'device'; label: string }[];
    usedSize: string;
    freeSize: string;
    totalSize: string;
}

interface DiskWidgetProps {
    disk: DiskInfo;
    variant?: 'local' | 'remote';
    className?: string;
}

function getProgressColor(percent: number): string {
    if (percent <= 50) return 'bg-green-500';
    if (percent <= 80) return 'bg-yellow-500';
    return 'bg-orange-500';
}

function getBadgeColor(percent: number): string {
    if (percent <= 50) return 'bg-green-500/20 text-green-400 border-green-500/30';
    if (percent <= 80) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
    return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
}

function FormattedSize({ value }: { value: string }) {
    const match = value.match(/^([\d.]+)\s*([A-Za-z]+)$/);
    if (!match) return <span className="text-white font-medium">{value}</span>;

    const [, vid, unit] = match;
    let displayUnit = unit;

    // Normalize units
    if (unit === 'G') displayUnit = 'GB';
    if (unit === 'T') displayUnit = 'TB';

    return (
        <span className="font-medium text-white">
            {vid} <span className="text-neutral-500 font-normal text-[10px] ml-0.5">{displayUnit}</span>
        </span>
    );
}

export function DiskWidget({ disk, variant = 'local', className }: DiskWidgetProps) {
    const Icon = variant === 'remote' ? IconCloud : IconDeviceSdCard;

    return (
        <div className={cn(
            "bg-neutral-900 rounded-xl p-4 border border-neutral-800 hover:border-neutral-700 transition-colors",
            className
        )}>
            {/* Header */}
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <Icon className={cn(
                        "h-4 w-4",
                        variant === 'remote' ? 'text-orange-400' : 'text-blue-400'
                    )} />
                    <span className="text-sm font-medium text-white">{disk.name}</span>
                </div>
                <Badge
                    variant="outline"
                    className={cn("text-xs font-mono", getBadgeColor(disk.usagePercent))}
                >
                    {disk.usagePercent}%
                </Badge>
            </div>

            {/* Progress Bar */}
            <div className="h-1.5 bg-neutral-800 rounded-full overflow-hidden mb-4">
                <div
                    className={cn("h-full rounded-full transition-all duration-500", getProgressColor(disk.usagePercent))}
                    style={{ width: `${disk.usagePercent}%` }}
                />
            </div>

            {/* Paths */}
            <div className="space-y-1.5 mb-4">
                {disk.paths.map((path, idx) => (
                    <div key={idx} className="flex items-center gap-2 text-xs text-neutral-400">
                        {path.type === 'folder' ? (
                            <IconFolder className="h-3.5 w-3.5 text-neutral-500" />
                        ) : (
                            <IconDeviceSdCard className="h-3.5 w-3.5 text-neutral-500" />
                        )}
                        <span className="truncate">{path.label}</span>
                    </div>
                ))}
            </div>

            {/* Storage Stats */}
            <div className="grid grid-cols-2 gap-y-2 text-xs mt-auto">
                <div className="space-y-1">
                    <span className="text-neutral-500 block">Used</span>
                    <div className="flex items-center gap-1.5">
                        <span className={cn(
                            "w-1.5 h-1.5 rounded-full",
                            getProgressColor(disk.usagePercent)
                        )} />
                        {/* Use FormattedSize component here */}
                        <FormattedSize value={disk.usedSize} />
                    </div>
                </div>

                <div className="space-y-1 text-right">
                    <span className="text-neutral-500 block">Free</span>
                    <div className="flex items-center justify-end gap-1.5">
                        {/* Use FormattedSize component here */}
                        <FormattedSize value={disk.freeSize} />
                    </div>
                </div>

                <div className="col-span-2 pt-2 border-t border-neutral-800/50 flex justify-between items-center">
                    <span className="text-neutral-500">Total Capacity</span>
                    {/* Use FormattedSize component here */}
                    <FormattedSize value={disk.totalSize} />
                </div>
            </div>
        </div>
    );
}
