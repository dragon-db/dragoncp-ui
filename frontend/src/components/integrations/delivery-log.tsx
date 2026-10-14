import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { useDeliveries } from "@/hooks/useConnectors";
import { IconHistory, IconRefresh } from "@tabler/icons-react";

/**
 * What was actually sent, and what happened to it.
 *
 * The whole answer to "why didn't I get told about that". Before this existed
 * the answer was in the server console, if it was still in the buffer.
 */
export function DeliveryLog({ connectorId }: { connectorId: string }) {
  const deliveries = useDeliveries(connectorId);
  const rows = deliveries.data ?? [];

  return (
    <SectionCard
      label="Recent messages"
      description="The last hundred announcements this connector handled, newest first."
      actions={
        <Button
          variant="outline"
          size="sm"
          onClick={() => deliveries.refetch()}
          disabled={deliveries.isFetching}
        >
          <IconRefresh className={`mr-2 h-4 w-4 ${deliveries.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      }
      contentClassName="divide-y divide-border/70"
    >
      {rows.length === 0 ? (
        <SectionEmpty
          icon={IconHistory}
          title="Nothing sent yet"
          hint="Once DragonCP announces something, every attempt shows up here — including the ones that were held back, and why."
        />
      ) : (
        rows.map((row) => (
          /* The outcome leads, the time trails. On a phone the timestamp drops
             under the message rather than squeezing it — what happened matters
             more than exactly when, and both stay readable. */
          <div key={row.id} className="flex items-start gap-3 px-4 py-3 sm:items-center">
            <Badge
              variant={row.ok ? "secondary" : row.skipped_reason ? "outline" : "destructive"}
              className="mt-0.5 shrink-0 sm:mt-0"
            >
              {row.ok ? "Sent" : row.skipped_reason ? "Held" : "Failed"}
            </Badge>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-foreground">{row.title || row.event_key}</div>
              <div className="text-xs text-pretty text-muted-foreground">
                {row.skipped_reason ??
                  row.error ??
                  `Delivered to “${row.target_label}” in ${row.duration_ms}ms`}
              </div>
              <div className="mt-1 text-xs text-muted-foreground tabular-nums sm:hidden">
                {new Date(row.created_at + "Z").toLocaleString()}
              </div>
            </div>
            <div className="hidden shrink-0 text-xs text-muted-foreground tabular-nums sm:block">
              {new Date(row.created_at + "Z").toLocaleString()}
            </div>
          </div>
        ))
      )}
    </SectionCard>
  );
}
