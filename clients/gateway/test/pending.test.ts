import assert from "node:assert/strict";
import { test } from "node:test";
import { held, pend, settle } from "../src/lib/pending";
import type { ChatItem, Pending } from "../src/types";

const out = (text: string): ChatItem => ({ kind: "out", text });

test("a pending message is dropped once the conversation holds it, and not before", () => {
  const first = pend(1, "run", [], [], 0);

  assert.equal(settle([first], []).length, 1);
  assert.equal(settle([first], [out("run")]).length, 0);
});

test("two equal messages sent in a row are each shown once", () => {
  const a = pend(1, "ok", [], [], 0);
  const b = pend(2, "ok", [], [a], 0);

  assert.equal(b.target, 2);
  assert.deepEqual(settle([a, b], [out("ok")]).map((p) => p.key), [2]);
  assert.equal(settle([a, b], [out("ok"), out("ok")]).length, 0);
});

test("an earlier identical message already in the conversation does not hide a new one", () => {
  const items = [out("ok")];
  const fresh = pend(3, "ok", items, [], 0);

  assert.equal(held(items, "ok"), 1);
  assert.equal(settle([fresh], items).length, 1);
});

test("a failed message stays until the person removes it", () => {
  const failed: Pending = { ...pend(1, "x", [], [], 0), state: "failed" };

  assert.equal(settle([failed], [out("x")]).length, 1);
});

test("a message run as the session's own prompt is stored as the person's and settles the pending one", () => {
  const sent = pend(1, "run", [], [], 0);

  assert.equal(settle([sent], [{ kind: "user", text: "run" }]).length, 0);
});
