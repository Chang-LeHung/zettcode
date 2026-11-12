// Searching inside the open conversation: the words, which bubbles hold them, and which one the reader is looking at.
// The search covers what is loaded; opening it reads the whole conversation first, so it is not a search of the last page.

import { computed, reactive } from "vue";
import { matchingKeys } from "../lib/messages";
import type { Row } from "../lib/rows";
import { loadEarlier, chat } from "./chat";

export const find = reactive({
  open: false,
  query: "",
  /** The bubbles that hold the words, oldest first. */
  keys: [] as string[],
  /** Which of them the reader is on. */
  at: 0,
});

/** The bubble the reader is on, or an empty string. */
export const currentKey = computed(() => (find.open ? (find.keys[find.at] ?? "") : ""));

export function openFind(): void {
  find.open = true;
  // Only what is loaded can be searched: take the rest of the conversation before the words are typed.
  if (chat.truncated) void loadEarlier();
}

export function closeFind(): void {
  find.open = false;
  find.query = "";
  find.keys = [];
  find.at = 0;
}

/** Look for the words in these rows again, staying on the same bubble when it still matches. */
export function search(rows: readonly Row[]): void {
  const before = find.keys[find.at];
  find.keys = matchingKeys(rows, find.query);
  const kept = before ? find.keys.indexOf(before) : -1;
  // A new search starts at the newest match, which is where a reader looking for something just said begins.
  find.at = kept >= 0 ? kept : Math.max(0, find.keys.length - 1);
}

/** Move to a newer match (`1`) or an older one (`-1`), wrapping round at the ends. */
export function step(direction: 1 | -1): void {
  const count = find.keys.length;
  if (!count) return;
  find.at = (find.at + direction + count) % count;
}
