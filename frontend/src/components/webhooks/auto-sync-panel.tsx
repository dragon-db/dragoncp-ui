import { useState, type ComponentType } from "react";
import { toast } from "sonner";
import { useUpdateWebhookSettings, useWebhookSettings } from "@/hooks/useWebhooks";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import {
  IconMovie,
  IconDeviceTv,
  IconBrandNetflix,
  IconBolt,
  IconChevronDown,
} from "@tabler/icons-react";

/**
 * Auto-sync per library, parked behind one header control so the arrivals list
 * keeps the page. The trigger carries the state — a dot per library, lit when
 * that library syncs on its own — so the popover only needs opening to change
 * something, not to check it. Each switch writes immediately.
 */

type SettingKey = "auto_sync_movies" | "auto_sync_series" | "auto_sync_anime";

interface Library {
  key: SettingKey;
  label: string;
  icon: ComponentType<{ className?: string }>;
  /** Subject of the confirmation toast. */
  noun: string;
}

const LIBRARIES: Library[] = [
  { key: "auto_sync_movies", label: "Movies", icon: IconMovie, noun: "Movies" },
  { key: "auto_sync_series", label: "TV Shows", icon: IconDeviceTv, noun: "TV shows" },
  { key: "auto_sync_anime", label: "Anime", icon: IconBrandNetflix, noun: "Anime" },
];

export function AutoSyncControl() {
  const settingsQuery = useWebhookSettings();
  const updateSettings = useUpdateWebhookSettings();
  const [pendingKey, setPendingKey] = useState<SettingKey | null>(null);

  const settings = settingsQuery.data?.settings;
  const waitSeconds = Number(settings?.series_anime_sync_wait_time ?? 60);
  const enabled = LIBRARIES.filter((library) => settings?.[library.key]);

  const toggle = async (library: Library, next: boolean) => {
    setPendingKey(library.key);
    try {
      await updateSettings.mutateAsync({ [library.key]: next });
      toast.success(
        next ? `${library.noun} will sync automatically` : `${library.noun} now need a manual sync`
      );
    } catch {
      toast.error(`Could not change auto-sync for ${library.label.toLowerCase()}`);
    } finally {
      setPendingKey(null);
    }
  };

  return (
    <Popover>
      <PopoverTrigger
        render={(props) => (
          <Button {...props} variant="outline" className="gap-2">
            <IconBolt className={cn("size-4", enabled.length > 0 && "text-brand-hover")} />
            Auto-sync
            <span className="flex items-center gap-1">
              {LIBRARIES.map((library) => (
                <span
                  key={library.key}
                  title={`${library.label}: ${settings?.[library.key] ? "on" : "off"}`}
                  className={cn(
                    "size-1.5 rounded-full transition-colors",
                    settings?.[library.key] ? "bg-brand-hover" : "bg-muted-foreground/40"
                  )}
                />
              ))}
            </span>
            <span className="font-mono text-[11px] text-muted-foreground">
              {enabled.length}/{LIBRARIES.length}
            </span>
            <IconChevronDown className="size-3.5 text-muted-foreground" />
          </Button>
        )}
      />

      <PopoverContent align="end" sideOffset={8} className="w-72 gap-0 p-0">
        <PopoverHeader className="p-3">
          <PopoverTitle className="text-[13px] font-semibold">Auto-sync</PopoverTitle>
          <PopoverDescription className="text-xs">
            Arrivals sync without asking. Off means each one waits in Media sync.
          </PopoverDescription>
        </PopoverHeader>

        <Separator />

        <div className="flex flex-col p-1.5">
          {LIBRARIES.map((library) => {
            const on = Boolean(settings?.[library.key]);
            const busy = pendingKey === library.key;
            return (
              <label
                key={library.key}
                className={cn(
                  "flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 transition-colors hover:bg-muted/40",
                  busy && "opacity-60"
                )}
              >
                <library.icon
                  className={cn(
                    "size-4 shrink-0",
                    on ? "text-brand-hover" : "text-muted-foreground"
                  )}
                />
                <span className="flex-1 text-[13px] text-foreground">{library.label}</span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {on ? "on" : "off"}
                </span>
                <Switch
                  checked={on}
                  disabled={busy || settingsQuery.isLoading}
                  onCheckedChange={(next) => toggle(library, next)}
                  aria-label={`Auto-sync ${library.label}`}
                />
              </label>
            );
          })}
        </div>

        <Separator />

        <p className="px-3 py-2 font-mono text-[10.5px] text-muted-foreground">
          TV &amp; anime wait {waitSeconds}s after the last episode.
        </p>
      </PopoverContent>
    </Popover>
  );
}
