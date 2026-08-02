import {
  IconArchive,
  IconFileFilled,
  IconPin,
  IconPinFilled,
  IconRestore,
  IconTrash,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatBytes, formatWhen } from "@/lib/explore-format";
import { REASON_LABELS, type Capture, type CurrentOccupant } from "@/lib/backup-types";
import { SectionEmpty } from "@/components/layout/section-card";

/**
 * One slot's version history.
 *
 * The library's current copy sits at the top, marked as current rather than
 * listed among the versions — it is what a restore would replace, not
 * something you can restore. Everything under it is a previous occupant,
 * newest first.
 */

/** The quality tag media servers put in the filename, when there is one. */
function qualityTag(name: string): string | null {
  const match = name.match(/\[([^\]]*(?:1080|2160|720|480|Bluray|WEBDL|WEBRip|HDTV)[^\]]*)\]/i);
  return match ? match[1] : null;
}

function FileRow({ name, size, muted }: { name: string; size: number; muted?: boolean }) {
  const tag = qualityTag(name);
  return (
    <div className="flex min-w-0 items-center gap-2 text-[12px]">
      <IconFileFilled
        className={cn("size-3 flex-none", muted ? "text-muted-foreground/50" : "text-brand/70")}
      />
      <span className="min-w-0 flex-1 truncate" title={name}>
        {name}
      </span>
      {tag && (
        <span className="flex-none rounded bg-muted/60 px-1.5 py-px font-mono text-[9.5px] text-muted-foreground">
          {tag}
        </span>
      )}
      <span className="flex-none font-mono text-[10.5px] text-muted-foreground tabular-nums">
        {formatBytes(size)}
      </span>
    </div>
  );
}

export function CurrentRow({ current }: { current: CurrentOccupant | null }) {
  if (!current) {
    return (
      <div className="border-b border-border/70 bg-muted/20 px-4 py-3">
        <div className="mb-1 font-mono text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
          In the library now
        </div>
        <p className="text-[12.5px] text-muted-foreground">
          Nothing — restoring a version here puts the episode back rather than replacing anything.
        </p>
      </div>
    );
  }

  return (
    <div className="border-b border-border/70 bg-emerald-500/[0.06] px-4 py-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="font-mono text-[10px] tracking-[0.12em] text-emerald-400 uppercase">
          In the library now
        </span>
      </div>
      <FileRow name={current.name} size={current.size} />
    </div>
  );
}

export function VersionRow({
  capture,
  index,
  busy,
  selected,
  onToggle,
  onRestore,
  onPin,
  onDelete,
}: {
  capture: Capture;
  index: number;
  busy: boolean;
  selected: boolean;
  onToggle: (capture: Capture) => void;
  onRestore: (capture: Capture) => void;
  onPin: (capture: Capture) => void;
  onDelete: (capture: Capture) => void;
}) {
  const media = (capture.files ?? []).filter((file) => file.is_media);
  const sidecars = (capture.files ?? []).filter((file) => !file.is_media);
  const reason = REASON_LABELS[capture.reason ?? ""] ?? "Displaced by a transfer";

  return (
    <div className="border-b border-border/60 px-4 py-3 last:border-b-0">
      <div className="mb-2 flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <Checkbox
          checked={selected}
          onCheckedChange={() => onToggle(capture)}
          aria-label={`Select version ${index + 1} for deletion`}
        />
        <span className="rounded bg-muted/70 px-1.5 py-px font-mono text-[9.5px] font-semibold text-muted-foreground">
          v{index + 1}
        </span>
        <span className="text-[12px] text-muted-foreground">{formatWhen(capture.captured_at)}</span>
        <span className="text-[11.5px] text-muted-foreground/70">· {reason}</span>
        {capture.pinned === 1 && (
          <span className="inline-flex items-center gap-1 rounded-full border border-brand/40 bg-brand/12 px-2 py-px text-[9.5px] font-bold tracking-[0.05em] text-brand-foreground uppercase">
            <IconPinFilled className="size-2.5" />
            Pinned
          </span>
        )}
        {capture.status === "restored" && (
          <span className="rounded-full border border-emerald-500/35 bg-emerald-500/12 px-2 py-px text-[9.5px] font-bold tracking-[0.05em] text-emerald-300 uppercase">
            Restored
          </span>
        )}

        <div className="ml-auto flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11.5px]"
            disabled={busy}
            onClick={() => onPin(capture)}
            aria-label={capture.pinned ? "Unpin this version" : "Pin this version"}
          >
            {capture.pinned ? (
              <IconPinFilled className="size-3.5" />
            ) : (
              <IconPin className="size-3.5" />
            )}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11.5px] text-rose-300 hover:text-rose-200"
            disabled={busy}
            onClick={() => onDelete(capture)}
            aria-label="Delete this version"
          >
            <IconTrash className="size-3.5" />
          </Button>
          <Button
            size="sm"
            className="h-7 px-2.5 text-[11.5px]"
            disabled={busy}
            onClick={() => onRestore(capture)}
          >
            <IconRestore className="size-3.5" />
            Restore
          </Button>
        </div>
      </div>

      <div className="space-y-1 pl-1">
        {media.map((file) => (
          <FileRow key={file.relative_path} name={file.relative_path} size={file.file_size} />
        ))}
        {sidecars.map((file) => (
          <FileRow key={file.relative_path} name={file.relative_path} size={file.file_size} muted />
        ))}
      </div>
    </div>
  );
}

export function VersionList({
  captures,
  current,
  loading,
  busyId,
  selected,
  onToggle,
  onRestore,
  onPin,
  onDelete,
}: {
  captures: Capture[];
  current: CurrentOccupant | null;
  loading: boolean;
  busyId: string | null;
  selected: Set<string>;
  onToggle: (capture: Capture) => void;
  onRestore: (capture: Capture) => void;
  onPin: (capture: Capture) => void;
  onDelete: (capture: Capture) => void;
}) {
  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (!captures.length) {
    return (
      <SectionEmpty
        icon={IconArchive}
        title="No versions stored"
        hint="Nothing has replaced this file yet."
      />
    );
  }

  return (
    <div>
      <CurrentRow current={current} />
      {captures.map((capture, index) => (
        <VersionRow
          key={capture.capture_id}
          capture={capture}
          index={index}
          busy={busyId === capture.capture_id}
          selected={selected.has(capture.capture_id)}
          onToggle={onToggle}
          onRestore={onRestore}
          onPin={onPin}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
