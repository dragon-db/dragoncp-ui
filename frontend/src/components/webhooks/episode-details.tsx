import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { StatusBadge } from "@/components/webhooks/webhook-bits";
import { DryRunSummary } from "@/components/dry-run/dry-run-report";
import {
  episodeEntries,
  episodeFileOf,
  fileBytes,
  formatSize,
  releaseTypeOf,
  timeAgo,
  type EpisodeEntry,
  type WebhookItem,
} from "@/lib/webhook-grouping";
import type { WebhookNotification } from "@/lib/api-types";
import {
  IconCheck,
  IconCode,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
  IconHistory,
} from "@tabler/icons-react";

export interface EpisodeActions {
  onSync: (notification: WebhookNotification) => void;
  onComplete: (notification: WebhookNotification) => void;
  onDryRun: (notification: WebhookNotification) => void;
  onJson: (notification: WebhookNotification) => void;
  onDelete: (notification: WebhookNotification) => void;
  /** Opens the stored dry-run result without re-running the validation. */
  onViewDryRun?: (notification: WebhookNotification) => void;
}

function Fact({ label, value, mono }: { label: string; value?: string; mono?: boolean }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </span>
      <span className={cn("text-xs break-words text-foreground", mono && "font-mono")}>
        {value}
      </span>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border bg-black/25 px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
      {children}
    </span>
  );
}

function PathBlock({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </span>
      <div className="rounded-md border border-border bg-background/60 px-2.5 py-1.5 font-mono text-[11px] break-all text-foreground/80">
        {value}
      </div>
    </div>
  );
}

/**
 * Everything known about one imported file: the release that delivered it, the
 * media facts, where it landed, and the actions available on it.
 */
export function EpisodeDetailPanel({
  notification,
  entry,
  seasonPath,
  actions,
}: {
  notification: WebhookNotification;
  entry?: EpisodeEntry;
  seasonPath?: string;
  actions: EpisodeActions;
}) {
  const file = episodeFileOf(notification);
  const releaseType = releaseTypeOf(notification);
  const media = file?.mediaInfo;

  return (
    <div className="flex flex-col gap-4">
      {/* Release */}
      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Release
          </span>
          <Chip>{formatSize(fileBytes(notification))} file</Chip>
          {notification.release_size ? (
            <Chip>{formatSize(notification.release_size)} grab</Chip>
          ) : null}
          {file?.quality && <Chip>{file.quality}</Chip>}
          {file?.releaseGroup && <Chip>{file.releaseGroup}</Chip>}
          {notification.release_indexer && <Chip>{notification.release_indexer}</Chip>}
          {releaseType !== "unknown" && (
            <Chip>{releaseType === "seasonPack" ? "season pack" : "single episode"}</Chip>
          )}
        </div>
        {notification.release_title && (
          <div className="rounded-md border border-border bg-background/60 px-2.5 py-1.5 font-mono text-[11px] break-all text-foreground/80">
            {notification.release_title}
          </div>
        )}
      </section>

      {/* Facts */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {entry && <Fact label="Episode" value={entry.label} mono />}
        {entry?.airDate && <Fact label="Air date" value={entry.airDate} mono />}
        <Fact label="Imported" value={timeAgo(notification.created_at)} />
        {media?.width && media?.height ? (
          <Fact label="Resolution" value={`${media.width}×${media.height}`} mono />
        ) : null}
        {media?.videoCodec ? <Fact label="Video" value={media.videoCodec} mono /> : null}
        {media?.audioCodec ? (
          <Fact
            label="Audio"
            value={`${media.audioCodec}${media.audioChannels ? ` ${media.audioChannels}ch` : ""}`}
            mono
          />
        ) : null}
        {media?.audioLanguages?.length ? (
          <Fact label="Languages" value={media.audioLanguages.join(", ")} mono />
        ) : null}
        {media?.subtitles?.length ? (
          <Fact label="Subtitles" value={media.subtitles.join(", ")} mono />
        ) : null}
      </section>

      {/* Paths */}
      <section className="grid gap-2 sm:grid-cols-2">
        <PathBlock label="Season path" value={seasonPath} />
        <PathBlock label="File path" value={file?.path || file?.relativePath} />
      </section>

      {/* Last dry-run, when one was already stored for this notification */}
      {notification.dry_run_result ? (
        <section className="flex flex-col gap-1.5">
          <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
            Last validation
          </span>
          <DryRunSummary
            payload={notification.dry_run_result}
            performedAt={notification.dry_run_performed_at}
            onOpen={actions.onViewDryRun ? () => actions.onViewDryRun?.(notification) : undefined}
          />
        </section>
      ) : null}

      {/* Superseded grabs */}
      {entry && entry.history.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
            Replaced by upgrade ({entry.history.length})
          </span>
          {entry.history.map((old) => (
            <div
              key={old.notification_id}
              className="flex items-center gap-2 font-mono text-[10.5px] text-muted-foreground"
            >
              <span className="shrink-0">{formatSize(fileBytes(old))}</span>
              <span className="truncate">{old.release_title}</span>
              <span className="flex-1" />
              <span className="shrink-0">{timeAgo(old.created_at)}</span>
            </div>
          ))}
        </section>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {(notification.status === "pending" || notification.status === "failed") && (
          <Button size="sm" variant="outline" onClick={() => actions.onSync(notification)}>
            <IconPlayerPlay className="mr-1.5 size-3.5" />
            {notification.status === "failed" ? "Retry" : "Sync"}
          </Button>
        )}
        {notification.status !== "completed" && (
          <Button size="sm" variant="outline" onClick={() => actions.onComplete(notification)}>
            <IconCheck className="mr-1.5 size-3.5" />
            Mark complete
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => actions.onDryRun(notification)}>
          <IconRefresh className="mr-1.5 size-3.5" />
          Dry-run
        </Button>
        <Button size="sm" variant="outline" onClick={() => actions.onJson(notification)}>
          <IconCode className="mr-1.5 size-3.5" />
          View JSON
        </Button>
        <span className="flex-1" />
        {notification.status !== "syncing" && (
          <Button
            size="sm"
            variant="outline"
            className="text-muted-foreground hover:text-rose-400"
            onClick={() => actions.onDelete(notification)}
          >
            <IconTrash className="mr-1.5 size-3.5" />
            Delete
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * The episodes of one season: a row per episode showing the file currently on
 * disk, expanding in place to that file's full detail.
 */
export function EpisodeList({ item, actions }: { item: WebhookItem; actions: EpisodeActions }) {
  const entries = episodeEntries(item.notifications, item.seasonNumber);
  const seasonPath = item.notifications.find((n) => n.season_path)?.season_path;

  if (!entries.length) {
    return (
      <p className="py-3 text-xs text-muted-foreground">
        No episode detail recorded for this arrival.
      </p>
    );
  }

  return (
    <Accordion className="flex flex-col gap-1.5">
      {entries.map((entry) => {
        const file = episodeFileOf(entry.current);
        const isPack = releaseTypeOf(entry.current) === "seasonPack";
        return (
          <AccordionItem
            key={entry.episodeNumber}
            value={String(entry.episodeNumber)}
            className="overflow-hidden rounded-lg border border-border bg-card/60"
          >
            {/* Phones stack the episode above its facts; from sm up it is one row. */}
            <AccordionTrigger className="items-start gap-3 px-3 py-2 no-underline hover:bg-muted/40 hover:no-underline sm:items-center">
              <span className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
                <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="shrink-0 font-mono text-xs font-semibold text-brand-hover">
                    {entry.label}
                  </span>
                  <span className="min-w-0 text-[13px] break-words text-foreground sm:truncate">
                    {entry.title || "Episode"}
                  </span>
                  {isPack && (
                    <span className="shrink-0 rounded border border-brand/30 bg-brand/10 px-1.5 py-px text-[9px] font-semibold tracking-wide text-brand-hover uppercase">
                      Pack
                    </span>
                  )}
                  {entry.history.length > 0 && (
                    <span
                      className="inline-flex shrink-0 items-center gap-1 font-mono text-[10px] text-muted-foreground"
                      title={`${entry.history.length + 1} grabs for this episode`}
                    >
                      <IconHistory className="size-3" />
                      {entry.history.length + 1}
                    </span>
                  )}
                </span>
                <span className="flex shrink-0 flex-wrap items-center gap-2">
                  {file?.quality && (
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {file.quality}
                    </span>
                  )}
                  <span className="font-mono text-[11px] text-foreground/80">
                    {formatSize(fileBytes(entry.current))}
                  </span>
                  <StatusBadge status={entry.current.status} size="sm" />
                </span>
              </span>
            </AccordionTrigger>
            <AccordionContent className="border-t border-border bg-black/20 px-3 py-3">
              <EpisodeDetailPanel
                notification={entry.current}
                entry={entry}
                seasonPath={seasonPath}
                actions={actions}
              />
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}
