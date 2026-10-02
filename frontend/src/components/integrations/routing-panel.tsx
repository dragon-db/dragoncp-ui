import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { errorText } from "@/lib/api-error";
import { useNotificationCatalogue, useSaveRoutes, type Connector } from "@/hooks/useConnectors";
import { IconCheck, IconInbox } from "@tabler/icons-react";

/** What a row means when no destination has been picked. */
const USE_DEFAULT = "__default__";

interface RouteDraft {
  targetId: string;
  enabled: boolean;
}

/**
 * Which destination each announcement goes to.
 *
 * Every notification the app can make is listed, including ones nobody has
 * configured — a notification you cannot see is a notification you cannot turn
 * off. A row left on "Use default" is not a gap: it is the rule that keeps a
 * newly added announcement from shipping silent.
 */
export function RoutingPanel({ connector }: { connector: Connector }) {
  const catalogue = useNotificationCatalogue();
  const saveRoutes = useSaveRoutes();
  const [draft, setDraft] = useState<Record<string, RouteDraft>>({});

  const events = catalogue.data?.events ?? [];
  const targets = useMemo(
    () => (connector.targets ?? []).filter((t) => t.enabled || t.is_default),
    [connector.targets]
  );
  const defaultTarget = (connector.targets ?? []).find((t) => t.is_default);

  /* eslint-disable react-hooks/set-state-in-effect -- server payload seeds a controlled form */
  useEffect(() => {
    if (!catalogue.data) return;
    const next: Record<string, RouteDraft> = {};
    for (const event of catalogue.data.events) {
      const route = event.routes[connector.id];
      next[event.key] = {
        targetId: route?.target_id ?? USE_DEFAULT,
        enabled: route?.enabled ?? true,
      };
    }
    setDraft(next);
  }, [catalogue.data, connector.id]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const dirty = useMemo(() => {
    if (!catalogue.data) return false;
    return catalogue.data.events.some((event) => {
      const route = event.routes[connector.id];
      const current = draft[event.key];
      if (!current) return false;
      return (
        current.targetId !== (route?.target_id ?? USE_DEFAULT) ||
        current.enabled !== (route?.enabled ?? true)
      );
    });
  }, [catalogue.data, draft, connector.id]);

  const onSave = async () => {
    try {
      await saveRoutes.mutateAsync(
        events.map((event) => ({
          event_key: event.key,
          connector_id: connector.id,
          target_id:
            draft[event.key]?.targetId === USE_DEFAULT
              ? null
              : (draft[event.key]?.targetId ?? null),
          enabled: draft[event.key]?.enabled ?? true,
        }))
      );
      toast.success("Saved where each notification goes");
    } catch (error) {
      toast.error(errorText(error, "Could not save"));
    }
  };

  if (!defaultTarget) {
    return (
      <SectionCard label="Notifications">
        <SectionEmpty
          icon={IconInbox}
          title="Nothing to route yet"
          hint={`Add a ${connector.target_noun ?? "destination"} first. Until there is one, DragonCP has nowhere to send an announcement and every notification is held.`}
        />
      </SectionCard>
    );
  }

  return (
    <SectionCard
      label="Notifications"
      description={`Each announcement DragonCP can make, and where it goes. “Use default” means “${defaultTarget.label}”, so a notification added in a later version arrives instead of going silent.`}
      actions={
        <Button onClick={onSave} disabled={!dirty || saveRoutes.isPending}>
          <IconCheck className="mr-2 h-4 w-4" />
          {saveRoutes.isPending ? "Saving…" : "Save routing"}
        </Button>
      }
      contentClassName="divide-y divide-border/70"
    >
      {events.map((event) => {
        const current = draft[event.key] ?? { targetId: USE_DEFAULT, enabled: true };
        const items = [
          { label: `Use default (${defaultTarget.label})`, value: USE_DEFAULT },
          ...targets.map((target) => ({ label: target.label, value: target.target_id })),
        ];

        return (
          /*
            A stacked statement on a phone, the table it already was from `sm`.
            Laid out as a row, the fixed-width destination control left the
            event name about ninety pixels to live in — "Sync finished" broke
            across two lines and its one-line description became six.
          */
          <div
            key={event.key}
            className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:gap-y-2 sm:py-3"
          >
            <div className="min-w-0 sm:flex-1">
              <div className="text-sm font-semibold text-foreground">{event.label}</div>
              <p className="mt-0.5 text-xs text-pretty text-muted-foreground">
                {event.description}
              </p>
            </div>

            <div className="flex items-center gap-3 sm:contents">
              <Select
                items={items}
                value={current.targetId}
                onValueChange={(value) =>
                  setDraft((previous) => ({
                    ...previous,
                    [event.key]: { ...current, targetId: String(value) },
                  }))
                }
              >
                <SelectTrigger
                  className="min-w-0 flex-1 sm:w-56 sm:flex-none sm:shrink-0"
                  disabled={!current.enabled}
                  aria-label={`Where ${event.label} goes`}
                >
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

              <div
                className="flex shrink-0 items-center gap-1.5"
                title="Turn this announcement off entirely"
              >
                <Switch
                  checked={current.enabled}
                  onCheckedChange={(checked) =>
                    setDraft((previous) => ({
                      ...previous,
                      [event.key]: { ...current, enabled: checked },
                    }))
                  }
                  aria-label={`Announce ${event.label}`}
                />
                <span className="w-7 text-xs text-muted-foreground">
                  {current.enabled ? "On" : "Off"}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </SectionCard>
  );
}
