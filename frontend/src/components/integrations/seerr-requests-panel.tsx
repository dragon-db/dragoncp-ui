import { useState } from "react";
import { toast } from "sonner";
import {
  IconAdjustments,
  IconAlertTriangle,
  IconCheck,
  IconCircle,
  IconCircleCheck,
  IconCircleDot,
  IconCircleX,
  IconListCheck,
  IconLock,
  IconRefresh,
  IconX,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { FilterChips, ListPagination } from "@/components/layout/list-controls";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import { Notice, TitlePoster, ToneChip } from "@/components/integrations/library-bits";
import { TONE_BAR, TONE_TEXT, libraryError } from "@/components/integrations/library-vocab";
import { since } from "@/components/integrations/jellyfin-vocab";
import { STEP_LABELS, seasonList, titleName } from "@/components/integrations/seerr-vocab";
import { ApproveDialog } from "@/components/integrations/seerr-approve-dialog";
import {
  useDecideRequest,
  useSeerrLive,
  useSeerrRequests,
  useSeerrSummary,
  useSeerrUsers,
} from "@/hooks/useSeerr";
import type { RequestSeason, RequestStep, SeerrRequest } from "@/lib/seerr-types";

const EVERYONE = "__everyone__";

const TYPES = [
  { value: "all", label: "Films and series" },
  { value: "movie", label: "Films" },
  { value: "tv", label: "Series" },
];

const SORTS = [
  { value: "added", label: "Newest first" },
  { value: "modified", label: "Last changed" },
];

type Decision = "approve" | "decline" | "retry";

/**
 * Seerr's requests, admin side: the ones waiting for a yes or no, and where
 * every approved one has got to — on the remote server, syncing here, in
 * Jellyfin — which Seerr itself only calls "processing".
 */
export function SeerrRequestsPanel({ onOpenSettings }: { onOpenSettings: () => void }) {
  const [view, setView] = useState("waiting");
  const [type, setType] = useState("all");
  const [sort, setSort] = useState("added");
  const [user, setUser] = useState("");
  const [skip, setSkip] = useState(0);
  const [take, setTake] = useState(25);
  const [confirm, setConfirm] = useState<{ request: SeerrRequest; decision: Decision } | null>(
    null
  );
  const [editing, setEditing] = useState<SeerrRequest | null>(null);

  useSeerrLive();
  const summary = useSeerrSummary();
  const users = useSeerrUsers();
  const { data, isLoading, isFetching, isError, error, refetch } = useSeerrRequests({
    view,
    type,
    sort,
    user,
    take,
    skip,
  });
  const decide = useDecideRequest();

  const counts = summary.data?.requests;
  const views = [
    { value: "waiting", label: "Waiting", count: counts?.pending },
    { value: "progress", label: "In progress", count: counts?.processing },
    { value: "failed", label: "Failed" },
    { value: "done", label: "Done", count: counts?.completed },
    { value: "all", label: "All", count: counts?.total },
  ];
  const userItems = [
    { value: EVERYONE, label: "Everyone" },
    ...(users.data ?? []).map((person) => ({ value: String(person.id), label: person.name })),
  ];
  const requests = data?.requests ?? [];
  const canChange = data?.can_change ?? summary.data?.can_change ?? false;
  const whyNot = data?.why_not || summary.data?.why_not || "";

  const resetTo = (apply: () => void) => {
    apply();
    setSkip(0);
  };

  const run = async (request: SeerrRequest, decision: Decision, changes?: object) => {
    const name = titleName(request.title);
    try {
      await decide.mutateAsync({ id: request.id, decision, changes });
      toast.success(
        decision === "approve"
          ? `Approved ${name}`
          : decision === "decline"
            ? `Declined ${name}`
            : `Sent ${name} again`
      );
      setEditing(null);
    } catch (failure) {
      toast.error(libraryError(failure, "Seerr did not do it"));
    }
  };

  return (
    <div className="space-y-3">
      {!canChange && whyNot && data?.state === "ok" && (
        <Notice tone="muted" icon={IconLock}>
          <span>{whyNot} </span>
          <button
            type="button"
            onClick={onOpenSettings}
            className="font-medium text-foreground underline-offset-2 hover:underline"
          >
            Open Connection
          </button>
        </Notice>
      )}
      <SectionCard
        label="Requests"
        description={data?.state === "ok" ? describe(view, data.total) : undefined}
        actions={
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            <IconRefresh className={cn("size-3.5", isFetching && "animate-spin")} />
            Refresh
          </Button>
        }
        toolbar={
          <div className="flex w-full flex-wrap items-center gap-2">
            <div className="flex flex-wrap gap-1">
              <FilterChips
                choices={views}
                value={view}
                onChange={(value) => resetTo(() => setView(value))}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
              <SmallSelect
                items={TYPES}
                value={type}
                label="Films or series"
                onChange={(value) => resetTo(() => setType(value))}
              />
              {userItems.length > 1 && (
                <SmallSelect
                  items={userItems}
                  value={user || EVERYONE}
                  label="Who asked"
                  onChange={(value) => resetTo(() => setUser(value === EVERYONE ? "" : value))}
                />
              )}
              <SmallSelect
                items={SORTS}
                value={sort}
                label="Order"
                onChange={(value) => resetTo(() => setSort(value))}
              />
            </div>
          </div>
        }
      >
        {isLoading ? (
          <RowsSkeleton />
        ) : isError ? (
          <div className="p-3">
            <Notice tone="crit" icon={IconAlertTriangle}>
              {libraryError(error, "Could not load the requests.")}
            </Notice>
          </div>
        ) : data && data.state !== "ok" ? (
          <div className="p-3">
            <Notice tone={data.state === "off" ? "muted" : "crit"} icon={IconAlertTriangle}>
              {data.message || "Seerr did not answer."}
            </Notice>
          </div>
        ) : requests.length === 0 ? (
          <SectionEmpty
            icon={IconListCheck}
            title={
              view === "waiting"
                ? "Nothing waiting for approval"
                : view === "progress"
                  ? "Nothing on its way"
                  : "No requests here"
            }
            hint={
              view === "waiting"
                ? "New requests appear here the moment Seerr's webhook says so, or on the next refresh."
                : "Try another filter."
            }
          />
        ) : (
          <>
            <ul
              className={cn(
                "divide-y divide-border/70 transition-opacity",
                isFetching && "opacity-60"
              )}
            >
              {requests.map((request) => (
                <RequestRow
                  key={request.id}
                  request={request}
                  canChange={canChange}
                  busy={decide.isPending && decide.variables?.id === request.id}
                  onDecide={(decision) => setConfirm({ request, decision })}
                  onEdit={() => setEditing(request)}
                />
              ))}
            </ul>
            <ListPagination
              offset={skip}
              limit={take}
              total={data?.total ?? 0}
              count={requests.length}
              onOffsetChange={setSkip}
              onLimitChange={(next) => {
                setTake(next);
                setSkip(0);
              }}
              noun="requests"
            />
          </>
        )}
      </SectionCard>

      {confirm && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setConfirm(null)}
          title={confirmTitle(confirm.request, confirm.decision)}
          description={confirmText(confirm.request, confirm.decision)}
          confirmLabel={
            confirm.decision === "approve"
              ? "Approve"
              : confirm.decision === "decline"
                ? "Decline"
                : "Retry"
          }
          destructive={confirm.decision === "decline"}
          pending={decide.isPending}
          onConfirm={() => run(confirm.request, confirm.decision)}
        />
      )}
      <ApproveDialog
        request={editing}
        pending={decide.isPending}
        onClose={() => setEditing(null)}
        onApprove={(changes) => editing && run(editing, "approve", changes)}
      />
    </div>
  );
}

/** "26 waiting for approval", "1 failed", "343 in all". */
function describe(view: string, total: number) {
  const n = total.toLocaleString();
  if (view === "waiting") return `${n} waiting for approval.`;
  if (view === "progress") return `${n} approved and on ${total === 1 ? "its" : "their"} way.`;
  if (view === "failed") return `${n} failed in Seerr.`;
  if (view === "done") return `${n} done.`;
  return `${n} in all.`;
}

function confirmTitle(request: SeerrRequest, decision: Decision) {
  const name = titleName(request.title);
  if (decision === "approve") return `Approve ${name}?`;
  if (decision === "decline") return `Decline ${name}?`;
  return `Send ${name} again?`;
}

function confirmText(request: SeerrRequest, decision: Decision) {
  const service = request.type === "tv" ? "Sonarr" : "Radarr";
  const what =
    request.type === "tv" ? seasonList(request.seasons.map((s) => s.number)) : "The film";
  const who = request.requested_by?.name ?? "someone";
  if (decision === "approve")
    return `${what}, asked for by ${who}. Seerr hands it to ${service}, which starts searching and downloading on the remote server.`;
  if (decision === "decline")
    return `Seerr tells ${who} the request was declined. They can ask again later.`;
  return `Seerr hands it to ${service} again. Nothing else changes.`;
}

function SmallSelect({
  items,
  value,
  label,
  onChange,
}: {
  items: { value: string; label: string }[];
  value: string;
  label: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select items={items} value={value} onValueChange={(next) => next && onChange(String(next))}>
      <SelectTrigger size="sm" className="h-8 min-w-[140px]" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function RequestRow({
  request,
  canChange,
  busy,
  onDecide,
  onEdit,
}: {
  request: SeerrRequest;
  canChange: boolean;
  busy: boolean;
  onDecide: (decision: Decision) => void;
  onEdit: () => void;
}) {
  const { title, stage } = request;
  const decided = request.status === "approved" || request.status === "completed";
  const percent = typeof stage.percent === "number" ? stage.percent : null;
  return (
    <li className="flex gap-3 px-3.5 py-3">
      <TitlePoster src={title.poster} movie={title.type === "movie"} className="w-12 self-start" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-start justify-between gap-3">
          <p className="min-w-0 text-[13.5px] leading-snug break-words">
            <span className="font-semibold text-foreground">{titleName(title)}</span>
            {title.year ? <span className="text-muted-foreground"> ({title.year})</span> : null}
            <span className="ml-1.5 text-[12px] whitespace-nowrap text-muted-foreground">
              {title.type === "movie" ? "Film" : seasonList(request.seasons.map((s) => s.number))}
            </span>
          </p>
          <div className="flex shrink-0 items-center gap-1.5">
            {request.is4k && <ToneChip tone="info" icon={IconCircle} label="4K" size="sm" />}
            <ToneChip
              tone={stage.tone}
              icon={stageIcon(stage.tone)}
              label={stage.label}
              title={stage.detail || undefined}
              size="sm"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
          <span className="font-medium text-foreground-2">
            {request.requested_by?.name ?? "Someone"}
          </span>
          {request.requested_at && (
            <span title={new Date(request.requested_at).toLocaleString()}>
              asked {since(request.requested_at)}
            </span>
          )}
          {decided && request.decided_by && (
            <span>
              approved by {request.decided_by.name}
              {request.updated_at ? ` · ${since(request.updated_at)}` : ""}
            </span>
          )}
          {request.profile && <span>{request.profile}</span>}
        </div>

        {decided && <Steps steps={request.steps} />}

        {(stage.detail || percent != null) && decided && stage.key !== "in_jellyfin" && (
          <div className="space-y-1">
            {percent != null && (
              <div
                className="h-1 max-w-md overflow-hidden rounded-full bg-white/8"
                role="progressbar"
                aria-valuenow={percent}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${stage.label}: ${percent}%`}
              >
                <div
                  className={cn(
                    "h-full rounded-full transition-[width] duration-500",
                    TONE_BAR[stage.tone]
                  )}
                  style={{ width: `${Math.max(2, Math.min(100, percent))}%` }}
                />
              </div>
            )}
            {stage.detail && (
              <p
                className={cn(
                  "text-[12px]",
                  stage.tone === "warn" || stage.tone === "crit"
                    ? TONE_TEXT[stage.tone]
                    : "text-muted-foreground"
                )}
              >
                {stage.detail}
              </p>
            )}
          </div>
        )}
        {!decided && stage.detail && (
          <p className="text-[12px] text-muted-foreground">{stage.detail}</p>
        )}

        {request.type === "tv" && request.seasons.length > 0 && decided && (
          <div className="flex flex-wrap gap-1">
            {request.seasons.map((season) => (
              <SeasonChip key={season.number} season={season} />
            ))}
          </div>
        )}

        {request.actions.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {request.actions.includes("approve") && (
              <>
                <Button size="sm" disabled={!canChange || busy} onClick={() => onDecide("approve")}>
                  <IconCheck className="size-3.5" />
                  Approve
                </Button>
                <Button size="sm" variant="outline" disabled={!canChange || busy} onClick={onEdit}>
                  <IconAdjustments className="size-3.5" />
                  Change, then approve
                </Button>
              </>
            )}
            {request.actions.includes("decline") && (
              <Button
                size="sm"
                variant="destructive"
                disabled={!canChange || busy}
                onClick={() => onDecide("decline")}
              >
                <IconX className="size-3.5" />
                Decline
              </Button>
            )}
            {request.actions.includes("retry") && (
              <Button
                size="sm"
                variant="outline"
                disabled={!canChange || busy}
                onClick={() => onDecide("retry")}
              >
                <IconRefresh className="size-3.5" />
                Retry
              </Button>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

function stageIcon(tone: string) {
  if (tone === "ok") return IconCircleCheck;
  if (tone === "crit") return IconCircleX;
  if (tone === "warn") return IconAlertTriangle;
  return IconCircleDot;
}

const STEP_STYLE: Record<RequestStep["state"], { icon: typeof IconCircle; className: string }> = {
  done: { icon: IconCircleCheck, className: "text-emerald-400" },
  active: { icon: IconCircleDot, className: "text-brand-hover" },
  waiting: { icon: IconCircle, className: "text-muted-foreground" },
  problem: { icon: IconAlertTriangle, className: "text-amber-400" },
  todo: { icon: IconCircle, className: "text-muted-foreground/50" },
};

/** Approved → on the remote server → synced here → in Jellyfin, each ticked off. */
function Steps({ steps }: { steps: RequestStep[] }) {
  return (
    // Two by two on a phone, where a wrapped row would start with a dangling
    // connector; one row from `sm` up.
    <ol
      className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px] sm:flex sm:flex-wrap sm:items-center sm:gap-x-1.5"
      aria-label="Progress"
    >
      {steps.map((step, index) => {
        const style = STEP_STYLE[step.state];
        const Glyph = style.icon;
        return (
          <li key={step.key} className="flex items-center gap-1.5">
            {index > 0 && (
              <span
                aria-hidden
                className={cn(
                  "hidden h-px w-5 sm:block",
                  step.state === "done" ? "bg-emerald-500/50" : "bg-border"
                )}
              />
            )}
            <span
              className={cn(
                "flex items-center gap-1",
                step.state === "todo" ? "text-muted-foreground/60" : "text-foreground-2"
              )}
            >
              <Glyph className={cn("size-3.5 shrink-0", style.className)} />
              {STEP_LABELS[step.key]}
              <span className="sr-only">: {step.state}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function SeasonChip({ season }: { season: RequestSeason }) {
  const counted =
    season.episodes_here != null && season.episodes_total
      ? ` · ${season.episodes_here}/${season.episodes_total}`
      : "";
  const [tone, words] =
    season.state === "available"
      ? (["ok", "in Jellyfin"] as const)
      : season.syncing
        ? (["brand", "syncing"] as const)
        : season.downloading
          ? (["brand", "downloading"] as const)
          : season.state === "partial"
            ? (["info", "partly"] as const)
            : (["muted", "not yet"] as const);
  return (
    <span
      className={cn(
        "rounded-md border px-1.5 py-0.5 font-mono text-[10.5px]",
        tone === "ok" && "border-emerald-500/30 text-emerald-300",
        tone === "brand" && "border-brand/35 text-brand-foreground",
        tone === "info" && "border-sky-500/30 text-sky-300",
        tone === "muted" && "border-border text-muted-foreground"
      )}
      title={
        season.episodes_here != null && season.episodes_total
          ? `${season.episodes_here} of ${season.episodes_total} episodes in Jellyfin`
          : undefined
      }
    >
      S{String(season.number).padStart(2, "0")} {words}
      {counted}
    </span>
  );
}

function RowsSkeleton() {
  return (
    <div className="divide-y divide-border/70">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex gap-3 px-3.5 py-3">
          <Skeleton className="aspect-[2/3] w-12 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/2" />
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
        </div>
      ))}
    </div>
  );
}
