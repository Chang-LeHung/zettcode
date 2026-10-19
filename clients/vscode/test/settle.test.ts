import assert from "node:assert/strict";
import test from "node:test";

import { applyEvent, cancelTurn, createTurn, failTurn, findTool } from "../src/core/state.js";

test("a stopped turn leaves no tool spinning", () => {
  const turn = createTurn("go");
  applyEvent(turn, { type: "tool_started", call_id: "c1", name: "bash", arguments: { command: "sleep 99" } }, 1000);
  assert.equal(findTool(turn, "c1")?.status, "running");
  cancelTurn(turn, 5000);
  assert.equal(findTool(turn, "c1")?.status, "skipped");
  assert.equal(findTool(turn, "c1")?.finishedAt, 5000);
});

test("a failed turn leaves no tool spinning either", () => {
  const turn = createTurn("go");
  applyEvent(turn, { type: "tool_started", call_id: "c2", name: "bash", arguments: {} }, 1000);
  failTurn(turn, "lost the connection", 2000);
  assert.equal(findTool(turn, "c2")?.status, "skipped");
});

test("a tool that finished before the stop keeps its result", () => {
  const turn = createTurn("go");
  applyEvent(turn, { type: "tool_started", call_id: "c3", name: "read_file", arguments: {} }, 1000);
  applyEvent(turn, { type: "tool_finished", call_id: "c3", name: "read_file", output: "ok", ok: true, skipped: false }, 1500);
  cancelTurn(turn, 3000);
  assert.equal(findTool(turn, "c3")?.status, "ok");
});
