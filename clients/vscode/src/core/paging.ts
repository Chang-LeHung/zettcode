/**
 * Showing a long conversation a page at a time. Reading a session back makes a request out of every message the person
 * sent, and a long one has hundreds; the view starts with the latest and fetches older ones when asked.
 */

import type { Turn } from "./state.js";

/** How many requests a page holds. */
export const PAGE_REQUESTS = 20;

/** A request is something the person asked; a compaction row, an announcement or a side question is not one. */
function isRequest(turn: Turn): boolean {
  return !turn.aside;
}

/**
 * Where the page that ends at `end` begins: the index of the first turn to show, so that `limit` requests (and
 * whatever sits between them) are on it. Rows before the first request go with the page when there is no request
 * left before them, so nothing is left behind that the reader could never ask for.
 */
export function pageStart(turns: Turn[], end = turns.length, limit = PAGE_REQUESTS): number {
  let seen = 0;
  for (let index = end - 1; index >= 0; index -= 1) {
    const turn = turns[index];
    if (turn !== undefined && isRequest(turn)) {
      seen += 1;
      if (seen === limit) {
        return turns.slice(0, index).some(isRequest) ? index : 0;
      }
    }
  }
  return 0;
}

/** How many requests lie before the index, which is what "show earlier" offers. */
export function requestsBefore(turns: Turn[], index: number): number {
  return turns.slice(0, index).filter(isRequest).length;
}
