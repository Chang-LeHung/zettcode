// Messages sent from this page that the stored conversation does not show yet.
//
// A message is sent and answered with who took it; it appears in the session's own conversation a moment later, when
// the session starts its turn (at once if it was idle, much later if it was queued). Until then the page draws it
// itself, and it must stop drawing it the moment the conversation holds it, or every message would show twice.
//
// The rule: a pending message carries a *target*, the number of identical messages the conversation must hold before
// it counts as shown. That is the number held when it was sent, plus the identical ones still waiting ahead of it,
// plus itself. It does not depend on order or on timing, so two equal messages sent in a row are each shown once.

import type { ChatItem, Pending } from "../types";

/** How many messages with exactly this text from the person the conversation holds (sent from here, or run as a prompt there). */
export function held(items: readonly ChatItem[], text: string): number {
  let count = 0;
  for (const item of items) if ((item.kind === "out" || item.kind === "user") && item.text === text) count += 1;
  return count;
}

/** Make the pending record for a message about to be sent. */
export function pend(key: number, text: string, items: readonly ChatItem[], waiting: readonly Pending[], at: number): Pending {
  const ahead = waiting.filter((other) => other.text === text && other.state !== "failed").length;
  return { key, text, target: held(items, text) + ahead + 1, state: "sending", at };
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
