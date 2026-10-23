import assert from "node:assert/strict";
import test from "node:test";

import type { Message, RunResult, Usage } from "../../typescript/src/types.js";
import {
  applyEvent,
  cancelTurn,
  createTurn,
  failTurn,
  findTool,
  findTurnByCall,
  finishTurn,
  MAX_TOOL_OUTPUT,
  markAnswer,
  markApproval,
  newTurnId,
  restoreTurns,
  type ApprovalBlock,
  type QuestionBlock,
} from "../src/core/state.js";

const usage: Usage = {
  input_tokens: 10,
  output_tokens: 4,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  seconds: 1,
  requests: 1,
  context_tokens: 14,
};

function result(text: string): RunResult {
  return {
    text,
    session_id: "session-1",
    usage,
    tools: [],
    stop: null,
    stop_message: null,
    questions: [],
  };
}

test("text and reasoning deltas coalesce into their own blocks", () => {
  const turn = createTurn("hello", [], 1000, "t");
  applyEvent(turn, { type: "text_delta", text: "Hel" }, 1100);
  applyEvent(turn, { type: "text_delta", text: "lo" }, 1200);
  applyEvent(turn, { type: "reasoning_delta", text: "thinking" }, 1300);
  applyEvent(turn, { type: "text_delta", text: " again" }, 1400);
  assert.equal(turn.blocks.length, 3);
  assert.deepEqual(turn.blocks[0], { kind: "text", text: "Hello" });
  assert.deepEqual(turn.blocks[1], { kind: "reasoning", text: "thinking" });
  assert.deepEqual(turn.blocks[2], { kind: "text", text: " again" });
});

test("a tool starts running and finishes in place", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(
    turn,
    { type: "tool_started", call_id: "c1", name: "read_file", arguments: { path: "a.py" } },
    1100,
  );
  const running = findTool(turn, "c1");
  assert.equal(running?.status, "running");
  applyEvent(
    turn,
    { type: "tool_finished", call_id: "c1", name: "read_file", output: "body", ok: true, skipped: false },
    1500,
  );
  assert.equal(turn.blocks.length, 1);
  assert.equal(running?.status, "ok");
  assert.equal(running?.output, "body");
  assert.equal(running?.finishedAt, 1500);
});

test("a hosted tool is a row like any other, and its query arrives with its end", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(turn, { type: "server_tool_started", call_id: "s1", name: "web_search", arguments: {} }, 1100);
  applyEvent(
    turn,
    {
      type: "server_tool_finished",
      call_id: "s1",
      name: "web_search",
      arguments: { query: "zettcode github" },
      output: "1 page\n- Page 1 — https://example.com/1",
      ok: true,
    },
    1600,
  );
  const tool = findTool(turn, "s1");
  assert.equal(turn.blocks.length, 1);
  assert.equal(tool?.status, "ok");
  assert.deepEqual(tool?.arguments, { query: "zettcode github" });
  assert.match(tool?.output ?? "", /example\.com\/1/);
  assert.equal(tool?.finishedAt, 1600);
});

test("a hosted tool that failed says so", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(
    turn,
    { type: "server_tool_finished", call_id: "s1", name: "web_search", arguments: {}, output: "max_uses", ok: false },
    1200,
  );

  assert.equal(findTool(turn, "s1")?.status, "failed");
});

test("a skipped or failed tool keeps its ending", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(turn, { type: "tool_finished", call_id: "a", name: "bash", output: "", ok: false, skipped: false });
  applyEvent(turn, { type: "tool_finished", call_id: "b", name: "bash", output: "", ok: false, skipped: true });
  assert.equal(findTool(turn, "a")?.status, "failed");
  assert.equal(findTool(turn, "b")?.status, "skipped");
});

test("a runaway output is capped with a note", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(turn, {
    type: "tool_finished",
    call_id: "c",
    name: "bash",
    output: "x".repeat(MAX_TOOL_OUTPUT + 100),
    ok: true,
    skipped: false,
  });
  const tool = findTool(turn, "c");
  assert.ok(tool !== null);
  assert.ok(tool.output.length < MAX_TOOL_OUTPUT + 200);
  assert.ok(tool.output.includes("left out"));
});

test("an approval is pending until someone answers it", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(
    turn,
    { type: "approval_requested", call_id: "c1", command: "pytest -q", approved: null },
    1100,
  );
  const block = turn.blocks.find((candidate): candidate is ApprovalBlock => candidate.kind === "approval");
  assert.equal(block?.approved, null);
  markApproval(turn, "c1", true);
  assert.equal(block?.approved, true);
});

test("a question records the answer", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(
    turn,
    {
      type: "question_asked",
      call_id: "q1",
      question: "Which database?",
      options: ["sqlite", "postgres"],
      allow_multiple: false,
      answered: false,
    },
    1100,
  );
  const block = turn.blocks.find((candidate): candidate is QuestionBlock => candidate.kind === "question");
  assert.equal(block?.answered, false);
  markAnswer(turn, "q1", "sqlite");
  assert.equal(block?.answered, true);
  assert.equal(findTurnByCall([turn], "q1"), turn);
});

test("compaction is one block that finishes", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(turn, { type: "compaction_started" }, 1100);
  applyEvent(turn, { type: "compaction_finished", applied: true, summary: "the story so far" }, 1200);
  assert.deepEqual(turn.blocks, [{ kind: "compaction", running: false, applied: true, summary: "the story so far" }]);
});

test("finishing does not repeat streamed text", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(turn, { type: "text_delta", text: "Hello" }, 1100);
  finishTurn(turn, result("Hello"), 2000);
  const text = turn.blocks.filter((block) => block.kind === "text");
  assert.equal(text.length, 1);
  assert.deepEqual(text[0], { kind: "text", text: "Hello" });
  assert.equal(turn.status, "done");
  assert.equal(turn.finishedAt, 2000);
  assert.deepEqual(turn.usage, usage);
});

test("a result with no streamed text still fills the turn", () => {
  const turn = createTurn("go", [], 1000, "t");
  finishTurn(turn, result("Answer"), 2000);
  assert.deepEqual(turn.blocks, [{ kind: "text", text: "Answer" }]);
});

test("failed, stopped and noticed turns say so", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(turn, { type: "notice", text: "an MCP server is down" });
  applyEvent(turn, { type: "steered", text: "also the docs" });
  applyEvent(turn, { type: "model_stopped", reason: "max_output", message: "output limit" });
  applyEvent(turn, { type: "event", name: "future_thing" });
  assert.ok(turn.blocks.some((block) => block.kind === "notice" && block.text.includes("MCP")));
  assert.ok(turn.blocks.some((block) => block.kind === "steered" && block.text === "also the docs"));
  assert.deepEqual(turn.stop, { reason: "max_output", message: "output limit" });
  assert.ok(turn.blocks.some((block) => block.kind === "notice" && block.text.includes("future_thing")));
  failTurn(turn, "boom", 3000);
  assert.equal(turn.status, "failed");
  assert.equal(turn.error, "boom");
  cancelTurn(turn, 4000);
  assert.equal(turn.status, "cancelled");
});

test("history pairs a tool call with the message that carries its output", () => {
  const messages: Message[] = [
    { role: "user", text: "Fix it", tool_calls: [], tool_call_id: null, tool_name: null, ok: true, images: 0 },
    {
      role: "assistant",
      text: "I will look.",
      tool_calls: [
        { call_id: "c1", name: "read_file", arguments: { path: "a.py" }, output: "", ok: true, skipped: false },
      ],
      tool_call_id: null,
      tool_name: null,
      ok: true,
      images: 0,
    },
    {
      role: "tool",
      text: "the file",
      tool_calls: [],
      tool_call_id: "c1",
      tool_name: "read_file",
      ok: true,
      images: 0,
    },
    { role: "assistant", text: "Done.", tool_calls: [], tool_call_id: null, tool_name: null, ok: true, images: 0 },
  ];
  const turns = restoreTurns(messages, 5000);
  assert.equal(turns.length, 1);
  const turn = turns[0];
  assert.ok(turn !== undefined);
  assert.equal(turn.prompt, "Fix it");
  assert.equal(turn.status, "done");
  assert.deepEqual(
    turn.blocks.map((block) => block.kind),
    ["text", "tool", "text"],
  );
  const tool = findTool(turn, "c1");
  assert.equal(tool?.output, "the file");
  assert.equal(tool?.status, "ok");
  assert.equal(tool?.finishedAt, 5000);
});

test("history without a tool result still closes the row", () => {
  const messages: Message[] = [
    { role: "user", text: "go", tool_calls: [], tool_call_id: null, tool_name: null, ok: true, images: 0 },
    {
      role: "assistant",
      text: "",
      tool_calls: [
        { call_id: "c1", name: "glob", arguments: { pattern: "*.ts" }, output: "", ok: true, skipped: false },
      ],
      tool_call_id: null,
      tool_name: null,
      ok: true,
      images: 0,
    },
  ];
  const tool = findTool(restoreTurns(messages)[0] ?? createTurn(""), "c1");
  assert.equal(tool?.status, "ok");
});

test("a run that ends settles a request it left waiting", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(turn, { type: "approval_requested", call_id: "a", command: "rm x", approved: null });
  applyEvent(
    turn,
    {
      type: "question_asked",
      call_id: "q",
      question: "Which?",
      options: ["one"],
      allow_multiple: false,
      answered: false,
    },
  );
  finishTurn(turn, result("done"), 3000);
  const approval = turn.blocks.find((block): block is ApprovalBlock => block.kind === "approval");
  const question = turn.blocks.find((block): block is QuestionBlock => block.kind === "question");
  assert.equal(approval?.approved, false);
  assert.equal(question?.answered, true);
  assert.equal(question?.answer, null);
});

test("a tool ending settles a request on its call", () => {
  const turn = createTurn("go", [], 1000, "t");
  applyEvent(turn, { type: "approval_requested", call_id: "a", command: "rm x", approved: null });
  applyEvent(turn, { type: "tool_finished", call_id: "a", name: "bash", output: "", ok: false, skipped: false });
  const approval = turn.blocks.find((block): block is ApprovalBlock => block.kind === "approval");
  assert.equal(approval?.approved, false);
});

test("restored history keeps what each turn spent and how long it took", () => {
  const spent = (input: number, output: number, cached: number, seconds: number) => ({
    input_tokens: input,
    output_tokens: output,
    cache_read_tokens: cached,
    cache_write_tokens: 0,
    reasoning_tokens: 0,
    seconds,
    requests: 1,
    context_tokens: 0,
  });
  const base = { tool_calls: [], tool_call_id: null, tool_name: null, ok: true, images: 0 };
  const turns = restoreTurns(
    [
      { ...base, role: "user", text: "go" },
      { ...base, role: "assistant", text: "", usage: spent(1000, 40, 600, 2), seconds: 2 },
      { ...base, role: "tool", text: "ok", tool_call_id: "t", tool_name: "bash", seconds: 1.5 },
      { ...base, role: "assistant", text: "done", usage: spent(1200, 60, 1000, 3), seconds: 3 },
    ],
    10_000,
  );
  const turn = turns[0];
  assert.ok(turn?.usage);
  assert.equal(turn.usage.input_tokens, 2200);
  assert.equal(turn.usage.output_tokens, 100);
  assert.equal(turn.usage.cache_read_tokens, 1600);
  assert.equal(turn.usage.requests, 2);
  assert.equal(turn.usage.seconds, 5);
  assert.equal((turn.finishedAt ?? 0) - turn.startedAt, 6500);
});

test("a stored turn with no recorded usage has no receipt figures", () => {
  const base = { tool_calls: [], tool_call_id: null, tool_name: null, ok: true, images: 0 };
  const [turn] = restoreTurns([
    { ...base, role: "user", text: "hi" },
    { ...base, role: "assistant", text: "yo" },
  ]);
  assert.equal(turn?.usage, undefined);
});

test("turn ids are unique", () => {
  assert.notEqual(newTurnId("t"), newTurnId("t"));
});
