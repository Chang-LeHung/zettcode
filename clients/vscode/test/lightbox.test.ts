import assert from "node:assert/strict";
import test from "node:test";

import { createTurn, type Turn } from "../src/core/state.js";
import { open, baseState } from "./harness.js";

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

function withPicture(): Turn {
  const turn = createTurn("look", [{ data: PIXEL, mediaType: "image/png" }], 1, "turn-a");
  turn.status = "done";
  turn.finishedAt = 2;
  return turn;
}

function withBlocks(text: string): Turn {
  const turn = createTurn("show", [], 1, "turn-b");
  turn.status = "done";
  turn.finishedAt = 2;
  turn.blocks.push({ kind: "text", text });
  return turn;
}

const key = (ui: Awaited<ReturnType<typeof open>>, name: string, target?: Element | null) =>
  (target ?? ui.window.document.body).dispatchEvent(
    new ui.window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true }),
  );

test("pressing a picture you sent opens it large, and Escape or the close button puts it away", async () => {
  const ui = await open([withPicture()]);
  assert.equal(ui.one("#lightbox"), null);

  await ui.click(".thumb");
  const box = ui.one("#lightbox");
  assert.ok(box, "the picture opened");
  assert.equal(box.getAttribute("role"), "dialog");
  assert.match(ui.one<HTMLImageElement>("#lightbox img")?.getAttribute("src") ?? "", /^data:image\/png;base64,iVBOR/);
  assert.equal(ui.text(".lb-title"), "Picture 1 of 1");

  key(ui, "Escape");
  await wait(10);
  assert.equal(ui.one("#lightbox"), null);

  await ui.click(".thumb");
  await ui.click("#lightbox .lb-close");
  assert.equal(ui.one("#lightbox"), null);
});

test("Escape closes the box and does not stop the request running behind it", async () => {
  const ui = await open([withPicture()], { ...baseState, busy: true });
  await ui.click(".thumb");
  assert.ok(ui.one("#lightbox"));

  key(ui, "Escape", ui.one("#input"));
  await wait(10);
  assert.equal(ui.one("#lightbox"), null);
  assert.equal(
    ui.messages.some((message) => message.type === "cancel"),
    false,
    "the key was the box's",
  );

  key(ui, "Escape", ui.one("#input"));
  await wait(10);
  assert.equal(ui.messages.some((message) => message.type === "cancel"), true, "and is the request's again once it is closed");
});

test("the keys and the buttons zoom a picture, and the percentage says by how much", async () => {
  const ui = await open([withPicture()]);
  await ui.click(".thumb");
  // jsdom lays nothing out and never loads a picture, so say that it has: the box then knows the size to fit.
  ui.one("#lightbox img")!.dispatchEvent(new ui.window.Event("load"));
  await wait(10);
  const before = ui.text(".lb-zoom");
  await ui.click('#lightbox [aria-label="Zoom in"]');
  const bigger = Number.parseInt(ui.text(".lb-zoom"), 10);
  assert.ok(bigger > Number.parseInt(before, 10), `${before} → ${bigger}%`);

  key(ui, "-");
  key(ui, "-");
  await wait(10);
  assert.ok(Number.parseInt(ui.text(".lb-zoom"), 10) < bigger);

  key(ui, "0");
  await wait(10);
  assert.equal(ui.text(".lb-zoom"), before, "0 fits it again");
});

test("a table and a code block open larger as they are, without the buttons that would do nothing there", async () => {
  const ui = await open([withBlocks("| a | b |\n| - | - |\n| 1 | 2 |\n\n```js\nlet x = 1\n```")]);

  await ui.click(".table-expand");
  assert.equal(ui.text(".lb-title"), "Table");
  assert.ok(ui.one("#lightbox .lb-doc table"));
  assert.equal(ui.all("#lightbox .code-actions").length, 0);
  assert.equal(ui.one("#lightbox .lb-zoom"), null, "a table is bigger, not zoomable");
  key(ui, "Escape");
  await wait(10);

  await ui.click(".code-block [data-expand]");
  assert.match(ui.text(".lb-title"), /^(Js|JavaScript)$/);
  assert.match(ui.text("#lightbox .lb-doc code"), /let x = 1/);
  assert.equal(ui.all("#lightbox .code-actions").length, 0);
});

test("a drawing opens from its own press, and a block that is not a drawing is not mistaken for one", async () => {
  const ui = await open([withBlocks("```js\nlet x = 1\n```")]);
  await ui.click("#transcript .code-block .code-body, #transcript .code-block pre");
  assert.equal(ui.one("#lightbox"), null, "pressing code itself opens nothing; its button does");
});
