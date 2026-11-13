import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { jumpToQuoted, markQuotes, ownWords } from "../src/lib/jump";

/** A message list as the page draws it: rows with a key, each with the words in `.md` (a quote is a blockquote). */
function list(rows: { key: string; html: string }[]): HTMLElement {
  const root = document.createElement("div");
  root.className = "messages";
  root.innerHTML = rows.map((row) => `<div class="msg" data-row="${row.key}"><div class="md">${row.html}</div></div>`).join("");
  document.body.appendChild(root);
  // jsdom has no layout: give the list what scrolling needs, and let a scroll be seen rather than done.
  (root as unknown as { scrollTo: (o: ScrollToOptions) => void }).scrollTo = (o) => (root.dataset.scrolled = String(o.top));
  root.querySelectorAll<HTMLElement>(".msg").forEach((row) => (row.scrollIntoView = () => (root.dataset.intoView = "1")));
  return root;
}

const quoteIn = (root: HTMLElement, key: string, at = 0): HTMLElement =>
  root.querySelector(`[data-row="${key}"]`)!.querySelectorAll<HTMLElement>("blockquote")[at]!;

test("a message's own words leave out what it quoted, and a quote's own words leave out the quote inside it", () => {
  const root = list([{ key: "m", html: "<p>mine</p><blockquote><p>outer</p><blockquote><p>inner</p></blockquote></blockquote>" }]);
  assert.equal(ownWords(root.querySelector(".md")!).trim(), "mine");
  assert.equal(ownWords(quoteIn(root, "m")).trim(), "outer");
  root.remove();
});

test("a quote of a quote is found: its words are compared the way the source's are, both without nested quotes", () => {
  const root = list([
    { key: "a", html: "<p>tax comes first</p>" },
    { key: "b", html: "<p>agreed</p><blockquote><p>tax comes first</p></blockquote>" },
    { key: "c", html: "<p>why?</p><blockquote><p>agreed</p><blockquote><p>tax comes first</p></blockquote></blockquote>" },
  ]);

  // c quotes b (which itself quoted a): the outer quote's own words are "agreed", said by b and not by a.
  assert.equal(jumpToQuoted(quoteIn(root, "c")), true);
  assert.equal(root.querySelector(".jumped")?.getAttribute("data-row"), "b");
  // The inner quote is a's words.
  assert.equal(jumpToQuoted(quoteIn(root, "c", 1)), true);
  assert.equal(root.querySelector(".jumped")?.getAttribute("data-row"), "a", "one message is lit at a time");
  root.remove();
});

test("a quote whose words nobody said, or that is too short to point, is not found and lights nothing", () => {
  const root = list([
    { key: "a", html: "<p>the build is broken</p>" },
    { key: "b", html: "<p>reply</p><blockquote><p>words nobody said</p></blockquote><blockquote><p>ok</p></blockquote>" },
  ]);

  assert.equal(jumpToQuoted(quoteIn(root, "b", 0)), false);
  assert.equal(jumpToQuoted(quoteIn(root, "b", 1)), false);
  assert.equal(root.querySelector(".jumped"), null);
  root.remove();
});

test("only the list is scrolled to the source, not every ancestor", () => {
  const root = list([
    { key: "a", html: "<p>tax comes first</p>" },
    { key: "b", html: "<p>reply</p><blockquote><p>tax comes first</p></blockquote>" },
  ]);

  assert.equal(jumpToQuoted(quoteIn(root, "b")), true);
  assert.notEqual(root.dataset.scrolled, undefined, "the list was scrolled");
  assert.equal(root.dataset.intoView, undefined, "scrollIntoView, which moves outer scrollers too, was not used");
  root.remove();
});

// -- naming a quote for a screen reader ---------------------------------------------------------


test("each quote is named by what it points at, so two quotes on a page do not read the same", () => {
  const root = list([
    { key: "a", html: "<blockquote><p>tax comes first</p></blockquote><blockquote><p>cart.py:11 is wrong</p></blockquote>" },
  ]);

  assert.equal(markQuotes(root, "Go to the quoted message"), 2);
  const [one, two] = [quoteIn(root, "a", 0), quoteIn(root, "a", 1)];
  assert.equal(one!.getAttribute("role"), "button");
  assert.equal(one!.getAttribute("tabindex"), "0");
  assert.equal(one!.getAttribute("aria-label"), "Go to the quoted message: tax comes first");
  assert.equal(two!.getAttribute("aria-label"), "Go to the quoted message: cart.py:11 is wrong");
  root.remove();
});

test("a long quote is named by its opening words, and a quote inside a quote is not read into the outer name", () => {
  const long = "word ".repeat(60).trim();
  const root = list([{ key: "a", html: `<blockquote><p>${long}</p></blockquote><blockquote><p>outer</p><blockquote><p>inner</p></blockquote></blockquote>` }]);

  markQuotes(root, "Go");
  const label = quoteIn(root, "a", 0).getAttribute("aria-label")!;
  assert.ok(label.length < 100 && label.endsWith("…"), label);
  assert.equal(quoteIn(root, "a", 1).getAttribute("aria-label"), "Go: outer");
  root.remove();
});

test("a quote that holds a link or other focusable content stays a plain quote, readable and with its link reachable", () => {
  const root = list([
    { key: "a", html: '<blockquote><p>see <a href="https://example.com">the page</a></p></blockquote><blockquote><p>plain</p></blockquote>' },
  ]);

  assert.equal(markQuotes(root, "Go"), 1, "only the quote with no link became a control");
  const withLink = quoteIn(root, "a", 0);
  assert.equal(withLink.getAttribute("role"), null);
  assert.equal(withLink.getAttribute("tabindex"), null);
  assert.equal(withLink.getAttribute("aria-label"), null);
  assert.equal(quoteIn(root, "a", 1).getAttribute("role"), "button");
  root.remove();
});
