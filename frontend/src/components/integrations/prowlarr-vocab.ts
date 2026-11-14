import type { ProwlarrIndexer, ProwlarrRelease, SearchType } from "@/lib/prowlarr-types";

/** The category chips under the search box, in Newznab's standard numbers.
 *  A parent number covers its children: TV covers TV/HD and TV/Anime. */
export const CATEGORIES = [
  { id: 2000, label: "Movies" },
  { id: 5000, label: "TV" },
  { id: 5070, label: "Anime" },
  { id: 3000, label: "Audio" },
  { id: 7000, label: "Books" },
  { id: 4000, label: "PC" },
  { id: 1000, label: "Console" },
  { id: 8000, label: "Other" },
] as const;

export const SEARCH_MODES: { value: SearchType; label: string }[] = [
  { value: "search", label: "Anything" },
  { value: "tvsearch", label: "TV" },
  { value: "movie", label: "Film" },
];

export const SORTS = [
  { value: "seeders", label: "Most seeders" },
  { value: "newest", label: "Newest" },
  { value: "biggest", label: "Biggest" },
  { value: "smallest", label: "Smallest" },
  { value: "grabs", label: "Most grabbed" },
  { value: "title", label: "Title A–Z" },
] as const;
export type SortKey = (typeof SORTS)[number]["value"];

export const RESOLUTIONS = ["2160p", "1080p", "720p", "SD"] as const;
export type Resolution = (typeof RESOLUTIONS)[number];

/** The words in a release name worth seeing at a glance, in reading order. */
const TOKEN_RULES: { kind: "res" | "src" | "codec" | "hdr" | "audio"; pattern: RegExp }[] = [
  { kind: "res", pattern: /\b(2160p|4k|uhd|1080p|1080i|720p|576p|480p)\b/i },
  {
    kind: "src",
    pattern: /\b(remux|blu-?ray|bdrip|brrip|web-?dl|webrip|web|hdtv|dvdrip|dvd|hdrip|cam|ts)\b/i,
  },
  { kind: "hdr", pattern: /\b(hdr10\+|hdr10|hdr|dv|dovi|dolby[ .]?vision)\b/i },
  { kind: "codec", pattern: /\b(x265|x264|h\.?265|h\.?264|hevc|avc|av1|xvid)\b/i },
  {
    kind: "audio",
    pattern:
      /\b(atmos|truehd|dts-?hd(?:[ .]?ma)?|dts-?x|dts|ddp?[ .]?[57]\.1|dd\+|eac3|ac3|aac|flac|opus)\b/i,
  },
];

export type QualityToken = { kind: (typeof TOKEN_RULES)[number]["kind"]; text: string };

export function qualityTokens(title: string): QualityToken[] {
  const tokens: QualityToken[] = [];
  for (const rule of TOKEN_RULES) {
    const match = rule.pattern.exec(title);
    if (match) tokens.push({ kind: rule.kind, text: normalise(match[1], rule.kind) });
  }
  return tokens;
}

function normalise(text: string, kind: QualityToken["kind"]) {
  const lower = text.toLowerCase();
  if (lower === "4k" || lower === "uhd") return "2160p";
  if (kind === "res") return lower;
  if (lower.startsWith("web-") || lower === "webdl") return "WEB-DL";
  if (lower === "webrip") return "WEBRip";
  if (lower.startsWith("blu")) return "BluRay";
  if (lower === "dovi" || lower.startsWith("dolby")) return "DV";
  if (kind === "codec" && lower.startsWith("x")) return lower;
  return text.toUpperCase();
}

export function resolutionOf(release: ProwlarrRelease): Resolution {
  const found = qualityTokens(release.title)
    .find((t) => t.kind === "res")
    ?.text.toLowerCase();
  if (found === "2160p") return "2160p";
  if (found?.startsWith("1080")) return "1080p";
  if (found === "720p") return "720p";
  return "SD";
}

/** "40 min", "3 h", "2 d", "5 mo", "1 y". Short enough for a phone's meta line. */
export function ageText(iso: string | null, now = Date.now()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const minutes = Math.max(0, (now - then) / 60_000);
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)} h`;
  const days = hours / 24;
  if (days < 60) return `${Math.round(days)} d`;
  if (days < 365) return `${Math.round(days / 30)} mo`;
  return `${(days / 365).toFixed(days < 3650 ? 1 : 0)} y`;
}

export function ageDays(iso: string | null, now = Date.now()): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  return Number.isFinite(then) ? (now - then) / 86_400_000 : null;
}

/** Flags as Prowlarr names them, in words. */
export function flagLabel(flag: string): string {
  const known: Record<string, string> = {
    freeleech: "Freeleech",
    halfleech: "Half leech",
    freeleech75: "75% free",
    freeleech25: "25% free",
    doubleupload: "Double up",
    internal: "Internal",
    scene: "Scene",
    exclusive: "Exclusive",
    nuked: "Nuked",
  };
  return known[flag] ?? flag.charAt(0).toUpperCase() + flag.slice(1);
}

export function isFree(release: ProwlarrRelease) {
  return release.flags.some((f) => f === "freeleech" || f.startsWith("freeleech"));
}

export function sortReleases(releases: ProwlarrRelease[], sort: SortKey): ProwlarrRelease[] {
  const by = [...releases];
  const num = (value: number | null | undefined) => value ?? -1;
  const time = (iso: string | null) => (iso ? new Date(iso).getTime() : 0);
  switch (sort) {
    case "seeders":
      // Usenet has no seeders; grabs stand in so it sorts among torrents sensibly.
      return by.sort(
        (a, b) => num(b.seeders ?? b.grabs) - num(a.seeders ?? a.grabs) || num(b.size) - num(a.size)
      );
    case "newest":
      return by.sort((a, b) => time(b.published) - time(a.published));
    case "biggest":
      return by.sort((a, b) => num(b.size) - num(a.size));
    case "smallest":
      return by.sort((a, b) => num(a.size) - num(b.size));
    case "grabs":
      return by.sort((a, b) => num(b.grabs) - num(a.grabs));
    case "title":
      return by.sort((a, b) => a.title.localeCompare(b.title));
  }
}

export interface ResultFilter {
  text: string;
  protocols: string[];
  resolutions: Resolution[];
  indexers: number[];
  minSeeders: number;
  maxAgeDays: number | null;
  minGb: number | null;
  maxGb: number | null;
  freeOnly: boolean;
}

export const EMPTY_FILTER: ResultFilter = {
  text: "",
  protocols: [],
  resolutions: [],
  indexers: [],
  minSeeders: 0,
  maxAgeDays: null,
  minGb: null,
  maxGb: null,
  freeOnly: false,
};

/** How many of the sheet's filters are set, for the badge on its button. */
export function activeFilters(filter: ResultFilter): number {
  return (
    (filter.protocols.length ? 1 : 0) +
    (filter.resolutions.length ? 1 : 0) +
    (filter.indexers.length ? 1 : 0) +
    (filter.minSeeders > 0 ? 1 : 0) +
    (filter.maxAgeDays != null ? 1 : 0) +
    (filter.minGb != null || filter.maxGb != null ? 1 : 0) +
    (filter.freeOnly ? 1 : 0)
  );
}

export function filterReleases(
  releases: ProwlarrRelease[],
  filter: ResultFilter,
  now = Date.now()
) {
  // Every word must appear, in any order; "-word" must not.
  const words = filter.text.toLowerCase().split(/\s+/).filter(Boolean);
  const must = words.filter((w) => !w.startsWith("-"));
  const mustNot = words.filter((w) => w.startsWith("-") && w.length > 1).map((w) => w.slice(1));
  const GB = 1024 ** 3;
  return releases.filter((release) => {
    const title = release.title.toLowerCase().replace(/[._]/g, " ");
    if (must.some((w) => !title.includes(w))) return false;
    if (mustNot.some((w) => title.includes(w))) return false;
    if (filter.protocols.length && !filter.protocols.includes(release.protocol)) return false;
    if (filter.resolutions.length && !filter.resolutions.includes(resolutionOf(release)))
      return false;
    if (
      filter.indexers.length &&
      (release.indexer_id == null || !filter.indexers.includes(release.indexer_id))
    )
      return false;
    if (
      filter.minSeeders > 0 &&
      release.protocol === "torrent" &&
      (release.seeders ?? 0) < filter.minSeeders
    )
      return false;
    if (filter.maxAgeDays != null) {
      const age = ageDays(release.published, now);
      if (age == null || age > filter.maxAgeDays) return false;
    }
    if (filter.minGb != null && (release.size ?? 0) < filter.minGb * GB) return false;
    if (filter.maxGb != null && (release.size ?? Infinity) > filter.maxGb * GB) return false;
    if (filter.freeOnly && !isFree(release)) return false;
    return true;
  });
}

export const INDEXER_STATE: Record<
  ProwlarrIndexer["state"],
  { label: string; dot: string; text: string }
> = {
  ok: { label: "Healthy", dot: "bg-emerald-400", text: "text-emerald-400" },
  failing: { label: "Failing", dot: "bg-amber-400", text: "text-amber-400" },
  paused: { label: "Paused", dot: "bg-rose-400", text: "text-rose-400" },
  off: { label: "Off", dot: "bg-muted-foreground/50", text: "text-muted-foreground" },
};

export function toggle<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}
