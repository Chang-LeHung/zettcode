import assert from "node:assert/strict";
import { test } from "node:test";
import { edgeCurve, type Point } from "../src/lib/graph";
import { FxEngine } from "../src/lib/graphFx";
import type { GraphMessage } from "../src/types";

const POINTS: Record<string, Point> = { a: { x: 0, y: 0 }, b: { x: 200, y: 0 }, c: { x: 0, y: 200 }, d: { x: 200, y: 200 } };
const curveOf = (from: string, to: string) => {
  const a = POINTS[from];
  const b = POINTS[to];
  return a && b ? edgeCurve(from, a, to, b) : null;
};

function message(to: "b" | { group: string; recipients: string[] }, via: GraphMessage["via"] = "agent"): GraphMessage {
  const group = typeof to === "object";
  return {
    id: 1,
    ts: 1,
    from: { session_id: "a", handle: "@a", title: "" },
    to: group ? { kind: "group", name: to.group } : { kind: "session", session_id: to },
    recipients: group ? to.recipients : [to],
    text: "hi",
    via,
    hops: 0,
    mode: "steer",
    status: "delivered",
    disposition: "steered",
  };
}

test("a packet leaves the sender, arrives at the recipient and is gone, and the loop may then stop", () => {
  const fx = new FxEngine({ duration: 1000 });
  assert.equal(fx.spawn(message("b"), 0), 1);
  assert.equal(fx.busy, true);

  const start = fx.step(0, curveOf).packets[0]!;
  assert.deepEqual([start.x, start.y], [0, 0]);
  const middle = fx.step(500, curveOf).packets[0]!;
  assert.ok(middle.x > 90 && middle.x < 110);
  const end = fx.step(999, curveOf).packets[0]!;
  assert.ok(end.x > 195);
  assert.equal(end.via, "agent");
  assert.equal(end.trail.length, 6);

  assert.equal(fx.step(1000, curveOf).packets.length, 0);
  fx.step(3000, curveOf);
  assert.equal(fx.busy, false);
});

test("the sender flashes at once and the recipient ripples when the packet lands", () => {
  const fx = new FxEngine({ duration: 1000 });
  fx.spawn(message("b"), 0);
  const early = fx.step(10, curveOf).pulses;
  assert.deepEqual(early.map((p) => p.kind).sort(), ["edge", "flash"]);
  const landed = fx.step(1100, curveOf).pulses;
  assert.ok(landed.some((p) => p.kind === "ripple" && p.target === "b" && p.progress > 0));
  assert.ok(!landed.some((p) => p.kind === "flash"));
});

test("a group message fans out one packet to each recipient and pulses the group once", () => {
  const fx = new FxEngine();
  assert.equal(fx.spawn(message({ group: "team", recipients: ["b", "c", "d", "a"] }), 0), 3);
  const frame = fx.step(450, curveOf);
  assert.equal(frame.packets.length, 3);
  assert.deepEqual(frame.packets.map((p) => p.to).sort(), ["b", "c", "d"]);
  assert.equal(frame.pulses.filter((p) => p.kind === "hull").length, 1);
  assert.equal(frame.pulses.filter((p) => p.kind === "hull")[0]!.target, "team");
  assert.equal(frame.pulses.filter((p) => p.kind === "edge").length, 0);
});

test("no more than the cap of packets are in flight, and the rest only ripple", () => {
  const fx = new FxEngine({ maxPackets: 5 });
  for (let i = 0; i < 4; i += 1) fx.spawn(message({ group: "g", recipients: ["b", "c"] }), 0);
  assert.equal(fx.inFlight, 5);
  const ripples = fx.step(10, curveOf).pulses.filter((p) => p.kind === "ripple");
  assert.equal(ripples.length, 3);
});

test("with reduced motion nothing travels: the nodes and the line only flash", () => {
  const fx = new FxEngine();
  assert.equal(fx.spawn(message("b"), 0, true), 0);
  const frame = fx.step(10, curveOf);
  assert.equal(frame.packets.length, 0);
  assert.deepEqual(frame.pulses.map((p) => p.kind).sort(), ["edge", "flash", "ripple"]);
  assert.ok(frame.pulses.every((p) => !p.grow));
});

test("a packet between nodes the page does not know is skipped, and clearing stops everything", () => {
  const fx = new FxEngine();
  const m = message("b");
  m.recipients = ["nobody"];
  fx.spawn(m, 0);
  assert.equal(fx.step(100, curveOf).packets.length, 0);
  fx.clear();
  assert.equal(fx.busy, false);
});
