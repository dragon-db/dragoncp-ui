import { createFileRoute } from "@tanstack/react-router";
import { SETTINGS_TABS, SettingsPage, type SettingsTab } from "@/components/pages/settings";

/** `tab` opens Settings on one tab, so other pages can link straight to it. */
export const Route = createFileRoute("/_authenticated/settings")({
  validateSearch: (search: Record<string, unknown>): { tab?: SettingsTab } => ({
    tab: SETTINGS_TABS.includes(search.tab as SettingsTab)
      ? (search.tab as SettingsTab)
      : undefined,
  }),
  component: SettingsComponent,
});

function SettingsComponent() {
  const { tab } = Route.useSearch();
  return <SettingsPage tab={tab ?? "remote"} />;
}
