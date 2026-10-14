import type { ComponentType } from "react";
import {
  IconBrandDiscord,
  IconDeviceTv,
  IconMovie,
  IconPlayerPlay,
  IconPlug,
} from "@tabler/icons-react";

/**
 * The one thing about a connector the server cannot send: what it looks like.
 *
 * Everything else — its name, its description, its settings form, what it can
 * do — comes from the adapter, so a connector added on the backend appears in
 * the sidebar and gets a working settings page without touching the frontend.
 * A connector with no entry here falls back to a plug rather than breaking
 * that promise.
 */
const ICONS: Record<string, ComponentType<{ className?: string }>> = {
  discord: IconBrandDiscord,
  sonarr: IconDeviceTv,
  radarr: IconMovie,
  jellyfin: IconPlayerPlay,
};

export function ConnectorIcon({
  connectorId,
  className,
}: {
  connectorId: string;
  className?: string;
}) {
  const Icon = ICONS[connectorId] ?? IconPlug;
  return <Icon className={className} />;
}
