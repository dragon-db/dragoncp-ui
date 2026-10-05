import { createFileRoute } from "@tanstack/react-router";
import { PipelineRunPage } from "@/components/pages/pipeline-run";

export const Route = createFileRoute("/_authenticated/pipeline/$runId")({
  component: PipelineRunComponent,
});

function PipelineRunComponent() {
  const { runId } = Route.useParams();
  // Keyed on the run, so opening a related sync starts from that sync's own
  // stages rather than carrying over which ones were open.
  return <PipelineRunPage key={runId} runId={runId} />;
}
