import {
  IconAlertTriangle,
  IconCircleCheck,
  IconDeviceTv,
  IconPlayerPause,
  IconPlayerPlay,
  IconPlugConnectedX,
  IconHistory,
  IconTransform,
  IconWorld,
  IconHome,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { Notice, TitlePoster, ToneChip } from "@/components/integrations/library-bits";
import { TONE_BAR, libraryError } from "@/components/integrations/library-vocab";
import {
  bitrate,
  clock,
  episodeCode,
  methodInfo,
  byCost,
  reasonInfo,
  resolution,
  trackText,
} from "@/components/integrations/jellyfin-vocab";
import { useNowPlaying } from "@/hooks/useJellyfin";
import type { Stream } from "@/lib/jellyfin-types";

/**
 * What is playing on Jellyfin right now, converted streams first.
 *
 * The point of the tab is the converted ones: each says, in plain words, why
 * Jellyfin could not send the file as it is, and what usually avoids it. A
 * stream played as it is needs no explanation and gets one quiet line.
 */
export function NowPlayingPanel({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { data, isLoading, isError, error } = useNowPlaying();
  const streams = data?.streams ?? [];
  const converting = streams.filter((s) => s.play_method === "Transcode").length;

  const summary = [
    streams.length ? `${streams.length} playing` : null,
    converting ? `${converting} converting` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="space-y-3">
      {data?.ok && data.recording === false && (
        <Notice tone="muted" icon={IconHistory}>
          <span>
            Plays are not being kept. Switch on <strong>Record plays</strong> to keep who watched
            what and why it was converted.{" "}
          </span>
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
        label="Now playing"
        description={
          data?.ok ? `${summary || "Nothing playing"}. Checked every 5 seconds.` : undefined
        }
      >
        {isLoading ? (
          <RowsSkeleton />
        ) : isError ? (
          <div className="p-3">
            <Notice tone="crit" icon={IconAlertTriangle}>
              {libraryError(error, "Could not read what is playing.")}
            </Notice>
          </div>
        ) : data?.state === "off" ? (
          <div className="p-3">
            <Notice tone="muted" icon={IconPlugConnectedX}>
              Jellyfin is off, or its address and API key are not saved yet.{" "}
              <button
                type="button"
                onClick={onOpenSettings}
                className="font-medium text-foreground underline-offset-2 hover:underline"
              >
                Open Connection
              </button>
            </Notice>
          </div>
        ) : data && !data.ok ? (
          <div className="p-3">
            <Notice tone="warn" icon={IconPlugConnectedX}>
              {data.message || "Jellyfin did not answer."}
            </Notice>
          </div>
        ) : streams.length === 0 ? (
          <SectionEmpty
            icon={IconCircleCheck}
            title="Nothing is playing"
            hint="Streams show up here within a few seconds of starting, converted ones first."
          />
        ) : (
          <ul className="divide-y divide-border/70">
            {streams.map((stream) => (
              <StreamRow key={`${stream.session_id}-${stream.item.id}`} stream={stream} />
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

function StreamRow({ stream }: { stream: Stream }) {
  const { item, transcode } = stream;
  const method = methodInfo(stream.play_method, transcode?.video);
  const code = episodeCode(item.season, item.episode);
  const runtime = item.runtime_seconds ?? 0;
  const percent = runtime ? Math.min(100, (stream.position_seconds / runtime) * 100) : 0;
  const reasons = byCost(transcode?.reasons ?? []);
  const file = [
    stream.source.container.toUpperCase(),
    trackText(stream.source.video, "video"),
    trackText(stream.source.audio, "audio"),
  ]
    .filter(Boolean)
    .join(" · ");
  const subtitle = trackText(stream.source.subtitle, "subtitle");
  const sent =
    transcode && stream.play_method === "Transcode"
      ? [
          transcode.video ? transcode.video_codec.toUpperCase() : "picture as it is",
          transcode.video ? resolution(transcode.width, transcode.height) : "",
          transcode.audio
            ? `${transcode.audio_codec.toUpperCase()}${transcode.audio_channels ? ` ${transcode.audio_channels} ch` : ""}`
            : "sound as it is",
          bitrate(transcode.bitrate),
          transcode.hardware && transcode.hardware !== "none"
            ? `on the GPU (${transcode.hardware.toUpperCase()})`
            : transcode.video
              ? "on the CPU"
              : "",
        ]
          .filter(Boolean)
          .join(" · ")
      : "";

  return (
    <li
      className={cn(
        "flex gap-3 px-3.5 py-3",
        stream.play_method === "Transcode" && transcode?.video !== false && "bg-amber-500/[0.03]"
      )}
    >
      <TitlePoster
        src={item.poster}
        movie={item.type === "Movie"}
        className="w-12 self-start sm:w-14"
      />
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-start justify-between gap-3">
          <p className="min-w-0 text-[13.5px] leading-snug break-words">
            <span className="font-semibold text-foreground">{item.series || item.title}</span>
            {!item.series && item.year ? (
              <span className="text-muted-foreground"> ({item.year})</span>
            ) : null}
            {code && <span className="ml-1.5 font-mono text-[12px] text-foreground-2">{code}</span>}
            {item.series && item.title && (
              <span className="ml-1.5 text-foreground-2">{item.title}</span>
            )}
          </p>
          <ToneChip
            tone={method.tone}
            icon={stream.play_method === "Transcode" ? IconTransform : IconPlayerPlay}
            label={method.label}
            title={method.hint}
          />
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
          <span className="font-medium text-foreground-2">{stream.user.name || "Someone"}</span>
          <span className="flex items-center gap-1">
            <IconDeviceTv className="size-3.5" />
            {stream.device.name || "Unknown device"}
          </span>
          {stream.client && (
            <span>
              {stream.client}
              {stream.app_version ? ` ${stream.app_version}` : ""}
            </span>
          )}
          {stream.network && (
            <span
              className="flex items-center gap-1"
              title={stream.address ? `From ${stream.address}` : undefined}
            >
              {stream.network === "local" ? (
                <IconHome className="size-3.5" />
              ) : (
                <IconWorld className="size-3.5" />
              )}
              {stream.network === "local" ? "At home" : "Away"}
            </span>
          )}
        </div>

        {runtime > 0 && (
          <div className="flex items-center gap-2">
            {stream.paused && (
              <IconPlayerPause
                className="size-3.5 shrink-0 text-muted-foreground"
                aria-label="Paused"
              />
            )}
            <div
              className="h-1 flex-1 overflow-hidden rounded-full bg-white/8"
              role="progressbar"
              aria-valuenow={Math.round(percent)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${Math.round(percent)}% watched`}
            >
              <div
                className={cn(
                  "h-full rounded-full transition-[width] duration-500",
                  stream.paused ? TONE_BAR.muted : TONE_BAR.brand
                )}
                style={{ width: `${percent}%` }}
              />
            </div>
            <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
              {clock(stream.position_seconds)} / {clock(runtime)}
            </span>
          </div>
        )}

        {reasons.length > 0 && (
          <ul className="space-y-1 rounded-lg border border-border/70 bg-well/60 px-3 py-2">
            {reasons.map((code) => {
              const info = reasonInfo(code);
              return (
                <li key={code} className="text-[12px] leading-snug">
                  <span className="font-semibold text-amber-300/90">{info.label}.</span>{" "}
                  <span className="text-foreground-2">{info.meaning}</span>
                  {info.fix && <span className="text-muted-foreground"> {info.fix}</span>}
                </li>
              );
            })}
          </ul>
        )}

        <div className="space-y-0.5 font-mono text-[10.5px] text-foreground-3">
          {file && (
            <p className="truncate" title={file}>
              File: {file}
            </p>
          )}
          {subtitle && <p className="truncate">Subtitles: {subtitle}</p>}
          {sent && (
            <p className="truncate" title={sent}>
              Sent as: {sent}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

function RowsSkeleton() {
  return (
    <div className="divide-y divide-border/70">
      {Array.from({ length: 2 }).map((_, i) => (
        <div key={i} className="flex gap-3 px-3.5 py-3">
          <Skeleton className="aspect-[2/3] w-14 rounded-md" />
          <div className="flex-1 space-y-2">
            <div className="flex justify-between gap-3">
              <Skeleton className="h-3.5 w-1/2" />
              <Skeleton className="h-4 w-24 rounded-full" />
            </div>
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="h-1 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}
