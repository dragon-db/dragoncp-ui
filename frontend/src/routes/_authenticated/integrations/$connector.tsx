import { createFileRoute } from "@tanstack/react-router";
import { IntegrationsPage } from "@/components/pages/integrations";

/**
 * `?tab=` is the tab in view; `?title=<tvdb or tmdb id>` shows that series or
 * film in place of the tab's list. Both live in the address so Back returns to
 * the list as it was, and a History or Queue row can link straight to a title.
 */
export const Route = createFileRoute("/_authenticated/integrations/$connector")({
  validateSearch: (search: Record<string, unknown>): { tab?: string; title?: number } => {
    const title = Number(search.title);
    return {
      tab: typeof search.tab === "string" && search.tab ? search.tab : undefined,
      // TVDB and TMDB ids are whole numbers; kept as one so the address reads
      // `?title=376098` rather than a quoted string.
      title: Number.isSafeInteger(title) && title > 0 ? title : undefined,
    };
  },
  component: IntegrationsComponent,
});

function IntegrationsComponent() {
  const { connector } = Route.useParams();
  // Keyed on the connector: switching from Discord to Sonarr must not carry
  // over a half-typed webhook URL or an unsaved routing change into a form
  // where neither means anything.
  return <IntegrationsPage key={connector} connectorId={connector} />;
}
