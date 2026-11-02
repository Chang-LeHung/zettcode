import assert from "node:assert/strict";
import { test } from "node:test";
import { applyGraph, applyTraffic, graph, loadGraph, loadOlder, resetGraph } from "../src/stores/graph";
import type { GraphMessage } from "../src/types";

function msg(id: number, to = "b"): GraphMessage {
  return {
    id,
    ts: id,
    from: { session_id: "a", handle: "@a", title: "a" },
    to: { kind: "session", session_id: to, handle: `@${to}`, title: to },
    recipients: [to],
    text: `m${id}`,
    via: "agent",
    hops: 0,
    mode: "steer",
    status: "delivered",
    disposition: "started",
  };
}

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => msg(from + i));

async function withOlder<T>(pages: Record<number, { messages: GraphMessage[]; more: boolean }>, run: (urls: string[]) => Promise<T>): Promise<T> {
  const real = globalThis.fetch;
  const urls: string[] = [];
  globalThis.fetch = (async (u: string) => {
    urls.push(String(u));
    const before = Number(new URL(String(u), "http://x").searchParams.get("before"));
    return new Response(JSON.stringify(pages[before] ?? { messages: [], more: false }), { status: 200 });
  }) as typeof fetch;
  try {
    return await run(urls);
  } finally {
    globalThis.fetch = real;
  }
}

test("a full first page says there may be more, a short one says there is not", () => {
  resetGraph();
  applyGraph({ sessions: [], groups: [], edges: [], recent: range(51, 100) });
  assert.equal(graph.more, true);
  applyGraph({ sessions: [], groups: [], edges: [], recent: range(1, 3) });
  assert.equal(graph.more, false);
});

test("older messages are put in front of the feed, from the oldest id it holds, and stop when none remain", async () => {
  resetGraph();
  applyGraph({ sessions: [], groups: [], edges: [], recent: range(51, 100) });
  await withOlder({ 51: { messages: range(1, 50), more: false } }, async (urls) => {
    await loadOlder();
    assert.match(urls[0]!, /\/api\/graph\/older\?before=51&limit=50/);
    await loadOlder();
    assert.equal(urls.length, 1, "nothing is asked once the start is reached");
  });
  assert.deepEqual(graph.feed.map((m) => m.id).slice(0, 3), [1, 2, 3]);
  assert.equal(graph.feed.length, 100);
  assert.equal(graph.more, false);
});

test("live messages join the end of a feed that was scrolled back, without repeating one it holds", async () => {
  resetGraph();
  applyGraph({ sessions: [], groups: [], edges: [], recent: range(51, 100) });
  await withOlder({ 51: { messages: range(1, 50), more: true } }, () => loadOlder());
  applyTraffic(msg(101));
  applyTraffic(msg(101));

  assert.equal(graph.feed.length, 101);
  assert.equal(graph.feed.at(-1)!.id, 101);
  assert.equal(graph.more, true);
});

test("a failed load is reported, keeps what is shown, and can be tried again", async () => {
  resetGraph();
  applyGraph({ sessions: [], groups: [], edges: [], recent: range(51, 100) });
  const real = globalThis.fetch;
  globalThis.fetch = (async () => new Response("{}", { status: 500 })) as typeof fetch;
  try {
    await loadOlder();
  } finally {
    globalThis.fetch = real;
  }
  assert.equal(graph.olderFailed, true);
  assert.equal(graph.loadingOlder, false);
  assert.equal(graph.feed.length, 50);
  assert.equal(graph.more, true);
});

test("a message that arrives while a read is on the way is kept once, and counted once", async () => {
  resetGraph();
  const real = globalThis.fetch;
  let release: (() => void) | undefined;
  globalThis.fetch = (async () => {
    await new Promise<void>((resolve) => (release = resolve));
    return new Response(JSON.stringify({ sessions: [], groups: [], edges: [], recent: range(1, 3) }), { status: 200 });
  }) as typeof fetch;
  try {
    const reading = loadGraph();
    await new Promise((resolve) => setTimeout(resolve, 0));
    applyTraffic(msg(4)); // newer than anything the read will return
    applyTraffic(msg(2)); // already in what the read returns
    release?.();
    await reading;
  } finally {
    globalThis.fetch = real;
  }

  assert.deepEqual(graph.feed.map((m) => m.id), [1, 2, 3, 4]);
  // The read is the broker's account up to message 3, so only message 4 (newer than it) is counted again, and once.
  assert.equal(graph.edges.find((e) => e.a === "a" && e.b === "b")?.count, 1);
});

test("a replay of a window that held more than could be read says its start is missing, and says it no more once left", async () => {
  const { exitReplay, graphReplay, loadReplay } = await import("../src/stores/graph");
  const real = globalThis.fetch;
  const asked: string[] = [];
  let answer: { messages: GraphMessage[]; truncated?: boolean } = { messages: range(5, 9), truncated: true };
  globalThis.fetch = (async (u: string) => {
    asked.push(String(u));
    return new Response(JSON.stringify({ ...answer, span: [1, 9], now: 10 }), { status: 200 });
  }) as typeof fetch;
  try {
    await loadReplay(1, 9);
    assert.match(asked[0]!, /limit=20000/, "a replay asks for a whole stretch, not a page");
    assert.equal(graphReplay.status, "ready");
    assert.equal(graphReplay.truncated, true);
    assert.deepEqual(graphReplay.replay?.messages.map((m) => m.id), [5, 6, 7, 8, 9], "what it holds is the end of the window");

    exitReplay();
    assert.equal(graphReplay.truncated, false);

    answer = { messages: range(1, 3) }; // an answer from a broker that does not say
    await loadReplay(1, 9);
    assert.equal(graphReplay.truncated, false);
    exitReplay();
  } finally {
    globalThis.fetch = real;
  }
});
