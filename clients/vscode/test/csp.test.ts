import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { chatHtml } from "../src/html.js";

const page = chatHtml({ styles: ["a.css"], script: "webview.js", cspSource: "vscode-webview://x", nonce: "n0nce" });
const policy = /Content-Security-Policy" content="([^"]+)"/.exec(page)?.[1] ?? "";

test("no script runs without the page's nonce, and none may be written inline", () => {
  assert.match(policy, /script-src 'nonce-n0nce';/);
  assert.equal(/script-src[^;]*(unsafe-inline|unsafe-eval)/.test(policy), false);
});

test("styles may be inline, because a drawn diagram carries its own style element", () => {
  assert.match(policy, /style-src vscode-webview:\/\/x 'unsafe-inline';/);
});

test("the diagram engine is its own script, not part of the view's", async () => {
  const entry = await readFile("src/webview/mermaid-entry.ts", "utf8");
  const main = await readFile("src/webview/main.ts", "utf8");
  const loader = await readFile("src/webview/mermaid.ts", "utf8");
  // Only the entry imports the library; the view reaches it by adding a script tag when a diagram is first met.
  assert.match(entry, /from "mermaid"/);
  assert.equal(/from "mermaid"/.test(main + loader), false);
  assert.match(loader, /script\.nonce/);
});
