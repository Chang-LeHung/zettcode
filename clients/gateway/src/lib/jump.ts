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
