/**
 * The words of the Jellyfin tabs: play methods, and the reasons Jellyfin gives
 * for converting a stream, each in plain words with what usually avoids it.
 *
 * Jellyfin sends the reasons as codes ("SubtitleCodecNotSupported"). Nobody
 * should have to know what those mean to see what to change, so each one says
 * what the viewer's app could not do and what would let it play the file as
 * it is. A code this list does not know is shown as Jellyfin sent it.
 */

import type { PlayMethod, TrackInfo } from "@/lib/jellyfin-types";
import type { Tone } from "@/components/integrations/library-vocab";

export interface ReasonInfo {
  /** A few words, for a chip. */
  label: string;
  /** What happened, as the operator would say it. */
  meaning: string;
  /** What usually avoids it next time. */
  fix: string;
}

export const REASONS: Record<string, ReasonInfo> = {
  SubtitleCodecNotSupported: {
    label: "Subtitles",
    meaning:
      "The app cannot draw these subtitles (styled ASS, or picture-based PGS), so Jellyfin burns them into the picture.",
    fix: "A plain-text subtitle track, or an app that draws styled subtitles itself.",
  },
  VideoCodecNotSupported: {
    label: "Video format",
    meaning: "The device cannot decode this video format (often HEVC or AV1).",
    fix: "A different app or device, or a copy in H.264.",
  },
  VideoBitDepthNotSupported: {
    label: "10-bit video",
    meaning: "The video is 10-bit and the device only plays 8-bit.",
    fix: "A different app or device, or an 8-bit copy.",
  },
  VideoRangeTypeNotSupported: {
    label: "HDR",
    meaning:
      "The video is HDR or Dolby Vision and the screen cannot show it, so Jellyfin tone-maps it.",
    fix: "An HDR-capable app, or an SDR copy.",
  },
  ContainerBitrateExceedsLimit: {
    label: "Quality limit",
    meaning:
      "The file's bitrate is higher than the app's quality setting or the user's streaming limit.",
    fix: "Raise the quality setting in the app, or the user's limit in Jellyfin.",
  },
  VideoBitrateNotSupported: {
    label: "Video bitrate",
    meaning: "The video's bitrate is higher than the device or its connection allows.",
    fix: "Raise the quality setting in the app, or the user's limit in Jellyfin.",
  },
  AudioCodecNotSupported: {
    label: "Audio format",
    meaning:
      "The device cannot play this audio (often TrueHD, DTS or FLAC). Usually only the sound is converted, which is cheap.",
    fix: "Usually nothing to do.",
  },
  AudioChannelsNotSupported: {
    label: "Surround sound",
    meaning: "The device cannot play this many audio channels, so Jellyfin mixes them down.",
    fix: "Usually nothing to do.",
  },
  ContainerNotSupported: {
    label: "File type",
    meaning:
      "The app cannot open this kind of file (often MKV), so Jellyfin repackages it. Cheap on its own.",
    fix: "Usually nothing to do.",
  },
  VideoProfileNotSupported: {
    label: "Video profile",
    meaning: "The video was encoded with a profile the device does not support.",
    fix: "A different app or device.",
  },
  VideoLevelNotSupported: {
    label: "Video level",
    meaning: "The video's encoding level is higher than the device supports.",
    fix: "A different app or device.",
  },
  VideoResolutionNotSupported: {
    label: "Resolution",
    meaning: "The video's resolution is higher than the device plays.",
    fix: "A different app or device, or a lower-resolution copy.",
  },
  VideoFramerateNotSupported: {
    label: "Frame rate",
    meaning: "The video's frame rate is higher than the device plays.",
    fix: "A different app or device.",
  },
  RefFramesNotSupported: {
    label: "Reference frames",
    meaning: "The video uses more reference frames than the device can handle.",
    fix: "A different app or device.",
  },
  InterlacedVideoNotSupported: {
    label: "Interlaced",
    meaning: "The video is interlaced and the device only plays progressive video.",
    fix: "A different app or device.",
  },
  AnamorphicVideoNotSupported: {
    label: "Anamorphic",
    meaning: "The video has non-square pixels and the device cannot stretch them.",
    fix: "A different app or device.",
  },
  VideoCodecTagNotSupported: {
    label: "Video tag",
    meaning: "The device does not accept how this video's format is labelled in the file.",
    fix: "A different app or device.",
  },
  AudioProfileNotSupported: {
    label: "Audio profile",
    meaning: "The audio was encoded with a profile the device does not support.",
    fix: "Usually nothing to do.",
  },
  AudioSampleRateNotSupported: {
    label: "Sample rate",
    meaning: "The audio's sample rate is one the device does not play.",
    fix: "Usually nothing to do.",
  },
  AudioBitDepthNotSupported: {
    label: "Audio bit depth",
    meaning: "The audio's bit depth is one the device does not play.",
    fix: "Usually nothing to do.",
  },
  AudioBitrateNotSupported: {
    label: "Audio bitrate",
    meaning: "The audio's bitrate is higher than the device allows.",
    fix: "Usually nothing to do.",
  },
  AudioIsExternal: {
    label: "Separate audio",
    meaning: "The audio track is a separate file, so Jellyfin has to join it to the video.",
    fix: "Usually nothing to do.",
  },
  SecondaryAudioNotSupported: {
    label: "Second audio track",
    meaning: "The chosen audio is not the first track, and the app can only play the first.",
    fix: "Usually nothing to do.",
  },
  UnknownVideoStreamInfo: {
    label: "Unreadable video",
    meaning: "Jellyfin could not read the video track's details.",
    fix: "Check the file; it may be damaged.",
  },
  UnknownAudioStreamInfo: {
    label: "Unreadable audio",
    meaning: "Jellyfin could not read the audio track's details.",
    fix: "Check the file; it may be damaged.",
  },
  DirectPlayError: {
    label: "Direct play failed",
    meaning:
      "The app tried to play the file as it is, failed, and fell back to a converted stream.",
    fix: "The app; try another one on that device.",
  },
  StreamCountExceedsLimit: {
    label: "Too many tracks",
    meaning: "The file has more tracks than the app accepts.",
    fix: "The app.",
  },
};

export function reasonInfo(code: string): ReasonInfo {
  return REASONS[code] ?? { label: code, meaning: `Jellyfin said: ${code}.`, fix: "" };
}

/** Reasons that only touch the sound or the file's packaging: cheap, and
 *  usually nothing to do. Listed after the ones that convert the picture. */
const CHEAP = new Set([
  "AudioCodecNotSupported",
  "AudioChannelsNotSupported",
  "AudioProfileNotSupported",
  "AudioSampleRateNotSupported",
  "AudioBitDepthNotSupported",
  "AudioBitrateNotSupported",
  "AudioIsExternal",
  "SecondaryAudioNotSupported",
  "ContainerNotSupported",
]);

/** The reasons worth acting on first: whatever converts the picture. */
export function byCost(codes: string[]): string[] {
  return [...codes].sort((a, b) => Number(CHEAP.has(a)) - Number(CHEAP.has(b)));
}

export interface MethodInfo {
  label: string;
  tone: Tone;
  hint: string;
}

/**
 * How a stream is played. "Converted" rather than "transcoded" on screen;
 * the hint gives Jellyfin's own word.
 */
export function methodInfo(
  method: PlayMethod | null | undefined,
  videoConverted?: boolean | null
): MethodInfo {
  if (method === "Transcode") {
    return videoConverted === false
      ? {
          label: "Sound converted",
          tone: "info",
          hint: "Jellyfin is converting only the sound (Transcode). The picture plays as it is.",
        }
      : {
          label: "Converting",
          tone: "warn",
          hint: "Jellyfin is converting the picture (Transcode). This is the expensive kind.",
        };
  }
  if (method === "DirectStream") {
    return {
      label: "Repackaged",
      tone: "info",
      hint: "Jellyfin is repackaging the file without converting the picture (Direct stream).",
    };
  }
  if (method === "DirectPlay") {
    return { label: "Direct", tone: "ok", hint: "The app plays the file as it is (Direct play)." };
  }
  return { label: "Unknown", tone: "muted", hint: "Jellyfin did not say how this is played." };
}

/** "S01E05" for an episode, the year for a film. */
export function episodeCode(season: number | null, episode: number | null): string {
  if (season == null || episode == null) return "";
  return `S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")}`;
}

/** 1:05:09 or 5:09. */
export function clock(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(seconds ?? 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

/** "1 h 5 min", "12 min", "under a minute". */
export function duration(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(seconds ?? 0));
  if (total < 60) return "under a minute";
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return h ? `${h} h${m ? ` ${m} min` : ""}` : `${m} min`;
}

export function bitrate(bits: number | null | undefined): string {
  if (!bits) return "";
  return bits >= 1_000_000
    ? `${(bits / 1_000_000).toFixed(1)} Mbps`
    : `${Math.round(bits / 1000)} kbps`;
}

export function resolution(width?: number | null, height?: number | null): string {
  if (!height && !width) return "";
  const h = height ?? 0;
  const w = width ?? 0;
  if (w >= 3800 || h >= 2100) return "4K";
  if (w >= 1900 || h >= 1060) return "1080p";
  if (w >= 1260 || h >= 700) return "720p";
  return h ? `${h}p` : `${w}w`;
}

/** "HEVC 10-bit 1080p", "AAC 5.1", "ASS (English)". */
export function trackText(
  track: TrackInfo | null | undefined,
  kind: "video" | "audio" | "subtitle"
): string {
  if (!track) return "";
  const codec = track.codec ? track.codec.toUpperCase() : "";
  if (kind === "video") {
    return [
      codec,
      track.bit_depth && track.bit_depth > 8 ? `${track.bit_depth}-bit` : "",
      track.range && track.range !== "SDR" ? track.range : "",
      resolution(track.width, track.height),
    ]
      .filter(Boolean)
      .join(" ");
  }
  if (kind === "audio") {
    const channels =
      track.channels === 6
        ? "5.1"
        : track.channels === 8
          ? "7.1"
          : track.channels === 2
            ? "stereo"
            : track.channels === 1
              ? "mono"
              : "";
    return [codec, channels, track.language].filter(Boolean).join(" ");
  }
  return [codec, track.language ? `(${track.language})` : "", track.external ? "separate file" : ""]
    .filter(Boolean)
    .join(" ");
}

/** "3 min ago", "2 h ago", "yesterday", or the date. */
export function since(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();
  if (Number.isNaN(diff)) return "";
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  if (hours < 48) return "yesterday";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
