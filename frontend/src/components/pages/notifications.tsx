import { useState } from "react";
import { useAlerts, useAlertSummary, type AlertView } from "@/hooks/useSync";
import { PageHeader } from "@/components/layout/page-header";
import { PageTabsList } from "@/components/layout/page-tabs";
import { SectionEmpty } from "@/components/layout/section-card";
import { ListPagination } from "@/components/layout/list-controls";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCard } from "@/components/pipeline/alert-card";
import { IconArchive, IconBell, IconChecks } from "@tabler/icons-react";

const PAGE_SIZE = 25;

/**
 * What needs a person. Every alert carries the actions that fit it — Sync now,
 * Retry, Sync anyway, Mark as done, Mark as wrong, Dismiss — and closing one
 * records who closed it and how. The same alerts are announced on Discord
 * once, when they open; this is where they are dealt with.
 */
export function NotificationsPage() {
  const [view, setView] = useState<AlertView>("open");
  const summary = useAlertSummary();
  const openCount = summary.data?.open ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader title="Notifications" />

      <Tabs value={view} onValueChange={(value) => setView(value as AlertView)} className="gap-5">
        <PageTabsList
          items={[
            { value: "open", label: "Open", icon: IconBell, count: openCount },
            { value: "closed", label: "Closed", icon: IconArchive },
          ]}
        />
        <TabsContent value="open">
          <AlertFeed view="open" />
        </TabsContent>
        <TabsContent value="closed">
          <AlertFeed view="closed" />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function AlertFeed({ view }: { view: AlertView }) {
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const alertsQuery = useAlerts(view, { limit, offset });
  const alerts = alertsQuery.data?.alerts ?? [];

  if (alertsQuery.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {[1, 2, 3].map((index) => (
          <Skeleton key={index} className="h-24 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (!alerts.length) {
    return (
      <div className="rounded-xl border border-border bg-card">
        <SectionEmpty
          icon={view === "open" ? IconChecks : IconArchive}
          title={view === "open" ? "Nothing needs you" : "Nothing closed yet"}
          hint={
            view === "open"
              ? "When a sync is stopped, fails, or is interrupted by a restart, it shows up here with what you can do about it."
              : "Alerts you act on, mark or dismiss are kept here."
          }
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {alerts.map((alert) => (
        <AlertCard key={alert.alert_id} alert={alert} />
      ))}
      {alertsQuery.data && alertsQuery.data.total > limit && (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <ListPagination
            offset={offset}
            limit={limit}
            total={alertsQuery.data.total}
            count={alerts.length}
            onOffsetChange={setOffset}
            onLimitChange={(value) => {
              setLimit(value);
              setOffset(0);
            }}
            noun="alerts"
          />
        </div>
      )}
    </div>
  );
}
