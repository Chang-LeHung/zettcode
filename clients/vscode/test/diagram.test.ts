import assert from "node:assert/strict";
import test, { afterEach, beforeEach } from "node:test";

import { clearDiagrams, drawnFor, ensureDrawn, onDiagramDrawn, setDiagramEngine } from "../src/core/diagram.js";
import { renderMarkdown, renderStreaming } from "../src/core/markdown.js";

const FLOW = "flowchart LR\n  A --> B";
const fence = (source: string): string => "```mermaid\n" + source + "\n```";

beforeEach(() => {
  clearDiagrams();
  setDiagramEngine(null);
});
afterEach(() => {
  clearDiagrams();
  setDiagramEngine(null);
});

test("a mermaid fence not yet drawn is its code, marked so the page can ask for it", () => {
  const html = renderMarkdown(fence(FLOW));
  assert.match(html, /class="code-block diagram-pending" data-diagram="flowchart LR\n  A --&gt; B"/);
  assert.match(html, /<code class="code[^"]*">/);
});

test("once drawn it is the drawing, with the source one press behind it and still copyable", async () => {
  setDiagramEngine(async () => "<svg><title>drawn</title></svg>");
  await ensureDrawn(FLOW, "dark");
  const html = renderMarkdown(fence(FLOW));
  assert.match(html, /class="diagram-body"><svg><title>drawn<\/title><\/svg>/);
  assert.match(html, /data-source/);
  assert.match(html, /data-copy/);
  assert.match(html, /<pre class="diagram-source" hidden>/);
  assert.equal(html.includes("diagram-pending"), false);
});

test("a diagram the engine refuses stays code and says why, once", async () => {
  let calls = 0;
  setDiagramEngine(async () => {
    calls += 1;
    throw new Error("Parse error on line 2\n  stack stack");
  });
  await Promise.all([ensureDrawn(FLOW, "dark"), ensureDrawn(FLOW, "dark")]);
  await ensureDrawn(FLOW, "dark");
  assert.equal(calls, 1, "asked once, however often the answer is rendered");
  const html = renderMarkdown(fence(FLOW));
  assert.match(html, /diagram-failed/);
  assert.match(html, /This diagram could not be drawn: Parse error on line 2/);
  assert.equal(html.includes("stack stack"), false, "only the first line of the complaint");
  assert.match(html, /A --&gt; B/);
});

test("with no engine a diagram is refused instead of waited for", async () => {
  await ensureDrawn(FLOW, "dark");
  assert.deepEqual(drawnFor(FLOW, "dark"), { ok: false, message: "The diagram engine is not available." });
});

test("a drawing is for one theme; the other is asked for again", async () => {
  const themes: string[] = [];
  setDiagramEngine(async (_source, theme) => {
    themes.push(theme);
    return `<svg data-theme="${theme}"/>`;
  });
  await ensureDrawn(FLOW, "dark");
  await ensureDrawn(FLOW, "light");
  assert.deepEqual(themes, ["dark", "light"]);
});

test("listeners hear of every drawing, and stop hearing when they leave", async () => {
  setDiagramEngine(async () => "<svg/>");
  let heard = 0;
  const stop = onDiagramDrawn(() => {
    heard += 1;
  });
  await ensureDrawn("a", "dark");
  stop();
  await ensureDrawn("b", "dark");
  assert.equal(heard, 1);
});

test("a fence still being typed is code until it closes, but finished drawings before it stay drawn", async () => {
  setDiagramEngine(async () => "<svg><title>drawn</title></svg>");
  await ensureDrawn(FLOW, "dark");

  const typing = renderStreaming(`${fence(FLOW)}\n\nthen\n\n\`\`\`mermaid\nflowchart LR\n  A --> B`);
  assert.equal(typing.split('class="diagram-body"').length - 1, 1, "the finished one is drawn");
  assert.equal(typing.includes("diagram-pending"), false, "the open one is not asked for");
  assert.match(typing, /<code class="code[^"]*">/);

  const closed = renderStreaming(`${fence(FLOW)}\n\nthen\n\n${fence(FLOW)}`);
  assert.equal(closed.split('class="diagram-body"').length - 1, 2);
});

test("other fences are untouched, and a word that only starts like mermaid is not a diagram", () => {
  assert.equal(renderMarkdown("```js\nlet a = 1\n```").includes("data-diagram"), false);
  assert.equal(renderMarkdown("```mermaidish\nx\n```").includes("data-diagram"), false);
});
