import { toast } from "sonner";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/page-header";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { PageTabsList } from "@/components/layout/page-tabs";
import { HistoryPanel } from "@/components/integrations/history-panel";
import { LibraryPanel } from "@/components/integrations/library-panel";
import { QueuePanel } from "@/components/integrations/queue-panel";
import { TitleDialog } from "@/components/integrations/title-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard } from "@/components/layout/section-card";
import { ConnectorForm } from "@/components/integrations/connector-form";
import { ScannerStatus } from "@/components/integrations/scanner-status";
import { errorText } from "@/lib/api-error";
import { DeliveryLog } from "@/components/integrations/delivery-log";
import { RoutingPanel } from "@/components/integrations/routing-panel";
import { TargetsPanel } from "@/components/integrations/targets-panel";
import { MentionsPanel } from "@/components/integrations/mentions-panel";
import { useConnector, useSaveConnector } from "@/hooks/useConnectors";
import { useLibrary, useLibraryQueue } from "@/hooks/useMediaLibrary";
import {
  IconAdjustmentsHorizontal,
  IconAt,
  IconDownload,
  IconHistory,
  IconInbox,
  IconLayoutGrid,
  IconPlugConnected,
  IconRoute,
} from "@tabler/icons-react";

const NOTIFY_TABS = ["targets", "mentions", "routing", "activity", "settings"];
const QUERY_TABS = ["library", "queue", "history", "settings"];

/** The saved "Look back (days)", read the way the server reads it: 1 to 30, 7 when empty. */
function lookbackDays(value: string | undefined): number {
  const days = Number.parseInt(value ?? "", 10);
  return Number.isFinite(days) ? Math.min(30, Math.max(1, days)) : 7;
}

/**
 * One connector, as its own small application.
 *
 * Which tabs appear is decided by what the connector says it can do, not by a
 * per-connector branch: a notifying connector gets destinations, routing and a
 * delivery log; a query connector gets its credentials and nothing it cannot
 * back up. Adding a connector on the backend produces a working page here with
 * no change to this file.
 */
export function IntegrationsPage({ connectorId }: { connectorId: string }) {
  const connectorQuery = useConnector(connectorId);
  const save = useSaveConnector(connectorId);
  const connector = connectorQuery.data;
  const search = useSearch({ from: "/_authenticated/integrations/$connector" });
  const navigate = useNavigate();
  const go = (next: { tab?: string; title?: number }) =>
    navigate({
      to: "/integrations/$connector",
      params: { connector: connectorId },
      search: next,
    });

  const answers = Boolean(connector?.enabled) && Boolean(connector?.capabilities.includes("query"));

  // The tab counts, from the same queries the panels make — the cache is shared,
  // so the Library count costs nothing and the Queue count one light read. The
  // queue is only asked for once the library has answered: a connector that
  // answers questions but has no library here (Jellyfin, today) would otherwise
  // be asked for a queue every thirty seconds and refuse every time.
  const library = useLibrary(connectorId, answers);
  const queue = useLibraryQueue(connectorId, answers && library.isSuccess);

  if (connectorQuery.isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!connector) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Not found"
          description={`There is no connector called ${connectorId}.`}
        />
      </div>
    );
  }

  const canNotify = connector.capabilities.includes("notify");
  const canQuery = connector.capabilities.includes("query");
  const hasSettings = connector.config_fields.length > 0;
  const tabs = canNotify ? NOTIFY_TABS : QUERY_TABS;
  const tab = search.tab && tabs.includes(search.tab) ? search.tab : tabs[0];
  // A title opens in a pop-up over the list; the address carries it, so the
  // browser's Back closes it and a link can open one directly.
  const title = canQuery && connector.enabled ? search.title : undefined;
  const openTitle = (externalId: string) => go({ tab, title: Number(externalId) });
  const closeTitle = () => go({ tab });

  const toggleEnabled = async (enabled: boolean) => {
    try {
      const response = await save.mutateAsync({ enabled });
      const name = connector.display_name;
      // The switch saves only on/off. Say so when there is nothing saved to
      // connect with, rather than "is on" over a form still waiting for Save.
      if (enabled && response.connector && !response.connector.configured) {
        toast.warning(
          canNotify
            ? `${name} is on, but it has no default webhook yet.`
            : `${name} is on, but nothing is saved to connect with yet. Fill in ${connector.config_fields
                .filter((field) => field.required)
                .map((field) => field.label)
                .join(" and ")} and press Save.`
        );
      } else {
        toast.success(enabled ? `${name} is on` : `${name} is off`);
      }
    } catch (error) {
      toast.error(errorText(error, "Could not change it"));
    }
  };

  return (
    <div className="space-y-6">
      {/* No description under the name: "Film library manager. Already sends
          notifications here…" told an operator what they already knew, and
          on a phone it took three lines above the tabs (operator,
          2026-10-20). The API still carries it. */}
      <PageHeader title={connector.display_name}>
        <div className="flex items-center gap-2.5 rounded-xl border border-border/70 bg-card/80 px-3.5 py-2">
          <Switch
            checked={connector.enabled}
            onCheckedChange={toggleEnabled}
            disabled={save.isPending}
            aria-label={`Turn ${connector.display_name} on or off`}
          />
          <span className="text-sm font-medium text-foreground">
            {connector.enabled ? "On" : "Off"}
          </span>
        </div>
      </PageHeader>

      {/*
        Two things used to sit here and neither survived contact with the
        screen they were on.

        A "Answers questions" badge, on a page whose tabs are Library, Queue and
        History — the tabs are the answer, and the badge restated it in the
        abstract every single visit.

        A panel promising the connector was only ever read from. True, and
        enforced in the adapter, but a reassurance nobody asked for is still a
        paragraph between the operator and the thing they came to look at. It
        belongs where somebody goes looking for it — the documentation — not
        above the content, forever.

        What is left is the one line that changes what you can expect from the
        page in front of you.
      */}
      {!connector.enabled && (
        <p className="text-xs text-muted-foreground">
          Turned off: nothing is sent to it or read from it.
        </p>
      )}

      {/*
        Destinations first, settings last. The settings tab used to lead and be
        the landing page, which put three fields you set once in front of the
        two screens you actually come here to change. For Discord it is not
        even a connection — it is how a message looks — so the adapter names
        the tab rather than this file assuming.
      */}
      {canNotify ? (
        <Tabs value={tab} onValueChange={(next) => go({ tab: String(next) })}>
          {/*
            The app's one page-level switcher, as on Transfers and Webhooks: an
            underlined row that scrolls rather than clips when a phone runs out
            of room. The settings tab sits at the far end: something set once,
            not another view of the connector.

            "Routing", not "Notifications": DragonCP's own Notifications page
            lists what needs a person; this tab decides which Discord webhook
            each announcement goes to.
          */}
          <PageTabsList
            items={[
              {
                value: "targets",
                label: `${titleCase(connector.target_noun ?? "destination")}s`,
                icon: IconInbox,
                count: (connector.targets ?? []).length,
              },
              ...(connector.supports_mentions
                ? [
                    {
                      value: "mentions",
                      label: "Mentions",
                      icon: IconAt,
                      count: (connector.mentions ?? []).length,
                    },
                  ]
                : []),
              { value: "routing", label: "Routing", icon: IconRoute },
              { value: "activity", label: "Activity", icon: IconHistory },
              ...(hasSettings
                ? [
                    {
                      value: "settings",
                      label: connector.settings_label,
                      icon: IconAdjustmentsHorizontal,
                      atEnd: true,
                    },
                  ]
                : []),
            ]}
          />

          <TabsContent value="targets" className="mt-4 space-y-4">
            <TargetsPanel connector={connector} />
          </TabsContent>
          {connector.supports_mentions && (
            <TabsContent value="mentions" className="mt-4 space-y-4">
              <MentionsPanel connector={connector} />
            </TabsContent>
          )}
          <TabsContent value="routing" className="mt-4 space-y-4">
            <RoutingPanel connector={connector} />
          </TabsContent>
          <TabsContent value="activity" className="mt-4 space-y-4">
            <DeliveryLog connectorId={connector.id} />
          </TabsContent>
          {hasSettings && (
            <TabsContent value="settings" className="mt-4 space-y-4">
              <ConnectorForm connector={connector} />
            </TabsContent>
          )}
        </Tabs>
      ) : canQuery ? (
        /*
          A connector that answers questions rather than receiving messages.
          Its library and its history are what somebody comes here to look at;
          the address and key are set once. So those lead, and the credentials
          sit last under the name the adapter gives them.
        */
        <Tabs value={tab} onValueChange={(next) => go({ tab: String(next) })}>
          <PageTabsList
            items={[
              {
                value: "library",
                label: "Library",
                icon: IconLayoutGrid,
                count: library.data?.total,
              },
              { value: "queue", label: "Queue", icon: IconDownload, count: queue.data?.total },
              { value: "history", label: "History", icon: IconHistory },
              {
                value: "settings",
                label: connector.settings_label,
                icon: IconPlugConnected,
                atEnd: true,
              },
            ]}
          />

          <TabsContent value="library" className="mt-4 space-y-4">
            {connector.enabled ? (
              <LibraryPanel
                source={connector.id}
                displayName={connector.display_name}
                onOpenTitle={openTitle}
              />
            ) : (
              <p className="rounded-xl border border-border/70 bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
                Turn {connector.display_name} on to read its library.
              </p>
            )}
          </TabsContent>

          <TabsContent value="queue" className="mt-4 space-y-4">
            {connector.enabled ? (
              <QueuePanel
                source={connector.id}
                displayName={connector.display_name}
                onOpenTitle={openTitle}
              />
            ) : (
              <p className="rounded-xl border border-border/70 bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
                Turn {connector.display_name} on to read its queue.
              </p>
            )}
          </TabsContent>

          <TabsContent value="history" className="mt-4 space-y-4">
            {connector.enabled ? (
              <HistoryPanel
                source={connector.id}
                displayName={connector.display_name}
                onOpenTitle={openTitle}
              />
            ) : (
              <p className="rounded-xl border border-border/70 bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
                Turn {connector.display_name} on to read its history.
              </p>
            )}
          </TabsContent>

          <TabsContent value="settings" className="mt-4 space-y-4">
            {hasSettings ? (
              <>
                <ConnectorForm connector={connector} />
                <ScannerStatus
                  source={connector.id}
                  displayName={connector.display_name}
                  connectorEnabled={connector.enabled}
                  mode={connector.config.auto_scanner_mode === "sync" ? "sync" : "alert"}
                  lookbackDays={lookbackDays(connector.config.auto_scanner_lookback_days)}
                />
              </>
            ) : (
              <SectionCard label="Nothing to configure" contentClassName="px-4 py-6">
                <p className="text-sm text-muted-foreground">This connector needs no settings.</p>
              </SectionCard>
            )}
          </TabsContent>
        </Tabs>
      ) : hasSettings ? (
        <ConnectorForm connector={connector} />
      ) : (
        <SectionCard label="Nothing to configure" contentClassName="px-4 py-6">
          <p className="text-sm text-muted-foreground">This connector needs no settings.</p>
        </SectionCard>
      )}

      {canQuery && (
        <TitleDialog
          source={connector.id}
          displayName={connector.display_name}
          externalId={title ? String(title) : null}
          onClose={closeTitle}
        />
      )}
    </div>
  );
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
