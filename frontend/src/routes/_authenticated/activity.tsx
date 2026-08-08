import { createFileRoute } from "@tanstack/react-router";
import { ActivityPage } from "@/components/pages/activity";

export const Route = createFileRoute("/_authenticated/activity")({
  component: ActivityPage,
});
