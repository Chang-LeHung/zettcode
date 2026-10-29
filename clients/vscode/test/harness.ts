/** A webview in jsdom, driven by the messages the extension host would send; shared by the tests that need a page. */

import { readFile } from "node:fs/promises";
import { after } from "node:test";

import { JSDOM } from "jsdom";

import type { Settings, Usage } from "../../typescript/src/types.js";
import type { WebviewState } from "../src/core/protocol.js";
import type { Turn } from "../src/core/state.js";
import { chatHtml } from "../src/html.js";

export const usage: Usage = {
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

export const baseState: WebviewState = {
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
  selfCompaction: { choice: null, effort: undefined, effective: true } as unknown as WebviewState["selfCompaction"],
  context: null,
  commands: [],
  version: "0.1.8",
};

const opened: JSDOM[] = [];
after(() => {
  for (const dom of opened) {
    dom.window.close();
  }
});

export const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

export async function open(turns: Turn[] = [], initial: WebviewState = baseState) {
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
  window.dispatchEvent(new window.MessageEvent("message", { data: { type: "init", state: initial, turns } }));
  await settle();
  return {
    window,
    messages,
    async send(message: unknown) {
      window.dispatchEvent(new window.MessageEvent("message", { data: JSON.parse(JSON.stringify(message)) }));
      await settle();
    },
    async click(selector: string) {
      const node = window.document.querySelector<HTMLElement>(selector);
      if (node === null) {
        throw new Error(`missing ${selector}`);
      }
      node.click();
      await settle();
    },
    text: (selector: string) => window.document.querySelector(selector)?.textContent ?? "",
    all: <T extends Element = Element>(selector: string) => Array.from(window.document.querySelectorAll<T>(selector)),
    one: <T extends Element = HTMLElement>(selector: string) => window.document.querySelector<T>(selector),
  };
}
