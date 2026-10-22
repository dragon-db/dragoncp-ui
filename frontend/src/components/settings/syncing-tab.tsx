import { toast } from "sonner";
import {
  IconArchive,
  IconArrowDown,
  IconArrowRight,
  IconBrandNetflix,
  IconClockHour4,
  IconDeviceTv,
  IconMovie,
} from "@tabler/icons-react";
import { Switch } from "@/components/ui/switch";
import { SectionCard } from "@/components/layout/section-card";
import { useUpdateWebhookSettings, useWebhookSettings } from "@/hooks/useWebhooks";
import { errorText } from "@/lib/api-error";
import {
  EnvNote,
  EnvValue,
  NumberSetting,
  SettingList,
  SettingRow,
  ToneIcon,
} from "./settings-bits";
import { useSaveSetting, useSettingMap } from "./settings-model";

type AutoSyncKey = "auto_sync_movies" | "auto_sync_series" | "auto_sync_anime";

/** The three libraries, in the order and with the icons the sidebar uses. */
const LIBRARIES = [
  {
    id: "movies",
    label: "Movies",
    icon: IconMovie,
    autoSync: "auto_sync_movies" as AutoSyncKey,
    on: "a film syncs as soon as Radarr imports it.",
    remote: "MOVIE_PATH",
    local: "MOVIE_DEST_PATH",
  },
  {
    id: "tvshows",
    label: "TV shows",
    icon: IconDeviceTv,
    autoSync: "auto_sync_series" as AutoSyncKey,
    on: "a season syncs once Sonarr has nothing more on the way for it.",
    remote: "TVSHOW_PATH",
    local: "TVSHOW_DEST_PATH",
  },
  {
    id: "anime",
    label: "Anime",
    icon: IconBrandNetflix,
    autoSync: "auto_sync_anime" as AutoSyncKey,
    on: "a season syncs once Sonarr has nothing more on the way for it.",
    remote: "ANIME_PATH",
    local: "ANIME_DEST_PATH",
  },
];

const OFF = "Off: imports wait on the Webhooks page until you press Sync.";

function AutoSyncSection() {
  const settingsQuery = useWebhookSettings();
  const update = useUpdateWebhookSettings();
  const settings = settingsQuery.data?.settings;
  const { map } = useSettingMap();
  const wait = map.get("SERIES_ANIME_SYNC_WAIT_TIME");

  const set = async (key: AutoSyncKey, label: string, next: boolean) => {
    try {
      await update.mutateAsync({ [key]: next });
      toast.success(next ? `${label} sync by themselves` : `${label} wait for you to press Sync`);
    } catch (error) {
      toast.error(errorText(error, `Could not change auto-sync for ${label.toLowerCase()}`));
    }
  };

  return (
    <SectionCard
      label="Automatic sync"
      description="What happens when Sonarr or Radarr reports an import. Auto-sync on the Webhooks page changes the same switches."
    >
      {settingsQuery.isError ? (
        <p className="px-4 py-4 text-[13px] text-rose-300">
          Could not read the auto-sync settings. Reload once the backend answers.
        </p>
      ) : (
        <SettingList>
          {LIBRARIES.map((library) => {
            const on = Boolean(settings?.[library.autoSync]);
            const id = `auto-sync-${library.id}`;
            return (
              <SettingRow
                key={library.id}
                inline
                label={library.label}
                htmlFor={id}
                icon={<ToneIcon icon={library.icon} tone={on ? "brand" : "muted"} />}
                description={on ? `On: ${library.on}` : OFF}
              >
                <Switch
                  id={id}
                  checked={on}
                  disabled={!settings || update.isPending}
                  onCheckedChange={(next) => set(library.autoSync, library.label, next)}
                />
              </SettingRow>
            );
          })}
          <SettingRow
            label="Fallback wait"
            htmlFor="fallback-wait"
            icon={<ToneIcon icon={IconClockHour4} tone="muted" />}
            description="Only used when Sonarr can't be asked: how long a season waits for more episodes before it syncs, up to 15 minutes in all."
          >
            <NumberSetting
              id="fallback-wait"
              value={settings?.series_anime_sync_wait_time ?? (wait?.value as number | undefined)}
              unit="seconds"
              min={wait?.minimum ?? 30}
              max={wait?.maximum ?? 900}
              disabled={!settings || update.isPending}
              onSave={async (next) => {
                try {
                  await update.mutateAsync({ series_anime_sync_wait_time: next });
                  toast.success(`Fallback wait is ${next} seconds`);
                  return true;
                } catch (error) {
                  toast.error(errorText(error, "Could not save the fallback wait"));
                  return false;
                }
              }}
            />
          </SettingRow>
        </SettingList>
      )}
    </SectionCard>
  );
}

/**
 * Where each library is copied from and to. Shown as a pair with the direction
 * of the copy between them, because that pair is what a library is here.
 */
function FoldersSection() {
  const { map } = useSettingMap();
  return (
    <SectionCard
      label="Library folders"
      description="Where each library is copied from, and where it lands on this machine."
    >
      <div className="hidden grid-cols-[9rem_minmax(0,1fr)_1rem_minmax(0,1fr)] gap-x-4 px-4 pt-2.5 text-[11.5px] text-muted-foreground sm:grid">
        <span />
        <span>On the remote server</span>
        <span />
        <span>On this machine</span>
      </div>
      <SettingList>
        {LIBRARIES.map((library) => (
          <div
            key={library.id}
            className="grid gap-x-4 gap-y-1.5 px-4 py-3 sm:grid-cols-[9rem_minmax(0,1fr)_1rem_minmax(0,1fr)] sm:items-center"
          >
            <div className="flex items-center gap-2.5 text-[13.5px] font-medium text-foreground">
              <ToneIcon icon={library.icon} tone="muted" />
              {library.label}
            </div>
            <EnvValue value={map.get(library.remote)?.value} />
            <IconArrowRight
              className="hidden size-4 text-brand-hover sm:block"
              aria-label="copied to"
            />
            <div className="flex items-center gap-1.5 sm:block">
              <IconArrowDown className="size-3.5 shrink-0 text-brand-hover sm:hidden" aria-hidden />
              <EnvValue value={map.get(library.local)?.value} />
            </div>
          </div>
        ))}
        <SettingRow
          stack
          label="Backups"
          description="Every file a sync replaces or removes is moved here first, so it can be put back."
          icon={<ToneIcon icon={IconArchive} tone="muted" />}
        >
          <EnvValue value={map.get("BACKUP_PATH")?.value} />
        </SettingRow>
      </SettingList>
      <EnvNote />
    </SectionCard>
  );
}

function RetentionSection() {
  const { map } = useSettingMap();
  const { save, saving } = useSaveSetting();
  const enabled = map.get("BACKUP_RETENTION_ENABLED");
  const keep = map.get("BACKUP_RETENTION_KEEP");
  const grace = map.get("BACKUP_RETENTION_GRACE_HOURS");
  const on = Boolean(enabled?.value);

  return (
    <SectionCard
      label="Backup retention"
      description="How many replaced versions of each movie or episode are kept. Runs after each sync and records every version it deletes."
    >
      <SettingList>
        <SettingRow
          inline
          label="Delete old versions"
          htmlFor="retention-enabled"
          description={
            on
              ? "On: only the newest are kept. Pinned versions and ones inside the grace period never go."
              : "Off: every version is kept until you delete it on the Backups page."
          }
        >
          <Switch
            id="retention-enabled"
            checked={on}
            disabled={!enabled || saving}
            onCheckedChange={(next) =>
              save(
                "BACKUP_RETENTION_ENABLED",
                next,
                next ? "Old versions will be deleted" : "Every version will be kept"
              )
            }
          />
        </SettingRow>
        <SettingRow
          label="Versions to keep"
          htmlFor="retention-keep"
          description="Per movie or episode, newest first."
        >
          <NumberSetting
            id="retention-keep"
            value={keep?.value as number | undefined}
            min={keep?.minimum}
            max={keep?.maximum}
            disabled={!keep || saving || !on}
            onSave={(next) => save("BACKUP_RETENTION_KEEP", next, `Keeping ${next} versions`)}
          />
        </SettingRow>
        <SettingRow
          label="Grace period"
          htmlFor="retention-grace"
          description="A new version is safe this long, so an accidental sync can't push out the copy you wanted."
        >
          <NumberSetting
            id="retention-grace"
            value={grace?.value as number | undefined}
            unit="hours"
            min={grace?.minimum}
            max={grace?.maximum}
            disabled={!grace || saving || !on}
            onSave={(next) =>
              save("BACKUP_RETENTION_GRACE_HOURS", next, `Grace period is ${next} hours`)
            }
          />
        </SettingRow>
      </SettingList>
    </SectionCard>
  );
}

export function SyncingTab() {
  return (
    <div className="space-y-4">
      <AutoSyncSection />
      <FoldersSection />
      <RetentionSection />
    </div>
  );
}
