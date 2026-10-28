import assert from "node:assert/strict";
import { test } from "node:test";
import { applyStream, resetStreams, seedStream, streams } from "../src/stores/stream";

test("a turn is built from its pieces and dropped when it ends", () => {
  resetStreams();
  applyStream("s", { kind: "begin" });
  applyStream("s", { kind: "thinking" });
  applyStream("s", { kind: "tool", id: "c", name: "bash", brief: "ls" });
  applyStream("s", { kind: "tool_end", id: "c", ok: true });
  applyStream("s", { kind: "text", text: "Hel" });
  applyStream("s", { kind: "text", text: "lo" });

  assert.deepEqual(streams.s, { text: "Hello", thinking: false, tools: [{ id: "c", name: "bash", brief: "ls", ok: true }] });
  applyStream("s", { kind: "end" });
  assert.equal(streams.s, undefined);
});

test("a piece that arrives before its begin still starts a turn, and a begin starts it afresh", () => {
  resetStreams();
  applyStream("s", { kind: "text", text: "late" });
  assert.equal(streams.s?.text, "late");

  applyStream("s", { kind: "begin" });
  assert.equal(streams.s?.text, "");
});

test("a turn read from the gateway does not replace pieces that have already arrived", () => {
  resetStreams();
  seedStream("a", { text: "from a read", thinking: false, tools: [] });
  applyStream("b", { kind: "text", text: "newer" });
  seedStream("b", { text: "older read", thinking: false, tools: [] });

  assert.equal(streams.a?.text, "from a read");
  assert.equal(streams.b?.text, "newer");
});
