import { IconBroadcast, IconFlask, IconWifi, IconWifiOff } from "@tabler/icons-react";
import { Switch } from "@/components/ui/switch";
import { SectionCard } from "@/components/layout/section-card";
import { useTestMode, useWebSocketStatus } from "@/hooks/useConfig";
import type { SettingDescriptor } from "@/lib/api-types";
import {
  EnvNote,
  EnvValue,
  Fact,
  FactGrid,
  NumberSetting,
  SettingList,
  SettingRow,
  ToneIcon,
} from "./settings-bits";
import { PLACED_KEYS, useSaveSetting, useSettingMap } from "./settings-model";
import { BackendLogPanel } from "./backend-log-panel";

function minutes(value: number) {
  if (value <= 0) return "just now";
  return value === 1 ? "1 min ago" : `${value} min ago`;
}

function RuntimeSection() {
  const testMode = useTestMode();
  const { map } = useSettingMap();
  const { save, saving } = useSaveSetting();
  const timeout = map.get("WEBSOCKET_TIMEOUT_MINUTES");

  return (
    <SectionCard label="Runtime" description="How this DragonCP process is running.">
      <SettingList>
        <SettingRow
          inline
          label="Test mode"
          icon={<ToneIcon icon={IconFlask} tone={testMode ? "warn" : "muted"} />}
          description={
            testMode
              ? "On: transfers are rehearsed and nothing is written. Deleting or moving files on the Backups page still acts on the real backup folder."
              : "Off: transfers write to disk."
          }
        >
          <EnvValue value={testMode ? "On" : "Off"} mono={false} />
        </SettingRow>
        <SettingRow
          label="Live updates time out after"
          htmlFor="realtime-timeout"
          icon={<ToneIcon icon={IconBroadcast} tone="muted" />}
          description="How long a browser's live connection stays open with nothing happening. Pages go back to polling when it closes. Applies from the next live connection."
        >
          <NumberSetting
            id="realtime-timeout"
            value={timeout?.value as number | undefined}
            unit="minutes"
            min={timeout?.minimum}
            max={timeout?.maximum}
            disabled={!timeout || saving}
            onSave={(next) =>
              save("WEBSOCKET_TIMEOUT_MINUTES", next, `Live updates time out after ${next} minutes`)
            }
          />
        </SettingRow>
      </SettingList>
      <EnvNote>
        Test mode comes from <span className="font-mono">TEST_MODE</span> in the environment when
        DragonCP starts.
      </EnvNote>
    </SectionCard>
  );
}

/** Browsers holding a live connection right now, as rows rather than a dump. */
function ConnectionsSection() {
  const query = useWebSocketStatus();
  const status = query.data?.websocket_status;
  const rows = status?.connection_details ?? [];

  return (
    <SectionCard
      label="Live connections"
      description={
        status && status.active_connections > 0
          ? `${status.active_connections} ${status.active_connections === 1 ? "browser" : "browsers"} receiving live updates.`
          : "Browsers receiving live updates."
      }
    >
      {query.isError ? (
        <p className="px-4 py-4 text-[13px] text-rose-300">
          Could not read the live connections. Reload once the backend answers.
        </p>
      ) : query.isLoading ? (
        <p className="px-4 py-4 text-[13px] text-muted-foreground">Reading live connections…</p>
      ) : rows.length === 0 ? (
        <SettingList>
          <SettingRow
            label="No browser is connected live"
            icon={<ToneIcon icon={IconWifiOff} tone="muted" />}
            description="Pages still refresh by polling. Turn live updates on from the status pill in the header."
          />
        </SettingList>
      ) : (
        <SettingList>
          {rows.map((row) => (
            <SettingRow
              key={row.session_id}
              label={<span className="font-mono text-[12.5px]">{row.session_id}</span>}
              icon={<ToneIcon icon={IconWifi} tone="ok" />}
              description={`Connected ${minutes(row.connected_minutes_ago)}, last active ${minutes(row.last_activity_minutes_ago)}. Closes after ${row.timeout_minutes} min idle.`}
            />
          ))}
        </SettingList>
      )}
    </SectionCard>
  );
}

function DisksSection() {
  const { map } = useSettingMap();
  return (
    <SectionCard
      label="Disk usage"
      description="The disks whose free space the dashboard's storage strip shows."
    >
      <FactGrid>
        {(["DISK_PATH_1", "DISK_PATH_2", "DISK_PATH_3"] as const).map((key, index) => (
          <Fact key={key} label={`Disk ${index + 1}`} value={map.get(key)?.value} />
        ))}
        <Fact
          label="Remote server's disk"
          value={map.get("DISK_API_ENDPOINT")?.value}
          hint="An address on the remote server that reports its free space."
        />
      </FactGrid>
      <EnvNote />
    </SectionCard>
  );
}

/**
 * A setting the server describes that no tab places. Nothing is meant to land
 * here today; it exists so a new setting shows up somewhere the day it ships.
 */
function OtherRow({ setting }: { setting: SettingDescriptor }) {
  const { save, saving } = useSaveSetting();
  const id = `setting-${setting.key}`;
  let control;
  if (!setting.editable) {
    control = <EnvValue value={setting.value} />;
  } else if (setting.kind === "boolean") {
    control = (
      <Switch
        id={id}
        checked={Boolean(setting.value)}
        disabled={saving}
        onCheckedChange={(next) => save(setting.key, next, `${setting.label} saved`)}
      />
    );
  } else if (setting.kind === "number") {
    control = (
      <NumberSetting
        id={id}
        value={setting.value as number}
        min={setting.minimum}
        max={setting.maximum}
        disabled={saving}
        onSave={(next) => save(setting.key, next, `${setting.label} saved`)}
      />
    );
  } else {
    control = <EnvValue value={setting.value} />;
  }
  return (
    <SettingRow label={setting.label} description={setting.description} htmlFor={id}>
      {control}
    </SettingRow>
  );
}

function OtherSection() {
  const { map } = useSettingMap();
  const others = [...map.values()].filter((setting) => !PLACED_KEYS.has(setting.key));
  if (others.length === 0) return null;
  return (
    <SectionCard label="Other settings" description="Settings no other tab shows yet.">
      <SettingList>
        {others.map((setting) => (
          <OtherRow key={setting.key} setting={setting} />
        ))}
      </SettingList>
      <EnvNote />
    </SectionCard>
  );
}

export function SystemTab() {
  return (
    <div className="space-y-4">
      <RuntimeSection />
      <ConnectionsSection />
      <DisksSection />
      <BackendLogPanel />
      <OtherSection />
    </div>
  );
}
