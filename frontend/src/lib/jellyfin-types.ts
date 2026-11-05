/** Jellyfin: what is playing, and DragonCP's record of every play. */

export type PlayMethod = "DirectPlay" | "DirectStream" | "Transcode" | "";

export interface JellyfinItem {
  id: string;
  /** Episode, Movie, ... as Jellyfin names it. */
  type: string;
  title: string;
  series: string;
  series_id: string;
  season: number | null;
  episode: number | null;
  year: number | null;
  runtime_seconds: number | null;
  /** A signed address on this app; empty when there is none. */
  poster?: string;
}

export interface TrackInfo {
  codec: string;
  language: string;
  title: string;
  width?: number | null;
  height?: number | null;
  bit_depth?: number | null;
  range?: string;
  bitrate?: number | null;
  profile?: string;
  channels?: number | null;
  external?: boolean;
  forced?: boolean;
}

/** What the file holds, and which of its tracks played. */
export interface SourceMedia {
  container: string;
  video: TrackInfo | null;
  audio: TrackInfo | null;
  subtitle: TrackInfo | null;
}

/** What Jellyfin is converting the stream to, and why. */
export interface TranscodeInfo {
  /** True: the picture is being converted. Null: Jellyfin did not say. */
  video: boolean | null;
  audio: boolean | null;
  reasons: string[];
  container: string;
  video_codec: string;
  audio_codec: string;
  width: number | null;
  height: number | null;
  bitrate: number | null;
  framerate: number | null;
  audio_channels: number | null;
  /** nvenc, qsv, vaapi, ... or none. */
  hardware: string;
  progress: number | null;
  method: PlayMethod;
}

export interface Stream {
  session_id: string;
  user: { id: string; name: string };
  client: string;
  app_version: string;
  device: { id: string; name: string };
  address: string;
  /** local: the home network or the tailnet. */
  network: "local" | "remote" | "";
  item: JellyfinItem;
  position_seconds: number;
  paused: boolean;
  play_method: PlayMethod;
  transcode: TranscodeInfo | null;
  source: SourceMedia;
}

export interface NowPlaying {
  success: boolean;
  ok: boolean;
  /** off: Jellyfin is switched off or not set up. */
  state: "ok" | "off" | "unreachable";
  streams: Stream[];
  recording?: boolean;
  signed_in?: number;
  message: string;
  checked_at: string;
}

export interface Play {
  id: number;
  /** live: watched by DragonCP. */
  source: string;
  user: string;
  client: string;
  app_version: string;
  device: string;
  address: string;
  network: string;
  item: JellyfinItem;
  started_at: string;
  last_seen_at: string | null;
  /** Null while it is still playing. */
  ended_at: string | null;
  watched_seconds: number;
  reached_seconds: number;
  finished: boolean;
  play_method: PlayMethod | null;
  video_converted: boolean;
  audio_converted: boolean;
  reasons: string[];
  transcode: TranscodeInfo | null;
  source_media: SourceMedia | null;
}

export interface PlaysPage {
  success: boolean;
  recording: boolean;
  plays: Play[];
  total: number;
  /** Everyone with a recorded play, most recent first. */
  users: string[];
}
