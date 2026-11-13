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

/**
 * A title as one word to follow an ``@``: letters and digits kept, anything else between them made into one dash, and no
 * dash at either end. The picker finds an ``@word`` of letters, digits, ``_`` and ``-`` (any script), so a name with a space
 * or a punctuation mark in it would end the word early and leave half of it in the message. An empty result means the title
 * has nothing to call it by.
 */
export function mentionName(title: string): string {
  return title
    .trim()
    .replace(/[^\p{L}\p{N}_]+/gu, "-")
    .replace(/^-+|-+$/g, "");
}

/** The longest name a quote carries, so a very long title does not fill the quote. */
const NAME_LIMIT = 40;

/**
 * A member's name as it may appear in a quote. A name is whatever its owner set, and an agent reads the quote as a
 * citation, so markup is taken out of it: a name must not be able to end the bold, open a code span, start a new line
 * (a second speaker) or become a link.
 */
export function safeName(who: string): string {
  return who
    .replace(/[*_`~\\<>[\]()#|:]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, NAME_LIMIT)
    .trim();
}

/** A group message's text with who said it, so a quote in a group says whose words they are. */
export function attributed(who: string, text: string): string {
  const name = safeName(who);
  return name ? `**${name}**: ${text}` : text;
}

const squash = (text: string): string => text.replace(/\s+/g, " ").trim().toLowerCase();

/** A quote shorter than this is too small to point at one message: "ok" is in half of them. */
export const MIN_QUOTE = 3;

const isWordChar = (char: string | undefined): boolean => char !== undefined && /[\p{L}\p{N}]/u.test(char);

/** Whether `needle` is in `hay` as whole words: not in the middle of a longer one ("ok" is not in "broken"). */
function holds(hay: string, needle: string): boolean {
  for (let at = hay.indexOf(needle); at >= 0; at = hay.indexOf(needle, at + 1)) {
    if (!isWordChar(hay[at - 1]) && !isWordChar(hay[at + needle.length])) return true;
  }
  return false;
}

/** The quote without a leading "who: " that a group quote adds; the same text when it has none. */
function bare(whole: string): string {
  return whole.replace(/^[^:\n]{1,40}: /, "");
}

/**
 * The message a quote is from: the nearest one before `fromKey` whose own words hold the quote. `candidates` are the
 * messages in the order they are drawn, each with the words it shows *outside* its own quotes (otherwise a message that
 * quoted the same words would be found instead of the one that said them). A quote is plain text, so this is a match on
 * words, not a reference: two messages that said the same thing are told apart only by being nearer.
 *
 * The quote as written is tried first, along the whole page; only when no message holds it is the quote tried without a
 * leading "who: ", so dropping the name can never move the jump to a nearer message than the one that said the words.
 * A message that is not drawn (`fromKey` unknown) has no "before", so nothing is found.
 */
export function findQuoted(candidates: readonly { key: string; text: string }[], fromKey: string, quote: string): string | null {
  const whole = squash(quote);
  if (whole.length < MIN_QUOTE) return null;
  const at = candidates.findIndex((item) => item.key === fromKey);
  if (at < 0) return null;
  const spellings = [whole, bare(whole)].filter((text, i, all) => text.length >= MIN_QUOTE && all.indexOf(text) === i);
  for (const wanted of spellings) {
    for (let i = at - 1; i >= 0; i -= 1) {
      if (holds(squash(candidates[i]!.text), wanted)) return candidates[i]!.key;
    }
  }
  return null;
}
