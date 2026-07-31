/**
 * Reading a media filename.
 *
 * Sonarr and Radarr write a predictable shape, and the library holds ~4,300
 * files in it:
 *
 *   Series - S01E03 - Third Episode [WEBRip-1080p][TAoE-Dragon DB].mkv
 *   Series (2025) - S02E04 - 016 - The Title [Anime Dual-Audio WEBDL-1080p][JA+EN][VARYG-Dragon DB].mkv
 *   Title (2025) WEBDL-1080p [HI+ML] [ViSTA-Dragon DB].mkv
 *
 * Two things follow from that shape, and both matter for how a row reads:
 *
 * 1. **The interesting parts sit at both ends.** The episode title is in the
 *    middle and the format is at the very end, so a name that truncates loses
 *    the format entirely. Pulling the format out means it survives.
 * 2. **The title slot is not always a title.** 48 files in the library are
 *    named `Example Show - S01E01 - 1080p x265.mkv`, where the slot holds
 *    quality instead. Printing that as a title makes twenty-two episodes look
 *    identical. It is recognised and reported as format, not as a name.
 */

const RESOLUTION = /\b\d{3,4}p\b/i;
const CODEC = /\b(?:x26[45]|h\.?26[45]|hevc|av1|xvid)\b/i;
const FLAG = /\b(?:proper|repack|remux|v\d|hdr\d*|dolby[\s-]?vision|dv|10bit)\b/i;
const LANGUAGES = /^[A-Z]{2,3}(?:\+[A-Z]{2,3})*$/;
/** Every group in this library is written `<name>-Dragon DB`. */
const GROUP_SUFFIX = "-Dragon DB";
/** `Series - S01E03 - ` or `Series (2025) - S02E04 - 016 - ` */
const EPISODE_PREFIX = /^.+? - S\d+E\d+ - (?:\d{2,4} - )?/i;
const SUBTITLE_TAG = /\.(?:[a-z]{2,3}|forced|sdh)$/i;

export interface ParsedFilename {
  /** The episode or movie title. Empty when the filename carries none. */
  title: string;
  /** `WEBDL-1080p`, `Bluray-1080p`, `1080p` — whatever the name states. */
  quality: string | null;
  codec: string | null;
  languages: string | null;
  group: string | null;
  /** `Proper`, `v2`, `HDR` and the like. */
  flags: string[];
  /** Everything above, in the order it should be shown. */
  format: string[];
}

/**
 * The container, from the extension: `MKV`, `MP4`, `SRT`.
 *
 * Worth its own chip because it sits at the very end of the name, which is the
 * first thing a truncating cell loses — and because it is the one fact about a
 * file that never appears anywhere else on the row.
 */
export function containerOf(name: string): string | null {
  const match = name.match(/\.([A-Za-z0-9]{2,4})$/);
  return match ? match[1].toUpperCase() : null;
}

/** The episode code inside a filename, so it can be picked out when shown. */
export const EPISODE_CODE = /S\d{1,3}E\d{1,4}/i;

/** Strips the extension, and a `.eng` / `.forced` tag from a subtitle. */
function stem(name: string): string {
  let out = name.replace(/\.[^.]+$/, "");
  if (SUBTITLE_TAG.test(out)) out = out.replace(SUBTITLE_TAG, "");
  return out;
}

export function parseFilename(name: string, isMovie = false): ParsedFilename {
  const base = stem(name);
  const brackets = [...base.matchAll(/\[([^\]]*)\]/g)].map((m) => m[1].trim());
  let head = base.replace(/\s*\[.*$/, "").trim();

  let quality: string | null = null;
  let codec: string | null = null;
  let languages: string | null = null;
  let group: string | null = null;
  const flags: string[] = [];

  for (const part of brackets) {
    if (part.endsWith(GROUP_SUFFIX)) group = part.slice(0, -GROUP_SUFFIX.length) || null;
    else if (LANGUAGES.test(part)) languages = part;
    else if (RESOLUTION.test(part)) quality = part;
    else if (part) flags.push(part);
  }

  // A movie states its quality outside the brackets: `Title (2025) WEBDL-1080p`.
  if (!quality) {
    const inHead = head.match(/\b[\w]*-?\d{3,4}p\b/i);
    if (inHead && isMovie) {
      quality = inHead[0];
      head = head.slice(0, inHead.index).trim();
    }
  }

  // The title is whatever follows the episode code.
  let title = isMovie
    ? head.replace(/\s*\(\d{4}\)\s*$/, "").trim()
    : head.replace(EPISODE_PREFIX, "").trim();

  // Some names put the quality in the title slot rather than in brackets:
  // `Pilot Bluray-1080p` still has a title, `1080p x265` does not. Lift the
  // format out and keep whatever words are left — blanking the whole slot
  // would throw away real titles.
  if (title && !isMovie && (RESOLUTION.test(title) || CODEC.test(title))) {
    const res = title.match(/\b(?:[A-Za-z]+-)?\d{3,4}p\b/i);
    if (res) {
      if (!quality) quality = res[0];
      title = title.replace(res[0], " ");
    }
    const cod = title.match(CODEC);
    if (cod) {
      if (!codec) codec = cod[0];
      title = title.replace(cod[0], " ");
    }
    title = title
      .replace(/\s{2,}/g, " ")
      .replace(/^[\s\-–—.]+|[\s\-–—.]+$/g, "")
      .trim();
  }

  // Codecs and flags can appear inside the quality bracket too.
  const haystack = [quality ?? "", ...flags].join(" ");
  if (!codec) codec = haystack.match(CODEC)?.[0] ?? null;
  const flagMatch = haystack.match(new RegExp(FLAG.source, "gi"));
  if (flagMatch) for (const f of flagMatch) if (!flags.includes(f)) flags.push(f);

  // `Anime Dual-Audio WEBDL-1080p` reads better as just the quality.
  if (quality) quality = quality.replace(/^anime\s+/i, "").trim();

  const format = [quality, codec, languages].filter(Boolean) as string[];
  for (const flag of flags) {
    // `[WEBDL-1080p Proper]` already says Proper — do not say it twice.
    const alreadyShown = format.some((shown) => shown.toLowerCase().includes(flag.toLowerCase()));
    if (!alreadyShown && !RESOLUTION.test(flag) && FLAG.test(flag)) format.push(flag);
  }

  return { title, quality, codec, languages, group, flags, format };
}
