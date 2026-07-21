import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { useWebhookNotifications, type WebhookNotification } from "@/hooks/useWebhooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { IconWebhook, IconRefresh, IconInfoCircle } from "@tabler/icons-react";

function statusDot(status: string): string {
  switch (status) {
    case "completed":
      return "bg-emerald-400";
    case "failed":
      return "bg-rose-400";
    case "syncing":
    case "READY_FOR_TRANSFER":
      return "bg-brand-hover";
    default:
      return "bg-amber-400";
  }
}

function timeAgo(dateString?: string): string {
  if (!dateString) return "";
  const diff = Date.now() - new Date(dateString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function WebhookRail() {
  const { data, isLoading, refetch } = useWebhookNotifications(undefined, 10);
  const notifications = data?.notifications ?? [];
  const latest: WebhookNotification | undefined = notifications[0];
  const rest = notifications.slice(1, 6);

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
        <div className="flex flex-col gap-2 p-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10 w-full rounded-lg" />
          ))}
        </div>
      ) : latest ? (
        <>
          <div className="border-b border-border bg-muted/40 px-4 py-3">
            <div className="mb-1 flex items-center gap-1.5 font-mono text-[10px] tracking-[0.04em] text-muted-foreground uppercase">
              <span className={cn("size-1.5 rounded-full", statusDot(latest.status))} />
              <span className="text-brand-hover">{latest.media_type}</span>
              <span>· {latest.status}</span>
              <span className="flex-1" />
              <span>{timeAgo(latest.created_at)}</span>
            </div>
            <div className="truncate text-sm font-medium text-foreground">
              {latest.display_title}
            </div>
          </div>

          <div className="flex-1 overflow-auto">
            {rest.map((item) => (
              <div
                key={item.notification_id}
                className="flex items-center gap-2.5 border-b border-border px-4 py-2.5 text-sm last:border-b-0"
              >
                <span className={cn("size-1.5 shrink-0 rounded-full", statusDot(item.status))} />
                <span className="w-14 shrink-0 truncate font-mono text-[10px] tracking-[0.04em] text-muted-foreground uppercase">
                  {item.media_type}
                </span>
                <span className="flex-1 truncate text-foreground">{item.display_title}</span>
                <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                  {timeAgo(item.created_at)}
                </span>
              </div>
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
