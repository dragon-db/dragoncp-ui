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
import { MentionPicker } from "@/components/integrations/mention-picker";
import { errorText } from "@/lib/api-error";
import {
  useNotificationCatalogue,
  useSaveRoutes,
  type CatalogueEvent,
  type Connector,
  type PingWhen,
} from "@/hooks/useConnectors";
import { IconCheck, IconInbox } from "@tabler/icons-react";

/** What a row means when no destination has been picked. */
const USE_DEFAULT = "__default__";

const PING_LABELS: Record<PingWhen, string> = {
  never: "Never ping",
  attention: "Ping on warnings and failures",
  always: "Ping on every message",
};

interface RouteDraft {
  targetId: string;
  enabled: boolean;
  pingWhen: PingWhen;
  /** Null: whoever the webhook pings. */
  mentionIds: string[] | null;
}

/** A row as stored, or as the catalogue's defaults when nothing is. */
function savedDraft(event: CatalogueEvent, connectorId: string): RouteDraft {
  const route = event.routes[connectorId];
  return {
    targetId: route?.target_id ?? USE_DEFAULT,
    enabled: route?.enabled ?? true,
    pingWhen: route?.ping_when ?? event.default_ping,
    mentionIds: route?.mention_ids ?? null,
  };
}

function sameDraft(a: RouteDraft, b: RouteDraft) {
  return (
    a.targetId === b.targetId &&
    a.enabled === b.enabled &&
    a.pingWhen === b.pingWhen &&
    JSON.stringify(a.mentionIds) === JSON.stringify(b.mentionIds)
  );
}

/**
 * Which destination each announcement goes to, and when and whom it pings.
 *
 * Every notification the app can make is listed, including ones nobody has
 * configured — a notification you cannot see is a notification you cannot turn
 * off. A row left on "Use default" is not a gap: it is the rule that keeps a
 * newly added announcement from shipping silent. Pings work the same way: a
 * row that names nobody pings whoever its webhook pings.
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
  const pings = Boolean(connector.supports_mentions);
  const mentions = connector.mentions ?? [];

  /* eslint-disable react-hooks/set-state-in-effect -- server payload seeds a controlled form */
  useEffect(() => {
    if (!catalogue.data) return;
    const next: Record<string, RouteDraft> = {};
    for (const event of catalogue.data.events) {
      next[event.key] = savedDraft(event, connector.id);
    }
    setDraft(next);
  }, [catalogue.data, connector.id]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const dirty = useMemo(() => {
    if (!catalogue.data) return false;
    return catalogue.data.events.some((event) => {
      const current = draft[event.key];
      return current ? !sameDraft(current, savedDraft(event, connector.id)) : false;
    });
  }, [catalogue.data, draft, connector.id]);

  /** "Webhook's pings (Admins)" for the webhook this row sends to. */
  const inheritLabel = (targetId: string) => {
    const target =
      targetId === USE_DEFAULT
        ? defaultTarget
        : (connector.targets ?? []).find((t) => t.target_id === targetId);
    const names = mentions
      .filter((mention) => target?.mention_ids.includes(mention.mention_id))
      .map((mention) => mention.label);
    return `Webhook’s pings (${names.length ? names.join(", ") : "nobody"})`;
  };

  const onSave = async () => {
    try {
      await saveRoutes.mutateAsync(
        events.map((event) => {
          const current = draft[event.key] ?? savedDraft(event, connector.id);
          return {
            event_key: event.key,
            connector_id: connector.id,
            target_id: current.targetId === USE_DEFAULT ? null : current.targetId,
            enabled: current.enabled,
            // The notification's own default is stored as "default", so a
            // later version that changes it is followed.
            ping_when: current.pingWhen === event.default_ping ? null : current.pingWhen,
            mention_ids: current.mentionIds,
          };
        })
      );
      toast.success("Saved where each notification goes");
    } catch (error) {
      toast.error(errorText(error, "Could not save"));
    }
  };

  if (!defaultTarget) {
    return (
      <SectionCard label="Routing">
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
      label="Routing"
      description={`Each announcement DragonCP can make, and where it goes. “Use default” means “${defaultTarget.label}”, so a notification added in a later version arrives instead of going silent.${
        pings
          ? " Below each one: when it pings, and whom — whoever its webhook pings unless you choose."
          : ""
      }`}
      actions={
        <Button onClick={onSave} disabled={!dirty || saveRoutes.isPending}>
          <IconCheck className="mr-2 h-4 w-4" />
          {saveRoutes.isPending ? "Saving…" : "Save routing"}
        </Button>
      }
      contentClassName="divide-y divide-border/70"
    >
      {events.map((event) => {
        const current = draft[event.key] ?? savedDraft(event, connector.id);
        const set = (patch: Partial<RouteDraft>) =>
          setDraft((previous) => ({ ...previous, [event.key]: { ...current, ...patch } }));
        const pingItems = (Object.keys(PING_LABELS) as PingWhen[]).map((value) => ({
          value,
          label: `${PING_LABELS[value]}${value === event.default_ping ? " (default)" : ""}`,
        }));
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
                onValueChange={(value) => set({ targetId: String(value) })}
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
                  onCheckedChange={(checked) => set({ enabled: checked })}
                  aria-label={`Announce ${event.label}`}
                />
                <span className="w-7 text-xs text-muted-foreground">
                  {current.enabled ? "On" : "Off"}
                </span>
              </div>
            </div>

            {/* When and whom it pings, on a line of its own. */}
            {pings && (
              <div className="flex flex-col gap-2 sm:basis-full sm:flex-row sm:items-center">
                <Select
                  items={pingItems}
                  value={current.pingWhen}
                  onValueChange={(value) => set({ pingWhen: value as PingWhen })}
                >
                  <SelectTrigger
                    className="w-full sm:w-[22rem]"
                    disabled={!current.enabled}
                    aria-label={`When ${event.label} pings`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {pingItems.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <MentionPicker
                  mentions={mentions}
                  value={current.mentionIds}
                  onChange={(next) => set({ mentionIds: next })}
                  inheritLabel={inheritLabel(current.targetId)}
                  disabled={!current.enabled || current.pingWhen === "never"}
                  className="w-full sm:w-64"
                  ariaLabel={`Who ${event.label} pings`}
                />
              </div>
            )}
          </div>
        );
      })}
    </SectionCard>
  );
}
