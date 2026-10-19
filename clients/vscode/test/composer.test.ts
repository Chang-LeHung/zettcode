import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";

import { JSDOM } from "jsdom";

import type { Settings, Usage } from "../../typescript/src/types.js";
import type { WebviewState } from "../src/core/protocol.js";
import { chatHtml } from "../src/html.js";

const usage: Usage = {
  input_tokens: 1200,
  output_tokens: 340,
  cache_read_tokens: 800,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  seconds: 4.2,
  requests: 3,
  context_tokens: 1540,
};

const settings: Settings = {
  model: {
    name: "fast",
    model: "gpt-5",
    context_window: 200_000,
    multimodal: true,
    efforts: ["low", "high"],
    active: true,
    compact_percent: 80,
  },
  effort: "low",
  efforts: ["low", "high"],
  permission: "ask",
  permissions: ["deny", "ask", "safe", "auto"],
};

const state: WebviewState = {
  server: { status: "ready", message: "Ready" },
  loaded: true,
  ready: true,
  health: {
    status: "ok",
    version: "0.1.8",
    workspace: "/work/project",
    ready: true,
    session: "session-1",
    models: 1,
    busy: false,
  },
  settings,
  models: [settings.model],
  currentModel: "fast",
  session: { id: "session-1", title: "Pagination work", locked: false, usage },
  sessions: [],
  busy: false,
  pending: null,
  resumable: null,
  selfCompaction: { choice: null, effective: true },
  context: null,
  version: "0.1.8",
};

const opened: JSDOM[] = [];
after(() => {
  for (const dom of opened) {
    dom.window.close();
  }
});

const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

async function open() {
  const html = chatHtml({
    styles: ["file:///base.css", "file:///webview.css"],
    script: "file:///webview.js",
    cspSource: "https://localhost",
    nonce: "test",
  });
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "https://localhost/" });
  opened.push(dom);
  const { window } = dom;
  const messages: Record<string, unknown>[] = [];
  (window as unknown as { acquireVsCodeApi: () => unknown }).acquireVsCodeApi = () => ({
    postMessage: (message: Record<string, unknown>) => messages.push(JSON.parse(JSON.stringify(message))),
    getState: () => null,
    setState: () => undefined,
  });
  (window.HTMLElement.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView = () => undefined;
  window.eval(await readFile(process.env.ZETTCODE_WEBVIEW_BUNDLE ?? "build/webview.js", "utf8"));
  window.dispatchEvent(new window.MessageEvent("message", { data: { type: "init", state, turns: [] } }));
  await settle();
  const input = window.document.getElementById("input") as HTMLTextAreaElement;
  return {
    window,
    messages,
    input,
    async type(value: string) {
      input.value = value;
      input.setSelectionRange(value.length, value.length);
      input.dispatchEvent(new window.Event("input", { bubbles: true }));
      await settle();
    },
    async key(name: string) {
      input.dispatchEvent(new window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true }));
      await settle();
    },
    labels: () => Array.from(window.document.querySelectorAll("#menu .menu-label")).map((node) => node.textContent),
    layer: () => window.document.querySelector(".mirror")?.textContent?.replace(/\u200b/g, "") ?? "",
    pieces: (kind: string) =>
      Array.from(window.document.querySelectorAll(`.mirror .piece-${kind}`)).map((node) => node.textContent),
  };
}

test("Tab completes a command and never runs it; Enter runs it", async () => {
  const ui = await open();
  await ui.type("/usa");
  assert.deepEqual(ui.labels(), ["/usage"]);
  await ui.key("Tab");
  assert.equal(ui.input.value, "/usage ");
  assert.equal(ui.messages.some((message) => message.type === "usage"), false);
  await ui.key("Enter");
  assert.equal(ui.messages.some((message) => message.type === "usage"), true);
});

test("a command that waits for an argument is completed by Tab and Enter alike, with a hint of what goes after it", async () => {
  for (const key of ["Tab", "Enter"]) {
    const ui = await open();
    await ui.type("/bt");
    await ui.key(key);
    assert.equal(ui.input.value, "/btw ");
    assert.deepEqual(ui.pieces("command"), ["/btw"]);
    assert.deepEqual(ui.pieces("ghost"), ["ask a side question…"]);
    assert.equal(ui.messages.some((message) => message.type === "ask"), false);
    await ui.type("/btw what is a mutex");
    assert.deepEqual(ui.pieces("ghost"), []);
    await ui.key("Enter");
    assert.deepEqual(
      ui.messages.filter((message) => message.type === "ask"),
      [{ type: "ask", question: "what is a mutex" }],
    );
  }
});

test("a command and an @ mention are coloured, and the layer repeats the draft letter for letter", async () => {
  const ui = await open();
  await ui.type("/rename Plan <b> and @src/app.ts please");
  assert.deepEqual(ui.pieces("command"), ["/rename"]);
  assert.deepEqual(ui.pieces("mention"), ["@src/app.ts"]);
  assert.equal(ui.layer(), "/rename Plan <b> and @src/app.ts please");
  assert.equal(ui.window.document.querySelector(".mirror b"), null);
  await ui.type("/notacommand here");
  assert.deepEqual(ui.pieces("command"), []);
  await ui.type("plain words");
  assert.deepEqual(ui.pieces("command").concat(ui.pieces("mention")), []);
});

test("every command is offered after a bare slash, and the list narrows as you type", async () => {
  const ui = await open();
  await ui.type("/");
  assert.ok(ui.labels().length >= 15);
  await ui.type("/c");
  assert.deepEqual(ui.labels(), ["/continue", "/compact", "/context", "/clear"]);
});
