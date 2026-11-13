// Jump from a quote to the message it was taken from. The quote is plain text, so the source is found by its words among
// the messages drawn on the page (see findQuoted); one that is not loaded, or was never said here, is not found.

import { findQuoted } from "./messages";

/** The words a message shows outside its own quotes: what it said itself, not what it repeated. */
function ownWords(row: HTMLElement): string {
  const body = row.querySelector(".md, .plain");
  if (!body) return "";
  const copy = body.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("blockquote").forEach((quote) => quote.remove());
  return copy.textContent ?? "";
}

/** Scroll to the message `quote` is from, starting from the message `origin` is in; say whether one was found. */
export function jumpToQuoted(origin: HTMLElement, quote: string): boolean {
  const list = origin.closest(".messages");
  const here = origin.closest<HTMLElement>("[data-row]")?.dataset.row ?? "";
  if (!list) return false;
  const rows = [...list.querySelectorAll<HTMLElement>("[data-row]")];
  const key = findQuoted(
    rows.map((row) => ({ key: row.dataset.row ?? "", text: ownWords(row) })),
    here,
    quote,
  );
  const target = rows.find((row) => row.dataset.row === key);
  if (!target) return false;
  target.scrollIntoView({ block: "center", behavior: "smooth" });
  // Restart the highlight if the reader jumps to the same message twice in a row.
  target.classList.remove("jumped");
  void target.offsetWidth;
  target.classList.add("jumped");
  setTimeout(() => target.classList.remove("jumped"), 1600);
  return true;
}
