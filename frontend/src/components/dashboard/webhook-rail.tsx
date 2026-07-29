import { Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { useWebhookNotifications } from "@/hooks/useWebhooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { IconWebhook, IconRefresh, IconInfoCircle, IconUser } from "@tabler/icons-react";
import {
  groupNotifications,
  groupStatus,
  itemDetail,
  formatSize,
  timeAgo,
  seasonBytes,
  type WebhookItem,
} from "@/lib/webhook-grouping";
import { WebhookPoster, StatusBadge, MediaBadge } from "@/components/webhooks/webhook-bits";

function WebhookRow({ item }: { item: WebhookItem }) {
  const status = groupStatus(item.notifications);
  const meta = [
    item.requestedBy,
    formatSize(seasonBytes(item.notifications)),
    timeAgo(item.createdAt),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="flex gap-3 border-b border-border px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/40">
      <WebhookPoster item={item} className="h-[62px] w-11" />

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex items-start gap-2">
          <span className="line-clamp-2 text-[13px] leading-tight font-semibold text-foreground">
            {item.title}
            {item.year ? (
              <span className="font-normal text-muted-foreground"> ({item.year})</span>
            ) : null}
          </span>
          <StatusBadge status={status} size="sm" className="ml-auto" />
        </div>

        <div className="flex min-w-0 items-center gap-2">
          <MediaBadge mediaType={item.mediaType} />
          <span className="truncate text-[11px] text-muted-foreground">{itemDetail(item)}</span>
        </div>

        <div className="flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
          <IconUser className="size-[11px] opacity-80" />
          <span className="truncate">{meta}</span>
        </div>
      </div>
    </div>
  );
}

export function WebhookRail() {
  const { data, isLoading, refetch } = useWebhookNotifications({ limit: 30 });
  // Group series/anime by show + season so one show doesn't flood the rail.
  const items = useMemo(
    () => groupNotifications(data?.notifications ?? []).slice(0, 5),
    [data?.notifications]
  );

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <IconWebhook className="size-4 text-muted-foreground" />
        <span className="font-display text-sm font-semibold text-foreground">Webhooks</span>
        {data?.total != null && (
          <Badge variant="outline" className="gap-1.5 text-muted-foreground">
            <span className="size-1.5 rounded-full bg-emerald-400" />
            {data.total}
          </Badge>
        )}
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => refetch()}
          title="Refresh"
        >
          <IconRefresh className="size-4" />
        </Button>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-3 p-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : items.length ? (
        <>
          <div className="flex-1 overflow-auto">
            {items.map((item) => (
              <WebhookRow key={item.key} item={item} />
            ))}
          </div>
          <div className="flex justify-center border-t border-border px-4 py-2">
            <Link to="/webhooks">
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-foreground"
              >
                View all webhooks →
              </Button>
            </Link>
          </div>
        </>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
          <IconInfoCircle className="size-5" />
          <span className="text-sm">No webhook activity</span>
        </div>
      )}
    </section>
  );
}
