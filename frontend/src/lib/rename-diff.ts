/**
 * Filename diffing for rename results.
 *
 * Sonarr renames change a few tokens inside a long filename — a quality tag, a
 * release group, the episode title. Showing the two names as plain strings
 * makes the reader hunt for the difference; diffing them by token and colouring
 * only what moved turns it into a glance.
 *
 * Tokens keep their separators, so joining a side's tokens reproduces the
 * original filename exactly.
 */

export type DiffKind = "same" | "removed" | "added";

export interface DiffToken {
  text: string;
  kind: DiffKind;
}

export interface FilenameDiff {
  before: DiffToken[];
  after: DiffToken[];
  /** True when the two names are identical. */
  unchanged: boolean;
  /** Token counts, for a one-line summary. */
  removedCount: number;
  addedCount: number;
}

/** Split on filename punctuation, keeping the separators as their own tokens. */
function tokenize(value: string): string[] {
  return value.split(/([ ._\-[\]()]+)/).filter((token) => token.length > 0);
}

/**
 * Punctuation and spacing between the parts of a filename. These shift around
 * whenever a word changes, so they are counted and coloured as noise rather
 * than as edits.
 */
export const isSeparatorToken = (token: string) => /^[ ._\-[\]()]+$/.test(token);
const isSeparator = isSeparatorToken;

/**
 * Longest common subsequence over tokens. Filenames are short (tens of tokens),
 * so the straightforward O(n·m) table is the right trade for exact results.
 */
function lcsTable(a: string[], b: string[]): number[][] {
  const table: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0)
  );

  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] =
        a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  return table;
}

/** Merge neighbouring tokens of the same kind so the markup stays light. */
function collapse(tokens: DiffToken[]): DiffToken[] {
  const merged: DiffToken[] = [];
  for (const token of tokens) {
    const last = merged[merged.length - 1];
    if (last && last.kind === token.kind) last.text += token.text;
    else merged.push({ ...token });
  }
  return merged;
}

export function diffFilenames(before: string, after: string): FilenameDiff {
  const a = tokenize(before ?? "");
  const b = tokenize(after ?? "");

  if (!before || !after || before === after) {
    return {
      before: before ? [{ text: before, kind: "same" }] : [],
      after: after ? [{ text: after, kind: "same" }] : [],
      unchanged: Boolean(before) && before === after,
      removedCount: 0,
      addedCount: 0,
    };
  }

  const table = lcsTable(a, b);
  const beforeTokens: DiffToken[] = [];
  const afterTokens: DiffToken[] = [];
  let removedCount = 0;
  let addedCount = 0;

  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      beforeTokens.push({ text: a[i], kind: "same" });
      afterTokens.push({ text: b[j], kind: "same" });
      i += 1;
      j += 1;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      beforeTokens.push({ text: a[i], kind: "removed" });
      if (!isSeparator(a[i])) removedCount += 1;
      i += 1;
    } else {
      afterTokens.push({ text: b[j], kind: "added" });
      if (!isSeparator(b[j])) addedCount += 1;
      j += 1;
    }
  }
  for (; i < a.length; i += 1) {
    beforeTokens.push({ text: a[i], kind: "removed" });
    if (!isSeparator(a[i])) removedCount += 1;
  }
  for (; j < b.length; j += 1) {
    afterTokens.push({ text: b[j], kind: "added" });
    if (!isSeparator(b[j])) addedCount += 1;
  }

  return {
    before: collapse(beforeTokens),
    after: collapse(afterTokens),
    unchanged: false,
    removedCount,
    addedCount,
  };
}

/** `Show - S01E07 - Title [WEBDL-1080p].mkv` → `S01E07`, when present. */
export function episodeTagOf(filename?: string): string | undefined {
  const match = filename?.match(/\bS(\d{1,3})E(\d{1,4})(?:-?E?\d{1,4})?\b/i);
  return match ? match[0].toUpperCase() : undefined;
}
