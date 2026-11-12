import "./dom-setup";
import assert from "node:assert/strict";
import { test } from "node:test";
import { matchingKeys, quoted, withQuote } from "../src/lib/messages";
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
