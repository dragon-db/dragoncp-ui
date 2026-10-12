import { createFileRoute } from "@tanstack/react-router";
import { TransfersPage } from "@/components/pages/transfers";

/**
 * `?sync=<run id>` opens that sync's stages in a side panel over the page.
 *
 * It is a search parameter rather than a route of its own so every place that
 * points at a sync — an alert, a webhook, the auto-scanner's card — lands on
 * the one page where syncs and their transfers live.
 */
export const Route = createFileRoute("/_authenticated/transfers")({
  validateSearch: (search: Record<string, unknown>): { sync?: string } => ({
    sync: typeof search.sync === "string" && search.sync ? search.sync : undefined,
  }),
  component: TransfersPage,
});
