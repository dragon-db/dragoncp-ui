import { toast } from "sonner";
import { IconCopy } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/layout/section-card";
import { since } from "@/components/integrations/jellyfin-vocab";
import { WEBHOOK_EVENTS } from "@/components/integrations/seerr-vocab";
import { useSeerrSummary } from "@/hooks/useSeerr";

const EVENTS =
  "Request Pending Approval, Request Automatically Approved, Request Approved, Request Declined, Request Available, Request Processing Failed, Issue Reported, Issue Comment, Issue Resolved, Issue Reopened";

/**
 * How to point Seerr's webhook at DragonCP, and whether it has been heard from.
 * The address is this page's own: Seerr runs in Docker on this machine, and
 * the address in the browser bar usually reaches the host from inside it.
 */
export function SeerrWebhookCard({ enabled }: { enabled: boolean }) {
  const summary = useSeerrSummary(enabled);
  const webhook = summary.data?.webhook;
  const address = `${window.location.origin}${webhook?.path ?? "/api/webhook/seerr"}`;
  const last = webhook?.last_at
    ? `Last heard from Seerr ${since(webhook.last_at)}: ${
        WEBHOOK_EVENTS[webhook.last_type ?? ""] ?? webhook.last_type?.toLowerCase() ?? "something"
      }.`
    : "Nothing heard from Seerr's webhook since DragonCP started.";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(address);
      toast.success("Address copied");
    } catch {
      toast.error("Could not copy. Select the address and copy it by hand.");
    }
  };

  return (
    <SectionCard
      label="Seerr's webhook"
      description="Tells DragonCP the moment a request or issue changes, so the tabs never wait for a refresh."
      contentClassName="space-y-3 px-4 py-4"
    >
      <ol className="list-decimal space-y-2 pl-5 text-[13px] text-foreground-2 marker:text-muted-foreground">
        <li>
          Fill in <strong>Webhook password</strong> above with any long random text, and press Save.
          {webhook && !webhook.password_set && (
            <span className="text-amber-400">
              {" "}
              Not set yet: DragonCP refuses the webhook until it is.
            </span>
          )}
        </li>
        <li>In Seerr, open Settings → Notifications → Webhook and switch it on.</li>
        <li className="space-y-1.5">
          <span>Webhook URL:</span>
          <div className="flex flex-wrap items-center gap-2">
            <code className="rounded-md border border-border bg-well px-2 py-1 font-mono text-[12px] break-all text-foreground">
              {address}
            </code>
            <Button size="sm" variant="outline" onClick={copy}>
              <IconCopy className="size-3.5" />
              Copy
            </Button>
          </div>
          <span className="block text-[12px] text-muted-foreground">
            Seerr calls it from its container, so <code className="font-mono">localhost</code> would
            mean Seerr itself. Use the address in your browser bar, or the media server's address.
          </span>
        </li>
        <li>Authorization Header: the same password. Leave the JSON payload as it is.</li>
        <li>Tick these notification types: {EVENTS}. Then press Test in Seerr.</li>
      </ol>
      <p className="text-[12px] text-muted-foreground">{last}</p>
      {summary.data?.polling && (
        <p className="text-[12px] text-muted-foreground">
          Also checking Seerr every 5 minutes, in case a webhook goes missing.
        </p>
      )}
    </SectionCard>
  );
}
