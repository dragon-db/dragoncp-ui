import { useEffect, useRef, useState, type ReactNode } from "react";
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
import {
  REDACTED,
  useCheckConnector,
  useSaveConnector,
  type CheckResult,
  type Connector,
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

  return (
    <SectionCard
      label={connector.settings_label}
      description={connector.settings_description}
      contentClassName="p-4"
    >
      <div className="grid gap-4 sm:max-w-xl">
        {/*
          The adapter says what kind each field is; this renders it. `boolean`
          and `number` were declared on the contract from the start and only
          ever drawn as text boxes, so a switch arrived as the word "true" in an
          input and a interval as a string somebody could type "soon" into. A
          `choice` is a dropdown of the values the server accepts.
        */}
        {connector.config_fields.map((field) => {
          const inputId = `${connector.id}-${field.name}`;

          if (field.kind === "boolean") {
            const on = isTruthy(draft[field.name]);
            return (
              <div key={field.name} className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <Label htmlFor={inputId}>{field.label}</Label>
                  {field.description && (
                    <p className="mt-0.5 text-xs text-muted-foreground">{field.description}</p>
                  )}
                </div>
                <Switch
                  id={inputId}
                  checked={on}
                  onCheckedChange={(next) =>
                    setDraft((previous) => ({ ...previous, [field.name]: next ? "true" : "false" }))
                  }
                />
              </div>
            );
          }

          if (field.kind === "choice") {
            const items = field.choices ?? [];
            return (
              <div key={field.name} className="grid gap-1.5">
                <Label htmlFor={inputId}>{field.label}</Label>
                <Select
                  items={items}
                  value={draft[field.name] || field.default || ""}
                  onValueChange={(value) =>
                    setDraft((previous) => ({ ...previous, [field.name]: String(value ?? "") }))
                  }
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
                {field.description && (
                  <p className="text-xs text-muted-foreground">{field.description}</p>
                )}
              </div>
            );
          }

          return (
            <div key={field.name} className="grid gap-1.5">
              <Label htmlFor={inputId}>
                {field.label}
                {field.required && <span className="ml-1 text-destructive">*</span>}
              </Label>
              <Input
                id={inputId}
                type={field.secret ? "password" : field.kind === "number" ? "number" : "text"}
                inputMode={field.kind === "number" ? "numeric" : undefined}
                placeholder={field.placeholder}
                value={draft[field.name] ?? ""}
                onChange={(event) => {
                  editedSinceFocus.current.add(field.name);
                  setDraft((previous) => ({ ...previous, [field.name]: event.target.value }));
                }}
                onFocus={(event) => {
                  // Clear the placeholder on focus rather than making someone
                  // select-all over a value that is not really there.
                  if (field.secret && event.target.value === REDACTED) {
                    editedSinceFocus.current.delete(field.name);
                    setDraft((previous) => ({ ...previous, [field.name]: "" }));
                  }
                }}
                onBlur={(event) => {
                  // Clicking through a stored key leaves it stored. Only typing
                  // and then emptying the box means "remove it".
                  if (
                    field.secret &&
                    connector.secrets_set[field.name] &&
                    event.target.value === "" &&
                    !editedSinceFocus.current.has(field.name)
                  ) {
                    setDraft((previous) => ({ ...previous, [field.name]: REDACTED }));
                  }
                }}
              />
              {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
              )}
            </div>
          );
        })}

        {/* The last Test while the form still holds what it tested; otherwise
            the saved connection's last check. */}
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
            <CheckNote ok={Boolean(connector.last_check_ok)} message={connector.last_check_message}>
              — last checked {new Date(connector.last_check_at + "Z").toLocaleString()}
            </CheckNote>
          )
        )}

        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <Button className="w-full sm:w-auto" onClick={onSave} disabled={save.isPending}>
            <IconCheck className="mr-2 h-4 w-4" />
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          {unsaved && <span className="text-xs font-medium text-amber-400">Unsaved changes</span>}
          {/* Only where there is something to reach. Discord is configured
              per webhook, so a connector-level test here would pass no matter
              what was typed. */}
          {connector.supports_check && (
            <>
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
              {missingRequired.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  Fill in {missingRequired.join(" and ")} to test.
                </span>
              )}
            </>
          )}
        </div>
      </div>
    </SectionCard>
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
    <div
      className={`rounded-lg border px-3 py-2 text-xs ${
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
