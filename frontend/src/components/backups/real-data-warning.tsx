import { IconAlertOctagon } from "@tabler/icons-react";
import { Checkbox } from "@/components/ui/checkbox";

const SHARED_FOLDER =
  "Syncs, restores and repairs are only rehearsed here; this is not. It acts on the real backup folder — and when production uses the same folder, production loses them too.";

/**
 * Test mode's one gap, said at the moment it matters.
 *
 * Test mode rehearses syncs, restores and repairs, and an operator who sees it
 * switched on reasonably expects every button to be a rehearsal. This page's
 * deletions and moves are not: they act on the backup folder itself, and a
 * test instance set up to mirror production shares that folder with it. So the
 * confirmation says so in words, and the button stays off until the operator
 * has ticked that they read it — a second instance is exactly where a person
 * clicks through a dialog assuming nothing is real.
 */
export function RealDataWarning({
  consequence,
  detail = SHARED_FOLDER,
  acknowledgement,
  acknowledged,
  onAcknowledge,
}: {
  /** What pressing the button does, finishing "This WILL …": "delete real backups". */
  consequence: string;
  /** Why, and who else it reaches. The default is the deletion's. */
  detail?: string;
  /** The tick-box's words: "I understand these backups are deleted for real". */
  acknowledgement: string;
  acknowledged: boolean;
  onAcknowledge: (next: boolean) => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-rose-500/45 bg-rose-500/[0.09] px-3 py-2.5 text-[12.5px]"
    >
      <div className="flex items-start gap-2">
        <IconAlertOctagon className="mt-px size-4 flex-none text-rose-400" />
        <div>
          <div className="font-semibold text-rose-300">
            Test mode does not cover this. This WILL {consequence}.
          </div>
          <p className="mt-0.5 text-muted-foreground">{detail}</p>
        </div>
      </div>
      <label className="mt-2.5 flex cursor-pointer items-center gap-2 pl-6 font-medium">
        <Checkbox
          checked={acknowledged}
          onCheckedChange={(value) => onAcknowledge(Boolean(value))}
        />
        {acknowledgement}
      </label>
    </div>
  );
}
