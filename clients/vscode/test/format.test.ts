import assert from "node:assert/strict";
import test from "node:test";

import { renderMarkdown } from "../src/core/markdown.js";
import {
  describeTool,
  escapeHtml,
  formatClock,
  formatDuration,
  formatTokens,
  permissionDescription,
  permissionLabel,
  relativeTime,
  sessionLabel,
  skillDescription,
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
  assert.deepEqual(describeTool("mcp__github__create_issue", { title: "A bug" }), {
    verb: "Called",
    target: "github/create_issue",
  });
  assert.deepEqual(describeTool("docs__search", { query: "fix" }), { verb: "Called", target: "docs/search" });
  assert.deepEqual(describeTool("my_plugin__helper", { x: 1 }), { verb: "Called", target: "my_plugin/helper" });
  assert.deepEqual(describeTool("mcp__github", {}), { verb: "mcp__github", target: "" }, "a name without a tool part is left whole");
});

test("a skill row names the skill and the description its file declares", () => {
  const skill = "---\nname: code-review\ndescription: Review code with evidence from the tree.\n---\n\n# Code review\n";

  assert.deepEqual(describeTool("read_skill", { name: "code-review" }), {
    verb: "Read skill",
    target: "code-review",
  });
  assert.deepEqual(describeTool("read_skill", { name: "code-review" }, skill), {
    verb: "Read skill",
    target: "code-review · Review code with evidence from the tree.",
  });
  assert.equal(skillDescription(skill), "Review code with evidence from the tree.");
  assert.equal(skillDescription("---\nname: x\ndescription: >\n  one long\n  line\n---\nbody"), "one long line");
  assert.equal(skillDescription("Unknown skill 'missing'"), "");
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

test("a figure of a thousand millions is written in billions, and no figure is ever written as 1000 of a unit", () => {
  // The numbers from a real ledger: 4064.4M total, 4052.9M in, 11.5M out.
  assert.equal(formatTokens(4_064_400_000), "4.06B");
  assert.equal(formatTokens(4_052_900_000), "4.05B");
  assert.equal(formatTokens(11_500_000), "11.5M", "the part that is still millions stays in millions");
  assert.equal(formatTokens(1_000_000_000), "1B");
  assert.equal(formatTokens(1_100_000_000), "1.1B", "no zero that adds nothing");
  assert.equal(formatTokens(12_340_000_000), "12.3B");
  assert.equal(formatTokens(123_400_000_000), "123B");
  assert.equal(formatTokens(999_000_000), "999M", "just under a billion is still millions");
  assert.equal(formatTokens(999_960_000), "1B", "and one that would round to 1000.0M steps up");
  assert.equal(formatTokens(999_500), "1M", "as one that would round to 1000k does");
  assert.equal(formatTokens(999_499), "999k");
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
  assert.equal(permissionLabel("full"), "Full");
  assert.equal(permissionLabel("auto"), "Full", "the old name reads as full");
  assert.equal(permissionLabel("ask"), "Ask");
  assert.equal(permissionLabel("yolo"), "Yolo", "a level this build does not know is shown as itself, not as Ask");
  assert.ok(permissionDescription("safe").includes("sandbox") && permissionDescription("safe").includes("/tmp"));
  assert.ok(permissionDescription("full").includes("your own access"));
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

test("a running clock says its units, and never a decimal", () => {
  assert.equal(formatClock(0), "0s");
  assert.equal(formatClock(8_400), "8s");
  assert.equal(formatClock(59_999), "59s");
  assert.equal(formatClock(79_000), "1m 19s");
  assert.equal(formatClock(3_600_000), "1h 0m");
  assert.equal(formatClock(-5), "0s");
});
