import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { diffFilenames, isSeparatorToken, type DiffToken } from "@/lib/rename-diff";

/**
 * Old name over new name, with only the changed tokens tinted. The `−` / `+`
 * gutter carries the same information as the colour, so the diff still reads
 * without it.
 */

const TOKEN_CLASS: Record<DiffToken["kind"], string> = {
  same: "",
  removed: "rounded-[3px] bg-rose-500/15 px-0.5 text-rose-300 line-through decoration-rose-400/40",
  added: "rounded-[3px] bg-emerald-500/15 px-0.5 text-emerald-300",
};

function Tokens({ tokens }: { tokens: DiffToken[] }) {
  return (
    <span className="min-w-0 break-all">
      {tokens.map((token, index) => (
        <span
          key={`${index}-${token.text}`}
          // Punctuation shifts whenever a word changes; tinting it would speckle
          // the line with edits nobody made.
          className={TOKEN_CLASS[isSeparatorToken(token.text) ? "same" : token.kind]}
        >
          {token.text}
        </span>
      ))}
    </span>
  );
}

export function FilenameDiff({
  before,
  after,
  className,
}: {
  before?: string;
  after?: string;
  className?: string;
}) {
  const diff = useMemo(() => diffFilenames(before ?? "", after ?? ""), [before, after]);

  if (diff.unchanged) {
    return (
      <div
        className={cn(
          "rounded-md border border-border bg-background/60 px-2.5 py-1.5 font-mono text-[11px] break-all text-foreground/75",
          className
        )}
      >
        {before}
        <span className="ml-2 text-muted-foreground">(name unchanged)</span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "overflow-hidden rounded-md border border-border bg-background/60 font-mono text-[11px]",
        className
      )}
    >
      <div className="flex gap-2 border-b border-border/70 px-2.5 py-1.5">
        <span className="shrink-0 text-rose-400/80 select-none">−</span>
        {before ? (
          <Tokens tokens={diff.before} />
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </div>
      <div className="flex gap-2 px-2.5 py-1.5">
        <span className="shrink-0 text-emerald-400/80 select-none">+</span>
        {after ? <Tokens tokens={diff.after} /> : <span className="text-muted-foreground">—</span>}
      </div>
    </div>
  );
}
