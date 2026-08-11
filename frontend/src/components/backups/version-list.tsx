import {
  IconArchive,
  IconInbox,
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
import { ActorBadge } from "@/components/activity/actor-badge";
import { FullPath } from "@/components/backups/full-path";

/**
 * One item's version history.
 *
 * Read top to bottom it answers three questions in order: what is in the
 * library right now, what could go back in its place, and what each of those
 * would cost. The library's copy is stated first and set apart, because it is
 * the thing every button below would overwrite — listing it among the versions
 * made the one file you cannot restore look like one you could.
 *
 * Versions are a sequence in time, so they are labelled by recency rather than
 * numbered: "Most recent" and then dates. `v1` for the newest read backwards to
 * everyone who saw it.
 */

/** The quality tag media servers put in the filename, when there is one. */
function qualityTag(name: string): string | null {
  const match = name.match(/\[([^\]]*(?:1080|2160|720|480|Bluray|WEBDL|WEBRip|HDTV)[^\]]*)\]/i);
  return match ? match[1] : null;
}

function QualityChip({ name }: { name: string }) {
  const tag = qualityTag(name);
  if (!tag) return null;
  return (
    <span className="flex-none rounded bg-black/30 px-1.5 py-px font-mono text-[9.5px] text-muted-foreground">
      {tag}
    </span>
  );
}

/**
 * What the library holds right now.
 *
 * Given its own block at the head of the panel rather than a row in the list:
 * it is the subject of the whole screen, and the full path is the one fact that
 * says exactly which file on disk a restore is about to displace.
 */
export function CurrentRow({ current }: { current: CurrentOccupant | null }) {
  if (!current) {
    return (
      <div className="border-b border-border px-4 py-3.5">
        <div className="mb-1.5 font-mono text-[9.5px] tracking-[0.14em] text-muted-foreground uppercase">
          In the library now
        </div>
        <div className="flex items-start gap-2 text-[12.5px] text-muted-foreground">
          <IconInbox className="mt-px size-4 flex-none" />
          <p className="text-pretty">
            Nothing. Restoring a version here puts the file back rather than replacing anything.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-border bg-emerald-500/[0.05] px-4 py-3.5">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[9.5px] tracking-[0.14em] text-emerald-400 uppercase">
          In the library now
        </span>
        <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">
          {formatBytes(current.size)}
        </span>
        <QualityChip name={current.name} />
      </div>
      <FullPath value={current.path} tone="ok" />
    </div>
  );
}

function VersionFile({
  name,
  fullPath,
  size,
  media,
}: {
  name: string;
  fullPath: string | null;
  size: number;
  media: boolean;
}) {
  return (
    <div className="min-w-0 rounded-md bg-black/20 px-2.5 py-2">
      <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          className={cn(
            "min-w-0 text-[12px] leading-snug font-medium break-all",
            media ? "text-foreground" : "text-muted-foreground"
          )}
        >
          {name}
        </span>
        <span className="flex-none font-mono text-[10.5px] text-muted-foreground tabular-nums">
          {formatBytes(size)}
        </span>
        {media && <QualityChip name={name} />}
      </div>
      {/* Where it lived before a sync moved it aside. The name alone cannot
          tell two libraries' copies of the same episode apart. */}
      <FullPath value={fullPath} label="Taken from" />
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
  const files = capture.files ?? [];
  const media = files.filter((file) => file.is_media);
  const sidecars = files.filter((file) => !file.is_media);
  const reason = REASON_LABELS[capture.reason ?? ""] ?? "Displaced by a sync";
  const newest = index === 0;

  return (
    <li
      className={cn(
        "border-b border-border/60 px-4 py-3.5 last:border-b-0",
        selected && "bg-brand/[0.06]"
      )}
    >
      <div className="flex items-start gap-2.5">
        {/*
          Base UI's checkbox forwards its click to a hidden input rendered as a
          SIBLING of the box, so nesting it inside another interactive element
          toggles the row straight back. It stays outside the buttons below.
        */}
        <Checkbox
          checked={selected}
          onCheckedChange={() => onToggle(capture)}
          aria-label={`Select the version kept ${formatWhen(capture.captured_at)} for deletion`}
          className="mt-0.5 flex-none"
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {newest ? (
              <span className="rounded bg-brand/15 px-1.5 py-px font-mono text-[9.5px] font-bold tracking-[0.05em] text-brand-foreground uppercase">
                Most recent
              </span>
            ) : (
              <span className="rounded bg-black/30 px-1.5 py-px font-mono text-[9.5px] font-bold tracking-[0.05em] text-muted-foreground uppercase">
                Older
              </span>
            )}
            <span className="text-[12.5px] font-medium">{formatWhen(capture.captured_at)}</span>
            <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">
              {formatBytes(capture.total_size)}
            </span>
            {capture.pinned === 1 && (
              <span className="inline-flex items-center gap-1 rounded-full border border-brand/40 bg-brand/15 px-2 py-px text-[9.5px] font-bold tracking-[0.05em] text-brand-foreground uppercase">
                <IconPinFilled className="size-2.5" />
                Pinned
              </span>
            )}
            {capture.restored_at && (
              <span className="rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-px text-[9.5px] font-bold tracking-[0.05em] text-emerald-300 uppercase">
                Restored
              </span>
            )}
            {capture.restored_at && capture.restored_by_name && (
              <ActorBadge
                kind={capture.restored_by_kind}
                name={capture.restored_by_name}
                size="sm"
              />
            )}
          </div>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">{reason}</p>
        </div>
      </div>

      <div className="mt-2.5 space-y-1.5 pl-7">
        {media.map((file) => (
          <VersionFile
            key={file.relative_path}
            name={file.relative_path}
            fullPath={file.original_path}
            size={file.file_size}
            media
          />
        ))}
        {sidecars.map((file) => (
          <VersionFile
            key={file.relative_path}
            name={file.relative_path}
            fullPath={file.original_path}
            size={file.file_size}
            media={false}
          />
        ))}
      </div>

      {/*
        Labelled, not icon-only. These three do very different things — one
        overwrites the library, one is permanent, one only sets a flag — and
        three unlabelled glyphs in a row asked the operator to remember which
        was which directly above a control with no undo.
      */}
      <div className="mt-3 flex flex-wrap items-center gap-2 pl-7">
        <Button size="sm" className="h-8" disabled={busy} onClick={() => onRestore(capture)}>
          <IconRestore className="size-4" />
          Restore this version
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-8"
          disabled={busy}
          onClick={() => onPin(capture)}
        >
          {capture.pinned ? <IconPinFilled className="size-4" /> : <IconPin className="size-4" />}
          {capture.pinned ? "Unpin" : "Pin"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto h-8 text-rose-300 hover:bg-rose-500/10 hover:text-rose-200"
          disabled={busy}
          onClick={() => onDelete(capture)}
        >
          <IconTrash className="size-4" />
          Delete
        </Button>
      </div>
    </li>
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
          <Skeleton key={row} className="h-24 w-full" />
        ))}
      </div>
    );
  }

  return (
    <div>
      <CurrentRow current={current} />

      {!captures.length ? (
        <SectionEmpty
          icon={IconArchive}
          title="No earlier versions kept"
          hint="A version appears here the first time a sync replaces this file."
        />
      ) : (
        <>
          <div className="flex items-center gap-2 border-b border-border/70 bg-muted/15 px-4 py-2">
            <span className="font-mono text-[9.5px] tracking-[0.14em] text-muted-foreground uppercase">
              Earlier versions
            </span>
            <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">
              {captures.length}
            </span>
            <span className="ml-auto text-[11px] text-muted-foreground">newest first</span>
          </div>
          <ul>
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
          </ul>
        </>
      )}
    </div>
  );
}
