import assert from "node:assert/strict";
import { test } from "node:test";
import { blankDraft, changesOf, draftOf, entryOf, problem, toggled } from "../src/lib/modelForm";
import type { ModelOption } from "../src/types";

const base: ModelOption = {
  name: "fast",
  model: "gpt-fast",
  default: true,
  context_window: 128000,
  multimodal: false,
  efforts: ["low", "high"],
  api: "chat",
  compact_percent: 80,
  temperature: 0.5,
};

test("a new model names only what was filled in", () => {
  const draft = { ...blankDraft(), model: " m ", token: " k ", context_window: "64000", multimodal: true, api: "anthropic" as const };
  assert.deepEqual(entryOf(draft), { model: "m", anthropic: true, token: "k", context_window: 64000, multimodal: true });
  assert.deepEqual(entryOf({ ...blankDraft(), model: "m" }), { model: "m" });
});

test("a change names only what moved, never an empty token, and null removes a key", () => {
  const same = draftOf(base);
  assert.deepEqual(changesOf(same, base), {});
  assert.deepEqual(changesOf({ ...same, temperature: "" }, base), { temperature: null });
  assert.deepEqual(changesOf({ ...same, context_window: "32000", token: "  " }, base), { context_window: 32000 });
  assert.deepEqual(changesOf({ ...same, token: "new" }, base), { token: "new" });
  assert.deepEqual(changesOf({ ...same, multimodal: true }, base), { multimodal: true });
  assert.deepEqual(changesOf({ ...same, efforts: [] }, base), { reasoning_efforts: null });
});

test("changing the protocol sets one key and takes the others out", () => {
  assert.deepEqual(changesOf({ ...draftOf(base), api: "responses" }, base), { anthropic: null, responses_api: true, chat: null });
  assert.deepEqual(changesOf({ ...draftOf(base), api: "anthropic" }, base), { anthropic: true, responses_api: null, chat: null });
});

test("the form says what is wrong before anything is sent", () => {
  assert.match(problem(blankDraft()), /model id/);
  assert.match(problem({ ...blankDraft(), model: "m", context_window: "1.5" }), /whole number/);
  assert.match(problem({ ...blankDraft(), model: "m", compact_percent: "0" }), /percentage/);
  assert.match(problem({ ...blankDraft(), model: "m", temperature: "1.5", api: "anthropic" }), /0 to 1/);
  assert.equal(problem({ ...blankDraft(), model: "m", temperature: "1.5" }), "");
  assert.match(problem({ ...blankDraft(), model: "m", context_window: "abc" }), /whole number/);
});

test("chosen levels stay cheapest first", () => {
  assert.deepEqual(toggled(["high"], "low"), ["low", "high"]);
  assert.deepEqual(toggled(["low", "high"], "low"), ["high"]);
});
