import { useState } from "react";
import { toast } from "sonner";
import {
  IconAlertTriangle,
  IconExternalLink,
  IconHeartbeat,
  IconInfoCircle,
  IconLoader2,
  IconRefresh,
  IconServer2,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { FilterChips } from "@/components/layout/list-controls";
import { Notice } from "@/components/integrations/library-bits";
import { libraryError, sinceText, stampText } from "@/components/integrations/library-vocab";
import { HealthDot, ProtocolMark } from "@/components/integrations/prowlarr-bits";
import { CATEGORIES, INDEXER_STATE } from "@/components/integrations/prowlarr-vocab";
import { useProwlarrOverview, useRefreshOverview, useTestIndexer } from "@/hooks/useProwlarr";
import type { ProwlarrIndexer } from "@/lib/prowlarr-types";

function categoryName(id: number): string {
  return CATEGORIES.find((c) => c.id === id)?.label ?? String(id);
}

const SEARCH_TYPE_WORDS: Record<string, string> = {
  search: "Search",
  tvsearch: "TV",
  movie: "Film",
  music: "Music",
  book: "Books",
};

/**
 * Which indexers work: healthy, failing, paused by Prowlarr after failures,
 * or switched off; how fast they answer and how often they fail. Read from
 * Prowlarr's own records — opening this tab asks no indexer anything. Test
 * asks one, when pressed.
 */
export function ProwlarrIndexersPanel({ onOpenSettings }: { onOpenSettings: () => void }) {
  const overview = useProwlarrOverview();
  const refresh = useRefreshOverview();
  const [view, setView] = useState("all");
  const data = overview.data;

  if (overview.isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }
  if (overview.isError || !data || data.state !== "ok") {
    return (
      <Notice tone="crit" icon={IconAlertTriangle}>
        <span>{data?.message || libraryError(overview.error, "Could not reach Prowlarr.")} </span>
        <button
          type="button"
          onClick={onOpenSettings}
          className="font-medium text-foreground underline-offset-2 hover:underline"
        >
          Open Connection
        </button>
      </Notice>
    );
  }

  const indexers = data.indexers ?? [];
  const problems = indexers.filter((i) => i.state === "paused" || i.state === "failing");
  const views = [
    { value: "all", label: "All", count: indexers.length },
    { value: "problems", label: "Problems", count: problems.length },
    {
      value: "torrent",
      label: "Torrent",
      count: indexers.filter((i) => i.protocol === "torrent").length,
    },
    {
      value: "usenet",
      label: "Usenet",
      count: indexers.filter((i) => i.protocol === "usenet").length,
    },
    { value: "off", label: "Off", count: indexers.filter((i) => !i.enabled).length },
  ].filter((v) => v.value === "all" || v.count > 0);
  const shown = indexers.filter((i) =>
    view === "problems"
      ? i.state === "paused" || i.state === "failing"
      : view === "off"
        ? !i.enabled
        : view === "torrent" || view === "usenet"
          ? i.protocol === view
          : true
  );
  const counts = {
    ok: indexers.filter((i) => i.state === "ok").length,
    failing: indexers.filter((i) => i.state === "failing").length,
    paused: indexers.filter((i) => i.state === "paused").length,
    off: indexers.filter((i) => i.state === "off").length,
  };
  const warnings = (data.health ?? []).filter((h) => h.level !== "ok");
  const clients = data.download_clients ?? [];

  return (
    <div className="space-y-3">
      {warnings.map((warning, index) => (
        <Notice
          key={index}
          tone={warning.level === "error" ? "crit" : warning.level === "notice" ? "muted" : "warn"}
          icon={warning.level === "notice" ? IconInfoCircle : IconAlertTriangle}
        >
          <span>{warning.message} </span>
          {warning.wiki_url && (
            <a
              href={warning.wiki_url}
              target="_blank"
              rel="noreferrer noopener"
              className="font-medium text-foreground underline-offset-2 hover:underline"
            >
              What to do
            </a>
          )}
        </Notice>
      ))}

      <div className="grid grid-cols-4 gap-2">
        {(Object.keys(counts) as (keyof typeof counts)[]).map((state) => (
          <div key={state} className="rounded-xl border border-border/70 bg-card/60 px-2.5 py-2">
            <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <HealthDot state={state} />
              {INDEXER_STATE[state].label}
            </p>
            <p className="font-mono text-lg font-semibold text-foreground tabular-nums">
              {counts[state]}
            </p>
          </div>
        ))}
      </div>

      <SectionCard
        label="Indexers"
        description={
          data.stats_available
            ? `Numbers cover the last ${data.stats_days} days.${data.version ? ` Prowlarr ${data.version}.` : ""}`
            : data.version
              ? `Prowlarr ${data.version}.`
              : undefined
        }
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            <IconRefresh className={cn("size-3.5", refresh.isPending && "animate-spin")} />
            Refresh
          </Button>
        }
        toolbar={
          <div className="flex flex-wrap gap-1">
            <FilterChips choices={views} value={view} onChange={setView} />
          </div>
        }
      >
        {shown.length === 0 ? (
          <SectionEmpty
            icon={IconServer2}
            title={view === "problems" ? "Every indexer is working" : "No indexers here"}
            hint={indexers.length ? "Try another filter." : "Add indexers in Prowlarr itself."}
          />
        ) : (
          <ul className="divide-y divide-border/70">
            {shown.map((indexer) => (
              <IndexerRow key={indexer.id} indexer={indexer} />
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard
        label="Download clients"
        description="Where “Send to download client” hands a release, and the category each kind of release goes in. Set up in Prowlarr."
      >
        {clients.length === 0 ? (
          <SectionEmpty
            icon={IconServer2}
            title="No download client in Prowlarr"
            hint="Add one in Prowlarr: Settings → Download Clients. Until then, use Copy magnet or Save file."
          />
        ) : (
          <ul className="divide-y divide-border/70">
            {clients.map((client) => (
              <li key={client.id} className="space-y-1 px-3.5 py-2.5 text-[13.5px]">
                <div className="flex items-center gap-2.5">
                  <ProtocolMark protocol={client.protocol} />
                  <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                    {client.name}
                  </span>
                  <span className="text-[12px] text-muted-foreground">{client.kind}</span>
                  <span
                    className={cn(
                      "text-[11px] font-semibold",
                      client.enabled ? "text-emerald-400" : "text-muted-foreground"
                    )}
                  >
                    {client.enabled ? "On" : "Off"}
                  </span>
                </div>
                {(client.mappings.length > 0 || client.category) && (
                  <p className="text-[12px] [overflow-wrap:anywhere] text-muted-foreground">
                    {[
                      ...client.mappings.map(
                        (m) => `${m.ids.map(categoryName).join(", ")} → ${m.category}`
                      ),
                      ...(client.category ? [`anything else → ${client.category}`] : []),
                    ].join(" · ")}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

function IndexerRow({ indexer }: { indexer: ProwlarrIndexer }) {
  const test = useTestIndexer();
  const state = INDEXER_STATE[indexer.state];
  const stats = indexer.stats;

  const run = async () => {
    try {
      const result = await test.mutateAsync(indexer.id);
      toast.success(`${indexer.name}: ${result.message}`);
    } catch (failure) {
      toast.error(`${indexer.name}: ${libraryError(failure, "the test failed")}`);
    }
  };

  return (
    <li className="space-y-1.5 px-3.5 py-3">
      <div className="flex items-center gap-2">
        <HealthDot state={indexer.state} />
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-foreground">
          {indexer.name}
        </span>
        <span className={cn("text-[11px] font-semibold", state.text)}>{state.label}</span>
        <Button
          size="sm"
          variant="outline"
          disabled={test.isPending || !indexer.enabled}
          onClick={run}
          aria-label={`Test ${indexer.name}`}
        >
          {test.isPending ? (
            <IconLoader2 className="size-3.5 animate-spin" />
          ) : (
            <IconHeartbeat className="size-3.5" />
          )}
          Test
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
        <ProtocolMark protocol={indexer.protocol} />
        <span className="capitalize">
          {indexer.privacy === "semiprivate" ? "semi-private" : indexer.privacy}
        </span>
        {indexer.priority != null && <span>priority {indexer.priority}</span>}
        {indexer.search_types.length > 0 && (
          <span>{indexer.search_types.map((t) => SEARCH_TYPE_WORDS[t] ?? t).join(" · ")}</span>
        )}
        {indexer.site && (
          <a
            href={indexer.site}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-0.5 hover:text-foreground"
          >
            site
            <IconExternalLink className="size-3" />
          </a>
        )}
      </div>

      {stats && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11.5px] text-foreground-2 tabular-nums">
          <span title="Average time to answer a search">
            {stats.avg_ms != null ? `${(stats.avg_ms / 1000).toFixed(1)}s avg` : "— avg"}
          </span>
          <span>{stats.queries.toLocaleString()} searches</span>
          <span>{stats.grabs.toLocaleString()} grabs</span>
          {stats.failure_rate != null && (
            <span
              className={cn(
                stats.failure_rate >= 0.2
                  ? "text-rose-400"
                  : stats.failure_rate >= 0.05
                    ? "text-amber-400"
                    : undefined
              )}
            >
              {Math.round(stats.failure_rate * 100)}% failed
            </span>
          )}
        </div>
      )}

      {indexer.state === "paused" && (
        <p className="text-[12px] text-rose-300">
          Paused by Prowlarr after failures
          {indexer.paused_until && (
            <span title={stampText(indexer.paused_until)}>
              {" "}
              until{" "}
              {new Date(indexer.paused_until).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          )}
          {indexer.failing_since && <> · failing since {sinceText(indexer.failing_since)}</>}.
          Searches skip it until then; Test tries it now.
        </p>
      )}
      {indexer.state === "failing" && indexer.last_failure && (
        <p className="text-[12px] text-amber-300">
          Last failed {sinceText(indexer.last_failure)}
          {indexer.failing_since && <>, failing since {sinceText(indexer.failing_since)}</>}.
        </p>
      )}
    </li>
  );
}
