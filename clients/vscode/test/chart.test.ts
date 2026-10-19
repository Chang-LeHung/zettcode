import assert from "node:assert/strict";
import test from "node:test";

import { donutSlices, donutSvg } from "../src/core/chart.js";

test("a donut keeps exact percentages and draws a full ring", () => {
  const result = donutSlices([
    { name: "System", value: 10, tone: "green" },
    { name: "User", value: 30, tone: "blue" },
    { name: "Assistant", value: 60, tone: "violet" },
  ]);
  assert.equal(result.total, 100);
  assert.equal(result.expanded, false);
  assert.deepEqual(
    result.slices.map((slice) => slice.percent),
    [10, 30, 60],
  );
  assert.ok(result.slices.reduce((sum, slice) => sum + slice.visualPercent, 0) > 99.9);
  for (const slice of result.slices) {
    const [visible = 0, rest = 0] = slice.dasharray.split(" ").map(Number);
    assert.ok(Number.isFinite(visible) && visible > 0);
    assert.ok(Number.isFinite(rest) && rest >= 0);
    assert.ok(Number.isFinite(Number(slice.dashoffset)));
  }
});

test("a tiny slice is enlarged for the drawing and the exact value stays in the legend", () => {
  const result = donutSlices([
    { name: "System", value: 0.2, tone: "green" },
    { name: "Tool output", value: 0.3, tone: "red" },
    { name: "Assistant", value: 99.5, tone: "violet" },
  ]);
  assert.equal(result.expanded, true);
  assert.equal(result.slices[0]?.percent, 0.2);
  assert.equal(result.slices[1]?.percent, 0.3);
  assert.ok((result.slices[0]?.visualPercent ?? 0) >= 1.4);
  assert.ok(result.slices.reduce((sum, slice) => sum + slice.visualPercent, 0) > 99.9);
});

test("no values is an empty ring, not a division by zero", () => {
  assert.deepEqual(donutSlices([]), { slices: [], total: 0, expanded: false });
  assert.deepEqual(donutSlices([{ name: "zero", value: 0, tone: "muted" }]).slices, []);
});

test("the SVG carries a slice per source and escapes the label", () => {
  const result = donutSlices([
    { name: "<System>", value: 1, tone: "green" },
    { name: "User", value: 1, tone: "blue" },
  ]);
  const svg = donutSvg(result, { label: "Context <composition>" });
  assert.ok(svg.includes('data-slice="0"'));
  assert.ok(svg.includes('data-slice="1"'));
  assert.ok(svg.includes("tone-green"));
  assert.ok(svg.includes("&lt;System&gt;"));
  assert.ok(svg.includes("Context &lt;composition&gt;"));
  assert.ok(svg.includes("donut-track"));
});

test("an unknown tone is drawn muted", () => {
  const result = donutSlices([{ name: "x", value: 1, tone: "not-a-tone" }]);
  assert.ok(donutSvg(result).includes("tone-muted"));
});
