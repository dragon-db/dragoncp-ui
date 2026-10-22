import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { errorText } from "@/lib/api-error";
import { useSettings, useUpdateSettings } from "@/hooks/useConfig";
import type { SettingDescriptor } from "@/lib/api-types";

/** What the Settings tabs share that is not a component: tones, and reading and saving. */

export type Tone = "ok" | "warn" | "crit" | "brand" | "muted";

export const TONE_CHIP: Record<Tone, string> = {
  ok: "border-emerald-500/30 bg-emerald-500/12 text-emerald-300",
  warn: "border-amber-500/30 bg-amber-500/12 text-amber-300",
  crit: "border-rose-500/30 bg-rose-500/12 text-rose-300",
  brand: "border-brand/35 bg-brand/15 text-brand-hover",
  muted: "border-border bg-black/25 text-muted-foreground",
};

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-emerald-300",
  warn: "text-amber-300",
  crit: "text-rose-300",
  brand: "text-brand-foreground",
  muted: "text-muted-foreground",
};

/** Every setting the server describes, by key, for tabs that pick their own. */
export function useSettingMap() {
  const settings = useSettings();
  const map = useMemo(() => {
    const out = new Map<string, SettingDescriptor>();
    for (const group of settings.data?.groups ?? []) {
      for (const setting of group.settings ?? []) out.set(setting.key, setting);
    }
    return out;
  }, [settings.data]);
  return { ...settings, map };
}

/** Save one database setting now, with a toast that says what happened. */
export function useSaveSetting() {
  const update = useUpdateSettings();
  const save = async (key: string, value: string | number | boolean, done: string) => {
    try {
      await update.mutateAsync({ [key]: value });
      toast.success(done);
      return true;
    } catch (error) {
      toast.error(errorText(error, "Could not save that setting"));
      return false;
    }
  };
  return { save, saving: update.isPending };
}

/**
 * Every setting a tab shows in its own place. Anything the server describes
 * that is not here lands in System, under Other settings, so a key added to
 * the registry later is never invisible.
 */
export const PLACED_KEYS = new Set([
  // Remote server
  "SSH_AUTO_CONNECT",
  "REMOTE_IP",
  "REMOTE_USER",
  "SSH_KEY_PATH",
  "SSH_HOST_KEY_CHECKING",
  "SSH_KNOWN_HOSTS_FILE",
  "RSYNC_DAEMON_PORT",
  "FAST_TRANSPORT_ENABLED",
  "FAST_TRANSPORT_ACCESS_MODE",
  "FAST_TRANSPORT_LIFECYCLE",
  // Syncing
  "AUTO_SYNC_MOVIES",
  "AUTO_SYNC_SERIES",
  "AUTO_SYNC_ANIME",
  "SERIES_ANIME_SYNC_WAIT_TIME",
  "MOVIE_PATH",
  "TVSHOW_PATH",
  "ANIME_PATH",
  "MOVIE_DEST_PATH",
  "TVSHOW_DEST_PATH",
  "ANIME_DEST_PATH",
  "BACKUP_PATH",
  "BACKUP_RETENTION_ENABLED",
  "BACKUP_RETENTION_KEEP",
  "BACKUP_RETENTION_GRACE_HOURS",
  // Account
  "JWT_EXPIRY_HOURS",
  "DRAGONCP_USERNAME",
  "WEBHOOK_ALLOWED_IPS",
  "CORS_ORIGINS",
  // System
  "TEST_MODE",
  "DISK_PATH_1",
  "DISK_PATH_2",
  "DISK_PATH_3",
  "DISK_API_ENDPOINT",
  // Logs
  "WEBSOCKET_TIMEOUT_MINUTES",
]);

/** The time now, refreshed every `ms`, so a "try again at" wait can end on screen. */
export function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(timer);
  }, [ms]);
  return now;
}

/**
 * A thumb-sized target on a phone (44px), the desktop size from `sm`: the same
 * rule as the Library tab's pop-up. For a `size="sm"` button, a select and an
 * input; `TAP_BUTTON` for a default-size button.
 */
export const TAP_SM =
  "max-sm:h-11 max-sm:px-3.5 max-sm:data-[size=default]:h-11 max-sm:data-[size=sm]:h-11";
export const TAP_BUTTON = "max-sm:h-11 max-sm:px-4";
