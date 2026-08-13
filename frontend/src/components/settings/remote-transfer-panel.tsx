import { useState } from "react";
import { toast } from "sonner";
import {
  useDetectAddress,
  useRemoteTransferAction,
  useRemoteTransferStatus,
  type RemoteTransferHealthState,
} from "@/hooks/useRemoteTransfer";
import { useUpdateSettings } from "@/hooks/useConfig";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  IconAlertTriangle,
  IconCheck,
  IconCopy,
  IconKey,
  IconPlayerPlay,
  IconPlayerStop,
  IconRefresh,
  IconRocket,
  IconTrash,
  IconWorldSearch,
} from "@tabler/icons-react";

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

const HEALTH_TONE: Record<RemoteTransferHealthState, string> = {
  ready: "bg-emerald-500",
  blocked: "bg-amber-500",
  auth_failed: "bg-amber-500",
  unreachable: "bg-neutral-600",
  error: "bg-red-500",
};

function StatusLight({ state, running }: { state: RemoteTransferHealthState; running: boolean }) {
  return (
    <span className="relative flex size-2.5">
      {state === "ready" && (
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500/60" />
      )}
      <span
        className={cn(
          "relative inline-flex size-2.5 rounded-full",
          running ? HEALTH_TONE[state] : HEALTH_TONE.unreachable,
        )}
      />
    </span>
  );
}

function Fact({ label, value, tone }: { label: string; value: string; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <span className="text-neutral-400">{label}</span>
      <span
        className={cn(
          "font-medium",
          tone === "good" && "text-emerald-300",
          tone === "warn" && "text-amber-300",
          tone === "bad" && "text-red-300",
          !tone && "text-neutral-200",
        )}
      >
        {value}
      </span>
    </div>
  );
}

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
    describe: string,
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
      toast.error("Could not ask the remote host which address we connect from");
    }
  };

  return (
    <Card className="border-neutral-800 bg-neutral-900/50">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-white">
              <IconRocket className="size-4" />
              Fast transfers
            </CardTitle>
            <CardDescription className="text-neutral-400">
              A transfer server on the media host that moves files about three times faster
              than SSH. Transfers fall back to SSH on their own whenever it is unavailable.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => statusQuery.refetch()}
            disabled={statusQuery.isFetching}
          >
            <IconRefresh className={cn("size-4", statusQuery.isFetching && "animate-spin")} />
            Check
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {statusQuery.isLoading && (
          <p className="text-sm text-neutral-400">Asking the remote host…</p>
        )}

        {statusQuery.isError && (
          <p className="text-sm text-red-300">
            Could not read the transfer server's status. The backend may need restarting
            after an update.
          </p>
        )}

        {server && (
          <>
            <div className="flex items-start gap-3 rounded-md border border-neutral-800 bg-neutral-950/40 p-3">
              <div className="mt-1">
                <StatusLight state={server.health.state} running={server.health.running} />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-neutral-100">{server.summary}</p>
                {server.health.detail && server.health.state !== "ready" && (
                  <p className="mt-0.5 text-xs text-neutral-400">{server.health.detail}</p>
                )}
              </div>
            </div>

            {server.detected_address_differs && (
              <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
                <IconAlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-400" />
                <div className="space-y-2 text-sm">
                  <p className="text-amber-200">
                    This server now reaches the media host from a different address than the
                    transfer server allows. Transfers are still running — over SSH, at the
                    slower speed.
                  </p>
                  <p className="text-xs text-neutral-400">
                    Either put the new address in <code>RSYNC_DAEMON_ALLOWED_IP</code> and
                    reinstall, or switch access to password-only below to get the speed back
                    now.
                  </p>
                </div>
              </div>
            )}

            {!server.configured && (
              <p className="rounded-md border border-neutral-800 bg-neutral-950/40 p-3 text-sm text-amber-200">
                {server.configuration_problem}
              </p>
            )}

            <div className="divide-y divide-neutral-800/70">
              <Fact label="Installed" value={yesNo(server.installed)} tone={server.installed ? "good" : undefined} />
              <Fact label="Running" value={server.service_state ?? "Unknown"} tone={server.service_state === "active" ? "good" : undefined} />
              <Fact
                label="Answering us"
                value={server.health.ok ? "Yes" : "No"}
                tone={server.health.ok ? "good" : server.health.running ? "warn" : undefined}
              />
              {server.installed && (
                <Fact
                  label="Settings match this app"
                  value={yesNo(server.up_to_date, "Yes", "Older — reinstall to apply")}
                  tone={server.up_to_date === false ? "warn" : undefined}
                />
              )}
              {server.access_mode === "restricted" && server.installed && (
                <Fact
                  label="Allowed address still matches"
                  value={yesNo(server.address_matches)}
                  tone={server.address_matches === false ? "warn" : "good"}
                />
              )}
              <Fact label="Port" value={String(server.port || "—")} />
              <Fact label="Libraries published" value={server.libraries.join(", ") || "None"} />
              {!server.password_file_secure && server.password_stored && (
                <Fact label="Stored password" value="Readable by others — rotate it" tone="bad" />
              )}
            </div>

            <Separator className="bg-neutral-800" />

            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => run("install", "Install the transfer server")} disabled={busy || !server.configured}>
                <IconRocket className="size-4" />
                {server.installed ? "Reinstall" : "Install"}
              </Button>
              <Button size="sm" variant="outline" onClick={() => run("start", "Start the transfer server")} disabled={busy || !server.installed}>
                <IconPlayerPlay className="size-4" />
                Start
              </Button>
              <Button size="sm" variant="outline" onClick={() => run("stop", "Stop the transfer server")} disabled={busy || !server.installed}>
                <IconPlayerStop className="size-4" />
                Stop
              </Button>
              <Button size="sm" variant="outline" onClick={() => run("rotate-password", "Change the password")} disabled={busy || !server.installed}>
                <IconKey className="size-4" />
                New password
              </Button>
              <Button
                size="sm"
                variant={confirmRemove ? "destructive" : "outline"}
                disabled={busy || !server.installed}
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
                {confirmRemove ? "Remove it — sure?" : "Remove"}
              </Button>
            </div>

            <Separator className="bg-neutral-800" />

            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <Label className="text-neutral-200">Use it for transfers</Label>
                  <p className="text-xs text-neutral-400">
                    When it is unavailable, transfers use SSH instead — nothing stops.
                  </p>
                </div>
                <Switch
                  checked={server.enabled_for_transfers}
                  disabled={updateSettings.isPending}
                  onCheckedChange={(checked) =>
                    saveSetting(
                      "FAST_TRANSPORT_ENABLED",
                      checked,
                      checked ? "Transfers will use the fast route when it is available" : "Transfers will use SSH",
                    )
                  }
                />
              </div>

              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <Label className="text-neutral-200">Who may connect</Label>
                  <p className="text-xs text-neutral-400">
                    Password-only is the fallback for when your fixed address changes.
                  </p>
                </div>
                <Select
                  value={server.access_mode}
                  disabled={updateSettings.isPending}
                  onValueChange={(value) => {
                    if (!value) return;
                    saveSetting(
                      "FAST_TRANSPORT_ACCESS_MODE",
                      value,
                      value === "restricted"
                        ? "Only the allowed address may connect — reinstall to apply"
                        : "Any address may connect, password only — reinstall to apply",
                    );
                  }}
                >
                  <SelectTrigger className="w-56">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="restricted">Only my address</SelectItem>
                    <SelectItem value="password">Any address, password only</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <Label className="text-neutral-200">When it runs</Label>
                  <p className="text-xs text-neutral-400">
                    Leaving it off between transfers keeps the port closed most of the day.
                  </p>
                </div>
                <Select
                  value={server.start_at_boot ? "always" : "on_demand"}
                  disabled={updateSettings.isPending}
                  onValueChange={(value) => {
                    if (!value) return;
                    saveSetting("FAST_TRANSPORT_LIFECYCLE", value, "Saved — reinstall to apply");
                  }}
                >
                  <SelectTrigger className="w-56">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="on_demand">Only while transfers run</SelectItem>
                    <SelectItem value="always">Always, and at boot</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <Separator className="bg-neutral-800" />

            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" size="sm" onClick={runDetect} disabled={detect.isPending}>
                  <IconWorldSearch className={cn("size-4", detect.isPending && "animate-pulse")} />
                  What address do we connect from?
                </Button>
                {detected && (
                  <>
                    <code className="rounded bg-neutral-950 px-2 py-1 font-mono text-sm text-neutral-100">
                      {detected}
                    </code>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        navigator.clipboard?.writeText(detected);
                        toast.success("Copied");
                      }}
                    >
                      <IconCopy className="size-4" />
                    </Button>
                    {server.has_allowed_address && (
                      <Badge
                        variant="outline"
                        className={cn(
                          server.address_matches
                            ? "border-emerald-500/40 text-emerald-300"
                            : "border-amber-500/40 text-amber-300",
                        )}
                      >
                        {server.address_matches ? (
                          <>
                            <IconCheck className="size-3" /> already configured
                          </>
                        ) : (
                          "differs from what is configured"
                        )}
                      </Badge>
                    )}
                  </>
                )}
              </div>
              <p className="text-xs text-neutral-500">
                Asked of the media host directly, so it is exact and goes nowhere else. To
                use it, put it in <code>RSYNC_DAEMON_ALLOWED_IP</code> in the environment
                file on this server and reinstall.
              </p>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
