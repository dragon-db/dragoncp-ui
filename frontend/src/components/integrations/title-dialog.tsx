import { useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  IconAlertTriangle,
  IconArrowsDiff,
  IconChevronDown,
  IconCircleCheck,
  IconCircleX,
  IconCloudDownload,
  IconHistory,
  IconFolderSearch,
  IconInfoCircle,
  IconListDetails,
  IconLoader2,
  IconRefresh,
  IconTool,
  IconX,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { PageTabsList } from "@/components/layout/page-tabs";
import {
  type LocalFile,
  type ServiceFile,
  type TitleDetail,
  type TitleEpisode,
  type TitleHistoryEntry,
  type TitleSeason,
  useLibrary,
  useLibraryTitle,
  useLibraryTitleHistory,
  useSyncLibraryItem,
} from "@/hooks/useMediaLibrary";
import { useExploreExecute, useExplorePlan } from "@/hooks/useExplore";
import { useSSHAutoConnect } from "@/hooks/useConfig";
import type { ExplorePlan } from "@/lib/explore-types";
import { EpisodeMark, TitlePoster } from "@/components/integrations/library-bits";
import {
  airText,
  formatSize,
  libraryError,
  sinceText,
  stampText,
} from "@/components/integrations/library-vocab";

/**
 * A finger-sized target on a phone (44px), the desktop size from `sm` up.
 * Links and small buttons here are text-sized, which a thumb misses.
 */
const TAP = "min-h-11 sm:min-h-0";
const TAP_BUTTON = "h-11 px-4 sm:h-8 sm:px-2.5";

/**
 * One Sonarr series or Radarr film in a pop-up over the list it was opened
 * from: the whole screen on a phone, a wide panel from `sm` up.
 *
 * Two tabs. Episodes answers the first question: is anything on the service
 * that is not here, and how do I get it. It leads with one sentence and one
 * action, and the seasons below are the evidence. History answers the second:
 * what happened to this title, on the service and here, and what did not get
 * done. Each fact is said once.
 */
export function TitleDialog({
  source,
  displayName,
  externalId,
  onClose,
}: {
  source: string;
  displayName: string;
  /** The title shown, by its TVDB or TMDB id; null when the pop-up is shut. */
  externalId: string | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={Boolean(externalId)} onOpenChange={(open) => !open && onClose()}>
      {/*
        Full screen below `sm`, where a centred card leaves no room for a list
        of episodes; a centred panel from `sm` up. The positioning classes are
        restated at `sm` because the base centres with translate, which the
        phone layout turns off.
      */}
      <DialogContent
        showCloseButton={false}
        className={cn(
          "flex flex-col gap-0 overflow-hidden p-0",
          "top-0 left-0 h-dvh max-h-dvh w-screen max-w-none translate-x-0 translate-y-0 rounded-none",
          "sm:top-1/2 sm:left-1/2 sm:h-auto sm:max-h-[88vh] sm:w-full sm:max-w-3xl sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl"
        )}
      >
        {externalId && (
          <TitleBody
            key={externalId}
            source={source}
            displayName={displayName}
            externalId={externalId}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function TitleBody({
  source,
  displayName,
  externalId,
}: {
  source: string;
  displayName: string;
  externalId: string;
}) {
  const [view, setView] = useState("episodes");
  const query = useLibraryTitle(source, externalId);
  // The list is already cached, so the header can be drawn before the
  // comparison answers.
  const listed = useLibrary(source).data?.items.find(
    (item) => String(item.external_id) === String(externalId)
  );
  const detail = query.data;
  const movie = source === "radarr";
  const header = detail?.title;
  const name = header?.title ?? listed?.title ?? "Untitled";
  const year = header?.year ?? listed?.year;
  const facts = [
    header?.network,
    header?.status ? capitalise(header.status) : null,
    header ? (header.monitored ? "Monitored" : "Not monitored") : null,
  ].filter(Boolean);
  const folderHere = header?.local_folder;
  // Said only when it is a different name, not the same name made safe for a
  // file system ("A: B" is filed as "A - B").
  const folderDiffers =
    Boolean(folderHere) && bare(folderHere ?? "") !== bare(`${name}${year ?? ""}`);

  return (
    <>
      <header className="flex items-start gap-3 px-4 pt-4 sm:gap-4 sm:px-5 sm:pt-5">
        <TitlePoster
          src={header?.poster ?? listed?.poster}
          movie={movie}
          className="w-12 sm:w-14"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <DialogTitle className="font-display text-lg leading-tight font-semibold text-balance text-foreground sm:text-xl">
            {name}
            {year ? <span className="ml-2 font-normal text-muted-foreground">{year}</span> : null}
          </DialogTitle>
          <DialogDescription className="text-[13px] text-muted-foreground">
            {facts.length ? facts.join(" · ") : `${displayName} title`}
          </DialogDescription>
          {folderDiffers && (
            <p className="text-[12px] break-all text-muted-foreground">
              Folder here: <span className="font-mono text-foreground-2">{folderHere}</span>
            </p>
          )}
        </div>
        <DialogClose
          render={(props) => (
            <button
              {...props}
              type="button"
              aria-label="Close"
              className="-mt-1 -mr-1 inline-flex size-11 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none sm:size-8"
            >
              <IconX className="size-4" />
            </button>
          )}
        />
      </header>

      <Tabs value={view} onValueChange={(next) => setView(String(next))} className="min-h-0 flex-1">
        <PageTabsList
          className="px-4 sm:px-5"
          items={[
            { value: "episodes", label: movie ? "File" : "Episodes", icon: IconListDetails },
            { value: "history", label: "History", icon: IconHistory },
          ]}
        />
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-2 pb-5 sm:px-5">
          <TabsContent value="episodes" className="space-y-5">
            {query.isLoading ? (
              <Loading displayName={displayName} />
            ) : query.isError ? (
              <Problem
                text={`Could not compare this with ${displayName}: ${libraryError(query.error, "the server did not answer")}.`}
                onRetry={() => query.refetch()}
              />
            ) : detail && !detail.live ? (
              <Problem
                text={`${displayName} did not answer${detail.message ? ` (${detail.message})` : ""}, so this cannot be checked right now.`}
                onRetry={() => query.refetch()}
              />
            ) : detail ? (
              <>
                <Status
                  detail={detail}
                  source={source}
                  displayName={displayName}
                  externalId={externalId}
                  checking={query.isFetching}
                  onCheck={() => query.refetch()}
                />
                {detail.movie ? (
                  <FilmFiles detail={detail} displayName={displayName} />
                ) : (
                  <Seasons seasons={detail.seasons ?? []} displayName={displayName} />
                )}
              </>
            ) : null}
          </TabsContent>
          <TabsContent value="history">
            <TitleHistoryList
              source={source}
              displayName={displayName}
              externalId={externalId}
              detail={detail}
              active={view === "history"}
            />
          </TabsContent>
        </div>
      </Tabs>
    </>
  );
}

function Loading({ displayName }: { displayName: string }) {
  return (
    <div className="space-y-3" aria-busy>
      <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
        <IconLoader2 className="size-4 animate-spin" />
        Comparing every episode with {displayName}…
      </p>
      <Skeleton className="h-20 w-full rounded-xl" />
      <Skeleton className="h-48 w-full rounded-xl" />
    </div>
  );
}

function Problem({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card px-4 py-3.5">
      <IconAlertTriangle className="size-4 shrink-0 text-amber-400" />
      <p className="min-w-0 flex-1 text-[13.5px] text-foreground">{text}</p>
      <Button size="sm" variant="outline" onClick={onRetry} className={TAP_BUTTON}>
        <IconRefresh className="size-3.5" />
        Try again
      </Button>
    </div>
  );
}

// -- the status: one sentence, one action ----------------------------------------

type Fix = "download" | "replace";

interface Pending {
  fix: Fix;
  plans: ExplorePlan[];
}

/** The seasons that count, with the episodes needing a given fix. */
function needing(detail: TitleDetail, state: "missing_here" | "different" | "nested") {
  return (detail.seasons ?? [])
    .filter((season) => season.counts_towards_state)
    .map((season) => ({
      season,
      episodes: season.episodes.filter((episode) => episode.state === state),
    }))
    .filter((entry) => entry.episodes.length > 0);
}

function codesText(episodes: TitleEpisode[]) {
  const codes = episodes.map((episode) => episode.code);
  return codes.length <= 4
    ? codes.join(", ")
    : `${codes.slice(0, 3).join(", ")} and ${codes.length - 3} more`;
}

function Status({
  detail,
  source,
  displayName,
  externalId,
  checking,
  onCheck,
}: {
  detail: TitleDetail;
  source: string;
  displayName: string;
  externalId: string;
  checking: boolean;
  onCheck: () => void;
}) {
  const navigate = useNavigate();
  const explore = detail.actions?.explore ?? null;
  const plan = useExplorePlan();
  const execute = useExploreExecute(explore?.media_type ?? "tvshows");
  const sync = useSyncLibraryItem(source);
  const connect = useSSHAutoConnect();
  const [phase, setPhase] = useState<"connecting" | "checking" | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState<string | null>(null);
  // Copy the series / Copy the film asks first, as Get does: it copies whole
  // folders, so nothing starts from a single press.
  const [confirmCopy, setConfirmCopy] = useState(false);

  const missing = needing(detail, "missing_here");
  const different = needing(detail, "different");
  const missingEpisodes = missing.flatMap((entry) => entry.episodes);
  const differentEpisodes = different.flatMap((entry) => entry.episodes);
  const nestedEpisodes = needing(detail, "nested").flatMap((entry) => entry.episodes);
  const film = detail.movie ?? null;
  // Files here one folder too deep. Copying them again would not make them
  // visible, so Repair in Explore is the answer — and the lead action.
  const nestedFiles = detail.nested_files ?? 0;
  const busy = phase !== null || execute.isPending || sync.isPending;

  const planAll = async (fix: Fix) => {
    const groups = fix === "download" ? missing : different;
    const plans: ExplorePlan[] = [];
    for (const { season, episodes } of groups) {
      plans.push(
        await plan.mutateAsync({
          media_type: explore!.media_type,
          operation: fix,
          folder: explore!.series!,
          season: season.explore_season,
          codes: episodes.map((episode) => episode.code),
        })
      );
    }
    return plans;
  };

  /**
   * Ask Explore for the exact plan, one per season, before anything moves.
   *
   * Explore reads the remote server over the app's browse session, which a
   * server restart drops. Rather than send the reader to Settings to press
   * Connect, it connects with the saved credentials (what that button does)
   * and asks once more.
   */
  const prepare = async (fix: Fix) => {
    if (!explore?.series) return;
    setError(null);
    setStarted(null);
    setPhase("checking");
    try {
      try {
        setPending({ fix, plans: await planAll(fix) });
      } catch (err) {
        if (!noBrowseSession(err)) throw err;
        setPhase("connecting");
        const answer = (await connect.mutateAsync()) as { status?: string; message?: string };
        if (answer?.status !== "success") {
          setError(
            `Could not connect to the remote server (${answer?.message ?? "no answer"}). Check the connection in Settings, then try again.`
          );
          return;
        }
        setPhase("checking");
        setPending({ fix, plans: await planAll(fix) });
      }
    } catch (err) {
      setError(libraryError(err, "Explore could not read the remote server"));
    } finally {
      setPhase(null);
    }
  };

  const run = async () => {
    if (!pending) return;
    setError(null);
    try {
      for (const ready of pending.plans) {
        await execute.mutateAsync({ plan_id: ready.plan_id });
      }
      const what =
        pending.fix === "download" ? codesText(missingEpisodes) : codesText(differentEpisodes);
      const verb = pending.fix === "download" ? "Copying" : "Replacing";
      setStarted(`${verb} ${what}.`);
      setPending(null);
      toast.success(`${verb} ${what}.`, {
        action: { label: "Transfers", onClick: () => navigate({ to: "/transfers" }) },
      });
    } catch (err) {
      setError(libraryError(err, "The copy could not start"));
    }
  };

  const copyTitle = async () => {
    setError(null);
    try {
      const result = await sync.mutateAsync(externalId);
      const said = (result.runs ?? []).map((entry) => entry.message).filter(Boolean);
      if (result.success) {
        setConfirmCopy(false);
        setStarted(said[0] ?? "Copy started.");
        toast.success(said[0] ?? "Copy started.", {
          action: { label: "Transfers", onClick: () => navigate({ to: "/transfers" }) },
        });
      } else {
        setError(result.error || "There is nothing to copy any more.");
      }
    } catch (err) {
      setError(libraryError(err, "The copy could not start"));
    }
  };

  // -- the sentence ------------------------------------------------------------
  let tone: "warn" | "ok" | "muted" = "muted";
  const lines: string[] = [];
  let note: string | null = null;

  if (film) {
    if (film.state === "missing_here") {
      tone = "warn";
      lines.push(`This film is on ${displayName} but not here yet.`);
      note = fileText(film.service_file);
    } else if (film.state === "different") {
      tone = "warn";
      lines.push(
        `${displayName} has an upgrade for this film: a different file from the one here.`
      );
      note = `${displayName}: ${fileText(film.service_file)}. Here: ${fileText(film.local_file)}.`;
    } else if (film.state === "nested") {
      tone = "warn";
      lines.push(`This film is here, but inside a nested folder your media server cannot see.`);
      note = film.local_file
        ? `${nestedWhere(film.local_file.relative_path, true)}. Repair moves it into the film's folder and deletes the empty one.`
        : null;
    } else if (film.state === "in_sync" && nestedFiles > 0) {
      tone = "warn";
      lines.push(`The film here is the same file as on ${displayName}.`);
      lines.push(`A second copy is inside a nested folder your media server cannot see.`);
    } else if (film.state === "in_sync") {
      tone = "ok";
      lines.push(`The film here is the same file as on ${displayName}.`);
    } else if (film.state === "only_here") {
      lines.push(`${displayName} no longer has a file for this film. The copy here is kept.`);
    } else {
      lines.push(`${displayName} has no file for this film yet.`);
    }
  } else if (missingEpisodes.length || differentEpisodes.length) {
    tone = "warn";
    if (missingEpisodes.length === 1) {
      const only = missingEpisodes[0];
      lines.push(`${only.code} is on ${displayName} but not here yet.`);
      note = [only.title, fileText(only.service_file)].filter(Boolean).join(" · ");
    } else if (missingEpisodes.length > 1) {
      lines.push(
        `${missingEpisodes.length} episodes are on ${displayName} but not here yet: ${codesText(missingEpisodes)}.`
      );
    }
    if (differentEpisodes.length === 1) {
      lines.push(
        `${displayName} has an upgrade for ${differentEpisodes[0].code}: a different file from the one here.`
      );
    } else if (differentEpisodes.length > 1) {
      lines.push(
        `${displayName} has upgrades for ${differentEpisodes.length} episodes: ${codesText(differentEpisodes)}.`
      );
    }
    if (nestedFiles > 0) lines.push(nestedLine(nestedEpisodes, nestedFiles));
  } else if (nestedFiles > 0) {
    tone = "warn";
    lines.push(nestedLine(nestedEpisodes, nestedFiles));
    const only = nestedEpisodes.length === 1 ? nestedEpisodes[0] : null;
    note = only?.local_file
      ? `${nestedWhere(only.local_file.relative_path)}. Repair moves it into the season folder and deletes the empty one.`
      : "Repair moves each one into its season folder and deletes the empty folders.";
  } else if (detail.state === "in_sync" || detail.state === "kept_here") {
    tone = "ok";
    lines.push(`Everything ${displayName} has for this series is here.`);
  } else if (detail.state === "never") {
    lines.push(`Nothing of this series is here yet.`);
  } else if (detail.state === "no_files") {
    lines.push(`${displayName} has no files for this series yet.`);
  } else if (detail.state === "orphan") {
    lines.push(`${displayName} no longer lists this series. The files here are kept.`);
  } else if (detail.summary) {
    lines.push(detail.summary);
  }

  const Icon =
    tone === "warn" ? IconAlertTriangle : tone === "ok" ? IconCircleCheck : IconInfoCircle;
  const canDownload = !film && missingEpisodes.length > 0 && Boolean(explore?.series);
  const canReplace = !film && differentEpisodes.length > 0 && Boolean(explore?.series);
  const canCopyTitle =
    detail.actions?.sync.offered === true && (detail.state === "never" || Boolean(film));
  /**
   * Which one action leads, filled; the rest are outlined. A stranded file
   * comes first — nothing else makes it visible — then what this pop-up can
   * do itself, and Explore when it can do nothing.
   */
  const lead: "repair" | "get" | "replace" | "copy" | "explore" =
    nestedFiles > 0
      ? "repair"
      : canDownload
        ? "get"
        : canReplace
          ? "replace"
          : canCopyTitle
            ? "copy"
            : "explore";
  const exploreLink = <ExploreButton explore={explore} repair={false} lead={lead === "explore"} />;

  return (
    <section
      aria-label="Sync status"
      className={cn(
        "rounded-xl border bg-card px-4 py-4",
        tone === "warn" ? "border-amber-500/35" : "border-border"
      )}
    >
      <div className="flex items-start gap-3">
        <Icon
          className={cn(
            "mt-0.5 size-5 shrink-0",
            tone === "warn"
              ? "text-amber-400"
              : tone === "ok"
                ? "text-emerald-400"
                : "text-muted-foreground"
          )}
        />
        <div className="min-w-0 flex-1 space-y-1">
          {lines.map((line) => (
            <p
              key={line}
              className="text-[15px] leading-snug font-medium text-pretty text-foreground"
            >
              {line}
            </p>
          ))}
          {note && <p className="text-[13px] text-muted-foreground">{note}</p>}
          <p className="flex flex-wrap items-center gap-x-1.5 pt-1 text-[12px] text-muted-foreground">
            <span title={stampText(detail.last_synced_at)}>
              {detail.last_synced_at
                ? `Last synced ${sinceText(detail.last_synced_at)}.`
                : "No finished sync on record."}
            </span>
            <span title={stampText(detail.computed_at)}>
              Checked {sinceText(detail.computed_at)}.
            </span>
            <button
              type="button"
              onClick={onCheck}
              disabled={checking}
              className={cn(
                "inline-flex items-center gap-1 rounded px-1 text-muted-foreground underline-offset-4 hover:text-foreground hover:underline disabled:opacity-60",
                TAP
              )}
            >
              <IconRefresh className={cn("size-3", checking && "animate-spin")} />
              Check again
            </button>
          </p>
        </div>
      </div>

      {(canDownload ||
        canReplace ||
        canCopyTitle ||
        nestedFiles > 0 ||
        (tone === "warn" && explore?.series)) && (
        <div className="mt-4 border-t border-border/70 pt-4 sm:pl-8">
          {pending ? (
            <Confirm
              pending={pending}
              running={execute.isPending}
              onRun={run}
              onCancel={() => setPending(null)}
              explore={explore}
            />
          ) : confirmCopy ? (
            <CopyConfirm
              detail={detail}
              running={sync.isPending}
              onRun={copyTitle}
              onCancel={() => {
                setConfirmCopy(false);
                setError(null);
              }}
            />
          ) : started ? (
            <p className="flex flex-wrap items-center gap-x-2 text-[13px] text-foreground">
              <IconCircleCheck className="size-4 text-emerald-400" />
              {started}
              <Link
                to="/transfers"
                className={cn(
                  "inline-flex items-center text-brand-hover underline-offset-4 hover:underline",
                  TAP
                )}
              >
                Follow it on Transfers
              </Link>
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              {nestedFiles > 0 && <ExploreButton explore={explore} repair lead />}
              {canDownload && (
                <Button
                  onClick={() => prepare("download")}
                  disabled={busy}
                  variant={lead === "get" ? "default" : "outline"}
                  className={TAP_BUTTON}
                >
                  {phase ? (
                    <IconLoader2 className="size-4 animate-spin" />
                  ) : (
                    <IconCloudDownload className="size-4" />
                  )}
                  {missingEpisodes.length === 1
                    ? `Get ${missingEpisodes[0].code}`
                    : `Get ${missingEpisodes.length} episodes`}
                </Button>
              )}
              {canReplace && (
                <Button
                  className={TAP_BUTTON}
                  variant={lead === "replace" ? "default" : "outline"}
                  onClick={() => prepare("replace")}
                  disabled={busy}
                >
                  <IconArrowsDiff className="size-4" />
                  {differentEpisodes.length === 1
                    ? `Replace ${differentEpisodes[0].code}`
                    : `Replace ${differentEpisodes.length} episodes`}
                </Button>
              )}
              {canCopyTitle && (
                <Button
                  onClick={() => {
                    setError(null);
                    setConfirmCopy(true);
                  }}
                  disabled={busy}
                  variant={lead === "copy" ? "default" : "outline"}
                  className={TAP_BUTTON}
                >
                  <IconCloudDownload className="size-4" />
                  {film ? "Copy the film" : "Copy the series"}
                </Button>
              )}
              {phase ? (
                <span className="text-[13px] text-muted-foreground" aria-live="polite">
                  {phase === "connecting"
                    ? "Connecting to the remote server…"
                    : "Checking what to copy…"}
                </span>
              ) : nestedFiles > 0 ? null : (
                exploreLink
              )}
            </div>
          )}
          {error && (
            <p role="alert" className="mt-3 text-[13px] text-rose-300">
              {error}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/** What is about to move, in one sentence, with the button that moves it. */
function Confirm({
  pending,
  running,
  onRun,
  onCancel,
  explore,
}: {
  pending: Pending;
  running: boolean;
  onRun: () => void;
  onCancel: () => void;
  explore: ExploreTarget | null;
}) {
  const fetch = pending.plans.reduce((sum, plan) => sum + plan.counts.fetch, 0);
  const replace = pending.plans.reduce((sum, plan) => sum + plan.counts.supersede, 0);
  const remove = pending.plans.reduce((sum, plan) => sum + plan.counts.remove, 0);
  const bytes = pending.plans.reduce((sum, plan) => sum + plan.counts.incoming_bytes, 0);
  const failed = pending.plans.flatMap((plan) => plan.checks).find((check) => !check.passed);
  const blocked = pending.plans.some((plan) => !plan.safe || plan.requires_override);
  const folders = [...new Set(pending.plans.map((plan) => plan.season_label).filter(Boolean))];
  const nested = pending.plans.reduce((sum, plan) => sum + (plan.nested_files ?? 0), 0);
  const where = folders.length ? ` into ${folders.join(", ")}` : "";

  let sentence: string;
  if (blocked) {
    sentence = `Explore's checks stopped this${failed ? `: ${failed.detail || failed.label}` : ""}. Review it in Explore.`;
  } else if (fetch === 0 && nested > 0 && pending.fix === "download") {
    // Here already, one folder too deep: Sonarr's view and this one both read
    // it as absent, and copying it again would not make it visible.
    sentence = `Already here, but inside a nested folder your media server cannot see. Open it in Explore and press Repair to move it into place.`;
  } else if (fetch === 0) {
    sentence =
      "Explore found nothing to copy: the remote server's folder may hold it under another name. Compare the folders in Explore.";
  } else if (pending.fix === "download") {
    sentence = `Copy ${plural(fetch, "file")} (${formatSize(bytes)}) from the remote server${where}. Nothing here is replaced or removed.`;
  } else {
    sentence = `Replace ${plural(replace || fetch, "file")} here with ${replace + fetch === 1 ? "the one" : "the ones"} on the remote server (${formatSize(bytes)}). The files here now are kept in Backups first.`;
  }
  const runnable = !blocked && fetch + replace > 0 && remove === 0;

  return (
    <div className="space-y-3">
      <p className="text-[13.5px] text-pretty text-foreground">{sentence}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {runnable ? (
          <Button onClick={onRun} disabled={running} className={TAP_BUTTON}>
            {running ? <IconLoader2 className="size-4 animate-spin" /> : null}
            {pending.fix === "download" ? "Copy now" : "Replace now"}
          </Button>
        ) : (
          // Nothing to run here: Explore is the way on, so it leads.
          <ExploreButton explore={explore} repair={nested > 0 && pending.fix === "download"} lead />
        )}
        <Button variant="outline" onClick={onCancel} disabled={running} className={TAP_BUTTON}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/**
 * What Copy the series / Copy the film is about to do, before it does it.
 *
 * Offered only when nothing of the title is here, so it can only add. The
 * numbers are the service's own: its files in the seasons the copy fetches
 * (Specials are not fetched), or the film's file. The sync behind it copies
 * whole folders, artwork and subtitles too, so the size is "about".
 */
function CopyConfirm({
  detail,
  running,
  onRun,
  onCancel,
}: {
  detail: TitleDetail;
  running: boolean;
  onRun: () => void;
  onCancel: () => void;
}) {
  const film = detail.movie ?? null;
  let what: string;
  if (film) {
    const file = film.service_file;
    const facts = [file?.quality, file?.size ? formatSize(file.size) : null].filter(Boolean);
    what = `Copy the film${facts.length ? ` (${facts.join(", ")})` : ""}`;
  } else {
    const wanted = new Set(detail.actions?.sync.seasons ?? []);
    const seasons = (detail.seasons ?? []).filter((season) => wanted.has(season.season_number));
    // One double-episode file sits on two episode rows; count it once.
    const unique = new Map<string, number>();
    for (const season of seasons) {
      for (const episode of season.episodes) {
        const file = episode.service_file;
        if (file) unique.set(file.relative_path || episode.code, file.size ?? 0);
      }
    }
    const files = [...unique.values()];
    const bytes = files.reduce((sum, size) => sum + size, 0);
    const numbers = seasons.map((season) => season.season_number);
    const which =
      numbers.length === 1
        ? `season ${numbers[0]}`
        : numbers.length > 1
          ? `seasons ${numbers.slice(0, -1).join(", ")} and ${numbers[numbers.length - 1]}`
          : "the series";
    what = `Copy ${which}: ${plural(files.length, "file")}${bytes ? `, about ${formatSize(bytes)}` : ""},`;
  }
  return (
    <div className="space-y-3">
      <p className="text-[13.5px] text-pretty text-foreground">
        {what} from the remote server. Nothing of it is here yet, so nothing here is replaced.
      </p>
      <p className="text-[12.5px] text-muted-foreground">
        It runs as a sync: a dry run checks it first, and it shows on Transfers.
      </p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button onClick={onRun} disabled={running} className={TAP_BUTTON}>
          {running ? (
            <IconLoader2 className="size-4 animate-spin" />
          ) : (
            <IconCloudDownload className="size-4" />
          )}
          Copy now
        </Button>
        <Button variant="outline" onClick={onCancel} disabled={running} className={TAP_BUTTON}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

type ExploreTarget = NonNullable<NonNullable<TitleDetail["actions"]>["explore"]>;

/**
 * Explore, as a button rather than a quiet link: it is where a copy is
 * planned file by file and where a stranded file is repaired. Filled when it
 * is the thing to do next; otherwise outlined in brand, so it still reads as
 * an action beside Get or Replace.
 */
function ExploreButton({
  explore,
  repair,
  lead,
}: {
  explore: ExploreTarget | null;
  repair: boolean;
  lead: boolean;
}) {
  if (!explore?.series) return null;
  const season = repair ? (explore.nested_season ?? explore.season) : explore.season;
  const Glyph = repair ? IconTool : IconFolderSearch;
  return (
    <Link
      to="/media/$type"
      params={{ type: explore.media_type }}
      search={{ series: explore.series, season: season ?? undefined }}
      className={cn(
        buttonVariants({ variant: lead ? "default" : "outline" }),
        TAP_BUTTON,
        !lead && "border-brand/45 text-brand-foreground hover:bg-brand/12 dark:border-brand/45"
      )}
    >
      <Glyph className="size-4" />
      {repair ? "Repair in Explore" : "Open in Explore"}
    </Link>
  );
}

/**
 * Where a nested file is, in words. The path itself is the file's name twice
 * (`Season 01/ep.mkv/ep.mkv`, 200+ characters), which on a phone fills the
 * screen and says less than "a folder named after the file".
 */
function nestedWhere(path: string, film = false): string {
  const parts = path.split("/").filter(Boolean);
  const name = parts[parts.length - 1] ?? "";
  // A film's path starts at its own folder's child; an episode's at the season.
  const home = film ? null : (parts[0] ?? null);
  const between = parts.slice(film ? 0 : 1, -1);
  const extra =
    between.length === 1 && between[0] === name
      ? "an extra folder named after the file"
      : `an extra folder (${between.join("/")})`;
  return home ? `Inside ${extra}, in ${home}` : `Inside ${extra}`;
}

/** "S01E38 is here, but inside a nested folder …" for the pop-up's lead sentence. */
function nestedLine(episodes: TitleEpisode[], files: number): string {
  const where = "inside a nested folder your media server cannot see";
  if (episodes.length === 1 && files === 1) return `${episodes[0].code} is here, but ${where}.`;
  if (episodes.length > 0 && episodes.length === files) {
    return `${episodes.length} episodes are here, but ${where}: ${codesText(episodes)}.`;
  }
  return `${plural(files, "file")} here ${files === 1 ? "is" : "are"} ${where}.`;
}

// -- the evidence, season by season ---------------------------------------------

/** Long seasons with something to fix open on just those episodes. */
const LONG_SEASON = 12;

function Seasons({ seasons, displayName }: { seasons: TitleSeason[]; displayName: string }) {
  const counted = seasons.filter((season) => season.counts_towards_state);
  const specials = seasons.filter((season) => !season.counts_towards_state);
  const ordered = [...counted, ...specials];
  const needs = (season: TitleSeason) => season.counts.missing_here + season.counts.different > 0;
  const startOpen = new Set(
    counted.some(needs)
      ? counted.filter(needs).map((season) => season.season_number)
      : counted.length === 1
        ? [counted[0].season_number]
        : []
  );

  if (!ordered.length) {
    return (
      <p className="rounded-xl border border-border bg-card px-4 py-6 text-center text-[13px] text-muted-foreground">
        {displayName} lists no episodes for this series, and none are here.
      </p>
    );
  }

  return (
    <section
      aria-label="Episodes by season"
      className="divide-y divide-border/70 overflow-hidden rounded-xl border border-border bg-card"
    >
      {ordered.map((season) => (
        <SeasonBlock
          key={season.season_number}
          season={season}
          displayName={displayName}
          defaultOpen={startOpen.has(season.season_number)}
        />
      ))}
    </section>
  );
}

function SeasonBlock({
  season,
  displayName,
  defaultOpen,
}: {
  season: TitleSeason;
  displayName: string;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [showAll, setShowAll] = useState(false);
  const [showUpcoming, setShowUpcoming] = useState(false);
  const counts = season.counts;
  const known = season.episodes.length - counts.not_downloaded;
  const here = known - counts.missing_here;
  const problems = season.episodes.filter(
    (episode) =>
      episode.state === "missing_here" ||
      episode.state === "different" ||
      episode.state === "nested"
  );
  // Episodes still to air are a fact about the schedule, not the files; a
  // season in progress would otherwise end in a column of "TBA, not
  // downloaded". They fold into one line.
  const upcoming = season.episodes.filter(isUpcoming);
  const aired = season.episodes.filter((episode) => !isUpcoming(episode));
  const trimmed = problems.length > 0 && aired.length > LONG_SEASON && !showAll;
  const rows = trimmed ? problems : aired;
  const label = season.specials ? "Specials" : `Season ${season.season_number}`;
  const panelId = `season-${season.season_number}`;

  const summary: Array<{ text: string; warn?: boolean; upgrade?: boolean }> = [];
  if (counts.missing_here) summary.push({ text: `${counts.missing_here} not here`, warn: true });
  // Every file of the season in a nested folder, a second copy included.
  const nested = season.nested_here?.length ?? 0;
  if (nested > 0) summary.push({ text: `${nested} nested`, warn: true });
  if (counts.different)
    summary.push({
      text: `${counts.different} upgrade${counts.different === 1 ? "" : "s"}`,
      upgrade: true,
    });
  if (known > 0) summary.push({ text: `${here} of ${known} here` });
  const neither = counts.not_downloaded - upcoming.length;
  if (neither > 0 && known === 0) summary.push({ text: `${neither} not downloaded` });
  if (upcoming.length > 0 && known === 0) summary.push({ text: `${upcoming.length} to air` });

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/30 focus-visible:bg-muted/30 focus-visible:outline-none"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-semibold text-foreground">{label}</span>
          {season.last_synced_at && (
            <span
              className="block text-[12px] text-muted-foreground"
              title={stampText(season.last_synced_at)}
            >
              Synced {sinceText(season.last_synced_at)}
            </span>
          )}
        </span>
        <span className="flex flex-wrap justify-end gap-x-3 text-[12.5px]">
          {summary.map((part) => (
            <span
              key={part.text}
              className={
                part.upgrade
                  ? "font-medium text-sky-300"
                  : part.warn
                    ? "font-medium text-amber-400"
                    : "text-muted-foreground"
              }
            >
              {part.text}
            </span>
          ))}
        </span>
        <IconChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-180"
          )}
        />
      </button>

      {open && (
        <div id={panelId} className="border-t border-border/50 px-4">
          <ul className="divide-y divide-border/50">
            {rows.map((episode) => (
              <EpisodeRow key={episode.code} episode={episode} displayName={displayName} />
            ))}
          </ul>
          {trimmed && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className={cn(
                "mb-3 inline-flex items-center text-[13px] text-muted-foreground underline-offset-4 hover:text-foreground hover:underline",
                TAP
              )}
            >
              Show all {aired.length} episodes
            </button>
          )}
          {upcoming.length > 0 && (
            <div className="border-t border-border/50 py-2.5">
              <button
                type="button"
                onClick={() => setShowUpcoming((value) => !value)}
                aria-expanded={showUpcoming}
                className={cn(
                  "inline-flex items-center text-[13px] text-muted-foreground underline-offset-4 hover:text-foreground hover:underline",
                  TAP
                )}
              >
                {upcoming.length === 1
                  ? `1 episode still to air, on ${dayText(upcoming[0].air_date)}`
                  : `${upcoming.length} episodes still to air, the next on ${dayText(upcoming[0].air_date)}`}
              </button>
              {showUpcoming && (
                <ul className="mt-1 divide-y divide-border/50">
                  {upcoming.map((episode) => (
                    <EpisodeRow key={episode.code} episode={episode} displayName={displayName} />
                  ))}
                </ul>
              )}
            </div>
          )}
          {season.unidentified_here.length > 0 && (
            <div className="space-y-1 border-t border-border/50 py-3">
              <p className="text-[12.5px] text-muted-foreground">
                {season.unidentified_here.length === 1
                  ? "1 file here has no episode number in its name:"
                  : `${season.unidentified_here.length} files here have no episode number in their names:`}
              </p>
              <ul className="space-y-0.5">
                {season.unidentified_here.map((file) => (
                  <li
                    key={file.relative_path}
                    className="font-mono text-[11.5px] break-all text-foreground-2"
                  >
                    {file.name}{" "}
                    <span className="text-muted-foreground">{formatSize(file.size)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EpisodeRow({ episode, displayName }: { episode: TitleEpisode; displayName: string }) {
  const number =
    episode.episode_number != null
      ? `E${String(episode.episode_number).padStart(2, "0")}`
      : episode.code;
  const theirs = episode.service_file;
  const ours = episode.local_file;
  let facts = "";
  if (episode.state === "missing_here") facts = `On ${displayName}: ${fileText(theirs)}`;
  else if (episode.state === "different")
    facts = `${displayName}: ${fileText(theirs)}. Here: ${fileText(ours)}`;
  else if (episode.state === "in_sync") facts = fileText(theirs ?? ours);
  else if (episode.state === "nested" && ours) facts = nestedWhere(ours.relative_path);
  else if (episode.state === "only_here" && ours?.size) facts = `${formatSize(ours.size)} here`;
  const air = airText(episode.air_date);
  const meta = [air, facts].filter(Boolean).join(" · ");

  return (
    <li className="flex items-start gap-3 py-2.5">
      <span className="w-9 shrink-0 pt-px font-mono text-[12px] text-muted-foreground tabular-nums">
        {number}
      </span>
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            "truncate text-[13.5px]",
            episode.title ? "text-foreground" : "text-muted-foreground"
          )}
          title={episode.title ?? undefined}
        >
          {episode.title ?? `Not listed on ${displayName}`}
        </p>
        {meta && <p className="mt-0.5 text-[12px] text-muted-foreground">{meta}</p>}
        {ours && ours.covers.length > 1 && (
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            One file here holds {ours.covers.join(" and ")}.
          </p>
        )}
        {episode.local_duplicates > 0 && (
          <p className="mt-0.5 text-[12px] text-amber-300/90">
            {episode.local_duplicates === 1
              ? "There is a second copy of this episode here."
              : `There are ${episode.local_duplicates + 1} copies of this episode here.`}
          </p>
        )}
      </div>
      <EpisodeMark state={episode.state} />
    </li>
  );
}

function FilmFiles({ detail, displayName }: { detail: TitleDetail; displayName: string }) {
  const film = detail.movie;
  if (!film) return null;
  // The same file on both sides is one fact, said once.
  const rows: Array<{ label: string; file: ServiceFile | LocalFile | null }> =
    film.state === "in_sync" && film.service_file
      ? [{ label: `On ${displayName} and here`, file: film.service_file }]
      : [
          { label: `On ${displayName}`, file: film.service_file },
          { label: "Here", file: film.local_file },
        ];
  return (
    <section
      aria-label="The film's files"
      className="divide-y divide-border/70 rounded-xl border border-border bg-card"
    >
      {rows.map((row) => (
        <div key={row.label} className="space-y-0.5 px-4 py-3">
          <p className="text-[13px] font-medium text-foreground">{row.label}</p>
          {row.file ? (
            <p className="text-[12.5px] text-muted-foreground">
              <span className="font-mono break-all text-foreground-2">
                {row.file.name || "file"}
              </span>
              <span className="ml-2">{fileText(row.file)}</span>
            </p>
          ) : (
            <p className="text-[12.5px] text-muted-foreground">No file</p>
          )}
        </div>
      ))}
      {film.other_files_here.length > 0 && (
        <p className="px-4 py-3 text-[12.5px] text-muted-foreground">
          Also here: {film.other_files_here.map((file) => file.name).join(", ")}
        </p>
      )}
    </section>
  );
}

// -- what happened to the title -------------------------------------------------

interface Mark {
  label: string;
  tone: "muted" | "warn" | "crit" | "brand";
  hint: string;
}

const MARKS: Record<string, Mark> = {
  done: { label: "Done", tone: "muted", hint: "This got done." },
  not_done: {
    label: "Not done",
    tone: "warn",
    hint: "This did not happen. The detail says why.",
  },
  failed: { label: "Failed", tone: "crit", hint: "This was tried and failed." },
  in_progress: { label: "In progress", tone: "brand", hint: "This is still going." },
};

const MARK_CLASS: Record<Mark["tone"], string> = {
  muted: "font-medium text-muted-foreground",
  warn: "font-semibold text-amber-400",
  crit: "font-semibold text-rose-400",
  brand: "font-medium text-brand-hover",
};

/**
 * Each entry's mark, said from what is true now rather than only from what
 * happened then.
 *
 * An import is marked from the episode comparison, the one exact answer to "is
 * it here now"; only an episode's newest import is marked, since an older one
 * was replaced by it. A failure that no longer matters (a failed download of
 * an episode that is here anyway, a sync of a folder that a later sync
 * finished) reads "Here anyway" or "Done later" and leaves the Not done list,
 * which is there for what is still undone.
 */
function marksFor(entries: TitleHistoryEntry[], detail: TitleDetail | undefined) {
  const states = new Map<string, TitleEpisode["state"]>();
  for (const season of detail?.seasons ?? []) {
    for (const episode of season.episodes) states.set(episode.code, episode.state);
  }
  const film = detail?.movie?.state;
  const stateOf = (code: string) => (code === "film" ? film : states.get(code));
  const isHere = (state: TitleEpisode["state"] | undefined) =>
    state === "in_sync" || state === "only_here" || state === "different";
  const seen = new Set<string>();
  // Entries arrive newest first, so a season is in here once a later sync of
  // it finished.
  const syncedLater = new Set<string>();

  return entries.map((entry): Mark | null => {
    const codes = entry.episodes.length ? entry.episodes : ["film"];
    if (entry.side === "dragoncp") {
      const folder = entry.season ?? "*";
      if (entry.status === "done") {
        syncedLater.add(folder);
        return MARKS.done;
      }
      if (
        (entry.status === "failed" || entry.status === "not_done") &&
        (syncedLater.has(folder) || syncedLater.has("*"))
      ) {
        return {
          label: "Done later",
          tone: "muted",
          hint: "A later sync of the same folder finished.",
        };
      }
      return MARKS[entry.status] ?? null;
    }
    if (entry.kind === "failed") {
      if (codes.every((code) => isHere(stateOf(code)))) {
        return {
          label: "Here anyway",
          tone: "muted",
          hint: "This is on this disk, from another download.",
        };
      }
      return MARKS.failed;
    }
    if (entry.kind !== "imported") return MARKS[entry.status] ?? null;
    if (codes.every((code) => seen.has(code))) return null;
    codes.forEach((code) => seen.add(code));
    const now = codes.map(stateOf);
    if (now.some((state) => state === "missing_here")) {
      return {
        label: "Not here yet",
        tone: "warn",
        hint: "The service still has this file and this disk does not.",
      };
    }
    if (now.some((state) => state === "different")) {
      return {
        label: "Different here",
        tone: "warn",
        hint: "The file here is not the one the service imported.",
      };
    }
    if (now.length && now.every((state) => state === "in_sync" || state === "only_here")) {
      return { label: "Here", tone: "muted", hint: "This is on this disk." };
    }
    return null;
  });
}

function dayAndTime(iso: string | null) {
  if (!iso) return { day: "", time: "" };
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return { day: "", time: "" };
  const sameYear = moment.getFullYear() === new Date().getFullYear();
  return {
    day: moment.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      ...(sameYear ? {} : { year: "numeric" }),
    }),
    time: moment.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
  };
}

function TitleHistoryList({
  source,
  displayName,
  externalId,
  detail,
  active,
}: {
  source: string;
  displayName: string;
  externalId: string;
  /** The episode comparison, which decides whether an import's episode is here now. */
  detail: TitleDetail | undefined;
  /** Read only once the tab is opened. */
  active: boolean;
}) {
  const [only, setOnly] = useState<"all" | "not_done">("all");
  const query = useLibraryTitleHistory(source, externalId, active);
  const history = query.data;

  if (query.isLoading || (!history && active && query.isFetching)) {
    return (
      <div className="space-y-3 pt-2" aria-busy>
        <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <IconLoader2 className="size-4 animate-spin" />
          Reading what {displayName} and DragonCP recorded for this title…
        </p>
        {[0, 1, 2, 3].map((row) => (
          <Skeleton key={row} className="h-12 w-full" />
        ))}
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="pt-2">
        <Problem
          text={`Could not read this title's history: ${libraryError(query.error, "the server did not answer")}.`}
          onRetry={() => query.refetch()}
        />
      </div>
    );
  }
  if (!history) return null;

  const marks = marksFor(history.entries, detail);
  const rows = history.entries.map((entry, index) => ({ entry, mark: marks[index] }));
  const notDone = rows.filter(
    (row) => row.mark && (row.mark.tone === "warn" || row.mark.tone === "crit")
  );
  const shown = only === "not_done" ? notDone : rows;

  return (
    <div className="space-y-3 pt-2">
      {!history.live && (
        <p className="text-[12.5px] text-muted-foreground">
          {displayName} did not answer, so only what DragonCP did is listed.
        </p>
      )}
      {rows.length > 0 && (
        <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
          {(
            [
              { value: "all", label: "Everything", count: rows.length },
              { value: "not_done", label: "Not done", count: notDone.length },
            ] as const
          ).map((choice) => (
            <button
              key={choice.value}
              type="button"
              aria-pressed={only === choice.value}
              onClick={() => setOnly(choice.value)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold transition-colors",
                "h-11 sm:h-8",
                only === choice.value
                  ? "border-brand/35 bg-brand/15 text-brand-foreground"
                  : "border-transparent text-muted-foreground hover:bg-muted/60 hover:text-foreground"
              )}
            >
              {choice.label}
              <span className="font-mono text-[10.5px] tabular-nums opacity-70">
                {choice.count}
              </span>
            </button>
          ))}
        </div>
      )}

      {rows.length === 0 ? (
        <p className="rounded-xl border border-border bg-card px-4 py-6 text-center text-[13px] text-muted-foreground">
          Nothing is recorded for this title yet. {displayName}&apos;s imports and DragonCP&apos;s
          syncs of it will show here.
        </p>
      ) : shown.length === 0 ? (
        <p className="rounded-xl border border-border bg-card px-4 py-6 text-center text-[13px] text-muted-foreground">
          Everything recorded here got done.
        </p>
      ) : (
        <ul className="divide-y divide-border/60 rounded-xl border border-border bg-card px-4">
          {shown.map(({ entry, mark }, index) => {
            const when = dayAndTime(entry.at);
            return (
              <li
                key={`${entry.at}-${entry.title}-${index}`}
                className="flex items-start gap-3 py-3"
              >
                <span
                  className="w-16 shrink-0 pt-px text-[12px] leading-snug text-muted-foreground tabular-nums"
                  title={stampText(entry.at)}
                >
                  {when.day}
                  <span className="block text-[11px] opacity-80">{when.time}</span>
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] text-foreground">{entry.title}</p>
                  {entry.detail && (
                    <p className="mt-0.5 text-[12px] break-words text-muted-foreground">
                      {entry.detail}
                    </p>
                  )}
                  {entry.run_id && (
                    <Link
                      to="/transfers"
                      search={{ sync: entry.run_id }}
                      className={cn(
                        "inline-flex items-center text-[12px] text-brand-hover underline-offset-4 hover:underline",
                        TAP
                      )}
                    >
                      Open the sync
                    </Link>
                  )}
                </div>
                {mark && (
                  <span
                    title={mark.hint}
                    className={cn(
                      "inline-flex shrink-0 items-center gap-1 text-[12px] whitespace-nowrap",
                      MARK_CLASS[mark.tone]
                    )}
                  >
                    {mark.tone === "crit" ? (
                      <IconCircleX className="size-3.5" />
                    ) : mark.tone === "warn" ? (
                      <IconAlertTriangle className="size-3.5" />
                    ) : mark.tone === "brand" ? (
                      <IconLoader2 className="size-3.5" />
                    ) : (
                      <IconCircleCheck className="size-3.5" />
                    )}
                    {mark.label}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {history.total > history.entries.length && (
        <p className="text-[12px] text-muted-foreground">
          Showing the newest {history.entries.length} of {history.total}.
        </p>
      )}
    </div>
  );
}

/** "WEBDL-1080p, 1.6 GB", or just the size for a file here. */
function fileText(file: ServiceFile | LocalFile | null | undefined): string {
  if (!file) return "no file";
  const quality = "quality" in file ? file.quality : null;
  return [quality, formatSize(file.size)].filter(Boolean).join(", ");
}

/** Explore's answer when the app has no browse session to the remote server. */
function noBrowseSession(error: unknown) {
  const response = (error as { response?: { status?: number; data?: { message?: string } } })
    ?.response;
  return response?.status === 409 && /browse session/i.test(response.data?.message ?? "");
}

/** An episode nobody has yet because it has not aired. */
function isUpcoming(episode: TitleEpisode) {
  if (episode.state !== "not_downloaded" || !episode.air_date) return false;
  const moment = new Date(`${episode.air_date}T12:00:00`).getTime();
  return Number.isFinite(moment) && moment > Date.now();
}

/** "Oct 18, 2026", without the "airs" that `airText` adds to a future date. */
function dayText(date: string | null) {
  return airText(date).replace(/^airs /, "");
}

/** Letters and digits only, for comparing a title with its folder's name. */
function bare(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function plural(count: number, word: string) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function capitalise(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
