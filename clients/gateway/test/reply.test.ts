import assert from "node:assert/strict";
import { test } from "node:test";
import "./dom-setup";
import { clearReply, replies, setReply, withReply } from "../src/stores/reply";

test("a reply is sent as a quote, with who said it, ahead of what was typed", () => {
  setReply("#team", "builder", "ship it\nnow");
  assert.equal(withReply("#team", "agreed"), "> **builder**: ship it\n> now\n\nagreed");
  clearReply("#team");
  assert.equal(withReply("#team", "agreed"), "agreed");
});

test("a reply to your own message carries no name, and each thread keeps its own", () => {
  setReply("a", "", "my words here");
  setReply("b", "bob", "other words");
  assert.equal(withReply("a", "x"), "> my words here\n\nx");
  assert.equal(withReply("b", "y"), "> **bob**: other words\n\ny");
  clearReply("a");
  assert.ok(replies.b);
  assert.equal(replies.a, undefined);
  clearReply("b");
});
