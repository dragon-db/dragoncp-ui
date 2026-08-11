import { useState } from "react";
import { IconArrowNarrowDown, IconCheck, IconCopy } from "@tabler/icons-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

/**
 * Paths, as the subject rather than the small print.
 *
 * This feature is about two locations — a media library and a backup disk —
 * and the thing an operator actually reasons about before restoring or
 * deleting is a path. Showing a friendly label instead ("Show · S01E02") asks
 * them to confirm an irreversible action against a name that could match three
 * files on disk.
 *
 * So paths are shown in full. The design work is making a 120-character path
 * readable rather than a monospace smear:
 *
 *   * the directory is dimmed and the filename carries full weight, so the eye
 *     lands on the file without losing where it lives,
 *   * lines wrap at separators instead of clipping, because a tooltip is no
 *     answer on a phone and nobody hovers a line they do not already suspect,
 *   * one tap copies it, because the next thing done with a path is paste it.
 */

function copyPath(value: string, onDone: () => void) {
  // Absent over plain http on a LAN address, which is how this app is often reached.
  if (!navigator.clipboard) {
    toast.error("Copying needs a secure connection");
    return;
  }
  navigator.clipboard
    .writeText(value)
    .then(() => {
      onDone();
      toast.success("Path copied");
    })
    .catch(() => toast.error("Copy failed"));
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() =>
        copyPath(value, () => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        })
      }
      aria-label="Copy the full path"
      className="mt-px flex-none rounded p-0.5 text-muted-foreground/60 transition-colors hover:bg-muted/60 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      {copied ? (
        <IconCheck className="size-3.5 text-emerald-400" />
      ) : (
        <IconCopy className="size-3.5" />
      )}
    </button>
  );
}

/** Everything up to the last separator, and everything after it. */
function splitPath(path: string): { dir: string; name: string } {
  const cut = path.lastIndexOf("/");
  if (cut < 0) return { dir: "", name: path };
  return { dir: path.slice(0, cut + 1), name: path.slice(cut + 1) };
}

/**
 * One path, in full, with the filename picked out of its directory.
 *
 * `break-all` rather than `truncate`: a media path is one long token with no
 * spaces, so the browser will not wrap it unaided and the row would overflow
 * its card. `whitespace-pre-wrap` keeps spaces in a filename visible instead of
 * collapsing them, which is how a stray double space gives itself away.
 */
export function FullPath({
  value,
  label,
  meta,
  tone = "default",
  className,
  copyable = true,
}: {
  value: string | null | undefined;
  /** The eyebrow above it — "In the library now", "Backup copy". */
  label?: string;
  /** A quiet line under the path: size, age, whatever the row is answering. */
  meta?: string;
  tone?: "default" | "danger" | "ok";
  className?: string;
  copyable?: boolean;
}) {
  if (!value) return null;
  const { dir, name } = splitPath(value);

  const nameTone =
    tone === "danger" ? "text-rose-200" : tone === "ok" ? "text-emerald-200" : "text-foreground";

  return (
    <div className={cn("min-w-0", className)}>
      {label && (
        <div className="mb-1 font-mono text-[9.5px] tracking-[0.14em] text-muted-foreground uppercase">
          {label}
        </div>
      )}
      <div className="flex min-w-0 items-start gap-1.5">
        <code className="min-w-0 flex-1 font-mono text-[11.5px] leading-[1.5] break-all whitespace-pre-wrap">
          {dir && <span className="text-muted-foreground/70">{dir}</span>}
          <span className={cn("font-semibold", nameTone)}>{name}</span>
        </code>
        {copyable && <CopyButton value={value} />}
      </div>
      {meta && <div className="mt-0.5 text-[11px] text-muted-foreground">{meta}</div>}
    </div>
  );
}

/**
 * Two paths as one statement: what is being written, and what it displaces.
 *
 * A restore is a swap *inside one directory* — almost always the same folder,
 * with only the filename differing. Printing both paths in full buries that one
 * difference in a hundred identical characters, so where the directories match
 * the shared prefix is printed once, dimmed, and only the two filenames are
 * aligned beneath it. The thing that changes is the thing you read.
 *
 * Where the directories genuinely differ — a restore into a folder that has
 * since been reorganised — the fold would hide the very fact worth noticing, so
 * both paths are shown in full instead.
 */
export function PathSwap({
  incoming,
  incomingLabel = "Putting back",
  incomingMeta,
  outgoing,
  outgoingLabel = "Over the file now there",
  outgoingMeta,
  emptyNote = "Nothing to replace — this file will be re-added",
  className,
}: {
  incoming: string;
  incomingLabel?: string;
  incomingMeta?: string;
  /** The file being displaced, or null when the slot is empty. */
  outgoing: string | null;
  outgoingLabel?: string;
  outgoingMeta?: string;
  emptyNote?: string;
  className?: string;
}) {
  const from = splitPath(incoming);
  const to = outgoing ? splitPath(outgoing) : null;
  const shared = to !== null && from.dir === to.dir && from.dir !== "";

  if (!outgoing) {
    return (
      <div className={cn("min-w-0", className)}>
        <FullPath label={incomingLabel} value={incoming} meta={incomingMeta} tone="ok" />
        <p className="mt-1.5 text-[11.5px] text-muted-foreground">{emptyNote}</p>
      </div>
    );
  }

  if (!shared) {
    return (
      <div className={cn("min-w-0 space-y-2.5", className)}>
        <FullPath label={incomingLabel} value={incoming} meta={incomingMeta} tone="ok" />
        <FullPath label={outgoingLabel} value={outgoing} meta={outgoingMeta} tone="danger" />
      </div>
    );
  }

  return (
    <div className={cn("min-w-0", className)}>
      <div className="mb-1 flex items-start gap-1.5">
        <code className="min-w-0 flex-1 font-mono text-[11px] leading-[1.5] break-all whitespace-pre-wrap text-muted-foreground/70">
          {from.dir}
        </code>
        <CopyButton value={incoming} />
      </div>

      <div className="space-y-1.5 border-l border-border/70 pl-2.5">
        <div className="min-w-0">
          <div className="font-mono text-[9.5px] tracking-[0.14em] text-emerald-400/90 uppercase">
            {incomingLabel}
          </div>
          <code className="font-mono text-[11.5px] leading-[1.5] font-semibold break-all whitespace-pre-wrap text-emerald-200">
            {from.name}
          </code>
          {incomingMeta && <div className="text-[11px] text-muted-foreground">{incomingMeta}</div>}
        </div>

        <div className="flex items-center gap-1.5 text-muted-foreground/60">
          <IconArrowNarrowDown className="size-3.5 flex-none" />
          <span className="font-mono text-[9.5px] tracking-[0.14em] uppercase">writes over</span>
        </div>

        <div className="min-w-0">
          <div className="font-mono text-[9.5px] tracking-[0.14em] text-rose-400/90 uppercase">
            {outgoingLabel}
          </div>
          <code className="font-mono text-[11.5px] leading-[1.5] font-semibold break-all whitespace-pre-wrap text-rose-200">
            {to!.name}
          </code>
          {outgoingMeta && <div className="text-[11px] text-muted-foreground">{outgoingMeta}</div>}
        </div>
      </div>
    </div>
  );
}

/** A filename on its own, in full — what an operator recognises and reads first. */
export function FullName({
  value,
  className,
  muted,
}: {
  value: string;
  className?: string;
  muted?: boolean;
}) {
  return (
    <span
      className={cn(
        "min-w-0 text-[12.5px] leading-snug font-medium break-all",
        muted ? "text-muted-foreground" : "text-foreground",
        className
      )}
    >
      {value}
    </span>
  );
}
