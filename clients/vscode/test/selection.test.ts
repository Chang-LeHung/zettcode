import assert from "node:assert/strict";
import test from "node:test";

import { baseState, open } from "./harness.js";
import { applyEvent, createTurn } from "../src/core/state.js";

/** A page whose one answer is still being written. */
async function writing() {
  const turn = createTurn("question", [], 1000, "turn-1");
  applyEvent(turn, { type: "text_delta", text: "Hello **world**, this is an answer" }, 1100);
  const ui = await open([turn], { ...baseState, busy: true });
  const md = ui.one(".md");
  assert.ok(md, "the answer is on the page");
  return { ui, md };
}

test("a sentence selected in an answer that is still being written is still selected when the next words arrive", async () => {
  const { ui, md } = await writing();
  const range = ui.window.document.createRange();
  range.selectNodeContents(md);
  const selection = ui.window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  assert.equal(selection?.toString(), "Hello world, this is an answer");

  for (const words of [" that keeps growing", " and growing, with `code` and **bold**"]) {
    await ui.send({ type: "turn-delta", turnId: "turn-1", text: words });
    assert.equal(
      ui.window.getSelection()?.toString().startsWith("Hello world, this is an answer"),
      true,
      "what was selected is selected still, so Ctrl+C has something to copy",
    );
  }
});

test("only part of the answer selected stays exactly that part, and the words that follow are not swallowed", async () => {
  const { ui, md } = await writing();
  const text = md.querySelector("p")?.lastChild;
  assert.ok(text);
  const selection = ui.window.getSelection();
  selection?.setBaseAndExtent(text, 2, text, 8); // "this is" of ", this is an answer"
  const chosen = selection?.toString();
  assert.equal(chosen, "this i");

  await ui.send({ type: "turn-delta", turnId: "turn-1", text: " and more" });

  assert.equal(ui.window.getSelection()?.toString(), chosen);
});

test("a selection made from the end back to the start keeps its direction", async () => {
  const { ui, md } = await writing();
  const paragraph = md.querySelector("p");
  assert.ok(paragraph?.firstChild && paragraph.lastChild);
  const selection = ui.window.getSelection();
  selection?.setBaseAndExtent(paragraph.lastChild, 5, paragraph.firstChild, 0);
  assert.equal(selection?.anchorNode, paragraph.lastChild, "the anchor is at the end");

  await ui.send({ type: "turn-delta", turnId: "turn-1", text: " more" });

  const after = ui.window.getSelection();
  assert.ok(after && !after.isCollapsed);
  const anchorAt = after.anchorNode?.compareDocumentPosition(after.focusNode as Node) ?? 0;
  assert.ok(
    anchorAt & ui.window.Node.DOCUMENT_POSITION_PRECEDING || (after.anchorNode === after.focusNode && after.anchorOffset > after.focusOffset),
    "the anchor still comes after the focus",
  );
});

test("a redraw selects nothing the reader did not select", async () => {
  const { ui } = await writing();
  ui.window.getSelection()?.removeAllRanges();

  await ui.send({ type: "turn-delta", turnId: "turn-1", text: " and more" });

  assert.equal(ui.window.getSelection()?.toString(), "");
});
