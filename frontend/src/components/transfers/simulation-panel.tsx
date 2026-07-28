import { useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import { Chip } from "@/components/transfers/transfer-bits";
import {
  busyConflictFrom,
  useCleanupSimulation,
  useSimulationStatus,
  useStartSimulation,
  useStopSimulation,
  type BusyTransfer,
  type SimulationScenario,
} from "@/hooks/useSimulation";
import { formatBytes } from "@/lib/transfer-progress";
import {
  IconAlertTriangle,
  IconFlask,
  IconPlayerPlay,
  IconPlayerStopFilled,
  IconTrash,
} from "@tabler/icons-react";

/**
 * What a scenario will actually do, in the terms an admin cares about: how many
 * copies, how big, and how long it will take at the speed it is held to.
 */
function scenarioFacts(scenario: SimulationScenario, maxConcurrent: number): string[] {
  const seconds = Math.round((scenario.size_mb * 1024) / scenario.bwlimit_kbps);
  const facts = [
    `${scenario.transfers} cop${scenario.transfers === 1 ? "y" : "ies"}`,
    `${scenario.size_mb} MB each`,
    `~${seconds}s each`,
  ];
  if (scenario.transfers > maxConcurrent) {
    facts.push(`${scenario.transfers - maxConcurrent} will wait`);
  }
  if (scenario.same_destination) facts.push("one destination");
  if (scenario.with_webhooks) facts.push("with webhooks");
  if (scenario.fail) facts.push("ends in failure");
  return facts;
}

function ScenarioCard({
  scenario,
  maxConcurrent,
  disabled,
  onStart,
}: {
  scenario: SimulationScenario;
  maxConcurrent: number;
  disabled: boolean;
  onStart: (key: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2.5 rounded-lg border border-border bg-card/60 p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">{scenario.name}</p>
          <p className="mt-1 text-[12.5px] text-pretty text-muted-foreground">
            {scenario.description}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="shrink-0"
          disabled={disabled}
          onClick={() => onStart(scenario.key)}
        >
          <IconPlayerPlay className="mr-1.5 size-3.5" />
          Run
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {scenarioFacts(scenario, maxConcurrent).map((fact) => (
          <Chip key={fact}>{fact}</Chip>
        ))}
      </div>
    </div>
  );
}

/**
 * Runs the real transfer pipeline against throwaway files, so queueing, webhook
 * handling and this page can be watched behaving without touching media or the
 * remote server.
 */
export function SimulationPanel({ onStarted }: { onStarted?: () => void }) {
  const [pendingScenario, setPendingScenario] = useState<string | null>(null);
  const [busyTransfers, setBusyTransfers] = useState<BusyTransfer[] | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const statusQuery = useSimulationStatus(true);
  const startMutation = useStartSimulation();
  const stopMutation = useStopSimulation();
  const cleanupMutation = useCleanupSimulation();

  const status = statusQuery.data;
  const onBoard = status?.total ?? 0;
  const busy = startMutation.isPending || stopMutation.isPending || cleanupMutation.isPending;

  const run = async (scenario: string, confirmBusy = false) => {
    try {
      const result = await startMutation.mutateAsync({ scenario, confirmBusy });
      toast.success(result.message);
      onStarted?.();
    } catch (error) {
      const conflict = busyConflictFrom(error);
      if (conflict) {
        // Real work is in the queue — say what, and let them decide
        setPendingScenario(scenario);
        setBusyTransfers(conflict);
        return;
      }
      const message =
        (error as { response?: { data?: { message?: string } } })?.response?.data?.message ??
        "Could not start the simulation";
      toast.error(message);
    }
  };

  const clear = async () => {
    try {
      const result = await cleanupMutation.mutateAsync();
      toast.success(result.message);
    } catch {
      toast.error("Could not clear the simulation");
    }
  };

  const statusSummary = Object.entries(status?.by_status ?? {})
    .map(([key, count]) => `${count} ${key}`)
    .join(" · ");

  return (
    <div className="flex flex-col gap-3.5">
      <SectionCard
        label="What this does"
        description="Copies files generated on this machine through the real transfer pipeline — the same queue, rsync, webhook handling and progress your media syncs use. Nothing touches your media or the remote server."
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 font-mono text-[11px] text-muted-foreground">
          <span>{status?.max_concurrent ?? 3} slots</span>
          <span className="opacity-50">·</span>
          <span>files removed on clear</span>
          <span className="opacity-50">·</span>
          <span>rows marked as simulations</span>
          {status?.disk_bytes ? (
            <>
              <span className="opacity-50">·</span>
              <span>{formatBytes(status.disk_bytes)} on disk now</span>
            </>
          ) : null}
        </div>
      </SectionCard>

      {onBoard > 0 && (
        <SectionCard
          label="On the board"
          description={statusSummary || "Running"}
          actions={
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={busy || status?.finished}
                onClick={async () => {
                  try {
                    const result = await stopMutation.mutateAsync();
                    toast.success(result.message);
                  } catch {
                    toast.error("Could not stop the simulation");
                  }
                }}
              >
                <IconPlayerStopFilled className="mr-1.5 size-3.5" />
                Stop
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-muted-foreground hover:text-rose-400"
                disabled={busy}
                onClick={() => setConfirmClear(true)}
              >
                <IconTrash className="mr-1.5 size-3.5" />
                Clear
              </Button>
            </>
          }
        >
          <div className="px-4 py-3 text-[12.5px] text-muted-foreground">
            {onBoard} simulated transfer{onBoard === 1 ? "" : "s"} — watch them in{" "}
            <span className="font-medium text-foreground">Activity</span>, then clear them when
            you are done. Clearing removes the rows and the generated files.
          </div>
        </SectionCard>
      )}

      <SectionCard
        label="Scenarios"
        description="Each one sets up a situation worth seeing the system handle"
      >
        {statusQuery.isLoading ? (
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            {[1, 2, 3, 4].map((index) => (
              <Skeleton key={index} className="h-28 w-full rounded-lg" />
            ))}
          </div>
        ) : status?.scenarios.length ? (
          <div className="grid gap-3 p-3 sm:grid-cols-2">
            {status.scenarios.map((scenario) => (
              <ScenarioCard
                key={scenario.key}
                scenario={scenario}
                maxConcurrent={status.max_concurrent}
                disabled={busy || onBoard > 0}
                onStart={run}
              />
            ))}
          </div>
        ) : (
          <SectionEmpty icon={IconFlask} title="No scenarios available" />
        )}

        {onBoard > 0 && (
          <p className="border-t border-border/70 px-4 py-2.5 text-[12.5px] text-muted-foreground">
            Clear the current simulation before running another.
          </p>
        )}
      </SectionCard>

      <ConfirmDialog
        open={Boolean(busyTransfers)}
        onOpenChange={(open) => {
          if (!open) {
            setBusyTransfers(null);
            setPendingScenario(null);
          }
        }}
        icon={<IconAlertTriangle />}
        destructive={false}
        title="Real transfers are running"
        description={
          <>
            A simulation takes a queue slot, so these may be delayed by up to about a minute:
            <span className="mt-2 flex flex-col gap-1">
              {(busyTransfers ?? []).map((transfer) => (
                <span key={transfer.id} className="font-mono text-[11px] text-foreground">
                  {transfer.title}{" "}
                  <span className="text-muted-foreground">({transfer.status})</span>
                </span>
              ))}
            </span>
          </>
        }
        confirmLabel="Start anyway"
        cancelLabel="Not now"
        pending={startMutation.isPending}
        onConfirm={() => {
          if (pendingScenario) run(pendingScenario, true);
          setBusyTransfers(null);
          setPendingScenario(null);
        }}
      />

      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        icon={<IconTrash />}
        title="Clear this simulation?"
        description="Stops anything still running, removes the simulated transfers and notifications, and deletes the generated files. Real transfers and media are not touched."
        confirmLabel="Clear simulation"
        pending={cleanupMutation.isPending}
        onConfirm={clear}
      />
    </div>
  );
}

/** Marks a row in the transfer lists as belonging to a simulation. */
export function SimulationBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[5px] border border-dashed border-brand/50 bg-brand/10 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-brand-foreground uppercase",
        className
      )}
    >
      <IconFlask className="size-[11px]" />
      Sim
    </span>
  );
}
