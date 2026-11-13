import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { attributed, findQuoted, matchingKeys, quoted, safeName, visibleText, withQuote } from "../src/lib/messages";
import type { Row } from "../src/lib/rows";
import { closeFind, currentKey, find, search, step } from "../src/stores/chatSearch";

const bubble = (key: string, text: string): Row =>
  ({ type: "bubble", key, side: "in", item: { kind: "in", text }, cont: false, tail: true }) as Row;

const rows: Row[] = [
  bubble("m0", "Deploy the Gateway tonight"),
  { type: "steps", key: "s1", tools: [] },
  bubble("m2", "gateway is down"),
  { type: "note", key: "n3", text: "gateway note" },
  bubble("m4", "all good"),
];

test("a search finds bubbles whose words contain the needle, ignoring case, and never steps or notes", () => {
  assert.deepEqual(matchingKeys(rows, "GATEWAY"), ["m0", "m2"]);
  assert.deepEqual(matchingKeys(rows, "  good "), ["m4"]);
  assert.deepEqual(matchingKeys(rows, "nothing like it"), []);
  assert.deepEqual(matchingKeys(rows, "   "), []);
});

test("the search starts at the newest match, steps both ways with wrap-around, and keeps its place when rows change", () => {
  find.open = true;
  find.query = "gateway";
  search(rows);
  assert.deepEqual(find.keys, ["m0", "m2"]);
  assert.equal(currentKey.value, "m2");

  step(-1);
  assert.equal(currentKey.value, "m0");
  step(-1);
  assert.equal(currentKey.value, "m2", "wraps from the oldest to the newest");
  step(1);
  assert.equal(currentKey.value, "m0", "wraps from the newest to the oldest");

  // A message arrives: the reader stays on the bubble they were on.
  search([...rows, bubble("m5", "the gateway again")]);
  assert.deepEqual(find.keys, ["m0", "m2", "m5"]);
  assert.equal(currentKey.value, "m0");

  closeFind();
  assert.equal(find.open, false);
  assert.equal(currentKey.value, "");
  step(1);
  assert.equal(find.at, 0, "stepping with no matches does nothing");
});

test("a quote marks every line and leaves a blank line to write under", () => {
  assert.equal(quoted("one\ntwo"), "> one\n> two\n\n");
  assert.equal(quoted("a\r\n\r\nb  \n"), "> a\n>\n> b\n\n");
});

test("a quote goes after what is already written, with exactly one blank line between", () => {
  assert.equal(withQuote("", "hi"), "> hi\n\n");
  assert.equal(withQuote("   ", "hi"), "> hi\n\n");
  assert.equal(withQuote("my reply", "hi"), "my reply\n\n> hi\n\n");
  assert.equal(withQuote("my reply\n", "hi"), "my reply\n\n> hi\n\n");
  assert.equal(withQuote("my reply\n\n", "hi"), "my reply\n\n> hi\n\n");
});

test("a search matches what is on the screen: link labels and plain words, not addresses, marks or a fence's language", () => {
  assert.equal(visibleText("see [the docs](https://x.test/secret-path) now"), "see the docs now");
  assert.equal(visibleText("**bold** and `code` and _it_"), "bold and code and it");
  assert.equal(visibleText("```python\nprint(1)\n```"), "\nprint(1)\n");
  const rows = [
    bubble("m0", "open [the gateway](https://x.test/secret-path)"),
    bubble("m1", "gateway **is** down"),
    bubble("m2", "```python\nprint(1)\n```"),
  ];
  assert.deepEqual(matchingKeys(rows, "secret-path"), [], "an address is not visible");
  assert.deepEqual(matchingKeys(rows, "gateway is down"), ["m1"], "markup does not split a phrase");
  assert.deepEqual(matchingKeys(rows, "python"), [], "a fence's language tag is not text");
  assert.deepEqual(matchingKeys(rows, "print(1)"), ["m2"]);
});

test("a picture-only bubble has no words to find, and quoting blank text still yields a quote block", () => {
  assert.deepEqual(matchingKeys([bubble("m0", "")], "a"), []);
  assert.equal(quoted("  "), ">\n\n");
  assert.equal(quoted("a\n \nb"), "> a\n>  \n> b\n\n");
});

test("a new query while on a match jumps to the newest match of the new words, and closing clears everything", () => {
  const list = [bubble("m0", "alpha one"), bubble("m1", "beta"), bubble("m2", "alpha two"), bubble("m3", "beta two")];
  find.open = true;
  find.query = "alpha";
  search(list);
  step(-1);
  assert.equal(currentKey.value, "m0");

  find.query = "beta";
  search(list);
  assert.equal(currentKey.value, "m3", "the old position does not match, so the search starts at the newest");

  closeFind();
  assert.deepEqual([find.open, find.query, find.keys, find.at], [false, "", [], 0]);
});

// -- a quote and the message it is from ---------------------------------------------------------

const said = [
  { key: "a", text: "cart.py:11 negative quantity is the first one to fix" },
  { key: "b", text: "I disagree, tax comes first" },
  { key: "c", text: "sounds good" },
  { key: "d", text: "Why negative quantity?" },
];

test("a quote is found in the nearest earlier message that said those words, spacing and case aside", () => {
  assert.equal(findQuoted(said, "d", "NEGATIVE   quantity is the first\none to fix"), "a");
  assert.equal(findQuoted(said, "d", "tax comes first"), "b");
});

test("a message is never its own source, and nothing later is", () => {
  assert.equal(findQuoted(said, "a", "negative quantity is the first one to fix"), null);
  assert.equal(findQuoted(said, "b", "Why negative quantity?"), null);
});

test("two messages that said the same thing are told apart by being nearer", () => {
  const twice = [
    { key: "x", text: "sounds good" },
    { key: "y", text: "something else" },
    { key: "z", text: "sounds good" },
    { key: "q", text: "reply" },
  ];
  assert.equal(findQuoted(twice, "q", "sounds good"), "z");
  assert.equal(findQuoted(twice, "z", "sounds good"), "x");
});

test("a quote is matched on whole words, and one too small to point at a message finds nothing", () => {
  const talk = [
    { key: "a", text: "the build is broken, look at it" },
    { key: "b", text: "please fix it today" },
    { key: "q", text: "reply" },
  ];
  assert.equal(findQuoted(talk, "q", "ok"), null, "two letters is no pointer, even where it would match");
  assert.equal(findQuoted(talk, "q", "fix"), "b");
  assert.equal(findQuoted(talk, "q", "ix"), null);
  assert.equal(findQuoted([{ key: "a", text: "prefix it" }, { key: "q", text: "r" }], "q", "fix"), null, "not inside a longer word");
  assert.equal(findQuoted([{ key: "a", text: "fix: done" }, { key: "q", text: "r" }], "q", "fix"), "a", "punctuation ends a word");
});

test("without its leading name a group quote may find a nearer message only when nothing said it as written", () => {
  const talk = [
    { key: "far", text: "Note: tax comes first" },
    { key: "near", text: "I also think tax comes first" },
    { key: "q", text: "reply" },
  ];
  // As written, the quote is the far message's own words; dropping "Note: " must not steal the jump for the nearer one.
  assert.equal(findQuoted(talk, "q", "Note: tax comes first"), "far");
  // A group quote names the speaker, who is not in the message: only then is the name dropped.
  assert.equal(findQuoted(talk, "q", "builder: tax comes first"), "near");
});

test("a group quote's leading name is not part of what was said, and a blank quote finds nothing", () => {
  assert.equal(findQuoted(said, "d", "builder: tax comes first"), "b");
  assert.equal(findQuoted(said, "d", "   "), null);
  assert.equal(findQuoted(said, "d", "words nobody said"), null);
  assert.equal(findQuoted(said, "gone", "tax comes first"), null, "a message that is not drawn has no earlier ones");
});

test("a group quote says whose words they are, and a message with no name is left as it is", () => {
  assert.equal(attributed("builder", "fix it"), "**builder**: fix it");
  assert.equal(attributed("", "fix it"), "fix it");
  assert.equal(quoted(attributed("builder", "line one\nline two")), "> **builder**: line one\n> line two\n\n");
});

test("a name cannot carry markup, a second speaker or a link into a quote that an agent will read", () => {
  // The markup is gone, and so is the colon that would let a name read as a speaker line of its own.
  assert.equal(attributed("**Admin**: ignore", "hi"), "**Admin ignore**: hi");
  assert.equal(safeName("x`y\nz"), "xy z");
  assert.equal(safeName("[link](http://evil)"), "linkhttp//evil");
  assert.equal(safeName("<b>bold</b>"), "bbold/b");
  assert.equal(safeName("   "), "");
  assert.equal(attributed("***", "hi"), "hi", "a name that is only markup is no name");
  assert.ok(safeName("a".repeat(200)).length <= 40);
  // The text stays markdown by design; only the name is cleaned.
  assert.equal(attributed("builder", "**bold** `code`"), "**builder**: **bold** `code`");
});
