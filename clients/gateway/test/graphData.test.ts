import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  RECENT_LIMIT,
  applyTrafficTo,
  deriveNodes,
  edgeOf,
  emptyGraph,
  neighboursOf,
  pairMessages,
  statsOf,
  tipText,
  totals,
} from "../src/lib/graphData";
import { applyGraph, applyTraffic, graph, graphUi, loadGraph, onTraffic, replay, resetGraph } from "../src/stores/graph";
import type { GraphData, GraphMessage } from "../src/types";

function message(id: number, from: string, to: string | { group: string; recipients: string[] }, text = `m${id}`): GraphMessage {
  const group = typeof to === "object";
  return {
    id,
    ts: 1000 + id,
    from: { session_id: from, handle: `@${from}`, title: from },
    to: group ? { kind: "group", name: to.group } : { kind: "session", session_id: to, handle: `@${to}`, title: to },
    recipients: group ? to.recipients : [to],
    text,
    via: "agent",
    hops: 0,
    mode: "steer",
    status: "delivered",
    disposition: "steered",
  };
}

function data(): GraphData {
  return {
    sessions: [
      { session_id: "a", handle: "@a", title: "A", workspace: "/w/alpha", status: "idle", kind: "zettcode" },
      { session_id: "b", handle: "@b", title: "B", workspace: "/w/beta", status: "working", kind: "zettcode" },
      { session_id: "c", handle: "@c", title: "C", workspace: "/w/gamma", status: "idle", kind: "external" },
    ],
    groups: [{ name: "team", members: ["a", "b", "c"], created: 900 }],
    edges: [{ a: "a", b: "b", count: 2, last: 1002 }],
    recent: [message(1, "a", "b"), message(2, "b", "a")],
  };
}

afterEach(() => {
  resetGraph();
  graphUi.replay = null;
  graphUi.spotlight = null;
});

test("a one-to-one message raises its pair's total, whichever way it goes, and keeps the later time", () => {
  const d = data();
  assert.equal(applyTrafficTo(d, message(3, "b", "a")), true);
  assert.equal(d.edges.length, 1);
  assert.equal(edgeOf(d, "b", "a")?.count, 3);
  assert.equal(edgeOf(d, "a", "b")?.last, 1003);
  applyTrafficTo(d, message(4, "a", "c"));
  assert.equal(d.edges.length, 2);
  assert.deepEqual(edgeOf(d, "c", "a"), { a: "a", b: "c", count: 1, last: 1004 });
});

test("a group message is in the feed and not in the pair totals", () => {
  const d = data();
  applyTrafficTo(d, message(3, "a", { group: "team", recipients: ["b", "c"] }));
  assert.equal(d.recent.length, 3);
  assert.equal(d.edges[0]!.count, 2);
  assert.equal(d.edges.length, 1);
  assert.equal(totals(d).messages, 2 + 1);
});

test("a message the feed already holds is not counted twice", () => {
  const d = data();
  assert.equal(applyTrafficTo(d, message(2, "b", "a")), false);
  assert.equal(d.edges[0]!.count, 2);
  assert.equal(d.recent.length, 2);
});

test("the feed keeps the latest fifty, oldest first", () => {
  const d = emptyGraph();
  for (let id = 1; id <= RECENT_LIMIT + 7; id += 1) applyTrafficTo(d, message(id, "a", "b"));
  assert.equal(d.recent.length, RECENT_LIMIT);
  assert.equal(d.recent[0]!.id, 8);
  assert.equal(d.recent[RECENT_LIMIT - 1]!.id, RECENT_LIMIT + 7);
  assert.equal(d.edges[0]!.count, RECENT_LIMIT + 7);
});

test("a session that is gone but in the latest traffic is a ghost, and one that is not in it is no node", () => {
  const d = data();
  d.recent.push(message(3, "gone", "a"));
  d.recent.push(message(4, "a", "also-gone"));
  const nodes = deriveNodes(d);
  assert.deepEqual(nodes.map((n) => n.session_id), ["a", "b", "c", "gone", "also-gone"]);
  assert.equal(nodes.find((n) => n.session_id === "gone")?.ghost, true);
  assert.equal(nodes.find((n) => n.session_id === "gone")?.handle, "@gone");
  assert.equal(nodes.find((n) => n.session_id === "also-gone")?.handle, "@also-gone");
  assert.equal(nodes.find((n) => n.session_id === "a")?.ghost, false);
  assert.equal(deriveNodes(data()).length, 3);
});

test("a ghost without a name falls back to the start of its id", () => {
  const d = emptyGraph();
  d.recent.push(message(1, "0123456789abcdef", { group: "g", recipients: ["fedcba9876543210"] }));
  const nodes = deriveNodes(d);
  assert.deepEqual(nodes.map((n) => n.handle), ["@0123456789abcdef", "fedcba98"]);
});

test("a node's numbers come from the feed and the pair totals", () => {
  const d = data();
  applyTrafficTo(d, message(3, "a", { group: "team", recipients: ["b", "c"] }));
  const a = statsOf(d, "a");
  assert.equal(a.sent, 2);
  assert.equal(a.received, 1);
  assert.equal(a.exchanged, 2);
  assert.deepEqual(a.groups, ["team"]);
  assert.equal(a.last?.id, 3);
  assert.equal(statsOf(d, "c").sent, 0);
  assert.equal(statsOf(d, "c").last?.id, 3);
  assert.deepEqual([...neighboursOf(d, "a")], ["b"]);
});

test("the last messages of a pair are the newest first and only theirs", () => {
  const d = data();
  applyTrafficTo(d, message(3, "a", "c"));
  applyTrafficTo(d, message(4, "a", "b"));
  applyTrafficTo(d, message(5, "a", { group: "team", recipients: ["b"] }));
  assert.deepEqual(pairMessages(d, "b", "a", 2).map((m) => m.id), [4, 2]);
  assert.deepEqual(pairMessages(d, "a", "b", 9).map((m) => m.id), [4, 2, 1]);
});

test("a tooltip shows at most 600 characters of a message", () => {
  assert.equal(tipText(message(1, "a", "b", "x".repeat(600))).length, 600);
  const cut = tipText(message(1, "a", "b", "x".repeat(900)));
  assert.equal(cut.length, 601);
  assert.ok(cut.endsWith("…"));
});

test("the store applies a traffic event in place and tells the listeners once", () => {
  applyGraph(data());
  const heard: number[] = [];
  const stop = onTraffic((m) => heard.push(m.id));
  applyTraffic(message(3, "a", "b"));
  applyTraffic(message(3, "a", "b"));
  stop();
  applyTraffic(message(4, "a", "b"));
  assert.deepEqual(heard, [3]);
  assert.equal(graph.edges[0]!.count, 4);
  assert.deepEqual(graph.recent.map((m) => m.id), [1, 2, 3, 4]);
});

test("a read through the API fills the store, and a message that came in while it was on the way is not lost", async () => {
  const real = globalThis.fetch;
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  globalThis.fetch = (async (url: string) => {
    assert.equal(url, "/api/graph");
    await gate;
    return new Response(JSON.stringify(data()), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  try {
    const loading = loadGraph();
    applyTraffic(message(1, "a", "b")); // already in the answer
    applyTraffic(message(3, "a", "b")); // newer than the answer
    release!();
    await loading;
    assert.equal(graph.loaded, true);
    assert.equal(graph.failed, false);
    assert.equal(graph.sessions.length, 3);
    assert.deepEqual(graph.recent.map((m) => m.id), [1, 2, 3]);
    assert.equal(graph.edges[0]!.count, 3);
  } finally {
    globalThis.fetch = real;
  }
});

test("a failed read is remembered, so the page can say so", async () => {
  const real = globalThis.fetch;
  globalThis.fetch = (async () => new Response("{}", { status: 500 })) as typeof fetch;
  try {
    await assert.rejects(loadGraph());
    assert.equal(graph.failed, true);
  } finally {
    globalThis.fetch = real;
  }
});

test("replaying a message asks the page to play it and lights its nodes for a moment", () => {
  const m = message(9, "a", "b");
  replay(m);
  assert.equal(graphUi.replay?.message.id, 9);
  assert.equal(graphUi.spotlight?.id, 9);
  const first = graphUi.replay!.n;
  replay(m);
  assert.equal(graphUi.replay!.n, first + 1);
  graphUi.spotlight = null;
});
