import { SystemTicker } from "@/components/dashboard/system-ticker";
import { StorageStrip } from "@/components/dashboard/storage-strip";
import { TransfersPanel } from "@/components/dashboard/transfers-panel";
import { WebhookRail } from "@/components/dashboard/webhook-rail";

export function DashboardPage() {
  return (
    <div className="flex flex-col gap-3.5">
      <SystemTicker />
      <StorageStrip />
      <div className="grid grid-cols-1 items-stretch gap-3.5 lg:grid-cols-[1.5fr_1fr]">
        <TransfersPanel />
        <WebhookRail />
      </div>
    </div>
  );
}
