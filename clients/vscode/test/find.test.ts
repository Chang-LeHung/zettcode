import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { JSDOM } from "jsdom";

import { findHits, findLabel, stepIndex } from "../src/core/find.js";
import { applyEvent, createTurn } from "../src/core/state.js";
import { open, settle } from "./harness.js";

test("a query is found wherever it occurs, in reading order, ignoring case, and never in a button or a script", () => {
  const { document } = new JSDOM(
    "<div id=r><p>Retry the Request, then retry again.</p><button>retry</button><script>retry()</script><p>nothing</p></div>",
  ).window;
  const root = document.getElementById("r");
  assert.ok(root);
  const hits = findHits(root, "RETRY");
  assert.deepEqual(
    hits.map((hit) => [hit.node.data.slice(hit.start, hit.end), hit.start]),
    [
      ["Retry", 0],
      ["retry", 24],
    ],
  );
  assert.deepEqual(findHits(root, "   "), []);
  assert.deepEqual(findHits(root, ""), []);
});

test("stepping wraps round at both ends and says where the reader is", () => {
  assert.equal(stepIndex(2, 3, 1), 0);
  assert.equal(stepIndex(0, 3, -1), 2);
  assert.equal(stepIndex(0, 0, 1), 0);
  assert.equal(findLabel("", 0, 0), "");
  assert.equal(findLabel("x", 0, 0), "No results");
  assert.equal(findLabel("x", 1, 4), "2 of 4");
});

function press(ui: Awaited<ReturnType<typeof open>>, key: string, extra: Record<string, boolean> = {}, target?: Element | null): void {
  (target ?? ui.window.document).dispatchEvent(
    new ui.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...extra }),
  );
}

async function typeQuery(ui: Awaited<ReturnType<typeof open>>, text: string): Promise<void> {
  const box = ui.one<HTMLInputElement>("#find .find-input");
  assert.ok(box);
  box.value = text;
  box.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 120));
}

function conversation() {
  const first = createTurn("where is the pager", [], 1000, "turn-1");
  applyEvent(first, { type: "text_delta", text: "The pager lives in pager.py; the Pager class wraps it." }, 1010);
  first.status = "done";
  first.finishedAt = 2000;
  const second = createTurn("thanks", [], 3000, "turn-2");
  applyEvent(second, { type: "text_delta", text: "You are welcome." }, 3010);
  second.status = "done";
  second.finishedAt = 4000;
  return [first, second];
}

test("Ctrl+F opens a search that counts the matches, steps through them and closes with Escape", async () => {
  const ui = await open(conversation());
  assert.equal(ui.one("#find"), null);

  press(ui, "f", { ctrlKey: true });
  await settle();
  assert.ok(ui.one("#find"), "the bar opens");
  assert.equal(ui.window.document.activeElement, ui.one("#find .find-input"), "the cursor is in it");

  await typeQuery(ui, "pager");
  assert.equal(ui.text("#find .find-count"), "1 of 4", "two in the message, two in the answer");

  const box = ui.one("#find .find-input");
  press(ui, "Enter", {}, box);
  await settle();
  assert.equal(ui.text("#find .find-count"), "2 of 4");
  press(ui, "Enter", { shiftKey: true }, box);
  press(ui, "Enter", { shiftKey: true }, box);
  await settle();
  assert.equal(ui.text("#find .find-count"), "4 of 4", "it wraps round");

  await typeQuery(ui, "zzz");
  assert.equal(ui.text("#find .find-count"), "No results");

  press(ui, "Escape", {}, box);
  await settle();
  assert.equal(ui.one("#find"), null, "Escape puts the bar away");
});

test("Cmd+F does the same on a Mac, and a short selection becomes the query", async () => {
  const ui = await open(conversation());
  press(ui, "F", { metaKey: true });
  await settle();
  assert.ok(ui.one("#find"));
  // Shift or Alt with F is some other shortcut, and is left alone.
  press(ui, "Escape", {}, ui.one("#find .find-input"));
  await settle();
  press(ui, "f", { ctrlKey: true, shiftKey: true });
  await settle();
  assert.equal(ui.one("#find"), null);
});

test("the command and the keybinding for the chat view reach the search too, when the editor takes the key first", async () => {
  const manifest = JSON.parse(await readFile("package.json", "utf8")) as {
    contributes: {
      commands: { command: string }[];
      keybindings: { command: string; key: string; mac: string; when: string }[];
    };
  };
  assert.ok(manifest.contributes.commands.some((entry) => entry.command === "zettcode.find"));
  const binding = manifest.contributes.keybindings.find((entry) => entry.command === "zettcode.find");
  assert.deepEqual([binding?.key, binding?.mac], ["ctrl+f", "cmd+f"]);
  assert.equal(binding?.when, "zettcode.chatFocused", "only while the chat is where the cursor is");

  const ui = await open(conversation());
  await ui.send({ type: "find" });
  assert.ok(ui.one("#find"));
});

test("an open search follows the conversation as it grows", async () => {
  const turns = conversation();
  const ui = await open(turns);
  press(ui, "f", { ctrlKey: true });
  await settle();
  await typeQuery(ui, "welcome");
  assert.equal(ui.text("#find .find-count"), "1 of 1");
  const running = turns[1]!;
  applyEvent(running, { type: "text_delta", text: " Welcome again, welcome." }, 3020);
  await ui.send({ type: "turn", turn: running });
  await new Promise((resolve) => setTimeout(resolve, 200));
  assert.equal(ui.text("#find .find-count"), "1 of 3");
});
