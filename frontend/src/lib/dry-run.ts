/**
 * Dry-run parsing.
 *
 * The backend hands back a validation blob (`safe_to_sync`, counts, file lists)
 * plus `raw_output`: the untouched stdout of `rsync -avv --dry-run --stats
 * --itemize-changes --delete`. Nearly everything a user wants to know before
 * approving a sync is buried in that text — which files move, which are already
 * in place, how many bytes are involved, whether rsync complained.
 *
 * This module turns both halves into one structured report so the UI can render
 * facts instead of a wall of escaped JSON. Every step is defensive: the payload
 * may arrive as a JSON string, may be missing counts, may have no raw output at
 * all (timeout / SSH failure), and rsync's format varies across versions.
 */

export type ChangeKind = "new" | "update" | "unchanged" | "delete";
export type EntryKind = "file" | "dir" | "link" | "special";

export interface DryRunEntry {
  /** Path relative to the season/movie folder, as rsync reported it. */
  path: string;
  name: string;
  dir: string;
  kind: EntryKind;
  change: ChangeKind;
  isMedia: boolean;
  /** `S01E03` when the filename carries an episode marker. */
  episode?: string;
  /** Human label: episode title, or the filename minus tags/extension. */
  label: string;
  /** Bracketed release tags, e.g. `WEBDL-1080p`, `N4B1L-Dragon DB`. */
  tags: string[];
  extension?: string;
}

export interface RsyncStats {
  totalFiles?: number;
  regularFiles?: number;
  directories?: number;
  createdFiles?: number;
  deletedFiles?: number;
  transferredFiles?: number;
  totalSize?: number;
  transferredSize?: number;
  literalData?: number;
  matchedData?: number;
  fileListSize?: number;
  fileListGenTime?: number;
  fileListTransferTime?: number;
  bytesSent?: number;
  bytesReceived?: number;
  rate?: number;
  speedup?: number;
}

export interface DryRunMessage {
  level: "error" | "warning";
  text: string;
}

export interface DryRunCheck {
  label: string;
  passed: boolean;
  detail: string;
}

export interface DryRunCounts {
  server: number;
  local: number;
  incoming: number;
  deleted: number;
  unchanged: number;
}

export interface DryRunReport {
  /** False when the payload carried nothing we could interpret. */
  ok: boolean;
  /**
   * `completed` means rsync actually ran and reported on the folder. A dry run
   * that timed out or died on SSH comes back with a reason and nothing else —
   * its zeroes are absence of data, not evidence that nothing would change.
   */
  completed: boolean;
  safeToSync: boolean;
  reason: string;
  headline: string;
  counts: DryRunCounts;
  entries: DryRunEntry[];
  stats: RsyncStats;
  connection: { user?: string; host?: string; remotePath?: string };
  messages: DryRunMessage[];
  checks: DryRunCheck[];
  raw: string;
  json: unknown;
}

const MEDIA_EXTENSIONS = [".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".flv", ".webm", ".ts"];

/**
 * rsync itemize line: `>f+++++++++ path`, `.f          path`, `cd+++++++++ path`.
 * Two type chars, nine attribute slots, then the path. Attribute slots are
 * letters, dots, `+`, `?` or spaces depending on rsync version and flags.
 */
const ITEMIZE_RE = /^([<>ch.*])([fdLDS])([a-zA-Z.+? ]{9})\s+(.+)$/;
const DELETING_RE = /^\*deleting\s+(.+)$/;
/** `opening connection using: ssh -o ... -l user host rsync --server ... "path"` */
const CONNECTION_RE = /opening connection using:\s*(.+)/;
const EPISODE_RE = /\bS(\d{1,3})E(\d{1,4})(?:-?E?\d{1,4})?\b/i;

function toNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const cleaned = value.replace(/,/g, "").trim();
    if (!cleaned) return undefined;
    const parsed = Number(cleaned);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function toCount(value: unknown): number {
  return Math.max(0, Math.round(toNumber(value) ?? 0));
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function isMediaPath(path: string): boolean {
  const lower = path.toLowerCase();
  return MEDIA_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/** Unwrap a payload that may be a JSON string, or nested under `dry_run_result`. */
function coercePayload(payload: unknown): Record<string, unknown> | null {
  let value = payload;

  if (typeof value === "string") {
    const text = value.trim();
    if (!text) return null;
    try {
      value = JSON.parse(text);
    } catch {
      // Not JSON — treat the string itself as raw rsync output.
      return { raw_output: text };
    }
  }

  if (!value || typeof value !== "object" || Array.isArray(value)) return null;

  const record = value as Record<string, unknown>;
  if (record.dry_run_result !== undefined && record.safe_to_sync === undefined) {
    return coercePayload(record.dry_run_result);
  }
  return record;
}

/** Split a media filename into the parts worth showing separately. */
function describeName(path: string): Pick<DryRunEntry, "episode" | "label" | "tags" | "extension"> {
  const name = path.split("/").filter(Boolean).pop() ?? path;
  const extMatch = name.match(/\.([a-z0-9]{1,5})$/i);
  const extension = extMatch ? extMatch[1].toLowerCase() : undefined;
  const stem = extMatch ? name.slice(0, -extMatch[0].length) : name;

  const tags = Array.from(stem.matchAll(/\[([^\]]+)\]/g)).map((match) => match[1].trim());
  let withoutTags = stem.replace(/\[[^\]]*\]/g, "").trim();

  // Subtitle sidecars carry a language sub-extension (`… .en.srt`); read it as a
  // tag so the filename itself stays clean.
  const language = withoutTags.match(/\.([a-z]{2,3})$/i);
  if (language) {
    tags.push(language[1].toLowerCase());
    withoutTags = withoutTags.slice(0, -language[0].length).trim();
  }

  const episodeMatch = withoutTags.match(EPISODE_RE);
  const episode = episodeMatch ? episodeMatch[0].toUpperCase() : undefined;

  // `Show - S01E03 - Episode Title` → keep the title, the show is the folder.
  let label = withoutTags;
  if (episodeMatch) {
    const after = withoutTags.slice(episodeMatch.index! + episodeMatch[0].length);
    const title = after.replace(/^\s*[-–—]\s*/, "").trim();
    if (title) label = title;
  }
  label = label
    .replace(/\s{2,}/g, " ")
    .replace(/[-–—\s]+$/, "")
    .trim();

  return { episode, label: label || name, tags, extension };
}

function makeEntry(path: string, kind: EntryKind, change: ChangeKind): DryRunEntry {
  const clean = path.replace(/^\.\//, "");
  const segments = clean.split("/").filter(Boolean);
  const name = segments[segments.length - 1] ?? clean;
  const dir = segments.slice(0, -1).join("/");
  return {
    path: clean || path,
    name,
    dir,
    kind,
    change,
    isMedia: kind === "file" && isMediaPath(clean),
    ...describeName(clean),
  };
}

function entryKindOf(typeChar: string): EntryKind {
  if (typeChar === "d") return "dir";
  if (typeChar === "L") return "link";
  if (typeChar === "f") return "file";
  return "special";
}

/** rsync stat lines, keyed by the label rsync prints. */
const STAT_FIELDS: Array<[keyof RsyncStats, RegExp]> = [
  ["createdFiles", /^Number of created files:\s*([\d,]+)/im],
  ["deletedFiles", /^Number of deleted files:\s*([\d,]+)/im],
  ["transferredFiles", /^Number of regular files transferred:\s*([\d,]+)/im],
  ["totalSize", /^Total file size:\s*([\d,]+)/im],
  ["transferredSize", /^Total transferred file size:\s*([\d,]+)/im],
  ["literalData", /^Literal data:\s*([\d,]+)/im],
  ["matchedData", /^Matched data:\s*([\d,]+)/im],
  ["fileListSize", /^File list size:\s*([\d,]+)/im],
  ["fileListGenTime", /^File list generation time:\s*([\d.,]+)/im],
  ["fileListTransferTime", /^File list transfer time:\s*([\d.,]+)/im],
  ["bytesSent", /^Total bytes sent:\s*([\d,]+)/im],
  ["bytesReceived", /^Total bytes received:\s*([\d,]+)/im],
];

function parseStats(raw: string): RsyncStats {
  const stats: RsyncStats = {};

  const fileCounts = raw.match(/^Number of files:\s*([\d,]+)(?:\s*\(([^)]*)\))?/im);
  if (fileCounts) {
    stats.totalFiles = toNumber(fileCounts[1]);
    const detail = fileCounts[2] ?? "";
    stats.regularFiles = toNumber(detail.match(/reg:\s*([\d,]+)/i)?.[1]);
    stats.directories = toNumber(detail.match(/dir:\s*([\d,]+)/i)?.[1]);
  }

  for (const [key, pattern] of STAT_FIELDS) {
    const value = toNumber(raw.match(pattern)?.[1]);
    if (value !== undefined) stats[key] = value;
  }

  // Trailing summary: `sent 94 bytes  received 820 bytes  121.87 bytes/sec`
  const rate = raw.match(/([\d.,]+)\s*bytes\/sec/i);
  if (rate) stats.rate = toNumber(rate[1]);
  const speedup = raw.match(/speedup is\s*([\d.,]+)/i);
  if (speedup) stats.speedup = toNumber(speedup[1]);
  if (stats.totalSize === undefined) {
    stats.totalSize = toNumber(raw.match(/^total size is\s*([\d,]+)/im)?.[1]);
  }
  if (stats.bytesSent === undefined) {
    stats.bytesSent = toNumber(raw.match(/^sent\s*([\d,]+)\s*bytes/im)?.[1]);
  }
  if (stats.bytesReceived === undefined) {
    stats.bytesReceived = toNumber(raw.match(/received\s*([\d,]+)\s*bytes/im)?.[1]);
  }

  return stats;
}

function parseConnection(raw: string): DryRunReport["connection"] {
  const line = raw.match(CONNECTION_RE)?.[1];
  if (!line) return {};

  const user = line.match(/\s-l\s+(\S+)/)?.[1];
  // The remote path is the last quoted argument of the ssh command.
  const quoted = Array.from(line.matchAll(/"([^"]+)"/g)).map((match) => match[1]);
  const remotePath = quoted.length ? quoted[quoted.length - 1].replace(/\\(.)/g, "$1") : undefined;

  // Host is the bare word right before `rsync --server`, after the -o options.
  const host =
    line.match(/(?:-l\s+\S+\s+)(\S+)\s+rsync\b/)?.[1] ?? line.match(/\s(\S+)\s+rsync\b/)?.[1];

  return { user, host, remotePath };
}

const ERROR_RE =
  /^(rsync:|rsync error:|@ERROR|ERROR:|ssh:|Permission denied|Host key verification failed|.*\bconnection unexpectedly closed\b.*)/i;
const WARNING_RE = /^(WARNING:|warning:|.*\bskipping\b.*|.*\bfailed to\b.*)/i;

function parseMessages(raw: string): DryRunMessage[] {
  const seen = new Set<string>();
  const messages: DryRunMessage[] = [];

  for (const line of raw.split("\n")) {
    const text = line.trim();
    if (!text || seen.has(text)) continue;
    if (ITEMIZE_RE.test(line) || DELETING_RE.test(text)) continue;

    if (ERROR_RE.test(text)) {
      seen.add(text);
      messages.push({ level: "error", text });
    } else if (WARNING_RE.test(text)) {
      seen.add(text);
      messages.push({ level: "warning", text });
    }
  }

  return messages;
}

/**
 * Walk the itemize-changes block. `>f` is an incoming transfer (`+++++++++`
 * attributes mean the file is brand new, anything else is an in-place update),
 * `.f` is a file already present and identical, `*deleting` is a local file
 * rsync would remove because it no longer exists on the server.
 */
function parseEntries(raw: string): DryRunEntry[] {
  const entries: DryRunEntry[] = [];
  const seen = new Set<string>();

  for (const line of raw.split("\n")) {
    const trimmed = line.trim();

    const deleting = trimmed.match(DELETING_RE);
    if (deleting) {
      const path = deleting[1].trim();
      const key = `delete:${path}`;
      if (path && !seen.has(key)) {
        seen.add(key);
        entries.push(makeEntry(path, path.endsWith("/") ? "dir" : "file", "delete"));
      }
      continue;
    }

    const match = line.match(ITEMIZE_RE);
    if (!match) continue;

    const [, typeChar, kindChar, attrs, rawPath] = match;
    const path = rawPath.trim();
    if (!path || path === "./") continue;

    const kind = entryKindOf(kindChar);
    let change: ChangeKind;
    if (typeChar === ">" || typeChar === "c" || typeChar === "<") {
      change = attrs.includes("+") ? "new" : "update";
    } else {
      change = "unchanged";
    }

    const key = `${change}:${path}`;
    if (seen.has(key)) continue;
    seen.add(key);
    entries.push(makeEntry(path, kind, change));
  }

  return entries;
}

const ENTRY_ORDER: Record<ChangeKind, number> = { delete: 0, new: 1, update: 2, unchanged: 3 };

function sortEntries(entries: DryRunEntry[]): DryRunEntry[] {
  return [...entries].sort((a, b) => {
    if (a.change !== b.change) return ENTRY_ORDER[a.change] - ENTRY_ORDER[b.change];
    return a.path.localeCompare(b.path, undefined, { numeric: true, sensitivity: "base" });
  });
}

function buildChecks(counts: DryRunCounts, messages: DryRunMessage[]): DryRunCheck[] {
  const checks: DryRunCheck[] = [];

  // Mirrors TransferService.perform_dry_run_rsync: the server must not have
  // fewer media files than the local copy.
  const comparable = counts.server > 0 && counts.local > 0;
  const serverOk = !comparable || counts.server >= counts.local;
  checks.push({
    label: "Server holds at least as many files as local",
    passed: serverOk,
    detail: comparable
      ? `${counts.server} on server vs ${counts.local} local`
      : "Not comparable — one side reported zero media files",
  });

  const deleteOk = counts.deleted <= counts.incoming;
  checks.push({
    label: "Deletions do not outnumber incoming files",
    passed: deleteOk,
    detail:
      counts.deleted === 0
        ? "Nothing would be deleted"
        : `${counts.deleted} to delete vs ${counts.incoming} incoming`,
  });

  const errors = messages.filter((message) => message.level === "error").length;
  checks.push({
    label: "rsync completed without errors",
    passed: errors === 0,
    detail: errors === 0 ? "No error output" : `${errors} error line(s) in rsync output`,
  });

  return checks;
}

function buildHeadline(counts: DryRunCounts, stats: RsyncStats): string {
  const parts: string[] = [];

  if (counts.incoming > 0) {
    const bytes = stats.transferredSize;
    parts.push(
      `transfer ${counts.incoming} file${counts.incoming === 1 ? "" : "s"}` +
        (bytes ? ` (${formatBytes(bytes)})` : "")
    );
  }
  if (counts.deleted > 0) {
    parts.push(`delete ${counts.deleted} local file${counts.deleted === 1 ? "" : "s"}`);
  }

  if (!parts.length) {
    return counts.server > 0
      ? `Already in sync — all ${counts.server} server file${counts.server === 1 ? "" : "s"} present locally`
      : "Nothing to transfer";
  }

  const summary = parts.join(" and ");
  const kept = counts.unchanged > 0 ? `, keeping ${counts.unchanged} already in sync` : "";
  return `This sync would ${summary}${kept}`;
}

/**
 * Build a display-ready report from whatever the dry-run endpoint returned.
 * Never throws — an unusable payload comes back as `ok: false`.
 */
export function parseDryRun(payload: unknown): DryRunReport {
  const empty: DryRunReport = {
    ok: false,
    completed: false,
    safeToSync: false,
    reason: "No dry-run output available",
    headline: "No dry-run output available",
    counts: { server: 0, local: 0, incoming: 0, deleted: 0, unchanged: 0 },
    entries: [],
    stats: {},
    connection: {},
    messages: [],
    checks: [],
    raw: "",
    json: payload ?? null,
  };

  const data = coercePayload(payload);
  if (!data) return empty;

  const raw = typeof data.raw_output === "string" ? data.raw_output : "";
  const parsedEntries = raw ? parseEntries(raw) : [];
  const stats = raw ? parseStats(raw) : {};
  const messages = raw ? parseMessages(raw) : [];

  // The JSON lists are authoritative (they are what the safety checks ran on);
  // fold in anything only the raw output knows about.
  const incomingFiles = toStringList(data.incoming_files);
  const deletedFiles = toStringList(data.deleted_files);
  const known = new Set(parsedEntries.map((entry) => `${entry.change}:${entry.path}`));

  for (const path of incomingFiles) {
    const clean = path.replace(/^\.\//, "");
    if (!known.has(`new:${clean}`) && !known.has(`update:${clean}`)) {
      parsedEntries.push(makeEntry(clean, "file", "new"));
    }
  }
  for (const path of deletedFiles) {
    const clean = path.replace(/^\.\//, "");
    if (!known.has(`delete:${clean}`)) {
      parsedEntries.push(makeEntry(clean, "file", "delete"));
    }
  }

  const entries = sortEntries(parsedEntries);
  const mediaEntries = entries.filter((entry) => entry.isMedia);
  const derivedIncoming = mediaEntries.filter(
    (entry) => entry.change === "new" || entry.change === "update"
  ).length;
  const derivedDeleted = mediaEntries.filter((entry) => entry.change === "delete").length;
  const derivedServer = mediaEntries.filter((entry) => entry.change !== "delete").length;

  const counts: DryRunCounts = {
    server: data.server_file_count !== undefined ? toCount(data.server_file_count) : derivedServer,
    local: toCount(data.local_file_count),
    incoming: data.incoming_count !== undefined ? toCount(data.incoming_count) : derivedIncoming,
    deleted: data.deleted_count !== undefined ? toCount(data.deleted_count) : derivedDeleted,
    unchanged: 0,
  };
  counts.unchanged = Math.max(0, counts.server - counts.incoming);

  const safeToSync = data.safe_to_sync === true;
  const reason =
    typeof data.reason === "string" && data.reason.trim()
      ? data.reason.trim()
      : safeToSync
        ? "All safety checks passed"
        : "No reason provided";

  // Without raw output and without a single counted file, rsync never got far
  // enough to say anything — the zeroes below would be lies dressed as facts.
  const completed =
    raw.length > 0 ||
    entries.length > 0 ||
    counts.server > 0 ||
    counts.local > 0 ||
    counts.incoming > 0 ||
    counts.deleted > 0;

  return {
    ok: true,
    completed,
    safeToSync,
    reason,
    headline: completed ? buildHeadline(counts, stats) : "Validation did not complete",
    counts,
    entries,
    stats,
    connection: raw ? parseConnection(raw) : {},
    messages,
    checks: completed ? buildChecks(counts, messages) : [],
    raw,
    json: coerceJsonView(payload, data),
  };
}

function coerceJsonView(payload: unknown, data: Record<string, unknown>): unknown {
  return typeof payload === "string" ? data : (payload ?? data);
}

/** Byte formatter that keeps small values readable (rsync reports exact bytes). */
export function formatBytes(bytes?: number): string {
  if (bytes === undefined || !Number.isFinite(bytes)) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(
    units.length - 1,
    Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024))
  );
  const value = bytes / 1024 ** exponent;
  const digits = exponent === 0 ? 0 : value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[exponent]}`;
}

export function formatNumber(value?: number): string {
  if (value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString();
}

export function formatDuration(seconds?: number): string {
  if (seconds === undefined || !Number.isFinite(seconds)) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  return `${seconds.toFixed(2)} s`;
}
