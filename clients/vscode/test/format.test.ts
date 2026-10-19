import assert from "node:assert/strict";
import test from "node:test";

import { renderMarkdown } from "../src/core/markdown.js";
import {
  describeTool,
  escapeHtml,
  formatDuration,
  formatTokens,
  permissionDescription,
  permissionLabel,
  relativeTime,
  sessionLabel,
  summariseOutput,
  toolDetail,
  toolLanguage,
} from "../src/core/format.js";

test("HTML is escaped before it reaches the page", () => {
  assert.equal(escapeHtml(`<img src=x onerror="alert('x')">`), "&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;");
  const rendered = renderMarkdown("<script>alert(1)</script>");
  assert.ok(!rendered.includes("<script>"));
  assert.ok(rendered.includes("&lt;script&gt;"));
});

test("a fenced block keeps its language, its code, and is coloured", () => {
  const rendered = renderMarkdown("```python\nprint('<hi>')\n```");
  assert.ok(rendered.includes("python"));
  assert.ok(rendered.includes("&lt;hi&gt;"));
  assert.ok(!rendered.includes("<hi>"));
  assert.ok(rendered.includes("hljs-"));
  assert.ok(rendered.includes("data-copy"));
});

test("inline code that names a path becomes a file link", () => {
  const rendered = renderMarkdown("Read `src/zettcode/app.py:12` next.");
  assert.ok(rendered.includes("data-open=\"src/zettcode/app.py:12\""));
  assert.ok(rendered.includes("<code>src/zettcode/app.py:12</code>"));
});

test("ordinary inline code stays code", () => {
  const rendered = renderMarkdown("Run `pytest -q` first.");
  assert.ok(rendered.includes("<code>pytest -q</code>"));
  assert.ok(!rendered.includes("data-open"));
});

test("relative links open in the editor and web links open outside it", () => {
  const local = renderMarkdown("See [the engine](src/engine.ts:7).");
  assert.ok(local.includes("data-open=\"src/engine.ts:7\""));
  const external = renderMarkdown("[docs](https://example.com/a)");
  assert.ok(external.includes("data-external=\"https://example.com/a\""));
  const script = renderMarkdown("[click](javascript:alert(1))");
  assert.ok(!script.includes("href=\"javascript:"));
});

test("emphasis, lists, quotes, headings and tables render", () => {
  const rendered = renderMarkdown(
    "# Title\n\n- one\n- two\n\n> quoted\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n**bold** and *italic* and ~~gone~~",
  );
  assert.ok(rendered.includes("<h1>Title</h1>"));
  assert.ok(/<ul>\s*<li>one<\/li>\s*<li>two<\/li>\s*<\/ul>/.test(rendered));
  assert.ok(rendered.includes("<blockquote>"));
  assert.ok(rendered.includes("<table>"));
  assert.ok(rendered.includes("<strong>bold</strong>"));
  assert.ok(rendered.includes("<em>italic</em>"));
  assert.ok(rendered.includes("<del>gone</del>"));
});

test("a tool row says what happened and where", () => {
  assert.deepEqual(describeTool("read_file", { path: "src/a.py" }), {
    verb: "Read",
    target: "src/a.py",
    path: "src/a.py",
  });
  assert.deepEqual(describeTool("bash", { command: "pytest -q" }), { verb: "Bash", target: "pytest -q" });
  assert.deepEqual(describeTool("grep", { pattern: "Agent", path: "src" }), {
    verb: "Grep",
    target: "Agent in src",
    path: "src",
  });
  assert.equal(describeTool("write_file", { path: "docs/a.md" }).verb, "Write");
  assert.equal(describeTool("edit", { path: "src/a.py" }).verb, "Edit");
  assert.equal(describeTool("glob", { pattern: "**/*.ts" }).target, "**/*.ts");
  assert.equal(describeTool("mcp__github__create_issue", { title: "A bug" }).verb, "Create issue");
});

test("a tool body is the command or the edit", () => {
  assert.equal(toolDetail("bash", { command: "ls -la" }), "ls -la");
  assert.equal(toolLanguage("bash", { command: "ls" }), "shell");
  const diff = toolDetail("edit", { edits: [{ old_text: "a", new_text: "  b" }, { old_text: "c", new_text: "d" }] });
  assert.equal(diff, "@@ edit 1 of 2\n-a\n+  b\n@@ edit 2 of 2\n-c\n+d");
  assert.equal(toolDetail("edit", { old_text: "a", new_text: "b" }), "-a\n+b");
  assert.equal(toolLanguage("edit", {}), "diff");
  assert.ok(toolDetail("read_file", { path: "a" }).includes("\"path\": \"a\""));
});

test("numbers, times and names read the way the UI shows them", () => {
  assert.equal(formatTokens(0), "0");
  assert.equal(formatTokens(999), "999");
  assert.equal(formatTokens(1234), "1.2k");
  assert.equal(formatTokens(123_456), "123k");
  assert.equal(formatTokens(1_234_567), "1.2M");
  assert.equal(formatDuration(250), "250ms");
  assert.equal(formatDuration(4200), "4.2s");
  assert.equal(formatDuration(65_000), "1m 5s");
  assert.equal(sessionLabel(null), "Untitled session");
  assert.equal(sessionLabel("  Work  "), "Work");
  assert.equal(permissionLabel("safe"), "Safe");
  assert.ok(permissionDescription("deny").includes("refused"));
  const now = Date.parse("2026-10-18T12:00:00Z");
  assert.equal(relativeTime("2026-10-18T11:59:30Z", now), "just now");
  assert.equal(relativeTime("2026-10-18T11:30:00Z", now), "30m ago");
  assert.equal(relativeTime("2026-10-17T12:00:00Z", now), "1d ago");
});

test("an output summary is one flat line", () => {
  assert.equal(summariseOutput("\n\n  hello   world\nsecond", 40), "hello world");
  assert.ok(summariseOutput("x".repeat(200), 20).endsWith("…"));
});
