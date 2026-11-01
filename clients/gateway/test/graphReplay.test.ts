import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  buildReplay,
  compress,
  due,
  fit30,
  formatSpan,
  histogram,
  recentTail,
  stateAt,
  windowFor,
} from "../src/lib/graphReplay";
import { exitReplay, graph, graphReplay, loadReplay, pause, play, seek, setSpeed, tick, toggleSkip } from "../src/stores/graph";
import type { GraphMessage } from "../src/types";

function msg(id: number, ts: number, from: string, to: string | { group: string; recipients: string[] }): GraphMessage {
  const group = typeof to === "object";
  return {
    id,
    ts,
    from: { session_id: from, handle: `@${from}`, title: from },
    to: group ? { kind: "group", name: to.group } : { kind: "session", session_id: to },
    recipients: group ? to.recipients : [to],
    text: `m${id}`,
    via: "agent",
    hops: 0,
    mode: "steer",
    status: "delivered",
    disposition: "steered",
  };
}

const all = [msg(3, 130, "b", "a"), msg(1, 110, "a", "b"), msg(2, 111, "a", "b"), msg(4, 190, "c", { group: "g", recipients: ["a", "b"] })];
const replay = () => buildReplay(all, 100, 200);

afterEach(() => exitReplay());

test("buildReplay sorts and bounds", () => {
  const r = replay();
  assert.deepEqual(r.messages.map((m) => m.id), [1, 2, 3, 4]);
  assert.equal(r.duration, 100);
  assert.equal(buildReplay(all, 150, 160).messages.length, 0);
});

test("stateAt counts 1:1 only and shrinks when scrubbing back", () => {
  const r = replay();
  const late = stateAt(r, 195);
  assert.equal(late.shown.length, 4);
  assert.deepEqual(late.edges.map((e) => [e.a, e.b, e.count]), [["a", "b", 3]]);
  assert.deepEqual([...late.groupsTouched], ["g"]);
  const early = stateAt(r, 111);
  assert.equal(early.edges[0]?.count, 2);
  assert.deepEqual([...early.shownIds].sort(), ["a", "b"]);
  assert.deepEqual([...early.sessionIds].sort(), ["a", "b", "c"]);
  assert.equal(stateAt(r, 50).edges.length, 0);
});

test("silence skipping squeezes long gaps", () => {
  const r = replay();
  const plain = compress(r, 1, false);
  assert.equal(plain.playbackDuration, 100);
  const skip = compress(r, 1, true);
  // gaps: 10, 1, 19, 60, 10 -> 2 + 1 + 2 + 2 + 2
  assert.equal(skip.playbackDuration, 9);
  assert.equal(skip.toPlayback(111), 3);
  assert.equal(skip.toReal(3), 111);
  assert.equal(skip.skippedBefore(200), 91);
  // at 10x a gap is only skipped beyond 20 real seconds
  assert.equal(compress(r, 10, true).segments.filter((s) => s.skipped).length, 1);
});

test("speed and fit30", () => {
  const r = replay();
  assert.equal(compress(r, 4, false).playbackDuration, 25);
  assert.equal(fit30(r), 100 / 30);
});

test("due and recentTail windows", () => {
  const r = replay();
  assert.deepEqual(due(r, 110, 130).map((m) => m.id), [2, 3]);
  assert.deepEqual(due(r, 0, 110).map((m) => m.id), [1]);
  assert.deepEqual(recentTail(r, 130, 20).map((m) => m.id), [2, 3]);
});

test("histogram and empty window", () => {
  assert.deepEqual(histogram(replay(), 4), [2, 1, 0, 1]);
  const empty = buildReplay([], 100, 100);
  assert.deepEqual(histogram(empty, 3), [0, 0, 0]);
  assert.equal(compress(empty, 1, true).playbackDuration, 0);
  assert.equal(stateAt(empty, 100).shown.length, 0);
});

test("windowFor and formatSpan", () => {
  assert.deepEqual(windowFor("1h", 10000, null), { since: 6400, until: 10000 });
  assert.deepEqual(windowFor("all", 10000, [500, 9000]), { since: 500, until: 10000 });
  assert.deepEqual(windowFor("all", 10000, null), { since: 10000, until: 10000 });
  assert.equal(formatSpan(3 * 3600 + 12 * 60), "3h 12m");
  assert.equal(formatSpan(45), "45s");
});

test("store: load, tick, seek, exit", async () => {
  const real = globalThis.fetch;
  let url = "";
  globalThis.fetch = (async (u: string) => {
    url = String(u);
    return new Response(JSON.stringify({ messages: all, span: [110, 190], now: 200 }), { status: 200 });
  }) as typeof fetch;
  try {
    await loadReplay(100, 200);
  } finally {
    globalThis.fetch = real;
  }
  assert.match(url, /\/api\/graph\/timeline\?since=100&until=200&limit=2000/);
  assert.equal(graphReplay.status, "ready");
  assert.equal(graphReplay.mode, "replay");
  assert.equal(graph.liveMuted, true);
  assert.deepEqual(tick(5), []);
  setSpeed(1);
  toggleSkip();
  assert.equal(graphReplay.skipSilence, false);
  play();
  assert.deepEqual(tick(11).map((m) => m.id), [1, 2]);
  assert.equal(graphReplay.playhead, 111);
  setSpeed(10);
  assert.deepEqual(tick(2).map((m) => m.id), [3]);
  seek(105);
  assert.equal(graphReplay.playhead, 105);
  pause();
  assert.deepEqual(tick(5), []);
  play();
  tick(1000);
  assert.equal(graphReplay.playing, false);
  assert.equal(graphReplay.playhead, 200);
  exitReplay();
  assert.equal(graphReplay.mode, "live");
  assert.equal(graph.liveMuted, false);
  assert.equal(graphReplay.replay, null);
});

test("store: a failed load reports an error", async () => {
  const real = globalThis.fetch;
  globalThis.fetch = (async () => new Response("{}", { status: 500 })) as typeof fetch;
  try {
    await loadReplay(1, 2);
  } finally {
    globalThis.fetch = real;
  }
  assert.equal(graphReplay.status, "error");
  assert.ok(graphReplay.error);
});
