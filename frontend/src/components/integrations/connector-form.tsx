import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { SectionCard } from "@/components/layout/section-card";
import { errorText } from "@/lib/api-error";
import {
  REDACTED,
  useCheckConnector,
  useSaveConnector,
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

export function ConnectorForm({ connector }: { connector: Connector }) {
  const save = useSaveConnector(connector.id);
  const check = useCheckConnector(connector.id);

  const [draft, setDraft] = useState<Record<string, string>>({});

  /* eslint-disable react-hooks/set-state-in-effect -- server payload seeds a controlled form */
  useEffect(() => {
    const next: Record<string, string> = {};
    for (const field of connector.config_fields) {
      next[field.name] = field.secret
        ? connector.secrets_set[field.name]
          ? REDACTED
          : ""
        : (connector.config[field.name] ?? "");
    }
    setDraft(next);
  }, [connector]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const missingRequired = connector.config_fields
    .filter((field) => field.required)
    .filter((field) => !(draft[field.name] ?? "").trim())
    .map((field) => field.label);

  const onSave = async () => {
    try {
      await save.mutateAsync({ config: draft });
      toast.success(`${connector.display_name} settings saved`);
    } catch (error) {
      toast.error(errorText(error, "Could not save the settings"));
    }
  };

  const onCheck = async () => {
    try {
      const result = await check.mutateAsync();
      if (result.ok) toast.success(result.message);
      else toast.error(result.message);
    } catch (error) {
      toast.error(errorText(error, "Could not reach the service"));
    }
  };

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
          input and a interval as a string somebody could type "soon" into.
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
                onChange={(event) =>
                  setDraft((previous) => ({ ...previous, [field.name]: event.target.value }))
                }
                onFocus={(event) => {
                  // Clear the placeholder on focus rather than making someone
                  // select-all over a value that is not really there.
                  if (field.secret && event.target.value === REDACTED) {
                    setDraft((previous) => ({ ...previous, [field.name]: "" }));
                  }
                }}
              />
              {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
              )}
            </div>
          );
        })}

        {connector.supports_check && connector.last_check_at && (
          <div
            className={`rounded-lg border px-3 py-2 text-xs ${
              connector.last_check_ok
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-destructive/30 bg-destructive/10 text-destructive"
            }`}
          >
            {connector.last_check_message}
            <span className="ml-1 opacity-70">
              — last checked {new Date(connector.last_check_at + "Z").toLocaleString()}
            </span>
          </div>
        )}

        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <Button className="w-full sm:w-auto" onClick={onSave} disabled={save.isPending}>
            <IconCheck className="mr-2 h-4 w-4" />
            {save.isPending ? "Saving…" : "Save"}
          </Button>
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
                    ? `Fill in ${missingRequired.join(" and ")} first`
                    : undefined
                }
              >
                <IconPlugConnected className="mr-2 h-4 w-4" />
                {check.isPending ? "Checking…" : "Test connection"}
              </Button>
              {missingRequired.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  Save {missingRequired.join(" and ")} before testing.
                </span>
              )}
            </>
          )}
        </div>
      </div>
    </SectionCard>
  );
}
