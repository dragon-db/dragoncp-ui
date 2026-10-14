import { createFileRoute, redirect } from "@tanstack/react-router";

// The Pipeline page became part of Transfers on 2026-10-06. Kept so a bookmark
// or an older Discord message still lands somewhere useful.
export const Route = createFileRoute("/_authenticated/pipeline/")({
  beforeLoad: () => {
    throw redirect({ to: "/transfers", replace: true });
  },
});
