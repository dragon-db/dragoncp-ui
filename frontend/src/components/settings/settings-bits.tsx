import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import { toast } from "sonner";
import { IconFileText, IconLock } from "@tabler/icons-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { TONE_CHIP, type Tone } from "./settings-model";

/**
 * The pieces every Settings tab is built from.
 *
 * A setting is a row: what it is and what it does on the left, its value or
 * control on the right. A value nobody can change from here (it lives in the
 * environment file) reads as text, not as a greyed-out input; the section says
 * once where such values come from instead of every row repeating it.
 *
 * One save model for the whole page: a switch or a choice saves the moment it
 * changes, a number saves on Enter or when the field loses focus.
 */

/**
 * A coloured icon whose colour is a state, never decoration: green when healthy,
 * amber when it needs a look, rose when broken, brand when on, grey when off.
 */
export function ToneIcon({
  icon: Icon,
  tone,
  size = "md",
}: {
  icon: ComponentType<{ className?: string }>;
  tone: Tone;
  size?: "md" | "lg";
}) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-lg border",
        size === "lg" ? "size-11 rounded-xl" : "size-8",
        TONE_CHIP[tone]
      )}
    >
      <Icon className={size === "lg" ? "size-5" : "size-4"} />
    </span>
  );
}

/** Rows inside a section card, divided by the card's own hairline. */
export function SettingList({ children }: { children: ReactNode }) {
  return <div className="divide-y divide-border/70">{children}</div>;
}

export function SettingRow({
  label,
  description,
  icon,
  htmlFor,
  children,
  stack = false,
  inline = false,
}: {
  label: ReactNode;
  description?: ReactNode;
  /** A ToneIcon, when the row is about something with a state. */
  icon?: ReactNode;
  /** The id of the control, so clicking the label reaches it. */
  htmlFor?: string;
  children?: ReactNode;
  /** Value under the label at every width: long paths and lists. */
  stack?: boolean;
  /** Control beside the label at every width, phone included: a switch, a short value. */
  inline?: boolean;
}) {
  const Label = htmlFor ? "label" : "div";
  return (
    <div
      className={cn(
        "flex gap-3 px-4 py-3.5",
        stack
          ? "flex-col"
          : inline
            ? "flex-row items-start justify-between sm:items-center sm:gap-6"
            : "flex-col sm:flex-row sm:items-center sm:justify-between sm:gap-6"
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        {icon}
        <div className="min-w-0">
          <Label htmlFor={htmlFor} className="block text-[13.5px] font-medium text-foreground">
            {label}
          </Label>
          {description && (
            <p className="mt-0.5 max-w-prose text-[12.5px] text-pretty text-muted-foreground">
              {description}
            </p>
          )}
        </div>
      </div>
      {children !== undefined && (
        <div
          className={cn(
            "min-w-0",
            stack ? (icon ? "sm:pl-11" : "") : "flex shrink-0 items-center gap-2 sm:justify-end"
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

/**
 * Locked values that need no explaining, as a compact two-column list: the
 * name and the value, nothing else.
 */
export function FactGrid({ children }: { children: ReactNode }) {
  return <dl className="grid gap-x-6 px-4 py-2 sm:grid-cols-2">{children}</dl>;
}

export function Fact({
  label,
  value,
  hint,
}: {
  label: string;
  value: unknown;
  /** Shown under the value, for the one fact that needs a word of explanation. */
  hint?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5 py-2">
      <dt className="text-[12px] text-muted-foreground">{label}</dt>
      <dd className="min-w-0">
        <EnvValue value={value} />
        {hint && <p className="mt-0.5 text-[12px] text-muted-foreground">{hint}</p>}
      </dd>
    </div>
  );
}

/** A value read from the environment file: text, with a lock, and "Not set" when empty. */
export function EnvValue({ value, mono = true }: { value: unknown; mono?: boolean }) {
  const text = value === undefined || value === null ? "" : String(value);
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-1.5 text-[12.5px]">
      <IconLock className="size-3.5 shrink-0 text-muted-foreground/70" aria-hidden />
      {text ? (
        <span className={cn("min-w-0 break-all text-foreground/90", mono && "font-mono")}>
          {text}
        </span>
      ) : (
        <span className="text-muted-foreground italic">Not set</span>
      )}
    </span>
  );
}

/** Said once per section: where its locked values come from and how to change them. */
export function EnvNote({ children }: { children?: ReactNode }) {
  return (
    <p className="flex items-start gap-2 border-t border-border/70 px-4 py-2.5 text-[12px] text-muted-foreground">
      <IconFileText className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>
        {children ?? (
          <>
            Values with a lock come from <span className="font-mono">dragoncp_env.env</span> on the
            server. Change them there, then restart DragonCP.
          </>
        )}
      </span>
    </p>
  );
}

/**
 * A number that saves on Enter or when the field loses focus. Out of range is
 * said and not saved; the field goes back to what is stored.
 */
export function NumberSetting({
  id,
  value,
  unit,
  min,
  max,
  disabled,
  onSave,
}: {
  id: string;
  value: number | string | undefined;
  unit?: string;
  min?: number;
  max?: number;
  disabled?: boolean;
  onSave: (next: number) => Promise<boolean> | boolean;
}) {
  const stored = value === undefined || value === null ? "" : String(value);
  const [draft, setDraft] = useState(stored);

  // The stored value seeds the field again whenever it changes underneath it.
  useEffect(() => {
    setDraft(stored);
  }, [stored]);

  const commit = async () => {
    if (draft.trim() === stored) return;
    const next = Number(draft);
    if (!Number.isFinite(next) || draft.trim() === "") {
      toast.error("Enter a number");
      setDraft(stored);
      return;
    }
    if ((min !== undefined && next < min) || (max !== undefined && next > max)) {
      toast.error(`Use a number from ${min ?? "any"} to ${max ?? "any"}`);
      setDraft(stored);
      return;
    }
    const ok = await onSave(next);
    if (!ok) setDraft(stored);
  };

  return (
    <div className="flex items-center gap-2">
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") (event.target as HTMLInputElement).blur();
          if (event.key === "Escape") {
            setDraft(stored);
            (event.target as HTMLInputElement).blur();
          }
        }}
        className="h-11 w-24 font-mono tabular-nums sm:h-9"
      />
      {unit && <span className="text-[12.5px] text-muted-foreground">{unit}</span>}
    </div>
  );
}
