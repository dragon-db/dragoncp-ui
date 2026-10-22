import { IconFlask } from "@tabler/icons-react";
import { Switch } from "@/components/ui/switch";
import { SectionCard } from "@/components/layout/section-card";
import { useTestMode } from "@/hooks/useConfig";
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

function RuntimeSection() {
  const testMode = useTestMode();

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
      </SettingList>
      <EnvNote>
        Test mode comes from <span className="font-mono">TEST_MODE</span> in the environment when
        DragonCP starts.
      </EnvNote>
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
      <DisksSection />
      <OtherSection />
    </div>
  );
}
