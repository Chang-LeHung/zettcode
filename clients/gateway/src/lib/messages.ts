// What a reader does with a message beyond reading it: find it again, quote it. Kept apart from the components so the
// rules can be tested.

import type { Row } from "./rows";

/** The keys of the bubbles whose text holds `needle` (case does not matter), oldest first. A blank needle finds nothing. */
export function matchingKeys(rows: readonly Row[], needle: string): string[] {
  const wanted = needle.trim().toLowerCase();
  if (!wanted) return [];
  const found: string[] = [];
  for (const row of rows) {
    if (row.type === "bubble" && row.item.text.toLowerCase().includes(wanted)) found.push(row.key);
  }
  return found;
}

/** `text` as a markdown quote, ready to be written under: every line marked, and a blank line after it. */
export function quoted(text: string): string {
  const lines = text.replace(/\r\n?/g, "\n").trimEnd().split("\n");
  return `${lines.map((line) => (line ? `> ${line}` : ">")).join("\n")}\n\n`;
}

/** A draft with a quote added to the end of what is already written, a blank line between the two. */
export function withQuote(draft: string, text: string): string {
  if (!draft.trim()) return quoted(text);
  const gap = draft.endsWith("\n\n") ? "" : draft.endsWith("\n") ? "\n" : "\n\n";
  return `${draft}${gap}${quoted(text)}`;
}
