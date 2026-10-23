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
    web_search: false,
    web_search_name: null,
  },
  effort: "low",
  efforts: ["low", "high"],
  permission: "ask",
  permissions: ["deny", "ask", "safe", "full"],
  harness: false,
};

const state: WebviewState = {
  server: { status: "ready", message: "Ready" },
  loaded: true,
  loading: null,
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

async function open(turns: unknown[] = []) {
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
  window.dispatchEvent(new window.MessageEvent("message", { data: { type: "init", state, turns } }));
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
    async key(name: string, modifiers: { shiftKey?: boolean; altKey?: boolean; ctrlKey?: boolean } = {}) {
      input.dispatchEvent(
        new window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true, ...modifiers }),
      );
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

test("an address in the draft is coloured as a link, without the punctuation that ends the sentence", async () => {
  const ui = await open();
  await ui.type("see https://example.com/a?b=1, and (https://x.dev/y). also @src/a.ts");
  assert.deepEqual(ui.pieces("link"), ["https://example.com/a?b=1", "https://x.dev/y"]);
  assert.deepEqual(ui.pieces("mention"), ["@src/a.ts"]);
  assert.equal(ui.layer(), "see https://example.com/a?b=1, and (https://x.dev/y). also @src/a.ts");
});

test("the paperclip asks the host for any file, and a file that is not a picture comes back as its path", async () => {
  const ui = await open();
  ui.window.document.querySelector<HTMLElement>("#attach")?.click();
  assert.ok(ui.messages.some((message) => message.type === "pick-files"));
  await ui.type("summarise");
  ui.window.dispatchEvent(
    new ui.window.MessageEvent("message", { data: { type: "files", paths: ["/tmp/report.pdf", "/tmp/my notes.pdf"] } }),
  );
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(ui.input.value, 'summarise /tmp/report.pdf "/tmp/my notes.pdf" ');
});

test("a skill is coloured as a skill and a file as a file, once the host has said which is which", async () => {
  const ui = await open();
  // On load the composer asks the host what `@` offers, so skills are known before the menu is ever opened.
  assert.ok(ui.messages.some((message) => message.type === "mentions" && message.query === ""));
  ui.window.dispatchEvent(
    new ui.window.MessageEvent("message", {
      data: {
        type: "mentions",
        query: "",
        items: [
          { token: "@grill-me", kind: "skill", name: "grill-me", description: "Interview" },
          { token: "@src/app.ts", kind: "file", name: "src/app.ts", description: "" },
        ],
      },
    }),
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
  await ui.type("use @grill-me on @src/app.ts and @unknown");
  assert.deepEqual(ui.pieces("skill"), ["@grill-me"]);
  assert.deepEqual(ui.pieces("mention"), ["@src/app.ts", "@unknown"]);
  assert.equal(ui.layer(), "use @grill-me on @src/app.ts and @unknown");
});

test("every command is offered after a bare slash, and the list narrows as you type", async () => {
  const ui = await open();
  await ui.type("/");
  assert.ok(ui.labels().length >= 15);
  await ui.type("/c");
  assert.deepEqual(ui.labels(), ["/continue", "/compact", "/context", "/clear"]);
});

const sent = (...prompts: string[]): unknown[] =>
  prompts.map((prompt, index) => ({
    id: `t${index + 1}`,
    prompt,
    images: [],
    startedAt: index,
    status: "done",
    blocks: [],
  }));

test("Up brings back what was sent before, and Down walks forward to the draft again", async () => {
  const ui = await open(sent("first", "second"));
  await ui.type("a draft");

  await ui.key("ArrowUp");
  assert.equal(ui.input.value, "second", "the newest message first");

  await ui.key("ArrowUp");
  assert.equal(ui.input.value, "first");

  await ui.key("ArrowUp");
  assert.equal(ui.input.value, "first", "and it stops at the oldest");

  await ui.key("ArrowDown");
  assert.equal(ui.input.value, "second");

  await ui.key("ArrowDown");
  assert.equal(ui.input.value, "a draft", "then the draft comes back exactly as it was");
});

test("with nothing sent there is nothing to bring back, and the caret stays the caret's", async () => {
  const ui = await open();
  await ui.type("hello");

  await ui.key("ArrowUp");

  assert.equal(ui.input.value, "hello");
});

test("a side question is not a message of the conversation and is not offered back", async () => {
  const turns = [...sent("asked"), { ...(sent("aside")[0] as object), aside: true }];
  const ui = await open(turns);

  await ui.key("ArrowUp");

  assert.equal(ui.input.value, "asked");
});

test("a command's arrows stay in the menu and never bring a message back", async () => {
  const ui = await open(sent("first"));
  await ui.type("/c");
  const before = ui.labels().length;

  await ui.key("ArrowDown");
  await ui.key("ArrowUp");

  assert.equal(ui.input.value, "/c");
  assert.equal(ui.labels().length, before, "the menu is still the thing moving");
});

test("a dismissed menu leaves the command's arrows meaning nothing", async () => {
  const ui = await open(sent("first"));
  await ui.type("/c");
  await ui.key("Escape");

  await ui.key("ArrowUp");

  assert.equal(ui.input.value, "/c");
});

test("shift with an arrow still selects text rather than bringing a message back", async () => {
  const ui = await open(sent("first"));
  await ui.type("one two");

  await ui.key("ArrowUp", { shiftKey: true });
  await ui.key("ArrowDown", { ctrlKey: true });

  assert.equal(ui.input.value, "one two");
});
