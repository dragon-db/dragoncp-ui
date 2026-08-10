import { useState } from "react";
import { IconCheck, IconCopy } from "@tabler/icons-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

/**
 * A path or filename, shown in full.
 *
 * Every action on this page happens to a specific file at a specific place on
 * disk, and an operator confirming one is entitled to see which. Truncating to
 * a hover tooltip fails that on a phone, where there is no hover, and fails it
 * on a desktop too — nobody hovers over a line they did not already suspect.
 *
 * So: the whole value, wrapped rather than clipped, broken at the separators so
 * a long path uses the lines it needs instead of one runaway row, and copyable
 * in one tap because the next thing an operator does with a path is paste it
 * into a terminal.
 */

function copyPath(value: string, onDone: () => void) {
  // Absent over plain http on a LAN address, which is how this app is often reached.
  if (!navigator.clipboard) {
    toast.error("Copy needs a secure connection");
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

export function FullPath({
  value,
  label,
  tone = "default",
  className,
  copyable = true,
}: {
  value: string | null | undefined;
  /** The eyebrow above it — "In the library", "On the backup disk". */
  label?: string;
  tone?: "default" | "muted" | "warning" | "danger";
  className?: string;
  copyable?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;

  const toneClass =
    tone === "warning"
      ? "text-amber-300"
      : tone === "danger"
        ? "text-rose-300"
        : tone === "muted"
          ? "text-muted-foreground"
          : "text-foreground/90";

  return (
    <div className={cn("min-w-0", className)}>
      {label && (
        <div className="mb-0.5 font-mono text-[9.5px] tracking-[0.12em] text-muted-foreground uppercase">
          {label}
        </div>
      )}
      <div className="flex min-w-0 items-start gap-1.5">
        {/*
          `break-all` rather than `truncate`: a media path is one long token with
          no spaces, so the browser will not wrap it on its own and the row
          would otherwise overflow its card. `whitespace-pre-wrap` keeps any
          spaces in a filename visible rather than collapsing them, which is how
          a trailing space in a name gives itself away.
        */}
        <code
          className={cn(
            "min-w-0 flex-1 font-mono text-[11.5px] leading-[1.45] break-all whitespace-pre-wrap",
            toneClass
          )}
        >
          {value}
        </code>
        {copyable && (
          <button
            type="button"
            onClick={() => {
              copyPath(value, () => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              });
            }}
            aria-label="Copy the full path"
            className="mt-px flex-none rounded p-0.5 text-muted-foreground/70 transition-colors hover:bg-muted/60 hover:text-foreground"
          >
            {copied ? (
              <IconCheck className="size-3.5 text-emerald-400" />
            ) : (
              <IconCopy className="size-3.5" />
            )}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * A filename on its own line, in full.
 *
 * Separate from FullPath because a name and a path want different emphasis:
 * the name is what an operator recognises and reads first, the path is the
 * supporting evidence underneath it.
 */
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
