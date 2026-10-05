import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { sinceText } from "@/lib/pipeline";
import type { RunSummary } from "@/lib/sync-types";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { isLiveState, useSyncCatalogue, useSyncRuns } from "@/hooks/useSync";
import { PageHeader } from "@/components/layout/page-header";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { StatTiles } from "@/components/layout/stat-tiles";
import { FilterChips, ListPagination, ListSearch } from "@/components/layout/list-controls";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  FactLine,
  KindBadge,
  RunStateBadge,
  StageStrip,
} from "@/components/pipeline/pipeline-bits";
import { IconChevronRight, IconRoute } from "@tabler/icons-react";

const IN_PROGRESS = ["waiting", "checking", "queued", "transferring", "paused", "finishing"];
const NEEDS_A_PERSON = ["held", "refused", "interrupted"];

/** The filters, each a set of run states, so counts come straight from the server's tally. */
const FILTERS = [
  { value: "all", label: "All", states: [] as string[] },
  { value: "live", label: "In progress", states: IN_PROGRESS },
  { value: "attention", label: "Needs a person", states: NEEDS_A_PERSON },
  { value: "failed", label: "Failed", states: ["failed"] },
  { value: "completed", label: "Synced", states: ["completed"] },
  { value: "cancelled", label: "Cancelled", states: ["cancelled"] },
] as const;

const ANY_KIND = "__any__";
const PAGE_SIZE = 50;

/**
 * Every sync, newest first — webhooks, the auto-scanner, a press of Sync,
 * Explore, restarts, restores and rehearsals alike, because they all run the
 * same nine stages. Each row shows how far it got as a nine-segment strip and
 * what it is doing now in the engine's own words; opening it shows every
 * stage.
 */
export function PipelinePage() {
  const catalogue = useSyncCatalogue();
  const [filter, setFilter] = useState<string>("all");
  const [kind, setKind] = useState<string>(ANY_KIND);
  const [search, setSearch] = useState("");
  const [rehearsals, setRehearsals] = useState(true);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const debouncedSearch = useDebouncedValue(search, 300);

  const chosen = FILTERS.find((item) => item.value === filter) ?? FILTERS[0];
  const runsQuery = useSyncRuns({
    state: chosen.states.length ? chosen.states.join(",") : "all",
    kinds: kind === ANY_KIND ? undefined : [kind],
    search: debouncedSearch.trim() || undefined,
    limit,
    offset,
    simulations: rehearsals,
  });

  const runs = runsQuery.data?.runs ?? [];
  const counts = runsQuery.data?.state_counts;
  const sum = (states: readonly string[]) =>
    states.reduce((total, state) => total + (counts?.[state] ?? 0), 0);
  const everything = counts ? Object.values(counts).reduce((total, n) => total + n, 0) : 0;

  const kindItems = useMemo(
    () => [
      { value: ANY_KIND, label: "Every kind" },
      ...(catalogue.data?.kinds ?? []).map((item) => ({ value: item.id, label: item.label })),
    ],
    [catalogue.data]
  );

  const reset = (change: () => void) => {
    change();
    setOffset(0);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pipeline"
        description="Every sync, stage by stage: what asked for it, what each stage decided, and why."
      />

      <StatTiles
        items={[
          { label: "In progress", value: sum(IN_PROGRESS) },
          {
            label: "Needs a person",
            value: sum(NEEDS_A_PERSON),
            tone: sum(NEEDS_A_PERSON) ? "warn" : "default",
          },
          { label: "Failed", value: sum(["failed"]), tone: sum(["failed"]) ? "crit" : "default" },
          { label: "Synced", value: sum(["completed"]), tone: "ok" },
        ]}
      />

      <SectionCard
        label="Syncs"
        toolbar={
          <>
            <FilterChips
              choices={FILTERS.map((item) => ({
                value: item.value,
                label: item.label,
                count: item.states.length ? sum(item.states) : everything,
              }))}
              value={filter}
              onChange={(value) => reset(() => setFilter(value))}
            />
            <div className="ml-auto flex w-full flex-wrap items-center gap-2 sm:w-auto">
              <Select
                items={kindItems}
                value={kind}
                onValueChange={(value) => reset(() => setKind(value ?? ANY_KIND))}
              >
                <SelectTrigger className="h-8 w-[170px] rounded-lg bg-black/30 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {kindItems.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <ListSearch
                value={search}
                onChange={(value) => reset(() => setSearch(value))}
                placeholder="Search title or folder"
                className="min-w-0 flex-1 sm:w-56 sm:flex-none"
              />
              <div className="flex items-center gap-2 px-1">
                <Switch
                  id="pipeline-rehearsals"
                  checked={rehearsals}
                  onCheckedChange={(value) => reset(() => setRehearsals(value))}
                />
                <Label htmlFor="pipeline-rehearsals" className="text-xs text-muted-foreground">
                  Rehearsals
                </Label>
              </div>
            </div>
          </>
        }
      >
        {runsQuery.isLoading ? (
          <div className="flex flex-col gap-3 p-4">
            {[1, 2, 3].map((index) => (
              <Skeleton key={index} className="h-20 w-full rounded-lg" />
            ))}
          </div>
        ) : runs.length ? (
          <ul>
            {runs.map((run) => (
              <RunRow key={run.run_id} run={run} />
            ))}
          </ul>
        ) : (
          <SectionEmpty
            icon={IconRoute}
            title={filter === "all" && !debouncedSearch ? "No syncs yet" : "Nothing matches"}
            hint={
              filter === "all" && !debouncedSearch
                ? "Each webhook, scan or press of Sync shows up here as it moves through the pipeline."
                : "Try another filter, or clear the search."
            }
          />
        )}

        {runsQuery.data && runsQuery.data.total > 0 && (
          <ListPagination
            offset={offset}
            limit={limit}
            total={runsQuery.data.total}
            count={runs.length}
            onOffsetChange={setOffset}
            onLimitChange={(value) => reset(() => setLimit(value))}
            noun="syncs"
          />
        )}
      </SectionCard>
    </div>
  );
}

function RunRow({ run }: { run: RunSummary }) {
  const catalogue = useSyncCatalogue();
  const stageLabel = catalogue.data?.stages.find((stage) => stage.id === run.current_stage)?.label;
  const webhooks = run.webhook_count ?? 0;
  // A live sync is described by what it is doing; a finished one by how it
  // ended — the rsync error, the safety check's reason — rather than by the
  // bookkeeping its last stage did.
  const sentence = isLiveState(run.state)
    ? run.current_summary || run.outcome_message
    : run.outcome_message || run.current_summary;

  return (
    <li className="border-b border-border last:border-b-0">
      <Link
        to="/pipeline/$runId"
        params={{ runId: run.run_id }}
        className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-muted/40 sm:items-center"
      >
        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-sm font-semibold break-words text-foreground">{run.label}</span>
            <KindBadge kind={run.kind} label={run.kind_label} />
            {run.is_simulation && run.kind !== "simulation" && (
              <KindBadge kind="simulation" label="Rehearsal" />
            )}
            <RunStateBadge state={run.state} label={run.state_label} className="sm:hidden" />
          </span>

          <span className="flex min-w-0 items-center gap-2.5">
            <StageStrip
              stages={run.stages}
              defs={catalogue.data?.stages}
              className="w-[180px] shrink-0 sm:w-[220px]"
            />
            {stageLabel && (
              <span className="truncate font-mono text-[10.5px] text-muted-foreground">
                {stageLabel}
              </span>
            )}
          </span>

          {sentence && (
            <span
              className={cn(
                "line-clamp-2 text-[12.5px] text-pretty",
                run.state === "failed" ? "text-rose-300/90" : "text-foreground/75"
              )}
            >
              {sentence}
            </span>
          )}

          <FactLine
            facts={[
              run.requested_by.label ? `by ${run.requested_by.label}` : null,
              sinceText(run.created_at),
              webhooks ? `${webhooks} webhook${webhooks === 1 ? "" : "s"}` : null,
            ]}
          />
        </span>

        <span className="hidden shrink-0 items-center gap-2 sm:flex">
          <RunStateBadge state={run.state} label={run.state_label} />
          <IconChevronRight className="size-4 text-muted-foreground" />
        </span>
      </Link>
    </li>
  );
}
