import type { ReactNode } from "react";
import { toast } from "sonner";
import {
  IconLoader2,
  IconPlayerPause,
  IconPlugConnected,
  IconPlugConnectedX,
  IconPlugX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { SectionCard } from "@/components/layout/section-card";
import { useRemoteSession, useSSHAutoConnect, useSSHDisconnect } from "@/hooks/useConfig";
import { useRuntimeStore } from "@/stores/runtime";
import { clockText } from "@/lib/pipeline";
import type { ExploreSession } from "@/lib/explore-types";
import { EnvNote, Fact, FactGrid, SettingList, SettingRow, ToneIcon } from "./settings-bits";
import { TAP_BUTTON, useNow, useSaveSetting, useSettingMap, type Tone } from "./settings-model";
import { RemoteTransferPanel } from "./remote-transfer-panel";

/** What each host-key policy means, in words, and whether it is safe. */
const HOST_KEY_POLICY: Record<string, { text: string; tone?: Tone }> = {
  strict: { text: "Only servers already in the known hosts file." },
  "accept-new": { text: "Trusted on first connect, refused if its key changes." },
  no: { text: "Any key accepted. Unsafe: a forged server would go unnoticed.", tone: "warn" },
};

function sessionState(session: ExploreSession | undefined): {
  tone: Tone;
  icon: typeof IconPlugConnected;
  title: string;
  detail: ReactNode;
} {
  const host = session?.host || "the remote server";
  if (!session) {
    return {
      tone: "muted",
      icon: IconPlugConnected,
      title: "Checking the connection…",
      detail: "",
    };
  }
  if (session.connected) {
    return {
      tone: "ok",
      icon: IconPlugConnected,
      title: `Connected to ${host}`,
      detail: "Transfers open their own connections and do not depend on this one.",
    };
  }
  // The server's messages may end in a full stop of their own.
  const error = (session.last_error || "").replace(/\.$/, "");
  if (session.paused) {
    return {
      tone: "crit",
      icon: IconPlugConnectedX,
      title: "The remote server refused the login",
      detail: (
        <>
          {error}. Automatic connecting is paused so repeated tries cannot get this address blocked.
          Check the login in the environment file, then press Connect.
        </>
      ),
    };
  }
  if (session.last_error) {
    return {
      tone: "warn",
      icon: IconPlugX,
      title: `Cannot reach ${host}`,
      detail: (
        <>
          {error}.
          {session.retry_at && session.auto_connect && (
            <> Trying again by itself at {clockText(session.retry_at)}.</>
          )}
        </>
      ),
    };
  }
  return {
    tone: "muted",
    icon: IconPlugX,
    title: "Not connected",
    detail: session.auto_connect
      ? "Explore connects by itself the next time it needs the remote server."
      : "Auto-connect is off. Press Connect to open the session.",
  };
}

function ConnectionSection() {
  const sessionQuery = useRemoteSession();
  const session = sessionQuery.data;
  const connect = useSSHAutoConnect();
  const disconnect = useSSHDisconnect();
  const setConfigChanged = useRuntimeStore((state) => state.setConfigChanged);
  const { map } = useSettingMap();
  const { save, saving } = useSaveSetting();

  const state = sessionState(session);
  const waitUntil = session?.manual_retry_at ?? null;
  const now = useNow(5_000);
  const waiting = waitUntil !== null && new Date(waitUntil).getTime() > now;
  const autoConnect = map.get("SSH_AUTO_CONNECT");
  const policyValue = String(map.get("SSH_HOST_KEY_CHECKING")?.value || "accept-new");
  const policy = HOST_KEY_POLICY[policyValue];

  const runConnect = async () => {
    try {
      const answer = (await connect.mutateAsync()) as { status?: string; message?: string };
      if (answer?.status !== "success") {
        // The server says why, and until when it will not try again.
        toast.error(answer?.message || "Could not connect");
      } else {
        setConfigChanged(false);
        toast.success("Connected to the remote server");
      }
    } catch {
      toast.error("Could not connect");
    }
    sessionQuery.refetch();
  };

  const runDisconnect = async () => {
    try {
      await disconnect.mutateAsync();
      toast.success("Disconnected");
    } catch {
      toast.error("Could not disconnect");
    }
    sessionQuery.refetch();
  };

  return (
    <SectionCard
      label="Connection"
      description="The SSH session Explore reads the remote server through."
    >
      <div className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <ToneIcon icon={state.icon} tone={state.tone} size="lg" />
          <div className="min-w-0">
            <p className="font-display text-[15px] font-semibold break-words text-foreground">
              {state.title}
            </p>
            {state.detail && (
              <p className="mt-0.5 max-w-prose text-[12.5px] text-pretty text-muted-foreground">
                {state.detail}
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 gap-2 sm:pl-0">
          {session?.connected ? (
            <Button
              variant="outline"
              className={TAP_BUTTON}
              onClick={runDisconnect}
              disabled={disconnect.isPending}
            >
              <IconPlayerPause className="size-4" />
              Disconnect
            </Button>
          ) : (
            <Button
              className={TAP_BUTTON}
              onClick={runConnect}
              disabled={connect.isPending || waiting}
            >
              {connect.isPending ? (
                <IconLoader2 className="size-4 animate-spin" />
              ) : (
                <IconPlugConnected className="size-4" />
              )}
              {waiting ? `Connect at ${clockText(waitUntil)}` : "Connect"}
            </Button>
          )}
        </div>
      </div>

      <div className="border-t border-border/70">
        <SettingList>
          <SettingRow
            inline
            label="Auto-connect"
            htmlFor="ssh-auto-connect"
            description="Connect by itself whenever Explore needs the remote server. Failed tries are spaced out and a refused login is never retried by itself."
          >
            <Switch
              id="ssh-auto-connect"
              checked={autoConnect ? Boolean(autoConnect.value) : true}
              disabled={!autoConnect || saving}
              onCheckedChange={(next) =>
                save(
                  "SSH_AUTO_CONNECT",
                  next,
                  next ? "Auto-connect is on" : "Auto-connect is off. Connect by hand."
                ).then(() => sessionQuery.refetch())
              }
            />
          </SettingRow>
        </SettingList>
      </div>
      <div className="border-t border-border/70">
        <FactGrid>
          <Fact label="Server" value={map.get("REMOTE_IP")?.value} />
          <Fact label="User" value={map.get("REMOTE_USER")?.value} />
          <Fact
            label="SSH key"
            value={map.get("SSH_KEY_PATH")?.value}
            hint={map.get("SSH_KEY_PATH")?.value ? undefined : "Logs in with the password instead."}
          />
          <Fact
            label="Host-key checking"
            value={policyValue}
            hint={
              policy?.tone === "warn" ? (
                <span className="text-amber-300">{policy.text}</span>
              ) : (
                policy?.text
              )
            }
          />
          <Fact
            label="Known hosts file"
            value={map.get("SSH_KNOWN_HOSTS_FILE")?.value}
            hint={
              map.get("SSH_KNOWN_HOSTS_FILE")?.value
                ? undefined
                : "dragoncp_known_hosts in the app folder."
            }
          />
        </FactGrid>
      </div>
      <EnvNote />
    </SectionCard>
  );
}

export function RemoteServerTab() {
  return (
    <div className="space-y-4">
      <ConnectionSection />
      <RemoteTransferPanel />
    </div>
  );
}
