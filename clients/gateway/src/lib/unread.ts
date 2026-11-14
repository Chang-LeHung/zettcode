// The rules for the unread marks, kept apart from the components so they can be tested: what a badge says, and when
// what has arrived counts as seen.

/** The most a badge shows; more reads as `99+`, so a session that talks all day does not make the list unreadable. */
export const BADGE_LIMIT = 99;

/** The text of a badge for `count` unread messages, or an empty string when there are none. */
export function badge(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return "";
  return count > BADGE_LIMIT ? `${BADGE_LIMIT}+` : String(Math.floor(count));
}

/**
 * Whether the open conversation's new messages are seen now: the page is in front, and the reader is at the bottom of
 * the conversation. Above the bottom they are not, as in any messenger; they are read when the reader comes down.
 */
export function seenNow(state: { hidden: boolean; atBottom: boolean; unread: number }): boolean {
  return state.unread > 0 && !state.hidden && state.atBottom;
}

/** How many conversations have something unread: what the tab shows, because a count of messages is dominated by one chatty session. */
export function unreadChats(threads: readonly { unread: number }[]): number {
  return threads.reduce((count, thread) => count + (thread.unread > 0 ? 1 : 0), 0);
}

/**
 * The row the unread line goes above: the first drawn from the item the unread stretch begins at.
 *
 * Rows are keyed `m<item>`, `s<item>` and `n<item>` for a bubble, a run of steps and a note, so the item a row was
 * drawn from is in its key. A message this page has sent and the conversation has not stored yet is keyed `p<n>` and
 * is never the place: it sits below everything the session said.
 */
export function lineRow<R extends { key: string }>(rows: readonly R[], from: number | null): R | undefined {
  if (from === null) return undefined;
  return rows.find((row) => {
    const kind = row.key.charAt(0);
    if (kind !== "m" && kind !== "s" && kind !== "n") return false;
    return Number(row.key.slice(1)) >= from;
  });
}
