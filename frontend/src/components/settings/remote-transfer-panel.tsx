import { useState } from "react";
import { toast } from "sonner";
import {
  useDetectAddress,
  useRemoteTransferAction,
  useRemoteTransferStatus,
  type RemoteTransferHealthState,
} from "@/hooks/useRemoteTransfer";
import { useUpdateSettings } from "@/hooks/useConfig";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SectionCard } from "@/components/layout/section-card";
import { cn } from "@/lib/utils";
import {
  IconAlertTriangle,
  IconCheck,
  IconCopy,
  IconKey,
  IconLoader2,
  IconPlayerPlay,
  IconPlayerStop,
  IconRefresh,
  IconRocket,
  IconTrash,
  IconWorldSearch,
} from "@tabler/icons-react";
import { SettingList, SettingRow, ToneIcon } from "./settings-bits";
import { TAP_SM, TONE_TEXT, type Tone } from "./settings-model";

/**
 * The remote transfer server.
 *
 * Transfers over SSH are held to about 11 MB/s on this link by a limit inside
 * SSH itself; the same files over this server move at about 35 MB/s. This card
 * is where it is installed, started, stopped and taken away again.
 *
 * The address allowed to reach it is never sent here — only whether one is set
 * and whether it still matches where we appear to connect from. That is enough
 * to be useful and nothing a reader could take away.
 */

/** How healthy the server is, in the page's four-note vocabulary. */
const HEALTH_TONE: Record<RemoteTransferHealthState, Tone> = {
  ready: "ok",
  blocked: "warn",
  auth_failed: "warn",
  unreachable: "muted",
  error: "crit",
};

/** One fact about the server: a name and a short answer, coloured only when it matters. */
function Fact({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-2">
      <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "text-right text-[12.5px] font-medium",
          TONE_TEXT[tone ?? "muted"],
          !tone && "text-foreground/90"
        )}
      >
        {value}
      </dd>
    </div>
  );
}

// The words a picker shows for its stored value; without them it shows the
// value itself ("on_demand").
const ACCESS_ITEMS = [
  { value: "restricted", label: "Only my address" },
  { value: "password", label: "Any address, password only" },
];
const LIFECYCLE_ITEMS = [
  { value: "on_demand", label: "Only while transfers run" },
  { value: "always", label: "Always, and at boot" },
];

function yesNo(value: boolean | null, good = "Yes", bad = "No", unknown = "Unknown") {
  if (value === null || value === undefined) return unknown;
  return value ? good : bad;
}

export function RemoteTransferPanel() {
  const statusQuery = useRemoteTransferStatus();
  const action = useRemoteTransferAction();
  const detect = useDetectAddress();
  const updateSettings = useUpdateSettings();

  const [detected, setDetected] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  const server = statusQuery.data;
  const busy = action.isPending || statusQuery.isFetching;

  const run = async (
    name: "install" | "start" | "stop" | "restart" | "uninstall" | "rotate-password",
    describe: string
  ) => {
    try {
      const result = await action.mutateAsync(name);
      if (result.status === "success") toast.success(result.message || describe);
      else toast.error(result.message || `Could not ${describe.toLowerCase()}`);
    } catch (error) {
      const message =
        (error as { response?: { data?: { message?: string } } })?.response?.data?.message ??
        `Could not ${describe.toLowerCase()}`;
      toast.error(message);
    }
  };

  const saveSetting = async (key: string, value: string | boolean, note: string) => {
    try {
      await updateSettings.mutateAsync({ [key]: value });
      toast.success(note);
      statusQuery.refetch();
    } catch {
      toast.error("Could not save that setting");
    }
  };

  const runDetect = async () => {
    try {
      const result = await detect.mutateAsync();
      setDetected(result.address);
      if (result.configured && result.matches_configured) {
        toast.success("This is already the address the transfer server allows");
      } else if (result.configured) {
        toast.warning("This is not the address the transfer server allows");
      }
    } catch {
      toast.error("Could not ask the remote server which address we connect from");
    }
  };

  const tone: Tone = server
    ? server.health.running
      ? HEALTH_TONE[server.health.state]
      : server.installed
        ? "warn"
        : "muted"
    : "muted";

  return (
    <SectionCard
      label="Fast transfers"
      description="A transfer server on the remote server that copies files about three times faster than SSH. When it is unavailable, transfers use SSH by themselves."
      actions={
        <Button
          variant="outline"
          size="sm"
          className={TAP_SM}
          onClick={() => statusQuery.refetch()}
          disabled={statusQuery.isFetching}
        >
          <IconRefresh className={cn("size-4", statusQuery.isFetching && "animate-spin")} />
          Check
        </Button>
      }
    >
      {statusQuery.isLoading && (
        <p className="flex items-center gap-2 px-4 py-4 text-[13px] text-muted-foreground">
          <IconLoader2 className="size-4 animate-spin" />
          Asking the remote server how its transfer server is doing…
        </p>
      )}

      {statusQuery.isError && (
        <p className="px-4 py-4 text-[13px] text-rose-300">
          Could not read the transfer server's status. If DragonCP was just updated, restart it and
          press Check.
        </p>
      )}

      {server && (
        <>
          <div className="flex items-start gap-3 px-4 py-4">
            <ToneIcon icon={IconRocket} tone={tone} size="lg" />
            <div className="min-w-0">
              <p className="font-display text-[15px] font-semibold text-foreground">
                {server.summary}
              </p>
              {server.health.detail && server.health.state !== "ready" && (
                <p className="mt-0.5 text-[12.5px] text-muted-foreground">{server.health.detail}</p>
              )}
            </div>
          </div>

          {server.detected_address_differs && (
            <div className="mx-4 mb-3 flex items-start gap-2.5 rounded-lg border border-amber-500/30 bg-amber-500/8 p-3">
              <IconAlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-400" />
              <div className="space-y-1.5 text-[12.5px]">
                <p className="text-amber-100">
                  DragonCP now reaches the remote server from a different address than the transfer
                  server allows. Transfers still run, over SSH, at the slower speed.
                </p>
                <p className="text-muted-foreground">
                  Put the new address in <code className="font-mono">RSYNC_DAEMON_ALLOWED_IP</code>{" "}
                  and reinstall, or set Who may connect to password only and reinstall. The
                  reinstall is what applies the change on the remote server.
                </p>
              </div>
            </div>
          )}

          {!server.configured && (
            <p className="mx-4 mb-3 rounded-lg border border-amber-500/30 bg-amber-500/8 p-3 text-[12.5px] text-amber-100">
              {server.configuration_problem}
            </p>
          )}

          <div className="flex flex-wrap gap-2 border-t border-border/70 px-4 py-3">
            <Button
              size="sm"
              className={TAP_SM}
              onClick={() => run("install", "Install the transfer server")}
              disabled={busy || !server.configured}
            >
              <IconRocket className="size-4" />
              {server.installed ? "Reinstall" : "Install"}
            </Button>
            <Button
              size="sm"
              className={TAP_SM}
              variant="outline"
              onClick={() => run("start", "Start the transfer server")}
              disabled={busy || !server.installed}
            >
              <IconPlayerPlay className="size-4" />
              Start
            </Button>
            <Button
              size="sm"
              className={TAP_SM}
              variant="outline"
              onClick={() => run("stop", "Stop the transfer server")}
              disabled={busy || !server.installed}
            >
              <IconPlayerStop className="size-4" />
              Stop
            </Button>
            <Button
              size="sm"
              className={TAP_SM}
              variant="outline"
              onClick={() => run("rotate-password", "Change the password")}
              disabled={busy || !server.installed}
            >
              <IconKey className="size-4" />
              New password
            </Button>
            <Button
              size="sm"
              className={TAP_SM}
              variant={confirmRemove ? "destructive" : "outline"}
              disabled={busy || !server.installed}
              onBlur={() => setConfirmRemove(false)}
              onClick={async () => {
                if (!confirmRemove) {
                  setConfirmRemove(true);
                  return;
                }
                setConfirmRemove(false);
                await run("uninstall", "Remove the transfer server");
              }}
            >
              <IconTrash className="size-4" />
              {confirmRemove ? "Press again to remove" : "Remove"}
            </Button>
          </div>

          <div className="border-t border-border/70">
            <SettingList>
              <SettingRow
                label="Use it for transfers"
                description="When it is unavailable, transfers use SSH instead. Nothing stops."
                htmlFor="fast-transfers-enabled"
              >
                <Switch
                  id="fast-transfers-enabled"
                  checked={server.enabled_for_transfers}
                  disabled={updateSettings.isPending}
                  onCheckedChange={(checked) =>
                    saveSetting(
                      "FAST_TRANSPORT_ENABLED",
                      checked,
                      checked
                        ? "Transfers will use the fast route when it is available"
                        : "Transfers will use SSH"
                    )
                  }
                />
              </SettingRow>
              <SettingRow
                label="Who may connect"
                description="Password only is the fallback for when your fixed address changes. Reinstall to apply."
              >
                <Select
                  items={ACCESS_ITEMS}
                  value={server.access_mode}
                  disabled={updateSettings.isPending}
                  onValueChange={(value) => {
                    if (!value) return;
                    saveSetting(
                      "FAST_TRANSPORT_ACCESS_MODE",
                      value,
                      value === "restricted"
                        ? "Only the allowed address may connect. Reinstall to apply."
                        : "Any address may connect, with the password. Reinstall to apply."
                    );
                  }}
                >
                  <SelectTrigger
                    className={cn("w-full sm:w-60", TAP_SM)}
                    aria-label="Who may connect"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="restricted">Only my address</SelectItem>
                    <SelectItem value="password">Any address, password only</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>
              <SettingRow
                label="When it runs"
                description="Leaving it off between transfers keeps its port closed most of the day. Reinstall to apply."
              >
                <Select
                  items={LIFECYCLE_ITEMS}
                  value={server.start_at_boot ? "always" : "on_demand"}
                  disabled={updateSettings.isPending}
                  onValueChange={(value) => {
                    if (!value) return;
                    saveSetting("FAST_TRANSPORT_LIFECYCLE", value, "Saved. Reinstall to apply.");
                  }}
                >
                  <SelectTrigger className={cn("w-full sm:w-60", TAP_SM)} aria-label="When it runs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="on_demand">Only while transfers run</SelectItem>
                    <SelectItem value="always">Always, and at boot</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>
            </SettingList>
          </div>

          <dl className="grid border-t border-border/70 py-1.5 sm:grid-cols-2">
            <Fact
              label="Installed"
              value={yesNo(server.installed)}
              tone={server.installed ? "ok" : undefined}
            />
            <Fact
              label="Running"
              value={server.service_state ?? "Unknown"}
              tone={server.service_state === "active" ? "ok" : undefined}
            />
            <Fact
              label="Answering us"
              value={server.health.ok ? "Yes" : "No"}
              tone={server.health.ok ? "ok" : server.health.running ? "warn" : undefined}
            />
            {server.installed && (
              <Fact
                label="Settings match this app"
                value={yesNo(server.up_to_date, "Yes", "Older, reinstall to apply")}
                tone={server.up_to_date === false ? "warn" : undefined}
              />
            )}
            {server.access_mode === "restricted" && server.installed && (
              <Fact
                label="Allowed address still matches"
                value={yesNo(server.address_matches)}
                tone={server.address_matches === false ? "warn" : "ok"}
              />
            )}
            <Fact label="Port" value={String(server.port || "Not set")} />
            <Fact label="Libraries published" value={server.libraries.join(", ") || "None"} />
            {/*
              Two different problems, two different remedies. A file others
              can read is fixed by rotating it. A file this server cannot read
              is a permissions problem on the file itself, and rotating would
              not touch it — so saying "rotate it" there sends somebody to do
              the one thing that cannot help.
            */}
            {server.password_problem ? (
              <Fact
                label="Stored password"
                value="Cannot be read: check the file's owner and permissions"
                tone="crit"
              />
            ) : (
              !server.password_file_secure &&
              server.password_stored && (
                <Fact label="Stored password" value="Readable by others: rotate it" tone="crit" />
              )
            )}
          </dl>

          <div className="space-y-2 border-t border-border/70 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className={TAP_SM}
                onClick={runDetect}
                disabled={detect.isPending}
              >
                <IconWorldSearch className={cn("size-4", detect.isPending && "animate-pulse")} />
                Which address do we connect from?
              </Button>
              {detected && (
                <>
                  <code className="rounded-md border border-border bg-black/30 px-2 py-1 font-mono text-[12.5px] text-foreground">
                    {detected}
                  </code>
                  <Button
                    variant="ghost"
                    size="sm"
                    className={TAP_SM}
                    aria-label="Copy the address"
                    onClick={async () => {
                      // Only claim it worked once it has. The clipboard is
                      // unavailable outside a secure context and can be
                      // refused by permission, and saying "Copied" either way
                      // means pasting nothing into the environment file.
                      try {
                        if (!navigator.clipboard) throw new Error("unavailable");
                        await navigator.clipboard.writeText(detected);
                        toast.success("Copied");
                      } catch {
                        toast.error("Could not copy. Select the address and copy it by hand.");
                      }
                    }}
                  >
                    <IconCopy className="size-4" />
                  </Button>
                  {server.has_allowed_address && (
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-[12px]",
                        server.address_matches ? "text-emerald-300" : "text-amber-300"
                      )}
                    >
                      {server.address_matches ? (
                        <>
                          <IconCheck className="size-3.5" /> Already the allowed address
                        </>
                      ) : (
                        "Differs from the allowed address"
                      )}
                    </span>
                  )}
                </>
              )}
            </div>
            <p className="text-[12px] text-muted-foreground">
              Asked of the remote server directly, so it is exact and goes nowhere else. To use it,
              put it in <code className="font-mono">RSYNC_DAEMON_ALLOWED_IP</code> in the
              environment file on this server and reinstall.
            </p>
          </div>
        </>
      )}
    </SectionCard>
  );
}
