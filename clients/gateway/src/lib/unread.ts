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
