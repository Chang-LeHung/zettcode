import assert from "node:assert/strict";
import { test } from "node:test";
import {
  approach,
  clampTooltip,
  convexHull,
  curvePoint,
  distance,
  edgeCurve,
  edgeStyle,
  hueOfName,
  hullLabelAnchor,
  layoutCircle,
  pairKey,
  polygonPath,
  preview,
  roundedHull,
  sampleCurve,
} from "../src/lib/graph";

const near = (a: number, b: number, eps = 1e-6): void => assert.ok(Math.abs(a - b) < eps, `${a} is not ${b}`);
const SIZE = { width: 800, height: 600 };

test("the ring is laid out by id, so the order of arrival does not matter", () => {
  const a = layoutCircle(["c", "a", "b"], SIZE);
  const b = layoutCircle(["b", "c", "a"], SIZE);
  assert.deepEqual([...a.entries()], [...b.entries()]);
  assert.deepEqual([...a.keys()], ["a", "b", "c"]);
});

test("the first id sits at twelve o'clock and every id is the same distance from the middle", () => {
  const ring = layoutCircle(["a", "b", "c", "d"], SIZE, 100);
  const top = ring.get("a")!;
  near(top.x, 400);
  near(top.y, 300 - 200);
  for (const point of ring.values()) near(distance(point, { x: 400, y: 300 }), 200);
});

test("a session that joins moves the others along the ring only", () => {
  const before = layoutCircle(["a", "c"], SIZE);
  const after = layoutCircle(["a", "b", "c"], SIZE);
  assert.deepEqual(after.get("a"), before.get("a"));
  assert.notDeepEqual(after.get("c"), before.get("c"));
  assert.equal(after.size, 3);
});

test("one session sits in the middle, none give an empty ring, and a small stage does not make a negative radius", () => {
  assert.deepEqual(layoutCircle(["a"], SIZE).get("a"), { x: 400, y: 300 });
  assert.equal(layoutCircle([], SIZE).size, 0);
  const tiny = layoutCircle(["a", "b"], { width: 100, height: 100 }, 88);
  near(distance(tiny.get("a")!, tiny.get("b")!), 0);
});

test("an edge bends the same way whichever end it is drawn from", () => {
  const p = { x: 100, y: 100 };
  const q = { x: 300, y: 100 };
  const forward = edgeCurve("a", p, "b", q);
  const backward = edgeCurve("b", q, "a", p);
  assert.deepEqual(forward.c, backward.c);
  assert.deepEqual(backward.a, q);
  assert.notEqual(forward.c.y, 100);
});

test("sampling a curve gives its ends and a point on the way", () => {
  const curve = edgeCurve("a", { x: 0, y: 0 }, "b", { x: 100, y: 0 }, 0.2);
  const points = sampleCurve(curve, 10);
  assert.equal(points.length, 11);
  assert.deepEqual(points[0], { x: 0, y: 0 });
  assert.deepEqual(points[10], { x: 100, y: 0 });
  const mid = curvePoint(curve, 0.5);
  near(mid.x, 50);
  near(mid.y, 0.5 * curve.c.y, 1e-9);
  assert.deepEqual(points[5], mid);
  assert.equal(sampleCurve(curve, 0).length, 2);
});

test("a curve with no bend is a straight line", () => {
  const curve = edgeCurve("a", { x: 0, y: 0 }, "b", { x: 90, y: 30 }, 0);
  for (const p of sampleCurve(curve, 6)) near(p.y, p.x / 3);
});

test("the hull leaves out the points inside it and the ones along its sides", () => {
  const hull = convexHull([
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 10, y: 10 },
    { x: 0, y: 10 },
    { x: 5, y: 5 },
    { x: 5, y: 0 },
    { x: 0, y: 0 },
  ]);
  assert.equal(hull.length, 4);
  assert.deepEqual(convexHull([{ x: 1, y: 1 }]), [{ x: 1, y: 1 }]);
});

test("the rounded hull of one member is a disc and of two a capsule that holds both", () => {
  const disc = roundedHull([{ x: 50, y: 50 }], 20);
  for (const p of disc) near(distance(p, { x: 50, y: 50 }), 20);
  const capsule = roundedHull(
    [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
    ],
    20,
  );
  const xs = capsule.map((p) => p.x);
  near(Math.min(...xs), -20);
  near(Math.max(...xs), 120);
  const ys = capsule.map((p) => p.y);
  near(Math.min(...ys), -20);
  near(Math.max(...ys), 20);
});

test("the rounded hull of three members is at least `pad` from each of them on every side", () => {
  const members = [
    { x: 0, y: 0 },
    { x: 200, y: 0 },
    { x: 100, y: 150 },
  ];
  const hull = roundedHull(members, 30);
  for (const member of members) for (const p of hull) assert.ok(distance(p, member) >= 30 - 1e-6);
  assert.ok(polygonPath(hull).startsWith("M"));
  assert.ok(polygonPath(hull).endsWith("Z"));
  assert.equal(polygonPath([]), "");
});

test("a group's label goes on the outside of the ring, and straight up for a group in the middle", () => {
  const middle = { x: 400, y: 300 };
  const members = [
    { x: 600, y: 280 },
    { x: 620, y: 340 },
  ];
  const right = hullLabelAnchor(roundedHull(members, 30), members, middle);
  assert.ok(right.x > 640);
  const centre = [
    { x: 380, y: 300 },
    { x: 420, y: 300 },
  ];
  const up = hullLabelAnchor(roundedHull(centre, 30), centre, middle);
  assert.ok(up.y < 280);
});

test("a tooltip sits beside the pointer, flips at an edge and never leaves the view", () => {
  const view = { width: 400, height: 300 };
  const card = { width: 120, height: 80 };
  assert.deepEqual(clampTooltip({ x: 50, y: 50 }, card, view), { x: 64, y: 64 });
  assert.deepEqual(clampTooltip({ x: 380, y: 50 }, card, view), { x: 246, y: 64 });
  assert.deepEqual(clampTooltip({ x: 50, y: 290 }, card, view), { x: 64, y: 196 });
  const corner = clampTooltip({ x: 395, y: 295 }, card, view);
  assert.ok(corner.x >= 8 && corner.x + card.width <= 392);
  assert.ok(corner.y >= 8 && corner.y + card.height <= 292);
  const huge = clampTooltip({ x: 10, y: 10 }, { width: 900, height: 900 }, view);
  assert.deepEqual(huge, { x: 8, y: 8 });
});

test("an edge is thicker for more messages and fainter for an older last one", () => {
  const fresh = edgeStyle(1, 1000, 1000);
  const busy = edgeStyle(40, 1000, 1000);
  const old = edgeStyle(1, 1000, 1000 + 3 * 3600);
  assert.ok(busy.width > fresh.width);
  assert.ok(busy.width <= 4);
  assert.ok(old.opacity < fresh.opacity);
  assert.ok(old.opacity >= 0.22);
  near(fresh.opacity, 0.8);
});

test("pair keys do not depend on order, group hues are stable, and the glide ends on its target", () => {
  assert.equal(pairKey("a", "b"), pairKey("b", "a"));
  assert.notEqual(pairKey("a", "bc"), pairKey("ab", "c"));
  assert.equal(hueOfName("reviewers"), hueOfName("reviewers"));
  assert.ok(hueOfName("x") >= 0 && hueOfName("x") < 360);
  let value = 0;
  for (let i = 0; i < 120; i += 1) value = approach(value, 100, 1 / 60);
  assert.equal(value, 100);
  assert.ok(approach(0, 100, 1 / 60) > 0);
});

test("a preview is one line and cut with an ellipsis", () => {
  assert.equal(preview("  a\n\n  b\tc ", 20), "a b c");
  assert.equal(preview("abcdefghij", 5), "abcd…");
});
