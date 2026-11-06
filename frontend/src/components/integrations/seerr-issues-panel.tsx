import { useState } from "react";
import { toast } from "sonner";
import {
  IconAlertTriangle,
  IconArrowBackUp,
  IconCircleCheck,
  IconLock,
  IconMessage2,
  IconMessageReport,
  IconRefresh,
  IconSend,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { FilterChips, ListPagination } from "@/components/layout/list-controls";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import { Notice, TitlePoster, ToneChip } from "@/components/integrations/library-bits";
import { libraryError } from "@/components/integrations/library-vocab";
import { episodeCode, since } from "@/components/integrations/jellyfin-vocab";
import { ISSUE_TYPES, titleName } from "@/components/integrations/seerr-vocab";
import {
  useReplyToIssue,
  useSeerrIssue,
  useSeerrIssues,
  useSeerrLive,
  useSeerrSummary,
  useSeerrUsers,
  useSetIssueState,
} from "@/hooks/useSeerr";
import type { SeerrIssue } from "@/lib/seerr-types";

const EVERYONE = "__everyone__";
const SORTS = [
  { value: "added", label: "Newest first" },
  { value: "modified", label: "Last changed" },
];
const MAX_MESSAGE = 2000;

/**
 * What users reported in Seerr: what is wrong (video, audio, subtitles), with
 * which episode, who said so, and the conversation. Replies and resolves go
 * through Seerr, which tells the user the way it always does.
 */
export function SeerrIssuesPanel({ onOpenSettings }: { onOpenSettings: () => void }) {
  const [view, setView] = useState("open");
  const [sort, setSort] = useState("added");
  const [user, setUser] = useState("");
  const [skip, setSkip] = useState(0);
  const [take, setTake] = useState(25);
  const [openId, setOpenId] = useState<number | null>(null);

  useSeerrLive();
  const summary = useSeerrSummary();
  const users = useSeerrUsers();
  const { data, isLoading, isFetching, isError, error, refetch } = useSeerrIssues({
    view,
    sort,
    user,
    take,
    skip,
  });
  const counts = summary.data?.issues;
  const views = [
    { value: "open", label: "Open", count: counts?.open },
    { value: "resolved", label: "Resolved", count: counts?.closed },
    { value: "all", label: "All", count: counts?.total },
  ];
  const userItems = [
    { value: EVERYONE, label: "Everyone" },
    ...(users.data ?? []).map((person) => ({ value: String(person.id), label: person.name })),
  ];
  const issues = data?.issues ?? [];
  const canChange = data?.can_change ?? summary.data?.can_change ?? false;
  const whyNot = data?.why_not || summary.data?.why_not || "";

  const resetTo = (apply: () => void) => {
    apply();
    setSkip(0);
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
        label="Issues"
        description={
          data?.state === "ok"
            ? `${data.total.toLocaleString()} ${view === "all" ? "in all" : view}.`
            : undefined
        }
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
              {userItems.length > 1 && (
                <SmallSelect
                  items={userItems}
                  value={user || EVERYONE}
                  label="Who reported"
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
              {libraryError(error, "Could not load the issues.")}
            </Notice>
          </div>
        ) : data && data.state !== "ok" ? (
          <div className="p-3">
            <Notice tone={data.state === "off" ? "muted" : "crit"} icon={IconAlertTriangle}>
              {data.message || "Seerr did not answer."}
            </Notice>
          </div>
        ) : issues.length === 0 ? (
          <SectionEmpty
            icon={IconMessageReport}
            title={view === "open" ? "No open issues" : "No issues here"}
            hint={
              view === "open"
                ? "When a user reports a problem in Seerr, it appears here."
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
              {issues.map((issue) => (
                <IssueRow key={issue.id} issue={issue} onOpen={() => setOpenId(issue.id)} />
              ))}
            </ul>
            <ListPagination
              offset={skip}
              limit={take}
              total={data?.total ?? 0}
              count={issues.length}
              onOffsetChange={setSkip}
              onLimitChange={(next) => {
                setTake(next);
                setSkip(0);
              }}
              noun="issues"
            />
          </>
        )}
      </SectionCard>

      <IssueSheet
        issueId={openId}
        preview={issues.find((issue) => issue.id === openId) ?? null}
        canChange={canChange}
        whyNot={whyNot}
        onClose={() => setOpenId(null)}
      />
    </div>
  );
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

function where(issue: SeerrIssue): string {
  if (issue.season == null) return issue.title.type === "movie" ? "" : "Whole series";
  if (issue.episode == null) return `Season ${issue.season}`;
  return episodeCode(issue.season, issue.episode);
}

function IssueRow({ issue, onOpen }: { issue: SeerrIssue; onOpen: () => void }) {
  const type = ISSUE_TYPES[issue.type];
  const open = issue.status === "open";
  const place = where(issue);
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full gap-3 px-3.5 py-3 text-left transition-colors hover:bg-muted/30 focus-visible:bg-muted/40 focus-visible:outline-none"
      >
        <TitlePoster
          src={issue.title.poster}
          movie={issue.title.type === "movie"}
          className="w-10 self-start"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start justify-between gap-3">
            <p className="min-w-0 text-[13.5px] leading-snug break-words">
              <span className="font-semibold text-foreground">{titleName(issue.title)}</span>
              {place && (
                <span className="ml-1.5 font-mono text-[12px] text-foreground-2">{place}</span>
              )}
            </p>
            <div className="flex shrink-0 items-center gap-1.5">
              <ToneChip
                tone={open ? "warn" : "muted"}
                icon={type.icon}
                label={type.label}
                size="sm"
              />
              {!open && <ToneChip tone="ok" icon={IconCircleCheck} label="Resolved" size="sm" />}
            </div>
          </div>
          {issue.message && (
            <p className="line-clamp-2 text-[12.5px] whitespace-pre-line text-foreground-2">
              {issue.message}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
            <span className="font-medium text-foreground-2">
              {issue.reported_by?.name ?? "Someone"}
            </span>
            {issue.reported_at && <span>{since(issue.reported_at)}</span>}
            {issue.replies > 0 && (
              <span className="flex items-center gap-1">
                <IconMessage2 className="size-3.5" />
                {issue.replies} repl{issue.replies === 1 ? "y" : "ies"}
              </span>
            )}
          </div>
        </div>
      </button>
    </li>
  );
}

function IssueSheet({
  issueId,
  preview,
  canChange,
  whyNot,
  onClose,
}: {
  issueId: number | null;
  preview: SeerrIssue | null;
  canChange: boolean;
  whyNot: string;
  onClose: () => void;
}) {
  return (
    <Sheet open={issueId != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className="gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl"
      >
        {issueId != null && (
          <IssueBody
            key={issueId}
            issueId={issueId}
            preview={preview}
            canChange={canChange}
            whyNot={whyNot}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function IssueBody({
  issueId,
  preview,
  canChange,
  whyNot,
}: {
  issueId: number;
  preview: SeerrIssue | null;
  canChange: boolean;
  whyNot: string;
}) {
  const detail = useSeerrIssue(issueId);
  const reply = useReplyToIssue();
  const setState = useSetIssueState();
  const [message, setMessage] = useState("");
  const [confirm, setConfirm] = useState<"resolve" | "reopen" | null>(null);
  const issue = detail.data?.issue ?? preview;
  const allowed = detail.data?.can_change ?? canChange;
  const reason = detail.data?.why_not || whyNot;

  if (!issue) {
    return (
      <>
        <SheetHeader className="border-b border-border px-4 py-3 pr-12">
          <SheetTitle>
            {detail.isError ? "Could not load this issue" : "Loading the issue"}
          </SheetTitle>
        </SheetHeader>
        <div className="p-4">
          {detail.isError ? (
            <Notice tone="crit" icon={IconAlertTriangle}>
              {libraryError(detail.error, "Seerr did not answer.")}
            </Notice>
          ) : (
            <Skeleton className="h-24 w-full" />
          )}
        </div>
      </>
    );
  }

  const type = ISSUE_TYPES[issue.type];
  const open = issue.status === "open";
  const place = where(issue);
  const busy = reply.isPending || setState.isPending;

  const send = async (resolve: boolean) => {
    try {
      await reply.mutateAsync({ id: issue.id, message: message.trim(), resolve });
      setMessage("");
      toast.success(resolve ? "Replied and resolved" : "Reply sent");
    } catch (failure) {
      toast.error(libraryError(failure, "Seerr did not take the reply"));
    }
  };

  const change = async (state: "resolve" | "reopen") => {
    try {
      await setState.mutateAsync({ id: issue.id, state });
      toast.success(state === "resolve" ? "Issue resolved" : "Issue reopened");
    } catch (failure) {
      toast.error(libraryError(failure, "Seerr did not change it"));
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <SheetHeader className="gap-2 border-b border-border px-4 py-3 pr-12">
        <div className="flex gap-3">
          <TitlePoster
            src={issue.title.poster}
            movie={issue.title.type === "movie"}
            className="w-12"
          />
          <div className="min-w-0 space-y-1">
            <SheetTitle className="text-base break-words">
              {titleName(issue.title)}
              {issue.title.year ? (
                <span className="font-normal text-muted-foreground"> ({issue.title.year})</span>
              ) : null}
            </SheetTitle>
            <div className="flex flex-wrap items-center gap-1.5">
              <ToneChip
                tone={open ? "warn" : "muted"}
                icon={type.icon}
                label={type.label}
                size="sm"
              />
              {place && <span className="font-mono text-[12px] text-foreground-2">{place}</span>}
              <ToneChip
                tone={open ? "warn" : "ok"}
                icon={open ? IconMessageReport : IconCircleCheck}
                label={open ? "Open" : "Resolved"}
                size="sm"
              />
            </div>
            <p className="text-[12px] text-muted-foreground">
              Reported by {issue.reported_by?.name ?? "someone"}
              {issue.reported_at ? ` · ${since(issue.reported_at)}` : ""}
            </p>
          </div>
        </div>
      </SheetHeader>

      <ol className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {issue.comments.map((comment, index) => (
          <li
            key={comment.id ?? index}
            className={cn(
              "rounded-lg border px-3 py-2",
              index === 0 ? "border-amber-500/25 bg-amber-500/5" : "border-border/70 bg-card/60"
            )}
          >
            <p className="mb-1 flex flex-wrap items-baseline gap-x-2 text-[12px]">
              <span className="font-semibold text-foreground">{comment.by?.name ?? "Someone"}</span>
              {comment.at && (
                <span
                  className="text-muted-foreground"
                  title={new Date(comment.at).toLocaleString()}
                >
                  {since(comment.at)}
                </span>
              )}
            </p>
            <p className="text-[13px] break-words whitespace-pre-wrap text-foreground-2">
              {comment.message || "(no message)"}
            </p>
          </li>
        ))}
      </ol>

      <div className="space-y-2 border-t border-border px-4 py-3">
        {!allowed && reason && (
          <Notice tone="muted" icon={IconLock}>
            {reason}
          </Notice>
        )}
        <Textarea
          value={message}
          onChange={(event) => setMessage(event.target.value.slice(0, MAX_MESSAGE))}
          placeholder={`Reply to ${issue.reported_by?.name ?? "them"}. Seerr tells them.`}
          disabled={!allowed || busy}
          rows={3}
          aria-label="Reply"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={!allowed || busy || !message.trim()}
            onClick={() => send(false)}
          >
            <IconSend className="size-3.5" />
            Reply
          </Button>
          {open && (
            <Button
              size="sm"
              variant="outline"
              disabled={!allowed || busy || !message.trim()}
              onClick={() => send(true)}
            >
              <IconCircleCheck className="size-3.5" />
              Reply and resolve
            </Button>
          )}
          <span className="flex-1" />
          {open ? (
            <Button
              size="sm"
              variant="ghost"
              disabled={!allowed || busy}
              onClick={() => setConfirm("resolve")}
            >
              <IconCircleCheck className="size-3.5" />
              Resolve
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              disabled={!allowed || busy}
              onClick={() => setConfirm("reopen")}
            >
              <IconArrowBackUp className="size-3.5" />
              Reopen
            </Button>
          )}
        </div>
      </div>

      {confirm && (
        <ConfirmDialog
          open
          onOpenChange={(next) => !next && setConfirm(null)}
          title={confirm === "resolve" ? "Resolve this issue?" : "Reopen this issue?"}
          description={
            confirm === "resolve"
              ? `Seerr tells ${issue.reported_by?.name ?? "the reporter"} it is resolved, with no message. To say what was done, write a reply and use Reply and resolve.`
              : "It goes back on the open list, and Seerr tells the reporter."
          }
          confirmLabel={confirm === "resolve" ? "Resolve" : "Reopen"}
          destructive={false}
          pending={busy}
          onConfirm={() => change(confirm)}
        />
      )}
    </div>
  );
}

function RowsSkeleton() {
  return (
    <div className="divide-y divide-border/70">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="flex gap-3 px-3.5 py-3">
          <Skeleton className="aspect-[2/3] w-10 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/2" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        </div>
      ))}
    </div>
  );
}
