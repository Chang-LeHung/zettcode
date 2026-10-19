import assert from "node:assert/strict";
import test from "node:test";

import { applyEvent, createTurn } from "../src/core/state.js";
import { baseState, open, settle } from "./harness.js";

/** Type a command into the box and press Enter, the way a reader does. */
async function run(ui: Awaited<ReturnType<typeof open>>, command: string): Promise<void> {
  const input = ui.one<HTMLTextAreaElement>("#input");
  assert.ok(input);
  input.value = command;
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await settle();
  input.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await settle();
}

test("compacting shows a row at once, then only that it was compacted, never the summary", async () => {
  const ui = await open();
  await run(ui, "/compact");
  assert.equal(ui.messages.filter((message) => message.type === "compact").length, 1);
  assert.ok(ui.text(".note.compaction").includes("Compacting the conversation"));
  assert.ok(ui.one(".note.compaction .shimmer"));
  assert.equal(ui.one(".note.compaction .spinner"), null, "the words shimmer, nothing spins");
  assert.equal(ui.all(".toast").length, 0);

  await ui.send({ type: "notice", level: "info", text: "Compacted 14 messages into a summary; 3 kept." });
  assert.equal(ui.text(".note.compaction").trim(), "Conversation compacted");
  assert.equal(ui.one(".note.compaction .shimmer"), null);
  assert.equal(ui.all(".toast").length, 0);
  assert.equal(ui.text('[data-id^="turn-compact-"]').includes("14 messages"), false);
});

test("compacting while a run is busy is refused with the reason, and no row is left", async () => {
  const ui = await open([], { ...baseState, busy: true });
  await run(ui, "/compact");
  assert.equal(ui.messages.some((message) => message.type === "compact"), false);
  assert.ok(ui.text(".toast").includes("Stop the run before compacting"));
  assert.equal(ui.one(".note.compaction"), null);
});

test("a compaction that finds nothing to do says so", async () => {
  const ui = await open();
  await run(ui, "/compact");
  await ui.send({ type: "notice", level: "info", text: "There was nothing to compact yet." });
  assert.equal(ui.text(".note.compaction").trim(), "Nothing to compact.");
});

test("a compaction that fails ends the row with the reason", async () => {
  const ui = await open();
  await run(ui, "/compact");
  await ui.send({ type: "notice", level: "error", text: "The model did not answer." });
  assert.ok(ui.text('[data-id^="turn-compact-"]').includes("The model did not answer."));
  assert.equal(ui.one(".note.compaction .shimmer"), null);
});

test("a message sits on the right with its time, a copy button and an edit button", async () => {
  const sent = createTurn("Fix the pager", [], new Date(2026, 9, 19, 23, 7).getTime(), "turn-1");
  applyEvent(sent, { type: "text_delta", text: "Done." }, 5);
  sent.status = "done";
  const restored = createTurn("An older message", [], Date.now(), "history-0");
  restored.status = "done";
  const ui = await open([restored, sent]);

  const meta = ui.one('[data-id="turn-1"] .user-meta');
  assert.ok(meta);
  // The clock follows the reader's locale: 11:07 PM or 23:07.
  assert.ok(/(11|23):07/.test(meta.textContent ?? ""), meta.textContent ?? "");
  assert.ok(ui.one('[data-id="turn-1"] .user-time')?.getAttribute("title"));
  // A turn read back from the store has no send time, and shows none rather than the moment it was opened.
  assert.equal(ui.one('[data-id="history-0"] .user-time'), null);

  await ui.click('[data-id="turn-1"] [title="Copy message"]');
  assert.deepEqual(
    ui.messages.filter((message) => message.type === "copy"),
    [{ type: "copy", text: "Fix the pager" }],
  );
  assert.ok(ui.one('[data-id="turn-1"] [title="Copied"]'));

  await ui.click('[data-id="turn-1"] [title="Edit and resend"]');
  assert.equal((ui.one("#input") as HTMLTextAreaElement).value, "Fix the pager");
});
