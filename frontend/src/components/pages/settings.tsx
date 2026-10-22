import { useNavigate } from "@tanstack/react-router";
import {
  IconFileText,
  IconPlugConnected,
  IconRefresh,
  IconServer,
  IconUserShield,
} from "@tabler/icons-react";
import { PageHeader } from "@/components/layout/page-header";
import { PageTabsList } from "@/components/layout/page-tabs";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { RemoteServerTab } from "@/components/settings/remote-server-tab";
import { SyncingTab } from "@/components/settings/syncing-tab";
import { AccountTab } from "@/components/settings/account-tab";
import { SystemTab } from "@/components/settings/system-tab";
import { LogsTab } from "@/components/settings/logs-tab";
import { useSettingMap } from "@/components/settings/settings-model";

/**
 * Settings, arranged by what an administrator is doing rather than by where a
 * value is stored (operator, 2026-10-21).
 *
 * It used to be five tabs by mechanism: "Core Config" held everything the
 * environment file sets, so the remote login sat on one tab and Connect on
 * another, the fast-transfer options appeared twice, and auto-sync and backup
 * retention were each split from their neighbours. Now each topic lives in one
 * place, every tab is built from the same section cards as the rest of the
 * app, and a value you cannot change from here reads as text, not as a
 * greyed-out field.
 */

export const SETTINGS_TABS = ["remote", "syncing", "account", "system", "logs"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];

const TABS = [
  { value: "remote", label: "Remote server", shortLabel: "Remote", icon: IconPlugConnected },
  { value: "syncing", label: "Syncing", icon: IconRefresh },
  { value: "account", label: "Account", icon: IconUserShield },
  { value: "system", label: "System", icon: IconServer },
  { value: "logs", label: "Logs", icon: IconFileText },
];

export function SettingsPage({ tab }: { tab: SettingsTab }) {
  const navigate = useNavigate();
  const settings = useSettingMap();

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" />

      <Tabs
        value={tab}
        onValueChange={(next) =>
          navigate({ to: "/settings", search: { tab: next as SettingsTab }, replace: true })
        }
        className="gap-4"
      >
        <PageTabsList items={TABS} />

        {settings.data && !Array.isArray(settings.data.groups) && (
          <p className="rounded-xl border border-amber-500/35 bg-amber-500/8 px-4 py-3 text-[13px] text-amber-100">
            The backend is running an older version: it answered without the grouped settings this
            page reads, so values below show as not set. Restart the backend.
          </p>
        )}

        {settings.isError && (
          <p className="rounded-xl border border-rose-500/35 bg-rose-500/8 px-4 py-3 text-[13px] text-rose-200">
            Could not load the settings: the backend did not answer. Values below may show as not
            set. Reload once it is running.
          </p>
        )}

        <TabsContent value="remote">
          <RemoteServerTab />
        </TabsContent>
        <TabsContent value="syncing">
          <SyncingTab />
        </TabsContent>
        <TabsContent value="account">
          <AccountTab />
        </TabsContent>
        <TabsContent value="system">
          <SystemTab />
        </TabsContent>
        <TabsContent value="logs">
          <LogsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
