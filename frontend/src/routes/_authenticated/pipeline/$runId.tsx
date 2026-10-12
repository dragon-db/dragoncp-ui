import { createFileRoute, redirect } from "@tanstack/react-router";

// One sync used to have a page of its own; it now opens in a panel on the
// Transfers page. Alerts stored before the move still carry this address.
export const Route = createFileRoute("/_authenticated/pipeline/$runId")({
  beforeLoad: ({ params }) => {
    throw redirect({ to: "/transfers", search: { sync: params.runId }, replace: true });
  },
});
