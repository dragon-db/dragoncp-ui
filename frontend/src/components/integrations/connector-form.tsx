import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SectionCard } from "@/components/layout/section-card";
import { errorText } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import {
  REDACTED,
  useCheckConnector,
  useSaveConnector,
  type CheckResult,
  type Connector,
  type ConnectorField,
  type ConnectorGroup,
} from "@/hooks/useConnectors";
import { IconCheck, IconPlugConnected } from "@tabler/icons-react";

/**
 * A connector's settings form, rendered from what the server says it needs.
 *
 * Nothing here is per-connector. Sonarr, Radarr and Jellyfin all get a working
 * page from this component alone, and so would anything added later — which is
 * the difference between a connector framework and four hand-built pages.
 *
 * A stored secret is shown as the redaction placeholder. Sending it back
 * unchanged means "leave it alone", so a form round-trips without the value
 * ever reaching the browser.
 */
/** The server stores every setting as text; a switch has to read it back. */
function isTruthy(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

/** The form as saved: every setting, with a stored secret as the placeholder. */
function savedValues(connector: Connector): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of connector.config_fields) {
    values[field.name] = field.secret
      ? connector.secrets_set[field.name]
        ? REDACTED
        : ""
      : connector.config[field.name] || (field.kind === "choice" ? (field.default ?? "") : "");
  }
  return values;
}

function differs(a: Record<string, string>, b: Record<string, string>, names: string[]) {
  return names.some((name) => (a[name] ?? "") !== (b[name] ?? ""));
}

export function ConnectorForm({ connector }: { connector: Connector }) {
  const save = useSaveConnector(connector.id);
  const check = useCheckConnector(connector.id);

  const [saved, setSaved] = useState<Record<string, string>>(() => savedValues(connector));
  const [draft, setDraft] = useState<Record<string, string>>(() => savedValues(connector));
  // The last Test, and the form values it tested. It is shown only while the
  // form still holds those values — after an edit it describes nothing here.
  const [tested, setTested] = useState<{
    result: CheckResult;
    values: Record<string, string>;
  } | null>(null);
  const savedRef = useRef(saved);
  const editedSinceFocus = useRef(new Set<string>());

  /* eslint-disable react-hooks/set-state-in-effect -- server payload seeds a controlled form */
  useEffect(() => {
    // Anything else on the page that saves — the On/Off switch — reloads the
    // connector. A field someone has typed in keeps what they typed; only an
    // untouched one follows the saved value.
    const before = savedRef.current;
    const next = savedValues(connector);
    savedRef.current = next;
    setSaved(next);
    setDraft((current) => {
      const merged: Record<string, string> = {};
      for (const name of Object.keys(next)) {
        const edited = name in current && (current[name] ?? "") !== (before[name] ?? "");
        merged[name] = edited ? current[name] : next[name];
      }
      return merged;
    });
  }, [connector]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const names = connector.config_fields.map((field) => field.name);
  // What a test reads: the address and the key. The auto-scanner switch
  // changes nothing about whether the service answers.
  const connectionNames = connector.config_fields
    .filter((field) => field.required || field.secret)
    .map((field) => field.name);
  const unsaved = differs(draft, saved, names);
  const fresh = tested && !differs(tested.values, draft, connectionNames) ? tested.result : null;

  const missingRequired = connector.config_fields
    .filter((field) => field.required)
    .filter((field) => !(draft[field.name] ?? "").trim())
    .map((field) => field.label);

  const runCheck = async (values: Record<string, string>, config?: Record<string, string>) => {
    try {
      const result = await check.mutateAsync(config ? { config } : undefined);
      setTested({ result, values });
    } catch (error) {
      toast.error(errorText(error, "Could not reach the service"));
    }
  };

  const onSave = async () => {
    const connectionChanged = differs(draft, saved, connectionNames);
    let next = draft;
    try {
      const response = await save.mutateAsync({ config: draft });
      if (response.connector) next = savedValues(response.connector);
      savedRef.current = next;
      setSaved(next);
      setDraft(next);
      toast.success(`${connector.display_name} settings saved`);
    } catch (error) {
      toast.error(errorText(error, "Could not save the settings"));
      return;
    }
    // Saving a new address or key forgets the old connection's check, so test
    // what was just saved and the badge describes it again.
    if (connectionChanged && connector.supports_check && missingRequired.length === 0) {
      await runCheck(next);
    }
  };

  const onCheck = () => runCheck(draft, draft);

  if (connector.config_fields.length === 0) {
    return null;
  }

  const setValue = (name: string, value: string) =>
    setDraft((previous) => ({ ...previous, [name]: value }));
  const groups = groupFields(connector);
  const columns = groups.length;
  // With three groups and two columns, the longest takes the right column
  // and the other two stack on the left, so neither side is left half empty.
  const tallest = groups.reduce(
    (best, entry, index) => (entry.fields.length > groups[best].fields.length ? index : best),
    0
  );

  return (
    <SectionCard
      label={connector.settings_label}
      description={connector.settings_description}
      contentClassName="p-0"
    >
      {/*
        One column of a dozen fields left most of a wide screen empty, so the
        groups an adapter declares sit side by side once there is room for
        them: Connection, Auto-scanner, Renames. A connector with no groups
        keeps the single narrow column, which suits a short form.
      */}
      <div
        className={cn(
          "grid gap-x-8 gap-y-8 p-4",
          columns === 1 && "sm:max-w-xl",
          columns === 2 && "lg:grid-cols-2",
          // Three columns only where each is wide enough for its sentences.
          columns >= 3 && "lg:grid-cols-2 2xl:grid-cols-3"
        )}
      >
        {groups.map(({ group, fields }, index) => {
          const headingId = `${connector.id}-group-${group.id || index}`;
          return (
            <div
              key={group.id || index}
              role="group"
              aria-labelledby={group.label ? headingId : undefined}
              className={cn(
                "min-w-0",
                // A rule between columns, only while they sit side by side.
                index > 0 && columns === 2 && "lg:border-l lg:border-border/60 lg:pl-8",
                columns >= 3 &&
                  index === tallest &&
                  cn(
                    "lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:border-l lg:border-border/60 lg:pl-8",
                    "2xl:col-start-auto 2xl:row-span-1 2xl:row-start-auto",
                    index === 0 && "2xl:border-l-0 2xl:pl-0"
                  ),
                columns >= 3 &&
                  index > 0 &&
                  index !== tallest &&
                  "2xl:border-l 2xl:border-border/60 2xl:pl-8"
              )}
            >
              {group.label && (
                <div className="mb-4">
                  <h3 id={headingId} className="text-[13.5px] font-semibold text-foreground">
                    {group.label}
                  </h3>
                  {group.description && (
                    <p className="mt-0.5 text-xs text-muted-foreground">{group.description}</p>
                  )}
                </div>
              )}
              <div className="grid gap-y-5">
                {fields.map((field) => {
                  const idle = Boolean(field.depends_on) && !isTruthy(draft[field.depends_on!]);
                  return (
                    <div
                      key={field.name}
                      className={cn("transition-opacity", idle && "opacity-55")}
                    >
                      <FieldControl
                        connectorId={connector.id}
                        field={field}
                        value={draft[field.name] ?? ""}
                        secretStored={Boolean(connector.secrets_set[field.name])}
                        editedSinceFocus={editedSinceFocus}
                        onChange={(value) => setValue(field.name, value)}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <footer className="flex flex-col gap-3 border-t border-border/70 px-4 py-3 lg:flex-row lg:items-center">
        <div className="min-w-0 lg:flex-1">
          {/* The last Test while the form still holds what it tested;
              otherwise the saved connection's last check. */}
          {connector.supports_check && fresh ? (
            <CheckNote ok={fresh.ok} message={fresh.message}>
              {fresh.unsaved
                ? fresh.ok
                  ? "— not saved yet. Press Save to keep it."
                  : "— tested the unsaved values in the form."
                : "— tested just now"}
            </CheckNote>
          ) : (
            connector.supports_check &&
            connector.last_check_at && (
              <CheckNote
                ok={Boolean(connector.last_check_ok)}
                message={connector.last_check_message}
              >
                — last checked {new Date(connector.last_check_at + "Z").toLocaleString()}
              </CheckNote>
            )
          )}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center lg:flex-none">
          {unsaved && <span className="text-xs font-medium text-amber-400">Unsaved changes</span>}
          {missingRequired.length > 0 && connector.supports_check && (
            <span className="text-xs text-muted-foreground">
              Fill in {missingRequired.join(" and ")} to test.
            </span>
          )}
          {/* Only where there is something to reach. Discord is configured
              per webhook, so a connector-level test here would pass no matter
              what was typed. */}
          {connector.supports_check && (
            <Button
              variant="outline"
              className="w-full sm:w-auto"
              onClick={onCheck}
              disabled={check.isPending || missingRequired.length > 0}
              title={
                missingRequired.length > 0
                  ? `Fill in ${missingRequired.join(" and ")} to test`
                  : "Tests what is in the form, saved or not. Saves nothing."
              }
            >
              <IconPlugConnected className="mr-2 h-4 w-4" />
              {check.isPending ? "Checking…" : "Test connection"}
            </Button>
          )}
          <Button className="w-full sm:w-auto" onClick={onSave} disabled={save.isPending}>
            <IconCheck className="mr-2 h-4 w-4" />
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </footer>
    </SectionCard>
  );
}

/** The adapter's groups, each with its fields, in the adapter's order. */
function groupFields(connector: Connector): Array<{
  group: ConnectorGroup;
  fields: ConnectorField[];
}> {
  const declared = connector.config_groups ?? [];
  if (declared.length === 0) {
    return [{ group: { id: "", label: "", description: "" }, fields: connector.config_fields }];
  }
  const known = new Set(declared.map((group) => group.id));
  return declared
    .map((group, index) => ({
      group,
      // A field naming no group, or one the adapter forgot to declare, joins
      // the first rather than disappearing from the form.
      fields: connector.config_fields.filter((field) =>
        field.group && known.has(field.group) ? field.group === group.id : index === 0
      ),
    }))
    .filter(({ fields }) => fields.length > 0);
}

/**
 * One field, drawn as what the adapter says it is. `boolean` and `number`
 * were declared on the contract from the start and only ever drawn as text
 * boxes, so a switch arrived as the word "true" in an input and an interval
 * as a string somebody could type "soon" into. A `choice` is a dropdown of
 * the values the server accepts.
 */
function FieldControl({
  connectorId,
  field,
  value,
  secretStored,
  editedSinceFocus,
  onChange,
}: {
  connectorId: string;
  field: ConnectorField;
  value: string;
  secretStored: boolean;
  /** Fields typed in since they took focus; read only in the handlers. */
  editedSinceFocus: RefObject<Set<string>>;
  onChange: (value: string) => void;
}) {
  const inputId = `${connectorId}-${field.name}`;
  const description = field.description && (
    <p className="text-xs leading-relaxed text-muted-foreground">{field.description}</p>
  );

  if (field.kind === "boolean") {
    return (
      <Row inputId={inputId} label={field.label} description={description}>
        <Switch
          id={inputId}
          checked={isTruthy(value)}
          onCheckedChange={(next) => onChange(next ? "true" : "false")}
        />
      </Row>
    );
  }

  if (field.kind === "number") {
    // A number is two or three digits: a small box beside its label, the way
    // a switch sits, so its description gets the whole width of the column.
    return (
      <Row inputId={inputId} label={field.label} description={description}>
        <Input
          id={inputId}
          type="number"
          inputMode="numeric"
          placeholder={field.placeholder}
          className="w-20 text-right tabular-nums"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </Row>
    );
  }

  if (field.kind === "choice") {
    const items = field.choices ?? [];
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={inputId}>{field.label}</Label>
        <Select
          items={items}
          value={value || field.default || ""}
          onValueChange={(next) => onChange(String(next ?? ""))}
        >
          <SelectTrigger id={inputId} className="w-full sm:w-56">
            <SelectValue />
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
        {description}
      </div>
    );
  }

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={inputId}>
        {field.label}
        {field.required && <span className="ml-1 text-destructive">*</span>}
      </Label>
      <Input
        id={inputId}
        type={field.secret ? "password" : "text"}
        placeholder={field.placeholder}
        value={value}
        onChange={(event) => {
          editedSinceFocus.current.add(field.name);
          onChange(event.target.value);
        }}
        onFocus={(event) => {
          // Clear the placeholder on focus rather than making someone
          // select-all over a value that is not really there.
          if (field.secret && event.target.value === REDACTED) {
            editedSinceFocus.current.delete(field.name);
            onChange("");
          }
        }}
        onBlur={(event) => {
          // Clicking through a stored key leaves it stored. Only typing and
          // then emptying the box means "remove it".
          if (
            field.secret &&
            secretStored &&
            event.target.value === "" &&
            !editedSinceFocus.current.has(field.name)
          ) {
            onChange(REDACTED);
          }
        }}
      />
      {description}
    </div>
  );
}

/** A label and its description on the left, a small control on the right. */
function Row({
  inputId,
  label,
  description,
  children,
}: {
  inputId: string;
  label: string;
  description: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <Label htmlFor={inputId}>{label}</Label>
        {description && <div className="mt-1">{description}</div>}
      </div>
      <div className="flex-none">{children}</div>
    </div>
  );
}

function CheckNote({
  ok,
  message,
  children,
}: {
  ok: boolean;
  message: string | null;
  children: ReactNode;
}) {
  return (
    // Sonarr's check reports its TMDB key on a line of its own.
    <div
      className={`inline-block max-w-full rounded-md border px-2.5 py-1.5 text-xs whitespace-pre-line ${
        ok
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
          : "border-destructive/30 bg-destructive/10 text-destructive"
      }`}
    >
      {message}
      <span className="ml-1 opacity-70">{children}</span>
    </div>
  );
}
