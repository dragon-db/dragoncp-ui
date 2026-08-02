import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  IconAlertTriangle,
  IconDeviceFloppy,
  IconFileText,
  IconInfoCircle,
  IconLock,
  IconRotate,
} from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { SectionCard } from "@/components/layout/section-card";
import { cn } from "@/lib/utils";
import { useSettings, useUpdateSettings } from "@/hooks/useConfig";
import type { SettingDescriptor, SettingGroup } from "@/lib/api-types";

/**
 * Settings, with the boundary visible.
 *
 * Two stores and the screen says which on every row. Environment-backed
 * settings render read-only with where they come from; database-backed ones are
 * editable and take effect immediately.
 *
 * This replaces an editor that accepted every field and wrote it to a
 * per-browser session. Background threads never read that session, so most of
 * what it offered was ignored by the machinery that used it — a field that
 * silently does nothing is worse than one that says it is read-only.
 */

/** Groups with a purpose-built editor on the Automation tab. */
const HANDLED_ELSEWHERE = new Set(["automation", "notifications"]);

/** An explanation where a screenful of settings would otherwise be. */
function Notice({
  tone,
  title,
  children,
}: {
  tone: "error" | "warn" | "info";
  title: string;
  children: React.ReactNode;
}) {
  const Icon = tone === "info" ? IconInfoCircle : IconAlertTriangle;
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3.5",
        tone === "error" && "border-rose-500/35 bg-rose-500/[0.07]",
        tone === "warn" && "border-amber-500/35 bg-amber-500/[0.08]",
        tone === "info" && "border-border/60 bg-muted/20"
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 size-5 flex-none",
          tone === "error" && "text-rose-400",
          tone === "warn" && "text-amber-400",
          tone === "info" && "text-muted-foreground"
        )}
      />
      <div className="text-[13px]">
        <div
          className={cn(
            "font-medium",
            tone === "error" && "text-rose-300",
            tone === "warn" && "text-amber-400"
          )}
        >
          {title}
        </div>
        <p className="text-pretty text-muted-foreground">{children}</p>
      </div>
    </div>
  );
}

function StoreBadge({ store }: { store: "env" | "db" }) {
  if (store === "env") {
    return (
      <Badge
        variant="outline"
        className="shrink-0 gap-1 border-border/70 text-[10px] text-muted-foreground"
      >
        <IconFileText className="size-3" />
        Environment file
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className="shrink-0 gap-1 border-brand/40 bg-brand/10 text-[10px] text-brand-foreground"
    >
      Editable
    </Badge>
  );
}

function SettingRow({
  setting,
  draft,
  onChange,
}: {
  setting: SettingDescriptor;
  draft: string | number | boolean | undefined;
  onChange: (key: string, value: string | number | boolean) => void;
}) {
  const value = draft ?? setting.value;
  const readOnly = !setting.editable;
  const changed = !readOnly && String(value) !== String(setting.value);
  // The setting key is already unique across the whole panel, so it makes a
  // stable id without a counter. Without one the label was attached to nothing
  // and clicking it did not focus the field it names.
  const controlId = `setting-${setting.key}`;

  return (
    <div
      className={cn(
        "space-y-2 rounded-xl border p-3",
        readOnly ? "border-border/50 bg-muted/20" : "border-border/70 bg-background/45"
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label htmlFor={controlId} className="flex items-center gap-1.5 text-foreground/90">
          {readOnly && <IconLock className="size-3 text-muted-foreground" />}
          {setting.label}
        </Label>
        <div className="flex items-center gap-1.5">
          {changed && (
            <Badge
              variant="outline"
              className="border-amber-500/50 bg-amber-500/10 text-[10px] text-amber-300"
            >
              Unsaved
            </Badge>
          )}
          <StoreBadge store={setting.store} />
        </div>
      </div>

      {setting.kind === "boolean" ? (
        <div className="flex items-center gap-2 pt-0.5">
          <Switch
            id={controlId}
            checked={Boolean(value)}
            disabled={readOnly}
            onCheckedChange={(next) => onChange(setting.key, next)}
          />
          <span className="text-[12.5px] text-muted-foreground">{value ? "On" : "Off"}</span>
        </div>
      ) : (
        <Input
          id={controlId}
          type={setting.sensitive ? "password" : setting.kind === "number" ? "number" : "text"}
          value={String(value ?? "")}
          readOnly={readOnly}
          disabled={readOnly}
          min={setting.minimum}
          max={setting.maximum}
          placeholder={readOnly ? "Not set" : undefined}
          onChange={(event) => onChange(setting.key, event.target.value)}
          className={cn(
            "border-border/70 bg-background/70 font-mono text-[12.5px]",
            readOnly && "cursor-default text-muted-foreground"
          )}
        />
      )}

      <p className="text-[11.5px] text-muted-foreground">{setting.description}</p>

      {readOnly && (
        <p className="text-[11px] text-muted-foreground/80">
          Set in <span className="font-mono">dragoncp_env.env</span> on the server. Change it there
          and restart.
        </p>
      )}
      {!readOnly && setting.is_default && (
        <p className="text-[11px] text-muted-foreground/80">
          Using the built-in default — nothing has been saved for this yet.
        </p>
      )}
    </div>
  );
}

export function SettingsPanel() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [draft, setDraft] = useState<Record<string, string | number | boolean>>({});

  /**
   * Whether the server answered in a shape this page understands.
   *
   * A backend still running the previous code replies with a flat map and no
   * `groups` at all. Rendering nothing in that case is not tolerance, it is a
   * blank screen with no explanation — which is exactly what happened. Say what
   * is wrong instead.
   */
  const understood = Array.isArray(settings.data?.groups);

  const groups: SettingGroup[] = useMemo(() => {
    const received = settings.data?.groups;
    if (!Array.isArray(received)) return [];
    return received.filter(
      (group) => group && Array.isArray(group.settings) && !HANDLED_ELSEWHERE.has(group.id)
    );
  }, [settings.data]);

  const editableChanges = useMemo(() => {
    const all = groups.flatMap((group) => group.settings);
    const changes: Record<string, string | number | boolean> = {};
    for (const setting of all) {
      if (!setting.editable) continue;
      const next = draft[setting.key];
      if (next === undefined) continue;
      if (String(next) !== String(setting.value)) changes[setting.key] = next;
    }
    return changes;
  }, [draft, groups]);

  const changeCount = Object.keys(editableChanges).length;

  function onChange(key: string, value: string | number | boolean) {
    setDraft((previous) => ({ ...previous, [key]: value }));
  }

  function save() {
    update.mutate(editableChanges, {
      onSuccess: (result) => {
        toast.success(result.message ?? "Settings saved");
        setDraft({});
      },
      onError: (error: unknown) => {
        const message =
          (error as { response?: { data?: { message?: string } } })?.response?.data?.message ??
          "Could not save settings";
        toast.error(message);
      },
    });
  }

  if (settings.isLoading) {
    return (
      <div className="grid gap-4 xl:grid-cols-2">
        {[0, 1, 2, 3].map((card) => (
          <Skeleton key={card} className="h-64 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (settings.isError) {
    return (
      <Notice tone="error" title="Could not load settings">
        The backend did not answer. Check it is running, then reload.
      </Notice>
    );
  }

  if (!understood) {
    return (
      <Notice tone="warn" title="The backend is running an older version">
        This page asks for settings grouped by where they are stored, and the server replied with
        the previous flat format. Restart the backend to pick up the current code — the Automation
        tab is unaffected and still works.
      </Notice>
    );
  }

  if (!groups.length) {
    return (
      <Notice tone="info" title="No settings to show here">
        Auto-sync and Discord settings live on the Automation tab.
      </Notice>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {(["env", "db"] as const).map((store) => {
          const meta = settings.data?.stores?.[store];
          if (!meta) return null;
          return (
            <div
              key={store}
              className={cn(
                "rounded-xl border px-4 py-3",
                store === "env" ? "border-border/60 bg-muted/20" : "border-brand/30 bg-brand/[0.06]"
              )}
            >
              <div className="mb-1 flex items-center gap-2">
                <StoreBadge store={store} />
                <span className="text-[12.5px] font-medium">{meta.label}</span>
              </div>
              <p className="text-[11.5px] text-pretty text-muted-foreground">{meta.description}</p>
            </div>
          );
        })}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {groups.map((group) => {
          const editable = group.settings.filter((setting) => setting.editable).length;
          return (
            <SectionCard
              key={group.id}
              label={group.label}
              actions={
                <Badge
                  variant="outline"
                  className="shrink-0 border-border/70 text-[10px] text-muted-foreground tabular-nums"
                >
                  {editable > 0 ? `${editable} editable` : "Read-only"}
                </Badge>
              }
              contentClassName="space-y-3 p-3"
            >
              {group.settings.map((setting) => (
                <SettingRow
                  key={setting.key}
                  setting={setting}
                  draft={draft[setting.key]}
                  onChange={onChange}
                />
              ))}
            </SectionCard>
          );
        })}
      </div>

      <p className="text-[12px] text-muted-foreground">
        Auto-sync and Discord settings have their own controls on the Automation tab. They are
        stored the same way — in the database, effective immediately.
      </p>

      {changeCount > 0 && (
        <div className="sticky bottom-0 z-20 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card/95 px-4 py-2.5 backdrop-blur-md">
          <span className="text-[12.5px] font-medium">
            {changeCount} unsaved change{changeCount === 1 ? "" : "s"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDraft({})}>
              <IconRotate className="size-4" />
              Discard
            </Button>
            <Button size="sm" onClick={save} disabled={update.isPending}>
              <IconDeviceFloppy className="size-4" />
              {update.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
