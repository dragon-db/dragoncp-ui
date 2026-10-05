import { toast } from "sonner";
import { PageHeader } from "@/components/layout/page-header";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { HistoryPanel } from "@/components/integrations/history-panel";
import { LibraryPanel } from "@/components/integrations/library-panel";
import { QueuePanel } from "@/components/integrations/queue-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard } from "@/components/layout/section-card";
import { ConnectorForm } from "@/components/integrations/connector-form";
import { ScannerStatus } from "@/components/integrations/scanner-status";
import { errorText } from "@/lib/api-error";
import { DeliveryLog } from "@/components/integrations/delivery-log";
import { RoutingPanel } from "@/components/integrations/routing-panel";
import { TargetsPanel } from "@/components/integrations/targets-panel";
import { useConnector, useSaveConnector } from "@/hooks/useConnectors";
import { IconAdjustmentsHorizontal, IconHistory, IconInbox, IconRoute } from "@tabler/icons-react";

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

  const toggleEnabled = async (enabled: boolean) => {
    try {
      await save.mutateAsync({ enabled });
      toast.success(
        enabled ? `${connector.display_name} is on` : `${connector.display_name} is off`
      );
    } catch (error) {
      toast.error(errorText(error, "Could not change it"));
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title={connector.display_name} description={connector.description}>
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
        belongs where somebody goes looking for it — the connector's own
        description, and the documentation — not above the content, forever.

        What is left is the one line that changes what you can expect from the
        page in front of you.
      */}
      {!connector.enabled && (
        <p className="text-xs text-muted-foreground">
          Turned off — nothing is sent to or read from it.
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
        <Tabs defaultValue="targets" className="gap-5">
          {/*
            Two columns on a phone, one row from `sm`. Four tabs do not fit
            across 390px: the strip clipped "Activity" off the right edge with
            nothing to say it was there. Wrapping keeps every tab labelled and
            gives each one a thumb-sized target.
          */}
          <TabsList className="grid h-auto w-full grid-cols-2 sm:inline-flex sm:h-8 sm:w-fit">
            <TabsTrigger value="targets" className="h-8">
              <IconInbox className="h-4 w-4" />
              {titleCase(connector.target_noun ?? "destination")}s
            </TabsTrigger>
            {/* "Routing", not "Notifications": DragonCP's own Notifications
                page lists what needs a person; this tab decides which Discord
                webhook each announcement goes to. */}
            <TabsTrigger value="routing" className="h-8">
              <IconRoute className="h-4 w-4" />
              Routing
            </TabsTrigger>
            <TabsTrigger value="activity" className="h-8">
              <IconHistory className="h-4 w-4" />
              Activity
            </TabsTrigger>
            {hasSettings && (
              <TabsTrigger value="settings" className="h-8">
                <IconAdjustmentsHorizontal className="h-4 w-4" />
                {connector.settings_label}
              </TabsTrigger>
            )}
          </TabsList>

          <TabsContent value="targets" className="mt-4 space-y-4">
            <TargetsPanel connector={connector} />
          </TabsContent>
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
        <Tabs defaultValue="library" className="gap-5">
          {/* Two columns on a phone, one row from `sm`: four labels do not fit
              across 390px, and a clipped tab is a tab nobody finds. */}
          <TabsList className="grid h-auto w-full grid-cols-2 sm:inline-flex sm:h-8 sm:w-fit">
            <TabsTrigger value="library" className="h-8">
              Library
            </TabsTrigger>
            <TabsTrigger value="queue" className="h-8">
              Queue
            </TabsTrigger>
            <TabsTrigger value="history" className="h-8">
              History
            </TabsTrigger>
            <TabsTrigger value="settings" className="h-8">
              {connector.settings_label}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="library" className="mt-4 space-y-4">
            {connector.enabled ? (
              <LibraryPanel source={connector.id} displayName={connector.display_name} />
            ) : (
              <p className="rounded-xl border border-border/70 bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
                Turn {connector.display_name} on to read its library.
              </p>
            )}
          </TabsContent>

          <TabsContent value="queue" className="mt-4 space-y-4">
            {connector.enabled ? (
              <QueuePanel source={connector.id} displayName={connector.display_name} />
            ) : (
              <p className="rounded-xl border border-border/70 bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
                Turn {connector.display_name} on to read its queue.
              </p>
            )}
          </TabsContent>

          <TabsContent value="history" className="mt-4 space-y-4">
            {connector.enabled ? (
              <HistoryPanel source={connector.id} displayName={connector.display_name} />
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
    </div>
  );
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
