// Jump from a quote to the message it was taken from. The quote is plain text, so the source is found by its words among
// the messages drawn on the page (see findQuoted); one that is not loaded, or was never said here, is not found.

import { findQuoted } from "./messages";

/**
 * The words an element shows outside the quotes nested in it: what was said there, not what was repeated. One helper for
 * a message and for the quote that was clicked, so both sides of the comparison leave out the same things (a quote of a
 * quote is then its own words only, on either side).
 */
export function ownWords(element: Element): string {
  const copy = element.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("blockquote").forEach((quote) => quote.remove());
  return copy.textContent ?? "";
}

/** The words a message shows outside its own quotes. */
function wordsOfRow(row: HTMLElement): string {
  const body = row.querySelector(".md, .plain");
  return body ? ownWords(body) : "";
}

/** The most of a quote's words put into the name of its control. */
const NAME_WORDS = 80;

/**
 * Make each quote under `root` a control that jumps to its source: reachable by keyboard and named by what it points at.
 * A control's name replaces what is inside it for a screen reader, so the name carries the opening words of the quote
 * rather than one fixed phrase that would make every quote on the page read the same. A quote that holds a link or other
 * focusable content is left a plain quote, because that nesting is invalid and unreachable; its words and link are read
 * as they were, and a click on it still jumps. Returns how many quotes became controls.
 */
export function markQuotes(root: Element, label: string): number {
  let marked = 0;
  root.querySelectorAll("blockquote").forEach((quote) => {
    if (quote.querySelector("a, button, input, [tabindex]")) return;
    const words = ownWords(quote).replace(/\s+/g, " ").trim();
    const shown = words.length > NAME_WORDS ? `${words.slice(0, NAME_WORDS).trimEnd()}…` : words;
    quote.setAttribute("role", "button");
    quote.setAttribute("tabindex", "0");
    quote.setAttribute("aria-label", `${label}: ${shown}`);
    marked += 1;
  });
  return marked;
}

let fading: ReturnType<typeof setTimeout> | undefined;
let lit: HTMLElement | null = null;

/** Light a message up for a moment; one already lit is put out first, and the reflow restarts the animation. */
function highlight(target: HTMLElement): void {
  clearTimeout(fading);
  lit?.classList.remove("jumped");
  void target.offsetWidth;
  target.classList.add("jumped");
  lit = target;
  fading = setTimeout(() => {
    target.classList.remove("jumped");
    if (lit === target) lit = null;
  }, 1600);
}

/**
 * Scroll to the message a quote is from, starting from the quote that was clicked; say whether one was found.
 * Only the message list scrolls: `scrollIntoView` would also move every scrolling ancestor, which in the group view is
 * the page around it.
 */
export function jumpToQuoted(quote: HTMLElement): boolean {
  const list = quote.closest<HTMLElement>(".messages");
  const here = quote.closest<HTMLElement>("[data-row]")?.dataset.row ?? "";
  if (!list) return false;
  const rows = [...list.querySelectorAll<HTMLElement>("[data-row]")];
  const key = findQuoted(
    rows.map((row) => ({ key: row.dataset.row ?? "", text: wordsOfRow(row) })),
    here,
    ownWords(quote),
  );
  const target = rows.find((row) => row.dataset.row === key);
  if (!target) return false;
  const inside = target.getBoundingClientRect().top - list.getBoundingClientRect().top;
  list.scrollTo({ top: list.scrollTop + inside - (list.clientHeight - target.offsetHeight) / 2, behavior: "smooth" });
  highlight(target);
  return true;
}
