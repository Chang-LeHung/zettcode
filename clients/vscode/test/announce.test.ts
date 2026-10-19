import assert from "node:assert/strict";
import test from "node:test";

import { announcement, createTurn } from "../src/core/state.js";
import { baseState, open, settle } from "./harness.js";

test("a change of model, effort or permission is a line across the view with its words in the middle", async () => {
  const before = createTurn("first", [], 100, "turn-a");
  before.status = "done";
  before.finishedAt = 200;
  const change = announcement("Model changed from fast to deep.", 300, "turn-announce-1");
  const after = createTurn("second", [], 400, "turn-b");
  after.status = "done";
  after.finishedAt = 500;
  const ui = await open([before, change, after]);

  const rule = ui.one('[data-id="turn-announce-1"] .rule');
  assert.ok(rule, "a rule is drawn");
  assert.equal(rule.getAttribute("role"), "separator");
  assert.equal(rule.textContent?.trim(), "Model changed from fast to deep.");
  // It is not a message: no bubble, no answer, no receipt, no copy or edit buttons.
  assert.equal(ui.one('[data-id="turn-announce-1"] .user'), null);
  assert.equal(ui.one('[data-id="turn-announce-1"] .assistant'), null);
  // It sits between the two requests it separates.
  const ids = ui.all(".turn").map((node) => node.getAttribute("data-id"));
  assert.deepEqual(ids, ["turn-a", "turn-announce-1", "turn-b"]);
});

test("a line that announces a change is not a request: folding all requests leaves it, and it hides nothing", async () => {
  const done = createTurn("first", [], 100, "turn-a");
  done.status = "done";
  done.finishedAt = 200;
  const ui = await open([done, announcement("Reasoning effort changed from low to high.", 300, "turn-announce-2")]);
  assert.ok(ui.one('[data-id="turn-announce-2"] .rule'));
  assert.equal(ui.all(".turn.folded").length, 0);
});

test("a follow-up still waits after a stopped run when a change was announced after it", async () => {
  const stopped = createTurn("second", [], 300, "turn-b");
  stopped.status = "cancelled";
  stopped.finishedAt = 400;
  const change = announcement("Shell permission changed from ask to auto.", 450, "turn-announce-3");
  const ui = await open([stopped, change]);
  await ui.send({ type: "state", state: { ...baseState, busy: true } });

  const input = ui.one<HTMLTextAreaElement>("#input");
  assert.ok(input);
  input.value = "later";
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await settle();
  await ui.click("#send");
  await ui.send({ type: "state", state: baseState });

  assert.equal(ui.messages.some((message) => message.type === "prompt"), false, "the stopped run is still the last request");
  assert.ok(ui.text("#queue").includes("Waiting to send"));
});

test("while a request runs its words shimmer and nothing spins", async () => {
  const running = createTurn("work", [], Date.now(), "turn-r");
  const ui = await open([running], { ...baseState, busy: true });
  const live = ui.one("#live-status");
  assert.ok(live, "the status line shows");
  assert.ok(live.textContent?.includes("Processing"));
  assert.ok(!live.textContent?.includes("…"), "no trailing ellipsis");
  assert.ok(ui.one("#live-status .live-label .shimmer"), "the label shimmers");
  assert.equal(ui.one("#live-status .spinner"), null, "no spinner");
});

test("when it waits for you the label stops shimmering and a pulsing dot says so", async () => {
  const running = createTurn("work", [], Date.now(), "turn-r");
  const ui = await open([running], {
    ...baseState,
    busy: true,
    pending: { kind: "approval", call_id: "c1", command: "rm -rf build", remember_supported: true },
  });
  assert.ok(ui.text("#live-status").includes("Waiting for your approval"));
  assert.equal(ui.one("#live-status .shimmer"), null);
  assert.ok(ui.one("#live-status .dot.pulse"));
});
