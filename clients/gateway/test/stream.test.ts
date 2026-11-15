import assert from "node:assert/strict";
import { test } from "node:test";
import { applyStream, resetStreams, seedStream, streamMark, streams } from "../src/stores/stream";

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

test("a read that was asked before a turn ended does not bring the turn back", () => {
  resetStreams();
  applyStream("s", { kind: "begin" });
  const mark = streamMark("s");
  applyStream("s", { kind: "end" });
  seedStream("s", { text: "done", thinking: false, tools: [] }, mark);
  assert.equal("s" in streams, false);

  seedStream("s", { text: "running", thinking: false, tools: [] }, streamMark("s"));
  assert.equal(streams.s?.text, "running");
});

test("a turn read from the gateway does not replace pieces that have already arrived", () => {
  resetStreams();
  seedStream("a", { text: "from a read", thinking: false, tools: [] });
  applyStream("b", { kind: "text", text: "newer" });
  seedStream("b", { text: "older read", thinking: false, tools: [] });

  assert.equal(streams.a?.text, "from a read");
  assert.equal(streams.b?.text, "newer");
});

test("a snapshot of a numbered turn whose end was heard is refused, whenever the read was asked", () => {
  resetStreams();
  applyStream("n", { kind: "begin", turn: 4 });
  applyStream("n", { kind: "end", turn: 4 });
  seedStream("n", { turn: 4, text: "done", thinking: false, tools: [] });
  assert.equal("n" in streams, false);

  seedStream("n", { turn: 5, text: "next", thinking: false, tools: [] });
  assert.equal(streams.n?.text, "next");
});

test("the end of an older turn leaves a newer one running, and a late piece does not start the old one again", () => {
  resetStreams();
  applyStream("m", { kind: "begin", turn: 7 });
  applyStream("m", { kind: "end", turn: 6 });
  assert.equal(streams.m?.turn, 7);

  applyStream("m", { kind: "end", turn: 7 });
  applyStream("m", { kind: "text", text: "late", turn: 7 });
  assert.equal("m" in streams, false);
});

test("a gateway that starts counting again is heard after the socket reconnects", () => {
  resetStreams();
  applyStream("r", { kind: "begin", turn: 9 });
  applyStream("r", { kind: "end", turn: 9 });
  resetStreams();
  applyStream("r", { kind: "begin", turn: 1 });
  assert.equal(streams.r?.turn, 1);
});
