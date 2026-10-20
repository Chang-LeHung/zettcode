import assert from "node:assert/strict";
import test from "node:test";

import { clampScale, drawingSize, fitScale, fitted, MAX_SCALE, MIN_SCALE, percent, zoomAt } from "../src/core/zoom.js";

test("a picture is fitted into the room that is left, and never blown up past its own pixels", () => {
  // 900 × 600 into 760 × 855 with a 32px margin on every side: width decides.
  const scale = fitScale(900, 600, 760, 855);
  assert.ok(Math.abs(scale - (760 - 64) / 900) < 1e-9);
  assert.equal(fitScale(100, 80, 760, 855), 1, "a small picture stays small");
});

test("a drawing may grow, up to the cap, because it stays sharp", () => {
  assert.equal(fitScale(100, 80, 760, 855, 4), 4);
  assert.ok(fitScale(100, 80, 760, 855, 4) <= 4);
});

test("a stage with no size or content with none is neutral, not a division by zero", () => {
  assert.equal(fitScale(0, 10, 100, 100), 1);
  assert.equal(fitScale(10, 10, 0, 100), 1);
});

test("zooming keeps the point under the pointer where it was", () => {
  const start = { scale: 1, x: 0, y: 0 };
  const px = 120;
  const py = -40;
  const next = zoomAt(start, 2, px, py);
  assert.equal(next.scale, 2);
  // The content point that was under (px, py) is (px - x) / scale before, and must be the same after.
  assert.equal((px - next.x) / next.scale, (px - start.x) / start.scale);
  assert.equal((py - next.y) / next.scale, (py - start.y) / start.scale);

  const again = zoomAt(next, 0.5, 10, 10);
  assert.ok(Math.abs((10 - again.x) / again.scale - (10 - next.x) / next.scale) < 1e-9);
});

test("the scale stays inside its limits, and the view does not drift when it is held there", () => {
  assert.equal(clampScale(1000), MAX_SCALE);
  assert.equal(clampScale(0), MIN_SCALE);
  const held = zoomAt({ scale: MAX_SCALE, x: 5, y: 6 }, 2, 50, 50);
  assert.deepEqual(held, { scale: MAX_SCALE, x: 5, y: 6 });
  assert.deepEqual(fitted(2), { scale: 2, x: 0, y: 0 });
});

test("a drawing's size is read from its viewBox, else from its width and height", () => {
  assert.deepEqual(drawingSize('<svg viewBox="0 0 640 480" width="100%">'), { width: 640, height: 480 });
  assert.deepEqual(drawingSize('<svg viewBox="-8 -8 1000.5 200">'), { width: 1000.5, height: 200 });
  assert.deepEqual(drawingSize('<svg width="300" height="150">'), { width: 300, height: 150 });
  assert.equal(drawingSize("<svg>"), null);
});

test("the percentage is the scale as people say it", () => {
  assert.equal(percent(1.25), "125%");
  assert.equal(percent(0.333), "33%");
});
