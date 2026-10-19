import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import type { Message, Usage } from "../../typescript/src/types.js";
import { lineStats, withoutEllipsis } from "../src/core/format.js";
import { renderMarkdown, renderStreaming } from "../src/core/markdown.js";
import { pageStart, requestsBefore } from "../src/core/paging.js";
import { applyEvent, createTurn, echoSteer, finishTurn, restoreTurns, retractSteer, type Turn } from "../src/core/state.js";
import { baseState, open, settle } from "./harness.js";

const usage: Usage = {
  input_tokens: 1200,
  output_tokens: 340,
  cache_read_tokens: 800,
  cache_write_tokens: 0,
  reasoning_tokens: 90,
  seconds: 4.2,
  requests: 3,
  context_tokens: 1540,
};

const message = (role: string, text: string, extra: Partial<Message> = {}): Message => ({
  role,
  text,
  tool_calls: [],
  tool_call_id: null,
  tool_name: null,
  ok: true,
  images: 0,
  ...extra,
});

function finished(id: string, start: number, end: number): Turn {
  const turn = createTurn("go", [], start, id);
  applyEvent(turn, { type: "text_delta", text: "ok" }, start + 10);
  turn.status = "done";
  turn.finishedAt = end;
  return turn;
}

// -- the receipt ---------------------------------------------------------------

test("the receipt says Processed in plain text, with its time and figures after it, and nothing to press", async () => {
  const turn = finished("turn-r", 1000, 11_000);
  turn.usage = usage;
  const ui = await open([turn]);
  const row = ui.one('[data-id="turn-r"] .receipt');
  assert.ok(row);
  assert.equal(ui.text('[data-id="turn-r"] .receipt-state').trim(), "Processed");
  assert.equal(row.textContent?.includes("Done"), false);
  assert.equal(ui.one(".receipt-state.done"), null, "no green state any more");
  assert.equal(row.querySelector("button"), null, "it is text, not a control");
  assert.ok(row.textContent?.includes("10s") && row.textContent?.includes("↑ 1.2k") && row.textContent?.includes("66.7% cached"));
  assert.equal(ui.one('[data-id="turn-r"] .receipt-detail'), null);
  const css = await readFile("src/webview/components/Receipt.vue", "utf8");
  assert.match(css, /user-select:\s*none/, "it cannot be selected");
});

test("a stopped request keeps its own word and colour", async () => {
  const stopped = finished("turn-s", 1000, 3000);
  stopped.status = "cancelled";
  const ui = await open([stopped]);
  assert.equal(ui.text('[data-id="turn-s"] .receipt-state').trim(), "Stopped");
  assert.ok(ui.one('[data-id="turn-s"] .receipt-state.amber'));
});

// -- steering ------------------------------------------------------------------

test("a steer shows at once and the run's report of it settles that block instead of adding another", () => {
  const turn = createTurn("work", [], 0, "t");
  applyEvent(turn, { type: "text_delta", text: "starting" }, 1);
  const block = echoSteer(turn, "use tabs");
  assert.deepEqual(
    turn.blocks.map((b) => b.kind),
    ["text", "steered"],
  );
  assert.equal(block.pending, true);

  applyEvent(turn, { type: "steered", text: "use tabs" }, 5);
  assert.equal(turn.blocks.filter((b) => b.kind === "steered").length, 1);
  assert.equal(block.pending, false);

  // A steer nobody drew first (sent from another window) still appears when the run reports it.
  applyEvent(turn, { type: "steered", text: "other" }, 6);
  assert.equal(turn.blocks.filter((b) => b.kind === "steered").length, 2);
});

test("two identical steers are two blocks, settled one at a time", () => {
  const turn = createTurn("work", [], 0, "t");
  const first = echoSteer(turn, "again");
  const second = echoSteer(turn, "again");
  applyEvent(turn, { type: "steered", text: "again" }, 2);
  assert.equal(first.pending, false);
  assert.equal(second.pending, true);
});

test("a steer that never reached a run is taken back, and a run that ends leaves none pending", () => {
  const turn = createTurn("work", [], 0, "t");
  const block = echoSteer(turn, "nobody home");
  retractSteer(turn, block);
  assert.equal(turn.blocks.length, 0);
  const kept = echoSteer(turn, "late");
  finishTurn(turn, { text: "", usage, stop: null, stop_message: null } as never, 9);
  assert.equal(kept.pending, false);
});

test("the view draws a pending steer with what it will do, and drops the hint once it is taken up", async () => {
  const turn = createTurn("work", [], Date.now(), "turn-w");
  echoSteer(turn, "prefer tabs");
  const ui = await open([turn], { ...baseState, busy: true });
  const note = ui.text('[data-id="turn-w"] .note.steered');
  assert.ok(note.includes("Steered") && note.includes("prefer tabs") && note.includes("next step"), note);
  applyEvent(turn, { type: "steered", text: "prefer tabs" });
  await ui.send({ type: "turn", turn });
  assert.equal(ui.text('[data-id="turn-w"] .note.steered').includes("next step"), false);
});

// -- compaction ----------------------------------------------------------------

test("a finished compaction can be opened to read its summary", async () => {
  const ui = await open();
  const input = ui.one<HTMLTextAreaElement>("#input");
  assert.ok(input);
  input.value = "/compact";
  input.dispatchEvent(new ui.window.Event("input", { bubbles: true }));
  await settle();
  input.dispatchEvent(new ui.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await settle();
  await ui.send({
    type: "notice",
    level: "info",
    text: "Compacted 14 messages into a summary; 3 kept.",
    summary: "The user is building a **pager**.",
  });
  assert.equal(ui.one(".compaction-summary"), null, "folded until it is asked for");
  await ui.click(".compaction-head");
  assert.ok(ui.text(".compaction-summary").includes("pager"));
  await ui.click(".compaction-head");
  assert.equal(ui.one(".compaction-summary"), null);
});

test("a reloaded compacted session starts with the compaction row, not a message the person typed", async () => {
  const turns = restoreTurns([
    message("summary", "Everything so far, summarised."),
    message("user", "next question"),
    message("assistant", "an answer"),
  ]);
  assert.equal(turns.length, 2);
  const [row, asked] = turns;
  assert.ok(row?.id.startsWith("turn-compact-"));
  assert.equal(row?.prompt, "");
  assert.equal(row?.blocks[0]?.kind, "compaction");
  assert.equal(asked?.prompt, "next question");
  assert.equal(
    asked?.blocks.some((b) => b.kind === "text"),
    true,
  );

  const ui = await open(turns);
  assert.equal(ui.all(".user-bubble").length, 1, "only the real question is a message");
  assert.ok(ui.text(".note.compaction").includes("Conversation compacted"));
  await ui.click(".compaction-head");
  assert.ok(ui.text(".compaction-summary").includes("Everything so far"));
});

// -- paging --------------------------------------------------------------------

function conversation(count: number): Turn[] {
  const messages: Message[] = [];
  for (let n = 0; n < count; n += 1) {
    messages.push(message("user", `question ${n}`), message("assistant", `answer ${n}`));
  }
  return restoreTurns(messages);
}

test("a page starts so that it holds the latest requests and leaves no orphan rows behind", () => {
  const turns = conversation(50);
  assert.equal(pageStart(turns, turns.length, 20), 30);
  assert.equal(requestsBefore(turns, 30), 30);
  assert.equal(pageStart(turns, 30, 20), 10);
  assert.equal(pageStart(turns, 10, 20), 0);
  assert.equal(pageStart(conversation(5)), 0);

  const withSummary = restoreTurns([message("summary", "s"), message("user", "q"), message("assistant", "a")]);
  assert.equal(pageStart(withSummary, withSummary.length, 1), 0, "the summary goes with the one request after it");
});

test("a long reloaded conversation shows its latest page and loads older ones in front on request", async () => {
  const all = conversation(30);
  const first = pageStart(all, all.length, 20);
  const ui = await open();
  await ui.send({ type: "turns", turns: all.slice(first), earlier: requestsBefore(all, first) });
  assert.equal(ui.all(".user-bubble").length, 20);
  assert.ok(ui.text("#earlier").includes("Show 10 earlier requests"));
  assert.equal(ui.text("#turns").includes("question 0 "), false);

  await ui.click("#earlier");
  assert.deepEqual(ui.messages.at(-1), { type: "load-earlier" });
  const next = pageStart(all, first, 20);
  await ui.send({ type: "earlier", turns: all.slice(next, first), earlier: requestsBefore(all, next) });
  assert.equal(ui.all(".user-bubble").length, 30);
  assert.equal(ui.one("#earlier"), null, "nothing older is left to ask for");
  const text = ui.text("#turns");
  assert.ok(text.indexOf("question 0") < text.indexOf("question 29"), "older ones sit in front");
});

test("an older page that overlaps what is on show does not repeat a request", async () => {
  const all = conversation(4);
  const ui = await open();
  await ui.send({ type: "turns", turns: all.slice(2), earlier: 2 });
  await ui.send({ type: "earlier", turns: all.slice(0, 3), earlier: 0 });
  assert.equal(ui.all(".user-bubble").length, 4);
});

// -- words that wait, and code -------------------------------------------------

test("waiting words lose their trailing dots, and the newest progress line of a running request shimmers", async () => {
  assert.equal(withoutEllipsis("Starting MCP server docs…"), "Starting MCP server docs");
  assert.equal(withoutEllipsis("Starting docs..."), "Starting docs");
  assert.equal(withoutEllipsis("Ready"), "Ready");

  const turn = createTurn("go", [], Date.now(), "turn-n");
  applyEvent(turn, { type: "notice", level: "info", text: "Starting MCP server 'docs' (process)…" } as never);
  const ui = await open([turn], { ...baseState, busy: true });
  assert.ok(ui.one('[data-id="turn-n"] .note.notice .shimmer'));
  assert.equal(ui.text('[data-id="turn-n"] .note.notice').includes("…"), false);

  applyEvent(turn, { type: "text_delta", text: "now" });
  await ui.send({ type: "turn", turn });
  assert.equal(ui.one('[data-id="turn-n"] .note.notice .shimmer'), null, "once something follows it, it rests");
});

test("keywords, strings and numbers are coloured by a palette of our own", async () => {
  const html = renderMarkdown("```python\ndef add(a, b):\n    return a + 1 if a else 'x'\n```");
  assert.ok(html.includes('class="hljs-keyword">def'), html);
  assert.ok(html.includes("hljs-string") && html.includes("hljs-number"));
  const css = await readFile("media/base.css", "utf8");
  assert.equal(/--syn-[a-z]+:\s*var\(--vscode-symbolIcon/.test(css), false, "most themes leave symbol-icon colours plain");
  for (const name of ["keyword", "string", "number", "function", "type", "comment"]) {
    assert.ok(new RegExp(`--syn-${name}:\\s*#`).test(css), name);
  }
});

test("a code block that has not closed yet is already coloured, and a half-typed closing fence is not code", () => {
  const html = renderStreaming("Here:\n\n```ts\nconst a = 1;\nreturn");
  assert.ok(html.includes("hljs-keyword"), html);
  assert.ok(html.includes("hljs-number"));
  const closing = renderStreaming("```ts\nconst a = 1;\n``");
  assert.equal(closing.includes("``"), false, closing);
  const full = renderStreaming("```ts\nconst a = 1;\n```");
  assert.equal(full, renderMarkdown("```ts\nconst a = 1;\n```"));
  assert.equal(renderStreaming("a `` b"), renderMarkdown("a `` b"));
});

test("a block with no language is coloured when the highlighter is sure, and left plain when it is not", () => {
  const code = renderMarkdown("```\nimport os\n\ndef main():\n    print(os.getcwd())\n    return 1\n```");
  assert.ok(code.includes("hljs-keyword"), code);
  const tree = renderMarkdown("```\nsrc/\n  app/\n  tui/\n```");
  assert.equal(tree.includes("hljs-"), false, tree);
});

// -- width ---------------------------------------------------------------------

test("an edit row shows the lines it added and removed, and a file written whole the lines it holds", async () => {
  assert.deepEqual(lineStats("edit", { path: "a.ts", old_text: "a\nb\n", new_text: "c\nd\ne" }), { added: 3, removed: 2 });
  assert.deepEqual(
    lineStats("edit", { path: "a.ts", edits: [{ old_text: "x", new_text: "y\nz" }, { old_text: "", new_text: "w" }] }),
    { added: 3, removed: 1 },
  );
  assert.deepEqual(lineStats("write_file", { path: "a.ts", content: "1\n2\n3\n" }), { added: 3, removed: 0 });
  assert.equal(lineStats("read_file", { path: "a.ts" }), null);
  assert.equal(lineStats("edit", { path: "a.ts" }), null);

  const turn = createTurn("edit", [], 0, "turn-e");
  applyEvent(turn, { type: "tool_started", call_id: "c", name: "edit", arguments: { path: "a.ts", old_text: "a", new_text: "b\nc" } }, 1);
  const ui = await open([turn]);
  assert.equal(ui.text('[data-id="turn-e"] .tool-stats').replace(/\s+/g, " ").trim(), "+2−1");
});

// -- width ---------------------------------------------------------------------

test("the conversation and the message box grow with the panel and keep a margin at both sides", async () => {
  const base = await readFile("media/base.css", "utf8");
  assert.match(base, /--column:\s*\d+px/);
  assert.match(base, /--gutter:\s*clamp\(/);
  const column = Number(/--column:\s*(\d+)px/.exec(base)?.[1]);
  assert.ok(column >= 1000 && column <= 1400, "wide, but not so wide that it cannot be read");
  for (const file of ["src/webview/components/Transcript.vue", "src/webview/components/Composer.vue"]) {
    const source = await readFile(file, "utf8");
    assert.ok(source.includes("max-width: var(--column)"), file);
    assert.ok(source.includes("var(--gutter)"), file);
    assert.equal(source.includes("780px"), false, file);
  }
});
