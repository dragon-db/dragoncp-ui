import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { ActorBadge } from "@/components/activity/actor-badge";
import { useActivity, useActivityFilters } from "@/hooks/useActivity";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  IconAlertTriangle,
  IconChevronLeft,
  IconChevronRight,
  IconHistory,
  IconSearch,
} from "@tabler/icons-react";

const PAGE_SIZE = 50;

/**
 * Stands in for "no filter". A select needs a real value for its unfiltered
 * state — it cannot be the empty string, which reads as a cleared field.
 *
 * Every dropdown is given this option in its own list, so the "any" case has a
 * label like everything else. `<SelectValue />` shows the label of the selected
 * item only when the Select is handed an `items` list; without one it falls
 * back to printing the raw value, which is how this sentinel ended up on screen.
 */
const ANY = "__any__";

/** Action families, in the order they matter when scanning for a culprit. */
const GROUPS = [
  { value: ANY, label: "Everything" },
  { value: "backup", label: "Backups" },
  { value: "transfer", label: "Syncs" },
  { value: "notification", label: "Notifications" },
  { value: "settings", label: "Settings" },
  { value: "auth", label: "Sign-ins" },
  { value: "simulation", label: "Simulation" },
  { value: "explore", label: "Explore" },
  { value: "ssh", label: "Connection" },
];

const OUTCOMES = [
  { value: ANY, label: "Any outcome" },
  { value: "ok", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "refused", label: "Refused" },
];

function whenText(iso: string): string {
  // Stored as UTC by SQLite's CURRENT_TIMESTAMP without a zone marker.
  const at = new Date(iso.includes("T") ? iso : `${iso.replace(" ", "T")}Z`);
  if (Number.isNaN(at.getTime())) return iso;

  const seconds = Math.round((Date.now() - at.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return at.toLocaleDateString();
}

function exactWhen(iso: string): string {
  const at = new Date(iso.includes("T") ? iso : `${iso.replace(" ", "T")}Z`);
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleString();
}

export function ActivityPage() {
  const [group, setGroup] = useState(ANY);
  const [actor, setActor] = useState(ANY);
  const [outcome, setOutcome] = useState(ANY);
  const [searchInput, setSearchInput] = useState("");
  const [page, setPage] = useState(0);

  const search = useDebouncedValue(searchInput, 300);

  const query = useMemo(
    () => ({
      group: group === ANY ? undefined : group,
      actor: actor === ANY ? undefined : actor,
      outcome: outcome === ANY ? undefined : outcome,
      search: search || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [group, actor, outcome, search, page]
  );

  const { data, isLoading, isError } = useActivity(query);
  const { data: filters } = useActivityFilters();

  // One list per dropdown, used both to render the options and to tell the
  // Select how to label the selected one. Deriving both from the same array is
  // what keeps the closed menu and the open menu saying the same thing.
  const actorItems = useMemo(() => {
    // The server groups actors by kind, name AND account id, so one name can
    // come back more than once — a name reused after a rename, or entries
    // written with and without an account id. The filter matches on name, so
    // duplicates would be two identical options and two identical React keys.
    const byName = new Map<string, { value: string; label: string }>();
    for (const a of filters?.actors ?? []) {
      if (byName.has(a.actor_name)) continue;
      byName.set(a.actor_name, {
        value: a.actor_name,
        label: a.actor_kind === "admin" ? a.actor_name : `AUTO / ${a.actor_name}`,
      });
    }
    return [{ value: ANY, label: "Anyone" }, ...byName.values()];
  }, [filters]);

  const entries = data?.entries ?? [];
  const total = data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  // Any filter change invalidates the current page number.
  const reset = (apply: () => void) => {
    apply();
    setPage(0);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Activity"
        description="Who did what, and when — people and automation alike"
      />

      <Card className="border-neutral-800 bg-neutral-900/50">
        <CardContent className="flex flex-wrap items-center gap-3 py-4">
          <div className="relative min-w-[220px] flex-1">
            <IconSearch className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchInput}
              onChange={(event) => reset(() => setSearchInput(event.target.value))}
              placeholder="Search what happened, or what it happened to"
              className="h-10 rounded-xl bg-black/30 pl-9"
            />
          </div>

          <Select
            items={GROUPS}
            value={group}
            onValueChange={(v) => reset(() => setGroup(v ?? ANY))}
          >
            <SelectTrigger className="h-10 w-[170px] rounded-xl bg-black/30">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {GROUPS.map((g) => (
                <SelectItem key={g.value} value={g.value}>
                  {g.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            items={actorItems}
            value={actor}
            onValueChange={(v) => reset(() => setActor(v ?? ANY))}
          >
            <SelectTrigger className="h-10 w-[200px] rounded-xl bg-black/30">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {actorItems.map((a) => (
                <SelectItem key={a.value} value={a.value}>
                  {a.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            items={OUTCOMES}
            value={outcome}
            onValueChange={(v) => reset(() => setOutcome(v ?? ANY))}
          >
            <SelectTrigger className="h-10 w-[150px] rounded-xl bg-black/30">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {OUTCOMES.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card className="border-neutral-800 bg-neutral-900/50">
        <CardContent className="p-0">
          {isLoading && (
            <div className="space-y-3 p-5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-3 p-6 text-sm text-red-300">
              <IconAlertTriangle className="size-5 shrink-0" />
              The activity trail could not be read.
            </div>
          )}

          {!isLoading && !isError && entries.length === 0 && (
            <div className="flex flex-col items-center gap-2 p-12 text-center">
              <IconHistory className="size-8 text-neutral-600" />
              <p className="text-sm font-medium text-neutral-300">Nothing recorded yet</p>
              <p className="max-w-sm text-xs text-neutral-500">
                Actions are recorded from the moment this was switched on. Anything done
                before then has no entry — it was never captured, rather than hidden.
              </p>
            </div>
          )}

          {!isLoading && !isError && entries.length > 0 && (
            <ul className="divide-y divide-neutral-800/70">
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5 hover:bg-white/[0.02]"
                >
                  <div className="w-[168px] shrink-0">
                    <ActorBadge kind={entry.actor_kind} name={entry.actor_name} size="sm" />
                  </div>

                  <div className="min-w-[220px] flex-1">
                    <p className="text-sm text-neutral-200">{entry.summary}</p>
                    {entry.target_label && (
                      <p className="truncate text-xs text-neutral-500">{entry.target_label}</p>
                    )}
                  </div>

                  {entry.outcome !== "ok" && (
                    <Badge
                      variant="outline"
                      className={
                        entry.outcome === "failed"
                          ? "border-red-500/40 text-red-300"
                          : "border-amber-500/40 text-amber-300"
                      }
                    >
                      {entry.outcome === "failed" ? "Failed" : "Refused"}
                    </Badge>
                  )}

                  <time
                    className="w-[92px] shrink-0 text-right text-xs text-neutral-500"
                    title={exactWhen(entry.occurred_at)}
                  >
                    {whenText(entry.occurred_at)}
                  </time>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-neutral-400">
          <span>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="rounded-lg"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              <IconChevronLeft className="size-4" /> Newer
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="rounded-lg"
              disabled={page >= lastPage}
              onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
            >
              Older <IconChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
