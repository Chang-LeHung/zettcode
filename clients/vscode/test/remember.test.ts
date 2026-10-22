import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { readRemembered, remember, REMEMBERED_SESSIONS, wantedPermission } from "../src/core/remember.js";

const levels = ["deny", "ask", "safe", "full"];

test("a session gets back the permission it was last set to, and a new one the last choice made here", () => {
  let stored = readRemembered(undefined);
  assert.equal(wantedPermission(stored, "a", levels), null, "nothing chosen yet: leave the server's own");

  stored = remember(stored, "a", "full");
  stored = remember(stored, "b", "safe");
  assert.equal(wantedPermission(stored, "a", levels), "full");
  assert.equal(wantedPermission(stored, "b", levels), "safe");
  assert.equal(wantedPermission(stored, "new", levels), "safe", "a session with none starts from the last choice");
  assert.equal(wantedPermission(stored, null, levels), "safe");

  stored = remember(stored, "a", "deny");
  assert.equal(wantedPermission(stored, "a", levels), "deny", "choosing again replaces it");
  assert.equal(wantedPermission(stored, "b", levels), "safe", "and does not touch the other session");
});

test("a level the server does not offer is not asked for", () => {
  const stored = remember(readRemembered(undefined), "a", "full");
  assert.equal(wantedPermission(stored, "a", ["deny", "ask"]), null);
});

test("a choice stored under the old name of full is read as full, so nobody loses the level they picked", () => {
  assert.deepEqual(readRemembered({ bySession: { a: "auto", b: "safe" }, last: "auto" }), {
    bySession: { a: "full", b: "safe" },
    last: "full",
  });
  const stored = readRemembered({ bySession: { a: "auto" } });
  assert.equal(wantedPermission(stored, "a", levels), "full", "and the server, which offers full, is asked for it");
});

test("what was stored is read back through a filter: a bad value, a bad shape, nothing at all", () => {
  assert.deepEqual(readRemembered("nonsense"), { bySession: {} });
  assert.deepEqual(readRemembered(null), { bySession: {} });
  assert.deepEqual(readRemembered({ bySession: { a: "auto", b: "root", c: 3 }, last: "yolo" }), {
    bySession: { a: "full" },
  });
  assert.deepEqual(readRemembered({ bySession: "x", last: "ask" }), { bySession: {}, last: "ask" });
});

test("only the newest sessions are kept, and choosing again counts as newest", () => {
  let stored = readRemembered(undefined);
  for (let n = 0; n < REMEMBERED_SESSIONS + 5; n += 1) {
    stored = remember(stored, `s${n}`, "safe");
  }
  assert.equal(Object.keys(stored.bySession).length, REMEMBERED_SESSIONS);
  assert.equal(stored.bySession["s0"], undefined, "the oldest went first");
  assert.equal(stored.bySession[`s${REMEMBERED_SESSIONS + 4}`], "safe");

  stored = remember(stored, "s5", "full");
  for (let n = 0; n < 10; n += 1) {
    stored = remember(stored, `t${n}`, "ask");
  }
  assert.equal(stored.bySession["s5"], "full", "a session chosen again is not the next to be forgotten");
});

test("the chat view puts the remembered permission back whenever a session is read, and saves each choice", async () => {
  const source = await readFile("src/chat.ts", "utf8");
  const extras = source.slice(source.indexOf("private async readExtras"), source.indexOf("// -- messages from the webview"));
  assert.ok(extras.includes("applyRememberedPermission"), "it runs when a session is loaded, opened or started");
  const update = source.slice(source.indexOf("async updateSettings"), source.indexOf("private rememberPermission"));
  assert.ok(update.includes("rememberPermission(this.settings.permission)"), "a choice is kept as soon as the server takes it");
});
