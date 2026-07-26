import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/webhooks/webhook-bits";
import {
  episodeEntries,
  episodeFileOf,
  fileBytes,
  formatSize,
  releaseTypeOf,
  seasonBytes,
  timeAgo,
  type EpisodeEntry,
  type WebhookItem,
} from "@/lib/webhook-grouping";
import type { WebhookNotification } from "@/lib/api-types";
import {
  IconChevronDown,
  IconCode,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
  IconHistory,
} from "@tabler/icons-react";

export interface EpisodeActions {
  onSync: (notification: WebhookNotification) => void;
  onDryRun: (notification: WebhookNotification) => void;
  onJson: (notification: WebhookNotification) => void;
  onDelete: (notification: WebhookNotification) => void;
}

/** Labelled key/value line used throughout the detail panel. */
function Field({ label, value, mono }: { label: string; value?: string; mono?: boolean }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </span>
      <span
        className={cn("text-[12.5px] break-words text-foreground", mono && "font-mono text-xs")}
      >
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

function EpisodeRow({
  entry,
  seasonPath,
  expanded,
  onToggle,
  actions,
}: {
  entry: EpisodeEntry;
  seasonPath?: string;
  expanded: boolean;
  onToggle: () => void;
  actions: EpisodeActions;
}) {
  const notification = entry.current;
  const file = episodeFileOf(notification);
  const releaseType = releaseTypeOf(notification);
  const isPack = releaseType === "seasonPack";
  const media = file?.mediaInfo;

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      {/* Collapsed header */}
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-muted/40"
      >
        <span className="font-mono text-xs font-semibold text-brand-hover">{entry.label}</span>
        <span className="truncate text-[13px] text-foreground">{entry.title || "Episode"}</span>
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
        <span className="flex-1" />
        {file?.quality && (
          <span className="hidden font-mono text-[11px] text-muted-foreground sm:inline">
            {file.quality}
          </span>
        )}
        <span className="shrink-0 font-mono text-[11px] text-foreground/80">
          {formatSize(fileBytes(notification))}
        </span>
        <StatusBadge status={notification.status} size="sm" />
        <IconChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-180"
          )}
        />
      </button>

      {expanded && (
        <div className="flex flex-col gap-4 border-t border-border bg-black/20 px-3.5 py-3.5">
          {/* Release */}
          <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Release
              </span>
              <span className="flex-1" />
              <Chip>{formatSize(fileBytes(notification))} file</Chip>
              {notification.release_size ? (
                <Chip>{formatSize(notification.release_size)} grab</Chip>
              ) : null}
              {file?.quality && <Chip>{file.quality}</Chip>}
              {file?.releaseGroup && <Chip>{file.releaseGroup}</Chip>}
              {notification.release_indexer && <Chip>{notification.release_indexer}</Chip>}
              {releaseType !== "unknown" && (
                <Chip>{isPack ? "season pack" : "single episode"}</Chip>
              )}
            </div>
            {notification.release_title && (
              <div className="rounded-md border border-border bg-background/60 px-3 py-2 font-mono text-[11px] break-all text-foreground/80">
                {notification.release_title}
              </div>
            )}
          </section>

          {/* Episode + media facts */}
          <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Field label="Episode" value={entry.label} mono />
            <Field label="Air date" value={entry.airDate} mono />
            <Field label="Imported" value={timeAgo(notification.created_at)} />
            {media?.width && media?.height ? (
              <Field label="Resolution" value={`${media.width}×${media.height}`} mono />
            ) : null}
            {media?.videoCodec ? <Field label="Video" value={media.videoCodec} mono /> : null}
            {media?.audioCodec ? (
              <Field
                label="Audio"
                value={`${media.audioCodec}${media.audioChannels ? ` ${media.audioChannels}ch` : ""}`}
                mono
              />
            ) : null}
            {media?.audioLanguages?.length ? (
              <Field label="Languages" value={media.audioLanguages.join(", ")} mono />
            ) : null}
            {media?.subtitles?.length ? (
              <Field label="Subtitles" value={media.subtitles.join(", ")} mono />
            ) : null}
          </section>

          {/* Paths */}
          <section className="flex flex-col gap-2">
            <span className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Paths
            </span>
            {seasonPath && (
              <div className="rounded-md border border-border bg-background/60 px-3 py-2 font-mono text-[11px] break-all text-muted-foreground">
                {seasonPath}
              </div>
            )}
            {(file?.path || file?.relativePath) && (
              <div className="rounded-md border border-border bg-background/60 px-3 py-2 font-mono text-[11px] break-all text-foreground/80">
                {file.path || file.relativePath}
              </div>
            )}
          </section>

          {/* Previous grabs for this episode */}
          {entry.history.length > 0 && (
            <section className="flex flex-col gap-1.5">
              <span className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
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
          <div className="flex flex-wrap gap-2 border-t border-border pt-3">
            {(notification.status === "pending" || notification.status === "failed") && (
              <Button size="sm" variant="outline" onClick={() => actions.onSync(notification)}>
                <IconPlayerPlay className="mr-1.5 size-3.5" />
                {notification.status === "failed" ? "Retry" : "Sync"}
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
      )}
    </div>
  );
}

/**
 * Per-episode breakdown of a grouped season: one row per episode showing the
 * file currently on disk, with release, media and path detail on expand.
 */
export function EpisodeDetails({ item, actions }: { item: WebhookItem; actions: EpisodeActions }) {
  const entries = episodeEntries(item.notifications, item.seasonNumber);
  const [openEpisode, setOpenEpisode] = useState<number | null>(
    entries.length === 1 ? entries[0].episodeNumber : null
  );
  const seasonPath = item.notifications.find((n) => n.season_path)?.season_path;

  if (!entries.length) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        No episode detail recorded for this notification.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
        <Chip>
          {entries.length} episode{entries.length === 1 ? "" : "s"}
        </Chip>
        <Chip>{formatSize(seasonBytes(item.notifications))} on disk</Chip>
        <Chip>
          {item.notifications.length} webhook{item.notifications.length === 1 ? "" : "s"}
        </Chip>
      </div>

      <div className="flex flex-col gap-2">
        {entries.map((entry) => (
          <EpisodeRow
            key={entry.episodeNumber}
            entry={entry}
            seasonPath={seasonPath}
            expanded={openEpisode === entry.episodeNumber}
            onToggle={() =>
              setOpenEpisode((current) =>
                current === entry.episodeNumber ? null : entry.episodeNumber
              )
            }
            actions={actions}
          />
        ))}
      </div>
    </div>
  );
}
