import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_authenticated/integrations/")({
  beforeLoad: () => {
    // Discord is the only connector that does anything yet, so it is the one
    // worth landing on.
    throw redirect({ to: "/integrations/$connector", params: { connector: "discord" } });
  },
});
