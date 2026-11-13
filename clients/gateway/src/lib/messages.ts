// What a reader does with a message beyond reading it: find it again, quote it. Kept apart from the components so the
// rules can be tested.

import type { Row } from "./rows";

/**
 * The words a reader sees in a message's markdown source: a link is its label, emphasis and code marks and heading or quote
 * marks are gone, and a fence's own lines (the ``` and its language) are not text. It is for matching, not for drawing, so it
 * need not be exact; it only has to stop a search from hitting what is not on the screen. Known gaps: `_` is dropped
 * everywhere, so `snake_case` is found by its joined spelling, and a picture's alt text is kept though it is drawn as a picture.
 */
export function visibleText(markdown: string): string {
  return markdown
    .replace(/^\s*```.*$/gm, "")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}(#{1,6}|>)\s?/gm, "")
    .replace(/(\*\*|__|~~|[*_`])/g, "");
}

/** The keys of the bubbles whose visible words hold `needle` (case does not matter), oldest first. A blank needle finds nothing. */
export function matchingKeys(rows: readonly Row[], needle: string): string[] {
  const wanted = needle.trim().toLowerCase();
  if (!wanted) return [];
  const found: string[] = [];
  for (const row of rows) {
    if (row.type === "bubble" && visibleText(row.item.text).toLowerCase().includes(wanted)) found.push(row.key);
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

/** A group message's text with who said it, so a quote in a group says whose words they are. */
export function attributed(who: string, text: string): string {
  return who ? `**${who}**: ${text}` : text;
}

const squash = (text: string): string => text.replace(/\s+/g, " ").trim().toLowerCase();

/** The spellings of a quote to look for: as written, and without a leading "who: " that a group quote adds. */
function spellings(quote: string): string[] {
  const whole = squash(quote);
  const bare = whole.replace(/^[^:\n]{1,40}: /, "");
  return [...new Set([whole, bare])].filter((text) => text.length > 0);
}

/**
 * The message a quote is from: the nearest one before `fromKey` whose own words hold the quote. `candidates` are the
 * messages in the order they are drawn, each with the words it shows *outside* its own quotes (otherwise a message that
 * quoted the same words would be found instead of the one that said them). A quote is plain text, so this is a match on
 * words, not a reference: two messages that said the same thing are told apart only by being nearer.
 */
export function findQuoted(candidates: readonly { key: string; text: string }[], fromKey: string, quote: string): string | null {
  const wanted = spellings(quote);
  if (!wanted.length) return null;
  const at = candidates.findIndex((item) => item.key === fromKey);
  for (let i = (at < 0 ? candidates.length : at) - 1; i >= 0; i -= 1) {
    const words = squash(candidates[i]!.text);
    if (wanted.some((text) => words.includes(text))) return candidates[i]!.key;
  }
  return null;
}
