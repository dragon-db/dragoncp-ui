/**
 * Comparing the release this tab is running against the one the server is.
 *
 * Kept as a plain function rather than living inside the hook so it can be
 * exercised on its own — the interesting part is not the fetching, it is the
 * decision about when to say nothing.
 */

/** A version we cannot act on: unset, or the marker for an unreadable VERSION file. */
function isUnknown(version: string | null | undefined): boolean {
  return !version || version === "unknown";
}

/**
 * Whether the running tab is behind the server.
 *
 * False whenever either side is unknown. Two cases produce that, and both must
 * stay quiet rather than guess:
 *
 *   * a backend too old to report its version at all, which is every server
 *     that has not been restarted since the field was added,
 *   * `unknown`, meaning the VERSION file could not be read — at build time for
 *     the bundle, or at startup for the server.
 *
 * Treating either as a mismatch would put a permanent "please reload" banner in
 * front of an operator whose install is fine, and a banner that is always there
 * is one nobody reads when it finally matters.
 */
export function isOutdated(running: string, available: string | null | undefined): boolean {
  if (isUnknown(running) || isUnknown(available)) return false;
  return running !== available;
}
