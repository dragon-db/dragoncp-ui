import { useEffect, useMemo, useState, type ComponentType } from 'react';
import { toast } from 'sonner';
import {
  useAppConfig,
  useEnvOnlyConfig,
  useResetConfig,
  useSSHAutoConnect,
  useSSHDisconnect,
  useSSHStatus,
  useUpdateConfig,
  useWebSocketStatus,
} from '@/hooks/useConfig';
import {
  useDiscordSettings,
  useTestDiscord,
  useUpdateDiscordSettings,
  useUpdateWebhookSettings,
  useWebhookSettings,
} from '@/hooks/useWebhooks';
import { useRuntimeStore } from '@/stores/runtime';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  IconArchive,
  IconBolt,
  IconBrandDiscord,
  IconCheck,
  IconClock,
  IconLink,
  IconPlayerPause,
  IconRefresh,
  IconServer,
  IconSettings,
  IconWebhook,
} from '@tabler/icons-react';
import type { AppConfig } from '@/lib/api-types';

type AppConfigKey = Extract<keyof AppConfig, string>;
type ConfigField = { key: AppConfigKey; label: string; type?: 'password' | 'number' };

const configFields: ConfigField[] = [
  { key: 'REMOTE_IP', label: 'Server Host/IP' },
  { key: 'REMOTE_USER', label: 'SSH Username' },
  { key: 'REMOTE_PASSWORD', label: 'SSH Password', type: 'password' },
  { key: 'SSH_KEY_PATH', label: 'SSH Key Path' },
  { key: 'MOVIE_PATH', label: 'Movie Source Path' },
  { key: 'TVSHOW_PATH', label: 'TV Show Source Path' },
  { key: 'ANIME_PATH', label: 'Anime Source Path' },
  { key: 'BACKUP_PATH', label: 'Backup Source Path' },
  { key: 'MOVIE_DEST_PATH', label: 'Movie Destination Path' },
  { key: 'TVSHOW_DEST_PATH', label: 'TV Show Destination Path' },
  { key: 'ANIME_DEST_PATH', label: 'Anime Destination Path' },
  { key: 'DISK_PATH_1', label: 'Disk Path 1' },
  { key: 'DISK_PATH_2', label: 'Disk Path 2' },
  { key: 'DISK_PATH_3', label: 'Disk Path 3' },
  { key: 'DISK_API_ENDPOINT', label: 'Remote Disk API Endpoint' },
  { key: 'DISK_API_TOKEN', label: 'Remote Disk API Token', type: 'password' },
  { key: 'WEBSOCKET_TIMEOUT_MINUTES', label: 'WebSocket Timeout (minutes)', type: 'number' },
];

interface ConfigGroup {
  id: string;
  title: string;
  description: string;
  icon: ComponentType<{ className?: string }>;
  keys: Array<AppConfigKey>;
}

const configFieldByKey = configFields.reduce(
  (acc, field) => {
    acc[field.key] = field;
    return acc;
  },
  {} as Partial<Record<AppConfigKey, ConfigField>>
);

const configGroups: ConfigGroup[] = [
  {
    id: 'connection',
    title: 'Connection & Access',
    description: 'Remote host credentials and session timeout behavior.',
    icon: IconServer,
    keys: ['REMOTE_IP', 'REMOTE_USER', 'REMOTE_PASSWORD', 'SSH_KEY_PATH', 'WEBSOCKET_TIMEOUT_MINUTES'],
  },
  {
    id: 'sources',
    title: 'Source Paths',
    description: 'Primary media source locations watched by Dragon-CP.',
    icon: IconLink,
    keys: ['MOVIE_PATH', 'TVSHOW_PATH', 'ANIME_PATH', 'BACKUP_PATH'],
  },
  {
    id: 'destinations',
    title: 'Destination Paths',
    description: 'Target folders where synced content is written.',
    icon: IconArchive,
    keys: ['MOVIE_DEST_PATH', 'TVSHOW_DEST_PATH', 'ANIME_DEST_PATH'],
  },
  {
    id: 'storage',
    title: 'Storage & Disk API',
    description: 'Disk mounts and remote usage endpoint configuration.',
    icon: IconSettings,
    keys: ['DISK_PATH_1', 'DISK_PATH_2', 'DISK_PATH_3', 'DISK_API_ENDPOINT', 'DISK_API_TOKEN'],
  },
];

const criticalKeys: Array<AppConfigKey> = [
  'REMOTE_IP',
  'REMOTE_USER',
  'REMOTE_PASSWORD',
  'SSH_KEY_PATH',
  'WEBSOCKET_TIMEOUT_MINUTES',
];

function normalizeValue(value: string | number | undefined) {
  if (value === undefined || value === null) return '';
  return String(value);
}

function wasCriticalConfigChanged(baseConfig: AppConfig | undefined, draft: Record<string, string>) {
  if (!baseConfig) return false;
  return criticalKeys.some((key) => normalizeValue(baseConfig[key]) !== normalizeValue(draft[key]));
}

function fieldValue(draft: Record<string, string>, key: AppConfigKey) {
  return draft[key as string] ?? '';
}

export function SettingsPage() {
  const configQuery = useAppConfig();
  const envConfigQuery = useEnvOnlyConfig();
  const webhookSettingsQuery = useWebhookSettings();
  const discordSettingsQuery = useDiscordSettings();
  const sshStatusQuery = useSSHStatus();
  const wsStatusQuery = useWebSocketStatus();

  const updateConfig = useUpdateConfig();
  const resetConfig = useResetConfig();
  const updateWebhookSettings = useUpdateWebhookSettings();
  const updateDiscordSettings = useUpdateDiscordSettings();
  const testDiscord = useTestDiscord();

  const autoConnect = useSSHAutoConnect();
  const disconnect = useSSHDisconnect();

  const setConfigChanged = useRuntimeStore((state) => state.setConfigChanged);

  const [draftConfig, setDraftConfig] = useState<Record<string, string>>({});
  const [webhookDraft, setWebhookDraft] = useState({
    auto_sync_movies: false,
    auto_sync_series: false,
    auto_sync_anime: false,
    series_anime_sync_wait_time: '60',
  });
  const [discordDraft, setDiscordDraft] = useState({
    enabled: false,
    webhook_url: '',
    app_url: '',
    icon_url: '',
    manual_sync_thumbnail_url: '',
  });

  useEffect(() => {
    if (!configQuery.data) return;
    const next: Record<string, string> = {};
    for (const field of configFields) {
      next[field.key as string] = normalizeValue(configQuery.data[field.key]);
    }
    setDraftConfig(next);
  }, [configQuery.data]);

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
      webhook_url: settings.webhook_url ?? '',
      app_url: settings.app_url ?? '',
      icon_url: settings.icon_url ?? '',
      manual_sync_thumbnail_url: settings.manual_sync_thumbnail_url ?? '',
    });
  }, [discordSettingsQuery.data]);

  const modifiedCount = useMemo(() => {
    if (!envConfigQuery.data) return 0;
    return configFields.reduce((count, field) => {
      const key = field.key as string;
      const envValue = normalizeValue(envConfigQuery.data?.[field.key]);
      const currentValue = normalizeValue(draftConfig[key]);
      return count + (envValue !== currentValue ? 1 : 0);
    }, 0);
  }, [draftConfig, envConfigQuery.data]);

  const connectionState = sshStatusQuery.data ? 'Connected' : 'Disconnected';
  const timeoutCurrent = draftConfig.WEBSOCKET_TIMEOUT_MINUTES || '30';

  const saveAllSettings = async () => {
    try {
      const configPayload: Record<string, string | number> = { ...draftConfig };
      if (configPayload.WEBSOCKET_TIMEOUT_MINUTES !== undefined) {
        const timeout = Number(configPayload.WEBSOCKET_TIMEOUT_MINUTES);
        configPayload.WEBSOCKET_TIMEOUT_MINUTES = Number.isFinite(timeout) ? Math.min(60, Math.max(5, timeout)) : 30;
      }

      await updateConfig.mutateAsync(configPayload as Partial<AppConfig>);

      await updateWebhookSettings.mutateAsync({
        auto_sync_movies: webhookDraft.auto_sync_movies,
        auto_sync_series: webhookDraft.auto_sync_series,
        auto_sync_anime: webhookDraft.auto_sync_anime,
        series_anime_sync_wait_time: Math.max(1, Number(webhookDraft.series_anime_sync_wait_time) || 60),
      });

      await updateDiscordSettings.mutateAsync({
        enabled: discordDraft.enabled,
        webhook_url: discordDraft.webhook_url,
        app_url: discordDraft.app_url,
        icon_url: discordDraft.icon_url,
        manual_sync_thumbnail_url: discordDraft.manual_sync_thumbnail_url,
      });

      const criticalChanged = wasCriticalConfigChanged(configQuery.data, draftConfig);
      setConfigChanged(criticalChanged);

      if (criticalChanged) {
        toast.info('Critical configuration changed. Reconnect is required to apply updates.');
      } else {
        toast.success('Settings saved');
      }

      configQuery.refetch();
      envConfigQuery.refetch();
      webhookSettingsQuery.refetch();
      discordSettingsQuery.refetch();
      wsStatusQuery.refetch();
    } catch {
      toast.error('Failed to save settings');
    }
  };

  const resetToEnv = async () => {
    try {
      await resetConfig.mutateAsync();
      await Promise.all([
        configQuery.refetch(),
        envConfigQuery.refetch(),
        webhookSettingsQuery.refetch(),
        discordSettingsQuery.refetch(),
      ]);
      setConfigChanged(false);
      toast.success('Configuration reset to environment values');
    } catch {
      toast.error('Failed to reset configuration');
    }
  };

  const runAutoConnect = async () => {
    try {
      await autoConnect.mutateAsync();
      setConfigChanged(false);
      sshStatusQuery.refetch();
      toast.success('Connected');
    } catch {
      toast.error('Connection failed');
    }
  };

  const runDisconnect = async () => {
    try {
      await disconnect.mutateAsync();
      sshStatusQuery.refetch();
      toast.success('Disconnected');
    } catch {
      toast.error('Failed to disconnect');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold text-white">Settings</h1>
          <p className="text-neutral-400 mt-1">Full static-equivalent configuration surface</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={resetToEnv} disabled={resetConfig.isPending}>
            <IconRefresh className={`h-4 w-4 mr-2 ${resetConfig.isPending ? 'animate-spin' : ''}`} />
            Reset to Env
          </Button>
          <Button onClick={saveAllSettings} disabled={updateConfig.isPending || updateWebhookSettings.isPending || updateDiscordSettings.isPending}>
            <IconCheck className="h-4 w-4 mr-2" />
            Save All
          </Button>
        </div>
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-border/70 bg-card/80 px-4 py-3">
          <div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-muted-foreground">
            <IconServer className="h-3.5 w-3.5" />
            SSH
          </div>
          <div className="mt-1 text-sm font-semibold text-foreground">{connectionState}</div>
        </div>
        <div className="rounded-xl border border-border/70 bg-card/80 px-4 py-3">
          <div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-muted-foreground">
            <IconClock className="h-3.5 w-3.5" />
            Timeout
          </div>
          <div className="mt-1 text-sm font-semibold text-foreground tabular-nums">{timeoutCurrent} min</div>
        </div>
        <div className="rounded-xl border border-border/70 bg-card/80 px-4 py-3">
          <div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-muted-foreground">
            <IconSettings className="h-3.5 w-3.5" />
            Modified
          </div>
          <div className="mt-1 text-sm font-semibold text-foreground tabular-nums">{modifiedCount} fields</div>
        </div>
        <div className="rounded-xl border border-border/70 bg-card/80 px-4 py-3">
          <div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-muted-foreground">
            <IconLink className="h-3.5 w-3.5" />
            WebSockets
          </div>
          <div className="mt-1 text-sm font-semibold text-foreground tabular-nums">
            {wsStatusQuery.data?.websocket_status.active_connections ?? 0} active
          </div>
        </div>
      </div>

      <Tabs defaultValue="config" className="gap-5">
        <TabsList
          variant="default"
          className="grid w-full max-w-3xl grid-cols-3 items-stretch rounded-xl border border-border/65 bg-card/75 p-1 group-data-[orientation=horizontal]/tabs:h-auto"
        >
          <TabsTrigger
            value="config"
            className="h-8 self-stretch gap-1.5 rounded-lg border border-transparent px-3 text-[13px] font-semibold text-muted-foreground transition-colors hover:text-foreground data-active:border-border/80 data-active:bg-background/90 data-active:text-foreground [&_svg]:h-3.5 [&_svg]:w-3.5"
          >
            <IconSettings className="h-4 w-4" />
            Core Config
          </TabsTrigger>
          <TabsTrigger
            value="automation"
            className="h-8 self-stretch gap-1.5 rounded-lg border border-transparent px-3 text-[13px] font-semibold text-muted-foreground transition-colors hover:text-foreground data-active:border-border/80 data-active:bg-background/90 data-active:text-foreground [&_svg]:h-3.5 [&_svg]:w-3.5"
          >
            <IconWebhook className="h-4 w-4" />
            Automation
          </TabsTrigger>
          <TabsTrigger
            value="diagnostics"
            className="h-8 self-stretch gap-1.5 rounded-lg border border-transparent px-3 text-[13px] font-semibold text-muted-foreground transition-colors hover:text-foreground data-active:border-border/80 data-active:bg-background/90 data-active:text-foreground [&_svg]:h-3.5 [&_svg]:w-3.5"
          >
            <IconServer className="h-4 w-4" />
            Diagnostics
          </TabsTrigger>
        </TabsList>

        <TabsContent value="config" className="mt-4 space-y-4">
          <div className="grid gap-4 xl:grid-cols-2">
            {configGroups.map((group) => {
              const GroupIcon = group.icon;
              const groupModifiedCount = group.keys.reduce((count, key) => {
                const envValue = normalizeValue(envConfigQuery.data?.[key]);
                const currentValue = normalizeValue(draftConfig[key as string]);
                return count + (envValue !== currentValue ? 1 : 0);
              }, 0);

              return (
                <Card key={group.id} className="border-border/70 bg-card/85">
                  <CardHeader className="border-b border-border/60 pb-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-3">
                        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/12 text-primary">
                          <GroupIcon className="h-4 w-4" />
                        </span>
                        <div>
                          <CardTitle className="text-base text-foreground">{group.title}</CardTitle>
                          <CardDescription className="mt-1 text-muted-foreground">{group.description}</CardDescription>
                        </div>
                      </div>
                      <Badge variant="outline" className="shrink-0 border-border/70 text-muted-foreground tabular-nums">
                        {groupModifiedCount} modified
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3 pt-4">
                    {group.keys.map((fieldKey) => {
                      const field = configFieldByKey[fieldKey];
                      if (!field) return null;

                      const key = field.key as string;
                      const envValue = normalizeValue(envConfigQuery.data?.[field.key]);
                      const currentValue = normalizeValue(draftConfig[key]);
                      const changed = envValue !== currentValue;

                      return (
                        <div key={key} className="space-y-2 rounded-xl border border-border/70 bg-background/45 p-3">
                          <div className="flex items-center justify-between gap-2">
                            <Label className="text-foreground/90">{field.label}</Label>
                            {changed && (
                              <Badge variant="outline" className="border-amber-500/50 bg-amber-500/10 text-amber-300">
                                Modified
                              </Badge>
                            )}
                          </div>
                          <Input
                            type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
                            value={fieldValue(draftConfig, field.key)}
                            onChange={(event) =>
                              setDraftConfig((previous) => ({
                                ...previous,
                                [key]: event.target.value,
                              }))
                            }
                            min={field.key === 'WEBSOCKET_TIMEOUT_MINUTES' ? 5 : undefined}
                            max={field.key === 'WEBSOCKET_TIMEOUT_MINUTES' ? 60 : undefined}
                            className="border-border/70 bg-background/70"
                          />
                          <div className="text-xs text-muted-foreground">Env: {envValue || 'Not set'}</div>
                        </div>
                      );
                    })}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </TabsContent>

        <TabsContent value="automation" className="mt-4 space-y-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Webhook Auto-Sync</CardTitle>
              <CardDescription className="text-neutral-400">Control movie/series/anime auto-sync behavior and wait window</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Auto-sync Movies</div>
                  <div className="text-xs text-neutral-500">Trigger sync automatically for movie webhooks</div>
                </div>
                <Switch
                  checked={webhookDraft.auto_sync_movies}
                  onCheckedChange={(checked) => setWebhookDraft((previous) => ({ ...previous, auto_sync_movies: checked }))}
                />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Auto-sync TV Shows</div>
                  <div className="text-xs text-neutral-500">Trigger sync automatically for series webhooks</div>
                </div>
                <Switch
                  checked={webhookDraft.auto_sync_series}
                  onCheckedChange={(checked) => setWebhookDraft((previous) => ({ ...previous, auto_sync_series: checked }))}
                />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Auto-sync Anime</div>
                  <div className="text-xs text-neutral-500">Trigger sync automatically for anime webhooks</div>
                </div>
                <Switch
                  checked={webhookDraft.auto_sync_anime}
                  onCheckedChange={(checked) => setWebhookDraft((previous) => ({ ...previous, auto_sync_anime: checked }))}
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
                  className="w-48 bg-neutral-900 border-neutral-700"
                />
              </div>
            </CardContent>
          </Card>

          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Discord Settings</CardTitle>
              <CardDescription className="text-neutral-400">Notification webhook, app links, and branding settings</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Enable Discord Notifications</div>
                  <div className="text-xs text-neutral-500">Send transfer and sync notifications to Discord</div>
                </div>
                <Switch
                  checked={discordDraft.enabled}
                  onCheckedChange={(checked) => setDiscordDraft((previous) => ({ ...previous, enabled: checked }))}
                />
              </div>
              <Input
                placeholder="Discord Webhook URL"
                value={discordDraft.webhook_url}
                onChange={(event) => setDiscordDraft((previous) => ({ ...previous, webhook_url: event.target.value }))}
                className="bg-neutral-900 border-neutral-700"
              />
              <Input
                placeholder="App URL"
                value={discordDraft.app_url}
                onChange={(event) => setDiscordDraft((previous) => ({ ...previous, app_url: event.target.value }))}
                className="bg-neutral-900 border-neutral-700"
              />
              <Input
                placeholder="Icon URL"
                value={discordDraft.icon_url}
                onChange={(event) => setDiscordDraft((previous) => ({ ...previous, icon_url: event.target.value }))}
                className="bg-neutral-900 border-neutral-700"
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
                className="bg-neutral-900 border-neutral-700"
              />
              <Button
                variant="outline"
                onClick={async () => {
                  try {
                    await testDiscord.mutateAsync();
                    toast.success('Discord test notification sent');
                  } catch {
                    toast.error('Discord test failed');
                  }
                }}
                disabled={testDiscord.isPending || !discordDraft.enabled}
              >
                <IconBrandDiscord className="h-4 w-4 mr-2" />
                Test Discord Notification
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="diagnostics" className="mt-4 space-y-4">
          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <CardTitle className="text-white">Connection Controls</CardTitle>
              <CardDescription className="text-neutral-400">Auto-connect/disconnect and runtime connection details</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Button onClick={runAutoConnect} disabled={autoConnect.isPending}>
                  <IconBolt className="h-4 w-4 mr-2" />
                  Auto Connect
                </Button>
                <Button variant="outline" onClick={runDisconnect} disabled={disconnect.isPending}>
                  <IconPlayerPause className="h-4 w-4 mr-2" />
                  Disconnect
                </Button>
              </div>
              <div className="text-sm text-neutral-300">
                SSH: {sshStatusQuery.data ? 'Connected' : 'Disconnected'} | Active WebSocket sessions:{' '}
                {wsStatusQuery.data?.websocket_status.active_connections ?? 0}
              </div>
            </CardContent>
          </Card>

          <Card className="border-neutral-800 bg-neutral-900/50">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-white">WebSocket Diagnostics</CardTitle>
                  <CardDescription className="text-neutral-400">Active connections, timeout details, and refresh actions</CardDescription>
                </div>
                <Button variant="outline" size="sm" onClick={() => wsStatusQuery.refetch()} disabled={wsStatusQuery.isFetching}>
                  <IconRefresh className={`h-4 w-4 mr-2 ${wsStatusQuery.isFetching ? 'animate-spin' : ''}`} />
                  Refresh Status
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <Textarea
                readOnly
                className="min-h-[280px] bg-neutral-950 border-neutral-800 font-mono text-xs"
                value={JSON.stringify(wsStatusQuery.data?.websocket_status ?? { status: 'no data' }, null, 2)}
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
