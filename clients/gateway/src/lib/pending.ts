// Messages sent from this page that the stored conversation does not show yet.
//
// A message is sent and answered with who took it; it appears in the session's own conversation a moment later, when
// the session starts its turn (at once if it was idle, much later if it was queued). Until then the page draws it
// itself, and it must stop drawing it the moment the conversation holds it, or every message would show twice.
//
// The rule: a pending message carries a *target*, the number of identical messages the conversation must hold before
// it counts as shown. That is the number held when it was sent, plus the identical ones still waiting ahead of it,
// plus itself. It does not depend on order or on timing, so two equal messages sent in a row are each shown once.

import type { ChatItem, Pending, Picture } from "../types";

/** How many messages with exactly this text from the person the conversation holds (sent from here, or run as a prompt there). */
export function held(items: readonly ChatItem[], text: string): number {
  let count = 0;
  for (const item of items) if ((item.kind === "out" || item.kind === "user") && item.text === text) count += 1;
  return count;
}

/** Make the pending record for a message about to be sent. */
export function pend(
  key: number,
  text: string,
  items: readonly ChatItem[],
  waiting: readonly Pending[],
  at: number,
  pictures: readonly Picture[] = [],
): Pending {
  const ahead = waiting.filter((other) => other.text === text && other.state !== "failed").length;
  const entry: Pending = { key, text, target: held(items, text) + ahead + 1, state: "sending", at };
  if (pictures.length) entry.pictures = [...pictures];
  return entry;
}

/**
 * The stored message that stands in for a pending one keeps the pending one's row key, so that the bubble is the same
 * element before and after the conversation holds it: no remount, and so no flash. A claim is `text + target`, which is
 * the occurrence of that text the stored conversation reaches when it shows the pending message.
 */
export function claimKey(text: string, occurrence: number): string {
  return `${occurrence}\u0000${text}`;
}

/** Note, for each pending message the conversation now holds, which row key the stored copy takes over. */
export function claim(waiting: readonly Pending[], items: readonly ChatItem[], into: Map<string, number>): void {
  for (const p of waiting) {
    if (p.state !== "failed" && held(items, p.text) >= p.target) into.set(claimKey(p.text, p.target), p.key);
  }
}

/** Drop the pending messages the conversation now holds. A failed one stays: it was never sent. */
export function settle(waiting: readonly Pending[], items: readonly ChatItem[]): Pending[] {
  const counts = new Map<string, number>();
  return waiting.filter((p) => {
    if (p.state === "failed") return true;
    let have = counts.get(p.text);
    if (have === undefined) {
      have = held(items, p.text);
      counts.set(p.text, have);
    }
    return have < p.target;
  });
}
