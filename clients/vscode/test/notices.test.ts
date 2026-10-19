import assert from "node:assert/strict";
import test from "node:test";

import { noticeMarkdown } from "../src/core/format.js";
import { applyEvent, createTurn } from "../src/core/state.js";
import { baseState, open } from "./harness.js";

const progress = "Starting MCP server 'docs' (process)…";
const down = "MCP server 'docs' is not available (FileNotFoundError); its tools are skipped until it works";

test("a notice keeps how serious it is, and one that does not say is progress", () => {
  const turn = createTurn("go", [], 1, "t");
  applyEvent(turn, { type: "notice", text: progress, level: "info" }, 2);
  applyEvent(turn, { type: "notice", text: down, level: "warn" }, 3);
  applyEvent(turn, { type: "notice", text: "from an older server" }, 4);
  assert.deepEqual(
    turn.blocks.map((block) => (block.kind === "notice" ? block.level : null)),
    ["info", "warn", "info"],
  );
});

test("names in the agent's news become code, but an apostrophe does not", () => {
  assert.equal(noticeMarkdown(progress), "Starting MCP server `docs` (process)…");
  assert.equal(noticeMarkdown("MCP server 'bad entry' in mcp.json is ignored"), "MCP server `bad entry` in mcp.json is ignored");
  assert.equal(noticeMarkdown("it's not what he's after"), "it's not what he's after");
  assert.equal(noticeMarkdown("'docs' is down"), "`docs` is down");
});

test("an MCP server starting and failing is shown in the transcript, as Markdown, a warning standing out", async () => {
  const turn = createTurn("hello", [], 1, "turn-1");
  applyEvent(turn, { type: "notice", text: progress, level: "info" }, 2);
  applyEvent(turn, { type: "notice", text: down, level: "warn" }, 3);
  applyEvent(turn, { type: "text_delta", text: "Here is the answer." }, 4);
  turn.status = "done";
  turn.finishedAt = 5;
  const ui = await open([turn]);

  const notes = ui.all('[data-id="turn-1"] .note.notice');
  assert.equal(notes.length, 2);
  assert.ok(notes[0]!.classList.contains("level-info"));
  assert.ok(notes[1]!.classList.contains("level-warn"));
  assert.equal(notes[1]!.getAttribute("role"), "alert", "a warning is announced");
  // Rendered through the Markdown the answers use: the server's name is code.
  assert.equal(notes[0]!.querySelector(".md code")?.textContent, "docs");
  assert.equal(notes[1]!.querySelector(".md code")?.textContent, "docs");
  assert.ok(notes[1]!.textContent?.includes("is not available"));
  assert.ok(notes[1]!.textContent?.includes("FileNotFoundError"));
  // The answer is still there, after the news.
  assert.ok(ui.text('[data-id="turn-1"]').includes("Here is the answer."));
});

test("raw HTML in a notice is shown as text, never run", async () => {
  const turn = createTurn("hello", [], 1, "turn-1");
  applyEvent(turn, { type: "notice", text: "MCP server '<img src=x onerror=alert(1)>' is not available", level: "warn" }, 2);
  turn.status = "done";
  turn.finishedAt = 3;
  const ui = await open([turn]);
  assert.equal(ui.one('[data-id="turn-1"] .note.notice img'), null);
  assert.ok(ui.text('[data-id="turn-1"] .note.notice').includes("<img"));
});

test("while a server starts the status line says what is happening, and a warning is not mistaken for it", async () => {
  const running = createTurn("hello", [], Date.now(), "turn-r");
  applyEvent(running, { type: "notice", text: progress, level: "info" });
  const starting = await open([running], { ...baseState, busy: true });
  assert.equal(starting.text("#live-status .live-detail"), "Starting MCP server docs (process)", "the name without its quotes or dots");

  const failed = createTurn("hello", [], Date.now(), "turn-f");
  applyEvent(failed, { type: "notice", text: down, level: "warn" });
  const warned = await open([failed], { ...baseState, busy: true });
  assert.equal(warned.one("#live-status .live-detail"), null, "a warning stays in the transcript, not in the status line");

  const working = createTurn("hello", [], Date.now(), "turn-w");
  applyEvent(working, { type: "notice", text: progress, level: "info" });
  applyEvent(working, { type: "text_delta", text: "thinking out loud" });
  const answering = await open([working], { ...baseState, busy: true });
  assert.equal(answering.one("#live-status .live-detail"), null, "once the answer starts, the start is old news");
});
