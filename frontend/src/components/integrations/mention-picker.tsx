import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { ConnectorMention } from "@/hooks/useConnectors";

/** The picker's stand-in for "whoever the webhook pings". Never sent. */
const INHERIT = "__webhook__";

/**
 * Choose who a message pings, from the mention list.
 *
 * With `inheritLabel` the first choice is "whoever the webhook pings", held as
 * `null`; choosing it clears everyone else, and choosing someone clears it.
 * An empty list is nobody.
 */
export function MentionPicker({
  mentions,
  value,
  onChange,
  inheritLabel,
  disabled,
  className,
  ariaLabel,
}: {
  mentions: ConnectorMention[];
  value: string[] | null;
  onChange: (next: string[] | null) => void;
  inheritLabel?: string;
  disabled?: boolean;
  className?: string;
  ariaLabel: string;
}) {
  const selected = value === null ? [INHERIT] : value;
  const byId = new Map(mentions.map((mention) => [mention.mention_id, mention]));
  const items = [
    ...(inheritLabel ? [{ value: INHERIT, label: inheritLabel }] : []),
    ...mentions.map((mention) => ({ value: mention.mention_id, label: mention.label })),
  ];

  const summary =
    value === null
      ? (inheritLabel ?? "Nobody")
      : value.length === 0
        ? "Nobody"
        : value
            .map((id) => byId.get(id))
            .filter((mention): mention is ConnectorMention => Boolean(mention))
            .map((mention) => mention.label)
            .join(", ") || "Nobody";

  return (
    <Select
      multiple
      items={items}
      value={selected}
      onValueChange={(next) => {
        const list = (next as string[]) ?? [];
        const added = list.filter((id) => !selected.includes(id));
        if (added.includes(INHERIT)) {
          onChange(null);
          return;
        }
        onChange(list.filter((id) => id !== INHERIT));
      }}
    >
      <SelectTrigger
        className={cn("min-w-0", className)}
        disabled={disabled}
        aria-label={ariaLabel}
      >
        <SelectValue className="truncate">{() => summary}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
