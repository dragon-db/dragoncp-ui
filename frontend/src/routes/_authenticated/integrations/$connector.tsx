import { createFileRoute } from "@tanstack/react-router";
import { IntegrationsPage } from "@/components/pages/integrations";

export const Route = createFileRoute("/_authenticated/integrations/$connector")({
  component: IntegrationsComponent,
});

function IntegrationsComponent() {
  const { connector } = Route.useParams();
  // Keyed on the connector: switching from Discord to Sonarr must not carry
  // over a half-typed webhook URL or an unsaved routing change into a form
  // where neither means anything.
  return <IntegrationsPage key={connector} connectorId={connector} />;
}
