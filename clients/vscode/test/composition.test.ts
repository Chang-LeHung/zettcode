import assert from "node:assert/strict";
import test from "node:test";

import { open, settle } from "./harness.js";

/** What the layer behind the box draws, without the zero-width space that keeps its last line open. */
const layer = (ui: Awaited<ReturnType<typeof open>>): string => ui.text(".mirror").replace(/\u200b/g, "");

test("letters typed through an input method are drawn while they are still being composed", async () => {
  const ui = await open();
  const box = ui.one<HTMLTextAreaElement>("#input");
  assert.ok(box);

  // The input method starts: from here Vue's v-model ignores the box until the word is chosen.
  box.dispatchEvent(new ui.window.Event("compositionstart", { bubbles: true }));
  box.value = "nihao";
  box.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  box.dispatchEvent(new ui.window.Event("compositionupdate", { bubbles: true }));
  await settle();

  // The draft has nothing yet, but the box's own text is transparent, so the layer must already show the letters.
  assert.equal(layer(ui), "nihao");

  box.value = "你好";
  box.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  box.dispatchEvent(new ui.window.Event("compositionend", { bubbles: true }));
  await settle();
  assert.equal(layer(ui), "你好");
  assert.equal(box.value, "你好");
});

test("the layer follows a draft that is set from outside the box, and empties when it is sent", async () => {
  const ui = await open();
  const box = ui.one<HTMLTextAreaElement>("#input");
  assert.ok(box);
  box.value = "hello";
  box.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await settle();
  assert.equal(layer(ui), "hello");

  box.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await settle();
  assert.equal(box.value, "");
  assert.equal(layer(ui), "");
});
