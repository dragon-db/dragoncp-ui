import { IconFlask } from "@tabler/icons-react";
import { useTestMode } from "@/hooks/useConfig";

/**
 * "This server is not writing anything to disk."
 *
 * Test mode changes what every action in the interface MEANS, and nothing said
 * so. A transfer reported "completed" and a restore reported "Restored 2
 * file(s)" while rsync ran with `--dry-run` and the restore skipped every
 * write — the only way to find out was to open the transfer's log and read it.
 *
 * That is the wrong way round. A success message that is not true is worse than
 * no message, because it is acted on: a restore that appears to have worked is
 * one nobody checks.
 *
 * Deliberately NOT dismissible, unlike the update banner. That one reports
 * something that will still be true tomorrow and can wait; this one is a
 * standing statement about whether anything you do is real, and it has to be
 * visible at the moment somebody reads a result, not whenever they last chose
 * to look.
 */
export function TestModeBanner() {
  const testMode = useTestMode();

  if (!testMode) return null;

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-amber-500/35 bg-amber-500/[0.08] px-4 py-2 sm:px-6"
    >
      <IconFlask aria-hidden="true" className="size-4 flex-none text-amber-400" />
      <p className="min-w-0 flex-1 text-[12.5px]">
        <span className="font-medium text-amber-200">Test mode</span>
        <span className="text-muted-foreground">
          {" "}
          — nothing is written to disk. Transfers and restores report success without
          moving any files.
        </span>
      </p>
    </div>
  );
}
