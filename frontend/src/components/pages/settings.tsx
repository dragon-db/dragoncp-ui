import { PageHeader } from "@/components/layout/page-header";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  useSSHAutoConnect,
  useSSHDisconnect,
  useSSHStatus,
  useWebSocketStatus,
} from "@/hooks/useConfig";
import { SettingsPanel } from "@/components/settings/settings-panel";
import { AccountPanel } from "@/components/settings/account-panel";
import {
  useDiscordSettings,
  useTestDiscord,
  useUpdateDiscordSettings,
  useUpdateWebhookSettings,
  useWebhookSettings,
} from "@/hooks/useWebhooks";
import { useRuntimeStore } from "@/stores/runtime";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  IconBolt,
  IconBrandDiscord,
  IconCheck,
  IconLink,
  IconPlayerPause,
  IconRefresh,
  IconServer,
  IconSettings,
  IconUserShield,
  IconWebhook,
} from "@tabler/icons-react";

export function SettingsPage() {
  const webhookSettingsQuery = useWebhookSettings();
  const discordSettingsQuery = useDiscordSettings();
  const sshStatusQuery = useSSHStatus();
  const wsStatusQuery = useWebSocketStatus();

  const updateWebhookSettings = useUpdateWebhookSettings();
  const updateDiscordSettings = useUpdateDiscordSettings();
  const testDiscord = useTestDiscord();

  const autoConnect = useSSHAutoConnect();
  const disconnect = useSSHDisconnect();

  const setConfigChanged = useRuntimeStore((state) => state.setConfigChanged);

  const [webhookDraft, setWebhookDraft] = useState({
    auto_sync_movies: false,
    auto_sync_series: false,
    auto_sync_anime: false,
    series_anime_sync_wait_time: "60",
  });
  const [discordDraft, setDiscordDraft] = useState({
    enabled: false,
    webhook_url: "",
    app_url: "",
    icon_url: "",
    manual_sync_thumbnail_url: "",
  });

  useEffect(() => {
    const settings = webhookSettingsQuery.data?.settings;
    if (!settings) return;
    setWebhookDraft({
      auto_sync_movies: Boolean(settings.auto_sync_movies),
      auto_sync_series: Boolean(settings.auto_sync_series),
      auto_sync_anime: Boolean(settings.auto_sync_anime),
      series_anime_sync_wait_time: String(settings.series_anime_sync_wait_time ?? 60),
    });
  }, [webhookSettingsQuery.data]);

  useEffect(() => {
    const settings = discordSettingsQuery.data?.settings;
    if (!settings) return;
    setDiscordDraft({
      enabled: Boolean(settings.enabled),
      webhook_url: settings.webhook_url ?? "",
      app_url: settings.app_url ?? "",
      icon_url: settings.icon_url ?? "",
      manual_sync_thumbnail_url: settings.manual_sync_thumbnail_url ?? "",
    });
  }, [discordSettingsQuery.data]);

  const connectionState = sshStatusQuery.data ? "Connected" : "Disconnected";

  /**
   * Saves the Automation tab only. The Config tab saves itself — its settings
   * are split across two stores and only one of them is writable, so a single
   * "save everything" button would have to claim it wrote things it did not.
   */
  const saveAutomationSettings = async () => {
    // Two requests, so say which one failed. "Failed to save settings" after
    // the first succeeded left the screen and the database disagreeing with no
    // clue which half was live.
    let failed: string | null = null;
    try {
      await updateWebhookSettings.mutateAsync({
        auto_sync_movies: webhookDraft.auto_sync_movies,
        auto_sync_series: webhookDraft.auto_sync_series,
        auto_sync_anime: webhookDraft.auto_sync_anime,
        series_anime_sync_wait_time: Math.max(
          1,
          Number(webhookDraft.series_anime_sync_wait_time) || 60
        ),
      });
    } catch {
      failed = "auto-sync";
    }

    try {
      await updateDiscordSettings.mutateAsync({
        enabled: discordDraft.enabled,
        webhook_url: discordDraft.webhook_url,
        app_url: discordDraft.app_url,
        icon_url: discordDraft.icon_url,
        manual_sync_thumbnail_url: discordDraft.manual_sync_thumbnail_url,
      });
    } catch {
      failed = failed ? "auto-sync and Discord" : "Discord";
    }

    if (failed) {
      toast.error(`Could not save the ${failed} settings`);
    } else {
      toast.success("Settings saved");
    }

    // Refetched either way. After a partial save the screen has to show what
    // the server actually holds, which is exactly when it differs from the form.
    webhookSettingsQuery.refetch();
    discordSettingsQuery.refetch();
    wsStatusQuery.refetch();
  };

  const runAutoConnect = async () => {
    try {
      await autoConnect.mutateAsync();
      setConfigChanged(false);
      sshStatusQuery.refetch();
      toast.success("Connected");
    } catch {
      toast.error("Connection failed");
    }
  };

  const runDisconnect = async () => {
    try {
      await disconnect.mutateAsync();
      sshStatusQuery.refetch();
      toast.success("Disconnected");
    } catch {
      toast.error("Failed to disconnect");
    }
  };

  return (
    <div className="space-y-6">
      {/*
        No save button up here any more. It used to be "Save All" and wrote
        every tab at once, which stopped being true when the Config tab split
        across two stores and gained its own save. A page-level button that
        saves one tab is worse than no page-level button.

        "Reset to Env" went with the per-browser session it reset: a setting now
        either comes from the environment file, and is read-only, or from the
        database, where it is the only value there is.
      */}
      <PageHeader title="Settings" description="Connection, media paths, and automation" />

      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-border/70 bg-card/80 px-4 py-3">
          <div className="inline-flex items-center gap-2 text-xs tracking-[0.14em] text-muted-foreground uppercase">
            <IconServer className="h-3.5 w-3.5" />
            SSH
          </div>
          <div className="mt-1 text-sm font-semibold text-foreground">{connectionState}</div>
        </div>
        <div className="rounded-xl border border-border/70 bg-card/80 px-4 py-3">
          <div className="inline-flex items-center gap-2 text-xs tracking-[0.14em] text-muted-foreground uppercase">
            <IconLink className="h-3.5 w-3.5" />
            WebSockets
          </div>
          <div className="mt-1 text-sm font-semibold text-foreground tabular-nums">
            {wsStatusQuery.data?.websocket_status.active_connections ?? 0} active
          </div>
        </div>
      </div>

      <Tabs defaultValue="config" className="gap-5">
        <TabsList>
          <TabsTrigger value="config">
            <IconSettings className="h-4 w-4" />
            Core Config
          </TabsTrigger>
          <TabsTrigger value="automation">
            <IconWebhook className="h-4 w-4" />
            Automation
          </TabsTrigger>
          <TabsTrigger value="account">
            <IconUserShield className="h-4 w-4" />
            Account
          </TabsTrigger>
          <TabsTrigger value="diagnostics">
            <IconServer className="h-4 w-4" />
            Diagnostics
          </TabsTrigger>
        </TabsList>

        <TabsContent value="config" className="mt-4 space-y-4">
          <SettingsPanel />
        </TabsContent>

        <TabsContent value="account" className="mt-4 space-y-4">
          <AccountPanel />
        </TabsContent>

        <TabsContent value="automation" className="mt-4 space-y-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Webhook Auto-Sync</CardTitle>
              <CardDescription className="text-neutral-400">
                Control movie/series/anime auto-sync behavior and wait window
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Auto-sync Movies</div>
                  <div className="text-xs text-neutral-500">
                    Trigger sync automatically for movie webhooks
                  </div>
                </div>
                <Switch
                  checked={webhookDraft.auto_sync_movies}
                  onCheckedChange={(checked) =>
                    setWebhookDraft((previous) => ({ ...previous, auto_sync_movies: checked }))
                  }
                />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Auto-sync TV Shows</div>
                  <div className="text-xs text-neutral-500">
                    Trigger sync automatically for series webhooks
                  </div>
                </div>
                <Switch
                  checked={webhookDraft.auto_sync_series}
                  onCheckedChange={(checked) =>
                    setWebhookDraft((previous) => ({ ...previous, auto_sync_series: checked }))
                  }
                />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Auto-sync Anime</div>
                  <div className="text-xs text-neutral-500">
                    Trigger sync automatically for anime webhooks
                  </div>
                </div>
                <Switch
                  checked={webhookDraft.auto_sync_anime}
                  onCheckedChange={(checked) =>
                    setWebhookDraft((previous) => ({ ...previous, auto_sync_anime: checked }))
                  }
                />
              </div>
              <Separator className="bg-neutral-800" />
              <div className="space-y-2">
                <Label className="text-neutral-200">Series/Anime Wait Time (seconds)</Label>
                <Input
                  type="number"
                  value={webhookDraft.series_anime_sync_wait_time}
                  onChange={(event) =>
                    setWebhookDraft((previous) => ({
                      ...previous,
                      series_anime_sync_wait_time: event.target.value,
                    }))
                  }
                  className="w-48 border-neutral-700 bg-neutral-900"
                />
              </div>
            </CardContent>
          </Card>

          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Discord Settings</CardTitle>
              <CardDescription className="text-neutral-400">
                Notification webhook, app links, and branding settings
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Enable Discord Notifications</div>
                  <div className="text-xs text-neutral-500">
                    Send transfer and sync notifications to Discord
                  </div>
                </div>
                <Switch
                  checked={discordDraft.enabled}
                  onCheckedChange={(checked) =>
                    setDiscordDraft((previous) => ({ ...previous, enabled: checked }))
                  }
                />
              </div>
              <Input
                placeholder="Discord Webhook URL"
                value={discordDraft.webhook_url}
                onChange={(event) =>
                  setDiscordDraft((previous) => ({ ...previous, webhook_url: event.target.value }))
                }
                className="border-neutral-700 bg-neutral-900"
              />
              <Input
                placeholder="App URL"
                value={discordDraft.app_url}
                onChange={(event) =>
                  setDiscordDraft((previous) => ({ ...previous, app_url: event.target.value }))
                }
                className="border-neutral-700 bg-neutral-900"
              />
              <Input
                placeholder="Icon URL"
                value={discordDraft.icon_url}
                onChange={(event) =>
                  setDiscordDraft((previous) => ({ ...previous, icon_url: event.target.value }))
                }
                className="border-neutral-700 bg-neutral-900"
              />
              <Input
                placeholder="Manual Sync Thumbnail URL"
                value={discordDraft.manual_sync_thumbnail_url}
                onChange={(event) =>
                  setDiscordDraft((previous) => ({
                    ...previous,
                    manual_sync_thumbnail_url: event.target.value,
                  }))
                }
                className="border-neutral-700 bg-neutral-900"
              />
              <Button
                variant="outline"
                onClick={async () => {
                  try {
                    await testDiscord.mutateAsync();
                    toast.success("Discord test notification sent");
                  } catch {
                    toast.error("Discord test failed");
                  }
                }}
                disabled={testDiscord.isPending || !discordDraft.enabled}
              >
                <IconBrandDiscord className="mr-2 h-4 w-4" />
                Test Discord Notification
              </Button>
            </CardContent>
          </Card>

          {/* Saves this tab, next to what it saves. */}
          <div className="flex items-center justify-end gap-2">
            <span className="text-[12px] text-muted-foreground">
              Auto-sync and Discord settings are stored in the database and take effect immediately.
            </span>
            <Button
              onClick={saveAutomationSettings}
              disabled={updateWebhookSettings.isPending || updateDiscordSettings.isPending}
            >
              <IconCheck className="mr-2 h-4 w-4" />
              {updateWebhookSettings.isPending || updateDiscordSettings.isPending
                ? "Saving…"
                : "Save automation settings"}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="diagnostics" className="mt-4 space-y-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Connection Controls</CardTitle>
              <CardDescription className="text-neutral-400">
                Auto-connect/disconnect and runtime connection details
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Button onClick={runAutoConnect} disabled={autoConnect.isPending}>
                  <IconBolt className="mr-2 h-4 w-4" />
                  Auto Connect
                </Button>
                <Button variant="outline" onClick={runDisconnect} disabled={disconnect.isPending}>
                  <IconPlayerPause className="mr-2 h-4 w-4" />
                  Disconnect
                </Button>
              </div>
              <div className="text-sm text-neutral-300">
                SSH: {sshStatusQuery.data ? "Connected" : "Disconnected"} | Active WebSocket
                sessions: {wsStatusQuery.data?.websocket_status.active_connections ?? 0}
              </div>
            </CardContent>
          </Card>

          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-white">WebSocket Diagnostics</CardTitle>
                  <CardDescription className="text-neutral-400">
                    Active connections, timeout details, and refresh actions
                  </CardDescription>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => wsStatusQuery.refetch()}
                  disabled={wsStatusQuery.isFetching}
                >
                  <IconRefresh
                    className={`mr-2 h-4 w-4 ${wsStatusQuery.isFetching ? "animate-spin" : ""}`}
                  />
                  Refresh Status
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <Textarea
                readOnly
                className="min-h-[280px] border-neutral-800 bg-neutral-950 font-mono text-xs"
                value={JSON.stringify(
                  wsStatusQuery.data?.websocket_status ?? { status: "no data" },
                  null,
                  2
                )}
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
